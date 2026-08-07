"""Unit tests for each Phase 1 building-cleaning step, against small hand-built geometries."""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString, MultiPolygon, Polygon, box

from lczkit.cleaning.buildings import (
    BUILDING_ID,
    absorb_small_buildings,
    clean_buildings,
    drop_non_polygons,
    drop_oversized,
    explode_multipolygons,
    fix_invalid_geometries,
    resolve_overlaps,
    trim_overlaps,
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


def test_trim_overlaps_removes_the_double_count_without_losing_a_feature() -> None:
    """`buildings_area`'s only overlap operation. Building surface fraction sums overlay pieces,
    so a shared 10 m2 strip is counted twice and can push the fraction above 1.0; trimming removes
    exactly that. Both features must survive — merging them would corrupt `building_count` and
    `mean_building_area_m2`, which is why merging stays on the topological layer."""
    gdf = _gdf([box(0, 0, 10, 10), box(9, 0, 19, 10)], height=[5.0, 7.0])

    trimmed, step = trim_overlaps(gdf)

    assert len(trimmed) == 2
    assert trimmed.geometry.area.sum() == pytest.approx(190.0)  # 200 minus the shared 10
    assert not trimmed.geometry.iloc[0].overlaps(trimmed.geometry.iloc[1])
    assert step.stage == "buildings_area"
    assert step.area_in_m2 == pytest.approx(200.0)
    assert step.area_out_m2 == pytest.approx(190.0)


def test_absorb_small_buildings_dissolves_touching_and_keeps_isolated() -> None:
    """CLAUDE.md's rule: this operation dissolves, it does not delete. `geoplanar.merge_touching`
    deletes any polygon sharing no boundary with a neighbour and cannot be told not to, so the
    isolates are held back from it and concatenated in afterwards. A free-standing garage is small,
    not spurious."""
    large = box(0, 0, 10, 10)  # area 100
    sliver = box(10, 0, 10.5, 10)  # touches `large` along its right edge, area 5 < min_area
    isolated = box(100, 100, 100.5, 100.5)  # area 0.25 < min_area, touches nothing
    gdf = _gdf([large, sliver, isolated])

    result, step = absorb_small_buildings(gdf, min_area_m2=6)

    assert len(result) == 2  # sliver dissolved into `large`; isolated retained
    assert result.geometry.area.sum() == pytest.approx(large.area + sliver.area + isolated.area)
    assert step.n_in == 3
    assert step.detail == {
        "min_area_m2": 6,
        "n_small": 2,
        "n_dissolved": 1,
        "n_isolated_retained": 1,
    }
    assert step.area_out_m2 == pytest.approx(step.area_in_m2)


def test_absorb_small_buildings_loses_no_area_when_every_small_one_is_isolated() -> None:
    """The Berlin case: 1043 of 1186 sub-20 m2 footprints touch nothing at all. Under the old
    behaviour every one of them was deleted."""
    gdf = _gdf([box(0, 0, 1, 1), box(50, 50, 51, 51), box(100, 100, 110, 110)])

    result, step = absorb_small_buildings(gdf, min_area_m2=5)

    assert len(result) == 3
    assert step.area_out_m2 == pytest.approx(step.area_in_m2)
    assert step.detail["n_isolated_retained"] == 2


def test_clean_buildings_forks_into_two_layers_sharing_a_building_id() -> None:
    gdf = _gdf([box(0, 0, 10, 10), box(9, 0, 19, 10)], height=[5.0, 7.0])

    layers, steps = clean_buildings(
        gdf,
        max_area_m2=10_000,
        min_area_m2=1,
        merge_limit_m2=1_000,
        overlap_limit=0.5,
    )

    assert [s.operation for s in steps] == [
        "fix_invalid_geometries",
        "explode_multipolygons",
        "drop_non_polygons",
        "drop_oversized",
        "assign_building_id",
        "trim_overlaps",
        "resolve_overlaps",
        "absorb_small_buildings",
        "validate_planarity",
    ]
    # The shared prefix is stage "buildings"; after the fork each step names the layer it built,
    # so `CleaningReport.area_retention` can be asked about either one.
    assert [s.stage for s in steps[:5]] == ["buildings"] * 5
    assert steps[5].stage == "buildings_area"
    assert {s.stage for s in steps[6:]} == {"buildings_topo"}

    # Area preserves both features; topo merges them into one.
    assert len(layers.area) == 2
    assert len(layers.topo) == 1
    assert layers.area[BUILDING_ID].is_unique
    assert set(layers.topo[BUILDING_ID]) <= set(layers.area[BUILDING_ID])
    assert steps[-1].detail["is_planar_enforced"] is True


def test_clean_buildings_keeps_more_area_on_the_area_layer_than_on_the_topological_one() -> None:
    """The whole point of the split. `buildings_topo` merges the overlapping pair into one feature
    and would go on to lose more to the road-buffer rule; `buildings_area` gives up only the
    double-counted strip."""
    gdf = _gdf([box(0, 0, 10, 10), box(9, 0, 19, 10), box(100, 100, 100.5, 100.5)])

    layers, _ = clean_buildings(
        gdf, max_area_m2=10_000, min_area_m2=1, merge_limit_m2=1_000, overlap_limit=0.5
    )

    assert layers.area.geometry.area.sum() == pytest.approx(190.25)
    assert layers.area.geometry.area.sum() >= layers.topo.geometry.area.sum()


def test_clean_buildings_retains_usage_and_provenance_columns() -> None:
    """`subtype`, `class` and `sources` must survive cleaning, not be dropped after geometry
    work — `class` is the only route to LCZ 10 and `sources` drives Phase 3's diagnostic.

    Both merge steps reduce via `GeoDataFrame.dissolve()` (`aggfunc="first"`), so a merged
    footprint inherits the attributes of one constituent rather than losing them. This test
    pins that behaviour: it is `geoplanar`'s, not ours, and a change to it would silently
    break Phases 3, 5 and 6.
    """
    gdf = _gdf(
        [box(0, 0, 10, 10), box(9, 0, 19, 10)],
        height=[5.0, None],
        num_floors=[2, None],
        subtype=["industrial", "residential"],
        sources=[[{"dataset": "OpenStreetMap"}], [{"dataset": "Microsoft ML Buildings"}]],
        **{"class": ["industrial", "apartments"]},
    )

    layers, _ = clean_buildings(
        gdf, max_area_m2=10_000, min_area_m2=1, merge_limit_m2=1_000, overlap_limit=0.5
    )

    for cleaned in (layers.area, layers.topo):
        assert {"height", "num_floors", "subtype", "class", "sources"} <= set(cleaned.columns)
        assert cleaned["sources"].iloc[0] is not None
    assert len(layers.topo) == 1
    assert layers.topo["class"].iloc[0] in {"industrial", "apartments"}
    # The area layer keeps both, so both usage types survive to `industrial_fraction`.
    assert set(layers.area["class"]) == {"industrial", "apartments"}


def test_clean_buildings_never_drops_a_building_for_a_null_height() -> None:
    """Overture conflation is winner-takes-all and parses `height` only from OSM tags, so
    footprints won by an ML source carry no height at all. A null height is normal here; the
    Phase 3 cascade owns it. Nothing in cleaning may filter on it.
    """
    gdf = _gdf(
        [box(0, 0, 10, 10), box(100, 100, 110, 110)],
        height=[None, None],
        num_floors=[None, None],
    )

    layers, _ = clean_buildings(
        gdf, max_area_m2=10_000, min_area_m2=1, merge_limit_m2=1_000, overlap_limit=0.5
    )

    assert len(layers.area) == 2
    assert len(layers.topo) == 2
    assert layers.area["height"].isna().all()
