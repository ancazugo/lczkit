"""Shared pytest fixtures for lczkit tests."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest

from lczkit.protocols import BBox

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "overture"

#: The full committed Berlin extract (~3x3 km, matching CLAUDE.md's test-strategy sizing).
FIXTURE_BBOX: BBox = (13.3789, 52.5057, 13.4231, 52.5327)

#: A ~650x600 m subset of the fixture, for tests that run `neatnet`/`clean_vectors` and need
#: to stay fast — the full extent's street network takes on the order of a minute to simplify.
SMALL_BBOX: BBox = (13.3966, 52.5165, 13.4054, 52.5219)


@pytest.fixture(autouse=True)
def _clean_data_dir_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure `DATA_DIR` from the real shell environment never leaks into a test.

    Tests that need `DATA_DIR` set do so explicitly via `monkeypatch.setenv`. Tests also pass
    an explicit, non-existent `dotenv_path` to `Settings.load()` so `python-dotenv`'s upward
    search never picks up the real repo `.env` (it searches from the calling module's
    location, not the current working directory, so `chdir` alone would not isolate this).
    """
    monkeypatch.delenv("DATA_DIR", raising=False)


class FixtureVectorSource:
    """A `VectorSource` reading from the committed Berlin fixture parquet files, spatially
    filtered to whatever bbox is requested. Structurally satisfies the `VectorSource` protocol
    without depending on `OvertureSource`/DuckDB/network — used by tests that need a real (but
    small, fast) vector source.
    """

    def __init__(self) -> None:
        self._buildings = gpd.read_parquet(FIXTURES_DIR / "buildings.parquet")
        self._streets = gpd.read_parquet(FIXTURES_DIR / "streets.parquet")
        self._waterlines = gpd.read_parquet(FIXTURES_DIR / "waterlines.parquet")
        self._waterbodies = gpd.read_parquet(FIXTURES_DIR / "waterbodies.parquet")

    def buildings(self, bbox: BBox) -> gpd.GeoDataFrame:
        minx, miny, maxx, maxy = bbox
        return self._buildings.cx[minx:maxx, miny:maxy].reset_index(drop=True)

    def streets(self, bbox: BBox) -> gpd.GeoDataFrame:
        minx, miny, maxx, maxy = bbox
        return self._streets.cx[minx:maxx, miny:maxy].reset_index(drop=True)

    def water(self, bbox: BBox) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
        minx, miny, maxx, maxy = bbox
        return (
            self._waterlines.cx[minx:maxx, miny:maxy].reset_index(drop=True),
            self._waterbodies.cx[minx:maxx, miny:maxy].reset_index(drop=True),
        )


@pytest.fixture(scope="session")
def fixture_vector_source() -> FixtureVectorSource:
    return FixtureVectorSource()
