"""Raster windowing shared by the two places in the package that read a raster.

Phase 3's height cascade reads a mean per building footprint; Phase 4's land-cover sources read
class fractions per spatial unit. Those are different reductions over different libraries, but
both begin by finding the one window of a raster that covers a set of geometries, and getting the
edge padding wrong is a quiet off-by-one rather than a crash. It lives here, next to `crs.py`,
because it belongs to neither phase.
"""

from __future__ import annotations

import math

import numpy as np
import rasterio
from rasterio import windows


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
