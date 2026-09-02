"""Validate the 107 primary morphometric attributes against real Overture data for Nairobi.

    uv run --active python scripts/test_morphometrics_nairobi.py [--extent-km 3]

Not a unit test (needs DATA_DIR and the network) and not a scaling sweep — a single real-city
smoke test confirming `compute_morphometrics` produces a schema-correct, sane table on a city
whose building fabric (OSM coverage, footprint density) is materially different from the Berlin
extents `scripts/morphometrics_scaling.py` measured. `--extent-km` defaults small: Phase 29's own
scaling measurement found 12 322 ETCs (a 16 km² Berlin window) taking ~17 minutes for the primary
attributes alone, so an unbounded Nairobi run (its GUPPD region is ~680 km²) is not attempted.

Checks: every column in the registry is present and vice versa; every column is fully numeric;
no column is entirely null; the documented [0, 1]-bounded ratios stay in range (with the two
known exceptions `coverage_area_ratio_etc`/`square_compactness*`, which are not bounded); ETC
count and wall time, for comparison against the Berlin scaling table.
"""

from __future__ import annotations

import sys
import time

from lczkit.cleaning.pipeline import clean_vectors
from lczkit.config import MorphometricsConfig, Settings
from lczkit.morphometrics.compute import compute_morphometrics
from lczkit.morphometrics.registry import PARAMETER_COLUMNS, PARAMETERS
from lczkit.places import load_places, place
from lczkit.presets import apply_preset
from lczkit.protocols import BBox

CITY = "nairobi"
DEFAULT_EXTENT_KM = 3.0

#: The same "area over an enclosing shape" ratios `test_morphometrics_compute.py` checks —
#: guaranteed in [0, 1] because the denominator's shape always contains the numerator's.
#: `square_compactness*` and `coverage_area_ratio_etc*` are deliberately excluded: Phase 29 found
#: both are not bounded above, on real ETC geometry.
BOUNDED_FRACTIONS = tuple(
    name
    for name in PARAMETER_COLUMNS
    if name.startswith(("courtyard_index", "circular_compactness", "convexity", "rectangularity"))
)


def shrink(bbox: BBox, extent_km: float) -> BBox:
    """A concentric `extent_km`-side square around the centre of `bbox`."""
    import math

    minx, miny, maxx, maxy = bbox
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    half_lat = (extent_km / 2) / 111.0
    half_lon = half_lat / max(math.cos(math.radians(cy)), 0.01)
    return (cx - half_lon, cy - half_lat, cx + half_lon, cy + half_lat)


def main() -> None:
    extent_km = DEFAULT_EXTENT_KM
    if "--extent-km" in sys.argv:
        extent_km = float(sys.argv[sys.argv.index("--extent-km") + 1])

    settings = apply_preset(Settings.load(run_id=f"morphometrics-test-{CITY}"))
    found = place(load_places(settings), CITY)
    bbox = shrink(found.bbox, extent_km)
    print(f"{found.name}, {found.country} — {extent_km} km window: {bbox}", flush=True)

    print("cleaning...", flush=True)
    from lczkit.sources.overture import OvertureSource

    cleaned = clean_vectors(
        OvertureSource(settings), bbox, settings.cleaning, cache_dir=settings.tile_cache_dir
    )
    print(
        f"  {len(cleaned.buildings_area):,} buildings, {len(cleaned.streets):,} streets",
        flush=True,
    )

    print("computing morphometrics...", flush=True)
    started = time.perf_counter()
    result, report = compute_morphometrics(
        bbox,
        cleaned.buildings_area,
        cleaned.streets,
        cleaned.waterbodies,
        config=MorphometricsConfig(enabled=True),
    )
    seconds = time.perf_counter() - started
    attribute_columns = [c for c in result.columns if c != "geometry"]

    print(f"\n{'=' * 70}")
    print(f"{report.tessellation.n_etc:,} ETCs in {seconds:.1f} s")
    print(f"tessellation report: {report.tessellation}")

    ok = True

    missing = sorted(set(PARAMETER_COLUMNS) - set(attribute_columns))
    extra = sorted(set(attribute_columns) - set(PARAMETER_COLUMNS))
    if missing or extra:
        ok = False
        print(f"FAIL registry mismatch — missing: {missing}, extra: {extra}")
    else:
        print(f"OK   all {len(PARAMETER_COLUMNS)} registered columns present, no extras")

    non_numeric = [
        c for c in attribute_columns if not str(result[c].dtype).startswith(("float", "int"))
    ]
    if non_numeric:
        ok = False
        print(f"FAIL non-numeric columns: {non_numeric}")
    else:
        print("OK   every column is numeric")

    all_null = [c for c in attribute_columns if result[c].isna().all()]
    if all_null:
        ok = False
        print(f"FAIL entirely-null columns: {all_null}")
    else:
        print("OK   no column is entirely null")

    null_fractions = result[attribute_columns].isna().mean().sort_values(ascending=False)
    print("\nnull fraction, top 10 (some nulls are expected — e.g. no qualifying neighbour):")
    for name, frac in null_fractions.head(10).items():
        print(f"  {name:<45} {frac:.1%}")

    out_of_range: list[str] = []
    for column in BOUNDED_FRACTIONS:
        values = result[column].dropna()
        if values.empty:
            continue
        if (values < -1e-6).any() or (values > 1.0 + 1e-4).any():
            out_of_range.append(column)
    if out_of_range:
        ok = False
        print(f"FAIL bounded ratios out of [0, 1]: {out_of_range}")
    else:
        print(f"OK   all {len(BOUNDED_FRACTIONS)} geometrically-bounded ratios stay in [0, 1]")

    print("\nsample stats (median):")
    for column in ["area_building", "area_etc", "coverage_area_ratio_etc", "street_length"]:
        if column in result.columns:
            print(f"  {column:<30} median={result[column].median():.2f}")

    assert set(p.name for p in PARAMETERS) == set(PARAMETER_COLUMNS)  # registry self-consistency

    print(
        f"\n{'PASS' if ok else 'FAIL'} — {CITY}, {extent_km} km, {report.tessellation.n_etc:,} ETCs"
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
