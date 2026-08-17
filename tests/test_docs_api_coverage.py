"""The API reference names every module in the package, and the docs_dir holds nothing ignored.

Two guarantees, both of the kind that decay silently. A new module joins the package and never
reaches the reference, because nothing looked; or a file lands in `docs_dir` that `.gitignore`
covers, and `mkdocs gh-deploy` publishes it. Neither is visible in a rendered site.

The second is the reason `docs_dir` is `docs_src/` and not `docs/`: that directory holds 205 MB
of gitignored PDFs and datasets alongside the committed write-ups, and a `docs_dir` that cannot
contain one is a stronger guarantee than an `exclude_docs` rule that has to stay correct.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "src" / "lczkit"
DOCS_SRC = REPO / "docs_src"
API_DIR = DOCS_SRC / "api"

_DIRECTIVE = re.compile(r"^:::\s+(lczkit[\w.]*)\s*$", re.MULTILINE)


def _documented() -> set[str]:
    """Every dotted path named by a `:::` directive anywhere under `docs_src/api/`."""
    return {
        match
        for page in API_DIR.rglob("*.md")
        for match in _DIRECTIVE.findall(page.read_text(encoding="utf-8"))
    }


def _modules() -> set[str]:
    """Every importable dotted path in the package, minus private modules.

    `__init__.py` maps to its package, which is what a `::: lczkit.units` directive documents.
    Modules whose own name starts with an underscore are internal (`cli/_options.py`,
    `cli/_render.py`) and are not part of the published surface.
    """
    names: set[str] = set()
    for path in PACKAGE.rglob("*.py"):
        parts = path.relative_to(PACKAGE.parent).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if any(part.startswith("_") for part in parts):
            continue
        names.add(".".join(parts))
    return names


def test_every_public_module_reaches_the_api_reference() -> None:
    missing = sorted(_modules() - _documented())
    assert not missing, (
        "these modules are in the package and in no API page, so they are absent from the "
        f"published reference: {missing}"
    )


def test_the_api_reference_names_no_module_that_does_not_exist() -> None:
    # A renamed or deleted module leaves a `:::` directive that mkdocstrings cannot resolve.
    # Under `strict: true` that fails the build, but only once someone runs it.
    unknown = sorted(_documented() - _modules())
    assert not unknown, f"these API pages document a module that is not in the package: {unknown}"


def test_the_docs_directory_holds_nothing_git_ignores() -> None:
    files = sorted(path for path in DOCS_SRC.rglob("*") if path.is_file())
    assert files, "docs_src/ is empty; the site would build to nothing"
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", *(str(path) for path in files)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    # `git check-ignore` exits 1 when it matches nothing, which is the passing case here.
    if result.returncode not in (0, 1):  # pragma: no cover - git absent or repo unreadable
        pytest.skip(f"git check-ignore unavailable: {result.stderr.strip()}")
    ignored = [line for line in result.stdout.splitlines() if line]
    assert not ignored, (
        "these files sit in the mkdocs docs_dir and are gitignored, so a local `mkdocs "
        f"gh-deploy` would publish what the repository deliberately does not ship: {ignored}"
    )


def test_the_nav_lists_every_api_page() -> None:
    # A page that exists and is not in `nav` is unreachable in the built site, and `strict: true`
    # reports it as an omitted file rather than silently dropping it.
    config = (REPO / "mkdocs.yml").read_text(encoding="utf-8")
    for page in sorted(API_DIR.rglob("*.md")):
        relative = page.relative_to(DOCS_SRC).as_posix()
        assert f": {relative}" in config, f"{relative} exists but is not in mkdocs.yml's nav"
