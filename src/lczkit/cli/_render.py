"""Console output for the CLI, and the one place `rich` is allowed to be imported.

Keeping it here is what lets `lczkit.pipeline` stay a library: it takes a `StageObserver` and never
learns whether anything is watching. The package's own convention is *record it in the report,
don't log it* — every number below is read back out of a report the run already produced, not
collected on the way past.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import NoReturn

import typer
from rich.console import Console
from rich.table import Table

from lczkit.pipeline import PipelineResult
from lczkit.viz import SiteReport

console = Console(stderr=True)
"""Progress and errors go to stderr, so a caller can pipe a command's real output somewhere."""

out = Console()
"""Results go to stdout."""

EXIT_CONFIG = 2
"""`DATA_DIR` unset, a bad config file, an unusable preset — anything resolved before work
starts."""

EXIT_MISSING_TOOL = 3
"""A required external tool is absent. Today that is only tippecanoe."""

LARGE_EXTENT_KM2 = 900.0
"""Above this an extent is a long run, and both `run` and `cities` say so.

Berlin's full 891 km² administrative extent is the measured reference — 9.8 minutes of cleaning —
so this is the size at which "try it with --extent-km first" stops being fussy advice. 239 of
GUPPD's 5 558 regions are above it; the median is 80 km².
"""


def fail(message: str, code: int = EXIT_CONFIG) -> NoReturn:
    """Print `message` and exit, with no traceback.

    CLAUDE.md asks config problems to fail loudly and early. A stack trace is loud but not clear:
    the message these raise already names the fix, so the trace only buries it.
    """
    console.print(f"[bold red]error[/bold red] {message}")
    raise typer.Exit(code)


class StageProgress:
    """A `StageObserver` that prints each stage and its wall time as it finishes.

    Deliberately a line per stage rather than a live spinner. Stages here run for minutes to hours,
    output is routinely redirected to a file on a batch node, and a re-rendering progress bar in a
    log is unreadable. This is the shape `scripts/berlin_metropolitan_run.Timer` already had.
    """

    def __init__(self, *, quiet: bool = False) -> None:
        self.quiet = quiet

    @contextmanager
    def _stage(self, name: str) -> Iterator[None]:
        if self.quiet:
            yield
            return
        # The "running" line is overwritten by the "done" line that replaces it, which only works
        # on a terminal. Redirected to a file — which is how a metropolitan run is actually invoked
        # — a carriage return is not an erase, so both lines survive and every stage appears twice.
        if console.is_terminal:
            console.print(f"  [dim]{name:<16}[/dim] [yellow]running[/yellow]", end="\r")
        try:
            yield
        except BaseException:
            console.print(f"  [dim]{name:<16}[/dim] [bold red]failed [/bold red]")
            raise
        console.print(f"  [dim]{name:<16}[/dim] [green]done   [/green]")

    def stage(self, name: str) -> AbstractContextManager[None]:
        """Context manager printing `name` as it starts, and its outcome as it ends.

        Failure is printed before the exception propagates, so a run that dies mid-pipeline says
        which stage it died in rather than only what the traceback shows.
        """
        return self._stage(name)


def stage_table(result: PipelineResult) -> Table:
    """Wall time per stage, in the order they ran."""
    table = Table(title="stages", title_justify="left", header_style="dim")
    table.add_column("stage")
    table.add_column("seconds", justify="right")
    for name, seconds in result.stages.items():
        table.add_row(name, f"{seconds:.1f}")
    table.add_row("[bold]total[/bold]", f"[bold]{result.seconds:.1f}[/bold]")
    return table


def tileset_table(site: SiteReport) -> Table:
    """What each tileset cost, read back out of the site report."""
    table = Table(title="tilesets", title_justify="left", header_style="dim")
    table.add_column("tileset")
    table.add_column("size", justify="right")
    table.add_column("zooms", justify="right")
    table.add_column("features", justify="right")
    table.add_column("seconds", justify="right")
    for tileset in site.tilesets:
        table.add_row(
            tileset.name,
            f"{tileset.size_bytes / 1e6:.2f} MB",
            f"z{tileset.min_zoom}-{tileset.max_zoom}",
            f"{tileset.n_features:,}",
            f"{tileset.seconds:.1f}",
        )
    total = sum(tileset.size_bytes for tileset in site.tilesets)
    table.add_row("[bold]total[/bold]", f"[bold]{total / 1e6:.2f} MB[/bold]", "", "", "")
    return table


def report_site(site: SiteReport) -> None:
    """Print a built site's tilesets, anything skipped, and the command that opens it."""
    out.print(tileset_table(site))
    for name, reason in site.skipped.items():
        console.print(f"  [yellow]skipped[/yellow] {name}: {reason}")
    serve_hint(site.site_dir)


def serve_hint(site_dir: Path) -> None:
    """Say how to open a site.

    Always printed after a build, because the first thing a recipient tries is opening
    `index.html`, and that fails with an unexplained network error — PMTiles reads byte ranges
    through `fetch`, and the Fetch standard leaves `file:` URLs unhandled.
    """
    # `soft_wrap` because a run directory under a long DATA_DIR otherwise wraps mid-path, and the
    # whole point of this line is that it can be copied and pasted.
    console.print(f"\n  open it: [bold]lczkit site serve {site_dir.parent}[/bold]", soft_wrap=True)
