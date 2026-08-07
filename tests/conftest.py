"""Shared pytest fixtures for lczkit tests."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from lczkit.protocols import BBox

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "overture"

#: Rotterdam's Waalhaven, added in Phase 6. The Berlin fixture cannot validate the LCZ 8 / LCZ 10
#: rule — it holds 36 industrial buildings of 6195 — so a second fixture over an area with real
#: industry is what turns that rule from a mechanism into evidence. Built by
#: `scripts/build_industry_fixture.py`; 259 industrial buildings of 1681 and 17 industrial
#: land-use parcels of 157.
INDUSTRY_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "overture_industry"

#: Real ESA WorldCover v200 and ETH canopy height, clipped to the fixture bboxes by
#: `scripts/build_landcover_fixture.py`. Unlike the Phase 3 height rasters these are committed:
#: both products exist and are freely licensed, so there is something real to clip.
LANDCOVER_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "landcover"

#: The Demuzere global LCZ map clipped to both fixture bboxes by
#: `scripts/build_lcz_reference_fixture.py` — the Phase 6 validation target, so the agreement
#: comparison runs offline in CI like everything else.
LCZ_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "lcz"

#: The full committed Berlin extract (~3x3 km, matching CLAUDE.md's test-strategy sizing).
FIXTURE_BBOX: BBox = (13.3789, 52.5057, 13.4231, 52.5327)

#: A ~650x600 m subset of the fixture, for tests that run `neatnet`/`clean_vectors` and need
#: to stay fast — the full extent's street network takes on the order of a minute to simplify.
SMALL_BBOX: BBox = (13.3966, 52.5165, 13.4054, 52.5219)

#: The full committed Rotterdam extract (~2.7x2.2 km).
INDUSTRY_BBOX: BBox = (4.3000, 51.8850, 4.3400, 51.9050)

#: A ~700x600 m subset over the densest industrial block, for the same reason `SMALL_BBOX` exists.
INDUSTRY_SMALL_BBOX: BBox = (4.3130, 51.8930, 4.3230, 51.8985)


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

    def __init__(self, directory: Path = FIXTURES_DIR) -> None:
        self._buildings = gpd.read_parquet(directory / "buildings.parquet")
        self._streets = gpd.read_parquet(directory / "streets.parquet")
        self._rail = gpd.read_parquet(directory / "rail.parquet")
        self._waterlines = gpd.read_parquet(directory / "waterlines.parquet")
        self._waterbodies = gpd.read_parquet(directory / "waterbodies.parquet")
        self._land_use = gpd.read_parquet(directory / "land_use.parquet")

    def buildings(self, bbox: BBox) -> gpd.GeoDataFrame:
        minx, miny, maxx, maxy = bbox
        return self._buildings.cx[minx:maxx, miny:maxy].reset_index(drop=True)

    def streets(self, bbox: BBox) -> gpd.GeoDataFrame:
        minx, miny, maxx, maxy = bbox
        return self._streets.cx[minx:maxx, miny:maxy].reset_index(drop=True)

    def rail(self, bbox: BBox) -> gpd.GeoDataFrame:
        minx, miny, maxx, maxy = bbox
        return self._rail.cx[minx:maxx, miny:maxy].reset_index(drop=True)

    def water(self, bbox: BBox) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
        minx, miny, maxx, maxy = bbox
        return (
            self._waterlines.cx[minx:maxx, miny:maxy].reset_index(drop=True),
            self._waterbodies.cx[minx:maxx, miny:maxy].reset_index(drop=True),
        )

    def land_use(self, bbox: BBox) -> gpd.GeoDataFrame:
        minx, miny, maxx, maxy = bbox
        return self._land_use.cx[minx:maxx, miny:maxy].reset_index(drop=True)


@pytest.fixture(scope="session")
def fixture_vector_source() -> FixtureVectorSource:
    return FixtureVectorSource()


@pytest.fixture(scope="session")
def industry_vector_source() -> FixtureVectorSource:
    return FixtureVectorSource(INDUSTRY_FIXTURES_DIR)


def write_height_raster(
    path: Path,
    values: np.ndarray,
    *,
    origin: tuple[float, float],
    cell_size_m: float,
    crs: str,
    nodata: float = -9999.0,
) -> Path:
    """Write a single-band float32 GeoTIFF for the height-cascade tests, returning `path`.

    Height rasters are synthesised rather than committed. Unlike the Overture fixture there is
    no real product to clip — none of the tier 2-4 datasets (Google Open Buildings 2.5D, WSF-3D,
    GHS-BUILT-H) is present on this system — so any committed file would be invented data in
    binary form, able to drift silently from the code that made it. Generating it here keeps the
    values readable in the test that asserts on them, and still exercises the real rasterio read.

    `origin` is the *top-left* corner, matching `rasterio.transform.from_origin`.
    """
    return _write_raster(
        path,
        values,
        origin=origin,
        cell_size_m=cell_size_m,
        crs=crs,
        nodata=nodata,
        dtype="float32",
    )


def write_class_raster(
    path: Path,
    values: np.ndarray,
    *,
    origin: tuple[float, float],
    cell_size_m: float,
    crs: str,
    nodata: float = 0.0,
) -> Path:
    """Write a single-band uint8 GeoTIFF of land-cover class codes, returning `path`.

    Synthesised alongside the committed real fixtures, not instead of them: a hand-built raster is
    the only way to assert an exact fraction, and exact fractions are how partial cell coverage —
    the thing `exactextract` is here for — gets tested at all.
    """
    return _write_raster(
        path, values, origin=origin, cell_size_m=cell_size_m, crs=crs, nodata=nodata, dtype="uint8"
    )


def _write_raster(
    path: Path,
    values: np.ndarray,
    *,
    origin: tuple[float, float],
    cell_size_m: float,
    crs: str,
    nodata: float,
    dtype: str,
) -> Path:
    array = np.asarray(values, dtype=dtype)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype=dtype,
        crs=crs,
        transform=from_origin(origin[0], origin[1], cell_size_m, cell_size_m),
        nodata=nodata,
    ) as dst:
        dst.write(array, 1)
    return path
