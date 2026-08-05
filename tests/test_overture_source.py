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
from lczkit.sources.overture import OvertureSource, bbox_key


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


def test_cache_hit_never_touches_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    source = OvertureSource(settings)
    bbox: BBox = (13.39, 52.50, 13.41, 52.51)

    cached = gpd.GeoDataFrame(
        {"id": ["a"], "height": [5.0], "num_floors": [2], "sources": [None]},
        geometry=[box(0, 0, 1, 1)],
        crs="EPSG:4326",
    )
    cache_path = source._cache_path("buildings", "building", bbox)
    cache_path.parent.mkdir(parents=True)
    cached.to_parquet(cache_path)

    def _boom(*args: object, **kwargs: object) -> gpd.GeoDataFrame:
        raise AssertionError("a cache hit should never call _fetch")

    monkeypatch.setattr(source, "_fetch", _boom)

    result = source.buildings(bbox)

    assert list(result["id"]) == ["a"]


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
