"""Normalisation and weighted partial distance from a unit to each LCZ prototype.

Bernard et al. (2024) Sect. 2.3 give the recipe. A class is a hypercube in the UCP space and a
unit is a point; the distance is the gap from the point to the box, zero inside it. Because the
dimensions have wildly different spreads - building height runs from zero to hundreds of metres
while a fraction is confined to [0, 1] - each is standardised first, "using the mean and the
standard deviation of all LCZ-type boundary values". That is the published operationalisation of
what CLAUDE.md calls normalising against the LCZ-defined range, and it is what this module does.

Two details are load-bearing and neither is spelled out in the paper.

**An open-ended bound never penalises.** LCZ 1's height range is "25 m and above"; a 90 m unit is
inside it, not 65 m outside. Blank cells in the transcribed table are exactly this, and there are
many of them.

**A dimension a prototype does not constrain is an unbounded interval, not missing data.** LCZ G
has no published height range at all. Treating that as an absent dimension would shrink LCZ G's
denominator relative to every other class's and make its distance systematically smaller - the
class would win units it has no claim on. Treating it as unbounded gives it a zero penalty there
while keeping the denominator identical across all seventeen, which is what makes the distances
comparable at all.

Only a null *unit* value shrinks the denominator, and then it shrinks it identically for every
prototype. That is CLAUDE.md's weighted partial distance: sum over available parameters,
renormalise by the sum of their weights, never impute and never drop the unit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from lczkit.classify.prototypes import PROTOTYPES, PrototypeRange


@dataclass(frozen=True)
class Normalisation:
    """Per-dimension standardisation derived from the prototype table itself."""

    dimensions: tuple[str, ...]
    means: dict[str, float]
    stds: dict[str, float]

    degenerate: tuple[str, ...]
    """Dimensions whose boundary values had zero spread, and whose standard deviation was
    therefore replaced by 1.0. None occur in the shipped table; recorded so a user-supplied
    prototype override cannot introduce a silent division by zero."""

    def z(self, column: str, value: float) -> float:
        """Standardise one value in one dimension."""
        return (value - self.means[column]) / self.stds[column]

    def as_dict(self) -> dict[str, dict[str, float]]:
        """For the run manifest."""
        return {
            column: {"mean": self.means[column], "std": self.stds[column]}
            for column in self.dimensions
        }


def normalisation(prototypes: Sequence[PrototypeRange] = PROTOTYPES) -> Normalisation:
    """Mean and standard deviation of every non-null boundary value, per dimension.

    Computed over *all* prototypes rather than per family, so the built and natural distances are
    expressed on one scale.

    The population standard deviation is used: these are the boundary values, the whole set of
    them, not a sample drawn from a larger population.
    """
    boundaries: dict[str, list[float]] = {}
    for prototype in prototypes:
        bounds = boundaries.setdefault(prototype.column, [])
        bounds += [bound for bound in (prototype.lo, prototype.hi) if bound is not None]

    means: dict[str, float] = {}
    stds: dict[str, float] = {}
    degenerate: list[str] = []
    for column, values in boundaries.items():
        if not values:
            raise ValueError(f"dimension {column!r} has no prototype boundary values to scale by")
        array = np.asarray(values, dtype="float64")
        means[column] = float(array.mean())
        spread = float(array.std())
        if spread == 0.0:
            degenerate.append(column)
            spread = 1.0
        stds[column] = spread
    return Normalisation(
        dimensions=tuple(boundaries),
        means=means,
        stds=stds,
        degenerate=tuple(degenerate),
    )


@dataclass(frozen=True)
class DistanceResult:
    """Distances to one family's prototypes, plus what the metric had to work with."""

    distances: pd.DataFrame
    """Indexed like the input, one column per LCZ code, in the order `codes` was given."""

    n_params_used: pd.Series
    """Dimensions that carried non-zero weight *and* a non-null value, per unit."""

    n_params_available: int
    """How many dimensions carried non-zero weight at all, for this family's weight vector.

    The denominator `n_params_used` is a count out of, and it differs *between families*: under
    `bernard2024_partial` a built unit can reach 3 and a natural unit 7, because four dimensions
    are zero-weighted for built types and leave both sides of the renormalisation. Without this,
    a single `n_params_used` column silently mixes the two scales and a built unit scoring 3 of 3
    is indistinguishable from a natural unit scoring 3 of 7.
    """

    missing_parameters: pd.Series
    """Comma-separated names of the weighted dimensions that were null, per unit; empty string
    where nothing was missing. A string rather than a list so the column survives a GeoParquet
    round trip unchanged and reads plainly in the Phase 7 sidebar."""


class PrototypeSpace:
    """A prototype table plus the normalisation derived from it.

    Holds the standardised bounds so a run does not re-derive them per call. Immutable in use;
    build a second one to classify against different thresholds.
    """

    def __init__(self, prototypes: Sequence[PrototypeRange] = PROTOTYPES) -> None:
        self.prototypes = tuple(prototypes)
        self.normalisation = normalisation(self.prototypes)
        self.dimensions = self.normalisation.dimensions
        self._position = {column: index for index, column in enumerate(self.dimensions)}
        self._bounds = {
            code: self._standardised_bounds(code)
            for code in sorted({prototype.code for prototype in self.prototypes})
        }

    @property
    def codes(self) -> tuple[int, ...]:
        """Every class this space carries ranges for, ascending."""
        return tuple(self._bounds)

    def _standardised_bounds(self, code: int) -> tuple[np.ndarray, np.ndarray]:
        """`(lo, hi)` over `dimensions` for one prototype, NaN where the class is open."""
        lo = np.full(len(self.dimensions), np.nan)
        hi = np.full(len(self.dimensions), np.nan)
        for prototype in self.prototypes:
            if prototype.code != code:
                continue
            index = self._position[prototype.column]
            if prototype.lo is not None:
                lo[index] = self.normalisation.z(prototype.column, prototype.lo)
            if prototype.hi is not None:
                hi[index] = self.normalisation.z(prototype.column, prototype.hi)
        return lo, hi

    def distances(
        self,
        values: pd.DataFrame,
        codes: Sequence[int],
        weights: Mapping[str, float],
    ) -> DistanceResult:
        """Weighted partial distance from each row of `values` to each prototype in `codes`.

        `values` must carry every dimension; extra columns are ignored. A row where no weighted
        dimension has a value gets an all-null distance row rather than a zero one - a unit the
        metric knows nothing about is unclassifiable, not equidistant from everything.
        """
        absent = [column for column in self.dimensions if column not in values.columns]
        if absent:
            raise ValueError(
                f"values is missing prototype dimensions: {', '.join(absent)}. "
                "Pass the table lczkit.ucp.compute_parameters() returns."
            )
        unknown = [code for code in codes if code not in self._bounds]
        if unknown:
            raise KeyError(f"no prototype ranges for LCZ code(s) {unknown}")
        if not codes:
            raise ValueError("codes must name at least one prototype")

        weight = np.asarray([float(weights[column]) for column in self.dimensions])
        raw = values[list(self.dimensions)].to_numpy(dtype="float64", na_value=np.nan)
        known = ~np.isnan(raw)

        means = np.asarray([self.normalisation.means[c] for c in self.dimensions])
        stds = np.asarray([self.normalisation.stds[c] for c in self.dimensions])
        z = (raw - means) / stds

        # Identical for every prototype, so a unit's distances stay comparable; a zero-weight
        # dimension leaves both sides and cannot influence the result.
        denominator = (known * weight).sum(axis=1)
        usable = denominator > 0
        safe = np.where(usable, denominator, 1.0)

        columns: dict[int, np.ndarray] = {}
        for code in codes:
            lo, hi = self._bounds[code]
            # An open end is NaN, which propagates through the comparison; `nan_to_num` then
            # reads it as "no bound on this side", i.e. no penalty. Only one of the two terms
            # can be positive, so adding them is the same as taking the gap to the nearer bound.
            penalty = np.nan_to_num(np.maximum(0.0, lo - z)) + np.nan_to_num(
                np.maximum(0.0, z - hi)
            )
            numerator = (np.where(known, penalty, 0.0) ** 2 * weight).sum(axis=1)
            columns[code] = np.where(usable, np.sqrt(numerator / safe), np.nan)

        weighted = [column for column, w in zip(self.dimensions, weight, strict=True) if w > 0]
        present = known[:, [self._position[column] for column in weighted]]
        return DistanceResult(
            distances=pd.DataFrame(columns, index=values.index),
            n_params_used=pd.Series(present.sum(axis=1), index=values.index, dtype="int64"),
            n_params_available=len(weighted),
            missing_parameters=pd.Series(
                [
                    ",".join(name for name, ok in zip(weighted, row, strict=True) if not ok)
                    for row in present
                ],
                index=values.index,
                dtype="object",
            ),
        )


def uniqueness(closest: pd.Series, second: pd.Series) -> pd.Series:
    """Bernard et al. (2024) Eq. (1): `|d1 - d2| / (d1 + d2)`, in [0, 1].

    Zero means the two nearest prototypes are equidistant and the label is a coin toss; one means
    the nearest is unrivalled. It answers a different question from the distance itself - a unit
    can sit close to its class and still be ambiguous, or far from every class but unambiguously
    nearest one of them.

    Both distances zero - a unit inside two hypercubes at once - gives zero rather than a division
    by zero, which is the formula's own limit and the honest answer: the label is arbitrary. A
    missing runner-up gives one: nothing rivals the label, which is the opposite of ambiguous.
    """
    total = closest + second
    scores = (closest - second).abs().div(total.where(total > 0)).fillna(0.0)
    return scores.mask(second.isna(), 1.0).where(closest.notna())
