"""Tests for the per-unit height provenance table."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from lczkit.heights.cascade import UNRESOLVED
from lczkit.heights.completeness import height_metrics
from lczkit.heights.tiers import OVERTURE_HEIGHT, OVERTURE_NUM_FLOORS

CRS = "EPSG:32633"
SOURCES = [OVERTURE_HEIGHT, OVERTURE_NUM_FLOORS, "ghsl", UNRESOLVED]
FRACTION_COLUMNS = [f"height_frac_{source}" for source in SOURCES]


def _units(*geoms: object) -> gpd.GeoDataFrame:
    ids = [f"unit_{i}" for i in range(len(geoms))]
    return gpd.GeoDataFrame({"unit_id": ids}, geometry=list(geoms), crs=CRS).set_index("unit_id")


def _buildings(pairs: list[tuple[object, str]]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"height_source": [source for _, source in pairs]},
        geometry=[geom for geom, _ in pairs],
        crs=CRS,
    )


def test_fractions_sum_to_one_and_completeness_is_the_tier1_share() -> None:
    units = _units(box(0, 0, 100, 100))
    buildings = _buildings(
        [
            (box(10, 10, 30, 30), OVERTURE_HEIGHT),  # area 400
            (box(40, 10, 60, 30), OVERTURE_NUM_FLOORS),  # area 400
            (box(70, 10, 90, 30), "ghsl"),  # area 400
            (box(10, 40, 30, 60), UNRESOLVED),  # area 400
        ]
    )

    metrics = height_metrics(buildings, units, SOURCES)

    assert list(metrics.columns) == ["height_completeness", *FRACTION_COLUMNS]
    assert metrics[FRACTION_COLUMNS].sum(axis=1).iloc[0] == pytest.approx(1.0)
    assert metrics.loc["unit_0", FRACTION_COLUMNS].tolist() == pytest.approx([0.25] * 4)
    assert metrics.loc["unit_0", "height_completeness"] == pytest.approx(0.5)


def test_weighting_is_by_footprint_area_not_building_count() -> None:
    units = _units(box(0, 0, 100, 100))
    buildings = _buildings(
        [
            (box(0, 0, 90, 90), "ghsl"),  # area 8100
            (box(90, 90, 100, 100), OVERTURE_HEIGHT),  # area 100
        ]
    )

    metrics = height_metrics(buildings, units, SOURCES)

    assert metrics.loc["unit_0", "height_completeness"] == pytest.approx(0.0122, abs=1e-4)


def test_a_building_straddling_two_units_splits_by_area() -> None:
    """A 100 m grid cuts through buildings constantly, so the split has to be proportional
    rather than assigning each footprint wholesale to one cell."""
    units = _units(box(0, 0, 100, 100), box(100, 0, 200, 100))
    buildings = _buildings(
        [
            # 75 m^2 in unit_0, 25 m^2 in unit_1
            (box(75, 10, 125, 20), OVERTURE_HEIGHT),
            (box(130, 10, 180, 20), "ghsl"),
        ]
    )

    metrics = height_metrics(buildings, units, SOURCES)

    assert metrics.loc["unit_0", "height_completeness"] == pytest.approx(1.0)
    # unit_1 holds 250 m^2 of tier-1 footprint against 500 m^2 of ghsl footprint
    assert metrics.loc["unit_1", "height_completeness"] == pytest.approx(250 / 750)


def test_a_unit_with_no_buildings_is_null_not_zero() -> None:
    """ "No buildings here" and "0% tier-1 coverage" are different statements. Collapsing them
    would report every park and water body as a height-data failure."""
    units = _units(box(0, 0, 100, 100), box(1000, 1000, 1100, 1100))
    buildings = _buildings([(box(10, 10, 30, 30), OVERTURE_HEIGHT)])

    metrics = height_metrics(buildings, units, SOURCES)

    assert metrics.loc["unit_0", "height_completeness"] == pytest.approx(1.0)
    assert metrics.loc["unit_1"].isna().all()


def test_the_column_set_comes_from_the_cascade_not_the_data() -> None:
    """Phases 6 and 7 need a stable schema: a city where one tier never fires must still
    produce that tier's column, holding zero."""
    units = _units(box(0, 0, 100, 100))
    buildings = _buildings([(box(10, 10, 30, 30), OVERTURE_HEIGHT)])

    metrics = height_metrics(buildings, units, SOURCES)

    assert list(metrics.columns) == ["height_completeness", *FRACTION_COLUMNS]
    assert metrics.loc["unit_0", "height_frac_ghsl"] == 0.0


def test_an_empty_buildings_layer_gives_null_metrics_for_every_unit() -> None:
    units = _units(box(0, 0, 100, 100))
    empty = _buildings([])

    metrics = height_metrics(empty, units, SOURCES)

    assert list(metrics.columns) == ["height_completeness", *FRACTION_COLUMNS]
    assert metrics.isna().all().all()
    assert metrics.index.equals(units.index)


def test_units_must_be_indexed_by_unit_id() -> None:
    units = _units(box(0, 0, 100, 100)).reset_index()
    buildings = _buildings([(box(10, 10, 30, 30), OVERTURE_HEIGHT)])

    with pytest.raises(ValueError, match="unit_id"):
        height_metrics(buildings, units, SOURCES)


def test_mismatched_crs_raises() -> None:
    units = _units(box(0, 0, 100, 100))
    buildings = _buildings([(box(10, 10, 30, 30), OVERTURE_HEIGHT)]).to_crs("EPSG:32634")

    with pytest.raises(ValueError, match="crs"):
        height_metrics(buildings, units, SOURCES)


def test_buildings_without_a_height_source_column_raise() -> None:
    units = _units(box(0, 0, 100, 100))
    buildings = gpd.GeoDataFrame(geometry=[box(10, 10, 30, 30)], crs=CRS)

    with pytest.raises(ValueError, match="fill_heights"):
        height_metrics(buildings, units, SOURCES)


def test_result_is_a_plain_frame_indexed_to_match_the_units() -> None:
    units = _units(box(0, 0, 100, 100), box(100, 0, 200, 100))
    buildings = _buildings([(box(10, 10, 30, 30), OVERTURE_HEIGHT)])

    metrics = height_metrics(buildings, units, SOURCES)

    assert isinstance(metrics, pd.DataFrame)
    assert metrics.index.name == "unit_id"
    assert metrics.index.equals(units.index)
    assert np.isfinite(metrics.loc["unit_0", "height_completeness"])
