"""`write_run`'s morphometrics support: a separate artefact, never joined to `units.parquet`.

Mirrors `test_output_writer.py`'s fixtures rather than importing them — the two files test
different contracts and a shared helper module would couple them for no benefit.
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from lczkit.classify import PrototypeClassifier
from lczkit.config import Settings
from lczkit.morphometrics.report import MorphometricsReport
from lczkit.output import MANIFEST_FILE, UNITS_FILE, write_run
from lczkit.output.writer import MORPHOMETRICS_FILE
from lczkit.units.tessellation import TessellationReport

CRS = "EPSG:32633"


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    (tmp_path / "input").mkdir()
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return Settings.load(run_id="test-run", dotenv_path=tmp_path / "absent.env")


def make_units(n: int = 4) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"unit_id": [f"grid_{index}" for index in range(n)]},
        geometry=[box(index * 100.0, 0.0, index * 100.0 + 100.0, 100.0) for index in range(n)],
        crs=CRS,
    ).set_index("unit_id")


def make_parameters(units: gpd.GeoDataFrame) -> pd.DataFrame:
    n = len(units)
    return pd.DataFrame(
        {
            "building_surface_fraction": np.linspace(0.0, 0.6, n),
            "impervious_surface_fraction": np.linspace(0.05, 0.4, n),
            "pervious_surface_fraction": np.linspace(0.95, 0.0, n),
            "tree_fraction": np.linspace(0.7, 0.0, n),
            "water_fraction": np.zeros(n),
            "height_of_roughness_elements_m": np.linspace(3.0, 20.0, n),
            "aspect_ratio": np.linspace(0.1, 1.4, n),
            "industrial_fraction_of_building_area": np.zeros(n),
            "industrial_fraction_of_unit_area": np.zeros(n),
            "industrial_fraction": np.zeros(n),
            "mean_building_area_m2": np.linspace(123.456789, 9876.54321, n),
            "sem_large_lowrise_buildings_of_building_area": np.zeros(n),
            "sem_lightweight_buildings_of_building_area": np.zeros(n),
        },
        index=units.index,
    )


def make_morphometrics(n: int = 3) -> gpd.GeoDataFrame:
    """A tiny ETC-shaped frame — a different index scheme and row count from `make_units`, on
    purpose: the two must never be assumed to line up."""
    return gpd.GeoDataFrame(
        {
            "unit_id": [f"etc_bld_{index}" for index in range(n)],
            "area_etc": np.linspace(50.0, 150.0, n),
        },
        geometry=[box(index * 10.0, 0.0, index * 10.0 + 10.0, 10.0) for index in range(n)],
        crs=CRS,
    ).set_index("unit_id")


def make_morphometrics_report(n: int = 3) -> MorphometricsReport:
    return MorphometricsReport(
        tessellation=TessellationReport(
            n_enclosures=1,
            n_buildings_in=n,
            n_etc=n,
            n_excluded_no_parent_building=0,
            etc_area_quantiles={"p10": 50.0, "p50": 100.0, "p90": 150.0},
        ),
        n_primary_attributes=107,
        contextual_enabled=False,
        n_contextual_attributes=0,
    )


def test_morphometrics_is_written_as_its_own_file_not_joined_to_units(settings: Settings) -> None:
    units = make_units()
    parameters = make_parameters(units)
    classifier = PrototypeClassifier()
    morphometrics = make_morphometrics()

    outputs = write_run(
        settings,
        units,
        parameters,
        classifier.classify(parameters),
        classifier,
        morphometrics=morphometrics,
        morphometrics_report=make_morphometrics_report(),
    )

    morphometrics_path = settings.run_dir / MORPHOMETRICS_FILE
    assert morphometrics_path.exists()
    written = gpd.read_parquet(morphometrics_path)
    assert list(written.index) == list(morphometrics.index)
    assert "area_etc" in written.columns

    # units.parquet must not have gained morphometrics columns or rows — it is a different unit
    # set entirely (grid cells here, ETCs there).
    written_units = gpd.read_parquet(settings.run_dir / UNITS_FILE)
    assert "area_etc" not in written_units.columns
    assert len(written_units) == len(units)
    assert outputs.morphometrics == morphometrics_path


def test_morphometrics_reaches_the_manifest_outputs_and_report(settings: Settings) -> None:
    units = make_units()
    parameters = make_parameters(units)
    classifier = PrototypeClassifier()

    outputs = write_run(
        settings,
        units,
        parameters,
        classifier.classify(parameters),
        classifier,
        morphometrics=make_morphometrics(),
        morphometrics_report=make_morphometrics_report(),
    )

    assert MORPHOMETRICS_FILE in outputs.manifest.outputs
    assert outputs.manifest.morphometrics is not None
    assert outputs.manifest.morphometrics.n_primary_attributes == 107

    manifest = json.loads((settings.run_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
    assert MORPHOMETRICS_FILE in manifest["outputs"]
    assert manifest["morphometrics"]["n_primary_attributes"] == 107
    # The morphometrics registry's own parameters reach the shared `parameters` list only when
    # the stage actually ran, per its own docstring.
    names = {p["name"] for p in manifest["parameters"]}
    assert "area_etc" in names


def test_a_run_with_no_morphometrics_writes_neither_file_nor_manifest_entry(
    settings: Settings,
) -> None:
    units = make_units()
    parameters = make_parameters(units)
    classifier = PrototypeClassifier()

    outputs = write_run(settings, units, parameters, classifier.classify(parameters), classifier)

    assert not (settings.run_dir / MORPHOMETRICS_FILE).exists()
    assert MORPHOMETRICS_FILE not in outputs.manifest.outputs
    assert outputs.manifest.morphometrics is None
    assert outputs.morphometrics is None
    names = {p["name"] for p in outputs.manifest.parameters}
    assert "area_etc" not in names
