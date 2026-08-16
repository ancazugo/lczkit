"""The run manifest — what it has to contain, and that it survives JSON.

CLAUDE.md accumulates manifest requirements across every phase: the full config, the pinned
Overture release, the GEE collection IDs and date ranges, resolved package versions, a run
timestamp, the cleaning report, the height source-availability diagnostic, the parameter registry
with units and references, the two deferred Stewart & Oke properties, and the Overture heavy/light
industry limitation — the last three required to be *data* rather than prose. Each of those is a
test here, because "it is in the docstring" satisfied none of them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from lczkit.classify import PrototypeClassifier
from lczkit.cleaning.report import CleaningReport, CleaningStep
from lczkit.config import ClassificationConfig, Settings
from lczkit.output.manifest import TRACKED_PACKAGES, build_manifest, package_versions
from lczkit.ucp.registry import LIMITATIONS, NOT_COMPUTED, PARAMETER_COLUMNS, semantic_specs
from lczkit.validation import agreement


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    (tmp_path / "input").mkdir()
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    loaded = Settings.load(run_id="test-run", dotenv_path=tmp_path / "absent.env")
    loaded.overture.release = "2026-07-22.0"
    return loaded


def test_the_manifest_round_trips_through_json(settings: Settings) -> None:
    manifest = build_manifest(settings, PrototypeClassifier())

    reloaded = json.loads(manifest.model_dump_json())

    assert reloaded["run_id"] == "test-run"
    assert reloaded["created_utc"].endswith("Z")


def test_the_config_is_serialised_verbatim(settings: Settings) -> None:
    """CLAUDE.md's wording. Every threshold in this package is config precisely so that this one
    field records the whole of what a run decided."""
    manifest = build_manifest(settings, PrototypeClassifier())

    assert manifest.config == settings.model_dump(mode="json")
    assert manifest.config["ucp"]["min_building_height_m"] == 0.1
    assert manifest.config["heights"]["storey_height_m"] == 3.0


def test_the_pinned_release_and_earth_engine_assets_are_recorded(settings: Settings) -> None:
    manifest = build_manifest(settings, PrototypeClassifier())

    assert manifest.overture_release == "2026-07-22.0"
    worldcover = manifest.earth_engine_assets["worldcover"]
    assert worldcover["collection_id"] == "ESA/WorldCover/v200"
    assert (worldcover["start_date"], worldcover["end_date"]) == ("2021-01-01", "2022-01-01")


def test_every_tracked_package_gets_a_version_or_an_explicit_absence() -> None:
    """ "Not installed" is itself a fact about the run — `earthengine-api` missing means the Earth
    Engine path could not have been used — so an absent package is recorded, not omitted."""
    versions = package_versions()

    assert set(versions) == set(TRACKED_PACKAGES)
    assert {"lczkit", "momepy", "neatnet", "geopandas"} <= set(versions)
    assert all(value for value in versions.values())


def test_the_parameter_registry_reaches_the_manifest_with_units_and_sources(
    settings: Settings,
) -> None:
    manifest = build_manifest(settings, PrototypeClassifier())

    named = {entry["name"]: entry for entry in manifest.parameters}
    # The registry's static block plus the Phase 18 semantic columns, whose names come from
    # the configured groups. Every one still has to arrive with a unit and a reference —
    # that is what this test is for, and it is why `semantic_specs` exists rather than a
    # static list the groups could outgrow.
    expected = {spec.name for spec in semantic_specs(settings.ucp.semantic_groups)}
    assert set(named) == set(PARAMETER_COLUMNS) | expected
    assert named["height_of_roughness_elements_m"]["unit"] == "m"
    assert all(entry["reference"] for entry in manifest.parameters)


def test_the_deferrals_and_limitations_reach_the_manifest_as_data(settings: Settings) -> None:
    """A consumer needs to know that two of Stewart & Oke's morphological properties are absent
    and that Overture cannot separate heavy from light industry. Neither is discoverable from a
    docstring by anything reading the output."""
    manifest = build_manifest(settings, PrototypeClassifier())

    assert manifest.not_computed == dict(NOT_COMPUTED)
    assert manifest.limitations == dict(LIMITATIONS)
    assert "warehouse" in manifest.limitations["industrial_fraction"]


def test_the_five_unused_prototype_properties_are_recorded_too(settings: Settings) -> None:
    """Wider than `not_computed`: sky view factor and terrain roughness are Phase 5 deferrals,
    while surface admittance, albedo and anthropogenic heat output are simply not derivable from
    the data this package ingests. Five of the published ten do not reach the metric."""
    manifest = build_manifest(settings, PrototypeClassifier())

    assert set(manifest.unused_lcz_properties) == {
        "sky_view_factor",
        "terrain_roughness_class",
        "surface_admittance",
        "surface_albedo",
        "anthropogenic_heat_output",
    }


def test_the_unapplied_bernard_weights_are_recorded_under_that_preset(settings: Settings) -> None:
    """4.5 of a published 21.5 total addresses properties lczkit does not compute. Anyone
    comparing an lczkit run against a GeoClimate one has to know the metric is not the same."""
    bernard = build_manifest(settings, PrototypeClassifier())
    equal = build_manifest(
        settings, PrototypeClassifier(ClassificationConfig(weight_preset="equal"))
    )

    assert {entry["property"] for entry in bernard.unapplied_weights} == {
        "sky_view_factor",
        "effective_terrain_roughness_length",
    }
    assert sum(entry["weight"] for entry in bernard.unapplied_weights) == pytest.approx(4.5)
    assert equal.unapplied_weights == []


def test_the_classification_block_carries_the_metric_and_the_thresholds(
    settings: Settings,
) -> None:
    manifest = build_manifest(settings, PrototypeClassifier())

    block = manifest.classification
    assert block["weights"]["built"]["building_surface_fraction"] == 8.0
    assert block["weights"]["built"]["impervious_surface_fraction"] == 0.0
    assert block["normalisation"]["height_of_roughness_elements_m"]["std"] > 0
    # Calibrated in Phase 14 by `scripts/lcz10_threshold_sweep.py`, not picked.
    assert block["thresholds"]["lcz10_min_industrial_fraction"] == 0.45
    assert block["thresholds"]["lcz10_industrial_column"] == (
        "industrial_fraction_of_building_area"
    )
    # 10 built classes x 5 published dimensions, plus 7 natural x 7 (the five published plus tree
    # and water), less the height range LCZ G does not have: 50 + 49 - 1.
    assert len(block["prototypes"]) == 98


def test_the_legend_travels_with_its_citation(settings: Settings) -> None:
    manifest = build_manifest(settings, PrototypeClassifier())

    assert manifest.legend["17"]["colour"] == "#6a6aff"
    assert manifest.legend_citation == "10.5194/essd-14-3835-2022"


def test_the_cleaning_report_is_embedded_when_there_is_one(settings: Settings) -> None:
    report = CleaningReport(
        steps=[CleaningStep(stage="buildings", operation="explode", n_in=10, n_out=12)]
    )

    manifest = build_manifest(settings, PrototypeClassifier(), cleaning=report)

    assert manifest.cleaning == report
    assert json.loads(manifest.model_dump_json())["cleaning"]["steps"][0]["n_out"] == 12


def test_the_two_references_and_the_ceiling_are_recorded_apart(settings: Settings) -> None:
    """Three separate fields, never one. `validation` is agreement against a model output,
    `validation_ground_truth` against hand-labelled polygons, and `reference_ceiling` is what the
    model output itself scores against those labels — the bound on the first. Collapsing any two
    of them is the mistake Phase 6.7 exists to undo.
    """
    index = pd.Index(["u0", "u1", "u2", "u3"], name="unit_id")
    area = pd.Series(10_000.0, index=index)
    truth = pd.Series([2, 2, 5, 5], index=index, dtype="Int8")
    comparator = pd.Series([2, 1, 5, 1], index=index, dtype="Int8")  # 50% right against `truth`
    run = pd.Series([2, 2, 2, 2], index=index, dtype="Int8")

    manifest = build_manifest(
        settings,
        PrototypeClassifier(),
        validation=agreement(run, comparator, area),
        validation_ground_truth=agreement(run, truth, area),
        reference_ceiling=agreement(comparator, truth, area),
    )

    assert manifest.reference_ceiling is not None
    assert manifest.reference_ceiling.overall_agreement == pytest.approx(0.5)
    assert manifest.validation_ground_truth is not None
    assert manifest.validation_ground_truth.overall_agreement == pytest.approx(0.5)
    assert manifest.validation is not None
    assert manifest.validation.overall_agreement == pytest.approx(0.25)

    restored = json.loads(manifest.model_dump_json())
    assert restored["reference_ceiling"]["overall_agreement"] == pytest.approx(0.5)
    assert restored["validation_ground_truth"]["built_agreement"] == pytest.approx(0.5)


def test_absent_stages_are_null_rather_than_fabricated(settings: Settings) -> None:
    """The stages are independently usable, so a run that classified a table it was handed has no
    cleaning report to record — and saying so is better than inventing an empty one."""
    manifest = build_manifest(settings, PrototypeClassifier())

    assert manifest.cleaning is None
    assert manifest.height_fill is None
    assert manifest.validation is None
    # A run against a city with no labelled coverage has no ceiling, and must not imply one.
    assert manifest.validation_ground_truth is None
    assert manifest.reference_ceiling is None
