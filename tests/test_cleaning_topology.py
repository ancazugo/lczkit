"""Unit tests for cross-layer topology cleanup, against small hand-built geometries."""

from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, box

from lczkit.cleaning.topology import (
    apply_cross_layer_topology,
    drop_buildings_on_streets_or_water,
    drop_waterlines_through_buildings,
)

CRS = "EPSG:32633"


def _gdf(geoms: list) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=geoms, crs=CRS)


def test_drop_buildings_on_streets_or_water_drops_both_kinds() -> None:
    clean = box(0, 0, 10, 10)
    on_street = box(100, 100, 110, 110)
    on_water = box(200, 200, 210, 210)
    buildings = _gdf([clean, on_street, on_water])
    streets = _gdf([LineString([(105, 90), (105, 120)])])  # crosses `on_street`
    waterbodies = _gdf([box(195, 195, 215, 215)])  # contains `on_water`

    result, steps = drop_buildings_on_streets_or_water(buildings, streets, waterbodies)

    assert len(result) == 1
    assert result.geometry.iloc[0].equals(clean)
    assert [s.operation for s in steps] == [
        "drop_buildings_on_streets",
        "drop_buildings_on_waterbodies",
    ]
    assert all(s.stage == "topology" for s in steps)
    assert steps[0].n_in == 3 and steps[0].n_out == 2
    assert steps[1].n_in == 2 and steps[1].n_out == 1


def test_drop_buildings_handles_empty_other_layers() -> None:
    buildings = _gdf([box(0, 0, 10, 10)])
    empty_streets = gpd.GeoDataFrame(geometry=[], crs=CRS)
    empty_water = gpd.GeoDataFrame(geometry=[], crs=CRS)

    result, steps = drop_buildings_on_streets_or_water(buildings, empty_streets, empty_water)

    assert len(result) == 1
    assert steps[0].n_in == steps[0].n_out == 1
    assert steps[1].n_in == steps[1].n_out == 1


def test_drop_waterlines_through_buildings() -> None:
    building = box(0, 0, 10, 10)
    buildings = _gdf([building])
    through = LineString([(-5, 5), (15, 5)])  # crosses the building
    beside = LineString([(20, 20), (30, 30)])  # doesn't touch it
    waterlines = _gdf([through, beside])

    result, step = drop_waterlines_through_buildings(waterlines, buildings)

    assert len(result) == 1
    assert result.geometry.iloc[0].equals(beside)
    assert step.stage == "topology"
    assert step.n_in == 2
    assert step.n_out == 1


def test_apply_cross_layer_topology_leaves_streets_and_waterbodies_unchanged() -> None:
    clean_building = box(0, 0, 10, 10)
    on_street_building = box(100, 100, 110, 110)
    buildings = _gdf([clean_building, on_street_building])
    streets = _gdf([LineString([(105, 90), (105, 120)])])
    waterbodies = _gdf([box(500, 500, 510, 510)])
    through_line = LineString([(-5, 5), (15, 5)])  # crosses the surviving building
    waterlines = _gdf([through_line])

    out_buildings, out_streets, out_waterlines, out_waterbodies, steps = apply_cross_layer_topology(
        buildings, streets, waterlines, waterbodies
    )

    assert len(out_buildings) == 1
    assert out_streets is streets
    assert out_waterbodies is waterbodies
    assert len(out_waterlines) == 0
    operations = [s.operation for s in steps]
    assert operations == [
        "drop_buildings_on_streets",
        "drop_buildings_on_waterbodies",
        "drop_waterlines_through_buildings",
    ]
