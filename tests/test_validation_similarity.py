"""`OA_w` and the class-similarity matrix behind it.

The matrix has 289 cells and a wrong one is invisible — it would shift a number rather than raise —
so the first test here is the same one that keeps `prototypes.py` exact: the packaged constants are
asserted equal to the committed markdown, cell for cell.

The rest guard the direction. That file holds two matrices with identical headers, and reading the
wrong one inverts the measure silently: a perfect map would score 0.00 and every cross-city
comparison would rank backwards.
"""

from __future__ import annotations

import pytest
import reference_tables as rt

from lczkit.classify.labels import CODES, code_of
from lczkit.validation.agreement import ConfusionCell, weighted_agreement
from lczkit.validation.similarity import SIMILARITY


def cell(reference: str, predicted: str, n: int) -> ConfusionCell:
    return ConfusionCell(
        reference=code_of(reference), predicted=code_of(predicted), n=n, area_m2=10_000.0 * n
    )


def test_the_packaged_matrix_equals_the_committed_table_cell_for_cell() -> None:
    """CLAUDE.md's sharpest rule, applied to 289 numbers: a Tier 1 value is read from the committed
    table, never reproduced. There is no second copy to drift — this asserts the parse, not a
    transcription — but a table edited in a way the parser silently mis-reads would land here."""
    table = rt.lcz_similarity()

    assert len(table) == len(CODES) ** 2 == 289
    for (reference, predicted), value in table.items():
        assert SIMILARITY[(code_of(reference), code_of(predicted))] == value


def test_the_matrix_is_a_similarity_and_not_its_complement() -> None:
    """The one mistake that would not raise. Bechtel et al. define OA_w over the *similarity*
    matrix, in which a class is fully similar to itself; the same file carries the dissimilarity
    matrix, whose diagonal is zero. Substituting it makes a perfect map score 0.00."""
    assert all(SIMILARITY[(code, code)] == 1.0 for code in CODES)
    assert all(0.0 <= value <= 1.0 for value in SIMILARITY.values())
    # LCZ 1 against LCZ G is the extreme case: compact high-rise and water share nothing.
    assert SIMILARITY[(code_of("1"), code_of("G"))] == 0.0


def test_the_matrix_is_symmetric() -> None:
    """Confusing 1 for A costs what confusing A for 1 costs. The confusion list is directional, so
    if the paper's matrix were asymmetric the orientation would matter and this would fail."""
    asymmetric = [
        (i, j) for i in CODES for j in CODES if SIMILARITY[(i, j)] != SIMILARITY[(j, i)]
    ]

    assert asymmetric == []


def test_a_perfect_map_scores_one() -> None:
    confusion = [cell("2", "2", 60), cell("5", "5", 40)]

    assert weighted_agreement(confusion) == pytest.approx(1.0)


def test_oa_w_reduces_to_overall_accuracy_under_an_identity_matrix() -> None:
    """Not a property invented here. Bechtel et al. present OA_w as a *generalisation* of overall
    accuracy: plain OA is already the same sum weighted by ones on the diagonal and zeros off it.
    So the identity case is the definition's own consistency check."""
    identity = {(i, j): float(i == j) for i in CODES for j in CODES}
    confusion = [cell("2", "2", 30), cell("2", "5", 50), cell("1", "G", 20)]

    assert weighted_agreement(confusion, identity) == pytest.approx(0.3)


def test_a_near_miss_scores_better_than_a_cross_family_error() -> None:
    """The whole reason the metric exists. Overall accuracy scores both of these zero, which for a
    scheme whose classes lie on a continuum of built form is plainly wrong — and is why this module
    reports the two confusion axes apart in the first place."""
    adjacent = weighted_agreement([cell("1", "2", 100)])
    across = weighted_agreement([cell("1", "G", 100)])

    assert adjacent == pytest.approx(0.92)
    assert across == pytest.approx(0.0)
    assert adjacent > across


def test_oa_w_is_never_below_overall_accuracy() -> None:
    """A structural consequence of a diagonal of one and non-negative weights off it: OA_w gives at
    least full credit for what OA credits, plus partial credit for some of what OA does not. A run
    reporting OA_w below OA has read the wrong matrix."""
    confusion = [
        cell("2", "2", 40),
        cell("2", "5", 25),
        cell("5", "6", 15),
        cell("1", "G", 10),
        cell("8", "10", 10),
    ]
    total = sum(entry.n for entry in confusion)
    overall = sum(e.n for e in confusion if e.reference == e.predicted) / total

    assert weighted_agreement(confusion) >= overall


def test_an_empty_confusion_scores_zero_rather_than_dividing_by_nothing() -> None:
    assert weighted_agreement([]) == 0.0


def test_a_run_reports_it_beside_overall_accuracy_never_instead_of_it() -> None:
    """Both, always. OA_w is the comparable-to-the-literature figure; OA is the one every other
    LCZ paper's headline uses, and dropping it would make this package's numbers unreadable
    against anything published before 2020."""
    import pandas as pd

    from lczkit.validation import agreement

    index = pd.Index([f"u{i}" for i in range(4)], name="unit_id")
    report = agreement(
        pd.Series([2, 2, 5, 17], index=index, dtype="Int8"),
        pd.Series([2, 5, 5, 1], index=index, dtype="Int8"),
        pd.Series(10_000.0, index=index),
    )

    assert report.overall_agreement == pytest.approx(0.5)
    assert report.weighted_agreement > report.overall_agreement
    assert report.weighted_agreement < 1.0
