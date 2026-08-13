"""One-off script: clip the Demuzere global LCZ map to the fixture bboxes for the validation
module, and write them into `tests/fixtures/lcz/`.

    uv run --active python scripts/build_lcz_reference_fixture.py

The validation module compares a run against an independent LCZ map. CI has to be able to run that
comparison offline, so a clip of the reference map is committed alongside the vector and land-cover
fixtures - a few kilobytes each at ~100 m resolution.

Unlike the other two fixture scripts this one reads from `DATA_DIR` rather than over HTTPS: the
global map is a 1.8 GB COG already present on this system under `input/`, and re-downloading it to
clip 30x49 cells would be absurd. It is read only. Nothing under `input/` is created, modified or
deleted, per CLAUDE.md - that directory is shared with other projects.

The map is CC-BY-4.0; attribution is recorded in `tests/fixtures/README.md`.
"""

from __future__ import annotations

from pathlib import Path

import rasterio
from rasterio.windows import from_bounds

from lczkit.config import Settings

BERLIN_FIXTURE_BBOX = (13.3789, 52.5057, 13.4231, 52.5327)
ROTTERDAM_FIXTURE_BBOX = (4.3000, 51.8850, 4.3400, 51.9050)
HONGKONG_FIXTURE_BBOX = (114.1645, 22.3210, 114.1931, 22.3485)

#: Where the global map lives under `DATA_DIR/input/`, and which version it is. Recorded here
#: rather than assumed: the file is version 3 of the map while the Tier 1 citation is the 2022
#: ESSD paper, which describes an earlier one, and a run manifest reports the two separately.
SOURCE_DIR_NAME = "Demuzere_2022_complete"
SOURCE_FILENAME = "lcz_v3.tif"

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "lcz"

TARGETS = {
    "lcz_reference_berlin.tif": BERLIN_FIXTURE_BBOX,
    "lcz_reference_rotterdam.tif": ROTTERDAM_FIXTURE_BBOX,
    "lcz_reference_hongkong.tif": HONGKONG_FIXTURE_BBOX,
}


def clip(source: Path, destination: Path, bbox: tuple[float, float, float, float]) -> None:
    """Read the window covering `bbox` and write it out, preserving nodata, CRS and colormap.

    The colormap is carried across deliberately. It is the authority the committed
    `docs/references/tables/demuzere_2022_lcz_codes.md` was transcribed from, so keeping it on the
    fixture means the transcription can be checked against the product itself without `DATA_DIR`.
    """
    with rasterio.open(source) as src:
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
        try:
            colormap = src.colormap(1)
        except ValueError:  # pragma: no cover - the shipped product has one
            colormap = None

    with rasterio.open(destination, "w", **profile) as dst:
        dst.write(values, 1)
        if colormap is not None:
            dst.write_colormap(1, colormap)


def main() -> None:
    settings = Settings.load()
    source = settings.source_dir(SOURCE_DIR_NAME) / SOURCE_FILENAME
    if not source.is_file():
        raise FileNotFoundError(
            f"the reference LCZ map is not at {source}. Place it there, or point "
            "SOURCE_DIR_NAME/SOURCE_FILENAME at wherever it lives."
        )

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    for filename, bbox in TARGETS.items():
        destination = FIXTURES_DIR / filename
        clip(source, destination, bbox)
        with rasterio.open(destination) as check:
            classes = sorted(set(check.read(1).ravel().tolist()) - {0})
            print(
                f"{filename}: {check.width}x{check.height} {check.dtypes[0]} "
                f"nodata={check.nodata} crs={check.crs} "
                f"({destination.stat().st_size / 1024:.0f} KB) classes={classes}"
            )
    print(f"wrote LCZ reference fixtures to {FIXTURES_DIR}")


if __name__ == "__main__":
    main()
