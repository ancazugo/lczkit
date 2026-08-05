"""Street-network simplification via `neatnet`.

`neatnet` owns its own tuning parameters (node-merge tolerance, continuity-stroke angle
threshold, and a dozen others) as documented package defaults — lczkit does not proxy them
into config; doing so would wrap an entire downstream library's parameter surface for no
current need.
"""

from __future__ import annotations

import geopandas as gpd
import neatnet

from lczkit.cleaning.report import CleaningStep
from lczkit.crs import assert_projected_crs


def simplify_streets(
    streets: gpd.GeoDataFrame, buildings: gpd.GeoDataFrame
) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Simplify `streets` with `neatnet.neatify`, using `buildings` as the exclusion mask.

    Required, not optional, per CLAUDE.md: unsimplified dual carriageways and roundabouts
    destroy enclosure generation downstream (Phase 2).
    """
    assert_projected_crs(streets, "streets")
    assert_projected_crs(buildings, "buildings")
    simplified = neatnet.neatify(streets, exclusion_mask=buildings.geometry)
    step = CleaningStep(
        stage="streets",
        operation="simplify_streets",
        n_in=len(streets),
        n_out=len(simplified),
    )
    return simplified, step
