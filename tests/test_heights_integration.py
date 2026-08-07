"""End-to-end Phase 3 integration: Phase 1's cleaned buildings through the height cascade and
onto Phase 2's spatial units, on the same small real Berlin fixture subset.

Asserts shape, schema and provenance accounting rather than exact heights, per CLAUDE.md's test
strategy. The tier 2-4 raster is synthesised (see `conftest.write_height_raster`) — none of
those products exists on this system to clip a fixture from.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from conftest import SMALL_BBOX, FixtureVectorSource, write_height_raster
from shapely.geometry import box

from lczkit.cleaning.pipeline import CleanedVectors, clean_vectors
from lczkit.config import ArealTierConfig, CleaningConfig, HeightConfig
from lczkit.crs import local_utm_crs
from lczkit.heights.cascade import UNRESOLVED, fill_heights
from lczkit.heights.completeness import FRACTION_PREFIX, height_metrics
from lczkit.heights.diagnostic import source_availability
from lczkit.heights.tiers import OVERTURE_HEIGHT, OVERTURE_NUM_FLOORS, build_cascade
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

WEST_HEIGHT = 8.0
EAST_HEIGHT = 24.0
AREAL_TIER = "ghsl"


@pytest.fixture(scope="module")
def cleaned(fixture_vector_source: FixtureVectorSource) -> CleanedVectors:
    return clean_vectors(fixture_vector_source, SMALL_BBOX, _TEST_CLEANING_CONFIG)


@pytest.fixture(scope="module")
def areal_raster(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A two-cell raster covering the whole fixture subset in its local UTM CRS.

    Two values rather than one so the test can tell "the tier read the raster" apart from "the
    tier wrote a constant", and cells large enough that every building falls squarely inside one
    — the point here is the cascade wiring, not the sampling, which `test_heights_raster` covers.
    """
    crs = local_utm_crs(SMALL_BBOX)
    minx, miny, maxx, maxy = (
        gpd.GeoSeries([box(*SMALL_BBOX)], crs="EPSG:4326").to_crs(crs).total_bounds
    )
    pad = 500.0
    cell = max((maxx - minx) / 2, maxy - miny) + 2 * pad
    return write_height_raster(
        tmp_path_factory.mktemp("rasters") / "areal.tif",
        np.array([[WEST_HEIGHT, EAST_HEIGHT]]),
        origin=(minx - pad, maxy + pad),
        cell_size_m=cell,
        crs=crs.to_string(),
    )


def _config(areal_raster: Path) -> HeightConfig:
    return HeightConfig(
        storey_height_m=3.0,
        overture_height_confidence=0.9,
        overture_num_floors_confidence=0.6,
        areal_tiers=[
            ArealTierConfig(
                name=AREAL_TIER,
                source_dir_name="GHSL",
                filename=areal_raster.name,
                confidence=0.3,
            )
        ],
    )


def test_cascade_and_per_unit_metrics_end_to_end(
    cleaned: CleanedVectors, areal_raster: Path
) -> None:
    config = _config(areal_raster)
    tiers = build_cascade(config, lambda name: areal_raster.parent)

    buildings, report = fill_heights(cleaned.buildings_area, tiers)

    # acceptance: every building has a non-null height and a source tag
    assert not buildings.empty
    assert buildings["height"].notna().all()
    assert buildings["height"].gt(0).all()
    assert buildings["height_source"].notna().all()
    assert buildings["height_confidence"].notna().all()
    assert set(buildings["height_source"]) <= set(report.height_sources)
    assert report.n_unresolved == 0
    assert report.n_resolved == len(buildings)

    # Phase 1's retained attributes survive the cascade untouched
    assert {"subtype", "class", "sources"} <= set(buildings.columns)

    # all three routes fire on this extent, and the areal tier really read the raster
    fired = {result.tier: result.n_filled for result in report.tiers}
    assert fired["overture"] > 0
    assert fired[AREAL_TIER] > 0
    areal = buildings.loc[buildings["height_source"] == AREAL_TIER, "height"]
    assert set(np.unique(areal)) <= {WEST_HEIGHT, EAST_HEIGHT}

    grid = GridUnits(cell_size_m=100.0).generate(SMALL_BBOX)
    barriers = assemble_barriers(cleaned.streets, cleaned.waterbodies)
    enclosures = EnclosureUnits().generate(SMALL_BBOX, barriers)
    fraction_columns = [f"{FRACTION_PREFIX}{source}" for source in report.height_sources]

    for units, name in [(grid, "grid"), (enclosures, "enclosures")]:
        metrics = height_metrics(buildings, units, report.height_sources)

        assert metrics.index.equals(units.index), name
        assert list(metrics.columns) == ["height_completeness", *fraction_columns], name

        populated = metrics["height_completeness"].notna()
        assert populated.any(), name
        # CLAUDE.md's named property test: fractions sum to ~1.0 per unit
        sums = metrics.loc[populated, fraction_columns].sum(axis=1).to_numpy()
        assert sums == pytest.approx(1.0)
        assert metrics.loc[populated, "height_completeness"].between(0.0, 1.0).all(), name
        # units with no building area report nothing rather than reporting zero coverage
        assert metrics.loc[~populated].isna().all().all(), name

        # completeness is exactly the tier-1 share, and here it is neither 0 nor 1 everywhere:
        # the fixture mixes real Overture heights with the areal fallback
        tier1 = [f"{FRACTION_PREFIX}{OVERTURE_HEIGHT}", f"{FRACTION_PREFIX}{OVERTURE_NUM_FLOORS}"]
        assert metrics.loc[populated, "height_completeness"].to_numpy() == pytest.approx(
            metrics.loc[populated, tier1].sum(axis=1).to_numpy()
        )
        assert metrics.loc[populated, f"{FRACTION_PREFIX}{AREAL_TIER}"].gt(0).any(), name


def test_tier1_entirely_absent_falls_through_to_the_areal_tier(
    cleaned: CleanedVectors, areal_raster: Path
) -> None:
    """CLAUDE.md's acceptance case, and the situation this package exists for: an
    ML-dominated city where Overture carries no heights at all.

    The cascade must still produce a height for every building, and the output must say
    unambiguously that none of it is tier 1 — same LCZ labels, very different trustworthiness.
    """
    stripped = cleaned.buildings_area.assign(height=np.nan, num_floors=np.nan)
    tiers = build_cascade(_config(areal_raster), lambda name: areal_raster.parent)

    buildings, report = fill_heights(stripped, tiers)

    assert buildings["height"].notna().all()
    assert set(buildings["height_source"]) == {AREAL_TIER}
    assert report.n_unresolved == 0
    assert [result.n_filled for result in report.tiers] == [0, len(buildings)]

    grid = GridUnits(cell_size_m=100.0).generate(SMALL_BBOX)
    metrics = height_metrics(buildings, grid, report.height_sources)
    populated = metrics["height_completeness"].notna()

    assert populated.any()
    assert (metrics.loc[populated, "height_completeness"] == 0.0).all()
    areal_fraction = metrics.loc[populated, f"{FRACTION_PREFIX}{AREAL_TIER}"].to_numpy()
    assert areal_fraction == pytest.approx(1.0)


def test_without_an_areal_tier_the_shortfall_is_reported_not_raised(
    cleaned: CleanedVectors,
) -> None:
    """The default state of tiers 2-4: no product on disk. The run still completes, and the
    buildings Overture cannot answer for are tagged rather than silently given a number."""
    config = HeightConfig(overture_height_confidence=0.9, overture_num_floors_confidence=0.6)
    tiers = build_cascade(config, lambda name: Path("/nonexistent") / name)

    buildings, report = fill_heights(cleaned.buildings_area, tiers)

    assert [tier.name for tier in tiers] == ["overture"]
    assert report.n_unresolved > 0
    unresolved = buildings["height_source"] == UNRESOLVED
    assert unresolved.sum() == report.n_unresolved
    assert buildings.loc[unresolved, "height"].isna().all()

    grid = GridUnits(cell_size_m=100.0).generate(SMALL_BBOX)
    metrics = height_metrics(buildings, grid, report.height_sources)
    populated = metrics["height_completeness"].notna()

    assert metrics.loc[populated, f"{FRACTION_PREFIX}{UNRESOLVED}"].gt(0).any()
    assert metrics.loc[populated, "height_completeness"].lt(1.0).any()


def test_the_diagnostic_reports_the_fixtures_real_provenance(cleaned: CleanedVectors) -> None:
    diagnostic = source_availability(cleaned.buildings_area)

    assert diagnostic.n_buildings == len(cleaned.buildings_area)
    assert diagnostic.n_with_height < diagnostic.n_buildings
    assert {row.dataset for row in diagnostic.by_footprint_dataset} <= {
        "OpenStreetMap",
        "Microsoft ML Buildings",
        "Esri Community Maps",
    }
    assert sum(row.n_with_height for row in diagnostic.by_height_dataset) == (
        diagnostic.n_with_height
    )
