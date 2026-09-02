"""`lczkit morphometrics` — regenerate the morphometrics raster from a finished run.

Takes a *run* directory, like `lczkit site build` and `lczkit export`: that is the level a user
archives and the level everything else in the CLI already speaks. Kept as its own nested command
rather than folded into `export` — that command is single-purpose GIS packaging, and rasterizing
morphometrics is an unrelated concern that happens to also read a run directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from lczkit.cli._render import console, fail
from lczkit.morphometrics.raster import refresh_raster

app = typer.Typer(no_args_is_help=True, help="Work with a run's morphometrics output.")


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
) -> None:
    """(Re)write `<run_dir>/morphometrics.tif` from `<run_dir>/morphometrics.parquet`.

    The same function `lczkit run --morphometrics-resolution` calls at run time, so a raster
    produced here is identical to one produced during the run — this just lets a resolution be
    tried, or retried, without recomputing the vector attributes.
    """
    if resolution <= 0:
        fail(f"--resolution must be positive, got {resolution}")
    wanted = None
    if columns is not None:
        wanted = [name.strip() for value in columns for name in value.split(",") if name.strip()]

    try:
        report = refresh_raster(run_dir, resolution, columns=wanted)
    except FileNotFoundError as error:
        fail(str(error))

    console.print(
        f"  wrote [bold]{run_dir / 'morphometrics.tif'}[/bold] "
        f"({report.n_rows}x{report.n_cols}, {len(report.band_names)} bands, "
        f"{report.resolution_m:g} m)",
        soft_wrap=True,
    )
