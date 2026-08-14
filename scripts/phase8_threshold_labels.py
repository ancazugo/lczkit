"""Phase 8 fix 2, the adopt bar: does the pooled threshold change any LCZ label?

    uv run --active python scripts/phase8_threshold_labels.py [--extent 256] [--full]

CLAUDE.md's condition for replacing the whole-network artifact threshold with a tile-pooled one is
that the deviation **does not move any classification**. `phase8_threshold_equivalence.py` measures
the deviation and counts the faces it moves; this measures the thing that actually matters, which
is whether the LCZ label of any 100 m cell changes.

The two arms differ in exactly one value — `CleaningConfig.street_artifact_threshold` — and are
otherwise the same code over the same data with the same tiling, so a label that moves moved
because of the threshold and nothing else.

**Two extents, for two different reasons.**

- **256 km2 is the real comparison.** At about this extent the whole network starts finding a
  genuine kernel-density valley, so it compares two thresholds rather than a threshold against a
  fallback.
- **64 km2 is the harsh case.** There the whole network finds no valley at all and falls back to
  7.0, while pooling may well find one. If pooling is going to move a label anywhere, it is here.

`--full` runs the whole 891 km2 administrative extent instead of a concentric window. That is the
extent the pooled threshold was adopted *for*, and the one condition attached to the adoption: a
materially higher flip rate than the 0.0230% measured at 256 km2 reopens the decision. It is also
expensive — the whole-network arm alone extrapolates to about 9.4 hours from the exponent-2.0 fit,
before either pipeline run — so it is a background job rather than something to sit and watch.

Each arm resolves its **own** whole-network threshold over its own window rather than reusing a
figure from `phase8_threshold_equivalence.py`: that script windows in projected metres and this one
in lon/lat, so the two cover nearly but not exactly the same ground, and a threshold carried across
would be a threshold from a different network.

**Where it writes.** `output/lczkit/<run_id>/`, including the two clipped rasters. Overture's
cache under `input/Overture_Maps/<release>/<bbox>/` gains new entries, which is the one write into
`input/` the source owns; nothing existing there is touched.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

from lczkit.classify import PrototypeClassifier
from lczkit.cleaning.pipeline import clean_vectors
from lczkit.cleaning.streets import resolve_artifact_threshold
from lczkit.config import Settings
from lczkit.crs import local_utm_crs
from lczkit.heights.cascade import fill_heights
from lczkit.heights.inherit import inherit_heights
from lczkit.heights.tiers import build_cascade
from lczkit.landcover.local import LocalRasterSource
from lczkit.protocols import BBox
from lczkit.sources.overture import OvertureSource
from lczkit.ucp.parameters import compute_parameters
from lczkit.units.grid import GridUnits

sys.path.insert(0, str(Path(__file__).resolve().parent))

from berlin_wide_validation import (  # noqa: E402 - sibling script, imported after the path fix
    clip_worldcover,
)
from unit_scale_experiment import (  # noqa: E402 - sibling script, imported after the path fix
    CLEANING,
    HEIGHTS,
    LAND_COVER,
    UCP,
)

BERLIN: BBox = (13.0884, 52.3383, 13.7612, 52.6755)
RELEASE = "2026-07-22.0"

#: Concentric windows on the metropolitan centre, snapped to the same series the threshold
#: deviation was measured on, so a label result at 256 km2 pairs with a deviation at 256 km2.
CENTRE = ((BERLIN[0] + BERLIN[2]) / 2, (BERLIN[1] + BERLIN[3]) / 2)

TILE_SIZE_M = 2000.0
TILE_BUFFER_M = 600.0


def _window(extent_km2: int) -> BBox:
    """A concentric lon/lat window of roughly `extent_km2` square kilometres."""
    half_km = extent_km2**0.5 / 2
    half_lat = half_km / 111.0
    half_lon = half_lat / 0.61  # cos(52.5 degrees)
    return (
        CENTRE[0] - half_lon,
        CENTRE[1] - half_lat,
        CENTRE[0] + half_lon,
        CENTRE[1] + half_lat,
    )


def label(
    settings: Settings, bbox: BBox, worldcover: Path, threshold: float | None, tag: str
) -> pd.DataFrame:
    """Run the pipeline end to end over `bbox` and return the per-cell classification."""
    cleaning = CLEANING.model_copy()
    cleaning.street_tile_size_m = TILE_SIZE_M
    cleaning.street_tile_buffer_m = TILE_BUFFER_M
    cleaning.street_artifact_threshold = threshold

    started = time.perf_counter()
    cleaned = clean_vectors(OvertureSource(settings), bbox, cleaning, cache_dir=None)
    street_step = next(
        step for step in cleaned.report.steps if step.operation.startswith("simplify_streets")
    )
    print(
        f"  [{tag}] cleaned in {time.perf_counter() - started:.0f}s, "
        f"threshold {street_step.detail.get('artifact_threshold')}, "
        f"{street_step.n_out} streets out",
        flush=True,
    )

    tiers = build_cascade(HEIGHTS, settings.source_dir)
    buildings_area, _ = fill_heights(cleaned.buildings_area, tiers)
    buildings_topo = inherit_heights(cleaned.buildings_topo, buildings_area)

    units = GridUnits().generate(bbox)
    fractions = LocalRasterSource(LAND_COVER.dataset(UCP.land_cover_dataset), worldcover).fractions(
        units
    )
    parameters = compute_parameters(
        units,
        buildings_area,
        buildings_topo,
        cleaned.streets,
        cleaned.land_use,
        fractions,
        config=UCP,
        land_cover_config=LAND_COVER,
    )
    classification = PrototypeClassifier().classify(parameters)
    classification.attrs["threshold"] = street_step.detail.get("artifact_threshold")
    return classification


def compare(whole: pd.DataFrame, pooled: pd.DataFrame) -> dict[str, Any]:
    """Per-cell label agreement between the two arms."""
    joined = pd.DataFrame({"whole": whole["lcz_primary"], "pooled": pooled["lcz_primary"]}).dropna(
        how="all"
    )
    moved = joined["whole"] != joined["pooled"]
    transitions = joined.loc[moved].groupby(["whole", "pooled"]).size().sort_values(ascending=False)
    return {
        "n_units": int(len(joined)),
        "n_units_moved": int(moved.sum()),
        "moved_fraction": float(moved.mean()) if len(joined) else 0.0,
        "transitions": {f"{int(a)}->{int(b)}": int(n) for (a, b), n in transitions.items()},
        "adopt": bool(moved.sum() == 0),
    }


def main() -> None:
    full = "--full" in sys.argv
    extents = (256, 64)
    if full:
        # A label, not a size: the whole bbox is 1714 km2 of which Berlin's administrative area is
        # 891 km2, and rounding either number into `_window` would silently run a different extent.
        extents = (0,)
    elif "--extent" in sys.argv:
        extents = (int(sys.argv[sys.argv.index("--extent") + 1]),)

    settings = Settings.load()
    settings.overture.release = RELEASE

    results: list[dict[str, Any]] = []
    for extent_km2 in extents:
        bbox = BERLIN if full else _window(extent_km2)
        extent_tag = "full" if full else f"{extent_km2}"
        print(f"\n{extent_tag} km2 {bbox}", flush=True)
        worldcover = clip_worldcover(bbox, settings.run_dir / f"worldcover_{extent_tag}.tif")

        # Arm "whole" pins the threshold the quadratic whole-network resolver would have chosen;
        # arm "pooled" lets `simplify_streets_tiled` derive it from the tiles.
        #
        # `--whole-threshold` skips re-deriving it. Deriving it is the hours-long step this whole
        # phase is about removing, so re-paying it to repeat the *downstream* comparison is pure
        # waste — but only ever pass a value measured on this same window, since it is a property
        # of the network and not of the city.
        if "--whole-threshold" in sys.argv:
            whole_threshold = float(sys.argv[sys.argv.index("--whole-threshold") + 1])
            print(f"  whole-network threshold {whole_threshold:.6f} (given)", flush=True)
        else:
            streets = OvertureSource(settings).streets(bbox).to_crs(local_utm_crs(bbox))
            started = time.perf_counter()
            whole_threshold = resolve_artifact_threshold(streets)
            print(
                f"  whole-network threshold {whole_threshold:.6f} "
                f"({time.perf_counter() - started:.0f}s over {len(streets)} streets)",
                flush=True,
            )

        whole = label(settings, bbox, worldcover, whole_threshold, "whole")
        pooled = label(settings, bbox, worldcover, None, "pooled")
        record = compare(whole, pooled) | {
            "extent_km2": None if full else extent_km2,
            "extent": extent_tag,
            "bbox": bbox,
            "whole_threshold": whole_threshold,
            "pooled_threshold": pooled.attrs.get("threshold"),
        }
        results.append(record)
        # `adopt` is the pre-registered bar, which was superseded — see
        # `docs/experiments/phase-8-scaling.md` section 4.2. It is still reported because the
        # condition attached to the adoption is a *rate*, and a rate needs the count beside it.
        verdict = "no cells moved" if record["adopt"] else "cells moved"
        print(
            f"  {extent_tag} km2: {record['n_units_moved']} of {record['n_units']} cells moved "
            f"({record['moved_fraction']:.4%}) -> {verdict}",
            flush=True,
        )
        if record["transitions"]:
            print(f"    transitions: {record['transitions']}", flush=True)

        destination = settings.run_dir / "phase8_threshold_labels.json"
        destination.write_text(
            json.dumps(
                {
                    "experiment": "phase-8-threshold-labels",
                    "overture_release": RELEASE,
                    "tile_size_m": TILE_SIZE_M,
                    "tile_buffer_m": TILE_BUFFER_M,
                    "results": results,
                },
                indent=2,
                default=str,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"  wrote {destination}", flush=True)


if __name__ == "__main__":
    main()
