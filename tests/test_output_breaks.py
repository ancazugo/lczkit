"""Precomputed classification breaks.

These exist so Phase 7 is a pure transform of run outputs — CLAUDE.md forbids the site build from
recomputing a parameter or a quantile — and so two viewers of the same run see the same class
boundaries. The awkward cases are all about variables that are mostly one value, which is what a
city's parameters actually look like.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lczkit.output.breaks import breaks_for, quantile_breaks


def series(values: list[float], name: str = "x") -> pd.Series:
    return pd.Series(values, name=name, dtype="float64")


def test_quartiles_of_a_uniform_run_are_where_they_should_be() -> None:
    result = quantile_breaks(series([float(value) for value in range(101)]), 4)

    assert result.breaks == pytest.approx([0.0, 25.0, 50.0, 75.0, 100.0])
    assert result.k == 4
    assert result.method == "quantile"
    assert result.n_valid == 101
    assert (result.minimum, result.maximum) == (0.0, 100.0)


def test_nulls_are_excluded_from_the_quantiles_rather_than_treated_as_zero() -> None:
    result = quantile_breaks(series([0.0, np.nan, 100.0]), 2)

    assert result.breaks == pytest.approx([0.0, 50.0, 100.0])
    assert result.n_valid == 2


def test_coincident_breaks_collapse_rather_than_drawing_empty_classes() -> None:
    """`industrial_fraction` is zero over most of a city, so several quantiles land on zero. A
    renderer handed [0, 0, 0, 0.4] would draw three classes no unit can fall into."""
    result = quantile_breaks(series([0.0] * 9 + [0.4]), 4)

    assert result.breaks == pytest.approx([0.0, 0.4])


def test_a_constant_variable_gets_one_boundary() -> None:
    result = quantile_breaks(series([3.0, 3.0, 3.0]), 5)

    assert result.breaks == pytest.approx([3.0])
    assert (result.minimum, result.maximum) == (3.0, 3.0)


def test_an_all_null_variable_gets_no_breaks_rather_than_an_error() -> None:
    """A small extent can legitimately produce a parameter nothing measured. A missing choropleth
    is a better outcome than a failed run."""
    result = quantile_breaks(series([np.nan, np.nan]), 4)

    assert result.breaks == []
    assert result.n_valid == 0
    assert result.minimum is None and result.maximum is None


def test_breaks_for_keeps_the_column_order_it_was_given() -> None:
    frame = pd.DataFrame({"a": [1.0, 2.0], "b": [10.0, 20.0], "c": [0.0, 1.0]})

    result = breaks_for(frame, ["c", "a"], 2)

    assert [entry.column for entry in result] == ["c", "a"]


def test_too_few_classes_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        quantile_breaks(series([1.0, 2.0]), 1)
