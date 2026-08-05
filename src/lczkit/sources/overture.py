"""`VectorSource` backed by DuckDB spatial+httpfs reads of Overture's S3 GeoParquet.

Cached locally, keyed on `(release, bbox, theme)`, under
`settings.source_dir(settings.overture.source_dir_name)`. A cache hit never touches DuckDB or
the network — the file being present on disk *is* the cache.
"""

from __future__ import annotations

from pathlib import Path

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


class OvertureSource:
    """Reads `buildings`, `streets`, and `water` layers from a pinned Overture release."""

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
        `sources`."""
        return self._read_theme(
            theme="buildings",
            type_="building",
            bbox=bbox,
            columns="id, height, num_floors, sources",
            where="TRUE",
        )

    def streets(self, bbox: BBox) -> gpd.GeoDataFrame:
        """Road segments intersecting `bbox`: `subtype = 'road'`, excluding `class =
        'service'`."""
        return self._read_theme(
            theme="transportation",
            type_="segment",
            bbox=bbox,
            columns="id, subtype, class",
            where="subtype = 'road' AND class IS DISTINCT FROM 'service'",
        )

    def water(self, bbox: BBox) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
        """`(waterlines, waterbodies)` intersecting `bbox`.

        Excludes underground/aboveground features (Overture's `level` field, nonzero) and
        subtypes `human_made`, `reservoir`, `spring`, `wastewater`. Note: Overture's own
        `WaterSubtype` value is `human_made` (underscore), not the hyphenated spelling in
        CLAUDE.md's prose.
        """
        excluded = ", ".join(f"'{subtype}'" for subtype in _WATER_EXCLUDED_SUBTYPES)
        gdf = self._read_theme(
            theme="base",
            type_="water",
            bbox=bbox,
            columns="id, subtype, level",
            where=(
                f"(level IS NULL OR level = 0) AND (subtype IS NULL OR subtype NOT IN ({excluded}))"
            ),
        )
        waterlines = gdf.loc[
            gdf.geometry.geom_type.isin(["LineString", "MultiLineString"])
        ].reset_index(drop=True)
        waterbodies = gdf.loc[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].reset_index(
            drop=True
        )
        return waterlines, waterbodies

    def _cache_path(self, theme: str, type_: str, bbox: BBox) -> Path:
        return self._cache_dir / self._release / bbox_key(bbox) / f"{theme}_{type_}.parquet"

    def _read_theme(
        self, *, theme: str, type_: str, bbox: BBox, columns: str, where: str
    ) -> gpd.GeoDataFrame:
        cache_path = self._cache_path(theme, type_, bbox)
        if cache_path.exists():
            gdf = gpd.read_parquet(cache_path)
            if not isinstance(gdf, gpd.GeoDataFrame):
                raise TypeError(f"cached file is not a GeoDataFrame: {cache_path}")
            return gdf
        gdf = self._fetch(theme=theme, type_=type_, bbox=bbox, columns=columns, where=where)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_parquet(cache_path)
        return gdf

    def _fetch(
        self, *, theme: str, type_: str, bbox: BBox, columns: str, where: str
    ) -> gpd.GeoDataFrame:
        minx, miny, maxx, maxy = bbox
        url = _S3_URL.format(release=self._release, theme=theme, type_=type_)
        query = f"""
            SELECT {columns}, ST_AsWKB(geometry) AS geometry_wkb
            FROM read_parquet(?, filename = true, hive_partitioning = 1)
            WHERE bbox.xmin <= ? AND bbox.xmax >= ?
              AND bbox.ymin <= ? AND bbox.ymax >= ?
              AND ({where})
        """
        df = self._con.execute(query, [url, maxx, minx, maxy, miny]).fetchdf()
        wkb = df["geometry_wkb"].map(bytes)  # duckdb returns bytearray, shapely needs bytes
        geometry = gpd.GeoSeries.from_wkb(wkb, crs="EPSG:4326")
        return gpd.GeoDataFrame(df.drop(columns="geometry_wkb"), geometry=geometry, crs="EPSG:4326")
