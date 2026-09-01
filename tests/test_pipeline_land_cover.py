"""Which land-cover backend a run reaches, and what it costs to get there.

`EarthEngineSource` was written to the same interface as `LocalRasterSource` and returned a
schema-identical table, and for several phases nothing in the chain could reach it: the land-cover
stage named `LocalRasterSource` outright, so `GEE_PROJECT_NAME` had no effect on `lczkit run` at
all. These tests pin the seam that fixed that — which backend answers, and that choosing one does
not quietly do the other one's work.

Nothing here needs `DATA_DIR`, credentials or the network. The two backends' *agreement* is a live
measurement and lives in `test_landcover_earthengine_live.py`, marked `network`; what is checked
here is the dispatch, which is the part that was missing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lczkit.config import Settings
from lczkit.landcover.local import LocalRasterSource
from lczkit.pipeline import land_cover_source

BBOX = (13.0, 52.0, 13.1, 52.1)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A `Settings` with no `DATA_DIR` involved — the model takes the path directly."""
    (tmp_path / "input").mkdir()
    return Settings(data_dir=tmp_path)


def test_the_local_backend_is_the_default_and_places_its_own_window(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default reaches WorldCover over HTTP and needs nothing configured.

    It is also the path CI exercises, which is the argument for it being the default: Earth Engine
    wants credentials, a billable project and a quota, and a default requiring all three would make
    a first run fail on setup rather than on data.
    """
    called: list[tuple[object, Path]] = []

    def fake_clip(bbox: object, destination: Path) -> Path:
        called.append((bbox, destination))
        return destination

    monkeypatch.setattr("lczkit.pipeline.clip_worldcover", fake_clip)

    source = land_cover_source(settings, BBOX)

    assert isinstance(source, LocalRasterSource)
    assert called == [(BBOX, settings.run_dir / "worldcover.tif")]
    assert source.name == settings.ucp.land_cover_dataset


def test_the_local_backend_reads_its_cell_ceiling_from_config(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`max_raster_cells` guards against a units layer whose bounds quietly span a continental
    product. The stage used to build `LocalRasterSource` without passing it, so the configured
    value was unreachable from a run and only the constructor default ever applied — the two
    happen to be equal, which is exactly why nothing noticed.
    """
    monkeypatch.setattr("lczkit.pipeline.clip_worldcover", lambda bbox, destination: destination)
    settings.land_cover.max_raster_cells = 1234

    source = land_cover_source(settings, BBOX)

    assert isinstance(source, LocalRasterSource)
    assert source.max_raster_cells == 1234


def test_the_earth_engine_backend_is_reachable_from_config(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seam this file exists for: `land_cover.source` is what selects the backend.

    `from_settings` is stubbed because constructing the real one calls `ee.Initialize`, which is a
    credentialed network call. What is asserted is that the chain asks for it, and asks for the
    configured dataset rather than a name of its own.
    """
    asked: list[str] = []
    monkeypatch.setattr(
        "lczkit.pipeline.EarthEngineSource.from_settings",
        classmethod(lambda cls, settings, name: asked.append(name) or "a-source"),  # type: ignore[arg-type,func-returns-value]
    )
    settings.land_cover.source = "gee"

    assert land_cover_source(settings, BBOX) == "a-source"
    assert asked == [settings.ucp.land_cover_dataset]


def test_choosing_earth_engine_does_not_also_download_worldcover(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A backend that reduces server-side has no use for a local mosaic, and fetching one anyway
    would spend the download the choice exists to avoid — the same shape as the site's offline
    layer set collecting the remote raster by prefix."""

    def refuse(bbox: object, destination: Path) -> Path:
        raise AssertionError("the Earth Engine backend must not clip WorldCover locally")

    monkeypatch.setattr("lczkit.pipeline.clip_worldcover", refuse)
    monkeypatch.setattr(
        "lczkit.pipeline.EarthEngineSource.from_settings",
        classmethod(lambda cls, settings, name: "a-source"),  # type: ignore[arg-type]
    )
    settings.land_cover.source = "gee"

    assert land_cover_source(settings, BBOX) == "a-source"


def test_the_backend_is_recorded_in_what_the_manifest_serialises(settings: Settings) -> None:
    """Two backends that disagree by a single percent on a boundary ring are two backends a reader
    must be able to tell apart afterwards. The manifest is `settings.model_dump()` verbatim, so
    the field reaches it by being a field — this pins that it is one, and what it defaults to."""
    assert settings.model_dump()["land_cover"]["source"] == "local"

    settings.land_cover.source = "gee"

    assert settings.model_dump()["land_cover"]["source"] == "gee"
