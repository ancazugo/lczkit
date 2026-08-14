"""Publish one map site per city, over the windows the validation sweeps used.

    uv run --active python scripts/publish_sites.py [CITY ...] [--buildings] [--no-site]

**Why more than one city.** CLAUDE.md requires at least two sites, one high-coverage and one low
tier-1, because that comparison is the paper's central figure and a static site is the natural place
to make it: `height_completeness` is a layer, so "Cairo has no heights" stops being a number in a
table and becomes something a reader sees. A single Berlin site cannot show it — Berlin is the end
of the range where the founding premise does not bite.

**The default three, and why these.** Chosen on measured tier-1 coverage from the Phase 13 record
(cascade `coarse`, share of buildings whose height came from Overture), not on reputation:

| city | tier-1 | why |
|---|---|---|
| Berlin | 68.9% | the high-coverage end, and the city carrying the 35.3% / 75.2% baseline |
| Hong Kong | 30.5% | 13 classes, the richest class set on disk; the primary morphological fixture |
| Cairo | 0.4% | the low end — Berlin against Cairo is a 68-point contrast |

**One pipeline, three cities.** The stages come from `berlin_metropolitan_run.run_and_publish` and
the configuration from its `configure`, so a difference between two published sites comes from the
cities rather than from a setting that drifted between two scripts.

**Where it writes.** `output/lczkit/<stamp>-<city>/` per city, plus the shared tile cache under
`output/lczkit/_cache/tiles/` and Overture's own cache under `input/Overture_Maps/`, which
`OvertureSource` owns. Nothing existing under `input/` is modified or removed.
"""

from __future__ import annotations

import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd

from lczkit.config import Settings
from lczkit.protocols import BBox

sys.path.insert(0, str(Path(__file__).resolve().parent))

from berlin_metropolitan_run import configure, run_and_publish  # noqa: E402 - sibling script
from multi_city_validation import (  # noqa: E402 - sibling script
    BY_KEY,
    SO2SAT_CITIES,
    SO2SAT_SOURCE_DIR_NAME,
    City,
    densest_window,
)

DEFAULT_CITIES = ("berlin", "hong_kong", "cairo")
"""High coverage, richest morphology, and the low end. Overridable on the command line."""


def window(city: City, settings: Settings) -> BBox:
    """The city's So2Sat window — the same extent every validation sweep since Phase 9 has used.

    Reusing `densest_window` rather than picking a bbox per city is what makes a published site
    comparable with the agreement figures already recorded for that city. The site is a view of the
    package's results, so it must not be a view of a different extent.
    """
    source = settings.source_dir(SO2SAT_SOURCE_DIR_NAME) / SO2SAT_CITIES / city.so2sat
    patches = gpd.read_file(source / f"patches_reference_{city.so2sat}.gpkg")
    return densest_window(patches)


def main() -> None:
    flags = {argument for argument in sys.argv[1:] if argument.startswith("--")}
    requested = [argument for argument in sys.argv[1:] if not argument.startswith("--")]
    keys = requested or list(DEFAULT_CITIES)

    unknown = [key for key in keys if key not in BY_KEY]
    if unknown:
        raise SystemExit(f"unknown city keys {unknown}; choose from {sorted(BY_KEY)}")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    published: list[tuple[str, Path]] = []
    failed: list[tuple[str, str]] = []

    for key in keys:
        city = BY_KEY[key]
        print(f"\n=== {key} ({city.region}) ===", flush=True)
        settings = configure(
            Settings.load(run_id=f"{stamp}-{key}"), buildings="--buildings" in flags
        )
        try:
            run_dir = run_and_publish(
                settings, window(city, settings), build_site_after="--no-site" not in flags
            )
        except Exception:  # a city that fails must not take the others with it
            traceback.print_exc()
            failed.append((key, "see traceback above"))
            continue
        published.append((key, run_dir))

    print("\n=== published ===", flush=True)
    for key, run_dir in published:
        print(f"  {key:12s} {run_dir / 'site'}", flush=True)
    for key, reason in failed:
        print(f"  {key:12s} FAILED — {reason}", flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
