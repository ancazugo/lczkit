"""`lczkit site` — build a map site from a finished run, and serve it.

Both commands take a *run* directory, not a site directory. The run directory is what a run
produces and what gets archived; `site/` is a thing inside it. Taking the run directory in both
places means a user never has to remember which level they are at.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from lczkit.cli._render import EXIT_MISSING_TOOL, console, fail, report_site
from lczkit.config import VizConfig
from lczkit.output import MANIFEST_FILE
from lczkit.viz import SITE_DIR, TippecanoeMissingError, build_site, serve
from lczkit.viz.basemaps import PROVIDERS

app = typer.Typer(no_args_is_help=True, help="Build and serve a run's map site.")


@app.command("build")
def build(
    run_dir: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            help="A run directory, i.e. output/lczkit/<run_id>/.",
        ),
    ],
    buildings: Annotated[
        bool | None,
        typer.Option(
            "--buildings/--no-buildings",
            help="Tile building footprints. Defaults to whatever the run recorded.",
        ),
    ] = None,
    basemap: Annotated[
        str | None,
        typer.Option(
            "--basemap",
            metavar="KEY",
            help=(
                f"Add a selectable online base map ({', '.join(sorted(PROVIDERS))}), "
                "or 'none'. Off by default: the site otherwise reaches no network."
            ),
        ),
    ] = None,
) -> None:
    """Build `<run_dir>/site/` from the run's own outputs.

    A pure transform: everything drawn was decided by the run and written into its manifest and
    its persisted layers. Rebuilding an archived run needs no access to `input/`.
    """
    manifest = run_dir / MANIFEST_FILE
    if not manifest.exists():
        fail(
            f"{run_dir} has no {MANIFEST_FILE}, so it is not a run directory. "
            "Pass the directory a run wrote, not its site/ subdirectory."
        )

    config: VizConfig | None = None
    if buildings is not None or basemap is not None:
        config = _viz_config(run_dir)
    if config is not None and buildings is not None:
        config.include_buildings = buildings
    if config is not None and basemap is not None:
        config.online_basemap = None if basemap == "none" else basemap
        try:
            VizConfig.model_validate(config.model_dump())
        except ValidationError as error:
            fail(f"--basemap: {error}")

    console.print(f"building site for [bold]{run_dir.name}[/bold]")
    if config is not None and config.online_basemap is not None:
        chosen = PROVIDERS[config.online_basemap]
        console.print(f"  base map: [bold]{chosen.label}[/bold] — {chosen.licence}")
        if chosen.terms:
            console.print(f"  [yellow]note[/yellow] {chosen.terms}")
    try:
        report = build_site(run_dir, config=config)
    except TippecanoeMissingError as error:
        fail(str(error), EXIT_MISSING_TOOL)
    report_site(report)


@app.command("serve")
def serve_site(
    run_dir: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=False, help="A run directory with a built site/."),
    ],
    port: Annotated[int, typer.Option("--port", help="Port to bind.")] = 8000,
    bind: Annotated[str, typer.Option("--bind", help="Address to bind.")] = "127.0.0.1",
) -> None:
    """Serve a built site over loopback until interrupted.

    A server is required rather than preferred: PMTiles reads byte ranges through `fetch`, and the
    Fetch standard leaves `file:` URLs unhandled, so opening `index.html` fails in both Chrome and
    Firefox. This reaches no network — it is the same standard-library server the site ships with.
    """
    site_dir = _resolve_site_dir(run_dir)
    try:
        serve(site_dir, port=port, bind=bind)
    except KeyboardInterrupt:
        console.print("\nstopped")
    except OSError as error:
        fail(f"cannot serve on {bind}:{port}: {error}")


def _viz_config(run_dir: Path) -> VizConfig:
    """The run's own recorded viz settings, so a flag overrides one field rather than all of them.

    The same read `build_site` does when it is given no config. Doing it here too is what lets
    `--buildings` mean "the run's settings, but with buildings" instead of "the defaults".
    """
    manifest = json.loads((run_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
    return VizConfig.model_validate(manifest.get("config", {}).get("viz", {}))


def _resolve_site_dir(run_dir: Path) -> Path:
    """Accept either a run directory or the site inside one, and say so when neither works."""
    if (run_dir / "index.html").exists():
        return run_dir
    site_dir = run_dir / SITE_DIR
    if (site_dir / "index.html").exists():
        return site_dir
    fail(
        f"no built site in {run_dir}. Build one first: lczkit site build {run_dir}",
    )
