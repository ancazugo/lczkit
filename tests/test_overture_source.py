"""Tests for `OvertureSource`: offline cache-key/cache-hit behaviour, plus live
(`@pytest.mark.network`) schema/filter correctness against the real Overture S3 bucket.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest
from conftest import FIXTURE_BBOX, SMALL_BBOX
from shapely.geometry import box

from lczkit.config import Settings
from lczkit.protocols import BBox
from lczkit.sources.overture import _BUILDINGS, _RAIL, _STREETS, OvertureSource, bbox_key


def _settings(tmp_path: Path, release: str | None = "2026-07-22.0") -> Settings:
    settings = Settings(data_dir=tmp_path, run_id="test")
    settings.overture.release = release
    return settings


def test_bbox_key_is_stable_and_distinct() -> None:
    a: BBox = (13.39, 52.50, 13.41, 52.51)
    b: BBox = (13.39, 52.50, 13.41, 52.51)
    c: BBox = (13.39, 52.50, 13.41, 52.52)

    assert bbox_key(a) == bbox_key(b)
    assert bbox_key(a) != bbox_key(c)
    assert bbox_key(a) == "13.390000_52.500000_13.410000_52.510000"


def test_constructor_raises_without_release(tmp_path: Path) -> None:
    settings = _settings(tmp_path, release=None)

    with pytest.raises(ValueError, match="release"):
        OvertureSource(settings)


def test_the_progress_bar_is_never_switched_off_by_assignment() -> None:
    """`SET enable_progress_bar` takes the whole source out of a Jupyter kernel.

    DuckDB reinitialises its display when that setting is *assigned*, so inside a kernel without
    `ipywidgets` it raises — and `OvertureSource.__init__` raises with it, which takes every code
    path that reads Overture with it. `PRAGMA disable_progress_bar` does the same job without
    touching the display.

    This is a source assertion because the failure is invisible everywhere a test normally runs:
    under pytest there is no kernel, DuckDB draws no progress bar, and the assignment succeeds.
    Only an interactive kernel sees it, and nothing in CI is one.

    It reads the module's *string literals* rather than its lines, so the docstring above — which
    has to name the forbidden form in order to explain it — is not itself a finding.
    """
    import ast

    module = ast.parse(
        (Path(__file__).resolve().parents[1] / "src/lczkit/sources/overture.py").read_text(
            encoding="utf-8"
        )
    )
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(module)
        if isinstance(node, ast.Module | ast.FunctionDef | ast.ClassDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    offenders = [
        node.value
        for node in ast.walk(module)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and "enable_progress_bar" in node.value
    ]
    assert offenders == [], offenders


def test_silencing_the_progress_bar_survives_a_connection_that_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cosmetic setting must not decide whether the source can be constructed."""
    import duckdb

    from lczkit.sources import overture

    real_execute = duckdb.DuckDBPyConnection.execute

    def refuse(self: duckdb.DuckDBPyConnection, query: str, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if "progress_bar" in query:
            raise duckdb.InvalidInputException("required package 'ipywidgets' is missing")
        return real_execute(self, query, *args, **kwargs)

    monkeypatch.setattr(duckdb.DuckDBPyConnection, "execute", refuse)

    source = overture.OvertureSource(_settings(tmp_path))
    assert source._con.execute("SELECT current_setting('s3_region')").fetchone()[0] == "us-west-2"


def test_cache_hit_never_touches_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    source = OvertureSource(settings)
    bbox: BBox = (13.39, 52.50, 13.41, 52.51)

    cached = gpd.GeoDataFrame(
        {"id": ["a"], "height": [5.0], "num_floors": [2], "sources": [None]},
        geometry=[box(0, 0, 1, 1)],
        crs="EPSG:4326",
    )
    cache_path = source._cache_path("buildings", bbox, _BUILDINGS.key)
    cache_path.parent.mkdir(parents=True)
    cached.to_parquet(cache_path)

    def _boom(*args: object, **kwargs: object) -> gpd.GeoDataFrame:
        raise AssertionError("a cache hit should never call _fetch")

    monkeypatch.setattr(source, "_fetch", _boom)

    result = source.buildings(bbox)

    assert list(result["id"]) == ["a"]


def test_a_layer_arrives_in_canonical_order_whatever_the_cache_holds(tmp_path: Path) -> None:
    """The pipeline's reproducibility boundary, asserted where it is enforced.

    DuckDB scans Overture's parquet in parallel with no `ORDER BY`, so `_fetch` returns rows in
    whatever order the readers finished — different between runs, and different again from the
    order a cached file replays. That would not matter if nothing downstream cared, but `neatnet`
    splits a network's edges according to the order it is handed (see
    `test_cleaning_streets_tiled.test_simplification_depends_on_input_row_order`), so an
    unordered source makes two runs over the same city produce two different maps.

    The cache file here is written deliberately out of order, standing in for what the S3 scan
    can return on any given run.
    """
    settings = _settings(tmp_path)
    source = OvertureSource(settings)
    bbox: BBox = (13.39, 52.50, 13.41, 52.51)

    scrambled = gpd.GeoDataFrame(
        {
            "id": ["08b2f5", "08b1aa", "08b3cc", "08b0ff"],
            "height": [5.0, 6.0, 7.0, 8.0],
            "num_floors": [2, 2, 3, 3],
            "sources": [None, None, None, None],
        },
        geometry=[box(i, i, i + 1, i + 1) for i in range(4)],
        crs="EPSG:4326",
    )
    cache_path = source._cache_path("buildings", bbox, _BUILDINGS.key)
    cache_path.parent.mkdir(parents=True)
    scrambled.to_parquet(cache_path)

    result = source.buildings(bbox)

    assert list(result["id"]) == sorted(scrambled["id"]), "rows must arrive in GERS id order"
    assert list(result.index) == list(range(len(result))), "and on a fresh RangeIndex"
    # The attribute must still travel with its own geometry, not merely be sorted alongside it.
    assert result.loc[result["id"] == "08b0ff", "height"].iloc[0] == 8.0


def test_streets_and_rail_cache_to_distinct_files(tmp_path: Path) -> None:
    """`streets()` and `rail()` both read `theme=transportation/type=segment`; the cache must
    key on more than `(theme, type_)` or one silently overwrites the other's cached file."""
    source = OvertureSource(_settings(tmp_path))
    bbox: BBox = (13.39, 52.50, 13.41, 52.51)

    streets = source._cache_path(_STREETS.layer, bbox, _STREETS.key)
    rail = source._cache_path(_RAIL.layer, bbox, _RAIL.key)

    assert streets != rail


def test_changing_a_layers_columns_changes_its_cache_path(tmp_path: Path) -> None:
    """A cached file's contents depend on the query, not just on `(release, bbox, layer)`.
    Widening a layer's column set must route to a new path rather than return a stale frame
    that is missing the new columns — and must never overwrite the old file, which lives in a
    directory shared with other projects."""
    source = OvertureSource(_settings(tmp_path))
    bbox: BBox = (13.39, 52.50, 13.41, 52.51)
    narrower = _BUILDINGS._replace(columns="id, height")

    old = source._cache_path(_BUILDINGS.layer, bbox, narrower.key)
    new = source._cache_path(_BUILDINGS.layer, bbox, _BUILDINGS.key)

    assert old != new
    assert old.parent == new.parent  # same (release, bbox) directory, different file


@pytest.mark.network
def test_rail_only_returns_rail_subtype(tmp_path: Path) -> None:
    source = OvertureSource(_settings(tmp_path))

    rail = source.rail(SMALL_BBOX)

    assert (rail["subtype"] == "rail").all()


@pytest.mark.network
def test_buildings_carry_usage_and_provenance_columns(tmp_path: Path) -> None:
    """`subtype`/`class` (usage type, the only route to LCZ 10) and `sources` (per-feature
    dataset provenance, driving Phase 3's diagnostic) must be pulled at ingestion."""
    source = OvertureSource(_settings(tmp_path))

    buildings = source.buildings(SMALL_BBOX)

    assert {"subtype", "class", "sources"} <= set(buildings.columns)


@pytest.mark.network
def test_land_use_returns_only_polygons_with_usage_columns(tmp_path: Path) -> None:
    source = OvertureSource(_settings(tmp_path))

    land_use = source.land_use(FIXTURE_BBOX)

    assert (land_use.geometry.geom_type.isin(["Polygon", "MultiPolygon"])).all()
    assert {"subtype", "class"} <= set(land_use.columns)


@pytest.mark.network
def test_streets_excludes_service_class(tmp_path: Path) -> None:
    source = OvertureSource(_settings(tmp_path))

    streets = source.streets(SMALL_BBOX)

    assert "service" not in streets["class"].tolist()
    assert (streets["subtype"] == "road").all()


@pytest.mark.network
def test_water_excludes_configured_subtypes(tmp_path: Path) -> None:
    source = OvertureSource(_settings(tmp_path))

    waterlines, waterbodies = source.water(FIXTURE_BBOX)

    excluded = {"human_made", "reservoir", "spring", "wastewater"}
    seen_subtypes = set(waterlines["subtype"].dropna()) | set(waterbodies["subtype"].dropna())
    assert not (seen_subtypes & excluded)
    assert (waterlines.geometry.geom_type.isin(["LineString", "MultiLineString"])).all()
    assert (waterbodies.geometry.geom_type.isin(["Polygon", "MultiPolygon"])).all()
