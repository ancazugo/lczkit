"""Phase 5 end to end on the fixture city, over both unit strategies.

Phases 1-4 each produce a table keyed on `unit_id`; this is the stage that consumes all of them at
once, so it is where the unit of exchange either holds together or does not. The assertions are on
shape, schema, index and the invariants CLAUDE.md names — not on particular parameter values,
which are properties of Berlin rather than of the code.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from conftest import (
    FIXTURE_CLEANING,
    FIXTURE_HEIGHTS,
    LANDCOVER_FIXTURES_DIR,
    SMALL_BBOX,
    FixtureVectorSource,
)

from lczkit.classify.classifier import PrototypeClassifier
from lczkit.cleaning.pipeline import CleanedVectors, clean_vectors
from lczkit.config import LandCoverConfig, UcpConfig
from lczkit.heights.cascade import cascade_height_sources, fill_heights
from lczkit.heights.completeness import height_metrics
from lczkit.heights.inherit import inherit_heights
from lczkit.heights.tiers import build_cascade
from lczkit.landcover.local import LocalRasterSource
from lczkit.ucp import PARAMETER_COLUMNS, compute_parameters
from lczkit.ucp.measure import COVERAGE_COLUMN, transfer_parameters
from lczkit.ucp.registry import spec
from lczkit.ucp.semantics import group_columns
from lczkit.units.enclosures import EnclosureUnits, assemble_barriers
from lczkit.units.grid import GridUnits

WORLDCOVER = LANDCOVER_FIXTURES_DIR / "worldcover_berlin.tif"

_LAND_COVER = LandCoverConfig()
_UCP = UcpConfig()

PARTITION = [
    "building_surface_fraction",
    "impervious_surface_fraction",
    "pervious_surface_fraction",
]


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


@pytest.fixture(scope="module")
def enclosure_units(
    cleaned: CleanedVectors, fixture_vector_source: FixtureVectorSource
) -> gpd.GeoDataFrame:
    rail = fixture_vector_source.rail(SMALL_BBOX).to_crs(cleaned.crs)
    barriers = assemble_barriers(cleaned.streets, cleaned.waterbodies, rail=rail)
    return EnclosureUnits().generate(SMALL_BBOX, barriers)


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
def enclosure_parameters(
    enclosure_units: gpd.GeoDataFrame, cleaned: CleanedVectors, buildings: gpd.GeoDataFrame
) -> pd.DataFrame:
    return parameters_for(enclosure_units, cleaned, buildings)


@pytest.fixture(scope="module")
def grid_parameters(
    grid_units: gpd.GeoDataFrame, cleaned: CleanedVectors, buildings: gpd.GeoDataFrame
) -> pd.DataFrame:
    return parameters_for(grid_units, cleaned, buildings)


def test_the_table_matches_the_registry_and_the_units_index(
    grid_parameters: pd.DataFrame, grid_units: gpd.GeoDataFrame
) -> None:
    """CLAUDE.md's acceptance criterion: a parameter table keyed by `unit_id` with every field
    documented. The registry lookup is what makes "documented" checkable at runtime."""
    assert tuple(grid_parameters.columns) == (
        *PARAMETER_COLUMNS,
        *group_columns(UcpConfig().semantic_groups),
    )
    assert grid_parameters.index.equals(grid_units.index)
    assert grid_parameters.index.name == "unit_id"
    groups = UcpConfig().semantic_groups
    assert all(spec(column, groups).unit for column in grid_parameters.columns)


def test_the_stewart_and_oke_fractions_partition_every_covered_unit(
    grid_parameters: pd.DataFrame,
) -> None:
    """Building, impervious and pervious sum to 1.0 wherever the land-cover raster reaches, which
    is what makes the unit comparable with Stewart & Oke's per-class ranges at all."""
    covered = grid_parameters[PARTITION].dropna()

    assert not covered.empty
    assert covered.sum(axis=1).to_numpy() == pytest.approx(1.0)


def test_central_berlin_reads_as_dense_and_impervious(grid_parameters: pd.DataFrame) -> None:
    """A sanity check on orientation, not on any particular number: this bbox is Mitte."""
    built = grid_parameters[grid_parameters["building_count"] > 0]

    assert built["building_surface_fraction"].mean() > 0.1
    assert grid_parameters["impervious_surface_fraction"].mean() > 0.5
    assert built["height_of_roughness_elements_m"].median() > 8.0


def test_hr_and_the_secondary_height_mean_differ_on_real_data(
    grid_parameters: pd.DataFrame,
) -> None:
    """The geometric and area-weighted means coincide only where a unit's buildings are uniform.
    On a real city they must not, or one of the two has quietly become the other — which is the
    exact substitution that would bias Phase 6 in heterogeneous units."""
    both = grid_parameters[["height_of_roughness_elements_m", "h_mean_area_weighted"]].dropna()

    assert not both.empty
    assert not both["height_of_roughness_elements_m"].equals(both["h_mean_area_weighted"])
    # And the spread is a real measurement, not a column of zeros from a single-building sample.
    assert grid_parameters["h_std"].max() > 0.0


def test_it_joins_onto_the_phase_3_and_phase_4_tables_with_no_spatial_work(
    grid_parameters: pd.DataFrame,
    grid_units: gpd.GeoDataFrame,
    buildings: gpd.GeoDataFrame,
) -> None:
    """The point of `unit_id` as the unit of exchange. Height provenance and land cover are
    computed independently of the parameters and have to land on the same index."""
    tiers = build_cascade(FIXTURE_HEIGHTS, lambda name: LANDCOVER_FIXTURES_DIR)
    heights = height_metrics(buildings, grid_units, cascade_height_sources(tiers))
    fractions = LocalRasterSource(_LAND_COVER.dataset("worldcover"), WORLDCOVER).fractions(
        grid_units
    )

    combined = grid_units.join(grid_parameters).join(heights).join(fractions)

    assert isinstance(combined, gpd.GeoDataFrame)
    assert combined.index.equals(grid_units.index)
    assert {"aspect_ratio", "height_completeness", "frac_impervious"} <= set(combined.columns)


def test_the_area_and_object_assignments_disagree_where_they_should(
    grid_parameters: pd.DataFrame,
) -> None:
    """On a 100 m grid a building routinely straddles a cell boundary, so the cell holding part of
    a footprint and the cell holding its representative point are not the same set. If these ever
    coincided exactly, one of the two assignment rules would have quietly become the other."""
    has_cover = grid_parameters["building_surface_fraction"] > 0
    has_count = grid_parameters["building_count"] > 0

    assert (has_cover & ~has_count).any()
    assert (has_count <= has_cover).all()


def test_enclosure_units_produce_the_same_schema(
    enclosure_units: gpd.GeoDataFrame, cleaned: CleanedVectors, buildings: gpd.GeoDataFrame
) -> None:
    """Phase 5 is indifferent to how the units were made — it needs a projected CRS and a `unit_id`
    index, which both strategies guarantee. Enclosures are the harder case: their boundaries *are*
    the streets, so the street metrics rely on a segment reaching both units it separates."""
    result = parameters_for(enclosure_units, cleaned, buildings)

    # `PARAMETER_COLUMNS` is the registry's static block; the Phase 18 semantic columns
    # follow it and their names come from the configured groups, so the assertion is that
    # the table *starts* with the registry in order and adds exactly the configured rest.
    assert tuple(result.columns) == (
        *PARAMETER_COLUMNS,
        *group_columns(UcpConfig().semantic_groups),
    )
    assert result.index.equals(enclosure_units.index)
    assert result["aspect_ratio"].notna().sum() > 0
    covered = result[PARTITION].dropna()
    assert covered.sum(axis=1).to_numpy() == pytest.approx(1.0)


def test_industrial_evidence_is_present_but_finds_almost_nothing_in_mitte(
    grid_parameters: pd.DataFrame,
) -> None:
    """Berlin Mitte holds 36 industrial buildings of 6195 and 2 industrial land-use parcels of
    1559, so this fixture exercises the plumbing and cannot exercise the rule. Asserting the
    smallness keeps that limitation visible rather than letting a future reader mistake a passing
    test for evidence that LCZ 10 discrimination works."""
    assert grid_parameters["industrial_fraction"].notna().all()
    assert grid_parameters["industrial_fraction"].max() < 0.1
    assert set(grid_parameters["industrial_evidence"]) <= {"none", "buildings"}


def test_measuring_on_enclosures_fills_the_aspect_ratio_a_grid_cell_cannot_have(
    grid_units: gpd.GeoDataFrame,
    enclosure_units: gpd.GeoDataFrame,
    grid_parameters: pd.DataFrame,
    enclosure_parameters: pd.DataFrame,
) -> None:
    """The measurement `UcpConfig.measure_on` exists for, on the fixture rather than on squares.

    A street canyon has to be measured against streets and a grid cell is not bounded by any, so
    `momepy.street_profile` reports nothing for a cell no street crosses. An enclosure is bounded
    *by* streets by construction. Transferring the enclosure measurement onto the grid should
    therefore leave fewer cells with no H/W at all than measuring on the grid directly — H/W being
    3 of the 17 applied weight units and the only dimension separating LCZ 8 from LCZ 3 and 6.

    An inequality rather than a figure: the size of the gap is a property of this 9 km² fixture,
    and the sixteen-city sweep that would make a claim about it has not been run.
    """
    transferred = transfer_parameters(enclosure_parameters, enclosure_units, grid_units)

    assert transferred.index.equals(grid_units.index)
    assert transferred["aspect_ratio"].isna().sum() < grid_parameters["aspect_ratio"].isna().sum()


def test_a_transferred_table_keeps_the_schema_the_registry_documents(
    grid_units: gpd.GeoDataFrame,
    enclosure_units: gpd.GeoDataFrame,
    enclosure_parameters: pd.DataFrame,
) -> None:
    """Every column survives the move, in order, plus the coverage the move itself introduces.

    The classifier selects dimensions by name, but the table is also written to disk against a
    registry that documents each column — so a transfer that quietly dropped one would produce a
    run whose parameters and whose manifest disagree.
    """
    transferred = transfer_parameters(enclosure_parameters, enclosure_units, grid_units)

    assert list(transferred.columns) == [*enclosure_parameters.columns, COVERAGE_COLUMN]
    assert set(PARAMETER_COLUMNS) <= set(transferred.columns)
    assert transferred["building_surface_fraction"].dropna().between(0.0, 1.0).all()


def test_a_transferred_table_still_classifies(
    grid_units: gpd.GeoDataFrame,
    enclosure_units: gpd.GeoDataFrame,
    enclosure_parameters: pd.DataFrame,
) -> None:
    """The point of the transfer is to be classified, so the seam is worth crossing once in a test
    rather than discovering at the end of a ten-minute run that a dtype did not survive."""
    transferred = transfer_parameters(enclosure_parameters, enclosure_units, grid_units)

    result = PrototypeClassifier().classify(transferred)

    assert result.index.equals(grid_units.index)
    assert result["lcz_primary"].notna().any()
