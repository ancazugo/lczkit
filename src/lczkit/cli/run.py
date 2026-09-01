"""`lczkit run` — a bbox or a city in, a run directory and a map site out.

**Two city locators, and the distinction is load-bearing.** `--city` names one of GUPPD's 5 558
urban regions and covers it; `--city ... --so2sat-window` takes the densest 30 km window of that
city's So2Sat labels instead, which is the extent the published agreement figures were measured
over. They are different ground, so a run says which one it used in its manifest rather than
leaving a reader to infer it from a bbox.

The default is the general one. Reproducing a recorded figure is the specialist case and asks for
itself; getting a map of a city is what the command is for.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from lczkit.cities import BY_KEY, WINDOW_KM, shrink, so2sat_window
from lczkit.cities import city as lookup_city
from lczkit.cli._options import (
    BASEMAP_HELP,
    LAND_COVER_SOURCE_HELP,
    apply_basemaps,
    apply_config_file,
    apply_land_cover_source,
    parse_basemaps,
    parse_bbox,
    parse_land_cover_source,
)
from lczkit.cli._render import (
    EXIT_MISSING_TOOL,
    LARGE_EXTENT_KM2,
    StageProgress,
    console,
    fail,
    out,
    report_site,
)
from lczkit.cli._render import stage_table as render_stages
from lczkit.config import Settings
from lczkit.output.extent import ExtentRecord
from lczkit.pipeline import PipelineResult, run_pipeline
from lczkit.places import load_places, normalise, place
from lczkit.presets import DEFAULT_PRESET, PRESETS, apply_preset
from lczkit.protocols import BBox


def run(
    bbox: Annotated[
        str | None,
        typer.Option(
            "--bbox",
            metavar="W,S,E,N",
            help="Extent in lon/lat degrees. Needs nothing on disk.",
        ),
    ] = None,
    city: Annotated[
        str | None,
        typer.Option(
            "--city",
            metavar="NAME",
            help="Any of GUPPD's 5 558 urban regions. `lczkit cities` searches them.",
        ),
    ] = None,
    country: Annotated[
        str | None,
        typer.Option(
            "--country",
            metavar="ISO",
            help="Disambiguate --city, e.g. GBR. 149 GUPPD names are shared.",
        ),
    ] = None,
    so2sat_window: Annotated[
        bool,
        typer.Option(
            "--so2sat-window",
            help="Use the city's densest 30 km So2Sat window instead of its GUPPD extent.",
        ),
    ] = False,
    extent_km: Annotated[
        float | None,
        typer.Option(
            "--extent-km",
            help="Shrink the extent to a concentric square of this side. Use it to try a run.",
        ),
    ] = None,
    run_id: Annotated[
        str | None,
        typer.Option("--run-id", help="Name the output directory. Defaults to a UTC timestamp."),
    ] = None,
    preset: Annotated[
        str,
        typer.Option("--preset", help=f"Run configuration. One of: {', '.join(sorted(PRESETS))}."),
    ] = DEFAULT_PRESET,
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            exists=True,
            dir_okay=False,
            help="JSON overriding any settings section. A run manifest works here.",
        ),
    ] = None,
    site: Annotated[
        bool, typer.Option("--site/--no-site", help="Build the map site after the run.")
    ] = True,
    buildings: Annotated[
        bool,
        typer.Option(
            "--buildings/--no-buildings",
            help="Tile building footprints for the 3D layer. Roughly triples the site.",
        ),
    ] = False,
    basemap: Annotated[
        list[str] | None,
        typer.Option("--basemap", metavar="KEY", help=BASEMAP_HELP),
    ] = None,
    land_cover_source: Annotated[
        str | None,
        typer.Option("--land-cover-source", metavar="BACKEND", help=LAND_COVER_SOURCE_HELP),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Resolve and print the configuration, then stop."),
    ] = False,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Suppress per-stage progress.")
    ] = False,
) -> None:
    """Run the whole pipeline over one extent.

    Give it either an explicit window or a city:

        lczkit run --bbox 13.29,52.45,13.52,52.59
        lczkit run --city nairobi
        lczkit run --city cambridge --country GBR --extent-km 3

    Writes `$DATA_DIR/output/lczkit/<run_id>/`, plus the caches the Overture and height-product
    sources own under `input/`. Nothing existing under `input/` is modified.
    """
    # Everything that can be judged from the command line alone comes first, because
    # `_load_settings` needs `DATA_DIR` and a caller who has not set one yet is exactly the caller
    # most likely to mistype an argument. Loading first answered "--bbox 1,2,3" with "DATA_DIR is
    # not set", which blames the environment for a typo and buries the fixable half. `site build`
    # has always split it this way; this is `run` catching up.
    if (bbox is None) == (city is None):
        fail("give exactly one of --bbox or --city (see --help for the forms)")
    if city is None and (country is not None or so2sat_window):
        fail("--country and --so2sat-window only apply to --city")
    if extent_km is not None and extent_km <= 0:
        fail(f"--extent-km must be positive, got {extent_km}")
    basemap_keys = parse_basemaps(basemap)
    backend = parse_land_cover_source(land_cover_source)

    parsed: BBox
    extent: ExtentRecord
    located: tuple[BBox, ExtentRecord] | None = None
    if bbox is not None:
        parsed = parse_bbox(bbox)
        located = (parsed, ExtentRecord(kind="bbox", bbox=parsed))

    settings = _load_settings(run_id=run_id, create=not dry_run)
    try:
        apply_preset(settings, preset)
    except KeyError as error:
        fail(str(error.args[0]))
    if config is not None:
        apply_config_file(settings, config)
    settings.viz.include_buildings = buildings
    apply_basemaps(settings.viz, basemap_keys)
    # After `--config`, so an explicit flag beats a file that also named a backend. `None` leaves
    # the file's answer alone, which is what makes the two composable rather than exclusive.
    apply_land_cover_source(settings, backend)

    # The city locators stay here on purpose: they read `guppd_bounds.csv` and the So2Sat archive
    # through `settings.source_dir`, so unlike a bbox they genuinely cannot answer without one.
    if located is not None:
        parsed, extent = located
    elif so2sat_window:
        parsed, extent = _so2sat_extent(city, country, settings)
    else:
        parsed, extent = _guppd_extent(city, country, settings)

    if extent_km is not None:
        parsed = shrink(parsed, extent_km)
        extent = extent.shrunk(parsed, extent_km)

    label = extent.label
    if dry_run:
        _print_plan(settings, extent, label=label, preset=preset, site=site)
        return

    console.print(f"run [bold]{settings.run_id}[/bold] over {label} {_format_bbox(parsed)}")
    _report_extent(extent)
    result = run_pipeline(
        settings,
        parsed,
        build_site_after=site,
        observer=StageProgress(quiet=quiet),
        extent=extent,
    )

    if not quiet:
        out.print(render_stages(result))
    console.print(f"  wrote [bold]{result.run_dir}[/bold]")
    _report_gis(result)
    _report_site(result)


def _report_site(result: PipelineResult) -> None:
    """Report the map site, or say why there is none and how to get one later.

    **Reported after the run directory, never instead of it.** A missing tippecanoe used to
    propagate out of `run_pipeline` and become an exit code before the line naming the run
    directory was printed, so a run whose only problem was an absent tool looked like a run that
    produced nothing — when in fact every file but the site was already written. The exit code is
    still non-zero, because a site was asked for and not produced.
    """
    if result.site is not None:
        report_site(result.site)
        return
    if result.site_skipped is None:
        return
    console.print(f"  [yellow]no map site[/yellow] {result.site_skipped}")
    console.print(f"  build it later: [bold]lczkit site build {result.run_dir}[/bold]")
    raise typer.Exit(EXIT_MISSING_TOOL)


def _report_gis(result: PipelineResult) -> None:
    """Name the file a GIS opens, and the CRS it is in.

    Printed because `units.parquet` is the file a reader reaches for and GeoParquet's driver is
    optional in GDAL — a QGIS built without it reports a correct file as having no CRS, which
    looks like a defect in the run rather than a gap in the reader.
    """
    outputs = result.outputs
    crs = outputs.manifest.crs or "an unnamed projected CRS"
    if outputs.units_gpkg is None:
        console.print(f"  units in [bold]{crs}[/bold] (GeoParquet only)")
        return
    console.print(f"  open in a GIS: [bold]{outputs.units_gpkg}[/bold] ({crs})", soft_wrap=True)


def _load_settings(*, run_id: str | None, create: bool) -> Settings:
    """`Settings.load`, with its two documented failures reported as messages rather than traces."""
    try:
        return Settings.load(run_id=run_id, create_run_dir=create)
    except ValidationError as error:
        fail(f"DATA_DIR is set but unusable.\n{error}")
    except ValueError as error:
        fail(str(error))


def _format_bbox(bbox: BBox) -> str:
    return "(" + ", ".join(f"{value:.4f}" for value in bbox) + ")"


def _print_plan(
    settings: Settings, extent: ExtentRecord, *, label: str, preset: str, site: bool
) -> None:
    """What `--dry-run` shows: the resolved configuration, and nothing created to show it."""
    console.print(f"[bold]dry run[/bold] — nothing written, {settings.run_dir} not created")
    out.print_json(
        json.dumps(
            {
                "run_id": settings.run_id,
                "locator": label,
                "bbox": list(extent.bbox),
                "extent": extent.model_dump(mode="json"),
                "preset": preset,
                "build_site": site,
                "run_dir": str(settings.run_dir),
                "config": settings.model_dump(mode="json"),
            }
        )
    )


def _guppd_extent(
    query: str | None, country: str | None, settings: Settings
) -> tuple[BBox, ExtentRecord]:
    """Resolve a city name against GUPPD, reporting its two failures as messages.

    Both are the caller's to fix and neither is a bug: the table may not be on disk, and a name may
    belong to more than one region. `place` raises `LookupError` for both, already carrying the
    text that says what to do, so there is nothing to add here beyond not printing a traceback.
    """
    assert query is not None
    try:
        found = place(load_places(settings), query, country=country)
    except (FileNotFoundError, ValueError, LookupError) as error:
        fail(str(error))
    record = ExtentRecord(
        kind="guppd",
        bbox=found.bbox,
        name=found.name,
        query=query,
        iso=found.iso,
        country=found.country,
        smod_id=found.smod_id,
    )
    return found.bbox, record


def _so2sat_extent(
    query: str | None, country: str | None, settings: Settings
) -> tuple[BBox, ExtentRecord]:
    """Resolve a registry key to its densest 30 km So2Sat window.

    Kept separate from the GUPPD path rather than folded into it as a fallback: this is the extent
    the recorded agreement figures were measured over, and reaching it by accident — or failing to
    reach it and silently getting the region instead — is exactly what would make a run look
    comparable with a published number when it is not.

    `--country` is **checked here rather than ignored**. The registry is keyed by name and three of
    its keys name a city that exists in more than one country, so ignoring the flag would answer
    `--city london --country CAN` with *London, UK's* window — the caller's own disambiguation
    silently overruled, and nothing downstream of a bbox able to say so.
    """
    assert query is not None
    key = query.strip().casefold().replace(" ", "_").replace("-", "_")
    if key not in BY_KEY:
        fail(
            f"--so2sat-window needs one of the {len(BY_KEY)} cities with labelled windows, and "
            f"{query!r} is not one: {', '.join(sorted(BY_KEY))}. Drop the flag to run "
            f"{query!r}'s GUPPD extent instead."
        )
    target = lookup_city(key)
    if country is not None and normalise(country) not in {
        normalise(target.iso),
        normalise(target.iso)[:2],
    }:
        fail(
            f"the labelled window for {query!r} is in {target.iso}, not {country!r}. "
            "Drop --so2sat-window to run the region you named."
        )
    try:
        window = so2sat_window(target, settings)
    except FileNotFoundError as error:
        fail(str(error))
    return window, ExtentRecord(
        kind="so2sat_window",
        bbox=window,
        name=target.so2sat.replace("_", " "),
        query=query,
        iso=target.iso,
        city_key=key,
        side_km=WINDOW_KM,
    )


def _report_extent(extent: ExtentRecord) -> None:
    """Say how much ground the run covers, and mention the trim flag when that is a lot.

    Printed before the first stage because it is the one number that predicts the wall time, and
    the point at which a caller can still change their mind cheaply.
    """
    console.print(f"  extent: [bold]{extent.area_km2:,.0f} km2[/bold]")
    if extent.area_km2 > LARGE_EXTENT_KM2 and extent.extent_km is None:
        console.print(
            "  [yellow]note[/yellow] this is a long run; --extent-km N trims it concentrically"
        )
