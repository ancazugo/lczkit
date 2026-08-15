"""Structural checks on the vendored-adjacent front end, `assets/app.js`.

**Why this file exists.** `app.js` is the one part of the site nothing executes in CI: there is no
JavaScript engine in this environment and adding one is a large dependency for a 500-line file.
CLAUDE.md's Phase 7 note argues that assertions about `app.js` "would be claims about a string",
which is right about *behaviour* — that is why the style is generated in Python and tested there.

It is not right about *syntax*. A syntax error in this file produces no error path at all: the IIFE
never runs, so the `catch` that prints "could not load the site" never installs either, and the page
is a blank panel beside a blank map. That is the same shape as the defect where the LCZ layer
painted every cell as no-data — invisible to every existing test because each one checked its own
half.

These are deliberately weak checks. They are a delimiter balance and a set of contract assertions
against the metadata `style.py` emits, not a parser. They catch the error an edit actually makes.
"""

from __future__ import annotations

import pytest

from lczkit.viz.site import ASSETS_DIR
from lczkit.viz.style import DISPLAY_LABELS, HEIGHT_SOURCE_LABELS

APP_JS = ASSETS_DIR / "app.js"
INDEX_HTML = ASSETS_DIR / "index.html"


def strip_literals(source: str) -> str:
    """Remove comments and string literals, so only structural delimiters remain.

    Regex literals are left in place. None in this file contains a bracket, and a general
    JavaScript lexer is well past what a balance check is worth — if that changes, this returns a
    false positive rather than a false negative, which is the safe direction.
    """
    out: list[str] = []
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]
        if ch == "/" and i + 1 < n and source[i + 1] == "/":
            i = source.find("\n", i)
            if i == -1:
                break
        elif ch == "/" and i + 1 < n and source[i + 1] == "*":
            end = source.find("*/", i + 2)
            i = n if end == -1 else end + 2
        elif ch in "\"'`":
            quote = ch
            i += 1
            while i < n:
                if source[i] == "\\":
                    i += 2
                    continue
                if source[i] == quote:
                    i += 1
                    break
                i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def test_app_js_delimiters_balance() -> None:
    """The failure mode an edit to this file actually produces, and the one nothing else notices."""
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    for char in strip_literals(APP_JS.read_text(encoding="utf-8")):
        if char in "([{":
            stack.append(char)
        elif char in pairs:
            assert stack, f"unbalanced {char!r}: closed with nothing open"
            assert stack.pop() == pairs[char], f"mismatched {char!r}"
    assert stack == [], f"unclosed {stack}"


def test_app_js_stays_a_single_iife_with_no_globals() -> None:
    """The page loads three classic scripts into one global scope. `app.js` leaking a name could
    collide with MapLibre's or PMTiles' own, which is a bug that appears only in a browser."""
    source = APP_JS.read_text(encoding="utf-8")

    assert source.lstrip().startswith("/*") or source.lstrip().startswith("(function")
    assert "(function ()" in source
    assert '"use strict"' in source


@pytest.mark.parametrize(
    "element",
    [
        "map",
        "panel",
        "view",
        "view-description",
        "hover-readout",
        "legend",
        "base-options",
        "base-note",
        "opacity",
        "opacity-value",
        "about",
        "unit-confidence",
        "unit-summary",
        "unit-heights",
        "unit-parameters",
        "distance-chart",
    ],
)
def test_every_element_the_script_reaches_for_exists_in_the_page(element: str) -> None:
    """`el(id)` returns null for an id the HTML does not define, and the failure surfaces as a
    `TypeError` on a property of null — several frames from the markup that is actually wrong."""
    html = INDEX_HTML.read_text(encoding="utf-8")
    source = APP_JS.read_text(encoding="utf-8")

    assert f'id="{element}"' in html, f"#{element} is used by app.js but absent from index.html"
    assert f'"{element}"' in source, f"#{element} is defined in index.html but unused"


def test_the_script_reads_only_metadata_the_style_module_emits() -> None:
    """`style.py` and `app.js` agree by convention rather than by a shared definition, which is
    exactly the gap the blank-LCZ-layer defect lived in. These are the keys the page dereferences;
    renaming one in Python without the other is a silent blank panel."""
    source = APP_JS.read_text(encoding="utf-8")

    for key in (
        "fill_layer",
        "units_source",
        "units_source_layer",
        "detail_source",
        "distance_columns",
        "distance_labels",
        "height_prefixes",
        "buildings_layer",
        "building_colour_by",
        "basemap",
        "labels",
        "height_source_labels",
        "groups",
        "centre",
    ):
        assert f"meta.{key}" in source or f'"{key}"' in source, key


def test_the_height_source_labels_cover_every_tier_the_cascade_can_report() -> None:
    """A tier missing from the table falls back to its raw key — "wsf3d" — in the one panel whose
    whole purpose is telling a reader how trustworthy a height is."""
    for source in ("overture_height", "overture_num_floors", "wsf3d", "ghsl", "unresolved"):
        assert source in HEIGHT_SOURCE_LABELS
        assert HEIGHT_SOURCE_LABELS[source] != source


def test_the_label_route_values_the_page_explains_are_the_ones_the_classifier_emits() -> None:
    """`label_route` says *how* a cell got its class — nearest prototype, or the functional
    industrial rule. Those are different claims, which is why the page spells them out.

    Written after the first attempt invented the vocabulary: the page mapped `distance`,
    `lcz10_rule` and `lcz1_constraint`, none of which the classifier emits, so every cell would
    have fallen through to printing its raw token. A consumer that guesses at a producer's enum
    fails silently in exactly this way.
    """
    from lczkit.classify.rules import ROUTES

    source = APP_JS.read_text(encoding="utf-8")
    for route in ROUTES:
        assert route in source, f"the page does not explain the {route!r} route"


def test_the_display_labels_name_the_classification_columns_the_registry_does_not() -> None:
    """The parameter registry describes urban canopy parameters. The classification outputs are
    not parameters and would otherwise fall back to underscore-stripping."""
    for column in ("lcz_primary", "lcz_secondary", "uniqueness", "n_params_used"):
        assert column in DISPLAY_LABELS
