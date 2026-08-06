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


class OvertureConfig(BaseModel):
    """Configuration for `OvertureSource` (Phase 1)."""

    release: str | None = None
    """Pinned Overture release string, e.g. "2026-07-22.0". Never "latest" — `OvertureSource`
    raises if this is unset."""

    source_dir_name: str = "Overture_Maps"
    """Name of the subdirectory under `input/` that `OvertureSource` caches into. Matches the
    directory already used by other projects sharing `DATA_DIR`, not CLAUDE.md's diagram
    spelling ("Overture")."""


class CleaningConfig(BaseModel):
    """Configurable thresholds for the Phase 1 building-cleaning pipeline.

    None of these have a literature-derived default — Majer & Fleischmann (arXiv:2603.00132)
    Supplementary D, the paper CLAUDE.md names as the cleaning spec, describes the
    corresponding operations only qualitatively. They are left unset here; the cleaning
    pipeline raises if used before being explicitly configured.
    """

    building_max_area_m2: float | None = None
    """Footprints larger than this are dropped as implausible."""

    building_min_area_m2: float | None = None
    """Footprints smaller than this are absorbed into a touching larger neighbour, or dropped
    if they touch nothing."""

    building_merge_limit_m2: float | None = None
    """`geoplanar.merge_overlaps`' `merge_limit` — overlapping polygons smaller than this are
    merged into a neighbour regardless of overlap size."""

    building_overlap_limit: float | None = None
    """`geoplanar.merge_overlaps`' `overlap_limit` (0-1 ratio) — polygons larger than
    `building_merge_limit_m2` are merged only if the shared overlap exceeds this fraction of
    their area."""


class ArealTierConfig(BaseModel):
    """One areal raster tier of the Phase 3 height cascade (tiers 2-4).

    Areal products assign a *neighbourhood* mean to individual buildings, which is a
    categorically weaker measurement than a per-building height. Everything product-specific
    lives here rather than in code: none of these three products is present on this system, and
    none of their documentation is in `docs/references/datasets/`, so hardcoding a band number,
    a unit scale or a nodata value would be guessing at a product nobody has read the manual for.
    """

    name: str
    """The tier's `height_source` tag, e.g. `"ghsl"`. Must be unique within a cascade."""

    source_dir_name: str
    """Subdirectory under `input/` holding this product, resolved via `settings.source_dir()`."""

    filename: str | None = None
    """COG filename within `input/<source_dir_name>/`. `None` means the product is not available
    and the tier is skipped entirely — the cascade is shorter, not broken."""

    band: int = 1
    """1-based raster band carrying height."""

    scale: float = 1.0
    """Multiplier converting raw raster values to metres (e.g. 0.1 for a decimetre product)."""

    nodata: float | None = None
    """Override the raster's own declared nodata value. `None` uses whatever the file declares."""

    min_height_m: float = 0.0
    """Sampled values at or below this are treated as "no building here" rather than as a
    height, so the next tier gets a chance. Zero is the neutral choice: an areal height product
    reports 0 for cells with no built-up volume."""

    confidence: float | None = None
    """`height_confidence` written for every building this tier resolves. No default: see
    `HeightConfig`."""


def _default_areal_tiers() -> list[ArealTierConfig]:
    """CLAUDE.md's tiers 2, 3 and 4, in cascade order, all inert until a COG is placed.

    `source_dir_name` follows CLAUDE.md's `input/` diagram. Note that none of these three
    directories exists on the system this was developed against — `input/GHS/` is present but
    holds GHS-SMOD and GHS-UCDB, not GHS-BUILT-H — so expect to override the name as
    `OvertureConfig.source_dir_name` already does for `Overture_Maps`.
    """
    return [
        ArealTierConfig(name="gob25d", source_dir_name="GOB25D"),
        ArealTierConfig(name="wsf3d", source_dir_name="WSF3D"),
        ArealTierConfig(name="ghsl", source_dir_name="GHSL"),
    ]


class HeightConfig(BaseModel):
    """Configuration for the Phase 3 building-height cascade.

    Tiers run in the order they appear: Overture attributes first, then `areal_tiers` in list
    order. Adding a fifth areal product is an entry in that list, not a code change.

    The three `*_confidence` values have no default for the same reason `CleaningConfig`'s
    thresholds have none: no published number defines them. `height_confidence` is an ordinal
    ranking of measurement quality, not a calibrated probability, and inventing plausible-looking
    defaults is the failure mode CLAUDE.md warns about most sharply — nothing would crash, the
    map would just carry a quietly wrong quality claim. Set them explicitly and they are
    serialised into the run manifest, where the choice is visible and reproducible.
    """

    storey_height_m: float = 3.0
    """Metres per storey for the `num_floors` fallback. Varies regionally and is a real error
    source; 3.0 m is the default CLAUDE.md states."""

    overture_height_confidence: float | None = None
    """`height_confidence` for buildings resolved from Overture's `height` attribute — except
    where Overture itself supplies a per-building confidence, which is preferred over this."""

    overture_num_floors_confidence: float | None = None
    """`height_confidence` for buildings resolved from `num_floors x storey_height_m`."""

    areal_tiers: list[ArealTierConfig] = Field(default_factory=_default_areal_tiers)
    """Tiers 2-4, in cascade order."""


class Settings(BaseModel):
    """Resolved configuration for a single lczkit run.

    Construct via `Settings.load()`, not directly — that is what resolves `DATA_DIR` from
    the environment and creates the run's output directory.
    """

    data_dir: Path
    run_id: str = Field(default_factory=_default_run_id)
    overture: OvertureConfig = Field(default_factory=OvertureConfig)
    cleaning: CleaningConfig = Field(default_factory=CleaningConfig)
    heights: HeightConfig = Field(default_factory=HeightConfig)

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
