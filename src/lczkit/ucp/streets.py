"""Per-unit street canyon geometry, from `momepy.street_profile()`.

CLAUDE.md names this function specifically. It measures along perpendicular ticks cast at a fixed
spacing from every street segment, so its output is per *segment*; getting to per *unit* is a
length-weighted mean over the parts of each segment that fall inside the unit.

That weighting is what makes the two unit strategies behave sensibly with one implementation. For
`GridUnits` a segment is cut where it crosses a cell boundary and each cell gets the piece it
contains. For `EnclosureUnits` the streets *are* the boundaries — `momepy.enclosures()` polygonises
the same linework — so a segment lies on the shared edge of two enclosures and is counted for both.
That is the right answer rather than a leak: a street canyon belongs to the fabric on both of its
sides.
"""

from __future__ import annotations

import geopandas as gpd
import momepy
import numpy as np
import pandas as pd

from lczkit.config import UcpConfig
from lczkit.crs import assert_projected_crs
from lczkit.units import check_units

COLUMNS = ("aspect_ratio", "street_openness", "street_width_m")

#: momepy's per-segment column names, and what this package calls them.
_RENAMES = {"hw_ratio": "aspect_ratio", "openness": "street_openness", "width": "street_width_m"}


def street_metrics(
    streets: gpd.GeoDataFrame,
    buildings: gpd.GeoDataFrame,
    units: gpd.GeoDataFrame,
    config: UcpConfig,
) -> pd.DataFrame:
    """Per-unit `aspect_ratio`, `street_openness` and `street_width_m`, indexed by `unit_id`.

    `buildings` must carry `height`. Buildings the Phase 3 cascade left unresolved keep a null
    height; momepy skips them when averaging tick heights rather than propagating the null, so a
    partially resolved cascade degrades the aspect ratio's *coverage* rather than corrupting its
    value.

    A unit crossed by no street is null on all three. A unit crossed by streets that reach no
    building is null on `aspect_ratio` only — momepy still reports a width (the tick length, as a
    theoretical maximum) and an openness of 1.0 there, which are real statements about an open
    street, whereas the height-to-width ratio of a canyon with no walls is not.
    """
    check_units(units)
    if streets.empty or buildings.empty:
        return _all_null(units.index)
    assert_projected_crs(streets, "streets")
    assert_projected_crs(buildings, "buildings")
    for name, layer in (("streets", streets), ("buildings", buildings)):
        if layer.crs != units.crs:
            raise ValueError(f"{name}.crs ({layer.crs}) != units.crs ({units.crs})")
    if "height" not in buildings.columns:
        raise ValueError(
            "buildings has no height column; run lczkit.heights.cascade.fill_heights before "
            "computing urban canopy parameters."
        )

    profile = momepy.street_profile(
        streets,
        buildings,
        distance=config.street_profile_distance_m,
        tick_length=config.street_profile_tick_length_m,
        height=buildings["height"],
    )
    segments = gpd.GeoDataFrame(
        profile[list(_RENAMES)].rename(columns=_RENAMES).reset_index(drop=True),
        geometry=streets.geometry.reset_index(drop=True),
        crs=streets.crs,
    )

    pieces = gpd.overlay(
        units[["geometry"]].reset_index(), segments, how="intersection", keep_geom_type=False
    )
    pieces = pieces.assign(length=pieces.geometry.length)
    pieces = pieces[pieces["length"] > 0]
    if pieces.empty:
        return _all_null(units.index)

    # One weighted mean per column rather than one over the frame: a segment reaching no building
    # has a width and an openness but no aspect ratio, and dropping the whole segment would throw
    # away the two measurements it does carry.
    return pd.DataFrame({column: _weighted_mean(pieces, column, units.index) for column in COLUMNS})


def _weighted_mean(pieces: pd.DataFrame, column: str, index: pd.Index) -> pd.Series:
    """Street-length-weighted mean of `column`, over the pieces that carry a value for it."""
    usable = pieces.dropna(subset=[column])
    if usable.empty:
        return pd.Series(np.nan, index=index, dtype="float64")

    weight = usable["length"]
    grouped = (
        pd.DataFrame({"unit_id": usable["unit_id"], "w": weight, "wx": weight * usable[column]})
        .groupby("unit_id")[["w", "wx"]]
        .sum()
    )
    return (grouped["wx"] / grouped["w"].where(grouped["w"] > 0)).reindex(index)


def _all_null(index: pd.Index) -> pd.DataFrame:
    frame = pd.DataFrame(np.nan, index=index, columns=pd.Index(COLUMNS), dtype="float64")
    frame.index.name = "unit_id"
    return frame
