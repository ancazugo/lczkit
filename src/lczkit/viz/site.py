"""`build_site(run_dir)` — a self-contained, archivable map of one run.

The deliverable is a directory that a reader can copy, open with a Python interpreter and nothing
else, and still read in ten years: no CDN, no basemap API key, no live kernel, no build step. It is
a paper supplement, not a dev tool.

**It is a pure transform of run outputs.** Every number it draws — labels, parameters, the 17-way
distance vector, the classification breaks the choropleths bin on — was decided by the run and read
back from `units.parquet`, `units_viz.parquet` and `manifest.json`. Nothing here computes a
parameter or a quantile, and nothing here reads `input/`. That is why `write_run` gained a `layers=`
argument: the basemap and the extrusions are drawn from geometry the *run* persisted, so an archived
run directory rebuilds its own site with no access to the source data.

**The one thing that is measured rather than assumed** is the attribute split. MVT repeats a
feature's whole attribute table in every tile at every zoom, so at metropolitan scale a 38-column
unit table costs more to tile than 892 000 building footprints — 115 MB against 61 MB. The render
attributes therefore ride at every zoom and the rest ride once, at the maximum zoom, where the only
thing that reads them is a click. Both tilesets and the choice between them are recorded in
`site.json`.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from lczkit.classify.classifier import DISTANCE_COLUMNS
from lczkit.config import VizConfig
from lczkit.output.writer import LAYERS_DIR, MANIFEST_FILE, UNITS_FILE, VIZ_FILE
from lczkit.viz import style as style_module
from lczkit.viz.tiles import TilesetReport, build_tileset, copy_tree

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
"""The vendored front end, shipped inside the wheel.

This is the one place in the package that resolves a path from `__file__`, and it is not the case
CLAUDE.md's rule is about: that rule forbids locating *data* relative to the source tree, because
data lives under `DATA_DIR`. These are package resources — JavaScript and HTML that ship in the
wheel — and there is no other way to find a file inside an installed package.
"""

SITE_DIR = "site"
SITE_REPORT = "site.json"

BASEMAP_LAYERS = ("land_use", "water", "streets")
"""Context layers drawn under the units, in draw order.

**Tiled as geometry alone.** They are painted flat, carry no labels, and answer no click, so every
attribute on them is dead weight — and it is not small dead weight: Overture's `id` is a
32-character GERS string, repeated once per feature per zoom level. Stripping the columns took a
9 km² basemap from 6.43 MB to 4.00 MB, for pixels that look identical.
"""


@dataclass(frozen=True)
class SiteReport:
    """What `build_site` wrote, and how."""

    site_dir: Path
    tilesets: list[TilesetReport] = field(default_factory=list)
    n_units: int = 0
    render_columns: list[str] = field(default_factory=list)
    detail_columns: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    """Anything the site could not draw, and why — an absent layer, a detail tileset declined for
    size. Recorded rather than silently omitted, so a missing basemap is distinguishable from a
    basemap that failed."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "site_dir": str(self.site_dir),
            "n_units": self.n_units,
            "render_columns": self.render_columns,
            "detail_columns": self.detail_columns,
            "skipped": self.skipped,
            "tilesets": [tileset.as_detail() for tileset in self.tilesets],
            "total_bytes": sum(tileset.size_bytes for tileset in self.tilesets),
        }


def build_site(run_dir: Path | str, *, config: VizConfig | None = None) -> SiteReport:
    """Write `<run_dir>/site/` from the run's own outputs, returning what was built.

    `config` defaults to the `viz` section recorded in the run's manifest, so rebuilding a site from
    an archived run reproduces the same tilesets without the caller having to restate the settings.
    """
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
    if config is None:
        config = VizConfig.model_validate(manifest.get("config", {}).get("viz", {}))

    units = gpd.read_parquet(run_dir / UNITS_FILE, columns=["geometry"])
    attributes = pd.read_parquet(run_dir / VIZ_FILE)
    table = gpd.GeoDataFrame(
        attributes.join(units[["geometry"]], how="inner"), geometry="geometry", crs=units.crs
    )
    table = table.reset_index().rename(columns={table.index.name or "index": "unit_id"})

    site_dir = run_dir / SITE_DIR
    tiles_dir = site_dir / "tiles"
    site_dir.mkdir(parents=True, exist_ok=True)
    tiles_dir.mkdir(parents=True, exist_ok=True)

    skipped: dict[str, str] = {}
    tilesets: list[TilesetReport] = []

    render_columns = _render_columns(list(table.columns), config)
    missing = sorted(set(config.render_columns) - set(render_columns))
    if missing:
        skipped["render_columns"] = f"not produced by this run: {', '.join(missing)}"

    tilesets.append(
        build_tileset(
            {"units": table[["unit_id", *render_columns, "geometry"]]},
            tiles_dir / "units.pmtiles",
            name="units",
            min_zoom=config.unit_min_zoom,
            max_zoom=config.unit_max_zoom,
        )
    )

    detail_columns = [
        column for column in table.columns if column not in {*render_columns, "unit_id", "geometry"}
    ]
    has_detail = bool(detail_columns) and len(table) <= config.detail_max_features
    if detail_columns and not has_detail:
        skipped["units_detail"] = (
            f"{len(table)} units exceeds detail_max_features={config.detail_max_features}; "
            "the sidebar falls back to the render attributes"
        )
    if has_detail:
        tilesets.append(
            build_tileset(
                {"units_detail": table[["unit_id", *detail_columns, "geometry"]]},
                tiles_dir / "units_detail.pmtiles",
                name="units_detail",
                min_zoom=config.unit_max_zoom,
                max_zoom=config.unit_max_zoom,
                # A dropped feature here is a unit whose sidebar silently comes up empty, which is
                # worse than a large tile — this tileset is only ever read one feature at a time.
                drop_densest=False,
            )
        )

    wanted = tuple(name for name in BASEMAP_LAYERS if name in config.basemap_layers)
    basemap = {name: frame[["geometry"]] for name, frame in _read_layers(run_dir, wanted).items()}
    if basemap:
        tilesets.append(
            build_tileset(
                basemap,
                tiles_dir / "basemap.pmtiles",
                name="basemap",
                min_zoom=config.basemap_min_zoom,
                max_zoom=config.basemap_max_zoom,
                simplification=config.basemap_simplification,
            )
        )
    else:
        skipped["basemap"] = (
            f"none of {', '.join(wanted) or 'the configured layers'} was persisted by this run; "
            "pass layers= to write_run to draw a basemap"
        )

    has_buildings = False
    if config.include_buildings:
        buildings = _read_layers(run_dir, ("buildings",))
        if buildings:
            tilesets.append(
                build_tileset(
                    {"buildings": _building_columns(buildings["buildings"])},
                    tiles_dir / "buildings.pmtiles",
                    name="buildings",
                    min_zoom=config.building_min_zoom,
                    max_zoom=config.building_max_zoom,
                )
            )
            has_buildings = True
        else:
            skipped["buildings"] = (
                "include_buildings is set but the run persisted no building layer"
            )

    bounds = table.to_crs(4326).total_bounds
    style = style_module.build_style(
        manifest,
        columns=["unit_id", *render_columns],
        bounds=(float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3])),
        centre=(float((bounds[0] + bounds[2]) / 2), float((bounds[1] + bounds[3]) / 2)),
        has_detail=has_detail,
        basemap_layers=tuple(basemap),
        has_buildings=has_buildings,
        online_basemap=config.online_basemap,
    )

    # `index.html` sits at the root because that is where a browser looks; everything it pulls in
    # lives under `assets/`, so the directory says at a glance what is page and what is machinery.
    copy_tree(ASSETS_DIR / "vendor", site_dir / "assets" / "vendor")
    shutil.copy2(ASSETS_DIR / "index.html", site_dir / "index.html")
    for name in ("app.js", "app.css", "LICENSES.md"):
        shutil.copy2(ASSETS_DIR / name, site_dir / "assets" / name)
    shutil.copy2(Path(__file__).resolve().parent / "serve.py", site_dir / "serve.py")
    # At the root beside `serve.py`, not under `assets/`: it is addressed to whoever receives the
    # directory, and the one thing they need to know is that opening `index.html` will not work.
    shutil.copy2(ASSETS_DIR / "README.md", site_dir / "README.md")
    shutil.copy2(run_dir / MANIFEST_FILE, site_dir / MANIFEST_FILE)
    (site_dir / "style.json").write_text(json.dumps(style, indent=2) + "\n", encoding="utf-8")

    report = SiteReport(
        site_dir=site_dir,
        tilesets=tilesets,
        n_units=len(table),
        render_columns=render_columns,
        detail_columns=detail_columns if has_detail else [],
        skipped=skipped,
    )
    (site_dir / SITE_REPORT).write_text(
        json.dumps(report.as_dict(), indent=2) + "\n", encoding="utf-8"
    )
    return report


def _render_columns(columns: list[str], config: VizConfig) -> list[str]:
    """The attributes to carry at every zoom: those `config` names, plus those it names by prefix.

    The prefix half exists for the height tier fractions, whose column names depend on which cascade
    the run chose — see `VizConfig.render_column_prefixes`. Prefix matches follow the literal names
    and keep the table's own column order, so the set is stable for a given run rather than
    depending on how the config happened to be written.

    A column matched both ways appears once: the two halves of the config are allowed to overlap,
    and a duplicated column would be tiled twice.
    """
    named = [column for column in config.render_columns if column in columns]
    chosen = dict.fromkeys(named)
    for column in columns:
        if column in chosen:
            continue
        if any(column.startswith(prefix) for prefix in config.render_column_prefixes):
            chosen[column] = None
    return list(chosen)


def _read_layers(run_dir: Path, names: tuple[str, ...]) -> dict[str, gpd.GeoDataFrame]:
    """Whichever of `names` the run persisted under `layers/`, in order."""
    found: dict[str, gpd.GeoDataFrame] = {}
    for name in names:
        path = run_dir / LAYERS_DIR / f"{name}.parquet"
        if path.is_file():
            found[name] = gpd.read_parquet(path)
    return found


def _building_columns(buildings: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Only what the extrusion draws: geometry, height, and where the height came from.

    Carrying the rest would multiply the largest tileset in the site by the width of the building
    table, for attributes no view reads.
    """
    wanted = [
        column for column in ("height", "height_source", "height_confidence") if column in buildings
    ]
    return buildings[[*wanted, "geometry"]]


def distance_columns_present(columns: list[str]) -> list[str]:
    """The 17-way distance columns among `columns`, in prototype order.

    Exposed so the sidebar's bar chart and the tests agree on the ordering without either
    re-deriving it from a column name pattern.
    """
    return [column for column in DISTANCE_COLUMNS if column in columns]
