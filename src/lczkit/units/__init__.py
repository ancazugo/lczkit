"""Spatial-unit generation: `EnclosureUnits`, `GridUnits`, and `aggregate()` between them.

Also home to `check_units()`, the entry contract every stage keyed on `unit_id` enforces. It lives
with the definition of the unit of exchange rather than with any one consumer.
"""

from __future__ import annotations

import geopandas as gpd

from lczkit.crs import assert_projected_crs


def check_units(units: gpd.GeoDataFrame) -> None:
    """Raise unless `units` is projected, indexed by `unit_id`, and uniquely indexed.

    Same checks `aggregate()` and `height_metrics()` make inline, for the same reason: a geographic
    CRS makes every area meaningless, and a missing or duplicated `unit_id` index makes the join
    silently wrong rather than loud.
    """
    assert_projected_crs(units, "units")
    if units.index.name != "unit_id":
        raise ValueError("units must be indexed by unit_id")
    if not units.index.is_unique:
        raise ValueError("units index must be unique")


__all__ = ["check_units"]
