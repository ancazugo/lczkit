"""Cross-layer topology cleanup: drop buildings that intersect streets or waterbodies, and
waterlines that pass through the resulting buildings.

Strictly sequential: the waterbody/waterline checks run against buildings *after* the
streets/waterbody drop, not against an independent snapshot of the raw layer.
"""

from __future__ import annotations

import geopandas as gpd

from lczkit.cleaning.report import CleaningStep, Stage
from lczkit.crs import assert_projected_crs


def _drop_intersecting(
    target: gpd.GeoDataFrame, other: gpd.GeoDataFrame, *, stage: Stage, operation: str
) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    assert_projected_crs(target, "target")
    if target.empty or other.empty:
        kept = target
    else:
        assert_projected_crs(other, "other")
        hits = gpd.sjoin(target, other[["geometry"]], predicate="intersects", how="inner")
        kept = target.loc[~target.index.isin(hits.index)]
    kept = kept.reset_index(drop=True)
    step = CleaningStep(stage=stage, operation=operation, n_in=len(target), n_out=len(kept))
    return kept, step


def drop_buildings_on_streets_or_water(
    buildings: gpd.GeoDataFrame, streets: gpd.GeoDataFrame, waterbodies: gpd.GeoDataFrame
) -> tuple[gpd.GeoDataFrame, list[CleaningStep]]:
    """Drop buildings intersecting `streets`, then drop buildings intersecting `waterbodies`."""
    after_streets, step_streets = _drop_intersecting(
        buildings, streets, stage="topology", operation="drop_buildings_on_streets"
    )
    after_water, step_water = _drop_intersecting(
        after_streets, waterbodies, stage="topology", operation="drop_buildings_on_waterbodies"
    )
    return after_water, [step_streets, step_water]


def drop_waterlines_through_buildings(
    waterlines: gpd.GeoDataFrame, buildings: gpd.GeoDataFrame
) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Drop waterlines that pass through `buildings`."""
    return _drop_intersecting(
        waterlines, buildings, stage="topology", operation="drop_waterlines_through_buildings"
    )


CrossLayerResult = tuple[
    gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame, list[CleaningStep]
]


def apply_cross_layer_topology(
    buildings: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    waterlines: gpd.GeoDataFrame,
    waterbodies: gpd.GeoDataFrame,
) -> CrossLayerResult:
    """Run cross-layer topology cleanup. `streets` and `waterbodies` pass through unchanged —
    only `buildings` and `waterlines` are filtered, per CLAUDE.md's Phase 1 spec."""
    cleaned_buildings, building_steps = drop_buildings_on_streets_or_water(
        buildings, streets, waterbodies
    )
    cleaned_waterlines, waterline_step = drop_waterlines_through_buildings(
        waterlines, cleaned_buildings
    )
    return (
        cleaned_buildings,
        streets,
        cleaned_waterlines,
        waterbodies,
        [*building_steps, waterline_step],
    )
