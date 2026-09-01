"""Live Earth Engine tests: `EarthEngineSource` against `LocalRasterSource` on the same units.

All marked `network` and skipped by default, so CI stays offline — but they are real calls, and
they are what makes the phase's acceptance criterion ("both sources return schema-identical tables
on the fixture") a measured fact rather than a claim about code that was never run.

Needs credentials and a billable project. `GEE_PROJECT_NAME` comes from `.env`, the same place
`Settings.load()` reads it; these tests skip rather than fail when it is absent, so a checkout
without Earth Engine access can still run `pytest -m network`.
"""

from __future__ import annotations

import os
from pathlib import Path

import geopandas as gpd
import pytest
from conftest import LANDCOVER_FIXTURES_DIR, SMALL_BBOX
from dotenv import load_dotenv

from lczkit.config import LandCoverConfig, LandCoverDatasetConfig, Settings
from lczkit.landcover.earthengine import EarthEngineSource
from lczkit.landcover.local import LocalRasterSource
from lczkit.units.grid import GridUnits

pytestmark = pytest.mark.network

#: Both backends see the same 10 m cells, but reduce them differently: `exactextract` weights each
#: cell by the exact fraction of it the unit covers, while `reduceRegions` counts whole pixels by
#: centre. On a 100 m unit that is a boundary ring of ~40 cells out of ~100, so single-percent
#: disagreement is the expected cost of the two reduction semantics, not an error in either.
AGREEMENT_TOLERANCE = 0.08


@pytest.fixture(scope="module")
def project() -> str:
    load_dotenv()
    name = os.environ.get("GEE_PROJECT_NAME")
    if not name:
        pytest.skip("GEE_PROJECT_NAME is not set; Earth Engine tests need a billable project.")
    return name


@pytest.fixture(scope="module")
def units() -> gpd.GeoDataFrame:
    """~48 cells. Small deliberately: these are billed, rate-limited calls."""
    return GridUnits().generate(SMALL_BBOX)


def _local(dataset: LandCoverDatasetConfig, filename: str) -> LocalRasterSource:
    return LocalRasterSource(dataset, LANDCOVER_FIXTURES_DIR / filename)


@pytest.mark.parametrize(
    ("name", "filename"),
    [("worldcover", "worldcover_berlin.tif"), ("eth_canopy", "eth_canopy_berlin.tif")],
)
def test_earth_engine_matches_the_local_raster(
    name: str, filename: str, project: str, units: gpd.GeoDataFrame, tmp_path: Path
) -> None:
    """The acceptance criterion, measured. `worldcover` is a catalogued `ImageCollection`;
    `eth_canopy` is a single user-asset `Image`, so this also covers both `asset_type` paths."""
    dataset = LandCoverConfig().dataset(name)

    local = _local(dataset, filename).fractions(units)
    remote = EarthEngineSource(dataset, project=project, cache_dir=tmp_path).fractions(units)

    assert list(remote.columns) == list(local.columns)
    assert remote.index.equals(local.index)
    assert remote.dtypes.equals(local.dtypes)
    assert remote.dropna(how="all").sum(axis=1).to_numpy() == pytest.approx(1.0)

    comparable = local.join(remote, lsuffix="_local", rsuffix="_remote").dropna()
    assert len(comparable) == len(units)
    for column in local.columns:
        difference = (comparable[f"{column}_local"] - comparable[f"{column}_remote"]).abs()
        assert difference.max() < AGREEMENT_TOLERANCE, column


def test_the_canopy_mask_is_handled_the_same_way_server_side(
    project: str, units: gpd.GeoDataFrame, tmp_path: Path
) -> None:
    """The finding that drove `NodataPolicy`, checked on the live asset.

    Locally, ETH's 255 is a value in the GeoTIFF. Server-side it may arrive masked instead, and
    `unmask()` casts its argument into the band's type — so an out-of-range sentinel would clamp
    into range and match nothing. Getting ~20% rather than ~100% tree cover here is what shows the
    mask is being caught by the image's own mask rather than by a value comparison that silently
    fails.
    """
    dataset = LandCoverConfig().dataset("eth_canopy")

    remote = EarthEngineSource(dataset, project=project, cache_dir=tmp_path).fractions(units)

    assert remote["canopy_frac_tree"].mean() < 0.4


def test_a_second_call_is_served_from_the_cache(
    project: str, units: gpd.GeoDataFrame, tmp_path: Path
) -> None:
    """A cache hit is just a file that is already there — and it must be byte-identical, since a
    silently different cached answer is worse than no cache."""
    dataset = LandCoverConfig().dataset("worldcover")
    source = EarthEngineSource(dataset, project=project, cache_dir=tmp_path)

    first = source.fractions(units)
    assert source.cache_path(units).exists()

    second = EarthEngineSource(dataset, project=project, cache_dir=tmp_path).fractions(units)

    assert second.equals(first)


def test_batching_across_several_calls_keeps_every_unit_matched(
    project: str, units: gpd.GeoDataFrame, tmp_path: Path
) -> None:
    """Forces the batching path with an absurdly small batch size, so the row-placement logic is
    exercised against a real multi-call reduction rather than a synthetic payload.

    Compared to a tolerance rather than exactly: splitting the same units across seven calls
    changes Earth Engine's summation order, which moves a handful of rows by ~1e-16. That is far
    below the ~0.1-1.0 discrepancy a misplaced row would produce, so this still fails loudly if the
    results and the units ever come apart.
    """
    dataset = LandCoverConfig().dataset("worldcover")

    batched = EarthEngineSource(
        dataset, project=project, cache_dir=tmp_path / "batched", batch_size=7
    ).fractions(units)
    single = EarthEngineSource(
        dataset, project=project, cache_dir=tmp_path / "single", batch_size=10_000
    ).fractions(units)

    assert batched.index.equals(single.index)
    assert batched.to_numpy() == pytest.approx(single.to_numpy(), abs=1e-9, nan_ok=True)


def test_an_oversized_run_is_refused_before_any_call(project: str, tmp_path: Path) -> None:
    """CLAUDE.md: never let `reduceRegions` element counts go unbounded."""
    dataset = LandCoverConfig().dataset("worldcover")
    source = EarthEngineSource(dataset, project=project, cache_dir=tmp_path, max_units=2)

    with pytest.raises(ValueError, match="gee_max_units"):
        source.fractions(GridUnits().generate(SMALL_BBOX))


def test_the_pipeline_reaches_earth_engine_when_the_config_asks_for_it(
    project: str, units: gpd.GeoDataFrame, tmp_path: Path
) -> None:
    """The wiring, measured rather than claimed — and it is the half that was missing.

    Everything above tests `EarthEngineSource` directly, which is what could always be reached. The
    chain named `LocalRasterSource` outright, so for several phases a schema-identical backend and
    a populated `gee_project` existed and no run could use either. This goes through
    `land_cover_source`, which is what `run_pipeline` calls, and checks the table it gets back is
    the one the local backend would have produced.

    A `Settings` built on `tmp_path` rather than loaded, so this needs no `DATA_DIR` — only the
    credentials every test in this file already needs.
    """
    from lczkit.pipeline import land_cover_source

    (tmp_path / "input").mkdir()
    settings = Settings(data_dir=tmp_path)
    settings.land_cover.source = "gee"
    settings.land_cover.gee_project = project

    source = land_cover_source(settings, SMALL_BBOX)
    remote = source.fractions(units)
    local = _local(settings.land_cover.dataset("worldcover"), "worldcover_berlin.tif").fractions(
        units
    )

    assert isinstance(source, EarthEngineSource)
    assert list(remote.columns) == list(local.columns)
    assert remote.index.equals(local.index)
    for column in local.columns:
        difference = (local[column] - remote[column]).abs().dropna()
        assert difference.max() < AGREEMENT_TOLERANCE, column

    # Its cache belongs under `input/GEE/`, where a cache hit is just a file that is already there.
    assert source.cache_path(units).parent == settings.source_dir("GEE")
