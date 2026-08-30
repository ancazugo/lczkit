"""Classification breaks, precomputed once at run time so the map site never recomputes them.

The static site is a pure transform of run outputs: it never recomputes a parameter or a quantile.
Breaks are the only quantity a choropleth needs beyond the values themselves, so computing them
here is what makes that possible — and it also means two viewers of the same run see the same class
boundaries, which they would not if each rendering derived its own.

Quantiles, not natural breaks. Jenks would mean a `mapclassify` dependency to save a one-line call.
The method name is recorded alongside the values so a consumer is never left inferring it.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd
from pydantic import BaseModel


class VariableBreaks(BaseModel):
    """Break points for one continuous variable, plus what they were computed from."""

    column: str
    method: str
    """Currently always `"quantile"`. Stated rather than assumed."""

    k: int
    """Number of classes the breaks divide the values into."""

    breaks: list[float]
    """The `k + 1` boundaries, ascending, from the minimum to the maximum. Fewer than `k + 1`
    distinct values collapse to however many distinct boundaries exist - a variable that is
    constant over a run gets a single-element list, which is the truthful answer."""

    n_valid: int
    """Non-null values the breaks were computed over."""

    minimum: float | None
    maximum: float | None


def quantile_breaks(values: pd.Series, k: int) -> VariableBreaks:
    """`k`-quantile breaks over the non-null values of `values`.

    An all-null or empty variable returns no breaks rather than raising: a run over a small extent
    can legitimately produce a parameter nothing measured, and a missing choropleth is a better
    outcome than a failed run.
    """
    if k < 2:
        raise ValueError(f"k must be at least 2, got {k}")
    clean = pd.to_numeric(values, errors="coerce").dropna()
    name = str(values.name)
    if clean.empty:
        return VariableBreaks(
            column=name, method="quantile", k=k, breaks=[], n_valid=0, minimum=None, maximum=None
        )

    array = clean.to_numpy(dtype="float64")
    edges = np.nanquantile(array, np.linspace(0.0, 1.0, k + 1))
    # Duplicate edges are real - a variable that is zero over most of a city has several
    # coincident quantiles - and a renderer given [0, 0, 0, 0.4] would draw three empty classes.
    unique = np.unique(edges)
    return VariableBreaks(
        column=name,
        method="quantile",
        k=k,
        breaks=[float(edge) for edge in unique],
        n_valid=int(clean.size),
        minimum=float(array.min()),
        maximum=float(array.max()),
    )


def breaks_for(frame: pd.DataFrame, columns: Iterable[str], k: int) -> list[VariableBreaks]:
    """Breaks for each named column of `frame`, in the order given."""
    return [quantile_breaks(frame[column], k) for column in columns]
