"""`dispersion_report` — the half of a height substitution that coverage does not describe.

Phase 10 rejected Open Buildings 2.5D for having too much within-unit spread. Nothing measured
whether the tiers that shipped have too little, and they do. These tests pin the instrument's
behaviour, not the finding: the finding lives in the module docstring with the cities it came from.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from lczkit.heights.dispersion import dispersion_report


def _units(**columns: list[float]) -> pd.DataFrame:
    return pd.DataFrame(columns, index=pd.Index([f"u{i}" for i in range(3)], name="unit_id"))


BASE = {
    "building_surface_fraction": [0.4, 0.4, 0.4],
    "building_count": [10.0, 10.0, 10.0],
    "h_mean_area_weighted": [10.0, 10.0, 10.0],
}


def test_a_unit_is_attributed_to_the_tier_that_supplied_most_of_its_building_area() -> None:
    """A simplification, and stated as one: the alternative mixes distributions."""
    frame = _units(
        **BASE,
        h_std=[3.0, 0.2, 0.1],
        height_frac_overture_height=[0.9, 0.1, 0.0],
        height_frac_wsf3d=[0.1, 0.9, 1.0],
    )

    report = dispersion_report(frame)

    by_source = {tier.source: tier for tier in report.tiers}
    assert by_source["overture_height"].n_units == 1
    assert by_source["wsf3d"].n_units == 2
    assert by_source["overture_height"].median_h_std == 3.0


def test_a_tier_that_hands_one_height_to_every_building_reports_it() -> None:
    """The measurement that matters: 23.6% of Bogota's GHSL units carry a single height."""
    frame = _units(
        **BASE,
        h_std=[0.0, 0.0, 2.0],
        height_frac_ghsl=[1.0, 1.0, 1.0],
    )

    report = dispersion_report(frame)

    assert report.tiers[0].source == "ghsl"
    assert report.tiers[0].constant_fraction == 2 / 3


def test_units_too_small_or_too_empty_to_describe_a_neighbourhood_are_excluded() -> None:
    """A spread over two buildings is a fact about two buildings, not about urban fabric.

    Both thresholds are recorded on the report rather than left implicit, since the medians are
    not comparable between two runs that filtered differently.
    """
    frame = _units(
        building_surface_fraction=[0.4, 0.001, 0.4],
        building_count=[10.0, 10.0, 2.0],
        h_mean_area_weighted=[10.0, 10.0, 10.0],
        h_std=[1.0, 5.0, 5.0],
        height_frac_wsf3d=[1.0, 1.0, 1.0],
    )

    report = dispersion_report(frame)

    assert report.n_units == 1
    assert report.tiers[0].median_h_std == 1.0
    assert report.min_building_surface_fraction == 0.05
    assert report.min_building_count == 3


def test_a_table_with_no_tier_fractions_reports_nothing_rather_than_raising() -> None:
    """A caller classifying a parameter table it assembled by hand has no provenance to group by,
    and the honest answer is an empty report rather than a refusal or an invented tier."""
    report = dispersion_report(_units(**BASE, h_std=[1.0, 1.0, 1.0]))

    assert report.n_units == 0
    assert report.tiers == []


def test_a_unit_with_no_mean_height_gives_a_null_cv_not_an_infinity() -> None:
    """`None` rather than a NaN, because a NaN is not valid JSON and the manifest is JSON."""
    frame = _units(
        **{**BASE, "h_mean_area_weighted": [0.0, 0.0, 0.0]},
        h_std=[1.0, 1.0, 1.0],
        height_frac_wsf3d=[1.0, 1.0, 1.0],
    )

    report = dispersion_report(frame)

    assert report.tiers[0].median_cv is None
    assert report.tiers[0].median_h_std == 1.0


def test_the_report_serialises_to_json_without_a_nan() -> None:
    frame = _units(**BASE, h_std=[1.0, np.nan, 2.0], height_frac_wsf3d=[1.0, 1.0, 1.0])

    dumped = dispersion_report(frame).model_dump_json()

    assert "NaN" not in dumped
