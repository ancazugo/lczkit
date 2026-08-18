"""`lczkit cities` — finding an extent before committing a download to it.

Runs against the committed twelve-row GUPPD fixture, so none of this needs the real table.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from lczkit.cli import app
from lczkit.cli._render import EXIT_CONFIG, LARGE_EXTENT_KM2

runner = CliRunner()


def test_a_search_lists_every_city_matching_the_query(places_data_dir: Path) -> None:
    result = runner.invoke(app, ["cities", "london"])

    assert result.exit_code == 0
    assert "United Kingdom" in result.output
    assert "Canada" in result.output
    assert "East London" in result.output


def test_a_country_narrows_the_search(places_data_dir: Path) -> None:
    result = runner.invoke(app, ["cities", "cambridge", "--country", "GBR"])

    assert result.exit_code == 0
    assert "United Kingdom" in result.output
    assert "Canada" not in result.output


def test_a_country_alone_lists_that_country(places_data_dir: Path) -> None:
    result = runner.invoke(app, ["cities", "--country", "KEN"])

    assert result.exit_code == 0
    assert "Nairobi" in result.output
    assert "Mombasa" in result.output
    assert "Berlin" not in result.output


def test_an_accented_name_is_reachable_by_its_plain_spelling(places_data_dir: Path) -> None:
    result = runner.invoke(app, ["cities", "sao paulo"])

    assert result.exit_code == 0
    assert "Brazil" in result.output


def test_the_bbox_is_printed_in_a_form_that_can_be_pasted_into_bbox(places_data_dir: Path) -> None:
    """The column exists to be copied into `--bbox`, so it is folded rather than truncated.

    Rich abbreviates an over-wide cell with an ellipsis by default, which would put `13.12…` in
    front of someone whose next action is to paste it.
    """
    result = runner.invoke(app, ["cities", "berlin"], terminal_width=100)

    assert "…" not in result.output
    assert "13.1209" in result.output


def test_a_large_region_is_flagged_with_the_flag_that_trims_it(places_data_dir: Path) -> None:
    """Jakarta's urban region is 17 661 km2 in the real table and 1 400 in the fixture window.

    Either way it is far past the extent Berlin's 9.8-minute benchmark was measured over, and the
    area column is the only thing in the interface that predicts a run's wall time.
    """
    result = runner.invoke(app, ["cities", "jakarta"])

    assert result.exit_code == 0
    assert f"{LARGE_EXTENT_KM2:,.0f} km2" in result.output
    assert "--extent-km" in result.output


def test_a_small_region_is_not_flagged(places_data_dir: Path) -> None:
    result = runner.invoke(app, ["cities", "cambridge", "--country", "GBR"])

    assert "--extent-km" not in result.output


def test_the_cities_carrying_a_so2sat_window_are_marked(places_data_dir: Path) -> None:
    """`--so2sat-window` works for 28 cities and no others, and the column says which.

    Without it a reader has to try the flag to discover whether their city is one of the ones a
    recorded agreement figure exists for.
    """
    marked = runner.invoke(app, ["cities", "berlin"])
    unmarked = runner.invoke(app, ["cities", "mombasa"])

    assert "*" in marked.output
    assert "*" not in unmarked.output


def test_the_mark_goes_on_the_right_country(places_data_dir: Path) -> None:
    """Matching on the name alone marked three cities that have no So2Sat labels at all.

    The registry is keyed by name; **London**, **Santiago** and **Los Angeles** each name a city in
    more than one country, so a name-only match told a reader to try `--so2sat-window` on London,
    Ontario. The registry carries an ISO code for exactly this.
    """
    result = runner.invoke(app, ["cities", "london"], terminal_width=200)

    rows = [line for line in result.output.splitlines() if "London" in line]
    marked = [line for line in rows if "*" in line]

    assert len(marked) == 1, rows
    assert "United Kingdom" in marked[0]


def test_a_city_the_registry_does_not_hold_is_unmarked_even_under_a_shared_name(
    places_data_dir: Path,
) -> None:
    result = runner.invoke(app, ["cities", "cambridge"], terminal_width=200)

    assert "*" not in result.output


def test_a_query_matching_nothing_is_an_error_rather_than_an_empty_table(
    places_data_dir: Path,
) -> None:
    result = runner.invoke(app, ["cities", "atlantis"])

    assert result.exit_code == EXIT_CONFIG
    assert "atlantis" in result.output


def test_a_limit_bounds_the_output_and_says_what_was_left_out(places_data_dir: Path) -> None:
    result = runner.invoke(app, ["cities", "--limit", "2"])

    assert result.exit_code == 0
    assert "more" in result.output


def test_the_command_needs_no_run_directory(places_data_dir: Path) -> None:
    """It resolves configuration and writes nothing, so it must not leave an output directory
    behind — the same defect `--dry-run` was fixed for."""
    runner.invoke(app, ["cities", "berlin"])

    assert not (places_data_dir / "output").exists()


def test_a_missing_bounds_table_is_a_message_and_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "input").mkdir()
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    result = runner.invoke(app, ["cities", "berlin"])

    assert result.exit_code == EXIT_CONFIG
    assert "guppd_bounds.csv" in result.output
