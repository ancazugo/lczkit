"""The "About this map" block describes the run it is on, rather than a run it assumes.

Both rows here were producer/consumer mismatches of the shape this project keeps finding: the
front end restating something the manifest already answers, and drifting when the answer changed.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_JS = Path(__file__).parent.parent / "src" / "lczkit" / "viz" / "assets" / "app.js"


def about_source() -> str:
    """The body of `renderAbout`, which is the only function these claims are about."""
    source = APP_JS.read_text(encoding="utf-8")
    start = source.index("function renderAbout(")
    end = source.index(
        "/* --------------------------------------------------------------------- boot */"
    )
    return source[start:end]


def about_code() -> str:
    """The same body with its comments stripped.

    The comment explaining why a hardcoded string was removed contains that string, so a test
    matching the raw source flags the explanation as the defect. Phase 22 hit the same shape from
    the other side — a docstring naming the forbidden DuckDB form — and answered it by reading the
    module's string literals through `ast` rather than its lines. There is no JavaScript parser
    here, so the comments come out and the assertion is about code.
    """
    body = re.sub(r"/\*.*?\*/", "", about_source(), flags=re.S)
    return re.sub(r"//[^\n]*", "", body)


def test_the_unit_strategy_is_read_from_the_config_and_not_asserted() -> None:
    """It said "grid, 100 m" for every run, whatever `units.strategy` was.

    The string predates `UnitsConfig` — Phase 17 made the strategy configurable and the front end
    went on describing every map as a 100 m grid, so a patch-units run would have misdescribed
    itself on its own page. The producer answers this; the consumer must ask.
    """
    code = about_code()

    assert "config.units" in code
    assert "strategy" in code
    assert not re.search(r'"grid,\s*100\s*m"', code), "the hardcoded description is back"


def test_the_extent_row_reads_the_manifest_field(tmp_path: Path) -> None:
    """`extent` is a top-level manifest field, not a config one, because it is derived from the
    bbox and appears in no `Settings`."""
    body = about_source()

    assert "manifest.extent" in body
    assert "area_km2" in body


def test_a_run_without_an_extent_omits_the_row_rather_than_guessing() -> None:
    """Every manifest written before the field existed has no extent, and a site rebuilt from one
    must not invent a place name for it."""
    body = about_source()

    assert re.search(r"if\s*\(extent\)", body), "the extent row is not guarded"


def test_the_manifest_keys_the_about_block_reads_are_ones_the_writer_emits() -> None:
    """The producer side, checked against the model rather than against a fixture.

    `tests/test_viz_app_js.py` does this for the keys `style.py` emits into `style.json`; these
    come from the manifest itself, which the site copies in whole, so they need the same check.
    """
    from lczkit.output.manifest import RunManifest

    body = about_source()
    fields = set(RunManifest.model_fields)

    for key in ("extent", "config"):
        assert key in fields, f"app.js reads manifest.{key}, which RunManifest does not emit"
        assert f"manifest.{key}" in body or "config" in body


def test_the_extent_fields_the_about_block_reads_exist_on_the_record() -> None:
    from lczkit.output.extent import ExtentRecord

    body = about_source()
    fields = set(ExtentRecord.model_fields)

    for key in ("name", "iso", "area_km2"):
        assert key in fields, f"app.js reads extent.{key}, which ExtentRecord does not carry"
        assert f"extent.{key}" in body
