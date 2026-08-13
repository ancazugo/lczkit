"""One-off script: clip real land-cover rasters to the Berlin test-fixture bbox and write them
into `tests/fixtures/landcover/`.

Run manually once, or whenever the fixture needs refreshing:

    uv run --active python scripts/build_landcover_fixture.py

Unlike the Phase 3 height rasters, which are synthesised in-test because no tier 2-4 product
exists anywhere to clip, both of these products are freely available and the clip is a few tens of
kilobytes — so CLAUDE.md's test strategy ("cache ... a clipped land cover raster as files under
tests/fixtures/") is met with real data.

Reads over HTTPS and writes only into the repo's fixture tree. Nothing is written under
`DATA_DIR`: these are not a cache of a source implementation, they are test fixtures, and
CLAUDE.md makes `tests/fixtures/` the single exception to the "no data in the repo" rule.

Both products are CC-BY-4.0; attribution is recorded in `tests/fixtures/README.md`.
"""

from __future__ import annotations

from pathlib import Path

import rasterio
from rasterio.windows import from_bounds

# Matches BERLIN_FIXTURE_BBOX in scripts/build_overture_fixture.py and FIXTURE_BBOX in
# tests/conftest.py — the land-cover fixture has to cover the same ground as the vector one.
BERLIN_FIXTURE_BBOX = (13.3789, 52.5057, 13.4231, 52.5327)

# Matches ROTTERDAM_FIXTURE_BBOX in scripts/build_industry_fixture.py, added in Phase 6 so the
# second fixture can be classified rather than only cleaned.
ROTTERDAM_FIXTURE_BBOX = (4.3000, 51.8850, 4.3400, 51.9050)

# Matches HONGKONG_FIXTURE_BBOX in scripts/build_overture_fixture.py, added in Phase 11 as the
# primary fixture. See that script for why.
HONGKONG_FIXTURE_BBOX = (114.1645, 22.3210, 114.1931, 22.3485)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "landcover"

#: `output filename -> (source URL, bbox)`. All are 10 m EPSG:4326 uint8 global products tiled on
#: a 3-degree grid; N51E012 holds Berlin, N51E003 Rotterdam and N21E114 Hong Kong.
#:
#: Rotterdam and Hong Kong get WorldCover only. The ETH canopy product is a second, competing tree
#: estimate that Phase 4 documents as reading high, and Phase 5 defaults to the WorldCover route;
#: Rotterdam exists to exercise the LCZ 8/10 rule and the Hong Kong window carries no natural class
#: at all, so in neither is tree cover the thing under test.
SOURCES = {
    "worldcover_berlin.tif": (
        "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
        "ESA_WorldCover_10m_2021_v200_N51E012_Map.tif",
        BERLIN_FIXTURE_BBOX,
    ),
    "eth_canopy_berlin.tif": (
        "https://libdrive.ethz.ch/index.php/s/cO8or7iOe5dT2Rt/download"
        "?path=%2F3deg_cogs&files=ETH_GlobalCanopyHeight_10m_2020_N51E012_Map.tif",
        BERLIN_FIXTURE_BBOX,
    ),
    "worldcover_rotterdam.tif": (
        "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
        "ESA_WorldCover_10m_2021_v200_N51E003_Map.tif",
        ROTTERDAM_FIXTURE_BBOX,
    ),
    "worldcover_hongkong.tif": (
        "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
        "ESA_WorldCover_10m_2021_v200_N21E114_Map.tif",
        HONGKONG_FIXTURE_BBOX,
    ),
}


def clip(url: str, destination: Path, bbox: tuple[float, float, float, float]) -> None:
    """Read the window covering `bbox` and write it out, preserving nodata and CRS."""
    with rasterio.open(url) as src:
        window = from_bounds(*bbox, transform=src.transform)
        values = src.read(1, window=window)
        profile = src.profile | {
            "driver": "GTiff",
            "height": values.shape[0],
            "width": values.shape[1],
            "transform": src.window_transform(window),
            "compress": "deflate",
            "tiled": False,
            "count": 1,
        }
    with rasterio.open(destination, "w", **profile) as dst:
        dst.write(values, 1)


def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    for filename, (url, bbox) in SOURCES.items():
        destination = FIXTURES_DIR / filename
        clip(url, destination, bbox)
        with rasterio.open(destination) as check:
            size_kb = destination.stat().st_size / 1024
            print(
                f"{filename}: {check.width}x{check.height} {check.dtypes[0]} "
                f"nodata={check.nodata} crs={check.crs} ({size_kb:.0f} KB)"
            )
    print(f"wrote land-cover fixtures to {FIXTURES_DIR}")


if __name__ == "__main__":
    main()
