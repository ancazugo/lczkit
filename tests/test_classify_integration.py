"""Phase 6 end to end on the Berlin fixture: clean, classify, write, validate.

CLAUDE.md's acceptance criterion for this phase — "an end-to-end run on the fixture city produces
a valid GeoParquet, `units_viz.parquet` and manifest; validation module reports per-class
agreement against the global map". This is the test that runs every stage in sequence against real
data, so it is also the one that catches a contract broken between two phases.

Assertions are on shape, schema, index and the invariants CLAUDE.md names — not on which class a
particular Berlin block came out as, which is a property of Berlin and of the parameter estimates
rather than of the code. The synthetic tests are where "this unit is LCZ 2" is asserted.
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from conftest import (
    FIXTURE_CLEANING,
    FIXTURE_HEIGHTS,
    LANDCOVER_FIXTURES_DIR,
    LCZ_FIXTURES_DIR,
    SMALL_BBOX,
    FixtureVectorSource,
)

from lczkit.classify import CLASSIFICATION_COLUMNS, DISTANCE_COLUMNS, PrototypeClassifier
from lczkit.classify.labels import BUILT_CODES, NATURAL_CODES
from lczkit.classify.rules import ROUTES
from lczkit.cleaning.pipeline import CleanedVectors, clean_vectors
from lczkit.config import (
    LandCoverConfig,
    Settings,
    UcpConfig,
    ValidationConfig,
)
from lczkit.heights.cascade import cascade_height_sources, fill_heights
from lczkit.heights.completeness import height_metrics
from lczkit.heights.inherit import inherit_heights
from lczkit.heights.tiers import build_cascade
from lczkit.landcover.local import LocalRasterSource
from lczkit.output import GPKG_FILE, GPKG_LAYER, MANIFEST_FILE, UNITS_FILE, VIZ_FILE, write_run
from lczkit.ucp import PARAMETER_COLUMNS, compute_parameters
from lczkit.units.grid import GridUnits
from lczkit.validation import agreement, reference_lcz

WORLDCOVER = LANDCOVER_FIXTURES_DIR / "worldcover_berlin.tif"
REFERENCE = LCZ_FIXTURES_DIR / "lcz_reference_berlin.tif"

_LAND_COVER = LandCoverConfig()
_UCP = UcpConfig()
_VALIDATION = ValidationConfig()


@pytest.fixture(scope="module")
def cleaned(fixture_vector_source: FixtureVectorSource) -> CleanedVectors:
    return clean_vectors(fixture_vector_source, SMALL_BBOX, FIXTURE_CLEANING)


@pytest.fixture(scope="module")
def buildings(cleaned: CleanedVectors) -> gpd.GeoDataFrame:
    tiers = build_cascade(FIXTURE_HEIGHTS, lambda name: LANDCOVER_FIXTURES_DIR)
    filled, _ = fill_heights(cleaned.buildings_area, tiers)
    return filled


@pytest.fixture(scope="module")
def grid_units() -> gpd.GeoDataFrame:
    return GridUnits().generate(SMALL_BBOX)


def parameters_for(
    units: gpd.GeoDataFrame, cleaned: CleanedVectors, buildings: gpd.GeoDataFrame
) -> pd.DataFrame:
    land_cover = LocalRasterSource(_LAND_COVER.dataset("worldcover"), WORLDCOVER).fractions(units)
    return compute_parameters(
        units,
        buildings,
        inherit_heights(cleaned.buildings_topo, buildings),
        cleaned.streets,
        cleaned.land_use,
        land_cover,
        config=_UCP,
        land_cover_config=_LAND_COVER,
    )


@pytest.fixture(scope="module")
def grid_parameters(
    grid_units: gpd.GeoDataFrame, cleaned: CleanedVectors, buildings: gpd.GeoDataFrame
) -> pd.DataFrame:
    return parameters_for(grid_units, cleaned, buildings)


@pytest.fixture(scope="module")
def classified(grid_parameters: pd.DataFrame) -> pd.DataFrame:
    return PrototypeClassifier().classify(grid_parameters)


def test_every_unit_gets_a_label_and_a_full_distance_vector(
    classified: pd.DataFrame, grid_units: gpd.GeoDataFrame
) -> None:
    """No unit goes unclassified. `building_surface_fraction` is never null, so the gate always
    resolves and the denominator is never empty — which is what makes that guarantee possible."""
    assert tuple(classified.columns) == CLASSIFICATION_COLUMNS
    assert classified.index.equals(grid_units.index)
    assert classified["lcz_primary"].notna().all()
    assert classified[list(DISTANCE_COLUMNS)].notna().all(axis=1).all()
    assert set(classified["lcz_primary"]) <= set(BUILT_CODES) | set(NATURAL_CODES)


def test_units_with_a_missing_parameter_are_labelled_rather_than_dropped(
    classified: pd.DataFrame,
) -> None:
    """`aspect_ratio` is null wherever no street reaches a building — a small but nonzero share of
    real units, and the case CLAUDE.md's null policy exists for. They must appear in the output,
    on a comparable scale, with a record of what was missing."""
    incomplete = classified[classified["missing_parameters"] != ""]
    named = {name for row in incomplete["missing_parameters"] for name in row.split(",")}

    assert not incomplete.empty
    assert incomplete["lcz_primary"].notna().all()
    assert "aspect_ratio" in named
    # Only the weighted dimensions can be reported missing; under the default preset that is
    # three of the seven for a built unit, and both nullable ones are among them.
    assert named <= {"aspect_ratio", "height_of_roughness_elements_m", "building_surface_fraction"}
    assert incomplete["n_params_used"].min() >= 1


def test_the_gate_sends_built_and_open_units_to_different_families(
    classified: pd.DataFrame, grid_parameters: pd.DataFrame
) -> None:
    """Central Berlin has both, so both branches have to fire — a fixture where only one did would
    leave half the classifier untested while passing."""
    routes = set(classified["label_route"].dropna())

    assert {"distance_built", "distance_natural"} <= routes
    assert routes <= set(ROUTES)
    built = classified["label_route"] == "distance_built"
    assert (grid_parameters.loc[built, "building_surface_fraction"] >= 0.10).all()
    assert (grid_parameters.loc[~built, "building_surface_fraction"] < 0.10).all()


def test_the_cells_that_hold_buildings_read_as_built(
    classified: pd.DataFrame, grid_parameters: pd.DataFrame
) -> None:
    """Orientation, not accuracy: a run that labelled built-up Berlin as vegetation would pass
    every structural assertion above.

    Restricted to cells that actually contain a building, because `SMALL_BBOX` is the Spree-side
    open ground around the Marx-Engels-Forum — 55 buildings over ~0.4 km2, with half the grid
    holding none at all — so the share over the whole grid says more about which 600 m of Berlin
    the fixture picked than about the classifier. Over the full 3x3 km fixture extent, which is
    too slow for the suite to clean on every run, 76% of 964 cells come out built.
    """
    built = classified.loc[grid_parameters["building_count"] > 0, "lcz_primary"]

    assert len(built) > 15
    assert built.isin(BUILT_CODES).mean() > 0.6
    assert built.isin([1, 2, 3]).any()


def test_uniqueness_is_bounded_and_discriminating(classified: pd.DataFrame) -> None:
    """A column of zeros or ones would mean the measure is not measuring anything."""
    unique = classified["uniqueness"].dropna()

    assert not unique.empty
    assert unique.between(0.0, 1.0).all()
    assert unique.nunique() > 5


def test_lcz_10_does_not_appear_in_mitte(classified: pd.DataFrame) -> None:
    """The counterpart to the Rotterdam test. Mitte holds 36 industrial buildings of 6195, so the
    rule must not fire here — a classifier that emitted heavy industry across a historic city
    centre would be worse than one that never emitted it at all."""
    assert not classified["lcz10_rule_applied"].any()


def test_a_full_run_writes_its_three_files_and_a_validation_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    grid_units: gpd.GeoDataFrame,
    grid_parameters: pd.DataFrame,
    classified: pd.DataFrame,
    buildings: gpd.GeoDataFrame,
) -> None:
    """CLAUDE.md's acceptance criterion for Phase 6, in one test."""
    (tmp_path / "input").mkdir()
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings = Settings.load(run_id="berlin", dotenv_path=tmp_path / "absent.env")
    settings.overture.release = "2026-07-22.0"

    tiers = build_cascade(FIXTURE_HEIGHTS, lambda name: LANDCOVER_FIXTURES_DIR)
    heights = height_metrics(buildings, grid_units, cascade_height_sources(tiers))
    fractions = LocalRasterSource(_LAND_COVER.dataset("worldcover"), WORLDCOVER).fractions(
        grid_units
    )
    reference = reference_lcz(grid_units, REFERENCE, settings.validation.reference)

    report = agreement(
        classified["lcz_primary"],
        reference["reference_lcz"],
        grid_units.geometry.area,
        coverage=reference["reference_coverage"],
        height_completeness=heights["height_completeness"],
        config=settings.validation,
        reference_file=REFERENCE.name,
    )
    outputs = write_run(
        settings,
        grid_units,
        grid_parameters,
        classified,
        PrototypeClassifier(),
        extras=pd.concat([heights, fractions, reference], axis=1),
        validation=report,
    )

    assert {path.name for path in settings.run_dir.iterdir()} == {
        UNITS_FILE,
        VIZ_FILE,
        MANIFEST_FILE,
        GPKG_FILE,
    }

    stored = gpd.read_parquet(outputs.units)
    assert stored.index.equals(grid_units.index)
    assert set(PARAMETER_COLUMNS) <= set(stored.columns)
    assert {"height_completeness", "frac_impervious", "reference_lcz"} <= set(stored.columns)
    assert stored.crs == grid_units.crs

    # End to end, on a real extent: the derived UTM CRS survives into both spatial artefacts and
    # into the manifest, which is the only one of the three a reader without a GeoParquet driver
    # can open.
    assert outputs.units_gpkg is not None
    epsg = grid_units.crs.to_epsg()
    assert gpd.read_file(outputs.units_gpkg, layer=GPKG_LAYER).crs.to_epsg() == epsg
    assert outputs.manifest.crs == f"EPSG:{epsg}"

    viz = pd.read_parquet(outputs.units_viz)
    assert viz.index.equals(grid_units.index)
    assert "geometry" not in viz.columns
    assert viz["lcz_d1"].dtype == "Int16"

    manifest = json.loads(outputs.manifest_path.read_text(encoding="utf-8"))
    assert manifest["overture_release"] == "2026-07-22.0"
    assert manifest["validation"]["n_compared"] > 0
    assert manifest["breaks"]


def test_the_validation_report_is_per_class_and_stratified_not_a_single_number(
    grid_units: gpd.GeoDataFrame,
    classified: pd.DataFrame,
    buildings: gpd.GeoDataFrame,
) -> None:
    """CLAUDE.md: reported lczexplore-style, plus the two breakdowns that make the Phase 3 height
    caveat measurable. The agreement figure itself is not asserted — that is a property of Berlin
    and of a fixture too small to draw a conclusion from."""
    tiers = build_cascade(FIXTURE_HEIGHTS, lambda name: LANDCOVER_FIXTURES_DIR)
    heights = height_metrics(buildings, grid_units, cascade_height_sources(tiers))
    reference = reference_lcz(grid_units, REFERENCE, _VALIDATION.reference)

    report = agreement(
        classified["lcz_primary"],
        reference["reference_lcz"],
        grid_units.geometry.area,
        coverage=reference["reference_coverage"],
        height_completeness=heights["height_completeness"],
    )

    assert report.n_compared > 0
    assert report.per_class
    assert report.confusion
    assert len(report.height_axis) == 6
    assert len(report.compactness_axis) == 3
    assert len(report.by_height_completeness) == 10
    assert 0.0 <= report.overall_agreement <= 1.0
    assert sum(cell.n for cell in report.confusion) == report.n_compared
