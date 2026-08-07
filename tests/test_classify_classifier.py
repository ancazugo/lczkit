"""`PrototypeClassifier` end to end on synthetic units with known answers.

Synthetic rather than fixture-based on purpose: these assert *which class* a unit lands in, and
that is only a meaningful assertion when the unit was built to be unambiguously that class. The
Berlin and Rotterdam fixtures assert schema, shape and distributional sanity instead.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lczkit.classify import CLASSIFICATION_COLUMNS, DISTANCE_COLUMNS, PrototypeClassifier
from lczkit.classify.labels import BUILT_CODES, NATURAL_CODES, code_of
from lczkit.classify.rules import ROUTE_BUILT, ROUTE_INDUSTRIAL, ROUTE_NATURAL
from lczkit.config import ClassificationConfig

#: A unit that is unambiguously nothing in particular, so a test can move one dimension at a time.
BASE = {
    "building_surface_fraction": 0.0,
    "impervious_surface_fraction": 0.05,
    "pervious_surface_fraction": 0.95,
    "tree_fraction": 0.0,
    "water_fraction": 0.0,
    "height_of_roughness_elements_m": np.nan,
    "aspect_ratio": np.nan,
    "industrial_fraction": 0.0,
}


def units(**overrides: dict[str, float]) -> pd.DataFrame:
    frame = pd.DataFrame({name: {**BASE, **values} for name, values in overrides.items()}).T
    frame.index.name = "unit_id"
    return frame


def test_the_output_carries_the_full_seventeen_way_vector_and_every_label_column() -> None:
    """CLAUDE.md: never return a bare LCZ integer; carry the distance vector. Seventeen distances
    are reported even though only the gated family's are eligible to win."""
    result = PrototypeClassifier().classify(units(u=dict(building_surface_fraction=0.5)))

    assert tuple(result.columns) == CLASSIFICATION_COLUMNS
    assert len(DISTANCE_COLUMNS) == 17
    assert result[list(DISTANCE_COLUMNS)].notna().all(axis=1).all()
    assert result.index.name == "unit_id"


def test_a_dense_tall_block_reads_as_compact_and_a_park_as_vegetated() -> None:
    result = PrototypeClassifier().classify(
        units(
            block=dict(
                building_surface_fraction=0.55,
                impervious_surface_fraction=0.42,
                pervious_surface_fraction=0.03,
                height_of_roughness_elements_m=18.0,
                aspect_ratio=1.2,
            ),
            park=dict(tree_fraction=0.85, pervious_surface_fraction=0.95),
            lake=dict(water_fraction=0.9, pervious_surface_fraction=0.95),
        )
    )

    assert result.loc["block", "lcz_primary"] == code_of("2")
    assert result.loc["park", "lcz_primary"] == code_of("A")
    assert result.loc["lake", "lcz_primary"] == code_of("G")


def test_the_gate_decides_the_family_and_the_argmin_never_crosses_it() -> None:
    """The two families are scored under different weight vectors, so comparing across them would
    be comparing two metrics. The gate, not the argmin, chooses which one applies."""
    result = PrototypeClassifier().classify(
        units(
            sparse=dict(building_surface_fraction=0.09),
            built=dict(building_surface_fraction=0.11),
        )
    )

    assert result.loc["sparse", "lcz_primary"] in NATURAL_CODES
    assert result.loc["sparse", "label_route"] == ROUTE_NATURAL
    assert result.loc["built", "lcz_primary"] in BUILT_CODES
    assert result.loc["built", "label_route"] == ROUTE_BUILT


def test_the_unreachable_classes_are_never_assigned_but_are_still_measured() -> None:
    """C and F are indistinguishable from D with the parameters this package computes. Excluding
    them from selection avoids a tie resolved by index order; reporting their distances anyway
    keeps the vector complete and lets a future land-cover mapping make them reachable."""
    classifier = PrototypeClassifier()
    result = classifier.classify(
        units(
            **{
                f"u{index}": dict(pervious_surface_fraction=0.90 + index / 100)
                for index in range(8)
            }
        )
    )

    assert classifier.unreachable_natural == (code_of("C"), code_of("F"))
    assert not set(result["lcz_primary"].dropna()) & set(classifier.unreachable_natural)
    for code in classifier.unreachable_natural:
        assert result[f"lcz_d{code}"].notna().all()


def test_a_null_aspect_ratio_is_still_classified_and_says_what_was_missing() -> None:
    """CLAUDE.md's null policy in one assertion: no imputation, no dropping, and a record of which
    parameters were absent so the label can be read with the right amount of trust."""
    result = PrototypeClassifier().classify(
        units(
            u=dict(
                building_surface_fraction=0.45,
                impervious_surface_fraction=0.5,
                pervious_surface_fraction=0.05,
                height_of_roughness_elements_m=15.0,
                aspect_ratio=np.nan,
            )
        )
    )

    assert result.loc["u", "lcz_primary"] in BUILT_CODES
    assert result.loc["u", "missing_parameters"] == "aspect_ratio"
    # bernard2024 weights three of the five available dimensions; one of them is missing here.
    assert result.loc["u", "n_params_used"] == 2


def test_the_industrial_rule_relabels_and_records_that_it_did() -> None:
    """Built to sit between LCZ 8 and LCZ 10 rather than measured from a city: the point is that
    the rule fires on the pair it is meant to, and that the output says so."""
    industrial = dict(
        building_surface_fraction=0.30,
        impervious_surface_fraction=0.45,
        pervious_surface_fraction=0.25,
        height_of_roughness_elements_m=9.0,
        aspect_ratio=0.25,
    )
    result = PrototypeClassifier().classify(
        units(
            plain=dict(**industrial, industrial_fraction=0.0),
            works=dict(**industrial, industrial_fraction=0.95),
        )
    )

    pair = {result.loc["plain", "lcz_primary"], result.loc["plain", "lcz_secondary"]}
    assert pair == {8, 10}, "the fixture unit must sit between 8 and 10 for this to test anything"
    assert not result.loc["plain", "lcz10_rule_applied"]
    assert result.loc["works", "lcz_primary"] == 10
    assert result.loc["works", "lcz_secondary"] == 8
    assert result.loc["works", "lcz10_rule_applied"]
    assert result.loc["works", "label_route"] == ROUTE_INDUSTRIAL


def test_the_weight_preset_changes_the_answer() -> None:
    """If it did not, the preset would be decoration. Bernard's zero weights on the impervious and
    pervious fractions are the whole reason a second preset exists."""
    contested = units(
        u=dict(
            building_surface_fraction=0.35,
            impervious_surface_fraction=0.20,
            pervious_surface_fraction=0.45,
            height_of_roughness_elements_m=7.0,
            aspect_ratio=0.4,
        )
    )

    bernard = PrototypeClassifier().classify(contested)
    equal = PrototypeClassifier(ClassificationConfig(weight_preset="equal")).classify(contested)

    # bernard2024 weights three of the seven dimensions for a built unit; `equal` weights all
    # seven, including the two the built prototypes leave unconstrained — those add nothing to any
    # built distance but do enter every denominator, which is what "equal" means.
    assert bernard.loc["u", "n_params_used"] == 3
    assert equal.loc["u", "n_params_used"] == 7
    assert not bernard[list(DISTANCE_COLUMNS)].equals(equal[list(DISTANCE_COLUMNS)])


def test_describe_records_everything_needed_to_reproduce_a_label() -> None:
    described = PrototypeClassifier().describe()

    assert described["weight_preset"] == "bernard2024"
    assert set(described["weights"]) == {"built", "natural"}
    assert described["thresholds"]["built_min_building_fraction"] == 0.10
    assert set(described["unreachable_classes"]) == {"13", "16"}
    assert any(entry["source"] == "lczkit" for entry in described["prototypes"])


def test_a_table_that_is_not_a_phase_5_parameter_table_is_refused() -> None:
    frame = units(u=dict(building_surface_fraction=0.5))

    with pytest.raises(ValueError, match="unit_id"):
        PrototypeClassifier().classify(frame.reset_index())
    with pytest.raises(ValueError, match="industrial_fraction"):
        PrototypeClassifier().classify(frame.drop(columns=["industrial_fraction"]))
