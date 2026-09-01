"""Calibrate the LCZ 7 and LCZ 8 semantic rules, or refuse them on measurement.

    uv run --active python scripts/lcz78_threshold_sweep.py --build berlin mumbai ...
    uv run --active python scripts/lcz78_threshold_sweep.py --evidence <dir>
    uv run --active python scripts/lcz78_threshold_sweep.py --report <path.json>

**Why this exists rather than a number in the config.** Both rules shipped disabled with
placeholder thresholds, because the standing ruling is that a threshold is swept against a
reference and chosen at an operating point, never picked. `scripts/lcz10_threshold_sweep.py` is the
template and this follows it deliberately rather than inventing a second methodology: the same
0.05-0.95 grid of nineteen thresholds, precision and recall against a real reference, the whole
curve reported rather than a single number, and an operating point selected by a rule stated in
advance.

**What it concluded, so the record and the config can be checked against each other.** Eight
cities, both references. `large_lowrise` is **enabled at 0.70 with no size gate** — six of 114
settings clear the criteria below, they form a contiguous 0.70-0.95 band, and at the operating
point LCZ 8's precision, recall, F1, built-class and overall agreement all rise in all eight
cities. `lightweight` is **refused at all 95 settings against both references**: Overture's
lightweight vocabulary is outbuildings, so the tagged evidence sits in the three cities carrying no
reference LCZ 7 at all, and the best any setting reached was two correct LCZ 7 labels while
displacing ninety-three the metric had right.

**Two differences from the LCZ 10 sweep, and both change what has to be measured.**

*LCZ 10 is not in the distance metric at all*, so the industrial rule can only add labels a metric
could never have produced. **LCZ 7 and LCZ 8 are both in the prototype set.** A semantic rule
overwrites whatever the distance said, so it can destroy a correct label as easily as it can supply
a missing one - a cell the metric correctly called LCZ 5 becomes a wrong LCZ 8 if it trips the rule.
Per-class precision cannot see that on its own. So every operating point here also reports what the
rule was right about *on the cells it fired on*, against what the displaced label was right about,
and the change in built-class agreement against the same city with the rule off.

*The LCZ 10 sweep had one fixture.* This has to span cities, because Overture's semantic tag
coverage is the thing under test: tagged building area runs 48.6% across Europe and North America
against 13.6% elsewhere, Rio at 3.1%, and both rules read a fraction whose denominator is tagged
building area.

**Pre-registered acceptance.** A rule is enabled only if, at its operating point, all four hold.
They are written as no-loss-anywhere plus a gain somewhere, rather than a gain everywhere, because
a rule that cannot fire in a city cannot improve it and `>` would then fail on equality - the same
vacuous-comparison trap as `all()` over an empty sequence, one criterion along.

1. **No class-precision loss anywhere, and a gain somewhere.** User's accuracy for the target class
   must be at least the every-rule-off baseline in every city, and strictly above it in at least
   one.
2. **The rule is right more often than what it overwrote.** Pooled over every scored cell the rule
   fired on across all cities, `reference == target` must occur more often than
   `reference == the displaced label` - the morphological answer the rule replaced, which
   `apply_semantic_rules` preserves as `lcz_secondary`. This is the sharp instrument: class
   precision pools the rule's own assignments with the metric's, so a rule can look accurate by
   sitting beside an accurate metric, or inaccurate beside an inaccurate one.
3. **Built-class agreement does not fall in any city measured.** Overall agreement is reported
   beside it and is not the criterion, since it is dominated by the natural classes neither rule
   touches.
4. **The rule is not decorative.** In at least one city it must relabel at least
   `MIN_TARGET_SHARE` of that city's reference cells of the target class.

> **Why criterion 4 asks for one city and not all of them.** The committed tag-coverage measurement
> - 48.6% of building area tagged across Europe and North America against 13.6% elsewhere - already
> predicts that a rule reading a tag fraction cannot fire where the tags are absent. Requiring it to
> reach the class in *every* city would make criterion 4 a test of Overture's coverage rather than
> of the rule, and would refuse both rules before any threshold was tried. Asking for one city keeps
> the criterion about the rule; where the rule then cannot fire is reported as the finding it is.

**Operating point, stated before the sweep ran.** Among settings passing all four, the one
relabelling the most scored cells, tie-broken by pooled rule precision. That is the LCZ 10 sweep's
own shape - precision is the constraint and reach is maximised subject to it - with criterion 2
serving as the precision constraint.

Failing any of the four, the rule stays disabled **and the measurement is the result** - which is
what the LCZ 10 sweep found for a different quantity (precision flat over a nineteen-fold change in
threshold, so the threshold governed the rate and not the accuracy).

**Which reference.** So2Sat LCZ42 hand labels decide, per the standing ruling that So2Sat is primary
where it exists. WUDAPT is swept on the same grid and reported beside it - it reaches 2.7x as many
cells - but does not decide. `lcz_v3` is not read at all: the LCZ 10 sweep's exemption is for
Rotterdam, which has no So2Sat coverage, and every city here has some.

**Two stages, because only one of them is expensive.** `--build` runs the pipeline over a city's
30 km So2Sat window and writes one parquet of parameters plus both references - that is 8-35
minutes a city (median 14). The sweep itself classifies each city **once** and then applies the
rule to the result, so a threshold grid can be widened for nothing. `--evidence <dir>` points at a
directory of already-built evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from lczkit.cities import BY_KEY, CITIES
from lczkit.classify import PrototypeClassifier, rules
from lczkit.config import ClassificationConfig, SemanticRuleConfig, Settings
from lczkit.heights.tiers import build_cascade
from lczkit.validation import agreement

sys.path.insert(0, str(Path(__file__).resolve().parent))

from berlin_metropolitan import CLEANING, RELEASE  # noqa: E402 - sibling script
from height_tier_experiment import cascade_for  # noqa: E402 - sibling script
from multi_city_validation import prepare  # noqa: E402 - sibling script
from unit_scale_experiment import (  # noqa: E402 - sibling script
    VALIDATION,
    build_arms,
    clean_for_arms,
    ground_truth_labels,
    wudapt_labels,
)

CASCADE = "coarse"
"""The shipped cascade, and the one every stored figure since it was adopted was measured under.
Tag every stored diagnostic with the configuration it was measured under, and do not carry one
forward across a configuration change."""

THRESHOLDS: tuple[float, ...] = (0.0, *(round(0.05 * step, 2) for step in range(1, 20)))
"""0.05 to 0.95, the grid `scripts/lcz10_threshold_sweep.py` uses, so the two rules are read on one
instrument - plus an explicit 0.0.

0.0 is not a candidate operating point. The comparison is strictly greater, so it is the
maximum-recall end of the curve: every cell holding *any* tagged evidence fires. It is here because
the question "could this rule ever reach the class" has to be separable from "is this threshold
right", and on a sparse attribute the first answer arrives before the second is worth asking."""

SIZE_GATES: dict[str, tuple[float | None, ...]] = {
    "large_lowrise": (None, 250.0, 500.0, 1000.0, 2000.0, 4000.0),
    "lightweight": (None, 50.0, 100.0, 200.0, 400.0),
}
"""Candidate values for the rule's `mean_building_area_m2` gate, spanning the shipped placeholder.

The placeholders are 1000 and 100 respectively and sit inside their grids rather than at an end, so
the sweep can move away from them in either direction. `None` - no size gate at all - is included
because the gate is optional in the config and a sweep that could not turn it off would be
measuring the pair rather than the threshold."""

TARGET = {"large_lowrise": 8, "lightweight": 7}

REFERENCES: tuple[str, ...] = ("so2sat", "wudapt")
"""Swept in this order. The first decides; the second is reported beside it."""

DECIDING_REFERENCE = "so2sat"

MIN_TARGET_SHARE = 0.05
"""Criterion 4: the rule must relabel at least this share of some city's reference cells of the
target class. Five per cent of a class is the smallest thing that could move that class's F1 by a
visible amount; below it a rule is decorative whatever its precision."""

VERIFY_AT = 0.5
"""The threshold at which the amortised rule application is checked against a full `classify`.

The sweep classifies each city once and then calls `rules.apply_semantic_rules` on the result,
because the distance metric does not depend on the rule and re-deriving it 220 times costs 8.4 s
each. That is a local operation standing in for the whole one, so it is checked rather than
asserted: at this threshold, and at the rule's shipped size gate, the labels must match a full
`PrototypeClassifier.classify` with the rule configured, cell for cell."""


@dataclass(frozen=True)
class Point:
    """One (threshold, size gate) setting, scored against one reference."""

    threshold: float
    size_gate: float | None
    n_fired: int
    """Units the rule relabelled, over the whole extent - not only the scored ones."""

    n_predicted: int
    n_reference: int
    precision: float
    """User's accuracy for the target class: of the ground lczkit calls it, how much the reference
    agrees on. Area-weighted, which on a 100 m grid is the same as count-weighted."""

    recall: float
    f1: float
    n_fired_scored: int
    """Cells the rule fired on that also carry a reference label. The denominator of the two
    figures below, and the reason they can be null while `n_fired` is large: a rule can fire all
    over an extent and touch almost nothing the reference labelled."""

    n_rule_correct: int
    """Of `n_fired_scored`, how many the reference calls the target class."""

    n_displaced_correct: int
    """Of `n_fired_scored`, how many the reference calls the label the rule overwrote."""

    rule_precision: float | None
    """`n_rule_correct / n_fired_scored`. What the rule itself gets right, with the metric's own
    calls excluded."""

    displaced_precision: float | None
    """`n_displaced_correct / n_fired_scored`. What the metric would have got right there.
    Criterion 2 is `rule_precision > displaced_precision`, pooled across cities."""

    overall_agreement: float
    built_agreement: float
    delta_overall: float
    """Change against the same city with every semantic rule off. A criterion, not decoration -
    both target classes are in the distance metric, so the rule can overwrite a correct label."""

    delta_built: float


def _rule(name: str, threshold: float, gate: float | None) -> SemanticRuleConfig:
    """The shipped rule called `name`, at one sweep setting, enabled."""
    base = next(r for r in ClassificationConfig().semantic_rules if r.name == name)
    field = "min_mean_building_area_m2" if name == "large_lowrise" else "max_mean_building_area_m2"
    return base.model_copy(
        update={"enabled": True, "min_fraction": threshold, field: gate},
    )


def _shipped_gate(name: str) -> float | None:
    """The rule's committed `mean_building_area_m2` gate, whichever side it is on."""
    base = next(r for r in ClassificationConfig().semantic_rules if r.name == name)
    return base.min_mean_building_area_m2 or base.max_mean_building_area_m2


def _config(rules_: list[SemanticRuleConfig]) -> ClassificationConfig:
    """A classification config carrying exactly `rules_` as its semantic rules.

    Every other field is left at its shipped value, including the calibrated LCZ 10 threshold: a
    sweep that also moved the one rule already calibrated would be measuring two changes.
    """
    return ClassificationConfig(semantic_rules=rules_)


# --------------------------------------------------------------------------------------------
# Stage 1 - the expensive half.


EVIDENCE_COLUMNS = ("so2sat_lcz", "so2sat_coverage", "wudapt_lcz", "wudapt_coverage", "area_m2")


def build_evidence(key: str, settings: Settings, destination: Path) -> dict[str, Any] | None:
    """One city's arm-A parameter table and both references, written as one parquet.

    Arm A comes from `build_arms`, not from a local re-assembly of the same calls. Every published
    multi-city figure in this project came through that function, and a convenience copy of it here
    would be a second definition of the pipeline whose divergence would show up only as a sweep
    that disagrees with a stored record for no visible reason.
    """
    prepared = prepare(BY_KEY[key], settings)
    if prepared is None:
        return None
    fixture, window = prepared

    started = time.time()
    print(f"\n=== {key} ({window['region']}) {window['bbox']}", file=sys.stderr, flush=True)
    ready = clean_for_arms(fixture, settings.cleaning, settings.tile_cache_dir)
    print(f"  cleaned in {time.time() - started:.0f}s", file=sys.stderr, flush=True)

    config, placed = cascade_for(settings, fixture.bbox, CASCADE)
    tiers = build_cascade(config, settings.source_dir)
    arms, _, provenance, _ = build_arms(fixture, tiers=tiers, prepared=ready)
    arm = next(a for a in arms if a.name == "A")

    frame = arm.parameters.copy()
    labelled = ground_truth_labels(fixture, arm.units)
    wudapt = wudapt_labels(fixture, arm.units)
    frame["so2sat_lcz"] = labelled[0]["reference_lcz"] if labelled else pd.NA
    frame["so2sat_coverage"] = labelled[0]["reference_coverage"] if labelled else np.nan
    frame["wudapt_lcz"] = wudapt[0]["reference_lcz"] if wudapt else pd.NA
    frame["wudapt_coverage"] = wudapt[0]["reference_coverage"] if wudapt else np.nan
    frame["area_m2"] = arm.units.geometry.area

    destination.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(destination / f"evidence_{key}.parquet")
    record = {
        "city": key,
        "region": window["region"],
        "window": window,
        "cascade": CASCADE,
        "overture_release": RELEASE,
        "height_products": placed,
        "n_units": int(len(frame)),
        "building_tag_coverage_mean": float(frame["building_tag_coverage"].mean()),
        "land_use_coverage_mean": float(frame["land_use_coverage"].mean()),
        "height_tier_fractions": provenance["height_tier_fractions"],
        "elapsed_s": round(time.time() - started, 1),
    }
    (destination / f"evidence_{key}.json").write_text(json.dumps(record, indent=2))
    print(f"  built in {record['elapsed_s']:.0f}s -> {destination.name}", file=sys.stderr)
    return record


# --------------------------------------------------------------------------------------------
# Stage 2 - the cheap half.


def _score(
    labels: pd.Series,
    reference: pd.Series,
    coverage: pd.Series,
    area: pd.Series,
    target: int,
    reference_file: str,
) -> tuple[Any, Any]:
    """The agreement report and the target class's row, or `(report, None)` if it is absent."""
    report = agreement(
        labels,
        reference,
        area,
        coverage=coverage,
        config=VALIDATION,
        reference_file=reference_file,
    )
    row = next((entry for entry in report.per_class if entry.code == target), None)
    return report, row


def _parameters(frame: pd.DataFrame) -> pd.DataFrame:
    """The parameter table, with the reference columns this script attached removed."""
    return frame.drop(columns=list(EVIDENCE_COLUMNS))


def _baseline_ranked(base: pd.DataFrame) -> rules.Ranked:
    """The classifier's ranking with every semantic rule off, as a `Ranked`.

    Semantic rules are the **last** thing `PrototypeClassifier.classify` applies to the ranking, so
    a run with the rule on differs from this one only by what `apply_semantic_rules` does to it.
    Only `primary`, `secondary` and the fired mask are read back; `runner_up` is not stored in the
    classification output and nothing here needs it, so it is explicitly absent rather than
    reconstructed from something that is not it. `VERIFY_AT` is what makes the shortcut a
    measurement rather than an assumption.
    """
    return rules.Ranked(
        primary=base["lcz_primary"],
        secondary=base["lcz_secondary"],
        closest=base["min_distance"],
        runner_up=pd.Series(np.nan, index=base.index),
    )


def _mismatches(left: pd.Series, right: pd.Series) -> int:
    """How many positions differ, counting a null against a value as a difference.

    `Int8 != Int8` returns null where either side is null, and `.sum()` skips nulls - so the naive
    comparison reports zero differences exactly where one side has no label and the other does,
    which is the case a check like this exists to catch.
    """
    left, right = left.astype("Int8"), right.astype("Int8")
    same = (left.isna() & right.isna()) | left.eq(right).fillna(False)
    return int((~same).sum())


def verify_amortisation(
    parameters: pd.DataFrame, base: pd.DataFrame, rule_name: str
) -> dict[str, Any]:
    """Check the amortised rule application against a full `classify` at one setting.

    Don't assert that a local operation is equivalent to the global one it replaces - measure the
    deviation where the global version is still tractable, and record it. Here the global version
    costs one extra 8-second classify per city per rule, so the check is exact rather than
    statistical: every label and every displaced label must match.
    """
    rule = _rule(rule_name, VERIFY_AT, _shipped_gate(rule_name))
    full = PrototypeClassifier(_config([rule])).classify(parameters)
    ranked, fired, _ = rules.apply_semantic_rules(_baseline_ranked(base), parameters, [rule])
    return {
        "rule": rule_name,
        "threshold": VERIFY_AT,
        "size_gate": _shipped_gate(rule_name),
        "n_units": int(len(parameters)),
        "primary_mismatches": _mismatches(full["lcz_primary"], ranked.primary),
        "secondary_mismatches": _mismatches(full["lcz_secondary"], ranked.secondary),
        "fired_mismatches": int((full["semantic_rule_applied"].astype(bool) != fired).sum()),
    }


def sweep_city(
    frame: pd.DataFrame,
    rule_name: str,
    reference: str,
    base: pd.DataFrame | None = None,
) -> dict[str, Any] | None:
    """The full curve for one rule on one city, against `reference` (`"so2sat"` or `"wudapt"`).

    `base` is the city's classification with every semantic rule off. It is an argument so one
    city's 8-second classify is shared across both rules and both references rather than repeated
    four times; passing `None` computes it, which is what the tests do.
    """
    target = TARGET[rule_name]
    truth = frame[f"{reference}_lcz"]
    coverage = frame[f"{reference}_coverage"]
    area = frame["area_m2"]
    if truth.notna().sum() == 0:
        return None

    parameters = _parameters(frame)
    file = f"{reference}_labels"
    if base is None:
        base = PrototypeClassifier(_config([])).classify(parameters)

    base_report, base_row = _score(base["lcz_primary"], truth, coverage, area, target, file)
    n_reference = base_row.n_reference if base_row else 0

    scored = truth.notna() & (coverage >= VALIDATION.min_reference_coverage)
    ranked0 = _baseline_ranked(base)
    points: list[Point] = []
    for gate in SIZE_GATES[rule_name]:
        for threshold in THRESHOLDS:
            rule = _rule(rule_name, threshold, gate)
            ranked, fired, counts = rules.apply_semantic_rules(ranked0, parameters, [rule])
            report, row = _score(ranked.primary, truth, coverage, area, target, file)
            # The rule's own assignments, isolated from the metric's. `lcz_secondary` holds the
            # morphological answer the rule displaced, which is what makes the comparison local:
            # on exactly these cells, was the rule right more often than what it overwrote?
            on = fired & scored
            n_on = int(on.sum())
            n_right = int((truth[on] == target).sum())
            n_was_right = int((truth[on] == ranked.secondary[on]).sum())
            points.append(
                Point(
                    threshold=threshold,
                    size_gate=gate,
                    n_fired=int(counts.get(rule_name, 0)),
                    n_predicted=row.n_predicted if row else 0,
                    n_reference=n_reference,
                    precision=row.user_accuracy if row else 0.0,
                    recall=row.agreement if row else 0.0,
                    f1=row.f1 if row else 0.0,
                    n_fired_scored=n_on,
                    n_rule_correct=n_right,
                    n_displaced_correct=n_was_right,
                    rule_precision=(n_right / n_on if n_on else None),
                    displaced_precision=(n_was_right / n_on if n_on else None),
                    overall_agreement=report.overall_agreement,
                    built_agreement=report.built_agreement,
                    delta_overall=report.overall_agreement - base_report.overall_agreement,
                    delta_built=report.built_agreement - base_report.built_agreement,
                )
            )
    return {
        "rule": rule_name,
        "target_lcz": target,
        "reference": reference,
        "n_scored": int(base_report.n_compared),
        "n_reference": int(n_reference),
        "baseline": {
            "overall_agreement": base_report.overall_agreement,
            "built_agreement": base_report.built_agreement,
            "precision": base_row.user_accuracy if base_row else 0.0,
            "recall": base_row.agreement if base_row else 0.0,
            "f1": base_row.f1 if base_row else 0.0,
            "n_predicted": base_row.n_predicted if base_row else 0,
        },
        "curve": [asdict(point) for point in points],
    }


def _order(setting: tuple[float, float | None]) -> tuple[float, float]:
    """Sort key for a (threshold, size gate) pair.

    `None` is a real gate value - no gate at all - and sorts first, so it needs a key rather than a
    comparison against a float.
    """
    threshold, gate = setting
    return (threshold, -1.0 if gate is None else gate)


def choose(city_curves: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply the four pre-registered criteria across every city, and say which one fails.

    Every setting is judged on **all** cities at once, because a threshold that helps one city and
    hurts another is not a threshold this package can ship: it would be a per-city constant wearing
    a global name.
    """
    if not city_curves:
        return {"verdict": "no city produced a curve", "operating_point": None}

    by_setting: dict[tuple[float, float | None], list[tuple[str, dict[str, Any]]]] = {}
    for city in city_curves:
        for point in city["curve"]:
            key = (point["threshold"], point["size_gate"])
            by_setting.setdefault(key, []).append((city["city"], point))

    baselines = {city["city"]: city["baseline"] for city in city_curves}
    candidates: list[dict[str, Any]] = []
    for setting in sorted(by_setting, key=_order):
        threshold, gate = setting
        rows = by_setting[setting]
        if threshold == 0.0:
            continue  # the reachability endpoint, never an operating point - see THRESHOLDS

        # C1 - no city loses class precision, and one gains. `>` alone would fail on the cities
        # where the rule cannot fire, which is a property of Overture's tags and not of the rule.
        losses = [
            point["precision"] - baselines[name]["precision"]
            for name, point in rows
            if point["n_reference"] > 0
        ]
        beats_metric = bool(losses) and min(losses) >= 0.0 and max(losses) > 0.0

        # C2 - pooled across cities, the rule beats the label it displaced. Pooled rather than
        # per-city so a city where it fires twice does not carry the same weight as one where it
        # fires two hundred times. `n_on == 0` everywhere leaves it undecided, which is a refusal:
        # `all()` over an empty sequence is True and would admit exactly the decorative rule
        # criterion 4 exists to refuse.
        n_on = sum(point["n_fired_scored"] for _, point in rows)
        n_right = sum(point["n_rule_correct"] for _, point in rows)
        n_was_right = sum(point["n_displaced_correct"] for _, point in rows)
        beats_displaced = n_on > 0 and n_right > n_was_right

        no_fall = all(point["delta_built"] >= 0.0 for _, point in rows)

        # C4 - not decorative. One city has to be reached; see the module docstring for why not all.
        reaches = any(
            point["n_fired_scored"] >= MIN_TARGET_SHARE * point["n_reference"]
            for _, point in rows
            if point["n_reference"] > 0
        )
        candidates.append(
            {
                "threshold": threshold,
                "size_gate": gate,
                "beats_metric_precision": beats_metric,
                "beats_displaced_label": beats_displaced,
                "no_built_agreement_fall": no_fall,
                "reaches_the_class": reaches,
                "passes": beats_metric and beats_displaced and no_fall and reaches,
                "mean_delta_built": float(np.mean([point["delta_built"] for _, point in rows])),
                "worst_delta_built": float(np.min([point["delta_built"] for _, point in rows])),
                "mean_precision": float(np.mean([point["precision"] for _, point in rows])),
                "mean_recall": float(np.mean([point["recall"] for _, point in rows])),
                "n_fired_scored": int(n_on),
                "n_rule_correct": int(n_right),
                "n_displaced_correct": int(n_was_right),
                "pooled_rule_precision": (n_right / n_on if n_on else None),
                "pooled_displaced_precision": (n_was_right / n_on if n_on else None),
                "total_fired": int(sum(point["n_fired"] for _, point in rows)),
            }
        )

    passing = [entry for entry in candidates if entry["passes"]]
    if passing:
        best = max(
            passing,
            key=lambda e: (e["n_fired_scored"], e["pooled_rule_precision"] or 0.0),
        )
        return {"verdict": "ENABLE", "operating_point": best, "candidates": candidates}
    failed = {
        "class precision below the metric's own": sum(
            1 for e in candidates if not e["beats_metric_precision"]
        ),
        "rule wrong more often than the label it overwrote": sum(
            1 for e in candidates if not e["beats_displaced_label"]
        ),
        "built-class agreement falls somewhere": sum(
            1 for e in candidates if not e["no_built_agreement_fall"]
        ),
        "does not reach the class anywhere": sum(
            1 for e in candidates if not e["reaches_the_class"]
        ),
    }
    return {
        "verdict": "KEEP DISABLED",
        "operating_point": None,
        "failed_criteria": failed,
        "candidates": candidates,
    }


# --------------------------------------------------------------------------------------------


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.1%}"


def show(record: dict[str, Any]) -> None:
    """Print the curve per city and the cross-city verdict for each rule."""
    print(f"\n{'=' * 110}")
    print(f"LCZ 7 / LCZ 8 semantic rule calibration - cascade {record['cascade']}")
    print(f"{'=' * 110}")

    print(f"\n{'city':14s}{'region':16s}{'units':>8}{'tagged':>9}{'parcels':>9}{'tier1':>8}")
    for city in record["cities"]:
        print(
            f"{city['city']:14s}{city['region']:16s}{city['n_units']:>8}"
            f"{city['building_tag_coverage_mean']:>9.1%}"
            f"{city['land_use_coverage_mean']:>9.1%}"
            f"{(city['height_tier_fractions'].get('overture_height') or 0.0):>8.1%}"
        )

    checks = record.get("amortisation_check", [])
    bad = [c for c in checks if max(c["primary_mismatches"], c["secondary_mismatches"]) > 0]
    print(
        f"\namortised rule application vs full classify: {len(checks)} checks, "
        f"{len(bad)} with any mismatch"
    )

    for key, block in record["rules"].items():
        rule, reference = block["rule"], block["reference"]
        deciding = " (decides)" if reference == DECIDING_REFERENCE else " (reported beside)"
        print(
            f"\n{'-' * 110}\n{rule} -> LCZ {TARGET[rule]}, against {reference}{deciding}  [{key}]"
        )
        for city in block["cities"]:
            print(
                f"\n  {city['city']}: {city['n_reference']} reference LCZ {TARGET[rule]} cells of "
                f"{city['n_scored']} scored;  metric alone: precision "
                f"{city['baseline']['precision']:.1%}, recall {city['baseline']['recall']:.1%}, "
                f"built {city['baseline']['built_agreement']:.1%}"
            )
            printed = 0
            print(
                f"  {'gate':>7}{'thresh':>8}{'fired':>8}{'judged':>8}{'rule ok':>9}"
                f"{'was ok':>8}{'prec':>8}{'recall':>8}{'F1':>8}{'d built':>9}{'d over':>9}"
            )
            for point in city["curve"]:
                if point["n_fired"] == 0 and point["threshold"] > 0.0:
                    continue
                gate = "-" if point["size_gate"] is None else f"{point['size_gate']:.0f}"
                print(
                    f"  {gate:>7}{point['threshold']:>8.2f}{point['n_fired']:>8}"
                    f"{point['n_fired_scored']:>8}{_pct(point['rule_precision']):>9}"
                    f"{_pct(point['displaced_precision']):>8}"
                    f"{point['precision']:>8.1%}"
                    f"{point['recall']:>8.1%}{point['f1']:>8.1%}"
                    f"{point['delta_built']:>+9.2%}{point['delta_overall']:>+9.2%}"
                )
                printed += 1
            if printed == 0:
                print("       (the rule fires on nothing in this city, at any setting)")

        decision = block["decision"]
        print(f"\n  VERDICT: {decision['verdict']}")
        if decision["operating_point"]:
            point = decision["operating_point"]
            print(
                f"    threshold {point['threshold']:.2f}, size gate {point['size_gate']}, "
                f"relabelled {point['n_fired_scored']} scored cells, "
                f"rule right {_pct(point['pooled_rule_precision'])} against displaced "
                f"{_pct(point['pooled_displaced_precision'])}, "
                f"worst built delta {point['worst_delta_built']:+.2%}"
            )
        else:
            for reason, count in decision.get("failed_criteria", {}).items():
                print(f"    {count:4d} of {len(decision['candidates'])} settings - {reason}")
            best = max(
                decision.get("candidates", []),
                key=lambda e: sum(
                    (
                        e["beats_metric_precision"],
                        e["beats_displaced_label"],
                        e["no_built_agreement_fall"],
                        e["reaches_the_class"],
                    )
                ),
                default=None,
            )
            if best is not None:
                print(
                    f"    closest setting: threshold {best['threshold']:.2f}, gate "
                    f"{best['size_gate']}, {best['n_fired_scored']} scored cells relabelled, "
                    f"rule right {_pct(best['pooled_rule_precision'])} against displaced "
                    f"{_pct(best['pooled_displaced_precision'])}, "
                    f"worst built delta {best['worst_delta_built']:+.2%}"
                )


def main() -> dict[str, Any]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cities", nargs="*", help="city keys; default is every built evidence file")
    parser.add_argument("--build", action="store_true", help="build evidence for the named cities")
    parser.add_argument("--evidence", type=Path, default=None, help="where evidence parquet lives")
    parser.add_argument("--out", type=Path, default=None, help="write the record as JSON")
    parser.add_argument("--report", type=Path, default=None, help="print a stored record")
    parser.add_argument("--run-id", default=None, help="name this run's output directory")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    if args.list:
        for city in CITIES:
            print(f"{city.key:18s} {city.region:16s} {city.so2sat}")
        return {}
    if args.report:
        record = json.loads(args.report.read_text(encoding="utf-8"))
        show(record)
        return record

    settings = Settings.load(run_id=args.run_id)
    settings.overture.release = RELEASE
    settings.cleaning = CLEANING.model_copy()
    evidence = args.evidence or settings.run_dir

    if args.build:
        for key in args.cities:
            if (evidence / f"evidence_{key}.parquet").exists():
                print(f"  {key}: already built, skipping", file=sys.stderr)
                continue
            try:
                build_evidence(key, settings, evidence)
            except Exception as error:  # noqa: BLE001 - one city must not end the sweep
                print(f"  {key}: FAILED - {type(error).__name__}: {error}", file=sys.stderr)
        return {}

    built = sorted(path.stem.removeprefix("evidence_") for path in evidence.glob("evidence_*.json"))
    keys = args.cities or built
    record: dict[str, Any] = {
        "experiment": "lcz7-lcz8-threshold-sweep",
        "run_id": settings.run_id,
        "cascade": CASCADE,
        "overture_release": RELEASE,
        "evidence_dir": str(evidence),
        "thresholds": list(THRESHOLDS),
        "size_gates": {name: list(values) for name, values in SIZE_GATES.items()},
        "min_target_share": MIN_TARGET_SHARE,
        "deciding_reference": DECIDING_REFERENCE,
        "cities": [],
        "amortisation_check": [],
        "rules": {},
    }
    frames: dict[str, pd.DataFrame] = {}
    for key in keys:
        record["cities"].append(json.loads((evidence / f"evidence_{key}.json").read_text()))
        frames[key] = pd.read_parquet(evidence / f"evidence_{key}.parquet")

    # One classify per city, shared by both rules and both references. Everything after this is
    # the rule and the arithmetic, which is why the grid can be this wide.
    bases: dict[str, pd.DataFrame] = {}
    for key, frame in frames.items():
        started = time.time()
        parameters = _parameters(frame)
        bases[key] = PrototypeClassifier(_config([])).classify(parameters)
        for rule_name in TARGET:
            check = verify_amortisation(parameters, bases[key], rule_name)
            check["city"] = key
            record["amortisation_check"].append(check)
        print(f"  {key}: classified in {time.time() - started:.0f}s", file=sys.stderr, flush=True)

    for rule_name in TARGET:
        for reference in REFERENCES:
            curves = []
            for key, frame in frames.items():
                curve = sweep_city(frame, rule_name, reference, base=bases[key])
                if curve is None:
                    continue
                curve["city"] = key
                curves.append(curve)
            record["rules"][f"{rule_name}:{reference}"] = {
                "rule": rule_name,
                "reference": reference,
                "cities": curves,
                "decision": choose(curves),
            }

    show(record)
    destination = args.out or (settings.run_dir / "lcz78_threshold_sweep.json")
    destination.write_text(json.dumps(record, indent=2))
    print(f"\n  written to {destination}")
    return record


if __name__ == "__main__":
    main()
