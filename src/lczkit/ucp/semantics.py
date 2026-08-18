"""Functional evidence from Overture's own attributes, and how much of it there is.

The package computes twenty parameters and exactly one of them reads a semantic attribute:
`industrial_fraction`, a literal `isin(["industrial"])`. Overture ingests and cleaning retains
`subtype` and `class` on every building and every land-use parcel, so the vocabulary was there and
unread. This module generalises the industrial machinery — `ucp.attributes` holds the one
definition of "which features match" and `lczkit.units.overlay` the one definition of "how much of
a unit they cover" — and adds the two columns that make the result honest.

**It used to intersect the land-use layer six times**, once for its coverage column and once per
configured semantic group, plus once per group for the buildings: twelve overlays whose count grew
with the configuration rather than with the city. The layers are intersected once by
`ucp.parameters` and selecting a group is now a mask over pieces that already exist.

**The two coverage columns are the point, not a diagnostic.** Measured over the sixteen study
cities the registry held at the time - the four added afterwards have no Overture extract on disk
and are **not** in this figure - **48.6% of building area carries an attribute across Europe and
North America against 13.6% elsewhere** — the same collapse Phase 9 measured for tier-1 height, on
a second and independent attribute. Rio is at 3.1%, so a `lightweight` fraction of 0.0 there is not
evidence that there is no informal settlement; it is 97% of building area carrying no tag. Without
`building_tag_coverage` beside it the two states are indistinguishable, exactly as "90% real
heights" and "90% coarse raster fallback" are without `height_tier_fractions`.

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
from lczkit.ucp.attributes import ATTRIBUTES, select_pieces, tagged_pieces
from lczkit.units import check_units
from lczkit.units.overlay import area_in_units, covered_fraction, share_of, unit_pieces

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
    building_pieces: gpd.GeoDataFrame | None = None,
    land_use_pieces: gpd.GeoDataFrame | None = None,
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

    **Each layer is intersected with the units once.** `building_pieces` and `land_use_pieces` come
    from `lczkit.ucp.parameters`, which overlays each layer once for every consumer of it; passing
    `None` overlays here instead. Selecting a group is then a mask over pieces that already exist,
    which is what stops the cost growing with the number of configured groups — this function used
    to run one intersection per group per layer, so five groups meant twelve overlays.

    `building_area_m2` is the denominator for the building columns, handed down for the same reason.

    No input is mutated.
    """
    check_units(units)
    assert_projected_crs(buildings, "buildings")
    assert_projected_crs(land_use, "land_use")

    groups = config.semantic_groups
    columns = group_columns(groups)
    result = pd.DataFrame(index=units.index, columns=list(columns), dtype="float64")

    if building_pieces is None:
        building_pieces = unit_pieces(units, buildings, columns=ATTRIBUTES)
    if land_use_pieces is None:
        land_use_pieces = unit_pieces(units, land_use, columns=ATTRIBUTES)

    total = (
        area_in_units(units, building_pieces)
        if building_area_m2 is None
        else building_area_m2.reindex(units.index)
    )

    result["building_tag_coverage"] = share_of(
        area_in_units(units, tagged_pieces(building_pieces)), total
    )
    result["land_use_coverage"] = covered_fraction(units, land_use_pieces, dissolve=True)

    for group in groups:
        selected = select_pieces(
            building_pieces,
            subtypes=group.building_subtypes,
            classes=group.building_classes,
        )
        result[f"{BUILDING_PREFIX}{group.name}{BUILDING_SUFFIX}"] = share_of(
            area_in_units(units, selected), total
        )

        parcels = select_pieces(
            land_use_pieces,
            subtypes=group.land_use_subtypes,
            classes=group.land_use_classes,
        )
        result[f"{BUILDING_PREFIX}{group.name}{PARCEL_SUFFIX}"] = covered_fraction(
            units, parcels, dissolve=True
        )

    result.index.name = "unit_id"
    return result[list(columns)]
