"""Tests for `GridUnits` against small, hand-built bboxes — exact cell counts and ids."""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import box

from lczkit.protocols import BBox
from lczkit.units.grid import GridUnits

_CRS = "EPSG:32633"
# A realistic easting/northing inside zone 33N's low-distortion domain — coordinates near
# (0, 0) are degenerate for a UTM projection (thousands of km from the zone's actual coverage)
# and round-trip through EPSG:4326 with enough distortion to break area/alignment assertions.
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


def test_generate_covers_bbox_with_expected_cell_count() -> None:
    # deliberately not aligned to any 100 m boundary, so sub-metre reprojection round-trip
    # jitter (UTM -> EPSG:4326 -> UTM) can never flip which cell an edge falls into
    bbox = _bbox_from_utm(63, 71, 241, 168)  # ~178x97, straddling 3 columns x 2 rows

    units = GridUnits(cell_size_m=100.0).generate(bbox)

    assert len(units) == 6
    assert units.crs is not None
    assert units.crs.is_projected


def test_unit_ids_are_unique_and_stable_across_overlapping_bboxes() -> None:
    strategy = GridUnits(cell_size_m=100.0)
    bbox_a = _bbox_from_utm(63, 71, 241, 168)
    bbox_b = _bbox_from_utm(163, 71, 341, 168)

    units_a = strategy.generate(bbox_a)
    units_b = strategy.generate(bbox_b)

    assert units_a.index.is_unique
    assert units_b.index.is_unique
    # the two bboxes overlap in x: [163, 241]: those cells must get identical ids
    shared_ids = set(units_a.index) & set(units_b.index)
    assert shared_ids == {
        "grid_5001_57000",
        "grid_5001_57001",
        "grid_5002_57000",
        "grid_5002_57001",
    }
    for unit_id in shared_ids:
        assert units_a.loc[unit_id, "geometry"].equals(units_b.loc[unit_id, "geometry"])


def test_every_cell_is_exactly_cell_size_square() -> None:
    units = GridUnits(cell_size_m=100.0).generate(_bbox_from_utm(17, 23, 163, 79))

    for geom in units.geometry:
        minx, miny, maxx, maxy = geom.bounds
        assert maxx - minx == pytest.approx(100.0)
        assert maxy - miny == pytest.approx(100.0)


def test_custom_cell_size() -> None:
    units = GridUnits(cell_size_m=50.0).generate(_bbox_from_utm(13, 9, 111, 58))

    assert len(units) == 6
    for geom in units.geometry:
        minx, miny, maxx, maxy = geom.bounds
        assert maxx - minx == pytest.approx(50.0)


def test_rejects_non_positive_cell_size() -> None:
    with pytest.raises(ValueError, match="cell_size_m"):
        GridUnits(cell_size_m=0.0)


def test_barriers_argument_is_ignored() -> None:
    bbox = _bbox_from_utm(0, 0, 100, 100)
    strategy = GridUnits(cell_size_m=100.0)

    without_barriers = strategy.generate(bbox)
    with_junk_barriers = strategy.generate(bbox, barriers=gpd.GeoDataFrame(geometry=[]))

    assert list(without_barriers.index) == list(with_junk_barriers.index)
