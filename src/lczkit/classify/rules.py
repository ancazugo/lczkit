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

**The rule is functional, not a pair gate, and the difference was measured.** The original design
swapped LCZ 10 in only where it was already the runner-up behind LCZ 8. That was **measured inert
on the Rotterdam fixture at every threshold from 0.05 to 0.5**: 671 cells of working port, 254
industrial buildings, three quarters of cells over 90% industrial by area, 88 placed in LCZ 10 by
the reference - and the pair never opened once. Port plots are large and sparsely built, so
building surface fraction lands them on LCZ 9 and LCZ 10 is nowhere near second. The threshold was
never the binding constraint, so no amount of tuning it could have helped.

Following Bernard et al. (2024), LCZ 10 is therefore **removed from the distance metric entirely**
and assigned functionally. Its distance is still computed and reported in the seventeen-way vector
- CLAUDE.md requires the full vector, and a class that is unreachable *by selection* is exactly
what the manifest's `unreachable_classes` field exists to record - but it can no longer win an
argmin, so the only route to LCZ 10 is the industrial evidence.

Note the asymmetry with LCZ 8, which is a deliberate divergence from Bernard, who excludes both.
LCZ 8's defining character - large, low, sparse buildings - is genuinely morphological, so it stays
in the metric. Excluding it would leave it assignable only functionally, which is worse.
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
    lcz10: int = 10,
) -> tuple[Ranked, pd.Series]:
    """Assign LCZ 10 wherever the industrial evidence exceeds `threshold`, whatever the morphology.

    Functional assignment, not a swap between two candidates the metric already liked. LCZ 10 is
    not in the built prototype set at all, so this is the only thing that can produce it: a unit
    over the threshold becomes LCZ 10 regardless of where the distance placed it, which is the
    point - the measured failure of the previous rule was that the port cells it was meant to
    catch were nowhere near LCZ 10 in the metric.

    The displaced morphological answer is preserved as `secondary`, so the output still says
    precisely what would have been emitted without the industrial evidence, and `runner_up` moves
    with it - it becomes the distance to that displaced class, keeping the invariant that
    `runner_up` is the distance to `secondary`.

    `closest` becomes null for a fired unit. LCZ 10 is outside the metric, so no distance to it is
    defined, and carrying the displaced class's distance under a column called `min_distance` would
    be a quiet lie about a label that was never measured by distance at all. `uniqueness` follows
    the same null: a margin between the two nearest prototypes is a property of the metric, and a
    functional assignment did not come from it.

    A null `industrial_fraction` never fires the rule. The unit-area share is 0.0 rather than null
    where there is no evidence, so a null means either that the layer was missing entirely or -
    for the building-area share, which is the default column - that the unit holds no buildings to
    judge. Neither is grounds for calling it heavy industry.
    """
    fired = (industrial_fraction > threshold).fillna(False)
    return (
        Ranked(
            primary=ranked.primary.where(~fired, lcz10),
            secondary=ranked.secondary.where(~fired, ranked.primary),
            closest=ranked.closest.where(~fired),
            runner_up=ranked.runner_up.where(~fired, ranked.closest),
        ),
        fired,
    )


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
