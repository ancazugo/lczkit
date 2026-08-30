"""Within-unit height dispersion, per cascade tier — what an areal product costs `Hr`.

`height_completeness` says *where* a height came from. It says nothing about what the substitution
did to the shape of the height distribution inside a unit, and that is the quantity `Hr` is
sensitive to: it is a geometric mean, so it is depressed by spread and rises as spread collapses.

The sensitivity was established from one side. Google Open Buildings 2.5D had the lowest
per-building error of any tier and the only within-unit skill, and it **degraded** the map, because
its within-unit spread was 0.441 against reality's 0.195 — over half of it noise. A height tier is
therefore accepted on within-unit dispersion and not on mean absolute error.

This module measures the other side, which nothing has: the tiers that *were* adopted compress
dispersion rather than inflating it. Measured on the runs on disk, over units with buildings:

| dominant source | city | median `h_std` | median CV | constant units |
|---|---|---:|---:|---:|
| Overture `height` | Berlin | 1.52 m | **0.266** | 0.1% |
| WSF-3D | Nairobi | 0.88 m | **0.192** | 1.3% |
| WSF-3D | Bogota | 1.05 m | 0.207 | 1.1% |
| GHS-BUILT-H | Bogota | 0.36 m | **0.112** | **23.6%** |

A 90 m or 100 m product hands one height to every building it covers, so what survives inside a
unit is variation *between raster cells* rather than between buildings. Same mechanism, opposite
sign, and it biases `Hr` upward exactly where the cascade is doing the most work.

Reported per run because it is the target any future shrinkage work aims at: shrinking a
fine-resolution product toward the unit mean is only worth doing against a measured statement of
how much dispersion the incumbent has already lost.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from lczkit.heights.completeness import FRACTION_PREFIX


class TierDispersion(BaseModel):
    """Within-unit height spread across the units one tier dominates."""

    source: str
    """The `height_source` tag, e.g. `"wsf3d"`."""

    n_units: int
    """Units where this tier supplied more building area than any other."""

    median_h_std: float | None
    """Median of `h_std` — the area-weighted standard deviation of building height within a unit."""

    median_cv: float | None
    """Median of `h_std / h_mean_area_weighted`. The scale-free form, and the one comparable
    against the 0.441-against-0.195 figures above."""

    constant_fraction: float
    """Share of those units whose buildings all carry the same height to within a centimetre.
    A direct reading of how often the product resolves nothing inside a unit at all."""


class DispersionReport(BaseModel):
    """Within-unit height dispersion for one run, per tier."""

    min_building_surface_fraction: float
    """Units below this are excluded: a unit holding almost no building has a spread that is
    about its two buildings rather than about its fabric."""

    min_building_count: int
    """Units with fewer buildings are excluded, for the same reason. A spread over two buildings
    is not a description of a neighbourhood."""

    n_units: int
    """Units that passed both filters and carried a dispersion value."""

    tiers: list[TierDispersion] = Field(default_factory=list)


def dispersion_report(
    parameters: pd.DataFrame,
    *,
    min_building_surface_fraction: float = 0.05,
    min_building_count: int = 3,
) -> DispersionReport:
    """Within-unit height dispersion per tier, from a finished parameter table.

    `parameters` is what `lczkit.ucp.compute_parameters()` returns joined to the per-unit height
    fractions — the table a run assembles anyway — so this reads columns rather than
    recomputing anything, and it moves no measurement.

    A unit is attributed to whichever tier supplied the largest share of its building area, which
    is a simplification and is stated as one: a unit split evenly between Overture and WSF-3D is
    counted wholly against the larger. The alternative, area-weighting every unit into every tier,
    would mix distributions and defeat the comparison the table exists to make.
    """
    fractions = [column for column in parameters.columns if column.startswith(FRACTION_PREFIX)]
    empty = DispersionReport(
        min_building_surface_fraction=min_building_surface_fraction,
        min_building_count=min_building_count,
        n_units=0,
    )
    required = {"h_std", "h_mean_area_weighted", "building_surface_fraction", "building_count"}
    if not fractions or not required <= set(parameters.columns):
        return empty

    usable = parameters[
        (parameters["building_surface_fraction"] >= min_building_surface_fraction)
        & (parameters["building_count"] >= min_building_count)
        & parameters["h_std"].notna()
        & parameters[fractions].notna().any(axis=1)
    ]
    if usable.empty:
        return empty

    dominant = (
        usable[fractions]
        .fillna(0.0)
        .idxmax(axis=1)
        .astype("string")
        .str.removeprefix(FRACTION_PREFIX)
    )
    mean = usable["h_mean_area_weighted"]
    cv = usable["h_std"].div(mean.where(mean > 0))

    tiers: list[TierDispersion] = []
    for source, rows in usable.groupby(dominant.to_numpy(), sort=True):
        spread = rows["h_std"]
        tiers.append(
            TierDispersion(
                source=str(source),
                n_units=int(len(rows)),
                median_h_std=_finite(spread.median()),
                median_cv=_finite(cv.loc[rows.index].median()),
                constant_fraction=float((spread < 0.01).mean()),
            )
        )
    return DispersionReport(
        min_building_surface_fraction=min_building_surface_fraction,
        min_building_count=min_building_count,
        n_units=int(len(usable)),
        tiers=tiers,
    )


def _finite(value: float) -> float | None:
    """`None` rather than a NaN, so the manifest carries a null instead of an invalid JSON float."""
    return None if not np.isfinite(value) else float(value)
