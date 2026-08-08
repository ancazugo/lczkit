"""Tests for the tile geometry underpinning Phase 8's chunked street simplification.

The load-bearing property is that cores **partition** the covered area. Concatenating per-tile
results is only safe if no ground is covered twice and none is missed, and the way that fails is
silent: an overlap double-counts a street, a gap loses one, and both look like ordinary
simplification noise downstream. Phase 2 learned this the expensive way when
`momepy.enclosures(clip=False)` returned 222 percent of the Berlin extent and every
area-weighted denominator downstream was quietly wrong.
"""

from __future__ import annotations

import geopandas as gpd
import pytest
import shapely
from shapely.geometry import box

from lczkit.cleaning.tiles import build_tiles, layer_extent, subset

EXTENT = box(0.0, 0.0, 4000.0, 4000.0)


def test_tiles_cover_the_extent_completely() -> None:
    tiles = build_tiles(EXTENT, tile_size_m=2000.0, buffer_m=300.0)
    covered = shapely.union_all([tile.core for tile in tiles])
    assert covered.covers(EXTENT)


def test_tile_cores_do_not_overlap() -> None:
    """A partition, asserted pairwise rather than by total area — equal areas can still overlap."""
    tiles = build_tiles(EXTENT, tile_size_m=2000.0, buffer_m=300.0)
    for i, first in enumerate(tiles):
        for second in tiles[i + 1 :]:
            assert first.core.intersection(second.core).area == pytest.approx(0.0)


def test_windows_extend_beyond_cores_by_the_buffer() -> None:
    (tile,) = build_tiles(box(10.0, 10.0, 20.0, 20.0), tile_size_m=2000.0, buffer_m=250.0)
    assert tile.window.contains(tile.core)
    assert tile.core.exterior.distance(tile.window.exterior) == pytest.approx(250.0, abs=1.0)


def test_tiles_align_to_the_crs_origin_not_the_extent() -> None:
    """Two overlapping extents must yield the same tile where they overlap, or the per-tile
    cache is unusable across runs: a cached tile would depend on which bbox first asked for it.
    """
    left = build_tiles(box(0.0, 0.0, 4000.0, 4000.0), tile_size_m=2000.0, buffer_m=100.0)
    right = build_tiles(box(1500.0, 1500.0, 5500.0, 5500.0), tile_size_m=2000.0, buffer_m=100.0)
    shared = {t.key for t in left} & {t.key for t in right}
    assert shared
    by_key = {t.key: t for t in right}
    for tile in left:
        if tile.key in shared:
            assert tile.core.equals(by_key[tile.key].core)


def test_only_tiles_meeting_the_extent_are_returned() -> None:
    """A study area that is not a filled rectangle must not pay for its empty corners.

    A river corridor or a coastal city is the real case: its bounding box is square, the data
    is not, and simplifying empty tiles is wasted wall time on the critical path.
    """
    corridor = box(100.0, 100.0, 3900.0, 500.0)
    tiles = build_tiles(corridor, tile_size_m=2000.0, buffer_m=100.0)
    assert len(tiles) == 2
    assert {tile.key for tile in tiles} == {"tile_0_0", "tile_1_0"}
    assert all(tile.core.intersects(corridor) for tile in tiles)


def test_build_tiles_rejects_nonsense() -> None:
    with pytest.raises(ValueError, match="tile_size_m must be positive"):
        build_tiles(EXTENT, tile_size_m=0.0, buffer_m=100.0)
    with pytest.raises(ValueError, match="buffer_m must be non-negative"):
        build_tiles(EXTENT, tile_size_m=1000.0, buffer_m=-1.0)
    with pytest.raises(ValueError, match="is empty"):
        build_tiles(shapely.Polygon(), tile_size_m=1000.0, buffer_m=100.0)


def test_layer_extent_spans_every_layer() -> None:
    left = gpd.GeoDataFrame(geometry=[box(0.0, 0.0, 10.0, 10.0)], crs="EPSG:32633")
    right = gpd.GeoDataFrame(geometry=[box(90.0, 90.0, 100.0, 100.0)], crs="EPSG:32633")
    assert layer_extent(left, right).bounds == (0.0, 0.0, 100.0, 100.0)


def test_layer_extent_ignores_empty_layers() -> None:
    populated = gpd.GeoDataFrame(geometry=[box(0.0, 0.0, 10.0, 10.0)], crs="EPSG:32633")
    empty = gpd.GeoDataFrame(geometry=[], crs="EPSG:32633")
    assert layer_extent(populated, empty).bounds == (0.0, 0.0, 10.0, 10.0)
    with pytest.raises(ValueError, match="every layer is empty"):
        layer_extent(empty)


def test_subset_takes_whole_features_not_clipped_ones() -> None:
    """neatnet decides a street's fate from its full shape, so a tile must receive it whole."""
    crossing = shapely.LineString([(-500.0, 50.0), (500.0, 50.0)])
    layer = gpd.GeoDataFrame(geometry=[crossing], crs="EPSG:32633")
    taken = subset(layer, box(0.0, 0.0, 100.0, 100.0))
    assert len(taken) == 1
    assert taken.geometry.iloc[0].length == pytest.approx(1000.0)


def test_subset_requires_a_projected_crs() -> None:
    layer = gpd.GeoDataFrame(geometry=[box(0.0, 0.0, 1.0, 1.0)], crs="EPSG:4326")
    with pytest.raises(ValueError, match="projected CRS"):
        subset(layer, box(0.0, 0.0, 1.0, 1.0))
