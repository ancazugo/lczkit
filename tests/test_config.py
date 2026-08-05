"""Tests for lczkit.config.Settings."""

from __future__ import annotations

from pathlib import Path

import pytest

from lczkit.config import Settings


def _no_dotenv(tmp_path: Path) -> Path:
    """A dotenv path guaranteed not to exist, so `load_dotenv()` is a no-op."""
    return tmp_path / "does-not-exist.env"


def test_load_raises_clear_error_when_data_dir_unset(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="DATA_DIR is not set"):
        Settings.load(dotenv_path=_no_dotenv(tmp_path))


def test_load_raises_clear_error_when_data_dir_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "does-not-exist"
    monkeypatch.setenv("DATA_DIR", str(missing))
    with pytest.raises(Exception, match="does not exist"):
        Settings.load(dotenv_path=_no_dotenv(tmp_path))


def test_load_resolves_data_dir_and_creates_run_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))

    settings = Settings.load(dotenv_path=_no_dotenv(tmp_path), run_id="20260101T000000Z")

    assert settings.data_dir == data_dir
    assert settings.input_dir == data_dir / "input"
    assert settings.output_dir == data_dir / "output"
    assert settings.run_dir == data_dir / "output" / "lczkit" / "20260101T000000Z"
    assert settings.run_dir.is_dir()


def test_load_never_creates_input_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))

    Settings.load(dotenv_path=_no_dotenv(tmp_path), run_id="run-a")

    assert not (data_dir / "input").exists()


def test_source_dir_is_under_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))

    settings = Settings.load(dotenv_path=_no_dotenv(tmp_path), run_id="run-a")

    assert settings.source_dir("Overture") == data_dir / "input" / "Overture"


def test_default_run_id_is_used_when_not_overridden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))

    settings = Settings.load(dotenv_path=_no_dotenv(tmp_path))

    assert settings.run_id
    assert settings.run_dir == data_dir / "output" / "lczkit" / settings.run_id


def test_json_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    settings = Settings.load(dotenv_path=_no_dotenv(tmp_path), run_id="run-a")

    restored = Settings.model_validate_json(settings.model_dump_json())

    assert restored == settings
