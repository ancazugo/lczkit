"""The whole chain, from a bbox to a run directory and optionally a map site.

`run_pipeline` is the only place the stages are wired together; the command line calls it. It does
not validate: agreement needs reference data that is not always on disk, so call
`lczkit.validation` yourself where you have it. `StageObserver` lets a caller watch the stages
without this module choosing a rendering.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import geopandas as gpd

from lczkit.classify import PrototypeClassifier
from lczkit.classify.smoothing import modal_filter
from lczkit.cleaning.pipeline import clean_vectors
from lczkit.config import Settings, UnitsConfig
from lczkit.heights.cascade import cascade_height_sources, fill_heights
from lczkit.heights.completeness import height_metrics
from lczkit.heights.diagnostic import source_availability
from lczkit.heights.inherit import inherit_heights
from lczkit.heights.tiers import build_cascade
from lczkit.landcover.earthengine import EarthEngineSource, check_asset
from lczkit.landcover.local import LocalRasterSource
from lczkit.morphometrics.compute import compute_morphometrics
from lczkit.morphometrics.raster import refresh_raster
from lczkit.output import RunOutputs, write_run
from lczkit.output.extent import ExtentRecord
from lczkit.protocols import BBox, RasterSource, SpatialUnitStrategy
from lczkit.sources.height_products import resolve_areal_tiers
from lczkit.sources.overture import OvertureSource
from lczkit.sources.worldcover import clip_worldcover
from lczkit.ucp.measure import transfer_parameters
from lczkit.ucp.parameters import compute_parameters
from lczkit.ucp.tag_diagnostic import tag_availability
from lczkit.units.enclosures import EnclosureUnits, assemble_barriers
from lczkit.units.grid import GridUnits
from lczkit.units.patches import PatchUnits, filter_street_barriers
from lczkit.viz import SiteReport, TippecanoeMissingError, build_site


class StageObserver(Protocol):
    """Something that watches each stage begin and end."""

    def stage(self, name: str) -> AbstractContextManager[None]:
        """A context manager wrapping one stage's work."""
        ...


@contextmanager
def _untimed(_name: str) -> Iterator[None]:
    yield


class _NullObserver:
    """The default: run the stages, record nothing, print nothing."""

    def stage(self, name: str) -> AbstractContextManager[None]:
        """A context manager that does nothing, satisfying the observer seam without output."""
        return _untimed(name)


def build_strategy(
    config: UnitsConfig, *, buildings: gpd.GeoDataFrame | None = None
) -> SpatialUnitStrategy:
    """The configured `SpatialUnitStrategy`.

    `buildings` is read only by `patch` with `patch_merge_on_morphology` on; it goes to the
    constructor because the protocol's `generate(bbox, barriers)` has no use for it elsewhere.
    """
    if config.strategy == "grid":
        return GridUnits(cell_size_m=config.cell_size_m)
    if config.strategy == "enclosure":
        return EnclosureUnits()
    return PatchUnits(
        min_area_m2=config.patch_min_area_m2,
        max_area_m2=config.patch_max_area_m2,
        buildings=buildings if config.patch_merge_on_morphology else None,
    )


def land_cover_source(settings: Settings, bbox: BBox) -> RasterSource:
    """The configured land-cover backend (`LandCoverConfig.source`).

    The local backend mosaics the ESA WorldCover tiles the extent spans into the run directory; a
    clip keyed to one run is not source data, so it never goes under `input/`. The Earth Engine
    backend caches its own reductions under `input/GEE/`.
    """
    dataset = settings.land_cover.dataset(settings.ucp.land_cover_dataset)
    if settings.land_cover.source == "gee":
        return EarthEngineSource.from_settings(settings, dataset.name)
    return LocalRasterSource(
        dataset,
        clip_worldcover(bbox, settings.run_dir / "worldcover.tif"),
        max_raster_cells=settings.land_cover.max_raster_cells,
    )


@dataclass(frozen=True)
class PipelineResult:
    """What a run produced, and how long each stage took."""

    outputs: RunOutputs

    site: SiteReport | None
    """`None` when the run was asked not to build one, or when tippecanoe is absent."""

    site_skipped: str | None = None
    """Why no site was built, where one was asked for. The site is the last stage, so a missing
    tippecanoe costs only the site; `lczkit site build <run_dir>` completes it later."""

    stages: dict[str, float] = field(default_factory=dict)
    """Wall seconds per stage, in the order they ran."""

    height_products: dict[str, str | None] = field(default_factory=dict)
    """The raster each enabled areal tier resolved to, by tier name; `None` where the product has
    no coverage for this extent (a disabled tier is absent instead)."""

    @property
    def run_dir(self) -> Path:
        """Where everything was written."""
        return self.outputs.run_dir

    @property
    def seconds(self) -> float:
        """Total wall time across the stages that ran."""
        return sum(self.stages.values())


def run_pipeline(
    settings: Settings,
    bbox: BBox,
    *,
    build_site_after: bool = True,
    observer: StageObserver | None = None,
    extent: ExtentRecord | None = None,
) -> PipelineResult:
    """Clean, fill heights, classify, write a run directory and optionally build its map site.

    `settings` must carry a runnable configuration; `lczkit.presets.apply_preset` fills the
    thresholds that default to `None`. Nothing existing under `input/` is modified. `extent`
    records how `bbox` was chosen (a named place, a So2Sat window, or the bbox alone) for the
    manifest.
    """
    watch = observer if observer is not None else _NullObserver()
    covered = extent if extent is not None else ExtentRecord(kind="bbox", bbox=bbox)
    stages: dict[str, float] = {}

    @contextmanager
    def timed(name: str) -> Iterator[None]:
        """Run one stage under the observer, recording its wall time into `stages`."""
        started = time.perf_counter()
        with watch.stage(name):
            yield
        stages[name] = time.perf_counter() - started

    # Checked before the long cleaning stage rather than when land cover is reached.
    if settings.land_cover.source == "gee":
        check_asset(
            settings.land_cover.dataset(settings.ucp.land_cover_dataset),
            settings.land_cover.gee_project,
        )

    source = OvertureSource(settings)
    with timed("clean_vectors"):
        cleaned = clean_vectors(
            source,
            bbox,
            settings.cleaning,
            cache_dir=settings.tile_cache_dir,
        )

    with timed("morphometrics"):
        # 2D and independent of the rest of the chain; off unless `morphometrics.enabled`.
        morphometrics_table = None
        morphometrics_report = None
        if settings.morphometrics.enabled:
            morphometrics_table, morphometrics_report = compute_morphometrics(
                bbox,
                cleaned.buildings_area,
                cleaned.streets,
                cleaned.waterbodies,
                config=settings.morphometrics,
            )

    with timed("heights"):
        # Fetch each enabled tier's raster and fill in its `filename` for `build_cascade`.
        heights, placed = resolve_areal_tiers(settings, bbox)
        tiers = build_cascade(heights, settings.source_dir)
        buildings_area, height_fill = fill_heights(cleaned.buildings_area, tiers)
        buildings_topo = inherit_heights(cleaned.buildings_topo, buildings_area)
        availability = source_availability(cleaned.buildings_area)
        tags = tag_availability(cleaned.buildings_area, cleaned.land_use)

    with timed("units"):
        strategy = build_strategy(settings.units, buildings=buildings_area)
        barriers = None
        measure_on_enclosures = settings.ucp.measure_on == "enclosures"
        if settings.units.strategy != "grid" or measure_on_enclosures:
            # Rail is a barrier only, so it comes straight off the source rather than cleaning.
            streets = (
                filter_street_barriers(cleaned.streets)
                if settings.units.drop_pedestrian_barriers
                else cleaned.streets
            )
            barriers = assemble_barriers(
                streets, cleaned.waterbodies, rail=source.rail(bbox).to_crs(cleaned.crs)
            )
        units = strategy.generate(bbox, barriers)

        # See `UcpConfig.measure_on`; nothing to transfer when the units are enclosures already.
        measurement_units = units
        if measure_on_enclosures and settings.units.strategy != "enclosure":
            measurement_units = EnclosureUnits().generate(bbox, barriers)

    with timed("land_cover"):
        raster = land_cover_source(settings, bbox)
        fractions = raster.fractions(units)
        # The surface fractions must describe the units the parameters are measured on.
        measurement_fractions = (
            fractions if measurement_units is units else raster.fractions(measurement_units)
        )

    with timed("provenance"):
        # Columns follow the configured cascade, so the schema does not depend on what fired.
        provenance = height_metrics(buildings_area, units, cascade_height_sources(tiers))

    with timed("parameters"):
        parameters = compute_parameters(
            measurement_units,
            buildings_area,
            buildings_topo,
            cleaned.streets,
            cleaned.land_use,
            measurement_fractions,
            config=settings.ucp,
            land_cover_config=settings.land_cover,
        )
        if measurement_units is not units:
            parameters = transfer_parameters(parameters, measurement_units, units)

    with timed("classify"):
        classifier = PrototypeClassifier(config=settings.classification)
        classification = classifier.classify(parameters)
        # Off by default; still reports, so "did not fire" differs from "not configured".
        classification, smoothing = modal_filter(
            units,
            classification,
            enabled=settings.classification.modal_filter,
            min_like_neighbours=settings.classification.modal_filter_min_like_neighbours,
        )

    with timed("write_run"):
        outputs = write_run(
            settings,
            units,
            parameters,
            classification,
            classifier,
            extras=fractions.join(provenance),
            cleaning=cleaned.report,
            extent=covered,
            units_report=getattr(strategy, "report", None),
            height_fill=height_fill,
            height_source_availability=availability,
            tag_availability=tags,
            smoothing=smoothing,
            # Persisted so an archived run rebuilds its own site without `input/`.
            layers={
                "streets": cleaned.streets,
                "water": cleaned.waterbodies,
                "land_use": cleaned.land_use,
                "buildings": buildings_area,
            },
            morphometrics=morphometrics_table,
            morphometrics_report=morphometrics_report,
        )

    if morphometrics_table is not None and settings.morphometrics.raster_resolution_m is not None:
        with timed("morphometrics_raster"):
            # The same call `lczkit morphometrics raster` makes later. It patches the manifest
            # file; mirror that onto the in-memory manifest.
            raster_report = refresh_raster(
                outputs.run_dir,
                settings.morphometrics.raster_resolution_m,
                max_cells=settings.morphometrics.max_raster_cells,
                format=settings.morphometrics.raster_format,
                tile_deg=settings.morphometrics.raster_tile_deg,
                max_bytes=settings.morphometrics.max_raster_bytes,
            )
            outputs.manifest.morphometrics_raster = raster_report.as_manifest()

    site: SiteReport | None = None
    skipped: str | None = None
    if build_site_after:
        with timed("build_site"):
            try:
                site = build_site(outputs.run_dir, config=settings.viz)
            except TippecanoeMissingError as error:
                # A missing tool, not a defect in the run; everything else is already written.
                skipped = str(error)

    return PipelineResult(
        outputs=outputs,
        site=site,
        site_skipped=skipped,
        stages=stages,
        height_products=dict(placed),
    )
