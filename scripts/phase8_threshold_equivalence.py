"""Phase 8 fix 2: does a tile-pooled artifact threshold equal the whole-network one?

    uv run --active python scripts/phase8_threshold_equivalence.py [--extents 64,144,...]

**Why this measurement exists.** `resolve_artifact_threshold` derives `neatnet`'s face-artifact
threshold by running `fix_topology` over the entire street network, which is quadratic in feature
count — 481.7 s, 1916.9 s, 5004.6 s and 12392.6 s at 33.8k, 67.2k, 106.7k and 168.5k Berlin
streets, an exponent of 2.0. Extrapolated to the 267,021 streets of Land Berlin that is roughly
8.6 hours, and it accounts for the entire gap between the 7.5 minutes the tiles themselves take
and the 15 hours the first metropolitan run spent before it was killed. A step introduced to make
seams correct reintroduced the whole-extent cost that Phase 8 exists to remove.

`pooled_artifact_threshold` assembles the same distribution from the per-tile windows, which is
k * (n/k)**2 and parallel. **That is an approximation, not an identity**: a face wider than the
tile buffer is cut by the window and is dropped rather than indexed, so the pooled distribution
is missing its largest faces. CLAUDE.md calls that error unbounded until measured. This is the
measurement.

**What is compared.** For each extent, the whole-network threshold, the pooled threshold, their
deviation, and the number of faces whose artifact classification the difference moves — the faces
whose index falls between the two thresholds are exactly those that change status. The
whole-network face-artifact index is written out alongside, so the flip analysis can be redone
without paying `fix_topology` again.

**Two extents are not comparable and are reported as such.** At 64 and 144 km2 the whole network
finds no kernel-density valley at all and `neatify` falls back to 7.0. A fallback is the absence
of a threshold rather than a threshold, so the growth-with-extent question is judged on 256, 324,
400 and 484 km2, where a valley genuinely exists. The fallback extents are still reported: if
pooling finds a valley where the whole network does not, that is a real behavioural difference.

**Where it writes.** `output/lczkit/<run_id>/`. Overture's cache under
`input/Overture_Maps/<release>/<bbox>/` is read only; nothing under `input/` is modified.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import geopandas as gpd
import neatnet
import shapely

from lczkit.cleaning.streets import (
    ARTIFACT_THRESHOLD_FALLBACK,
    _preprocess,
    _threshold_from_index,
    pooled_artifact_threshold,
)
from lczkit.cleaning.tiles import build_tiles, layer_extent
from lczkit.config import Settings
from lczkit.crs import local_utm_crs
from lczkit.protocols import BBox
from lczkit.sources.overture import OvertureSource

BERLIN: BBox = (13.0884, 52.3383, 13.7612, 52.6755)
RELEASE = "2026-07-22.0"

#: Concentric square windows on the metropolitan centre, in km2 — the same series the original
#: whole-network timings were measured on, so those numbers carry over rather than being redone.
EXTENTS_KM2 = (64, 144, 256, 324, 400, 484)

#: The production tiling. Deliberately not swept: the question here is whether pooling reproduces
#: the whole-network threshold at the settings lczkit actually runs, not which settings are best.
TILE_SIZE_M = 2000.0
TILE_BUFFER_M = 600.0


def _window(streets: gpd.GeoDataFrame, extent_km2: int) -> gpd.GeoDataFrame:
    """The concentric window of `extent_km2` square kilometres, by spatial index."""
    minx, miny, maxx, maxy = streets.total_bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    half = extent_km2**0.5 * 500.0
    box = shapely.box(cx - half, cy - half, cx + half, cy + half)
    return streets.iloc[streets.sindex.query(box, predicate="intersects")].copy()


def measure(streets: gpd.GeoDataFrame, extent_km2: int, workers: int) -> dict[str, Any]:
    """Whole-network and pooled thresholds over one window, with the flip count between them."""
    window = _window(streets, extent_km2)

    started = time.perf_counter()
    faces = neatnet.FaceArtifacts(_preprocess(window))
    index = faces.polygons["face_artifact_index"].to_numpy(dtype=float)
    whole = _threshold_from_index(index)
    whole_seconds = time.perf_counter() - started

    tiles = build_tiles(
        layer_extent(window), tile_size_m=TILE_SIZE_M, buffer_m=TILE_BUFFER_M, crs_hint="streets"
    )
    started = time.perf_counter()
    pooled = pooled_artifact_threshold(window, tiles, workers=workers)
    pooled_seconds = time.perf_counter() - started

    # Faces between the two thresholds are exactly those whose artifact status changes, since
    # `neatnet` classifies a face as an artifact iff its index is below the threshold.
    applied = ARTIFACT_THRESHOLD_FALLBACK if whole is None else whole
    low, high = min(applied, pooled.value), max(applied, pooled.value)
    flipped = int(((index >= low) & (index < high)).sum())

    return {
        "extent_km2": extent_km2,
        "n_streets": len(window),
        "n_tiles": len(tiles),
        "whole_threshold": whole,
        "whole_found_valley": whole is not None,
        "whole_applied": applied,
        "whole_seconds": round(whole_seconds, 1),
        "whole_n_faces": int(index.size),
        "pooled_threshold": pooled.value,
        "pooled_found_valley": not pooled.fallback_used,
        "pooled_seconds": round(pooled_seconds, 1),
        "pooled_n_faces": pooled.n_faces,
        "pooled_n_faces_dropped": pooled.n_faces_dropped,
        "pooled_dropped_area_fraction": pooled.dropped_area_fraction,
        "deviation": abs(applied - pooled.value),
        "comparable": whole is not None,
        "n_faces_flipped": flipped,
        "faces_flipped_fraction": flipped / index.size if index.size else 0.0,
        "speedup": round(whole_seconds / pooled_seconds, 1) if pooled_seconds else None,
    }


def main() -> None:
    extents = EXTENTS_KM2
    if "--extents" in sys.argv:
        extents = tuple(int(x) for x in sys.argv[sys.argv.index("--extents") + 1].split(","))

    settings = Settings.load()
    settings.overture.release = RELEASE
    streets = OvertureSource(settings).streets(BERLIN).to_crs(local_utm_crs(BERLIN))
    print(f"metropolitan network: {len(streets)} streets", file=sys.stderr, flush=True)

    workers = len(os.sched_getaffinity(0))
    results = []
    for extent_km2 in extents:
        record = measure(streets, extent_km2, workers)
        results.append(record)
        mark = "" if record["comparable"] else "   (no whole-network valley: not comparable)"
        print(
            f"{extent_km2:4d} km2 | {record['n_streets']:6d} streets | "
            f"whole {record['whole_applied']:.6f} in {record['whole_seconds']:8.1f}s | "
            f"pooled {record['pooled_threshold']:.6f} in {record['pooled_seconds']:6.1f}s | "
            f"dev {record['deviation']:.6f} | flips {record['n_faces_flipped']:5d}"
            f" ({record['faces_flipped_fraction']:.3%}) | dropped "
            f"{record['pooled_n_faces_dropped']:4d}"
            f" ({record['pooled_dropped_area_fraction']:.2%} area){mark}",
            flush=True,
        )
        _write(settings, results)

    comparable = [r for r in results if r["comparable"]]
    if len(comparable) > 1:
        first, last = comparable[0], comparable[-1]
        growth = "GROWING - disqualifying" if last["deviation"] > first["deviation"] else "flat"
        print(
            f"\ndeviation at {first['extent_km2']} km2: {first['deviation']:.6f}"
            f"  ->  at {last['extent_km2']} km2: {last['deviation']:.6f}   ({growth})",
            flush=True,
        )
    _write(settings, results)


def _write(settings: Settings, results: list[dict[str, Any]]) -> None:
    """Rewrite after every extent, so a run killed part way still leaves what it measured.

    Named for the extents it covers, because the whole-network side is hours per extent and the
    series is therefore run as one process per extent rather than one process for the series.
    """
    covered = "_".join(str(record["extent_km2"]) for record in results)
    destination = settings.run_dir / f"phase8_threshold_equivalence_{covered}.json"
    payload = {
        "experiment": "phase-8-threshold-equivalence",
        "bbox": BERLIN,
        "overture_release": RELEASE,
        "tile_size_m": TILE_SIZE_M,
        "tile_buffer_m": TILE_BUFFER_M,
        "fallback": ARTIFACT_THRESHOLD_FALLBACK,
        "results": results,
    }
    destination.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
