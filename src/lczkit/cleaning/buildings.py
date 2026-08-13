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
import numpy as np
import pandas as pd
import shapely
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components

from lczkit.cleaning.geometry import largest_part
from lczkit.cleaning.report import CleaningStep, FootprintCoverage, Stage
from lczkit.crs import assert_projected_crs

BUILDING_ID = "building_id"
"""Stable per-footprint identifier, assigned once on the shared base and carried by both layers.

On `buildings_area` it is unique. On `buildings_topo` a dissolved feature keeps one constituent's
id — arbitrary, and deliberately not relied on: heights reach `buildings_topo` by largest-overlap
inheritance (`lczkit.heights.inherit`), not by this join.
"""


def _area(buildings: gpd.GeoDataFrame) -> float:
    return float(buildings.geometry.area.sum())


def union_area(buildings: gpd.GeoDataFrame) -> float:
    """Ground actually covered by `buildings`, counting overlapping footprints once.

    The denominator Phase 1's retention criterion is stated against, and the quantity building
    surface fraction is trying to measure — BSF sums overlay pieces, so a self-overlapping layer
    inflates it. See `FootprintCoverage` for why the sum cannot serve.

    **Component-wise, because the obvious implementation is superlinear.** A single
    `shapely.union_all` over every footprint was measured at five Berlin extents before being
    rejected: exponent 1.26 -> 1.80 in feature count, reaching **711 s for 892k footprints at
    891 km2** — roughly doubling a metropolitan `clean_vectors` run, which is 9.8 minutes in total.
    CLAUDE.md's rule that a whole-extent operation gets its exponent measured at three or more
    extents is what caught it.

    Footprints are very nearly disjoint — Berlin's raw set overlaps itself by 0.19% of summed area
    at metropolitan extent — so almost every footprint is its own component and the global union is
    doing enormous work to discover that. Unioning only within groups that genuinely overlap is
    exact, not an approximation: area is additive over disjoint sets, and two footprints in
    different components share no area by construction.

    Sharing only a boundary is not sharing area, so pairs are filtered on positive intersection
    area rather than on `intersects` alone. Otherwise a terrace row becomes one component and the
    saving goes with it.
    """
    if buildings.empty:
        return 0.0
    assert_projected_crs(buildings, "buildings")
    geometry = np.asarray(buildings.geometry.values)
    areas = shapely.area(geometry)

    candidates = np.asarray(buildings.sindex.query(buildings.geometry, predicate="intersects"))
    left, right = candidates[0], candidates[1]
    keep = left < right
    left, right = left[keep], right[keep]
    if left.size:
        shared = shapely.area(shapely.intersection(geometry[left], geometry[right]))
        overlapping = shared > 0.0
        left, right = left[overlapping], right[overlapping]

    if not left.size:
        return float(areas.sum())

    n = len(geometry)
    graph = csr_matrix(
        (np.ones(left.size, dtype=np.int8), (left, right)),
        shape=(n, n),
    )
    _, labels = connected_components(graph, directed=False)

    order = np.argsort(labels, kind="stable")
    grouped = labels[order]
    boundaries = np.flatnonzero(np.r_[True, grouped[1:] != grouped[:-1], True])

    total = 0.0
    for start, stop in zip(boundaries[:-1], boundaries[1:], strict=True):
        members = order[start:stop]
        if members.size == 1:
            total += float(areas[members[0]])
        else:
            total += float(shapely.union_all(geometry[members]).area)
    return total


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


def _overlapping_pairs(buildings: gpd.GeoDataFrame) -> list[tuple[int, int]]:
    """Every pair of positions whose footprints overlap, unordered and deduplicated.

    The same `overlaps` predicate `geoplanar.is_overlapping` tests with, so a layer this returns
    nothing for is a layer that reports planar.
    """
    found = np.asarray(buildings.sindex.query(buildings.geometry, predicate="overlaps"))
    return sorted({(min(a, b), max(a, b)) for a, b in found.T.tolist() if a != b})


RESIDUAL_OVERLAP_EPS_M = 1e-6
"""Width of the buffer subtracted to separate a residual zero-area overlap, in metres.

One micrometre — six orders of magnitude below any survey precision, and eleven below a footprint.
It is a numerical tolerance for a floating-point artefact, not a decision about buildings, which is
why it lives here rather than in `CleaningConfig`: nothing about a city would make a different
value right. Measured on the Berlin fixture it removes 4.5e-5 m² of 3.13 km², or 1.4e-9 %.
"""

MAX_PLANARITY_PASSES = 8
"""Bound on the fixed-point loop in `enforce_planarity`.

Separating one pair can expose another, so the loop is genuinely iterative — Berlin needs two
passes for three pairs. The bound exists so a pathological layer terminates instead of hanging.
"""

PLANARITY_EPS_ESCALATION = 10.0
MAX_PLANARITY_EPS_M = 1e-3
"""Growth factor per pass, and the ceiling it grows to.

A *fixed* epsilon cannot converge: a pair the buffer fails to separate at one width will fail at
that width however many passes it is given, so the loop spins to its bound and raises. That is
what a 9 km² fixture cannot show and 891 km² of Berlin did — three pairs on the fixture all clear
at one micrometre, and one pair in the metropolitan extent cleared at none of the eight passes.

The ceiling is one millimetre: still three orders of magnitude below survey precision, and six
below a footprint, so escalating this far cannot move a building.
"""


def enforce_planarity(
    buildings: gpd.GeoDataFrame,
    *,
    eps_m: float = RESIDUAL_OVERLAP_EPS_M,
    max_passes: int = MAX_PLANARITY_PASSES,
) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Clear the overlaps `geoplanar.trim_overlaps` cannot. `buildings_topo` only.

    **Why anything is left to clear.** `trim_overlaps` subtracts one footprint of an overlapping
    pair from the other with a plain `difference`. Where the pair's overlap has collapsed to zero
    area — two polygons sharing a boundary that is collinear but carries mismatched vertices — that
    subtraction is a no-op, and the pair stays flagged however many times it is run. Measured on the
    Berlin fixture: three such pairs survive `resolve_overlaps`, relating as `212111212` (a 2-D
    interior intersection) while `intersection()` returns a MultiLineString of area exactly 0.0.
    That single flag is what made `buildings_topo` report `is_planar_enforced: False` for two
    phases, while `momepy.enclosures()` — which needs a planar input — was reading it.

    Neither `shapely.set_precision` nor `shapely.difference(grid_size=...)` fixes them reliably;
    tried across 1e-9 to 1e-2, each resolved at most one of the three and coarser grids introduced
    new overlaps elsewhere. Subtracting a `eps_m`-wide buffer of the smaller polygon from the larger
    does resolve all three, because it forces a genuine re-noding of the shared boundary.

    The larger of each pair is trimmed, matching `trim_overlaps(strategy="largest")`, so which
    feature loses the sliver does not depend on which operation reached it first.
    """
    assert_projected_crs(buildings, "buildings")
    working = buildings.reset_index(drop=True)
    # Edited as a positional array rather than through `.loc`: the spatial index reports positions,
    # and a pass rewrites the same footprint more than once when it overlaps two neighbours.
    geometries = working.geometry.to_numpy().copy()

    passes = 0
    n_pairs = 0
    eps = eps_m
    pairs = _overlapping_pairs(working)
    while pairs and passes < max_passes:
        passes += 1
        n_pairs = max(n_pairs, len(pairs))

        touched: set[int] = set()
        for first, second in pairs:
            larger = first if geometries[first].area >= geometries[second].area else second
            smaller = second if larger == first else first
            geometries[larger] = geometries[larger].difference(geometries[smaller].buffer(eps))
            touched.add(larger)

        positions = sorted(touched)
        geometries[positions] = largest_part(
            gpd.GeoSeries(geometries[positions], crs=working.crs)
        ).to_numpy()
        working = working.set_geometry(
            gpd.GeoSeries(geometries, index=working.index, crs=working.crs)
        )
        pairs = _overlapping_pairs(working)
        # Widen for the next pass: the same width that just failed on a pair will keep failing.
        eps = min(eps * PLANARITY_EPS_ESCALATION, MAX_PLANARITY_EPS_M)

    # Last resort: drop the smaller footprint of whatever still overlaps. `buildings_topo` is the
    # destructive layer and the one that must be planar for `momepy.enclosures()`; `buildings_area`
    # carries every area statistic and is untouched by this. Recorded, never silent — an
    # unexplained gap in the topology layer is exactly what CLAUDE.md's cleaning report exists to
    # make visible, and it is preferable to ending a run over a whole city on one bad pair.
    unresolvable = sorted(
        {
            second if geometries[first].area >= geometries[second].area else first
            for first, second in pairs
        }
    )
    if unresolvable:
        working = working.drop(index=working.index[unresolvable])

    working = working.loc[working.geometry.notna() & ~working.geometry.is_empty].reset_index(
        drop=True
    )
    return working, _step(
        "enforce_planarity",
        buildings,
        working,
        stage="buildings_topo",
        eps_m=eps_m,
        eps_final_m=eps / PLANARITY_EPS_ESCALATION if passes else eps_m,
        n_passes=passes,
        n_residual_pairs=n_pairs,
        n_dropped_unresolvable=len(unresolvable),
        area_removed_m2=_area(buildings) - _area(working),
    )


@dataclass(frozen=True)
class BuildingLayers:
    """The two layers `clean_buildings()` forks into, before cross-layer topology runs on `topo`."""

    area: gpd.GeoDataFrame
    """Area-preserving. Every area statistic reads this."""

    topo: gpd.GeoDataFrame
    """Planar and non-overlapping. Topology and the street profile read this."""

    coverage: FootprintCoverage
    """Union-based footprint accounting for the area layer, against the raw input.

    Carried here rather than returned as a third tuple element so adding it does not change the
    signature every caller unpacks.
    """


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

    # Measured on `base`, i.e. after the validity fixes and before the fork, which is where
    # CLAUDE.md states the criterion ("retains >=99% of the union of input footprint area after
    # validity fixes"). Taking it on the raw input instead would fold make_valid's repairs into
    # the denominator and make the criterion depend on how broken the source geometry was.
    coverage = FootprintCoverage(
        raw_summed_area_m2=_area(base),
        raw_union_area_m2=union_area(base),
        area_summed_m2=_area(area),
        area_union_m2=union_area(area),
    )

    topo, step = resolve_overlaps(base, merge_limit_m2, overlap_limit)
    steps.append(step)
    topo, step = absorb_small_buildings(topo, min_area_m2)
    steps.append(step)

    # Last, not earlier: `absorb_small_buildings` dissolves, and a dissolve can reintroduce the
    # artefact this clears. The invariant has to be established after the last thing that can
    # break it, or `validate_planarity` below is measuring a layer that no longer exists.
    topo, step = enforce_planarity(topo)
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
    return BuildingLayers(area=area, topo=topo, coverage=coverage), steps
