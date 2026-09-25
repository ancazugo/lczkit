"""The rules that sit outside the distance metric.

Each exists because a dimension the LCZ scheme needs is not in the parameter vector.

**The family gate.** Where nothing is built, Stewart & Oke's natural classes differ only by
building-derived properties, so the built and natural types are compared in separate families. A
unit below the building surface fraction the published table itself uses as the built/natural
boundary is compared against the natural prototypes only (Bernard et al. 2024, Sect. 2.3).

**Functional assignment.** LCZ 10 and LCZ 8 are geometrically near-identical; only anthropogenic
heat separates them, which open data does not measure. Following Bernard et al. (2024), LCZ 10
leaves the distance metric and is assigned from the industrial share instead. A pair-gated
morphological rule was measured inert on Rotterdam at every threshold from 0.05 to 0.5: port plots
are sparsely built and land on LCZ 9. The semantic rules (`SemanticRuleConfig`) use the same
mechanism. LCZ 8 stays in the metric, a deliberate divergence from Bernard, because its large, low,
sparse form is genuinely morphological.

A functionally assigned unit keeps the displaced label as `lcz_secondary` and a null
`min_distance`, since the assigned class was not reached by distance.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from lczkit.config import SemanticRuleConfig

BUILT = "built"
NATURAL = "natural"

ROUTE_BUILT = "distance_built"
ROUTE_NATURAL = "distance_natural"
ROUTE_INDUSTRIAL = "industrial_rule"
ROUTE_SEMANTIC = "semantic_rule"
"""A label assigned by a functional rule other than the industrial one.

Distinct from `industrial_rule` rather than folded into it: that rule's threshold is calibrated
against the Rotterdam reference and its firing count is a published figure, so a second rule
sharing its route value would silently change what that count means. Which rule fired is in
`semantic_rule_applied`."""

ROUTE_SMOOTHED = "modal_filter"
"""A label taken from the unit's neighbours rather than from its own parameters.

Only `lczkit.classify.smoothing` emits it, and only when that filter is enabled — which it is not
by default. Kept in the vocabulary regardless, so the category set does not depend on a
configuration flag and a run with the filter off is schema-identical to one with it on."""

ROUTES: tuple[str, ...] = (
    ROUTE_BUILT,
    ROUTE_NATURAL,
    ROUTE_INDUSTRIAL,
    ROUTE_SEMANTIC,
    ROUTE_SMOOTHED,
)
"""Every value `label_route` can take. A fixed vocabulary so the column is a stable category."""


def family_of(building_surface_fraction: pd.Series, threshold: float) -> pd.Series:
    """`"built"` where the building surface fraction reaches `threshold`, else `"natural"`.

    `building_surface_fraction` is never null - the parameter stage reports 0.0, not NaN, for a
    unit holding no buildings, because "no buildings here" is a measurement - so the gate is defined
    for every unit and no unit goes unclassified for want of it.
    """
    if building_surface_fraction.isna().any():
        raise ValueError(
            "building_surface_fraction contains nulls; the parameter stage reports 0.0 for a unit "
            "with no buildings, so a null here means the parameter table was not produced by "
            "lczkit.ucp.compute_parameters()."
        )
    return pd.Series(
        np.where(building_surface_fraction >= threshold, BUILT, NATURAL),
        index=building_surface_fraction.index,
        dtype="object",
    )


@dataclass(frozen=True)
class Ranked:
    """The two nearest prototypes and their distances, per unit."""

    primary: pd.Series
    secondary: pd.Series
    closest: pd.Series
    runner_up: pd.Series


def _relabel(ranked: Ranked, fires: pd.Series, code: int) -> Ranked:
    """Assign `code` where `fires`, keeping the displaced label as `secondary`.

    `runner_up` moves with the displaced label so it stays the distance to `secondary`, and
    `closest` goes null: the assigned class was not reached by distance, so no distance to it is
    defined.
    """
    return Ranked(
        primary=ranked.primary.where(~fires, code),
        secondary=ranked.secondary.where(~fires, ranked.primary),
        closest=ranked.closest.where(~fires),
        runner_up=ranked.runner_up.where(~fires, ranked.closest),
    )


def apply_lcz10_rule(
    ranked: Ranked,
    industrial_fraction: pd.Series,
    threshold: float,
    *,
    lcz10: int = 10,
) -> tuple[Ranked, pd.Series]:
    """Assign LCZ 10 wherever the industrial share exceeds `threshold`, whatever the morphology.

    LCZ 10 is not in the built prototype set, so this is its only route. A null share never fires:
    it means the unit holds no buildings to judge, which is not evidence of heavy industry.
    """
    fired = (industrial_fraction > threshold).fillna(False)
    return _relabel(ranked, fired, lcz10), fired


def apply_semantic_rules(
    ranked: Ranked,
    parameters: pd.DataFrame,
    rules: Sequence[SemanticRuleConfig],
) -> tuple[Ranked, pd.Series, dict[str, int]]:
    """Apply the configured functional rules in order, returning what each one fired on.

    A later rule overrides an earlier one on a unit both fire on, and each rule's count is of units
    where it fired *and survived*, so a shadowed rule shows as zero. Every configured rule appears
    in the counts, enabled or not, so "never fired" stays distinguishable from "never configured".
    """
    # Which rule *last* fired on each unit. LCZ 7 and 8 are also reachable by distance, so counting
    # labels would conflate the rule's work with the metric's.
    winner = pd.Series("", index=ranked.primary.index, dtype="object")
    counts: dict[str, int] = {}
    for rule in rules:
        counts[rule.name] = 0
        if not rule.enabled:
            continue
        if rule.column not in parameters.columns:
            raise ValueError(
                f"semantic rule {rule.name!r} reads {rule.column!r}, which the parameter table "
                f"does not carry. Configure `ucp.semantic_groups` so that column is emitted, or "
                "disable the rule."
            )
        fires = (parameters[rule.column] > rule.min_fraction).fillna(False)
        if rule.max_mean_building_area_m2 is not None:
            area = parameters["mean_building_area_m2"]
            fires &= (area <= rule.max_mean_building_area_m2).fillna(False)
        if rule.min_mean_building_area_m2 is not None:
            area = parameters["mean_building_area_m2"]
            fires &= (area >= rule.min_mean_building_area_m2).fillna(False)
        ranked = _relabel(ranked, fires, rule.lcz)
        winner = winner.where(~fires, rule.name)

    for name in counts:
        counts[name] = int((winner == name).sum())
    return ranked, winner.ne(""), counts


def drop_lcz1_below_height(
    distances: pd.DataFrame,
    height_of_roughness_elements_m: pd.Series,
    minimum: float | None,
    *,
    lcz1: int = 1,
) -> pd.DataFrame:
    """Discard the LCZ 1 distance for units shorter than `minimum`, if one is configured.

    Bernard et al. (2024) Sect. 2.3 apply the equivalent constraint on mean building levels,
    reporting that without it GeoClimate produced LCZ 1 across European cities where no urban
    researcher would place any. Off by default here: lczkit has no reliable storey count, so this
    reaches for `Hr` instead, and applying an untested constraint by default would be a worse
    failure than the over-prediction it guards against.

    A null height never triggers the drop - the constraint is evidence of shortness, not absence
    of evidence of tallness.
    """
    if minimum is None or lcz1 not in distances.columns:
        return distances
    too_short = (height_of_roughness_elements_m < minimum).fillna(False)
    result = distances.copy()
    result.loc[too_short, lcz1] = np.nan
    return result
