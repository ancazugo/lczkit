"""`industrial_fraction` — the one functional attribute in the parameter table.

It exists because LCZ 8 (large low-rise) and LCZ 10 (heavy industry) are geometrically
near-identical: large footprint, low, sparse. Nothing in morphology or land cover separates a
distribution warehouse from a refinery, so without a functional signal LCZ 10 is unreachable and
the package would silently never emit it. Phase 6 applies this *after* the prototype distance, as
an explicit rule — it is deliberately not folded into the morphological metric, where it would
distort every other class.

Two evidence sources, combined by union: industrial building footprints are dissolved together
with industrial land-use parcels before the area is measured, so a factory standing inside an
industrial parcel counts once rather than twice. The two sources therefore reinforce each other's
*coverage* without inflating the magnitude. Each source's own fraction ships alongside the
combined one, together with `industrial_evidence` naming which contributed — CLAUDE.md requires
that, and the two are very differently reliable.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from lczkit.config import UcpConfig
from lczkit.crs import assert_projected_crs
from lczkit.units import check_units

COLUMNS = (
    "industrial_fraction",
    "industrial_fraction_buildings",
    "industrial_fraction_land_use",
    "industrial_evidence",
)

EVIDENCE = ("none", "buildings", "land_use", "both")
"""Fixed category set for `industrial_evidence`, so the output schema does not depend on which
evidence a given city happens to carry."""


def industrial_metrics(
    buildings: gpd.GeoDataFrame,
    land_use: gpd.GeoDataFrame,
    units: gpd.GeoDataFrame,
    config: UcpConfig,
) -> pd.DataFrame:
    """Per-unit industrial area shares and evidence, indexed by `unit_id` to match `units`.

    Every column is zero rather than null where nothing industrial is present: unlike a land-cover
    fraction, which can be genuinely unobserved, "no industrial feature covers this unit" is a
    measurement. Neither input is mutated.
    """
    check_units(units)
    for name, layer in (("buildings", buildings), ("land_use", land_use)):
        if layer.empty:
            continue
        assert_projected_crs(layer, name)
        if layer.crs != units.crs:
            raise ValueError(f"{name}.crs ({layer.crs}) != units.crs ({units.crs})")

    from_buildings = _select(
        buildings,
        "buildings",
        subtypes=config.industrial_building_subtypes,
        classes=config.industrial_building_classes,
    )
    from_land_use = _select(
        land_use,
        "land_use",
        subtypes=config.industrial_land_use_subtypes,
        classes=config.industrial_land_use_classes,
    )

    combined = gpd.GeoSeries(
        pd.concat([from_buildings, from_land_use], ignore_index=True), crs=units.crs
    )

    building_share = _covered_fraction(from_buildings, units)
    land_use_share = _covered_fraction(from_land_use, units)
    union_share = _covered_fraction(combined, units, dissolve=True)

    evidence = pd.Series("none", index=units.index, dtype="object")
    evidence[building_share > 0] = "buildings"
    evidence[land_use_share > 0] = "land_use"
    evidence[(building_share > 0) & (land_use_share > 0)] = "both"

    frame = pd.DataFrame(
        {
            "industrial_fraction": union_share,
            "industrial_fraction_buildings": building_share,
            "industrial_fraction_land_use": land_use_share,
            "industrial_evidence": pd.Categorical(evidence, categories=EVIDENCE),
        }
    )
    frame.index.name = "unit_id"
    return frame


def _select(
    layer: gpd.GeoDataFrame, name: str, *, subtypes: list[str], classes: list[str]
) -> gpd.GeoSeries:
    """Geometries of `layer` whose `subtype` or `class` is configured as industrial.

    Matching on either attribute rather than both: Overture files most industrial buildings under
    `subtype='industrial'` *and* `class='industrial'`, but the two are independently nullable and
    a feature carrying only one of them is still industrial.
    """
    if layer.empty:
        return gpd.GeoSeries([], crs=layer.crs, dtype="geometry")

    mask = pd.Series(False, index=layer.index)
    for column, wanted in (("subtype", subtypes), ("class", classes)):
        if not wanted:
            continue
        if column not in layer.columns:
            raise ValueError(
                f"{name} has no {column!r} column, but ucp config selects industrial features by "
                f"it ({', '.join(wanted)}). Phase 1 cleaning must retain subtype and class."
            )
        mask |= layer[column].isin(wanted)
    return gpd.GeoSeries(layer.geometry[mask], crs=layer.crs)


def _covered_fraction(
    geometries: gpd.GeoSeries, units: gpd.GeoDataFrame, *, dissolve: bool = False
) -> pd.Series:
    """Share of each unit's area covered by `geometries`.

    With `dissolve`, overlapping inputs are unioned first so shared area is counted once — which
    is the whole point of combining the two evidence sources this way. Without it the inputs come
    from a single layer, where Phase 1's planar enforcement has already removed the overlaps.
    """
    unit_area = units.geometry.area
    zero = pd.Series(0.0, index=units.index, dtype="float64")
    if geometries.empty:
        return zero

    if dissolve:
        covering = gpd.GeoDataFrame(geometry=gpd.GeoSeries([geometries.union_all()], crs=units.crs))
    else:
        covering = gpd.GeoDataFrame(geometry=geometries.reset_index(drop=True))

    pieces = gpd.overlay(units[["geometry"]].reset_index(), covering, how="intersection")
    if pieces.empty:
        return zero

    covered = pieces.assign(area=pieces.geometry.area).groupby("unit_id")["area"].sum()
    return covered.reindex(units.index).fillna(0.0).div(unit_area.where(unit_area > 0))
