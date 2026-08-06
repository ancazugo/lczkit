"""A minimal local zonal read for the Phase 3 height cascade.

CLAUDE.md defers the `RasterSource` protocol and its Earth Engine backend to Phase 4, but tiers
2-4 need raster values now. This module is that stopgap, deliberately kept to one function so
Phase 4 can put a `RasterSource` call in its place by touching one line per tier.

It is *not* a general zonal-statistics implementation and should not grow into one — Phase 4
brings `exactextract` for that. What it does is read one window of one band and reduce it to a
mean per footprint, which is all tiers 2-4 ask for.
"""

from __future__ import annotations

import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import CRS
from rasterio import features, transform, windows


def zonal_mean(
    path: Path,
    geoms: gpd.GeoSeries,
    *,
    band: int = 1,
    nodata: float | None = None,
) -> np.ndarray:
    """Mean raster value under each geometry in `geoms`, as a float array aligned to `geoms`.

    Returns `nan` for any geometry the raster cannot answer for: outside its extent, or covering
    only nodata cells. That is a real answer — "this product does not know" — and the caller
    passes those rows on to the next tier rather than inventing a value.

    Cells are attributed with `all_touched=True`, so a footprint smaller than one cell still
    picks up the cell(s) it overlaps. For the coarse products this backs (~90-100 m), a building
    is typically far smaller than a cell and the result is that cell's neighbourhood mean, which
    is exactly what those products measure. Footprints that burn no cell at all fall back to the
    value at their representative point.

    `geoms` is reprojected to the raster's CRS internally; it must have a CRS set, and so must
    the raster. Overlapping geometries are resolved last-writer-wins by `rasterio.features`;
    Phase 1's planar enforcement means building footprints do not overlap, so this does not
    arise for the cascade's own use.
    """
    n = len(geoms)
    empty = np.full(n, np.nan, dtype="float64")
    if n == 0:
        return empty
    if geoms.crs is None:
        raise ValueError("geoms has no CRS set; cannot reproject to the raster's CRS.")

    with rasterio.open(path) as src:
        if src.crs is None:
            raise ValueError(f"{path} declares no CRS; cannot align it to the buildings layer.")
        projected = geoms.to_crs(CRS.from_user_input(src.crs.to_wkt()))
        window = _covering_window(src, projected.total_bounds)
        if window is None:
            return empty

        # Read unmasked and build the validity mask here, rather than via `masked=True`: it
        # keeps the file's declared nodata and the caller's override going through one code
        # path, and sidesteps rasterio's masked-read, which trips a NumPy 2.5 deprecation.
        values = src.read(band, window=window).astype("float64")
        declared_nodata = src.nodatavals[band - 1]
        win_transform = src.window_transform(window)

    valid = np.isfinite(values)
    for sentinel in (declared_nodata, nodata):
        if sentinel is not None:
            valid &= values != sentinel

    # Label 0 is the "no footprint here" background, so labels are 1-based and the bincount
    # results are sliced from index 1.
    labels = features.rasterize(
        ((geom, index) for index, geom in enumerate(projected, start=1) if geom is not None),
        out_shape=values.shape,
        transform=win_transform,
        fill=0,
        all_touched=True,
        dtype="int32",
    )

    flat_labels = labels[valid]
    counts = np.bincount(flat_labels, minlength=n + 1)[1:]
    sums = np.bincount(flat_labels, weights=values[valid], minlength=n + 1)[1:]
    means = np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)

    unburnt = np.flatnonzero(counts == 0)
    if unburnt.size:
        means[unburnt] = _sample_representative_points(
            gpd.GeoSeries(projected.iloc[unburnt]), values, valid, win_transform
        )
    return means


def _covering_window(src: rasterio.DatasetReader, bounds: np.ndarray) -> windows.Window | None:
    """The raster window covering `bounds`, padded one cell and clipped to the raster.

    Returns `None` when `bounds` falls entirely outside the raster. The one-cell pad matters for
    `all_touched` rasterization: a footprint whose edge sits exactly on a cell boundary touches
    the cell beyond it, and that cell must be in the window to be counted.
    """
    raw = windows.from_bounds(*bounds, transform=src.transform)
    col_off = max(0, math.floor(raw.col_off) - 1)
    row_off = max(0, math.floor(raw.row_off) - 1)
    col_end = min(src.width, math.ceil(raw.col_off + raw.width) + 1)
    row_end = min(src.height, math.ceil(raw.row_off + raw.height) + 1)
    if col_end <= col_off or row_end <= row_off:
        return None
    return windows.Window(col_off, row_off, col_end - col_off, row_end - row_off)


def _sample_representative_points(
    geoms: gpd.GeoSeries,
    values: np.ndarray,
    valid: np.ndarray,
    win_transform: transform.Affine,
) -> np.ndarray:
    """Single-cell fallback for footprints that burnt no cell during rasterization."""
    points = geoms.representative_point()
    rows, cols = transform.rowcol(win_transform, points.x.to_numpy(), points.y.to_numpy())
    rows = np.asarray(rows)
    cols = np.asarray(cols)
    in_window = (rows >= 0) & (rows < values.shape[0]) & (cols >= 0) & (cols < values.shape[1])
    sampled = np.full(len(geoms), np.nan, dtype="float64")
    if not in_window.any():
        return sampled
    hit_rows, hit_cols = rows[in_window], cols[in_window]
    usable = valid[hit_rows, hit_cols]
    sampled[np.flatnonzero(in_window)[usable]] = values[hit_rows[usable], hit_cols[usable]]
    return sampled
