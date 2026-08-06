"""`aggregate()`: move attribute columns between two unit systems via an area overlay."""

from __future__ import annotations

from typing import Literal

import geopandas as gpd
import pandas as pd

from lczkit.crs import assert_projected_crs

AggregateMethod = Literal["majority", "area_weighted"]


def aggregate(
    from_units: gpd.GeoDataFrame,
    to_units: gpd.GeoDataFrame,
    method: AggregateMethod,
) -> gpd.GeoDataFrame:
    """Move every non-geometry column of `from_units` onto `to_units`' polygons.

    Both must be indexed by `unit_id`, in the same projected CRS — typically both are outputs
    of a `SpatialUnitStrategy.generate()` call, with `from_units` carrying attribute columns
    already joined onto it elsewhere in the pipeline. This function is a geometric overlay plus
    a column-wise reduction; it does not compute any parameter itself.

    `"majority"`: every column takes the value from whichever `from_units` polygon overlaps a
    given `to_units` polygon by the largest area. Works for any column dtype.
    `"area_weighted"`: every *numeric* column becomes the area-weighted mean across overlapping
    `from_units` polygons; non-numeric columns are dropped (there is no defined mean of a
    string) rather than silently guessing a reducer for them.

    `to_units` rows with no overlapping `from_units` polygon get null attribute values.
    """
    assert_projected_crs(from_units, "from_units")
    assert_projected_crs(to_units, "to_units")
    if from_units.crs != to_units.crs:
        raise ValueError(f"from_units.crs ({from_units.crs}) != to_units.crs ({to_units.crs})")
    if from_units.index.name != "unit_id" or to_units.index.name != "unit_id":
        raise ValueError("both from_units and to_units must be indexed by unit_id")

    value_cols = [c for c in from_units.columns if c != "geometry"]

    left = to_units[["geometry"]].reset_index().rename(columns={"unit_id": "to_id"})
    right = (
        from_units[[*value_cols, "geometry"]].reset_index().rename(columns={"unit_id": "from_id"})
    )
    pieces = gpd.overlay(left, right, how="intersection")
    pieces["overlap_area"] = pieces.geometry.area
    pieces = pieces[pieces["overlap_area"] > 0]
    if pieces.empty:
        raise ValueError("from_units and to_units do not overlap with positive area")

    agg: pd.DataFrame
    if method == "majority":
        idx = pieces.groupby("to_id")["overlap_area"].idxmax()
        agg = pd.DataFrame(pieces.loc[idx].set_index("to_id")[value_cols])
    elif method == "area_weighted":
        numeric_cols = [c for c in value_cols if pd.api.types.is_numeric_dtype(from_units[c])]
        if not numeric_cols:
            raise ValueError("area_weighted requires at least one numeric column in from_units")
        weighted = pieces[numeric_cols].multiply(pieces["overlap_area"], axis=0)
        weighted["to_id"] = pieces["to_id"]
        sums = weighted.groupby("to_id").sum()
        area_sums = pieces.groupby("to_id")["overlap_area"].sum()
        agg = sums[numeric_cols].div(area_sums, axis=0)
    else:
        raise ValueError(f"Unknown aggregate method: {method!r}")

    joined = to_units[["geometry"]].join(agg, how="left")
    result = gpd.GeoDataFrame(joined, geometry="geometry", crs=to_units.crs)
    result.index.name = "unit_id"
    return result
