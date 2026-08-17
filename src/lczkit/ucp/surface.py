"""Stewart & Oke's surface fractions, reassembled from the Phase 4 land-cover table.

Phase 4 emits disjoint classes summing to 1.0, because that is what the `RasterSource` protocol
requires. Stewart & Oke (2012) do not partition the surface the same way, and two of the
differences change which LCZ classes are reachable at all:

- **Tree cover and water are pervious.** Their table puts LCZ A (dense trees) and LCZ G (water)
  both at 90%+ pervious surface fraction. Phase 4 carves `tree` out of `pervious` and reports
  `water` separately, so both have to be folded back in here or neither class can ever be matched.
  Both stay available as their own columns as well — they are what separates LCZ A and B from the
  other pervious classes, and LCZ G from everything.
- **Buildings are inside the impervious class, and must come out.** A raster's built-up class is
  measured from above and contains the roofs; Stewart & Oke's building, impervious and pervious
  fractions partition the surface between them, their per-class midpoints summing to roughly one.
  Left in, a compact midrise unit would report a building fraction of 0.5 alongside an impervious
  fraction of 0.9 and sit nowhere near any prototype.
"""

from __future__ import annotations

import pandas as pd

from lczkit.config import LandCoverDatasetConfig, UcpConfig

COLUMNS = (
    "impervious_surface_fraction",
    "pervious_surface_fraction",
    "tree_fraction",
    "water_fraction",
)

#: Which `UcpConfig` field names the classes for each surface type.
_GROUPS = ("tree_classes", "pervious_classes", "impervious_classes", "water_classes")


def surface_fractions(
    land_cover: pd.DataFrame,
    building_surface_fraction: pd.Series,
    dataset: LandCoverDatasetConfig,
    config: UcpConfig,
) -> pd.DataFrame:
    """Stewart & Oke surface fractions, indexed to match `building_surface_fraction`.

    `land_cover` is a Phase 4 fractions table for `dataset` — column names are `dataset`'s own
    `column_prefix` plus a class name. Units the raster did not cover are null there and stay null
    here; a null land-cover fraction is not zero cover.
    """
    groups = _resolve(dataset, config)
    index = building_surface_fraction.index
    aligned = land_cover.reindex(index)

    # A unit the raster never reached is null in every land-cover column. Kept as an explicit mask
    # so an empty group can distinguish "this dataset emits no such class" from "this unit was not
    # observed" - answering 0.0 for both would report cover the raster never measured.
    observed = (
        aligned.notna().any(axis=1)
        if len(aligned.columns)
        else pd.Series(False, index=index, dtype="bool")
    )

    def total(group: str) -> pd.Series:
        """Summed fraction over one configured class group, null where the raster reached nothing.

        `min_count` keeps a partially-null group null rather than summing the columns that did
        arrive; an empty group answers 0.0, but only for units the raster actually covered.
        """
        columns = groups[group]
        if not columns:
            return pd.Series(0.0, index=index, dtype="float64").where(observed)
        return aligned[columns].sum(axis=1, min_count=len(columns))

    tree = total("tree_classes")
    water = total("water_classes")
    pervious = total("pervious_classes") + tree + water
    impervious = (total("impervious_classes") - building_surface_fraction).clip(lower=0.0)

    return pd.DataFrame(
        {
            "impervious_surface_fraction": impervious,
            "pervious_surface_fraction": pervious,
            "tree_fraction": tree,
            "water_fraction": water,
        }
    )


def _resolve(dataset: LandCoverDatasetConfig, config: UcpConfig) -> dict[str, list[str]]:
    """Map each surface group to its `land_cover` column names, refusing an inconsistent config.

    Three ways the mapping can be wrong, all of which produce a plausible-looking table rather than
    an error if left unchecked: a class name that the dataset does not emit (silently zero), a
    class claimed by two groups (silently double-counted), and a class no group claims (silently
    dropped from a partition that is then no longer one).
    """
    named: dict[str, str] = {}
    groups: dict[str, list[str]] = {}
    for group in _GROUPS:
        names: list[str] = getattr(config, group)
        for name in names:
            if name not in dataset.classes:
                raise ValueError(
                    f"ucp.{group} names {name!r}, which land-cover dataset "
                    f"{dataset.name!r} does not emit; it has: {', '.join(dataset.classes)}"
                )
            if name in named:
                raise ValueError(
                    f"land-cover class {name!r} is claimed by both ucp.{named[name]} and "
                    f"ucp.{group}; surface groups must be disjoint or its area is counted twice"
                )
            named[name] = group
        groups[group] = [f"{dataset.column_prefix}{name}" for name in names]

    unclaimed = [name for name in dataset.classes if name not in named]
    if unclaimed:
        raise ValueError(
            f"land-cover dataset {dataset.name!r} emits {', '.join(unclaimed)}, which no "
            f"ucp surface group claims; that area would vanish from the surface fractions"
        )
    return groups
