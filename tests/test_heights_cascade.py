"""Tests for `fill_heights`: tier ordering, tagging, and the report."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from conftest import write_height_raster
from shapely.geometry import box

from lczkit.heights.cascade import UNRESOLVED, cascade_height_sources, fill_heights
from lczkit.heights.tiers import (
    OVERTURE_HEIGHT,
    OVERTURE_NUM_FLOORS,
    ArealRasterTier,
    OvertureAttributeTier,
)

CRS = "EPSG:32633"


@pytest.fixture
def raster(tmp_path: Path) -> Path:
    """One 200 m cell holding 8 m, covering every geometry the tests below build."""
    return write_height_raster(
        tmp_path / "areal.tif",
        np.array([[8.0]]),
        origin=(0.0, 200.0),
        cell_size_m=200.0,
        crs=CRS,
        nodata=-9999.0,
    )


@pytest.fixture
def tier1() -> OvertureAttributeTier:
    return OvertureAttributeTier(
        storey_height_m=3.0, height_confidence=0.9, num_floors_confidence=0.6
    )


def _buildings(height: list, num_floors: list) -> gpd.GeoDataFrame:
    geoms = [box(10 * i, 10, 10 * i + 8, 18) for i in range(len(height))]
    return gpd.GeoDataFrame({"height": height, "num_floors": num_floors}, geometry=geoms, crs=CRS)


def test_each_building_is_resolved_by_the_first_tier_that_can(
    tier1: OvertureAttributeTier, raster: Path
) -> None:
    buildings = _buildings(height=[12.0, None, None], num_floors=[None, 4, None])
    areal = ArealRasterTier(name="ghsl", path=raster, confidence=0.3)

    filled, report = fill_heights(buildings, [tier1, areal])

    assert filled["height"].tolist() == [12.0, 12.0, 8.0]
    assert filled["height_source"].tolist() == [OVERTURE_HEIGHT, OVERTURE_NUM_FLOORS, "ghsl"]
    assert filled["height_confidence"].tolist() == [0.9, 0.6, 0.3]
    assert report.n_buildings == 3
    assert report.n_resolved == 3
    assert report.n_unresolved == 0


def test_report_counts_candidates_and_fills_per_tier(
    tier1: OvertureAttributeTier, raster: Path
) -> None:
    buildings = _buildings(height=[12.0, None, None], num_floors=[None, 4, None])
    areal = ArealRasterTier(name="ghsl", path=raster, confidence=0.3)

    _, report = fill_heights(buildings, [tier1, areal])

    overture, ghsl = report.tiers
    assert (overture.tier, overture.n_candidates, overture.n_filled) == ("overture", 3, 2)
    assert overture.filled_by_source == {OVERTURE_HEIGHT: 1, OVERTURE_NUM_FLOORS: 1}
    assert (ghsl.tier, ghsl.n_candidates, ghsl.n_filled) == ("ghsl", 1, 1)
    assert ghsl.filled_by_source == {"ghsl": 1}


def test_unresolved_buildings_are_tagged_not_dropped(tier1: OvertureAttributeTier) -> None:
    """With no areal product on disk the cascade is one tier long, and buildings Overture has no
    attributes for stay unresolved. That is reported, never raised — the package is meant to be
    honest about incompleteness, not to refuse to run because of it."""
    buildings = _buildings(height=[12.0, None], num_floors=[None, None])

    filled, report = fill_heights(buildings, [tier1])

    assert len(filled) == 2
    assert filled["height_source"].tolist() == [OVERTURE_HEIGHT, UNRESOLVED]
    assert np.isnan(filled["height"].iloc[1])
    assert np.isnan(filled["height_confidence"].iloc[1])
    assert report.n_resolved == 1
    assert report.n_unresolved == 1


def test_report_lists_every_tag_the_cascade_could_emit(
    tier1: OvertureAttributeTier, raster: Path
) -> None:
    """The per-unit fraction columns key off this, so it must reflect the configured cascade —
    not whichever tiers happened to fire on this city."""
    buildings = _buildings(height=[12.0], num_floors=[None])
    areal = ArealRasterTier(name="ghsl", path=raster, confidence=0.3)

    _, report = fill_heights(buildings, [tier1, areal])

    assert report.height_sources == [
        OVERTURE_HEIGHT,
        OVERTURE_NUM_FLOORS,
        "ghsl",
        UNRESOLVED,
    ]
    assert cascade_height_sources([tier1, areal]) == report.height_sources


def test_fill_heights_does_not_mutate_its_input(tier1: OvertureAttributeTier) -> None:
    buildings = _buildings(height=[None], num_floors=[4])

    fill_heights(buildings, [tier1])

    assert buildings["height"].isna().all()
    assert "height_source" not in buildings.columns


def test_an_empty_cascade_leaves_everything_unresolved() -> None:
    buildings = _buildings(height=[12.0], num_floors=[4])

    filled, report = fill_heights(buildings, [])

    assert filled["height_source"].tolist() == [UNRESOLVED]
    assert np.isnan(filled["height"].iloc[0])
    assert report.height_sources == [UNRESOLVED]


def test_an_empty_buildings_layer_produces_an_empty_result(
    tier1: OvertureAttributeTier,
) -> None:
    empty = _buildings(height=[], num_floors=[])

    filled, report = fill_heights(empty, [tier1])

    assert filled.empty
    assert {"height", "height_source", "height_confidence"} <= set(filled.columns)
    assert (report.n_buildings, report.n_resolved, report.n_unresolved) == (0, 0, 0)
