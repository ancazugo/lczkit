"""Agreement statistics against hand-built confusion, with the arithmetic done by hand.

Every number here is computable on paper from a handful of units, which is the only way to be
sure an agreement figure means what it says. The two breakdowns beyond the standard ones — by
`height_completeness` decile, and the 1<->4 / 2<->5 / 3<->6 pairs — are the point of the module:
they turn the Phase 3 caveat about areal height products into something measured.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lczkit.config import ValidationConfig
from lczkit.validation import agreement


def build(
    predicted: list[float], reference: list[float], area: list[float] | None = None
) -> tuple[pd.Series, pd.Series, pd.Series]:
    index = pd.Index([f"u{position}" for position in range(len(predicted))], name="unit_id")
    areas = [10_000.0] * len(predicted) if area is None else area
    return (
        pd.Series(predicted, index=index, dtype="Int8"),
        pd.Series(reference, index=index, dtype="Int8"),
        pd.Series(areas, index=index, dtype="float64"),
    )


def test_overall_agreement_is_area_weighted_not_a_unit_count() -> None:
    """On a regular grid the two coincide; on enclosures they do not, and counting units there
    would let a thousand courtyards outvote a district."""
    predicted, reference, area = build([2, 2, 5], [2, 5, 5], area=[100.0, 900.0, 1000.0])

    report = agreement(predicted, reference, area)

    # 100 + 1000 of 2000 m2 agree, though two of three units do not.
    assert report.overall_agreement == pytest.approx(0.55)
    assert report.n_compared == 3
    assert report.n_disagree == 1


def test_per_class_agreement_is_reported_rather_than_a_headline_number() -> None:
    """CLAUDE.md: comparability with the literature matters more than a headline figure. A class
    the run never gets right can hide entirely inside a good overall number."""
    predicted, reference, area = build([2, 2, 2, 6], [2, 2, 6, 6])

    report = agreement(predicted, reference, area)

    by_code = {entry.code: entry for entry in report.per_class}
    assert by_code[2].agreement == pytest.approx(1.0)
    assert by_code[2].n_reference == 2
    assert by_code[6].agreement == pytest.approx(0.5)
    assert by_code[6].name == "Open low-rise"


def test_the_confusion_matrix_is_sparse_and_complete() -> None:
    predicted, reference, area = build([2, 5, 5], [2, 2, 5])

    report = agreement(predicted, reference, area)

    cells = {(cell.reference, cell.predicted): cell.n for cell in report.confusion}
    assert cells == {(2, 2): 1, (2, 5): 1, (5, 5): 1}
    assert sum(cells.values()) == report.n_compared


def test_the_compactness_axis_pairs_are_counted_in_both_directions() -> None:
    """A footprint deficit moves a label along the compact/open axis in whichever direction it
    errs, so counting one way would halve the signal this breakdown exists to measure."""
    predicted, reference, area = build([4, 1, 5, 9], [1, 4, 2, 3])

    report = agreement(predicted, reference, area)

    pairs = {(entry.a, entry.b): entry for entry in report.compactness_axis}
    assert pairs[(1, 4)].n_a_as_b == 1
    assert pairs[(1, 4)].n_b_as_a == 1
    assert pairs[(1, 4)].n_total == 2
    assert pairs[(2, 5)].n_total == 1
    assert pairs[(3, 6)].n_total == 0
    # Three of the four disagreements sit on the compactness axis.
    assert pairs[(1, 4)].share_of_disagreement == pytest.approx(0.5)
    assert sum(entry.n_total for entry in report.compactness_axis) == 3


def test_the_two_axes_are_reported_separately_and_measure_different_things() -> None:
    """The correction CLAUDE.md's resolved-discrepancy table records.

    A reference LCZ 2 called LCZ 5 is a *compactness* error — both are midrise — and a reference
    LCZ 2 called LCZ 3 is a *height* error, both being compact. Pooling them, or reporting the
    first under the name of the second, inverts what a reader concludes about whether heights or
    footprints are the limiting factor.
    """
    predicted, reference, area = build([5, 3, 6], [2, 2, 2])

    report = agreement(predicted, reference, area)

    height = {(entry.a, entry.b): entry.n_total for entry in report.height_axis}
    compactness = {(entry.a, entry.b): entry.n_total for entry in report.compactness_axis}

    assert len(report.height_axis) == 6
    assert len(report.compactness_axis) == 3
    assert height[(2, 3)] == 1  # compact midrise read as compact low-rise: height
    assert compactness[(2, 5)] == 1  # compact midrise read as open midrise: compactness
    # 2 -> 6 differs on both axes at once and belongs to neither.
    assert sum(height.values()) + sum(compactness.values()) == 2
    assert report.n_disagree == 3


def test_agreement_is_stratified_by_height_completeness_in_equal_width_bands() -> None:
    """Equal-width, not equal-count: the whole point is to compare cities, and a decile boundary
    at "the 40th percentile of this city" says nothing about any other."""
    predicted, reference, area = build([2, 2, 2, 2], [2, 5, 2, 2])
    completeness = pd.Series([0.05, 0.05, 0.95, 0.95], index=predicted.index)

    report = agreement(
        predicted, reference, area, height_completeness=completeness, config=ValidationConfig()
    )

    strata = {entry.index: entry for entry in report.by_height_completeness}
    assert len(strata) == 10
    assert strata[0].n == 2 and strata[0].agreement == pytest.approx(0.5)
    assert strata[9].n == 2 and strata[9].agreement == pytest.approx(1.0)
    assert strata[4].n == 0 and strata[4].agreement == 0.0


def test_the_top_stratum_includes_a_completeness_of_exactly_one() -> None:
    """`height_completeness` of 1.0 is the best possible case and must not fall outside every
    band — which is what a half-open interval on the last bin would do."""
    predicted, reference, area = build([2], [2])
    report = agreement(
        predicted, reference, area, height_completeness=pd.Series([1.0], index=predicted.index)
    )

    assert report.by_height_completeness[-1].n == 1


def test_units_without_a_label_on_either_side_are_excluded_and_counted() -> None:
    """A run comparing a tenth of its units against the reference is a different claim from one
    comparing all of them, so the exclusions are reported rather than silently dropped."""
    predicted, reference, area = build([2, 2, np.nan], [2, np.nan, 2])

    report = agreement(predicted, reference, area)

    assert report.n_units == 3
    assert report.n_compared == 1
    assert report.excluded_no_prediction == 1
    assert report.excluded_no_reference == 1


def test_a_unit_the_reference_barely_covers_is_excluded() -> None:
    """A unit half outside the reference map would otherwise contribute a confident majority
    computed from a corner of itself."""
    predicted, reference, area = build([2, 2], [5, 5])
    coverage = pd.Series([0.9, 0.1], index=predicted.index)

    report = agreement(predicted, reference, area, coverage=coverage)

    assert report.n_compared == 1
    assert report.excluded_low_coverage == 1
    assert report.min_reference_coverage == 0.5


def test_built_agreement_is_reported_apart_from_an_overall_figure_water_can_carry() -> None:
    """Rotterdam's headline 42.5% was 266 water cells agreeing at 95.9% while LCZ 8 sat at 0.0%
    over 224. Here: three water cells all right, three built cells all wrong. An overall 50% would
    be a true statement about nothing.
    """
    predicted, reference, area = build([17, 17, 17, 2, 2, 2], [17, 17, 17, 5, 5, 5])

    report = agreement(predicted, reference, area)

    assert report.overall_agreement == pytest.approx(0.5)
    assert report.built_agreement == pytest.approx(0.0)
    assert report.natural_agreement == pytest.approx(1.0)
    assert report.n_built == 3
    assert report.n_natural == 3
    assert report.natural_share == pytest.approx(0.5)


def test_the_built_natural_split_is_taken_from_the_reference_not_the_prediction() -> None:
    """Otherwise a classifier could raise its built score by predicting water: the mislabelled
    cell would leave the built denominator along with the error."""
    predicted, reference, area = build([17, 2], [2, 2])

    report = agreement(predicted, reference, area)

    assert report.n_built == 2
    assert report.n_natural == 0
    assert report.built_agreement == pytest.approx(0.5)
    assert report.natural_agreement == 0.0


def test_nothing_comparable_gives_an_empty_report_rather_than_an_error() -> None:
    predicted, reference, area = build([np.nan], [np.nan])

    report = agreement(predicted, reference, area)

    assert report.n_compared == 0
    assert report.overall_agreement == 0.0
    assert report.per_class == []
    assert report.confusion == []


def test_the_report_round_trips_through_json() -> None:
    """It is embedded verbatim in the run manifest, so it has to survive serialisation."""
    predicted, reference, area = build([2, 5], [2, 2])

    report = agreement(predicted, reference, area)

    assert type(report).model_validate_json(report.model_dump_json()) == report
