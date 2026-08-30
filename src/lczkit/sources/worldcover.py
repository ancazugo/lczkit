"""Placing the ESA WorldCover window a run's land cover is reduced over.

`LocalRasterSource` reads a COG the caller placed, which is what happens for a run whose
`LandCoverDatasetConfig.filename` is set. This module is the other half, for a run that names a
bbox and expects the land cover to follow — the same split `sources.height_products` makes for
tiers 2-4.

**Why this is a module and not four lines at a call site.** WorldCover ships on a 3-degree grid.
A 30 km window usually lands inside one tile and sometimes spans two or four, and the failure when
it spans two is not an error: `clip_raster` windows with `from_bounds` and `read(window=...)`
returns a *smaller array*, while `LocalRasterSource.fractions` turns uncovered units into
all-`NaN`. Two individually-correct behaviours compose into a map missing a quarter of its land
cover with nothing saying so — and land cover is the sole classifier for LCZ A-G, so a window
that spans two WorldCover tiles and reads only one loses a whole edge of the map.
`clip_worldcover` therefore reopens what it wrote and raises, naming the short side.

**Where it writes.** Into the run directory, never into `input/`. A clip keyed to one run's bbox
is not a source cache, and `input/` is shared with other projects.
"""

from __future__ import annotations

import math
from pathlib import Path

import rasterio
from rasterio.merge import merge as merge_rasters

from lczkit.protocols import BBox
from lczkit.raster_window import clip_raster, coverage_shortfall

WORLDCOVER_BASE = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"
WORLDCOVER_TILE_DEG = 3
"""ESA WorldCover v200 ships on a 3-degree grid named for each tile's lower-left corner. Read as
remote COGs over range requests, the way `scripts/build_landcover_fixture.py` reads them."""


def worldcover_tiles(bbox: BBox) -> list[str]:
    """Every ESA WorldCover v200 tile URL covering `bbox`.

    A 30 km window is about a quarter of a degree and usually lands inside one 3-degree tile, but
    nothing makes it do so — a city near a tile corner needs two or four. Returning the list and
    mosaicking is the only version of this that is correct everywhere, and a single-tile guess
    would fail as a band of nodata down one side of the map rather than as an error.
    """
    minx, miny, maxx, maxy = bbox
    step = WORLDCOVER_TILE_DEG
    lons = range(math.floor(minx / step) * step, math.floor(maxx / step) * step + 1, step)
    lats = range(math.floor(miny / step) * step, math.floor(maxy / step) * step + 1, step)
    urls = []
    for lat in lats:
        for lon in lons:
            ns = f"N{lat:02d}" if lat >= 0 else f"S{abs(lat):02d}"
            ew = f"E{lon:03d}" if lon >= 0 else f"W{abs(lon):03d}"
            urls.append(f"{WORLDCOVER_BASE}/ESA_WorldCover_10m_2021_v200_{ns}{ew}_Map.tif")
    return urls


def clip_worldcover(bbox: BBox, destination: Path) -> Path:
    """Mosaic whichever WorldCover tiles `bbox` spans and write the window into the run dir."""
    urls = worldcover_tiles(bbox)
    if len(urls) == 1:
        clip_raster(urls[0], destination, bbox)
    else:
        sources = [rasterio.open(url) for url in urls]
        try:
            values, transform = merge_rasters(sources, bounds=bbox)
            profile = sources[0].profile | {
                "driver": "GTiff",
                "height": values.shape[1],
                "width": values.shape[2],
                "transform": transform,
                "compress": "deflate",
                "tiled": False,
                "count": 1,
            }
        finally:
            for source in sources:
                source.close()
        with rasterio.open(destination, "w", **profile) as dst:
            dst.write(values[0], 1)

    with rasterio.open(destination) as written:
        short = coverage_shortfall(tuple(written.bounds), bbox, written.res[0])
    if short:
        raise ValueError(
            f"WorldCover mosaic for {bbox} falls short of the requested window by "
            f"{short} pixels; tiles used: {[url.rsplit('/', 1)[-1] for url in urls]}. "
            "Land cover is the sole classifier for LCZ A-G, so a partial raster would be "
            "silently missing classes rather than failing."
        )
    return destination
