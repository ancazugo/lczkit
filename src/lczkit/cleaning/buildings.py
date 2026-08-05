"""Building-footprint cleaning: the six-step pipeline from CLAUDE.md's Phase 1 spec.

Every function is a pure transform — `(buildings) -> (cleaned, CleaningStep)` — with no shared
mutable state, so each is testable in isolation. `clean_buildings()` composes them in the
order CLAUDE.md specifies and is the only function callers outside this module need.
"""

from __future__ import annotations

import geopandas as gpd
import geoplanar

from lczkit.cleaning.report import CleaningStep
from lczkit.crs import assert_projected_crs


def fix_invalid_geometries(buildings: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Repair invalid geometries in place via `make_valid()`. Never changes feature count."""
    assert_projected_crs(buildings, "buildings")
    n_invalid = int((~buildings.geometry.is_valid).sum())
    fixed = buildings.copy()
    fixed["geometry"] = fixed.geometry.make_valid()
    step = CleaningStep(
        stage="buildings",
        operation="fix_invalid_geometries",
        n_in=len(buildings),
        n_out=len(fixed),
        detail={"n_invalid_before": n_invalid},
    )
    return fixed, step


def explode_multipolygons(buildings: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Split multi-part geometries (MultiPolygons, and any GeometryCollections left over from
    `make_valid()`) into single-part rows."""
    assert_projected_crs(buildings, "buildings")
    exploded = buildings.explode(index_parts=False).reset_index(drop=True)
    step = CleaningStep(
        stage="buildings",
        operation="explode_multipolygons",
        n_in=len(buildings),
        n_out=len(exploded),
    )
    return exploded, step


def drop_non_polygons(buildings: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Drop features that are not (non-empty) Polygons — e.g. stray Points or LineStrings left
    over from geometry repair, and any empty geometries."""
    assert_projected_crs(buildings, "buildings")
    keep = (buildings.geometry.geom_type == "Polygon") & (~buildings.geometry.is_empty)
    filtered = buildings.loc[keep].reset_index(drop=True)
    step = CleaningStep(
        stage="buildings",
        operation="drop_non_polygons",
        n_in=len(buildings),
        n_out=len(filtered),
    )
    return filtered, step


def drop_oversized(
    buildings: gpd.GeoDataFrame, max_area_m2: float
) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Drop footprints larger than `max_area_m2` — implausible for a single building."""
    assert_projected_crs(buildings, "buildings")
    filtered = buildings.loc[buildings.geometry.area <= max_area_m2].reset_index(drop=True)
    step = CleaningStep(
        stage="buildings",
        operation="drop_oversized",
        n_in=len(buildings),
        n_out=len(filtered),
        detail={"max_area_m2": max_area_m2},
    )
    return filtered, step


def resolve_overlaps(
    buildings: gpd.GeoDataFrame, merge_limit: float, overlap_limit: float
) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Merge overlapping footprints below `merge_limit`, or above it if the shared overlap
    exceeds `overlap_limit`; trim whatever overlap remains.

    `merge_limit` and `overlap_limit` map directly onto `geoplanar.merge_overlaps`'
    identically-named parameters.
    """
    assert_projected_crs(buildings, "buildings")
    merged = geoplanar.merge_overlaps(buildings, merge_limit, overlap_limit)
    trimmed = geoplanar.trim_overlaps(merged, strategy="largest")
    step = CleaningStep(
        stage="buildings",
        operation="resolve_overlaps",
        n_in=len(buildings),
        n_out=len(trimmed),
        detail={"merge_limit_m2": merge_limit, "overlap_limit": overlap_limit},
    )
    return trimmed, step


def absorb_small_buildings(
    buildings: gpd.GeoDataFrame, min_area_m2: float
) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Absorb footprints smaller than `min_area_m2` into a touching larger neighbour; drop them
    if they touch nothing (`geoplanar.merge_touching`'s documented behaviour for isolates)."""
    assert_projected_crs(buildings, "buildings")
    small_index = buildings.index[buildings.geometry.area < min_area_m2].tolist()
    if not small_index:
        step = CleaningStep(
            stage="buildings",
            operation="absorb_small_buildings",
            n_in=len(buildings),
            n_out=len(buildings),
            detail={"min_area_m2": min_area_m2, "n_small": 0},
        )
        return buildings, step
    merged = geoplanar.merge_touching(buildings, index=small_index, largest=True)
    step = CleaningStep(
        stage="buildings",
        operation="absorb_small_buildings",
        n_in=len(buildings),
        n_out=len(merged),
        detail={"min_area_m2": min_area_m2, "n_small": len(small_index)},
    )
    return merged, step


def clean_buildings(
    buildings: gpd.GeoDataFrame,
    *,
    max_area_m2: float,
    min_area_m2: float,
    merge_limit_m2: float,
    overlap_limit: float,
) -> tuple[gpd.GeoDataFrame, list[CleaningStep]]:
    """Run the full building-cleaning pipeline in CLAUDE.md's stated order."""
    steps: list[CleaningStep] = []

    cleaned, step = fix_invalid_geometries(buildings)
    steps.append(step)
    cleaned, step = explode_multipolygons(cleaned)
    steps.append(step)
    cleaned, step = drop_non_polygons(cleaned)
    steps.append(step)
    cleaned, step = drop_oversized(cleaned, max_area_m2)
    steps.append(step)
    cleaned, step = resolve_overlaps(cleaned, merge_limit_m2, overlap_limit)
    steps.append(step)
    cleaned, step = absorb_small_buildings(cleaned, min_area_m2)
    steps.append(step)

    # allow_gaps=True: buildings are not a plane tessellation — gaps between separate
    # buildings are normal and expected; only overlaps are a real violation here.
    is_planar = bool(geoplanar.is_planar_enforced(cleaned, allow_gaps=True))
    steps.append(
        CleaningStep(
            stage="buildings",
            operation="validate_planarity",
            n_in=len(cleaned),
            n_out=len(cleaned),
            detail={"is_planar_enforced": is_planar},
        )
    )
    return cleaned, steps
