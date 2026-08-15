"""The command line: what it accepts, what it refuses, and what it must not let drift.

**The drift guard is the point of this file.** CLAUDE.md's Phase 14 ruling is that "a ruling is not
applied until the code says so", after four rulings sat in the spec as decided while the code did
the superseded thing. The same shape of failure is available here in a new place: `lczkit run` and
`scripts/publish_sites.py` must configure a run identically, or the command line quietly produces
something that is not what the published figures were measured from. They now share
`lczkit.presets`, so a divergence has to be introduced deliberately — and the tests at the bottom
fail if the values in that preset stop matching the constants the published runs used.

Nothing here needs `DATA_DIR`, the network, or tippecanoe.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from typer.testing import CliRunner

from lczkit.cli import app
from lczkit.cli._render import EXIT_CONFIG
from lczkit.config import Settings
from lczkit.presets import PRESETS, apply_preset

runner = CliRunner()


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A `DATA_DIR` the CLI will accept.

    Set through the environment rather than a `.env`, which matters: `Settings.load` calls
    `load_dotenv` with `override=False`, so an already-set variable wins and the repository's own
    `.env` cannot reach into the test. The `_clean_data_dir_env` autouse fixture in `conftest.py`
    has already removed any inherited value.
    """
    (tmp_path / "input").mkdir()
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def load_script(name: str) -> ModuleType:
    """Import a module from `scripts/` by path, the way its sibling tests do.

    `scripts/` is deliberately not a package, so there is no import to reach it with.
    """
    path = Path(__file__).resolve().parent.parent / "scripts" / f"{name}.py"
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(path.parent))


# --------------------------------------------------------------------------- help and wiring


def test_every_command_has_help_that_does_not_need_data_dir() -> None:
    """`--help` must work on a clean checkout, before anything is configured.

    It is the first thing anyone runs, and a traceback about `DATA_DIR` at that point reads as
    "this package is broken" rather than "you have not set it up yet".
    """
    for argv in ([], ["run"], ["site"], ["site", "build"], ["site", "serve"]):
        result = runner.invoke(app, [*argv, "--help"])
        assert result.exit_code == 0, f"lczkit {' '.join(argv)} --help failed:\n{result.output}"
        assert "Traceback" not in result.output


def test_the_console_script_points_at_something_importable() -> None:
    """`[project.scripts]` names `lczkit.cli:main`, and a rename would break the installed command
    without breaking a single import in the package."""
    pyproject = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
    assert 'lczkit = "lczkit.cli:main"' in pyproject

    from lczkit.cli import main

    assert callable(main)


def test_version_prints_the_package_version() -> None:
    from lczkit import __version__

    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


# --------------------------------------------------------------------------- locating an extent


def test_a_run_needs_exactly_one_locator() -> None:
    """Neither flag, or both, is a mistake worth catching before `DATA_DIR` is even resolved."""
    for argv in ([], ["--bbox", "1,2,3,4", "--city", "berlin"]):
        result = runner.invoke(app, ["run", *argv])
        assert result.exit_code == EXIT_CONFIG
        assert "exactly one of --bbox or --city" in result.output


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("1,2,3", "four comma-separated"),
        ("1,2,3,4,5", "four comma-separated"),
        ("a,2,3,4", "must be numbers"),
        ("10,2,5,4", "-180 <= W < E <= 180"),
        ("1,50,3,20", "-90 <= S < N <= 90"),
        ("-200,2,3,4", "-180 <= W < E <= 180"),
    ],
)
def test_a_malformed_bbox_is_refused_with_the_reason(value: str, message: str) -> None:
    """A reversed or transposed bbox otherwise produces an empty Overture extract and a confusing
    failure about an empty frame, having already spent the download."""
    result = runner.invoke(app, ["run", "--bbox", value])
    assert result.exit_code != 0
    assert message in result.output


def test_an_unknown_city_lists_the_ones_that_exist(data_dir: Path) -> None:
    result = runner.invoke(app, ["run", "--city", "atlantis"])
    assert result.exit_code == EXIT_CONFIG
    assert "unknown city 'atlantis'" in result.output
    assert "berlin" in result.output


def test_a_non_positive_extent_is_refused(data_dir: Path) -> None:
    result = runner.invoke(app, ["run", "--bbox", "13.0,52.0,13.1,52.1", "--extent-km", "0"])
    assert result.exit_code == EXIT_CONFIG
    assert "--extent-km must be positive" in result.output


# --------------------------------------------------------------------------- configuration


def test_a_missing_data_dir_is_a_message_and_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLAUDE.md asks config problems to fail loudly and early. A stack trace is loud but not
    clear — the message already names the fix, and the trace only buries it.

    `load_dotenv` is neutralised because `Settings.load` searches upward for a `.env` and the tests
    run with the repository root as the working directory, so the real `DATA_DIR` would otherwise
    be found. That search is not what this test is about.
    """
    monkeypatch.setattr("lczkit.config.load_dotenv", lambda **_: None)
    result = runner.invoke(app, ["run", "--bbox", "13.0,52.0,13.1,52.1"])
    assert result.exit_code == EXIT_CONFIG
    assert "DATA_DIR is not set" in result.output
    assert "Traceback" not in result.output


def test_an_unknown_preset_lists_the_ones_that_exist(data_dir: Path) -> None:
    result = runner.invoke(
        app, ["run", "--bbox", "13.0,52.0,13.1,52.1", "--preset", "nonesuch", "--dry-run"]
    )
    assert result.exit_code == EXIT_CONFIG
    assert "unknown run preset 'nonesuch'" in result.output
    assert "published" in result.output


def test_dry_run_creates_nothing(data_dir: Path) -> None:
    """`Settings.load` creates `run_dir` as a side effect, which would make a command whose whole
    purpose is *not* to act still leave a directory behind."""
    result = runner.invoke(
        app, ["run", "--bbox", "13.0,52.0,13.1,52.1", "--run-id", "dry", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert not (data_dir / "output" / "lczkit" / "dry").exists()


def test_dry_run_reports_the_configuration_it_would_use(data_dir: Path) -> None:
    result = runner.invoke(
        app, ["run", "--bbox", "13.0,52.0,13.1,52.1", "--run-id", "dry", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout[result.stdout.index("{") :])
    assert payload["run_id"] == "dry"
    assert payload["bbox"] == [13.0, 52.0, 13.1, 52.1]
    assert payload["preset"] == "published"
    # The preset has to have been applied, or the run it describes could not start.
    assert payload["config"]["cleaning"]["building_max_area_m2"] == 100_000.0
    assert payload["config"]["overture"]["release"] is not None


def test_a_config_file_overrides_one_section_and_leaves_the_rest(
    data_dir: Path, tmp_path: Path
) -> None:
    """A partial document is the useful case — a file naming only `classification` should not have
    to restate the cleaning thresholds."""
    config = tmp_path / "over.json"
    config.write_text(json.dumps({"classification": {"lcz10_min_industrial_fraction": 0.9}}))
    result = runner.invoke(
        app,
        ["run", "--bbox", "13.0,52.0,13.1,52.1", "--config", str(config), "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout[result.stdout.index("{") :])
    assert payload["config"]["classification"]["lcz10_min_industrial_fraction"] == 0.9
    assert payload["config"]["cleaning"]["building_max_area_m2"] == 100_000.0


def test_a_run_manifest_works_as_a_config_file(data_dir: Path, tmp_path: Path) -> None:
    """A manifest nests the settings under `config`, and it is the most likely thing to be handed
    to this flag — accepting it means a run can be reproduced from its own output."""
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"config": {"classification": {"lcz10_min_industrial_fraction": 0.8}}})
    )
    result = runner.invoke(
        app,
        ["run", "--bbox", "13.0,52.0,13.1,52.1", "--config", str(manifest), "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout[result.stdout.index("{") :])
    assert payload["config"]["classification"]["lcz10_min_industrial_fraction"] == 0.8


def test_a_config_file_may_not_move_the_output_directory(data_dir: Path, tmp_path: Path) -> None:
    """`data_dir` and `run_id` come from the environment and the command line. A file that could
    move either would make the same command write to two different places depending on a path the
    user did not type."""
    config = tmp_path / "bad.json"
    config.write_text(json.dumps({"data_dir": "/somewhere/else"}))
    result = runner.invoke(
        app, ["run", "--bbox", "13.0,52.0,13.1,52.1", "--config", str(config), "--dry-run"]
    )
    assert result.exit_code != 0
    assert "data_dir" in result.output


def test_a_config_file_with_an_unknown_section_says_what_is_valid(
    data_dir: Path, tmp_path: Path
) -> None:
    config = tmp_path / "bad.json"
    config.write_text(json.dumps({"clasification": {}}))
    result = runner.invoke(
        app, ["run", "--bbox", "13.0,52.0,13.1,52.1", "--config", str(config), "--dry-run"]
    )
    assert result.exit_code != 0
    assert "unknown settings" in result.output
    assert "classification" in result.output


# --------------------------------------------------------------------------- site


def test_site_build_refuses_a_directory_that_is_not_a_run(tmp_path: Path) -> None:
    """The commonest mistake is passing `site/` rather than the run directory that contains it."""
    result = runner.invoke(app, ["site", "build", str(tmp_path)])
    assert result.exit_code == EXIT_CONFIG
    assert "not a run directory" in result.output


def test_site_serve_says_how_to_build_when_there_is_no_site(tmp_path: Path) -> None:
    result = runner.invoke(app, ["site", "serve", str(tmp_path)])
    assert result.exit_code == EXIT_CONFIG
    assert "lczkit site build" in result.output


def test_site_commands_reject_a_path_that_does_not_exist(tmp_path: Path) -> None:
    missing = tmp_path / "absent"
    for argv in (["site", "build"], ["site", "serve"]):
        result = runner.invoke(app, [*argv, str(missing)])
        assert result.exit_code != 0


# --------------------------------------------------------------------------- the drift guard


def test_the_published_preset_holds_the_values_the_published_runs_used() -> None:
    """The preset moved into the package; the constants it was built from are still in the script
    that measured them. If either is edited alone, the command line stops reproducing the sites.

    This is the check CLAUDE.md's Phase 14 ruling asks for — the two must be compared to each
    other, because nothing else notices when one moves.
    """
    script = load_script("berlin_metropolitan")
    published = PRESETS["published"]

    assert published.overture_release == script.RELEASE
    assert published.cleaning.model_dump() == script.CLEANING.model_dump()


def test_the_published_preset_keeps_the_areal_confidences_the_experiments_share() -> None:
    """`AREAL_CONFIDENCE` is an ordinal quality ranking with no published number behind it. The
    experiment arms and a command-line run must not disagree about it, or two runs of the same city
    carry different confidence claims into their manifests."""
    from lczkit.presets import AREAL_CONFIDENCE

    script = load_script("unit_scale_experiment")
    assert AREAL_CONFIDENCE == script.AREAL_CONFIDENCE


def test_the_publish_driver_configures_a_run_the_same_way_the_cli_does(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`scripts/berlin_metropolitan_run.configure` is what every published site went through, and
    `lczkit run` applies the preset directly. They must land on the same `Settings`."""
    script = load_script("berlin_metropolitan_run")

    from_script = script.configure(Settings.load(run_id="a", create_run_dir=False))
    from_cli = apply_preset(Settings.load(run_id="a", create_run_dir=False))
    from_cli.viz.include_buildings = False

    assert from_script.model_dump() == from_cli.model_dump()
