"""The Phase 10/11 harness' one load-bearing helper: which tiers a cascade variant runs, in
what order.

The sweep itself is not a test — it is a nine-hour analysis over sixteen cities. What is tested
here is `cascade_for`, because the failure it can have is silent. `full` and `full_reversed`
differ in **nothing but order**, and every tier claims only the buildings earlier tiers left, so a
`cascade_for` that took its order from the configured list rather than from the variant would run
the two identically and still print two rows. Phase 11 would then report a confident null on a
comparison it never made.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from lczkit.config import HeightConfig, Settings


def load_script() -> ModuleType:
    """Import `scripts/height_tier_experiment.py` by path.

    By path rather than as a package, for the reason `tests/test_unit_scale_experiment.py` gives:
    `scripts/` holds one-off analyses, and making it importable to run a test would put the wrong
    thing on the package's runtime surface.
    """
    root = Path(__file__).resolve().parent.parent / "scripts"
    sys.path.insert(0, str(root))
    try:
        spec = importlib.util.spec_from_file_location(
            "height_tier_experiment", root / "height_tier_experiment.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(root))


@pytest.fixture(scope="module")
def script() -> ModuleType:
    return load_script()


def _resolved(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, variant: str, tmp_path: Path
) -> HeightConfig:
    """`cascade_for` with the fetching stubbed out — the ordering is what is under test."""
    monkeypatch.setattr(
        script,
        "resolve_areal_tiers",
        lambda settings, bbox, config: (config, {}),
    )
    config, _ = script.cascade_for(
        Settings(data_dir=tmp_path, run_id="test"), (0.0, 0.0, 0.01, 0.01), variant
    )
    return config


def _enabled(config: HeightConfig) -> list[str]:
    return [tier.name for tier in config.areal_tiers if tier.enabled]


def test_reversing_a_variant_reverses_the_cascade(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The whole content of Phase 11's second measurement."""
    full = _resolved(script, monkeypatch, "full", tmp_path)
    reversed_ = _resolved(script, monkeypatch, "full_reversed", tmp_path)

    assert _enabled(full) == ["gob25d", "wsf3d", "ghsl"]
    assert _enabled(reversed_) == ["wsf3d", "ghsl", "gob25d"]


def test_a_variant_disables_the_tiers_it_leaves_out_rather_than_dropping_them(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A tier left out of a variant stays in the config, switched off.

    That is what puts it in the run manifest as a deliberate exclusion. Dropping it from the list
    instead would make "we did not run Open Buildings here" indistinguishable from "this build of
    the harness has never heard of it"."""
    config = _resolved(script, monkeypatch, "coarse", tmp_path)

    assert _enabled(config) == ["wsf3d", "ghsl"]
    assert [tier.name for tier in config.areal_tiers] == ["wsf3d", "ghsl", "gob25d"]
    assert [tier.name for tier in config.areal_tiers if not tier.enabled] == ["gob25d"]


def test_every_variant_names_only_tiers_that_exist(script: ModuleType) -> None:
    """A typo in `CASCADES` would otherwise surface as a `KeyError` nine hours into a sweep."""
    configured = {tier.name for tier in script.HEIGHTS.areal_tiers}

    for variant, names in script.CASCADES.items():
        assert set(names) <= configured, variant
        assert len(set(names)) == len(names), variant


def test_the_baseline_variant_runs_tier_one_alone(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`none` is the comparability check against Phases 9 and 10, so it must stay empty."""
    assert script.CASCADES["none"] == ()
    assert _enabled(_resolved(script, monkeypatch, "none", tmp_path)) == []
