"""`lczkit.morphometrics.raster` — format dispatch (GeoTIFF/COG/Zarr) and geographic tiling.

The single-file GeoTIFF path is the pre-existing behaviour and stays default; these tests add
coverage for the new format and tiling arguments, on synthetic two/four-cell layers so the
expected area-weighted values are hand-computable.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
import xarray as xr
from shapely.geometry import box

from lczkit.morphometrics.raster import (
    RASTER_FILE,
    RASTER_TILE_DIR,
    RASTER_ZARR_FILE,
    RasterExportReport,
    raster_filename,
    rasterize_attributes,
    refresh_raster,
)

# A small ETC-like layer: two 10 m x 10 m cells side by side, one attribute column.
_TWO_CELL = gpd.GeoDataFrame(
    {"unit_id": ["etc_0", "etc_1"], "value": [2.0, 8.0]},
    geometry=[box(0.0, 0.0, 10.0, 10.0), box(10.0, 0.0, 20.0, 10.0)],
    crs="EPSG:32633",
).set_index("unit_id")


def test_gtiff_is_area_weighted_and_is_the_default(tmp_path: Path) -> None:
    report = rasterize_attributes(_TWO_CELL, 10.0, tmp_path / "out.tif")

    assert report.format == "gtiff"
    assert report.tile_deg is None
    assert report.tiles == ()
    assert report.band_names == ("value",)

    with rasterio.open(tmp_path / "out.tif") as src:
        assert src.crs.to_epsg() == 32633
        array = src.read(1)
        assert array.shape == (1, 2)
        np.testing.assert_allclose(array[0], [2.0, 8.0])
        assert src.descriptions == ("value",)


def test_cog_round_trips_the_same_values_as_gtiff(tmp_path: Path) -> None:
    rasterize_attributes(_TWO_CELL, 10.0, tmp_path / "out.tif", format="gtiff")
    rasterize_attributes(_TWO_CELL, 10.0, tmp_path / "out_cog.tif", format="cog")

    with (
        rasterio.open(tmp_path / "out.tif") as plain,
        rasterio.open(tmp_path / "out_cog.tif") as cog,
    ):
        np.testing.assert_allclose(plain.read(1), cog.read(1))
        assert cog.crs == plain.crs
        # COG's defining property: internally tiled rather than striped.
        assert cog.profile.get("tiled", False) or cog.block_shapes[0] != (1, cog.width)


def test_zarr_round_trips_crs_and_values(tmp_path: Path) -> None:
    """The property that ruled out GDAL's own `Zarr` driver: CRS must survive a plain reopen.

    Measured directly before choosing the `xarray`/`rioxarray` route (see
    `lczkit.config.RasterFormat`'s docstring) — GDAL's driver writes the array but stores the CRS
    only in a `pam.aux.xml` sidecar a plain `zarr`/`xarray` reader never looks at, so
    `xr.open_zarr` without `decode_coords="all"` would silently show no CRS even when the store is
    otherwise correct.
    """
    out = tmp_path / "out.zarr"
    report = rasterize_attributes(_TWO_CELL, 10.0, out, format="zarr")

    assert report.format == "zarr"
    reopened = xr.open_zarr(out, decode_coords="all")
    da = reopened["morphometrics"]
    assert da.rio.crs.to_epsg() == 32633
    np.testing.assert_allclose(da.sel(band="value").to_numpy()[0], [2.0, 8.0])


def test_raster_filename_matches_format() -> None:
    assert raster_filename("gtiff") == RASTER_FILE
    assert raster_filename("cog") == RASTER_FILE
    assert raster_filename("zarr") == RASTER_ZARR_FILE


def test_an_untiled_and_a_tiled_run_agree_pixel_for_pixel(tmp_path: Path) -> None:
    """Tiling must not change a single value — only how the array is split into files.

    Rather than hand-deriving the `geotessera`-style tile names a real extent would produce (a
    UTM-to-degree conversion done by eye is exactly the kind of arithmetic this project's own
    anti-pattern list warns against trusting unchecked), this stitches the tiles back together
    and asserts the result equals the untiled raster — a property that holds regardless of which
    tile grid the extent happens to fall on.
    """
    # A four-cell 2x2 layer at a real-world-scale UTM offset, so it plausibly straddles a
    # 0.1-degree boundary rather than sitting inside a single tile by construction.
    minx, miny = 500_000.0, 5_700_000.0
    size = 6_000.0  # 6 km cells -> a 12 km x 12 km extent, comfortably over 0.1 degrees (~7-11 km)
    cells = gpd.GeoDataFrame(
        {
            "unit_id": ["etc_00", "etc_01", "etc_10", "etc_11"],
            "value": [1.0, 2.0, 3.0, 4.0],
        },
        geometry=[
            box(minx, miny, minx + size, miny + size),
            box(minx + size, miny, minx + 2 * size, miny + size),
            box(minx, miny + size, minx + size, miny + 2 * size),
            box(minx + size, miny + size, minx + 2 * size, miny + 2 * size),
        ],
        crs="EPSG:32633",
    ).set_index("unit_id")

    untiled_path = tmp_path / "untiled.tif"
    rasterize_attributes(cells, 500.0, untiled_path, format="gtiff")
    with rasterio.open(untiled_path) as src:
        full = src.read(1)
        full_transform = src.transform
        full_crs = src.crs

    tile_dir = tmp_path / "tiles"
    report = rasterize_attributes(cells, 500.0, tile_dir, format="gtiff", tile_deg=0.1)

    assert report.tile_deg == 0.1
    assert report.tiles, "the extent should produce at least one tile"
    for name in report.tiles:
        assert re.fullmatch(r"grid_-?\d+\.\d{2}_-?\d+\.\d{2}\.tif", name), name

    stitched = np.full_like(full, np.nan)
    for name in report.tiles:
        with rasterio.open(tile_dir / name) as tile_src:
            assert tile_src.crs == full_crs
            tile_array = tile_src.read(1)
            row_off = round((full_transform.f - tile_src.transform.f) / -full_transform.e)
            col_off = round((tile_src.transform.c - full_transform.c) / full_transform.a)
            stitched[
                row_off : row_off + tile_array.shape[0], col_off : col_off + tile_array.shape[1]
            ] = tile_array

    np.testing.assert_allclose(stitched, full)


def test_tiling_drops_tiles_with_no_real_data(tmp_path: Path) -> None:
    tile_dir = tmp_path / "tiles"
    report = rasterize_attributes(_TWO_CELL, 10.0, tile_dir, format="gtiff", tile_deg=0.1)
    # A 20 m x 10 m extent is far smaller than one 0.1 degree tile, so this must collapse to
    # exactly one tile rather than several mostly-empty ones from the surrounding global grid.
    assert len(report.tiles) == 1


def test_origin_anchors_the_pixel_lattice_to_an_external_grid(tmp_path: Path) -> None:
    """Without `origin` the lattice starts at the data's own bounds, which lands off any grid
    somebody else defined. Measured on the real case this was built for: a 1 280 m training grid
    anchored at a non-round easting sat 0.998 px from a raster started at its data bounds — enough
    to misregister every patch cut from it.
    """
    origin = (1234.5678, 98765.4321)  # deliberately off any round lattice
    rasterize_attributes(_TWO_CELL, 10.0, tmp_path / "free.tif")
    rasterize_attributes(_TWO_CELL, 10.0, tmp_path / "anchored.tif", origin=origin)

    with rasterio.open(tmp_path / "anchored.tif") as anchored:
        assert (anchored.transform.c - origin[0]) % 10.0 == pytest.approx(0.0, abs=1e-9)
        assert (origin[1] - anchored.transform.f) % 10.0 == pytest.approx(0.0, abs=1e-9)

    with rasterio.open(tmp_path / "free.tif") as free:
        assert (free.transform.c - origin[0]) % 10.0 != pytest.approx(0.0, abs=1e-9)


def test_an_anchored_grid_still_covers_every_input_geometry(tmp_path: Path) -> None:
    """Snapping grows the extent outward, never crops it — so anchoring cannot drop data."""
    origin = (7.5, 99999.5)
    rasterize_attributes(_TWO_CELL, 10.0, tmp_path / "anchored.tif", origin=origin)
    with rasterio.open(tmp_path / "anchored.tif") as src:
        left, bottom, right, top = src.bounds
        minx, miny, maxx, maxy = _TWO_CELL.total_bounds
        assert left <= minx and bottom <= miny and right >= maxx and top >= maxy


def test_byte_ceiling_refuses_before_allocating(tmp_path: Path) -> None:
    # The two-cell layer at 10 m resolution needs 1 x 2 x 4 = 8 bytes; below that is refused.
    with pytest.raises(ValueError, match="max_raster_bytes"):
        rasterize_attributes(_TWO_CELL, 10.0, tmp_path / "out.tif", max_bytes=4)


def test_tile_deg_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="tile_deg"):
        rasterize_attributes(_TWO_CELL, 10.0, tmp_path / "out", tile_deg=0.0)


def test_refresh_raster_records_format_and_tiles_in_the_manifest(tmp_path: Path) -> None:
    _TWO_CELL.to_parquet(tmp_path / "morphometrics.parquet")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"outputs": []}), encoding="utf-8")

    report = refresh_raster(tmp_path, 10.0, format="zarr")
    assert isinstance(report, RasterExportReport)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    recorded = manifest["morphometrics_raster"]
    assert recorded["format"] == "zarr"
    assert recorded["tile_deg"] is None
    assert recorded["tiles"] == []
    assert RASTER_ZARR_FILE in manifest["outputs"]


def test_refresh_raster_tiled_writes_into_the_tile_directory(tmp_path: Path) -> None:
    _TWO_CELL.to_parquet(tmp_path / "morphometrics.parquet")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"outputs": []}), encoding="utf-8")

    report = refresh_raster(tmp_path, 10.0, tile_deg=0.1)

    assert (tmp_path / RASTER_TILE_DIR).is_dir()
    assert report.tiles
    for name in report.tiles:
        assert (tmp_path / RASTER_TILE_DIR / name).exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert RASTER_TILE_DIR in manifest["outputs"]
    assert manifest["morphometrics_raster"]["tile_deg"] == 0.1
