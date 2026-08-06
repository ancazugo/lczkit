"""`street_metrics` against hand-built scenes.

`momepy.street_profile()` is momepy's algorithm, not this package's, so these do not assert its
numbers. What they assert is the part written here: the length-weighted move from per-segment to
per-unit, and the conventions around segments that reach no building. Expected values are read
back out of momepy's own output and recombined by hand, so a change in momepy's measurement
changes both sides of the assertion and the weighting stays under test.
"""

from __future__ import annotations

import geopandas as gpd
import momepy
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, box

from lczkit.config import UcpConfig
from lczkit.ucp.streets import street_metrics

CRS = "EPSG:32633"
CONFIG = UcpConfig()


def make_units(*bounds: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"unit_id": [f"u{i}" for i in range(len(bounds))]},
        geometry=[box(*b) for b in bounds],
        crs=CRS,
    ).set_index("unit_id")


def make_streets(*lines: list[tuple[float, float]]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=[LineString(line) for line in lines], crs=CRS)


def flanking(
    y: float, x0: float, x1: float, height: float, *, setback: float = 5.0, depth: float = 15.0
) -> list[tuple[tuple[float, float, float, float], float]]:
    """A pair of buildings facing each other across a street running along `y`.

    Both sit inside the default 50 m tick length, so momepy's ticks reach them and the segment
    gets a real width, openness and height-to-width ratio rather than the open-street defaults.
    """
    return [
        ((x0, y + setback, x1, y + setback + depth), height),
        ((x0, y - setback - depth, x1, y - setback), height),
    ]


def make_buildings(
    *specs: tuple[tuple[float, float, float, float], float],
) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"height": [height for _, height in specs]},
        geometry=[box(*bounds) for bounds, _ in specs],
        crs=CRS,
    )


def profile_of(streets: gpd.GeoDataFrame, buildings: gpd.GeoDataFrame) -> pd.DataFrame:
    """momepy's own per-segment answer, for tests that recombine it by hand."""
    return momepy.street_profile(
        streets,
        buildings,
        distance=CONFIG.street_profile_distance_m,
        tick_length=CONFIG.street_profile_tick_length_m,
        height=buildings["height"],
    )


def test_a_segment_wholly_inside_one_unit_hands_that_unit_its_own_value() -> None:
    units = make_units((0, 0, 200, 200), (200, 0, 400, 200))
    streets = make_streets([(20, 100), (180, 100)], [(220, 100), (380, 100)])
    buildings = make_buildings(
        *flanking(100, 20, 180, 30.0),
        *flanking(100, 220, 380, 6.0),
    )
    profile = profile_of(streets, buildings)

    result = street_metrics(streets, buildings, units, CONFIG)

    assert result.loc["u0", "aspect_ratio"] == pytest.approx(profile.loc[0, "hw_ratio"])
    assert result.loc["u1", "aspect_ratio"] == pytest.approx(profile.loc[1, "hw_ratio"])
    assert result.loc["u0", "street_width_m"] == pytest.approx(profile.loc[0, "width"])
    # The scene is built so the two differ; otherwise the assertion above would hold under any
    # aggregation, including one that ignored the unit boundary entirely.
    assert result.loc["u0", "aspect_ratio"] > result.loc["u1", "aspect_ratio"]


def test_two_segments_in_one_unit_combine_by_street_length() -> None:
    """100 m of tall canyon and 280 m of low canyon in the same unit. An unweighted mean would sit
    halfway between the two; the answer has to sit nearer the longer one."""
    units = make_units((0, 0, 400, 400))
    streets = make_streets([(10, 50), (110, 50)], [(10, 350), (290, 350)])
    buildings = make_buildings(*flanking(50, 10, 110, 30.0), *flanking(350, 10, 290, 6.0))
    profile = profile_of(streets, buildings)
    expected = (100 * profile.loc[0, "hw_ratio"] + 280 * profile.loc[1, "hw_ratio"]) / 380

    result = street_metrics(streets, buildings, units, CONFIG)

    assert result.loc["u0", "aspect_ratio"] == pytest.approx(expected)
    unweighted = profile["hw_ratio"].mean()
    assert result.loc["u0", "aspect_ratio"] != pytest.approx(unweighted)


def test_a_segment_crossing_a_boundary_reaches_both_units_with_its_own_value() -> None:
    """A weighted mean of one value is that value, however the segment is cut. This is what makes
    `EnclosureUnits` work: a street lies on the shared edge of the two enclosures it bounds, and
    both sides of the canyon get the same measurement."""
    units = make_units((0, 0, 200, 200), (200, 0, 400, 200))
    streets = make_streets([(20, 100), (380, 100)])
    buildings = make_buildings(*flanking(100, 20, 380, 24.0))
    profile = profile_of(streets, buildings)

    result = street_metrics(streets, buildings, units, CONFIG)

    assert result["aspect_ratio"].to_numpy() == pytest.approx(profile.loc[0, "hw_ratio"])


def test_a_unit_no_street_reaches_is_null_on_all_three() -> None:
    units = make_units((0, 0, 200, 200), (1000, 0, 1200, 200))
    streets = make_streets([(20, 100), (180, 100)])
    buildings = make_buildings(*flanking(100, 20, 180, 18.0))

    result = street_metrics(streets, buildings, units, CONFIG)

    assert result.loc["u1"].isna().all()
    assert result.loc["u0"].notna().all()


def test_an_open_street_keeps_its_width_and_openness_but_has_no_aspect_ratio() -> None:
    """momepy reports the tick length as a theoretical width and an openness of 1.0 for a segment
    reaching no building. Both are true statements about an open street; the height-to-width ratio
    of a canyon with no walls is not, so it stays null rather than becoming zero."""
    units = make_units((0, 0, 400, 400))
    streets = make_streets([(10, 50), (110, 50)], [(10, 350), (290, 350)])
    # Buildings flank the first segment only.
    buildings = make_buildings(*flanking(50, 10, 110, 30.0))
    profile = profile_of(streets, buildings)
    assert np.isnan(profile.loc[1, "hw_ratio"])

    result = street_metrics(streets, buildings, units, CONFIG)

    # The aspect ratio comes from the first segment alone, so the second's absence does not drag
    # it anywhere; the width does average both, the open one contributing the tick length.
    assert result.loc["u0", "aspect_ratio"] == pytest.approx(profile.loc[0, "hw_ratio"])
    assert result.loc["u0", "street_openness"] == pytest.approx(
        (100 * profile.loc[0, "openness"] + 280 * profile.loc[1, "openness"]) / 380
    )
    assert result.loc["u0", "street_width_m"] < CONFIG.street_profile_tick_length_m


def test_no_streets_or_no_buildings_gives_a_null_table() -> None:
    units = make_units((0, 0, 200, 200))
    streets = make_streets([(20, 100), (180, 100)])
    buildings = make_buildings(*flanking(100, 20, 180, 18.0))
    empty_streets = gpd.GeoDataFrame(geometry=[], crs=CRS)
    empty_buildings = gpd.GeoDataFrame({"height": []}, geometry=[], crs=CRS)

    assert street_metrics(empty_streets, buildings, units, CONFIG).isna().all().all()
    assert street_metrics(streets, empty_buildings, units, CONFIG).isna().all().all()


def test_entry_contract_failures_are_refused() -> None:
    units = make_units((0, 0, 200, 200))
    streets = make_streets([(20, 100), (180, 100)])
    buildings = make_buildings(*flanking(100, 20, 180, 18.0))

    with pytest.raises(ValueError, match="unit_id"):
        street_metrics(streets, buildings, units.reset_index(), CONFIG)
    with pytest.raises(ValueError, match="streets.crs"):
        street_metrics(streets.to_crs("EPSG:32634"), buildings, units, CONFIG)
    with pytest.raises(ValueError, match="fill_heights"):
        street_metrics(streets, buildings.drop(columns=["height"]), units, CONFIG)
