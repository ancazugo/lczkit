"""Unit tests for each Phase 1 building-cleaning step, against small hand-built geometries."""

from __future__ import annotations

import geopandas as gpd
import geoplanar
import pytest
from shapely.geometry import LineString, MultiPolygon, Polygon, box

from lczkit.cleaning.buildings import (
    BUILDING_ID,
    MAX_PLANARITY_EPS_M,
    absorb_small_buildings,
    clean_buildings,
    drop_non_polygons,
    drop_oversized,
    enforce_planarity,
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


def _zero_area_overlap() -> gpd.GeoDataFrame:
    """Two footprints that `overlaps()` reports as overlapping while their intersection has area
    exactly 0.0 — the artefact `geoplanar.trim_overlaps` cannot clear.

    The smaller polygon carries a zero-width spike along the shared edge. `difference` on such a
    pair returns the input unchanged, so the pair survives any number of trimming passes; on the
    Berlin fixture three of them did, and they are why `buildings_topo` reported
    `is_planar_enforced: False` while `momepy.enclosures()` was reading it.

    The spike sits on the *smaller* polygon deliberately: `trim_overlaps` trims the larger, so
    subtracting the spiked one from the plain one is the no-op, which is the case that survives.
    """
    plain = box(0, 0, 20, 10)
    spiked = Polygon([(20, 0), (25, 0), (25, 10), (20, 10), (20, 6), (20, 4), (20, 6)])
    return _gdf([plain, spiked])


def test_trim_overlaps_cannot_clear_a_zero_area_overlap() -> None:
    """The premise of `enforce_planarity`, asserted rather than assumed. If a future geoplanar
    fixes this, this test fails and the extra step can go."""
    gdf = _zero_area_overlap()
    left, right = gdf.geometry.iloc[0], gdf.geometry.iloc[1]
    assert left.overlaps(right)
    assert left.intersection(right).area == 0.0

    trimmed, _ = trim_overlaps(gdf)

    assert trimmed.geometry.iloc[0].overlaps(trimmed.geometry.iloc[1])


def test_enforce_planarity_clears_what_trimming_cannot_at_negligible_cost() -> None:
    gdf = _zero_area_overlap()

    result, step = enforce_planarity(gdf)

    assert not result.geometry.iloc[0].overlaps(result.geometry.iloc[1])
    assert geoplanar.is_planar_enforced(result, allow_gaps=True)
    assert len(result) == 2
    assert step.detail["n_residual_pairs"] == 1
    assert step.detail["n_passes"] >= 1
    # A micrometre-wide sliver off a 200 m2 footprint. The step exists to make a layer planar, not
    # to change what it measures, and the report has to show that it did not.
    assert step.detail["area_removed_m2"] < 1e-3
    assert step.area_out_m2 == pytest.approx(step.area_in_m2, abs=1e-3)


def test_enforce_planarity_leaves_an_already_planar_layer_alone() -> None:
    """A rule that never fires must be distinguishable from one never run — `n_passes` is 0, not
    absent, and not 1."""
    gdf = _gdf([box(0, 0, 10, 10), box(20, 0, 30, 10)])

    result, step = enforce_planarity(gdf)

    assert step.detail["n_passes"] == 0
    assert step.detail["n_residual_pairs"] == 0
    assert step.detail["area_removed_m2"] == pytest.approx(0.0)
    assert result.geometry.area.sum() == pytest.approx(200.0)


def test_enforce_planarity_trims_the_larger_footprint_of_a_pair() -> None:
    """Matching `trim_overlaps(strategy="largest")`, so which feature loses the sliver does not
    depend on which operation reached the pair first."""
    gdf = _gdf([box(0, 0, 10, 10), box(9, 0, 30, 10)])
    before = gdf.geometry.area.to_numpy()

    result, _ = enforce_planarity(gdf)
    after = result.geometry.area.to_numpy()

    assert after[0] == pytest.approx(before[0])
    assert after[1] < before[1]


def test_enforce_planarity_widens_the_buffer_between_passes() -> None:
    """A *fixed* epsilon cannot converge, and the fixture was too small to show it.

    A pair the buffer fails to separate at one width fails at that width however many passes it is
    given, so the loop spins to its bound. Berlin's three fixture pairs all clear at one
    micrometre; the metropolitan extent produced one that cleared at none of eight passes and
    ended the run. The epsilon now grows per pass, capped a thousand times below survey precision.
    """
    _, step = enforce_planarity(_zero_area_overlap(), eps_m=1e-6)
    assert step.detail["eps_final_m"] >= 1e-6
    assert step.detail["eps_final_m"] <= 1e-3


def test_eps_final_m_reports_the_width_that_was_actually_subtracted() -> None:
    """It used to be derived after the loop by dividing the escalated value back down, which is
    wrong precisely where the escalation stops: once `eps` saturates at the ceiling, two passes
    share a width and the division reports one that was never used. Starting at the ceiling makes
    the loop saturate on its first pass, so the reported width must be the ceiling itself."""
    _, step = enforce_planarity(_zero_area_overlap(), eps_m=MAX_PLANARITY_EPS_M)

    assert step.detail["n_passes"] >= 1
    assert step.detail["eps_final_m"] == MAX_PLANARITY_EPS_M


def test_enforce_planarity_drops_a_pair_it_cannot_separate_rather_than_ending_the_run() -> None:
    """Last resort, and recorded rather than silent.

    `buildings_topo` is the destructive layer and the one that must be planar for
    `momepy.enclosures()`; `buildings_area` carries every area statistic and is untouched. One
    pathological pair among a city's footprints should cost that pair, not the run — but an
    unexplained gap in the topology layer is exactly what the cleaning report exists to surface,
    so the count appears in the step.
    """
    result, step = enforce_planarity(_zero_area_overlap(), max_passes=0)

    assert step.detail["n_dropped_unresolvable"] == 1
    assert step.detail["n_passes"] == 0
    assert len(result) == 1
    assert geoplanar.is_planar_enforced(result, allow_gaps=True)


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
        # First, and necessarily before the explode: it is the only point at which one source
        # feature is still one row, which is what "one building, one vote" downstream needs.
        "assign_feature_id",
        "fix_invalid_geometries",
        "explode_multipolygons",
        "drop_non_polygons",
        "drop_oversized",
        "assign_building_id",
        "trim_overlaps",
        "resolve_overlaps",
        "absorb_small_buildings",
        "enforce_planarity",
        "validate_planarity",
    ]
    # The shared prefix is stage "buildings"; after the fork each step names the layer it built,
    # so `CleaningReport.area_retention` can be asked about either one.
    assert [s.stage for s in steps[:6]] == ["buildings"] * 6
    assert steps[6].stage == "buildings_area"
    assert {s.stage for s in steps[7:]} == {"buildings_topo"}

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


def test_a_self_overlapping_source_reports_the_double_count_it_removed() -> None:
    """The Kowloon case, in three rectangles. This is what the sum-based criterion could not state.

    Two footprints overlap over 10 m2, so the source sums to 210 m2 while covering 200 m2 of
    ground. Against the sum, `trim_overlaps` looks like it lost 4.8%; against the union it kept
    everything. Both are true statements about the same operation, and only the second is what
    building surface fraction cares about, because BSF sums overlay pieces and would count the
    overlapping strip twice.
    """
    gdf = _gdf([box(0, 0, 10, 10), box(9, 0, 20, 10)])

    layers, _ = clean_buildings(
        gdf, max_area_m2=10_000, min_area_m2=1, merge_limit_m2=1, overlap_limit=0.9
    )
    coverage = layers.coverage

    assert coverage.raw_summed_area_m2 == pytest.approx(210.0)
    assert coverage.raw_union_area_m2 == pytest.approx(200.0)
    assert coverage.raw_self_overlap_fraction == pytest.approx(10 / 210)

    # Against the sum this reads as attrition; against the union it is a clean pass.
    assert coverage.area_summed_m2 / coverage.raw_summed_area_m2 == pytest.approx(200 / 210)
    assert coverage.union_retention == pytest.approx(1.0)
    assert coverage.ground_retention == pytest.approx(1.0)
    assert coverage.residual_self_overlap_fraction == pytest.approx(0.0)


def test_a_disjoint_source_reports_no_self_overlap_and_the_two_denominators_agree() -> None:
    """Berlin's situation, near enough: where nothing overlaps, sum and union are the same number
    and the change of denominator is a no-op. That is the property that lets the criterion be
    restated without moving any city that already met it."""
    gdf = _gdf([box(0, 0, 10, 10), box(20, 0, 30, 10)])

    layers, _ = clean_buildings(
        gdf, max_area_m2=10_000, min_area_m2=1, merge_limit_m2=1, overlap_limit=0.9
    )
    coverage = layers.coverage

    assert coverage.raw_self_overlap_fraction == pytest.approx(0.0)
    assert coverage.raw_union_area_m2 == pytest.approx(coverage.raw_summed_area_m2)
    assert coverage.union_retention == pytest.approx(1.0)


def test_residual_double_counting_is_reported_rather_than_asserted_away() -> None:
    """`union_retention` above 1.0 means the BSF numerator still double-counts.

    `trim_overlaps` resolves overlapping *pairs*; it does not claim to resolve every stack. The
    report therefore has to be able to say "this layer holds more area than the ground it covers"
    rather than folding both failures into one number that cannot tell losing ground from
    double-counting it. Here the two properties are asserted as a consistent pair, whichever way
    the fixture happens to fall.
    """
    gdf = _gdf([box(0, 0, 10, 10), box(5, 0, 15, 10), box(8, 0, 18, 10)])

    layers, _ = clean_buildings(
        gdf, max_area_m2=10_000, min_area_m2=1, merge_limit_m2=1, overlap_limit=0.9
    )
    coverage = layers.coverage
    residual = coverage.residual_self_overlap_fraction
    retention = coverage.union_retention
    assert residual is not None and retention is not None

    # union_retention counts double-counted area; ground_retention cannot. They differ by exactly
    # the residual overlap, which is what makes the pair diagnostic rather than a single opinion.
    assert retention * (1.0 - residual) == pytest.approx(coverage.ground_retention)
