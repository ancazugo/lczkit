"""Computing the parameters on one unit set and moving them to another.

**The measurement this exists to answer.** A street canyon has to be measured against streets, and
a 100 m grid cell is not bounded by any. `momepy.street_profile` reports nothing for a cell no
street crosses, so `aspect_ratio` — 3 of the 17 applied weight units, and the only dimension
separating LCZ 8 from LCZ 3 and 6 — is simply null there. An enclosure is bounded *by* streets by
construction, so it almost always has one. Measured on one Istanbul extent, over built units:

| units | count | median area | `aspect_ratio` null | H/W median |
|---|---:|---:|---:|---:|
| 100 m grid | 455 538 | 1.00 ha | **10.8%** | 0.52 |
| enclosure | 111 293 | 0.42 ha | **0.9%** | 0.64 |
| patch | 10 943 | 10.12 ha | 0.2% | 0.57 |

And on the densest decile the difference is not only coverage but value: the grid gives a median
H/W of 0.93 with 70.2% inside LCZ 2's published band, the enclosures 1.03 with 82.2% inside it.

So the two unit systems are **complementary rather than rival**, which is not how the record has
treated them. An enclosure is a block and not an LCZ patch — median 0.42 ha against a So2Sat
patch's 10.24 — and has been rejected as a classification unit three times for that reason. It is
still the better thing to *measure* a canyon on. This module lets a run do both: compute on
enclosures, classify on whatever the caller asked for.

**No accuracy claim is attached and none is available.** CLAUDE.md's Phase 12 lever is unit
definition at a normalised compactness lift of 1.16 against height's 0.86, and the pre-registered
reading is that if this is the answer the **compactness lift falls toward 1.0**. Plain enclosures
as classification units *raised* it to 2.33, so a rise here is a refutation and not a success. That
sweep is a sweep and has not been run, which is why `UcpConfig.measure_on` defaults to `"units"`
and every stored figure remains comparable.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd

from lczkit.crs import assert_projected_crs

COVERAGE_COLUMN = "measurement_coverage"
"""Share of a target unit covered by the units the parameters were measured on.

Renamed from `aggregate.aggregate_coverage` on the way through, because in a run there is more than
one aggregation and this one has a specific meaning: how much of this cell was actually reached by
the enclosures its parameters came from. Below 1.0 means the enclosure partition did not cover the
cell — outside the barrier network, typically — and the parameters describe only the part it did.
"""


def transfer_parameters(
    parameters: pd.DataFrame,
    measurement_units: gpd.GeoDataFrame,
    target_units: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """Move a parameter table from the units it was measured on to the units to be classified.

    Numeric columns are moved **area-weighted** and non-numeric ones by **majority**, which is the
    only defensible pair: there is no mean of `industrial_evidence`, and taking the majority of a
    building surface fraction would throw away most of the cell. Both reducers run over one
    overlay, so a target unit's numeric and categorical answers describe the same overlap.

    **The weight is computed per column, over the pieces that carried a value.** That is not what
    `lczkit.units.aggregate` does — it divides by the total overlap area, so a piece contributing a
    null still enlarges the denominator and pulls the mean towards zero. Harmless where every
    column is populated, and wrong for the one column this module exists to move: `aspect_ratio` is
    null exactly where no street reached a building, which is a large minority of enclosures, and a
    cell must take the mean of the enclosures that *had* a canyon rather than a mean diluted by
    those that did not. `aggregate` is left alone because its normalisation is what every stored
    arm-B projection was computed under.

    Every result carries `measurement_coverage`. A target unit no measurement unit reaches is
    all-null rather than zero — the same rule the rest of the package applies to an unobserved
    quantity — and its coverage is null too.

    Neither input is mutated, and the result is indexed by `target_units`' `unit_id`.
    """
    if not parameters.index.equals(measurement_units.index):
        raise ValueError(
            "parameters and measurement_units must share an index; parameters must be the table "
            "compute_parameters() returned for those units"
        )
    assert_projected_crs(measurement_units, "measurement_units")
    assert_projected_crs(target_units, "target_units")
    if measurement_units.crs != target_units.crs:
        raise ValueError(
            f"measurement_units.crs ({measurement_units.crs}) != "
            f"target_units.crs ({target_units.crs})"
        )

    numeric = [
        column
        for column in parameters.columns
        if pd.api.types.is_numeric_dtype(parameters[column])
        and not pd.api.types.is_bool_dtype(parameters[column])
    ]
    other = [column for column in parameters.columns if column not in numeric]

    left = target_units[["geometry"]].reset_index().rename(columns={"unit_id": "to_id"})
    right = (
        measurement_units[["geometry"]]
        .join(parameters)
        .reset_index()
        .rename(columns={"unit_id": "from_id"})
    )
    pieces = gpd.overlay(left, right, how="intersection", keep_geom_type=False)
    pieces = pieces.assign(overlap_area=pieces.geometry.area)
    pieces = pieces[pieces["overlap_area"] > 0]

    frame = pd.DataFrame(index=target_units.index, columns=list(parameters.columns), dtype="object")
    frame.index.name = "unit_id"
    coverage = pd.Series(np.nan, index=target_units.index, dtype="float64")
    if pieces.empty:
        frame[COVERAGE_COLUMN] = coverage
        return frame[[*parameters.columns, COVERAGE_COLUMN]]

    area = pieces["overlap_area"]
    group = pieces["to_id"]
    for column in numeric:
        values = pd.to_numeric(pieces[column], errors="coerce")
        known = values.notna()
        weight = area.where(known)
        totals = pd.DataFrame({"to_id": group, "w": weight, "wx": weight * values}).groupby("to_id")
        summed = totals[["w", "wx"]].sum(min_count=1)
        frame[column] = (summed["wx"] / summed["w"].where(summed["w"] > 0)).reindex(
            target_units.index
        )
    if other:
        # Majority: the value of whichever measurement unit covers most of the target.
        dominant = pieces.loc[pieces.groupby("to_id")["overlap_area"].idxmax()].set_index("to_id")
        for column in other:
            frame[column] = dominant[column].reindex(target_units.index)

    target_area = target_units.geometry.area
    covered = area.groupby(group).sum().reindex(target_units.index)
    frame[COVERAGE_COLUMN] = covered.div(target_area.where(target_area > 0))
    return frame[[*parameters.columns, COVERAGE_COLUMN]].infer_objects()
