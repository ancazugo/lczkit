"""The run manifest: everything needed to read a run's output and to reproduce it.

CLAUDE.md treats reproducibility as a feature of the package rather than an afterthought, and
names what has to be in here: the full serialised config, the pinned Overture release, the Earth
Engine collection IDs and date ranges, the resolved package versions, a run timestamp, and the
cleaning report. Earlier phases added to that list - the height source-availability diagnostic,
the parameter registry with its units and references, the two deferred Stewart & Oke properties,
and the Overture heavy/light industry limitation, each required to be *data* rather than prose.

The result is a single JSON file that answers, without the code in hand: what was measured, in
what units, from which sources, under which thresholds, with which parameters missing, and how
well it agreed with an independent map.
"""

from __future__ import annotations

import importlib.metadata
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from lczkit.classify.classifier import PrototypeClassifier
from lczkit.classify.labels import DEMUZERE_2022, legend
from lczkit.classify.prototypes import UNUSED_PROPERTIES
from lczkit.classify.weights import BERNARD2024, UNAPPLIED_BERNARD_WEIGHTS
from lczkit.cleaning.report import CleaningReport
from lczkit.config import Settings
from lczkit.heights.cascade import HeightFillReport
from lczkit.heights.diagnostic import SourceAvailability
from lczkit.output.breaks import VariableBreaks
from lczkit.ucp.registry import LIMITATIONS, NOT_COMPUTED, PARAMETERS
from lczkit.validation.agreement import AgreementReport

TRACKED_PACKAGES: tuple[str, ...] = (
    "lczkit",
    "geopandas",
    "shapely",
    "pandas",
    "numpy",
    "pyarrow",
    "pyogrio",
    "momepy",
    "libpysal",
    "neatnet",
    "geoplanar",
    "duckdb",
    "exactextract",
    "rasterio",
    "pydantic",
    "earthengine-api",
)
"""Packages whose version changes could change a run's numbers. CLAUDE.md names momepy, neatnet
and geopandas specifically; the rest are here because every one of them performs a geometric or
zonal computation whose result this package reports as a measurement."""


def package_versions() -> dict[str, str]:
    """Resolved version of every tracked package. An absent one is recorded as such rather than
    omitted, because "not installed" is itself a fact about the run - `earthengine-api` missing
    means the Earth Engine path could not have been used."""
    versions: dict[str, str] = {}
    for name in TRACKED_PACKAGES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not installed"
    return versions


class RunManifest(BaseModel):
    """One run, described completely enough to be read and repeated."""

    run_id: str
    created_utc: str
    """ISO 8601, UTC, second resolution."""

    config: dict[str, Any]
    """`Settings` serialised verbatim, per CLAUDE.md."""

    versions: dict[str, str]

    overture_release: str | None
    """The pinned release the vector layers came from, never "latest"."""

    earth_engine_assets: dict[str, dict[str, Any]] = Field(default_factory=dict)
    """Per land-cover dataset, the collection ID, asset type, band, date range and scale."""

    parameters: list[dict[str, str]] = Field(default_factory=list)
    """The Phase 5 registry: every emitted column with its unit, description and source."""

    not_computed: dict[str, str] = Field(default_factory=dict)
    """Stewart & Oke properties Phase 5 does not compute, and why."""

    limitations: dict[str, str] = Field(default_factory=dict)
    """Known limitations of specific parameters, in the parameters' own terms."""

    unused_lcz_properties: dict[str, str] = Field(default_factory=dict)
    """Properties present in the published prototype table but absent from the distance metric.
    Five of the ten, which is a material caveat on every label a run emits."""

    unapplied_weights: list[dict[str, Any]] = Field(default_factory=list)
    """Weights the active preset publishes for properties this package cannot compute. Under
    `bernard2024` this is 4.5 of a published 21.5 total, so a reader comparing against a
    GeoClimate run knows the metric is not the same one."""

    classification: dict[str, Any] = Field(default_factory=dict)
    """Active weights, normalisation, the full prototype table, every threshold, and which
    classes could not be assigned."""

    classification_summary: dict[str, Any] = Field(default_factory=dict)
    """What the classifier actually did to this city: the label distribution, how many units each
    route produced, and how many times the LCZ 10 rule fired.

    The firing count is here because a rule that never fires is indistinguishable, from the output
    alone, from one that was never configured — and CLAUDE.md's whole concern about LCZ 10 is that
    it can go silently unemitted. A run over an industrial port reporting zero firings is a
    finding about the rule, and it should not take a separate investigation to notice it.
    """

    legend: dict[str, dict[str, str | int]] = Field(default_factory=dict)
    legend_citation: str = DEMUZERE_2022

    breaks: list[VariableBreaks] = Field(default_factory=list)
    """Precomputed classification breaks. Phase 7 reads these and never recomputes a quantile."""

    cleaning: CleaningReport | None = None
    height_fill: HeightFillReport | None = None
    height_source_availability: SourceAvailability | None = None
    validation: AgreementReport | None = None
    """Agreement against the Demuzere global map. A comparator, not ground truth - read it against
    `reference_ceiling`."""

    validation_ground_truth: AgreementReport | None = None
    """Agreement against hand-labelled LCZ polygons (So2Sat LCZ42 / DFC2017) where they exist.
    **This is the primary validation figure**; `validation` is secondary."""

    reference_ceiling: AgreementReport | None = None
    """Agreement between the Demuzere map and the labelled polygons, on the same units.

    The bound on what any run can score against `validation`, and the number that has to exist
    before a residual there is called a defect. Measured at 53.2% on the Berlin fixture, which is
    inside the 50-60% band lczkit was being compared against as though it were a target."""

    outputs: list[str] = Field(default_factory=list)
    """Files written into the run directory, by name."""


def build_manifest(
    settings: Settings,
    classifier: PrototypeClassifier,
    *,
    breaks: list[VariableBreaks] | None = None,
    classification_summary: dict[str, Any] | None = None,
    cleaning: CleaningReport | None = None,
    height_fill: HeightFillReport | None = None,
    height_source_availability: SourceAvailability | None = None,
    validation: AgreementReport | None = None,
    validation_ground_truth: AgreementReport | None = None,
    reference_ceiling: AgreementReport | None = None,
    outputs: list[str] | None = None,
) -> RunManifest:
    """Assemble the manifest for one run.

    Every argument beyond the first two is optional because the stages are independently usable -
    a run that classified a parameter table it was handed has no cleaning report to record, and
    saying so is better than fabricating one.
    """
    return RunManifest(
        run_id=settings.run_id,
        created_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        config=settings.model_dump(mode="json"),
        versions=package_versions(),
        overture_release=settings.overture.release,
        earth_engine_assets={
            dataset.name: dataset.gee.model_dump(mode="json")
            for dataset in settings.land_cover.datasets
        },
        parameters=[
            {
                "name": parameter.name,
                "label": parameter.label,
                "unit": parameter.unit,
                "description": parameter.description,
                "reference": parameter.reference,
            }
            for parameter in PARAMETERS
        ],
        not_computed=dict(NOT_COMPUTED),
        limitations=dict(LIMITATIONS),
        unused_lcz_properties=dict(UNUSED_PROPERTIES),
        unapplied_weights=[
            {"property": name, "weight": weight, "reason": reason}
            for name, weight, reason in UNAPPLIED_BERNARD_WEIGHTS
        ]
        if classifier.weights.name == BERNARD2024.name
        else [],
        classification=classifier.describe(),
        classification_summary=classification_summary or {},
        legend=legend(),
        breaks=breaks or [],
        cleaning=cleaning,
        height_fill=height_fill,
        height_source_availability=height_source_availability,
        validation=validation,
        validation_ground_truth=validation_ground_truth,
        reference_ceiling=reference_ceiling,
        outputs=outputs or [],
    )
