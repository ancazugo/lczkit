"""The two rules that sit outside the distance metric, and why each has to.

Both exist because a dimension the LCZ scheme depends on is not in the parameter vector.

**The family gate.** Stewart & Oke separate LCZ A, B, C and D by sky view factor, aspect ratio and
height of roughness elements alone - all three building-derived, all three null or zero in open
ground - so once a unit has no buildings the natural classes collapse onto one point and the
built ones are the only thing left with any spread. Bernard et al. (2024) avoid this by deciding
land cover first and running the closest-distance approach only over the built types (Sect. 2.3,
Figs. 2-3). The gate is the same idea in one threshold: below a building surface fraction the
published table itself treats as the built/natural boundary, a unit is compared against the
natural prototypes and never against the built ones.

**LCZ 10.** Large low-rise and heavy industry are geometrically near-identical - large footprint,
low, sparse - and the only published property separating them is anthropogenic heat output, at 300+
W m-2 against at most 50, which nothing in open vector or raster data measures. So a functional
attribute has to break the tie. CLAUDE.md is explicit that it must be applied *after* the distance
and never folded into the metric, where a functional attribute would silently distort every other
class.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

Family = str
"""`"built"` or `"natural"`."""

BUILT = "built"
NATURAL = "natural"

ROUTE_BUILT = "distance_built"
ROUTE_NATURAL = "distance_natural"
ROUTE_INDUSTRIAL = "industrial_rule"

ROUTES: tuple[str, ...] = (ROUTE_BUILT, ROUTE_NATURAL, ROUTE_INDUSTRIAL)
"""Every value `label_route` can take. A fixed vocabulary so the column is a stable category."""


def family_of(building_surface_fraction: pd.Series, threshold: float) -> pd.Series:
    """`"built"` where the building surface fraction reaches `threshold`, else `"natural"`.

    `building_surface_fraction` is never null - Phase 5 reports 0.0, not NaN, for a unit holding
    no buildings, precisely because "no buildings here" is a measurement - so the gate is defined
    for every unit and no unit goes unclassified for want of it.
    """
    if building_surface_fraction.isna().any():
        raise ValueError(
            "building_surface_fraction contains nulls; Phase 5 reports 0.0 for a unit with no "
            "buildings, so a null here means the parameter table was not produced by "
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


def apply_lcz10_rule(
    ranked: Ranked,
    industrial_fraction: pd.Series,
    threshold: float,
    *,
    lcz8: int = 8,
    lcz10: int = 10,
) -> tuple[Ranked, pd.Series]:
    """Prefer LCZ 10 over LCZ 8 where the unit is predominantly industrial.

    Fires where the nearest prototype is LCZ 8, the runner-up is LCZ 10 and `industrial_fraction`
    exceeds `threshold`. The two ranks are then swapped as a pair, so the reported
    `min_distance` stays the distance to the class actually reported and the runner-up becomes
    the morphological answer the rule displaced - which is more useful than nulling it, since it
    says precisely what would have been emitted without the industrial evidence.

    A unit already nearest LCZ 10 does not "fire": the flag means the rule *changed* the label,
    which is the question a reader has when they see LCZ 10 on a map.

    A null `industrial_fraction` never fires the rule. Phase 5 reports 0.0 rather than null for a
    unit with no industrial evidence, so a null means the layer was missing entirely - a reason to
    leave the morphological answer alone, not to override it.
    """
    fired = (
        (ranked.primary == lcz8)
        & (ranked.secondary == lcz10)
        & (industrial_fraction > threshold).fillna(False)
    )
    swapped = Ranked(
        primary=ranked.primary.where(~fired, ranked.secondary),
        secondary=ranked.secondary.where(~fired, ranked.primary),
        closest=ranked.closest.where(~fired, ranked.runner_up),
        runner_up=ranked.runner_up.where(~fired, ranked.closest),
    )
    return swapped, fired


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
