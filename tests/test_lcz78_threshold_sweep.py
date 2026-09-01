"""The LCZ 7 and LCZ 8 semantic-rule calibration, as tests rather than claims in a docstring.

Two things are pinned here, and they are different kinds of statement.

**The instrument discriminates.** `choose` applies four criteria and the whole value of the sweep
is that they can refuse. A synthetic city whose reference agrees with the rule must come back
`ENABLE`; one whose reference agrees with the label the rule *overwrote* must come back
`KEEP DISABLED`, naming that criterion. Without these the sweep is a function that has only ever
been run on data whose answer nobody could check independently — and this project's record has two
instruments that returned a confident wrong answer for exactly that reason.

**The shipped configuration is what the sweep concluded.** CLAUDE.md's standing rule is that a
ruling is not applied until the code says so, and the LCZ 10 sweep has the same guard. Here the
conclusion is *enable LCZ 8 at 0.70 with no size gate, refuse LCZ 7*, so that is what is asserted.

Unlike the LCZ 10 sweep, this one cannot be re-run inside a test: it needs eight cities of built
evidence under `DATA_DIR` and CI has none. So the guard is split — the criteria are exercised
against synthetic frames here, and the operating point is pinned as a literal, with the run record
archived under `output/lczkit/lcz78-sweep/`.

Entirely offline: the synthetic frames are built in this file, and nothing reads `DATA_DIR`.
"""

from __future__ import annotations

import pandas as pd
import pytest
from conftest import load_script

from lczkit.config import ClassificationConfig

SCRIPT = load_script("lcz78_threshold_sweep")

#: A cell the distance metric calls LCZ 5 — open midrise — chosen so a rule pushing it to LCZ 8 is
#: visibly a change rather than a coincidence. Verified by classifying it: LCZ 5, runner-up 6.
MIDRISE = {
    "building_surface_fraction": 0.15,
    "impervious_surface_fraction": 0.30,
    "pervious_surface_fraction": 0.30,
    "height_of_roughness_elements_m": 15.0,
    "aspect_ratio": 0.6,
    "tree_fraction": 0.0,
    "water_fraction": 0.0,
    "mean_building_area_m2": 300.0,
    "industrial_fraction_of_building_area": 0.0,
    "sem_large_lowrise_buildings_of_building_area": 0.0,
    "sem_lightweight_buildings_of_building_area": 0.0,
}

TAGGED = {
    **MIDRISE,
    "sem_large_lowrise_buildings_of_building_area": 0.9,
    "mean_building_area_m2": 4000.0,
}


def _city(tagged_reference: int, untagged_reference: int, *, labelled: bool = True) -> pd.DataFrame:
    """Twenty tagged cells and twenty untagged, with the reference each side is given.

    `labelled=False` withholds the reference from the tagged half only, which is the case a rule
    can fire all over an extent and touch nothing anyone measured.
    """
    rows = {f"tag{i}": dict(TAGGED) for i in range(20)}
    rows |= {f"plain{i}": dict(MIDRISE) for i in range(20)}
    frame = pd.DataFrame(rows).T
    frame.index.name = "unit_id"
    is_tagged = frame.index.str.startswith("tag")
    frame["so2sat_lcz"] = pd.array(
        [
            (tagged_reference if labelled else None) if tag else untagged_reference
            for tag in is_tagged
        ],
        dtype="Int8",
    )
    frame["so2sat_coverage"] = [0.0 if (tag and not labelled) else 1.0 for tag in is_tagged]
    frame["wudapt_lcz"] = pd.array([None] * len(frame), dtype="Int8")
    frame["wudapt_coverage"] = 0.0
    frame["area_m2"] = 10_000.0
    return frame


def _decide(frame: pd.DataFrame) -> dict:
    curve = SCRIPT.sweep_city(frame, "large_lowrise", "so2sat")
    assert curve is not None
    curve["city"] = "synthetic"
    return SCRIPT.choose([curve])


def test_a_rule_that_agrees_with_the_reference_is_enabled() -> None:
    """The positive control. Without it, a sweep that refuses everything is indistinguishable from
    one that cannot accept anything."""
    decision = _decide(_city(tagged_reference=8, untagged_reference=5))

    assert decision["verdict"] == "ENABLE"
    assert decision["operating_point"]["threshold"] > 0.0


def test_a_rule_that_overwrites_a_correct_label_is_refused_and_the_reason_is_named() -> None:
    """The criterion that does not exist in the LCZ 10 sweep, and has to exist here.

    LCZ 10 is outside the distance metric, so the industrial rule can only add. LCZ 8 is *in* the
    prototype set, so a semantic rule replaces whatever the metric said — and a cell the metric had
    right becomes a cell the rule has wrong. Per-class precision cannot see that; comparing the
    rule against the label it displaced can.
    """
    decision = _decide(_city(tagged_reference=5, untagged_reference=8))

    assert decision["verdict"] == "KEEP DISABLED"
    assert all(not entry["beats_displaced_label"] for entry in decision["candidates"])
    assert decision["failed_criteria"]["rule wrong more often than the label it overwrote"] > 0


def test_a_rule_firing_only_where_nothing_is_labelled_cannot_pass_by_vacuous_truth() -> None:
    """`all()` over an empty sequence is True, so a rule that reaches no scored cell would satisfy
    the displaced-label criterion by having nothing to be judged on. That is the decorative rule
    the criteria exist to refuse, and it would have passed silently."""
    decision = _decide(_city(tagged_reference=8, untagged_reference=5, labelled=False))

    assert decision["verdict"] == "KEEP DISABLED"
    assert all(not entry["beats_displaced_label"] for entry in decision["candidates"])


def test_the_reachability_endpoint_is_never_an_operating_point() -> None:
    """0.0 is on the curve so that "could this rule reach the class at all" is separable from "is
    this threshold right". It is not a candidate: the comparison is strictly greater, so 0.0 fires
    on every cell holding any evidence whatever."""
    decision = _decide(_city(tagged_reference=8, untagged_reference=5))

    assert 0.0 in SCRIPT.THRESHOLDS
    assert all(entry["threshold"] > 0.0 for entry in decision["candidates"])


def test_a_size_gate_of_none_orders_alongside_the_numeric_ones() -> None:
    """`None` is a real setting — no size gate at all — and sorting it against floats raises. Found
    by running the sweep, not by reading it."""
    ordered = sorted([(0.5, 1000.0), (0.5, None), (0.1, None)], key=SCRIPT._order)

    assert ordered == [(0.1, None), (0.5, None), (0.5, 1000.0)]


@pytest.mark.parametrize(
    ("name", "enabled", "threshold", "gate"),
    [
        ("large_lowrise", True, 0.70, None),
        ("lightweight", False, 0.5, 100.0),
    ],
)
def test_the_shipped_rules_are_what_the_sweep_concluded(
    name: str, enabled: bool, threshold: float, gate: float | None
) -> None:
    """The operating point, pinned where the config can be compared against it.

    `large_lowrise` cleared all four criteria at 0.70 with no size gate — 662 labelled cells
    relabelled, 72.2% of them reference LCZ 8 against 14.8% for the label displaced, and precision,
    recall, F1 and built-class agreement all up in all eight cities.

    `lightweight` was refused at all 95 settings on all four criteria, so its values stay at the
    placeholders and `enabled=False` is a result rather than a rule awaiting one. Its best setting
    anywhere produced **2** correct LCZ 7 labels against So2Sat while displacing 93 the metric had
    right: Overture's lightweight vocabulary is outbuildings, and the tagged evidence is in the
    three cities carrying no reference LCZ 7 at all.
    """
    rule = next(r for r in ClassificationConfig().semantic_rules if r.name == name)

    assert rule.enabled is enabled
    assert rule.min_fraction == pytest.approx(threshold)
    assert (rule.min_mean_building_area_m2 or rule.max_mean_building_area_m2) == gate
