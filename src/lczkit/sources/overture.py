"""`VectorSource` backed by DuckDB spatial+httpfs reads of Overture's S3 GeoParquet.

Cached locally, keyed on `(release, bbox, layer, query)`, under
`settings.source_dir(settings.overture.source_dir_name)`. A cache hit never touches DuckDB or
the network — the file being present on disk *is* the cache.

The `query` component of that key matters: a cached file's contents depend on which columns
were selected and which rows were filtered, not just on which layer was asked for. Keying on
the layer alone would let a change to a layer's column set silently return a stale frame that
is missing columns the caller now requires.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import NamedTuple

import duckdb
import geopandas as gpd

from lczkit.config import Settings
from lczkit.protocols import BBox

_S3_REGION = "us-west-2"
_S3_URL = "s3://overturemaps-us-west-2/release/{release}/theme={theme}/type={type_}/*"

_WATER_EXCLUDED_SUBTYPES = ("human_made", "reservoir", "spring", "wastewater")


def bbox_key(bbox: BBox) -> str:
    """A stable, filesystem-safe, human-inspectable cache key for a bbox.

    Six decimal places (~11cm) — a fixed-precision string, not a hash, so a cache directory
    shared with other projects stays browsable.
    """
    minx, miny, maxx, maxy = bbox
    return f"{minx:.6f}_{miny:.6f}_{maxx:.6f}_{maxy:.6f}"


class _LayerQuery(NamedTuple):
    """One layer's S3 partition and the query run against it.

    `layer` names the cache file; `theme`/`type_` select the Overture S3 partition. They
    diverge for `streets`/`rail`, which both read `transportation/segment` — keying the cache
    on `(theme, type_)` alone would let the two silently overwrite each other's cached file.
    """

    layer: str
    theme: str
    type_: str
    columns: str
    where: str

    @property
    def key(self) -> str:
        """Short hash of `(columns, where)`, forming part of the cache filename.

        Changing either invalidates the cached file, and does so by writing to a *new* path
        rather than overwriting the old one — files under `input/` are shared with other
        projects and are never modified in place.
        """
        return hashlib.sha256(f"{self.columns}||{self.where}".encode()).hexdigest()[:8]


_BUILDINGS = _LayerQuery(
    layer="buildings",
    theme="buildings",
    type_="building",
    columns="id, height, num_floors, subtype, class, sources",
    where="TRUE",
)

_STREETS = _LayerQuery(
    layer="streets",
    theme="transportation",
    type_="segment",
    columns="id, subtype, class",
    where="subtype = 'road' AND class IS DISTINCT FROM 'service'",
)

_RAIL = _LayerQuery(
    layer="rail",
    theme="transportation",
    type_="segment",
    columns="id, subtype, class",
    where="subtype = 'rail'",
)

_WATER_EXCLUDED_SQL = ", ".join(f"'{subtype}'" for subtype in _WATER_EXCLUDED_SUBTYPES)

_WATER = _LayerQuery(
    layer="water",
    theme="base",
    type_="water",
    columns="id, subtype, level",
    where=(
        "(level IS NULL OR level = 0) AND "
        f"(subtype IS NULL OR subtype NOT IN ({_WATER_EXCLUDED_SQL}))"
    ),
)

_LAND_USE = _LayerQuery(
    layer="land_use",
    theme="base",
    type_="land_use",
    columns="id, subtype, class",
    # No filter. CLAUDE.md prescribes a level/subtype filter for water and describes none for
    # land use, and this module does not invent one.
    where="TRUE",
)


class OvertureSource:
    """Reads `buildings`, `streets`, `rail`, `water` and `land_use` layers from a pinned
    Overture release."""

    def __init__(self, settings: Settings) -> None:
        release = settings.overture.release
        if release is None:
            raise ValueError(
                "settings.overture.release is not set; refusing to query Overture against "
                '"latest". Pin an explicit release string, e.g. "2026-07-22.0".'
            )
        self._release = release
        self._cache_dir = settings.source_dir(settings.overture.source_dir_name)
        self._con = duckdb.connect(":memory:")
        self._con.execute("INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;")
        self._con.execute(f"SET s3_region = '{_S3_REGION}'; SET enable_progress_bar = false;")

    def buildings(self, bbox: BBox) -> gpd.GeoDataFrame:
        """Building footprints intersecting `bbox`. Columns: `id`, `height`, `num_floors`,
        `subtype`, `class`, `sources`.

        `height` and `num_floors` are nullable and frequently null — that is expected, not an
        error. Overture's conflation is winner-takes-all at the geometry level, and `height` is
        parsed only from OSM tags, so footprints won by a machine-learning source carry no
        height at all. The height cascade (Phase 3) owns that problem; nothing in ingestion or
        cleaning may treat a null height as a failure.

        `subtype`/`class` carry usage type (residential / commercial / industrial) and `sources`
        carries per-feature dataset provenance. Both are retained through cleaning — `class` is
        the only route to LCZ 10, and `sources` drives Phase 3's source-availability diagnostic.
        """
        return self._read_theme(_BUILDINGS, bbox)

    def streets(self, bbox: BBox) -> gpd.GeoDataFrame:
        """Road segments intersecting `bbox`: `subtype = 'road'`, excluding `class =
        'service'`."""
        return self._read_theme(_STREETS, bbox)

    def rail(self, bbox: BBox) -> gpd.GeoDataFrame:
        """Rail segments intersecting `bbox`: `subtype = 'rail'`, no `class` filter — CLAUDE.md
        names rail as a barrier type for Phase 2's `EnclosureUnits` but does not describe any
        sub-filtering of it, unlike streets' `class != 'service'`."""
        return self._read_theme(_RAIL, bbox)

    def water(self, bbox: BBox) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
        """`(waterlines, waterbodies)` intersecting `bbox`.

        Excludes underground/aboveground features (Overture's `level` field, nonzero) and
        subtypes `human_made`, `reservoir`, `spring`, `wastewater`. Note: Overture's own
        `WaterSubtype` value is `human_made` (underscore), not the hyphenated spelling in
        CLAUDE.md's prose.
        """
        gdf = self._read_theme(_WATER, bbox)
        waterlines = gdf.loc[
            gdf.geometry.geom_type.isin(["LineString", "MultiLineString"])
        ].reset_index(drop=True)
        waterbodies = gdf.loc[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].reset_index(
            drop=True
        )
        return waterlines, waterbodies

    def land_use(self, bbox: BBox) -> gpd.GeoDataFrame:
        """Land-use polygons intersecting `bbox`. Columns: `id`, `subtype`, `class`.

        Functional semantics only — this layer exists to supply the industrial share of a unit's
        area (Phase 5's `industrial_fraction`, consumed by Phase 6's LCZ 8/10 disambiguation).
        It is **not** a barrier for spatial-unit generation and **not** a land-cover source;
        rasters own land cover.

        Non-polygon features are dropped here rather than in SQL, so the cached file stays the
        raw query result — the same split `water()` performs.
        """
        gdf = self._read_theme(_LAND_USE, bbox)
        return gdf.loc[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].reset_index(
            drop=True
        )

    def _cache_path(self, layer: str, bbox: BBox, query_key: str) -> Path:
        return self._cache_dir / self._release / bbox_key(bbox) / f"{layer}_{query_key}.parquet"

    def _read_theme(self, query: _LayerQuery, bbox: BBox) -> gpd.GeoDataFrame:
        cache_path = self._cache_path(query.layer, bbox, query.key)
        if cache_path.exists():
            gdf = gpd.read_parquet(cache_path)
            if not isinstance(gdf, gpd.GeoDataFrame):
                raise TypeError(f"cached file is not a GeoDataFrame: {cache_path}")
            return gdf
        gdf = self._fetch(query, bbox)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_parquet(cache_path)
        return gdf

    def _fetch(self, query: _LayerQuery, bbox: BBox) -> gpd.GeoDataFrame:
        minx, miny, maxx, maxy = bbox
        url = _S3_URL.format(release=self._release, theme=query.theme, type_=query.type_)
        sql = f"""
            SELECT {query.columns}, ST_AsWKB(geometry) AS geometry_wkb
            FROM read_parquet(?, filename = true, hive_partitioning = 1)
            WHERE bbox.xmin <= ? AND bbox.xmax >= ?
              AND bbox.ymin <= ? AND bbox.ymax >= ?
              AND ({query.where})
        """
        df = self._con.execute(sql, [url, maxx, minx, maxy, miny]).fetchdf()
        wkb = df["geometry_wkb"].map(bytes)  # duckdb returns bytearray, shapely needs bytes
        geometry = gpd.GeoSeries.from_wkb(wkb, crs="EPSG:4326")
        return gpd.GeoDataFrame(df.drop(columns="geometry_wkb"), geometry=geometry, crs="EPSG:4326")
