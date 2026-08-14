"""Per-unit building morphology: surface fraction, height moments, count, mean footprint.

Buildings are assigned to units two different ways here, deliberately. The surface fraction and
the height statistics split footprints at unit boundaries, so a building straddling two grid cells
reaches both; that is the rule `lczkit.heights.completeness.height_metrics()` already uses, and
using a second one would make `building_surface_fraction` and `height_completeness` describe
subtly different populations. Object quantities — the count and the mean footprint area — assign
each whole building to the unit containing its representative point, because half a building is
not a building and the mean area of a set of fragments is not the mean area of a set of buildings.

For `EnclosureUnits` the two agree almost everywhere: Phase 1's cross-layer topology already drops
buildings intersecting the streets that form enclosure boundaries. It is the 100 m grid where the
distinction bites.

Three height statistics come out of this module and only one of them is `Hr`. Stewart & Oke's
height of roughness elements is the **geometric** mean of building heights — Bernard et al. (2024)
Table 1 gives it as `exp(mean(log(h)))` — and the LCZ property ranges Phase 6 normalises against
were defined for that quantity. The arithmetic mean sits above it whenever a unit mixes tall and
short buildings, so substituting one for the other would bias exactly the heterogeneous units where
classification is hardest, and would do it silently. `h_mean_area_weighted` and `h_std` are
therefore shipped as **secondary** columns: the deferred roughness work (Macdonald, Kanda) needs
them, and classification must not use them.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd

from lczkit.cleaning.buildings import FEATURE_ID
from lczkit.config import UcpConfig
from lczkit.crs import assert_projected_crs
from lczkit.units import check_units

COLUMNS = (
    "building_surface_fraction",
    "height_of_roughness_elements_m",
    "h_geometric_area_weighted",
    "h_mean_area_weighted",
    "h_std",
    "building_count",
    "mean_building_area_m2",
)

#: Columns that are a real measurement rather than an absence when a unit holds no buildings.
#: "No buildings cover this unit" is 0.0 coverage and 0 buildings; the mean height and mean
#: footprint area of nothing are undefined and stay null.
_ZERO_WHEN_EMPTY = ("building_surface_fraction", "building_count")


def building_metrics(
    buildings: gpd.GeoDataFrame, units: gpd.GeoDataFrame, config: UcpConfig
) -> pd.DataFrame:
    """Per-unit building morphology, indexed by `unit_id` to match `units`.

    `buildings` must carry `height`, i.e. have been through
    `lczkit.heights.cascade.fill_heights()`. Buildings that cascade left unresolved keep a null
    height: they still count towards `building_surface_fraction`, `building_count` and
    `mean_building_area_m2`, because a footprint is observed whether or not its height is, but
    they are excluded from the height statistics rather than imputed.

    Neither input is mutated.
    """
    check_units(units)
    if buildings.empty:
        return _empty(units)
    assert_projected_crs(buildings, "buildings")
    if buildings.crs != units.crs:
        raise ValueError(f"buildings.crs ({buildings.crs}) != units.crs ({units.crs})")
    if "height" not in buildings.columns:
        raise ValueError(
            "buildings has no height column; run lczkit.heights.cascade.fill_heights before "
            "computing urban canopy parameters."
        )

    frame = pd.concat(
        [_area_metrics(buildings, units, config), _object_metrics(buildings, units)], axis=1
    )
    frame[list(_ZERO_WHEN_EMPTY)] = frame[list(_ZERO_WHEN_EMPTY)].fillna(0.0)
    frame["building_count"] = frame["building_count"].astype("int64")
    return frame[list(COLUMNS)]


def _area_metrics(
    buildings: gpd.GeoDataFrame, units: gpd.GeoDataFrame, config: UcpConfig
) -> pd.DataFrame:
    """Surface fraction and the three height statistics, over footprints split by unit."""
    columns = ["height", "geometry"]
    if FEATURE_ID in buildings.columns:
        columns.insert(0, FEATURE_ID)
    pieces = gpd.overlay(
        units[["geometry"]].reset_index(),
        buildings[columns].reset_index(drop=True),
        how="intersection",
    )
    unit_area = units.geometry.area
    if pieces.empty:
        return pd.DataFrame(
            {
                "building_surface_fraction": 0.0,
                "height_of_roughness_elements_m": np.nan,
                "h_geometric_area_weighted": np.nan,
                "h_mean_area_weighted": np.nan,
                "h_std": np.nan,
            },
            index=units.index,
        )

    pieces["piece_area"] = pieces.geometry.area
    covered = pieces.groupby("unit_id")["piece_area"].sum().reindex(units.index)
    fraction = covered.div(unit_area.where(unit_area > 0))

    heights = _height_stats(pieces.dropna(subset=["height"]), units.index, config)
    return pd.DataFrame({"building_surface_fraction": fraction, **heights})


def _height_stats(pieces: pd.DataFrame, index: pd.Index, config: UcpConfig) -> dict[str, pd.Series]:
    """`Hr` plus the two secondary height columns, over the buildings intersecting each unit.

    All three run over the same population — every building with a resolved height that overlaps
    the unit — so `Hr` is defined exactly where `h_mean_area_weighted` is, and the two are directly
    comparable.

    `Hr` is unweighted, one term per building, per Bernard et al. (2024) Table 1. The overlay gives
    one row per (unit, building) pair, so a building straddling a grid boundary enters both units'
    geometric means once each; assigning it to a single unit instead would leave `Hr` null in cells
    that are visibly built, which is the worse failure.

    **One building, one vote.** Phase 1's shared prefix explodes multipolygons before either layer
    forks, so a courtyard block or a multi-wing complex arrives here as N rows carrying one height.
    Left alone that is N equal terms in an unweighted mean of logs, which quietly weights a
    multi-part footprint N times against its single-part neighbours. Parts are therefore collapsed
    on `FEATURE_ID` first, taking one height per source feature per unit. Where the column is absent
    — a caller assembling buildings by hand — the collapse is skipped rather than guessed at.

    `h_geometric_area_weighted` is the same geometric mean with footprint area as the weight,
    shipped **secondary and unused by classification**. Bernard et al. Table 1 specifies the
    unweighted form and the Stewart & Oke ranges Phase 6 normalises against were defined for it, so
    substituting the weighted one would change the definition of `Hr` silently. It is emitted
    because the unweighted mean gives a 5 m² shed the same vote as a tower block, and Phase 10
    already established that `Hr`'s sensitivity to dispersion is what made the most accurate height
    product degrade the map — this column is what makes the size of that effect measurable without
    moving a published number.

    The remaining two secondaries are area-weighted, as a matched pair. The population (no Bessel
    correction) standard deviation is used because an area-weighted spread has no natural sample
    correction — the weights are areas, not observation counts — and because a unit holding one
    building should report a spread of zero rather than a null.
    """
    empty = pd.Series(np.nan, index=index, dtype="float64")
    if pieces.empty:
        return {
            "height_of_roughness_elements_m": empty,
            "h_geometric_area_weighted": empty.copy(),
            "h_mean_area_weighted": empty.copy(),
            "h_std": empty.copy(),
        }

    if FEATURE_ID in pieces.columns:
        # Sum the parts' areas and take their shared height once. `first` rather than a mean
        # because every part of one feature carries the same height by construction.
        pieces = (
            pieces.groupby(["unit_id", FEATURE_ID], observed=True)
            .agg(piece_area=("piece_area", "sum"), height=("height", "first"))
            .reset_index()
        )

    weight = pieces["piece_area"]
    height = pieces["height"]
    log_h = np.log(height.clip(lower=config.min_building_height_m))
    grouped = (
        pd.DataFrame(
            {
                "unit_id": pieces["unit_id"],
                "w": weight,
                "wh": weight * height,
                "wh2": weight * height**2,
                "w_log_h": weight * log_h,
                "log_h": log_h,
            }
        )
        .groupby("unit_id")
        .agg({"w": "sum", "wh": "sum", "wh2": "sum", "w_log_h": "sum", "log_h": "mean"})
    )

    total = grouped["w"].where(grouped["w"] > 0)
    mean = grouped["wh"] / total
    # Var(X) = E[X^2] - E[X]^2, clipped because catastrophic cancellation can drive a
    # single-height unit fractionally below zero.
    variance = (grouped["wh2"] / total - mean**2).clip(lower=0.0)
    geometric_weighted = pd.Series(
        np.exp((grouped["w_log_h"] / total).to_numpy()), index=grouped.index, dtype="float64"
    )
    return {
        "height_of_roughness_elements_m": np.exp(grouped["log_h"]).reindex(index),
        "h_geometric_area_weighted": geometric_weighted.reindex(index),
        "h_mean_area_weighted": mean.reindex(index),
        "h_std": np.sqrt(variance).reindex(index),
    }


def _object_metrics(buildings: gpd.GeoDataFrame, units: gpd.GeoDataFrame) -> pd.DataFrame:
    """Count and mean footprint area, over whole buildings assigned by representative point.

    Multi-part features are recombined first, on the same grounds as `Hr`: a courtyard block that
    arrived as a MultiPolygon is one building, and counting its wings separately inflates
    `building_count` while deflating `mean_building_area_m2` — the parameter that carries LCZ 8's
    "large, low, sparse" character. The parts are dissolved rather than merely counted once, so the
    reported area is the whole footprint and its representative point lies inside the whole.
    """
    if FEATURE_ID in buildings.columns and buildings[FEATURE_ID].duplicated().any():
        buildings = buildings.dissolve(by=FEATURE_ID, as_index=False)

    points = gpd.GeoDataFrame(
        {"footprint_area": buildings.geometry.area.to_numpy()},
        geometry=buildings.geometry.representative_point().to_numpy(),
        crs=buildings.crs,
    )
    joined = gpd.sjoin(points, units[["geometry"]].reset_index(), predicate="within")
    if joined.empty:
        return pd.DataFrame(
            {"building_count": 0.0, "mean_building_area_m2": np.nan}, index=units.index
        )

    grouped = joined.groupby("unit_id")["footprint_area"]
    return pd.DataFrame(
        {
            "building_count": grouped.size().reindex(units.index),
            "mean_building_area_m2": grouped.mean().reindex(units.index),
        }
    )


def _empty(units: gpd.GeoDataFrame) -> pd.DataFrame:
    frame = pd.DataFrame(np.nan, index=units.index, columns=pd.Index(COLUMNS), dtype="float64")
    frame[list(_ZERO_WHEN_EMPTY)] = 0.0
    frame["building_count"] = frame["building_count"].astype("int64")
    return frame
