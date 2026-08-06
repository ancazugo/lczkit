"""Running the height tiers in order, and recording what each one managed.

The report is the point. A cascade that fills every building silently is indistinguishable from
one that fell all the way through to a 100 m raster, and CLAUDE.md is explicit that those two
outcomes must not look the same in the output.
"""

from __future__ import annotations

from collections.abc import Sequence

import geopandas as gpd
import numpy as np
from pydantic import BaseModel, Field

from lczkit.heights.tiers import prepare
from lczkit.protocols import HeightSource

UNRESOLVED = "unresolved"
"""`height_source` tag for a building no tier could resolve. Its `height` stays null."""


class HeightTierResult(BaseModel):
    """What one tier contributed to one cascade run."""

    tier: str
    n_candidates: int
    """Buildings still unresolved when this tier ran."""

    n_filled: int
    """Buildings this tier resolved."""

    filled_by_source: dict[str, int] = Field(default_factory=dict)
    """Breakdown by `height_source` tag, for tiers that resolve rows by more than one route."""


class HeightFillReport(BaseModel):
    """The full record of one `fill_heights()` run, for the output manifest."""

    n_buildings: int
    n_resolved: int
    n_unresolved: int
    tiers: list[HeightTierResult] = Field(default_factory=list)
    height_sources: list[str] = Field(default_factory=list)
    """Every tag the configured cascade could emit, in tier order, ending with `"unresolved"`.
    Downstream stages use this as the fixed column set for per-unit tier fractions, so the
    output schema depends on the configured cascade rather than on which tiers happened to fire.
    """


def cascade_height_sources(tiers: Sequence[HeightSource]) -> list[str]:
    """Every `height_source` tag `tiers` can emit, in order, plus `"unresolved"`."""
    return [source for tier in tiers for source in tier.height_sources] + [UNRESOLVED]


def fill_heights(
    buildings: gpd.GeoDataFrame, tiers: Sequence[HeightSource]
) -> tuple[gpd.GeoDataFrame, HeightFillReport]:
    """Run `tiers` in order over `buildings`, returning the filled layer and a report.

    Every returned row carries `height_source` and `height_confidence`. Rows no tier resolved
    are tagged `"unresolved"` with a null `height` rather than raising: with a tier's product
    simply absent from disk — the normal state of tiers 2-4 — refusing to return would make the
    package unusable where it should instead be honest. Callers that need completeness should
    read it off the report or off `height_completeness` per unit.

    `buildings` is not mutated.
    """
    out = prepare(buildings)
    results: list[HeightTierResult] = []

    for tier in tiers:
        pending = out["height_source"].isna()
        out = tier.fill(out)
        newly = pending & out["height_source"].notna()
        results.append(
            HeightTierResult(
                tier=tier.name,
                n_candidates=int(pending.sum()),
                n_filled=int(newly.sum()),
                filled_by_source={
                    str(source): int(count)
                    for source, count in out.loc[newly, "height_source"].value_counts().items()
                },
            )
        )

    unresolved = out["height_source"].isna()
    out.loc[unresolved, "height"] = np.nan
    out.loc[unresolved, "height_source"] = UNRESOLVED

    report = HeightFillReport(
        n_buildings=len(out),
        n_resolved=int(len(out) - unresolved.sum()),
        n_unresolved=int(unresolved.sum()),
        tiers=results,
        height_sources=cascade_height_sources(tiers),
    )
    return out, report
