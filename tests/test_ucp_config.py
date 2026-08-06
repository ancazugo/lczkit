"""`UcpConfig` against the other config models it has to agree with.

The Phase 5 defaults are only meaningful in combination with the Phase 4 defaults — the surface
groups name land-cover classes another model defines. Nothing else checks that pairing, so a class
added to `_WORLDCOVER_CLASSES` would otherwise surface as a runtime error in the middle of a run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lczkit.config import LandCoverConfig, Settings, UcpConfig


def test_the_shipped_surface_groups_exactly_partition_the_shipped_dataset() -> None:
    """Every class the default land-cover dataset emits is claimed by exactly one surface group.
    An unclaimed class would vanish from a partition that is then no longer one; a class in two
    groups would be counted twice. `surface_fractions` refuses both, so this is the test that the
    shipped defaults do not trip its own guard."""
    config = UcpConfig()
    dataset = LandCoverConfig().dataset(config.land_cover_dataset)
    claimed = [
        *config.tree_classes,
        *config.pervious_classes,
        *config.impervious_classes,
        *config.water_classes,
    ]

    assert sorted(claimed) == sorted(dataset.classes)


def test_the_default_land_cover_dataset_exists() -> None:
    assert LandCoverConfig().dataset(UcpConfig().land_cover_dataset).name == "worldcover"


def test_a_warehouse_is_not_industrial_by_default() -> None:
    """CLAUDE.md's own example of the LCZ 8 / LCZ 10 confusion is a distribution warehouse, which
    is the LCZ 8 case. Counting it would push exactly the units the rule exists to separate towards
    LCZ 10."""
    config = UcpConfig()

    assert "warehouse" not in config.industrial_building_classes
    assert "industrial" in config.industrial_building_classes


def test_land_use_subtypes_select_nothing_by_default() -> None:
    """Overture files industrial parcels under `subtype='developed'`, which also covers commercial
    and retail, so the subtype alone carries no industrial signal."""
    assert UcpConfig().industrial_land_use_subtypes == []
    assert UcpConfig().industrial_land_use_classes == ["industrial"]


def test_ucp_config_reaches_the_manifest_through_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLAUDE.md serialises the config verbatim into the run manifest, so every Phase 5 choice —
    the street-profile geometry, the class vocabulary — has to survive a JSON round trip."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings = Settings.load(dotenv_path=tmp_path / "absent.env")
    settings.ucp.industrial_land_use_classes = ["industrial", "brownfield"]

    restored = Settings.model_validate_json(settings.model_dump_json())

    assert restored.ucp == settings.ucp
    assert restored.ucp.street_profile_tick_length_m == 50.0
    assert restored.ucp.industrial_land_use_classes == ["industrial", "brownfield"]
