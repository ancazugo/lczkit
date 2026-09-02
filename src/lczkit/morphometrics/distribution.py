"""Spatial Distribution & Intensity morphometrics — Majer & Fleischmann (2026), Supplementary A §2.

Buildings and ETCs (enclosed tessellation cells) share one index throughout (`unit_id`) — see
`lczkit.units.tessellation.buildings_for_etc`. `Coverage Area Ratio` in particular relies on this
directly: it is a plain division of a building's area by its own ETC's area, with no join.
"""

from __future__ import annotations

import geopandas as gpd
import momepy
import pandas as pd
from libpysal.graph import Graph

from lczkit.morphometrics.graphs import etc_granularity_graph


def distribution_metrics(
    buildings: gpd.GeoDataFrame,
    etc: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    *,
    building_contiguity: Graph,
    building_adjacency_neighborhood: Graph,
    building_w100m: Graph,
    building_w200m: Graph,
    building_distance_bands: dict[str, Graph],
    building_knn: dict[str, Graph],
    etc_higher_order: dict[int, Graph],
) -> pd.DataFrame:
    """The 23 Spatial Distribution & Intensity columns, indexed like `buildings`/`etc` (`unit_id`).

    `building_adjacency_neighborhood` is the 200 m distance-band graph both `building_adjacency`
    and `mean_interbuilding_distance` read as their neighbourhood extent.
    `building_distance_bands` and `building_knn` key on the paper's own labels (`"20m"`, `"100m"`,
    `"200m"`, `"knn10"`, `"knn20"`, `"knn30"`); `etc_higher_order` keys on the step count
    (`1`, `2`, `3`), already expanded via `lczkit.morphometrics.graphs.etc_higher_order`.
    """
    area_etc = etc.geometry.area
    area_building = buildings.geometry.area
    columns: dict[str, pd.Series] = {
        "building_adjacency_200m": momepy.building_adjacency(
            building_contiguity, building_adjacency_neighborhood
        ),
        "mean_interbuilding_distance_200m": momepy.mean_interbuilding_distance(
            buildings, building_contiguity, building_adjacency_neighborhood
        ),
        "shared_walls_building": momepy.shared_walls(buildings),
    }

    street_index = momepy.get_nearest_street(buildings, streets)
    building_orientation = momepy.orientation(buildings)
    street_orientation = momepy.orientation(streets)
    alignment = momepy.street_alignment(building_orientation, street_orientation, street_index)
    columns["street_alignment_building"] = alignment
    columns["street_alignment_building_w100m"] = momepy.weighted_character(
        alignment, area_building, building_w100m
    )
    columns["street_alignment_building_w200m"] = momepy.weighted_character(
        alignment, area_building, building_w200m
    )

    # ETC index is the parent building's, so this is a direct row-aligned division — the numerator
    # and denominator describe the same ground by construction, not a join that could drift.
    # Not clipped at 1.0: `momepy.enclosed_tessellation`'s shrink/segment step does not guarantee
    # a cell fully contains the building that seeded it, and on the Hong Kong fixture 7 of 110
    # ETCs (6.4%) are measurably smaller than their own building — a real property of the
    # tessellation on dense, irregular fabric, reported rather than hidden by a clip.
    coverage_area_ratio = (area_building / area_etc.where(area_etc > 0)).reindex(etc.index)
    columns["coverage_area_ratio_etc"] = coverage_area_ratio
    columns["coverage_area_ratio_etc_w3steps"] = momepy.weighted_character(
        coverage_area_ratio, area_etc, etc_higher_order[3]
    )

    columns["etc_granularity_1step"] = etc_granularity_graph(etc_higher_order[1]).lag(area_etc)

    for label, graph in building_distance_bands.items():
        columns[f"neighbors_building_{label}"] = momepy.neighbors(buildings, graph, weighted=False)
        columns[f"mean_dist_neighbors_building_{label}"] = momepy.neighbor_distance(
            buildings, graph
        )
    for label, graph in building_knn.items():
        columns[f"mean_dist_neighbors_building_{label}"] = momepy.neighbor_distance(
            buildings, graph
        )
    for steps, graph in etc_higher_order.items():
        columns[f"neighbors_etc_{steps}steps"] = momepy.neighbors(etc, graph, weighted=False)
        if steps > 1:
            columns[f"mean_dist_neighbors_etc_{steps}steps"] = momepy.neighbor_distance(etc, graph)

    return pd.DataFrame(columns, index=buildings.index)
