"""`compute_morphometrics`: the one function `lczkit.pipeline` calls for this stage.

Builds the tessellation, builds every `libpysal.graph.Graph` the metric modules need exactly
once, runs the three attribute blocks (`dimensional`, `distribution`, `streets`), validates the
result against the registry, and optionally runs the opt-in contextual expansion.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from lczkit.config import MorphometricsConfig
from lczkit.morphometrics import graphs
from lczkit.morphometrics.contextual import contextual_expand
from lczkit.morphometrics.dimensional import dimensional_metrics
from lczkit.morphometrics.distribution import distribution_metrics
from lczkit.morphometrics.registry import PARAMETER_COLUMNS
from lczkit.morphometrics.report import MorphometricsReport
from lczkit.morphometrics.streets import street_metrics
from lczkit.protocols import BBox
from lczkit.units.enclosures import assemble_barriers
from lczkit.units.tessellation import TessellationUnits, buildings_for_etc


def compute_morphometrics(
    bbox: BBox,
    buildings: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    waterbodies: gpd.GeoDataFrame,
    *,
    config: MorphometricsConfig,
) -> tuple[gpd.GeoDataFrame, MorphometricsReport]:
    """The 107 primary morphometric attributes, indexed by ETC `unit_id`, alongside geometry.

    Plus, if `config.contextual`, their percentile expansion. `buildings` should be
    `buildings_area` from `lczkit.cleaning.pipeline.clean_vectors` — the
    area-preserving layer every other area statistic in this package reads. `streets` should be
    the cleaned, simplified network; `waterbodies` the cleaned waterbody polygons. All three must
    already share one projected CRS, as `clean_vectors` returns them.
    """
    barriers = assemble_barriers(streets, waterbodies)
    strategy = TessellationUnits(
        buildings=buildings,
        shrink=config.tessellation_shrink,
        segment=config.tessellation_segment,
        threshold=config.tessellation_threshold,
    )
    etc = strategy.generate(bbox, barriers)
    assert strategy.report is not None  # generate() always sets it before returning

    if len(etc) > config.max_tessellation_cells:
        raise ValueError(
            f"tessellation produced {len(etc)} cells, over the configured ceiling of "
            f"{config.max_tessellation_cells} (MorphometricsConfig.max_tessellation_cells)"
        )

    matched_buildings = buildings_for_etc(buildings, etc)

    building_contiguity = graphs.building_contiguity(matched_buildings)
    building_distance_bands = {
        f"{int(distance)}m": graphs.building_distance_band(matched_buildings, distance)
        for distance in config.building_neighborhood_distances_m
    }
    building_knn = {
        f"knn{k}": graphs.building_knn(matched_buildings, k) for k in config.building_knn_values
    }
    etc_contiguity = graphs.etc_contiguity(etc)
    etc_higher_order = {
        steps: graphs.etc_higher_order(etc_contiguity, steps)
        for steps in config.etc_topological_steps
    }

    dimensional = dimensional_metrics(
        matched_buildings,
        etc,
        building_contiguity=building_contiguity,
        building_w100m=building_distance_bands["100m"],
        building_w200m=building_distance_bands["200m"],
        etc_w3steps=etc_higher_order[3],
    )
    distribution = distribution_metrics(
        matched_buildings,
        etc,
        streets,
        building_contiguity=building_contiguity,
        building_adjacency_neighborhood=building_distance_bands["200m"],
        building_w100m=building_distance_bands["100m"],
        building_w200m=building_distance_bands["200m"],
        building_distance_bands=building_distance_bands,
        building_knn=building_knn,
        etc_higher_order=etc_higher_order,
    )
    street = street_metrics(
        etc,
        streets,
        buildings,
        profile_distance_m=config.street_profile_distance_m,
        profile_tick_length_m=config.street_profile_tick_length_m,
        node_radii_m=tuple(config.street_node_radii_m),
    )

    primary = pd.concat([dimensional, distribution, street], axis=1)
    missing = sorted(set(PARAMETER_COLUMNS) - set(primary.columns))
    extra = sorted(set(primary.columns) - set(PARAMETER_COLUMNS))
    if missing or extra:
        raise RuntimeError(
            "compute_morphometrics output does not match the registry — "
            f"missing: {missing}, unexpected: {extra}"
        )
    primary = primary[list(PARAMETER_COLUMNS)]

    n_contextual = 0
    if config.contextual:
        if len(etc) > config.max_contextual_cells:
            raise ValueError(
                f"tessellation produced {len(etc)} cells, over the configured ceiling of "
                f"{config.max_contextual_cells} for the contextual expansion "
                "(MorphometricsConfig.max_contextual_cells)"
            )
        contextual_graph = graphs.etc_higher_order(etc_contiguity, config.contextual_steps)
        contextual = contextual_expand(
            primary, contextual_graph, quantiles=config.contextual_quantiles
        )
        n_contextual = contextual.shape[1]
        primary = pd.concat([primary, contextual], axis=1)

    result = gpd.GeoDataFrame(primary.join(etc[["geometry"]]), geometry="geometry", crs=etc.crs)
    report = MorphometricsReport(
        tessellation=strategy.report,
        n_primary_attributes=len(PARAMETER_COLUMNS),
        contextual_enabled=config.contextual,
        n_contextual_attributes=n_contextual,
    )
    return result, report
