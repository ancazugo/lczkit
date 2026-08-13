"""Unit tests for the tier 2-4 product fetchers, entirely offline.

Nothing here touches the network. The three products are large, remote and — for Open Buildings
— behind Earth Engine, so what is tested is the part that can be got wrong silently: which tile
covers which bbox, whether a request would exceed Earth Engine's caps, and whether a cache hit
can ever be a truncated file. The download itself is exercised over `file://`, which is the same
`urllib` path a real fetch takes.
"""

from __future__ import annotations

import urllib.error
from pathlib import Path

import numpy as np
import pytest
import rasterio
from conftest import write_height_raster

from lczkit.config import ArealTierConfig, HeightConfig, Settings
from lczkit.heights.tiers import build_cascade
from lczkit.sources.height_products import (
    MOLLWEIDE_ORIGIN_X,
    MOLLWEIDE_ORIGIN_Y,
    MOLLWEIDE_TILE_M,
    GhslBuiltHSource,
    OpenBuildings25dSource,
    Wsf3dSource,
    _download,
    _verify_tile_position,
    resolve_areal_tiers,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, run_id="test")


def _mollweide_tile(path: Path, row: int, column: int, *, inset: float = 0.0) -> Path:
    """A one-cell stand-in for a GHS-BUILT-H tile, placed on the real R2023A grid.

    `inset` shifts the tile's own bounds inside its nominal square, which is what the published
    product does where a tile meets the edge of the Mollweide world ellipse.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    return write_height_raster(
        path,
        np.array([[5.0]], dtype="float32"),
        origin=(
            MOLLWEIDE_ORIGIN_X + (column - 1) * MOLLWEIDE_TILE_M + inset,
            MOLLWEIDE_ORIGIN_Y - (row - 1) * MOLLWEIDE_TILE_M,
        ),
        cell_size_m=MOLLWEIDE_TILE_M - inset,
        crs="ESRI:54009",
        nodata=255.0,
    )


# --- GHS-BUILT-H tiling -------------------------------------------------------------------


def test_a_city_window_resolves_to_the_tile_that_really_holds_it(tmp_path: Path) -> None:
    """The tile names below were verified against the published product during Phase 10.

    This is the assertion that would have caught an origin off by one tile, which is the failure
    mode with no symptom: heights from the wrong continent, all finite, all plausible.
    """
    source = GhslBuiltHSource(_settings(tmp_path))
    expected = {
        (13.229, 52.353, 13.673, 52.623): (3, 20),  # Berlin
        (-46.80, -23.70, -46.45, -23.45): (12, 14),  # Sao Paulo
        (31.10, 29.92, 31.41, 30.18): (6, 21),  # Cairo
        (36.70, -1.40, 36.95, -1.15): (10, 22),  # Nairobi
        (18.30, -34.05, 18.60, -33.80): (14, 20),  # Cape Town
        (72.95, 33.55, 73.25, 33.80): (5, 25),  # Islamabad
        (106.70, -6.35, 107.00, -6.05): (10, 29),  # Jakarta
    }
    for bbox, tile in expected.items():
        assert source.tiles_for(bbox) == [tile], bbox


def test_a_window_spanning_a_tile_boundary_asks_for_both(tmp_path: Path) -> None:
    source = GhslBuiltHSource(_settings(tmp_path))
    inside = source.tiles_for((13.229, 52.353, 13.673, 52.623))
    spanning = source.tiles_for((8.0, 52.0, 14.0, 53.0))

    assert len(inside) == 1
    assert len(spanning) > 1
    assert inside[0] in spanning


def test_the_tile_name_matches_the_published_filename(tmp_path: Path) -> None:
    source = GhslBuiltHSource(_settings(tmp_path))

    assert source.tile_name(6, 21) == "GHS_BUILT_H_ANBH_E2018_GLOBE_R2023A_54009_100_V1_0_R6_C21"


def test_a_tile_cropped_to_its_data_extent_still_verifies(tmp_path: Path) -> None:
    """`R14_C20` is 400x300 km inside its nominal 1000 km square, and is not an error.

    Requiring the corners to match exactly — which is what this check did first — rejected Cape
    Town's tile outright.
    """
    _verify_tile_position(
        _mollweide_tile(tmp_path / "cropped.tif", 14, 20, inset=600_000.0), 14, 20
    )


def test_a_tile_outside_its_nominal_square_is_rejected(tmp_path: Path) -> None:
    displaced = _mollweide_tile(tmp_path / "displaced.tif", 6, 21)

    with pytest.raises(ValueError, match="R7_C21"):
        _verify_tile_position(displaced, 7, 21)


def test_a_tile_the_product_does_not_publish_is_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`R14_C19` falls outside the Mollweide world ellipse and is simply absent.

    A 404 there means "no data here", the same statement a nodata cell makes, so it must not stop
    a city whose other tile is fine.
    """
    source = GhslBuiltHSource(_settings(tmp_path))
    present = _mollweide_tile(source.directory / f"{source.tile_name(14, 20)}.tif", 14, 20)

    def refuse(url: str, destination: Path) -> Path:
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr("lczkit.sources.height_products._download", refuse)
    monkeypatch.setattr(source, "tiles_for", lambda bbox: [(14, 19), (14, 20)])

    assert source.ensure((18.3, -34.05, 18.6, -33.8)) == present


def test_no_tile_at_all_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = GhslBuiltHSource(_settings(tmp_path))

    def refuse(url: str, destination: Path) -> Path:
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr("lczkit.sources.height_products._download", refuse)

    with pytest.raises(FileNotFoundError, match="R3_C20"):
        source.ensure((13.229, 52.353, 13.673, 52.623))


# --- WSF-3D -------------------------------------------------------------------------------


def test_the_global_file_answers_for_every_window(tmp_path: Path) -> None:
    """One 2.1 GB tiled COG serves every city, so `ensure` must not clip per window.

    A per-window clip here would be a second copy of data already on disk, in a directory shared
    with other projects.
    """
    settings = _settings(tmp_path)
    source = Wsf3dSource(settings)
    placed = source.directory / source.config.filename
    placed.parent.mkdir(parents=True, exist_ok=True)
    placed.write_bytes(b"stand-in")

    berlin = source.ensure((13.229, 52.353, 13.673, 52.623))
    jakarta = source.ensure((106.70, -6.35, 107.00, -6.05))

    assert berlin == jakarta == placed


def test_wsf3d_carries_the_decimetre_gain_from_its_readme() -> None:
    """DLR stores height as int16 with "a gain factor of 0.1". Reading it as metres would report
    a ten-storey block as a kerbstone, and nothing downstream would flag it."""
    tier = next(t for t in Settings(data_dir=Path(".")).heights.areal_tiers if t.name == "wsf3d")

    assert tier.scale == pytest.approx(0.1)
    assert tier.nodata == pytest.approx(-32767.0)


def test_ghsl_carries_the_nodata_from_its_documentation() -> None:
    """GHSL Data Package 2023, p. 36: ANBH is Float32 with NoData 255 at 100 m. A 255 read as a
    height is a 255 m building, which no areal 100 m mean ever is."""
    tier = next(t for t in Settings(data_dir=Path(".")).heights.areal_tiers if t.name == "ghsl")

    assert tier.scale == pytest.approx(1.0)
    assert tier.nodata == pytest.approx(255.0)


# --- Open Buildings 2.5D ------------------------------------------------------------------


def test_sub_windows_stay_under_both_earth_engine_caps(tmp_path: Path) -> None:
    source = OpenBuildings25dSource(_settings(tmp_path))
    bbox = (31.10, 29.92, 31.41, 30.18)  # ~30 km, the Phase 10 window size

    windows = source.sub_windows(bbox)

    assert len(windows) > 1, "a 900 km2 window at 4 m is 56 Mpx and cannot be one request"
    for minx, miny, maxx, maxy in windows:
        metres = max(
            (maxx - minx) * 111_320.0 * np.cos(np.radians((miny + maxy) / 2)),
            (maxy - miny) * 110_540.0,
        )
        pixels = (metres / source.config.scale_m) ** 2
        assert pixels <= source.config.max_pixels_per_request
        assert pixels * 4 <= source.config.max_bytes_per_request


def test_sub_windows_tile_the_bbox_exactly(tmp_path: Path) -> None:
    """Gaps would be missing buildings; overlaps would be paid for twice."""
    source = OpenBuildings25dSource(_settings(tmp_path))
    bbox = (31.10, 29.92, 31.41, 30.18)

    windows = source.sub_windows(bbox)
    area = sum((w[2] - w[0]) * (w[3] - w[1]) for w in windows)

    assert area == pytest.approx((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
    assert min(w[0] for w in windows) == pytest.approx(bbox[0])
    assert max(w[2] for w in windows) == pytest.approx(bbox[2])


def test_a_cached_export_is_returned_without_touching_earth_engine(tmp_path: Path) -> None:
    """`ensure` imports `ee` only after the cache miss, so this passing proves it never got
    there — the export is keyed on bbox and year, and re-running a city is free."""
    source = OpenBuildings25dSource(_settings(tmp_path))
    bbox = (31.10, 29.92, 31.41, 30.18)
    destination = source.path_for(bbox)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"stand-in")

    assert source.ensure(bbox) == destination
    assert str(source.config.year) in destination.name


# --- download safety ----------------------------------------------------------------------


def test_an_existing_file_is_never_refetched_or_rewritten(tmp_path: Path) -> None:
    """`input/` is shared with other projects: a fetcher that rewrites is a fetcher that can
    corrupt someone else's run. The bogus URL is the assertion — reaching it would raise."""
    destination = tmp_path / "already-there.tif"
    destination.write_bytes(b"someone else's bytes")

    assert _download("http://0.0.0.0/does-not-exist", destination) == destination
    assert destination.read_bytes() == b"someone else's bytes"


def test_a_download_is_only_visible_once_complete(tmp_path: Path) -> None:
    """The `.partial` rename is what keeps a truncated file from looking like a cache hit — the
    next run would read it, get a short raster, and report nothing."""
    origin = tmp_path / "origin.bin"
    origin.write_bytes(b"payload" * 1000)
    destination = tmp_path / "fetched.bin"

    _download(origin.as_uri(), destination)

    assert destination.read_bytes() == origin.read_bytes()
    assert not list(tmp_path.glob("*.partial"))


def test_a_fetched_tile_reads_back_as_a_raster(tmp_path: Path) -> None:
    """End to end over `file://`: the same `urllib` path a real fetch takes, and a check that
    what lands on disk is openable rather than merely present."""
    origin = _mollweide_tile(tmp_path / "origin.tif", 6, 21)
    destination = tmp_path / "input" / "GHSL" / "fetched.tif"

    _download(origin.as_uri(), destination)

    with rasterio.open(destination) as src:
        assert src.crs is not None
        assert src.read(1)[0, 0] == pytest.approx(5.0)


# --- resolving a whole cascade ------------------------------------------------------------


class _StubProduct:
    """A fetcher that answers with a path, or with `None` for "no coverage here"."""

    def __init__(self, name: str, path: Path | None) -> None:
        self._name = name
        self._path = path
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    def ensure(self, bbox: tuple[float, float, float, float]) -> Path | None:
        del bbox
        self.calls += 1
        return self._path


#: Tier name to the `input/` subdirectory it owns, matching the shipped config.
_TIER_DIRS = {"gob25d": "GOB25D", "wsf3d": "WSF3D", "ghsl": "GHSL"}


def _stub_fetchers(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, **covered: bool
) -> dict[str, _StubProduct]:
    """Replace the three real fetchers with stubs, one per tier.

    A covered tier gets a one-cell raster written into the directory that tier really owns,
    because `resolve_areal_tiers` records `filename` *relative to* that directory — placing it
    anywhere else would pass a test the real cascade could not then open.
    """
    stubs = {}
    for name, source_dir_name in _TIER_DIRS.items():
        path = None
        if covered.get(name, True):
            path = settings.source_dir(source_dir_name) / "h.tif"
            path.parent.mkdir(parents=True, exist_ok=True)
            write_height_raster(
                path,
                np.array([[8.0]], dtype="float32"),
                origin=(0.0, 100.0),
                cell_size_m=100.0,
                crs="EPSG:32633",
            )
        stubs[name] = _StubProduct(name, path)
    for attribute, name in (
        ("OpenBuildings25dSource", "gob25d"),
        ("Wsf3dSource", "wsf3d"),
        ("GhslBuiltHSource", "ghsl"),
    ):
        monkeypatch.setattr(
            "lczkit.sources.height_products." + attribute,
            lambda settings, stub=stubs[name]: stub,
        )
    return stubs


def test_resolving_the_default_cascade_leaves_open_buildings_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shipped default is `coarse`, so the disabled tier is never even fetched.

    Worth asserting on the *fetch* rather than only on the result: Open Buildings is the one
    product with no public bucket behind it, so a disabled tier that still called `ensure` would
    open an Earth Engine session for a raster nothing goes on to read.
    """
    settings = _settings(tmp_path)
    stubs = _stub_fetchers(settings, monkeypatch)

    resolved, placed = resolve_areal_tiers(settings, (0.0, 0.0, 0.01, 0.01))

    assert [tier.name for tier in resolved.areal_tiers] == ["wsf3d", "ghsl"]
    assert set(placed) == {"wsf3d", "ghsl"}
    assert stubs["gob25d"].calls == 0


def test_a_product_with_no_coverage_shortens_the_cascade_rather_than_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Absence is a real answer, and it is recorded as one.

    `None` in the record and a missing entry are different facts — "asked, nothing there" against
    "never asked, because it is switched off" — and only the first belongs to the study area.
    """
    settings = _settings(tmp_path)
    config = HeightConfig(
        overture_height_confidence=0.9,
        overture_num_floors_confidence=0.6,
        areal_tiers=[
            ArealTierConfig(name="gob25d", source_dir_name="GOB25D", confidence=0.5),
            ArealTierConfig(name="ghsl", source_dir_name="GHSL", confidence=0.25),
        ],
    )
    stubs = _stub_fetchers(settings, monkeypatch, gob25d=False)

    resolved, placed = resolve_areal_tiers(settings, (0.0, 0.0, 0.01, 0.01), config)

    assert [tier.name for tier in resolved.areal_tiers] == ["ghsl"]
    assert placed == {"gob25d": None, "ghsl": str(stubs["ghsl"].ensure((0, 0, 0, 0)))}


def test_a_resolved_tier_carries_a_filename_build_cascade_can_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seam between placing a product and reading it: `filename` is relative to the tier's
    own `input/` subdirectory, which is the only form `build_cascade` resolves."""
    settings = _settings(tmp_path)
    settings.heights.overture_height_confidence = 0.9
    settings.heights.overture_num_floors_confidence = 0.6
    for tier in settings.heights.areal_tiers:
        tier.confidence = 0.3
    _stub_fetchers(settings, monkeypatch, gob25d=False)

    resolved, _ = resolve_areal_tiers(settings, (0.0, 0.0, 0.01, 0.01))

    assert [tier.filename for tier in resolved.areal_tiers] == ["h.tif", "h.tif"]
    tiers = build_cascade(resolved, settings.source_dir)
    assert [tier.name for tier in tiers] == ["overture", "wsf3d", "ghsl"]


def test_the_cascade_runs_in_configured_order_not_alphabetical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Order is the whole content of the `full` / `full_reversed` comparison Phase 11 runs, and
    every tier claims only what earlier ones left, so a resolver that reordered would make two
    variants identical while still printing two rows."""
    settings = _settings(tmp_path)
    _stub_fetchers(settings, monkeypatch)
    names = ["wsf3d", "ghsl", "gob25d"]
    config = HeightConfig(
        overture_height_confidence=0.9,
        overture_num_floors_confidence=0.6,
        areal_tiers=[
            ArealTierConfig(name=name, source_dir_name=_TIER_DIRS[name], confidence=0.3)
            for name in names
        ],
    )

    resolved, _ = resolve_areal_tiers(settings, (0.0, 0.0, 0.01, 0.01), config)

    assert [tier.name for tier in resolved.areal_tiers] == names


def test_resolving_does_not_mutate_the_settings_it_was_handed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resolver that edited `settings.heights` in place would leave the second city in a sweep
    configured with the first city's rasters — which is a wrong map, not a crash."""
    settings = _settings(tmp_path)
    _stub_fetchers(settings, monkeypatch, gob25d=False)

    resolve_areal_tiers(settings, (0.0, 0.0, 0.01, 0.01))

    assert [tier.filename for tier in settings.heights.areal_tiers] == [None, None, None]
    assert [tier.name for tier in settings.heights.areal_tiers] == ["gob25d", "wsf3d", "ghsl"]
