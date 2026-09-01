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

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import typer
from conftest import load_script
from typer.testing import CliRunner

from lczkit.cli import app
from lczkit.cli._render import EXIT_CONFIG, EXIT_MISSING_TOOL

# By function, not by module: `lczkit.cli.__init__` binds the name `run` to the command function,
# which shadows the submodule of the same name for `from lczkit.cli import run`.
from lczkit.cli.run import _report_site
from lczkit.config import Settings
from lczkit.output import MANIFEST_FILE
from lczkit.pipeline import PipelineResult
from lczkit.presets import AREAL_CONFIDENCE, PRESETS, apply_preset

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


# --------------------------------------------------------------------------- help and wiring


def test_every_command_has_help_that_does_not_need_data_dir() -> None:
    """`--help` must work on a clean checkout, before anything is configured.

    It is the first thing anyone runs, and a traceback about `DATA_DIR` at that point reads as
    "this package is broken" rather than "you have not set it up yet".
    """
    for argv in ([], ["run"], ["export"], ["site"], ["site", "build"], ["site", "serve"]):
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


def test_an_unknown_city_says_how_to_search_for_the_right_name(places_data_dir: Path) -> None:
    """The registry used to be 28 cities and an unknown name could list them all. It is now 5 558
    urban regions, so the useful answer is the search command rather than the catalogue."""
    result = runner.invoke(app, ["run", "--city", "atlantis"])
    assert result.exit_code == EXIT_CONFIG
    assert "lczkit cities" in result.output


def test_a_city_without_the_bounds_table_names_the_file_and_offers_bbox(data_dir: Path) -> None:
    """`--bbox` needs nothing on disk, and that is the thing to say when a locator's data is
    missing rather than reporting a file error with no way forward."""
    result = runner.invoke(app, ["run", "--city", "berlin"])
    assert result.exit_code == EXIT_CONFIG
    assert "guppd_bounds.csv" in result.output
    assert "--bbox" in result.output


def test_an_ambiguous_city_is_refused_with_the_candidates(places_data_dir: Path) -> None:
    """Two Cambridges, and taking the first would run the wrong continent under a manifest that
    looks entirely correct."""
    result = runner.invoke(app, ["run", "--city", "cambridge"])
    assert result.exit_code == EXIT_CONFIG
    assert "--country" in result.output


def test_a_named_city_resolves_to_its_gazetteer_extent(places_data_dir: Path) -> None:
    """The general locator: a name in, that region's window out, recorded with the row it came
    from so the run can say which of two same-named cities it covered."""
    result = runner.invoke(app, ["run", "--city", "cambridge", "--country", "GBR", "--dry-run"])
    assert result.exit_code == 0

    plan = json.loads(result.stdout[result.stdout.index("{") :])
    extent = plan["extent"]
    assert extent["kind"] == "guppd"
    assert extent["name"] == "Cambridge"
    assert extent["iso"] == "GBR"
    assert extent["smod_id"] == "30_4732"
    assert plan["bbox"] == list(extent["bbox"])
    assert 50 < extent["area_km2"] < 80


def test_shrinking_a_city_keeps_the_locator_and_records_what_it_was_trimmed_from(
    places_data_dir: Path,
) -> None:
    """A 3 km trial over Cambridge is still a run about Cambridge.

    Replacing the locator with a bare bbox on shrink is how a directory of trial runs becomes
    unreadable — every one of them a rectangle with no name.
    """
    result = runner.invoke(
        app,
        ["run", "--city", "cambridge", "--country", "GBR", "--extent-km", "3", "--dry-run"],
    )
    extent = json.loads(result.stdout[result.stdout.index("{") :])["extent"]

    assert extent["kind"] == "guppd"
    assert extent["name"] == "Cambridge"
    assert extent["extent_km"] == 3.0
    assert extent["source_bbox"] is not None
    assert extent["area_km2"] < 12.0


def test_the_so2sat_window_is_a_flag_and_not_a_fallback(places_data_dir: Path) -> None:
    """Two locators that mean different ground, so neither may be reached by accident.

    `--so2sat-window` gives the extent every recorded agreement figure was measured over. Falling
    back to it — or silently past it — is how a run comes to look comparable with a published
    number when it covers different ground. Asking for it where no labelled window exists is an
    error naming the flag, not a quiet substitution of the region.
    """
    unlisted = runner.invoke(app, ["run", "--city", "mombasa", "--so2sat-window", "--dry-run"])
    assert unlisted.exit_code == EXIT_CONFIG
    assert "Drop the flag" in unlisted.output


def test_a_country_is_checked_against_the_labelled_window_rather_than_ignored(
    places_data_dir: Path,
) -> None:
    """`--city london --country CAN --so2sat-window` must not run London, UK.

    The So2Sat registry is keyed by name and three of its keys name a city that exists in more than
    one country, so ignoring `--country` here overrules the caller's own disambiguation and returns
    the wrong continent under a manifest that looks entirely correct. This is the exact failure the
    two-locator split exists to prevent, reachable through the flag that implements it.
    """
    wrong = runner.invoke(
        app, ["run", "--city", "london", "--country", "CAN", "--so2sat-window", "--dry-run"]
    )
    assert wrong.exit_code == EXIT_CONFIG
    assert "GBR" in wrong.output
    assert "not 'CAN'" in wrong.output

    # The matching country gets past the check and fails on the archive instead, which is as far
    # as this can go without So2Sat on disk — and is exactly the distinction being asserted.
    right = runner.invoke(
        app, ["run", "--city", "london", "--country", "GBR", "--so2sat-window", "--dry-run"]
    )
    assert right.exit_code == EXIT_CONFIG
    assert "So2Sat" in right.output
    assert "GBR" not in right.output


def test_every_registry_city_carries_the_country_its_labels_are_in() -> None:
    """The field that stops the two locators colliding, asserted as present and plausible.

    It is not derived from anything — the So2Sat archive has no country dimension — so nothing
    else would notice a city added without one, or with a two-letter code where the gazetteer uses
    three.
    """
    from lczkit.cities import CITIES

    assert len(CITIES) == 28
    for city in CITIES:
        assert len(city.iso) == 3 and city.iso.isupper(), city
    assert {city.key: city.iso for city in CITIES}["london"] == "GBR"
    assert {city.key: city.iso for city in CITIES}["santiago"] == "CHL"
    assert {city.key: city.iso for city in CITIES}["los_angeles"] == "USA"


def test_the_city_flags_are_refused_alongside_an_explicit_bbox(data_dir: Path) -> None:
    for extra in (["--country", "GBR"], ["--so2sat-window"]):
        result = runner.invoke(app, ["run", "--bbox", "13.0,52.0,13.1,52.1", *extra, "--dry-run"])
        assert result.exit_code == EXIT_CONFIG
        assert "only apply to --city" in result.output


def test_an_explicit_bbox_records_itself_as_the_locator(data_dir: Path) -> None:
    """A library caller who computed their own window can claim nothing more than the window."""
    result = runner.invoke(app, ["run", "--bbox", "13.0,52.0,13.1,52.1", "--dry-run"])
    extent = json.loads(result.stdout[result.stdout.index("{") :])["extent"]

    assert extent["kind"] == "bbox"
    assert extent["name"] is None
    assert extent["bbox"] == [13.0, 52.0, 13.1, 52.1]


def test_a_non_positive_extent_is_refused(data_dir: Path) -> None:
    result = runner.invoke(app, ["run", "--bbox", "13.0,52.0,13.1,52.1", "--extent-km", "0"])
    assert result.exit_code == EXIT_CONFIG
    assert "--extent-km must be positive" in result.output


# --------------------------------------------------------------------------- configuration


def test_a_missing_data_dir_is_a_message_and_not_a_traceback() -> None:
    """CLAUDE.md asks config problems to fail loudly and early. A stack trace is loud but not
    clear — the message already names the fix, and the trace only buries it.

    The `.env` neutralisation this used to do inline now lives in `conftest._clean_data_dir_env`,
    where it applies to every test rather than to the one that noticed it was needed.
    """
    result = runner.invoke(app, ["run", "--bbox", "13.0,52.0,13.1,52.1"])
    assert result.exit_code == EXIT_CONFIG
    assert "DATA_DIR is not set" in result.output
    assert "Traceback" not in result.output


def test_an_argument_is_judged_before_the_environment_is_consulted() -> None:
    """A malformed argument must name the argument, even with no `DATA_DIR` anywhere.

    `run` used to load `Settings` first, so `--bbox 1,2,3` answered "DATA_DIR is not set" — it
    blamed the environment for a typo, at the one moment the reader has neither configured yet and
    cannot tell which of the two is really wrong. `--city` is the deliberate exception below: its
    locators read their tables through `settings.source_dir`, so there the environment genuinely
    is the blocker and saying so is correct.
    """
    for argv, expected in (
        (["run", "--bbox", "1,2,3"], "four comma-separated"),
        (["run", "--bbox", "10,2,5,4"], "-180 <= W < E <= 180"),
        (["run", "--bbox", "13.0,52.0,13.1,52.1", "--basemap", "nonesuch"], "unknown basemap"),
        (["run", "--bbox", "13.0,52.0,13.1,52.1", "--extent-km", "0"], "must be positive"),
        (
            ["run", "--bbox", "13.0,52.0,13.1,52.1", "--land-cover-source", "nonesuch"],
            "unknown land-cover source",
        ),
    ):
        result = runner.invoke(app, argv)
        assert result.exit_code != 0, f"{argv} was accepted"
        assert expected in result.output, f"{argv} said:\n{result.output}"
        assert "DATA_DIR" not in result.output, f"{argv} blamed the environment:\n{result.output}"

    blocked = runner.invoke(app, ["run", "--city", "berlin"])
    assert blocked.exit_code == EXIT_CONFIG
    assert "DATA_DIR is not set" in blocked.output


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


# --------------------------------------------------------------------------- base maps


def _dry_run_config(data_dir: Path, *argv: str, section: str = "viz") -> dict:
    result = runner.invoke(
        app, ["run", "--bbox", "13.0,52.0,13.1,52.1", "--run-id", "dry", "--dry-run", *argv]
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout[result.stdout.index("{") :])["config"][section]


def test_no_basemap_flag_offers_the_keyless_grounds(data_dir: Path) -> None:
    """The command-line default, which is deliberately *not* the library default.

    `VizConfig()` is still empty and `build_site()` still reaches no network unasked — that is the
    property the no-external-reference test pins. What differs is the command a person types to
    look at a map: a keyless ground costs them nothing and publishes nothing, so making them ask
    for it twice bought a guarantee that only the library needed.
    """
    from lczkit.viz.basemaps import DEFAULT_BASEMAP_KEYS

    assert _dry_run_config(data_dir)["online_basemaps"] == list(DEFAULT_BASEMAP_KEYS)


def test_the_default_grounds_publish_no_api_key(data_dir: Path) -> None:
    """The line between the two defaults, and the reason it is drawn at `requires_key`.

    A keyed provider writes an API key into every site built with it, so it cannot be something a
    caller gets without asking. Derived from `requires_key` rather than listed, so a keyed provider
    added later cannot join the defaults by being forgotten.
    """
    from lczkit.viz.basemaps import PROVIDERS

    for key in _dry_run_config(data_dir)["online_basemaps"]:
        assert not PROVIDERS[key].requires_key, key


def test_basemap_none_asks_for_a_site_that_reaches_no_network(data_dir: Path) -> None:
    """ "I did not say" and "I said no" are different, and only one of them is an instruction."""
    assert _dry_run_config(data_dir, "--basemap", "none")["online_basemaps"] == []


def test_the_basemap_flag_repeats_and_keeps_its_order(data_dir: Path) -> None:
    """Order is what the reader's dropdown is built in, so it is a decision and not incidental."""
    viz = _dry_run_config(data_dir, "--basemap", "carto-dark", "--basemap", "osm")

    assert viz["online_basemaps"] == ["carto-dark", "osm"]


def test_the_basemap_flag_takes_a_comma_separated_list(data_dir: Path) -> None:
    viz = _dry_run_config(data_dir, "--basemap", "osm,esri-satellite")

    assert viz["online_basemaps"] == ["osm", "esri-satellite"]


def test_basemap_all_offers_every_provider(data_dir: Path) -> None:
    from lczkit.viz.basemaps import PROVIDERS

    viz = _dry_run_config(data_dir, "--basemap", "all")

    assert set(viz["online_basemaps"]) == set(PROVIDERS)


def test_the_licence_and_the_terms_are_printed_when_a_basemap_is_chosen(data_dir: Path) -> None:
    """Selecting a provider takes on its usage policy, and for MapTiler it publishes an API key in
    the built site. Both belong at the moment the choice is made, not in the output afterwards."""
    result = runner.invoke(
        app,
        [
            "run",
            "--bbox",
            "13.0,52.0,13.1,52.1",
            "--run-id",
            "dry",
            "--dry-run",
            "--basemap",
            "osm",
            "--basemap",
            "maptiler-topo",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "OpenStreetMap" in result.output
    assert "donated resource" in result.output  # the OSMF tile policy
    assert "plain text" in result.output  # the key travels with the site


# ------------------------------------------------------------------- choosing a land-cover backend


def test_land_cover_defaults_to_the_local_backend(data_dir: Path) -> None:
    """The default is the path that needs nothing but HTTP.

    Earth Engine wants credentials, a billable project and a quota, and it is not what continuous
    integration exercises — so a default requiring all three would make a first run fail on setup
    rather than on data.
    """
    assert _dry_run_config(data_dir, section="land_cover")["source"] == "local"


def test_the_land_cover_flag_selects_the_earth_engine_backend(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`EarthEngineSource` existed and was schema-identical to the local backend for several
    phases, and no chain could reach it — setting `GEE_PROJECT_NAME` had no effect on `lczkit run`
    at all. This is the flag that reaches it."""
    monkeypatch.setenv("GEE_PROJECT_NAME", "a-project")

    resolved = _dry_run_config(data_dir, "--land-cover-source", "gee", section="land_cover")

    assert resolved["source"] == "gee"
    assert resolved["gee_project"] == "a-project"


def test_the_preset_does_not_discard_the_project_the_environment_supplied(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`gee_project` is a credential, not a measured configuration, and a preset must not clear it.

    `RunPreset.apply` replaces the whole `land_cover` section, so it overwrote the value
    `Settings.load` had just read from `GEE_PROJECT_NAME` — every `lczkit run` cleared the variable
    moments after reading it. Invisible while nothing downstream read the field, and immediately
    fatal once a backend did. The same silent-discard failure `Settings.load` documents in the
    other direction, one layer up.
    """
    monkeypatch.setenv("GEE_PROJECT_NAME", "a-project")

    from_load = Settings.load(run_id="a", create_run_dir=False)
    assert from_load.land_cover.gee_project == "a-project"

    assert apply_preset(from_load).land_cover.gee_project == "a-project"


def test_earth_engine_without_a_project_is_refused_before_the_run_starts(data_dir: Path) -> None:
    """A dry run's whole purpose is to say whether the configuration will run.

    Without this it printed "as project None" and exited zero, which is the one command that must
    not do that. The check is `landcover.earthengine.check_asset` rather than a second copy of it,
    so the library still refuses the same way when a caller skips the command line.
    """
    result = runner.invoke(
        app,
        ["run", "--bbox", "13.0,52.0,13.1,52.1", "--dry-run", "--land-cover-source", "gee"],
    )

    assert result.exit_code == EXIT_CONFIG
    assert "GEE_PROJECT_NAME" in result.output
    assert "Traceback" not in result.output


def test_the_land_cover_flag_beats_a_config_file_that_also_names_a_backend(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not passing the flag leaves the file's answer alone; passing it overrules the file.

    Both directions are needed, which is why `parse_land_cover_source` returns `None` for an absent
    flag rather than the default name — a flag that could not tell "I did not say" from "local"
    would silently overrule a config file on every run that did not repeat it.
    """
    monkeypatch.setenv("GEE_PROJECT_NAME", "a-project")
    config = tmp_path / "gee.json"
    config.write_text(json.dumps({"land_cover": {"source": "gee", "gee_project": "a-project"}}))

    deferred = _dry_run_config(data_dir, "--config", str(config), section="land_cover")
    overruled = _dry_run_config(
        data_dir, "--config", str(config), "--land-cover-source", "local", section="land_cover"
    )

    assert deferred["source"] == "gee"
    assert overruled["source"] == "local"


@pytest.mark.parametrize("command", [["run", "--bbox", "13.0,52.0,13.1,52.1"], None])
def test_an_unknown_basemap_is_refused_the_same_way_by_both_commands(
    data_dir: Path, tmp_path: Path, command: list[str] | None
) -> None:
    """One flag, one meaning. `run` used to check `PROVIDERS` directly while `site build`
    round-tripped the config, and only `site build` accepted `none` — so the same argument was an
    error in one command and an instruction in the other."""
    if command is None:
        (tmp_path / MANIFEST_FILE).write_text(json.dumps({"config": {"viz": {}}}))
        argv = ["site", "build", str(tmp_path)]
    else:
        argv = [*command, "--dry-run"]

    result = runner.invoke(app, [*argv, "--basemap", "nonesuch"])

    assert result.exit_code != 0
    assert "unknown basemap" in result.output
    assert "esri-satellite" in result.output


def test_an_absent_flag_and_an_explicit_none_stay_distinguishable() -> None:
    """The distinction `apply_basemaps` resolves. Collapsing them would make a ground unremovable
    on rebuild, or make every rebuild silently re-add one."""
    from lczkit.cli._options import parse_basemaps

    assert parse_basemaps(None) is None
    assert parse_basemaps(["none"]) == []
    assert parse_basemaps(["osm", "none"]) == ["osm"]


def test_rebuilding_a_run_does_not_change_the_grounds_it_recorded() -> None:
    """A rebuild reproduces a site; it does not redecide it.

    The default fills a gap — an older run recorded nothing, and rebuilding it is exactly when a
    reader wants grounds — but a run that recorded a choice has already answered, and quietly
    adding three more to it would make a rebuilt site disagree with the one it replaced.
    """
    from lczkit.cli._options import apply_basemaps
    from lczkit.config import VizConfig

    recorded = VizConfig(online_basemaps=["carto-dark"])
    apply_basemaps(recorded, None)
    assert recorded.online_basemaps == ["carto-dark"]

    # And the deprecated singular counts as a recorded choice, since that is what old runs wrote.
    archived = VizConfig(online_basemap="osm")
    apply_basemaps(archived, None)
    assert archived.online_basemaps == ["osm"]


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


# --------------------------------------------------------------------------- export


def test_export_writes_a_geopackage_and_names_the_crs(tmp_path: Path) -> None:
    """It reports the CRS because that is the thing a reader came here missing — a GIS without
    GDAL's optional Parquet driver reports a correct GeoParquet as having none."""
    import geopandas as gpd
    from shapely.geometry import box

    from lczkit.output import GPKG_FILE, UNITS_FILE

    gpd.GeoDataFrame(
        {"unit_id": ["grid_0"]}, geometry=[box(0.0, 0.0, 100.0, 100.0)], crs="EPSG:32633"
    ).set_index("unit_id").to_parquet(tmp_path / UNITS_FILE)

    result = runner.invoke(app, ["export", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert (tmp_path / GPKG_FILE).exists()
    assert "EPSG:32633" in result.output


def test_export_refuses_a_directory_that_is_not_a_run(tmp_path: Path) -> None:
    result = runner.invoke(app, ["export", str(tmp_path)])
    assert result.exit_code == EXIT_CONFIG
    # Whitespace-collapsed: rich wraps the message, and where it wraps depends on the path length.
    assert "not a run directory" in " ".join(result.output.split())


# --------------------------------------------------------------------------- the drift guard


def test_the_published_preset_still_holds_the_measured_metropolitan_values() -> None:
    """The eight cleaning numbers the published sites went through, pinned to literals.

    They used to be pinned by comparing two copies — one in `lczkit.presets` and one in
    `scripts/berlin_metropolitan.py` — which answered "have these drifted apart?" and not "are
    these the right numbers?". The scripts now derive theirs from the preset, so that comparison
    has no subject left; this asserts the values themselves, which is what it was standing in for.
    `lczkit.presets._published_cleaning` records what each was measured against.

    `building_max_area_m2` is the one to watch. `scripts/unit_scale_experiment.py` carries a
    genuinely different `CleaningConfig` for the 9 km² arms whose value is 50 000, and CLAUDE.md
    records taking the wrong one of the two as a real failure — it would make `lczkit run`
    silently irreproducible against every published figure.
    """
    cleaning = PRESETS["published"].cleaning

    assert cleaning.building_max_area_m2 == 100_000.0
    assert cleaning.building_min_area_m2 == 20.0
    assert cleaning.building_merge_limit_m2 == 50.0
    assert cleaning.building_overlap_limit == 0.1
    assert cleaning.building_road_buffer_m == 4.0
    assert cleaning.building_road_overlap_limit == 0.5
    assert cleaning.street_tile_size_m == 2000.0
    assert cleaning.street_tile_buffer_m == 600.0
    assert PRESETS["published"].overture_release == "2026-07-22.0"


def test_the_experiment_scripts_take_their_configuration_from_the_preset() -> None:
    """One definition, and the scripts read it rather than restating it.

    `scripts/berlin_metropolitan.CLEANING`/`RELEASE` and
    `scripts/unit_scale_experiment.AREAL_CONFIDENCE`/`HEIGHTS` were copies of what
    `lczkit.presets` holds, guarded by tests asserting the copies still matched. The copies are
    gone; this asserts the derivation is still in place, so a future edit cannot reintroduce a
    literal without failing here.

    Equal but **not identical**: each script copies the model rather than aliasing it, because
    several drivers build variants by mutation and a mutation reaching the preset would
    reconfigure every later run in the same process.
    """
    published = PRESETS["published"]
    metropolitan = load_script("berlin_metropolitan")
    experiment = load_script("unit_scale_experiment")

    assert metropolitan.RELEASE == published.overture_release
    assert metropolitan.CLEANING.model_dump() == published.cleaning.model_dump()
    assert metropolitan.CLEANING is not published.cleaning

    assert experiment.AREAL_CONFIDENCE == AREAL_CONFIDENCE
    assert experiment.HEIGHTS.model_dump() == published.heights.model_dump()
    assert experiment.HEIGHTS is not published.heights

    # The other `CLEANING` is a different measured configuration and must stay different.
    assert experiment.CLEANING.building_max_area_m2 != published.cleaning.building_max_area_m2


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


# --------------------------------------------------------------------------- the site is last


def _result(tmp_path: Path, *, skipped: str | None) -> PipelineResult:
    """A `PipelineResult` carrying only what `_report_site` reads."""
    outputs = SimpleNamespace(run_dir=tmp_path / "20260101T000000Z")
    return cast(
        PipelineResult,
        SimpleNamespace(site=None, site_skipped=skipped, outputs=outputs, run_dir=outputs.run_dir),
    )


def test_a_missing_tippecanoe_is_reported_without_losing_the_run(tmp_path: Path) -> None:
    """The site is the last stage and every other file is on disk before it starts.

    The error used to propagate out of `run_pipeline` and become an exit code *before* the line
    naming the run directory was printed, so a ten-minute city whose only problem was an absent
    tool reported as a run that produced nothing. The exit code stays non-zero — a site was asked
    for and not produced — but the directory is named and so is the command that finishes it.
    """
    with pytest.raises(typer.Exit) as exit_info:
        _report_site(_result(tmp_path, skipped="tippecanoe is required"))

    assert exit_info.value.exit_code == EXIT_MISSING_TOOL


def test_a_run_that_wanted_no_site_reports_nothing_and_exits_cleanly(tmp_path: Path) -> None:
    """`--no-site` is not a failure, so it must not take the non-zero path."""
    _report_site(_result(tmp_path, skipped=None))
