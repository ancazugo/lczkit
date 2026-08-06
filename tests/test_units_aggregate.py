"""Tests for `aggregate()` — hand-built unit systems with known overlap areas so the exact
expected weighted mean / majority pick can be asserted."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from lczkit.units.aggregate import aggregate

_CRS = "EPSG:32633"


def _units(ids: list[str], geoms: list, **cols: list) -> gpd.GeoDataFrame:
    data = {**cols, "geometry": geoms}
    return gpd.GeoDataFrame(data, index=pd.Index(ids, name="unit_id"), crs=_CRS)


def test_area_weighted_mean_of_two_equal_area_sources() -> None:
    from_units = _units(
        ["f1", "f2"], [box(0, 0, 100, 100), box(100, 0, 200, 100)], value=[10.0, 20.0]
    )
    to_units = _units(["t1"], [box(0, 0, 200, 100)])

    result = aggregate(from_units, to_units, "area_weighted")

    assert result.loc["t1", "value"] == pytest.approx(15.0)
    assert result.index.name == "unit_id"


def test_area_weighted_mean_is_weighted_by_overlap_not_count() -> None:
    # f1 covers 3/4 of the target, f2 covers 1/4 -> weighted mean is 10*0.75 + 30*0.25 = 15
    from_units = _units(
        ["f1", "f2"], [box(0, 0, 150, 100), box(150, 0, 200, 100)], value=[10.0, 30.0]
    )
    to_units = _units(["t1"], [box(0, 0, 200, 100)])

    result = aggregate(from_units, to_units, "area_weighted")

    assert result.loc["t1", "value"] == pytest.approx(15.0)


def test_majority_picks_largest_overlap() -> None:
    from_units = _units(
        ["f1", "f2"],
        [box(0, 0, 150, 100), box(150, 0, 200, 100)],
        label=["big", "small"],
    )
    to_units = _units(["t1"], [box(0, 0, 200, 100)])

    result = aggregate(from_units, to_units, "majority")

    assert result.loc["t1", "label"] == "big"


def test_majority_works_per_target_unit_independently() -> None:
    from_units = _units(
        ["f1", "f2"], [box(0, 0, 100, 100), box(100, 0, 200, 100)], label=["a", "b"]
    )
    to_units = _units(["t1", "t2"], [box(0, 0, 100, 100), box(100, 0, 200, 100)])

    result = aggregate(from_units, to_units, "majority")

    assert result.loc["t1", "label"] == "a"
    assert result.loc["t2", "label"] == "b"


def test_area_weighted_drops_non_numeric_columns() -> None:
    from_units = _units(["f1"], [box(0, 0, 100, 100)], value=[10.0], label=["a"])
    to_units = _units(["t1"], [box(0, 0, 100, 100)])

    result = aggregate(from_units, to_units, "area_weighted")

    assert "value" in result.columns
    assert "label" not in result.columns


def test_target_unit_with_no_overlap_gets_null() -> None:
    from_units = _units(["f1"], [box(0, 0, 100, 100)], value=[10.0])
    to_units = _units(["t1", "t2"], [box(0, 0, 100, 100), box(1000, 1000, 1100, 1100)])

    result = aggregate(from_units, to_units, "area_weighted")

    assert result.loc["t1", "value"] == pytest.approx(10.0)
    assert pd.isna(result.loc["t2", "value"])


def test_unknown_method_raises() -> None:
    from_units = _units(["f1"], [box(0, 0, 100, 100)], value=[10.0])
    to_units = _units(["t1"], [box(0, 0, 100, 100)])

    with pytest.raises(ValueError, match="method"):
        aggregate(from_units, to_units, "bogus")  # type: ignore[arg-type]


def test_requires_unit_id_index() -> None:
    from_units = gpd.GeoDataFrame({"value": [1.0]}, geometry=[box(0, 0, 1, 1)], crs=_CRS)
    to_units = _units(["t1"], [box(0, 0, 1, 1)])

    with pytest.raises(ValueError, match="unit_id"):
        aggregate(from_units, to_units, "area_weighted")


def test_mismatched_crs_raises() -> None:
    from_units = _units(["f1"], [box(0, 0, 100, 100)], value=[1.0])
    to_units = gpd.GeoDataFrame(
        {"geometry": [box(0, 0, 100, 100)]},
        index=pd.Index(["t1"], name="unit_id"),
        crs="EPSG:32634",
    )

    with pytest.raises(ValueError, match="crs"):
        aggregate(from_units, to_units, "area_weighted")
