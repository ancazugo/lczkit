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
from pyproj import CRS

from lczkit.classify.classifier import PrototypeClassifier
from lczkit.classify.labels import DEMUZERE_2022, legend
from lczkit.classify.prototypes import UNUSED_PROPERTIES
from lczkit.classify.weights import BERNARD2024, UNAPPLIED_BERNARD_WEIGHTS
from lczkit.cleaning.report import CleaningReport
from lczkit.config import Settings
from lczkit.heights.cascade import HeightFillReport
from lczkit.heights.diagnostic import SourceAvailability
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
"""Packages whose version changes could change a run's numbers. CLAUDE.md names momepy, neatnet
and geopandas specifically; the rest are here because every one of them performs a geometric or
zonal computation whose result this package reports as a measurement."""


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

    extent: ExtentRecord | None = None
    """The ground this run covered, and the locator that chose it.

    **Derived, like `crs`, and for the same reason absent until it was asked for.** The extent is an
    argument to `run_pipeline`, so it appears in no `Settings` field and therefore in none of the
    `config` block below — leaving a run directory unable to say which city it was, which is not a
    recoverable question from a bbox once `--city` reaches 5 558 named regions.

    `None` on runs written before this field existed. `lczkit export` backfills those from the
    units' own bounds, under `kind="recovered"` so a reconstruction is never read as a record.
    """

    cleaning: CleaningReport | None = None
    units: PatchReport | None = None
    """What the patch merge did, where `units.strategy` is `"patch"`.

    The *choice* of strategy already reaches the manifest through `config`; this is the outcome,
    and the two are different things. A run recording `patch_min_area_m2=50000` says what was asked
    for, and `seed_area_quantiles` beside `patch_area_quantiles` says what was got — which is the
    only way to tell a city where the merge worked from one where isolates or the area ceiling
    stopped it."""

    height_fill: HeightFillReport | None = None
    height_source_availability: SourceAvailability | None = None
    tag_availability: TagAvailability | None = None
    """Overture attribute availability by upstream dataset — the Phase 18 counterpart of
    `height_source_availability`, and the same finding on a second attribute: building tags are
    48.6% of building area is tagged across Europe and North America against 13.6% elsewhere.

    Read every `sem_*` column against `tagged_area_fraction`. Without it a semantic fraction of 0.0
    cannot be told from an untagged city, which is the same mistake `height_tier_fractions` exists
    to prevent for the cascade."""
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

    crs: str | None = None
    """The CRS every geometry in this run is written in, as an authority code — `"EPSG:32618"`.

    **It is derived, not configured.** CLAUDE.md's locked decision is that internal computation
    happens in whatever projected CRS `estimate_utm_crs()` returns for the extent, so the answer
    depends on the bbox and appears nowhere in `config`. Until this field existed a run directory
    could not say what CRS it was in without a GeoParquet reader — which is precisely the tool a
    reader who cannot open GeoParquet does not have.

    `None` only where the CRS carries no authority code; `crs_wkt` is the fallback and is always
    present. `units_viz.parquet` has no geometry at all and so has no CRS."""

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
    height_source_availability: SourceAvailability | None = None,
    tag_availability: TagAvailability | None = None,
    validation: AgreementReport | None = None,
    validation_ground_truth: AgreementReport | None = None,
    reference_ceiling: AgreementReport | None = None,
    crs: CRS | None = None,
    outputs: list[str] | None = None,
) -> RunManifest:
    """Assemble the manifest for one run.

    Every argument beyond the first two is optional because the stages are independently usable -
    a run that classified a parameter table it was handed has no cleaning report to record, and
    saying so is better than fabricating one.
    """
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
            for parameter in (*PARAMETERS, *semantic_specs(settings.ucp.semantic_groups))
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
        height_source_availability=height_source_availability,
        tag_availability=tag_availability,
        validation=validation,
        validation_ground_truth=validation_ground_truth,
        reference_ceiling=reference_ceiling,
        crs=None if epsg is None else f"EPSG:{epsg}",
        crs_wkt=None if crs is None else crs.to_wkt(),
        outputs=outputs or [],
    )
