"""Phase 12: reconcile the two confusion-axis measurements, and name the next accuracy lever.

    uv run --active python scripts/axis_reconciliation.py

CLAUDE.md records the contradiction that opened this phase:

    | Phase 9, 15-city median | height 15.5% | compactness  2.6% |
    | Berlin, vs labels       | height 17.0% | compactness 55.2% |
    | Hong Kong, vs labels    | height 18.1% | compactness 27.6% |

Height is stable at 15-18%; compactness swings by a factor of twenty. The spec offers two
explanations - either the medians were computed differently from the per-city comparisons, or class
composition drives the compactness share so hard that a cross-city median of it is meaningless.

**This script re-analyses the stored run records rather than re-running the cities.** Every run
persists its full sparse confusion matrix, and `axis_summary` is computed from that matrix and
nothing else, so a figure recomputed here is the same computation the run performed. Sixteen cities
cost seconds against Phase 11's 8.9 h, and the equivalence is pinned in CI by
`test_the_axis_summary_reads_the_same_confusion_matrix_a_run_persists`.

Three outputs, in the order they have to be read:

1. **A provenance audit.** Every axis figure against its reference file, cascade, arm, cell count
   and reference-class count. CLAUDE.md's instruction is to verify like-for-like *first*, because a
   prior version of this comparison mixed `lcz_v3` and label references and was caught pre-commit.
   An audit is a table, not an assertion.
2. **The normalised sixteen-city table.** Raw share, axis-eligible share, and lift, for both axes
   and both arms.
3. **The lever recommendation**, with the evidence.

Reads run records from `output/lczkit/`; writes `axis_reconciliation.json` to a fresh run dir.
Nothing under `input/` is touched.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lczkit.classify.labels import COMPACTNESS_AXIS_PAIRS, HEIGHT_AXIS_PAIRS
from lczkit.config import Settings
from lczkit.validation.agreement import AxisSummary, ConfusionCell, axis_summary

#: The records this phase re-analyses, by the run id that produced them. Pinned rather than
#: discovered: "the newest file matching a glob" is how a re-analysis silently changes population
#: between one reading and the next, and the whole point here is that these are the runs whose
#: figures CLAUDE.md quotes.
RECORDS: dict[str, tuple[str, str]] = {
    "phase_9": ("20260810T083158Z", "multi_city_validation.json"),
    "phase_11": ("20260812T184810Z", "unit_decision_experiment.json"),
}

PUBLISHED = {
    "phase_9_median_height": 0.155,
    "phase_9_median_compactness": 0.026,
}
"""What CLAUDE.md quotes for Phase 9. Reproducing these before applying any correction is what
distinguishes "the medians were computed differently" from "the medians were computed correctly and
are not comparable across cities"."""

EXPECTATIONS: dict[str, dict[str, Any]] = {
    "E1": {
        "claim": (
            "The lever flips to unit definition / footprint coverage. At `coarse` - what lczkit "
            "has shipped since Phase 10 - normalised compactness leads height across the sixteen "
            "cities, and at `none` the ordering reverses, showing the candidate order was set on a "
            "configuration the package no longer ships."
        ),
        "prediction": "median compactness lift > median height lift at coarse; reversed at none",
        "measured_in_planning": {
            "arm_A_coarse_compactness_lift": 1.16,
            "arm_A_coarse_height_lift": 0.86,
        },
        "falsifier": "If compactness does not lead at coarse, height stays the lever.",
    },
    "E2": {
        "claim": (
            "Normalisation makes a cross-city median meaningful: the spread of the compactness "
            "axis across cities falls by at least 2x, and no city exceeds 5x the median."
        ),
        "prediction": "raw spread 15.6x falls below 7.8x; max/median lift below 5",
        "falsifier": (
            "If the spread stays wide, a cross-city median of either axis is not a reportable "
            "quantity and this phase says so rather than publishing one."
        ),
    },
}

REFERENCE_KIND = {
    "agreement": "lcz_v3",
    "agreement_ground_truth": "so2sat_labels",
}

EUROPE_AND_NORTH_AMERICA_CITIES = frozenset(
    {"berlin", "london", "paris", "cologne", "rome", "milan", "vancouver"}
)
"""The seven cities Phase 11's A/B split on, named the same way so the two are comparable.

Not a claim that continent is a mechanism — CLAUDE.md rules that out explicitly for `unit_strategy`
— but the population split is the one already in the record, and reusing it is what makes "the same
seven against the same nine" a checkable statement rather than a resemblance.
"""


@dataclass(frozen=True)
class Axes:
    """One report's two axes, plus the provenance needed to know what it can be compared with."""

    city: str
    source: str
    variant: str
    arm: str
    reference_kind: str
    reference_file: str
    n_compared: int
    n_disagree: int
    n_reference_classes: int
    natural_share: float
    height: AxisSummary
    compactness: AxisSummary

    @property
    def comparable_key(self) -> tuple[str, str, str]:
        """What must match before two rows may be put in the same column of a table."""
        return (self.reference_kind, self.variant, self.arm)


def read_axes(report: dict[str, Any], **provenance: Any) -> Axes | None:
    """Recompute both axes for one stored `AgreementReport` dump."""
    confusion = report.get("confusion")
    if not confusion:
        return None
    cells = [ConfusionCell.model_validate(cell) for cell in confusion]
    return Axes(
        reference_file=str(report.get("reference_file") or "?"),
        n_compared=int(report.get("n_compared", 0)),
        n_disagree=int(report.get("n_disagree", 0)),
        n_reference_classes=len({cell.reference for cell in cells}),
        natural_share=float(report.get("natural_share", 0.0)),
        height=axis_summary(cells, HEIGHT_AXIS_PAIRS, axis="height"),
        compactness=axis_summary(cells, COMPACTNESS_AXIS_PAIRS, axis="compactness"),
        **provenance,
    )


def city_name(report: dict[str, Any], fallback: str) -> str:
    reference = report.get("reference_file")
    if not reference:
        return fallback
    stem = Path(str(reference)).stem
    for prefix in ("so2sat_", "lcz_reference_"):
        stem = stem.removeprefix(prefix)
    return stem


def collect(settings: Settings) -> list[Axes]:
    """Every axis figure in the pinned records, with its provenance attached.

    The two record shapes nest differently - Phase 9 puts arms at the city, Phase 11 puts a cascade
    variant in between - so they are walked separately rather than through a generic descent that
    would have to guess which level it was at.
    """
    rows: list[Axes] = []

    run_id, name = RECORDS["phase_9"]
    phase_9 = json.loads((settings.output_dir / "lczkit" / run_id / name).read_text())
    for index, city in enumerate(phase_9["cities"]):
        for arm, payload in city.get("arms", {}).items():
            for key, kind in REFERENCE_KIND.items():
                found = read_axes(
                    payload.get(key) or {},
                    city=city_name(payload.get(key) or {}, f"city_{index}"),
                    source="phase_9",
                    variant="none",
                    arm=arm,
                    reference_kind=kind,
                )
                if found:
                    rows.append(found)

    run_id, name = RECORDS["phase_11"]
    phase_11 = json.loads((settings.output_dir / "lczkit" / run_id / name).read_text())
    for index, city in enumerate(phase_11["cities"]):
        for variant, cascade in city.get("cascades", {}).items():
            for arm, payload in cascade.get("arms", {}).items():
                for key, kind in REFERENCE_KIND.items():
                    found = read_axes(
                        payload.get(key) or {},
                        city=city_name(payload.get(key) or {}, f"city_{index}"),
                        source="phase_11",
                        variant=variant,
                        arm=arm,
                        reference_kind=kind,
                    )
                    if found:
                        rows.append(found)

    return rows


def collect_fixtures(settings: Settings, run_id: str | None) -> list[Axes]:
    """The fixture-scale runs, which are what CLAUDE.md's Berlin and Hong Kong rows come from.

    Optional: the table stands without them, but they are the controlled within-city test of the
    extent confound - the same city, the same reference, the same arm, at 9 km2 and at 30 km.
    """
    if run_id is None:
        return []
    path = settings.output_dir / "lczkit" / run_id / "unit_scale_experiment.json"
    if not path.exists():
        print(f"  (no fixture record at {path}; skipping the fixture comparison)", file=sys.stderr)
        return []
    record = json.loads(path.read_text())
    rows: list[Axes] = []
    for fixture in record.get("fixtures", []):
        for arm, payload in fixture.get("arms", {}).items():
            for key, kind in REFERENCE_KIND.items():
                found = read_axes(
                    payload.get(key) or {},
                    city=city_name(payload.get(key) or {}, str(fixture.get("fixture", "?"))),
                    source="fixture",
                    variant="fixture",
                    arm=arm,
                    reference_kind=kind,
                )
                if found:
                    rows.append(found)
    return rows


def _spread(values: list[float]) -> float:
    """Max over min, the figure E2 is registered against. Infinite where any city reads zero."""
    low = min(values)
    return max(values) / low if low > 0 else float("inf")


def audit(rows: list[Axes]) -> dict[str, Any]:
    """Confirm every published figure is like-for-like before anything is compared."""
    print("\n=== 1. provenance audit ===")
    print("  every axis figure, with what it was measured against\n")
    print(
        f"  {'source':<10}{'variant':<10}{'arm':<5}{'reference':<15}{'city':<16}"
        f"{'cells':>7}{'cls':>5}{'nat':>7}{'height':>8}{'compact':>9}"
    )
    for row in sorted(rows, key=lambda r: (r.source, r.variant, r.arm, r.city)):
        print(
            f"  {row.source:<10}{row.variant:<10}{row.arm:<5}{row.reference_kind:<15}"
            f"{row.city:<16}{row.n_compared:>7}{row.n_reference_classes:>5}"
            f"{row.natural_share:>7.1%}{row.height.share_of_disagreement:>8.1%}"
            f"{row.compactness.share_of_disagreement:>9.1%}"
        )

    kinds = sorted({row.reference_kind for row in rows})
    variants = sorted({row.variant for row in rows})
    print(f"\n  reference kinds present: {kinds}")
    print(f"  cascade variants present: {variants}")
    print(
        "  A figure may only be compared with another sharing (reference_kind, variant, arm). "
        "The published table compared across all three."
    )
    return {"reference_kinds": kinds, "variants": variants, "n_rows": len(rows)}


def reproduce_published(rows: list[Axes]) -> dict[str, Any]:
    """Reproduce Phase 9's medians before correcting anything.

    If they do not reproduce, the audit is measuring something other than what was published and
    every conclusion below is void - so this runs before the normalisation, not after.
    """
    print("\n=== 2. do the published medians reproduce? ===")
    selected = [
        r
        for r in rows
        if r.source == "phase_9" and r.arm == "A" and r.reference_kind == "so2sat_labels"
    ]
    heights = [r.height.share_of_disagreement for r in selected]
    compacts = [r.compactness.share_of_disagreement for r in selected]
    got = (statistics.median(heights), statistics.median(compacts))
    want = (PUBLISHED["phase_9_median_height"], PUBLISHED["phase_9_median_compactness"])
    ok = all(abs(g - w) < 0.001 for g, w in zip(got, want, strict=True))
    print(f"  Phase 9, {len(selected)} cities, arm A, So2Sat labels, cascade none")
    print(f"    height      published {want[0]:.1%}   recomputed {got[0]:.1%}")
    print(f"    compactness published {want[1]:.1%}   recomputed {got[1]:.1%}")
    print(f"  -> {'REPRODUCES' if ok else 'DOES NOT REPRODUCE - everything below is void'}")
    return {
        "reproduces": ok,
        "n_cities": len(selected),
        "published": {"height": want[0], "compactness": want[1]},
        "recomputed": {"height": got[0], "compactness": got[1]},
    }


def confounds(rows: list[Axes]) -> dict[str, Any]:
    """Isolate each confound with a comparison that varies it and holds the rest fixed."""
    print("\n=== 3. what the swing actually is ===")
    result: dict[str, Any] = {}

    print("\n  (a) cascade variant - same cities, same reference, same arm, heights filled or not")
    for variant in ("none", "coarse"):
        selected = [
            r
            for r in rows
            if r.source == "phase_11"
            and r.arm == "A"
            and r.reference_kind == "so2sat_labels"
            and r.variant == variant
        ]
        if not selected:
            continue
        h = statistics.median([r.height.share_of_disagreement for r in selected])
        c = statistics.median([r.compactness.share_of_disagreement for r in selected])
        print(f"    {variant:<8} n={len(selected):<3} height {h:>6.1%}   compactness {c:>6.1%}")
        result[f"median_{variant}"] = {"height": h, "compactness": c, "n": len(selected)}

    print(
        "\n  (b) denominator population - all disagreement, or only references that reach an axis"
    )
    selected = [
        r
        for r in rows
        if r.source == "phase_11"
        and r.arm == "A"
        and r.reference_kind == "so2sat_labels"
        and r.variant == "coarse"
    ]
    if selected:
        raw_h = statistics.median([r.height.share_of_disagreement for r in selected])
        raw_c = statistics.median([r.compactness.share_of_disagreement for r in selected])
        eli_h = statistics.median([r.height.share_of_axis_eligible for r in selected])
        eli_c = statistics.median([r.compactness.share_of_axis_eligible for r in selected])
        nat = statistics.median([r.natural_share for r in selected])
        print(f"    all disagreement      height {raw_h:>6.1%}   compactness {raw_c:>6.1%}")
        print(f"    reference in LCZ 1-6  height {eli_h:>6.1%}   compactness {eli_c:>6.1%}")
        print(f"    (median natural share of compared area: {nat:.1%})")
        result["denominator"] = {
            "raw": {"height": raw_h, "compactness": raw_c},
            "axis_eligible": {"height": eli_h, "compactness": eli_c},
            "median_natural_share": nat,
        }

    print("\n  (c) what the reference composition affords each axis before any error is measured")
    for variant in ("none", "coarse"):
        selected = [
            r
            for r in rows
            if r.source == "phase_11"
            and r.arm == "A"
            and r.reference_kind == "so2sat_labels"
            and r.variant == variant
        ]
        if not selected:
            continue
        exp_h = statistics.median([r.height.expected_share for r in selected])
        exp_c = statistics.median([r.compactness.expected_share for r in selected])
        obs_h = statistics.median([r.height.share_of_disagreement for r in selected])
        obs_c = statistics.median([r.compactness.share_of_disagreement for r in selected])
        print(
            f"    {variant:<8} expected  height {exp_h:>6.1%}  compactness {exp_c:>6.1%}   "
            f"ratio {exp_h / exp_c if exp_c else float('inf'):>5.1f}x"
        )
        print(
            f"    {'':<8} observed  height {obs_h:>6.1%}  compactness {obs_c:>6.1%}   "
            f"ratio {obs_h / obs_c if obs_c else float('inf'):>5.1f}x"
        )
        result.setdefault("affordance", {})[variant] = {
            "expected": {"height": exp_h, "compactness": exp_c},
            "observed": {"height": obs_h, "compactness": obs_c},
        }
    print(
        "    The height axis has six pairs to compactness's three and more reachable directions,\n"
        "    so a null that never looks at an axis still hands it most of the disagreement."
    )

    print("\n  (d) extent and class composition - one city, two extents, everything else fixed")
    for city in ("berlin", "hong_kong"):
        pair = [
            r
            for r in rows
            if r.city.replace("_", "") == city.replace("_", "")
            and r.arm == "A"
            and r.reference_kind == "so2sat_labels"
        ]
        for row in sorted(pair, key=lambda r: r.n_compared):
            print(
                f"    {row.city:<10} {row.source:<9} {row.variant:<8} "
                f"{row.n_compared:>6} cells, {row.n_reference_classes:>2} classes   "
                f"height {row.height.share_of_disagreement:>6.1%}   "
                f"compactness {row.compactness.share_of_disagreement:>6.1%}"
            )
        if pair:
            result.setdefault("extent", {})[city] = [
                {
                    "source": r.source,
                    "variant": r.variant,
                    "n_compared": r.n_compared,
                    "n_reference_classes": r.n_reference_classes,
                    "height": r.height.share_of_disagreement,
                    "compactness": r.compactness.share_of_disagreement,
                }
                for r in sorted(pair, key=lambda r: r.n_compared)
            ]
    return result


def normalised_table(rows: list[Axes], variant: str, arm: str) -> dict[str, Any]:
    """The deliverable: both axes, normalised, across every city in one population."""
    selected = sorted(
        [
            r
            for r in rows
            if r.source == "phase_11"
            and r.variant == variant
            and r.arm == arm
            and r.reference_kind == "so2sat_labels"
        ],
        key=lambda r: r.city,
    )
    if not selected:
        return {}

    print(f"\n  cascade={variant}  arm={arm}  reference=So2Sat labels  n={len(selected)}")
    print(
        f"    {'city':<16}{'cls':>4}{'nat':>7}"
        f"{'h raw':>8}{'h elig':>8}{'h lift':>8}"
        f"{'c raw':>8}{'c elig':>8}{'c lift':>8}   lever"
    )
    for row in selected:
        lever = "compactness" if row.compactness.lift > row.height.lift else "height"
        print(
            f"    {row.city:<16}{row.n_reference_classes:>4}{row.natural_share:>7.1%}"
            f"{row.height.share_of_disagreement:>8.1%}{row.height.share_of_axis_eligible:>8.1%}"
            f"{row.height.lift:>8.2f}"
            f"{row.compactness.share_of_disagreement:>8.1%}"
            f"{row.compactness.share_of_axis_eligible:>8.1%}{row.compactness.lift:>8.2f}"
            f"   {lever}"
        )

    h_raw = [r.height.share_of_disagreement for r in selected]
    c_raw = [r.compactness.share_of_disagreement for r in selected]
    h_lift = [r.height.lift for r in selected]
    c_lift = [r.compactness.lift for r in selected]
    compactness_leads = sum(1 for r in selected if r.compactness.lift > r.height.lift)

    print(
        f"    {'MEDIAN':<16}{'':>4}{'':>7}"
        f"{statistics.median(h_raw):>8.1%}{'':>8}{statistics.median(h_lift):>8.2f}"
        f"{statistics.median(c_raw):>8.1%}{'':>8}{statistics.median(c_lift):>8.2f}"
        f"   compactness leads in {compactness_leads}/{len(selected)}"
    )

    # The same seven-against-nine split Phase 11 found on A vs B, reported here because a lever
    # that concentrates in one half of the population is a different recommendation from one that
    # applies everywhere - and because "which cities lead on which axis" reads as a coverage story
    # until the medians are put side by side and it turns out not to be one.
    regional: dict[str, Any] = {}
    for label, inside in (("Europe + N. America", True), ("everywhere else", False)):
        group = [r for r in selected if (r.city in EUROPE_AND_NORTH_AMERICA_CITIES) is inside]
        if not group:
            continue
        entry = {
            "n": len(group),
            "height_lift": statistics.median([r.height.lift for r in group]),
            "compactness_lift": statistics.median([r.compactness.lift for r in group]),
        }
        regional[label] = entry
        print(
            f"    {label:<22} n={entry['n']:<3} median height lift {entry['height_lift']:>5.2f}   "
            f"compactness lift {entry['compactness_lift']:>5.2f}"
        )

    return {
        "regional": regional,
        "variant": variant,
        "arm": arm,
        "n_cities": len(selected),
        "median": {
            "height_raw": statistics.median(h_raw),
            "compactness_raw": statistics.median(c_raw),
            "height_lift": statistics.median(h_lift),
            "compactness_lift": statistics.median(c_lift),
        },
        "spread": {
            "height_raw": _spread(h_raw),
            "compactness_raw": _spread(c_raw),
            "height_lift": _spread(h_lift),
            "compactness_lift": _spread(c_lift),
        },
        "max_over_median_lift": {
            "height": max(h_lift) / statistics.median(h_lift)
            if statistics.median(h_lift)
            else float("inf"),
            "compactness": max(c_lift) / statistics.median(c_lift)
            if statistics.median(c_lift)
            else float("inf"),
        },
        "compactness_leads": compactness_leads,
        "cities": [
            {
                "city": r.city,
                "n_reference_classes": r.n_reference_classes,
                "natural_share": r.natural_share,
                "height": r.height.model_dump(),
                "compactness": r.compactness.model_dump(),
            }
            for r in selected
        ],
    }


def verdicts(tables: dict[str, Any]) -> dict[str, Any]:
    """E1 and E2 against what was measured, reported confirmed / refuted / partial."""
    print("\n=== 5. pre-registered expectations ===")
    out: dict[str, Any] = {}

    coarse_a = tables.get("coarse_A", {})
    none_a = tables.get("none_A", {})
    coarse_b = tables.get("coarse_B", {})
    e1: dict[str, Any] = {"expectation": EXPECTATIONS["E1"]}
    if coarse_a and none_a:
        leads_at_coarse = coarse_a["median"]["compactness_lift"] > coarse_a["median"]["height_lift"]
        reverses_at_none = none_a["median"]["height_lift"] > none_a["median"]["compactness_lift"]
        leads_on_b = (
            bool(coarse_b)
            and coarse_b["median"]["compactness_lift"] > coarse_b["median"]["height_lift"]
        )
        e1["verdict"] = (
            "confirmed"
            if leads_at_coarse and reverses_at_none
            else "partial"
            if leads_at_coarse or reverses_at_none
            else "refuted"
        )
        e1["measured"] = {
            "coarse_arm_A": coarse_a["median"],
            "none_arm_A": none_a["median"],
            "compactness_leads_at_coarse": leads_at_coarse,
            "ordering_reverses_at_none": reverses_at_none,
            "survives_on_arm_B": leads_on_b,
        }
        print(f"  E1 {e1['verdict'].upper()}")
        print(
            f"     coarse: compactness lift {coarse_a['median']['compactness_lift']:.2f} "
            f"vs height {coarse_a['median']['height_lift']:.2f}  "
            f"(compactness leads in {coarse_a['compactness_leads']}/{coarse_a['n_cities']})"
        )
        print(
            f"     none:   compactness lift {none_a['median']['compactness_lift']:.2f} "
            f"vs height {none_a['median']['height_lift']:.2f}  "
            f"(compactness leads in {none_a['compactness_leads']}/{none_a['n_cities']})"
        )
        if coarse_b:
            print(
                f"     arm B:  compactness lift {coarse_b['median']['compactness_lift']:.2f} "
                f"vs height {coarse_b['median']['height_lift']:.2f}"
            )
    out["E1"] = e1

    e2: dict[str, Any] = {"expectation": EXPECTATIONS["E2"]}
    if coarse_a:
        raw_spread = coarse_a["spread"]["compactness_raw"]
        lift_spread = coarse_a["spread"]["compactness_lift"]
        ratio = raw_spread / lift_spread if lift_spread else float("inf")
        concentrated = coarse_a["max_over_median_lift"]["compactness"] < 5.0
        e2["verdict"] = (
            "confirmed"
            if ratio >= 2.0 and concentrated
            else "partial"
            if ratio >= 2.0
            else "refuted"
        )
        e2["measured"] = {
            "compactness_raw_spread": raw_spread,
            "compactness_lift_spread": lift_spread,
            "spread_reduction": ratio,
            "max_over_median_lift": coarse_a["max_over_median_lift"]["compactness"],
        }
        print(f"  E2 {e2['verdict'].upper()}")
        print(
            f"     compactness spread: raw {raw_spread:.1f}x -> lift {lift_spread:.1f}x "
            f"(reduction {ratio:.1f}x); "
            f"max/median lift {coarse_a['max_over_median_lift']['compactness']:.1f}"
        )
    out["E2"] = e2
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture-run",
        default=None,
        help="run id of a unit_scale_experiment.json to include in the extent comparison",
    )
    args = parser.parse_args()

    settings = Settings.load()
    started = time.time()
    rows = collect(settings) + collect_fixtures(settings, args.fixture_run)

    record: dict[str, Any] = {
        "experiment": "phase-12-axis-reconciliation",
        "run_id": settings.run_id,
        "records": {name: f"{run}/{file}" for name, (run, file) in RECORDS.items()},
        "fixture_run": args.fixture_run,
        "expectations": EXPECTATIONS,
    }
    record["audit"] = audit(rows)
    record["reproduction"] = reproduce_published(rows)
    record["confounds"] = confounds(rows)

    print("\n=== 4. normalised axis table ===")
    tables: dict[str, Any] = {}
    for variant in ("coarse", "none"):
        for arm in ("A", "B"):
            table = normalised_table(rows, variant, arm)
            if table:
                tables[f"{variant}_{arm}"] = table
    record["tables"] = tables
    record["verdicts"] = verdicts(tables)

    record["elapsed_s"] = round(time.time() - started, 1)
    destination = settings.run_dir / "axis_reconciliation.json"
    destination.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nwrote {destination}")


if __name__ == "__main__":
    main()
