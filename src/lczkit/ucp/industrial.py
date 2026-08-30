"""`industrial_fraction` — the one functional attribute in the parameter table.

It exists because LCZ 8 (large low-rise) and LCZ 10 (heavy industry) are geometrically
near-identical: large footprint, low, sparse. Nothing in morphology or land cover separates a
distribution warehouse from a refinery, so without a functional signal LCZ 10 is unreachable and
the package would silently never emit it. The classifier applies this *after* the prototype
distance, as an explicit rule — it is deliberately not folded into the morphological metric, where
it would distort every other class.

Two evidence sources, combined by union: industrial building footprints are dissolved together
with industrial land-use parcels before the area is measured, so a factory standing inside an
industrial parcel counts once rather than twice. The two sources therefore reinforce each other's
*coverage* without inflating the magnitude. Each source's own fraction ships alongside the
combined one, together with `industrial_evidence` naming which contributed, because the two are
very differently reliable.

**Two denominators, both emitted, each named for what it divides by.** A single column called
`industrial_fraction` cannot be read correctly when it is unclear whether it divides by building
area or by unit area, and that is not resolvable by
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

**The geometry is `lczkit.units.overlay`'s, not this module's.** Three private helpers here each
carried a copy of "intersect a layer with the units, measure the pieces, sum by `unit_id`", and
two more sat in `ucp.semantics`. One of the five reached its dissolved coverage through a
whole-layer `union_all`, which is safe on the industrial subset and is the operation this file's
own anti-pattern list warns about on a whole layer — a distinction nothing in the helper's name
carried. `ucp.parameters` now intersects each layer once and hands the pieces down, and the
recorded values for all three fixtures reproduce to 1e-9.
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
            "industrial_fraction": union_share,
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
