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


def building_distance_band(buildings: gpd.GeoDataFrame, distance_m: float) -> Graph:
    """Binary distance-band graph over building centroids at `distance_m`.

    Binary (unweighted 0/1 edges) because every building-scale metric in this module reads counts
    or unweighted means over the neighbourhood, never a distance-decayed one.
    """
    return Graph.build_distance_band(buildings.geometry.centroid, threshold=distance_m, binary=True)


def building_knn(buildings: gpd.GeoDataFrame, k: int) -> Graph:
    """K-nearest-neighbour graph over building centroids.

    The paper's "10/20/30 nearest neighbours" scale for mean distance to neighbours.
    """
    return Graph.build_knn(buildings.geometry.centroid, k=k)


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
