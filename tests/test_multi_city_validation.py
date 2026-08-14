"""The WorldCover tiling, and the guard that makes a short mosaic loud.

**Why this file exists.** Phase 7's publish driver clipped land cover from a single hardcoded
tile — Berlin's `N51E012`. Hong Kong and Cairo each span two, so both raised
`RasterioIOError: 0x0 dataset` and the bug was found. That was luck: those two windows miss
Berlin's tile *entirely*. A city one tile-width away would have been partially covered instead,
and the failure would have been silent, because two correct behaviours compose into one:

- `clip_raster` windows with `from_bounds` and then `read(window=...)`, which returns a **smaller
  array** rather than raising when the window overruns the source; and
- `LocalRasterSource.fractions` returns **all-`NaN`** for units with no coverage rather than an
  error — intended, and tested by `test_a_unit_outside_the_raster_is_null_not_zero`.

So a partial raster yields NaN land cover over the uncovered strip and no error anywhere. Since
the rasters are the *sole* classifier for LCZ A-G, that is a quarter of a map's natural classes
going missing quietly. Nothing asserted the precondition until this file.

The sixteen validation runs were checked against their persisted rasters and are clean — every
one covers its window to within half a pixel. These tests keep it that way.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from lczkit.protocols import BBox


def load_script() -> ModuleType:
    """Import `scripts/berlin_wide_validation.py` by path, for the reason its sibling tests give:
    `scripts/` holds one-off analyses and is deliberately not importable as a package."""
    path = Path(__file__).resolve().parent.parent / "scripts" / "berlin_wide_validation.py"
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location("berlin_wide_validation", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(path.parent))


SCRIPT = load_script()

#: The windows the published sixteen-city results were computed over, read back from the Phase 13
#: run record. `densest_window` is deterministic, so these are stable — a change here means the
#: windows moved, which would make two runs of the same city incomparable and is worth failing on.
CITY_WINDOWS: dict[str, BBox] = {
    "berlin": (13.229306, 52.353092, 13.673155, 52.623362),
    "london": (-0.185997, 51.421780, 0.248705, 51.692050),
    "paris": (2.096941, 48.619452, 2.506885, 48.889723),
    "cologne": (6.644759, 50.817198, 7.073782, 51.087468),
    "rome": (12.275811, 41.771021, 12.638960, 42.041292),
    "milan": (9.037019, 45.260627, 9.421906, 45.530898),
    "sao_paulo": (-46.755568, -23.673923, -46.460768, -23.403652),
    "rio_de_janeiro": (-43.722921, -22.992147, -43.429620, -22.721877),
    "cairo": (31.044940, 29.824326, 31.356894, 30.094596),
    "nairobi": (36.707775, -1.474760, 36.978119, -1.204490),
    "cape_town": (18.359733, -34.064630, 18.685468, -33.794360),
    "islamabad": (72.933324, 33.503450, 73.257954, 33.773720),
    "mumbai": (72.813340, 18.921078, 73.099280, 19.191348),
    "jakarta": (106.679038, -6.308668, 106.950885, -6.038397),
    "hong_kong": (113.972151, 22.212201, 114.264368, 22.482471),
    "vancouver": (-123.308623, 49.055586, -122.895077, 49.325857),
}

#: Six of the sixteen straddle a tile boundary. Recorded rather than derived so that a change in
#: the tile arithmetic that quietly stopped mosaicking would fail here rather than pass.
SPAN_TWO_TILES = {"london", "cologne", "rome", "cairo", "hong_kong", "vancouver"}


def tile_bounds(url: str) -> BBox:
    """Decode a WorldCover tile URL back to the 3-degree box it covers.

    Parsed from the filename rather than taken from a table, so this is an independent reading of
    the naming convention. A test that built the name the same way the code does would agree with
    it by construction and prove nothing.
    """
    name = url.rsplit("/", 1)[-1]
    corner = name.split("_")[-2]
    lat = int(corner[1:3]) * (1 if corner[0] == "N" else -1)
    lon = int(corner[4:7]) * (1 if corner[3] == "E" else -1)
    step = SCRIPT.WORLDCOVER_TILE_DEG
    return (lon, lat, lon + step, lat + step)


def covered(bbox: BBox, urls: list[str], n: int = 25) -> bool:
    """Whether the union of `urls` covers `bbox`, by sampling the window on a dense grid.

    Sampled rather than computed from the tile grid on purpose. The first version of this walked
    the window in 3-degree strides from its lower-left corner, which for a 0.4-degree city window
    samples exactly one point and so returned `True` for every straddling city even when the
    second tile was missing — it agreed with the implementation by construction. Sampling knows
    nothing about the tiling and fails when any part of the window is unreachable.
    """
    minx, miny, maxx, maxy = bbox
    boxes = [tile_bounds(url) for url in urls]
    for i in range(n + 1):
        x = minx + (maxx - minx) * i / n
        for j in range(n + 1):
            y = miny + (maxy - miny) * j / n
            if not any(
                left <= x <= right and bottom <= y <= top for left, bottom, right, top in boxes
            ):
                return False
    return True


@pytest.mark.parametrize("city", sorted(CITY_WINDOWS))
def test_every_published_city_window_is_covered_by_the_tiles_resolved_for_it(city: str) -> None:
    """The assertion the sixteen-city results rest on, per city."""
    bbox = CITY_WINDOWS[city]
    urls = SCRIPT.worldcover_tiles(bbox)
    assert covered(bbox, urls), (
        f"{city}: tiles {[u.rsplit('/', 1)[-1] for u in urls]} do not cover {bbox}"
    )


@pytest.mark.parametrize("city", sorted(CITY_WINDOWS))
def test_no_city_resolves_more_tiles_than_it_needs(city: str) -> None:
    """Coverage alone is satisfiable by fetching the whole world. Each tile must be touched."""
    bbox = CITY_WINDOWS[city]
    urls = SCRIPT.worldcover_tiles(bbox)
    for url in urls:
        left, bottom, right, top = tile_bounds(url)
        assert left < bbox[2] and right > bbox[0] and bottom < bbox[3] and top > bbox[1], (
            f"{city}: {url.rsplit('/', 1)[-1]} does not intersect {bbox}"
        )


def test_the_cities_that_straddle_a_tile_boundary_still_do() -> None:
    """The mosaic path is exercised by real inputs, not merely present.

    If this set ever empties, every city fits one tile and the single-tile branch is the only one
    the sixteen-city runs ever took — which is exactly the state Phase 7's driver was in.
    """
    spanning = {
        city for city, bbox in CITY_WINDOWS.items() if len(SCRIPT.worldcover_tiles(bbox)) > 1
    }
    assert spanning == SPAN_TWO_TILES


def test_berlins_tile_does_not_cover_hong_kong_or_cairo() -> None:
    """Phase 7's defect, as a regression case.

    The publish driver passed Berlin's `N51E012` for every city. These two are the windows that
    made it fail loudly; the test exists so the assumption cannot be reintroduced silently.
    """
    berlin_tile = SCRIPT.worldcover_tiles(CITY_WINDOWS["berlin"])
    assert len(berlin_tile) == 1 and "N51E012" in berlin_tile[0]
    for city in ("hong_kong", "cairo"):
        assert not covered(CITY_WINDOWS[city], berlin_tile)
        assert len(SCRIPT.worldcover_tiles(CITY_WINDOWS[city])) == 2


@pytest.mark.parametrize(
    ("name", "bbox", "n_tiles"),
    [
        ("inside one tile", (13.3, 52.4, 13.5, 52.6), 1),
        ("straddling east-west", (14.9, 52.4, 15.1, 52.6), 2),
        ("straddling north-south", (13.3, 53.9, 13.5, 54.1), 2),
        ("four tile corners", (14.9, 53.9, 15.1, 54.1), 4),
        ("negative longitude", (-123.3, 49.0, -122.9, 49.3), 2),
        ("southern hemisphere", (18.4, -34.1, 18.7, -33.8), 1),
        ("straddling the equator", (36.7, -0.1, 36.9, 0.1), 2),
        ("straddling the prime meridian", (-0.2, 51.4, 0.2, 51.7), 2),
    ],
)
def test_the_tile_arithmetic_holds_at_the_awkward_places(
    name: str, bbox: BBox, n_tiles: int
) -> None:
    """Sign handling and grid snapping, where an off-by-one is a whole missing tile."""
    urls = SCRIPT.worldcover_tiles(bbox)
    assert len(urls) == n_tiles, f"{name}: {[u.rsplit('/', 1)[-1] for u in urls]}"
    assert covered(bbox, urls), name


def test_a_raster_that_covers_the_window_reports_no_shortfall() -> None:
    assert SCRIPT.coverage_shortfall((0.0, 0.0, 10.0, 10.0), (1.0, 1.0, 9.0, 9.0), 0.1) == {}


def test_a_sub_pixel_shortfall_is_rounding_not_missing_ground() -> None:
    """A clip lands on cell boundaries, so every real run is short by a fraction of a cell. The
    sixteen stored runs sit at 0.45 px; a guard that fired on those would be useless."""
    bounds = (1.0 + 0.045, 1.0 + 0.045, 9.0 - 0.045, 9.0 - 0.045)
    assert SCRIPT.coverage_shortfall(bounds, (1.0, 1.0, 9.0, 9.0), 0.1) == {}


@pytest.mark.parametrize(
    ("side", "bounds"),
    [
        ("west", (2.0, 1.0, 9.0, 9.0)),
        ("south", (1.0, 2.0, 9.0, 9.0)),
        ("east", (1.0, 1.0, 8.0, 9.0)),
        ("north", (1.0, 1.0, 9.0, 8.0)),
    ],
)
def test_a_short_raster_names_the_side_it_is_short_on(
    side: str, bounds: tuple[float, float, float, float]
) -> None:
    """Naming the side is the point: a shortfall on one edge is a strip of the map with no land
    cover, and the reader needs to know which strip without reopening the raster."""
    short = SCRIPT.coverage_shortfall(bounds, (1.0, 1.0, 9.0, 9.0), 0.1)
    assert set(short) == {side}
    assert short[side] == pytest.approx(10.0)
