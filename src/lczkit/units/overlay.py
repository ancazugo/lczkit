"""Overlaying a layer against the units: the one definition every per-unit area statistic uses.

Intersect once with `unit_pieces`, then select, sum and share over the pieces. A footprint
straddling a unit boundary contributes its share to each side, the same rule the height provenance
uses, so every fraction built here shares a denominator with `building_surface_fraction`.

`covered_fraction(dissolve=True)` clips first and dissolves per unit. A whole-layer `union_all` is
superlinear and raises `GEOSException: side location conflict` on real Overture land use even after
`make_valid`; the union of clipped pieces within a unit equals the clip of the global union, so the
bounded form is exact.
"""

from __future__ import annotations

from collections.abc import Sequence

import geopandas as gpd
import pandas as pd

from lczkit.units import check_units

PIECE_AREA = "piece_area"
"""Column `unit_pieces` measures each intersection into. Named rather than recomputed downstream so
two consumers of the same pieces cannot disagree about what area means."""


def unit_pieces(
    units: gpd.GeoDataFrame,
    layer: gpd.GeoDataFrame | gpd.GeoSeries,
    *,
    columns: Sequence[str] = (),
    keep_geom_type: bool = True,
) -> gpd.GeoDataFrame:
    """`layer` intersected with `units`, one row per (unit, feature) pair.

    Carries `unit_id`, the piece geometry, `piece_area`, and whichever of `columns` the layer has.
    Absent columns are skipped rather than raising, so a caller can ask for `height` and `subtype`
    without first checking which of them a hand-assembled layer happens to carry.

    The layer is reset positionally before the overlay. The building layers carry no uniqueness
    guarantee and `.loc[an_index]` over a duplicated one silently returns extra rows — a wrong
    number rather than an error — so nothing here selects by index.

    Returns an empty frame with the right columns when either side is empty, so callers branch on
    `.empty` and never on `None`.
    """
    # Checked here as well as in the blocks that call it. Everything below groups by `unit_id`, so
    # a frame indexed under another name fails several lines later with a `KeyError` naming a
    # column the caller never mentioned; a geographic CRS fails not at all, and silently reports
    # areas in square degrees.
    check_units(units)
    if isinstance(layer, gpd.GeoSeries):
        wanted: list[str] = []
        covering = gpd.GeoDataFrame(geometry=layer.reset_index(drop=True), crs=units.crs)
    else:
        wanted = [column for column in columns if column in layer.columns]
        name = layer.geometry.name
        covering = gpd.GeoDataFrame(
            layer[[*wanted, name]].reset_index(drop=True), geometry=name, crs=layer.crs
        )
        # `gpd.overlay` joins on the *active* geometry but the result keeps the left frame's
        # column name, so a right-hand layer whose geometry column is called something else still
        # works — renaming unconditionally does not, because geopandas refuses to rename a column
        # to the name it already has.
        if name != "geometry":
            covering = covering.rename_geometry("geometry")

    if units.empty or covering.empty:
        return _empty_pieces(units, wanted)

    pieces = gpd.overlay(
        units[["geometry"]].reset_index(),
        covering,
        how="intersection",
        keep_geom_type=keep_geom_type,
    )
    if pieces.empty:
        return _empty_pieces(units, wanted)
    return pieces.assign(**{PIECE_AREA: pieces.geometry.area})


def _empty_pieces(units: gpd.GeoDataFrame, columns: list[str]) -> gpd.GeoDataFrame:
    """An empty pieces frame carrying the columns a populated one would."""
    frame = gpd.GeoDataFrame(
        {
            "unit_id": pd.Series(dtype=units.index.dtype),
            **{column: pd.Series(dtype="object") for column in columns},
            PIECE_AREA: pd.Series(dtype="float64"),
        },
        geometry=gpd.GeoSeries([], crs=units.crs),
        crs=units.crs,
    )
    return frame


def area_in_units(units: gpd.GeoDataFrame, pieces: gpd.GeoDataFrame) -> pd.Series:
    """Total piece area per unit, zero where nothing reached the unit.

    Zero rather than null: "nothing of this layer is here" is a measurement, unlike a land-cover
    fraction over ground the raster never covered. Callers that need the undefined case — a share
    of a unit holding no buildings — mask it themselves, where the reason is visible.
    """
    zero = pd.Series(0.0, index=units.index, dtype="float64")
    if pieces.empty:
        return zero
    summed = pieces.groupby("unit_id")[PIECE_AREA].sum()
    return summed.reindex(units.index).fillna(0.0)


def covered_fraction(
    units: gpd.GeoDataFrame, pieces: gpd.GeoDataFrame, *, dissolve: bool
) -> pd.Series:
    """Share of each unit's area covered by `pieces`.

    `dissolve` unions the pieces within each unit first, so ground under two overlapping features
    counts once. Required wherever the source layer has no overlap resolution — `cleaning.land_use`
    applies `make_valid` and nothing else, and Milan's parcels sum to 106.6% of its bbox — and
    wrong to pay for where it does: `trim_overlaps` has already made `buildings_area` disjoint.

    Explicit rather than defaulted, because both mistakes are silent. Without it a fraction can
    exceed 1.0; with it unnecessarily, a run pays for a union nobody needed.
    """
    unit_area = units.geometry.area
    if pieces.empty:
        return pd.Series(0.0, index=units.index, dtype="float64")
    covered = (
        pieces.dissolve(by="unit_id").geometry.area
        if dissolve
        else pieces.groupby("unit_id")[PIECE_AREA].sum()
    )
    return covered.reindex(units.index).fillna(0.0).div(unit_area.where(unit_area > 0))


def share_of(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """`numerator / denominator`, null where the denominator is zero.

    The shape every "of what is built here, how much is X" column takes. Null rather than zero: a
    share of nothing is undefined, and reporting 0.0 tells a downstream rule that a cell definitely
    is not X rather than that there was nothing to judge.
    """
    return numerator.div(denominator.where(denominator > 0))
