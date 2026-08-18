"""`surface_fractions` — turning Phase 4's disjoint classes into Stewart & Oke's partition.

Two transformations happen here and both change which LCZ classes Phase 6 can reach: tree and
water fold back into pervious, and the building share comes out of impervious. Getting either
wrong produces a table that looks entirely reasonable and classifies badly, so the arithmetic is
asserted exactly rather than by property.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lczkit.config import LandCoverConfig, UcpConfig
from lczkit.ucp.surface import surface_fractions

WORLDCOVER = LandCoverConfig().dataset("worldcover")
CONFIG = UcpConfig()

PARTITION = [
    "building_surface_fraction",
    "impervious_surface_fraction",
    "pervious_surface_fraction",
]


def land_cover(**rows: tuple[float, float, float, float]) -> pd.DataFrame:
    """A Phase 4 fractions table. Each row is (tree, pervious, impervious, water)."""
    frame = pd.DataFrame.from_dict(
        rows,
        orient="index",
        columns=["frac_tree", "frac_pervious", "frac_impervious", "frac_water"],
    )
    frame.index.name = "unit_id"
    return frame


def buildings(**rows: float) -> pd.Series:
    series = pd.Series(rows, dtype="float64")
    series.index.name = "unit_id"
    return series


def test_tree_and_water_fold_into_pervious() -> None:
    """Stewart & Oke put LCZ A (dense trees) and LCZ G (water) both at 90%+ pervious. Phase 4
    carves tree out of pervious and reports water separately so its own fractions sum to 1.0, so
    neither class is reachable unless both are added back here."""
    result = surface_fractions(
        land_cover(park=(0.60, 0.25, 0.05, 0.10)), buildings(park=0.0), WORLDCOVER, CONFIG
    )

    assert result.loc["park", "pervious_surface_fraction"] == pytest.approx(0.95)
    assert result.loc["park", "tree_fraction"] == pytest.approx(0.60)
    assert result.loc["park", "water_fraction"] == pytest.approx(0.10)


def test_the_building_share_comes_out_of_impervious() -> None:
    """A raster's built-up class is measured from above and contains the roofs. Left in, a compact
    midrise unit reports a building fraction of 0.3 alongside an impervious fraction of 0.6 and
    sums to 1.3 — nowhere near any prototype."""
    result = surface_fractions(
        land_cover(block=(0.10, 0.20, 0.60, 0.10)), buildings(block=0.30), WORLDCOVER, CONFIG
    )

    assert result.loc["block", "impervious_surface_fraction"] == pytest.approx(0.30)


def test_the_three_stewart_and_oke_fractions_partition_the_unit() -> None:
    frame = land_cover(
        block=(0.10, 0.20, 0.60, 0.10),
        paved=(0.00, 0.00, 1.00, 0.00),
        park=(0.60, 0.25, 0.05, 0.10),
    )
    share = buildings(block=0.30, paved=0.50, park=0.0)

    result = surface_fractions(frame, share, WORLDCOVER, CONFIG).join(
        share.rename("building_surface_fraction")
    )

    assert result[PARTITION].sum(axis=1).to_numpy() == pytest.approx(1.0)


def test_more_building_than_built_up_clips_at_zero_and_the_partition_exceeds_one() -> None:
    """The vector footprints and the raster disagree — a 10 m product under-resolves buildings, so
    a dense unit can carry more footprint than the raster calls built up. Clipping is the honest
    response: there is no negative impervious surface. The consequence is that the partition sums
    above 1.0 for those units, which is a visible signal of the disagreement rather than a hidden
    one, and is the only case where it does.
    """
    result = surface_fractions(
        land_cover(dense=(0.05, 0.15, 0.75, 0.05)), buildings(dense=0.90), WORLDCOVER, CONFIG
    )

    assert result.loc["dense", "impervious_surface_fraction"] == 0.0
    total = result.loc["dense", ["impervious_surface_fraction", "pervious_surface_fraction"]].sum()
    assert total + 0.90 > 1.0


def test_a_unit_the_raster_never_covered_stays_null() -> None:
    """Phase 4 returns all-null for a unit outside the raster. Null is not zero cover, and turning
    it into zero here would report open country as fully impervious."""
    frame = land_cover(covered=(0.10, 0.20, 0.60, 0.10))
    frame.loc["outside"] = np.nan

    result = surface_fractions(frame, buildings(covered=0.3, outside=0.0), WORLDCOVER, CONFIG)

    assert result.loc["outside"].isna().all()
    assert result.loc["covered"].notna().all()


def test_units_absent_from_the_land_cover_table_are_null_not_dropped() -> None:
    result = surface_fractions(
        land_cover(covered=(0.10, 0.20, 0.60, 0.10)),
        buildings(covered=0.3, missing=0.1),
        WORLDCOVER,
        CONFIG,
    )

    assert list(result.index) == ["covered", "missing"]
    assert result.loc["missing"].isna().all()


def test_a_class_the_dataset_does_not_emit_is_refused() -> None:
    config = CONFIG.model_copy(update={"pervious_classes": ["pervious", "grass"]})

    with pytest.raises(ValueError, match="'grass'"):
        surface_fractions(land_cover(a=(0.1, 0.2, 0.6, 0.1)), buildings(a=0.0), WORLDCOVER, config)


def test_a_class_claimed_by_two_groups_is_refused() -> None:
    """It would otherwise be counted twice and the partition would quietly exceed one."""
    config = CONFIG.model_copy(update={"pervious_classes": ["pervious", "tree"]})

    with pytest.raises(ValueError, match="claimed by both"):
        surface_fractions(land_cover(a=(0.1, 0.2, 0.6, 0.1)), buildings(a=0.0), WORLDCOVER, config)


def test_a_class_no_group_claims_is_refused() -> None:
    """Its area would vanish from a set of fractions that is then no longer a partition."""
    config = CONFIG.model_copy(update={"water_classes": []})

    with pytest.raises(ValueError, match="water"):
        surface_fractions(land_cover(a=(0.1, 0.2, 0.6, 0.1)), buildings(a=0.0), WORLDCOVER, config)


def test_the_canopy_dataset_is_refused_as_a_land_cover_source() -> None:
    """ETH canopy height emits `tree`/`non_tree` — a second estimate of one class, not a land-cover
    product. Pointing `land_cover_dataset` at it must fail rather than report every unit as either
    fully pervious or fully unclassified."""
    canopy = LandCoverConfig().dataset("eth_canopy")
    frame = pd.DataFrame({"canopy_frac_tree": [0.4], "canopy_frac_non_tree": [0.6]}, index=["a"])
    frame.index.name = "unit_id"

    with pytest.raises(ValueError, match="non_tree"):
        surface_fractions(frame, buildings(a=0.0), canopy, CONFIG)


def test_an_empty_group_is_null_where_the_raster_never_reached() -> None:
    """An empty group is legitimate for a dataset that emits no such class, but it must not answer
    0.0 for a unit that was never observed. The module's own contract is that a null land-cover
    fraction is not zero cover, and a group with no columns was the one path that broke it."""
    frame = land_cover(seen=(0.1, 0.2, 0.6, 0.1), unseen=(np.nan, np.nan, np.nan, np.nan))
    config = CONFIG.model_copy(update={"water_classes": [], "pervious_classes": ["pervious"]})
    dataset = WORLDCOVER.model_copy(update={"classes": ["tree", "pervious", "impervious"]})

    result = surface_fractions(
        frame.drop(columns=["frac_water"]), buildings(seen=0.0, unseen=0.0), dataset, config
    )

    assert result.loc["seen", "water_fraction"] == 0.0
    assert pd.isna(result.loc["unseen", "water_fraction"])


def test_the_clip_is_flagged_where_the_buildings_exceed_the_raster_built_up() -> None:
    """`building + impervious + pervious` is exactly 1.0 by construction — except here.

    The subtraction that moves roofs out of the raster's built-up class goes negative wherever the
    vector footprints cover more ground than a 10 m product calls built-up, and the clip that stops
    the fraction going negative is what breaks the partition. Dense low-rise mapped from imagery
    does this routinely, which is why it is reported per unit rather than absorbed.
    """
    result = surface_fractions(
        land_cover(clipped=(0.0, 0.70, 0.30, 0.0), fine=(0.0, 0.20, 0.80, 0.0)),
        buildings(clipped=0.55, fine=0.30),
        WORLDCOVER,
        CONFIG,
    )

    assert bool(result.loc["clipped", "impervious_clipped"]) is True
    assert bool(result.loc["fine", "impervious_clipped"]) is False
    assert result.loc["clipped", "impervious_surface_fraction"] == 0.0

    total = (
        result["impervious_surface_fraction"]
        + result["pervious_surface_fraction"]
        + buildings(clipped=0.55, fine=0.30)
    )
    assert total["fine"] == pytest.approx(1.0)
    assert total["clipped"] > 1.0


def test_a_unit_the_raster_never_reached_has_a_null_clip_flag_not_a_false_one() -> None:
    """ "The clip did not fire" and "nothing was measured" are different statements, and False
    would claim a partition held over a unit that has no fractions at all."""
    result = surface_fractions(
        land_cover(covered=(0.0, 0.5, 0.5, 0.0)),
        buildings(covered=0.1, missing=0.1),
        WORLDCOVER,
        CONFIG,
    )

    assert pd.isna(result.loc["missing", "impervious_clipped"])
    assert result.loc["covered", "impervious_clipped"] is not pd.NA
