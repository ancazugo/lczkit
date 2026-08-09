"""Phase 8 acceptance: a full Berlin metropolitan extent, end to end, with a wall time.

    uv run --active python scripts/berlin_metropolitan.py [tiled|untiled] [--extent KM]

**What this is for.** Every figure in this repository before Phase 8 was measured on a 9 km2
fixture, and `clean_vectors` was superlinear in extent without anyone seeing it: 100 km2 takes
50 minutes of `neatnet` on one core, 144 km2 completed only after hours, and 256 km2 was
abandoned after 4h12m without producing output. This script is the standing check that lczkit
can process a city rather than a tile.

`untiled` runs the pre-Phase-8 path and is expected to be unusable at this extent. It exists so
the comparison is reproducible rather than asserted, and it takes an `--extent` so it can be run
at a size that finishes.

**Where it writes.** Everything goes to `output/lczkit/<run_id>/`, except the per-tile
simplification cache at `output/lczkit/_cache/tiles/` and Overture's own cache under
`input/Overture_Maps/<release>/<bbox>/`, which `OvertureSource` owns. Nothing existing under
`input/` is modified or removed.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any

from lczkit.cleaning.pipeline import clean_vectors
from lczkit.config import CleaningConfig, Settings
from lczkit.protocols import BBox
from lczkit.sources.overture import OvertureSource

#: Land Berlin's administrative extent, 891 km2 — the whole city, not a window onto it.
BERLIN: BBox = (13.0884, 52.3383, 13.7612, 52.6755)

RELEASE = "2026-07-22.0"
"""The same pinned release the fixtures use, so only the extent differs from every other run."""

#: Phase 8's fixture-derived working values. 2000 m tiles keep the largest face-artifact
#: component tractable; the 600 m buffer is where seam agreement stops improving — measured on
#: 16 km2 of Berlin at 99.77 percent (300 m), 99.97 percent (600 m) and 99.95 percent (900 m).
CLEANING = CleaningConfig(
    building_max_area_m2=100_000.0,
    building_min_area_m2=20.0,
    building_merge_limit_m2=50.0,
    building_overlap_limit=0.1,
    building_road_buffer_m=4.0,
    building_road_overlap_limit=0.5,
    street_tile_size_m=2000.0,
    street_tile_buffer_m=600.0,
)


def _shrink(bbox: BBox, extent_km: float) -> BBox:
    """A concentric window of roughly `extent_km` on a side, for the untiled comparison."""
    minx, miny, maxx, maxy = bbox
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    half_lat = extent_km / 2 / 111.0
    half_lon = half_lat / 0.61  # cos(52.5 degrees)
    return (cx - half_lon, cy - half_lat, cx + half_lon, cy + half_lat)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "tiled"
    if mode not in {"tiled", "untiled"}:
        raise SystemExit(f"unknown mode {mode!r}; choose 'tiled' or 'untiled'")
    extent_km = None
    if "--extent" in sys.argv:
        extent_km = float(sys.argv[sys.argv.index("--extent") + 1])

    settings = Settings.load()
    settings.overture.release = RELEASE
    settings.cleaning = CLEANING.model_copy()
    if mode == "untiled":
        settings.cleaning.street_tile_size_m = None
        settings.cleaning.street_tile_buffer_m = None

    bbox = BERLIN if extent_km is None else _shrink(BERLIN, extent_km)
    source = OvertureSource(settings)

    print(f"{mode} run over {bbox}", file=sys.stderr, flush=True)
    fetch_started = time.time()
    cleaned = clean_vectors(
        source,
        bbox,
        settings.cleaning,
        cache_dir=settings.tile_cache_dir if mode == "tiled" else None,
    )
    elapsed = time.time() - fetch_started

    street_step = next(
        step for step in cleaned.report.steps if step.operation.startswith("simplify_streets")
    )
    print(
        f"\n{mode}: {elapsed / 60:.1f} min\n"
        f"  buildings {street_step.n_in} streets in -> {street_step.n_out} out\n"
        f"  buildings_area {len(cleaned.buildings_area)}, "
        f"buildings_topo {len(cleaned.buildings_topo)}\n"
        f"  street step detail: {street_step.detail}\n"
        f"  area retention (buildings_area): {cleaned.report.area_retention('buildings_area')}",
        flush=True,
    )

    record: dict[str, Any] = {
        "experiment": "phase-8-scaling",
        "mode": mode,
        "bbox": bbox,
        "extent_km": extent_km,
        "run_id": settings.run_id,
        "overture_release": RELEASE,
        "cleaning": settings.cleaning.model_dump(mode="json"),
        "elapsed_s": round(elapsed, 1),
        "n_streets_in": street_step.n_in,
        "n_streets_out": street_step.n_out,
        "street_detail": street_step.detail,
        "n_buildings_area": len(cleaned.buildings_area),
        "n_buildings_topo": len(cleaned.buildings_topo),
        "area_retention": cleaned.report.area_retention("buildings_area"),
        "report": cleaned.report.model_dump(mode="json"),
    }
    suffix = mode if extent_km is None else f"{mode}_{extent_km:.0f}km"
    destination = settings.run_dir / f"berlin_metropolitan_{suffix}.json"
    destination.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"wrote {destination}")


if __name__ == "__main__":
    main()
