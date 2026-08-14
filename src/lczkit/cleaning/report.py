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

from pydantic import BaseModel, Field, computed_field

Stage = Literal[
    "ingestion",
    "buildings",
    "buildings_area",
    "buildings_topo",
    "streets",
    "land_use",
    "topology",
]
"""The pipeline stages a step can belong to.

`"ingestion"` covers repairs made to raw source data before any layer-specific cleaning starts —
at present only the clipping of features that have no finite representation in the study area's
UTM zone. It spans every layer at once, which is why it is not any one of the others.
"""


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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def area_retained(self) -> float | None:
        """Fraction of incoming area this step passed through, or `None` for an areal-free stage.

        Can exceed 1.0: trimming a self-overlapping footprint set removes double-counted area, so
        a step that *lowers* the measured total can be the one making it correct.
        """
        if self.area_in_m2 <= 0.0:
            return None
        return self.area_out_m2 / self.area_in_m2


class FootprintCoverage(BaseModel):
    """How much ground the raw footprints cover, against how much area they sum to.

    The two differ because **sources self-overlap**. Overture conflates footprints from OSM, Esri,
    Google Open Buildings and Microsoft ML geometry-first and winner-takes-all, and where that
    leaves a podium and its tower as two features, or a duplicate that survived conflation, their
    areas add up while the ground beneath them is counted once. Measured on the committed fixtures:
    Kowloon's raw footprints double-count **7.52%** of their summed area against Berlin's **0.61%**.

    This is why retention is measured against the **union**. Building surface fraction sums overlay
    pieces, so the union is what BSF is trying to measure, and a criterion stated against the sum is
    unmeetable wherever self-overlap exceeds the tolerance: `trim_overlaps` takes Kowloon to 98.40%
    of summed area without dropping a single feature, which reads as 1.6% attrition and is in fact
    1.6% of double-counting removed. The sum-based criterion and "trim overlaps but do not merge"
    were jointly unsatisfiable there.

    `raw_self_overlap_fraction` is reported in its own right: it is a real source-quality signal,
    and a city where it is high is a city where footprint provenance deserves a second look.
    """

    raw_summed_area_m2: float = 0.0
    raw_union_area_m2: float = 0.0
    area_summed_m2: float = 0.0
    """Summed area of `buildings_area`, the layer every area statistic reads."""

    area_union_m2: float = 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def raw_self_overlap_fraction(self) -> float | None:
        """Share of the raw summed area that is double-counted. 0.0 for a disjoint source."""
        if self.raw_summed_area_m2 <= 0.0:
            return None
        return 1.0 - self.raw_union_area_m2 / self.raw_summed_area_m2

    @computed_field  # type: ignore[prop-decorator]
    @property
    def residual_self_overlap_fraction(self) -> float | None:
        """The same measure on `buildings_area`, after cleaning.

        **Non-zero means the BSF numerator still double-counts**, because building surface fraction
        sums overlay pieces. `trim_overlaps` resolves pairwise overlaps and does not claim to
        resolve stacks, so this is expected to be small but not always zero, and it is reported
        rather than assumed away.
        """
        if self.area_summed_m2 <= 0.0:
            return None
        return 1.0 - self.area_union_m2 / self.area_summed_m2

    @computed_field  # type: ignore[prop-decorator]
    @property
    def union_retention(self) -> float | None:
        """`buildings_area`'s summed area over the raw **union** — Phase 1's acceptance criterion.

        Above 1.0 means the layer holds more area than the ground it covers, i.e. residual
        double-counting; below 0.99 means ground was lost. The criterion is one-sided on the losing
        side, and the excess is reported through `residual_self_overlap_fraction` rather than being
        folded into a single number that cannot distinguish the two failures.
        """
        if self.raw_union_area_m2 <= 0.0:
            return None
        return self.area_summed_m2 / self.raw_union_area_m2

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ground_retention(self) -> float | None:
        """Union out over union in: the share of covered ground the layer kept.

        Immune to double-counting on both sides, so it is the honest "did cleaning lose any
        building?" figure, where `union_retention` is the one the BSF numerator cares about.
        """
        if self.raw_union_area_m2 <= 0.0:
            return None
        return self.area_union_m2 / self.raw_union_area_m2


class CleaningReport(BaseModel):
    """The full sequence of cleaning steps applied by one `clean_vectors()` run."""

    steps: list[CleaningStep] = Field(default_factory=list)
    footprints: FootprintCoverage | None = None
    """Union-based footprint accounting. `None` where the run predates it or recorded no
    buildings."""

    def stage_steps(self, stage: Stage) -> list[CleaningStep]:
        """Every step recorded for `stage`, in the order it ran."""
        return [step for step in self.steps if step.stage == stage]

    def area_retention(self, stage: Stage) -> float | None:
        """Area out of `stage`'s last step over area into its first — end-to-end, not per-step.

        Measured against the **sum** of incoming area, which is the wrong denominator for the
        `buildings_area` acceptance criterion and is retained because it is the per-stage figure
        every other stage wants. For `buildings_area`, read `footprints.union_retention` instead —
        see `FootprintCoverage` for why the sum cannot serve.
        """
        steps = [step for step in self.stage_steps(stage) if step.area_in_m2 > 0.0]
        if not steps:
            return None
        return steps[-1].area_out_m2 / steps[0].area_in_m2
