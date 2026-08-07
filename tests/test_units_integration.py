"""End-to-end Phase 2 integration test: Phase 1's `clean_vectors()` output feeds
`assemble_barriers`/`EnclosureUnits`, alongside `GridUnits`, and `aggregate()` moves values
between the two unit systems on the same real (small) Berlin fixture subset. Asserts
shape/schema/CRS and "round trips sensibly" per CLAUDE.md's Phase 2 acceptance criterion, not
exact values.
"""

from __future__ import annotations

import numpy as np
from conftest import SMALL_BBOX, FixtureVectorSource

from lczkit.cleaning.pipeline import clean_vectors
from lczkit.config import CleaningConfig
from lczkit.crs import assert_projected_crs
from lczkit.units.aggregate import aggregate
from lczkit.units.enclosures import EnclosureUnits, assemble_barriers
from lczkit.units.grid import GridUnits

_TEST_CLEANING_CONFIG = CleaningConfig(
    building_max_area_m2=10_000,
    building_min_area_m2=15,
    building_merge_limit_m2=50,
    building_overlap_limit=0.3,
    building_road_buffer_m=4.0,
    building_road_overlap_limit=0.5,
)


def test_enclosure_and_grid_units_and_aggregate_round_trip(
    fixture_vector_source: FixtureVectorSource,
) -> None:
    cleaned = clean_vectors(fixture_vector_source, SMALL_BBOX, _TEST_CLEANING_CONFIG)
    rail = fixture_vector_source.rail(SMALL_BBOX).to_crs(cleaned.crs)
    assert not rail.empty, "SMALL_BBOX is expected to contain real rail segments"

    barriers = assemble_barriers(cleaned.streets, cleaned.waterbodies, rail=rail)
    enclosures = EnclosureUnits().generate(SMALL_BBOX, barriers)
    grid = GridUnits(cell_size_m=100.0).generate(SMALL_BBOX)

    for units, name in [(enclosures, "enclosures"), (grid, "grid")]:
        assert_projected_crs(units, name)
        assert units.crs == cleaned.crs
        assert units.index.name == "unit_id"
        assert units.index.is_unique
        assert not units.empty
        assert units.geometry.is_valid.all()

    rng = np.random.default_rng(0)
    enclosures = enclosures.assign(
        value=enclosures.geometry.area,
        label=rng.choice(["A", "B", "C"], size=len(enclosures)),
    )

    grid_from_enclosures_mean = aggregate(enclosures, grid, "area_weighted")
    grid_from_enclosures_majority = aggregate(enclosures, grid, "majority")

    # "round trips sensibly": no aggregated value extrapolates outside the source range, most
    # target cells get real coverage (the two unit systems cover ~the same footprint), and
    # majority labels are always one of the real source categories.
    non_null = grid_from_enclosures_mean["value"].dropna()
    assert len(non_null) / len(grid) > 0.5
    assert non_null.min() >= enclosures["value"].min()
    assert non_null.max() <= enclosures["value"].max() + 1e-6

    non_null_labels = grid_from_enclosures_majority["label"].dropna()
    assert set(non_null_labels.unique()) <= {"A", "B", "C"}

    # and the reverse direction: grid -> enclosures
    grid = grid.assign(value=grid.geometry.area)
    enclosures_from_grid = aggregate(grid, enclosures, "area_weighted")
    assert enclosures_from_grid["value"].dropna().gt(0).all()
