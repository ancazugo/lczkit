"""The run manifest: everything needed to read a run's output and to reproduce it.

One JSON file carrying the serialised config, the pinned Overture release, the Earth Engine assets,
package versions, the cleaning and height reports, the parameter registry with units and
references, and the known limitations, so a run can be read without the code in hand.
"""

from __future__ import annotations

import importlib.metadata
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from pyproj import CRS

from lczkit.classify.classifier import PrototypeClassifier
from lczkit.classify.labels import DEMUZERE_2022, legend
from lczkit.classify.prototypes import UNUSED_PROPERTIES
from lczkit.classify.smoothing import SmoothingReport
from lczkit.classify.weights import BERNARD2024, UNAPPLIED_BERNARD_WEIGHTS
from lczkit.cleaning.report import CleaningReport
from lczkit.config import Settings
from lczkit.heights.cascade import HeightFillReport
from lczkit.heights.diagnostic import SourceAvailability
from lczkit.heights.dispersion import DispersionReport
from lczkit.morphometrics.registry import PARAMETERS as MORPHOMETRICS_PARAMETERS
from lczkit.morphometrics.registry import contextual_specs
from lczkit.morphometrics.report import MorphometricsReport
from lczkit.output.breaks import VariableBreaks
from lczkit.output.extent import ExtentRecord
from lczkit.ucp.registry import LIMITATIONS, NOT_COMPUTED, PARAMETERS, semantic_specs
from lczkit.ucp.tag_diagnostic import TagAvailability
from lczkit.units.patches import PatchReport
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
"""Packages whose version changes could change a run's numbers. Every one of them performs a
geometric or zonal computation whose result this package reports as a measurement."""


def package_versions() -> dict[str, str]:
    """Resolved version of every tracked package.

    An absent one is recorded as such rather than omitted, because "not installed" is itself a
    fact about the run - `earthengine-api` missing means the Earth Engine path could not have
    been used.
    """
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
    """`Settings` serialised verbatim."""

    versions: dict[str, str]

    overture_release: str | None
    """The pinned release the vector layers came from, never "latest"."""

    earth_engine_assets: dict[str, dict[str, Any]] = Field(default_factory=dict)
    """Per land-cover dataset, the collection ID, asset type, band, date range and scale."""

    parameters: list[dict[str, str]] = Field(default_factory=list)
    """The parameter registry: every emitted column with its unit, description and source."""

    not_computed: dict[str, str] = Field(default_factory=dict)
    """Stewart & Oke properties this package does not compute, and why."""

    limitations: dict[str, str] = Field(default_factory=dict)
    """Known limitations of specific parameters, in the parameters' own terms."""

    unused_lcz_properties: dict[str, str] = Field(default_factory=dict)
    """Stewart & Oke properties absent from the distance metric (five of the ten)."""

    unapplied_weights: list[dict[str, Any]] = Field(default_factory=list)
    """Published weights for properties this package does not compute: 4.5 of Bernard et al.'s
    21.5 under `bernard2024_partial`."""

    classification: dict[str, Any] = Field(default_factory=dict)
    """Active weights, normalisation, the full prototype table, every threshold, and which
    classes could not be assigned."""

    classification_summary: dict[str, Any] = Field(default_factory=dict)
    """What the classifier did: the label distribution, units per route, and how often the LCZ 10
    rule fired, so a rule that never fires is visible from the output."""

    legend: dict[str, dict[str, str | int]] = Field(default_factory=dict)
    legend_citation: str = DEMUZERE_2022

    breaks: list[VariableBreaks] = Field(default_factory=list)
    """Precomputed classification breaks. The map site reads these and never recomputes a
    quantile."""

    extent: ExtentRecord | None = None
    """The ground this run covered and the locator that chose it. Not part of `config`, since the
    extent is an argument to `run_pipeline`. `lczkit export` backfills older runs from the units'
    bounds under `kind="recovered"`."""

    cleaning: CleaningReport | None = None
    units: PatchReport | None = None
    """What the patch merge produced, where `units.strategy` is `"patch"` (the request itself is
    in `config`)."""

    height_fill: HeightFillReport | None = None

    height_dispersion: DispersionReport | None = None
    """Within-unit height spread per tier. `Hr` is a geometric mean, so an areal product that
    compresses spread biases it upward. See `lczkit.heights.dispersion`."""

    height_source_availability: SourceAvailability | None = None
    tag_availability: TagAvailability | None = None
    """Overture attribute availability by upstream dataset. Read every `sem_*` column against it:
    a semantic fraction of 0.0 in an untagged city is not evidence of absence."""
    smoothing: SmoothingReport | None = None
    """What the modal filter did. Written even when the filter is off."""

    validation: AgreementReport | None = None
    """Agreement against the Demuzere global map: a comparator, not ground truth. Populated only by
    a caller who validates; `run_pipeline` does not."""

    validation_ground_truth: AgreementReport | None = None
    """Agreement against hand-labelled LCZ polygons (So2Sat LCZ42 / DFC2017) where they exist.
    **This is the primary validation figure**; `validation` is secondary."""

    reference_ceiling: AgreementReport | None = None
    """Agreement between the Demuzere map and the labelled polygons on the same units: context for
    `validation`, though not a strict bound (a run can beat it)."""

    morphometrics: MorphometricsReport | None = None
    """What the morphometrics stage produced, describing `morphometrics.parquet`. `None` where the
    stage did not run."""

    morphometrics_raster: dict[str, Any] | None = None
    """The morphometrics raster, if one was written: `RasterExportReport.as_manifest()`. A dict
    because `refresh_raster` patches it into an already-written manifest's JSON."""

    crs: str | None = None
    """The CRS every geometry in this run is written in, e.g. `"EPSG:32618"`. Derived from the
    extent, so it is in no config. `None` where there is no authority code; see `crs_wkt`."""

    crs_wkt: str | None = None
    """The same CRS as WKT2, so it is recoverable when no authority code applies."""

    outputs: list[str] = Field(default_factory=list)
    """Files written into the run directory, by name."""


def build_manifest(
    settings: Settings,
    classifier: PrototypeClassifier,
    *,
    breaks: list[VariableBreaks] | None = None,
    classification_summary: dict[str, Any] | None = None,
    cleaning: CleaningReport | None = None,
    extent: ExtentRecord | None = None,
    units: PatchReport | None = None,
    height_fill: HeightFillReport | None = None,
    height_dispersion: DispersionReport | None = None,
    height_source_availability: SourceAvailability | None = None,
    tag_availability: TagAvailability | None = None,
    smoothing: SmoothingReport | None = None,
    validation: AgreementReport | None = None,
    validation_ground_truth: AgreementReport | None = None,
    reference_ceiling: AgreementReport | None = None,
    morphometrics: MorphometricsReport | None = None,
    morphometrics_raster: dict[str, Any] | None = None,
    crs: CRS | None = None,
    outputs: list[str] | None = None,
) -> RunManifest:
    """Assemble the manifest for one run. Reports a stage did not produce are left `None`."""
    epsg = None if crs is None else crs.to_epsg()
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
            # The semantic specs come from the configured groups, not from a static
            # list, so a group added in config documents itself here rather than
            # appearing in the output with no unit and no reference.
            for parameter in (
                *PARAMETERS,
                *semantic_specs(settings.ucp.semantic_groups),
                # Only documented when the stage actually ran — otherwise a run that never
                # touched morphometrics would claim 107+ parameters it does not carry.
                *(MORPHOMETRICS_PARAMETERS if morphometrics is not None else ()),
                *(
                    contextual_specs(settings.morphometrics.contextual_quantiles)
                    if morphometrics is not None and morphometrics.contextual_enabled
                    else ()
                ),
            )
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
        extent=extent,
        cleaning=cleaning,
        units=units,
        height_fill=height_fill,
        height_dispersion=height_dispersion,
        height_source_availability=height_source_availability,
        tag_availability=tag_availability,
        smoothing=smoothing,
        validation=validation,
        validation_ground_truth=validation_ground_truth,
        reference_ceiling=reference_ceiling,
        morphometrics=morphometrics,
        morphometrics_raster=morphometrics_raster,
        crs=None if epsg is None else f"EPSG:{epsg}",
        crs_wkt=None if crs is None else crs.to_wkt(),
        outputs=outputs or [],
    )
