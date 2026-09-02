"""How `compute_morphometrics` scales with extent, and what that sets the cell-count ceilings to.

    uv run --active python scripts/morphometrics_scaling.py [--extents 1,4,9,16]

CLAUDE.md's standing anti-pattern: no whole-extent operation ships without measuring its scaling
exponent at three or more extents first. This is a *new* whole-extent operation — one enclosed
tessellation cell per building, three metric blocks, several `libpysal.graph` constructions per
extent — so `MorphometricsConfig.max_tessellation_cells`/`max_contextual_cells` are set from this
script's own numbers rather than copied from `LandCoverConfig.max_raster_cells`'s ceiling, which
measures a different operation (zonal raster reduction, not per-building tessellation).

Extents are concentric squares in km2, an order of magnitude smaller than
`scripts/ucp_overlay_scaling.py`'s: per-building tessellation is markedly more expensive per unit
area than a unit/layer overlay, so a fair comparison needs a correspondingly smaller range to stay
inside a few minutes per point.

Reads Overture through the ordinary cache under `input/Overture_Maps/`. Writes one JSON report
into the run directory and nothing else.
"""

from __future__ import annotations

import json
import math
import sys
import time
from typing import Any

from lczkit.cleaning.pipeline import clean_vectors
from lczkit.config import MorphometricsConfig, Settings
from lczkit.morphometrics.compute import compute_morphometrics
from lczkit.morphometrics.contextual import contextual_expand
from lczkit.morphometrics.graphs import etc_contiguity, etc_higher_order
from lczkit.morphometrics.raster import rasterize_attributes
from lczkit.presets import apply_preset
from lczkit.protocols import BBox
from lczkit.sources.overture import OvertureSource

#: Berlin's centre, the same point `scripts/ucp_overlay_scaling.py` and
#: `scripts/phase8_step_scaling.py` use, so a number here is comparable with one there.
CENTRE = (13.4050, 52.5200)

DEFAULT_EXTENTS_KM2 = (1, 4, 9, 16)


def window(extent_km2: float) -> BBox:
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


def exponent(points: list[tuple[float, float]]) -> float | None:
    """Least-squares slope of log(seconds) against log(extent) — 1.0 is linear in area."""
    points = [(x, y) for x, y in points if y > 0]
    if len(points) < 2:
        return None
    n = len(points)
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    denominator = sum((x - mean_x) ** 2 for x, _ in points)
    if denominator == 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in points) / denominator


def main() -> None:
    extents = DEFAULT_EXTENTS_KM2
    if "--extents" in sys.argv:
        extents = tuple(
            float(part) for part in sys.argv[sys.argv.index("--extents") + 1].split(",")
        )

    settings = apply_preset(Settings.load(run_id="morphometrics-scaling"))
    source = OvertureSource(settings)
    results: list[dict[str, Any]] = []

    for extent_km2 in extents:
        bbox = window(extent_km2)
        print(f"[{extent_km2} km2] cleaning {bbox}", flush=True)
        cleaned = clean_vectors(source, bbox, settings.cleaning, cache_dir=settings.tile_cache_dir)

        started = time.perf_counter()
        primary, report = compute_morphometrics(
            bbox,
            cleaned.buildings_area,
            cleaned.streets,
            cleaned.waterbodies,
            config=MorphometricsConfig(enabled=True),
        )
        primary_seconds = time.perf_counter() - started
        n_etc = report.tessellation.n_etc
        print(
            f"  primary: {primary_seconds:.2f} s, {n_etc:,} ETCs, "
            f"{report.n_primary_attributes} attributes",
            flush=True,
        )

        attribute_columns = [c for c in primary.columns if c != "geometry"]
        contextual_graph = etc_higher_order(etc_contiguity(primary), 3)
        started = time.perf_counter()
        contextual = contextual_expand(primary[attribute_columns], contextual_graph)
        contextual_seconds = time.perf_counter() - started
        print(
            f"  contextual: {contextual_seconds:.2f} s, {contextual.shape[1]} attributes",
            flush=True,
        )

        raster_path = settings.run_dir / f"morphometrics_{extent_km2}km2.tif"
        started = time.perf_counter()
        raster_report = rasterize_attributes(primary, 10.0, raster_path, max_cells=10**9)
        raster_seconds = time.perf_counter() - started
        print(
            f"  raster (10 m): {raster_seconds:.2f} s, "
            f"{raster_report.n_rows}x{raster_report.n_cols} pixels",
            flush=True,
        )
        raster_path.unlink(missing_ok=True)

        results.append(
            {
                "extent_km2": extent_km2,
                "n_etc": n_etc,
                "n_enclosures": report.tessellation.n_enclosures,
                "n_buildings_in": report.tessellation.n_buildings_in,
                "primary_seconds": round(primary_seconds, 3),
                "contextual_seconds": round(contextual_seconds, 3),
                "raster_10m_seconds": round(raster_seconds, 3),
                "raster_10m_pixels": raster_report.n_rows * raster_report.n_cols,
            }
        )

    print(f"\n{'km2':>6} {'ETCs':>8} {'primary s':>10} {'contextual s':>13} {'raster s':>9}")
    for row in results:
        print(
            f"{row['extent_km2']:>6} {row['n_etc']:>8,} {row['primary_seconds']:>10.2f} "
            f"{row['contextual_seconds']:>13.2f} {row['raster_10m_seconds']:>9.2f}"
        )

    exponents = {
        "primary_vs_etc": exponent(
            [(math.log(r["n_etc"]), math.log(r["primary_seconds"])) for r in results if r["n_etc"]]
        ),
        "contextual_vs_etc": exponent(
            [
                (math.log(r["n_etc"]), math.log(r["contextual_seconds"]))
                for r in results
                if r["n_etc"]
            ]
        ),
        "primary_vs_extent": exponent(
            [(math.log(r["extent_km2"]), math.log(r["primary_seconds"])) for r in results]
        ),
    }
    for name, value in exponents.items():
        print(f"{name} exponent: {value:.2f}" if value is not None else f"{name}: n/a")

    report_path = settings.run_dir / "morphometrics_scaling.json"
    report_path.write_text(
        json.dumps(
            {
                "centre": list(CENTRE),
                "overture_release": settings.overture.release,
                "results": results,
                "exponents": exponents,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {report_path}")


if __name__ == "__main__":
    main()
