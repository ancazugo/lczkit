"""`lczkit morphometrics` — regenerate the morphometrics raster from a finished run.

Takes a *run* directory, like `lczkit site build` and `lczkit export`: that is the level a user
archives and the level everything else in the CLI already speaks. Kept as its own nested command
rather than folded into `export` — that command is single-purpose GIS packaging, and rasterizing
morphometrics is an unrelated concern that happens to also read a run directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, get_args

import typer

from lczkit.cli._render import console, fail
from lczkit.config import RasterFormat
from lczkit.morphometrics.raster import RASTER_TILE_DIR, raster_filename, refresh_raster

app = typer.Typer(no_args_is_help=True, help="Work with a run's morphometrics output.")

_FORMATS = get_args(RasterFormat)


@app.command("raster")
def raster(
    run_dir: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            help="A run directory, i.e. output/lczkit/<run_id>/.",
        ),
    ],
    resolution: Annotated[
        float,
        typer.Option("--resolution", help="Pixel size in metres."),
    ],
    columns: Annotated[
        list[str] | None,
        typer.Option(
            "--columns",
            metavar="NAME",
            help="Attribute(s) to rasterize. Repeatable; comma-"
            "separated also works. Defaults to every attribute in morphometrics.parquet.",
        ),
    ] = None,
    format: Annotated[
        str,
        typer.Option(
            "--format",
            metavar="FORMAT",
            help=f"Output format ({', '.join(_FORMATS)}). 'gtiff' is a plain GeoTIFF, 'cog' is "
            "the same file reorganised for efficient partial HTTP reads, 'zarr' is a "
            "cloud-native chunked store.",
        ),
    ] = "gtiff",
    tile_deg: Annotated[
        float | None,
        typer.Option(
            "--tile-deg",
            metavar="DEGREES",
            help="Split the output into a geographic tile grid this many degrees on a side "
            "(geotessera's naming convention: grid_<lon>_<lat>) instead of one file. Unset "
            "writes a single file, the original behaviour.",
        ),
    ] = None,
) -> None:
    """(Re)write a run's morphometrics raster output from `<run_dir>/morphometrics.parquet`.

    The same function `lczkit run --morphometrics-resolution` calls at run time, so a raster
    produced here is identical to one produced during the run — this just lets a resolution,
    format, or tiling be tried, or retried, without recomputing the vector attributes.
    """
    if resolution <= 0:
        fail(f"--resolution must be positive, got {resolution}")
    if format not in _FORMATS:
        fail(f"unknown format {format!r}; choose from {', '.join(_FORMATS)}")
    if tile_deg is not None and tile_deg <= 0:
        fail(f"--tile-deg must be positive, got {tile_deg}")
    wanted = None
    if columns is not None:
        wanted = [name.strip() for value in columns for name in value.split(",") if name.strip()]

    try:
        report = refresh_raster(
            run_dir,
            resolution,
            columns=wanted,
            format=format,  # type: ignore[arg-type]  # validated against _FORMATS above
            tile_deg=tile_deg,
        )
    except FileNotFoundError as error:
        fail(str(error))

    if report.tiles:
        console.print(
            f"  wrote [bold]{len(report.tiles)}[/bold] tiles under "
            f"[bold]{run_dir / RASTER_TILE_DIR}[/bold] "
            f"({report.n_rows}x{report.n_cols} full grid, {len(report.band_names)} bands, "
            f"{report.resolution_m:g} m, {report.tile_deg:g}° tiles)",
            soft_wrap=True,
        )
    else:
        console.print(
            f"  wrote [bold]{run_dir / raster_filename(format)}[/bold] "  # type: ignore[arg-type]
            f"({report.n_rows}x{report.n_cols}, {len(report.band_names)} bands, "
            f"{report.resolution_m:g} m)",
            soft_wrap=True,
        )
