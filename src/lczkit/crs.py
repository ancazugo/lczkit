"""CRS enforcement for lczkit's internal computation.

All internal computation happens in a projected CRS obtained via `gdf.estimate_utm_crs()`.
Lat/lon appears only at ingestion and export boundaries — this helper is the single place
that enforces it, rather than relying on a docstring convention.
"""

from __future__ import annotations

import geopandas as gpd


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
