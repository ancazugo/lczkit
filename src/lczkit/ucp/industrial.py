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

**Two denominators, both emitted, each named for what it divides by.** The denominator was
contradicted three ways across this repository at once: CLAUDE.md's resolved-discrepancy table and
`ucp.parameters`' docstring both said building area, while this module, `ucp.registry` and the
config field all said unit area and argued for it. A single column called `industrial_fraction`
cannot be read correctly under that disagreement, and the disagreement is not resolvable by
picking, because the two quantities answer different questions:

- `industrial_fraction_of_building_area` — of what is *built* here, how much is industrial. This
  is Bernard et al. (2024)'s `FIND/B`, so their published 0.33 threshold transfers to it directly.
  Null where nothing is built, because "what share of no buildings is industrial" has no answer.
- `industrial_fraction_of_unit_area` — of this cell's *ground*, how much is industrial. Sensitive
  to how much of the cell is built at all, which is why Bernard's threshold does not transfer.

A working port plot is a case where they diverge sharply: sparsely built, so a low unit-area share
and a high building-area one. That is exactly the fabric the LCZ 10 rule has to catch, which is why
the rule reads the building-area column by default.

`industrial_fraction` is retained as a deprecated alias for the unit-area column, so no stored
figure changes meaning underneath a reader.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from lczkit.config import UcpConfig
from lczkit.crs import assert_projected_crs
from lczkit.units import check_units

COLUMNS = (
    "industrial_fraction_of_building_area",
    "industrial_fraction_of_unit_area",
    "industrial_fraction",
    "industrial_fraction_buildings",
    "industrial_fraction_land_use",
    "industrial_evidence",
)

DEPRECATED_ALIAS = "industrial_fraction"
"""Alias for `industrial_fraction_of_unit_area`, kept for one release.

Named rather than merely left in place: a bare `industrial_fraction` is precisely the column whose
denominator nobody could agree on, and anything still reading it is reading the unit-area answer
whether or not it meant to.
"""

EVIDENCE = ("none", "buildings", "land_use", "both")
"""Fixed category set for `industrial_evidence`, so the output schema does not depend on which
evidence a given city happens to carry."""


def industrial_metrics(
    buildings: gpd.GeoDataFrame,
    land_use: gpd.GeoDataFrame,
    units: gpd.GeoDataFrame,
    config: UcpConfig,
    *,
    building_area_m2: pd.Series | None = None,
) -> pd.DataFrame:
    """Per-unit industrial area shares and evidence, indexed by `unit_id` to match `units`.

    `building_area_m2` is the per-unit building footprint area, the denominator of
    `industrial_fraction_of_building_area`. Passed in rather than recomputed because
    `lczkit.ucp.buildings` has already overlaid every footprint against every unit to get
    `building_surface_fraction`, and repeating that at whole-city scale is the expensive half of
    this function.

    Every unit-area column is zero rather than null where nothing industrial is present: unlike a
    land-cover fraction, which can be genuinely unobserved, "no industrial feature covers this unit"
    is a measurement. The building-area column is the exception and is null where the unit holds no
    buildings, because a share of nothing is not zero — it is undefined, and reporting 0.0 there
    would tell the LCZ 10 rule that a buildingless cell is definitely not industrial rather than
    that there is nothing to judge. Neither input is mutated.
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

    # `from_buildings` comes from `buildings_area`, which `trim_overlaps` has already made
    # non-overlapping, so it needs no dissolve. `from_land_use` does: `lczkit.cleaning.land_use`
    # states it gets no overlap resolution of any kind, and two parcels covering the same ground
    # would count it twice. `combined` dissolves because that is the whole point of unioning two
    # evidence sources. Dissolving all three cost a union over every industrial feature three times
    # rather than once, for no gain on the one layer that is already planar.
    building_share = _covered_fraction(from_buildings, units, dissolve=False)
    land_use_share = _covered_fraction(from_land_use, units, dissolve=True)
    union_share = _covered_fraction(combined, units, dissolve=True)
    of_building_area = _industrial_share_of_building_area(
        from_buildings, units, buildings, building_area_m2=building_area_m2
    )

    evidence = pd.Series("none", index=units.index, dtype="object")
    evidence[building_share > 0] = "buildings"
    evidence[land_use_share > 0] = "land_use"
    evidence[(building_share > 0) & (land_use_share > 0)] = "both"

    frame = pd.DataFrame(
        {
            "industrial_fraction_of_building_area": of_building_area,
            "industrial_fraction_of_unit_area": union_share,
            "industrial_fraction": union_share,
            "industrial_fraction_buildings": building_share,
            "industrial_fraction_land_use": land_use_share,
            "industrial_evidence": pd.Categorical(evidence, categories=EVIDENCE),
        }
    )
    frame.index.name = "unit_id"
    return frame


def _industrial_share_of_building_area(
    industrial_buildings: gpd.GeoSeries,
    units: gpd.GeoDataFrame,
    all_buildings: gpd.GeoDataFrame,
    *,
    building_area_m2: pd.Series | None,
) -> pd.Series:
    """Bernard et al. (2024)'s `FIND/B`: industrial building area over all building area, per unit.

    **Industrial *buildings* only, not the union with land-use parcels.** A parcel is evidence about
    ground, and `industrial_fraction_of_unit_area` is where ground evidence belongs; folding it into
    a building-area numerator would make this a second unit-area measure wearing a different name.
    This is also what `FIND/B` means in the paper — industrial building typology over building area.

    `building_area_m2` is the denominator, passed in from the overlay `building_metrics` has already
    performed rather than recomputed here. That is not only cheaper: it guarantees the ratio shares
    a denominator with `building_surface_fraction`, so the two are internally consistent. A direct
    caller may omit it and pay for the overlay, which is what they would otherwise write themselves;
    `compute_parameters` always supplies it, and at metropolitan scale that difference is the whole
    cost of this function.

    Null where the unit holds no building area at all — a share of nothing is undefined.
    """
    index = units.index
    total = (
        building_area_m2.reindex(index)
        if building_area_m2 is not None
        else _overlaid_area(all_buildings, units)
    )
    if industrial_buildings.empty:
        return pd.Series(0.0, index=index, dtype="float64").where(total > 0)

    # Overlay against the industrial subset alone. Overlaying every footprint and then intersecting
    # each piece against a dissolved industrial geometry is the same answer at whole-city cost: it
    # unions every industrial feature and then runs 892k intersections against the result. The
    # subset is a few hundred features on the fixtures and a few thousand at metropolitan scale.
    covering = gpd.GeoDataFrame(geometry=industrial_buildings.reset_index(drop=True), crs=units.crs)
    pieces = gpd.overlay(units[["geometry"]].reset_index(), covering, how="intersection")
    if pieces.empty:
        return pd.Series(0.0, index=index, dtype="float64").where(total > 0)

    numerator = (
        pieces.assign(area=pieces.geometry.area)
        .groupby("unit_id")["area"]
        .sum()
        .reindex(index)
        .fillna(0.0)
    )
    return numerator.div(total.where(total > 0))


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


def _overlaid_area(buildings: gpd.GeoDataFrame, units: gpd.GeoDataFrame) -> pd.Series:
    """Building footprint area inside each unit, splitting at unit boundaries.

    The fallback denominator for a direct caller. `compute_parameters` never reaches this — it hands
    the value down from the overlay `building_metrics` already ran.
    """
    if buildings.empty:
        return pd.Series(0.0, index=units.index, dtype="float64")
    covering = gpd.GeoDataFrame(geometry=buildings.geometry.reset_index(drop=True), crs=units.crs)
    pieces = gpd.overlay(units[["geometry"]].reset_index(), covering, how="intersection")
    if pieces.empty:
        return pd.Series(0.0, index=units.index, dtype="float64")
    return (
        pieces.assign(area=pieces.geometry.area)
        .groupby("unit_id")["area"]
        .sum()
        .reindex(units.index)
        .fillna(0.0)
    )


def _covered_fraction(
    geometries: gpd.GeoSeries, units: gpd.GeoDataFrame, *, dissolve: bool
) -> pd.Series:
    """Share of each unit's area covered by `geometries`.

    `dissolve` unions overlapping inputs first so shared ground counts once. Required for
    `land_use`, which `lczkit.cleaning.land_use` states gets no overlap resolution of any kind — two
    parcels covering the same ground double-counted it and could push the fraction past 1.0. Not
    required for `buildings_area`, which `trim_overlaps` has already made non-overlapping, and a
    union is superlinear, so it is not run there.

    Explicit rather than defaulted: each caller has a reason, and the wrong answer here is either a
    fraction above 1.0 or a whole-extent union nobody asked for.
    """
    unit_area = units.geometry.area
    zero = pd.Series(0.0, index=units.index, dtype="float64")
    if geometries.empty:
        return zero

    covering = (
        gpd.GeoDataFrame(geometry=gpd.GeoSeries([geometries.union_all()], crs=units.crs))
        if dissolve
        else gpd.GeoDataFrame(geometry=geometries.reset_index(drop=True), crs=units.crs)
    )

    pieces = gpd.overlay(units[["geometry"]].reset_index(), covering, how="intersection")
    if pieces.empty:
        return zero

    covered = pieces.assign(area=pieces.geometry.area).groupby("unit_id")["area"].sum()
    return covered.reindex(units.index).fillna(0.0).div(unit_area.where(unit_area > 0))
