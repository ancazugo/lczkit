"""Phase 9: the same pipeline over ten or more So2Sat cities, scored against real labels.

    uv run --active python scripts/multi_city_validation.py --list
    uv run --active python scripts/multi_city_validation.py berlin sao_paulo jakarta
    uv run --active python scripts/multi_city_validation.py --all

**Everything known about lczkit's accuracy came from one city.** Berlin's 40.9% against a 53.2%
ceiling may be typical, fortunate or unfortunate, and this project's history is of single
measurements turning out to be artefacts. Phase 8 made the question askable: a city cleans in
minutes rather than never, and So2Sat's labelled patches for 51 cities are already on local disk.

Three questions in one pass, per CLAUDE.md's Phase 9:

1. **A vs B.** Enclosures led Berlin 45.4% to 40.9% against labels, but the whole lead lived in
   one class of one city, which is why the decision was deferred twice. Unit definition is 55.2%
   of Berlin's disagreement — the largest available lever — so it is decided here or not at all.
2. **A distribution rather than a point estimate**, for both agreement and the ceiling. The
   ceiling matters as much as the score: `lcz_v3` is a model with its own error, and on Berlin it
   clears only 53.2% against the labels it is being used to stand in for.
3. **`height_tier_fractions` outside Europe.** The height cascade was built for cities where OSM
   heights fail and had never run outside Europe. See `HEIGHT TIERS` below for what this run can
   and cannot test.

**Extent: a 30 km window, not the full So2Sat bbox.** Those bboxes run 3 800–9 100 km², four to
ten times the 891 km² Berlin extent measured at 9.8 minutes, and enclosure generation has never
been measured above 16 km². A 30 km window is ~900 km² — directly comparable to the Berlin
baseline — and centred on the densest cluster of labelled patches it retains 31–95% of a city's
patches, median about half. That still leaves 1 700–16 600 labelled cells per city, against the
432 the 40.9% baseline was computed from. The binding constraint is representativeness, not
sample size, and it is recorded per city as `patch_retention`.

**HEIGHT TIERS — what this measures and what it does not.** Tiers 2–4 are areal products that
CLAUDE.md has the *user* place under `input/GOB25D/`, `input/WSF3D/` or `input/GHSL/`. None of
those directories exists on this system, so `build_cascade` skips all three and the cascade runs
tier 1 alone. Every building Overture cannot answer for is therefore tagged `unresolved` with a
null height, and `height_frac_unresolved` is the share of building area in that state.

That measures the **premise** the package was built on — that Overture's heights collapse outside
Europe — and it measures it for the first time. It does **not** test the package's answer to it:
no areal tier has ever fired against real data. Those are different claims and this run can only
make the first. GHS-BUILT-H is reachable at ~42 MB per tile and `lczkit.heights.raster.zonal_mean`
already reprojects into its Mollweide grid, so the second is cheap to arrange — but it needs the
product placed, and placing it is not this script's call to make.

**Where it writes.** Everything goes to `output/lczkit/<run_id>/`. The two exceptions are
Overture's own cache under `input/Overture_Maps/`, which `OvertureSource` owns and which this run
adds new entries to, and the per-tile street cache under `output/lczkit/_cache/`. Nothing existing
under `input/` is modified or removed. The rasters are clipped into the run directory, not into
`input/`, because a clip keyed to one experiment's window is not a source cache.
"""

from __future__ import annotations

import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np

from lczkit.classify import PrototypeClassifier
from lczkit.config import Settings
from lczkit.protocols import BBox
from lczkit.sources.overture import OvertureSource

sys.path.insert(0, str(Path(__file__).resolve().parent))

from berlin_metropolitan import CLEANING, RELEASE  # noqa: E402 - sibling script
from berlin_wide_validation import (  # noqa: E402 - sibling script
    LCZ_SOURCE_DIR_NAME,
    LCZ_SOURCE_FILENAME,
    SO2SAT_SOURCE_DIR_NAME,
    WUDAPT_SOURCE_DIR_NAME,
    WUDAPT_SOURCE_FILENAME,
    clip_patches,
    clip_raster,
    # Lives beside `clip_raster` rather than here because that module is imported *by* this one
    # and so cannot import back. Re-exported through this import, which is where
    # `berlin_metropolitan_run` and `publish_sites` already look for it.
    clip_worldcover,
    clip_wudapt,
)
from unit_scale_experiment import (  # noqa: E402 - sibling script
    HEIGHTS,
    UCP,
    VALIDATION,
    Fixture,
    build_arms,
    evaluate,
    show,
)

WINDOW_KM = 30.0
"""Side of the square window, in kilometres. ~900 km2, matching the measured Berlin extent."""

SO2SAT_CITIES = Path("v4") / "cities"

MIN_PATCHES = 500
MIN_CLASSES = 4
"""Screening floor. Not every So2Sat city is usable: Karachi has 1 140 patches of a *single*
class, Manila 384 of one class and Dhaka 30 of one. A city with one class has no confusion axis,
so it cannot answer any of the three questions and its agreement figure is arithmetic rather
than evidence. Screened on the window actually run, not on the city's full extent."""


@dataclass(frozen=True)
class City:
    """One So2Sat city: where its labels live and which continent it speaks for."""

    key: str
    so2sat: str
    """Directory name under `input/So2Sat-LCZ42/v4/cities/`."""

    region: str


#: Chosen by measuring labelled-patch density inside a 30 km window across all 51 cities on disk,
#: not by picking recognisable names. São Paulo is required by CLAUDE.md; Jakarta, Islamabad and
#: Mumbai are the viable South/Southeast Asian options, the obvious candidates having failed the
#: screen above. Europe is over-represented because that is where So2Sat's dense coverage is, and
#: the per-region breakdown in the report says so rather than averaging it away.
CITIES = (
    City("berlin", "Berlin", "Europe"),
    City("london", "London", "Europe"),
    City("paris", "Paris", "Europe"),
    City("cologne", "Cologne", "Europe"),
    City("rome", "Rome", "Europe"),
    City("milan", "Milan", "Europe"),
    City("sao_paulo", "Sao_Paulo", "South America"),
    City("rio_de_janeiro", "Rio_De_Janeiro", "South America"),
    City("cairo", "Cairo", "Africa"),
    City("nairobi", "Nairobi", "Africa"),
    City("cape_town", "Cape_Town", "Africa"),
    City("islamabad", "Rawalpindi_[Islamabad]", "South Asia"),
    City("mumbai", "Mumbai", "South Asia"),
    City("jakarta", "Jakarta", "Southeast Asia"),
    City("hong_kong", "Hong_Kong", "East Asia"),
    City("vancouver", "Vancouver", "North America"),
)

BY_KEY = {city.key: city for city in CITIES}


def densest_window(patches: gpd.GeoDataFrame, side_km: float = WINDOW_KM) -> BBox:
    """The `side_km` square holding the most labelled patch centres, as a lon/lat bbox.

    Searched over a quantile grid of candidate centres rather than optimised: the objective is
    piecewise constant and this is deterministic, which matters more here than optimality — a
    window that moved between runs would make two runs of the same city incomparable.

    Centres, not areas. So2Sat patches are 320 m squares on a 100 m stride and overlap about
    sevenfold, so counting area would measure the sampling density rather than the city; the same
    reason `lczkit.validation.labelled` anchors each label on its patch centre.
    """
    utm = patches.estimate_utm_crs()
    centres = patches.to_crs(utm).geometry.centroid
    x, y = centres.x.to_numpy(), centres.y.to_numpy()
    half = side_km * 1000.0 / 2.0

    best = (-1, float(np.median(x)), float(np.median(y)))
    grid = np.linspace(0.05, 0.95, 19)
    for cx in np.quantile(x, grid):
        for cy in np.quantile(y, grid):
            n = int(((np.abs(x - cx) <= half) & (np.abs(y - cy) <= half)).sum())
            if n > best[0]:
                best = (n, float(cx), float(cy))
    _, cx, cy = best

    centre = gpd.GeoSeries(gpd.points_from_xy([cx], [cy]), crs=utm).to_crs("EPSG:4326")
    lon, lat = float(centre.x.iloc[0]), float(centre.y.iloc[0])
    half_lat = side_km / 2.0 / 111.0
    half_lon = half_lat / max(math.cos(math.radians(lat)), 0.01)
    return (lon - half_lon, lat - half_lat, lon + half_lon, lat + half_lat)


def prepare(city: City, settings: Settings) -> tuple[Fixture, dict[str, Any]] | None:
    """Clip a city's three references into the run directory and describe its window.

    Returns `None` when the window fails the screen, with the reason printed — a city that cannot
    answer the question must be visibly excluded rather than quietly averaged in.
    """
    source = settings.source_dir(SO2SAT_SOURCE_DIR_NAME) / SO2SAT_CITIES / city.so2sat
    patches_path = source / f"patches_reference_{city.so2sat}.gpkg"
    if not patches_path.is_file():
        print(f"  {city.key}: no So2Sat patches at {patches_path}", file=sys.stderr)
        return None

    patches = gpd.read_file(patches_path)
    bbox = densest_window(patches)
    inside = patches.cx[bbox[0] : bbox[2], bbox[1] : bbox[3]]
    classes = sorted(int(value) for value in inside["LCZ_class"].unique())
    if len(inside) < MIN_PATCHES or len(classes) < MIN_CLASSES:
        print(
            f"  {city.key}: SKIPPED — {len(inside)} patches across {len(classes)} classes in the "
            f"window (need {MIN_PATCHES} and {MIN_CLASSES})",
            file=sys.stderr,
        )
        return None

    run = settings.run_dir
    worldcover = clip_worldcover(bbox, run / f"worldcover_{city.key}.tif")
    reference = clip_raster(
        str(settings.source_dir(LCZ_SOURCE_DIR_NAME) / LCZ_SOURCE_FILENAME),
        run / f"lcz_reference_{city.key}.tif",
        bbox,
    )
    ground_truth = clip_patches(patches_path, run / f"so2sat_{city.key}.parquet", bbox)
    # Added in Phase 16. `None` where the export is absent or the window holds no polygon, which
    # is a state the record has to be able to show — a city scored against two references and one
    # scored against three must not look the same.
    wudapt = clip_wudapt(
        settings.source_dir(WUDAPT_SOURCE_DIR_NAME) / WUDAPT_SOURCE_FILENAME,
        run / f"wudapt_{city.key}.parquet",
        bbox,
    )

    fixture = Fixture(
        name=city.key,
        bbox=bbox,
        vectors=lambda: OvertureSource(settings),
        worldcover=worldcover,
        reference=reference,
        ground_truth=ground_truth,
        wudapt=wudapt,
    )
    window = {
        "region": city.region,
        "so2sat_city": city.so2sat,
        "bbox": list(bbox),
        "window_km": WINDOW_KM,
        "n_patches_city": int(len(patches)),
        "n_patches_window": int(len(inside)),
        "patch_retention": float(len(inside) / len(patches)),
        "classes_in_window": classes,
        "has_wudapt": wudapt is not None,
    }
    return fixture, window


def run_city(city: City, settings: Settings) -> dict[str, Any] | None:
    """One city end to end: clip, clean, three arms, score against both references."""
    prepared = prepare(city, settings)
    if prepared is None:
        return None
    fixture, window = prepared

    print(f"\n=== {city.key} ({city.region}) {window['bbox']}", file=sys.stderr, flush=True)
    started = time.time()
    # The tiled cleaning config, explicitly. `build_arms` defaults to the fixture-scale one,
    # which has no tiling — correct for 9 km2 and, at 900 km2, a whole-extent `neatify` that
    # neither finishes nor errors.
    arms, cleaned, provenance, completeness = build_arms(
        fixture, settings.cleaning, settings.tile_cache_dir
    )
    cleaned_s = time.time() - started
    print(f"  cleaned + arms in {cleaned_s:.0f}s; evaluating", file=sys.stderr, flush=True)

    results = evaluate(fixture, arms, provenance, cleaned.buildings_area, completeness)
    results["window"] = window
    results["elapsed_s"] = round(time.time() - started, 1)
    results["cascade"] = _cascade_tag(provenance)
    show(results)
    return results


def _cascade_tag(provenance: dict[str, Any]) -> str:
    """Which height tiers actually fired, as a name — `none`, `coarse`, `full`, or the tier list.

    Recorded per city rather than inferred from the config, because a tier configured but whose
    product is not on disk is silently skipped, and the difference is not visible in the config.
    Phase 12's ruling: tag every stored diagnostic with the configuration it was measured under.
    Phase 9's records are untagged and were read for three phases as though they described the
    shipped default, when they were measured at `none` — and Phase 10, which shipped `coarse`,
    was itself the intervention that invalidated them.
    """
    tiers = {
        entry["tier"]
        for entry in provenance.get("height_fill", {}).get("tiers", [])
        if entry.get("n_filled", 0) > 0 and not entry["tier"].startswith("overture")
    }
    if not tiers:
        return "none"
    if tiers == {"wsf3d", "ghsl"}:
        return "coarse"
    if tiers == {"gob25d", "wsf3d", "ghsl"}:
        return "full"
    return "+".join(sorted(tiers))


def _axes(report: dict[str, Any]) -> tuple[float, float]:
    """The two confusion axes as pair-normalised lift: (height, compactness).

    **Not the raw share.** Phase 12 retired it outright — "removed from reporting", not "use with
    care" — and this script was the one reporting path never migrated, so it went on summing
    `share_of_disagreement` across sixteen cities and taking medians of it. That quantity is not
    comparable in either direction: not across cities, where the denominator is all disagreement
    and the natural-class share ranges 3.5% to 54.1%, and not between the two axes, where height
    affords six confusable pairs to compactness's three and a null that never looks at the data
    still awards height 3.9x more error.

    `lift` divides the observed share by what a composition-preserving null affords, so 1.0 means
    "no more than the class mix already implies". Read it as a lower bound: the null draws wrong
    labels from the run's own error distribution, so a real concentration on one axis inflates the
    expectation it is measured against and pulls its own lift back toward 1.
    """
    height = report["height_axis_summary"]["lift"]
    compact = report["compactness_axis_summary"]["lift"]
    return float(height), float(compact)


def _quantiles(values: list[float]) -> str:
    if not values:
        return "—"
    array = np.asarray(values, dtype="float64")
    return (
        f"{array.min():.1%} / {np.median(array):.1%} / {array.max():.1%}"
        f"  (n={len(values)}, mean {array.mean():.1%})"
    )


def _points(values: list[float]) -> str:
    """Same shape as `_quantiles`, for a signed difference in percentage points."""
    if not values:
        return "—"
    array = 100.0 * np.asarray(values, dtype="float64")
    return (
        f"{array.min():+.1f} / {np.median(array):+.1f} / {array.max():+.1f}"
        f"  (n={len(values)}, mean {array.mean():+.1f})"
    )


def _lifts(values: list[float]) -> str:
    """Same shape as `_quantiles`, but a lift is a ratio and reads wrong as a percentage."""
    if not values:
        return "—"
    array = np.asarray(values, dtype="float64")
    return (
        f"{array.min():.2f} / {np.median(array):.2f} / {array.max():.2f}"
        f"  (n={len(values)}, mean {array.mean():.2f})"
    )


def summarise(record: dict[str, Any]) -> None:
    """The three questions Phase 9 was opened to answer, printed from the per-city records.

    Every figure is against **So2Sat labels**, never against `lcz_v3` — which appears here only
    as the ceiling, because it is a model with its own error and scoring against it reports the
    disagreement between two estimates as lczkit's.
    """
    cities = [c for c in record["cities"] if c.get("ground_truth")]
    if not cities:
        print("no city produced a labelled comparison")
        return

    print(f"\n{'=' * 100}\nPHASE 9 — {len(cities)} cities, {record['window_km']:.0f} km windows")

    print(
        f"\n{'city':16s}{'region':16s}{'cells':>7}{'ceiling':>9}{'A':>8}{'B':>8}"
        f"{'A built':>9}{'B built':>9}{'A-ceil':>8}{'hgt ax':>8}{'cmp ax':>8}{'tier1':>7}"
    )
    rows: list[dict[str, Any]] = []
    for city in cities:
        ceiling = city["reference_ceiling"]["overall_agreement"]
        arm_a = city["arms"]["A"]["agreement_ground_truth"]
        arm_b = city["arms"]["B"]["agreement_ground_truth"]
        height, compact = _axes(arm_a)
        tier1 = city["cleaning"].get("height_completeness_mean")
        row = {
            "city": city["fixture"],
            "region": city["window"]["region"],
            "n": arm_a["n_compared"],
            "ceiling": ceiling,
            "a": arm_a["overall_agreement"],
            "b": arm_b["overall_agreement"],
            "a_built": arm_a["built_agreement"],
            "b_built": arm_b["built_agreement"],
            "height_axis": height,
            "compactness_axis": compact,
            "tier1": tier1,
            "tiers": city["cleaning"].get("height_tier_fractions", {}),
        }
        rows.append(row)
        print(
            f"{row['city']:16s}{row['region']:16s}{row['n']:>7}{ceiling:>9.1%}"
            f"{row['a']:>8.1%}{row['b']:>8.1%}{row['a_built']:>9.1%}{row['b_built']:>9.1%}"
            f"{100 * (row['a'] - ceiling):>+8.1f}"
            f"{height:>8.2f}{compact:>8.2f}"
            f"{(f'{tier1:.0%}' if tier1 is not None else '—'):>7}"
        )

    print("\n1. DISTRIBUTION (min / median / max)")
    print(f"   ceiling, lcz_v3 vs labels   {_quantiles([r['ceiling'] for r in rows])}")
    print(f"   lczkit arm A vs labels      {_quantiles([r['a'] for r in rows])}")
    print(f"   arm A, built classes only   {_quantiles([r['a_built'] for r in rows])}")
    # Their *difference*, never their ratio. CLAUDE.md: "% of ceiling" is a broken metric, because
    # the comparator is another estimator rather than a bound — Vancouver scores 41.8% against a
    # 36.7% ceiling, which reads as 114% and means lczkit beat lcz_v3 there, not that it exceeded
    # what is achievable. Ceilings span 22.8% to 83.2%, so agreement is not comparable across
    # cities without its ceiling printed beside it, which is what the table above does.
    gap = [r["a"] - r["ceiling"] for r in rows]
    print(f"   arm A minus ceiling, points {_points(gap)}")

    print("\n2. A vs B — enclosures minus grid, in points, against labels")
    deltas = [
        (r["city"], 100 * (r["b"] - r["a"]), 100 * (r["b_built"] - r["a_built"])) for r in rows
    ]
    wins = sum(1 for _, d, _ in deltas if d > 0)
    for city, delta, built in sorted(deltas, key=lambda item: -item[1]):
        print(f"   {city:16s} overall {delta:+6.1f}   built {built:+6.1f}")
    mean_delta = float(np.mean([d for _, d, _ in deltas]))
    print(f"   B ahead in {wins} of {len(deltas)} cities; mean {mean_delta:+.1f} points")

    print("\n3. CONFUSION AXES — which lever is next")
    print("   Pair-normalised lift against a composition-preserving null; 1.00 = no more than the")
    print("   class mix already affords. The raw share was retired in Phase 12 and is not shown.")
    heights = [r["height_axis"] for r in rows]
    compacts = [r["compactness_axis"] for r in rows]
    print(f"   height axis (1-2-3, 4-5-6)       {_lifts(heights)}")
    print(f"   compactness axis (1-4, 2-5, 3-6) {_lifts(compacts)}")
    dominant = sum(1 for h, c in zip(heights, compacts, strict=True) if c > h)
    print(f"   compactness leads in {dominant} of {len(rows)} cities")

    print("\n4. HEIGHT TIER FRACTIONS — the founding premise, by region")
    print("   (share of building area; the cascade runs tier 1 only, see this module's docstring)")
    print(
        f"   {'city':16s}{'region':16s}{'overture_height':>16}{'num_floors':>12}{'unresolved':>12}"
    )
    for row in sorted(rows, key=lambda r: r["region"]):
        tiers = row["tiers"]
        print(
            f"   {row['city']:16s}{row['region']:16s}"
            f"{tiers.get('overture_height', 0.0):>16.1%}"
            f"{tiers.get('overture_num_floors', 0.0):>12.1%}"
            f"{tiers.get('unresolved', 0.0):>12.1%}"
        )


def main() -> None:
    if "--list" in sys.argv:
        for city in CITIES:
            print(f"{city.key:18s} {city.region:16s} {city.so2sat}")
        return

    if "--report" in sys.argv:
        path = Path(sys.argv[sys.argv.index("--report") + 1])
        summarise(json.loads(path.read_text(encoding="utf-8")))
        return

    requested = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--all" in sys.argv or not requested:
        selected = list(CITIES)
    else:
        unknown = [key for key in requested if key not in BY_KEY]
        if unknown:
            raise SystemExit(f"unknown city keys {unknown}; try --list")
        selected = [BY_KEY[key] for key in requested]

    settings = Settings.load()
    settings.overture.release = RELEASE
    settings.cleaning = CLEANING.model_copy()

    started = time.time()
    record: dict[str, Any] = {
        "experiment": "phase-9-multi-city-validation",
        "run_id": settings.run_id,
        "overture_release": RELEASE,
        "window_km": WINDOW_KM,
        "config": {
            "cleaning": settings.cleaning.model_dump(mode="json"),
            "heights": HEIGHTS.model_dump(mode="json"),
            "ucp": UCP.model_dump(mode="json"),
            "validation": VALIDATION.model_dump(mode="json"),
            "classification": PrototypeClassifier().describe(),
        },
        "cities": [],
        "skipped": [],
    }
    destination = settings.run_dir / "multi_city_validation.json"

    for city in selected:
        try:
            results = run_city(city, settings)
        except Exception as error:  # noqa: BLE001 - one city must not end the sweep
            print(f"  {city.key}: FAILED — {type(error).__name__}: {error}", file=sys.stderr)
            record["skipped"].append(
                {"city": city.key, "error": f"{type(error).__name__}: {error}"}
            )
            results = None
        if results is None:
            record["skipped"].append({"city": city.key, "reason": "screened or failed"})
        else:
            record["cities"].append(results)
        # Written after every city, so a sweep interrupted at city eight is still eight cities of
        # evidence rather than none.
        record["elapsed_s"] = round(time.time() - started, 1)
        destination.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")

    summarise(record)
    print(f"\nwrote {destination}")


if __name__ == "__main__":
    main()
