"""Pydantic configuration model for lczkit runs.

`DATA_DIR` is resolved exactly once, here, via `Settings.load()`. Every other module reaches
data through `settings.input_dir`, `settings.output_dir`, `settings.source_dir(name)`, and
`settings.run_dir` — nothing else reads `os.environ` or builds a path from `__file__` or the
current working directory.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator


def _default_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


class Settings(BaseModel):
    """Resolved configuration for a single lczkit run.

    Construct via `Settings.load()`, not directly — that is what resolves `DATA_DIR` from
    the environment and creates the run's output directory.
    """

    data_dir: Path
    run_id: str = Field(default_factory=_default_run_id)

    @field_validator("data_dir")
    @classmethod
    def _validate_data_dir(cls, value: Path) -> Path:
        if not value.is_dir():
            raise ValueError(
                f"DATA_DIR does not exist or is not a directory: {value}. "
                "Set DATA_DIR in .env to the shared data directory."
            )
        return value

    @property
    def input_dir(self) -> Path:
        """`$DATA_DIR/input/` — organised by data origin, owned by other projects too."""
        return self.data_dir / "input"

    @property
    def output_dir(self) -> Path:
        """`$DATA_DIR/output/` — organised by the tool that produced the results."""
        return self.data_dir / "output"

    @property
    def run_dir(self) -> Path:
        """`$DATA_DIR/output/lczkit/<run_id>/` — this run's own output directory."""
        return self.output_dir / "lczkit" / self.run_id

    def source_dir(self, name: str) -> Path:
        """Return `input/<name>/`, the directory a source implementation owns.

        Only the source implementation for `name` writes here; nothing else in the package
        writes under `input/` at all.
        """
        return self.input_dir / name

    @classmethod
    def load(cls, *, run_id: str | None = None, dotenv_path: Path | str | None = None) -> Settings:
        """Load `.env`, resolve `DATA_DIR`, and create `output/lczkit/<run_id>/` if absent.

        Never creates or modifies anything under `input/`. Raises `ValueError` with a clear
        message if `DATA_DIR` is unset; raises a `pydantic.ValidationError` (also with a
        clear message) if it is set but does not exist.
        """
        load_dotenv(dotenv_path=dotenv_path)
        raw_data_dir = os.environ.get("DATA_DIR")
        if raw_data_dir is None:
            raise ValueError(
                "DATA_DIR is not set. Copy .env.example to .env and point DATA_DIR at the "
                "shared data directory."
            )
        settings = (
            cls(data_dir=Path(raw_data_dir), run_id=run_id)
            if run_id is not None
            else cls(data_dir=Path(raw_data_dir))
        )
        settings.run_dir.mkdir(parents=True, exist_ok=True)
        return settings
