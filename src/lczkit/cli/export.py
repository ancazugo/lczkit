"""`lczkit export` — make a finished run openable in a GIS.

Takes a *run* directory, like `lczkit site build`, for the same reason: that is the level a user
archives and the level everything else in the CLI already speaks.

A current run needs this only if it was written with `output.gis_format = "none"`. It exists for
older runs, which carry a correct GeoParquet and no GeoPackage — and for which re-running a
ten-minute city to change how it is packaged would be the wrong trade.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from lczkit.cli._render import console, fail
from lczkit.output import export_gis


def export(
    run_dir: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            help="A run directory, i.e. output/lczkit/<run_id>/.",
        ),
    ],
) -> None:
    """Write units.gpkg beside a run's units.parquet, and record its CRS and extent.

    The extent is **recovered from the units' own bounds**, not from the run's own record of what
    it was asked for — an archived run has no such record, which is why the field exists. It is
    tagged `kind="recovered"` so the two are never confused, and a run that already states its
    extent keeps what it states.
    """
    try:
        result = export_gis(run_dir)
    except FileNotFoundError as error:
        fail(str(error))

    crs = result.crs or "an unnamed projected CRS"
    console.print(f"  wrote [bold]{result.units_gpkg}[/bold]", soft_wrap=True)
    console.print(f"  {result.n_units:,} units in [bold]{crs}[/bold]")
    if not result.manifest_updated:
        return
    # Named rather than summarised as "the CRS". The two fields are backfilled independently — an
    # older run may already carry one — and a message that says CRS while writing an extent is the
    # kind of small untruth that makes a reader distrust the rest of the output.
    if result.extent is None:
        console.print("  manifest now records the CRS")
        return
    console.print(
        f"  manifest now records the CRS and a recovered extent ({result.extent.area_km2:,.1f} km2)"
    )
