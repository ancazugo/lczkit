"""Raster windowing shared by the places in the package that read or clip a raster.

Phase 3's height cascade reads a mean per building footprint; Phase 4's land-cover sources read
class fractions per spatial unit. Those are different reductions over different libraries, but
both begin by finding the one window of a raster that covers a set of geometries, and getting the
edge padding wrong is a quiet off-by-one rather than a crash. It lives here, next to `crs.py`,
because it belongs to neither phase.

`clip_raster` and `coverage_shortfall` join them because a run has to *materialise* a window before
it can reduce over one — the global land-cover and reference products are read remotely and written
into the run directory. They were script-local until Phase 15, which is how the publish driver came
to clip Berlin's tile for every city; see `lczkit.sources.worldcover`.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio import windows
from rasterio.windows import from_bounds

from lczkit.protocols import BBox


def covering_window(
    src: rasterio.DatasetReader, bounds: np.ndarray | tuple[float, float, float, float]
) -> windows.Window | None:
    """The raster window covering `bounds`, padded one cell and clipped to the raster.

    `bounds` is `(minx, miny, maxx, maxy)` in the raster's own CRS. Returns `None` when it falls
    entirely outside the raster, which callers report as "this product cannot answer" rather than
    as an error.

    The one-cell pad matters at the edges: a geometry whose boundary sits exactly on a cell
    boundary still touches the cell beyond it, and that cell has to be inside the window to be
    counted at all.
    """
    raw = windows.from_bounds(*bounds, transform=src.transform)
    col_off = max(0, math.floor(raw.col_off) - 1)
    row_off = max(0, math.floor(raw.row_off) - 1)
    col_end = min(src.width, math.ceil(raw.col_off + raw.width) + 1)
    row_end = min(src.height, math.ceil(raw.row_off + raw.height) + 1)
    if col_end <= col_off or row_end <= row_off:
        return None
    return windows.Window(col_off, row_off, col_end - col_off, row_end - row_off)


def clip_raster(source: str, destination: Path, bbox: BBox) -> Path:
    """Window `source` to `bbox` and write it into the run directory, preserving nodata and CRS."""
    with rasterio.open(source) as src:
        window = from_bounds(*bbox, transform=src.transform)
        values = src.read(1, window=window)
        profile = src.profile | {
            "driver": "GTiff",
            "height": values.shape[0],
            "width": values.shape[1],
            "transform": src.window_transform(window),
            "compress": "deflate",
            "tiled": False,
            "count": 1,
        }
    with rasterio.open(destination, "w", **profile) as dst:
        dst.write(values, 1)
    return destination


def coverage_shortfall(
    bounds: tuple[float, float, float, float], bbox: BBox, res: float
) -> dict[str, float]:
    """How far a raster's `bounds` fall short of `bbox` on each side, in pixels.

    Empty when the raster covers the window. A shortfall under one pixel is not reported: a clip
    lands on cell boundaries, so a fraction of a cell is rounding rather than missing ground.

    Separated out because the failure this guards against is silent. `clip_raster` windows with
    `from_bounds` and then `read(window=...)`, which **returns a smaller array** rather than
    raising when the window overruns the source, and `LocalRasterSource.fractions` turns units
    with no coverage into all-`NaN` rather than an error. Both behaviours are correct on their
    own; together they let a raster that covers a quarter of the requested window produce a map
    with a quarter of its land cover missing and nothing anywhere saying so.
    """
    left, bottom, right, top = bounds
    minx, miny, maxx, maxy = bbox
    gaps = {
        "west": (left - minx) / res,
        "south": (bottom - miny) / res,
        "east": (maxx - right) / res,
        "north": (maxy - top) / res,
    }
    return {side: round(gap, 3) for side, gap in gaps.items() if gap > 1.0}
