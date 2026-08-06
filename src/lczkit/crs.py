"""CRS enforcement for lczkit's internal computation.

All internal computation happens in a projected CRS obtained via `gdf.estimate_utm_crs()`.
Lat/lon appears only at ingestion and export boundaries — this helper is the single place
that enforces it, rather than relying on a docstring convention.
"""

from __future__ import annotations

import geopandas as gpd
from pyproj import CRS
from shapely.geometry import box

from lczkit.protocols import BBox


def local_utm_crs(bbox: BBox) -> CRS:
    """The single UTM CRS to use for all internal computation over `bbox`.

    Computed from `bbox` itself (in EPSG:4326), not from any individual layer —
    `estimate_utm_crs()` can differ between layers covering nearly the same area (e.g. near a
    UTM zone boundary), which would silently break cross-layer operations if each layer picked
    its own zone. Every stage working over the same bbox should call this once and share the
    result rather than re-deriving it.
    """
    return gpd.GeoSeries([box(*bbox)], crs="EPSG:4326").estimate_utm_crs()


def assert_projected_crs(gdf: gpd.GeoDataFrame, name: str = "gdf") -> None:
    """Raise `ValueError` unless `gdf` has a projected CRS.

    Call this at the entry point of any function that performs internal geometric
    computation (areas, lengths, buffers, distances) — those are meaningless in a
    geographic CRS.
    """
    if gdf.crs is None:
        raise ValueError(f"{name} has no CRS set; expected a projected CRS.")
    if not gdf.crs.is_projected:
        raise ValueError(
            f"{name} has geographic CRS {gdf.crs.to_string()!r}; expected a projected CRS "
            "(e.g. via gdf.estimate_utm_crs())."
        )
