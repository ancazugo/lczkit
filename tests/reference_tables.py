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

import re
from pathlib import Path

TABLES_DIR = Path(__file__).resolve().parent.parent / "docs" / "references" / "tables"

STEWART_OKE_TABLE = TABLES_DIR / "stewart_oke_2012_properties.md"
DEMUZERE_TABLE = TABLES_DIR / "demuzere_2022_lcz_codes.md"
NATURAL_RANGES_TABLE = TABLES_DIR / "lczkit_natural_class_ranges.md"
BUILDING_SIZE_TABLE = TABLES_DIR / "lczkit_building_size_ranges.md"
SIMILARITY_TABLE = TABLES_DIR / "lcz_class_similarity.md"

SIMILARITY_HEADING = "## Similarity matrix of LCZ classes"
"""The heading of the matrix `OA_w` uses.

Selected by heading rather than by header row, which is what `rows()` does, because that file holds
**two** matrices with an identical `| LCZ | 1 | 2 | ...` header — a similarity matrix and its
complement. `rows()` would return whichever appears first, and the first is the dissimilarity one.
Reading the wrong one does not fail: it inverts the metric, so a perfect map scores 0.00 and every
cross-city comparison ranks backwards. See the table file for the worked values.
"""

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


def lczkit_building_size_ranges() -> Ranges:
    """The lczkit-owned mean building area ranges, for LCZ 7 and LCZ 8 only.

    Classes the table does not list are unbounded on both sides, so they are absent from the result
    rather than present with a `(None, None)` pair — matching how `_RANGES` records an unconstrained
    property, and keeping "this class has no size claim" distinct from "this class has one and it is
    blank on both ends".
    """
    header, *body = rows(BUILDING_SIZE_TABLE, first_column="LCZ")
    pairs = _paired_columns(header, {"mean building area m²": "mean_building_area"})
    return {
        label: {name: bounds for name, bounds in properties.items() if bounds != (None, None)}
        for label, properties in _read(body, pairs).items()
    }


def lcz_similarity() -> dict[tuple[str, str], float]:
    """The Bechtel et al. (2020) similarity weights, keyed by `(reference label, predicted label)`.

    Labels are the Stewart & Oke ones — `"1"`-`"10"`, `"A"`-`"G"` — not integer codes, so a reader
    comparing a cell against the paper is comparing the same thing the paper prints.
    """
    lines = SIMILARITY_TABLE.read_text(encoding="utf-8").splitlines()
    # Trailing parenthetical stripped, so the table can record which figure of the paper each
    # matrix came from — "(Figure 3b)" — without an added citation breaking the parse.
    start = next(
        i
        for i, line in enumerate(lines)
        if re.sub(r"\s*\([^)]*\)\s*$", "", line.strip()) == SIMILARITY_HEADING
    )
    # The contiguous run of table lines. The section also carries a worked-values table further
    # down, which filtering on `startswith("|")` alone would run straight into.
    body = lines[start:]
    first = next(index for index, line in enumerate(body) if line.startswith("|"))
    table: list[str] = []
    for line in body[first:]:
        if not line.startswith("|"):
            break
        table.append(line)
    header = _cells(table[0])[1:]
    weights: dict[tuple[str, str], float] = {}
    for line in table[2:]:  # +2 skips the alignment row
        cells = _cells(line)
        for column, value in zip(header, cells[1:], strict=True):
            weights[(cells[0], column)] = float(value)
    return weights


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
