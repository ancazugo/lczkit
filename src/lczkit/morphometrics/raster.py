"""Rasterizing morphometric attributes to a multiband raster at a user-defined resolution.

Not part of the paper — Majer & Fleischmann (2026) never rasterize their 2D attributes, only the
20-attribute subset feeding their fusion schemes (out of scope here, see the module docstring of
`lczkit.morphometrics`). This is a new lczkit capability: one raster, one band per attribute,
each pixel the **area-weighted mean** of whichever ETCs overlap it.

Reuses `lczkit.units.overlay.unit_pieces` rather than a new vector-to-raster library — the
overlay-and-measure primitive already in the package is exactly what "which ETCs does this pixel
cover, and how much of each" is. A local, purpose-built grid builder is used rather than stretching
`GridUnits` to a second contract: `GridUnits` takes a lon/lat `bbox` and estimates its own CRS,
which is the wrong shape for a grid built directly over an already-projected ETC layer's own
bounds at an arbitrary resolution.

**Three output formats.** `"gtiff"` (default, unchanged from the original single-file behaviour)
and `"cog"` both go through `rasterio`'s own GDAL drivers — verified to need no new dependency.
`"zarr"` goes through `xarray`/`rioxarray` rather than GDAL's `Zarr` driver: measured directly
before choosing this route (see `lczkit.config.RasterFormat`) — GDAL's own driver writes the
array correctly but stores the CRS only in a GDAL-specific sidecar invisible to a plain
`zarr`/`xarray` reader, which defeats the interoperability a cloud-native format is for.

**Optional tiling.** `tile_deg` splits the raster into a `geotessera`-style geographic tile grid
(github.com/ucam-eo/geotessera) rather than one file covering the whole extent — see
`lczkit.config.MorphometricsConfig.raster_tile_deg`. The expensive step (the area-weighted overlay)
runs exactly once regardless of tiling; tiling only changes how the resulting array is windowed
and written.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rioxarray  # noqa: F401  (registers the `.rio` accessor used below)
import xarray as xr
from rasterio import Affine
from rasterio.crs import CRS
from rasterio.transform import from_origin
from rasterio.warp import transform as warp_transform
from rasterio.warp import transform_bounds
from rasterio.windows import Window
from rasterio.windows import transform as window_transform
from shapely.geometry import box

from lczkit.config import RasterFormat
from lczkit.crs import assert_projected_crs
from lczkit.output.writer import MANIFEST_FILE, MORPHOMETRICS_FILE
from lczkit.units.overlay import PIECE_AREA, unit_pieces

RASTER_FILE = "morphometrics.tif"
RASTER_ZARR_FILE = "morphometrics.zarr"
RASTER_TILE_DIR = "morphometrics_tiles"

_GDAL_DRIVERS: dict[str, str] = {"gtiff": "GTiff", "cog": "COG"}


def raster_filename(format: RasterFormat) -> str:
    """The single-file output name for `format` — a `.zarr` store is a directory, not a `.tif`."""
    return RASTER_ZARR_FILE if format == "zarr" else RASTER_FILE


def _tile_ext(format: RasterFormat) -> str:
    return ".zarr" if format == "zarr" else ".tif"


@dataclass(frozen=True)
class RasterExportReport:
    """What `rasterize_attributes` wrote, for the run manifest."""

    resolution_m: float
    n_rows: int
    n_cols: int
    band_names: tuple[str, ...]
    format: RasterFormat = "gtiff"
    tile_deg: float | None = None
    tiles: tuple[str, ...] = ()
    """Filenames written under `out_path` when `tile_deg` is set; empty for a single-file write,
    where `out_path` itself (known to the caller) is the whole answer."""

    def as_manifest(self) -> dict[str, Any]:
        """The `manifest.morphometrics_raster` entry describing this raster."""
        return {
            "resolution_m": self.resolution_m,
            "n_rows": self.n_rows,
            "n_cols": self.n_cols,
            "band_names": list(self.band_names),
            "format": self.format,
            "tile_deg": self.tile_deg,
            "tiles": list(self.tiles),
        }


def _snap(
    bounds: tuple[float, float, float, float],
    resolution_m: float,
    origin: tuple[float, float],
) -> tuple[float, float, float, float]:
    """`bounds` grown outward to the pixel lattice anchored at `origin` (an x, top-y pair).

    Growing rather than rounding: the returned box always contains the input, so no data falls
    outside the grid that gets built over it.
    """
    ox, oy = origin
    minx = ox + math.floor((bounds[0] - ox) / resolution_m) * resolution_m
    maxx = ox + math.ceil((bounds[2] - ox) / resolution_m) * resolution_m
    maxy = oy - math.floor((oy - bounds[3]) / resolution_m) * resolution_m
    miny = oy - math.ceil((oy - bounds[1]) / resolution_m) * resolution_m
    return (minx, miny, maxx, maxy)


def _pixel_grid(
    bounds: tuple[float, float, float, float],
    resolution_m: float,
    origin: tuple[float, float] | None = None,
) -> tuple[gpd.GeoDataFrame, int, int]:
    """A regular `resolution_m` grid covering `bounds`, one row per pixel, `row`/`col` attached.

    Row 0 is the **top** row (highest y), matching `rasterio`'s array convention and
    `rasterio.transform.from_origin`'s own origin-at-top-left contract — so the array this module
    builds from `unit_id -> (row, col)` needs no vertical flip before it is written.

    `origin` anchors the lattice to an external grid instead of to the data's own bounding box.
    Without it a raster starts wherever the ETC layer happens to end, which is fine for a
    standalone map and wrong the moment the pixels have to line up with a grid somebody else
    defined: an existing training grid whose cells must land on whole pixels, or a second run over
    a neighbouring extent. Measured on a real case — a 1 280 m training grid anchored at
    x=227744.5668 against a raster starting at its own data bounds — the two lattices sat
    0.998 px apart in x and 0.286 px in y, enough to misregister every patch cut from it.
    """
    if origin is not None:
        bounds = _snap(bounds, resolution_m, origin)
    minx, miny, maxx, maxy = bounds
    n_cols = max(1, math.ceil((maxx - minx) / resolution_m))
    n_rows = max(1, math.ceil((maxy - miny) / resolution_m))

    rows: list[int] = []
    cols: list[int] = []
    geoms = []
    for row in range(n_rows):
        y1 = maxy - row * resolution_m
        y0 = y1 - resolution_m
        for col in range(n_cols):
            x0 = minx + col * resolution_m
            geoms.append(box(x0, y0, x0 + resolution_m, y1))
            rows.append(row)
            cols.append(col)

    unit_ids = [f"px_{r}_{c}" for r, c in zip(rows, cols, strict=True)]
    grid = gpd.GeoDataFrame(
        {"unit_id": unit_ids, "row": rows, "col": cols}, geometry=geoms
    ).set_index("unit_id")
    return grid, n_rows, n_cols


def _area_weighted_mean(pieces: pd.DataFrame, column: str, grid_index: pd.Index) -> pd.Series:
    """Area-weighted mean of `column` per `unit_id`, over pieces where `column` is not null.

    Null pieces are dropped from **both** the numerator and the denominator — the weight total
    used is the area that actually carried a value, not the pixel's full covered area. Weighting
    by the full area while summing only non-null values would silently bias every mean toward
    zero wherever an attribute was null on part of a pixel, which is common: several morphometric
    columns are null exactly where an ETC has no qualifying neighbour.
    """
    valid = pieces.loc[pieces[column].notna(), ["unit_id", column, PIECE_AREA]]
    if valid.empty:
        return pd.Series(np.nan, index=grid_index, dtype="float64")
    weighted_sum = (valid[column] * valid[PIECE_AREA]).groupby(valid["unit_id"]).sum()
    weight_total = valid.groupby("unit_id")[PIECE_AREA].sum()
    mean = weighted_sum / weight_total.where(weight_total > 0)
    return mean.reindex(grid_index)


def _compute_band_stack(
    pieces: pd.DataFrame,
    attribute_columns: list[str],
    grid: gpd.GeoDataFrame,
    n_rows: int,
    n_cols: int,
) -> np.ndarray:
    """One `(bands, rows, cols)` float32 array, computed once regardless of format or tiling."""
    row_by_unit = grid["row"].to_numpy()
    col_by_unit = grid["col"].to_numpy()
    stack = np.full((len(attribute_columns), n_rows, n_cols), np.nan, dtype="float32")
    for band_index, column in enumerate(attribute_columns):
        values = _area_weighted_mean(pieces, column, grid.index)
        stack[band_index, row_by_unit, col_by_unit] = values.to_numpy()
    return stack


def _write_gdal_raster(
    stack: np.ndarray,
    transform: Affine,
    crs: CRS,
    band_names: Sequence[str],
    out_path: Path,
    *,
    driver: str,
) -> None:
    n_bands, n_rows, n_cols = stack.shape
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        out_path,
        "w",
        driver=driver,
        height=n_rows,
        width=n_cols,
        count=n_bands,
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=np.nan,
    ) as dst:
        dst.write(stack)
        for band_index, name in enumerate(band_names, start=1):
            dst.set_band_description(band_index, name)


def _write_zarr(
    stack: np.ndarray,
    transform: Affine,
    crs: CRS,
    band_names: Sequence[str],
    out_path: Path,
) -> None:
    """CF-convention Zarr, written through `xarray`/`rioxarray` rather than GDAL's own driver.

    A `spatial_ref` coordinate carries the CRS, referenced from the data variable's
    `grid_mapping` attribute — the convention `xr.open_zarr(path, decode_coords="all")` and any
    other CF-aware reader round-trips, confirmed directly rather than assumed (see
    `lczkit.config.RasterFormat`). `rioxarray`'s own `.rio.to_raster(..., driver="Zarr")` was
    tried first and rejected: it still writes through GDAL's `Zarr` driver underneath and loses
    the CRS the same way `rasterio.open(..., driver="Zarr")` does.
    """
    n_bands, n_rows, n_cols = stack.shape
    xs = transform.c + transform.a * (np.arange(n_cols) + 0.5)
    ys = transform.f + transform.e * (np.arange(n_rows) + 0.5)
    da = xr.DataArray(
        stack,
        dims=("band", "y", "x"),
        coords={"band": list(band_names), "y": ys, "x": xs},
        name="morphometrics",
    )
    da = da.rio.write_crs(crs.to_wkt()).rio.write_transform(transform)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    da.to_dataset().to_zarr(out_path, mode="w")


def _write_raster(
    stack: np.ndarray,
    transform: Affine,
    crs: CRS,
    band_names: Sequence[str],
    out_path: Path,
    *,
    format: RasterFormat,
) -> None:
    if format == "zarr":
        _write_zarr(stack, transform, crs, band_names, out_path)
    else:
        _write_gdal_raster(
            stack, transform, crs, band_names, out_path, driver=_GDAL_DRIVERS[format]
        )


def _tile_grid(
    bounds: tuple[float, float, float, float],
    crs: CRS,
    tile_deg: float,
    transform: Affine,
    n_rows: int,
    n_cols: int,
) -> list[tuple[str, Window]]:
    """Geotessera-style tile ids and their pixel windows over an `n_rows x n_cols` array.

    Tiles form a fixed global grid in EPSG:4326: tile `(i, j)` spans
    `[i*tile_deg, (i+1)*tile_deg) x [j*tile_deg, (j+1)*tile_deg)` and is named after its centre,
    `((i + 0.5) * tile_deg, (j + 0.5) * tile_deg)` — the same convention `geotessera`
    (github.com/ucam-eo/geotessera) uses for its own 0.1 degree grid (`grid_{lon:.2f}_{lat:.2f}`,
    centred on the half-step offset), so tile ids from the two tools agree.

    **Every row cut and column cut is reprojected and rounded exactly once**, and the same
    rounded pixel index is reused by the tile above it and the tile below it (respectively left
    and right). The first version of this function reprojected and rounded each tile's box
    independently, which can round a shared geographic edge to two different pixel rows on either
    side of it — a real, measured defect: two adjacent tiles left a one-pixel gap between them,
    caught by a test that stitches tiled output back together and compares it to the untiled
    raster. Sharing the boundary rules the gap (or an overlap) out by construction rather than by
    tolerance.

    The reprojection itself is still a bounding-rectangle approximation: each cut line uses the
    extent's own geographic centre as its cross-axis reference, since a UTM projection is not
    conformal with a geographic grid at the pixel level. Adequate at the ~10 km scale a 0.1 degree
    tile spans; stated here rather than left implicit.
    """
    minx, miny, maxx, maxy = bounds
    lon_min, lat_min, lon_max, lat_max = transform_bounds(crs, "EPSG:4326", minx, miny, maxx, maxy)
    lon_ref, lat_ref = (lon_min + lon_max) / 2.0, (lat_min + lat_max) / 2.0

    i_min, i_max = math.floor(lon_min / tile_deg), math.floor(lon_max / tile_deg)
    j_min, j_max = math.floor(lat_min / tile_deg), math.floor(lat_max / tile_deg)

    lon_edges = [i * tile_deg for i in range(i_min, i_max + 2)]
    lat_edges = [j * tile_deg for j in range(j_min, j_max + 2)]
    xs, _ = warp_transform("EPSG:4326", crs, lon_edges, [lat_ref] * len(lon_edges))
    _, ys = warp_transform("EPSG:4326", crs, [lon_ref] * len(lat_edges), lat_edges)

    col_at = {
        i: max(0, min(n_cols, round((x - transform.c) / transform.a)))
        for i, x in zip(range(i_min, i_max + 2), xs, strict=True)
    }
    # Rows increase southward while latitude increases northward, so row_at is built from the
    # same edges but read in reverse when paired into (top, bottom) below.
    row_at = {
        j: max(0, min(n_rows, round((transform.f - y) / -transform.e)))
        for j, y in zip(range(j_min, j_max + 2), ys, strict=True)
    }

    tiles: list[tuple[str, Window]] = []
    for i in range(i_min, i_max + 1):
        col_left, col_right = col_at[i], col_at[i + 1]
        if col_right <= col_left:
            continue
        for j in range(j_min, j_max + 1):
            row_top, row_bottom = row_at[j + 1], row_at[j]
            if row_bottom <= row_top:
                continue
            lon_c, lat_c = (i + 0.5) * tile_deg, (j + 0.5) * tile_deg
            name = f"grid_{lon_c:.2f}_{lat_c:.2f}"
            window = Window(
                col_off=col_left,
                row_off=row_top,
                width=col_right - col_left,
                height=row_bottom - row_top,
            )
            tiles.append((name, window))
    return tiles


def rasterize_attributes(
    gdf: gpd.GeoDataFrame,
    resolution_m: float,
    out_path: Path,
    *,
    columns: list[str] | None = None,
    max_cells: int = 50_000_000,
    format: RasterFormat = "gtiff",
    tile_deg: float | None = None,
    max_bytes: int = 4_000_000_000,
    origin: tuple[float, float] | None = None,
) -> RasterExportReport:
    """Write `out_path` as a multiband raster, one band per attribute of `gdf`, area-weighted.

    `columns` defaults to every non-geometry column of `gdf`. Raises `ValueError` before building
    the grid if it would exceed `max_cells` (pixel count) or `max_bytes` (the in-memory band
    stack — every format now goes through one array built once, see `_compute_band_stack`) —
    refusing is cheap; an unbounded allocation is not.

    With `tile_deg` set, `out_path` is a directory and the output is one file per geographic tile
    (`lczkit.morphometrics.raster._tile_grid`) instead of one file for the whole extent. Without
    it, `out_path` is the single output file (or, for `format="zarr"`, the single output store
    directory) — the original, still-default behaviour.

    `origin` anchors the pixel lattice to an external grid rather than to `gdf`'s own bounds — see
    `_pixel_grid`. Pass the top-left corner of the grid the output has to register against; the
    extent is grown outward to that lattice, never cropped to it.
    """
    assert_projected_crs(gdf, "gdf")
    if resolution_m <= 0:
        raise ValueError(f"resolution_m must be positive, got {resolution_m}")
    if tile_deg is not None and tile_deg <= 0:
        raise ValueError(f"tile_deg must be positive, got {tile_deg}")
    assert gdf.crs is not None  # narrows for mypy; assert_projected_crs already guarantees this
    attribute_columns = (
        columns if columns is not None else [c for c in gdf.columns if c != "geometry"]
    )

    raw_bounds = gdf.total_bounds
    bounds = (
        _snap((raw_bounds[0], raw_bounds[1], raw_bounds[2], raw_bounds[3]), resolution_m, origin)
        if origin is not None
        else (raw_bounds[0], raw_bounds[1], raw_bounds[2], raw_bounds[3])
    )
    grid, n_rows, n_cols = _pixel_grid(bounds, resolution_m)
    if n_rows * n_cols > max_cells:
        raise ValueError(
            f"a {resolution_m} m grid over this extent would be {n_rows}x{n_cols} = "
            f"{n_rows * n_cols} cells, over the configured ceiling of {max_cells} "
            "(MorphometricsConfig.max_raster_cells)"
        )
    projected_bytes = len(attribute_columns) * n_rows * n_cols * 4
    if projected_bytes > max_bytes:
        raise ValueError(
            f"a {resolution_m} m grid over this extent with {len(attribute_columns)} attributes "
            f"would need ~{projected_bytes / 1e9:.2f} GB in memory (bands x rows x cols x 4 "
            f"bytes), over the configured ceiling of {max_bytes / 1e9:.2f} GB "
            "(MorphometricsConfig.max_raster_bytes) — rasterize fewer columns, a coarser "
            "resolution, or raise the ceiling"
        )
    grid = grid.set_geometry(grid.geometry, crs=gdf.crs)

    pieces = unit_pieces(grid, gdf, columns=attribute_columns)
    stack = _compute_band_stack(pieces, attribute_columns, grid, n_rows, n_cols)

    minx, _, _, maxy = bounds
    transform = from_origin(minx, maxy, resolution_m, resolution_m)
    crs = CRS.from_user_input(gdf.crs)

    if tile_deg is None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _write_raster(stack, transform, crs, attribute_columns, out_path, format=format)
        return RasterExportReport(
            resolution_m=resolution_m,
            n_rows=n_rows,
            n_cols=n_cols,
            band_names=tuple(attribute_columns),
            format=format,
            tile_deg=None,
            tiles=(),
        )

    out_path.mkdir(parents=True, exist_ok=True)
    ext = _tile_ext(format)
    raster_bounds = (minx, maxy - n_rows * resolution_m, minx + n_cols * resolution_m, maxy)
    written: list[str] = []
    for name, window in _tile_grid(raster_bounds, crs, tile_deg, transform, n_rows, n_cols):
        row_off, col_off = int(window.row_off), int(window.col_off)
        tile_array = stack[
            :, row_off : row_off + int(window.height), col_off : col_off + int(window.width)
        ]
        if not np.isfinite(tile_array).any():
            continue
        tile_transform = window_transform(window, transform)
        filename = f"{name}{ext}"
        _write_raster(
            tile_array, tile_transform, crs, attribute_columns, out_path / filename, format=format
        )
        written.append(filename)

    return RasterExportReport(
        resolution_m=resolution_m,
        n_rows=n_rows,
        n_cols=n_cols,
        band_names=tuple(attribute_columns),
        format=format,
        tile_deg=tile_deg,
        tiles=tuple(sorted(written)),
    )


def refresh_raster(
    run_dir: Path,
    resolution_m: float,
    *,
    columns: list[str] | None = None,
    max_cells: int = 50_000_000,
    format: RasterFormat = "gtiff",
    tile_deg: float | None = None,
    max_bytes: int = 4_000_000_000,
) -> RasterExportReport:
    """Re-derive the morphometrics raster(s) from an already-written run's `morphometrics.parquet`.

    The one function both `run_pipeline` (when `--morphometrics-resolution` is given) and
    `lczkit morphometrics raster` call — a run gets the same raster whether it was produced at
    run time or requested afterwards at a different resolution or format, because both paths go
    through this. Patches the manifest as JSON, the same way `lczkit.output.gis`'s backfill does:
    this can run against a manifest written by an older version of `RunManifest`, and
    round-tripping it through today's model would rewrite fields the run never had.

    A previous single-file or tiled output at a different format is never deleted — only appended
    to `manifest.outputs` — matching the project's standing convention of adding rather than
    overwriting a run's on-disk record (e.g. `lczkit export`'s `units.gpkg`).
    """
    morphometrics_path = run_dir / MORPHOMETRICS_FILE
    if not morphometrics_path.exists():
        raise FileNotFoundError(
            f"no {MORPHOMETRICS_FILE} in {run_dir} — this run has no morphometrics to rasterize"
        )
    gdf = gpd.read_parquet(morphometrics_path)
    target = (
        run_dir / RASTER_TILE_DIR if tile_deg is not None else run_dir / raster_filename(format)
    )
    report = rasterize_attributes(
        gdf,
        resolution_m,
        target,
        columns=columns,
        max_cells=max_cells,
        format=format,
        tile_deg=tile_deg,
        max_bytes=max_bytes,
    )

    manifest_path = run_dir / MANIFEST_FILE
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["morphometrics_raster"] = report.as_manifest()
        outputs = list(manifest.get("outputs", []))
        output_entry = RASTER_TILE_DIR if tile_deg is not None else raster_filename(format)
        if output_entry not in outputs:
            outputs.append(output_entry)
        manifest["outputs"] = outputs
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return report
