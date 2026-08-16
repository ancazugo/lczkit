"""The whole chain, from a bbox to a run directory and optionally a map site.

**Why this is in the package and not in a script.** Until Phase 15 the only end-to-end pipeline in
the repository was `run_and_publish` in `scripts/berlin_metropolitan_run.py`: not importable (no
`__init__.py`, reached by `sys.path` insertion), not covered by `mypy src` in CI, and dependent on
constants and a raster fetcher living in two *other* scripts. Three partial re-implementations of
the same chain existed alongside it. A command line cannot import any of that, and neither can a
user. The stages are unchanged — this is the same sequence, in a place things can reach.

**What is deliberately absent.** Validation. `write_run` takes a `validation=` report and the
manifest has a slot for it, but the chain has never populated them: agreement is measured by the
sweep scripts, against references that are not always on disk. Wiring it in here would make every
run depend on `input/So2Sat-LCZ42/` and `input/Demuzere_2022_complete/`. It stays where it is.

`StageObserver` is how a caller watches a long run without this module choosing a rendering. The
CLI passes a `rich` one; `scripts/berlin_metropolitan_run.Timer` already satisfies the protocol
structurally and keeps printing exactly what it printed before.
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
from lczkit.cleaning.pipeline import clean_vectors
from lczkit.config import Settings, UnitsConfig
from lczkit.heights.cascade import cascade_height_sources, fill_heights
from lczkit.heights.completeness import height_metrics
from lczkit.heights.diagnostic import source_availability
from lczkit.heights.inherit import inherit_heights
from lczkit.heights.tiers import build_cascade
from lczkit.landcover.local import LocalRasterSource
from lczkit.output import RunOutputs, write_run
from lczkit.protocols import BBox, SpatialUnitStrategy
from lczkit.sources.height_products import resolve_areal_tiers
from lczkit.sources.overture import OvertureSource
from lczkit.sources.worldcover import clip_worldcover
from lczkit.ucp.parameters import compute_parameters
from lczkit.ucp.tag_diagnostic import tag_availability
from lczkit.units.enclosures import EnclosureUnits, assemble_barriers
from lczkit.units.grid import GridUnits
from lczkit.units.patches import PatchUnits, filter_street_barriers
from lczkit.viz import SiteReport, build_site

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
) -> PipelineResult:
    """Clean, fill heights, classify, write a run directory and optionally build its map site.

    `settings` must already carry a runnable configuration — `CleaningConfig` and `HeightConfig`
    both have fields that default to `None` and raise at call time. `lczkit.presets.apply_preset`
    is what fills them.

    Every path comes from `settings`: the run directory, the tile cache, and the `input/`
    subdirectories the Overture and height-product fetchers own. Nothing existing under `input/`
    is modified or removed.
    """
    watch = observer if observer is not None else _NullObserver()
    stages: dict[str, float] = {}

    @contextmanager
    def timed(name: str) -> Iterator[None]:
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
        # `filename` unset and silently runs tier 1 alone — which is what every run before
        # Phase 11 did, and why the default cascade needs a step that actually fetches.
        heights, placed = resolve_areal_tiers(settings, bbox)
        tiers = build_cascade(heights, settings.source_dir)
        buildings_area, height_fill = fill_heights(cleaned.buildings_area, tiers)
        buildings_topo = inherit_heights(cleaned.buildings_topo, buildings_area)
        availability = source_availability(cleaned.buildings_area)
        tags = tag_availability(cleaned.buildings_area, cleaned.land_use)

    with timed("units"):
        # Was a literal `GridUnits()` until Phase 17, which is why Phase 11's `unit_strategy`
        # ruling had no effect for six phases: the chain not only defaulted to the grid, it could
        # not reach anything else, because it never assembled barriers either.
        strategy = build_strategy(settings.units, buildings=buildings_area)
        barriers = None
        if settings.units.strategy != "grid":
            # `clean_vectors` does not carry rail — it is a barrier layer, not something the
            # cleaning pipeline has a rule for — so it comes straight off the source, exactly as
            # `scripts/unit_scale_experiment.build_arms` has fetched it since Phase 2.
            streets = (
                filter_street_barriers(cleaned.streets)
                if settings.units.drop_pedestrian_barriers
                else cleaned.streets
            )
            barriers = assemble_barriers(
                streets, cleaned.waterbodies, rail=source.rail(bbox).to_crs(cleaned.crs)
            )
        units = strategy.generate(bbox, barriers)

    with timed("land_cover"):
        # `clip_worldcover` resolves the tiles the bbox actually spans and mosaics them. A single
        # hardcoded tile is correct for one city and a 0x0 window — `RasterioIOError` — for the
        # next one, or worse, a quarter of the map silently missing.
        worldcover = clip_worldcover(bbox, settings.run_dir / "worldcover.tif")
        fractions = LocalRasterSource(
            settings.land_cover.dataset(settings.ucp.land_cover_dataset), worldcover
        ).fractions(units)

    with timed("provenance"):
        # The column set comes from the configured cascade, not from which tiers happened to fire,
        # so a run with no areal product still reports its tier fractions as zeros rather than
        # omitting the columns and changing the output schema.
        provenance = height_metrics(buildings_area, units, cascade_height_sources(tiers))

    with timed("parameters"):
        parameters = compute_parameters(
            units,
            buildings_area,
            buildings_topo,
            cleaned.streets,
            cleaned.land_use,
            fractions,
            config=settings.ucp,
            land_cover_config=settings.land_cover,
        )

    with timed("classify"):
        classifier = PrototypeClassifier(config=settings.classification)
        classification = classifier.classify(parameters)

    with timed("write_run"):
        outputs = write_run(
            settings,
            units,
            parameters,
            classification,
            classifier,
            extras=fractions.join(provenance),
            cleaning=cleaned.report,
            units_report=getattr(strategy, "report", None),
            height_fill=height_fill,
            height_source_availability=availability,
            tag_availability=tags,
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
    if build_site_after:
        with timed("build_site"):
            site = build_site(outputs.run_dir, config=settings.viz)

    return PipelineResult(outputs=outputs, site=site, stages=stages, height_products=dict(placed))
