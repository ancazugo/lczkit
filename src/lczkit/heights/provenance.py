"""Reading per-attribute provenance out of Overture's `sources` column.

Overture records provenance per *attribute*, not just per feature. Each entry in `sources`
carries a `property` naming what it applies to — `''` for the footprint as a whole, or a JSON
pointer such as `/properties/height` for one attribute — alongside the `dataset` it came from
and, for machine-derived values, a `confidence`.

That distinction is load-bearing here, and it contradicts CLAUDE.md's Phase 1 description of
Overture conflation as winner-takes-all with no attribute fusion. In release `2026-07-22.0`,
394 of the 6195 footprints in the Berlin test fixture are OSM-won yet carry a `height`
attributed to Microsoft ML Buildings — a quarter of every tier-1 height in that extent. Grouping
provenance by the footprint's dataset alone would report those as surveyed OSM heights.

These two functions are the single parser for that column; the tier-1 height source and the
source-availability diagnostic both read through them rather than each growing their own.
"""

from __future__ import annotations

from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

FOOTPRINT_PROPERTY = ""
"""`sources[].property` value marking the entry that describes the feature as a whole."""

HEIGHT_PROPERTY = "/properties/height"
"""`sources[].property` value marking the entry that describes the `height` attribute."""


def _entry_for(sources: Any, wanted: str) -> dict[str, Any] | None:
    if sources is None or isinstance(sources, float):  # null column value
        return None
    for entry in sources:
        if not isinstance(entry, dict):
            continue
        prop = entry.get("property") or FOOTPRINT_PROPERTY
        if prop == wanted:
            return entry
    return None


def footprint_datasets(buildings: gpd.GeoDataFrame) -> pd.Series:
    """The upstream dataset that won each footprint's geometry, as a string Series.

    Null where the row carries no whole-feature provenance entry, and for every row when
    `buildings` has no `sources` column at all — a non-Overture `VectorSource` degrades to "no
    provenance known" rather than raising.
    """
    if "sources" not in buildings.columns:
        return pd.Series(pd.NA, index=buildings.index, dtype="object")
    return buildings["sources"].map(
        lambda s: (_entry_for(s, FOOTPRINT_PROPERTY) or {}).get("dataset")
    )


def height_attribution(buildings: gpd.GeoDataFrame) -> tuple[pd.Series, pd.Series]:
    """`(dataset, confidence)` describing where each row's `height` value came from.

    Where Overture records a `/properties/height` provenance entry, both come from it — this is
    the case that separates a conflated machine-learning height from a surveyed one, and the
    `confidence` is a real per-building number rather than anything this package assigns.

    Where it does not, the dataset falls back to the footprint's own and the confidence is null:
    the height, if any, came in with the footprint, and Overture attaches no confidence to it.
    """
    footprint = footprint_datasets(buildings)
    if "sources" not in buildings.columns:
        return footprint, pd.Series(np.nan, index=buildings.index, dtype="float64")

    entries = buildings["sources"].map(lambda s: _entry_for(s, HEIGHT_PROPERTY))
    dataset = entries.map(lambda e: (e or {}).get("dataset")).fillna(footprint)
    confidence = pd.to_numeric(
        entries.map(lambda e: (e or {}).get("confidence")), errors="coerce"
    ).astype("float64")
    return dataset, confidence
