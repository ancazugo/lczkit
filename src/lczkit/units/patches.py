"""`PatchUnits`: street-bounded blocks merged into units at the scale an LCZ patch is drawn at.

**The measurement this exists to answer.** Enclosures are a block, not a patch. On the Hong Kong
fixture `momepy.enclosures` over the cleaned barrier set returns a *median unit of 0.04 ha with
72.9% under 0.1 ha*, against WUDAPT polygons that run 2.2-52 ha across the sixteen study cities and
a So2Sat patch of 10.24 ha. Berlin shows the same from the other direction: 78% of its enclosures
are sub-1000 m2 slivers.

Re-cutting the barrier set does not fix that, which was worth measuring before assuming it:

| barriers (HK fixture) | seeds | median | p90 | max | % < 0.1 ha |
|---|---:|---:|---:|---:|---:|
| all streets | 4095 | 0.04 ha | 0.36 ha | 673 ha | 72.9% |
| drop footway/steps/path | 769 | 0.11 ha | 2.52 ha | 691 ha | 48.6% |
| major + tertiary | 509 | 0.07 ha | 3.85 ha | 692 ha | 56.2% |
| major only | 397 | 0.07 ha | 2.96 ha | 692 ha | 57.9% |

Every barrier set is **bimodal** — slivers plus a handful of very large faces — because a thinner
barrier network does not enlarge the small faces, it only stops subdividing the big ones. The scale
is set by a merge step, not by which streets are barriers.

**So: seeds, then merge.** Stage 1 is `EnclosureUnits` unchanged, over a barrier set with the
pedestrian classes removed — a footpath is not a boundary between two LCZ patches, and it is 50-73%
of the network in Berlin, Hong Kong and Milan. Stage 2 merges each seed into the contiguous
neighbour it most resembles until the units reach `min_area_m2`.

**This does not replace `GridUnits` and is not the default.** The strategy is config, the default
is `grid`, and there is no auto-selection. Grid cells are what every published LCZ map, validation
dataset and WRF workflow uses, and every published figure here is measured on them.

**A caveat that must not be lost.** The merge reads building surface fraction and mean height, and
those are two of the seven dimensions the classifier then scores. Units defined partly by the
quantity being measured is the standard shape of a regionalisation (SKATER, AZP and the rest work
this way), and it is still a form of circularity: a patch is more homogeneous in BSF than a cell
partly because it was *built* to be. It cannot inflate agreement with an external reference, which
is what the validation measures, but it does mean `bsf_by_reference_class` on patch units is a
weaker test than the same table on a grid, so read that table on the grid.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from libpysal.graph import Graph

from lczkit.crs import assert_projected_crs
from lczkit.protocols import BBox
from lczkit.units.enclosures import EnclosureUnits

DEFAULT_MIN_AREA_M2 = 50_000.0
"""5 ha - the median WUDAPT polygon across the sixteen study cities, which is the grain the
reference is actually drawn at. A 100 m cell is 1 ha and a So2Sat patch 10.24 ha, so this sits
between the two objects that are genuinely patch-scale.

**A floor, not a centre**, which is why it is named for what it does. Merging stops when a unit
*reaches* the minimum, and the merge that gets it there overshoots, so the resulting median lands
around twice this value: on the Hong Kong fixture 5 ha gives p10 5.75, median 10.5, p90 24.5 ha.
Set it to roughly half the grain wanted."""

DEFAULT_MAX_AREA_M2 = 500_000.0
"""50 ha. A ceiling, not a target: it stops a merge chain swallowing a whole industrial estate or
a park into one unit, which is the failure mode of merging on size alone."""

PEDESTRIAN_CLASSES: frozenset[str] = frozenset(
    {"footway", "steps", "path", "cycleway", "bridleway"}
)
"""Overture road classes excluded from the barrier set by default.

Not a quality judgement about the data - these are real features, correctly mapped. They are
excluded because an LCZ patch is a neighbourhood of homogeneous cover and a footpath through a
housing estate does not divide one patch from another. They are also the *majority* of the network
where they are mapped at all: 72.7% of Berlin's segments, 72.8% of Hong Kong's, 50.6% of Milan's,
against 3.5-7.5% in cities where pedestrian mapping is sparser. Left in, the seed partition is
mostly an artefact of how thoroughly a city's footpaths have been surveyed.

`pedestrian` itself is **not** here: Overture uses it for plazas and pedestrianised streets, which
are genuine breaks in the urban fabric at the width a street has.
"""

MERGE_COLUMNS: tuple[str, ...] = ("building_surface_fraction", "height_of_roughness_elements_m")
"""The seed-level features the merge compares neighbours on.

Deliberately the two cheap ones. Both come from `buildings_area` alone with a single overlay - no
land cover, no street profile, no second `compute_parameters` - and between them they carry the two
axes LCZ separates built types on: compactness and height band. Adding the land-cover fractions
would double the cost of unit generation to refine a decision the classifier makes afterwards
anyway.
"""


@dataclass(frozen=True)
class PatchReport:
    """What the merge did, for the run manifest.

    A unit strategy whose output depends on a threshold has to say what that threshold produced,
    or two runs at different settings are indistinguishable in the archive.
    """

    n_seeds: int
    n_patches: int
    n_merges: int

    n_isolates: int
    """Seeds adjacent to nothing - an island, or a face fully enclosed by the study boundary. They
    stay as their own patch at whatever size they are, since there is nothing to merge them into."""

    n_below_minimum: int
    """Patches still under `min_area_m2` when the merge stopped. Non-zero exactly where isolates
    or the `max_area_m2` ceiling blocked further merging, so it is the number that says whether the
    target was reachable rather than merely requested."""

    n_blocked_by_max_area: int
    """Merges that took the smallest neighbour rather than the most similar one, because every
    similar neighbour would have breached `max_area_m2`. High values mean the two thresholds are
    fighting each other."""

    n_seeds_split: int
    """Seeds that exceeded `max_area_m2` and were subdivided before merging.

    Zero on a barrier set that produced no oversized face, and zero whenever `max_area_m2` is
    `None`. High values say the barrier network left large unbounded faces — usually water, or a
    periphery Overture does not cover — which is worth seeing rather than inferring from a
    suspiciously round patch count."""

    n_above_maximum: int
    """Patches larger than `max_area_m2` when the merge stopped.

    Non-zero only where a merge could not be avoided: `split_oversized` cuts every oversized seed
    before the merge starts, so what remains here is a unit the merge itself pushed over the line
    because the alternative was leaving a sliver stranded. That trade is deliberate — see
    `n_blocked_by_max_area` — and this is the count that says how often it was taken."""

    area_above_maximum: float
    """Total area in those patches, m². The count alone understates it badly: a handful of units
    can hold most of the extent."""

    min_area_m2: float
    max_area_m2: float

    seed_area_quantiles: dict[str, float] = field(default_factory=dict)
    patch_area_quantiles: dict[str, float] = field(default_factory=dict)
    """p10/p50/p90 in m², before and after. The pair is the point: it says what the merge moved."""


def filter_street_barriers(
    streets: gpd.GeoDataFrame,
    *,
    drop_classes: frozenset[str] = PEDESTRIAN_CLASSES,
    class_column: str = "class",
) -> gpd.GeoDataFrame:
    """`streets` without the classes that are not boundaries between LCZ patches.

    A no-op returning `streets` unchanged when the frame has no class column, which is the honest
    behaviour for a `VectorSource` that does not supply one: silently treating every segment as
    keepable is what the caller would get anyway, and raising would make the class column a hard
    requirement of a protocol that does not promise it.

    Overture's `transportation/segment` carries `class` on 87-99% of rows globally, and
    `OvertureSource` already selects it, so on the shipped source this is free.
    """
    assert_projected_crs(streets, "streets")
    if class_column not in streets.columns or not drop_classes:
        return streets
    keep = ~streets[class_column].isin(drop_classes)
    return gpd.GeoDataFrame(streets.loc[keep])


def seed_features(seeds: gpd.GeoDataFrame, buildings: gpd.GeoDataFrame) -> pd.DataFrame:
    """`MERGE_COLUMNS` per seed, from `buildings` alone.

    Building surface fraction is footprint area overlaid onto the seed, over seed area — the same
    definition `lczkit.ucp.buildings` uses, recomputed here rather than imported because this runs
    *before* units exist and `compute_parameters` takes units as an input.

    Height is the unweighted geometric mean, matching `Hr`, so a seed's value here and its value in
    the parameter table are the same statistic. Null where the seed holds no building with a height,
    and the merge handles that as a missing dimension rather than as a zero — a block of unmeasured
    buildings is not a block of 1 m buildings.

    `buildings` must already carry heights; pass what the cascade returned.
    """
    assert_projected_crs(seeds, "seeds")
    assert_projected_crs(buildings, "buildings")
    frame = pd.DataFrame(
        {column: np.nan for column in MERGE_COLUMNS},
        index=seeds.index,
    )
    if buildings.empty:
        frame["building_surface_fraction"] = 0.0
        return frame

    pieces = gpd.overlay(
        seeds.reset_index()[["unit_id", "geometry"]],
        buildings[["geometry", *(c for c in ("height",) if c in buildings.columns)]],
        how="intersection",
        keep_geom_type=True,
    )
    seed_area = seeds.geometry.area
    if pieces.empty:
        frame["building_surface_fraction"] = 0.0
        return frame

    pieces = pieces.assign(piece_area=pieces.geometry.area)
    covered = pieces.groupby("unit_id")["piece_area"].sum()
    frame["building_surface_fraction"] = (
        covered.reindex(seeds.index).fillna(0.0).div(seed_area.where(seed_area > 0)).clip(upper=1.0)
    )
    if "height" in pieces.columns:
        heights = pd.to_numeric(pieces["height"], errors="coerce")
        usable = pieces.loc[heights.gt(0).fillna(False)].assign(log_h=np.log(heights[heights > 0]))
        if not usable.empty:
            frame["height_of_roughness_elements_m"] = np.exp(
                usable.groupby("unit_id")["log_h"].mean()
            ).reindex(seeds.index)
    return frame


def _standardise(features: pd.DataFrame) -> np.ndarray:
    """`features` as a z-scored array, nulls preserved as NaN.

    Standardised so building surface fraction (0-1) and height in metres (0-300) contribute
    comparably; a raw Euclidean distance over the two would be a distance in metres with a rounding
    error attached. A zero-spread column is left at zero rather than divided by zero — the same
    treatment `classify.distance.normalisation` gives a degenerate dimension.
    """
    values = features.to_numpy(dtype="float64")
    mean = np.zeros(values.shape[1])
    std = np.ones(values.shape[1])
    # A column no seed has a value for is left at mean 0 / std 1 rather than handed to `nanmean`,
    # which returns NaN *and warns*. That is a real state — a city where the cascade resolved no
    # height at all — so it is handled rather than caught, and the NaNs then fall out of `_distance`
    # as a missing dimension, which is what they are.
    present = (~np.isnan(values)).sum(axis=0) > 0
    if present.any():
        mean[present] = np.nanmean(values[:, present], axis=0)
        std[present] = np.nanstd(values[:, present], axis=0)
    return (values - mean) / np.where(std == 0, 1.0, std)


def _distance(a: np.ndarray, b: np.ndarray) -> float:
    """Partial Euclidean distance over the dimensions both rows have.

    The same policy the classifier applies to a null parameter — compare on what is available and
    renormalise, never impute — because the reason a dimension is missing is the same one: a unit
    with no measured building has no height, and giving it the mean would merge it into whatever
    happens to be average.
    """
    known = ~(np.isnan(a) | np.isnan(b))
    if not known.any():
        return 0.0
    difference = a[known] - b[known]
    return float(np.sqrt(np.dot(difference, difference) / known.sum()))


def split_oversized(
    seeds: gpd.GeoDataFrame, max_area_m2: float | None
) -> tuple[gpd.GeoDataFrame, int]:
    """Subdivide any seed larger than `max_area_m2`, returning the seeds and how many were split.

    **`max_area_m2` was a merge guard and not a ceiling, and this is what makes the name true.**
    It refused to *combine* two seeds into something oversized and had no way to divide a seed that
    already exceeded it — and enclosure seeds routinely do, because a face bounded by nothing but
    the study edge is as large as the unmapped ground it covers. On a 4 555 km² Istanbul extent 807
    patches exceeded the shipped 50 ha setting and held 72.7% of the total area, the largest being
    1 073 km²; one 98 km² unit contained 1 310 buildings and was given a single LCZ label at a
    uniqueness of 0.12. Benign where the giant faces are sea. Not benign where a city's periphery is
    simply unsurveyed, which is the case in the cities this package exists to reach.

    The cut is a regular grid of side `sqrt(max_area_m2)` anchored on each seed's own bounds, and it
    is deliberately the dullest thing that works. It needs no building layer, so it behaves the same
    on the unmapped hinterland that produces most oversized seeds; it is deterministic, so two runs
    over the same extent agree; and intersecting a polygon with a grid that covers it preserves the
    partition exactly — the pieces union back to the seed, and no ground is gained or lost. Pieces
    that a concave seed leaves disconnected are exploded, so every unit stays a single polygon.

    Slivers along the cut lines are expected and are not a problem: `merge_to_patches` runs next and
    absorbs anything under `min_area_m2` into its most similar neighbour, which is the same
    treatment enclosure slivers already get.

    Piece count is bounded by the seed area over `max_area_m2` — that is, by the number of units the
    caller asked for — so this adds no unbounded operation to the stage.
    """
    if max_area_m2 is None:
        return seeds, 0
    oversized = seeds.geometry.area > max_area_m2
    if not bool(oversized.any()):
        return seeds, 0

    side = float(np.sqrt(max_area_m2))
    kept = [seeds.loc[~oversized]]
    for unit_id, geometry in seeds.loc[oversized, "geometry"].items():
        pieces = _grid_pieces(geometry, side)
        kept.append(
            gpd.GeoDataFrame(
                {"unit_id": [f"{unit_id}_s{index:04d}" for index in range(len(pieces))]},
                geometry=gpd.GeoSeries(pieces, crs=seeds.crs),
            ).set_index("unit_id")
        )
    out = pd.concat(kept)
    return gpd.GeoDataFrame(out, geometry="geometry", crs=seeds.crs), int(oversized.sum())


def _grid_pieces(geometry: shapely.Geometry, side: float) -> list[shapely.Geometry]:
    """One polygon cut by a `side`-metre grid anchored on its own bounds, exploded and cleaned."""
    minx, miny, maxx, maxy = shapely.bounds(geometry)
    # Cell *origins*, so the grid covers [min, max) and one more cell always reaches past max. A
    # degenerate bound gives a single origin rather than none — an empty grid would drop the seed.
    columns = np.arange(minx, maxx, side) if maxx > minx else np.array([minx])
    rowsy = np.arange(miny, maxy, side) if maxy > miny else np.array([miny])
    cells = [
        shapely.box(x, y, x + side, y + side) for x in columns.tolist() for y in rowsy.tolist()
    ]
    pieces: list[shapely.Geometry] = []
    for part in shapely.intersection(np.asarray(cells), geometry):
        if part.is_empty:
            continue
        pieces.extend(
            piece
            for piece in shapely.get_parts(shapely.get_parts(part))
            if piece.geom_type in ("Polygon", "MultiPolygon") and piece.area > 0
        )
    # A seed smaller than one cell, or one the grid missed entirely, keeps itself rather than
    # vanishing: losing ground here would break the partition the whole strategy rests on.
    return pieces or [geometry]


def merge_to_patches(
    seeds: gpd.GeoDataFrame,
    features: pd.DataFrame | None = None,
    *,
    min_area_m2: float = DEFAULT_MIN_AREA_M2,
    max_area_m2: float | None = DEFAULT_MAX_AREA_M2,
) -> tuple[gpd.GeoDataFrame, PatchReport]:
    """Merge contiguous `seeds` until each reaches `min_area_m2`, most similar neighbour first.

    Repeatedly takes the **smallest** surviving unit and merges it into the contiguous neighbour
    closest to it in `features`, subject to the combined area not exceeding `max_area_m2`. Where no
    neighbour satisfies that ceiling it takes the smallest neighbour instead, so the loop always
    makes progress and cannot stall on a unit hemmed in by large ones.

    **Deterministic.** Units are processed smallest-area-first with ties broken on `unit_id`,
    candidate neighbours are scanned in sorted order, and equal distances break on `unit_id` too.
    The same seeds in a different row order give the same patches.

    **A partition in, a partition out.** Only contiguous units are ever merged and the result is
    their union, so the covered ground and the absence of overlap are both preserved exactly from
    the seed partition. `EnclosureUnits` supplies that with `clip=True`.

    `features` may be `None`, in which case every neighbour is equally similar and the merge runs on
    size alone. That is a worse unit and it is offered because it needs no building layer.
    """
    assert_projected_crs(seeds, "seeds")
    if seeds.index.name != "unit_id":
        raise ValueError("seeds must be indexed by unit_id")
    if not seeds.index.is_unique:
        raise ValueError("seeds index must be unique")
    if min_area_m2 <= 0:
        raise ValueError(f"min_area_m2 must be positive, got {min_area_m2}")
    if max_area_m2 is not None and max_area_m2 < min_area_m2:
        raise ValueError(
            f"max_area_m2 ({max_area_m2}) must be at least min_area_m2 ({min_area_m2}); "
            "a ceiling below the target would block every merge"
        )

    # Before anything else, and before the seed quantiles are taken, so those describe the seeds
    # the merge actually ran on rather than the faces the barrier set happened to produce.
    seeds, n_split = split_oversized(seeds, max_area_m2)

    seed_area = seeds.geometry.area
    quantiles = {
        q: float(seed_area.quantile(v)) for q, v in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9))
    }
    if seeds.empty:
        return seeds, PatchReport(
            n_seeds=0,
            n_patches=0,
            n_merges=0,
            n_isolates=0,
            n_below_minimum=0,
            n_blocked_by_max_area=0,
            n_seeds_split=n_split,
            n_above_maximum=0,
            area_above_maximum=0.0,
            min_area_m2=min_area_m2,
            max_area_m2=max_area_m2 or float("inf"),
        )

    graph = Graph.build_contiguity(seeds, rook=False)
    neighbours: dict[str, set[str]] = {
        str(focal): {str(other) for other in tuple(others)}
        for focal, others in graph.neighbors.items()
    }
    n_isolates = sum(1 for others in neighbours.values() if not others)

    standardised = (
        _standardise(features.reindex(seeds.index)[list(MERGE_COLUMNS)])
        if features is not None
        else np.zeros((len(seeds), 0))
    )
    position = {str(uid): i for i, uid in enumerate(seeds.index)}
    vectors = {str(uid): standardised[i].copy() for uid, i in position.items()}
    areas = {str(uid): float(value) for uid, value in seed_area.items()}
    members: dict[str, list[str]] = {str(uid): [str(uid)] for uid in seeds.index}

    alive = set(areas)
    queue = [(area, uid) for uid, area in areas.items() if area < min_area_m2]
    heapq.heapify(queue)
    n_merges = 0
    n_blocked = 0

    while queue:
        area, uid = heapq.heappop(queue)
        # Lazy deletion: an entry whose area no longer matches describes a unit that has since
        # grown, and one whose id is gone describes a unit that was absorbed.
        if uid not in alive or areas[uid] != area or area >= min_area_m2:
            continue
        candidates = sorted(neighbours[uid] & alive)
        if not candidates:
            continue

        fits = [
            c for c in candidates if max_area_m2 is None or areas[uid] + areas[c] <= max_area_m2
        ]
        if fits:
            best = min(fits, key=lambda c: (_distance(vectors[uid], vectors[c]), c))
        else:
            # Every neighbour breaches the ceiling. Take the smallest so the loop still advances —
            # refusing would leave a sliver permanently, which is the state this exists to remove —
            # and count it, because a high rate means the two thresholds are fighting each other.
            n_blocked += 1
            best = min(candidates, key=lambda c: (areas[c], c))
        _absorb(uid, best, areas, members, neighbours, vectors, alive)
        n_merges += 1
        if areas[best] < min_area_m2:
            heapq.heappush(queue, (areas[best], best))

    return _assemble(
        seeds,
        members,
        alive,
        quantiles,
        min_area_m2,
        max_area_m2,
        n_merges,
        n_isolates,
        n_blocked,
        n_split,
    )


def _absorb(
    small: str,
    into: str,
    areas: dict[str, float],
    members: dict[str, list[str]],
    neighbours: dict[str, set[str]],
    vectors: dict[str, np.ndarray],
    alive: set[str],
) -> None:
    """Fold `small` into `into`, updating adjacency in O(degree).

    Rather than rebuilding the graph, which is what makes the merge linear in seed count.
    """
    total = areas[small] + areas[into]
    if vectors[into].size:
        # Area-weighted, so a merged unit's feature vector is the vector of the ground it covers
        # rather than the average of two summaries computed over unequal areas.
        combined = (vectors[small] * areas[small] + vectors[into] * areas[into]) / total
        # `nan * 0` is `nan`, so a dimension one side is missing must fall back to the other side's
        # value rather than poisoning the merged vector.
        vectors[into] = np.where(
            np.isnan(vectors[small]),
            vectors[into],
            np.where(np.isnan(vectors[into]), vectors[small], combined),
        )
    areas[into] = total
    members[into].extend(members[small])
    for other in neighbours[small]:
        neighbours[other].discard(small)
        if other != into:
            neighbours[other].add(into)
            neighbours[into].add(other)
    neighbours[into].discard(small)
    alive.discard(small)


def _assemble(
    seeds: gpd.GeoDataFrame,
    members: dict[str, list[str]],
    alive: set[str],
    seed_quantiles: dict[str, float],
    min_area_m2: float,
    max_area_m2: float | None,
    n_merges: int,
    n_isolates: int,
    n_blocked: int,
    n_split: int,
) -> tuple[gpd.GeoDataFrame, PatchReport]:
    """Union each surviving group's geometries and name it after its largest constituent seed."""
    area = seeds.geometry.area
    geometry: list[shapely.Geometry] = []
    unit_ids: list[str] = []
    for key in sorted(alive):
        group = members[key]
        # Named for the largest member, not for whichever seed the merge happened to start from:
        # an id should point at the ground it mostly describes, and the merge order is an
        # implementation detail that a stored run should not depend on.
        anchor = max(group, key=lambda uid: (area[uid], uid))
        unit_ids.append(f"patch_{anchor.removeprefix('enclosure_')}")
        parts = list(seeds.geometry.loc[group])
        geometry.append(parts[0] if len(parts) == 1 else shapely.union_all(parts))

    patches = gpd.GeoDataFrame(
        {"unit_id": unit_ids}, geometry=gpd.GeoSeries(geometry, crs=seeds.crs)
    ).set_index("unit_id")
    patch_area = patches.geometry.area
    return patches, PatchReport(
        n_seeds=int(len(seeds)),
        n_patches=int(len(patches)),
        n_merges=n_merges,
        n_isolates=n_isolates,
        n_below_minimum=int((patch_area < min_area_m2).sum()),
        n_blocked_by_max_area=n_blocked,
        n_seeds_split=n_split,
        n_above_maximum=int((patch_area > (max_area_m2 or float("inf"))).sum()),
        area_above_maximum=float(patch_area[patch_area > (max_area_m2 or float("inf"))].sum()),
        min_area_m2=min_area_m2,
        max_area_m2=max_area_m2 if max_area_m2 is not None else float("inf"),
        seed_area_quantiles=seed_quantiles,
        patch_area_quantiles={
            "p10": float(patch_area.quantile(0.1)),
            "p50": float(patch_area.quantile(0.5)),
            "p90": float(patch_area.quantile(0.9)),
        },
    )


class PatchUnits:
    """Enclosure seeds merged to LCZ-patch scale, satisfying `SpatialUnitStrategy`.

    `buildings` is taken at construction rather than passed to `generate` because the protocol's
    signature is `(bbox, barriers)` and widening it for one strategy would put a building layer in
    the interface every strategy has to accept. Without it the merge runs on size alone, which is
    supported and worse — `MERGE_COLUMNS` is what makes a patch homogeneous rather than merely big.

    The last `PatchReport` is kept on the instance so a caller can put it in the manifest without
    the strategy having to return two things and break the protocol.
    """

    def __init__(
        self,
        *,
        min_area_m2: float = DEFAULT_MIN_AREA_M2,
        max_area_m2: float | None = DEFAULT_MAX_AREA_M2,
        buildings: gpd.GeoDataFrame | None = None,
    ) -> None:
        """Set the area floor the merge works towards, and the building layer it judges by.

        `min_area_m2` is a floor, not a target: merging stops when a unit *reaches* it and the
        merge that got it there overshoots, so 5 ha yields a ~10.5 ha median. `max_area_m2`
        blocks a merge that would overshoot too far. `buildings` is optional and the merge runs
        on size alone without it — supported, and worse.
        """
        self.min_area_m2 = min_area_m2
        self.max_area_m2 = max_area_m2
        self.buildings = buildings
        self.report: PatchReport | None = None

    def generate(self, bbox: BBox, barriers: gpd.GeoDataFrame | None = None) -> gpd.GeoDataFrame:
        """Seed enclosures over `barriers` and merge them to patch scale, indexed by `unit_id`.

        Same contract as the other two strategies — `bbox` lon/lat, geometry-only frame back in
        the projected CRS — and the same requirement as `EnclosureUnits` that `barriers` be
        supplied, since the seeds are enclosures.

        Sets `self.report` as a side effect. The protocol returns one frame, and a caller that
        wants the merge outcome in the manifest reads it off the instance afterwards rather than
        the interface growing a second return value for one strategy.
        """
        seeds = EnclosureUnits().generate(bbox, barriers)
        features = None if self.buildings is None else seed_features(seeds, self.buildings)
        patches, report = merge_to_patches(
            seeds,
            features,
            min_area_m2=self.min_area_m2,
            max_area_m2=self.max_area_m2,
        )
        self.report = report
        return patches
