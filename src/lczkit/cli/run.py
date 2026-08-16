"""`lczkit run` — a bbox or a city in, a run directory and a map site out."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from lczkit.cities import BY_KEY, shrink, so2sat_window
from lczkit.cities import city as lookup_city
from lczkit.cli._options import apply_config_file, parse_bbox
from lczkit.cli._render import EXIT_MISSING_TOOL, StageProgress, console, fail, out, report_site
from lczkit.cli._render import stage_table as render_stages
from lczkit.config import Settings
from lczkit.pipeline import PipelineResult, run_pipeline
from lczkit.presets import DEFAULT_PRESET, PRESETS, apply_preset
from lczkit.protocols import BBox
from lczkit.viz import TippecanoeMissingError
from lczkit.viz.basemaps import PROVIDERS


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
            metavar="KEY",
            help="A So2Sat city, using the same 30 km window every validation sweep used.",
        ),
    ] = None,
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
        str | None,
        typer.Option(
            "--basemap",
            metavar="KEY",
            help=(
                f"Add a selectable online base map ({', '.join(sorted(PROVIDERS))}). "
                "Off by default: the site otherwise reaches no network."
            ),
        ),
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
        lczkit run --city berlin --extent-km 4

    Writes `$DATA_DIR/output/lczkit/<run_id>/`, plus the caches the Overture and height-product
    sources own under `input/`. Nothing existing under `input/` is modified.
    """
    if (bbox is None) == (city is None):
        fail("give exactly one of --bbox or --city (see --help for the forms)")

    parsed: BBox
    settings = _load_settings(run_id=run_id, create=not dry_run)
    try:
        apply_preset(settings, preset)
    except KeyError as error:
        fail(str(error.args[0]))
    if config is not None:
        apply_config_file(settings, config)
    settings.viz.include_buildings = buildings
    if basemap is not None:
        if basemap not in PROVIDERS:
            fail(f"unknown basemap {basemap!r}; choose from {', '.join(sorted(PROVIDERS))}")
        settings.viz.online_basemap = basemap
        chosen = PROVIDERS[basemap]
        console.print(f"base map: [bold]{chosen.label}[/bold] — {chosen.licence}")
        if chosen.terms:
            console.print(f"[yellow]note[/yellow] {chosen.terms}")

    if bbox is not None:
        parsed = parse_bbox(bbox)
        label = "bbox"
    else:
        assert city is not None
        if city not in BY_KEY:
            fail(f"unknown city {city!r}; choose from {', '.join(sorted(BY_KEY))}")
        try:
            parsed = so2sat_window(lookup_city(city), settings)
        except FileNotFoundError as error:
            fail(str(error))
        label = city

    if extent_km is not None:
        if extent_km <= 0:
            fail(f"--extent-km must be positive, got {extent_km}")
        parsed = shrink(parsed, extent_km)

    if dry_run:
        _print_plan(settings, parsed, label=label, preset=preset, site=site)
        return

    console.print(f"run [bold]{settings.run_id}[/bold] over {label} {_format_bbox(parsed)}")
    try:
        result = run_pipeline(
            settings,
            parsed,
            build_site_after=site,
            observer=StageProgress(quiet=quiet),
        )
    except TippecanoeMissingError as error:
        fail(str(error), EXIT_MISSING_TOOL)

    if not quiet:
        out.print(render_stages(result))
    console.print(f"  wrote [bold]{result.run_dir}[/bold]")
    _report_gis(result)
    if result.site is not None:
        report_site(result.site)


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


def _print_plan(settings: Settings, bbox: BBox, *, label: str, preset: str, site: bool) -> None:
    """What `--dry-run` shows: the resolved configuration, and nothing created to show it."""
    console.print(f"[bold]dry run[/bold] — nothing written, {settings.run_dir} not created")
    out.print_json(
        json.dumps(
            {
                "run_id": settings.run_id,
                "locator": label,
                "bbox": list(bbox),
                "preset": preset,
                "build_site": site,
                "run_dir": str(settings.run_dir),
                "config": settings.model_dump(mode="json"),
            }
        )
    )
