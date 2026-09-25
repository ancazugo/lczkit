"""Functional evidence from Overture's own attributes, and how much of it there is.

Per configured `SemanticGroupConfig`, the share of building area and of unit area whose Overture
`subtype` or `class` places it in the group, plus two coverage columns that make those shares
readable: `building_tag_coverage` and `land_use_coverage`.

**The coverage columns are the point.** Tagged building area is 48.6% across Europe and North
America against 13.6% elsewhere (Rio 3.1%), because ML-derived footprints carry no attributes and
Overture's conflation is winner-takes-all per building. A `lightweight` share of 0.0 where 97% of
building area is untagged is not evidence of absence. Land-use parcels generalise better (30-65%
coverage where building tags are near-absent), so the two are reported separately.

Built types only: `park`, `forest`, `grass` and `farmland` are deliberately unmapped, because
rasters own land cover. The vocabulary is `docs/references/tables/overture_lcz_semantic_mapping.md`,
which a test parses and asserts against.
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

The two are not comparable: one divides tagged building area by all building area, the other
dissolved parcel area by unit area.
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

    `building_pieces`, `land_use_pieces` and `building_area_m2` are handed down by
    `lczkit.ucp.parameters`, which intersects each layer once; passing `None` computes them here.

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
