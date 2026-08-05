"""Pure model tests for CleaningStep / CleaningReport — no geodata."""

from __future__ import annotations

from lczkit.cleaning.report import CleaningReport, CleaningStep


def test_cleaning_step_defaults() -> None:
    step = CleaningStep(stage="buildings", operation="drop_oversized", n_in=10, n_out=8)

    assert step.detail == {}


def test_cleaning_report_accumulates_steps() -> None:
    step1 = CleaningStep(stage="buildings", operation="drop_oversized", n_in=10, n_out=8)
    step2 = CleaningStep(stage="streets", operation="simplify_streets", n_in=20, n_out=15)

    report = CleaningReport(steps=[step1, step2])

    assert len(report.steps) == 2
    assert report.steps[0].stage == "buildings"
    assert report.steps[1].stage == "streets"


def test_cleaning_report_json_round_trip() -> None:
    report = CleaningReport(
        steps=[
            CleaningStep(
                stage="buildings",
                operation="drop_oversized",
                n_in=10,
                n_out=8,
                detail={"max_area_m2": 5000.0},
            )
        ]
    )

    restored = CleaningReport.model_validate_json(report.model_dump_json())

    assert restored == report
