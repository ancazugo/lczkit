"""Phase 6.7: the three-arm harness over a 16x16 km Berlin extent, against real ground truth.

    uv run --active python scripts/berlin_wide_validation.py

**Why a second extent at all.** The committed 3x3 km fixture carries only 438 labelled cells and
So2Sat gives them just two classes, LCZ 2 and LCZ 5 — both midrise, so the compactness axis is a
single pair and most of the height axis is untestable. That is enough to measure the ceiling and
not enough to decide anything about the classifier. At 16x16 km the same city yields **3584
labelled cells across eight classes** (2, 4, 5, 6, 8, A, B, D), including 205 LCZ 8 cells, which is
a real test of both axes and of the A/B unit-scale question.

    half-width   extent      labelled cells   classes
    6 km         12x12 km    2715             2, 5, 6, 8, A, B
    8 km         16x16 km    3584             2, 4, 5, 6, 8, A, B, D

Measured before the window was picked; 6 km is the fallback if the 16 km run proves too slow.

**Not a fixture and never committed.** It reads from `DATA_DIR` and the network, so CI cannot run
it. The committed fixtures remain the offline test, and `scripts/unit_scale_experiment.py` remains
the comparable-across-phases figure — this is the wider look that the narrow fixture cannot give.

**Where it writes.** Everything goes to `output/lczkit/<run_id>/`. The one exception is Overture's
own cache under `input/Overture_Maps/<release>/<bbox>/`, which `OvertureSource` owns and which this
run adds a new entry to; nothing existing under `input/` is read for writing, modified or removed.
The two rasters are clipped out of their global sources **into the run directory**, not into
`input/`, because a clip keyed to one experiment's bbox is not a source cache.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import rasterio
from rasterio.windows import from_bounds

from lczkit.classify import PrototypeClassifier
from lczkit.config import Settings
from lczkit.protocols import BBox
from lczkit.sources.overture import OvertureSource

sys.path.insert(0, str(Path(__file__).resolve().parent))

from unit_scale_experiment import (  # noqa: E402 - sibling script, imported after the path fix
    CLEANING,
    HEIGHTS,
    UCP,
    VALIDATION,
    Fixture,
    build_arms,
    evaluate,
    show,
)

#: 16x16 km centred on the committed fixture and snapped to the 100 m UTM grid, so its cells are
#: the same cells — a figure here and a figure there describe the same ground where they overlap.
BERLIN_WIDE_BBOX: BBox = (13.2902, 52.4467, 13.5207, 52.5937)

#: Fallback if the run above is too slow: 12x12 km, 2715 labelled cells over six classes.
BERLIN_MEDIUM_BBOX: BBox = (13.3190, 52.4651, 13.4918, 52.5753)

RELEASE = "2026-07-22.0"
"""Same pinned release as the committed fixtures, so the vector data is the data the offline
numbers were computed from — only the extent differs."""

#: ESA WorldCover v200 (2021) tile N51E012 covers 12-15E, 51-54N, i.e. the whole window. Read as a
#: remote COG over range requests, the way `scripts/build_landcover_fixture.py` reads it.
WORLDCOVER_URL = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
    "ESA_WorldCover_10m_2021_v200_N51E012_Map.tif"
)

LCZ_SOURCE_DIR_NAME = "Demuzere_2022_complete"
LCZ_SOURCE_FILENAME = "lcz_v3.tif"

SO2SAT_SOURCE_DIR_NAME = "So2Sat-LCZ42"
SO2SAT_RELATIVE = Path("v4") / "cities" / "Berlin" / "patches_reference_Berlin.gpkg"


def clip_raster(source: str, destination: Path, bbox: BBox) -> Path:
    """Window `source` to `bbox` and write it into the run directory, preserving nodata and CRS."""
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
    with rasterio.open(destination, "w", **profile) as dst:
        dst.write(values, 1)
    return destination


def clip_patches(source: Path, destination: Path, bbox: BBox) -> Path:
    """So2Sat patches intersecting `bbox`, geometries **unclipped**.

    Clipping would move the centroids, and the centroid is what decides which cell a label lands
    in — see `lczkit.validation.labelled`.
    """
    import geopandas as gpd

    patches = gpd.read_file(source, bbox=bbox)
    patches.to_parquet(destination)
    return destination


def main() -> None:
    settings = Settings.load()
    settings.overture.release = RELEASE
    bbox = BERLIN_WIDE_BBOX
    started = time.time()

    print(f"clipping rasters for {bbox}...", file=sys.stderr, flush=True)
    worldcover = clip_raster(WORLDCOVER_URL, settings.run_dir / "worldcover_berlin_wide.tif", bbox)
    reference = clip_raster(
        str(settings.source_dir(LCZ_SOURCE_DIR_NAME) / LCZ_SOURCE_FILENAME),
        settings.run_dir / "lcz_reference_berlin_wide.tif",
        bbox,
    )
    ground_truth = clip_patches(
        settings.source_dir(SO2SAT_SOURCE_DIR_NAME) / SO2SAT_RELATIVE,
        settings.run_dir / "so2sat_berlin_wide.parquet",
        bbox,
    )

    fixture = Fixture(
        name="berlin_wide",
        bbox=bbox,
        vectors=lambda: OvertureSource(settings),
        worldcover=worldcover,
        reference=reference,
        ground_truth=ground_truth,
    )

    print("running the three arms (this is 256 km2)...", file=sys.stderr, flush=True)
    arms, cleaned, provenance = build_arms(fixture)
    results = evaluate(fixture, arms, provenance, cleaned.buildings_area)
    show(results)

    record: dict[str, Any] = {
        "experiment": "phase-6.7-berlin-wide",
        "run_id": settings.run_id,
        "overture_release": RELEASE,
        "config": {
            "cleaning": CLEANING.model_dump(mode="json"),
            "heights": HEIGHTS.model_dump(mode="json"),
            "ucp": UCP.model_dump(mode="json"),
            "validation": VALIDATION.model_dump(mode="json"),
            "classification": PrototypeClassifier().describe(),
        },
        "fixtures": [results],
        "elapsed_s": round(time.time() - started, 1),
    }
    destination = settings.run_dir / "berlin_wide_validation.json"
    destination.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nwrote {destination}")


if __name__ == "__main__":
    main()
