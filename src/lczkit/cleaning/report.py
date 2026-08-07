"""Structured record of what every cleaning operation consumed and produced.

Every cleaning function returns the layer it produced alongside one or more
`CleaningStep` fragments; the pipeline orchestrator in `pipeline.py` is the only place these
fragments are assembled into a `CleaningReport`. This keeps every cleaning function a pure,
independently testable transform with no shared mutable state.

**Steps record area, not only feature counts.** Counts alone are why a 23.5% loss of Berlin's
building footprint area survived from Phase 1 to Phase 6.5 without anyone seeing it: the two
operations responsible removed 1177 and 439 features respectively, and by count the second looks
like the smaller of the two. By area the first costs 0.12% and the second 22.5%. Building surface
fraction carries roughly 47% of the classification metric, so footprint area *is* the output here
and a report that does not state it cannot be audited.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Stage = Literal["buildings", "buildings_area", "buildings_topo", "streets", "land_use", "topology"]


class CleaningStep(BaseModel):
    """One recorded operation: how many features and how much area went in, and came out.

    `area_in_m2` / `area_out_m2` are polygon area in the layer's projected CRS. They are 0.0 for
    stages whose geometry has no area — the street and waterline steps — which is a true statement
    about a linework layer rather than a missing measurement.
    """

    stage: Stage
    operation: str
    n_in: int
    n_out: int
    area_in_m2: float = 0.0
    area_out_m2: float = 0.0
    detail: dict[str, Any] = Field(default_factory=dict)

    @property
    def area_retained(self) -> float | None:
        """Fraction of incoming area this step passed through, or `None` for an areal-free stage.

        Can exceed 1.0: trimming a self-overlapping footprint set removes double-counted area, so
        a step that *lowers* the measured total can be the one making it correct.
        """
        if self.area_in_m2 <= 0.0:
            return None
        return self.area_out_m2 / self.area_in_m2


class CleaningReport(BaseModel):
    """The full sequence of cleaning steps applied by one `clean_vectors()` run."""

    steps: list[CleaningStep] = Field(default_factory=list)

    def stage_steps(self, stage: Stage) -> list[CleaningStep]:
        """Every step recorded for `stage`, in the order it ran."""
        return [step for step in self.steps if step.stage == stage]

    def area_retention(self, stage: Stage) -> float | None:
        """Area out of `stage`'s last step over area into its first — end-to-end, not per-step.

        `None` when the stage recorded no step, or no area. This is the number Phase 1's acceptance
        criterion is stated against: `buildings_area` must retain >=99% of the raw footprint area.
        """
        steps = [step for step in self.stage_steps(stage) if step.area_in_m2 > 0.0]
        if not steps:
            return None
        return steps[-1].area_out_m2 / steps[0].area_in_m2
