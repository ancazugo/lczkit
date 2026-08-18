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
from conftest import load_script

from lczkit.protocols import BBox

SCRIPT = load_script("berlin_wide_validation")


def load_multi_city() -> ModuleType:
    """`multi_city_validation.py` itself, for the tags and guards that live there.

    Registered in `sys.modules` before execution because `@dataclass` resolves its own module
    through it while the class body is processed, and fails outright if it is absent.
    """
    path = Path(__file__).resolve().parent.parent / "scripts" / "multi_city_validation.py"
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location("multi_city_validation", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(path.parent))


MULTI_CITY = load_multi_city()

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


def test_no_reporting_path_reads_the_retired_raw_axis_share() -> None:
    """Phase 12 Ruling 1 retired `share_of_disagreement` outright — "removed from reporting", not
    "use with care" — because it cannot carry a comparison in either direction. Not across cities,
    where the denominator is all disagreement and the natural-class share ranges 3.5% to 54.1%, and
    not between the axes, where height affords six confusable pairs to compactness's three so a
    null that never looks at the data awards it 3.9x more error.

    The field stays on `AxisSummary` — Phase 6.7 to 11 records depend on its definition and must
    not move silently — but the scripts that report must read `lift`. This one was the path never
    migrated: it went on medianing the raw share across sixteen cities for four phases after the
    ruling. The failure mode is a script quietly reading a field that still exists, so the guard
    has to be on the reading rather than on the field.
    """
    # `axis_reconciliation.py` is the one exemption, and it is the reason the ruling exists: its
    # table prints raw share, axis-eligible share and lift side by side because the *comparison
    # between them* is the Phase 12 measurement. Showing the broken quantity next to what replaces
    # it is the evidence; showing it alone is the defect.
    exempt = {"axis_reconciliation.py"}
    offenders = [
        f"{path.name}:{index + 1}"
        for path in (Path(__file__).resolve().parent.parent / "scripts").glob("*.py")
        if path.name not in exempt
        for index, line in enumerate(path.read_text().splitlines())
        if ('"share_of_disagreement"' in line or "'share_of_disagreement'" in line)
        and not line.lstrip().startswith("#")
    ]

    assert offenders == [], f"scripts still read the retired raw axis share: {offenders}"


def test_percent_of_ceiling_is_not_reported_anywhere() -> None:
    """The other committed ruling this script was violating. The ceiling is another estimator, not
    a bound: Vancouver scores 41.8% against a 36.7% ceiling, which as a ratio reads 114% and looks
    like an impossibility rather than what it is — lczkit beating `lcz_v3` in that city. Report the
    two side by side, or their difference in points."""
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    script = (scripts / "multi_city_validation.py").read_text()

    assert "/ r['ceiling']" not in script
    assert '/ r["ceiling"]' not in script
    assert "share of ceiling" not in script


def _provenance(*tiers: tuple[str, int]) -> dict:
    """A provenance dict shaped like the one `build_arms` returns."""
    return {
        "height_fill": {
            "tiers": [{"tier": name, "n_filled": filled} for name, filled in tiers],
        }
    }


def test_the_cascade_tag_names_the_tiers_that_actually_fired() -> None:
    """Phase 12's ruling: tag every stored diagnostic with the configuration it was measured under.
    Phase 9's records were untagged and read for three phases as though they described the shipped
    default, when they were measured at `none` — and Phase 10, which shipped `coarse`, was itself
    the intervention that invalidated them.

    Derived from what fired rather than from the config, because a tier configured but whose product
    is not on disk is silently skipped and the difference is invisible in the config.
    """
    assert MULTI_CITY._cascade_tag(_provenance(("overture_height", 900))) == "none"
    assert (
        MULTI_CITY._cascade_tag(
            _provenance(("overture_height", 900), ("wsf3d", 400), ("ghsl", 100))
        )
        == "coarse"
    )
    assert (
        MULTI_CITY._cascade_tag(
            _provenance(("overture_height", 900), ("gob25d", 50), ("wsf3d", 400), ("ghsl", 100))
        )
        == "full"
    )


def test_a_configured_tier_that_filled_nothing_is_not_counted_as_having_run() -> None:
    """The whole point of deriving the tag from the fill rather than the config. A tier whose raster
    is absent is skipped in silence, and a record tagged `coarse` that ran at `none` is exactly the
    mislabelling this function exists to prevent."""
    tag = MULTI_CITY._cascade_tag(_provenance(("overture_height", 900), ("wsf3d", 0), ("ghsl", 0)))

    assert tag == "none"


def test_the_tag_reads_the_structure_build_arms_actually_returns() -> None:
    """Guarding the shape, not just the logic. The tiers list sits at `height_fill.tiers`, and a
    lookup one level too shallow returns an empty list rather than raising — so every city would be
    tagged `none` and the tag would be worse than absent, because it would look measured."""
    shallow = {"tiers": [{"tier": "wsf3d", "n_filled": 400}]}

    assert MULTI_CITY._cascade_tag(shallow) == "none"
    assert MULTI_CITY._cascade_tag(_provenance(("wsf3d", 400), ("ghsl", 100))) == "coarse"


def test_the_sweep_and_the_package_share_one_city_registry() -> None:
    """`City`, `CITIES`, `BY_KEY`, `WINDOW_KM` and `densest_window` were defined **twice** between
    Phase 15 and Phase 18 — lifted into `lczkit.cities` so the CLI could resolve `--city`, and left
    behind in the sweep unchanged.

    Two registries of the same sixteen cities is the failure CLAUDE.md records for `CLEANING`: the
    two agree until one is edited, and then the sweep — the half that produces every published
    figure — is quietly running a different population from the command line. It was found by
    adding four cities, not by reading. Identity, not equality: two tuples that happen to match
    today is exactly the state this is here to rule out.
    """
    from lczkit import cities as package

    sweep = MULTI_CITY

    assert sweep.CITIES is package.CITIES
    assert sweep.BY_KEY is package.BY_KEY
    assert sweep.City is package.City
    assert sweep.densest_window is package.densest_window
    assert sweep.WINDOW_KM == package.WINDOW_KM


def test_the_cities_added_after_the_recorded_sweeps_are_marked_as_such() -> None:
    """Every stored figure in `docs/experiments/` is over the original sixteen. Twelve cities came
    later, so any comparison against a stored record has to intersect the city sets first —
    CLAUDE.md records pooling two populations as a mistake this project has already made, and
    reported 6.6% of deviation that was 0.0% once restricted.

    Pinned as a list rather than asserted by count, so that a twenty-ninth city is a deliberate edit
    here rather than a silently passing test.
    """
    from lczkit.cities import BY_KEY, CITIES

    added_after_the_recorded_sweeps = {
        # North America was n=1 (Vancouver); adding these reorganised the regional grouping.
        "los_angeles",
        "new_york",
        "washington_dc",
        "santiago",
        # East Asia was n=1 (Hong Kong); Oceania and West Asia were empty.
        "beijing",
        "guangzhou",
        "nanjing",
        "tokyo",
        "wuhan",
        "istanbul",
        "tehran",
        "sydney",
    }
    original_sixteen = {city.key for city in CITIES} - added_after_the_recorded_sweeps

    assert len(original_sixteen) == 16
    assert added_after_the_recorded_sweeps <= set(BY_KEY)


def test_the_regions_still_represented_by_one_city_are_the_ones_with_no_alternative() -> None:
    """A region of one cannot separate a regional effect from that city, and this project read a
    regional regularity off "Europe + N. America" for three phases while North America *was*
    Vancouver. When it grew to four the grouping reorganised, so n=1 is not a theoretical weakness
    here — it has already produced a wrong reading once.

    Two regions remain at one city and **cannot be fixed from the data on disk**, which is why they
    are pinned by name rather than merely tolerated:

    - **Southeast Asia** is Jakarta. The only other So2Sat city in the region is Quezon City /
      Manila, which carries 246 patches of a single class and fails the screen.
    - **Oceania** is Sydney. Melbourne passes So2Sat comfortably — 5 506 patches, 7 classes — but
      WUDAPT holds exactly *one* polygon there, so it has no second reference.

    Any figure grouped by either region is a figure about one city, and should say so. A new
    singleton appearing fails here; so does one of these two becoming fixable and not being fixed.
    """
    from collections import Counter

    from lczkit.cities import CITIES

    counts = Counter(city.region for city in CITIES)
    singletons = {region for region, n in counts.items() if n < 2}

    assert singletons == {"Southeast Asia", "Oceania"}
