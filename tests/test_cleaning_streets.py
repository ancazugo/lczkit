"""Test for `simplify_streets` against a small real subset of the committed Berlin fixture.

`neatnet`'s exact output on real topology isn't hand-predictable, unlike the building-cleaning
leaf functions — this asserts structural properties, not exact values, per CLAUDE.md's test
strategy for anything beyond hand-built synthetic cases.
"""

from __future__ import annotations

from conftest import SMALL_BBOX, FixtureVectorSource

from lczkit.cleaning.pipeline import reproject_to_local_utm
from lczkit.cleaning.streets import simplify_streets
from lczkit.crs import assert_projected_crs


def test_simplify_streets_on_real_subset(fixture_vector_source: FixtureVectorSource) -> None:
    _, layers = reproject_to_local_utm(
        SMALL_BBOX,
        buildings=fixture_vector_source.buildings(SMALL_BBOX),
        streets=fixture_vector_source.streets(SMALL_BBOX),
    )
    buildings, streets = layers["buildings"], layers["streets"]

    simplified, step = simplify_streets(streets, buildings)

    assert_projected_crs(simplified, "simplified")
    assert simplified.crs == streets.crs
    assert len(simplified) <= len(streets)
    assert simplified.geometry.is_valid.all()
    assert (simplified.geometry.geom_type.isin(["LineString", "MultiLineString"])).all()
    assert step.stage == "streets"
    assert step.operation == "simplify_streets"
    assert step.n_in == len(streets)
    assert step.n_out == len(simplified)
