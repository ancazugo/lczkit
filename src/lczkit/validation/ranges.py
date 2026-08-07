"""Where a computed parameter actually falls, against the range Stewart & Oke published for it.

Agreement says *whether* a label was right. This says *why* it was wrong, and it is the instrument
Phase 6.5 turns on: if a parameter is systematically outside the published band for the class a
unit genuinely belongs to, no weighting or threshold downstream can recover the label, because the
prototype the unit should match is unreachable in that dimension.

**Group by the reference class, not by the assigned one.** Grouping by the assigned class asks
whether the labelling is self-consistent, which it is almost by construction - the classifier
placed those units near that prototype, so their parameter lands near its range. Grouping by the
reference class asks whether the parameter *reaches* the published range on units of known type,
which is the question. The two are easy to confuse and give opposite answers: on the Berlin
fixture, building surface fraction grouped by assigned class sits inside LCZ 2's published 40-70%,
while grouped by reference class it sits at 0.31.

Everything is area-weighted, for the reason `agreement` is: on enclosures, weighting by count lets
a thousand street-margin slivers outvote a district.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from lczkit.classify.labels import lcz
from lczkit.classify.prototypes import property_of, ranges_for


class ClassRange(BaseModel):
    """One class: where the units it should contain actually sit, against its published range."""

    code: int
    label: str
    name: str

    n: int
    area_m2: float

    published_min: float | None
    published_max: float | None
    """The prototype interval in the column's own unit. `None` is an open end - a class unbounded
    on that side, which no value can fall outside."""

    median: float | None
    """Area-weighted median of the parameter over this class' units."""

    p10: float | None
    p90: float | None

    share_in_range: float
    """Area share of this class' units whose parameter lies inside the published interval. The
    headline number: 1.0 means the published prototype is reachable for every unit that should
    match it, 0.0 means it is reachable for none of them."""


class RangeReport(BaseModel):
    """One parameter, compared against its published range across every class present."""

    column: str
    property_name: str
    source: str
    """`STEWART_OKE_2012` or `lczkit` - whether the range being tested against is published at
    all. Testing a measurement against a range this package invented proves nothing about the
    measurement, so the provenance travels with the numbers."""

    grouped_by: str
    """`"reference"` or `"assigned"`. See the module docstring: these answer different questions."""

    n_units: int
    per_class: list[ClassRange] = Field(default_factory=list)


def parameter_ranges(
    values: pd.Series,
    labels: pd.Series,
    area_m2: pd.Series,
    *,
    column: str,
    grouped_by: str = "reference",
) -> RangeReport:
    """Compare `values` against the published range of `column`, grouped by `labels`.

    All three series are indexed by `unit_id`. Units with a null value or a null label are
    excluded - a unit the reference map does not reach cannot tell us anything about whether the
    parameter reaches a range - and classes absent from `labels` are omitted rather than reported
    as empty, since a class no unit belongs to has nothing to say about the parameter.
    """
    spec = property_of(column)
    frame = pd.DataFrame(
        {
            "value": pd.to_numeric(values, errors="coerce"),
            "label": pd.to_numeric(labels, errors="coerce"),
            "area": pd.to_numeric(area_m2, errors="coerce"),
        }
    ).dropna(subset=["value", "label", "area"])

    report = RangeReport(
        column=column,
        property_name=spec.name,
        source=spec.source,
        grouped_by=grouped_by,
        n_units=int(len(frame)),
    )
    for code in sorted(frame["label"].unique()):
        entry = lcz(int(code))
        group = frame[frame["label"] == code]
        lo, hi = ranges_for(entry.code).get(column, (None, None))
        value = group["value"].to_numpy(dtype="float64")
        weight = group["area"].to_numpy(dtype="float64")
        inside = (value >= (-np.inf if lo is None else lo)) & (
            value <= (np.inf if hi is None else hi)
        )
        total = float(weight.sum())
        report.per_class.append(
            ClassRange(
                code=entry.code,
                label=entry.label,
                name=entry.name,
                n=int(len(group)),
                area_m2=total,
                published_min=lo,
                published_max=hi,
                median=weighted_quantile(value, weight, 0.5),
                p10=weighted_quantile(value, weight, 0.1),
                p90=weighted_quantile(value, weight, 0.9),
                share_in_range=float(weight[inside].sum() / total) if total > 0 else 0.0,
            )
        )
    return report


def weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float | None:
    """The `q`-quantile of `values` weighted by `weights`, or `None` for an empty input.

    The lower of the two interpolation candidates rather than a blend: the quantity is reported
    beside a published interval, and an interpolated value is not one any unit actually has.
    """
    if values.size == 0:
        return None
    order = np.argsort(values, kind="stable")
    sorted_values, sorted_weights = values[order], weights[order]
    total = sorted_weights.sum()
    if total <= 0:
        return float(np.median(sorted_values))
    position = int(np.searchsorted(np.cumsum(sorted_weights), q * total))
    return float(sorted_values[min(position, sorted_values.size - 1)])
