"""End-to-end integration test: `clean_vectors()` against a small real subset of the committed
Berlin fixture. Asserts shape/schema/CRS/planarity, not exact values, per CLAUDE.md's test
strategy.
"""

from __future__ import annotations

from conftest import SMALL_BBOX, FixtureVectorSource

from lczkit.cleaning.pipeline import clean_vectors
from lczkit.config import CleaningConfig
from lczkit.crs import assert_projected_crs

_TEST_CLEANING_CONFIG = CleaningConfig(
    building_max_area_m2=10_000,
    building_min_area_m2=15,
    building_merge_limit_m2=50,
    building_overlap_limit=0.3,
)


def test_clean_vectors_end_to_end(fixture_vector_source: FixtureVectorSource) -> None:
    result = clean_vectors(fixture_vector_source, SMALL_BBOX, _TEST_CLEANING_CONFIG)

    for layer, name in [
        (result.buildings, "buildings"),
        (result.streets, "streets"),
        (result.waterlines, "waterlines"),
        (result.waterbodies, "waterbodies"),
    ]:
        assert_projected_crs(layer, name)
        assert layer.crs == result.crs

    assert (result.buildings.geometry.geom_type == "Polygon").all()
    assert result.buildings.geometry.is_valid.all()
    assert (result.waterbodies.geometry.geom_type.isin(["Polygon", "MultiPolygon"])).all()
    assert (result.streets.geometry.geom_type.isin(["LineString", "MultiLineString"])).all()
    assert (result.waterlines.geometry.geom_type.isin(["LineString", "MultiLineString"])).all()

    # cross-layer topology: no surviving building should intersect a street or waterbody
    if not result.streets.empty:
        hits = result.buildings.sjoin(
            result.streets[["geometry"]], predicate="intersects", how="inner"
        )
        assert hits.empty
    if not result.waterbodies.empty:
        hits = result.buildings.sjoin(
            result.waterbodies[["geometry"]], predicate="intersects", how="inner"
        )
        assert hits.empty

    steps = result.report.steps
    assert len(steps) > 0
    stages = {s.stage for s in steps}
    assert stages == {"buildings", "streets", "topology"}
    validate_step = next(s for s in steps if s.operation == "validate_planarity")
    assert isinstance(validate_step.detail["is_planar_enforced"], bool)
    for step in steps:
        if step.operation not in ("explode_multipolygons",):
            # every operation except explode is a filter/merge — never grows feature count
            assert step.n_out <= step.n_in
