"""The whole chain, from a bbox to a run directory and optionally a map site.

`run_pipeline` is the only place the stages are wired together. The command line calls it rather
than restating any of it, so there is one definition of what a run does.

**What is deliberately absent.** Validation. `write_run` takes a `validation=` report and the
manifest has a slot for it, but the chain never populates them: agreement is measured separately,
against reference datasets that are not always on disk. Wiring it in here would make every run
depend on those datasets being present. Call `lczkit.validation` yourself when you have them.

`StageObserver` is how a caller watches a long run without this module choosing a rendering. The
command line passes one backed by `rich`; any object with the same two methods will do.
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
from lczkit.landcover.local import LocalRasterSource
from lczkit.output import RunOutputs, write_run
from lczkit.output.extent import ExtentRecord
from lczkit.protocols import BBox, SpatialUnitStrategy
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

STAGES = (
    "clean_vectors",
    "heights",
    "units",
    "land_cover",
    "provenance",
    "parameters",
    "classify",
    "write_run",
    "build_site",
)
"""Stage names, in order, so a caller can size a progress display before the run starts."""


class StageObserver(Protocol):
    """Something that watches each stage begin and end.

    A `typing.Protocol` rather than a base class, following the same decision the five data-source
    protocols were built under: the point is the seam, and a caller that already has a timer should
    not have to inherit anything to use it.
    """

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

    `buildings` is only read by `patch`, and only when `patch_merge_on_morphology` is on. It is
    passed at construction rather than to `generate` because the protocol's signature is
    `(bbox, barriers)`, and widening that for one strategy would put a building layer into an
    interface the other two have no use for.
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


@dataclass(frozen=True)
class PipelineResult:
    """What a run produced, and how long each stage took."""

    outputs: RunOutputs

    site: SiteReport | None
    """`None` when the run was asked not to build one, or when tippecanoe is absent."""

    site_skipped: str | None = None
    """Why no site was built, where one was asked for. `None` when one was built or not wanted.

    The site is the **last** stage and everything else is already on disk by the time it runs, so
    a missing tippecanoe must not cost a caller the run. It used to: the error propagated out of
    `run_pipeline`, the command line turned it into an exit code, and the line naming the run
    directory was never printed — a ten-minute city reported as a failure with no mention that its
    output existed. `lczkit site build <run_dir>` completes it later.
    """

    stages: dict[str, float] = field(default_factory=dict)
    """Wall seconds per stage, in the order they ran."""

    height_products: dict[str, str | None] = field(default_factory=dict)
    """Which areal height product file each enabled tier resolved to, by tier name.

    `None` where the product has no coverage for this extent — Open Buildings stops at Europe —
    which is a different state from a tier that was disabled, and stays separable here.
    """

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

    `settings` must already carry a runnable configuration — `CleaningConfig` and `HeightConfig`
    both have fields that default to `None` and raise at call time. `lczkit.presets.apply_preset`
    is what fills them.

    Every path comes from `settings`: the run directory, the tile cache, and the `input/`
    subdirectories the Overture and height-product fetchers own. Nothing existing under `input/`
    is modified or removed.

    `extent` records **how** `bbox` was chosen — a named place, a So2Sat window, or four numbers —
    and goes into the manifest. It defaults to the bbox alone, which is all a library caller who
    computed their own window can honestly claim.
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

    source = OvertureSource(settings)
    with timed("clean_vectors"):
        cleaned = clean_vectors(
            source,
            bbox,
            settings.cleaning,
            cache_dir=settings.tile_cache_dir,
        )

    with timed("heights"):
        # Places the products the configured cascade needs, and returns the config with each
        # tier's file resolved. Without this step `build_cascade` finds every areal tier's
        # `filename` unset and silently runs tier 1 alone, so the default cascade needs a step
        # that actually fetches.
        heights, placed = resolve_areal_tiers(settings, bbox)
        tiers = build_cascade(heights, settings.source_dir)
        buildings_area, height_fill = fill_heights(cleaned.buildings_area, tiers)
        buildings_topo = inherit_heights(cleaned.buildings_topo, buildings_area)
        availability = source_availability(cleaned.buildings_area)
        tags = tag_availability(cleaned.buildings_area, cleaned.land_use)

    with timed("units"):
        # The strategy is config, so the chain has to assemble barriers for the two that need
        # them rather than defaulting to the grid and being unable to reach anything else.
        strategy = build_strategy(settings.units, buildings=buildings_area)
        barriers = None
        measure_on_enclosures = settings.ucp.measure_on == "enclosures"
        if settings.units.strategy != "grid" or measure_on_enclosures:
            # `clean_vectors` does not carry rail — it is a barrier layer, not something the
            # cleaning pipeline has a rule for — so it comes straight off the source.
            streets = (
                filter_street_barriers(cleaned.streets)
                if settings.units.drop_pedestrian_barriers
                else cleaned.streets
            )
            barriers = assemble_barriers(
                streets, cleaned.waterbodies, rail=source.rail(bbox).to_crs(cleaned.crs)
            )
        units = strategy.generate(bbox, barriers)

        # A street canyon has to be measured against streets, and a grid cell is not bounded by
        # any. Off by default — see `UcpConfig.measure_on` — and where the target units *are* the
        # enclosures there is nothing to transfer, so the extra partition is skipped.
        measurement_units = units
        if measure_on_enclosures and settings.units.strategy != "enclosure":
            measurement_units = EnclosureUnits().generate(bbox, barriers)

    with timed("land_cover"):
        # `clip_worldcover` resolves the tiles the bbox actually spans and mosaics them. A single
        # hardcoded tile is correct for one city and a 0x0 window — `RasterioIOError` — for the
        # next one, or worse, a quarter of the map silently missing.
        worldcover = clip_worldcover(bbox, settings.run_dir / "worldcover.tif")
        raster = LocalRasterSource(
            settings.land_cover.dataset(settings.ucp.land_cover_dataset), worldcover
        )
        fractions = raster.fractions(units)
        # The surface fractions have to describe the units the parameters are measured on, or the
        # building share and the impervious share it is subtracted from would come from different
        # ground. A second zonal pass, and only when the two unit sets actually differ.
        measurement_fractions = (
            fractions if measurement_units is units else raster.fractions(measurement_units)
        )

    with timed("provenance"):
        # The column set comes from the configured cascade, not from which tiers happened to fire,
        # so a run with no areal product still reports its tier fractions as zeros rather than
        # omitting the columns and changing the output schema.
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
        # Off by default, so this is a no-op that still produces a report — a run has to be able to
        # say the filter did not fire as distinct from never having been configured.
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
            # The site draws its basemap and its extrusions from these, so that an archived run
            # directory rebuilds its own map with no access to `input/`.
            layers={
                "streets": cleaned.streets,
                "water": cleaned.waterbodies,
                "land_use": cleaned.land_use,
                "buildings": buildings_area,
            },
        )

    site: SiteReport | None = None
    skipped: str | None = None
    if build_site_after:
        with timed("build_site"):
            try:
                site = build_site(outputs.run_dir, config=settings.viz)
            except TippecanoeMissingError as error:
                # Caught rather than raised, and only this one: it is a statement about the
                # machine rather than about the run, and everything the run produced is already
                # written. Any other failure here is a defect and stays loud.
                skipped = str(error)

    return PipelineResult(
        outputs=outputs,
        site=site,
        site_skipped=skipped,
        stages=stages,
        height_products=dict(placed),
    )
