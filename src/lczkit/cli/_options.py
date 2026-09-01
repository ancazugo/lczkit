"""Turning command-line strings into the objects the package already uses.

Every function here raises `typer.BadParameter` rather than returning a sentinel, so a malformed
argument is reported against the flag that carried it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast, get_args

import typer
from pydantic import ValidationError

from lczkit.cli._render import console, fail
from lczkit.config import LandCoverBackend, Settings, VizConfig
from lczkit.landcover.earthengine import check_asset
from lczkit.protocols import BBox
from lczkit.viz.basemaps import DEFAULT_BASEMAP_KEYS, PROVIDERS

BASEMAP_HELP = (
    f"Online base map to offer, repeatable ({', '.join(sorted(PROVIDERS))}), "
    f"or 'all', or 'none'. Defaults to the keyless grounds "
    f"({', '.join(DEFAULT_BASEMAP_KEYS)}); the MapTiler ones must be asked for, because they "
    "write an API key into the built site."
)

LAND_COVER_BACKENDS: tuple[str, ...] = get_args(LandCoverBackend)
"""The accepted `--land-cover-source` values, read off the config type rather than listed here.

A backend added to `LandCoverBackend` reaches the command line by being added, and one removed
stops being accepted — the alternative is a second list that agrees until someone edits one.
"""

LAND_COVER_SOURCE_HELP = (
    f"Where land-cover fractions come from ({', '.join(LAND_COVER_BACKENDS)}). "
    "'local' mosaics the ESA WorldCover tiles the extent spans and reduces them here; "
    "'gee' reduces the configured Earth Engine asset server-side and needs credentials and a "
    "billable project. Defaults to what the preset or --config says, which is 'local'."
)


def parse_basemaps(values: list[str] | None) -> list[str] | None:
    """`--basemap` occurrences resolved to provider keys, or `None` when the flag was not given.

    `None` and `[]` are different answers and both are reachable: not passing the flag defers to
    the run and then to `DEFAULT_BASEMAP_KEYS`, while `--basemap none` asks for a site that reaches
    no network. Returning the same value for both would make the flag unable to turn a ground off —
    which is the difference between "I did not say" and "I said no", and only one of those is an
    instruction. `apply_basemaps` is where the two are resolved.

    Shared by `run` and `site build` because it is one flag with one meaning. They previously
    validated it two different ways — one checking `PROVIDERS` directly, the other round-tripping
    the config — and only one of them accepted `none`, so the same argument was an error in one
    command and a instruction in the other.
    """
    if values is None:
        return None
    keys: list[str] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if not part or part == "none":
                continue
            if part == "all":
                keys.extend(PROVIDERS)
            elif part in PROVIDERS:
                keys.append(part)
            else:
                raise typer.BadParameter(
                    f"unknown basemap {part!r}; choose from {', '.join(sorted(PROVIDERS))}, "
                    "or 'all', or 'none'"
                )
    return list(dict.fromkeys(keys))


def apply_basemaps(config: VizConfig, keys: list[str] | None) -> None:
    """Put the chosen grounds on `config` and print what they oblige the caller to.

    `keys` is what `parse_basemaps` returned, so `None` means the flag was absent. That falls back
    to `DEFAULT_BASEMAP_KEYS` **only when the run has no grounds of its own** — rebuilding a site
    must not quietly change what the run was built with, and a run that recorded a ground has
    already answered this question.

    Usage terms are printed for providers the caller *named* and summarised for the defaults. A
    provider selected on purpose is one whose policy the caller is taking on knowingly — the OSMF
    tile servers are a donated resource, and MapTiler publishes a key — while four blocks of terms
    on every ordinary run is the kind of output people stop reading.
    """
    explicit = keys is not None
    if keys is None:
        keys = list(config.basemap_keys) or list(DEFAULT_BASEMAP_KEYS)
    config.online_basemaps = keys
    # The deprecated singular would otherwise survive alongside the list and reappear in the picker.
    config.online_basemap = None

    if not keys:
        console.print("  base maps: [bold]none[/bold] — this site will reach no network")
        return
    chosen = [PROVIDERS[key] for key in keys]
    if explicit:
        for entry in chosen:
            console.print(f"  base map: [bold]{entry.label}[/bold] — {entry.licence}")
            if entry.terms:
                console.print(f"  [yellow]note[/yellow] {entry.terms}")
        return
    console.print(
        "  base maps: [bold]" + "[/bold], [bold]".join(e.label for e in chosen) + "[/bold]"
    )
    console.print(
        "  [dim]each carries its provider's usage terms, shown when you name one; "
        "--basemap none to build a site that reaches no network[/dim]"
    )


def parse_land_cover_source(value: str | None) -> LandCoverBackend | None:
    """`--land-cover-source` resolved to a backend name, or `None` when the flag was not given.

    `None` means "I did not say", which leaves whatever the preset and `--config` resolved to.
    That is the same distinction `parse_basemaps` draws, and it matters for the same reason: a
    config file may set `land_cover.source`, and a flag that could not tell "unset" from "local"
    would silently overrule it on every run that did not repeat it.

    Validated here rather than by `typer`'s own enum handling so that the message names the
    alternatives in the package's own words, and so that it is refused before `DATA_DIR` is
    consulted — a mistyped backend is not an environment problem.
    """
    if value is None:
        return None
    cleaned = value.strip()
    if cleaned not in LAND_COVER_BACKENDS:
        raise typer.BadParameter(
            f"unknown land-cover source {cleaned!r}; choose from {', '.join(LAND_COVER_BACKENDS)}"
        )
    return cast(LandCoverBackend, cleaned)


def apply_land_cover_source(settings: Settings, value: LandCoverBackend | None) -> None:
    """Put the chosen backend on `settings`, refuse one that cannot run, and print its terms.

    The refusal calls `check_asset` rather than restating it, so there is one definition of what
    Earth Engine needs and the command line only decides how it is reported. Without this a
    `--dry-run` naming a backend with no `GEE_PROJECT_NAME` printed "project None" and exited
    zero — the one command whose whole purpose is to say whether the configuration will run,
    saying it will.

    The terms are printed for the same reason a base map's are: Earth Engine is a credentialed,
    quota-limited service billed to a named project, and the moment the choice is made is when
    that is worth knowing. The local backend is the default and says nothing.
    """
    if value is not None:
        settings.land_cover.source = value
    if settings.land_cover.source != "gee":
        return
    dataset = settings.land_cover.dataset(settings.ucp.land_cover_dataset)
    try:
        check_asset(dataset, settings.land_cover.gee_project)
    except ValueError as error:
        fail(str(error))
    console.print(
        f"  land cover: [bold]Earth Engine[/bold] {dataset.gee.collection_id} "
        f"as project {settings.land_cover.gee_project}"
    )
    console.print(
        "  [dim]a billed, quota-limited service; --land-cover-source local reduces ESA "
        "WorldCover here instead[/dim]"
    )


def parse_bbox(value: str) -> BBox:
    """`"W,S,E,N"` in lon/lat degrees, validated as an ordered, in-range window.

    Checked here rather than three stages in: a reversed or transposed bbox produces an empty
    Overture extract and then a confusing failure about an empty frame, having already spent the
    download.
    """
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise typer.BadParameter(
            f"expected four comma-separated numbers 'W,S,E,N', got {len(parts)}: {value!r}"
        )
    try:
        west, south, east, north = (float(part) for part in parts)
    except ValueError:
        raise typer.BadParameter(f"all four values must be numbers: {value!r}") from None

    if not -180.0 <= west < east <= 180.0:
        raise typer.BadParameter(
            f"longitudes must satisfy -180 <= W < E <= 180, got W={west}, E={east}"
        )
    if not -90.0 <= south < north <= 90.0:
        raise typer.BadParameter(
            f"latitudes must satisfy -90 <= S < N <= 90, got S={south}, N={north}"
        )
    return (west, south, east, north)


def apply_config_file(settings: Settings, path: Path) -> Settings:
    """Overlay a JSON config file onto `settings`, section by section.

    A *partial* document is the useful case — a file naming only `classification` should not have
    to restate the cleaning thresholds. So each top-level key is validated against the model that
    owns it and replaces that section wholesale, rather than the whole document being validated as
    a `Settings`, which would demand every field.

    `data_dir` and `run_id` are refused: they are resolved from the environment and the command
    line respectively, and a file that could move either would make the same command write to two
    different places depending on a path the user did not type.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise typer.BadParameter(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise typer.BadParameter(f"{path} is not valid JSON: {error}") from error

    if not isinstance(document, dict):
        raise typer.BadParameter(
            f"{path} must contain a JSON object, not {type(document).__name__}"
        )

    # A manifest is the most likely thing to be handed to this flag, and it nests the settings
    # under "config". Accepting it means a run can be reproduced from its own output.
    if "config" in document and isinstance(document["config"], dict):
        document = document["config"]

    refused = sorted({"data_dir", "run_id"} & set(document))
    if refused:
        raise typer.BadParameter(
            f"{path} sets {', '.join(refused)}, which comes from the environment and --run-id; "
            "remove it from the file"
        )

    fields = Settings.model_fields
    unknown = sorted(set(document) - set(fields))
    if unknown:
        raise typer.BadParameter(
            f"{path} has unknown settings {', '.join(unknown)}; expected any of "
            f"{', '.join(sorted(set(fields) - {'data_dir', 'run_id'}))}"
        )

    for name, value in document.items():
        annotation = fields[name].annotation
        if annotation is None:
            continue
        try:
            setattr(settings, name, annotation.model_validate(value))
        except ValidationError as error:
            raise typer.BadParameter(f"{path}, section '{name}': {error}") from error
    return settings
