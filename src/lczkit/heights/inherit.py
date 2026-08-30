"""Carry resolved heights from one building layer onto another.

Cleaning produces two building layers from one source. The height cascade runs **once**, on
`buildings_area` — that is the complete population, and so the honest denominator for
`height_completeness` and for the source-availability diagnostic. `buildings_topo` still needs
heights, because `momepy.street_profile` measures a canyon's height-to-width ratio against the
buildings walling it, so the values have to reach it from somewhere.

Not by `building_id`. A dissolved `buildings_topo` feature keeps one arbitrary constituent's id,
and on the Berlin fixture that constituent is as likely to be an absorbed sub-20 m² shed as the
block that absorbed it — which would hand a perimeter block a garage's height. Largest overlap is
the correct rule and costs one overlay.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from lczkit.crs import assert_projected_crs

INHERITED_COLUMNS = ("height", "height_source", "height_confidence")
"""What the cascade produces per building, and therefore what travels."""


def inherit_heights(target: gpd.GeoDataFrame, source: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Give every `target` footprint the height of the `source` footprint it overlaps most.

    `source` must have been through `lczkit.heights.cascade.fill_heights()`. A `target` footprint
    overlapping no `source` footprint keeps a null height rather than being dropped or imputed:
    `street_profile` skips null-height buildings when averaging, so the aspect ratio's *coverage*
    degrades rather than its value. Neither input is mutated.
    """
    assert_projected_crs(target, "target")
    assert_projected_crs(source, "source")
    if target.crs != source.crs:
        raise ValueError(f"target.crs ({target.crs}) != source.crs ({source.crs})")
    missing = [column for column in INHERITED_COLUMNS if column not in source.columns]
    if missing:
        raise ValueError(
            f"source has no {', '.join(missing)}; run lczkit.heights.cascade.fill_heights on it "
            "before inheriting heights from it."
        )

    out = target.drop(columns=list(INHERITED_COLUMNS), errors="ignore").copy()
    if out.empty or source.empty:
        return out.assign(**dict.fromkeys(INHERITED_COLUMNS, None))

    pieces = gpd.overlay(
        out[["geometry"]].reset_index(names="_target"),
        source[[*INHERITED_COLUMNS, "geometry"]].reset_index(drop=True),
        how="intersection",
        keep_geom_type=True,
    )
    if pieces.empty:
        return out.assign(**dict.fromkeys(INHERITED_COLUMNS, None))

    # `idxmax` then `.loc`, rather than a groupby aggregation: `first`/`last` skip nulls per
    # column, so a target whose largest overlap is an unresolved building would silently inherit
    # a smaller neighbour's height instead of staying null. That is imputation, which the cascade
    # refuses — an unresolved height is information about the data, not a gap to be filled.
    pieces["_overlap"] = pieces.geometry.area
    winners = pieces.loc[pieces.groupby("_target")["_overlap"].idxmax()].set_index("_target")
    for column in INHERITED_COLUMNS:
        out[column] = pd.Series(winners[column]).reindex(out.index)
    return out
