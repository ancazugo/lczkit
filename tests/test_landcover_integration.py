"""Phase 4 end to end on the fixture city, joined against what Phases 2 and 3 produce.

The point of the "unit of exchange" decision is that every stage after unit generation is a join
on `unit_id`. This is where that gets checked for land cover: the fractions table has to land on
the same index the height metrics do, for both unit strategies.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from conftest import LANDCOVER_FIXTURES_DIR, SMALL_BBOX, FixtureVectorSource

from lczkit.cleaning.pipeline import clean_vectors
from lczkit.config import CleaningConfig, HeightConfig, LandCoverConfig
from lczkit.heights.cascade import cascade_height_sources, fill_heights
from lczkit.heights.completeness import height_metrics
from lczkit.heights.tiers import build_cascade
from lczkit.landcover.local import LocalRasterSource
from lczkit.units.enclosures import EnclosureUnits, assemble_barriers
from lczkit.units.grid import GridUnits

WORLDCOVER = LANDCOVER_FIXTURES_DIR / "worldcover_berlin.tif"
CANOPY = LANDCOVER_FIXTURES_DIR / "eth_canopy_berlin.tif"

_CLEANING = CleaningConfig(
    building_max_area_m2=50_000.0,
    building_min_area_m2=20.0,
    building_merge_limit_m2=200.0,
    building_overlap_limit=0.1,
)


def _source(name: str, path) -> LocalRasterSource:  # type: ignore[no-untyped-def]
    return LocalRasterSource(LandCoverConfig().dataset(name), path)


@pytest.fixture(scope="module")
def grid_units() -> gpd.GeoDataFrame:
    return GridUnits().generate(SMALL_BBOX)


def test_fractions_sum_to_one_on_the_fixture_grid(grid_units: gpd.GeoDataFrame) -> None:
    """CLAUDE.md's named property test for this phase."""
    result = _source("worldcover", WORLDCOVER).fractions(grid_units)

    covered = result.dropna(how="all")
    assert not covered.empty
    assert covered.sum(axis=1).to_numpy() == pytest.approx(1.0)


def test_both_datasets_join_onto_one_units_table(grid_units: gpd.GeoDataFrame) -> None:
    worldcover = _source("worldcover", WORLDCOVER).fractions(grid_units)
    canopy = _source("eth_canopy", CANOPY).fractions(grid_units)

    joined = grid_units.join(worldcover).join(canopy)

    assert joined.index.equals(grid_units.index)
    assert {"frac_impervious", "frac_tree", "canopy_frac_tree"} <= set(joined.columns)
    assert isinstance(joined, gpd.GeoDataFrame)


def test_land_cover_joins_against_the_phase_3_height_metrics(
    fixture_vector_source: FixtureVectorSource, grid_units: gpd.GeoDataFrame
) -> None:
    """The whole point of `unit_id` as the unit of exchange: two independently computed tables land
    on the same index and merge without any spatial work."""
    cleaned = clean_vectors(fixture_vector_source, SMALL_BBOX, _CLEANING)

    heights_config = HeightConfig(
        overture_height_confidence=0.9, overture_num_floors_confidence=0.6
    )
    tiers = build_cascade(heights_config, lambda name: LANDCOVER_FIXTURES_DIR)
    buildings, _ = fill_heights(cleaned.buildings, tiers)
    heights = height_metrics(buildings, grid_units, cascade_height_sources(tiers))

    fractions = _source("worldcover", WORLDCOVER).fractions(grid_units)
    combined = heights.join(fractions)

    assert combined.index.equals(grid_units.index)
    assert "height_completeness" in combined.columns
    assert "frac_impervious" in combined.columns
    # Units holding buildings should be the impervious ones — a weak check, deliberately: this
    # asserts the two tables describe the same places, not any particular parameter value.
    built = combined.dropna(subset=["height_completeness", "frac_impervious"])
    assert not built.empty
    assert built["frac_impervious"].mean() > 0.5


def test_enclosure_units_work_the_same_way(
    fixture_vector_source: FixtureVectorSource,
) -> None:
    """`RasterSource` is indifferent to how the units were made — it only needs a projected CRS and
    a `unit_id` index, which both strategies guarantee."""
    cleaned = clean_vectors(fixture_vector_source, SMALL_BBOX, _CLEANING)
    rail = fixture_vector_source.rail(SMALL_BBOX).to_crs(cleaned.crs)
    barriers = assemble_barriers(cleaned.streets, cleaned.waterbodies, rail=rail)
    units = EnclosureUnits().generate(SMALL_BBOX, barriers)

    result = _source("worldcover", WORLDCOVER).fractions(units)

    assert result.index.equals(units.index)
    covered = result.dropna(how="all")
    assert not covered.empty
    assert covered.sum(axis=1).to_numpy() == pytest.approx(1.0)
    assert np.isfinite(covered.to_numpy()).all()
