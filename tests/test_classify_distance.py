"""The distance metric against hand-built prototypes with arithmetic done by hand.

A synthetic two-dimensional prototype space is used for most of these rather than the real
seventeen-class one: the whole point is that every expected number is computable on paper, and the
normalisation over the real table's several hundred boundary values is not.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lczkit.classify.distance import PrototypeSpace, normalisation, uniqueness
from lczkit.classify.prototypes import PROTOTYPES, PrototypeRange

#: Two classes over one dimension whose boundary values are 0, 10, 20 and 30, so their mean is 15
#: and their population standard deviation is sqrt(125) = 11.180.
SIMPLE = (
    PrototypeRange(code=1, property_name="x", column="aspect_ratio", lo=0.0, hi=10.0, source="t"),
    PrototypeRange(code=2, property_name="x", column="aspect_ratio", lo=20.0, hi=30.0, source="t"),
)

MEAN = 15.0
STD = float(np.std([0.0, 10.0, 20.0, 30.0]))


def frame(**columns: list[float]) -> pd.DataFrame:
    result = pd.DataFrame(columns)
    result.index = pd.Index([f"u{index}" for index in range(len(result))], name="unit_id")
    return result


def test_normalisation_is_the_mean_and_spread_of_the_boundary_values() -> None:
    """Bernard et al. (2024) Sect. 2.3: standardise "using the mean and the standard deviation of
    all LCZ-type boundary values". Population spread, because these are the whole set of
    boundaries rather than a sample from a larger one."""
    stats = normalisation(SIMPLE)

    assert stats.means["aspect_ratio"] == pytest.approx(MEAN)
    assert stats.stds["aspect_ratio"] == pytest.approx(STD)
    assert stats.degenerate == ()


def test_a_value_inside_the_hypercube_is_at_distance_zero() -> None:
    """The defining property of the closest-distance approach: a class is a box, not a point, so
    anywhere inside it is equally and exactly the class."""
    space = PrototypeSpace(SIMPLE)

    result = space.distances(frame(aspect_ratio=[0.0, 5.0, 10.0]), [1], {"aspect_ratio": 1.0})

    assert result.distances[1].to_list() == pytest.approx([0.0, 0.0, 0.0])


def test_a_value_outside_is_the_standardised_gap_to_the_nearer_edge() -> None:
    """15 is 5 above LCZ 1's upper bound of 10, which standardises to 5 / sqrt(125)."""
    space = PrototypeSpace(SIMPLE)

    result = space.distances(frame(aspect_ratio=[15.0]), [1, 2], {"aspect_ratio": 1.0})

    assert result.distances.loc["u0", 1] == pytest.approx(5.0 / STD)
    assert result.distances.loc["u0", 2] == pytest.approx(5.0 / STD)


def test_an_open_ended_bound_never_penalises() -> None:
    """ "25 m and above" means a 90 m unit is inside the class, not 65 m outside it. Blank cells
    in the published table are exactly this, and there are many of them."""
    open_ended = (
        PrototypeRange(
            code=1, property_name="x", column="aspect_ratio", lo=20.0, hi=None, source="t"
        ),
    )
    space = PrototypeSpace(open_ended)

    result = space.distances(frame(aspect_ratio=[1e6, 20.0, 0.0]), [1], {"aspect_ratio": 1.0})

    assert result.distances[1].to_list() == pytest.approx(
        [0.0, 0.0, 20.0 / space.normalisation.stds["aspect_ratio"]]
    )


def test_a_dimension_a_prototype_does_not_constrain_is_unbounded_not_missing() -> None:
    """LCZ G has no published height range. Dropping the dimension for that class alone would
    shrink its denominator and make its distance systematically smaller than everyone else's — it
    would win units it has no claim on. As an unbounded interval it scores zero there and the
    denominators stay equal, which is what makes seventeen distances comparable.
    """
    partial = (
        PrototypeRange(
            code=1, property_name="a", column="aspect_ratio", lo=0.0, hi=1.0, source="t"
        ),
        PrototypeRange(
            code=1, property_name="t", column="tree_fraction", lo=0.0, hi=1.0, source="t"
        ),
        PrototypeRange(
            code=2, property_name="a", column="aspect_ratio", lo=0.0, hi=1.0, source="t"
        ),
        # code 2 constrains no tree fraction at all
    )
    space = PrototypeSpace(partial)
    weights = {"aspect_ratio": 1.0, "tree_fraction": 1.0}

    result = space.distances(frame(aspect_ratio=[0.5], tree_fraction=[99.0]), [1, 2], weights)

    # Class 2 is unpenalised on the wild tree fraction; class 1 is not. Both divide by 2.0.
    assert result.distances.loc["u0", 2] == pytest.approx(0.0)
    assert result.distances.loc["u0", 1] > 0.0
    assert result.n_params_used.loc["u0"] == 2


def test_a_null_parameter_renormalises_rather_than_dropping_the_unit() -> None:
    """CLAUDE.md's null policy. Two units identical except that one is missing a parameter must
    come out on the same scale — otherwise a unit with fewer measurements looks closer to
    everything, and `aspect_ratio` is null in a small but nonzero share of real units."""
    space = PrototypeSpace(
        (
            PrototypeRange(
                code=1, property_name="a", column="aspect_ratio", lo=0.0, hi=1.0, source="t"
            ),
            PrototypeRange(
                code=1, property_name="t", column="tree_fraction", lo=0.0, hi=1.0, source="t"
            ),
        )
    )
    weights = {"aspect_ratio": 1.0, "tree_fraction": 1.0}
    complete = frame(aspect_ratio=[3.0], tree_fraction=[3.0])
    partial = frame(aspect_ratio=[3.0], tree_fraction=[np.nan])

    both = space.distances(complete, [1], weights)
    one = space.distances(partial, [1], weights)

    assert both.distances.loc["u0", 1] == pytest.approx(one.distances.loc["u0", 1])
    assert both.n_params_used.loc["u0"] == 2
    assert one.n_params_used.loc["u0"] == 1
    assert one.missing_parameters.loc["u0"] == "tree_fraction"


def test_a_zero_weight_dimension_leaves_both_sides_of_the_ratio() -> None:
    """Bernard's FI and FP weights are zero, so those dimensions must not affect the distance at
    all — not even by inflating the denominator, which would shrink every distance uniformly."""
    space = PrototypeSpace(
        (
            PrototypeRange(
                code=1, property_name="a", column="aspect_ratio", lo=0.0, hi=1.0, source="t"
            ),
            PrototypeRange(
                code=1, property_name="t", column="tree_fraction", lo=0.0, hi=1.0, source="t"
            ),
        )
    )
    values = frame(aspect_ratio=[5.0], tree_fraction=[99.0])

    ignored = space.distances(values, [1], {"aspect_ratio": 1.0, "tree_fraction": 0.0})
    alone = space.distances(
        values.drop(columns=["tree_fraction"]).assign(tree_fraction=np.nan),
        [1],
        {"aspect_ratio": 1.0, "tree_fraction": 0.0},
    )

    assert ignored.distances.loc["u0", 1] == pytest.approx(alone.distances.loc["u0", 1])
    assert ignored.n_params_used.loc["u0"] == 1
    assert ignored.missing_parameters.loc["u0"] == ""


def test_a_unit_with_nothing_measured_is_unclassifiable_not_equidistant() -> None:
    space = PrototypeSpace(SIMPLE)

    result = space.distances(frame(aspect_ratio=[np.nan]), [1, 2], {"aspect_ratio": 1.0})

    assert result.distances.loc["u0"].isna().all()
    assert result.n_params_used.loc["u0"] == 0


def test_uniqueness_is_bernards_equation_one() -> None:
    """|d1 - d2| / (d1 + d2). Zero where the two nearest are tied, one where the nearest is
    unrivalled — a different question from "how close is it", which `min_distance` answers."""
    closest = pd.Series([0.0, 1.0, 2.0, 0.0])
    second = pd.Series([0.0, 3.0, 2.0, 1.0])

    assert uniqueness(closest, second).to_list() == pytest.approx([0.0, 0.5, 0.0, 1.0])


def test_uniqueness_of_an_unrivalled_label_is_one_not_zero() -> None:
    """A missing runner-up is the opposite of ambiguity, and the naive formula would report 0.0."""
    assert uniqueness(pd.Series([0.4]), pd.Series([np.nan])).to_list() == [1.0]
    assert uniqueness(pd.Series([np.nan]), pd.Series([np.nan])).isna().all()


def test_the_real_table_produces_finite_stats_for_every_dimension() -> None:
    space = PrototypeSpace(PROTOTYPES)
    stats = space.normalisation

    assert set(stats.dimensions) == set(stats.means) == set(stats.stds)
    assert all(np.isfinite(value) and value > 0 for value in stats.stds.values())
    assert stats.degenerate == ()


def test_missing_dimensions_and_unknown_codes_are_refused() -> None:
    space = PrototypeSpace(SIMPLE)

    with pytest.raises(ValueError, match="compute_parameters"):
        space.distances(frame(other=[1.0]), [1], {"aspect_ratio": 1.0})
    with pytest.raises(KeyError, match="99"):
        space.distances(frame(aspect_ratio=[1.0]), [99], {"aspect_ratio": 1.0})
