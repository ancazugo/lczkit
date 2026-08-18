"""The glossary against the pages that lean on it.

This project's standing lesson is that a rule is not applied until something checks it. The rule
here is that a reader should never meet an abbreviation or a domain term this documentation has not
defined — and a glossary goes stale the moment a new term arrives and nobody remembers the page
exists. These tests are what remembers.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
GLOSSARY = REPO / "docs_src" / "glossary.md"
MKDOCS = REPO / "mkdocs.yml"

#: Every abbreviation and domain term this documentation uses in prose and a reader is unlikely to
#: know. Curated rather than scraped: the point is to assert that *these* are defined, and a
#: scraper would drift into asserting that `HTTP` and `JSON` have entries.
TERMS = (
    "Local Climate Zone",
    "urban canopy parameter",
    "building surface fraction",
    "aspect ratio",
    "height of roughness elements",
    "sky view factor",
    "roughness length",
    "frontal area index",
    "spatial unit",
    "partition",
    "bounding box",
    "enclosure",
    "prototype distance",
    "uniqueness",
    "Overture Maps",
    "OpenStreetMap",
    "ESA WorldCover",
    "WSF-3D",
    "TanDEM-X",
    "GHS-BUILT-H",
    "GUPPD",
    "So2Sat LCZ42",
    "WUDAPT",
    "ceiling",
    "confusion axes",
    "GeoParquet",
    "GeoPackage",
    "coordinate reference system",
    "GDAL",
    "PMTiles",
    "MapLibre",
    "tippecanoe",
    "WRF",
    "cascade",
    "provenance",
    "preset",
    "sweep",
)


@pytest.mark.parametrize("term", TERMS)
def test_every_domain_term_has_a_glossary_entry(term: str) -> None:
    """A term used in the documentation and defined nowhere is a term the reader has to guess at."""
    assert GLOSSARY.is_file(), "docs_src/glossary.md is missing"

    assert term.lower() in GLOSSARY.read_text().lower(), (
        f"{term!r} is used in this documentation and has no glossary entry. "
        "Either add one to docs_src/glossary.md or stop using the term."
    )


def test_the_glossary_is_in_the_nav() -> None:
    """`mkdocs build --strict` fails on a page outside the nav, but that costs a full build to
    find out; this says so in under a second."""
    assert ": glossary.md" in MKDOCS.read_text()


def test_the_glossary_expands_every_abbreviation_it_defines() -> None:
    """An entry headed by an abbreviation must spell it out, or it has defined nothing.

    Checked on the abbreviation-shaped headings only — a heading like *Patch* is a word, not an
    abbreviation, and needs no expansion.
    """
    text = GLOSSARY.read_text()
    # Definition-list terms are the non-indented lines whose next line begins the definition.
    lines = text.split("\n")
    headings = [
        line.strip("*` ")
        for line, following in zip(lines, lines[1:], strict=False)
        if line.strip() and not line.startswith((" ", "#", "|", ":")) and following.startswith(":")
    ]
    bare = [
        head
        for head in headings
        if re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{1,}", head.split(" ")[0].strip("()"))
        and "(" not in head
        and len(head.split()) == 1
    ]

    for head in bare:
        entry = text.split(head, 1)[1].split("\n\n", 1)[0]
        assert re.search(r"[A-Z][a-z]+ [A-Za-z]", entry), (
            f"the glossary entry for {head!r} never spells it out"
        )
