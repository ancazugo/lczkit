"""Per-unit height provenance: `height_completeness` and the full tier distribution.

These are primary deliverables, not diagnostics. CLAUDE.md's argument is that "90% surveyed
heights" and "90% coarse raster fallback" produce the same LCZ label with very different
trustworthiness, so the output has to carry the whole distribution across tiers rather than a
single completeness number.
"""

from __future__ import annotations

from collections.abc import Sequence

import geopandas as gpd
import numpy as np
import pandas as pd

from lczkit.crs import assert_projected_crs
from lczkit.heights.tiers import OVERTURE_HEIGHT, OVERTURE_NUM_FLOORS

TIER1_SOURCES = (OVERTURE_HEIGHT, OVERTURE_NUM_FLOORS)
"""The `height_source` tags that count towards `height_completeness`.

Both of CLAUDE.md's tier-1 routes, per its literal definition of the tier. The two are reported
as separate fractions as well, so a stricter reading — completeness as surveyed heights only —
stays computable from the same table without this module choosing it for everyone.
"""

FRACTION_PREFIX = "height_frac_"


def height_metrics(
    buildings: gpd.GeoDataFrame,
    units: gpd.GeoDataFrame,
    sources: Sequence[str],
) -> pd.DataFrame:
    """Per-unit height provenance, indexed by `unit_id` to match `units`.

    Returns `height_completeness` — the area fraction of building footprint resolved by tier 1 —
    plus one `height_frac_<source>` column for every tag in `sources`, which is
    `HeightFillReport.height_sources` in a real run. Passing the tag list explicitly is what
    fixes the output schema to the configured cascade rather than to whichever tiers happened to
    fire in a given city; Phases 6 and 7 need that stability.

    Weighting is by the area of each footprint *inside* the unit, so a building straddling two
    grid cells contributes to both in proportion. For `EnclosureUnits` this is equivalent to
    assigning each building to one unit, since Phase 1's cross-layer topology already removes
    buildings that intersect the streets forming enclosure boundaries.

    Units containing no building area are all-null, not zero: "no buildings here" and "0% tier-1
    coverage" are different statements and collapsing them would misreport every park and water
    body as a height-data failure.
    """
    assert_projected_crs(units, "units")
    if units.index.name != "unit_id":
        raise ValueError("units must be indexed by unit_id")
    columns = [f"{FRACTION_PREFIX}{source}" for source in sources]

    if buildings.empty:
        return _all_null(units.index, columns)
    assert_projected_crs(buildings, "buildings")
    if buildings.crs != units.crs:
        raise ValueError(f"buildings.crs ({buildings.crs}) != units.crs ({units.crs})")
    if "height_source" not in buildings.columns:
        raise ValueError(
            "buildings has no height_source column; run lczkit.heights.cascade.fill_heights "
            "before computing per-unit height metrics."
        )

    pieces = gpd.overlay(
        units[["geometry"]].reset_index(),
        buildings[["height_source", "geometry"]].reset_index(drop=True),
        how="intersection",
    )
    if pieces.empty:
        return _all_null(units.index, columns)

    pieces["piece_area"] = pieces.geometry.area
    by_source = (
        pieces.groupby(["unit_id", "height_source"], observed=True)["piece_area"]
        .sum()
        .unstack(fill_value=0)
        .reindex(columns=list(sources), fill_value=0.0)
        .reindex(index=units.index)
    )
    totals = by_source.sum(axis=1)
    fractions = by_source.div(totals.where(totals > 0), axis=0)
    fractions.columns = pd.Index(columns)

    tier1 = [f"{FRACTION_PREFIX}{source}" for source in sources if source in TIER1_SOURCES]
    completeness = fractions[tier1].sum(axis=1) if tier1 else pd.Series(0.0, index=units.index)
    fractions.insert(0, "height_completeness", completeness.where(totals > 0))
    fractions.index.name = "unit_id"
    return fractions


def _all_null(index: pd.Index, columns: Sequence[str]) -> pd.DataFrame:
    frame = pd.DataFrame(
        np.nan, index=index, columns=pd.Index(["height_completeness", *columns]), dtype="float64"
    )
    frame.index.name = "unit_id"
    return frame
