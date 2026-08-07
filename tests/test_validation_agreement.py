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


def test_the_height_axis_pairs_are_counted_in_both_directions() -> None:
    """A height estimate that cannot resolve the LCZ height bands moves a label along the
    compact/open axis in whichever direction it errs, so counting one way would halve the signal
    this breakdown exists to measure."""
    predicted, reference, area = build([4, 1, 5, 9], [1, 4, 2, 3])

    report = agreement(predicted, reference, area)

    pairs = {(entry.compact, entry.open): entry for entry in report.height_axis}
    assert pairs[(1, 4)].n_compact_as_open == 1
    assert pairs[(1, 4)].n_open_as_compact == 1
    assert pairs[(1, 4)].n_total == 2
    assert pairs[(2, 5)].n_total == 1
    assert pairs[(3, 6)].n_total == 0
    # Three of the four disagreements sit on the height axis.
    assert pairs[(1, 4)].share_of_disagreement == pytest.approx(0.5)
    assert sum(entry.n_total for entry in report.height_axis) == 3


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
