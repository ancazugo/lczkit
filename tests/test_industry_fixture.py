"""The second fixture: Rotterdam's Waalhaven, and what it says about the LCZ 10 rule.

CLAUDE.md requires this fixture before the LCZ 8 / LCZ 10 rule can be claimed to work — "Synthetic
tests establish the mechanism; only a real fixture establishes that it discriminates." It does not
discriminate. That is the finding, and these tests record it rather than working around it.

`test_classify_rules.py` and `test_classify_classifier.py` show the rule firing correctly on units
built to sit between LCZ 8 and LCZ 10. This module shows that on 671 cells over a working
industrial port — 254 industrial buildings, 17 industrial parcels, and a reference map that puts
88 cells in LCZ 10 — **no unit has LCZ 8 and LCZ 10 as its two nearest prototypes**, at any
threshold, so the rule as specified never gets the chance to fire. A test asserting that LCZ 10
appears would have to weaken the fixture or the rule to pass; asserting the measurement keeps the
gap visible until it is decided what to do about it.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from conftest import (
    INDUSTRY_BBOX,
    INDUSTRY_FIXTURES_DIR,
    LANDCOVER_FIXTURES_DIR,
    LCZ_FIXTURES_DIR,
    FixtureVectorSource,
)

from lczkit.classify import PrototypeClassifier
from lczkit.cleaning.pipeline import CleanedVectors, clean_vectors
from lczkit.config import (
    ClassificationConfig,
    CleaningConfig,
    HeightConfig,
    LandCoverConfig,
    UcpConfig,
    ValidationConfig,
)
from lczkit.heights.cascade import fill_heights
from lczkit.heights.tiers import build_cascade
from lczkit.landcover.local import LocalRasterSource
from lczkit.ucp import compute_parameters
from lczkit.units.grid import GridUnits
from lczkit.validation import agreement, reference_lcz

WORLDCOVER = LANDCOVER_FIXTURES_DIR / "worldcover_rotterdam.tif"
REFERENCE = LCZ_FIXTURES_DIR / "lcz_reference_rotterdam.tif"

_CLEANING = CleaningConfig(
    building_max_area_m2=50_000.0,
    building_min_area_m2=20.0,
    building_merge_limit_m2=200.0,
    building_overlap_limit=0.1,
)
_HEIGHTS = HeightConfig(overture_height_confidence=0.9, overture_num_floors_confidence=0.6)
_LAND_COVER = LandCoverConfig()
_UCP = UcpConfig()
_VALIDATION = ValidationConfig()


@pytest.fixture(scope="module")
def source() -> FixtureVectorSource:
    return FixtureVectorSource(INDUSTRY_FIXTURES_DIR)


@pytest.fixture(scope="module")
def cleaned(source: FixtureVectorSource) -> CleanedVectors:
    return clean_vectors(source, INDUSTRY_BBOX, _CLEANING)


@pytest.fixture(scope="module")
def units() -> gpd.GeoDataFrame:
    return GridUnits().generate(INDUSTRY_BBOX)


@pytest.fixture(scope="module")
def parameters(cleaned: CleanedVectors, units: gpd.GeoDataFrame) -> pd.DataFrame:
    tiers = build_cascade(_HEIGHTS, lambda name: LANDCOVER_FIXTURES_DIR)
    buildings, _ = fill_heights(cleaned.buildings, tiers)
    land_cover = LocalRasterSource(_LAND_COVER.dataset("worldcover"), WORLDCOVER).fractions(units)
    return compute_parameters(
        units,
        buildings,
        cleaned.streets,
        cleaned.land_use,
        land_cover,
        config=_UCP,
        land_cover_config=_LAND_COVER,
    )


@pytest.fixture(scope="module")
def classified(parameters: pd.DataFrame) -> pd.DataFrame:
    return PrototypeClassifier().classify(parameters)


def test_the_fixture_carries_industrial_evidence_the_berlin_one_cannot(
    cleaned: CleanedVectors,
) -> None:
    """The reason this fixture exists. Berlin Mitte has 36 industrial buildings of 6195 and 2
    parcels of 1559; the Waalhaven has two orders of magnitude more of the first."""
    industrial_buildings = int((cleaned.buildings["class"] == "industrial").sum())
    industrial_parcels = int((cleaned.land_use["class"] == "industrial").sum())

    assert industrial_buildings > 200
    assert industrial_parcels > 10


def test_both_evidence_sources_reach_the_same_units(parameters: pd.DataFrame) -> None:
    """`industrial_fraction` is a union of building footprints and land-use parcels, so the case
    that matters is the one where both contribute to the same unit and must count once. Berlin
    never produces it; this fixture does."""
    evidence = parameters["industrial_evidence"].value_counts()

    assert evidence.get("both", 0) > 50
    assert evidence.get("land_use", 0) > 0
    assert evidence.get("buildings", 0) > 0
    combined = parameters["industrial_evidence"] == "both"
    assert (
        parameters.loc[combined, "industrial_fraction"]
        <= parameters.loc[combined, "industrial_fraction_buildings"]
        + parameters.loc[combined, "industrial_fraction_land_use"]
        + 1e-9
    ).all()


def test_the_port_is_overwhelmingly_industrial_by_area(parameters: pd.DataFrame) -> None:
    """Whatever the rule does with it, the input is unambiguous: over half these cells are more
    than 98% industrial land. If the rule cannot reach LCZ 10 here it cannot reach it anywhere."""
    assert parameters["industrial_fraction"].quantile(0.75) > 0.9


def test_no_unit_has_lcz_8_and_lcz_10_as_its_two_nearest_prototypes(
    classified: pd.DataFrame,
) -> None:
    """**The finding.** CLAUDE.md's rule fires "where a unit's nearest prototypes are 8 and 10".
    On a real industrial port that pair never occurs: the distance metric places these cells on
    LCZ 9 (sparsely built) and LCZ 4, because port plots are large and sparsely built and the
    building surface fraction that dominates the built metric comes out well below LCZ 8's 30-50%.

    So the rule as specified is inert, and the fixture CLAUDE.md required in order to establish
    that it discriminates establishes instead that it does not get the opportunity to. Asserted
    rather than worked around: this test failing in future means someone changed the rule or the
    metric, which is exactly when a reader should be told.
    """
    pair = classified.apply(
        lambda row: {row["lcz_primary"], row["lcz_secondary"]} == {8, 10}, axis=1
    )

    assert not pair.any()
    assert not classified["lcz10_rule_applied"].any()


def test_the_threshold_is_not_what_is_stopping_it(parameters: pd.DataFrame) -> None:
    """Lowering the threshold does not help, which is what distinguishes "set too conservatively"
    from "never reached". The conservative default is therefore not the thing to revisit."""
    firings = {
        threshold: int(
            PrototypeClassifier(ClassificationConfig(lcz10_min_industrial_fraction=threshold))
            .classify(parameters)["lcz10_rule_applied"]
            .sum()
        )
        for threshold in (0.05, 0.25, 0.5)
    }

    assert set(firings.values()) == {0}


def test_the_reference_map_does_put_heavy_industry_here(units: gpd.GeoDataFrame) -> None:
    """The target the rule is failing to hit. An independent map puts 88 of these cells in LCZ 10
    and 224 in LCZ 8 — so the gap is real rather than an artefact of the extent being wrong."""
    reference = reference_lcz(units, REFERENCE, _VALIDATION.reference)

    counts = reference["reference_lcz"].value_counts()
    assert counts.get(10, 0) > 50
    assert counts.get(8, 0) > 100


def test_agreement_is_reported_for_the_industrial_fixture_too(
    units: gpd.GeoDataFrame, classified: pd.DataFrame
) -> None:
    """Not an accuracy assertion — the agreement figure is a property of Rotterdam and of a
    prototype-distance classifier missing two of Stewart & Oke's seven properties. What is
    asserted is that the comparison runs and that LCZ 8 and 10 appear in the confusion matrix,
    so the gap above is measurable from a run's own output."""
    reference = reference_lcz(units, REFERENCE, _VALIDATION.reference)

    report = agreement(
        classified["lcz_primary"],
        reference["reference_lcz"],
        units.geometry.area,
        coverage=reference["reference_coverage"],
        config=_VALIDATION,
    )

    assert report.n_compared > 500
    assert 0.0 <= report.overall_agreement <= 1.0
    referenced = {cell.reference for cell in report.confusion}
    assert {8, 10} <= referenced
