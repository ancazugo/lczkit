"""`lczkit cities` — find the urban region a run should cover, before spending a download.

The command that makes `--city` usable. GUPPD names 5 558 regions and 149 of those names are shared
by more than one, so a caller needs to see what they are about to ask for: which country, how much
ground, and therefore roughly what it will cost. Printing the area is the point — a 64 km² region
is a few minutes and a 17 661 km² one is not, and nothing else in the interface says so.

Reads one 564 KB table under `input/NASA/`. No pipeline, no network, no label archive.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from lczkit.cities import BY_KEY
from lczkit.cli._render import LARGE_EXTENT_KM2, console, fail, out
from lczkit.config import Settings
from lczkit.places import Place, find, load_places, normalise


def cities(
    query: Annotated[
        str | None,
        typer.Argument(help="Part of a city name. Omit to list the largest regions."),
    ] = None,
    country: Annotated[
        str | None,
        typer.Option(
            "--country",
            metavar="ISO",
            help="ISO code or country name, e.g. GBR or 'united kingdom'.",
        ),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Most rows to print.")] = 20,
) -> None:
    """Search the GUPPD urban regions `--city` resolves against.

        lczkit cities cambridge
        lczkit cities london --country gb

    Prints each match's bounding box and its area, so the extent a run would cover is visible
    before the run starts. Pass any of these names to `lczkit run --city`.
    """
    settings = _settings()
    try:
        places = load_places(settings)
    except (FileNotFoundError, ValueError) as error:
        fail(str(error))

    matches = find(places, query or "", country=country)
    if not matches:
        where = f" in {country}" if country else ""
        fail(f"no urban region matching {query!r}{where}. Names come from the JRC gazetteer.")

    if query is None:
        # Nothing to rank by, so show the ones a reader is most likely to be looking for.
        matches = sorted(matches, key=lambda entry: entry.area_km2, reverse=True)

    out.print(_table(matches[:limit]))
    if len(matches) > limit:
        console.print(f"  {len(matches) - limit:,} more; narrow with --country or raise --limit")
    _note_large(matches[:limit])


def _table(matches: list[Place]) -> Table:
    """One row per region: what to type, where it is, and what it would cost."""
    table = Table(header_style="dim")
    table.add_column("city")
    table.add_column("country")
    # Folded rather than truncated: this column exists to be copied into `--bbox`, and an
    # ellipsis in the middle of a coordinate is worse than a wrapped line.
    table.add_column("bbox (W,S,E,N)", overflow="fold")
    table.add_column("km2", justify="right")
    table.add_column("so2sat", justify="center")
    for entry in matches:
        bbox = ",".join(f"{value:.4f}" for value in entry.bbox)
        # The 28 keys `--so2sat-window` accepts, marked because that flag is the only way to
        # reproduce a recorded agreement figure and it works for these cities alone.
        pinned = "*" if (normalise(entry.name), entry.iso) in _SO2SAT_ROWS else ""
        table.add_row(
            entry.name,
            f"{entry.country} ({entry.iso})",
            bbox,
            f"{entry.area_km2:,.0f}",
            pinned,
        )
    return table


def _note_large(matches: list[Place]) -> None:
    """Say so when a listed region is big enough that a whole-extent run is a long one."""
    large = [entry for entry in matches if entry.area_km2 > LARGE_EXTENT_KM2]
    if not large:
        return
    console.print(
        f"  [yellow]note[/yellow] {len(large)} of these exceed {LARGE_EXTENT_KM2:,.0f} km2, "
        "where a run takes tens of minutes; --extent-km trims one concentrically"
    )


_SO2SAT_ROWS = {
    (normalise(name), city.iso)
    for city in BY_KEY.values()
    for name in (city.key, city.so2sat.replace("_", " "))
}
"""(normalised name, ISO) of every GUPPD row `--so2sat-window` can pin a window for.

**Keyed on the country as well as the name, because the name alone marks the wrong cities.** Three
registry keys name a city that exists in more than one country — London (GBR *and* CAN), Santiago
(CHL *and* PHL) and Los Angeles (USA, against Chile's Los Ángeles) — so a name-only match put the
mark on three rows that carry no So2Sat labels at all, telling a reader to try a flag that cannot
work there.

Both the registry key and the So2Sat directory name, because they differ: `islamabad` against
`Rawalpindi_[Islamabad]`, which is how GUPPD spells it too.
"""


def _settings() -> Settings:
    """`Settings.load` without creating a run directory — this command writes nothing."""
    try:
        return Settings.load(create_run_dir=False)
    except (ValueError, OSError) as error:
        fail(str(error))
