"""Street Descriptors & Connectivity morphometrics — Majer & Fleischmann (2026), Supplementary A §3.

Computed per street segment (`street_length`, `street_linearity`, `street_width*`) or per network
node (everything else), then joined onto each ETC (enclosed tessellation cell) via
`momepy.get_nearest_street`/`momepy.get_nearest_node` — the paper's own "linked to nearest street,
node and edge" rule (Supplementary A).

**5 m / 400 m are network-distance radii, not topological hops.** Every connectivity function here
(`mean_node_degree`, `node_density`, `edge_node_ratio`, `cds_length`, `cyclomatic`, `gamma`,
`meshedness`) reads `radius` as a topological hop count *unless* `distance` names an edge
attribute, in which case `radius` is measured along that attribute — confirmed against the
installed momepy. `distance="mm_len"` (the length attribute `momepy.gdf_to_nx` writes by default)
makes `radius=5`/`radius=400` mean 5 m / 400 m of street, matching the only reading of the paper's
own numbers that makes sense (5 or 400 topological hops would be a nonsensical pairing on any
real network).

**Two things about momepy's network functions this module works around, not just uses:**

- `nx.get_node_attributes` keys its result by momepy's own node identity, an `(x, y)` coordinate
  tuple. Handed straight to `pd.Series(...)`, pandas reads a dict of tuple keys as a *MultiIndex*
  rather than as one column of coordinate pairs, which breaks a later `.reindex()` against
  `nodeID`-keyed data with an opaque error. Every extraction here goes through `nodeID` instead,
  via a coordinate-to-`nodeID` map built once from `momepy.nx_to_gdf`'s stable node geometry.
- Several functions have no `name=` parameter and always write the same attribute
  (`node_density` in particular: `node_density`/`node_density_weighted`, fixed). Calling one twice
  at two radii without reading the first result out in between would silently overwrite it — so
  this module processes one radius fully, in a fixed function order, reading every attribute out
  before moving to the next.
"""

from __future__ import annotations

import geopandas as gpd
import momepy
import networkx as nx
import pandas as pd
from networkx import Graph as NxGraph

NODE_RADII_M: tuple[float, ...] = (5.0, 400.0)


def _by_node_id(
    graph: NxGraph, attribute: str, coord_to_id: dict[tuple[float, float], int]
) -> pd.Series:
    """`nx.get_node_attributes(graph, attribute)`, re-keyed from `(x, y)` tuples to `nodeID`."""
    raw = nx.get_node_attributes(graph, attribute)
    return pd.Series({coord_to_id[node]: value for node, value in raw.items()})


def _nearest_join(values: pd.Series, nearest: pd.Series) -> pd.Series:
    """The join every column in this module ends with.

    `values` is indexed by street or node id; `nearest` is indexed by `unit_id` and holds a
    street/node id per ETC.
    """
    return values.reindex(nearest.to_numpy()).set_axis(nearest.index)


def street_metrics(
    etc: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    buildings_for_profile: gpd.GeoDataFrame,
    *,
    profile_distance_m: float,
    profile_tick_length_m: float,
    node_radii_m: tuple[float, ...] = NODE_RADII_M,
) -> pd.DataFrame:
    """The 22 Street Descriptors & Connectivity columns, indexed like `etc` (`unit_id`).

    `streets` is reset to a clean integer index first: `momepy.gdf_to_nx`/`get_nearest_street`
    both key off it, and a stray non-default index from upstream cleaning would silently change
    what "street index 8" means between the two calls. `buildings_for_profile` need not share
    `etc`'s index — `momepy.street_profile` only needs building geometry, not identity — so the
    unfiltered building layer works and there is no reason to pass the ETC-reindexed one.
    """
    streets = streets.reset_index(drop=True)

    street_length = streets.geometry.length
    street_linearity = momepy.linearity(streets)
    profile = momepy.street_profile(
        streets,
        buildings_for_profile,
        distance=profile_distance_m,
        tick_length=profile_tick_length_m,
    )

    graph = momepy.gdf_to_nx(streets, length="mm_len")
    # Node identity and geometry never change after this point — only attributes are added — so
    # this map is built once and reused for every later extraction.
    coord_to_id = {
        (row.geometry.x, row.geometry.y): row.nodeID
        for row in momepy.nx_to_gdf(graph, points=True, lines=False).itertuples()
    }

    graph = momepy.node_degree(graph)
    graph = momepy.mean_node_dist(graph)
    graph = momepy.clustering(graph)
    node_degree = _by_node_id(graph, "degree", coord_to_id)
    mean_node_distance = _by_node_id(graph, "meanlen", coord_to_id)
    node_clustering = _by_node_id(graph, "cluster", coord_to_id)

    per_radius: dict[float, dict[str, pd.Series]] = {}
    for radius in node_radii_m:
        graph = momepy.mean_node_degree(graph, radius=radius, distance="mm_len", name="_mean_nd")
        graph = momepy.node_density(graph, radius=radius, distance="mm_len")
        density = _by_node_id(graph, "node_density", coord_to_id)
        graph = momepy.edge_node_ratio(graph, radius=radius, distance="mm_len", name="_enr")
        graph = momepy.cds_length(graph, radius=radius, distance="mm_len", name="_cds")
        graph = momepy.cyclomatic(graph, radius=radius, distance="mm_len", name="_cyc")
        graph = momepy.gamma(graph, radius=radius, distance="mm_len", name="_gamma")
        graph = momepy.meshedness(graph, radius=radius, distance="mm_len", name="_mesh")
        per_radius[radius] = {
            "mean_node_degree": _by_node_id(graph, "_mean_nd", coord_to_id),
            "node_density": density,
            "edge_node_ratio": _by_node_id(graph, "_enr", coord_to_id),
            "cds_length": _by_node_id(graph, "_cds", coord_to_id),
            "cyclomatic": _by_node_id(graph, "_cyc", coord_to_id),
            "gamma_index": _by_node_id(graph, "_gamma", coord_to_id),
            "meshedness": _by_node_id(graph, "_mesh", coord_to_id),
        }

    nodes, edges = momepy.nx_to_gdf(graph, points=True, lines=True)

    nearest_street = momepy.get_nearest_street(etc, streets)
    nearest_node = momepy.get_nearest_node(etc, nodes, edges, nearest_street)

    columns: dict[str, pd.Series] = {
        "street_length": _nearest_join(street_length, nearest_street),
        "street_linearity": _nearest_join(street_linearity, nearest_street),
        "street_width": _nearest_join(profile["width"], nearest_street),
        "street_width_deviation": _nearest_join(profile["width_deviation"], nearest_street),
        "street_openness": _nearest_join(profile["openness"], nearest_street),
        "node_degree": _nearest_join(node_degree, nearest_node),
        "mean_node_distance": _nearest_join(mean_node_distance, nearest_node),
        "node_clustering": _nearest_join(node_clustering, nearest_node),
    }
    for radius, values in per_radius.items():
        suffix = f"r{int(radius)}m"
        for label, series in values.items():
            columns[f"{label}_{suffix}"] = _nearest_join(series, nearest_node)

    return pd.DataFrame(columns, index=etc.index)
