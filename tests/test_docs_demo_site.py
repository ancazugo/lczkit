"""The demonstration notebook's embedded maps are publishable, and reach nothing.

`docs_src/demo/` is the one place a run's output is committed to the repository, and it is
published to GitHub Pages verbatim. Three properties have to hold, none of which is visible in a
rendered page:

- **The iframes resolve.** A notebook is committed with its outputs, so a broken `src` is a
  permanently broken map rather than a build error — mkdocs does not validate raw HTML inside
  notebook output.
- **Nothing reaches a host.** A run can opt into an online basemap, and one already on disk did.
  Publishing that would put OpenStreetMap's donated tile server behind a docs page for every
  reader, and a keyed provider would put a MapTiler credential into a public repository in plain
  text. This is `test_viz_site.py`'s guarantee, re-pointed at what actually ships.
- **The bytes stay bounded.** The repository's largest committed file is otherwise 1.4 MB. A
  rebuild at a larger extent must fail here rather than quietly enter git history.

Each test skips rather than fails when the directory is absent: the sites are produced by
executing the notebook against real data, which CI cannot do.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DEMO_DIR = REPO / "docs_src" / "demo"
NOTEBOOK = DEMO_DIR / "bogota.ipynb"

BUDGET_BYTES = 12_000_000
"""Ceiling on everything committed under `docs_src/demo/`.

Roughly twice what the 5 km demonstration window measures, so an accidental rebuild at a
metropolitan extent — the full Bogotá site is 28 MB on its own — fails here. `scripts/
publish_demo_sites.py` applies the same ceiling before it writes.
"""

_SITES = ("bogota-grid", "bogota-patch")
_REMOTE = re.compile(r"https?://[^\s\"'`)]*")
_LOOPBACK = ("http://{", "http://127.0.0.1", "http://localhost")


def _site_dirs() -> list[Path]:
    present = [DEMO_DIR / name for name in _SITES if (DEMO_DIR / name).is_dir()]
    if not present:
        pytest.skip("docs_src/demo/ holds no built site; run scripts/publish_demo_sites.py")
    return present


def test_no_demo_directory_is_named_site() -> None:
    """`.gitignore` carries `site/` for mkdocs' output, and that pattern matches at any depth.

    A run's site copied across under its own name would be silently ignored by git and never
    published — the map would simply be missing, with nothing raising anywhere.
    """
    if not DEMO_DIR.is_dir():
        pytest.skip("docs_src/demo/ does not exist yet")
    offenders = [path for path in DEMO_DIR.rglob("*") if path.is_dir() and path.name == "site"]
    assert offenders == [], offenders


def test_every_iframe_in_the_notebook_resolves() -> None:
    """A committed notebook's outputs are frozen, so a wrong `src` is a permanently blank map."""
    if not NOTEBOOK.is_file():
        pytest.skip("the demonstration notebook has not been executed yet")
    document = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    sources = [
        source
        for cell in document["cells"]
        for source in re.findall(r'<iframe[^>]*\ssrc="([^"]+)"', "".join(cell["source"]))
    ]
    assert sources, "the notebook embeds no map at all"
    for source in sources:
        # The notebook page renders at demo/bogota/, one level below demo/, so `../x/` is demo/x/.
        assert source.startswith("../"), source
        target = DEMO_DIR / source.removeprefix("../")
        assert target.is_file(), f"{source} -> {target} does not exist"


def test_no_published_map_reaches_a_host() -> None:
    """Scoped to resource references, as `test_viz_site.py` scopes it.

    The bare string `http` appears legitimately inside the vendored MapLibre bundle as licence
    text, as documentation links in error messages and as the SVG XML namespace. What the page
    actually requests is decided by `index.html`'s resource attributes, `url()` in the
    stylesheets, and the absolute URLs in the authored files.
    """
    for site in _site_dirs():
        html = (site / "index.html").read_text(encoding="utf-8")
        for attribute in re.findall(r'(?:src|href)="([^"]+)"', html):
            assert not attribute.startswith(("http://", "https://", "//")), (
                f"{site.name}: {attribute}"
            )

        for stylesheet in sorted(site.rglob("*.css")):
            for target in re.findall(r"url\(([^)]+)\)", stylesheet.read_text(encoding="utf-8")):
                target = target.strip("\"'")
                assert target.startswith("data:") or not target.startswith(
                    ("http://", "https://", "//")
                ), f"{site.name}/{stylesheet.name}: {target[:80]}"

        for name in ("assets/app.js", "style.json", "serve.py"):
            path = site / name
            if not path.is_file():
                continue
            remote = [
                url
                for url in _REMOTE.findall(path.read_text(encoding="utf-8"))
                if not url.startswith(_LOOPBACK)
            ]
            assert remote == [], f"{site.name}/{name}: {remote}"


def test_no_credential_from_the_environment_is_published() -> None:
    """`VizConfig.maptiler_key` never reaches a manifest, but a keyed basemap reaches `style.json`.

    The browser fetches tiles itself, so an opted-in MapTiler ground puts the key into the built
    style in plain text. This looks for the credential rather than for the field carrying it.
    """
    env = REPO / ".env"
    if not env.is_file():
        pytest.skip("no .env on this machine to check against")
    secrets = []
    for line in env.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        value = value.strip().strip("\"'").strip()
        if "=" in line and len(value) >= 12 and ("KEY" in key.upper() or "TOKEN" in key.upper()):
            secrets.append((key.strip(), value))
    if not secrets:
        pytest.skip(".env defines no credential to look for")

    for site in _site_dirs():
        for path in sorted(p for p in site.rglob("*") if p.is_file()):
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for name, value in secrets:
                assert value not in text, f"{path.relative_to(DEMO_DIR)} carries {name}"


def test_each_published_map_is_complete() -> None:
    """A site missing its style or its tiles renders as a blank page with no error."""
    for site in _site_dirs():
        for required in ("index.html", "style.json", "manifest.json", "assets/app.js"):
            assert (site / required).is_file(), f"{site.name}: {required} missing"
        assert list((site / "tiles").glob("*.pmtiles")), f"{site.name}: no tileset"


def test_the_published_copies_drop_what_only_a_download_needs() -> None:
    """`README.md` and `serve.py` each break the docs build, in different ways.

    `README.md` sits beside the site's own `index.html`, and mkdocs refuses that pair — it drops
    the file and warns, which `strict: true` turns into a failed build. `serve.py` is matched by
    mkdocs-jupyter's default `include`, which treats it as a notebook, renders it as a page and
    moves it to `<site>/serve/serve.py`.

    Both are correct to ship in a run directory, which is a copy someone downloads and opens
    offline. Neither applies to one already being served, so `scripts/publish_demo_sites.py`
    strips them — and the run directory keeps them.
    """
    for site in _site_dirs():
        for name in ("README.md", "serve.py"):
            assert not (site / name).exists(), (
                f"{site.name}/{name} would break `mkdocs build --strict`; "
                "re-run scripts/publish_demo_sites.py"
            )


def test_the_notebook_still_matches_its_reviewable_source() -> None:
    """`scripts/notebooks/bogota.py` is the source; the committed `.ipynb` carries its outputs.

    Two files holding the same content is the shape this project has been bitten by twice — two
    `CLEANING` constants, two city registries — and the fix each time was an assertion rather than
    a convention. Here the risk is one-directional and easy to hit: editing the notebook in a
    kernel leaves the percent script behind, and the script is the only half a reviewer can read.
    """
    source = REPO / "scripts" / "notebooks" / "bogota.py"
    if not (NOTEBOOK.is_file() and source.is_file()):
        pytest.skip("the demonstration notebook has not been executed yet")
    jupytext = pytest.importorskip("jupytext")

    def cells(path: Path) -> list[tuple[str, str]]:
        document = jupytext.read(path)
        return [
            (cell["cell_type"], cell["source"].strip())
            for cell in document["cells"]
            if cell["source"].strip()
        ]

    assert cells(NOTEBOOK) == cells(source), (
        "docs_src/demo/bogota.ipynb and scripts/notebooks/bogota.py have diverged; "
        "re-run `jupytext --to ipynb --set-kernel python3 --execute` to regenerate the notebook"
    )


def test_the_published_maps_stay_within_budget() -> None:
    """Bytes committed here are permanent, and a larger window is a silent way to add many."""
    if not DEMO_DIR.is_dir():
        pytest.skip("docs_src/demo/ does not exist yet")
    total = sum(path.stat().st_size for path in DEMO_DIR.rglob("*") if path.is_file())
    assert total <= BUDGET_BYTES, (
        f"docs_src/demo/ is {total / 1e6:.1f} MB against a {BUDGET_BYTES / 1e6:.0f} MB budget; "
        "rebuild at a smaller window, or raise the budget with the new measurement recorded"
    )
