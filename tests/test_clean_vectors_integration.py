"""End-to-end integration test: `clean_vectors()` against a small real subset of the committed
Berlin fixture. Asserts shape/schema/CRS/planarity, not exact values, per CLAUDE.md's test
strategy — with one exception. Phase 1's acceptance criterion is a *number*, `buildings_area`
retaining at least 99% of the raw footprint area, and it is asserted here against the report's own
fields rather than against a recomputation, so that what is being trusted is the report a reader
would see.
"""

from __future__ import annotations

import pytest
from conftest import SMALL_BBOX, FixtureVectorSource

from lczkit.cleaning.buildings import BUILDING_ID
from lczkit.cleaning.pipeline import CleanedVectors, clean_vectors
from lczkit.config import CleaningConfig
from lczkit.crs import assert_projected_crs

_TEST_CLEANING_CONFIG = CleaningConfig(
    building_max_area_m2=10_000,
    building_min_area_m2=15,
    building_merge_limit_m2=50,
    building_overlap_limit=0.3,
    building_road_buffer_m=4.0,
    building_road_overlap_limit=0.5,
)


@pytest.fixture(scope="module")
def result(fixture_vector_source: FixtureVectorSource) -> CleanedVectors:
    return clean_vectors(fixture_vector_source, SMALL_BBOX, _TEST_CLEANING_CONFIG)


def test_clean_vectors_end_to_end(result: CleanedVectors) -> None:
    for layer, name in [
        (result.buildings_area, "buildings_area"),
        (result.buildings_topo, "buildings_topo"),
        (result.streets, "streets"),
        (result.waterlines, "waterlines"),
        (result.waterbodies, "waterbodies"),
        (result.land_use, "land_use"),
    ]:
        assert_projected_crs(layer, name)
        assert layer.crs == result.crs

    for layer in (result.buildings_area, result.buildings_topo):
        assert (layer.geometry.geom_type == "Polygon").all()
        assert layer.geometry.is_valid.all()
    assert (result.waterbodies.geometry.geom_type.isin(["Polygon", "MultiPolygon"])).all()
    assert (result.streets.geometry.geom_type.isin(["LineString", "MultiLineString"])).all()
    assert (result.waterlines.geometry.geom_type.isin(["LineString", "MultiLineString"])).all()

    # Land use is functional metadata, not a physical surface — it is carried through with
    # geometry repair only and takes no part in cross-layer topology.
    assert not result.land_use.empty
    assert (result.land_use.geometry.geom_type.isin(["Polygon", "MultiPolygon"])).all()
    assert result.land_use.geometry.is_valid.all()
    assert {"subtype", "class"} <= set(result.land_use.columns)

    # `subtype`/`class` (the only route to LCZ 10) and `sources` (Phase 3's diagnostic) must
    # survive cleaning on both layers, not be dropped after the geometry work.
    for layer in (result.buildings_area, result.buildings_topo):
        assert {"subtype", "class", "sources", BUILDING_ID} <= set(layer.columns)

    # Overture parses `height` only from OSM tags and conflates winner-takes-all, so on real
    # data a large share of footprints carry none. That is expected — Phase 3 owns it, and
    # nothing in Phase 1 may treat it as an error.
    assert result.buildings_area["height"].isna().any()


def test_the_area_layer_retains_the_footprint_area_the_metric_needs(result: CleanedVectors) -> None:
    """Phase 1's acceptance criterion, and the regression guard for the whole of Phase 6.6.

    Read off the report rather than recomputed: a report that says 99% while the layer holds 76%
    is exactly the failure this phase exists to close, and only reading the report catches it.
    """
    retention = result.report.area_retention("buildings_area")

    assert retention is not None
    assert retention >= 0.99

    # ...and the report is not lying about the layer it describes.
    steps = result.report.stage_steps("buildings_area")
    assert steps[-1].area_out_m2 == pytest.approx(result.buildings_area.geometry.area.sum())


def test_the_two_layers_are_joinable_and_the_area_one_is_the_larger(result: CleanedVectors) -> None:
    """Both derive from one base and share `building_id`, so a statistic computed on one can be
    carried to the other. `buildings_area` is unique on it; `buildings_topo` is a subset, having
    dissolved and dropped features the other keeps."""
    assert result.buildings_area[BUILDING_ID].is_unique
    assert set(result.buildings_topo[BUILDING_ID]) <= set(result.buildings_area[BUILDING_ID])
    assert result.buildings_area.geometry.area.sum() > result.buildings_topo.geometry.area.sum()


def test_only_the_topological_layer_is_cleared_of_streets_and_water(result: CleanedVectors) -> None:
    """The split's whole point. `buildings_topo` is clear of waterbodies and holds nothing
    substantially inside the roadway; `buildings_area` is not asked to be either, because every
    operation that would make it so costs footprint area."""
    if not result.waterbodies.empty:
        hits = result.buildings_topo.sjoin(
            result.waterbodies[["geometry"]], predicate="intersects", how="inner"
        )
        assert hits.empty

    if not result.streets.empty:
        road = result.streets.geometry.buffer(_TEST_CLEANING_CONFIG.building_road_buffer_m or 0.0)
        inside = result.buildings_topo.geometry.intersection(road.union_all()).area
        fraction = inside / result.buildings_topo.geometry.area
        assert (fraction <= _TEST_CLEANING_CONFIG.building_road_overlap_limit).all()


def test_every_step_records_both_a_count_and_an_area(result: CleanedVectors) -> None:
    """Counts alone are why a 23.5% area loss survived from Phase 1 to Phase 6.5: by count, the
    operation responsible was the smaller of the two suspects."""
    steps = result.report.steps
    assert len(steps) > 0
    assert {s.stage for s in steps} == {
        "buildings",
        "buildings_area",
        "buildings_topo",
        "streets",
        "land_use",
        "topology",
    }

    # Asserted `is True`, not `isinstance(..., bool)`. It sat at False for two phases while
    # `momepy.enclosures()` — which requires a planar input — read this layer, and a test that
    # only checked the type could not tell.

    validate_step = next(s for s in steps if s.operation == "validate_planarity")
    assert validate_step.detail["is_planar_enforced"] is True

    for step in steps:
        if step.operation not in ("explode_multipolygons",):
            # every operation except explode is a filter/merge — never grows feature count
            assert step.n_out <= step.n_in
        if step.stage in ("buildings", "buildings_area", "buildings_topo"):
            assert step.area_in_m2 > 0.0
            assert step.area_retained is not None


def test_the_street_rule_reports_what_it_dropped_and_trimmed(result: CleanedVectors) -> None:
    """A rule that never fires must be distinguishable from one never configured, and trimming
    must be distinguishable from dropping — they cost very different amounts of area."""
    step = next(s for s in result.report.steps if s.operation == "resolve_buildings_on_streets")

    assert step.detail["road_buffer_m"] == 4.0
    assert step.detail["overlap_limit"] == 0.5
    assert step.detail["n_dropped"] + step.detail["n_trimmed"] > 0
    assert step.detail["area_dropped_m2"] <= step.area_in_m2 - step.area_out_m2
