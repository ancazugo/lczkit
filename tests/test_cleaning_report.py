"""The cleaning report's area accounting.

Counts alone are why a 23.5% loss of Berlin's footprint area survived from Phase 1 to Phase 6.5:
the two operations responsible removed 1177 and 439 features, and by count the second looks like
the smaller. By area it is 22.5% against 0.12%. These tests pin the arithmetic that makes that
visible.
"""

from __future__ import annotations

import pytest

from lczkit.cleaning.report import CleaningReport, CleaningStep, FootprintCoverage


def _step(operation: str, stage: str, area_in: float, area_out: float) -> CleaningStep:
    return CleaningStep(
        stage=stage,  # type: ignore[arg-type]
        operation=operation,
        n_in=10,
        n_out=10,
        area_in_m2=area_in,
        area_out_m2=area_out,
    )


def test_area_retained_is_the_share_of_area_a_step_passed_through() -> None:
    assert _step("drop", "buildings", 100.0, 77.0).area_retained == pytest.approx(0.77)


def test_a_step_over_a_layer_with_no_area_reports_none_rather_than_zero() -> None:
    """Waterlines have no footprint area. `None` says the question does not apply; 0.0 would say
    the step destroyed everything."""
    assert _step("drop_waterlines", "topology", 0.0, 0.0).area_retained is None


def test_retention_above_one_is_possible_and_is_not_an_error() -> None:
    """Trimming a self-overlapping footprint set removes double-counted area, so the step that
    *lowers* the measured total is the one making it correct. The inverse can happen when a
    reported total was inflated to begin with, and the model must not reject it."""
    assert _step("trim", "buildings_area", 90.0, 100.0).area_retained == pytest.approx(10 / 9)


def test_area_retention_is_end_to_end_across_a_stage_not_a_product_of_steps() -> None:
    """A stage's retention is its last step's output over its first step's input. Multiplying
    per-step ratios would give the same answer only if the steps chained exactly, and they do not
    once a stage is entered twice."""
    report = CleaningReport(
        steps=[
            _step("fix", "buildings", 100.0, 100.0),
            _step("trim", "buildings_area", 100.0, 99.0),
            _step("merge", "buildings_topo", 100.0, 96.0),
            _step("road", "buildings_topo", 96.0, 80.0),
        ]
    )

    assert report.area_retention("buildings_area") == pytest.approx(0.99)
    assert report.area_retention("buildings_topo") == pytest.approx(0.80)
    assert report.area_retention("buildings") == pytest.approx(1.0)


def test_a_stage_that_never_ran_has_no_retention_rather_than_a_default() -> None:
    assert CleaningReport().area_retention("buildings_area") is None
    assert (
        CleaningReport(steps=[_step("x", "topology", 0.0, 0.0)]).area_retention("topology") is None
    )


def test_stage_steps_preserves_the_order_operations_ran_in() -> None:
    report = CleaningReport(
        steps=[
            _step("first", "buildings_topo", 10.0, 9.0),
            _step("other", "buildings_area", 10.0, 10.0),
            _step("second", "buildings_topo", 9.0, 8.0),
        ]
    )

    assert [s.operation for s in report.stage_steps("buildings_topo")] == ["first", "second"]


def test_the_report_round_trips_through_json_with_its_areas() -> None:
    """It is copied verbatim into the run manifest, which is the artefact an auditor reads."""
    report = CleaningReport(steps=[_step("trim", "buildings_area", 100.0, 99.0)])

    restored = CleaningReport.model_validate_json(report.model_dump_json())

    assert restored.area_retention("buildings_area") == pytest.approx(0.99)


def test_the_acceptance_criterion_survives_serialisation() -> None:
    """`union_retention` is Phase 1's acceptance criterion and every headline ratio was a plain
    `@property`, so `model_dump()` and the JSON manifest carried only the four raw areas. Someone
    reading a run record saw four numbers and had to know the formula."""
    coverage = FootprintCoverage(
        raw_summed_area_m2=1000.0,
        raw_union_area_m2=900.0,
        area_summed_m2=891.0,
        area_union_m2=882.0,
    )

    dumped = coverage.model_dump()

    assert dumped["union_retention"] == pytest.approx(0.99)
    assert dumped["ground_retention"] == pytest.approx(0.98)
    assert dumped["raw_self_overlap_fraction"] == pytest.approx(0.1)
    assert dumped["residual_self_overlap_fraction"] == pytest.approx(1.0 - 882.0 / 891.0)
