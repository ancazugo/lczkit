"""Phase 10: what the areal height tiers are worth, measured against pre-registered predictions.

    uv run --active python scripts/height_tier_experiment.py --list
    uv run --active python scripts/height_tier_experiment.py cairo
    uv run --active python scripts/height_tier_experiment.py --all
    uv run --active python scripts/height_tier_experiment.py --report <path.json>

**Phase 3 specified a four-tier cascade; only tier 1 was ever built.** `ArealRasterTier` and
`build_cascade` have been complete and tested since Phase 3 — what was missing was the data, so
every areal tier was skipped at every run for seven phases. Phase 9 showed what that costs:
tier-1 height coverage is 64.3% across Europe and North America and 9.6% everywhere else, and
built-class agreement tracks it at r = 0.67. With `Hr` null nearly everywhere the distance metric
runs on building surface fraction alone and the built types stop being separable *in principle*.

This runs the same harness as Phase 9 — same windows, same references, same metrics — over three
cascades against one cleaning, so a before/after difference is the cascade and nothing else.

    none    tier 1 only. Reproduces Phase 9, and is the comparability check.
    coarse  + WSF-3D (~90 m) and GHS-BUILT-H (100 m).
    full    + Google Open Buildings 2.5D (4 m), where it has coverage.

**The predictions are written into the report before the sweep runs** (`PREDICTIONS` below), so
the verdict cannot be composed after the numbers are in. Both come from CLAUDE.md's Phase 10.

**Where it writes.** Everything goes to `output/lczkit/<run_id>/`, except the height products
themselves, which `lczkit.sources.height_products` places under `input/GOB25D/`, `input/WSF3D/`
and `input/GHSL/`, and Overture's cache under `input/Overture_Maps/`. New files only; nothing
existing under `input/` is modified or removed.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Sequence
from functools import partial
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from lczkit.classify import PrototypeClassifier
from lczkit.config import HeightConfig, Settings
from lczkit.heights.cascade import UNRESOLVED, cascade_height_sources, fill_heights
from lczkit.heights.raster import zonal_mean
from lczkit.heights.tiers import OVERTURE_HEIGHT, OVERTURE_NUM_FLOORS, build_cascade
from lczkit.protocols import BBox
from lczkit.sources.height_products import resolve_areal_tiers
from lczkit.units.grid import GridUnits

sys.path.insert(0, str(Path(__file__).resolve().parent))

from berlin_metropolitan import CLEANING, RELEASE  # noqa: E402 - sibling script
from multi_city_validation import (  # noqa: E402 - sibling script
    BY_KEY,
    CITIES,
    prepare,
)
from unit_scale_experiment import (  # noqa: E402 - sibling script
    AREAL_CONFIDENCE,
    HEIGHTS,
    UCP,
    VALIDATION,
    Fixture,
    build_arms,
    clean_for_arms,
    evaluate,
)

TIER1 = (OVERTURE_HEIGHT, OVERTURE_NUM_FLOORS)

CASCADES: dict[str, tuple[str, ...]] = {
    "none": (),
    "coarse": ("wsf3d", "ghsl"),
    "full": ("gob25d", "wsf3d", "ghsl"),
    "full_reversed": ("wsf3d", "ghsl", "gob25d"),
}
"""The variants, in the order they are reported, **each tuple being the cascade order itself**.

`full` is finest-product-first, so a coarser tier only ever claims what a finer one could not.
`full_reversed` inverts that: the coarse products claim first and Open Buildings 2.5D gets only
what they left. Phase 11 measures the difference — see `cascade_for`, which orders the tiers by
this tuple rather than by the configured list, because a reordering experiment that quietly does
not reorder would report a confident null.
"""

#: The eight cities Phase 9 measured below 50% tier-1 coverage, plus Berlin as a high-coverage
#: control. Berlin gets no GOB 2.5D — the product stops at Europe — but WSF-3D and GHS-BUILT-H are
#: global, and 20.3% of its building area was still unresolved, so it is a real test rather than a
#: formality. It is also the only city with enough tier-1 heights to hold a large held-out set.
LOW_COVERAGE = (
    "sao_paulo",
    "rio_de_janeiro",
    "cairo",
    "nairobi",
    "cape_town",
    "islamabad",
    "mumbai",
    "jakarta",
)
SELECTED = ("berlin", *LOW_COVERAGE)

MIN_BUILDINGS_PER_UNIT = 5
"""Units below this are dropped from the within-unit statistics. A rank correlation over three
buildings is noise, and averaging noise across thousands of cells produces a confident zero."""

AREAL_READ = {tier.name: (tier.scale, tier.nodata) for tier in HeightConfig().areal_tiers}
"""Each product's unit scale and nodata, from its own documentation via `lczkit.config`."""

PREDICTIONS = {
    "P1": {
        "claim": (
            "Filling Hr is necessary but may not be sufficient. Areal products assign a "
            "neighbourhood mean and cannot resolve height bands WITHIN a unit, which is the axis "
            "Phase 9 found dominating. GOB 2.5D at 4 m should discriminate within a 100 m cell; "
            "GHS-BUILT-H at 100 m should not."
        ),
        "expected": [
            "within-unit height dispersion: tier1 > gob25d >> wsf3d > ghsl, with ghsl near zero",
            "held-out within-unit Spearman rho against tier 1: materially positive for gob25d, "
            "near zero for ghsl",
            "built-class agreement: full > coarse > none, with coarse->full the larger step",
        ],
        "source": "CLAUDE.md Phase 10, prediction 1",
    },
    "P2": {
        "claim": (
            "GHS-BUILT-H at 100 m matches the 100 m grid exactly and is coarser than most "
            "enclosures. If so it favours the grid, and is a fourth input to the A/B question."
        ),
        "expected": [
            "most enclosures are smaller than one 100 m cell (10 000 m2)",
            "B's built-class lead over A narrows once the coarse tiers fill heights",
        ],
        "source": "CLAUDE.md Phase 10, prediction 2",
    },
}


def cascade_for(
    settings: Settings, bbox: BBox, variant: str
) -> tuple[HeightConfig, dict[str, str | None]]:
    """A `HeightConfig` for `variant`, with every areal tier's file fetched and resolved.

    Returns the config and a record of which product answered for this window. A tier whose
    product has no coverage here — Open Buildings stops at Europe — is left out of the cascade
    rather than configured to read a file that is not there, which is the difference between a
    shorter cascade and a crash.

    **The tiers come back in `CASCADES[variant]` order, not in configured order.** The package
    default is `coarse`, so `gob25d` ships `enabled=False` and the configured list is no longer
    the thing a variant can be read off; and `full_reversed` differs from `full` in nothing but
    order, so taking the order from the config would make the two variants identical while still
    printing two rows.
    """
    wanted = CASCADES[variant]
    config = HEIGHTS.model_copy(deep=True)
    by_name = {tier.name: tier for tier in config.areal_tiers}
    ordered = []
    for name in wanted:
        tier = by_name[name]
        tier.enabled = True
        tier.confidence = AREAL_CONFIDENCE[name]
        ordered.append(tier)
    for tier in config.areal_tiers:
        if tier.name not in wanted:
            tier.enabled = False
            ordered.append(tier)
    config.areal_tiers = ordered
    return resolve_areal_tiers(settings, bbox, config)


UNIT_COLUMN = "_unit"
"""Name given to the joined unit id.

`gpd.sjoin` names the right frame's index column after that index — `unit_id` here, not the
`index_right` the documentation's examples show, because the units are indexed by `unit_id`.
Renaming it explicitly is what stops that detail from being rediscovered.
"""


def _join_to_units(buildings: gpd.GeoDataFrame, grid: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Each building tagged with the unit it falls in, under a name this module controls."""
    units = grid[["geometry"]].reset_index().rename(columns={grid.index.name: UNIT_COLUMN})
    return gpd.sjoin(buildings, units, how="inner", predicate="intersects")


def dispersion_by_source(buildings: gpd.GeoDataFrame, grid: gpd.GeoDataFrame) -> dict[str, Any]:
    """Within-unit spread of building heights, grouped by which tier supplied them.

    **The direct test of P1.** A product that resolves height bands inside a 100 m cell leaves
    variation there; one that hands every building in the cell the same neighbourhood mean leaves
    none. Reported as the coefficient of variation so tall and short cities are comparable, and
    as the share of units whose heights are literally constant, which is the sharper statement.
    """
    joined = _join_to_units(buildings[["height", "height_source", "geometry"]], grid)
    joined = joined[joined["height"].notna()]
    out: dict[str, Any] = {}
    for source, part in joined.groupby("height_source"):
        grouped = part.groupby(UNIT_COLUMN)["height"]
        stats = grouped.agg(["count", "mean", "std"])
        stats = stats[stats["count"] >= MIN_BUILDINGS_PER_UNIT]
        if stats.empty:
            continue
        cv = (stats["std"] / stats["mean"].where(stats["mean"] > 0)).replace(
            [np.inf, -np.inf], np.nan
        )
        out[str(source)] = {
            "n_units": int(len(stats)),
            "n_buildings": int(stats["count"].sum()),
            "median_cv": _finite(cv.median()),
            "mean_cv": _finite(cv.mean()),
            "median_std_m": _finite(stats["std"].median()),
            "share_of_units_constant": float((stats["std"].fillna(0.0) < 1e-6).mean()),
        }
    return out


def held_out_fidelity(
    buildings: gpd.GeoDataFrame, grid: gpd.GeoDataFrame, products: dict[str, Path]
) -> dict[str, Any]:
    """Score each areal product against the tier-1 heights it would have replaced.

    The strongest available form of P1: the buildings *do* have real heights, so masking them and
    asking each product what it would have said is a like-for-like comparison rather than an
    inference from agreement. `within_unit_spearman` is the number that matters — a product can
    have a fine city-wide correlation purely by getting the average neighbourhood right, and
    still rank every building inside a cell identically, which is exactly the failure P1 predicts
    for GHS-BUILT-H.
    """
    truth = buildings[buildings["height_source"].isin(TIER1) & buildings["height"].notna()]
    if truth.empty:
        return {"n_buildings": 0}

    cells = _join_to_units(truth[["height", "geometry"]], grid)
    cells = cells[~cells.index.duplicated(keep="first")]
    actual = cells["height"].to_numpy()

    out: dict[str, Any] = {"n_buildings": int(len(cells)), "products": {}}
    for name, path in products.items():
        scale, nodata = AREAL_READ[name]
        predicted = zonal_mean(path, cells.geometry, nodata=nodata) * scale
        usable = np.isfinite(predicted) & (predicted > 0)
        if usable.sum() < MIN_BUILDINGS_PER_UNIT:
            out["products"][name] = {"n": int(usable.sum())}
            continue
        error = predicted[usable] - actual[usable]
        frame = pd.DataFrame(
            {
                "unit": cells[UNIT_COLUMN].to_numpy()[usable],
                "actual": actual[usable],
                "predicted": predicted[usable],
            }
        )
        out["products"][name] = {
            "n": int(usable.sum()),
            "coverage": float(usable.mean()),
            "mae_m": float(np.abs(error).mean()),
            "bias_m": float(error.mean()),
            "overall_spearman": _finite(spearmanr(frame["actual"], frame["predicted"]).statistic),
            "within_unit_spearman": _within_unit_spearman(frame),
        }
    return out


def implausible_share(buildings: gpd.GeoDataFrame) -> dict[str, Any]:
    """Share of each tier's heights below one storey — the diagnostic behind `min_height_m = 0.0`.

    Every areal tier is configured with a zero floor, which is each product's own "no built
    volume" sentinel and the only value not invented. The risk that carries is a product handing
    a real building a fraction of a metre, which then drags the geometric-mean `Hr` down without
    anything looking wrong. Measured over Cairo's 580 000 footprints before the sweep: 0.0% for
    GHS-BUILT-H, 0.1% for WSF-3D, **20.0% for Open Buildings 2.5D**.

    Reported rather than thresholded. Choosing a floor here would be picking a number no
    documentation supports, on the axis this phase exists to measure.
    """
    out: dict[str, Any] = {}
    for source, part in buildings.groupby("height_source"):
        heights = pd.to_numeric(part["height"], errors="coerce").dropna()
        if heights.empty:
            continue
        out[str(source)] = {
            "n": int(len(heights)),
            "share_below_2m": float((heights < 2.0).mean()),
            "share_below_3m": float((heights < 3.0).mean()),
            "median_m": float(heights.median()),
        }
    return out


def _within_unit_spearman(frame: pd.DataFrame) -> float | None:
    """Mean per-unit rank correlation, over units with enough buildings to have a rank at all."""
    values = []
    for _, part in frame.groupby("unit"):
        if len(part) < MIN_BUILDINGS_PER_UNIT or part["predicted"].nunique() < 2:
            # A unit where every prediction is identical carries no rank information. Counting it
            # as zero would be the honest reading, and is what `share_constant` reports; leaving
            # it out here keeps this statistic about the units the product *could* have ranked.
            continue
        rho = spearmanr(part["actual"], part["predicted"]).statistic
        if np.isfinite(rho):
            values.append(float(rho))
    return float(np.mean(values)) if values else None


def unit_size_against_the_grid(
    enclosures: gpd.GeoDataFrame, cell_m: float = 100.0
) -> dict[str, Any]:
    """How enclosure size compares with one GHS-BUILT-H cell — the measurable half of P2.

    A 100 m product aligns with the 100 m grid by construction and is coarser than an enclosure
    that fits inside a single cell: every building in such an enclosure gets the same height, and
    the unit gains no internal structure from the product at all.
    """
    area = enclosures.geometry.area
    cell_area = cell_m * cell_m
    return {
        "n_units": int(len(area)),
        "cell_area_m2": cell_area,
        "median_area_m2": float(area.median()),
        "share_below_one_cell": float((area < cell_area).mean()),
        "area_weighted_share_below_one_cell": float(
            area[area < cell_area].sum() / area.sum() if area.sum() else 0.0
        ),
    }


def _finite(value: Any) -> float | None:
    number = float(value)
    return number if np.isfinite(number) else None


PHASE_10_VARIANTS = ("none", "coarse", "full")
"""What Phase 10 ran, kept as the default so this module still reproduces its own record."""


def run_city(
    key: str,
    settings: Settings,
    variants: Sequence[str] = PHASE_10_VARIANTS,
    diagnostics_on: str | None = "full",
    prepared: tuple[Fixture, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """One city, cleaned once, scored under each of `variants`.

    `diagnostics_on` names the variant whose filled heights the P1 mechanism tests run against —
    they are statements about a *product*, so they need the cascade that fires every tier. Pass
    `None` where no such cascade runs; the enclosure-size measurement is unconditional, because
    it is one pass over an area array and it speaks to the A/B question rather than to heights.

    `prepared` skips the `prepare()` this would otherwise do, for a caller that already needed
    the window — Phase 11 resolves each city's variant list from whether Open Buildings covers
    its bbox, and clipping three rasters twice to answer that would be work for nothing.
    """
    prepared = prepared or prepare(BY_KEY[key], settings)
    if prepared is None:
        return None
    fixture, window = prepared

    print(f"\n=== {key} ({window['region']}) {window['bbox']}", file=sys.stderr, flush=True)
    started = time.time()
    ready = clean_for_arms(fixture, settings.cleaning, settings.tile_cache_dir)
    print(f"  cleaned in {time.time() - started:.0f}s", file=sys.stderr, flush=True)

    record: dict[str, Any] = {"fixture": key, "window": window, "cascades": {}}
    grid = GridUnits().generate(fixture.bbox)
    products: dict[str, Path] = {}

    for variant in variants:
        mark = time.time()
        config, placed = cascade_for(settings, fixture.bbox, variant)
        products.update({name: Path(path) for name, path in placed.items() if path is not None})
        tiers = build_cascade(config, settings.source_dir)
        arms, cleaned, provenance, completeness = build_arms(fixture, tiers=tiers, prepared=ready)
        results = evaluate(fixture, arms, provenance, cleaned.buildings_area, completeness)
        results["window"] = window
        results["height_products"] = placed
        results["cascade_sources"] = cascade_height_sources(tiers)
        results["elapsed_s"] = round(time.time() - mark, 1)
        record["cascades"][variant] = results
        print(
            f"  {variant:7s} {time.time() - mark:5.0f}s  "
            f"A {results['arms']['A']['agreement_ground_truth']['overall_agreement']:.1%} "
            f"built {results['arms']['A']['agreement_ground_truth']['built_agreement']:.1%}",
            file=sys.stderr,
            flush=True,
        )
        enclosures = next(arm.units for arm in arms if arm.name == "B")
        diagnostics = [("unit_size", partial(unit_size_against_the_grid, enclosures))]
        if variant == diagnostics_on:
            # `build_arms` returns the cleaned vectors, not the height-filled buildings, so the
            # mechanism tests refill here. It is a second pass over the same tiers rather than a
            # change to `build_arms`, whose signature four other scripts depend on.
            filled, _ = fill_heights(ready.cleaned.buildings_area, tiers)
            diagnostics += [
                ("dispersion", partial(dispersion_by_source, filled, grid)),
                ("held_out", partial(held_out_fidelity, filled, grid, products)),
                ("implausible", partial(implausible_share, filled)),
            ]
        # Isolated from the cascades deliberately. These are diagnostics computed *after* the
        # cascade has already succeeded, and the first version of this block threw a `KeyError`
        # that sent a fully-measured Cairo — three cascades, 18 minutes — into the skipped list
        # with nothing kept. A diagnostic must not be able to discard evidence.
        for name, compute in diagnostics:
            try:
                record[name] = compute()
            except Exception as error:  # noqa: BLE001 - a diagnostic must not lose a city
                record[name] = {"error": f"{type(error).__name__}: {error}"}
                print(f"  {name}: FAILED — {error}", file=sys.stderr, flush=True)

    record["elapsed_s"] = round(time.time() - started, 1)
    return record


def built_agreement(city: dict[str, Any], variant: str, arm: str) -> float | None:
    report = city["cascades"][variant]["arms"][arm]["agreement_ground_truth"]
    return None if report is None else float(report["built_agreement"])


def overall_agreement(city: dict[str, Any], variant: str, arm: str) -> float | None:
    report = city["cascades"][variant]["arms"][arm]["agreement_ground_truth"]
    return None if report is None else float(report["overall_agreement"])


def _tier1_share(city: dict[str, Any], variant: str) -> float:
    tiers = city["cascades"][variant]["cleaning"]["height_tier_fractions"]
    return sum(float(tiers.get(name) or 0.0) for name in TIER1)


def resolved_share(city: dict[str, Any], variant: str) -> float:
    tiers = city["cascades"][variant]["cleaning"]["height_tier_fractions"]
    return 1.0 - float(tiers.get(UNRESOLVED) or 0.0)


def summarise(record: dict[str, Any]) -> None:
    """Print the before/after tables and the verdict on each pre-registered prediction."""
    cities = [c for c in record["cities"] if c["cascades"]["none"].get("ground_truth")]
    if not cities:
        print("no city produced a labelled comparison")
        return

    print(f"\n{'=' * 104}\nPHASE 10 — {len(cities)} cities, three cascades against one cleaning")

    print("\n1. HEIGHT COVERAGE AND BUILT-CLASS AGREEMENT, before and after")
    print(
        f"\n{'city':16}{'resolved: none':>15}{'coarse':>9}{'full':>8}"
        f"{'  |  built: none':>17}{'coarse':>9}{'full':>8}{'delta':>8}"
    )
    coverage_gain: list[float] = []
    built_gain: list[float] = []
    overall_gain: list[float] = []
    for city in cities:
        built = {v: built_agreement(city, v, "A") for v in PHASE_10_VARIANTS}
        delta = (built["full"] or 0.0) - (built["none"] or 0.0)
        coverage_gain.append(resolved_share(city, "full") - resolved_share(city, "none"))
        built_gain.append(delta)
        overall_gain.append(
            (overall_agreement(city, "full", "A") or 0.0)
            - (overall_agreement(city, "none", "A") or 0.0)
        )
        print(
            f"{city['fixture']:16}"
            f"{resolved_share(city, 'none'):>15.1%}{resolved_share(city, 'coarse'):>9.1%}"
            f"{resolved_share(city, 'full'):>8.1%}   |  "
            f"{built['none']:>12.1%}{built['coarse']:>9.1%}{built['full']:>8.1%}"
            f"{100 * delta:>+8.1f}"
        )
    print(
        f"\n   mean built-class change {100 * float(np.mean(built_gain)):+.1f} pts, "
        f"overall {100 * float(np.mean(overall_gain)):+.1f} pts; "
        f"improved in {sum(1 for d in built_gain if d > 0)} of {len(built_gain)} cities"
    )
    if len(cities) > 2:
        # The acceptance criterion: agreement change against tier-coverage change, per city. If
        # filling Hr is what matters, the cities that gained the most coverage gained the most
        # agreement — and if it is not, this is the number that says so.
        print(
            f"   corr(coverage gain, built-class gain) = "
            f"{float(np.corrcoef(coverage_gain, built_gain)[0, 1]):+.2f}"
        )

    print("\n2. P1 — WITHIN-UNIT DISPERSION by the tier that supplied the height")
    print(f"\n{'source':22}{'units':>8}{'median CV':>11}{'median std (m)':>16}{'constant':>10}")
    pooled: dict[str, list[float]] = {}
    for city in cities:
        for source, stats in city.get("dispersion", {}).items():
            if stats.get("median_cv") is not None:
                pooled.setdefault(source, []).append(stats["median_cv"])
            print(
                f"{source[:20]:22}{stats['n_units']:>8}"
                f"{(stats['median_cv'] if stats['median_cv'] is not None else float('nan')):>11.3f}"
                f"{(stats['median_std_m'] or 0.0):>16.2f}"
                f"{stats['share_of_units_constant']:>10.1%}   ({city['fixture']})"
            )
    print("\n   pooled median CV by source:")
    for source, values in sorted(pooled.items(), key=lambda item: -float(np.median(item[1]))):
        print(f"     {source:20} {float(np.median(values)):.3f}  (n={len(values)} cities)")

    print("\n3. P1 — HELD-OUT FIDELITY against the tier-1 heights each product would replace")
    print(
        f"\n{'city':16}{'product':10}{'n':>8}{'MAE (m)':>9}{'bias':>8}"
        f"{'overall rho':>13}{'within-unit rho':>17}"
    )
    for city in cities:
        held = city.get("held_out", {})
        for name, stats in held.get("products", {}).items():
            if "mae_m" not in stats:
                continue
            within = stats["within_unit_spearman"]
            print(
                f"{city['fixture']:16}{name:10}{stats['n']:>8}{stats['mae_m']:>9.2f}"
                f"{stats['bias_m']:>8.2f}{stats['overall_spearman']:>13.3f}"
                f"{(f'{within:.3f}' if within is not None else '—'):>17}"
            )

    print("\n4. P2 — ENCLOSURE SIZE against one 100 m GHS-BUILT-H cell")
    print(f"\n{'city':16}{'median area m2':>16}{'share < 1 cell':>16}{'by area':>10}")
    for city in cities:
        size = city.get("unit_size")
        if not size:
            continue
        print(
            f"{city['fixture']:16}{size['median_area_m2']:>16.0f}"
            f"{size['share_below_one_cell']:>16.1%}"
            f"{size['area_weighted_share_below_one_cell']:>10.1%}"
        )

    print("\n5. P2 — A vs B, built classes, before and after the cascade")
    print(f"\n{'city':16}{'B-A none':>10}{'B-A coarse':>12}{'B-A full':>10}")
    gaps: dict[str, list[float]] = {v: [] for v in PHASE_10_VARIANTS}
    for city in cities:
        row = {}
        for variant in PHASE_10_VARIANTS:
            a, b = built_agreement(city, variant, "A"), built_agreement(city, variant, "B")
            row[variant] = 100 * ((b or 0.0) - (a or 0.0))
            gaps[variant].append(row[variant])
        print(
            f"{city['fixture']:16}{row['none']:>+10.1f}{row['coarse']:>+12.1f}{row['full']:>+10.1f}"
        )
    print(
        "   mean B-A: "
        + "  ".join(f"{v} {float(np.mean(values)):+.1f}" for v, values in gaps.items())
    )

    print("\n6. VERDICTS — against the predictions recorded before the sweep")
    for name, prediction in record["predictions"].items():
        print(f"\n   {name}: {prediction['claim']}")
        for line in prediction["expected"]:
            print(f"      expected: {line}")
    print("\n   (stated in the write-up; the tables above are the evidence)")


def main() -> None:
    if "--list" in sys.argv:
        for city in CITIES:
            mark = "*" if city.key in SELECTED else " "
            print(f"{mark} {city.key:18s} {city.region:16s} {city.so2sat}")
        return

    if "--report" in sys.argv:
        path = Path(sys.argv[sys.argv.index("--report") + 1])
        summarise(json.loads(path.read_text(encoding="utf-8")))
        return

    requested = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--all" in sys.argv or not requested:
        selected = list(SELECTED)
    else:
        unknown = [key for key in requested if key not in BY_KEY]
        if unknown:
            raise SystemExit(f"unknown city keys {unknown}; try --list")
        selected = requested

    settings = Settings.load()
    settings.overture.release = RELEASE
    settings.cleaning = CLEANING.model_copy()

    started = time.time()
    record: dict[str, Any] = {
        "experiment": "phase-10-height-cascade",
        "run_id": settings.run_id,
        "overture_release": RELEASE,
        "cascades": {name: list(tiers) for name, tiers in CASCADES.items()},
        "predictions": PREDICTIONS,
        "config": {
            "cleaning": settings.cleaning.model_dump(mode="json"),
            "heights": HEIGHTS.model_dump(mode="json"),
            "height_products": settings.height_products.model_dump(mode="json"),
            "ucp": UCP.model_dump(mode="json"),
            "validation": VALIDATION.model_dump(mode="json"),
            "classification": PrototypeClassifier().describe(),
        },
        "cities": [],
        "skipped": [],
    }
    destination = settings.run_dir / "height_tier_experiment.json"

    for key in selected:
        try:
            results = run_city(key, settings)
        except Exception as error:  # noqa: BLE001 - one city must not end the sweep
            print(f"  {key}: FAILED — {type(error).__name__}: {error}", file=sys.stderr)
            record["skipped"].append({"city": key, "error": f"{type(error).__name__}: {error}"})
            results = None
        if results is None:
            record["skipped"].append({"city": key, "reason": "screened or failed"})
        else:
            record["cities"].append(results)
        record["elapsed_s"] = round(time.time() - started, 1)
        destination.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")

    summarise(record)
    print(f"\nwrote {destination}")


if __name__ == "__main__":
    main()
