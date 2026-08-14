"""`build_site`: the directory it writes, and the guarantees that directory has to keep.

Two of these assertions are the phase's acceptance criteria rather than ordinary unit tests:

- **nothing the site loads is external.** CLAUDE.md forbids a CDN link, an inlined data blob in
  `index.html`, and a basemap needing an API key, so that the directory still renders years from
  now. That is checkable by walking the emitted files rather than by trusting a docstring.
- **the site is a pure transform of run outputs.** Every file it reads is one the run wrote, and the
  manifest it ships is byte-identical to the run's.

Tile generation needs `lczkit[viz]`; those tests skip cleanly without it rather than failing, so a
checkout without the extra still runs green.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from shapely.geometry import LineString, box

from lczkit.classify import PrototypeClassifier
from lczkit.config import Settings, VizConfig
from lczkit.output import write_run
from lczkit.viz import build_site
from lczkit.viz.site import _render_columns
from lczkit.viz.style import NODATA_COLOUR
from lczkit.viz.tiles import TIPPECANOE_EXTRA, TippecanoeMissingError, tippecanoe_available

pytestmark = pytest.mark.skipif(
    not tippecanoe_available(), reason=f"needs the viz extra: pip install '{TIPPECANOE_EXTRA}'"
)

CRS = "EPSG:32633"
ORIGIN = (390_000.0, 5_818_000.0)  # a plausible UTM 33N origin near Berlin, so lon/lat is sane


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    (tmp_path / "input").mkdir()
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return Settings.load(run_id="site-run", dotenv_path=tmp_path / "absent.env")


def make_units(n: int = 24) -> gpd.GeoDataFrame:
    east, north = ORIGIN
    return gpd.GeoDataFrame(
        {"unit_id": [f"grid_{index:03d}" for index in range(n)]},
        geometry=[
            box(
                east + (index % 6) * 100.0,
                north + (index // 6) * 100.0,
                east + (index % 6) * 100.0 + 100.0,
                north + (index // 6) * 100.0 + 100.0,
            )
            for index in range(n)
        ],
        crs=CRS,
    ).set_index("unit_id")


def make_parameters(units: gpd.GeoDataFrame) -> pd.DataFrame:
    n = len(units)
    aspect = np.linspace(0.1, 1.6, n)
    aspect[:3] = np.nan  # units no street reaches: the null-parameter case, deliberately present
    return pd.DataFrame(
        {
            "building_surface_fraction": np.linspace(0.0, 0.7, n),
            "impervious_surface_fraction": np.linspace(0.05, 0.4, n),
            "pervious_surface_fraction": np.linspace(0.95, 0.0, n),
            "tree_fraction": np.linspace(0.7, 0.0, n),
            "water_fraction": np.zeros(n),
            "height_of_roughness_elements_m": np.linspace(3.0, 28.0, n),
            "aspect_ratio": aspect,
            "industrial_fraction_of_building_area": np.zeros(n),
            "industrial_fraction_of_unit_area": np.zeros(n),
            "industrial_fraction": np.zeros(n),
            "mean_building_area_m2": np.linspace(120.0, 9000.0, n),
        },
        index=units.index,
    )


def make_layers() -> dict[str, gpd.GeoDataFrame]:
    east, north = ORIGIN
    return {
        "streets": gpd.GeoDataFrame(
            {"road_class": ["primary", "residential"]},
            geometry=[
                LineString([(east, north), (east + 600.0, north + 400.0)]),
                LineString([(east + 100.0, north + 300.0), (east + 500.0, north)]),
            ],
            crs=CRS,
        ),
        "water": gpd.GeoDataFrame(
            {"subtype": ["river"]},
            geometry=[box(east + 200.0, north + 100.0, east + 260.0, north + 380.0)],
            crs=CRS,
        ),
        "buildings": gpd.GeoDataFrame(
            {
                "height": [12.5, 31.0, 6.0],
                "height_source": ["overture", "ghsl", "overture"],
                "height_confidence": [1.0, 0.3, 1.0],
            },
            geometry=[
                box(
                    east + 10.0 + index * 120.0,
                    north + 10.0,
                    east + 50.0 + index * 120.0,
                    north + 60.0,
                )
                for index in range(3)
            ],
            crs=CRS,
        ),
    }


@pytest.fixture
def run_dir(settings: Settings) -> Path:
    units = make_units()
    parameters = make_parameters(units)
    classifier = PrototypeClassifier()
    outputs = write_run(
        settings,
        units,
        parameters,
        classifier.classify(parameters),
        classifier,
        layers=make_layers(),
    )
    return outputs.run_dir


def test_the_site_directory_holds_what_claude_md_specifies(run_dir: Path) -> None:
    report = build_site(run_dir, config=VizConfig(include_buildings=True))

    site = run_dir / "site"
    assert (site / "index.html").is_file()
    assert (site / "style.json").is_file()
    assert (site / "manifest.json").is_file()
    assert (site / "serve.py").is_file()
    assert (site / "README.md").is_file()
    assert (site / "assets" / "vendor" / "maplibre-gl.js").is_file()
    assert (site / "assets" / "vendor" / "pmtiles.js").is_file()
    assert (site / "assets" / "app.js").is_file()

    tiles = {path.name for path in (site / "tiles").glob("*.pmtiles")}
    assert tiles == {
        "units.pmtiles",
        "units_detail.pmtiles",
        "basemap.pmtiles",
        "buildings.pmtiles",
    }
    assert report.site_dir == site
    assert report.n_units == 24


def test_the_readme_gives_the_command_that_works_and_not_the_one_that_does_not(
    run_dir: Path,
) -> None:
    """The site is handed to people as a directory, and the first thing they will try is opening
    `index.html`. That fails with a network error and no explanation, so the README has to lead
    with the working command — this is the one instruction the directory cannot do without."""
    build_site(run_dir)
    readme = (run_dir / "site" / "README.md").read_text(encoding="utf-8")

    assert "python serve.py" in readme
    assert "http://127.0.0.1:8000/" in readme
    assert "will not work" in readme, "the README must say that opening index.html directly fails"


def test_every_tileset_is_a_real_pmtiles_archive(run_dir: Path) -> None:
    """A tippecanoe that exits zero having written nothing is a failure mode worth excluding."""
    build_site(run_dir)

    for path in (run_dir / "site" / "tiles").glob("*.pmtiles"):
        assert path.stat().st_size > 0
        with path.open("rb") as handle:
            assert handle.read(7) == b"PMTiles", path.name


def test_nothing_the_site_loads_comes_from_outside_the_directory(run_dir: Path) -> None:
    """CLAUDE.md: no CDN link, no basemap API key, no inlined data — the directory must open
    offline and stay valid years from now.

    Scoped to *resource references* rather than to the string "http", which appears legitimately
    inside the vendored bundles as licence text, documentation links in error messages, and the SVG
    XML namespace. What the vendored MapLibre actually requests is decided by the style document,
    and `test_viz_style.py` asserts that names no glyphs, no sprite and only relative sources.
    """
    site = run_dir / "site"
    build_site(run_dir)

    html = (site / "index.html").read_text(encoding="utf-8")
    for attribute in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert not attribute.startswith(("http://", "https://", "//")), attribute

    for stylesheet in site.rglob("*.css"):
        for target in re.findall(r"url\(([^)]+)\)", stylesheet.read_text(encoding="utf-8")):
            target = target.strip("\"'")
            assert target.startswith("data:") or not target.startswith(
                ("http://", "https://", "//")
            ), f"{stylesheet.name}: {target[:80]}"

    for authored in (site / "assets" / "app.js", site / "style.json", site / "serve.py"):
        text = authored.read_text(encoding="utf-8")
        # `serve.py` prints the loopback address it just bound, which is an absolute URL that
        # reaches nothing. Everything with a real host is a finding.
        remote = [
            url
            for url in re.findall(r"https?://[^\s\"'`)]*", text)
            if not url.startswith(("http://{", "http://127.0.0.1", "http://localhost"))
        ]
        assert remote == [], f"{authored.name}: {remote}"


def test_the_manifest_is_the_runs_own_manifest_unchanged(run_dir: Path) -> None:
    """The site reports what the run decided. A manifest edited on the way in would let the page
    and the archival record disagree about the same number."""
    build_site(run_dir)

    assert (run_dir / "site" / "manifest.json").read_bytes() == (
        run_dir / "manifest.json"
    ).read_bytes()


def test_the_style_only_offers_views_the_tiles_can_paint(run_dir: Path) -> None:
    build_site(run_dir)

    style = json.loads((run_dir / "site" / "style.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    carried = set(VizConfig().render_columns)

    for view in style["metadata"]["lczkit"]["views"]:
        assert view["column"] in carried

    published = {entry["column"] for entry in manifest["breaks"] if entry["breaks"]}
    offered = {view["column"] for view in style["metadata"]["lczkit"]["views"]} - {"lcz_primary"}
    assert offered <= published, "a view was offered for a variable the run published no breaks for"


def test_the_detail_tileset_carries_the_distance_vector(run_dir: Path) -> None:
    """The sidebar's bar chart is the one thing the render tileset cannot serve, which is the
    entire reason a second tileset exists."""
    report = build_site(run_dir)

    assert "lcz_d1" in report.detail_columns
    assert "lcz_d17" in report.detail_columns
    assert not set(report.detail_columns) & set(report.render_columns)


def test_a_run_too_large_for_a_detail_tileset_says_so_rather_than_building_one(
    run_dir: Path,
) -> None:
    """The click-detail tileset is the one part of the site whose size is unbounded in extent.
    Declining it is a reported decision, not a silent omission."""
    report = build_site(run_dir, config=VizConfig(detail_max_features=4))

    assert not (run_dir / "site" / "tiles" / "units_detail.pmtiles").exists()
    assert "units_detail" in report.skipped
    assert report.detail_columns == []
    style = json.loads((run_dir / "site" / "style.json").read_text(encoding="utf-8"))
    assert "units_detail" not in style["sources"]


def test_buildings_are_off_by_default_and_the_default_is_the_measured_one(run_dir: Path) -> None:
    """891 994 Berlin footprints tile to tens of megabytes — two to three times the rest of the
    site. The default is off, and a run that does not ask for them does not pay for them."""
    assert VizConfig().include_buildings is False

    report = build_site(run_dir)

    assert not (run_dir / "site" / "tiles" / "buildings.pmtiles").exists()
    assert {tileset.name for tileset in report.tilesets} == {"units", "units_detail", "basemap"}


def test_a_run_with_no_context_layers_still_builds_a_site(settings: Settings) -> None:
    """`layers=` is optional, so a run written before it existed must still produce a map — with
    the missing basemap recorded rather than referenced and broken."""
    units = make_units()
    parameters = make_parameters(units)
    classifier = PrototypeClassifier()
    outputs = write_run(settings, units, parameters, classifier.classify(parameters), classifier)

    report = build_site(outputs.run_dir)

    assert "basemap" in report.skipped
    assert not (outputs.run_dir / "site" / "tiles" / "basemap.pmtiles").exists()
    style = json.loads((outputs.run_dir / "site" / "style.json").read_text(encoding="utf-8"))
    assert set(style["sources"]) == {"units", "units_detail"}


def test_the_tippecanoe_invocation_is_recorded(run_dir: Path) -> None:
    """CLAUDE.md: record the exact tippecanoe invocation in the manifest. Without it a reader
    cannot tell a tile that is empty because the data was empty from one that is empty because
    `--drop-densest-as-needed` threw it away."""
    build_site(run_dir)

    site_report = json.loads((run_dir / "site" / "site.json").read_text(encoding="utf-8"))
    units = next(entry for entry in site_report["tilesets"] if entry["name"] == "units")

    assert units["tippecanoe_version"].startswith("tippecanoe")
    assert "--drop-densest-as-needed" in units["tippecanoe_argv"]
    assert units["min_zoom"] == VizConfig().unit_min_zoom
    assert units["max_zoom"] == VizConfig().unit_max_zoom


def test_the_detail_tileset_does_not_drop_features(run_dir: Path) -> None:
    """A dropped feature here is a unit whose sidebar silently comes up empty. The right failure
    is a large tile, not a missing one, and the two are opposite tippecanoe flags."""
    build_site(run_dir)

    site_report = json.loads((run_dir / "site" / "site.json").read_text(encoding="utf-8"))
    detail = next(entry for entry in site_report["tilesets"] if entry["name"] == "units_detail")

    assert "--drop-densest-as-needed" not in detail["tippecanoe_argv"]
    assert "--no-feature-limit" in detail["tippecanoe_argv"]


def test_build_site_writes_only_inside_the_run_directory(run_dir: Path, settings: Settings) -> None:
    before = {path for path in settings.data_dir.rglob("*") if path.is_file()}

    build_site(run_dir)

    written = {path for path in settings.data_dir.rglob("*") if path.is_file()} - before
    assert written, "the site build wrote nothing"
    assert all(path.is_relative_to(run_dir / "site") for path in written)


def test_the_missing_tippecanoe_message_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """An import error mentioning a module nobody has heard of is a worse answer than a one-line
    install command."""
    import builtins

    real_import = builtins.__import__

    def refuse(name: str, *args: object, **kwargs: object) -> object:
        if name == "tippecanoe":
            raise ModuleNotFoundError("No module named 'tippecanoe'")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", refuse)

    from lczkit.viz.tiles import tippecanoe_binary

    with pytest.raises(TippecanoeMissingError, match=re.escape(TIPPECANOE_EXTRA)):
        tippecanoe_binary()


def test_a_tier_fraction_column_rides_at_every_zoom_rather_than_in_the_detail_tileset() -> None:
    """A selectable layer has to paint while the map is zoomed out, and it has to paint from tiles
    already in memory — a view change that refetched would break the one performance property
    Phase 7 is held to. The tier fractions are named after whichever cascade fired, so they reach
    the render set by prefix rather than by name."""
    columns = ["lcz_primary", "height_completeness", "height_frac_wsf3d", "height_frac_unresolved"]

    chosen = _render_columns(columns, VizConfig())

    assert chosen == columns, "the whole height-provenance family must be in the render set"


def test_the_prefix_half_only_admits_columns_matching_a_configured_prefix() -> None:
    """It is not a licence to sweep in whatever the run happened to produce."""
    columns = ["lcz_primary", "height_completeness", "height_frac_wsf3d"]

    chosen = _render_columns(columns, VizConfig(render_columns=["lcz_primary"]))

    assert chosen == ["lcz_primary", "height_frac_wsf3d"]


def test_the_prefix_half_adds_nothing_when_a_run_produced_no_matching_column() -> None:
    """A run at cascade `none` still has tier fractions; a table without them must not gain a
    phantom column that would tile as nulls."""
    chosen = _render_columns(["lcz_primary", "aspect_ratio"], VizConfig())

    assert chosen == ["lcz_primary", "aspect_ratio"]


def test_a_column_named_both_literally_and_by_prefix_is_carried_once() -> None:
    """The two halves of the config are allowed to overlap; a duplicate would be tiled twice."""
    config = VizConfig(
        render_columns=["height_frac_wsf3d"], render_column_prefixes=["height_frac_"]
    )

    chosen = _render_columns(["height_frac_wsf3d", "height_frac_ghsl"], config)

    assert chosen == ["height_frac_wsf3d", "height_frac_ghsl"]


def test_an_empty_prefix_is_refused_rather_than_matching_every_column() -> None:
    """It would put the whole attribute table at every zoom — the cost the render/detail split was
    measured to avoid."""
    with pytest.raises(ValidationError, match="must not contain an empty string"):
        VizConfig(render_column_prefixes=[""])


def decode_units_tiles(site: Path) -> str:
    """Decode `units.pmtiles` back to JSON with the tippecanoe the package already resolves."""
    from lczkit.viz.tiles import tippecanoe_binary

    decoder = tippecanoe_binary().with_name("tippecanoe-decode")
    return subprocess.run(
        [str(decoder), str(site / "tiles" / "units.pmtiles")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_the_lcz_paint_expression_matches_the_values_actually_in_the_tiles(run_dir: Path) -> None:
    """The defect this exists for: the LCZ layer — the site's *default view* — painted every cell
    `NODATA_COLOUR` in every published site, because tippecanoe's FlatGeobuf reader writes integer
    attributes as strings and the `match` expression compared against integers.

    Neither existing test could see it. `test_viz_style.py` asserts the expression carries the
    committed colours; `test_the_site_directory_holds_what_claude_md_specifies` asserts the tileset
    is a valid archive. Each half was checked against its own assumption and nothing checked that
    the type in the tiles is a type the expression can match. So this test reads the built tiles and
    evaluates the real expression against the real values.
    """
    build_site(run_dir)
    site = run_dir / "site"
    style = json.loads((site / "style.json").read_text(encoding="utf-8"))
    lcz = next(v for v in style["metadata"]["lczkit"]["views"] if v["id"] == "lcz")

    values = set(re.findall(r'"lcz_primary": (".*?"|[-\d.]+)', decode_units_tiles(site)))
    assert values, "no unit in the tiles carries an LCZ class at all"

    painted = {value: evaluate_match(lcz["paint"], json.loads(value)) for value in values}
    unmatched = {value for value, colour in painted.items() if colour == NODATA_COLOUR}
    assert not unmatched, (
        f"{len(unmatched)} of {len(values)} LCZ values in the tiles paint as no-data: "
        f"{sorted(unmatched)[:5]}"
    )


def evaluate_match(expression: list, value: object) -> str:
    """Evaluate `["match", ["to-number", ["get", ...]], label, colour, ..., default]` on `value`.

    Small enough to write out, and writing it out is the point: the assertion has to go through the
    same coercion MapLibre would, or it tests something the browser does not do.
    """
    assert expression[0] == "match"
    coerce = expression[1][0] == "to-number"
    number = float(value) if coerce else value
    labels, colours, default = expression[2:-1:2], expression[3:-1:2], expression[-1]
    for label, colour in zip(labels, colours, strict=True):
        if label == number:
            return str(colour)
    return str(default)
