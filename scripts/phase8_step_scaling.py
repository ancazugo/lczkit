"""Phase 8: the scaling exponent of every whole-extent step that is left.

    uv run --active python scripts/phase8_step_scaling.py [--extents 64,144,256,484]

CLAUDE.md's acceptance for this phase is that **no whole-extent operation is left with an
unmeasured scaling exponent**, and its anti-pattern list requires three or more extents before an
exponent may be claimed. `neatify` was profiled that way and tiling worked; the threshold-pinning
step was not, and cost fifteen hours. This script is the standing check that closes the gap for
everything else.

Steps covered, and why each is a suspect:

- `resolve_buildings_on_streets` unions the **entire** buffered street network into one geometry
  and intersects every footprint against it
- `drop_buildings_on_waterbodies` and `drop_waterlines_through_buildings` are whole-layer joins
- `enforce_planarity` queries the building index against itself and then loops per pass
- `clean_land_use` and `clean_buildings` are included as controls; `clean_buildings` was already
  measured near-linear at exponent 0.98, so a different answer here would mean the harness is
  wrong rather than the step

Street simplification is deliberately **not** measured here — it is tiled, so it has no
whole-extent form left. Its stitch does still run over the whole network, and is measured in
`docs/experiments/phase-8-scaling.md` §4.3 at 1.8 s, 5.1 s and 17.4 s over ~30k, ~60k and ~210k
features: an exponent of about 1.16, and 17 seconds over the whole of Berlin.

**Where it writes.** `output/lczkit/<run_id>/`. Nothing under `input/` is modified.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from typing import Any

import geopandas as gpd
import numpy as np
import shapely

from lczkit.cleaning.buildings import clean_buildings, enforce_planarity
from lczkit.cleaning.land_use import clean_land_use
from lczkit.cleaning.topology import (
    drop_buildings_on_waterbodies,
    drop_waterlines_through_buildings,
    resolve_buildings_on_streets,
)
from lczkit.config import CleaningConfig, Settings
from lczkit.crs import local_utm_crs
from lczkit.protocols import BBox
from lczkit.sources.overture import OvertureSource

BERLIN: BBox = (13.0884, 52.3383, 13.7612, 52.6755)
RELEASE = "2026-07-22.0"
EXTENTS_KM2 = (64, 144, 256, 484)

CLEANING = CleaningConfig(
    building_max_area_m2=100_000.0,
    building_min_area_m2=20.0,
    building_merge_limit_m2=50.0,
    building_overlap_limit=0.1,
    building_road_buffer_m=4.0,
    building_road_overlap_limit=0.5,
)


def _window(layer: gpd.GeoDataFrame, centre: tuple[float, float], extent_km2: int):
    cx, cy = centre
    half = extent_km2**0.5 * 500.0
    box = shapely.box(cx - half, cy - half, cx + half, cy + half)
    return layer.iloc[layer.sindex.query(box, predicate="intersects")].copy()


def _time(label: str, call: Callable[[], Any]) -> tuple[float, Any]:
    started = time.perf_counter()
    result = call()
    elapsed = time.perf_counter() - started
    print(f"      {label:34s} {elapsed:9.2f}s", flush=True)
    return elapsed, result


def measure(layers: dict[str, gpd.GeoDataFrame], extent_km2: int) -> dict[str, Any]:
    """Time each whole-extent step over one window, on the same inputs the pipeline gives it."""
    buildings = layers["buildings"]
    streets = layers["streets"]
    print(f"  {extent_km2} km2: {len(buildings)} buildings, {len(streets)} streets", flush=True)

    timings: dict[str, float] = {}
    timings["clean_buildings"], (cleaned, _) = _time(
        "clean_buildings",
        lambda: clean_buildings(
            buildings,
            max_area_m2=CLEANING.building_max_area_m2,
            min_area_m2=CLEANING.building_min_area_m2,
            merge_limit_m2=CLEANING.building_merge_limit_m2,
            overlap_limit=CLEANING.building_overlap_limit,
        ),
    )
    topo = cleaned.topo

    timings["enforce_planarity"], _ = _time("enforce_planarity", lambda: enforce_planarity(topo))
    timings["clean_land_use"], _ = _time(
        "clean_land_use", lambda: clean_land_use(layers["land_use"])
    )
    timings["resolve_buildings_on_streets"], (after_streets, _) = _time(
        "resolve_buildings_on_streets",
        lambda: resolve_buildings_on_streets(
            topo,
            streets,
            buffer_m=CLEANING.building_road_buffer_m,
            overlap_limit=CLEANING.building_road_overlap_limit,
        ),
    )
    timings["drop_buildings_on_waterbodies"], (after_water, _) = _time(
        "drop_buildings_on_waterbodies",
        lambda: drop_buildings_on_waterbodies(after_streets, layers["waterbodies"]),
    )
    timings["drop_waterlines_through_buildings"], _ = _time(
        "drop_waterlines_through_buildings",
        lambda: drop_waterlines_through_buildings(layers["waterlines"], after_water),
    )

    return {
        "extent_km2": extent_km2,
        "n_buildings": len(buildings),
        "n_streets": len(streets),
        "seconds": {name: round(value, 2) for name, value in timings.items()},
    }


def _exponents(results: list[dict[str, Any]], key: str) -> dict[str, float]:
    """Least-squares exponent of each step's cost against `key`, in log-log space."""
    counts = np.array([float(record[key]) for record in results])
    exponents: dict[str, float] = {}
    for step in results[0]["seconds"]:
        seconds = np.array([float(record["seconds"][step]) for record in results])
        if (seconds <= 0).any():
            continue
        slope, _ = np.polyfit(np.log(counts), np.log(seconds), 1)
        exponents[step] = round(float(slope), 2)
    return exponents


def main() -> None:
    extents = EXTENTS_KM2
    if "--extents" in sys.argv:
        extents = tuple(int(x) for x in sys.argv[sys.argv.index("--extents") + 1].split(","))

    settings = Settings.load()
    settings.overture.release = RELEASE
    source = OvertureSource(settings)
    crs = local_utm_crs(BERLIN)
    waterlines, waterbodies = source.water(BERLIN)
    whole = {
        "buildings": source.buildings(BERLIN).to_crs(crs),
        "streets": source.streets(BERLIN).to_crs(crs),
        "waterlines": waterlines.to_crs(crs),
        "waterbodies": waterbodies.to_crs(crs),
        "land_use": source.land_use(BERLIN).to_crs(crs),
    }
    minx, miny, maxx, maxy = whole["streets"].total_bounds
    centre = ((minx + maxx) / 2, (miny + maxy) / 2)
    print({name: len(layer) for name, layer in whole.items()}, flush=True)

    results: list[dict[str, Any]] = []
    for extent_km2 in extents:
        windowed = {name: _window(layer, centre, extent_km2) for name, layer in whole.items()}
        results.append(measure(windowed, extent_km2))
        payload = {
            "experiment": "phase-8-step-scaling",
            "bbox": BERLIN,
            "overture_release": RELEASE,
            "results": results,
            "exponent_in_buildings": _exponents(results, "n_buildings") if len(results) > 1 else {},
            "exponent_in_streets": _exponents(results, "n_streets") if len(results) > 1 else {},
        }
        destination = settings.run_dir / "phase8_step_scaling.json"
        destination.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")

    if len(results) > 1:
        print("\nexponent in building count (>1.2 is superlinear and must be named):", flush=True)
        for step, exponent in sorted(
            _exponents(results, "n_buildings").items(), key=lambda kv: -kv[1]
        ):
            flag = "  <-- superlinear" if exponent > 1.2 else ""
            print(f"  {step:36s} {exponent:5.2f}{flag}", flush=True)
    print(f"wrote {settings.run_dir / 'phase8_step_scaling.json'}", flush=True)


if __name__ == "__main__":
    main()
