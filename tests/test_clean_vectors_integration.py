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
        (result.land_use, "land_use"),
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

    # Land use is functional metadata, not a physical surface — it is carried through with
    # geometry repair only and takes no part in cross-layer topology.
    assert not result.land_use.empty
    assert (result.land_use.geometry.geom_type.isin(["Polygon", "MultiPolygon"])).all()
    assert result.land_use.geometry.is_valid.all()
    assert {"subtype", "class"} <= set(result.land_use.columns)

    # `subtype`/`class` (the only route to LCZ 10) and `sources` (Phase 3's diagnostic) must
    # survive cleaning, not be dropped after the geometry work.
    assert {"subtype", "class", "sources"} <= set(result.buildings.columns)

    # Overture parses `height` only from OSM tags and conflates winner-takes-all, so on real
    # data a large share of footprints carry none. That is expected — Phase 3 owns it, and
    # nothing in Phase 1 may treat it as an error.
    assert result.buildings["height"].isna().any()

    steps = result.report.steps
    assert len(steps) > 0
    stages = {s.stage for s in steps}
    assert stages == {"buildings", "streets", "land_use", "topology"}
    validate_step = next(s for s in steps if s.operation == "validate_planarity")
    assert isinstance(validate_step.detail["is_planar_enforced"], bool)
    for step in steps:
        if step.operation not in ("explode_multipolygons",):
            # every operation except explode is a filter/merge — never grows feature count
            assert step.n_out <= step.n_in
