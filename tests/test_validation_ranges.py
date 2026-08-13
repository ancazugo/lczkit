"""`parameter_ranges` — where a computed parameter sits against its published range.

Hand-built inputs throughout: the point of this instrument is an exact area-weighted share, and an
exact share is only assertable against numbers chosen to produce one.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lczkit.validation.ranges import parameter_ranges, weighted_quantile


def frame(values: list[float], labels: list[int], areas: list[float] | None = None):
    index = pd.Index([f"grid_{i}" for i in range(len(values))], name="unit_id")
    return (
        pd.Series(values, index=index, dtype="float64"),
        pd.Series(labels, index=index, dtype="Int8"),
        pd.Series(areas or [10_000.0] * len(values), index=index, dtype="float64"),
    )


def test_share_in_range_is_the_area_share_inside_the_published_interval() -> None:
    """LCZ 2's published building surface fraction is 40-70%. Two of these four units are inside
    it, and they carry three quarters of the area — so counting units and weighting by area give
    different answers, and the area-weighted one is what is reported."""
    values, labels, areas = frame(
        [0.10, 0.45, 0.60, 0.90], [2, 2, 2, 2], [1_000.0, 4_000.0, 5_000.0, 2_000.0]
    )

    report = parameter_ranges(values, labels, areas, column="building_surface_fraction")

    (entry,) = report.per_class
    # The table transcribes percentages; the conversion to a fraction is a float multiply, so the
    # bound is 0.7000000000000001 rather than 0.7 and comparing it exactly would be comparing
    # against the arithmetic rather than against the published value.
    assert entry.published_min == pytest.approx(0.40)
    assert entry.published_max == pytest.approx(0.70)
    assert entry.share_in_range == pytest.approx(9_000 / 12_000)
    assert entry.n == 4
    assert entry.area_m2 == pytest.approx(12_000.0)


def test_an_open_ended_bound_can_never_be_fallen_outside() -> None:
    """LCZ 9's aspect ratio is 0.1-0.25, but LCZ 1's is `2` with no upper bound. A unit at 50 is
    inside it — an unconstrained end is an unbounded interval, not a missing value, which is the
    same convention the distance metric uses."""
    values, labels, areas = frame([50.0, 0.01], [1, 1])

    report = parameter_ranges(values, labels, areas, column="aspect_ratio")

    (entry,) = report.per_class
    assert (entry.published_min, entry.published_max) == (2.0, None)
    assert entry.share_in_range == pytest.approx(0.5)


def test_the_median_is_area_weighted_and_is_a_value_some_unit_actually_has() -> None:
    """A tiny unit must not move the median the way an equal-count median lets it. Enclosures make
    this load-bearing: 78% of Berlin's are street-margin slivers holding 4% of the area."""
    values, labels, areas = frame(
        [0.05, 0.05, 0.05, 0.50], [5, 5, 5, 5], [1.0, 1.0, 1.0, 100_000.0]
    )

    report = parameter_ranges(values, labels, areas, column="building_surface_fraction")

    (entry,) = report.per_class
    assert entry.median == pytest.approx(0.50)
    assert entry.median in set(values)


def test_classes_are_reported_only_where_units_exist_and_carry_their_names() -> None:
    values, labels, areas = frame([0.5, 0.25, 0.0], [2, 5, 17])

    report = parameter_ranges(values, labels, areas, column="building_surface_fraction")

    assert [entry.code for entry in report.per_class] == [2, 5, 17]
    assert [entry.label for entry in report.per_class] == ["2", "5", "G"]
    assert report.per_class[2].name == "Water"
    assert report.n_units == 3


def test_a_class_with_no_published_range_in_this_dimension_is_unbounded_not_missing() -> None:
    """LCZ G carries no height range at all in the published table. Reported with both ends open
    and a share of 1.0 — the honest reading, and the one the classifier already uses."""
    values, labels, areas = frame([0.0, 40.0], [17, 17])

    report = parameter_ranges(values, labels, areas, column="height_of_roughness_elements_m")

    (entry,) = report.per_class
    assert (entry.published_min, entry.published_max) == (None, None)
    assert entry.share_in_range == pytest.approx(1.0)


def test_nulls_are_excluded_rather_than_counted_as_outside() -> None:
    """A unit the reference map does not reach says nothing about whether the parameter can
    reach a range, and scoring it as a miss would understate the parameter."""
    values, labels, areas = frame([0.45, np.nan, 0.45], [2, 2, 2])
    labels.iloc[2] = pd.NA

    report = parameter_ranges(values, labels, areas, column="building_surface_fraction")

    (entry,) = report.per_class
    assert entry.n == 1
    assert report.n_units == 1
    assert entry.share_in_range == pytest.approx(1.0)


def test_the_provenance_of_the_range_travels_with_the_numbers() -> None:
    """Testing a measurement against a range lczkit invented proves nothing about the measurement,
    so a reader has to be able to tell the two apart without leaving the report."""
    values, labels, areas = frame([0.5], [11])

    published = parameter_ranges(values, labels, areas, column="building_surface_fraction")
    ours = parameter_ranges(values, labels, areas, column="tree_fraction")

    assert published.source == "10.1175/BAMS-D-11-00019.1"
    assert ours.source == "lczkit"


def test_grouped_by_is_recorded_because_the_two_groupings_answer_opposite_questions() -> None:
    values, labels, areas = frame([0.3], [2])

    assert parameter_ranges(values, labels, areas, column="aspect_ratio").grouped_by == "reference"
    assert (
        parameter_ranges(
            values, labels, areas, column="aspect_ratio", grouped_by="assigned"
        ).grouped_by
        == "assigned"
    )


def test_an_unknown_column_is_refused_rather_than_silently_unbounded() -> None:
    values, labels, areas = frame([1.0], [2])

    with pytest.raises(KeyError, match="street_width_m"):
        parameter_ranges(values, labels, areas, column="street_width_m")


def test_weighted_quantile_on_empty_and_zero_weight_input() -> None:
    assert weighted_quantile(np.array([]), np.array([]), 0.5) is None
    assert weighted_quantile(np.array([1.0, 3.0]), np.zeros(2), 0.5) == pytest.approx(2.0)


def test_the_reference_file_travels_with_the_numbers() -> None:
    """Phase 13: a `RangeReport` that does not name its reference cannot be compared with another
    one, and the caller grouped by `lcz_v3` undetected for four phases because of it."""
    values, labels, areas = frame([0.45, 0.55], [2, 2])

    report = parameter_ranges(
        values,
        labels,
        areas,
        column="building_surface_fraction",
        grouped_by="ground_truth",
        reference_file="so2sat_berlin.parquet",
    )

    assert report.grouped_by == "ground_truth"
    assert report.reference_file == "so2sat_berlin.parquet"
    # Absent by default, so a caller that names nothing is visibly nameless rather than
    # silently inheriting whatever the previous one used.
    assert parameter_ranges(values, labels, areas, column="aspect_ratio").reference_file is None


def test_two_references_over_the_same_units_give_two_different_reports() -> None:
    """The failure Phase 13 found, in miniature: identical parameter values, two references
    disagreeing about which class each unit belongs to, and therefore two different answers to
    "does BSF reach its published range". Both are labelled `reference`-shaped groupings, so
    nothing but `reference_file` distinguishes them."""
    index = pd.Index([f"grid_{i}" for i in range(4)], name="unit_id")
    values = pd.Series([0.45, 0.45, 0.10, 0.10], index=index, dtype="float64")
    areas = pd.Series([10_000.0] * 4, index=index, dtype="float64")
    # The labels call the high-BSF pair compact midrise; the comparator calls the low-BSF pair so.
    truth = pd.Series([2, 2, 6, 6], index=index, dtype="Int8")
    comparator = pd.Series([6, 6, 2, 2], index=index, dtype="Int8")

    by_truth = parameter_ranges(
        values,
        truth,
        areas,
        column="building_surface_fraction",
        grouped_by="ground_truth",
        reference_file="so2sat.parquet",
    )
    by_comparator = parameter_ranges(
        values,
        comparator,
        areas,
        column="building_surface_fraction",
        grouped_by="reference",
        reference_file="lcz_v3.tif",
    )

    lcz2_truth = next(e for e in by_truth.per_class if e.code == 2)
    lcz2_comparator = next(e for e in by_comparator.per_class if e.code == 2)

    # Same values, same units, same class, opposite verdicts on whether the range is reached.
    assert lcz2_truth.share_in_range == pytest.approx(1.0)
    assert lcz2_comparator.share_in_range == pytest.approx(0.0)
    assert by_truth.reference_file != by_comparator.reference_file
