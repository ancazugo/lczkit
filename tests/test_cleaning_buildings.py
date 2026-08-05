"""Unit tests for each Phase 1 building-cleaning step, against small hand-built geometries."""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString, MultiPolygon, Polygon, box

from lczkit.cleaning.buildings import (
    absorb_small_buildings,
    clean_buildings,
    drop_non_polygons,
    drop_oversized,
    explode_multipolygons,
    fix_invalid_geometries,
    resolve_overlaps,
)

CRS = "EPSG:32633"  # a real projected CRS; assert_projected_crs requires one


def _gdf(geoms: list, **cols: list) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({**cols}, geometry=geoms, crs=CRS)


def test_fix_invalid_geometries_repairs_bowtie() -> None:
    bowtie = Polygon([(0, 0), (10, 10), (10, 0), (0, 10), (0, 0)])
    assert not bowtie.is_valid
    gdf = _gdf([bowtie])

    fixed, step = fix_invalid_geometries(gdf)

    assert fixed.geometry.is_valid.all()
    assert step.n_in == 1
    assert step.n_out == 1
    assert step.detail["n_invalid_before"] == 1


def test_explode_multipolygons_splits_parts() -> None:
    multi = MultiPolygon([box(0, 0, 1, 1), box(5, 5, 6, 6)])
    gdf = _gdf([multi, box(10, 10, 11, 11)])

    exploded, step = explode_multipolygons(gdf)

    assert len(exploded) == 3
    assert (exploded.geometry.geom_type == "Polygon").all()
    assert step.n_in == 2
    assert step.n_out == 3


def test_drop_non_polygons_keeps_only_polygons() -> None:
    gdf = _gdf([box(0, 0, 1, 1), LineString([(0, 0), (1, 1)])])

    filtered, step = drop_non_polygons(gdf)

    assert len(filtered) == 1
    assert filtered.geometry.iloc[0].geom_type == "Polygon"
    assert step.n_in == 2
    assert step.n_out == 1


def test_drop_oversized_drops_only_large_footprints() -> None:
    small = box(0, 0, 10, 10)  # area 100
    huge = box(100, 100, 200, 200)  # area 10000
    gdf = _gdf([small, huge])

    filtered, step = drop_oversized(gdf, max_area_m2=1000)

    assert len(filtered) == 1
    assert filtered.geometry.iloc[0].area == pytest.approx(100)
    assert step.n_in == 2
    assert step.n_out == 1
    assert step.detail["max_area_m2"] == 1000


def test_resolve_overlaps_merges_below_merge_limit() -> None:
    # two 10x10 squares overlapping by a 1x10 strip (area 10) — both under merge_limit
    g1 = box(0, 0, 10, 10)
    g2 = box(9, 0, 19, 10)
    gdf = _gdf([g1, g2], height=[5.0, 7.0])

    merged, step = resolve_overlaps(gdf, merge_limit=1000, overlap_limit=0.5)

    assert len(merged) == 1
    assert step.n_in == 2
    assert step.n_out == 1
    # merge_overlaps preserves the columns of one of the merged inputs
    assert merged["height"].iloc[0] in (5.0, 7.0)


def test_absorb_small_buildings_merges_touching_and_drops_isolated() -> None:
    large = box(0, 0, 10, 10)  # area 100
    sliver = box(10, 0, 10.5, 10)  # touches `large` along its right edge, area 5 < min_area
    isolated = box(100, 100, 100.5, 100.5)  # area 0.25 < min_area, touches nothing
    gdf = _gdf([large, sliver, isolated])

    result, step = absorb_small_buildings(gdf, min_area_m2=6)

    assert len(result) == 1  # sliver absorbed into `large`; isolated dropped
    assert result.geometry.iloc[0].area == pytest.approx(large.area + sliver.area)
    assert step.n_in == 3
    assert step.detail["n_small"] == 2


def test_clean_buildings_runs_full_pipeline_in_order() -> None:
    gdf = _gdf([box(0, 0, 10, 10), box(9, 0, 19, 10)], height=[5.0, 7.0])

    cleaned, steps = clean_buildings(
        gdf,
        max_area_m2=10_000,
        min_area_m2=1,
        merge_limit_m2=1_000,
        overlap_limit=0.5,
    )

    operations = [s.operation for s in steps]
    assert operations == [
        "fix_invalid_geometries",
        "explode_multipolygons",
        "drop_non_polygons",
        "drop_oversized",
        "resolve_overlaps",
        "absorb_small_buildings",
        "validate_planarity",
    ]
    assert all(s.stage == "buildings" for s in steps)
    assert len(cleaned) == 1
    assert steps[-1].detail["is_planar_enforced"] is True
