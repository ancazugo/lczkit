"""Turning command-line strings into the objects the package already uses.

Every function here raises `typer.BadParameter` rather than returning a sentinel, so a malformed
argument is reported against the flag that carried it.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from pydantic import ValidationError

from lczkit.config import Settings
from lczkit.protocols import BBox


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
