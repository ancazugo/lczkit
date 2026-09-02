"""What a morphometrics run produced, for the run manifest."""

from __future__ import annotations

from dataclasses import dataclass

from lczkit.units.tessellation import TessellationReport


@dataclass(frozen=True)
class MorphometricsReport:
    """Counts and settings a reader of the manifest needs to interpret `morphometrics.parquet`."""

    tessellation: TessellationReport
    n_primary_attributes: int
    contextual_enabled: bool
    n_contextual_attributes: int
    """0 when `contextual_enabled` is `False` — the two fields are kept separate rather than one
    being inferred from the other, so a manifest reader never has to know the rule."""
