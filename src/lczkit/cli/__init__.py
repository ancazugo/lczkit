"""The `lczkit` command line.

Everything here is a wrapper. `run` calls `lczkit.pipeline.run_pipeline`, `site build` calls
`lczkit.viz.build_site`, `site serve` calls `lczkit.viz.serve`, `export` calls
`lczkit.output.export_gis`. No command computes anything, and none of them is the only way to
reach what it wraps: the library API is unchanged and the experiment drivers in `scripts/` still
call it directly.
"""

from __future__ import annotations

from typing import Annotated

import typer

from lczkit import __version__
from lczkit.cli import site
from lczkit.cli.cities import cities
from lczkit.cli.export import export
from lczkit.cli.run import run

app = typer.Typer(
    name="lczkit",
    no_args_is_help=True,
    add_completion=False,
    help=(
        "Map cities into Local Climate Zones from open vector and raster data.\n\n"
        "Set DATA_DIR in .env first — every path derives from it."
    ),
)

app.command("run")(run)
app.command("cities")(cities)
app.command("export")(export)
app.add_typer(site.app, name="site")


def _version(value: bool) -> None:
    if value:
        typer.echo(f"lczkit {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version, is_eager=True, help="Show the version."),
    ] = False,
) -> None:
    """Map cities into Local Climate Zones from open vector and raster data.

    Every run records the Overture release, the height cascade, the classifier weights and the
    resolved package versions in its manifest, so a result can be traced back to what produced
    it. `lczkit cities <name>` finds an extent and `lczkit run --city <name>` maps it;
    `--dry-run` resolves the config without acting.
    """


def main() -> None:
    """Console-script entry point, named in `[project.scripts]`."""
    app()


__all__ = ["app", "main"]
