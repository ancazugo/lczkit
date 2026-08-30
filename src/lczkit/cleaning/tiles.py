"""Square tiles with buffered working windows, for chunking work that is superlinear in extent.

This exists because `neatnet.neatify` is superlinear in the extent handed to it. Measured on
Berlin, with everything else in `clean_vectors` held constant:

    extent    streets   neatify    largest rook-connected artifact component
      1 km2       706      9.6 s       538
      9 km2      6428     93.4 s      3658
     36 km2     21168    580.3 s     13348
    100 km2     51682   2983.3 s     32966

The exponent in area climbs from 0.95 (1 -> 4 km2) to 1.67 (36 -> 64 km2), because face
artifacts percolate: 93 percent of them fall into a *single* rook-contiguous component, and
`neatify_clusters` simplifies each component as one unit. Extent does not merely add work, it
enlarges the single largest piece of work.

Superlinearity is exactly what makes tiling pay. Splitting an extent into `k` tiles cuts the
largest component roughly `k`-fold, so the total shrinks by about `k**(1 - p)` for exponent `p`
*before* any tile runs in parallel.

Tiles are aligned to the projected CRS's own coordinate origin rather than to the extent, the
same convention `lczkit.units.grid.GridUnits` uses. Two overlapping extents therefore produce
identical tile boundaries wherever they overlap, which is what lets a per-tile result be cached
and reused across runs whose bboxes differ.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import shapely
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry

from lczkit.crs import assert_projected_crs


@dataclass(frozen=True)
class Tile:
    """One tile: an exclusive `core` and the larger `window` actually computed over.

    `core` tiles partition the covered area exactly — no gaps, no overlaps — so concatenating
    per-tile results clipped to their cores neither duplicates nor drops ground. `window` is
    `core` expanded by the buffer, giving each tile enough surrounding context that a feature
    near the seam is decided with its neighbourhood present rather than truncated.
    """

    col: int
    row: int
    core: Polygon
    window: Polygon

    @property
    def key(self) -> str:
        """Stable identifier: the tile's position on the CRS-origin-aligned grid.

        Independent of which extent asked for it, so it is usable as a cache key.
        """
        return f"tile_{self.col}_{self.row}"


def build_tiles(
    extent: Polygon, *, tile_size_m: float, buffer_m: float, crs_hint: str = "extent"
) -> list[Tile]:
    """Tile `extent` into `tile_size_m` squares, each with a `buffer_m` working margin.

    `extent` must be in a projected CRS — the caller enforces that; the sizes here are metres.
    Only tiles whose core actually meets `extent` are returned, so an L-shaped or diagonal
    study area does not pay for the empty corners of its bounding box.
    """
    if tile_size_m <= 0:
        raise ValueError(f"tile_size_m must be positive, got {tile_size_m}")
    if buffer_m < 0:
        raise ValueError(f"buffer_m must be non-negative, got {buffer_m}")
    if extent.is_empty:
        raise ValueError(f"{crs_hint} is empty; nothing to tile")

    minx, miny, maxx, maxy = extent.bounds
    col_start, col_end = math.floor(minx / tile_size_m), math.floor(maxx / tile_size_m)
    row_start, row_end = math.floor(miny / tile_size_m), math.floor(maxy / tile_size_m)

    tiles: list[Tile] = []
    for col in range(col_start, col_end + 1):
        x0 = col * tile_size_m
        for row in range(row_start, row_end + 1):
            y0 = row * tile_size_m
            core = box(x0, y0, x0 + tile_size_m, y0 + tile_size_m)
            # `touches` rather than `intersects`: an extent whose maximum falls exactly on a
            # tile boundary — which is every extent snapped to a round grid — otherwise spawns a
            # column of tiles meeting it along a line and holding no area at all. Those tiles
            # then fail artifact detection, since a network with no faces cannot be indexed.
            if not core.intersects(extent) or core.touches(extent):
                continue
            tiles.append(Tile(col=col, row=row, core=core, window=core.buffer(buffer_m)))
    if not tiles:
        raise ValueError(f"{crs_hint} produced no tiles; check tile_size_m against its extent")
    return tiles


def shared_edges(tile: Tile, tiles: list[Tile]) -> BaseGeometry | None:
    """The parts of `tile`'s boundary that a neighbour in `tiles` will emit instead.

    Cores partition by *area*, but they share their boundary *lines*, and a road running along a
    seam lies in both. Clipping each tile to its closed core therefore emits that road twice —
    measured at 30.9 km of output from 24.0 km of input on a grid aligned to the tiling, which
    is not a contrived case: tiles are axis-aligned to the CRS origin and so are many streets.

    Ownership is resolved by giving every shared edge to the lower-indexed tile: each tile drops
    the linework lying along its right and top edges, because the neighbour on that side keeps
    it. Deterministic, and independent of the order tiles happen to be processed in.
    """
    present = {(other.col, other.row) for other in tiles}
    minx, miny, maxx, maxy = tile.core.bounds
    edges: list[BaseGeometry] = []
    if (tile.col + 1, tile.row) in present:
        edges.append(shapely.LineString([(maxx, miny), (maxx, maxy)]))
    if (tile.col, tile.row + 1) in present:
        edges.append(shapely.LineString([(minx, maxy), (maxx, maxy)]))
    return shapely.union_all(edges) if edges else None


def layer_extent(*layers: gpd.GeoDataFrame) -> Polygon:
    """The bounding box covering every non-empty layer in `layers`, in their shared CRS.

    Used to decide what to tile. Takes the union of bounds rather than of geometry: a tiling
    only needs to cover the data, and unioning a metropolitan street network to find that out
    would cost more than the tiling saves.
    """
    boxes = [box(*layer.total_bounds) for layer in layers if len(layer)]
    if not boxes:
        raise ValueError("every layer is empty; nothing to tile")
    return box(*shapely.union_all(boxes).bounds)


def subset(layer: gpd.GeoDataFrame, window: Polygon) -> gpd.GeoDataFrame:
    """Features of `layer` intersecting `window`, as a copy with a fresh index.

    Uses the spatial index rather than `.clip()`: geometry must reach a tile *whole*, because
    neatnet decides a street's fate from its full shape and a truncated one would be simplified
    against a shape that does not exist.

    **The positions are sorted, and that is load-bearing.** geopandas documents `sindex.query` as
    returning results in no guaranteed order ("often sorted, but there is no guarantee"), and
    `neatnet` simplifies a network as a function of the row order it receives — pinned by
    `test_simplification_depends_on_input_row_order`. Every layer arrives in one canonical order
    (`overture._canonical_order`, sorted by GERS id) so that two runs of a city agree; taking the
    query result unsorted here would silently undo that on the tiled path, leaving the
    order a property of the installed GEOS build rather than of the data. It also fed
    `pooled_artifact_threshold`, so a change in STRtree traversal would have moved the threshold and
    with it the tile cache key.
    """
    assert_projected_crs(layer, "layer")
    positions = np.sort(layer.sindex.query(window, predicate="intersects"))
    return layer.iloc[positions].reset_index(drop=True).copy()
