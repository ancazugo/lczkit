"""Unit tests for cross-layer topology cleanup, against small hand-built geometries.

The street rule carries most of these. It is the operation that destroyed 22.5% of Berlin's
footprint area by deleting every building touching a road centreline, so the tests state the
distinction it now has to make: a block fronting a street is kept, a shed standing in one is not.
"""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString, box

from lczkit.cleaning.topology import (
    apply_cross_layer_topology,
    drop_buildings_on_waterbodies,
    drop_waterlines_through_buildings,
    resolve_buildings_on_streets,
)

CRS = "EPSG:32633"


def _gdf(geoms: list) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=geoms, crs=CRS)


def _street() -> gpd.GeoDataFrame:
    """One centreline running east-west along y=0."""
    return _gdf([LineString([(-100, 0), (100, 0)])])


def test_a_block_fronting_a_street_is_trimmed_rather_than_dropped() -> None:
    """The perimeter-block case, and the whole reason the centreline rule was wrong. A 20x20 m
    block whose edge sits 2 m over the centreline overlaps a 4 m buffer by 6 m of its 20 m depth —
    0.3, comfortably under the limit. The old rule deleted it outright for touching the line."""
    block = box(0, -2, 20, 18)  # 400 m2, 2 m of it south of the centreline
    result, step = resolve_buildings_on_streets(
        _gdf([block]), _street(), buffer_m=4.0, overlap_limit=0.5
    )

    assert len(result) == 1
    assert step.detail["n_dropped"] == 0
    assert step.detail["n_trimmed"] == 1
    # 20 m wide by the 6 m inside the buffer (from y=-2 up to y=+4) is what goes.
    assert result.geometry.area.iloc[0] == pytest.approx(400.0 - 120.0)
    assert step.area_out_m2 == pytest.approx(280.0)


def test_a_footprint_lying_in_the_roadway_is_dropped() -> None:
    """A 4x2 m structure straddling the centreline is entirely inside the buffer. On Berlin the
    dropped population has a median footprint of 2.5 m2 — this is what the rule is for."""
    shed = box(0, -1, 4, 1)
    result, step = resolve_buildings_on_streets(
        _gdf([shed]), _street(), buffer_m=4.0, overlap_limit=0.5
    )

    assert len(result) == 0
    assert step.detail["n_dropped"] == 1
    assert step.detail["area_dropped_m2"] == pytest.approx(8.0)


def test_a_building_clear_of_the_buffer_is_untouched() -> None:
    clear = box(0, 10, 20, 30)  # 6 m north of the 4 m buffer's edge
    result, step = resolve_buildings_on_streets(
        _gdf([clear]), _street(), buffer_m=4.0, overlap_limit=0.5
    )

    assert result.geometry.iloc[0].equals(clear)
    assert step.detail == {
        "road_buffer_m": 4.0,
        "overlap_limit": 0.5,
        "n_dropped": 0,
        "n_trimmed": 0,
        "area_dropped_m2": 0.0,
        "median_dropped_footprint_m2": None,
    }


def test_the_threshold_is_what_decides_between_trimming_and_dropping() -> None:
    """Same geometry, same buffer, two limits. The operating point is configuration, and the
    fixture-derived 0.5 is a choice rather than a property of the data."""
    # 10 x 16 = 160 m2, of which the buffer's y in [-4, 4] band covers 10 x 8 = 80: exactly half.
    half_in = box(0, -4, 10, 12)

    kept, _ = resolve_buildings_on_streets(
        _gdf([half_in]), _street(), buffer_m=4.0, overlap_limit=0.6
    )
    dropped, _ = resolve_buildings_on_streets(
        _gdf([half_in]), _street(), buffer_m=4.0, overlap_limit=0.4
    )

    assert len(kept) == 1
    assert len(dropped) == 0


def test_a_building_the_buffer_cuts_in_two_stays_one_feature() -> None:
    """Otherwise one building becomes two in `building_count`, and a `building_id` gets two rows."""
    spanning = box(0, -20, 10, 20)  # the buffer slices a band out of its middle
    result, step = resolve_buildings_on_streets(
        _gdf([spanning]), _street(), buffer_m=4.0, overlap_limit=0.5
    )

    assert len(result) == 1
    assert result.geometry.iloc[0].geom_type == "Polygon"
    assert result.geometry.area.iloc[0] == pytest.approx(160.0)  # the larger half, 10 x 16
    assert step.detail["n_trimmed"] == 1


def test_resolve_buildings_on_streets_passes_through_an_empty_street_layer() -> None:
    buildings = _gdf([box(0, 0, 10, 10)])

    result, step = resolve_buildings_on_streets(
        buildings, gpd.GeoDataFrame(geometry=[], crs=CRS), buffer_m=4.0, overlap_limit=0.5
    )

    assert len(result) == 1
    assert step.n_in == step.n_out == 1
    assert step.area_in_m2 == step.area_out_m2 == pytest.approx(100.0)


def test_drop_buildings_on_waterbodies_still_drops_on_intersection() -> None:
    """Unchanged, deliberately: a footprint reaching into a river is a conflation error rather
    than a building fronting it, and it cost 6 features on Berlin against the street rule's 439."""
    clean = box(0, 0, 10, 10)
    on_water = box(200, 200, 210, 210)
    result, step = drop_buildings_on_waterbodies(
        _gdf([clean, on_water]), _gdf([box(195, 195, 215, 215)])
    )

    assert len(result) == 1
    assert result.geometry.iloc[0].equals(clean)
    assert step.stage == "buildings_topo"
    assert step.area_in_m2 == pytest.approx(200.0)
    assert step.area_out_m2 == pytest.approx(100.0)


def test_drop_waterlines_through_buildings() -> None:
    building = box(0, 0, 10, 10)
    through = LineString([(-5, 5), (15, 5)])  # crosses the building
    beside = LineString([(20, 20), (30, 30)])  # doesn't touch it

    result, step = drop_waterlines_through_buildings(_gdf([through, beside]), _gdf([building]))

    assert len(result) == 1
    assert result.geometry.iloc[0].equals(beside)
    assert step.stage == "topology"
    assert step.n_in == 2
    assert step.n_out == 1
    # A linework layer has no footprint area, and says so rather than leaving the field unset.
    assert step.area_in_m2 == step.area_out_m2 == 0.0


def test_apply_cross_layer_topology_leaves_streets_and_waterbodies_unchanged() -> None:
    block = box(0, -2, 20, 18)  # fronts the street, kept and trimmed
    shed = box(40, -1, 44, 1)  # in the roadway, dropped
    streets = _street()
    waterbodies = _gdf([box(500, 500, 510, 510)])
    waterlines = _gdf([LineString([(-5, 10), (25, 10)])])  # passes through the surviving block

    buildings, out_streets, out_waterlines, out_waterbodies, steps = apply_cross_layer_topology(
        _gdf([block, shed]),
        streets,
        waterlines,
        waterbodies,
        road_buffer_m=4.0,
        road_overlap_limit=0.5,
    )

    assert len(buildings) == 1
    assert out_streets is streets
    assert out_waterbodies is waterbodies
    assert len(out_waterlines) == 0  # the surviving block sits under it
    assert [s.operation for s in steps] == [
        "resolve_buildings_on_streets",
        "drop_buildings_on_waterbodies",
        "drop_waterlines_through_buildings",
    ]
