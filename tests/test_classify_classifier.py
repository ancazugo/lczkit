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
    # Null rather than a value: the dimension ships at weight zero in every preset, so a value here
    # would assert nothing, and a null keeps these units unambiguous on the dimensions that do act.
    "mean_building_area_m2": np.nan,
    "industrial_fraction_of_building_area": 0.0,
    "industrial_fraction_of_unit_area": 0.0,
    "industrial_fraction": 0.0,
    # The semantic evidence the shipped LCZ 8 rule reads. Zero, so the rule never fires on a unit
    # built to be unambiguous on the morphological dimensions — but present, because a real
    # `compute_parameters` table carries these and the classifier refuses one that does not.
    "sem_large_lowrise_buildings_of_building_area": 0.0,
    "sem_lightweight_buildings_of_building_area": 0.0,
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
    # bernard2024_partial weights three of the five available dimensions; one is missing here.
    assert result.loc["u", "n_params_used"] == 2


def test_the_industrial_rule_relabels_and_records_what_it_displaced() -> None:
    """Functional assignment, not a swap between two classes the metric already liked.

    The unit here is morphologically nothing like heavy industry — the previous pair-gated rule
    would never have fired on it, which is exactly the Rotterdam failure: port plots are sparsely
    built, so building surface fraction places them on LCZ 9 and LCZ 10 never comes within reach of
    the argmin. The industrial evidence has to be able to override the morphology outright.
    """
    industrial = dict(
        building_surface_fraction=0.15,
        impervious_surface_fraction=0.25,
        pervious_surface_fraction=0.60,
        height_of_roughness_elements_m=8.0,
        aspect_ratio=0.15,
    )
    result = PrototypeClassifier().classify(
        units(
            plain=dict(**industrial, industrial_fraction_of_building_area=0.0),
            works=dict(**industrial, industrial_fraction_of_building_area=0.95),
        )
    )

    assert result.loc["plain", "lcz_primary"] != 10
    assert not result.loc["plain", "lcz10_rule_applied"]

    assert result.loc["works", "lcz_primary"] == 10
    assert result.loc["works", "lcz10_rule_applied"]
    assert result.loc["works", "label_route"] == ROUTE_INDUSTRIAL
    # The morphological answer is preserved rather than discarded, so the output says what would
    # have been emitted without the industrial evidence.
    assert result.loc["works", "lcz_secondary"] == result.loc["plain", "lcz_primary"]


def test_a_functionally_assigned_unit_reports_no_distance_to_the_class_it_was_given() -> None:
    """LCZ 10 is outside the metric, so no distance to it is defined. Reporting the displaced
    runner-up's distance under a column called `min_distance` would be a quiet lie about a label
    that was never measured by distance at all."""
    result = PrototypeClassifier().classify(
        units(
            works=dict(
                building_surface_fraction=0.15,
                height_of_roughness_elements_m=8.0,
                aspect_ratio=0.15,
                industrial_fraction_of_building_area=0.95,
            )
        )
    )

    assert result.loc["works", "lcz_primary"] == 10
    assert pd.isna(result.loc["works", "min_distance"])
    # `uniqueness` is a margin between the two nearest prototypes, so it is undefined for a label
    # the metric did not produce. Null, not 1.0 — reporting an unrivalled winner would claim the
    # distance vector agreed with the industrial evidence, which it was never asked.
    assert pd.isna(result.loc["works", "uniqueness"])
    # Still measured, still reported — CLAUDE.md requires the full seventeen-way vector.
    assert result["lcz_d10"].notna().all()


def test_lcz10_can_never_be_reached_by_the_distance_metric() -> None:
    """Bernard et al. (2024) remove it from the closest-distance approach, and the measurement
    behind following them is Rotterdam's: the morphological rule was inert at every threshold from
    0.05 to 0.5 over 671 cells of working port. A unit sitting exactly on the LCZ 10 prototype must
    still not be labelled 10 without the functional evidence."""
    result = PrototypeClassifier().classify(
        units(
            on_the_prototype=dict(
                building_surface_fraction=0.25,
                impervious_surface_fraction=0.30,
                pervious_surface_fraction=0.45,
                height_of_roughness_elements_m=10.0,
                aspect_ratio=0.35,
            )
        )
    )

    assert result.loc["on_the_prototype", "lcz_primary"] != 10
    assert result.loc["on_the_prototype", "lcz_secondary"] != 10


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

    # bernard2024_partial weights three of seven for a built unit; `equal` weights all
    # seven, including the two the built prototypes leave unconstrained — those add nothing to any
    # built distance but do enter every denominator, which is what "equal" means.
    assert bernard.loc["u", "n_params_used"] == 3
    assert equal.loc["u", "n_params_used"] == 7
    assert not bernard[list(DISTANCE_COLUMNS)].equals(equal[list(DISTANCE_COLUMNS)])


def test_describe_records_everything_needed_to_reproduce_a_label() -> None:
    described = PrototypeClassifier().describe()

    assert described["weight_preset"] == "bernard2024_partial"
    assert set(described["weights"]) == {"built", "natural"}
    assert described["thresholds"]["built_min_building_fraction"] == 0.10
    assert set(described["unreachable_classes"]) == {"10", "13", "16"}
    assert described["thresholds"]["lcz10_industrial_column"] == (
        "industrial_fraction_of_building_area"
    )
    assert any(entry["source"] == "lczkit" for entry in described["prototypes"])


def test_a_table_that_is_not_a_phase_5_parameter_table_is_refused() -> None:
    frame = units(u=dict(building_surface_fraction=0.5))

    with pytest.raises(ValueError, match="unit_id"):
        PrototypeClassifier().classify(frame.reset_index())
    with pytest.raises(ValueError, match="industrial_fraction"):
        PrototypeClassifier().classify(frame.drop(columns=["industrial_fraction_of_building_area"]))


def test_lcz_f_is_recorded_as_dominated_rather_than_merely_excluded() -> None:
    """The two exclusions are not the same kind of thing. C is a policy choice — it wins outright
    wherever aspect ratio and Hr are non-null. F's box is contained in D's in every dimension, so
    d(F) >= d(D) for any possible unit and ties break to the lower code: adding "F" back to
    `reachable_natural_classes` cannot make it assignable. A manifest that called both "excluded"
    would invite someone to try."""
    described = PrototypeClassifier().describe()
    unreachable = described["unreachable_classes"]

    assert "Dominated" in unreachable["16"]
    assert "arithmetic rather than by configuration" in unreachable["16"]
    assert "Excluded by configuration" in unreachable["13"]


def test_n_params_used_is_reported_against_the_scale_it_is_counted_on() -> None:
    """The maximum differs by family: under `bernard2024_partial` four of the seven dimensions are
    zero-weighted for built types and leave both sides of the renormalisation, so a built unit can
    reach 3 and a natural unit 7. One bare count silently mixed the two, and a built unit scoring
    3 of 3 read the same as a natural unit scoring 3 of 7."""
    result = PrototypeClassifier().classify(
        units(
            block=dict(
                building_surface_fraction=0.55,
                height_of_roughness_elements_m=18.0,
                aspect_ratio=1.2,
            ),
            park=dict(tree_fraction=0.85),
        )
    )
    built = result["label_route"] == ROUTE_BUILT

    assert set(result.loc[built, "n_params_available"]) == {3}
    assert set(result.loc[~built, "n_params_available"]) == {7}
    assert (result["n_params_used"] <= result["n_params_available"]).all()
