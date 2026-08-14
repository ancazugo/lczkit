"""A complete Berlin run — cleaning to classification to a map site — over the whole 891 km².

    uv run --active python scripts/berlin_metropolitan_run.py \
        [--extent KM] [--no-site] [--buildings]

**Why this exists.** Nothing in the repository called `write_run` outside the tests, so no real run
directory had ever been produced: every experiment stopped at a comparison table. Phase 7's site is
a pure transform of run outputs, which means it needs one. And Phase 8 is what makes that worth
doing at this extent — before it, `clean_vectors` over Berlin did not finish.

The chain is the same one `phase8_threshold_labels.label()` runs, plus the two steps that script
had no use for: `write_run`, which persists the units, the viz table, the manifest and the context
geometry the site draws; and `build_site`, which turns them into a directory that opens in a
browser.

**Where it writes.** `output/lczkit/<run_id>/` and nothing else, except the per-tile simplification
cache under `output/lczkit/_cache/tiles/` and Overture's own cache under
`input/Overture_Maps/<release>/<bbox>/`, which `OvertureSource` owns. Nothing existing under
`input/` is modified or removed.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from lczkit.classify import PrototypeClassifier
from lczkit.cleaning.pipeline import clean_vectors
from lczkit.config import Settings
from lczkit.heights.cascade import cascade_height_sources, fill_heights
from lczkit.heights.completeness import height_metrics
from lczkit.heights.diagnostic import source_availability
from lczkit.heights.inherit import inherit_heights
from lczkit.heights.tiers import build_cascade
from lczkit.landcover.local import LocalRasterSource
from lczkit.output import write_run
from lczkit.protocols import BBox
from lczkit.sources.height_products import resolve_areal_tiers
from lczkit.sources.overture import OvertureSource
from lczkit.ucp.parameters import compute_parameters
from lczkit.units.grid import GridUnits
from lczkit.viz import build_site

sys.path.insert(0, str(Path(__file__).resolve().parent))

from berlin_metropolitan import BERLIN, CLEANING, RELEASE, _shrink  # noqa: E402 - sibling script
from multi_city_validation import clip_worldcover  # noqa: E402 - sibling script
from unit_scale_experiment import HEIGHTS, LAND_COVER, UCP  # noqa: E402 - sibling script


class Timer:
    """Wall time per stage, printed as it goes so a long run is legible while it runs."""

    def __init__(self) -> None:
        self.stages: dict[str, float] = {}

    def stage(self, name: str) -> Timer:
        self._name = name
        return self

    def __enter__(self) -> Timer:
        self._started = time.perf_counter()
        return self

    def __exit__(self, *_: object) -> None:
        elapsed = time.perf_counter() - self._started
        self.stages[self._name] = elapsed
        print(f"  {self._name:26s} {elapsed:8.1f}s", flush=True)


def configure(settings: Settings, *, buildings: bool = False) -> Settings:
    """The configuration every published run shares, applied in place.

    One function rather than a copy per driver: the sites are meant to be read side by side, so a
    difference between two cities must come from the cities and not from a setting that drifted
    between two scripts.
    """
    settings.overture.release = RELEASE
    settings.cleaning = CLEANING.model_copy()
    settings.heights = HEIGHTS.model_copy()
    settings.land_cover = LAND_COVER.model_copy()
    settings.ucp = UCP.model_copy()
    settings.viz.include_buildings = buildings
    return settings


def run_and_publish(settings: Settings, bbox: BBox, *, build_site_after: bool = True) -> Path:
    """Clean, classify, write a run directory and turn it into a map site.

    Returns the run directory.

    Split out of `main` so `publish_sites.py` can run this chain over another city without
    copying it. A second copy of these stages would be a second thing to keep in step, and the
    comparison the site exists to support only holds if every city went through one pipeline.
    """
    print(f"run {settings.run_id} over {bbox}", flush=True)
    timer = Timer()

    with timer.stage("clean_vectors"):
        cleaned = clean_vectors(
            OvertureSource(settings),
            bbox,
            settings.cleaning,
            cache_dir=settings.tile_cache_dir,
        )

    with timer.stage("heights"):
        # Places the products the configured cascade needs, and returns the config with each
        # tier's file resolved. Without this step `build_cascade` finds every areal tier's
        # `filename` unset and silently runs tier 1 alone — which is what every run before
        # Phase 11 did, and why the default cascade needs a step that actually fetches.
        heights, placed = resolve_areal_tiers(settings, bbox)
        print(f"  height products: {placed}", flush=True)
        tiers = build_cascade(heights, settings.source_dir)
        buildings_area, height_fill = fill_heights(cleaned.buildings_area, tiers)
        buildings_topo = inherit_heights(cleaned.buildings_topo, buildings_area)
        availability = source_availability(cleaned.buildings_area)

    with timer.stage("units"):
        units = GridUnits().generate(bbox)

    with timer.stage("land_cover"):
        # `clip_worldcover` resolves the tiles the bbox actually spans and mosaics them. The
        # Berlin-only `WORLDCOVER_URL` this used to pass is a single hardcoded tile: correct for
        # Berlin, and a 0x0 window — `RasterioIOError` — for any city outside it.
        worldcover = clip_worldcover(bbox, settings.run_dir / "worldcover.tif")
        fractions = LocalRasterSource(
            settings.land_cover.dataset(settings.ucp.land_cover_dataset), worldcover
        ).fractions(units)

    with timer.stage("provenance"):
        # The column set comes from the configured cascade, not from which tiers happened to fire,
        # so a run with no areal product still reports its tier fractions as zeros rather than
        # omitting the columns and changing the output schema.
        provenance = height_metrics(buildings_area, units, cascade_height_sources(tiers))

    with timer.stage("parameters"):
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

    with timer.stage("classify"):
        classifier = PrototypeClassifier(config=settings.classification)
        classification = classifier.classify(parameters)

    with timer.stage("write_run"):
        outputs = write_run(
            settings,
            units,
            parameters,
            classification,
            classifier,
            extras=fractions.join(provenance),
            cleaning=cleaned.report,
            height_fill=height_fill,
            height_source_availability=availability,
            # The site draws its basemap and its extrusions from these, so that an archived run
            # directory rebuilds its own map with no access to `input/`.
            layers={
                "streets": cleaned.streets,
                "water": cleaned.waterbodies,
                "land_use": cleaned.land_use,
                "buildings": buildings_area,
            },
        )
    print(f"  wrote {outputs.run_dir}", flush=True)

    if build_site_after:
        with timer.stage("build_site"):
            report = build_site(outputs.run_dir, config=settings.viz)
        for tileset in report.tilesets:
            print(
                f"    {tileset.name:14s} {tileset.size_bytes / 1e6:8.2f} MB  "
                f"z{tileset.min_zoom}-{tileset.max_zoom}  "
                f"{tileset.n_features} features  {tileset.seconds:.1f}s",
                flush=True,
            )
        total = sum(tileset.size_bytes for tileset in report.tilesets)
        print(f"    {'total':14s} {total / 1e6:8.2f} MB", flush=True)
        for name, reason in report.skipped.items():
            print(f"    skipped {name}: {reason}", flush=True)
        print(f"  serve it: python {report.site_dir / 'serve.py'}", flush=True)

    print(f"\ntotal {sum(timer.stages.values()) / 60:.1f} min", flush=True)
    return outputs.run_dir


def main() -> None:
    extent_km = None
    if "--extent" in sys.argv:
        extent_km = float(sys.argv[sys.argv.index("--extent") + 1])
    bbox: BBox = BERLIN if extent_km is None else _shrink(BERLIN, extent_km)

    settings = configure(Settings.load(), buildings="--buildings" in sys.argv)
    run_and_publish(settings, bbox, build_site_after="--no-site" not in sys.argv)


if __name__ == "__main__":
    main()
