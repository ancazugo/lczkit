"""`building_metrics` against hand-built geometry with exact arithmetic.

Two 100 m cells side by side, so every expected number is computable by hand. The point of these
is the pair of assignment rules: area quantities split footprints at unit boundaries, object
quantities move whole buildings to the unit holding their representative point. A test that only
used buildings sitting wholly inside one unit would pass under either rule and prove nothing.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box

from lczkit.config import UcpConfig
from lczkit.ucp.buildings import building_metrics

CRS = "EPSG:32633"
CONFIG = UcpConfig()

#: Two adjacent 100 x 100 m cells, so unit area is 10 000 m2 and a fraction reads off directly.
LEFT = (0.0, 0.0, 100.0, 100.0)
RIGHT = (100.0, 0.0, 200.0, 100.0)


def make_units() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"unit_id": ["left", "right"]}, geometry=[box(*LEFT), box(*RIGHT)], crs=CRS
    ).set_index("unit_id")


def make_buildings(*specs: tuple[tuple[float, float, float, float], float]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"height": [height for _, height in specs]},
        geometry=[box(*bounds) for bounds, _ in specs],
        crs=CRS,
    )


def test_a_footprint_covering_half_a_unit_gives_half_the_surface_fraction() -> None:
    result = building_metrics(make_buildings(((0, 0, 50, 100), 10.0)), make_units(), CONFIG)

    assert result.loc["left", "building_surface_fraction"] == pytest.approx(0.5)
    assert result.loc["right", "building_surface_fraction"] == 0.0


def test_a_footprint_straddling_two_units_splits_its_area_but_not_itself() -> None:
    """The whole reason for two assignment rules. A 6000 m2 footprint with 2000 m2 on the left and
    4000 m2 on the right is 0.2 and 0.4 of the two cells' cover — but it is *one* building, and it
    is one building in the cell holding its representative point, not half a building in each.
    """
    result = building_metrics(make_buildings(((80, 0, 140, 100), 12.0)), make_units(), CONFIG)

    assert result["building_surface_fraction"].to_list() == pytest.approx([0.2, 0.4])
    assert result["building_count"].to_list() == [0, 1]
    assert result.loc["right", "mean_building_area_m2"] == pytest.approx(6000.0)
    assert np.isnan(result.loc["left", "mean_building_area_m2"])


def test_hr_is_the_geometric_mean_not_the_area_weighted_one() -> None:
    """A 9000 m2 building at 10 m and a 1000 m2 building at 30 m. Three different answers:

    - `Hr`, the unweighted geometric mean, is sqrt(10 x 30) = 17.32 m
    - `h_mean_area_weighted` is (9000x10 + 1000x30) / 10000 = 12 m
    - the plain arithmetic mean, which nothing emits, would be 20 m

    Stewart & Oke's ranges were defined for the geometric mean, so `Hr` is the one Phase 6
    classifies on. This scene exists to make substituting one for the other impossible to miss.
    """
    buildings = make_buildings(((0, 0, 90, 100), 10.0), ((90, 0, 100, 100), 30.0))

    result = building_metrics(buildings, make_units(), CONFIG)

    assert result.loc["left", "height_of_roughness_elements_m"] == pytest.approx(np.sqrt(300.0))
    assert result.loc["left", "h_mean_area_weighted"] == pytest.approx(12.0)
    # Weighted variance is E[h^2] - E[h]^2 = 180 - 144 = 36, so the spread is exactly 6 m.
    assert result.loc["left", "h_std"] == pytest.approx(6.0)


def test_hr_ignores_footprint_size_entirely() -> None:
    """Two buildings of wildly different size at the same pair of heights give the same `Hr` as
    two equal ones — the geometric mean is unweighted. `h_mean_area_weighted` moves a long way."""
    lopsided = make_buildings(((0, 0, 99, 100), 8.0), ((99, 0, 100, 100), 32.0))
    balanced = make_buildings(((0, 0, 50, 100), 8.0), ((50, 0, 100, 100), 32.0))

    left = building_metrics(lopsided, make_units(), CONFIG).loc["left"]
    right = building_metrics(balanced, make_units(), CONFIG).loc["left"]

    assert left["height_of_roughness_elements_m"] == pytest.approx(16.0)
    assert right["height_of_roughness_elements_m"] == pytest.approx(16.0)
    assert left["h_mean_area_weighted"] == pytest.approx(8.24)
    assert right["h_mean_area_weighted"] == pytest.approx(20.0)


def test_a_zero_height_building_is_floored_rather_than_annihilating_the_unit() -> None:
    """`log(0)` is negative infinity, and one bad Overture row would otherwise take a whole unit's
    `Hr` to zero. The floor is the height such a building is counted as, so it is config."""
    buildings = make_buildings(((0, 0, 50, 100), 0.0), ((50, 0, 100, 100), 20.0))

    result = building_metrics(buildings, make_units(), CONFIG)

    expected = np.exp((np.log(CONFIG.min_building_height_m) + np.log(20.0)) / 2)
    assert result.loc["left", "height_of_roughness_elements_m"] == pytest.approx(expected)
    assert result.loc["left", "height_of_roughness_elements_m"] > 0.0


def test_a_unit_holding_one_building_has_zero_height_spread() -> None:
    """Zero rather than null: an area-weighted standard deviation has no sample correction, and
    "one building, so no variation" is a measurement rather than an absence."""
    result = building_metrics(make_buildings(((10, 10, 90, 90), 15.0)), make_units(), CONFIG)

    assert result.loc["left", "h_std"] == 0.0
    assert result.loc["left", "height_of_roughness_elements_m"] == pytest.approx(15.0)


def test_a_building_straddling_a_boundary_enters_both_units_geometric_means() -> None:
    """`Hr` is unweighted, so it needs a rule for a building the boundary cuts. Counting it once
    per unit it touches keeps `Hr` defined wherever there is building area — assigning it to a
    single unit would leave it null in cells that are visibly built."""
    buildings = make_buildings(((80, 0, 140, 100), 12.0), ((0, 0, 40, 100), 3.0))

    result = building_metrics(buildings, make_units(), CONFIG)

    assert result.loc["left", "height_of_roughness_elements_m"] == pytest.approx(6.0)
    assert result.loc["right", "height_of_roughness_elements_m"] == pytest.approx(12.0)
    assert result.loc["right", "building_surface_fraction"] > 0.0


def test_an_unresolved_height_counts_for_area_but_not_for_the_moments() -> None:
    """Phase 3 leaves a building `unresolved` with a null height rather than inventing one. The
    footprint is still observed, so it counts towards cover and count; imputing it into the mean
    height would be exactly the invented number the cascade refused to make."""
    buildings = make_buildings(((0, 0, 50, 100), np.nan), ((50, 0, 100, 100), 20.0))

    result = building_metrics(buildings, make_units(), CONFIG)

    assert result.loc["left", "building_surface_fraction"] == pytest.approx(1.0)
    assert result.loc["left", "building_count"] == 2
    assert result.loc["left", "mean_building_area_m2"] == pytest.approx(5000.0)
    assert result.loc["left", "height_of_roughness_elements_m"] == pytest.approx(20.0)


def test_a_unit_with_no_buildings_reports_zero_cover_and_no_mean() -> None:
    """The two halves of the empty case say different things. Zero cover and zero buildings are
    real measurements of the unit; the mean height and mean footprint area of nothing are not.
    Collapsing both to null would misreport every park as a data gap, and collapsing both to zero
    would put a park at 0 m building height, which is a value the classifier would believe.
    """
    result = building_metrics(make_buildings(((0, 0, 50, 100), 10.0)), make_units(), CONFIG)

    assert result.loc["right", "building_surface_fraction"] == 0.0
    assert result.loc["right", "building_count"] == 0
    assert np.isnan(result.loc["right", "height_of_roughness_elements_m"])
    assert np.isnan(result.loc["right", "h_mean_area_weighted"])
    assert np.isnan(result.loc["right", "h_std"])
    assert np.isnan(result.loc["right", "mean_building_area_m2"])


def test_an_empty_buildings_layer_uses_the_same_conventions() -> None:
    empty = gpd.GeoDataFrame({"height": []}, geometry=[], crs=CRS)

    result = building_metrics(empty, make_units(), CONFIG)

    assert result["building_surface_fraction"].to_list() == [0.0, 0.0]
    assert result["building_count"].to_list() == [0, 0]
    assert result["height_of_roughness_elements_m"].isna().all()


def test_buildings_entirely_outside_every_unit_are_ignored() -> None:
    result = building_metrics(make_buildings(((500, 500, 600, 600), 10.0)), make_units(), CONFIG)

    assert result["building_surface_fraction"].to_list() == [0.0, 0.0]
    assert result["building_count"].to_list() == [0, 0]


def test_a_geographic_crs_is_refused() -> None:
    units = make_units().to_crs("EPSG:4326")

    with pytest.raises(ValueError, match="projected"):
        building_metrics(make_buildings(((0, 0, 50, 100), 10.0)), units, CONFIG)


def test_units_must_be_indexed_by_unit_id() -> None:
    units = make_units().reset_index()

    with pytest.raises(ValueError, match="unit_id"):
        building_metrics(make_buildings(((0, 0, 50, 100), 10.0)), units, CONFIG)


def test_a_crs_mismatch_is_refused() -> None:
    buildings = make_buildings(((0, 0, 50, 100), 10.0)).to_crs("EPSG:32634")

    with pytest.raises(ValueError, match="buildings.crs"):
        building_metrics(buildings, make_units(), CONFIG)


def test_buildings_that_never_went_through_the_cascade_are_refused() -> None:
    buildings = make_buildings(((0, 0, 50, 100), 10.0)).drop(columns=["height"])

    with pytest.raises(ValueError, match="fill_heights"):
        building_metrics(buildings, make_units(), CONFIG)
