"""The reference LCZ map, reduced to one label per spatial unit.

The comparator map is the Demuzere global LCZ map, compared on the 100 m grid. The
reduction that needs is areal class fractions per unit followed by the majority - which is
exactly what `LocalRasterSource` already does for land cover, down to the CRS handling, the
covering window, the exact cell weighting and the nodata policy. So the reference map is described
as a `LandCoverDatasetConfig` and read through that source rather than growing a second
`exactextract` path that could drift from the first.

The one adaptation is that nodata is assigned to its own class instead of being excluded, so the
fractions still say how much of each unit the reference map reaches. Without that a unit lying
half outside the map would report a confident majority computed from a corner of itself, and the
agreement statistics would quietly include it.

**"The 100 m grid" describes lczkit's units, not the reference.**
`lcz_v3.tif` is distributed in EPSG:4326 at 0.000898315 degrees, which is ~100 m north-south and
100 m east-west only at the equator: at Berlin's latitude the cells are **60.9 m** wide, at
Rotterdam 61.7 m, at Hong Kong 92.5 m. The lczkit unit is a 100 m square in a projected CRS, so the
two grids share neither an origin nor an east-west cell size, and each unit takes the areal-majority
label over roughly one-and-a-half reference cells across by one down.

Nothing here is approximated by that - units are reprojected into the raster's CRS rather than
warping a categorical raster, and `exactextract` weights each cell by its exact covered fraction.
But the majority is a *reduction*, and `reference_majority_fraction` reports how decisively it was
won. A unit whose winner holds 0.34 of the observed area is close to a coin toss between three
classes and is currently weighted the same as one holding 1.0.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from lczkit.classify.labels import CODES
from lczkit.config import LandCoverDatasetConfig
from lczkit.landcover.local import LocalRasterSource
from lczkit.units import check_units

NODATA_CLASS = "nodata"
"""Class name the reference dataset config assigns unmapped/nodata cells to."""

COLUMNS = ("reference_lcz", "reference_coverage", "reference_majority_fraction")


def reference_lcz(
    units: gpd.GeoDataFrame,
    path: Path,
    config: LandCoverDatasetConfig,
    *,
    max_raster_cells: int = 200_000_000,
) -> pd.DataFrame:
    """The majority reference class per `unit_id`, with how well it is supported.

    Returns three columns:

    - `reference_lcz` - the integer code covering most of the unit, or null where the reference
      map covers none of it. Nullable `Int8`, never a sentinel: "the reference does not reach
      here" and "the reference says class 0" must not look the same.
    - `reference_coverage` - fraction of the unit the reference map actually observed.
    - `reference_majority_fraction` - fraction of the *observed* part the majority class holds.
      A unit split evenly between two classes agrees with whichever it is compared against about
      half the time, and that is worth knowing before reading a confusion matrix.

    Neither input is mutated.
    """
    check_units(units)
    if config.nodata_class != NODATA_CLASS:
        raise ValueError(
            f"reference dataset must assign nodata to a {NODATA_CLASS!r} class so unit coverage "
            f"is measurable; got nodata_class={config.nodata_class!r}"
        )

    fractions = LocalRasterSource(config, path, max_raster_cells=max_raster_cells).fractions(units)
    class_columns = [f"{config.column_prefix}lcz_{code}" for code in CODES]
    nodata_column = f"{config.column_prefix}{NODATA_CLASS}"

    observed = 1.0 - fractions[nodata_column]
    shares = fractions[class_columns]
    best = shares.max(axis=1)
    # `idxmax` would return a column name and a spurious winner for an all-zero row, so the
    # position is taken directly and masked where nothing was observed at all.
    winner = pd.Series(
        np.asarray(CODES)[shares.to_numpy(dtype="float64", na_value=0.0).argmax(axis=1)],
        index=fractions.index,
        dtype="float64",
    ).where(best > 0)

    return pd.DataFrame(
        {
            "reference_lcz": winner.astype("Int8"),
            "reference_coverage": observed,
            "reference_majority_fraction": best.div(observed.where(observed > 0)),
        },
        index=units.index,
    )
