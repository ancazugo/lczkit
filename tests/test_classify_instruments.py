"""The Phase 25 instruments over the prototype metric: what it shares, ties and prefers.

None of these change a label. They exist because three properties of the metric were true from
Phase 6 onwards and were readable only by someone who sat down with the prototype table: that a
height error moves two dimensions and not one, that a missing parameter makes specific class pairs
inseparable, and that the classes claim wildly different shares of the space before any city is
seen. A property nobody can see is a property nobody accounts for.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from lczkit.classify.classifier import PrototypeClassifier, _n_tied
from lczkit.classify.distance import PrototypeSpace
from lczkit.classify.labels import BUILT_CODES
from lczkit.classify.prototypes import HEIGHT_DEPENDENT_DIMENSIONS
from lczkit.classify.weights import BERNARD2024


def test_the_two_height_dependent_dimensions_are_named_and_only_those() -> None:
    """`aspect_ratio` is the one that does not look like a height, and it is the point.

    `momepy.street_profile(height=...)` puts the Phase 3 cascade in H/W's numerator, so the two
    dimensions move together. If a future dimension reads building height it must be declared
    here, and if this assertion is loosened the manifest figure silently stops meaning anything.
    """
    assert set(HEIGHT_DEPENDENT_DIMENSIONS) == {
        "aspect_ratio",
        "height_of_roughness_elements_m",
    }


def test_the_shared_height_weight_is_derived_from_the_active_preset() -> None:
    """9 of 17 on the shipped built weights — H/W's 3 plus Hr's 6 — and it follows the preset."""
    described = PrototypeClassifier().describe()["height_dependent_weight"]
    assert isinstance(described, dict)

    built = described["built"]
    assert isinstance(built, dict)
    assert (
        built["weight"]
        == BERNARD2024.built["aspect_ratio"] + (BERNARD2024.built["height_of_roughness_elements_m"])
    )
    assert built["total_weight"] == sum(BERNARD2024.built.values())
    assert built["fraction"] > 0.5, "over half the built metric moves with the height cascade"


def test_dropping_a_dimension_makes_more_class_pairs_inseparable() -> None:
    """And the pairs it creates are the confusion axes measured over sixteen cities.

    Losing `height_of_roughness_elements_m` ties {2,3} and {5,6} — compactness held fixed, height
    band varying, which is the height axis by definition. Losing `aspect_ratio` ties {3,8} and
    {6,8}. Both fall out of the prototype table's geometry with no city involved, which is why
    this test needs no fixture.
    """
    space = PrototypeSpace()
    selectable = [code for code in BUILT_CODES if code != 10]
    active = [column for column, weight in BERNARD2024.built.items() if weight > 0]

    everything = set(space.indistinguishable(selectable, active))
    without_height = set(
        space.indistinguishable(
            selectable, [c for c in active if c != "height_of_roughness_elements_m"]
        )
    )
    without_hw = set(
        space.indistinguishable(selectable, [c for c in active if c != "aspect_ratio"])
    )

    assert everything < without_height, "dropping a dimension cannot separate anything"
    assert everything < without_hw
    assert {(2, 3), (5, 6)} <= without_height
    assert {(3, 8), (6, 8)} <= without_hw


def test_the_full_dimension_set_leaves_the_built_classes_nearly_disjoint() -> None:
    """One overlapping pair, LCZ 3 with LCZ 7 — recorded because the intuition is the opposite.

    A metric built from overlapping published ranges looks like it should tie constantly. It does
    not, on the three dimensions that carry weight, which is *why* the missing-parameter case above
    is the interesting one rather than a footnote.
    """
    space = PrototypeSpace()
    active = [column for column, weight in BERNARD2024.built.items() if weight > 0]

    assert space.indistinguishable([code for code in BUILT_CODES if code != 10], active) == (
        (3, 7),
    )


def test_the_geometric_prior_is_very_uneven_and_says_what_space_it_measured() -> None:
    """LCZ 2 claims an order of magnitude more of the parameter space than LCZ 8 or 9.

    Not a defect — the classes are genuinely different sizes in UCP space — but it is a prior the
    output carries in silence, and per-class recall is not comparable across classes without it.
    The bounds travel with the shares because they set what "the space" means.
    """
    classifier = PrototypeClassifier()
    prior = classifier.describe()["geometric_prior"]
    assert isinstance(prior, dict)
    built = prior["built"]
    assert isinstance(built, dict)

    share = built["share"]
    assert isinstance(share, dict)
    assert set(share) == {str(code) for code in classifier.selectable_built}
    assert abs(sum(share.values()) - 1.0) < 1e-9
    assert set(built["bounds"]) == {
        "aspect_ratio",
        "building_surface_fraction",
        "height_of_roughness_elements_m",
    }
    assert share["2"] > 5 * share["8"], "the imbalance this instrument exists to report"


def test_the_prior_reproduces_across_calls() -> None:
    """A fixed seed, because a manifest that changes on every run is not a record."""
    first = PrototypeClassifier().describe()["geometric_prior"]
    second = PrototypeClassifier().describe()["geometric_prior"]

    assert first == second


def test_a_unit_inside_two_boxes_reports_the_tie_and_one_inside_none_does_not() -> None:
    """`n_tied_classes` counts classes at exactly the minimum, which is the arbitrary-label case.

    LCZ 3 and LCZ 7 overlap on all three weighted dimensions, so a unit placed in that overlap is
    at distance zero from both and the label falls to the ascending-code tie-break. A unit well
    away from every box has one nearest class and no tie, however far away it is — the distinction
    `uniqueness` cannot draw, since it only looks at the runner-up's distance.
    """
    frame = pd.DataFrame(
        {
            # In the LCZ 3 ∩ LCZ 7 overlap: H/W 1-1.5, BSF 0.6-0.7, Hr 3-4.
            "aspect_ratio": [1.2, 0.5],
            "building_surface_fraction": [0.65, 0.25],
            "height_of_roughness_elements_m": [3.5, 12.0],
            "impervious_surface_fraction": [0.2, 0.4],
            "pervious_surface_fraction": [0.15, 0.35],
            "tree_fraction": [0.0, 0.0],
            "water_fraction": [0.0, 0.0],
            "mean_building_area_m2": [np.nan, np.nan],
            "industrial_fraction_of_building_area": [0.0, 0.0],
            # The semantic evidence the shipped LCZ 8 rule reads. Zero, so the rule cannot fire and
            # move either unit off the tie the distance metric alone produces — but present, because
            # a real `compute_parameters` table carries these and the classifier refuses one that
            # does not.
            "sem_large_lowrise_buildings_of_building_area": [0.0, 0.0],
            "sem_lightweight_buildings_of_building_area": [0.0, 0.0],
        },
        index=pd.Index(["tied", "clear"], name="unit_id"),
    )

    result = PrototypeClassifier().classify(frame)

    assert result.loc["tied", "n_tied_classes"] == 2
    assert result.loc["tied", "uniqueness"] == 0.0
    assert result.loc["clear", "n_tied_classes"] == 1


def test_a_row_the_metric_could_not_score_reports_no_tie_rather_than_every_class() -> None:
    """An unscored row is unclassifiable, and "tied with all nine" would read as the opposite.

    Exercised on the candidate frame directly rather than through `classify()`, because it cannot
    be reached from there: `building_surface_fraction` is never null by contract — Phase 5 reports
    0.0 for a unit with no buildings — and it carries weight in both families, so every unit has at
    least one usable dimension. The guard is for a caller supplying its own weights.
    """
    candidates = pd.DataFrame(
        {2: [0.4, np.nan], 5: [0.4, np.nan], 6: [0.9, np.nan]},
        index=pd.Index(["tied", "unscored"], name="unit_id"),
    )

    tied = _n_tied(candidates)

    assert tied["tied"] == 2
    assert tied["unscored"] == 0
