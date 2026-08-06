"""Tests for the Phase 4 config surface.

The class mapping is the one place a mistake produces no error and a wrong map, so the validator
is tested as carefully as the code that reads it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lczkit.config import GeeAssetConfig, LandCoverConfig, LandCoverDatasetConfig


def _dataset(**overrides: object) -> LandCoverDatasetConfig:
    kwargs: dict[str, object] = {
        "name": "test",
        "source_dir_name": "Test",
        "classes": ["tree", "pervious"],
        "value_classes": {10: "tree", 30: "pervious"},
    }
    kwargs.update(overrides)
    return LandCoverDatasetConfig(**kwargs)  # type: ignore[arg-type]


def test_defaults_ship_both_mvp_datasets_inert() -> None:
    """Neither product is on this system, so both ship implemented and switched off — the same
    posture Phase 3's areal height tiers take."""
    config = LandCoverConfig()

    assert [dataset.name for dataset in config.datasets] == ["worldcover", "eth_canopy"]
    assert all(dataset.filename is None for dataset in config.datasets)


def test_the_worldcover_default_maps_every_v200_class() -> None:
    """All eleven codes in the transcribed class table, so `unmapped_policy="raise"` never fires
    on a well-formed v200 raster."""
    value_classes = LandCoverConfig().dataset("worldcover").value_classes or {}

    assert sorted(value_classes) == [10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100]
    assert value_classes[10] == "tree"
    assert value_classes[50] == "impervious"
    assert value_classes[80] == "water"


def test_tree_is_carved_out_of_pervious_and_the_classes_stay_disjoint() -> None:
    """Stewart & Oke count trees *within* the pervious surface fraction, but the protocol requires
    fractions summing to 1.0. Phase 5 must add frac_tree back into frac_pervious."""
    worldcover = LandCoverConfig().dataset("worldcover")

    assert worldcover.classes == ["tree", "pervious", "impervious", "water"]
    assert worldcover.value_classes is not None
    assert "tree" not in {name for value, name in worldcover.value_classes.items() if value != 10}


def test_the_canopy_threshold_is_the_lcz_tree_scrub_boundary() -> None:
    """3 m, from `docs/references/tables/stewart_oke_2012_properties.md`: LCZ C (bush, scrub) tops
    out at 2 m and LCZ A/B (trees) start at 3 m."""
    canopy = LandCoverConfig().dataset("eth_canopy")

    assert canopy.bins == [3.0]
    assert canopy.bin_classes == ["non_tree", "tree"]


def test_the_two_datasets_do_not_collide_on_their_tree_column() -> None:
    """Both estimate tree cover, and Phase 5 chooses between them — so both must be able to sit on
    one units table at once."""
    config = LandCoverConfig()
    worldcover, canopy = config.dataset("worldcover"), config.dataset("eth_canopy")

    columns = {f"{worldcover.column_prefix}{c}" for c in worldcover.classes} | {
        f"{canopy.column_prefix}{c}" for c in canopy.classes
    }

    assert len(columns) == len(worldcover.classes) + len(canopy.classes)


def test_the_canopy_default_assigns_its_mask_rather_than_excluding_it() -> None:
    canopy = LandCoverConfig().dataset("eth_canopy")

    assert (canopy.nodata, canopy.nodata_policy, canopy.nodata_class) == (
        255.0,
        "assign",
        "non_tree",
    )


def test_both_defaults_carry_an_earth_engine_asset_of_the_right_kind() -> None:
    """The two MVP products are different kinds of Earth Engine asset, and loading one as the other
    raises immediately — so `asset_type` is declared rather than probed. Both IDs were confirmed by
    loading them; ETH is a user asset absent from the public STAC catalogue."""
    config = LandCoverConfig()

    worldcover = config.dataset("worldcover").gee
    assert (worldcover.collection_id, worldcover.asset_type, worldcover.band) == (
        "ESA/WorldCover/v200",
        "image_collection",
        "Map",
    )

    canopy = config.dataset("eth_canopy").gee
    assert (canopy.collection_id, canopy.asset_type, canopy.band) == (
        "users/nlang/ETH_GlobalCanopyHeight_2020_10m_v1",
        "image",
        "b1",
    )


def test_a_single_image_asset_does_not_require_a_date_range() -> None:
    """`filterDate` applies to a collection; a single image has nothing to filter. The dates are
    still recorded, because CLAUDE.md requires them in the manifest."""
    canopy = LandCoverConfig().dataset("eth_canopy").gee

    assert "start_date" not in canopy.required_fields()
    assert canopy.start_date == "2020-01-01"
    assert "start_date" in LandCoverConfig().dataset("worldcover").gee.required_fields()


def test_worldcover_declares_its_nodata_rather_than_relying_on_the_file() -> None:
    """A GeoTIFF declares its nodata; an Earth Engine asset does not. Stating it in config is what
    keeps the two backends agreeing on which cells leave the denominator."""
    assert LandCoverConfig().dataset("worldcover").nodata == 0.0


def test_a_dataset_must_be_categorical_or_binned_but_not_both() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        _dataset(bins=[3.0], bin_classes=["pervious", "tree"])
    with pytest.raises(ValidationError, match="exactly one"):
        _dataset(value_classes=None)


def test_bin_classes_must_be_one_longer_than_bins() -> None:
    with pytest.raises(ValidationError, match="len\\(bins\\) \\+ 1"):
        LandCoverDatasetConfig(
            name="t",
            source_dir_name="T",
            classes=["tree", "pervious"],
            bins=[3.0],
            bin_classes=["tree"],
        )


def test_bins_must_ascend() -> None:
    with pytest.raises(ValidationError, match="strictly ascending"):
        LandCoverDatasetConfig(
            name="t",
            source_dir_name="T",
            classes=["a", "b", "c"],
            bins=[5.0, 3.0],
            bin_classes=["a", "b", "c"],
        )


def test_every_referenced_class_must_appear_in_classes() -> None:
    with pytest.raises(ValidationError, match="not in classes"):
        _dataset(value_classes={10: "tree", 30: "water"})


def test_an_assign_policy_requires_its_class_and_vice_versa() -> None:
    with pytest.raises(ValidationError, match="nodata_class is not set"):
        _dataset(nodata_policy="assign")
    with pytest.raises(ValidationError, match="unmapped_class is not set"):
        _dataset(unmapped_policy="assign")
    with pytest.raises(ValidationError, match="not 'assign'"):
        _dataset(nodata_class="tree")


def test_duplicate_class_names_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicates"):
        _dataset(classes=["tree", "tree"])


def test_duplicate_dataset_names_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate land-cover dataset names"):
        LandCoverConfig(datasets=[_dataset(), _dataset()])


def test_dataset_lookup_names_what_is_available() -> None:
    with pytest.raises(KeyError, match="worldcover"):
        LandCoverConfig().dataset("nope")


def test_config_round_trips_through_json() -> None:
    """Integer `value_classes` keys become strings in JSON; the manifest has to survive that."""
    config = LandCoverConfig(
        datasets=[_dataset(gee=GeeAssetConfig(collection_id="A/B", band="Map"))]
    )

    assert LandCoverConfig.model_validate_json(config.model_dump_json()) == config
