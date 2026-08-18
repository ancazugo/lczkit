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

from lczkit.config import Settings
from lczkit.pipeline import run_pipeline
from lczkit.presets import apply_preset
from lczkit.protocols import BBox

sys.path.insert(0, str(Path(__file__).resolve().parent))

from berlin_metropolitan import BERLIN, _shrink  # noqa: E402 - sibling script


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

    The values themselves moved into `lczkit.presets` in Phase 15, so `lczkit run` and this driver
    configure a run identically by construction rather than by two lists agreeing. A test asserts
    the two paths still produce the same `Settings`.
    """
    apply_preset(settings, "published")
    settings.viz.include_buildings = buildings
    return settings


def run_and_publish(settings: Settings, bbox: BBox, *, build_site_after: bool = True) -> Path:
    """Clean, classify, write a run directory and turn it into a map site.

    Returns the run directory.

    Split out of `main` so `publish_sites.py` can run this chain over another city without
    copying it. A second copy of these stages would be a second thing to keep in step, and the
    comparison the site exists to support only holds if every city went through one pipeline.

    Phase 15 moved the stages themselves into `lczkit.pipeline.run_pipeline`, where a command line
    and a test can reach them. This function is now the printing around that call, kept because the
    Phase 8 timings in the write-ups are quoted from its output and `publish_sites.py` calls it by
    name. `Timer` satisfies the `StageObserver` protocol structurally, so the per-stage lines are
    the same lines.
    """
    print(f"run {settings.run_id} over {bbox}", flush=True)
    timer = Timer()

    result = run_pipeline(settings, bbox, build_site_after=build_site_after, observer=timer)
    print(f"  height products: {result.height_products}", flush=True)
    print(f"  wrote {result.run_dir}", flush=True)

    report = result.site
    if report is not None:
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
    elif result.site_skipped is not None:
        # The site is the last stage and everything else is already written, so a missing
        # tippecanoe is reported rather than raised. Saying so here keeps this driver's output as
        # honest as the command line's — a run with no site line and no explanation reads as one
        # that was asked not to build one.
        print(f"  no map site: {result.site_skipped}", flush=True)
        print(f"  build it later: lczkit site build {result.run_dir}", flush=True)

    print(f"\ntotal {result.seconds / 60:.1f} min", flush=True)
    return result.run_dir


def main() -> None:
    extent_km = None
    if "--extent" in sys.argv:
        extent_km = float(sys.argv[sys.argv.index("--extent") + 1])
    bbox: BBox = BERLIN if extent_km is None else _shrink(BERLIN, extent_km)

    settings = configure(Settings.load(), buildings="--buildings" in sys.argv)
    run_and_publish(settings, bbox, build_site_after="--no-site" not in sys.argv)


if __name__ == "__main__":
    main()
