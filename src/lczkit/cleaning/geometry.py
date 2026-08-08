"""Geometry helpers shared by more than one cleaning operation.

Small by design. Anything here is used by both `buildings` and `topology`, and putting it in
either would give the two modules a dependency direction neither wants.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import shapely


def largest_part(geometry: gpd.GeoSeries) -> gpd.GeoSeries:
    """Reduce each geometry to its single largest polygon part.

    Subtracting something from a footprint can split it in two — a building a road crosses end to
    end, or one whose neighbour is subtracted through the middle. Keeping both parts would turn one
    building into two in `building_count` and give a `building_id` two rows; keeping the largest
    keeps the feature a feature. A geometry the subtraction emptied has no parts and comes back
    missing, for the caller to drop.
    """
    parts, origin = shapely.get_parts(geometry.to_numpy(), return_index=True)
    if len(parts) == 0:
        empty = pd.Series(index=geometry.index, dtype="object")
        return gpd.GeoSeries(empty, crs=geometry.crs)
    winners = pd.DataFrame({"origin": origin, "area": shapely.area(parts)})
    picked = winners.groupby("origin")["area"].idxmax()
    largest = pd.Series(parts[picked.to_numpy()], index=geometry.index[picked.index])
    return gpd.GeoSeries(largest.reindex(geometry.index), crs=geometry.crs)
