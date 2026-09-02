"""The three attribute blocks, the graphs they share, and the orchestrator that assembles them.

Property tests rather than exact-value tests, per the project's own test-strategy convention —
what's asserted is shape, schema, and the documented mathematical properties of each metric
(bounded ratios, non-negative counts, area identities), never a specific number that would make
this test a second copy of the implementation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from conftest import HONGKONG_FIXTURES_DIR, HONGKONG_SMALL_BBOX, SMALL_CLEANING, FixtureVectorSource
from shapely.geometry import MultiPolygon, box

from lczkit.cleaning.pipeline import CleanedVectors, clean_vectors
from lczkit.config import MorphometricsConfig
from lczkit.morphometrics import graphs
from lczkit.morphometrics.compute import compute_morphometrics
from lczkit.morphometrics.contextual import contextual_expand
from lczkit.morphometrics.dimensional import dimensional_metrics
from lczkit.morphometrics.distribution import distribution_metrics
from lczkit.morphometrics.registry import PARAMETER_COLUMNS
from lczkit.morphometrics.streets import street_metrics
from lczkit.units.enclosures import assemble_barriers
from lczkit.units.tessellation import TessellationUnits, buildings_for_etc

#: Ratios geometrically guaranteed to fall in [0, 1] because the denominator always contains the
#: numerator's shape (an enclosing circle, a convex hull, a bounding rectangle, or a comparison of
#: two sides). `dimensional_metrics` clips all of these explicitly (see
#: `_BOUNDED_TO_UNIT_INTERVAL` there) because the underlying GEOS computation measurably overshoots
#: 1.0 by a few parts in 10\N{SUPERSCRIPT FOUR} on real data (Hong Kong fixture: `rectangularity`
#: at 1.0000039; a Nairobi smoke test: 1.000246) — floating-point noise, not a real property.
#: Deliberately excludes `square_compactness` — `(4*sqrt(area)/perimeter)^2` is exactly 1 for a
#: square but *not* bounded above: a shape rounder than a square exceeds it, which is not a defect.
_BOUNDED_FRACTIONS = (
    "courtyard_index_building",
    "circular_compactness_building",
    "circular_compactness_etc",
    "convexity_building",
    "convexity_etc",
    "elongation_building",
    "elongation_etc",
    "rectangularity_building",
    "rectangularity_etc",
    "shape_index_building",
    "shape_index_etc",
)


@pytest.fixture(scope="session")
def hongkong_vector_source() -> FixtureVectorSource:
    return FixtureVectorSource(HONGKONG_FIXTURES_DIR)


@pytest.fixture(scope="session")
def cleaned(hongkong_vector_source: FixtureVectorSource) -> CleanedVectors:
    return clean_vectors(hongkong_vector_source, HONGKONG_SMALL_BBOX, SMALL_CLEANING)


@pytest.fixture(scope="session")
def etc_and_buildings(cleaned: CleanedVectors):
    barriers = assemble_barriers(cleaned.streets, cleaned.waterbodies)
    strategy = TessellationUnits(buildings=cleaned.buildings_area)
    etc = strategy.generate(HONGKONG_SMALL_BBOX, barriers)
    buildings = buildings_for_etc(cleaned.buildings_area, etc)
    return etc, buildings


# --------------------------------------------------------------------------------------------
# graphs.py
# --------------------------------------------------------------------------------------------


def test_etc_contiguity_uses_fuzzy_matching(etc_and_buildings) -> None:
    """momepy's own documented reason `enclosed_tessellation` output needs fuzzy contiguity: a
    plain queen graph over the same cells finds fewer neighbour pairs."""
    etc, _ = etc_and_buildings
    fuzzy = graphs.etc_contiguity(etc)
    from libpysal.graph import Graph

    exact = Graph.build_contiguity(etc, rook=False)
    assert fuzzy.n_edges >= exact.n_edges


def test_higher_order_is_inclusive_of_lower_orders(etc_and_buildings) -> None:
    etc, _ = etc_and_buildings
    base = graphs.etc_contiguity(etc)
    one_step = graphs.etc_higher_order(base, 1)
    two_step = graphs.etc_higher_order(base, 2)
    assert one_step.n_edges == base.n_edges
    assert two_step.n_edges >= one_step.n_edges


def test_granularity_graph_includes_the_focal_cell(etc_and_buildings) -> None:
    etc, _ = etc_and_buildings
    base = graphs.etc_contiguity(etc)
    granularity = graphs.etc_granularity_graph(graphs.etc_higher_order(base, 1))
    area = etc.geometry.area
    lagged = granularity.lag(area)
    # A cell with zero neighbours still contributes its own area once self-weighted.
    isolated = [node for node, neighbours in base.neighbors.items() if len(neighbours) == 0]
    if isolated:
        assert lagged.loc[isolated[0]] == pytest.approx(area.loc[isolated[0]])


# --------------------------------------------------------------------------------------------
# dimensional.py
# --------------------------------------------------------------------------------------------


def test_dimensional_metrics_shape_and_area_identity(etc_and_buildings) -> None:
    etc, buildings = etc_and_buildings
    bc = graphs.building_contiguity(buildings)
    bw100 = graphs.building_distance_band(buildings, 100)
    bw200 = graphs.building_distance_band(buildings, 200)
    etc3 = graphs.etc_higher_order(graphs.etc_contiguity(etc), 3)

    result = dimensional_metrics(
        buildings,
        etc,
        building_contiguity=bc,
        building_w100m=bw100,
        building_w200m=bw200,
        etc_w3steps=etc3,
    )

    assert result.shape == (len(buildings), 62)
    assert result.index.equals(buildings.index)
    np.testing.assert_allclose(
        result["area_building"].to_numpy(), buildings.geometry.area.to_numpy()
    )
    np.testing.assert_allclose(result["area_etc"].to_numpy(), etc.geometry.area.to_numpy())


def test_bounded_shape_ratios_stay_in_range(etc_and_buildings) -> None:
    """Ratios momepy itself defines as area-over-enclosing-area must fall in [0, 1] up to a small
    floating-point tolerance — the property this project's own test-strategy notes call cheap and
    worth asserting directly rather than trusting by construction."""
    etc, buildings = etc_and_buildings
    bc = graphs.building_contiguity(buildings)
    bw100 = graphs.building_distance_band(buildings, 100)
    bw200 = graphs.building_distance_band(buildings, 200)
    etc3 = graphs.etc_higher_order(graphs.etc_contiguity(etc), 3)
    result = dimensional_metrics(
        buildings,
        etc,
        building_contiguity=bc,
        building_w100m=bw100,
        building_w200m=bw200,
        etc_w3steps=etc3,
    )
    # Exact bounds: `dimensional_metrics` clips these explicitly, so no floating-point tolerance
    # is needed here — a value outside [0, 1] would mean the clip itself regressed.
    for column in _BOUNDED_FRACTIONS:
        values = result[column].dropna()
        assert (values >= 0.0).all(), column
        assert (values <= 1.0).all(), column


def test_courtyard_is_null_not_negative_for_a_multipolygon_building(etc_and_buildings) -> None:
    """Found on real Nairobi Overture data: `momepy.courtyard_area` calls
    `shapely.get_exterior_ring`, defined only for a single `Polygon`. On a MultiPolygon it
    returns `None`, which silently turns the courtyard-area formula's "filled" term into 0 and
    the result into `-area` — a real footprint, and a value no one would design deliberately.
    `buildings_area` can legitimately hold MultiPolygons (small-building-absorption dissolves two
    non-adjacent footprints without erasing either), so this has to be handled, not assumed away.
    """
    etc, buildings = etc_and_buildings
    multipart = buildings.copy()
    multipart.iloc[0, multipart.columns.get_loc("geometry")] = MultiPolygon(
        [box(0, 0, 10, 10), box(20, 20, 25, 25)]
    )
    bc = graphs.building_contiguity(multipart)
    bw100 = graphs.building_distance_band(multipart, 100)
    bw200 = graphs.building_distance_band(multipart, 200)
    etc3 = graphs.etc_higher_order(graphs.etc_contiguity(etc), 3)

    result = dimensional_metrics(
        multipart,
        etc,
        building_contiguity=bc,
        building_w100m=bw100,
        building_w200m=bw200,
        etc_w3steps=etc3,
    )

    affected = result.iloc[0]
    assert pd.isna(affected["courtyard_area_building"])
    assert pd.isna(affected["courtyard_index_building"])
    # Every other building is untouched.
    assert result["courtyard_index_building"].iloc[1:].notna().any()


# --------------------------------------------------------------------------------------------
# distribution.py
# --------------------------------------------------------------------------------------------


def test_distribution_metrics_shape_and_coverage_ratio(
    etc_and_buildings, cleaned: CleanedVectors
) -> None:
    etc, buildings = etc_and_buildings
    bc = graphs.building_contiguity(buildings)
    b20 = graphs.building_distance_band(buildings, 20)
    b100 = graphs.building_distance_band(buildings, 100)
    b200 = graphs.building_distance_band(buildings, 200)
    knn = {f"knn{k}": graphs.building_knn(buildings, k) for k in (10, 20, 30)}
    etc_contig = graphs.etc_contiguity(etc)
    higher = {steps: graphs.etc_higher_order(etc_contig, steps) for steps in (1, 2, 3)}

    result = distribution_metrics(
        buildings,
        etc,
        cleaned.streets,
        building_contiguity=bc,
        building_adjacency_neighborhood=b200,
        building_w100m=b100,
        building_w200m=b200,
        building_distance_bands={"20m": b20, "100m": b100, "200m": b200},
        building_knn=knn,
        etc_higher_order=higher,
    )

    assert result.shape == (len(buildings), 23)
    # Coverage area ratio is a building's own footprint over its own ETC's area. Usually <= 1,
    # but not guaranteed: momepy's tessellation shrink/segment step does not guarantee a cell
    # fully contains the building that seeded it — measured on 6.4% of this fixture's ETCs, a
    # documented property of the algorithm rather than a bug in this computation. The invariant
    # that *is* safe to assert is non-negativity and that most cells are near or under 1.
    coverage = result["coverage_area_ratio_etc"].dropna()
    assert (coverage >= 0.0).all()
    assert (coverage <= 1.05).mean() > 0.9


# --------------------------------------------------------------------------------------------
# streets.py
# --------------------------------------------------------------------------------------------


def test_street_metrics_shape_and_non_negative_counts(
    etc_and_buildings, cleaned: CleanedVectors
) -> None:
    etc, _ = etc_and_buildings
    result = street_metrics(
        etc,
        cleaned.streets,
        cleaned.buildings_area,
        profile_distance_m=10.0,
        profile_tick_length_m=50.0,
    )
    assert result.shape == (len(etc), 22)
    assert result.index.equals(etc.index)
    assert (result["node_degree"].dropna() >= 0).all()
    assert (result["street_length"].dropna() >= 0).all()


# --------------------------------------------------------------------------------------------
# contextual.py
# --------------------------------------------------------------------------------------------


def test_contextual_expand_adds_three_columns_per_input_without_changing_them(
    etc_and_buildings,
) -> None:
    etc, buildings = etc_and_buildings
    bc = graphs.building_contiguity(buildings)
    bw100 = graphs.building_distance_band(buildings, 100)
    bw200 = graphs.building_distance_band(buildings, 200)
    etc_contig = graphs.etc_contiguity(etc)
    etc3 = graphs.etc_higher_order(etc_contig, 3)
    primary = dimensional_metrics(
        buildings,
        etc,
        building_contiguity=bc,
        building_w100m=bw100,
        building_w200m=bw200,
        etc_w3steps=etc3,
    )

    contextual = contextual_expand(
        primary, graphs.etc_higher_order(etc_contig, 3), quantiles=[25, 50, 75]
    )

    assert contextual.shape == (len(primary), primary.shape[1] * 3)
    for column in primary.columns:
        assert f"{column}_p25" in contextual.columns
        assert f"{column}_p50" in contextual.columns
        assert f"{column}_p75" in contextual.columns


# --------------------------------------------------------------------------------------------
# compute.py — the orchestrator
# --------------------------------------------------------------------------------------------


def test_compute_morphometrics_matches_the_registry_exactly(cleaned: CleanedVectors) -> None:
    result, report = compute_morphometrics(
        HONGKONG_SMALL_BBOX,
        cleaned.buildings_area,
        cleaned.streets,
        cleaned.waterbodies,
        config=MorphometricsConfig(enabled=True),
    )
    attribute_columns = [c for c in result.columns if c != "geometry"]
    assert set(attribute_columns) == set(PARAMETER_COLUMNS)
    assert len(attribute_columns) == 107
    assert result.crs == cleaned.crs
    assert report.n_primary_attributes == 107
    assert report.contextual_enabled is False
    assert report.n_contextual_attributes == 0
    assert report.tessellation.n_etc == len(result)


def test_compute_morphometrics_with_contextual_expansion_adds_321_columns(
    cleaned: CleanedVectors,
) -> None:
    result, report = compute_morphometrics(
        HONGKONG_SMALL_BBOX,
        cleaned.buildings_area,
        cleaned.streets,
        cleaned.waterbodies,
        config=MorphometricsConfig(enabled=True, contextual=True),
    )
    attribute_columns = [c for c in result.columns if c != "geometry"]
    assert len(attribute_columns) == 107 + 321
    assert report.contextual_enabled is True
    assert report.n_contextual_attributes == 321


def test_compute_morphometrics_refuses_an_oversized_tessellation(cleaned: CleanedVectors) -> None:
    config = MorphometricsConfig(enabled=True, max_tessellation_cells=1)
    with pytest.raises(ValueError, match="max_tessellation_cells"):
        compute_morphometrics(
            HONGKONG_SMALL_BBOX,
            cleaned.buildings_area,
            cleaned.streets,
            cleaned.waterbodies,
            config=config,
        )
