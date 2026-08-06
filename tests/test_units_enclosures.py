"""Tests for `assemble_barriers` and `EnclosureUnits` — hand-built synthetic barriers for exact
enclosure counts, plus a real-fixture test exercising `OvertureSource.rail` end to end.
"""

from __future__ import annotations

import geopandas as gpd
import pytest
from conftest import SMALL_BBOX, FixtureVectorSource
from shapely.geometry import LineString, box

from lczkit.crs import local_utm_crs
from lczkit.protocols import BBox
from lczkit.units.enclosures import EnclosureUnits, assemble_barriers

_CRS = "EPSG:32633"
# A realistic easting/northing inside zone 33N's low-distortion domain — see test_units_grid.py
# for why coordinates near (0, 0) are unsuitable here.
_ORIGIN_E = 500_000.0
_ORIGIN_N = 5_700_000.0


def _bbox_from_utm(minx: float, miny: float, maxx: float, maxy: float) -> BBox:
    bounds = (
        gpd.GeoSeries(
            [box(_ORIGIN_E + minx, _ORIGIN_N + miny, _ORIGIN_E + maxx, _ORIGIN_N + maxy)],
            crs=_CRS,
        )
        .to_crs("EPSG:4326")
        .total_bounds
    )
    return (bounds[0], bounds[1], bounds[2], bounds[3])


def test_assemble_barriers_combines_streets_and_waterbodies() -> None:
    streets = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (10, 10)])], crs=_CRS)
    waterbodies = gpd.GeoDataFrame(geometry=[box(20, 20, 30, 30)], crs=_CRS)

    barriers = assemble_barriers(streets, waterbodies)

    assert len(barriers) == 2
    assert barriers.crs == _CRS
    assert list(barriers.columns) == ["geometry"]


def test_assemble_barriers_includes_optional_rail_and_vegetation() -> None:
    streets = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (10, 10)])], crs=_CRS)
    waterbodies = gpd.GeoDataFrame(geometry=[], crs=_CRS)
    rail = gpd.GeoDataFrame(geometry=[LineString([(0, 10), (10, 0)])], crs=_CRS)
    vegetation = gpd.GeoDataFrame(geometry=[box(40, 40, 50, 50)], crs=_CRS)

    barriers = assemble_barriers(streets, waterbodies, rail=rail, vegetation=vegetation)

    assert len(barriers) == 3


def test_assemble_barriers_rejects_mismatched_crs() -> None:
    streets = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (10, 10)])], crs=_CRS)
    waterbodies = gpd.GeoDataFrame(geometry=[], crs=_CRS)
    rail = gpd.GeoDataFrame(geometry=[LineString([(0, 10), (10, 0)])], crs="EPSG:32634")

    with pytest.raises(ValueError, match="crs"):
        assemble_barriers(streets, waterbodies, rail=rail)


def test_generate_splits_bbox_into_enclosures_by_a_single_street() -> None:
    bbox = _bbox_from_utm(0, 0, 200, 100)
    crs = local_utm_crs(bbox)
    # a single street bisecting the bbox vertically at x=100 splits it into two enclosures
    streets = gpd.GeoDataFrame(
        geometry=gpd.GeoSeries(
            [LineString([(_ORIGIN_E + 100, _ORIGIN_N - 10), (_ORIGIN_E + 100, _ORIGIN_N + 110)])],
            crs=crs,
        ),
        crs=crs,
    )
    waterbodies = gpd.GeoDataFrame(geometry=[], crs=crs)
    barriers = assemble_barriers(streets, waterbodies)

    units = EnclosureUnits().generate(bbox, barriers)

    assert len(units) == 2
    assert units.index.is_unique
    assert list(units.index) == ["enclosure_0", "enclosure_1"]
    assert units.crs == crs
    total_area = units.geometry.area.sum()
    # a small relative discrepancy vs. the nominal 200x100 area is expected: `bbox` itself is
    # already a UTM->EPSG:4326 round trip, and UTM's scale factor is never exactly 1 away from
    # the central meridian — this is real projection distortion, not a bug.
    assert total_area == pytest.approx(200 * 100, rel=1e-3)


def test_generate_raises_without_barriers() -> None:
    bbox = _bbox_from_utm(0, 0, 100, 100)

    with pytest.raises(ValueError, match="barriers"):
        EnclosureUnits().generate(bbox, None)

    with pytest.raises(ValueError, match="barriers"):
        EnclosureUnits().generate(bbox, gpd.GeoDataFrame(geometry=[]))


def test_generate_on_real_fixture_barriers(fixture_vector_source: FixtureVectorSource) -> None:
    """Streets + rail + waterbodies from the real Berlin fixture, on `SMALL_BBOX` for speed —
    exercises `OvertureSource.rail` (via `FixtureVectorSource`) as a real barrier input, not
    just the hand-built synthetic case above."""
    crs = local_utm_crs(SMALL_BBOX)
    streets = fixture_vector_source.streets(SMALL_BBOX).to_crs(crs)
    rail = fixture_vector_source.rail(SMALL_BBOX).to_crs(crs)
    _waterlines, waterbodies = fixture_vector_source.water(SMALL_BBOX)
    waterbodies = waterbodies.to_crs(crs)
    assert len(rail) > 0, "SMALL_BBOX is expected to contain real rail segments"

    barriers = assemble_barriers(streets, waterbodies, rail=rail)
    units = EnclosureUnits().generate(SMALL_BBOX, barriers)

    assert len(units) > 1
    assert units.index.is_unique
    assert units.crs == crs
    assert units.geometry.is_valid.all()
