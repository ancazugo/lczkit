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
    # No filter. Water needs a level/subtype filter; land use does not, and this module does not
    # invent one.
    where="TRUE",
)


def _canonical_order(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Rows in GERS `id` order, so the same query is the same frame every time.

    **This is the pipeline's reproducibility boundary.** `_fetch` runs a DuckDB scan across many
    remote parquet files with no `ORDER BY`, so its row order is whatever the parallel readers
    finished in — nondeterministic between runs, and different again from the order a cached
    file replays. That would be harmless if nothing downstream cared, but `neatnet` re-nodes and
    re-merges a network by the order it receives it: on the test grid, a shuffled input yields
    the same feature count and the same total length with the edges split at different points,
    which reaches `momepy.street_profile` and so `aspect_ratio`.

    Sorting here rather than in SQL is deliberate. It costs one sort instead of a distributed
    one, and — the reason that matters — it applies to the cache-hit path too, so the files
    already written under `input/Overture_Maps/` yield the canonical order without being
    rewritten. Nothing under `input/` is shared with other projects and then modified.

    `id` is Overture's GERS identifier: present in every layer this module selects, unique per
    feature, and stable across releases for a feature that persists.
    """
    if "id" not in gdf.columns:
        raise ValueError(f"expected an `id` column to order on; got {list(gdf.columns)}")
    return gdf.sort_values("id", kind="stable").reset_index(drop=True)


def _silence_progress_bar(con: duckdb.DuckDBPyConnection) -> None:
    """Turn DuckDB's query progress bar off, without letting that decide whether ingestion runs.

    `SET enable_progress_bar = false` looks like the obvious way and **cannot be used here**:
    inside a Jupyter kernel DuckDB reinitialises its display when the setting is assigned, and
    raises `InvalidInputException: required package 'ipywidgets' is missing` — for an assignment
    whose whole purpose is to not draw anything. Measured on duckdb 1.5.5: assigning it fails,
    assigning `enable_progress_bar_print` first fails, and passing it in `duckdb.connect(config=)`
    fails differently ("cannot be set as a global option"). The `PRAGMA` form does not touch the
    display and succeeds.

    The `except` is not defensive habit. A cosmetic setting took `OvertureSource.__init__` — and
    with it every code path that reads Overture — out of an entire execution environment, and the
    correct behaviour when a progress bar cannot be switched off is to carry on without one.
    """
    try:
        con.execute("PRAGMA disable_progress_bar;")
    except duckdb.Error:  # pragma: no cover - depends on the host's display environment
        pass


class OvertureSource:
    """Reads the five Overture layers this package ingests, from a pinned release.

    `buildings`, `streets`, `rail`, `water` and `land_use`.
    """

    def __init__(self, settings: Settings) -> None:
        """Pin the release, bind the cache directory, and open a DuckDB spatial connection.

        Refuses a `release` of `None` rather than falling back to "latest": every manifest
        records the release string, and a run against a moving target is not reproducible. The
        connection is in-memory — nothing is written outside `input/<source_dir_name>/`.
        """
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
        self._con.execute(f"SET s3_region = '{_S3_REGION}';")
        _silence_progress_bar(self._con)

    def buildings(self, bbox: BBox) -> gpd.GeoDataFrame:
        """Building footprints intersecting `bbox`.

        Columns: `id`, `height`, `num_floors`, `subtype`, `class`, `sources`.

        `height` and `num_floors` are nullable and frequently null — that is expected, not an
        error. Overture's conflation is winner-takes-all at the geometry level, and `height` is
        parsed only from OSM tags, so footprints won by a machine-learning source carry no
        height at all. The height cascade owns that problem; nothing in ingestion or cleaning may
        treat a null height as a failure.

        `subtype`/`class` carry usage type (residential / commercial / industrial) and `sources`
        carries per-feature dataset provenance. Both are retained through cleaning — `class` is
        the only route to LCZ 10, and `sources` drives the source-availability diagnostic.
        """
        return self._read_theme(_BUILDINGS, bbox)

    def streets(self, bbox: BBox) -> gpd.GeoDataFrame:
        """Road segments intersecting `bbox`.

        `subtype = 'road'`, excluding `class = 'service'`.
        """
        return self._read_theme(_STREETS, bbox)

    def rail(self, bbox: BBox) -> gpd.GeoDataFrame:
        """Rail segments intersecting `bbox`: `subtype = 'rail'`, no `class` filter.

        Rail is a barrier type for `EnclosureUnits`, and unlike streets' `class != 'service'` it
        takes no sub-filtering.
        """
        return self._read_theme(_RAIL, bbox)

    def water(self, bbox: BBox) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
        """`(waterlines, waterbodies)` intersecting `bbox`.

        Excludes underground/aboveground features (Overture's `level` field, nonzero) and
        subtypes `human_made`, `reservoir`, `spring`, `wastewater`. Note that Overture's own
        `WaterSubtype` value is `human_made`, with an underscore rather than a hyphen.
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
        area, which is `industrial_fraction` and which the LCZ 8/10 rule reads.
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
            return _canonical_order(gdf)
        gdf = self._fetch(query, bbox)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_parquet(cache_path)
        return _canonical_order(gdf)

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
