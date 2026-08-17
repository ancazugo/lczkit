"""Copy the demonstration runs' map sites into `docs_src/demo/`, or refuse to.

This is the one place anything writes a run artefact *inside* the repository, and it is a script
rather than a notebook cell for that reason: CLAUDE.md keeps the pipeline's outputs under
`DATA_DIR`, so the copy that crosses that line should be one reviewable, testable step.

Three things it checks before writing, each of which has cost this project something before:

- **A directory named `site` is unpublishable.** `.gitignore` carries `site/` for mkdocs' build
  output and that pattern matches at *any* depth, so copying `<run>/site/` across under its own
  name would produce a directory git silently ignores and `mkdocs gh-deploy` never publishes.
  The destination names are fixed here and asserted not to be `site`.
- **A site that reaches the network must not ship.** A run can opt into an online basemap, and the
  Bogotá run already on disk did — its `style.json` names `tile.openstreetmap.org`. Publishing
  that would put OpenStreetMap's donated tile server behind a documentation page for every reader.
  The same opt-in can substitute a MapTiler API key into `style.json` in plain text.
- **Bytes are permanent.** These files go into git history, where the repository's largest
  committed file is currently 1.4 MB. A budget that fails loudly beats a repository that grows
  quietly.

Usage:

    python scripts/publish_demo_sites.py [--budget-mb 12] [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEMO_DIR = REPO / "docs_src" / "demo"

SITES: dict[str, str] = {
    # destination under docs_src/demo/  ->  run_id under $DATA_DIR/output/lczkit/
    "bogota-grid": "docs-bogota-grid",
    "bogota-patch": "docs-bogota-patch",
}

DEFAULT_BUDGET_MB = 12.0
"""Ceiling on the whole published pair, in megabytes.

Not a guess at what is reasonable — it is roughly twice what the 5 km window measures, so an
accidental rebuild at a metropolitan extent (the full Bogotá site is 28 MB on its own) fails here
instead of in a commit. Raise it deliberately, with the new measurement in the message.
"""

_REMOTE = re.compile(r"https?://[^\s\"'`)]*")
_LOOPBACK = ("http://{", "http://127.0.0.1", "http://localhost")


def _run_root() -> Path:
    """Where runs are written, from `DATA_DIR` — the only environment read outside the config."""
    raw = os.environ.get("DATA_DIR")
    if not raw:
        for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("DATA_DIR"):
                raw = line.split("=", 1)[1].strip().strip("\"'")
                break
    if not raw:
        raise SystemExit("DATA_DIR is unset and no .env defines it")
    return Path(raw) / "output" / "lczkit"


def remote_references(site: Path) -> list[str]:
    """Every reference in `site` that would reach a host, as `path: url` strings.

    Scoped the same way `tests/test_viz_site.py` scopes it, and for the same reason: the bare
    string `http` appears legitimately inside the vendored MapLibre bundle as licence text, as
    documentation links in error messages, and as the SVG XML namespace. What the page actually
    *requests* is decided by `index.html`'s resource attributes, `url()` in the stylesheets, and
    the absolute URLs in the authored files.
    """
    findings: list[str] = []

    html = site / "index.html"
    for attribute in re.findall(r'(?:src|href)="([^"]+)"', html.read_text(encoding="utf-8")):
        if attribute.startswith(("http://", "https://", "//")):
            findings.append(f"index.html: {attribute}")

    for stylesheet in sorted(site.rglob("*.css")):
        for target in re.findall(r"url\(([^)]+)\)", stylesheet.read_text(encoding="utf-8")):
            target = target.strip("\"'")
            if target.startswith(("http://", "https://", "//")) and not target.startswith("data:"):
                findings.append(f"{stylesheet.relative_to(site)}: {target}")

    for name in ("assets/app.js", "style.json", "serve.py"):
        path = site / name
        if not path.is_file():
            continue
        for url in _REMOTE.findall(path.read_text(encoding="utf-8")):
            # serve.py prints the loopback address it bound, which reaches nothing.
            if not url.startswith(_LOOPBACK):
                findings.append(f"{name}: {url}")

    return findings


def leaked_secrets(site: Path) -> list[str]:
    """Any value from `.env` that appears in a file about to be published.

    `VizConfig.maptiler_key` is `exclude=True` so it never reaches a manifest, but the browser
    fetches tiles directly and a keyed provider therefore puts the key into `style.json` in plain
    text. This looks for the credential itself rather than for the field that carries it.
    """
    env = REPO / ".env"
    if not env.is_file():
        return []
    secrets = []
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip("\"'").strip()
        if len(value) >= 12 and ("KEY" in key.upper() or "TOKEN" in key.upper()):
            secrets.append((key.strip(), value))

    findings = []
    for path in sorted(p for p in site.rglob("*") if p.is_file()):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, value in secrets:
            if value in text:
                findings.append(f"{path.relative_to(site)}: {name}")
    return findings


ARCHIVE_ONLY = ("README.md", "serve.py")
"""Files a built site carries for a reader who *downloads* it, dropped from the published copy.

Both document and implement opening the site offline — `serve.py` is the standard-library server
that answers Range requests, and `README.md` explains that `file://` cannot work. Neither applies
to a copy already being served by GitHub Pages, and each breaks the docs build in its own way:

- `README.md` sits beside the site's `index.html`, and mkdocs refuses that pair — "Excluding
  'demo/<site>/README.md' because it conflicts with 'demo/<site>/index.html'", which `strict: true`
  turns into a failed build.
- `serve.py` is matched by mkdocs-jupyter's default `include`, so the plugin treats it as a
  notebook, renders it as a page, and *relocates* it to `demo/<site>/serve/serve.py`.

The run directory keeps both. This drops them only from the copy that is embedded.
"""


def directory_bytes(path: Path) -> int:
    """Total size of every file under `path`."""
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def main() -> int:
    """Copy each configured run's site into `docs_src/demo/`, checking before it writes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget-mb", type=float, default=DEFAULT_BUDGET_MB)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = _run_root()
    staged: list[tuple[str, Path]] = []

    for destination, run_id in SITES.items():
        assert destination != "site", "'site' is gitignored at any depth"
        site = root / run_id / "site"
        if not site.is_dir():
            print(f"missing: {site}\n  run the notebook first (scripts/notebooks/bogota.py)")
            return 1

        remote = remote_references(site)
        if remote:
            print(f"REFUSED {run_id}: the built site reaches the network")
            for finding in remote:
                print(f"  {finding}")
            print("  rebuild it keyless:  lczkit site build <run_dir> --basemap none")
            return 1

        leaked = leaked_secrets(site)
        if leaked:
            print(f"REFUSED {run_id}: a credential from .env appears in the built site")
            for finding in leaked:
                print(f"  {finding}")
            return 1

        staged.append((destination, site))
        megabytes = directory_bytes(site) / 1e6
        print(f"ok  {run_id:20s} {megabytes:6.2f} MB  -> docs_src/demo/{destination}/")

    total = sum(directory_bytes(site) for _, site in staged)
    print(f"\ntotal {total / 1e6:.2f} MB against a {args.budget_mb:.1f} MB budget")
    if total / 1e6 > args.budget_mb:
        print("REFUSED: over budget. Rebuild at a smaller window, or raise --budget-mb knowingly.")
        return 1

    if args.dry_run:
        print("dry run — nothing written")
        return 0

    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    for destination, site in staged:
        target = DEMO_DIR / destination
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(site, target)
        for name in ARCHIVE_ONLY:
            (target / name).unlink(missing_ok=True)
        print(f"wrote docs_src/demo/{destination}/  ({directory_bytes(target) / 1e6:.2f} MB)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
