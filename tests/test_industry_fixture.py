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
from lczkit.heights.inherit import inherit_heights
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
    building_road_buffer_m=4.0,
    building_road_overlap_limit=0.5,
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
    buildings, _ = fill_heights(cleaned.buildings_area, tiers)
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
def classified(parameters: pd.DataFrame) -> pd.DataFrame:
    return PrototypeClassifier().classify(parameters)


def test_the_fixture_carries_industrial_evidence_the_berlin_one_cannot(
    cleaned: CleanedVectors,
) -> None:
    """The reason this fixture exists. Berlin Mitte has 36 industrial buildings of 6195 and 2
    parcels of 1559; the Waalhaven has two orders of magnitude more of the first."""
    industrial_buildings = int((cleaned.buildings_area["class"] == "industrial").sum())
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


def test_the_metric_still_never_places_a_port_cell_near_lcz_10(
    classified: pd.DataFrame,
) -> None:
    """**The finding that retired the pair-gated rule, kept as a test.**

    The original rule fired "where a unit's nearest prototypes are 8 and 10". On a real industrial
    port that pair never occurs: the distance metric places these cells on LCZ 9 (sparsely built)
    and LCZ 4, because port plots are large and sparsely built and the building surface fraction
    that dominates the built metric comes out well below LCZ 8's 30-50%. The rule was inert here at
    every threshold, so the fixture that was meant to show it discriminating showed instead that it
    never got the opportunity.

    LCZ 10 is now outside the metric entirely, so the pair cannot occur by construction — but the
    underlying morphological fact is what justified that change, and it is worth keeping asserted.
    If these cells ever do start reading as LCZ 8, the reasoning behind the functional rule needs
    revisiting and this test is where a reader finds that out.
    """
    # LCZ 10 arrives only through the rule: it is never the argmin, so `lcz_primary == 10` and
    # "the rule fired" are the same set of cells.
    is_ten = (classified["lcz_primary"] == 10).fillna(False).to_numpy(dtype=bool)
    assert (is_ten == classified["lcz10_rule_applied"].to_numpy(dtype=bool)).all()

    # And the morphology, left to itself, does not put these cells on LCZ 8 either — which is what
    # made the pair-gated rule unreachable. Displaced answers are LCZ 9 and the natural classes.
    displaced = classified.loc[classified["lcz10_rule_applied"], "lcz_secondary"]
    assert (displaced == 8).mean() < 0.10  # measured 5.3%


def test_the_functional_rule_does_fire_where_the_pair_gated_one_could_not(
    classified: pd.DataFrame,
) -> None:
    """The point of the replacement. Assigned functionally, the port is found; gated on the
    morphology it never was."""
    fired = classified["lcz10_rule_applied"]

    # 95 cells, against a reference of 88 — the rate matches, which is what the threshold buys.
    assert fired.sum() > 50
    assert (classified.loc[fired, "lcz_primary"] == 10).all()
    # The displaced morphological answer is kept, and it is not LCZ 10 — that is the whole reason
    # the evidence had to override rather than break a tie.
    assert (classified.loc[fired, "lcz_secondary"] != 10).all()


def test_the_threshold_now_controls_how_much_of_the_port_is_labelled(
    parameters: pd.DataFrame,
) -> None:
    """It could not before: the pair-gated rule fired zero times at 0.05, 0.25 and 0.5 alike, which
    is what distinguished "set too conservatively" from "never reached".

    Note what the threshold does and does not buy. `scripts/lcz10_threshold_sweep.py` measures
    precision **flat at 24-27% across the whole range** against the Rotterdam reference, so this
    governs how much of the map carries LCZ 10 and not how often that label is right.
    """
    firings = {
        threshold: int(
            PrototypeClassifier(ClassificationConfig(lcz10_min_industrial_fraction=threshold))
            .classify(parameters)["lcz10_rule_applied"]
            .sum()
        )
        for threshold in (0.05, 0.5, 0.95)
    }

    assert firings[0.05] > firings[0.5] > firings[0.95] > 0


def test_the_building_area_share_keeps_real_spread_at_a_hundred_metre_cell(
    parameters: pd.DataFrame,
) -> None:
    """`FIND/B` survives the move from an RSU to a 100 m cell, and the *unit-area* share is the more
    saturated of the two.

    This test previously asserted the opposite, and the opposite was an artefact of how the
    numerator was built rather than a property of the quantity. Counting every building standing
    inside an industrial *parcel* as industrial made 84% of cells read exactly 1.0 — parcels are
    large and swallow whole cells — and that was read as `FIND/B` degenerating into a binary
    indicator. Counting industrial *buildings*, which is what `FIND/B` means, gives a median of
    0.66 and a tenth percentile of 0.11.

    Kept as a test because the failure mode is live: a numerator that mixes ground evidence into a
    building-area share will reproduce it, and it looks exactly like a scale finding.
    """
    built = parameters["industrial_fraction_of_building_area"]
    ground = parameters["industrial_fraction_of_unit_area"]

    present = built[built > 0]
    assert (present >= 0.999).mean() < 0.3
    assert 0.05 < present.quantile(0.1) < 0.5
    assert 0.4 < present.median() < 0.9

    # And the comparison that decides which column the rule reads.
    assert (ground[ground > 0] >= 0.999).mean() > (present >= 0.999).mean()


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
