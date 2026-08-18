"""A modal filter over the classified units — the minimum mapping unit this package never had.

Every unit is classified independently of its neighbours. Nothing in the pipeline has ever looked
at what surrounds a cell, so a 100 m cell whose parameters wobble across a prototype boundary takes
a different label from the fabric it sits in, and the result is salt-and-pepper at a grain Stewart
& Oke never intended a class to be read at. An LCZ patch is a neighbourhood — the published
guidance is a few hundred metres across, and the So2Sat patches this project validates against are
320 m — so a single isolated 1 ha cell is not a claim the scheme can carry.

The LCZ literature's answer is a spatial filter and it is standard: the LCZ Generator applies one
before publishing a map. lczkit omitted it, which is why the omission is worth naming rather than
quietly fixing — every stored figure in this project was measured without one.

**It ships disabled, and that is a ruling rather than caution.** `min_like_neighbours` is a
threshold, CLAUDE.md requires a threshold to be swept against a reference and chosen at an
operating point, and this one has not been swept. Turning it on before that would move every label
in a run on the strength of a number nobody measured.

**A functionally assigned label is never overwritten.** The industrial rule and the semantic rules
place a unit on evidence about what is there, not on morphology that might have wobbled, so an
isolated LCZ 10 cell in a residential block is a claim about an industrial parcel and not noise.
Smoothing it away would silently undo the one part of the classifier that reads the data directly.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from libpysal.graph import Graph
from pydantic import BaseModel

from lczkit.classify import rules

DEFAULT_MIN_LIKE_NEIGHBOURS = 2
"""Placeholder marking where a swept number goes. Not calibrated — see the module docstring.

A unit with fewer than this many neighbours sharing its label is treated as isolated. Two is the
weakest setting that does anything at all on a Queen-contiguous grid, chosen so that a caller who
enables the filter without sweeping it does the smallest thing rather than the boldest.
"""


class SmoothingReport(BaseModel):
    """What the modal filter did to one run."""

    enabled: bool
    min_like_neighbours: int

    n_units: int
    n_relabelled: int
    """Units the filter moved. Zero when disabled, and zero on a map with no isolated cells —
    "never fired" and "never configured" stay distinguishable via `enabled`."""

    n_protected: int
    """Units the filter left alone because a rule had placed them. See the module docstring."""


def modal_filter(
    units: gpd.GeoDataFrame,
    classification: pd.DataFrame,
    *,
    enabled: bool = False,
    min_like_neighbours: int = DEFAULT_MIN_LIKE_NEIGHBOURS,
) -> tuple[pd.DataFrame, SmoothingReport]:
    """Replace an isolated unit's label with the most common label among its neighbours.

    A unit is *isolated* when strictly fewer than `min_like_neighbours` of its contiguous
    neighbours carry its own label. Isolation is judged on the labels the classifier produced, and
    every reassignment is computed from that same snapshot rather than applied in sequence, so the
    result does not depend on the order units are visited and one pass cannot cascade.

    Only `lcz_primary` moves. The distance vector, `uniqueness` and `n_params_used` describe the
    unit's own parameters and remain true of it; overwriting them would make the metric's own
    output disagree with the label it produced, which is worse than the label being smoothed.
    `label_route` records the change.

    Neither input is mutated.
    """
    out = classification.copy()
    protected = classification["lcz10_rule_applied"].to_numpy(dtype="bool") | classification[
        "semantic_rule_applied"
    ].to_numpy(dtype="bool")
    if not enabled or len(units) < 2:
        return out, SmoothingReport(
            enabled=enabled,
            min_like_neighbours=min_like_neighbours,
            n_units=len(units),
            n_relabelled=0,
            n_protected=0,
        )

    labels = classification["lcz_primary"]
    graph = Graph.build_contiguity(units, rook=False)
    positions = {unit_id: index for index, unit_id in enumerate(units.index)}
    values = labels.to_numpy(dtype="float64")

    replacement = np.full(len(units), np.nan)
    like = np.zeros(len(units), dtype="int64")
    for focal, neighbours in graph.neighbors.items():
        index = positions[focal]
        if np.isnan(values[index]) or not len(neighbours):
            continue
        around = values[[positions[other] for other in neighbours]]
        around = around[~np.isnan(around)]
        if not around.size:
            continue
        like[index] = int((around == values[index]).sum())
        codes, counts = np.unique(around, return_counts=True)
        # Ties break to the lower code, matching `_two_closest` — arbitrary, but the same
        # arbitrary rule the rest of the classifier already uses.
        replacement[index] = codes[counts.argmax()]

    isolated = (like < min_like_neighbours) & ~np.isnan(replacement) & ~np.isnan(values)
    moved = isolated & (replacement != values) & ~protected

    out.loc[moved, "lcz_primary"] = replacement[moved].astype("int64")
    # `ROUTE_SMOOTHED` is in `rules.ROUTES`, so the classifier's categorical already carries it and
    # the column needs no widening — which is what keeps a filtered run schema-identical to an
    # unfiltered one rather than differing by a category.
    out.loc[moved, "label_route"] = rules.ROUTE_SMOOTHED
    return out, SmoothingReport(
        enabled=True,
        min_like_neighbours=min_like_neighbours,
        n_units=len(units),
        n_relabelled=int(moved.sum()),
        n_protected=int((isolated & (replacement != values) & protected).sum()),
    )
