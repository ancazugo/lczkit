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

from lczkit.classify.labels import HEIGHT_AXIS_PAIRS
from lczkit.config import ValidationConfig
from lczkit.validation import agreement
from lczkit.validation.agreement import axis_summary


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


def test_the_axis_share_denominator_is_narrowed_to_references_that_could_reach_the_axis() -> None:
    """Only LCZ 1-6 can land on either axis, so a reference outside that band inflates the raw
    denominator while being unable to contribute to any numerator.

    Two of these four disagreements sit on an axis, but only three of the four have a reference
    that could have: the LCZ 9 unit is deadweight in the raw share and excluded from the narrowed
    one. This is half of why Phase 9's cross-city medians were not comparable - a city carrying a
    lot of water or scattered-build reference dilutes both axes without saying anything about
    either.
    """
    predicted, reference, area = build([3, 5, 1, 2], [2, 2, 4, 9])

    report = agreement(predicted, reference, area)
    height = report.height_axis_summary
    assert height is not None

    assert report.n_disagree == 4
    assert report.n_disagree_axis_eligible == 3
    # 2 -> 3 is a height error; 4 -> 1 is a compactness error; 9 -> 2 is on neither axis.
    assert height.n_total == 1
    assert height.share_of_disagreement == pytest.approx(0.25)
    assert height.share_of_axis_eligible == pytest.approx(1 / 3)


def test_lift_is_one_when_error_falls_exactly_where_class_composition_affords_it() -> None:
    """`lift` is what makes two cities comparable, and this pins its calibration.

    Every reference here is LCZ 2, whose height partners are 1 and 3 and whose compactness partner
    is 5. The run's wrong labels are one each of 1, 3 and 5, so two thirds of the error lands on
    the height axis and one third on compactness - which is exactly the proportion the reference
    affords, three partners split two to one. Both axes must therefore read 1.0 despite the height
    axis holding twice the raw share.
    """
    predicted, reference, area = build([1, 3, 5], [2, 2, 2])

    report = agreement(predicted, reference, area)
    height, compactness = report.height_axis_summary, report.compactness_axis_summary
    assert height is not None and compactness is not None

    assert height.share_of_disagreement == pytest.approx(2 / 3)
    assert compactness.share_of_disagreement == pytest.approx(1 / 3)
    assert height.lift == pytest.approx(1.0)
    assert compactness.lift == pytest.approx(1.0)


def test_a_two_class_reference_flatters_the_compactness_axis_until_lift_corrects_it() -> None:
    """The Berlin fixture's distortion, reduced to four units, and the reason for Phase 12.

    With only LCZ 2 and 5 in the reference the compactness pair has *both* members available to
    confuse, while each height pair can contribute only one direction. Here every disagreement
    lands on the compactness axis, which reads as a total footprint failure on the raw share; lift
    reports it as barely above what a two-class reference hands out for free.
    """
    predicted, reference, area = build([5, 5, 2, 2], [2, 2, 5, 5])

    report = agreement(predicted, reference, area)
    compactness = report.compactness_axis_summary
    assert compactness is not None

    assert compactness.share_of_disagreement == pytest.approx(1.0)
    assert compactness.expected_share == pytest.approx(1.0)
    assert compactness.lift == pytest.approx(1.0)


def test_axis_shares_carry_both_weightings_because_the_grid_hides_the_difference() -> None:
    """Every published axis figure is count-based, so that definition is kept and the
    area-weighted one is reported beside it rather than replacing it.

    On a regular grid the two coincide and the distinction is invisible - which is how it survived
    to Phase 11. On enclosures, where one unit can be a thousand times another, they do not.
    """
    predicted, reference, area = build([5, 3], [2, 2], area=[100.0, 9900.0])

    report = agreement(predicted, reference, area)

    pairs = {(entry.a, entry.b): entry for entry in report.compactness_axis}
    assert pairs[(2, 5)].share_of_disagreement == pytest.approx(0.5)
    assert pairs[(2, 5)].share_of_disagreement_area == pytest.approx(0.01)
    assert pairs[(2, 5)].area_m2 == pytest.approx(100.0)


def test_the_axis_summary_reads_the_same_confusion_matrix_a_run_persists() -> None:
    """What makes re-analysing a stored run legitimate rather than a second implementation.

    `axis_summary` takes the confusion list and nothing else, so a figure recomputed from an old
    manifest is the same computation the run performed, not a lookalike. Phase 12 rests on this:
    it re-reads sixteen cities from disk rather than spending 8.9 h re-running them.
    """
    predicted, reference, area = build([5, 3, 6, 2], [2, 2, 2, 5])

    report = agreement(predicted, reference, area)
    recomputed = axis_summary(report.confusion, HEIGHT_AXIS_PAIRS, axis="height")

    assert recomputed == report.height_axis_summary


def test_over_prediction_is_invisible_to_recall_and_visible_to_user_accuracy() -> None:
    """The reason both are reported. A classifier that calls everything LCZ 5 scores a perfect
    producer's accuracy on LCZ 5 — it found all of it — while being useless, and grouping by the
    reference alone is structurally unable to say so. Demuzere et al. (2021) report the pair
    through F1 for this reason."""
    predicted, reference, area = build([5, 5, 5, 5], [5, 2, 2, 2])

    report = agreement(predicted, reference, area)
    by_code = {entry.code: entry for entry in report.per_class}

    assert by_code[5].agreement == pytest.approx(1.0)  # found all of the one real LCZ 5
    assert by_code[5].user_accuracy == pytest.approx(0.25)  # and three false ones besides
    assert by_code[5].f1 == pytest.approx(2 * 1.0 * 0.25 / 1.25)
    assert by_code[2].agreement == pytest.approx(0.0)


def test_a_class_only_ever_predicted_still_gets_a_row() -> None:
    """Grouping by reference class alone would drop it, and a class the map invents wholesale is
    precisely what a reader needs to see."""
    predicted, reference, area = build([8, 8], [2, 2])

    report = agreement(predicted, reference, area)

    assert {entry.code for entry in report.per_class} == {2, 8}
    assert next(e for e in report.per_class if e.code == 8).n_reference == 0
    assert next(e for e in report.per_class if e.code == 8).user_accuracy == pytest.approx(0.0)


def test_built_versus_natural_accuracy_separates_two_different_failures() -> None:
    """OA_bu, per Demuzere et al. (2021) Sect. 2.4: "the overall accuracy of the built vs. natural
    LCZ classes only, ignoring their internal differentiation".

    Finding the built fabric and misjudging its form is a different failure from not finding it,
    and `overall_agreement` charges both the same. Here every unit is built and every label is
    wrong, so overall agreement is zero while the built/natural call is perfect."""
    predicted, reference, area = build([2, 3, 5], [1, 2, 6])

    report = agreement(predicted, reference, area)

    assert report.overall_agreement == pytest.approx(0.0)
    assert report.built_natural_agreement == pytest.approx(1.0)


def test_built_versus_natural_accuracy_falls_when_the_family_is_missed() -> None:
    predicted, reference, area = build([2, 12, 5, 5], [1, 2, 6, 6])

    report = agreement(predicted, reference, area)

    # One of four calls the wrong family — a built patch labelled scattered trees.
    assert report.built_natural_agreement == pytest.approx(0.75)
