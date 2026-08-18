"""The LCZ 10 threshold calibration, as a test rather than a claim in a docstring.

CLAUDE.md: "Calibrate the threshold, do not pick it." These assert that the sweep runs offline on
the committed Rotterdam fixture, that the shipped default is the point it selects, and — the part
worth guarding — that the curve is as flat as this phase measured it, so nobody reads the default
as a precision optimum it is not.
"""

from __future__ import annotations

import pytest
from conftest import load_script

from lczkit.config import ClassificationConfig

SCRIPT = load_script("lcz10_threshold_sweep")


@pytest.fixture(scope="module")
def swept() -> tuple[list, dict]:
    parameters, reference = SCRIPT.build()
    column = ClassificationConfig().lcz10_industrial_column
    points = SCRIPT.sweep(parameters, reference, column)
    return points, {"column": column}


def test_the_shipped_default_is_the_point_the_sweep_selects(swept: tuple[list, dict]) -> None:
    """The number in `ClassificationConfig` has to be the one this curve chose, or the config is
    asserting a calibration that never happened."""
    points, _ = swept

    chosen = SCRIPT.choose(points)

    assert chosen is not None
    assert chosen.threshold == pytest.approx(ClassificationConfig().lcz10_min_industrial_fraction)


def test_the_rule_fires_at_every_threshold_unlike_the_one_it_replaced(
    swept: tuple[list, dict],
) -> None:
    """The pair-gated rule produced zero LCZ 10 cells at 0.05, 0.25 and 0.5 alike. Functional
    assignment has to actually reach the port."""
    points, _ = swept

    assert all(point.n_predicted > 0 for point in points)
    assert all(point.true_positive > 0 for point in points)


def test_precision_is_flat_so_the_threshold_is_not_buying_correctness(
    swept: tuple[list, dict],
) -> None:
    """**The measurement that refutes CLAUDE.md's stated expectation** of landing high-precision,
    low-recall. Precision moves by about six points across a 19-fold change in threshold, so the
    threshold governs how much of the map carries LCZ 10 and not how often that label is right.

    Guarded as a range rather than an exact value: the point is the *shape* of the curve, and a
    future change that gave the threshold real discriminating power should fail this and be read,
    not silently absorbed."""
    points, _ = swept
    precisions = [point.precision for point in points]

    # Measured 16.7% to 23.2% on FIND/B, a 6.5-point range over a 19-fold change in threshold.
    assert max(precisions) - min(precisions) < 0.10
    assert max(precisions) < 0.40


def test_recall_falls_with_the_threshold_so_it_still_controls_coverage(
    swept: tuple[list, dict],
) -> None:
    """Flat precision does not mean the knob does nothing — it halves how much of the map is
    labelled. That is what makes a conservative default meaningful."""
    points, _ = swept

    assert points[0].recall > points[-1].recall
    assert points[0].n_predicted > points[-1].n_predicted


def test_the_record_names_the_reference_it_was_calibrated_against(
    swept: tuple[list, dict],
) -> None:
    """Rotterdam has no So2Sat coverage, so this is `lcz_v3` — a comparator carrying its own error,
    permitted by CLAUDE.md for the LCZ 10 rule only. A curve that does not say so is
    indistinguishable from one measured against ground truth."""
    points, meta = swept

    assert meta["column"] == "industrial_fraction_of_building_area"
    assert all(point.n_reference > 50 for point in points)
