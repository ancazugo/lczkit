"""`transfer_parameters` — measuring on one unit set and classifying on another.

A street canyon has to be measured against streets and a grid cell is not bounded by any, so H/W —
3 of the 17 applied weight units, and the only dimension separating LCZ 8 from LCZ 3 and 6 — is
null on 10.8% of one Istanbul extent's built grid cells against 0.9% of its enclosures. These tests
pin the transfer, not that finding: the sixteen-city sweep is wired and has not been run, and
`UcpConfig.measure_on` defaults to `"units"` until it has.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely

from lczkit.ucp.measure import COVERAGE_COLUMN, transfer_parameters


def frame(**cells: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    out = gpd.GeoDataFrame(
        {"unit_id": list(cells)},
        geometry=gpd.GeoSeries([shapely.box(*box) for box in cells.values()], crs="EPSG:32633"),
    ).set_index("unit_id")
    return out


#: Two 50 m halves of one 100 m cell, so an area weight is exactly a half-and-half mean.
HALVES = frame(west=(0, 0, 50, 100), east=(50, 0, 100, 100))
CELL = frame(cell=(0, 0, 100, 100))


def params(**columns: list[float]) -> pd.DataFrame:
    out = pd.DataFrame(columns, index=HALVES.index)
    out.index.name = "unit_id"
    return out


def test_a_numeric_parameter_arrives_area_weighted() -> None:
    moved = transfer_parameters(params(building_surface_fraction=[0.2, 0.6]), HALVES, CELL)

    assert moved.loc["cell", "building_surface_fraction"] == pytest.approx(0.4)
    assert moved.loc["cell", COVERAGE_COLUMN] == pytest.approx(1.0)


def test_a_null_measurement_unit_does_not_drag_the_mean_towards_zero() -> None:
    """The whole reason this exists. An enclosure that never saw a street reports a null
    `aspect_ratio`, and a cell must take the mean of the enclosures that *did* have one rather than
    being pulled down by those that did not — which is what treating the null as a zero would do.
    """
    moved = transfer_parameters(params(aspect_ratio=[np.nan, 0.8]), HALVES, CELL)

    assert moved.loc["cell", "aspect_ratio"] == pytest.approx(0.8)


def test_a_categorical_parameter_arrives_by_majority() -> None:
    """There is no mean of `industrial_evidence`, and taking a majority of a surface fraction would
    throw away most of the cell — so the two kinds of column need the two different reducers."""
    table = params(building_surface_fraction=[0.2, 0.6])
    table["industrial_evidence"] = ["buildings", "land_use"]
    # East is the larger overlap once the cell is shifted, so its category should win.
    shifted = frame(cell=(40, 0, 140, 100))

    moved = transfer_parameters(table, HALVES, shifted)

    assert moved.loc["cell", "industrial_evidence"] == "land_use"
    # 10 m of west at 0.2 and 50 m of east at 0.6, over the 60 m the cell actually overlaps.
    assert moved.loc["cell", "building_surface_fraction"] == pytest.approx(3200 / 6000)


def test_a_target_unit_nothing_reaches_is_null_rather_than_zero() -> None:
    """The rule the rest of the package applies to an unobserved quantity: "no measurement here"
    and "measured as zero" are different statements and must not collapse."""
    targets = frame(covered=(0, 0, 100, 100), elsewhere=(1000, 1000, 1100, 1100))

    moved = transfer_parameters(params(building_surface_fraction=[0.2, 0.6]), HALVES, targets)

    assert pd.isna(moved.loc["elsewhere", "building_surface_fraction"])
    assert pd.isna(moved.loc["elsewhere", COVERAGE_COLUMN])


def test_partial_coverage_is_reported_rather_than_hidden() -> None:
    """A cell half outside the enclosure partition takes the mean of the half that was measured,
    which is right — and indistinguishable from a fully measured cell without this column."""
    wide = frame(cell=(0, 0, 200, 100))

    moved = transfer_parameters(params(building_surface_fraction=[0.2, 0.6]), HALVES, wide)

    assert moved.loc["cell", COVERAGE_COLUMN] == pytest.approx(0.5)
    assert moved.loc["cell", "building_surface_fraction"] == pytest.approx(0.4)


def test_the_column_order_and_index_survive_the_round_trip() -> None:
    """The classifier selects dimensions by name but the parameter table is also written to disk,
    where a reordered schema is a diff in every archived run for no reason."""
    table = params(building_surface_fraction=[0.2, 0.6], aspect_ratio=[0.4, 0.5])

    moved = transfer_parameters(table, HALVES, CELL)

    assert list(moved.columns) == [*table.columns, COVERAGE_COLUMN]
    assert moved.index.name == "unit_id"


def test_a_mismatched_index_is_refused_rather_than_silently_joined() -> None:
    """Passing the parameters of one unit set with the geometry of another would produce a
    plausible table describing nothing, which is exactly the failure this package keeps finding."""
    with pytest.raises(ValueError, match="share an index"):
        transfer_parameters(params(building_surface_fraction=[0.2, 0.6]), CELL, CELL)
