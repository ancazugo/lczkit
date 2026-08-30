"""Overture's `subtype` and `class`, and how every functional parameter selects on them.

Ingestion reads these two attributes on every building and every land-use parcel, and cleaning is
test-pinned to retain them. Two parameter blocks select on them — `industrial_fraction` and the
semantic groups — so the vocabulary lives here rather than in whichever module happened to need
it first.

It lives here instead because three modules now read it: `ucp.industrial`, `ucp.semantics`, and
`ucp.buildings`, which carries the two attributes through its overlay so the other two can select
without intersecting the layer again.
"""

from __future__ import annotations

from collections.abc import Sequence

import geopandas as gpd
import pandas as pd

ATTRIBUTES = ("subtype", "class")
"""The two attributes every functional selection in this package reads.

Both, and either — Overture files most industrial buildings under `subtype='industrial'` *and*
`class='industrial'`, but the two are independently nullable and a feature carrying only one of
them is still industrial.
"""

UNKNOWN = "unknown"
"""Overture's sentinel for "no answer recorded", which is not a category.

Counting it as a tag would report coverage the data does not have, which is the exact failure
`building_tag_coverage` exists to prevent.
"""


def require_attributes(
    layer: gpd.GeoDataFrame, name: str, *, subtypes: Sequence[str], classes: Sequence[str]
) -> None:
    """Raise if the configuration selects on a column the layer does not carry.

    Checked against the layer, not against an overlay of it, so an extent where nothing intersects
    cannot turn a missing column into a silent zero.
    """
    if layer.empty:
        return
    for column, wanted in (("subtype", subtypes), ("class", classes)):
        if wanted and column not in layer.columns:
            raise ValueError(
                f"{name} has no {column!r} column, but ucp config selects features by it "
                f"({', '.join(wanted)}). Cleaning must retain subtype and class."
            )


def select_pieces(
    pieces: gpd.GeoDataFrame, *, subtypes: Sequence[str], classes: Sequence[str]
) -> gpd.GeoDataFrame:
    """The pieces whose `subtype` or `class` is one of the configured values.

    A boolean mask over pieces that already exist, so selecting a second group costs a comparison
    rather than a second intersection — which is what stops the parameter stage's cost growing with
    the number of configured semantic groups.

    Positional throughout. Neither building layer carries a uniqueness guarantee, and `.loc` by
    index over a duplicated one silently returns extra rows: a wrong number, not an error.
    """
    if pieces.empty:
        return pieces
    mask = pd.Series(False, index=pieces.index)
    for column, wanted in (("subtype", subtypes), ("class", classes)):
        if wanted and column in pieces.columns:
            mask |= pieces[column].isin(list(wanted))
    return pieces.loc[mask]


def tagged_pieces(pieces: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """The pieces carrying any usable `subtype` or `class`, i.e. neither null nor `unknown`.

    The numerator of `building_tag_coverage`, and the column that makes every other semantic
    fraction readable: a `lightweight` share of 0.0 in Nairobi is 94.8% of building area carrying
    no tag, not an absence of informal settlement.
    """
    if pieces.empty:
        return pieces
    mask = pd.Series(False, index=pieces.index)
    for column in ATTRIBUTES:
        if column in pieces.columns:
            values = pieces[column]
            mask |= values.notna() & (values.astype("string").str.lower() != UNKNOWN)
    return pieces.loc[mask]
