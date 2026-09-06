"""Every `libpysal.graph.Graph` this package's morphometrics build, in one place.

Two modules building "the same" neighbourhood graph independently is how a weighted mean and a
neighbour count end up describing different neighbourhoods without either call site knowing it.
Every graph `lczkit.morphometrics` uses is constructed here and passed down, never rebuilt inline.

**ETC contiguity is fuzzy, not the `Graph.build_contiguity(gdf, rook=False)` queen contiguity
lczkit uses everywhere else** (`lczkit.units.patches`, `lczkit.classify.smoothing`). This is
momepy's own documented requirement, not a new pattern invented here:
`momepy.enclosed_tessellation`'s own docstring warns that its output "does not form a precise
polygonal coverage" and that a contiguity graph over it should use
`Graph.build_fuzzy_contiguity(tessellation, buffer=...)` instead — a plain queen graph misses
edges that fall just short of touching because of the shrink/segment tolerances the tessellation
algorithm applies.
"""

from __future__ import annotations

import geopandas as gpd
from libpysal.graph import Graph

FUZZY_CONTIGUITY_BUFFER_M = 1e-6
"""momepy's own suggested tolerance for `enclosed_tessellation` output, applied here rather than
left as a magic number at the one call site that needs it."""


def building_contiguity(buildings: gpd.GeoDataFrame) -> Graph:
    """Queen contiguity between buildings.

    What `momepy.perimeter_wall` groups joined structures by, and the `contiguity_graph`
    argument `momepy.building_adjacency` compares against.
    """
    return Graph.build_contiguity(buildings, rook=False)


def tessellation_adjacency_by_building(etc: gpd.GeoDataFrame, buildings: gpd.GeoDataFrame) -> Graph:
    """ETC contiguity, relabelled onto the building index — what adjacency means between buildings.

    `momepy.mean_interbuilding_distance` documents its `adjacency_graph` as "a contiguity graph
    derived from tessellation cells linked to buildings", and its own worked example passes a
    Delaunay triangulation. Building-footprint contiguity is not a substitute: footprints in the
    area-preserving layer mostly do not touch, so that graph is nearly edgeless and the metric
    has no adjacent pair to measure a distance between.

    Measured on the Hong Kong fixture, 5 448 buildings:

        building queen contiguity   4 242 edges   2 975 isolates (55%)   metric identically 0.0
        ETC contiguity             23 128 edges      12 isolates         median 10.06 m, max 61.7

    `etc` and `buildings` must be row-aligned, as `buildings_for_etc` returns them: the cells
    carry the adjacency and the buildings carry the index the metric's `geometry` is indexed by.
    """
    if len(etc) != len(buildings):
        raise ValueError(
            f"etc ({len(etc)}) and buildings ({len(buildings)}) must be row-aligned; pass the "
            "frame `buildings_for_etc` returned"
        )
    return Graph.build_fuzzy_contiguity(
        etc.set_axis(buildings.index), buffer=FUZZY_CONTIGUITY_BUFFER_M
    )


def building_distance_band(buildings: gpd.GeoDataFrame, distance_m: float) -> Graph:
    """Binary distance-band graph over building centroids at `distance_m`.

    Binary (unweighted 0/1 edges) because every building-scale metric in this module reads counts
    or unweighted means over the neighbourhood, never a distance-decayed one.
    """
    return Graph.build_distance_band(buildings.geometry.centroid, threshold=distance_m, binary=True)


def building_knn(buildings: gpd.GeoDataFrame, k: int) -> Graph:
    """K-nearest-neighbour graph over building centroids.

    The paper's "10/20/30 nearest neighbours" scale for mean distance to neighbours.

    **`coplanar="clique"`, not libpysal's `"raise"` default.** Two buildings can share a centroid
    exactly — concentric footprints, or a footprint and its own courtyard ring — and `build_knn`
    then refuses outright rather than degrading, taking the whole stage down with it. Measured on
    real Overture data: a 9 km² window over central Nairobi holds 8 014 buildings at 8 013 unique
    centroids, one coplanar pair, and that is enough to raise `CoplanarError`. The failure is
    data-dependent and silent until it fires, so it would surface unpredictably part-way through a
    multi-city extraction rather than up front.

    `"clique"` over `"jitter"` — the other option that avoids the error — because jitter displaces
    the duplicates *randomly*, which would make `mean_dist_neighbors_building_knn*` differ between
    two runs over identical input. This package spends real effort on determinism (sorted Overture
    fetches, sorted tile subsets, pinned thread counts); a random tie-break in a shipped metric
    would undo that for the sake of a tie that `"clique"` resolves deterministically and
    defensibly: two buildings at one point genuinely are each other's nearest neighbour, at
    distance zero.
    """
    return Graph.build_knn(buildings.geometry.centroid, k=k, coplanar="clique")


def etc_contiguity(etc: gpd.GeoDataFrame) -> Graph:
    """Fuzzy queen contiguity between tessellation cells.

    See the module docstring for why fuzzy rather than exact contiguity is required here.
    """
    return Graph.build_fuzzy_contiguity(etc, buffer=FUZZY_CONTIGUITY_BUFFER_M)


def etc_higher_order(base: Graph, steps: int) -> Graph:
    """`base` expanded to every cell reachable within `steps` topological hops.

    `base` itself is included (`lower_order=True`) — "within N topological steps" in the
    paper's own wording, not "exactly N steps away".
    """
    if steps <= 1:
        return base
    return base.higher_order(steps, lower_order=True)


def etc_granularity_graph(base: Graph) -> Graph:
    """`base`'s 1-step neighbourhood with the focal cell included in its own neighbour set.

    `momepy.percentile`/`momepy.weighted_character`/`momepy.neighbors` all read a graph's
    neighbours as *other* cells, so "granularity" — the paper's "sum of ETC area within 1
    topological step" — needs the one graph in this module where a cell counts itself: without
    `assign_self_weight`, `Graph.lag(area)` would sum a cell's neighbours and silently exclude the
    cell's own area from a quantity meant to describe the immediate cluster it sits in.
    """
    return base.assign_self_weight(1)
