"""The family gate and the LCZ 10 rule, in isolation from the distance metric.

Both are deliberately outside the metric, so both are testable without one. That separation is
CLAUDE.md's requirement for LCZ 10 specifically — a functional attribute folded into a
morphological distance would silently distort every other class — and it is what lets these be
five-line functions with hand-checkable behaviour.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lczkit.classify import rules
from lczkit.classify.rules import (
    BUILT,
    NATURAL,
    Ranked,
    apply_lcz10_rule,
    drop_lcz1_below_height,
    family_of,
)
from lczkit.config import ClassificationConfig, SemanticRuleConfig


def series(*values: float) -> pd.Series:
    return pd.Series(values, index=[f"u{index}" for index in range(len(values))], dtype="float64")


def test_the_gate_splits_at_the_threshold_inclusively() -> None:
    """At or above is built. The default 0.10 is the boundary the Stewart & Oke table draws
    itself — every built class starts there and every natural class stops there — so a unit
    sitting exactly on it belongs to the built side, matching LCZ 9's published range."""
    result = family_of(series(0.0, 0.099, 0.10, 0.55), 0.10)

    assert result.to_list() == [NATURAL, NATURAL, BUILT, BUILT]


def test_the_gate_refuses_a_null_building_fraction() -> None:
    """Phase 5 reports 0.0 for a unit holding no buildings, on purpose — "no buildings here" is a
    measurement. A null therefore means the table did not come from Phase 5, and quietly gating it
    one way or the other would misclassify every such unit without saying so."""
    with pytest.raises(ValueError, match="compute_parameters"):
        family_of(series(0.5, np.nan), 0.10)


def ranked(primary: float, secondary: float, closest: float, runner_up: float) -> Ranked:
    return Ranked(
        primary=pd.Series([primary], index=["u0"]),
        secondary=pd.Series([secondary], index=["u0"]),
        closest=pd.Series([closest], index=["u0"]),
        runner_up=pd.Series([runner_up], index=["u0"]),
    )


def test_lcz10_is_assigned_functionally_whatever_the_morphology_said() -> None:
    """The measured failure of the pair-gated rule it replaces. Rotterdam has 671 cells of working
    port, 254 industrial buildings, three quarters of cells over 90% industrial by area and 88 cells
    placed in LCZ 10 by the reference — and the LCZ 8 / LCZ 10 pair never opened once, at any
    threshold from 0.05 to 0.5. Port plots are large and sparsely built, so building surface
    fraction lands them on LCZ 9. The evidence has to override the morphology, not wait for it."""
    swapped, fired = apply_lcz10_rule(ranked(9, 6, 0.2, 0.3), pd.Series([0.9], index=["u0"]), 0.5)

    assert fired.to_list() == [True]
    assert swapped.primary.to_list() == [10]
    assert swapped.secondary.to_list() == [9]


def test_lcz10_leaves_the_unit_alone_below_the_threshold() -> None:
    """The default is set to under-trigger. Overture cannot tell heavy industry from light, so a
    light-industrial estate mislabelled as heavy industry is an invisible error that propagates
    into any model consuming the map, whereas a missing LCZ 10 is a visible gap."""
    swapped, fired = apply_lcz10_rule(ranked(8, 6, 0.2, 0.3), pd.Series([0.4], index=["u0"]), 0.5)

    assert fired.to_list() == [False]
    assert swapped.primary.to_list() == [8]
    assert swapped.closest.to_list() == [0.2]


def test_the_displaced_morphological_answer_is_kept_with_its_distance() -> None:
    """`runner_up` is the distance to `secondary`, and that invariant has to survive the rule:
    after firing, `secondary` is the class the morphology chose and `runner_up` is how far away it
    was. The output then says exactly what would have been emitted without the evidence."""
    swapped, _ = apply_lcz10_rule(ranked(8, 6, 0.2, 0.7), pd.Series([0.9], index=["u0"]), 0.5)

    assert swapped.secondary.to_list() == [8]
    assert swapped.runner_up.to_list() == [0.2]


def test_a_functionally_assigned_unit_has_no_distance_to_report() -> None:
    """LCZ 10 is not in the metric, so no distance to it exists. Carrying the displaced class's
    distance under `min_distance` would describe a different classification from `lcz_primary`."""
    swapped, _ = apply_lcz10_rule(ranked(9, 6, 0.2, 0.3), pd.Series([0.9], index=["u0"]), 0.5)

    assert swapped.closest.isna().to_list() == [True]


def test_a_null_industrial_fraction_never_fires_the_rule() -> None:
    """The unit-area share is 0.0 where there is no evidence, so a null means the layer was absent
    entirely — or, for the building-area share the rule reads by default, that the unit holds no
    buildings to judge. Neither is grounds for calling it heavy industry."""
    _, fired = apply_lcz10_rule(ranked(8, 10, 0.2, 0.3), pd.Series([np.nan], index=["u0"]), 0.5)

    assert fired.to_list() == [False]


def test_the_lcz1_height_constraint_is_off_unless_configured() -> None:
    distances = pd.DataFrame({1: [0.1, 0.1], 8: [0.5, 0.5]}, index=["u0", "u1"])
    heights = pd.Series([4.0, 90.0], index=["u0", "u1"])

    assert drop_lcz1_below_height(distances, heights, None).equals(distances)


def test_the_lcz1_height_constraint_drops_only_the_short_units() -> None:
    """Bernard et al. report LCZ 1 appearing across European cities without an equivalent guard.
    lczkit has no reliable storey count so this reaches for Hr and defaults to off, but the hook
    has to work when a user turns it on."""
    distances = pd.DataFrame({1: [0.1, 0.1, 0.1], 8: [0.5, 0.5, 0.5]}, index=["u0", "u1", "u2"])
    heights = pd.Series([4.0, 90.0, np.nan], index=["u0", "u1", "u2"])

    result = drop_lcz1_below_height(distances, heights, 30.0)

    assert np.isnan(result.loc["u0", 1])
    assert result.loc["u1", 1] == 0.1
    # A null height is not evidence of shortness, so it is not evidence for dropping LCZ 1.
    assert result.loc["u2", 1] == 0.1
    assert result[8].equals(distances[8])


# --------------------------------------------------------------------------------------------
# Phase 18: the generalised functional rules
# --------------------------------------------------------------------------------------------


def _ranked(primary: list[int], secondary: list[int]) -> rules.Ranked:
    index = pd.Index([f"u{i}" for i in range(len(primary))], name="unit_id")
    return rules.Ranked(
        primary=pd.Series(primary, index=index, dtype="float64"),
        secondary=pd.Series(secondary, index=index, dtype="float64"),
        closest=pd.Series(0.5, index=index, dtype="float64"),
        runner_up=pd.Series(0.9, index=index, dtype="float64"),
    )


def _params(**columns: list[float]) -> pd.DataFrame:
    length = len(next(iter(columns.values())))
    return pd.DataFrame(columns, index=pd.Index([f"u{i}" for i in range(length)], name="unit_id"))


def test_a_disabled_rule_is_reported_as_zero_rather_than_omitted() -> None:
    """CLAUDE.md's requirement, first written for the LCZ 10 rule: a rule that never fires must be
    distinguishable from one never configured. Every shipped semantic rule is disabled, so without
    this the manifest would say nothing at all about them."""
    rule = SemanticRuleConfig(name="lightweight", lcz=7, column="sem_x", enabled=False)

    ranked, fired, counts = rules.apply_semantic_rules(
        _ranked([2, 3], [5, 6]), _params(sem_x=[0.9, 0.9]), [rule]
    )

    assert counts == {"lightweight": 0}
    assert not fired.any()
    assert list(ranked.primary) == [2.0, 3.0]


def test_an_enabled_rule_overrides_the_metric_and_keeps_the_displaced_answer() -> None:
    """Same contract as `apply_lcz10_rule`: the label the morphology would have produced is not
    lost, it becomes `secondary`, and `closest` goes null because the assigned class was not
    reached by distance."""
    rule = SemanticRuleConfig(
        name="large_lowrise", lcz=8, column="sem_x", min_fraction=0.5, enabled=True
    )

    ranked, fired, counts = rules.apply_semantic_rules(
        _ranked([3, 3], [6, 6]), _params(sem_x=[0.9, 0.1]), [rule]
    )

    assert list(ranked.primary) == [8.0, 3.0]
    assert list(ranked.secondary) == [3.0, 6.0]
    assert pd.isna(ranked.closest.iloc[0]) and ranked.closest.iloc[1] == 0.5
    assert list(fired) == [True, False]
    assert counts == {"large_lowrise": 1}


def test_a_building_size_gate_narrows_a_rule_the_metric_cannot_express() -> None:
    """`mean_building_area_m2` is not a metric dimension — Phase 14 established that, and that the
    stated reason for keeping LCZ 8 in the metric therefore described a parameter that never
    reached it. A rule is not the metric, so it may read it."""
    rule = SemanticRuleConfig(
        name="large_lowrise",
        lcz=8,
        column="sem_x",
        min_fraction=0.5,
        min_mean_building_area_m2=1000.0,
        enabled=True,
    )

    _, fired, _ = rules.apply_semantic_rules(
        _ranked([3, 3], [6, 6]),
        _params(sem_x=[0.9, 0.9], mean_building_area_m2=[2000.0, 100.0]),
        [rule],
    )

    assert list(fired) == [True, False]


def test_a_null_fraction_never_fires_a_rule() -> None:
    """Null means "no buildings to judge", which is not grounds for asserting a class."""
    rule = SemanticRuleConfig(name="lightweight", lcz=7, column="sem_x", enabled=True)

    _, fired, counts = rules.apply_semantic_rules(
        _ranked([3], [6]), _params(sem_x=[float("nan")]), [rule]
    )

    assert not fired.any()
    assert counts == {"lightweight": 0}


def test_a_later_rule_wins_and_the_counts_say_so() -> None:
    """Order is the config's order, and the counts are of units each rule *holds* at the end — not
    of units it fired on — so a rule shadowed by a later one reads zero rather than double-counting.
    LCZ 7 and 8 are both in the prototype set, so counting the resulting labels instead would also
    sweep up every unit the metric assigned."""
    first = SemanticRuleConfig(name="large_lowrise", lcz=8, column="sem_a", enabled=True)
    second = SemanticRuleConfig(name="lightweight", lcz=7, column="sem_b", enabled=True)

    ranked, fired, counts = rules.apply_semantic_rules(
        _ranked([3, 3], [6, 6]),
        _params(sem_a=[0.9, 0.9], sem_b=[0.9, 0.1]),
        [first, second],
    )

    assert list(ranked.primary) == [7.0, 8.0]
    assert counts == {"large_lowrise": 1, "lightweight": 1}
    assert fired.all()


def test_a_rule_reading_an_absent_column_is_refused_by_name() -> None:
    """Silently skipping would make a misconfigured rule indistinguishable from one that never
    fired, which is the state the whole reporting contract exists to rule out."""
    rule = SemanticRuleConfig(name="lightweight", lcz=7, column="sem_missing", enabled=True)

    with pytest.raises(ValueError, match="sem_missing"):
        rules.apply_semantic_rules(_ranked([3], [6]), _params(sem_x=[0.9]), [rule])


def test_every_shipped_semantic_rule_is_disabled_pending_calibration() -> None:
    """CLAUDE.md's standing ruling: a threshold is swept against a reference and chosen at an
    operating point, never picked. These have not been swept, so shipping one enabled would put an
    invented number into a published label."""
    shipped = ClassificationConfig().semantic_rules

    assert shipped, "the rules should exist and be off, not be absent"
    assert not any(rule.enabled for rule in shipped)
    assert all(rule.reason for rule in shipped)
