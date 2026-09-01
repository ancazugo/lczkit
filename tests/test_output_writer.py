"""Writing a run: the two tables, the manifest, and the boundary they must not cross.

The assertions worth having here are about contracts rather than content: that nothing lands
outside `run_dir`, that the archival table keeps full precision while the viz table does not, and
that a column appearing twice is an error rather than a silent overwrite.
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
from lczkit.output import (
    GPKG_FILE,
    GPKG_LAYER,
    MANIFEST_FILE,
    UNITS_FILE,
    VIZ_FILE,
    viz_table,
    write_run,
)

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
    frame = pd.DataFrame(
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
            # The semantic evidence the shipped LCZ 8 rule reads. Zero, so the rule never fires
            # here — but present, because a real `compute_parameters` table carries these and the
            # classifier refuses one that does not.
            "sem_large_lowrise_buildings_of_building_area": np.zeros(n),
            "sem_lightweight_buildings_of_building_area": np.zeros(n),
        },
        index=units.index,
    )
    return frame


def run(settings: Settings, extras: pd.DataFrame | None = None):
    units = make_units()
    parameters = make_parameters(units)
    classifier = PrototypeClassifier()
    return (
        units,
        parameters,
        write_run(
            settings,
            units,
            parameters,
            classifier.classify(parameters),
            classifier,
            extras=extras,
        ),
    )


def test_a_run_writes_a_known_set_of_files_and_only_inside_its_own_directory(
    settings: Settings,
) -> None:
    """CLAUDE.md: never write outside `output/lczkit/<run_id>/`. `output/` is shared with other
    tools and `input/` with other projects, so this is the one that must not regress."""
    before = {path for path in settings.data_dir.rglob("*") if path.is_file()}

    _, _, outputs = run(settings)

    written = {path for path in settings.data_dir.rglob("*") if path.is_file()} - before
    assert {path.name for path in written} == {UNITS_FILE, VIZ_FILE, MANIFEST_FILE, GPKG_FILE}
    assert all(path.parent == settings.run_dir for path in written)
    assert outputs.run_dir == settings.run_dir
    assert not any(path.is_relative_to(settings.input_dir) for path in written)


def test_the_archival_table_is_geoparquet_at_full_precision(settings: Settings) -> None:
    units, parameters, outputs = run(settings)

    stored = gpd.read_parquet(outputs.units)

    assert isinstance(stored, gpd.GeoDataFrame)
    assert stored.crs == units.crs
    assert stored.index.equals(units.index)
    assert stored["mean_building_area_m2"].equals(parameters["mean_building_area_m2"])
    assert stored["lcz_primary"].notna().all()
    assert "lcz_d17" in stored.columns


def test_the_viz_table_drops_geometry_rounds_floats_and_scales_the_distances(
    settings: Settings,
) -> None:
    """Three significant figures and int16 distances: at full float64 the distance vector alone
    triples what a browser has to parse, and no sidebar reads past the third digit."""
    _, _, outputs = run(settings)

    stored = pd.read_parquet(outputs.units_viz)

    assert "geometry" not in stored.columns
    # 123.456789, 3374.4856, 6625.5144, 9876.54321 to three significant figures.
    assert stored["mean_building_area_m2"].to_list() == pytest.approx(
        [123.0, 3370.0, 6630.0, 9880.0]
    )
    assert stored["lcz_d1"].dtype == "Int16"
    assert stored["lcz_d1"].notna().all()


def test_the_scaled_distances_recover_the_originals_to_three_decimals(
    settings: Settings,
) -> None:
    _, parameters, outputs = run(settings)

    exact = PrototypeClassifier().classify(parameters)["lcz_d5"]
    stored = pd.read_parquet(outputs.units_viz)["lcz_d5"]

    assert (stored.astype("float64") / 1000.0).to_list() == pytest.approx(exact.to_list(), abs=5e-4)


def test_rounding_leaves_zeros_nulls_and_integers_alone(settings: Settings) -> None:
    """`log10(0)` is negative infinity and would take a zero to NaN; a null must stay null; an
    integer column is a count, not a measurement to round."""
    frame = pd.DataFrame(
        {"value": [0.0, np.nan, 0.00123456, 98765.4], "count": [1, 2, 3, 4]},
        index=pd.Index(list("abcd"), name="unit_id"),
    )

    result = viz_table(frame, Settings(data_dir=settings.data_dir))

    assert result["value"].to_list()[0] == 0.0
    assert np.isnan(result["value"].to_list()[1])
    assert result["value"].to_list()[2] == pytest.approx(0.00123)
    assert result["value"].to_list()[3] == pytest.approx(98800.0)
    assert result["count"].to_list() == [1, 2, 3, 4]


def test_the_manifest_is_valid_json_and_names_what_was_written(settings: Settings) -> None:
    _, _, outputs = run(settings)

    loaded = json.loads(outputs.manifest_path.read_text(encoding="utf-8"))

    assert loaded["run_id"] == "test-run"
    assert set(loaded["outputs"]) == {UNITS_FILE, VIZ_FILE, MANIFEST_FILE, GPKG_FILE}
    assert loaded["config"]["classification"]["weight_preset"] == "bernard2024_partial"


def test_the_manifest_records_the_crs_the_run_was_computed_in(settings: Settings) -> None:
    """The CRS comes from `estimate_utm_crs()` on the extent, so it is nowhere in `config` — and
    a run directory that cannot say what CRS it is in without a GeoParquet reader is unreadable
    by exactly the reader that needs to be told."""
    _, _, outputs = run(settings)

    loaded = json.loads(outputs.manifest_path.read_text(encoding="utf-8"))

    assert loaded["crs"] == CRS
    assert "UTM zone 33N" in loaded["crs_wkt"]
    assert CRS not in json.dumps(loaded["config"]), "config cannot carry a CRS it never chose"


def test_the_geopackage_carries_the_crs_as_an_authority_code_and_keeps_the_join_key(
    settings: Settings,
) -> None:
    """Why this file exists: GeoParquet is correct here, but its driver is optional in GDAL, so a
    GIS without it reports a valid file as having no CRS. A GeoPackage stores the CRS in a table
    rather than in metadata a driver must know how to parse."""
    units, _, outputs = run(settings)

    assert outputs.units_gpkg is not None
    stored = gpd.read_file(outputs.units_gpkg, layer=GPKG_LAYER)

    assert stored.crs.to_epsg() == 32633
    assert "unit_id" in stored.columns, "a GeoPackage has no index; unit_id must be a column"
    assert sorted(stored["unit_id"]) == sorted(units.index)
    archival = gpd.read_parquet(outputs.units)
    assert stored["lcz_primary"].to_list() == archival["lcz_primary"].to_list()


def test_the_geopackage_can_be_switched_off_and_the_manifest_stops_claiming_it(
    settings: Settings,
) -> None:
    settings.output.gis_format = "none"

    _, _, outputs = run(settings)

    assert outputs.units_gpkg is None
    assert not (settings.run_dir / GPKG_FILE).exists()
    assert GPKG_FILE not in outputs.manifest.outputs


def test_the_archival_geoparquet_still_carries_the_crs_in_its_own_metadata(
    settings: Settings,
) -> None:
    """The GeoPackage is a second copy, not a replacement. `units.parquet` stays the archival
    record and the site build still reads it, so its `geo` metadata must keep the EPSG code."""
    import pyarrow.parquet as pq

    _, _, outputs = run(settings)

    geo = json.loads(pq.read_schema(outputs.units).metadata[b"geo"])
    column = geo["columns"][geo["primary_column"]]

    assert column["crs"]["id"] == {"authority": "EPSG", "code": 32633}
    assert gpd.read_parquet(outputs.units).crs.to_epsg() == 32633


def test_breaks_cover_the_continuous_columns_and_skip_the_categorical_ones(
    settings: Settings,
) -> None:
    """The seventh decile of an LCZ code is not a class boundary, and the distance vector is drawn
    as a per-unit bar chart rather than a choropleth."""
    _, _, outputs = run(settings)

    columns = {entry.column for entry in outputs.manifest.breaks}

    assert "building_surface_fraction" in columns
    assert "uniqueness" in columns
    assert not columns & {"lcz_primary", "lcz_secondary", "lcz_d1", "lcz_d17"}
    assert all(entry.method == "quantile" for entry in outputs.manifest.breaks)


def test_the_manifest_summarises_what_the_classifier_did_to_this_city(
    settings: Settings,
) -> None:
    """The LCZ 10 firing count especially. A rule that never fires is indistinguishable, from the
    output alone, from one that was never configured — and on the Rotterdam fixture it never
    fires, so this count is how a reader of any run finds that out."""
    _, _, outputs = run(settings)

    summary = outputs.manifest.classification_summary

    assert summary["n_units"] == 4
    assert summary["n_unlabelled"] == 0
    assert sum(summary["labels"].values()) == 4
    assert sum(summary["label_route"].values()) == 4
    assert summary["lcz10_rule_applied"] == 0
    assert 0.0 <= summary["median_uniqueness"] <= 1.0


def test_extras_are_carried_through_to_both_tables(settings: Settings) -> None:
    units = make_units()
    extras = pd.DataFrame({"height_completeness": [1.0, 0.5, 0.0, np.nan]}, index=units.index)

    _, _, outputs = run(settings, extras=extras)

    assert "height_completeness" in gpd.read_parquet(outputs.units).columns
    assert "height_completeness" in pd.read_parquet(outputs.units_viz).columns


def test_a_column_supplied_twice_is_an_error_not_a_silent_overwrite(settings: Settings) -> None:
    units = make_units()
    parameters = make_parameters(units)
    classifier = PrototypeClassifier()

    with pytest.raises(ValueError, match="aspect_ratio"):
        write_run(
            settings,
            units,
            parameters,
            classifier.classify(parameters),
            classifier,
            extras=parameters[["aspect_ratio"]],
        )


def test_a_misaligned_index_is_refused(settings: Settings) -> None:
    units = make_units()
    parameters = make_parameters(units)
    classifier = PrototypeClassifier()

    with pytest.raises(ValueError, match="parameters index"):
        write_run(
            settings,
            units,
            parameters.iloc[:2],
            classifier.classify(parameters),
            classifier,
        )


def test_context_layers_land_under_layers_and_are_named_in_the_manifest(
    settings: Settings,
) -> None:
    """Phase 7's site is a pure transform of run outputs, so the geometry it draws has to be one of
    them. Without this the only way to render a basemap would be to re-read `input/` at site-build
    time, and an archived run directory could not rebuild its own map."""
    units = make_units()
    parameters = make_parameters(units)
    classifier = PrototypeClassifier()

    outputs = write_run(
        settings,
        units,
        parameters,
        classifier.classify(parameters),
        classifier,
        layers={"buildings": units.reset_index(), "streets": units.reset_index()},
    )

    assert set(outputs.layers) == {"streets", "buildings"}
    assert all(path.is_file() for path in outputs.layers.values())
    assert all(path.parent == settings.run_dir / "layers" for path in outputs.layers.values())
    assert "layers/streets.parquet" in outputs.manifest.outputs
    assert "layers/buildings.parquet" in outputs.manifest.outputs
    # Fixed order, not the caller's, so two runs of the same city produce the same manifest.
    assert list(outputs.layers) == ["streets", "buildings"]


def test_an_unknown_context_layer_is_refused_rather_than_written(settings: Settings) -> None:
    """`layers=` is a named set, not a free-form dump: a reader of a run directory should be able
    to tell what `layers/streets.parquet` contains without consulting the code that wrote it."""
    units = make_units()
    parameters = make_parameters(units)
    classifier = PrototypeClassifier()

    with pytest.raises(ValueError, match="scratch"):
        write_run(
            settings,
            units,
            parameters,
            classifier.classify(parameters),
            classifier,
            layers={"scratch": units.reset_index()},
        )


def test_a_run_without_context_layers_writes_no_layers_directory(settings: Settings) -> None:
    _, _, outputs = run(settings)

    assert outputs.layers == {}
    assert not (settings.run_dir / "layers").exists()
