"""`industrial_metrics` — the union rule and the evidence record.

This is the only functional attribute in the parameter table, and the only route to LCZ 10. The
Berlin fixture holds 36 industrial buildings out of 6195 and 2 industrial land-use parcels out of
1559, which exercises the plumbing but cannot exercise the rule; these hand-built scenes do.
"""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import box

from lczkit.config import UcpConfig
from lczkit.ucp.industrial import industrial_metrics

CRS = "EPSG:32633"
CONFIG = UcpConfig()

#: Four 100 x 100 m cells in a row, so unit area is 10 000 m2 and a fraction reads off directly.
UNIT_IDS = ("both", "buildings", "land_use", "none")


def make_units() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"unit_id": list(UNIT_IDS)},
        geometry=[box(100 * i, 0, 100 * (i + 1), 100) for i in range(4)],
        crs=CRS,
    ).set_index("unit_id")


def layer(*specs: tuple[tuple[float, float, float, float], str, str]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "subtype": [subtype for _, subtype, _ in specs],
            "class": [klass for _, _, klass in specs],
        },
        geometry=[box(*bounds) for bounds, _, _ in specs],
        crs=CRS,
    )


def scene() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """An industrial building inside an industrial parcel, then each source alone, then neither."""
    buildings = layer(
        ((0, 0, 50, 50), "industrial", "industrial"),  # 2500 m2, inside the parcel below
        ((100, 0, 150, 50), "industrial", "industrial"),  # 2500 m2, no parcel
        ((300, 0, 380, 80), "residential", "apartments"),  # not industrial at all
    )
    land_use = layer(
        ((0, 0, 100, 50), "developed", "industrial"),  # 5000 m2, contains the first building
        ((200, 0, 250, 50), "developed", "industrial"),  # 2500 m2, no building
        ((300, 0, 400, 100), "managed", "grass"),  # not industrial at all
    )
    return buildings, land_use


def test_a_building_inside_a_parcel_is_counted_once() -> None:
    """The whole point of the union rule. Summing the two sources would give 0.25 + 0.50 = 0.75 for
    a unit that is half industrial; dissolving them first gives 0.50."""
    buildings, land_use = scene()

    result = industrial_metrics(buildings, land_use, make_units(), CONFIG)

    assert result.loc["both", "industrial_fraction_buildings"] == pytest.approx(0.25)
    assert result.loc["both", "industrial_fraction_land_use"] == pytest.approx(0.50)
    assert result.loc["both", "industrial_fraction"] == pytest.approx(0.50)


def test_each_source_alone_carries_its_own_area() -> None:
    buildings, land_use = scene()

    result = industrial_metrics(buildings, land_use, make_units(), CONFIG)

    assert result.loc["buildings", "industrial_fraction"] == pytest.approx(0.25)
    assert result.loc["buildings", "industrial_fraction_land_use"] == 0.0
    assert result.loc["land_use", "industrial_fraction"] == pytest.approx(0.25)
    assert result.loc["land_use", "industrial_fraction_buildings"] == 0.0


def test_the_evidence_column_names_which_sources_contributed() -> None:
    buildings, land_use = scene()

    result = industrial_metrics(buildings, land_use, make_units(), CONFIG)

    assert list(result["industrial_evidence"]) == list(UNIT_IDS)


def test_evidence_is_a_fixed_category_set_whatever_the_city_holds() -> None:
    """A city with no industry must still produce the same four categories, so the output schema
    does not depend on which evidence happened to be present."""
    buildings, land_use = scene()

    result = industrial_metrics(buildings, land_use, make_units(), CONFIG)

    assert list(result["industrial_evidence"].cat.categories) == [
        "none",
        "buildings",
        "land_use",
        "both",
    ]


def test_a_unit_with_nothing_industrial_is_zero_not_null() -> None:
    """Unlike a land-cover fraction, which can be genuinely unobserved, "no industrial feature
    covers this unit" is a measurement. Phase 6 thresholds on this value and a null would make
    every non-industrial unit unclassifiable."""
    buildings, land_use = scene()

    result = industrial_metrics(buildings, land_use, make_units(), CONFIG)

    assert result.loc["none", "industrial_fraction"] == 0.0
    assert result.loc["none", "industrial_evidence"] == "none"
    assert result.notna().to_numpy().all()


def test_a_warehouse_is_not_industrial() -> None:
    """CLAUDE.md's own statement of the problem: a distribution warehouse and a refinery are
    geometrically identical, the warehouse being LCZ 8 and the refinery LCZ 10. Counting warehouses
    as industrial would push exactly the units this rule exists to separate towards LCZ 10."""
    buildings = layer(((0, 0, 100, 100), "commercial", "warehouse"))
    empty = layer()

    result = industrial_metrics(buildings, empty, make_units(), CONFIG)

    assert result["industrial_fraction"].to_list() == [0.0, 0.0, 0.0, 0.0]


def test_either_attribute_alone_is_enough() -> None:
    """Overture's `subtype` and `class` are independently nullable, and a feature carrying only one
    of them is still industrial."""
    buildings = layer(
        ((0, 0, 50, 50), "industrial", "office"),
        ((100, 0, 150, 50), "commercial", "industrial"),
    )
    empty = layer()

    result = industrial_metrics(buildings, empty, make_units(), CONFIG)

    assert result["industrial_fraction"].to_list() == pytest.approx([0.25, 0.25, 0.0, 0.0])


def test_empty_layers_give_a_table_of_zeros() -> None:
    empty = gpd.GeoDataFrame({"subtype": [], "class": []}, geometry=[], crs=CRS)

    result = industrial_metrics(empty, empty, make_units(), CONFIG)

    assert result["industrial_fraction"].to_list() == [0.0] * 4
    assert set(result["industrial_evidence"]) == {"none"}


@pytest.mark.parametrize("side", ["buildings", "land_use"])
def test_one_empty_layer_still_lets_the_other_contribute(side: str) -> None:
    """An empty layer arrives with no CRS of its own, so the union has to take its CRS from the
    units rather than from whichever input happened to be non-empty."""
    empty = gpd.GeoDataFrame({"subtype": [], "class": []}, geometry=[])
    present = layer(((0, 0, 50, 50), "industrial", "industrial"))
    buildings, land_use = (empty, present) if side == "land_use" else (present, empty)

    result = industrial_metrics(buildings, land_use, make_units(), CONFIG)

    assert result.loc["both", "industrial_fraction"] == pytest.approx(0.25)
    assert result.loc["both", "industrial_evidence"] == side


def test_land_use_selection_can_be_switched_off_entirely() -> None:
    """`industrial_land_use_subtypes` is empty by default — Overture files industrial parcels under
    `subtype='developed'`, which also covers commercial and retail — so an empty selector must be a
    no-op rather than an error."""
    buildings, land_use = scene()
    config = CONFIG.model_copy(update={"industrial_land_use_classes": []})

    result = industrial_metrics(buildings, land_use, make_units(), config)

    assert result["industrial_fraction_land_use"].to_list() == [0.0] * 4
    assert result.loc["both", "industrial_fraction"] == pytest.approx(0.25)


def test_a_layer_missing_the_attribute_the_config_selects_on_is_refused() -> None:
    """Phase 1 must retain `subtype` and `class` through cleaning — CLAUDE.md says `class` is the
    only route to LCZ 10. Losing it should be loud, not a table of zeros."""
    buildings, land_use = scene()

    with pytest.raises(ValueError, match="Phase 1 cleaning"):
        industrial_metrics(buildings.drop(columns=["class"]), land_use, make_units(), CONFIG)


def test_the_units_entry_contract_is_enforced() -> None:
    buildings, land_use = scene()

    with pytest.raises(ValueError, match="unit_id"):
        industrial_metrics(buildings, land_use, make_units().reset_index(), CONFIG)
    with pytest.raises(ValueError, match="buildings.crs"):
        industrial_metrics(buildings.to_crs("EPSG:32634"), land_use, make_units(), CONFIG)
