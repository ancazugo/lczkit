"""Unit tests for `zonal_mean`, the Phase 3 minimal local raster read.

The raster is a 4x4 grid of 100 m cells holding 0..15 in row-major order, with its top-left
corner at (0, 400) in EPSG:32633 — so cell (row, col) covers x in [100*col, 100*col+100) and
y in (400-100*row-100, 400-100*row].
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from conftest import write_height_raster
from shapely.geometry import box

CRS = "EPSG:32633"
NODATA = -9999.0


@pytest.fixture
def raster(tmp_path: Path) -> Path:
    values = np.arange(16, dtype="float32").reshape(4, 4)
    return write_height_raster(
        tmp_path / "heights.tif",
        values,
        origin=(0.0, 400.0),
        cell_size_m=100.0,
        crs=CRS,
        nodata=NODATA,
    )


def _geoms(*geometries: object, crs: str = CRS) -> gpd.GeoSeries:
    return gpd.GeoSeries(list(geometries), crs=crs)


def test_footprint_inside_one_cell_gets_that_cells_value(raster: Path) -> None:
    from lczkit.heights.raster import zonal_mean

    # well inside cell (0, 0), which holds 0.0
    result = zonal_mean(raster, _geoms(box(10, 310, 30, 330)))

    assert result == pytest.approx([0.0])


def test_footprint_spanning_cells_gets_their_mean(raster: Path) -> None:
    from lczkit.heights.raster import zonal_mean

    # covers cells (1,0), (1,1), (2,0), (2,1) -> 4, 5, 8, 9
    result = zonal_mean(raster, _geoms(box(10, 110, 190, 290)))

    assert result == pytest.approx([6.5])


def test_footprint_smaller_than_a_cell_still_gets_a_value(raster: Path) -> None:
    """`all_touched=True` is what makes the coarse tiers usable at all — a 20 m building in a
    100 m product must pick up the cell it sits in, not fall through to the next tier."""
    from lczkit.heights.raster import zonal_mean

    result = zonal_mean(raster, _geoms(box(350, 5, 351, 6)))  # cell (3, 3) -> 15.0

    assert result == pytest.approx([15.0])


def test_footprint_outside_the_raster_is_nan(raster: Path) -> None:
    from lczkit.heights.raster import zonal_mean

    result = zonal_mean(raster, _geoms(box(5000, 5000, 5100, 5100)))

    assert np.isnan(result).all()


def test_results_are_aligned_to_the_input_order(raster: Path) -> None:
    from lczkit.heights.raster import zonal_mean

    result = zonal_mean(
        raster,
        _geoms(
            box(5000, 5000, 5100, 5100),  # off-raster
            box(10, 310, 30, 330),  # cell (0, 0)
            box(350, 5, 351, 6),  # cell (3, 3)
        ),
    )

    assert np.isnan(result[0])
    assert result[1:] == pytest.approx([0.0, 15.0])


def test_nodata_cells_are_excluded_from_the_mean(tmp_path: Path) -> None:
    values = np.full((2, 2), NODATA, dtype="float32")
    values[0, 0] = 12.0
    path = write_height_raster(
        tmp_path / "sparse.tif",
        values,
        origin=(0.0, 200.0),
        cell_size_m=100.0,
        crs=CRS,
        nodata=NODATA,
    )
    from lczkit.heights.raster import zonal_mean

    covering_everything = zonal_mean(path, _geoms(box(1, 1, 199, 199)))
    only_nodata = zonal_mean(path, _geoms(box(110, 10, 190, 90)))

    assert covering_everything == pytest.approx([12.0])
    assert np.isnan(only_nodata).all()


def test_nodata_can_be_overridden_per_read(raster: Path) -> None:
    """Tier config may need to mask a sentinel the file itself does not declare."""
    from lczkit.heights.raster import zonal_mean

    spanning = _geoms(box(10, 110, 190, 290))  # cells holding 4, 5, 8, 9

    assert zonal_mean(raster, spanning, nodata=4.0) == pytest.approx([(5 + 8 + 9) / 3])


def test_geometries_are_reprojected_to_the_rasters_crs(raster: Path) -> None:
    """The buildings layer is in the local UTM CRS; a global height product will not be."""
    from lczkit.heights.raster import zonal_mean

    utm = _geoms(box(10, 310, 30, 330), box(10, 110, 190, 290))

    assert zonal_mean(raster, utm.to_crs("EPSG:4326")) == pytest.approx(zonal_mean(raster, utm))


def test_empty_input_returns_empty(raster: Path) -> None:
    from lczkit.heights.raster import zonal_mean

    assert zonal_mean(raster, gpd.GeoSeries([], dtype="geometry", crs=CRS)).shape == (0,)


def test_missing_crs_on_geometries_raises(raster: Path) -> None:
    from lczkit.heights.raster import zonal_mean

    with pytest.raises(ValueError, match="no CRS"):
        zonal_mean(raster, gpd.GeoSeries([box(10, 310, 30, 330)]))
