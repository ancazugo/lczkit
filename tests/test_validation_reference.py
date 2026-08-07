"""Reducing a reference LCZ raster to one label per unit.

The reduction reuses `LocalRasterSource`, so what needs testing here is not the zonal machinery —
Phase 4 covers that — but the three things layered on top: that the majority is the areal majority,
that coverage is measured rather than assumed, and that "the reference does not reach here" never
looks like a class.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from conftest import LCZ_FIXTURES_DIR, write_class_raster
from shapely.geometry import box

from lczkit.config import ValidationConfig
from lczkit.units.grid import GridUnits
from lczkit.validation import reference_lcz

CRS = "EPSG:32633"
CONFIG = ValidationConfig().reference

#: Two 100 m cells side by side, so a cell holds exactly 100 of the 10 m raster cells below.
LEFT = (0.0, 0.0, 100.0, 100.0)
RIGHT = (100.0, 0.0, 200.0, 100.0)


def make_units() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"unit_id": ["left", "right"]}, geometry=[box(*LEFT), box(*RIGHT)], crs=CRS
    ).set_index("unit_id")


def make_raster(path: Path, values: np.ndarray) -> Path:
    """A 10 m raster whose top-left corner is (0, 100) — i.e. covering the two cells above."""
    return write_class_raster(path, values, origin=(0.0, 100.0), cell_size_m=10.0, crs=CRS)


def test_the_majority_class_wins_and_its_support_is_reported(tmp_path: Path) -> None:
    """60% LCZ 2 against 40% LCZ 5 in the left cell. A unit split this way agrees with whichever
    map it is compared against about half the time, and that is worth knowing before reading a
    confusion matrix."""
    values = np.full((10, 20), 5, dtype="uint8")
    values[:6, :10] = 2

    result = reference_lcz(make_units(), make_raster(tmp_path / "r.tif", values), CONFIG)

    assert result.loc["left", "reference_lcz"] == 2
    assert result.loc["left", "reference_majority_fraction"] == pytest.approx(0.6)
    assert result.loc["right", "reference_lcz"] == 5
    assert result.loc["right", "reference_majority_fraction"] == pytest.approx(1.0)


def test_coverage_measures_how_much_of_the_unit_the_reference_reached(tmp_path: Path) -> None:
    """Nodata is assigned to its own class rather than excluded, precisely so this number exists.
    Excluding it would renormalise over the covered cells and lose it."""
    values = np.full((10, 20), 2, dtype="uint8")
    values[:, :5] = 0  # the reference map's own nodata

    result = reference_lcz(make_units(), make_raster(tmp_path / "r.tif", values), CONFIG)

    assert result.loc["left", "reference_coverage"] == pytest.approx(0.5)
    assert result.loc["right", "reference_coverage"] == pytest.approx(1.0)
    # The majority is over the observed part, so a half-covered unit still reports its class.
    assert result.loc["left", "reference_lcz"] == 2
    assert result.loc["left", "reference_majority_fraction"] == pytest.approx(1.0)


def test_a_unit_the_reference_never_reaches_is_null_not_zero(tmp_path: Path) -> None:
    """Nodata is 0 in this product, and 0 is not a class. Collapsing the two would put "bare rock"
    or nothing at all across every unit outside the map's extent."""
    values = np.zeros((10, 20), dtype="uint8")

    result = reference_lcz(make_units(), make_raster(tmp_path / "r.tif", values), CONFIG)

    assert result["reference_lcz"].isna().all()
    assert result["reference_coverage"].to_list() == pytest.approx([0.0, 0.0])


def test_units_outside_the_raster_entirely_come_back_null(tmp_path: Path) -> None:
    values = np.full((10, 10), 2, dtype="uint8")
    raster = write_class_raster(
        tmp_path / "r.tif", values, origin=(10_000.0, 10_100.0), cell_size_m=10.0, crs=CRS
    )

    result = reference_lcz(make_units(), raster, CONFIG)

    assert result["reference_lcz"].isna().all()


def test_a_config_that_discards_nodata_is_refused(tmp_path: Path) -> None:
    """Without a nodata class there is no way to know how much of a unit was observed, and the
    agreement statistics would silently include units the reference barely touches."""
    excluding = CONFIG.model_copy(
        update={"nodata_policy": "exclude", "nodata_class": None, "classes": CONFIG.classes[:-1]}
    )
    values = np.full((10, 20), 2, dtype="uint8")

    with pytest.raises(ValueError, match="nodata"):
        reference_lcz(make_units(), make_raster(tmp_path / "r.tif", values), excluding)


def test_the_committed_berlin_fixture_reduces_onto_the_100_m_grid() -> None:
    """The real reference map against the real grid — CLAUDE.md compares on the 100 m grid, and
    the reference is itself a ~100 m product in EPSG:4326, so the two never align exactly. What
    matters is that every cell gets a well-supported label rather than a coin toss."""
    units = GridUnits().generate((13.3900, 52.5150, 13.4000, 52.5220))

    result = reference_lcz(units, LCZ_FIXTURES_DIR / "lcz_reference_berlin.tif", CONFIG)

    assert result.index.equals(units.index)
    assert result["reference_lcz"].notna().all()
    assert result["reference_coverage"].min() > 0.99
    assert result["reference_majority_fraction"].median() > 0.5
    assert set(result["reference_lcz"].dropna()) <= set(range(1, 18))
