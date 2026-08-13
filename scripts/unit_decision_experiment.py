"""Phase 11: which unit the pipeline should compute in, and whether cascade order matters.

    uv run --active python scripts/unit_decision_experiment.py --list
    uv run --active python scripts/unit_decision_experiment.py berlin hong_kong
    uv run --active python scripts/unit_decision_experiment.py --all
    uv run --active python scripts/unit_decision_experiment.py --report <path.json>

Two questions Phase 10 moved and could not close.

**A vs B.** Enclosures have gained twice, both times for a reason rather than by luck: they
approximate an LCZ patch, and a patch-scale `Hr` only means anything once heights exist, so every
A/B measurement before Phase 10 handicapped exactly the unit type designed to exploit them. At
`coarse` the overall deficit that was the sole basis for not adopting them is gone (+1.0 overall,
+4.1 built over nine cities). **But those nine were selected for low tier-1 coverage and
under-represent Europe, which is where enclosures do worst.** Fifteen cities settles it; nine
cannot. This runs all sixteen — the fifteen of Phase 9 plus Hong Kong, which crashed there and
completes since Phase 10 — and reports the fifteen separately so the comparison with Phase 9's
population stays exact.

**Cascade order.** `full` runs Open Buildings 2.5D first, so it claims most of the building area
and the coarse tiers barely fire. `full_reversed` inverts that. It is a confirmation rather than a
hope: `coarse -> full` is already −1.9 points and positive in only 4 of 9.

Same harness as Phases 9 and 10 — same windows, same references, same metrics. `prepare()` derives
each window deterministically from the labelled patches, so every city's extent matches its earlier
runs cell for cell, and `run_city` scores every cascade against **one** cleaning.

**Where it writes.** `output/lczkit/<run_id>/`, plus the height products under `input/GOB25D/`,
`input/WSF3D/` and `input/GHSL/` and Overture's cache under `input/Overture_Maps/`, all of which
are owned by the source implementations that write them. New files only.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from lczkit.classify import PrototypeClassifier
from lczkit.config import Settings
from lczkit.protocols import BBox
from lczkit.sources.height_products import OpenBuildings25dSource

sys.path.insert(0, str(Path(__file__).resolve().parent))

from berlin_metropolitan import CLEANING, RELEASE  # noqa: E402 - sibling script
from height_tier_experiment import (  # noqa: E402 - sibling script
    built_agreement,
    overall_agreement,
    resolved_share,
    run_city,
)
from multi_city_validation import BY_KEY, CITIES, prepare  # noqa: E402 - sibling script
from unit_scale_experiment import HEIGHTS, UCP, VALIDATION  # noqa: E402 - sibling script

BASE_VARIANTS = ("none", "coarse")
"""Run everywhere. `none` is not needed for the decision — Phase 9 already holds it — but it is
what makes "the evidence moved once heights were filled" a **within-run** statement for Europe,
which is the population this whole question turns on."""

GOB_VARIANTS = ("full", "full_reversed")
"""Run only where Open Buildings 2.5D has coverage. Where it does not, `full` is `coarse` with a
different name, and running it would report a duplicate as a comparison."""

PHASE_9_CITIES = tuple(city.key for city in CITIES if city.key != "hong_kong")
"""The fifteen Phase 9 measured. Hong Kong failed there on a GEOS predicate and completes since
Phase 10, so it is a sixteenth city rather than a replacement — reported beside the fifteen, never
folded into them, because a changing denominator is how a population quietly stops being the one
an earlier finding was made on."""

EUROPE_AND_NORTH_AMERICA = ("Europe", "North America")
"""Phase 9's split, kept verbatim. Tier-1 height coverage there is 64.3% against 9.6% elsewhere,
and it is also where enclosures lose, so the two groups are reported apart rather than averaged."""

EXPECTATIONS = {
    "E1": {
        "claim": (
            "A vs B at `coarse` over all fifteen cities. B keeps its built-class lead; the "
            "overall figure sits below Phase 10's +1.0 because the seven cities Phase 10 did not "
            "run are six European/North American plus Hong Kong, and Europe is where enclosures "
            "lose."
        ),
        "expected": [
            "built-class B - A positive, in the +2 to +4 point range, B ahead in more than half",
            "overall B - A below +1.0, plausibly at or below zero",
        ],
        "decision_rule": (
            "Adopt enclosures as the computation unit only if B leads on BOTH overall and "
            "built-class agreement over the fifteen. A built-class lead alone is a split verdict "
            "for the third time, and is reported as one."
        ),
        "baselines": {
            "phase_9_none_15_cities": {"overall": -1.5, "built": +2.4},
            "phase_10_coarse_9_cities": {"overall": +1.0, "built": +4.1},
        },
        "source": "CLAUDE.md Phase 11, item 1",
    },
    "E2": {
        "claim": (
            "Reversing the cascade order lands between `coarse` and `full`: better than `full`, "
            "no better than `coarse`. Letting the coarse tiers claim first leaves Open Buildings "
            "only what they could not answer, so its over-wide within-unit spread — CV 0.441 "
            "against reality's 0.195 — enters fewer units."
        ),
        "expected": [
            "built-class agreement: coarse >= full_reversed > full",
            "full_reversed resolves a smaller share of building area from gob25d than full does",
        ],
        "note": (
            "If full_reversed beats coarse, the dispersion mechanism Phase 10 proposed is wrong "
            "and that is the finding."
        ),
        "source": "CLAUDE.md Phase 11, item 2",
    },
}


def variants_for(settings: Settings, bbox: BBox) -> tuple[str, ...]:
    """The cascades worth running over `bbox`.

    Coverage is asked of the product rather than inferred from the continent. Open Buildings
    answers with one `collection.size()` call and no download where it has nothing, and a
    hardcoded region list would be a guess about a product's extent that nothing would ever
    check.
    """
    if OpenBuildings25dSource(settings).ensure(bbox) is None:
        return BASE_VARIANTS
    return BASE_VARIANTS + GOB_VARIANTS


def _gob_share(city: dict[str, Any], variant: str) -> float | None:
    """Share of building area this variant resolved from Open Buildings, or `None` if it never
    ran here."""
    cascade = city["cascades"].get(variant)
    if cascade is None:
        return None
    return float(cascade["cleaning"]["height_tier_fractions"].get("gob25d") or 0.0)


def _rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per city that produced a labelled comparison, with both arms at both cascades."""
    rows = []
    for city in record["cities"]:
        if not city["cascades"]["none"].get("ground_truth"):
            continue
        row: dict[str, Any] = {
            "city": city["fixture"],
            "region": city["window"]["region"],
            "n": city["cascades"]["coarse"]["arms"]["A"]["agreement_ground_truth"]["n_compared"],
            "ceiling": city["cascades"]["coarse"]["reference_ceiling"]["overall_agreement"],
            "variants": sorted(city["cascades"]),
            "unit_size": city.get("unit_size"),
        }
        for variant in ("none", "coarse", "full", "full_reversed"):
            if variant not in city["cascades"]:
                continue
            for arm in ("A", "B"):
                row[f"{variant}_{arm}_overall"] = overall_agreement(city, variant, arm)
                row[f"{variant}_{arm}_built"] = built_agreement(city, variant, arm)
            row[f"{variant}_gob"] = _gob_share(city, variant)
            row[f"{variant}_resolved"] = resolved_share(city, variant)
        rows.append(row)
    return rows


def _gap(row: dict[str, Any], variant: str, metric: str) -> float | None:
    """B minus A in points, or `None` where the variant did not run for this city."""
    a, b = row.get(f"{variant}_A_{metric}"), row.get(f"{variant}_B_{metric}")
    return None if a is None or b is None else 100 * (b - a)


def _summarise_gaps(rows: list[dict[str, Any]], variant: str) -> dict[str, Any]:
    """Mean B − A and win count for both metrics, over whichever rows ran `variant`."""
    out: dict[str, Any] = {"n_cities": 0}
    for metric in ("overall", "built"):
        values = [g for row in rows if (g := _gap(row, variant, metric)) is not None]
        out["n_cities"] = len(values)
        out[metric] = {
            "mean": float(np.mean(values)) if values else None,
            "median": float(np.median(values)) if values else None,
            "b_ahead": sum(1 for value in values if value > 0),
            "n": len(values),
        }
    return out


def summarise(record: dict[str, Any]) -> None:
    """Print the A/B tables, the reversed-order table, and the verdict on each expectation."""
    rows = _rows(record)
    if not rows:
        print("no city produced a labelled comparison")
        return
    fifteen = [row for row in rows if row["city"] in PHASE_9_CITIES]

    print(f"\n{'=' * 108}\nPHASE 11 — {len(rows)} cities ({len(fifteen)} of Phase 9), one cleaning")

    print("\n1. A vs B AT `coarse` — the decision")
    print(
        f"\n{'city':16}{'region':16}{'cells':>7}{'ceil':>7}"
        f"{'A':>8}{'B':>8}{'B-A':>7}   |{'A built':>9}{'B built':>9}{'B-A':>7}"
    )
    for row in sorted(rows, key=lambda r: r["region"]):
        print(
            f"{row['city']:16}{row['region']:16}{row['n']:>7}{row['ceiling']:>7.1%}"
            f"{row['coarse_A_overall']:>8.1%}{row['coarse_B_overall']:>8.1%}"
            f"{_gap(row, 'coarse', 'overall') or 0.0:>+7.1f}   |"
            f"{row['coarse_A_built']:>9.1%}{row['coarse_B_built']:>9.1%}"
            f"{_gap(row, 'coarse', 'built') or 0.0:>+7.1f}"
        )

    for label, subset in (("fifteen Phase 9 cities", fifteen), ("all cities", rows)):
        gaps = _summarise_gaps(subset, "coarse")
        print(
            f"\n   {label}: overall {gaps['overall']['mean']:+.1f} pts "
            f"(B ahead {gaps['overall']['b_ahead']}/{gaps['overall']['n']})   "
            f"built {gaps['built']['mean']:+.1f} pts "
            f"(B ahead {gaps['built']['b_ahead']}/{gaps['built']['n']})"
        )

    print("\n   by region group, over all cities:")
    for name, subset in (
        ("Europe + N. America", [r for r in rows if r["region"] in EUROPE_AND_NORTH_AMERICA]),
        ("everywhere else", [r for r in rows if r["region"] not in EUROPE_AND_NORTH_AMERICA]),
    ):
        if not subset:
            continue
        gaps = _summarise_gaps(subset, "coarse")
        print(
            f"     {name:22} overall {gaps['overall']['mean']:+6.1f}  "
            f"built {gaps['built']['mean']:+6.1f}  (n={gaps['built']['n']})"
        )

    print("\n2. WHAT FILLING THE HEIGHTS DID TO THE GAP — B - A at `none` against at `coarse`")
    print(
        f"\n{'city':16}{'resolved none':>14}{'coarse':>9}"
        f"{'  |  overall none':>18}{'coarse':>9}{'  |  built none':>16}{'coarse':>9}"
    )
    for row in sorted(rows, key=lambda r: r["region"]):
        print(
            f"{row['city']:16}{row['none_resolved']:>14.1%}{row['coarse_resolved']:>9.1%}   |"
            f"{_gap(row, 'none', 'overall') or 0.0:>+15.1f}"
            f"{_gap(row, 'coarse', 'overall') or 0.0:>+9.1f}   |"
            f"{_gap(row, 'none', 'built') or 0.0:>+12.1f}"
            f"{_gap(row, 'coarse', 'built') or 0.0:>+9.1f}"
        )
    for variant in ("none", "coarse"):
        gaps = _summarise_gaps(rows, variant)
        print(
            f"   {variant:7} mean B-A: overall {gaps['overall']['mean']:+.1f} "
            f"({gaps['overall']['b_ahead']}/{gaps['overall']['n']})   "
            f"built {gaps['built']['mean']:+.1f} ({gaps['built']['b_ahead']}/{gaps['built']['n']})"
        )

    print("\n3. E2 — CASCADE ORDER, on the cities Open Buildings covers")
    ordered = [row for row in rows if row.get("full_A_built") is not None]
    if not ordered:
        print("   no city in this run had Open Buildings coverage")
    else:
        print(
            f"\n{'city':16}{'built: coarse':>14}{'full':>9}{'reversed':>10}"
            f"{'  |  gob share: full':>21}{'reversed':>10}"
        )
        for row in ordered:
            print(
                f"{row['city']:16}{row['coarse_A_built']:>14.1%}{row['full_A_built']:>9.1%}"
                f"{row['full_reversed_A_built']:>10.1%}   |"
                f"{row['full_gob']:>18.1%}{row['full_reversed_gob']:>10.1%}"
            )
        for variant in ("full", "full_reversed"):
            deltas = [100 * (row[f"{variant}_A_built"] - row["coarse_A_built"]) for row in ordered]
            print(
                f"   coarse -> {variant:14} {float(np.mean(deltas)):+.1f} pts, "
                f"positive in {sum(1 for d in deltas if d > 0)} of {len(deltas)}"
            )
        against_full = [
            100 * (row["full_reversed_A_built"] - row["full_A_built"]) for row in ordered
        ]
        print(
            f"   full   -> full_reversed  {float(np.mean(against_full)):+.1f} pts, "
            f"positive in {sum(1 for d in against_full if d > 0)} of {len(against_full)}"
        )

    print("\n4. ENCLOSURE SIZE against one 100 m cell, by region")
    print(f"\n{'city':16}{'region':16}{'median area m2':>16}{'< 1 cell':>10}{'by area':>10}")
    for row in sorted(rows, key=lambda r: r["region"]):
        size = row["unit_size"]
        if not size or "error" in size:
            continue
        print(
            f"{row['city']:16}{row['region']:16}{size['median_area_m2']:>16.0f}"
            f"{size['share_below_one_cell']:>10.1%}"
            f"{size['area_weighted_share_below_one_cell']:>10.1%}"
        )

    print("\n5. THE DECISION RULE, applied to the fifteen")
    gaps = _summarise_gaps(fifteen, "coarse")
    leads_overall = (gaps["overall"]["mean"] or 0.0) > 0
    leads_built = (gaps["built"]["mean"] or 0.0) > 0
    verdict = (
        "ADOPT enclosures" if leads_overall and leads_built else "SPLIT VERDICT — do not adopt"
    )
    print(f"\n   B leads overall: {leads_overall}   B leads built: {leads_built}   -> {verdict}")
    print("\n6. EXPECTATIONS — recorded before the sweep")
    for name, expectation in record["expectations"].items():
        print(f"\n   {name}: {expectation['claim']}")
        for line in expectation["expected"]:
            print(f"      expected: {line}")


def main() -> None:
    if "--list" in sys.argv:
        for city in CITIES:
            mark = " " if city.key in PHASE_9_CITIES else "*"
            print(f"{mark} {city.key:18s} {city.region:16s} {city.so2sat}")
        return

    if "--report" in sys.argv:
        path = Path(sys.argv[sys.argv.index("--report") + 1])
        summarise(json.loads(path.read_text(encoding="utf-8")))
        return

    requested = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--all" in sys.argv or not requested:
        selected = [city.key for city in CITIES]
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
        "experiment": "phase-11-unit-decision",
        "run_id": settings.run_id,
        "overture_release": RELEASE,
        "base_variants": list(BASE_VARIANTS),
        "gob_variants": list(GOB_VARIANTS),
        "phase_9_cities": list(PHASE_9_CITIES),
        "expectations": EXPECTATIONS,
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
    destination = settings.run_dir / "unit_decision_experiment.json"

    for key in selected:
        try:
            prepared = prepare(BY_KEY[key], settings)
            if prepared is None:
                record["skipped"].append({"city": key, "reason": "screened"})
                results = None
            else:
                variants = variants_for(settings, prepared[0].bbox)
                print(f"  {key}: {' '.join(variants)}", file=sys.stderr, flush=True)
                results = run_city(
                    key,
                    settings,
                    variants=variants,
                    diagnostics_on=None,
                    prepared=prepared,
                )
        except Exception as error:  # noqa: BLE001 - one city must not end the sweep
            print(f"  {key}: FAILED — {type(error).__name__}: {error}", file=sys.stderr)
            record["skipped"].append({"city": key, "error": f"{type(error).__name__}: {error}"})
            results = None
        if results is not None:
            record["cities"].append(results)
        # Written after every city, so a sweep interrupted at city eight is eight cities of
        # evidence rather than none.
        record["elapsed_s"] = round(time.time() - started, 1)
        destination.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")

    summarise(record)
    print(f"\nwrote {destination}")


if __name__ == "__main__":
    main()
