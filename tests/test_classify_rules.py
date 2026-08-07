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

from lczkit.classify.rules import (
    BUILT,
    NATURAL,
    Ranked,
    apply_lcz10_rule,
    drop_lcz1_below_height,
    family_of,
)


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


def test_lcz10_fires_only_on_the_eight_ten_pair_above_the_threshold() -> None:
    swapped, fired = apply_lcz10_rule(ranked(8, 10, 0.2, 0.3), pd.Series([0.9], index=["u0"]), 0.5)

    assert fired.to_list() == [True]
    assert swapped.primary.to_list() == [10]
    assert swapped.secondary.to_list() == [8]


def test_lcz10_leaves_the_pair_alone_below_the_threshold() -> None:
    """The default is set to under-trigger. Overture cannot tell heavy industry from light, so a
    light-industrial estate mislabelled as heavy industry is an invisible error that propagates
    into any model consuming the map, whereas a missing LCZ 10 is a visible gap."""
    swapped, fired = apply_lcz10_rule(ranked(8, 10, 0.2, 0.3), pd.Series([0.4], index=["u0"]), 0.5)

    assert fired.to_list() == [False]
    assert swapped.primary.to_list() == [8]


def test_lcz10_ignores_a_pair_that_is_not_eight_and_ten() -> None:
    """A heavily industrial unit that reads morphologically as LCZ 6 is not relabelled. The rule
    breaks a tie the morphology genuinely cannot resolve; it is not a land-use override."""
    _, fired = apply_lcz10_rule(ranked(8, 6, 0.1, 0.2), pd.Series([0.99], index=["u0"]), 0.5)

    assert fired.to_list() == [False]


def test_a_unit_already_nearest_lcz10_does_not_count_as_fired() -> None:
    """The flag means the rule *changed* the label, which is what a reader seeing LCZ 10 on a map
    wants to know. A unit the morphology placed there unaided is a different claim."""
    swapped, fired = apply_lcz10_rule(ranked(10, 8, 0.1, 0.2), pd.Series([0.99], index=["u0"]), 0.5)

    assert fired.to_list() == [False]
    assert swapped.primary.to_list() == [10]


def test_the_swapped_distance_follows_the_swapped_label() -> None:
    """`min_distance` has to be the distance to the class actually reported, or the two columns
    describe different classifications."""
    swapped, _ = apply_lcz10_rule(ranked(8, 10, 0.2, 0.7), pd.Series([0.9], index=["u0"]), 0.5)

    assert swapped.closest.to_list() == [0.7]
    assert swapped.runner_up.to_list() == [0.2]


def test_a_null_industrial_fraction_never_fires_the_rule() -> None:
    """Phase 5 reports 0.0 where there is no industrial evidence, so a null means the layer was
    absent entirely — a reason to leave the morphological answer alone, not to override it."""
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
