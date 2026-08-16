"""Functional evidence from Overture's own attributes, and how much of it there is.

The package computes twenty parameters and exactly one of them reads a semantic attribute:
`industrial_fraction`, a literal `isin(["industrial"])`. Overture ingests and cleaning retains
`subtype` and `class` on every building and every land-use parcel, so the vocabulary was there and
unread. This module generalises the industrial machinery — it *imports* the selection and coverage
helpers rather than restating them, so there is one definition of "which features match" and one of
"how much of a unit they cover" — and adds the two columns that make the result honest.

**The two coverage columns are the point, not a diagnostic.** Measured over the sixteen study
cities, **48.6% of building area carries an attribute across Europe and North America against
13.6% elsewhere** — the same collapse Phase 9 measured for tier-1 height, on a second and
independent attribute, with the same seven-against-nine shape. Rio is at 3.1%. So a `lightweight`
fraction of 0.0 there is not evidence that there is no informal settlement; it is 97% of building
area carrying no tag. Without `building_tag_coverage` beside it the two states are
indistinguishable, exactly as "90% real heights" and "90% coarse raster fallback" are without
`height_tier_fractions`.

**Land-use parcels are the evidence that generalises.** They cover 30-65% of the same cities where
building tags are near-absent (Rio 64.5%, Jakarta 55.8%, Cairo 37.6%, Nairobi 35.6%, Mumbai 30.5%),
and 79-107% in Europe. That is why the two are reported as separate
columns with their denominators in their names rather than fused into one number: they have
different availability, different meanings and different failure modes, and a single blended
fraction would hide all three.

**Scope: built types only.** CLAUDE.md's locked decision is that land use supplies functional
semantics and never land cover — rasters own that. `park`, `forest`, `grass` and `farmland` are all
present in the vocabulary and all deliberately unmapped, so nothing here can reach LCZ A-G.

The vocabulary is transcribed from `docs/references/tables/overture_lcz_semantic_mapping.md`, which
`tests/test_ucp_semantics.py` parses and asserts against, and every value in it was taken from what
is present in the pinned release rather than from the schema documentation.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from lczkit.config import SemanticGroupConfig, UcpConfig
from lczkit.crs import assert_projected_crs
from lczkit.ucp.industrial import _select
from lczkit.units import check_units

BUILDING_PREFIX = "sem_"
BUILDING_SUFFIX = "_buildings_of_building_area"
PARCEL_SUFFIX = "_parcels_of_unit_area"
"""Both a numerator and a denominator in every column name.

`industrial_fraction` was contradicted three ways inside this repository at once because its name
said neither, and CLAUDE.md's ruling from that is a standing anti-pattern. These columns are not
comparable to each other and must not look as though they are: one divides tagged building area by
*all* building area, the other divides dissolved parcel area by *unit* area.
"""

COVERAGE_COLUMNS = ("building_tag_coverage", "land_use_coverage")


def group_columns(groups: list[SemanticGroupConfig]) -> tuple[str, ...]:
    """Every column `semantic_metrics` emits for `groups`, in order.

    Derived from the configured groups rather than listed as a constant, so a group added in config
    cannot silently fail to appear in the output schema or the registry.
    """
    return (
        *(f"{BUILDING_PREFIX}{g.name}{BUILDING_SUFFIX}" for g in groups),
        *(f"{BUILDING_PREFIX}{g.name}{PARCEL_SUFFIX}" for g in groups),
        *COVERAGE_COLUMNS,
    )


def semantic_metrics(
    buildings: gpd.GeoDataFrame,
    land_use: gpd.GeoDataFrame,
    units: gpd.GeoDataFrame,
    config: UcpConfig,
    *,
    building_area_m2: pd.Series | None = None,
) -> pd.DataFrame:
    """Per-unit functional evidence and its coverage, keyed by `unit_id`.

    Per configured group, two columns:

    - `sem_<group>_buildings_of_building_area` — share of the unit's building area whose `subtype`
      or `class` places it in the group. Bernard et al.'s `FIND/B` quantity, generalised. Null where
      the unit holds no building area at all, never 0.0: "no industrial buildings here" and "no
      buildings here" are different statements.
    - `sem_<group>_parcels_of_unit_area` — share of the unit's area under land-use parcels of the
      group, **dissolved first**. `lczkit.cleaning.land_use` applies `make_valid` and no overlap
      resolution, and Milan's parcels sum to 106.6% of its bbox, so anything dividing by unit area
      without dissolving can exceed 1.0.

    Plus, always:

    - `building_tag_coverage` — share of the unit's building area carrying any `subtype` or `class`.
    - `land_use_coverage` — share of the unit's area under any land-use parcel, dissolved.

    **Groups are not a partition and the fractions do not sum to one.** A big-box store is genuinely
    evidence for both large-low-rise form and commercial function, and `retail` appears in both
    groups deliberately.

    `building_area_m2` is the denominator for the building columns; `compute_parameters` hands down
    the value `building_metrics` already computed rather than paying for a second overlay. Passing
    `None` recomputes it.

    No input is mutated.
    """
    check_units(units)
    assert_projected_crs(buildings, "buildings")
    assert_projected_crs(land_use, "land_use")

    groups = config.semantic_groups
    columns = group_columns(groups)
    result = pd.DataFrame(index=units.index, columns=list(columns), dtype="float64")

    total = (
        _area_in_units(gpd.GeoSeries(buildings.geometry, crs=buildings.crs), units)
        if building_area_m2 is None
        else building_area_m2
    ).reindex(units.index)
    denominator = total.where(total > 0)

    result["building_tag_coverage"] = _area_in_units(_tagged(buildings), units).div(denominator)
    result["land_use_coverage"] = _dissolved_coverage(
        gpd.GeoSeries(land_use.geometry, crs=land_use.crs), units
    )

    for group in groups:
        selected = _select(
            buildings,
            f"buildings ({group.name})",
            subtypes=list(group.building_subtypes),
            classes=list(group.building_classes),
        )
        result[f"{BUILDING_PREFIX}{group.name}{BUILDING_SUFFIX}"] = _area_in_units(
            selected, units
        ).div(denominator)

        parcels = _select(
            land_use,
            f"land_use ({group.name})",
            subtypes=list(group.land_use_subtypes),
            classes=list(group.land_use_classes),
        )
        result[f"{BUILDING_PREFIX}{group.name}{PARCEL_SUFFIX}"] = _dissolved_coverage(
            parcels, units
        )

    result.index.name = "unit_id"
    return result[list(columns)]


def _tagged(buildings: gpd.GeoDataFrame) -> gpd.GeoSeries:
    """Geometries of buildings carrying any usable `subtype` or `class`.

    "Usable" excludes null and Overture's `unknown` sentinel, which is a recorded absence of
    knowledge rather than a category — counting it as a tag would report coverage the data does not
    have, which is precisely the failure this column exists to prevent.

    Returns geometries rather than an index, and every selection here does, because a building
    layer is not guaranteed to be uniquely indexed and `.loc[an_index]` over a duplicated one
    silently returns extra rows. Positional selection cannot do that.
    """
    mask = pd.Series(False, index=buildings.index).to_numpy()
    for column in ("subtype", "class"):
        if column in buildings.columns:
            values = buildings[column]
            usable = values.notna() & (values.astype("string").str.lower() != "unknown")
            mask = mask | usable.to_numpy()
    return gpd.GeoSeries(buildings.geometry[mask], crs=buildings.crs)


def _dissolved_coverage(geometries: gpd.GeoSeries, units: gpd.GeoDataFrame) -> pd.Series:
    """Share of each unit covered by `geometries`, counting shared ground once.

    **Clipped first, dissolved per unit second** — never a whole-extent `union_all`. `industrial.py`
    can afford the global union because it runs on the industrial *subset*, a few dozen parcels;
    this runs on the whole land-use layer, which is 70 509 parcels over Berlin's extent. Two
    separate reasons not to:

    - CLAUDE.md's standing anti-pattern. A union over a city's geometry is superlinear and looks
      cheap because its result is a scalar; Phase 12 measured 711 s at Berlin's 891 km² against a
      9.8-minute whole run.
    - It is not robust. A global union over real Overture land use raises
      `GEOSException: side location conflict` even after `make_valid`, because validity per feature
      does not make a collection unionable.

    Clipping to the units first bounds every union to one unit's worth of parcels, which is both
    cheap and well-conditioned, and gives exactly the same answer: the union of the clipped pieces
    inside a unit is the clip of the global union.
    """
    unit_area = units.geometry.area
    zero = pd.Series(0.0, index=units.index, dtype="float64")
    if geometries.empty:
        return zero
    covering = gpd.GeoDataFrame(geometry=geometries.reset_index(drop=True), crs=units.crs)
    pieces = gpd.overlay(units[["geometry"]].reset_index(), covering, how="intersection")
    if pieces.empty:
        return zero
    merged = pieces.dissolve(by="unit_id")
    return merged.geometry.area.reindex(units.index).fillna(0.0).div(unit_area.where(unit_area > 0))


def _area_in_units(geometries: gpd.GeoSeries, units: gpd.GeoDataFrame) -> pd.Series:
    """Area of `geometries` inside each unit, split at unit boundaries.

    Splitting rather than assigning whole footprints, matching `building_metrics` and the Phase 3
    rule: a footprint straddling a boundary contributes its share to each side, so these fractions
    share a denominator with `building_surface_fraction` exactly.

    No dissolve, and none needed: `trim_overlaps` has already made `buildings_area` non-overlapping,
    and a whole-extent union is superlinear. The land-use side does dissolve, and says so.
    """
    zero = pd.Series(0.0, index=units.index, dtype="float64")
    if geometries.empty:
        return zero
    covering = gpd.GeoDataFrame(geometry=geometries.reset_index(drop=True), crs=units.crs)
    pieces = gpd.overlay(units[["geometry"]].reset_index(), covering, how="intersection")
    if pieces.empty:
        return zero
    return (
        pieces.assign(area=pieces.geometry.area)
        .groupby("unit_id")["area"]
        .sum()
        .reindex(units.index)
        .fillna(0.0)
    )
