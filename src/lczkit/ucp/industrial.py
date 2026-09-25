"""The industrial shares that drive the LCZ 10 rule.

LCZ 8 (large low-rise) and LCZ 10 (heavy industry) are geometrically near-identical, so LCZ 10 needs
a functional signal; the classifier applies it after the prototype distance, never inside it.
Industrial buildings and industrial land-use parcels are combined by union, so a factory standing
inside an industrial parcel counts once.

Both denominators are emitted, each named for what it divides by:

- `industrial_fraction_of_building_area`: industrial building area over all building area, Bernard
  et al. (2024)'s `FIND/B`, so their 0.33 threshold transfers. Null where nothing is built.
- `industrial_fraction_of_unit_area`: industrial ground (buildings or parcels) over unit area.

A working port plot is sparsely built, so the two diverge sharply there; the LCZ 10 rule reads the
building-area share. Each source's own unit-area share ships too, with `industrial_evidence` naming
which contributed.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from lczkit.config import UcpConfig
from lczkit.crs import assert_projected_crs
from lczkit.ucp.attributes import ATTRIBUTES, require_attributes, select_pieces
from lczkit.units import check_units
from lczkit.units.overlay import (
    PIECE_AREA,
    area_in_units,
    covered_fraction,
    share_of,
    unit_pieces,
)

COLUMNS = (
    "industrial_fraction_of_building_area",
    "industrial_fraction_of_unit_area",
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
    *,
    building_area_m2: pd.Series | None = None,
    building_pieces: gpd.GeoDataFrame | None = None,
    land_use_pieces: gpd.GeoDataFrame | None = None,
) -> pd.DataFrame:
    """Per-unit industrial area shares and evidence, indexed by `unit_id` to match `units`.

    `building_area_m2` is the per-unit building footprint area, the denominator of
    `industrial_fraction_of_building_area`. `building_pieces` and `land_use_pieces` are the two
    layers already intersected with the units by `lczkit.units.overlay.unit_pieces`. All three are
    passed in rather than recomputed because `lczkit.ucp.parameters` has them: overlaying a city's
    buildings against its units is the expensive half of this function, and it is the same overlay
    `building_metrics` and `semantic_metrics` need. A direct caller may omit any of them and pay
    for the work, which is what they would otherwise write themselves.

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

    require_attributes(
        buildings,
        "buildings",
        subtypes=config.industrial_building_subtypes,
        classes=config.industrial_building_classes,
    )
    require_attributes(
        land_use,
        "land_use",
        subtypes=config.industrial_land_use_subtypes,
        classes=config.industrial_land_use_classes,
    )

    if building_pieces is None:
        building_pieces = unit_pieces(units, buildings, columns=ATTRIBUTES)
    if land_use_pieces is None:
        land_use_pieces = unit_pieces(units, land_use, columns=ATTRIBUTES)

    from_buildings = select_pieces(
        building_pieces,
        subtypes=config.industrial_building_subtypes,
        classes=config.industrial_building_classes,
    )
    from_land_use = select_pieces(
        land_use_pieces,
        subtypes=config.industrial_land_use_subtypes,
        classes=config.industrial_land_use_classes,
    )

    # `from_buildings` comes from `buildings_area`, which `trim_overlaps` has already made
    # non-overlapping, so it needs no dissolve. `from_land_use` does: `lczkit.cleaning.land_use`
    # states it gets no overlap resolution of any kind, and two parcels covering the same ground
    # would count it twice. The union of the two dissolves for the same reason — counting a factory
    # standing inside an industrial parcel once is the whole point of combining the sources.
    building_share = covered_fraction(units, from_buildings, dissolve=False)
    land_use_share = covered_fraction(units, from_land_use, dissolve=True)
    combined = _concat_pieces(from_buildings, from_land_use, units)
    union_share = covered_fraction(units, combined, dissolve=True)

    # Bernard et al. (2024)'s `FIND/B`: industrial building area over *all* building area.
    # **Industrial buildings only, never the union with the parcels.** A parcel is evidence about
    # ground, and `industrial_fraction_of_unit_area` is where ground evidence belongs; folding it
    # into a building-area numerator would make this a second unit-area measure wearing a different
    # name, which is also not what `FIND/B` means in the paper. Sharing `total` with
    # `building_surface_fraction` is what keeps the two internally consistent.
    total = (
        building_area_m2.reindex(units.index)
        if building_area_m2 is not None
        else area_in_units(units, building_pieces)
    )
    of_building_area = share_of(area_in_units(units, from_buildings), total)

    evidence = pd.Series("none", index=units.index, dtype="object")
    evidence[building_share > 0] = "buildings"
    evidence[land_use_share > 0] = "land_use"
    evidence[(building_share > 0) & (land_use_share > 0)] = "both"

    frame = pd.DataFrame(
        {
            "industrial_fraction_of_building_area": of_building_area,
            "industrial_fraction_of_unit_area": union_share,
            "industrial_fraction_buildings": building_share,
            "industrial_fraction_land_use": land_use_share,
            "industrial_evidence": pd.Categorical(evidence, categories=EVIDENCE),
        }
    )
    frame.index.name = "unit_id"
    return frame


def _concat_pieces(
    left: gpd.GeoDataFrame, right: gpd.GeoDataFrame, units: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """Two piece sets stacked, for a coverage measured over their union."""
    if left.empty:
        return right
    if right.empty:
        return left
    stacked = pd.concat(
        [left[["unit_id", PIECE_AREA, "geometry"]], right[["unit_id", PIECE_AREA, "geometry"]]],
        ignore_index=True,
    )
    return gpd.GeoDataFrame(stacked, geometry="geometry", crs=units.crs)
