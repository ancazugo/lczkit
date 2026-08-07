"""Parsers for the committed markdown reference tables, so tests can check transcriptions.

CLAUDE.md's sharpest warning is about numeric lookups: "Don't reproduce a Tier 1 numeric range
from memory. Read `docs/references/tables/`... A plausible-looking wrong threshold is the worst
failure mode this package has." The tables are committed precisely so a checkout can reproduce a
classification; these parsers are what make the packaged constants provably equal to them rather
than merely intended to be.

Reading `docs/` from a test is `__file__`-relative, like `tests/fixtures/`. Both are repo content
rather than data, so neither needs `DATA_DIR` and both work on a clean checkout — which is the
whole point of the rule that exception exists for.
"""

from __future__ import annotations

from pathlib import Path

TABLES_DIR = Path(__file__).resolve().parent.parent / "docs" / "references" / "tables"

STEWART_OKE_TABLE = TABLES_DIR / "stewart_oke_2012_properties.md"
DEMUZERE_TABLE = TABLES_DIR / "demuzere_2022_lcz_codes.md"
NATURAL_RANGES_TABLE = TABLES_DIR / "lczkit_natural_class_ranges.md"

#: Column header in `stewart_oke_2012_properties.md` -> property name in
#: `lczkit.classify.prototypes.PROPERTIES`. Explicit rather than derived from the header text: a
#: renamed column should fail loudly here rather than be silently normalised into a match.
STEWART_OKE_PROPERTIES = {
    "Sky view factor": "sky_view_factor",
    "Aspect ratio": "aspect_ratio",
    "Building surface fraction %": "building_surface_fraction",
    "Impervious surface fraction %": "impervious_surface_fraction",
    "Pervious surface fraction %": "pervious_surface_fraction",
    "Height of roughness elements m": "height_of_roughness_elements",
    "Terrain roughness class": "terrain_roughness_class",
    "Surface admittance": "surface_admittance",
    "Surface albedo": "surface_albedo",
    "Anthropogenic heat output W/m²": "anthropogenic_heat_output",
}

Ranges = dict[str, dict[str, tuple[float | None, float | None]]]
"""`LCZ label -> property -> (min, max)`, with `None` for a blank cell."""


def rows(path: Path, *, first_column: str) -> list[list[str]]:
    """Cells of the one markdown table in `path` whose header starts with `first_column`.

    A file may hold several tables — `lczkit_natural_class_ranges.md` does — so the header is
    matched rather than the first pipe-delimited line being assumed to be the right one.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    header_index = next(
        index
        for index, line in enumerate(lines)
        if line.startswith("|") and _cells(line)[0] == first_column
    )
    header = _cells(lines[header_index])
    body: list[list[str]] = [header]
    for line in lines[header_index + 2 :]:  # +2 skips the alignment row
        if not line.startswith("|"):
            break
        body.append(_cells(line))
    return body


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def stewart_oke_ranges() -> Ranges:
    """The published property table, keyed by LCZ label and property name."""
    header, *body = rows(STEWART_OKE_TABLE, first_column="LCZ")
    pairs = _paired_columns(header, STEWART_OKE_PROPERTIES)
    return _read(body, pairs)


def lczkit_natural_ranges() -> Ranges:
    """The lczkit-owned tree and water ranges."""
    header, *body = rows(NATURAL_RANGES_TABLE, first_column="LCZ")
    pairs = _paired_columns(header, {"tree": "tree_fraction", "water": "water_fraction"})
    return _read(body, pairs)


def demuzere_classes() -> list[dict[str, str]]:
    """`code`, `lcz`, `name` and `colour` per row of the code/colour table."""
    header, *body = rows(DEMUZERE_TABLE, first_column="Code")
    return [dict(zip(header, row, strict=True)) for row in body]


def _paired_columns(header: list[str], properties: dict[str, str]) -> dict[str, tuple[int, int]]:
    """`property name -> (min column index, max column index)`."""
    positions: dict[str, tuple[int, int]] = {}
    for label, name in properties.items():
        positions[name] = (
            header.index(f"{label} (min)"),
            header.index(f"{label} (max)"),
        )
    return positions


def _read(body: list[list[str]], pairs: dict[str, tuple[int, int]]) -> Ranges:
    table: Ranges = {}
    for row in body:
        label = row[0].removeprefix("LCZ ")
        entries = {
            name: (_value(row[low]), _value(row[high])) for name, (low, high) in pairs.items()
        }
        table[label] = {name: bounds for name, bounds in entries.items() if bounds != (None, None)}
    return table


def _value(cell: str) -> float | None:
    return None if cell == "" else float(cell)
