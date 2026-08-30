"""Land-use cleaning — deliberately minimal.

Land use is functional metadata passed through to `industrial_fraction`, not a morphological
layer. It gets no thresholded cleaning of any kind: no size filter, no overlap resolution, no
absorption of small parcels. The one operation applied is geometry repair, so that an area overlay
cannot die on an invalid upstream polygon.

MultiPolygons are kept rather than exploded — a land-use parcel is legitimately multipart, and
area overlays handle multipart geometry without help.
"""

from __future__ import annotations

import geopandas as gpd

from lczkit.cleaning.report import CleaningStep
from lczkit.crs import assert_projected_crs


def clean_land_use(land_use: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Repair invalid land-use geometries via `make_valid()`. Never changes feature count."""
    assert_projected_crs(land_use, "land_use")
    n_invalid = int((~land_use.geometry.is_valid).sum())
    fixed = land_use.copy()
    fixed["geometry"] = fixed.geometry.make_valid()
    step = CleaningStep(
        stage="land_use",
        operation="fix_invalid_geometries",
        n_in=len(land_use),
        n_out=len(fixed),
        detail={"n_invalid_before": n_invalid},
    )
    return fixed, step
