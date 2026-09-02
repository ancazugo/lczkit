"""`TessellationUnits`: every ETC traces to exactly one parent building, and none partitions air.

Run over `clean_vectors()`'s real output on the Hong Kong fixture — the primary fixture since
Phase 10 — rather than over hand-built shapes, because the property this module exists to
guarantee (a unique, traceable `unit_id` per building-bearing tessellation cell) is exactly the
kind of thing that breaks on real, messy input and not on a synthetic square.
"""

from __future__ import annotations

import pytest
from conftest import HONGKONG_FIXTURES_DIR, HONGKONG_SMALL_BBOX, SMALL_CLEANING, FixtureVectorSource

from lczkit.cleaning.pipeline import CleanedVectors, clean_vectors
from lczkit.units import check_units
from lczkit.units.enclosures import assemble_barriers
from lczkit.units.tessellation import TessellationUnits


@pytest.fixture(scope="session")
def hongkong_vector_source() -> FixtureVectorSource:
    return FixtureVectorSource(HONGKONG_FIXTURES_DIR)


@pytest.fixture(scope="session")
def cleaned(hongkong_vector_source: FixtureVectorSource) -> CleanedVectors:
    return clean_vectors(hongkong_vector_source, HONGKONG_SMALL_BBOX, SMALL_CLEANING)


def test_every_etc_has_exactly_one_parent_building(cleaned: CleanedVectors) -> None:
    barriers = assemble_barriers(cleaned.streets, cleaned.waterbodies)
    strategy = TessellationUnits(buildings=cleaned.buildings_area)

    units = strategy.generate(HONGKONG_SMALL_BBOX, barriers)

    check_units(units)
    assert units.crs == cleaned.crs
    assert units["parent_building_id"].is_unique
    assert units["parent_building_id"].notna().all()
    assert (units["parent_building_id"].astype(str) != "").all()


def test_report_accounts_for_every_tessellation_cell(cleaned: CleanedVectors) -> None:
    barriers = assemble_barriers(cleaned.streets, cleaned.waterbodies)
    strategy = TessellationUnits(buildings=cleaned.buildings_area)

    units = strategy.generate(HONGKONG_SMALL_BBOX, barriers)
    report = strategy.report

    assert report is not None
    assert report.n_etc == len(units)
    assert report.n_enclosures > 0
    assert report.n_buildings_in >= report.n_etc
    # Cells without a parent building are excluded, per Majer & Fleischmann (2026): tessellation
    # is not required to partition the enclosure, only to describe built ground.
    assert report.n_excluded_no_parent_building >= 0
    assert set(report.etc_area_quantiles) == {"p10", "p50", "p90"}
    assert report.etc_area_quantiles["p10"] <= report.etc_area_quantiles["p50"]
    assert report.etc_area_quantiles["p50"] <= report.etc_area_quantiles["p90"]


def test_generate_requires_barriers(cleaned: CleanedVectors) -> None:
    strategy = TessellationUnits(buildings=cleaned.buildings_area)
    with pytest.raises(ValueError, match="barriers"):
        strategy.generate(HONGKONG_SMALL_BBOX, None)


def test_duplicate_building_identifiers_still_yield_unique_unit_ids(
    cleaned: CleanedVectors,
) -> None:
    """A building layer whose `building_id` repeats (e.g. exploded multipolygon parts sharing one
    pre-explode stamp) must not silently collapse two real footprints under `set_index("unit_id")`.
    """
    barriers = assemble_barriers(cleaned.streets, cleaned.waterbodies)
    duplicated = cleaned.buildings_area.copy()
    duplicated["building_id"] = "same-id-for-everyone"

    strategy = TessellationUnits(buildings=duplicated)
    units = strategy.generate(HONGKONG_SMALL_BBOX, barriers)

    check_units(units)
    assert units.index.is_unique
