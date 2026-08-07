"""Building-footprint cleaning, producing **two** layers rather than one.

Every function is a pure transform — `(buildings, ...) -> (cleaned, CleaningStep)` — with no shared
mutable state, so each is testable in isolation. `clean_buildings()` composes them and is the only
function callers outside this module need.

**Why two layers.** The original single-layer pipeline followed Majer & Fleischmann
(arXiv:2603.00132) Supplementary D, where cleaning exists to produce a valid planar partition for
tessellation and lost footprint area costs nothing. lczkit feeds the same layer to building surface
fraction, which carries roughly 47% of the classification metric, so cleaning for topology silently
destroyed the numerator — measured at 23.5% of Berlin's footprint area, worth 9.1 points of
agreement (Phase 6.5, `docs/experiments/phase-6.6-footprint-attrition.md`). The answer is not
weaker cleaning; it is two products with different contracts:

- **`buildings_area`** — shared prefix plus overlap *trimming* only. Feeds building surface
  fraction, `Hr`, building count, mean building area and `industrial_fraction`. Feature-preserving,
  so `building_id` is unique here and every area statistic has a complete population.
- **`buildings_topo`** — planar and non-overlapping, whatever that costs. Feeds the `neatnet`
  exclusion mask and `momepy.street_profile`. Destructive operations permitted.

Both derive from one shared base and carry `building_id` from it, so statistics stay joinable.
"""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import geoplanar
import pandas as pd

from lczkit.cleaning.report import CleaningStep, Stage
from lczkit.crs import assert_projected_crs

BUILDING_ID = "building_id"
"""Stable per-footprint identifier, assigned once on the shared base and carried by both layers.

On `buildings_area` it is unique. On `buildings_topo` a dissolved feature keeps one constituent's
id — arbitrary, and deliberately not relied on: heights reach `buildings_topo` by largest-overlap
inheritance (`lczkit.heights.inherit`), not by this join.
"""


def _area(buildings: gpd.GeoDataFrame) -> float:
    return float(buildings.geometry.area.sum())


def _step(
    operation: str,
    before: gpd.GeoDataFrame,
    after: gpd.GeoDataFrame,
    *,
    stage: Stage = "buildings",
    **detail: object,
) -> CleaningStep:
    """Record one operation's feature counts and footprint area, in and out."""
    return CleaningStep(
        stage=stage,
        operation=operation,
        n_in=len(before),
        n_out=len(after),
        area_in_m2=_area(before),
        area_out_m2=_area(after),
        detail=dict(detail),
    )


def fix_invalid_geometries(buildings: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Repair invalid geometries in place via `make_valid()`. Never changes feature count."""
    assert_projected_crs(buildings, "buildings")
    n_invalid = int((~buildings.geometry.is_valid).sum())
    fixed = buildings.copy()
    fixed["geometry"] = fixed.geometry.make_valid()
    return fixed, _step("fix_invalid_geometries", buildings, fixed, n_invalid_before=n_invalid)


def explode_multipolygons(buildings: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Split multi-part geometries (MultiPolygons, and any GeometryCollections left over from
    `make_valid()`) into single-part rows."""
    assert_projected_crs(buildings, "buildings")
    exploded = buildings.explode(index_parts=False).reset_index(drop=True)
    return exploded, _step("explode_multipolygons", buildings, exploded)


def drop_non_polygons(buildings: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Drop features that are not (non-empty) Polygons — e.g. stray Points or LineStrings left
    over from geometry repair, and any empty geometries."""
    assert_projected_crs(buildings, "buildings")
    keep = (buildings.geometry.geom_type == "Polygon") & (~buildings.geometry.is_empty)
    filtered = buildings.loc[keep].reset_index(drop=True)
    return filtered, _step("drop_non_polygons", buildings, filtered)


def drop_oversized(
    buildings: gpd.GeoDataFrame, max_area_m2: float
) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Drop footprints larger than `max_area_m2` — implausible for a single building."""
    assert_projected_crs(buildings, "buildings")
    filtered = buildings.loc[buildings.geometry.area <= max_area_m2].reset_index(drop=True)
    return filtered, _step("drop_oversized", buildings, filtered, max_area_m2=max_area_m2)


def assign_building_id(buildings: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Stamp `BUILDING_ID` onto the shared base, before the two layers diverge.

    Assigned here rather than at ingestion because the shared prefix explodes multipolygons: an id
    taken from the source would be shared by every part of a multi-part footprint and would not
    identify a row. Positional, and stable for a given input and configuration.
    """
    assert_projected_crs(buildings, "buildings")
    stamped = buildings.copy()
    stamped[BUILDING_ID] = [f"bld_{i}" for i in range(len(stamped))]
    return stamped, _step("assign_building_id", buildings, stamped)


def trim_overlaps(buildings: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Remove the shared part of every pair of overlapping footprints, keeping both features.

    This is the *only* overlap operation `buildings_area` gets, and it is there for correctness
    rather than topology: `lczkit.ucp.buildings` sums overlay pieces per unit, so two footprints
    overlapping by 50 m² contribute that area twice and building surface fraction can exceed 1.0.
    Trimming removes exactly the double count. Merging, which would also dissolve the pair into one
    feature and corrupt `building_count` and `mean_building_area_m2`, is topology work and stays on
    `buildings_topo`.
    """
    assert_projected_crs(buildings, "buildings")
    trimmed = geoplanar.trim_overlaps(buildings, strategy="largest")
    return trimmed, _step("trim_overlaps", buildings, trimmed, stage="buildings_area")


def resolve_overlaps(
    buildings: gpd.GeoDataFrame, merge_limit: float, overlap_limit: float
) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Merge overlapping footprints below `merge_limit`, or above it if the shared overlap
    exceeds `overlap_limit`; trim whatever overlap remains. `buildings_topo` only.

    `merge_limit` and `overlap_limit` map directly onto `geoplanar.merge_overlaps`'
    identically-named parameters.
    """
    assert_projected_crs(buildings, "buildings")
    merged = geoplanar.merge_overlaps(buildings, merge_limit, overlap_limit)
    trimmed = geoplanar.trim_overlaps(merged, strategy="largest")
    return trimmed, _step(
        "resolve_overlaps",
        buildings,
        trimmed,
        stage="buildings_topo",
        merge_limit_m2=merge_limit,
        overlap_limit=overlap_limit,
    )


def absorb_small_buildings(
    buildings: gpd.GeoDataFrame, min_area_m2: float
) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Dissolve footprints smaller than `min_area_m2` into a touching larger neighbour, **keeping
    those that touch nothing**. `buildings_topo` only.

    `geoplanar.merge_touching` deletes any polygon in `index` that shares no boundary segment with
    a neighbour, and offers no way to turn that off. Deletion is wrong here: a free-standing garage
    is small, not spurious, and CLAUDE.md's rule is that this operation dissolves rather than
    deletes. So the small set is partitioned on the same predicate `merge_touching` uses internally,
    only the touching part is passed to it, and the isolates are concatenated back untouched.

    Measured on the Berlin fixture: 1186 footprints under 20 m², of which 1043 are isolated. The
    deletion was worth 0.12% of footprint area — a real bug, and not the one that mattered.
    """
    assert_projected_crs(buildings, "buildings")
    small = buildings.index[buildings.geometry.area < min_area_m2]
    if small.empty:
        return buildings, _step(
            "absorb_small_buildings",
            buildings,
            buildings,
            stage="buildings_topo",
            min_area_m2=min_area_m2,
            n_small=0,
            n_dissolved=0,
            n_isolated_retained=0,
        )

    # `source` indexes positionally into the query geometries, i.e. into `small`. This is the same
    # predicate `merge_touching` applies internally, so the partition matches exactly what it would
    # have dissolved and what it would have deleted.
    source, _ = buildings.boundary.sindex.query(buildings.loc[small].boundary, predicate="overlaps")
    touching = small[sorted(set(source.tolist()))]
    isolated = small.difference(touching)

    if touching.empty:
        merged = buildings
    else:
        merged = geoplanar.merge_touching(
            buildings.drop(index=isolated), index=touching.tolist(), largest=True
        )
        if not isolated.empty:
            merged = gpd.GeoDataFrame(
                pd.concat([merged, buildings.loc[isolated]], ignore_index=True),
                geometry="geometry",
                crs=buildings.crs,
            )

    return merged, _step(
        "absorb_small_buildings",
        buildings,
        merged,
        stage="buildings_topo",
        min_area_m2=min_area_m2,
        n_small=len(small),
        n_dissolved=len(touching),
        n_isolated_retained=len(isolated),
    )


@dataclass(frozen=True)
class BuildingLayers:
    """The two layers `clean_buildings()` forks into, before cross-layer topology runs on `topo`."""

    area: gpd.GeoDataFrame
    """Area-preserving. Every area statistic reads this."""

    topo: gpd.GeoDataFrame
    """Planar and non-overlapping. Topology and the street profile read this."""


def clean_buildings(
    buildings: gpd.GeoDataFrame,
    *,
    max_area_m2: float,
    min_area_m2: float,
    merge_limit_m2: float,
    overlap_limit: float,
) -> tuple[BuildingLayers, list[CleaningStep]]:
    """Run the shared prefix, then fork into the area-preserving and topological layers.

    `buildings_topo` returns without cross-layer topology applied — the road-buffer rule needs the
    *simplified* street network, which `pipeline.clean_vectors()` produces after this point.
    """
    steps: list[CleaningStep] = []
    base = buildings
    for operation in (
        fix_invalid_geometries,
        explode_multipolygons,
        drop_non_polygons,
    ):
        base, step = operation(base)
        steps.append(step)
    base, step = drop_oversized(base, max_area_m2)
    steps.append(step)
    base, step = assign_building_id(base)
    steps.append(step)

    area, step = trim_overlaps(base)
    steps.append(step)

    topo, step = resolve_overlaps(base, merge_limit_m2, overlap_limit)
    steps.append(step)
    topo, step = absorb_small_buildings(topo, min_area_m2)
    steps.append(step)

    # allow_gaps=True: buildings are not a plane tessellation — gaps between separate
    # buildings are normal and expected; only overlaps are a real violation here.
    planar = bool(geoplanar.is_planar_enforced(topo, allow_gaps=True))
    steps.append(
        CleaningStep(
            stage="buildings_topo",
            operation="validate_planarity",
            n_in=len(topo),
            n_out=len(topo),
            area_in_m2=_area(topo),
            area_out_m2=_area(topo),
            detail={"is_planar_enforced": planar},
        )
    )
    return BuildingLayers(area=area, topo=topo), steps
