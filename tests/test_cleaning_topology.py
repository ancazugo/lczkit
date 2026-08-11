"""Unit tests for cross-layer topology cleanup, against small hand-built geometries.

The street rule carries most of these. It is the operation that destroyed 22.5% of Berlin's
footprint area by deleting every building touching a road centreline, so the tests state the
distinction it now has to make: a block fronting a street is kept, a shed standing in one is not.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
import shapely
from conftest import FIXTURE_BBOX, FixtureVectorSource
from shapely.geometry import LineString, box

from lczkit.cleaning.buildings import clean_buildings
from lczkit.cleaning.geometry import largest_part
from lczkit.cleaning.land_use import clean_land_use
from lczkit.cleaning.pipeline import reproject_to_local_utm
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


def test_the_road_rule_is_bounded_by_the_index_not_by_the_city(
    fixture_vector_source: FixtureVectorSource,
) -> None:
    """Phase 8: the index-bounded road rule must equal the global-union one it replaced.

    The original unioned every buffered street into one geometry and intersected every footprint
    against it, which costs O(footprints x road complexity) and so is quadratic in extent — 87.8 s
    for 9563 footprints over 16 km2, projecting to roughly 75 hours over Berlin. It had never
    appeared in a profile because no run had ever got that far.

    Restricting each footprint to the road buffers it actually meets is exact, not approximate: a
    part of the roadway a footprint does not touch changes neither its intersection nor its
    difference. This asserts that exactness on real Berlin fabric, where the fixture's hand-built
    geometries above could not — they have one street each.
    """
    _, layers, _ = reproject_to_local_utm(
        FIXTURE_BBOX,
        buildings=fixture_vector_source.buildings(FIXTURE_BBOX),
        streets=fixture_vector_source.streets(FIXTURE_BBOX),
    )
    streets = layers["streets"]
    cleaned, _ = clean_buildings(
        layers["buildings"],
        max_area_m2=100_000.0,
        min_area_m2=20.0,
        merge_limit_m2=50.0,
        overlap_limit=0.1,
    )
    buildings = cleaned.topo

    # The replaced implementation, verbatim, as the reference. Restating it is the point: an
    # assertion against a re-derived expectation would test the re-derivation.
    road = streets.geometry.buffer(4.0).union_all()
    footprint_area = buildings.geometry.area
    fraction = (
        buildings.geometry.intersection(road)
        .area.div(footprint_area.where(footprint_area > 0))
        .fillna(0.0)
    )
    dropped = fraction > 0.5
    trimmed = (fraction > 0.0) & ~dropped
    expected = buildings.loc[~dropped].copy()
    to_trim = trimmed.loc[expected.index]
    expected.loc[to_trim, "geometry"] = largest_part(
        expected.loc[to_trim].geometry.difference(road)
    ).to_numpy()
    expected = expected.loc[expected.geometry.notna() & ~expected.geometry.is_empty]

    kept, _ = resolve_buildings_on_streets(buildings, streets, buffer_m=4.0, overlap_limit=0.5)

    assert len(kept) == len(expected)
    assert set(kept["building_id"]) == set(expected["building_id"])
    # Same ground, not merely the same amount of it.
    difference = kept.geometry.union_all().symmetric_difference(expected.geometry.union_all())
    assert difference.area == pytest.approx(0.0, abs=1e-6)
    # Total area to ten significant figures: the two differ only by floating-point noise in the
    # order GEOS unions the buffers, not by which ground each considers roadway.
    assert kept.geometry.area.sum() == pytest.approx(expected.geometry.area.sum(), rel=1e-9)


def test_a_globe_spanning_feature_is_clipped_rather_than_taking_the_city_down() -> None:
    """Overture's `base/land_use` carries marine protected areas spanning all 360 degrees.

    Two `species_management_area` polygons with bounds -180..180 intersect the Hong Kong study
    window. A UTM zone is 6 degrees wide, so projecting them into UTM 50N produced 663 non-finite
    coordinates, and the first thing to touch one — `make_valid()` in `clean_land_use` — failed
    with `CGAlgorithmsDD::orientationIndex encountered NaN/Inf numbers`, taking the whole city
    out of the Phase 9 sweep. A city that crashes is worse than a city that scores badly.

    The clipped remainder is the part inside the study area, which is the only part any statistic
    here uses.
    """
    bbox = (114.0, 22.2, 114.1, 22.3)
    ordinary = shapely.box(114.02, 22.22, 114.04, 22.24)
    # Vertices taken from where the real feature actually diverges. Transverse Mercator runs to
    # infinity 90 degrees from its central meridian, worst at the equator — UTM 50N is centred on
    # 117E, and the failing coordinates sit near 158W at 3S. A polygon merely spanning -180..180
    # at Hong Kong's own latitude projects perfectly finitely, which is why the first version of
    # this test passed against the broken code.
    ocean_wide = shapely.Polygon(
        [
            (114.02, 22.22),
            (114.04, 22.24),
            (170.0, 22.0),
            (-158.0, -3.0),
            (-160.0, 0.5),
            (-177.0, 10.0),
        ]
    )
    land_use = gpd.GeoDataFrame(
        {"subtype": ["residential", "protected"]},
        geometry=[ordinary, ocean_wide],
        crs="EPSG:4326",
    )

    _, layers, repaired = reproject_to_local_utm(bbox, land_use=land_use)
    projected = layers["land_use"]

    assert repaired["land_use"] == 1
    assert len(projected) == 2, "the clipped feature is kept, not dropped"
    coords = shapely.get_coordinates(projected.geometry.values)
    assert np.isfinite(coords).all(), "nothing non-finite may reach make_valid()"
    # And the operation the crash happened in now completes.
    clean_land_use(projected)


def test_an_ordinary_layer_is_not_touched_by_the_repair() -> None:
    """Zero for every city measured before Phase 10, and it must stay that way — the repair is a
    guard against unrepresentable geometry, not a general clip to the study extent."""
    bbox = (114.0, 22.2, 114.1, 22.3)
    outside = shapely.box(114.15, 22.35, 114.16, 22.36)
    land_use = gpd.GeoDataFrame({"subtype": ["residential"]}, geometry=[outside], crs="EPSG:4326")

    _, layers, repaired = reproject_to_local_utm(bbox, land_use=land_use)

    assert repaired["land_use"] == 0
    assert layers["land_use"].geometry.iloc[0].bounds == pytest.approx(
        gpd.GeoSeries([outside], crs="EPSG:4326").to_crs(layers["land_use"].crs).total_bounds
    )
