"""How the parameter stage scales after the unit overlays were shared, and what sharing saved.

    uv run --active python scripts/ucp_overlay_scaling.py [--extents 16,64,144,256]

**Why this exists rather than a claim.** CLAUDE.md's standing anti-pattern is that no whole-extent
operation may be introduced without measuring its scaling exponent at three or more extents. That
rule has already paid twice here — `neatnet`'s superlinearity cost fifteen hours before anyone
looked, and Phase 12's footprint union looked like a cheap scalar and ran 711 s at Berlin's extent.
`compute_parameters` now performs two `gpd.overlay` calls that every downstream block reads,
instead of each block performing its own, and "fewer, larger overlays" is exactly the shape of
change that can be faster on a fixture and steeper at metropolitan extent.

**What it measures, stated precisely because the two easy overstatements are both wrong.** Per
extent: wall time for the parameter stage's three layer-reading blocks, and the number of overlays
and rows each arm pushes through `gpd.overlay`.

- `shared` is what `ucp.parameters` does: each layer intersected once, the pieces handed down.
- `separate` is what a **direct caller** gets — each block intersecting the layers it needs for
  itself, five overlays in total.

`separate` is **not** the pre-consolidation code. That code ran seventeen overlays because
`semantic_metrics` intersected a layer once per configured group; group selection is now a mask
over pieces, so the old pattern no longer exists to run and this script cannot measure it. The 17
figure is measured on the Hong Kong fixture against the implementation as it stood before, and is
recorded there. What this script answers is the question the anti-pattern actually asks: whether
concentrating the work into two large intersections makes the stage *steeper in extent* than
leaving it as five smaller ones.

Reads Overture through the ordinary cache under `input/Overture_Maps/`. Writes one JSON report into
the run directory and nothing else.
"""

from __future__ import annotations

import json
import math
import sys
import time
from collections.abc import Callable
from typing import Any

import geopandas as gpd

from lczkit.cleaning.pipeline import clean_vectors
from lczkit.config import Settings, UcpConfig
from lczkit.heights.cascade import fill_heights
from lczkit.heights.tiers import build_cascade
from lczkit.presets import apply_preset
from lczkit.protocols import BBox
from lczkit.sources.overture import OvertureSource
from lczkit.ucp.attributes import ATTRIBUTES
from lczkit.ucp.buildings import OVERLAY_COLUMNS, building_metrics
from lczkit.ucp.industrial import industrial_metrics
from lczkit.ucp.semantics import semantic_metrics
from lczkit.units.grid import GridUnits
from lczkit.units.overlay import unit_pieces

#: Berlin's centre, and the extents are concentric squares around it — the same shape
#: `scripts/phase8_step_scaling.py` uses, so a number here is comparable with one there.
CENTRE = (13.4050, 52.5200)

DEFAULT_EXTENTS = (16, 64, 144, 256)
"""Four, where the anti-pattern asks for three. A four-point fit is what distinguishes a genuine
exponent from two points and a straight line through them."""


class CountingOverlay:
    """Counts what goes through `gpd.overlay` while it is installed.

    Patched over the module attribute rather than measured by instrumenting each call site: the
    question is how much geometry the stage pushes through the library in total, and a call the
    patch missed would be a call the answer is wrong by.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.rows = 0
        self._real: Callable[..., Any] | None = None

    def __enter__(self) -> CountingOverlay:
        self._real = gpd.overlay

        def counting(left: Any, right: Any, **kwargs: Any) -> Any:
            self.calls += 1
            self.rows += len(right)
            assert self._real is not None
            return self._real(left, right, **kwargs)

        gpd.overlay = counting  # type: ignore[assignment]
        return self

    def __exit__(self, *_: object) -> None:
        assert self._real is not None
        gpd.overlay = self._real  # type: ignore[assignment]


def window(extent_km2: int) -> BBox:
    """A concentric lon/lat window of roughly `extent_km2` square kilometres."""
    half_km = math.sqrt(extent_km2) / 2
    half_lat = half_km / 111.0
    half_lon = half_lat / max(math.cos(math.radians(CENTRE[1])), 0.01)
    return (
        CENTRE[0] - half_lon,
        CENTRE[1] - half_lat,
        CENTRE[0] + half_lon,
        CENTRE[1] + half_lat,
    )


def prepare(settings: Settings, bbox: BBox) -> tuple[Any, Any, gpd.GeoDataFrame]:
    """Clean the extent and fill heights, returning what the parameter stage consumes."""
    cleaned = clean_vectors(
        OvertureSource(settings), bbox, settings.cleaning, cache_dir=settings.tile_cache_dir
    )
    tiers = build_cascade(settings.heights, settings.source_dir)
    buildings, _ = fill_heights(cleaned.buildings_area, tiers)
    units = GridUnits(cell_size_m=settings.units.cell_size_m).generate(bbox, None)
    return buildings, cleaned.land_use, units


def measure(
    buildings: gpd.GeoDataFrame,
    land_use: gpd.GeoDataFrame,
    units: gpd.GeoDataFrame,
    *,
    shared: bool,
) -> dict[str, Any]:
    """One arm: the three blocks that read the two layers, timed and counted."""
    config = UcpConfig()
    with CountingOverlay() as counter:
        started = time.perf_counter()
        building_pieces = unit_pieces(units, buildings, columns=OVERLAY_COLUMNS) if shared else None
        land_use_pieces = unit_pieces(units, land_use, columns=ATTRIBUTES) if shared else None

        morphology = building_metrics(buildings, units, config, pieces=building_pieces)
        building_area_m2 = morphology["building_surface_fraction"] * units.geometry.area
        industrial = industrial_metrics(
            buildings,
            land_use,
            units,
            config,
            building_area_m2=building_area_m2,
            building_pieces=building_pieces,
            land_use_pieces=land_use_pieces,
        )
        semantic = semantic_metrics(
            buildings,
            land_use,
            units,
            config,
            building_area_m2=building_area_m2,
            building_pieces=building_pieces,
            land_use_pieces=land_use_pieces,
        )
        seconds = time.perf_counter() - started

    return {
        "arm": "shared" if shared else "separate",
        "seconds": round(seconds, 3),
        "overlay_calls": counter.calls,
        "overlay_rows": counter.rows,
        "n_columns": int(morphology.shape[1] + industrial.shape[1] + semantic.shape[1]),
    }


def exponent(results: list[dict[str, Any]], arm: str) -> float | None:
    """Least-squares slope of log(seconds) against log(extent), for one arm.

    The quantity the anti-pattern is about: 1.0 is linear in area, and anything approaching 2.0 is
    the shape that has twice made a step here unusable at metropolitan extent.
    """
    points = [
        (math.log(row["extent_km2"]), math.log(row[arm]["seconds"]))
        for row in results
        if row[arm]["seconds"] > 0
    ]
    if len(points) < 2:
        return None
    n = len(points)
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    denominator = sum((x - mean_x) ** 2 for x, _ in points)
    if denominator == 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in points) / denominator


def show(results: list[dict[str, Any]]) -> None:
    """Print the table, then the two exponents and the saving."""
    print(
        f"\n{'km2':>6} {'units':>8} {'bldgs':>8} {'parcels':>8}  "
        f"{'separate s':>11} {'shared s':>9} {'x':>6}  "
        f"{'sep calls':>10} {'sh calls':>9}  {'sep rows':>10} {'sh rows':>9}"
    )
    for row in results:
        separate, shared = row["separate"], row["shared"]
        speedup = separate["seconds"] / shared["seconds"] if shared["seconds"] else float("nan")
        print(
            f"{row['extent_km2']:>6} {row['n_units']:>8,} {row['n_buildings']:>8,} "
            f"{row['n_land_use']:>8,}  {separate['seconds']:>11.2f} {shared['seconds']:>9.2f} "
            f"{speedup:>6.2f}  {separate['overlay_calls']:>10} {shared['overlay_calls']:>9}  "
            f"{separate['overlay_rows']:>10,} {shared['overlay_rows']:>9,}"
        )

    for arm in ("separate", "shared"):
        value = exponent(results, arm)
        print(f"\n{arm:>8} scaling exponent in extent: {value:.2f}" if value else f"{arm}: n/a")

    total_separate = sum(row["separate"]["seconds"] for row in results)
    total_shared = sum(row["shared"]["seconds"] for row in results)
    print(
        f"\ntotal {total_separate:.1f} s separate against {total_shared:.1f} s shared "
        f"({total_separate / total_shared:.2f}x)"
    )
    print(
        "Read the exponent, not only the ratio: a change that is faster at 16 km2 and steeper in "
        "extent is the failure this script exists to catch."
    )


def main() -> None:
    """Measure both arms at each extent and write the report into the run directory."""
    extents = DEFAULT_EXTENTS
    if "--extents" in sys.argv:
        extents = tuple(int(part) for part in sys.argv[sys.argv.index("--extents") + 1].split(","))

    settings = apply_preset(Settings.load(run_id="ucp-overlay-scaling"))
    results: list[dict[str, Any]] = []
    for extent_km2 in extents:
        bbox = window(extent_km2)
        print(f"[{extent_km2} km2] cleaning {bbox}", flush=True)
        buildings, land_use, units = prepare(settings, bbox)
        row: dict[str, Any] = {
            "extent_km2": extent_km2,
            "bbox": list(bbox),
            "n_units": int(len(units)),
            "n_buildings": int(len(buildings)),
            "n_land_use": int(len(land_use)),
        }
        # Separate first, so the shared arm cannot benefit from a warm cache the other paid for.
        for shared in (False, True):
            arm = measure(buildings, land_use, units, shared=shared)
            row[arm["arm"]] = arm
            print(
                f"  {arm['arm']:>8}: {arm['seconds']:.2f} s, "
                f"{arm['overlay_calls']} overlays over {arm['overlay_rows']:,} rows",
                flush=True,
            )
        results.append(row)

    show(results)
    report = settings.run_dir / "ucp_overlay_scaling.json"
    report.write_text(
        json.dumps(
            {
                "centre": list(CENTRE),
                "overture_release": settings.overture.release,
                "semantic_groups": [group.name for group in settings.ucp.semantic_groups],
                "results": results,
                "exponents": {arm: exponent(results, arm) for arm in ("separate", "shared")},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {report}")


if __name__ == "__main__":
    main()
