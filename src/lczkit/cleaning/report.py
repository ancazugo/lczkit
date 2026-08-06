"""Structured record of feature counts in and out of every cleaning operation.

Every cleaning function returns the layer it produced alongside one or more
`CleaningStep` fragments; the pipeline orchestrator in `pipeline.py` is the only place these
fragments are assembled into a `CleaningReport`. This keeps every cleaning function a pure,
independently testable transform with no shared mutable state.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Stage = Literal["buildings", "streets", "land_use", "topology"]


class CleaningStep(BaseModel):
    """One recorded operation: how many features went in, how many came out."""

    stage: Stage
    operation: str
    n_in: int
    n_out: int
    detail: dict[str, Any] = Field(default_factory=dict)


class CleaningReport(BaseModel):
    """The full sequence of cleaning steps applied by one `clean_vectors()` run."""

    steps: list[CleaningStep] = Field(default_factory=list)
