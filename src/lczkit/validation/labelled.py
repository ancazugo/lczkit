"""Labelled LCZ ground truth (So2Sat LCZ42 / DFC2017), reduced to one label per spatial unit.

CLAUDE.md's ruling for Phase 6.7: `lcz_v3.tif` is an estimate carrying its own error, so measuring
against it compares two models and reports the disagreement as lczkit's. Where hand-labelled LCZ
polygons exist they are the **primary** reference and `lcz_v3` is a secondary comparator; the
agreement between the two, on the same cells, is the ceiling on what lczkit can score against
`lcz_v3` at all.

**Why the label is anchored on the patch centre rather than overlaid areally.** So2Sat patches are
320 m squares sampled on a **100 m stride**, so they overlap each other about sevenfold - measured
on the Berlin fixture bbox: 473 patches, 48.4 km2 of patch area over a 7.1 km2 union, 16,560
overlapping pairs. An areal overlay would therefore count the same ground up to nine times, under
labels that need not agree, and the resulting "majority" would be a property of the sampling
density rather than of the city. Anchoring each label on the patch centre removes the double
counting entirely and is exact at the scale lczkit validates on: on the Berlin fixture 438 patch
centres fall into 438 distinct cells with **no cell receiving two labels**.

The 1:1 property holds, but not for the reason first recorded here. The patch centres are *not*
aligned to the local UTM origin: measured on the Berlin fixture in EPSG:32633 they sit on an exact
100 m stride at a fixed phase offset of **(40.0, 70.0) m** from the `GridUnits` cell corners. That
offset is what makes the property robust - being far from both 0 and 50 m, no centre can land on a
cell boundary and no two centres can share a cell. An offset near either value would degrade, which
is precisely what `LabelMatch` exists to expose, so it is reported per run rather than assumed.

**What the centre rule does not control** is support. The label describes a 320 x 320 m patch,
10.24 ha, and is attributed to one 1 ha cell whose centre is systematically ~22 m from the patch
centre. A 100 m cell inside a compact-midrise patch can legitimately be a courtyard. That is an
irreducible floor under any agreement figure measured this way, and it is the same patch-versus-cell
mismatch Phase 13 found in the published parameter ranges - the labels are patch-scale objects too.

The reduction is deliberately not raster-based. `reference_lcz` reads a categorical raster through
`LocalRasterSource` because the Demuzere map *is* one; these patches are vector polygons whose
value lies in their exact placement, and rasterising them to reuse that path would reintroduce the
overlap problem in a less visible form.

Returns the same three columns as `lczkit.validation.reference.reference_lcz`, so `agreement()`
consumes either without knowing which it was given.
"""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import pandas as pd

from lczkit.units import check_units

LABEL_COLUMN = "LCZ_class"
"""So2Sat LCZ42's own class column. Integer 1-17, matching Demuzere's coding for 1-10 and A-G, so
no translation is needed - asserted by `tests/test_validation_labelled.py`."""

SO2SAT_CITATION = "10.1109/MGRS.2020.2964708"
"""Zhu et al. (2020), *IEEE GRSM* 8(3), 76-89. So2Sat LCZ42."""

COLUMNS = ("reference_lcz", "reference_coverage", "reference_majority_fraction")


@dataclass(frozen=True)
class LabelMatch:
    """How the patch centres landed on the units, so a misaligned city is visible in the output.

    The 1:1 mapping above holds because a So2Sat patch grid and a 100 m `GridUnits` grid share the
    UTM origin. Nothing guarantees that for every city or every unit strategy, and a silent
    degradation - centres falling on cell boundaries, or several centres per unit disagreeing -
    would look exactly like a well-measured run. These counts make it look like what it is.
    """

    n_patches: int
    n_centres_matched: int
    """Centres falling strictly inside exactly one unit."""

    n_centres_unmatched: int
    """Centres outside every unit, or on a shared boundary and so inside none of them."""

    n_centres_ambiguous: int
    """Centres matching more than one unit. Zero for any valid partition; non-zero means the units
    overlap, and those centres are discarded rather than counted twice."""

    n_units_labelled: int
    n_units_multi_label: int
    """Units receiving centres of more than one class, and so decided by a majority rather than by
    a single label. Zero on a 100 m grid; non-zero on enclosures, which are larger than a patch."""


def labelled_lcz(
    units: gpd.GeoDataFrame,
    patches: gpd.GeoDataFrame,
    *,
    class_column: str = LABEL_COLUMN,
) -> tuple[pd.DataFrame, LabelMatch]:
    """The ground-truth class per `unit_id`, and a record of how the labels were matched.

    Returns three columns, matching `reference_lcz` so the two are interchangeable downstream:

    - `reference_lcz` - the majority class among the patch centres inside the unit, or null where
      no centre falls in it. Nullable `Int8`, never a sentinel.
    - `reference_coverage` - 1.0 where the unit carries at least one centre, else 0.0. Labelled
      patches are a *sample*, not a map: a unit either has a label or has none, and reporting a
      fractional coverage would invite `min_reference_coverage` to filter on a number that means
      something different from the one it was written for.
    - `reference_majority_fraction` - share of the unit's centres holding the winning class. 1.0
      wherever a unit holds one centre, which on a 100 m grid is every labelled unit.

    Neither input is mutated.
    """
    check_units(units)
    if class_column not in patches.columns:
        raise ValueError(
            f"patches must carry a {class_column!r} column; got {list(patches.columns)}"
        )
    if patches.crs is None:
        raise ValueError("patches must declare a CRS")
    target = units.crs
    assert target is not None  # noqa: S101 - check_units already raised if it were
    # Reprojected before the centroid is taken, never after: the centroid of a lat/lon polygon is
    # not the projection of the centroid, and this one decides which cell the label lands in.
    patches = patches.to_crs(target)

    centres = gpd.GeoDataFrame(
        {class_column: patches[class_column].to_numpy()},
        geometry=patches.geometry.centroid,
        crs=target,
    )
    # `within` rather than `intersects`: a centre on a shared cell boundary belongs to neither
    # cell, and counting it in both would let one patch label two units.
    matched = centres.sjoin(units[["geometry"]], predicate="within", how="left")

    ambiguous = matched.index.duplicated(keep=False) & matched["unit_id"].notna()
    unmatched = matched["unit_id"].isna()
    usable = matched.loc[~ambiguous & ~unmatched]

    votes = (
        usable.groupby(["unit_id", class_column]).size().rename("n").reset_index()
        if not usable.empty
        else pd.DataFrame(columns=["unit_id", class_column, "n"])
    )
    result = pd.DataFrame(
        {
            "reference_lcz": pd.Series(dtype="Int8"),
            "reference_coverage": 0.0,
            "reference_majority_fraction": pd.Series(dtype="float64"),
        },
        index=units.index,
    )
    n_multi = 0
    if not votes.empty:
        totals = votes.groupby("unit_id")["n"].sum()
        # `idxmax` on the group, not `.first()`/`.last()`: those skip nulls per column and would
        # silently return a class the unit's largest vote block does not hold.
        winners = votes.loc[votes.groupby("unit_id")["n"].idxmax()].set_index("unit_id")
        result["reference_lcz"] = winners[class_column].reindex(units.index).astype("Int8")
        result["reference_coverage"] = totals.reindex(units.index).notna().astype("float64")
        result["reference_majority_fraction"] = (
            winners["n"].div(totals).reindex(units.index).astype("float64")
        )
        n_multi = int((votes.groupby("unit_id").size() > 1).sum())

    match = LabelMatch(
        n_patches=int(len(patches)),
        n_centres_matched=int(len(usable)),
        n_centres_unmatched=int(unmatched.sum()),
        n_centres_ambiguous=int(matched.loc[ambiguous].index.nunique()),
        n_units_labelled=int(result["reference_lcz"].notna().sum()),
        n_units_multi_label=n_multi,
    )
    return result, match
