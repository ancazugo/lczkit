"""The 107-attribute registry against its committed source table, cell for cell.

The same treatment `overture_lcz_semantic_mapping.md` and `stewart_oke_2012_properties.md` get —
a registry that only lives in Python is one nobody can check against the paper it claims to
implement. This is also the acceptance test for "all 107 attributes were actually built": the
table was transcribed from Majer & Fleischmann (2026) Supplementary A before any compute module
was written, independently tallied to 107 by section, and this test is what proves the shipped
`PARAMETERS` tuple reproduces it exactly rather than merely matching its count.
"""

from __future__ import annotations

import re
from pathlib import Path

from lczkit.morphometrics.registry import PARAMETER_COLUMNS, PARAMETERS

TABLE = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "references"
    / "tables"
    / "majer_2026_morphometrics_menu.md"
)

_ROW = re.compile(
    r"^\|\s*`(?P<name>[a-z0-9_]+)`\s*\|(?P<object>[^|]*)\|(?P<call>[^|]*)\|(?P<scale>[^|]*)\|\s*$"
)


def parse_menu() -> dict[str, dict[str, str]]:
    """Every attribute row in the committed table, as `name -> {object, call, scale}`."""
    rows: dict[str, dict[str, str]] = {}
    for line in TABLE.read_text(encoding="utf-8").splitlines():
        match = _ROW.match(line.strip())
        if not match:
            continue
        rows[match["name"]] = {
            "object": match["object"].strip(),
            "call": match["call"].strip(),
            "scale": match["scale"].strip(),
        }
    return rows


def test_the_menu_table_has_exactly_107_rows() -> None:
    """The number the paper itself reports (§3.1: "107 primary morphometric attributes"),
    independently re-tallied by section (62 + 23 + 22) before this test was written."""
    assert len(parse_menu()) == 107


def test_every_registered_parameter_is_a_menu_row_and_vice_versa() -> None:
    menu = parse_menu()
    registered = set(PARAMETER_COLUMNS)

    missing_from_registry = sorted(set(menu) - registered)
    missing_from_menu = sorted(registered - set(menu))
    assert not missing_from_registry, f"in the menu but not implemented: {missing_from_registry}"
    assert not missing_from_menu, f"implemented but not in the menu: {missing_from_menu}"


def test_no_duplicate_names_in_either_source() -> None:
    assert len(PARAMETER_COLUMNS) == len(set(PARAMETER_COLUMNS))
    assert len(PARAMETERS) == 107


def test_every_registered_parameter_has_a_documented_unit_and_reference() -> None:
    """The project's own rule: no parameter reaches the output without a documented unit and a
    source reference. Cheap and absolute, so it stays a test rather than a code-review habit."""
    from lczkit.ucp.registry import UNITS

    for parameter in PARAMETERS:
        assert parameter.unit in UNITS, parameter.name
        assert parameter.description, parameter.name
        assert parameter.reference, parameter.name
