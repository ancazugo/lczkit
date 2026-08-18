"""Enclosure seeds merged to LCZ-patch scale.

Two properties carry this module and both are asserted on real fixture data rather than only on
constructed shapes: the result is still a **partition** — merging unions adjacent faces, so it
cannot be otherwise, and "cannot be otherwise" is exactly the class of claim this project has been
wrong about before — and it is **deterministic**, because the merge is a greedy loop over a hash-
backed adjacency structure and would not be if any iteration order were left unsorted.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from conftest import HONGKONG_BBOX, HONGKONG_FIXTURES_DIR
from shapely.geometry import box

from lczkit.crs import local_utm_crs
from lczkit.units import check_units
from lczkit.units.enclosures import EnclosureUnits, assemble_barriers
from lczkit.units.patches import (
    MERGE_COLUMNS,
    PEDESTRIAN_CLASSES,
    PatchUnits,
    filter_street_barriers,
    merge_to_patches,
    seed_features,
)

CRS = "EPSG:32650"


def strip(*bounds: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """Seeds from explicit bounds, indexed like `EnclosureUnits` names them."""
    return gpd.GeoDataFrame(
        {"unit_id": [f"enclosure_{i}" for i in range(len(bounds))]},
        geometry=[box(*b) for b in bounds],
        crs=CRS,
    ).set_index("unit_id")


def features_for(seeds: gpd.GeoDataFrame, **columns: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {c: columns.get(c, [np.nan] * len(seeds)) for c in MERGE_COLUMNS}, index=seeds.index
    )


# --------------------------------------------------------------------------------------------
# The barrier filter
# --------------------------------------------------------------------------------------------


def test_pedestrian_classes_leave_the_barrier_set_and_streets_stay() -> None:
    streets = gpd.GeoDataFrame(
        {"class": ["residential", "footway", "steps", "primary", "path"]},
        geometry=[box(i, 0, i + 1, 1).boundary for i in range(5)],
        crs=CRS,
    )

    kept = filter_street_barriers(streets)

    assert set(kept["class"]) == {"residential", "primary"}


def test_pedestrian_the_class_survives_because_a_plaza_is_a_real_break() -> None:
    """Overture uses `pedestrian` for plazas and pedestrianised streets, which divide urban fabric
    at the width a street does. `footway` is a path through it."""
    assert "pedestrian" not in PEDESTRIAN_CLASSES
    streets = gpd.GeoDataFrame(
        {"class": ["pedestrian", "footway"]},
        geometry=[box(0, 0, 1, 1).boundary, box(2, 0, 3, 1).boundary],
        crs=CRS,
    )

    assert list(filter_street_barriers(streets)["class"]) == ["pedestrian"]


def test_a_source_without_a_class_column_is_passed_through_rather_than_refused() -> None:
    """`VectorSource` does not promise a class column. Raising would make it a hard requirement of
    a protocol that does not have one; the pass-through is what the caller would get anyway."""
    streets = gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1).boundary], crs=CRS)

    assert len(filter_street_barriers(streets)) == 1


# --------------------------------------------------------------------------------------------
# The merge
# --------------------------------------------------------------------------------------------


def test_the_smallest_seed_merges_into_the_neighbour_it_most_resembles() -> None:
    """The whole point of merging on morphology rather than size: a sliver between a dense block
    and an open one belongs with whichever it looks like, not with whichever is nearer the top of
    an arbitrary list."""
    # A 1000 m2 sliver between two 10 000 m2 blocks, so it has a candidate on each side.
    seeds = strip((0, 0, 100, 100), (100, 0, 110, 100), (110, 0, 210, 100))
    features = features_for(seeds, building_surface_fraction=[0.1, 0.6, 0.62])

    # Above the sliver and below what a merged pair reaches, so exactly one merge happens and the
    # test is about *which* neighbour rather than about how many rounds the loop ran.
    patches, report = merge_to_patches(seeds, features, min_area_m2=2_000.0)

    assert report.n_merges == 1
    # enclosure_1 (0.6) joined enclosure_2 (0.62), not enclosure_0 (0.1).
    assert len(patches) == 2
    assert patches.geometry.area.max() == pytest.approx(11_000.0)


def test_a_missing_dimension_is_compared_on_what_is_left_never_imputed() -> None:
    """Same policy as the classifier's weighted partial distance, for the same reason: a seed with
    no measured building has no height, and giving it the mean would merge it into whatever happens
    to be average."""
    seeds = strip((0, 0, 100, 100), (100, 0, 110, 100), (110, 0, 210, 100))
    features = pd.DataFrame(
        {
            "building_surface_fraction": [0.1, 0.6, 0.62],
            "height_of_roughness_elements_m": [4.0, np.nan, 30.0],
        },
        index=seeds.index,
    )

    patches, report = merge_to_patches(seeds, features, min_area_m2=2_000.0)

    # Height is unavailable on the sliver, so the decision falls to BSF alone and still picks 0.62.
    assert report.n_merges == 1
    assert patches.geometry.area.max() == pytest.approx(11_000.0)


def test_merging_stops_at_the_minimum_which_is_a_floor_not_a_centre() -> None:
    seeds = strip(*[(i * 10.0, 0.0, i * 10.0 + 10.0, 10.0) for i in range(10)])

    patches, report = merge_to_patches(seeds, None, min_area_m2=250.0)

    assert (patches.geometry.area >= 250.0).all()
    assert report.n_below_minimum == 0


def test_the_area_ceiling_blocks_a_merge_and_the_block_is_counted() -> None:
    """`n_blocked_by_max_area` exists so two thresholds fighting each other is visible rather than
    showing up as a merge that quietly did something else."""
    # 10 000 m2 beside a 1000 m2 sliver: merging them reaches 11 000, above the ceiling.
    seeds = strip((0, 0, 100, 100), (100, 0, 110, 100))

    _, report = merge_to_patches(seeds, None, min_area_m2=5_000.0, max_area_m2=10_500.0)

    # The merge happens anyway — refusing would leave the sliver permanently, which is the state
    # this exists to remove — but it is recorded as forced rather than chosen.
    assert report.n_blocked_by_max_area == 1
    assert report.n_merges == 1


def test_a_seed_already_over_the_ceiling_is_split_rather_than_surviving_it() -> None:
    """`max_area_m2` used to be a merge guard wearing a ceiling's name, and this is the difference.

    It refused to *combine* two seeds into something oversized and had no way to divide a seed that
    already exceeded it — and enclosure seeds routinely do, because a face bounded by nothing but
    the study edge is as large as the unmapped ground it covers. Measured on a 4 555 km² Istanbul
    extent: 807 patches over the shipped 50 ha setting, holding 72.7% of the area, the largest
    1 073 km², and one 98 km² unit holding 1 310 buildings under a single label.
    """
    # One seed ten times the ceiling, beside a small one.
    seeds = strip((0, 0, 1000, 100), (1000, 0, 1010, 100))

    patches, report = merge_to_patches(seeds, None, min_area_m2=500.0, max_area_m2=10_000.0)

    assert report.n_seeds_split == 1
    assert report.n_above_maximum == 0
    assert patches.geometry.area.max() <= 10_000.0
    # The partition survives the cut: the same ground, still without overlaps.
    assert patches.geometry.area.sum() == pytest.approx(seeds.geometry.area.sum())
    assert patches.union_all().area == pytest.approx(seeds.geometry.area.sum())


def test_splitting_is_off_when_no_ceiling_is_asked_for() -> None:
    """`max_area_m2=None` means "no ceiling", and a caller who says so gets the faces they gave."""
    seeds = strip((0, 0, 1000, 100), (1000, 0, 1010, 100))

    patches, report = merge_to_patches(seeds, None, min_area_m2=500.0, max_area_m2=None)

    assert report.n_seeds_split == 0
    assert patches.geometry.area.max() == pytest.approx(100_000.0)


def test_no_patch_over_the_ceiling_reports_zero_rather_than_nothing() -> None:
    """ "Never fired" and "never measured" have to stay distinguishable, as everywhere else here."""
    seeds = strip(*[(i * 10.0, 0.0, i * 10.0 + 10.0, 10.0) for i in range(10)])

    _, report = merge_to_patches(seeds, None, min_area_m2=250.0, max_area_m2=10_000.0)

    assert report.n_above_maximum == 0
    assert report.area_above_maximum == 0.0
    assert report.n_seeds_split == 0


def test_an_isolate_stays_its_own_patch_and_is_counted() -> None:
    """An island has nothing to merge into. Leaving it below the minimum is correct; leaving it
    *unreported* would make a city full of islands look like one where the merge succeeded."""
    seeds = strip((0, 0, 10, 10), (1000, 1000, 1010, 1010))

    patches, report = merge_to_patches(seeds, None, min_area_m2=50_000.0)

    assert report.n_isolates == 2
    assert report.n_patches == 2
    assert report.n_below_minimum == 2
    check_units(patches)


def test_a_ceiling_below_the_floor_is_refused_rather_than_silently_blocking_everything() -> None:
    seeds = strip((0, 0, 10, 10))

    with pytest.raises(ValueError, match="max_area_m2"):
        merge_to_patches(seeds, None, min_area_m2=1000.0, max_area_m2=500.0)


def test_a_patch_is_named_for_its_largest_constituent_not_for_the_merge_order() -> None:
    """An id should point at the ground it mostly describes. Naming it after whichever seed the
    loop happened to start from would make a stored run depend on an implementation detail."""
    seeds = strip((0, 0, 10, 10), (10, 0, 110, 100))

    patches, _ = merge_to_patches(seeds, None, min_area_m2=50_000.0)

    assert list(patches.index) == ["patch_1"]


# --------------------------------------------------------------------------------------------
# The two properties that carry the module, on the real fixture
# --------------------------------------------------------------------------------------------


def hongkong_seeds() -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    crs = local_utm_crs(HONGKONG_BBOX)
    read = lambda name: gpd.read_parquet(HONGKONG_FIXTURES_DIR / f"{name}.parquet").to_crs(crs)  # noqa: E731
    buildings = read("buildings")
    buildings["height"] = pd.to_numeric(buildings["height"], errors="coerce").fillna(
        pd.to_numeric(buildings["num_floors"], errors="coerce") * 3.0
    )
    barriers = assemble_barriers(
        filter_street_barriers(read("streets")), read("waterbodies"), rail=read("rail")
    )
    seeds = EnclosureUnits().generate(HONGKONG_BBOX, barriers)
    return seeds, seed_features(seeds, buildings)


def test_the_merge_preserves_the_partition_exactly() -> None:
    """Seeds are a partition (`clip=True`, Phase 2) and merging unions adjacent faces, so the
    covered ground and the absence of overlap both survive. Asserted rather than argued: Phase 2's
    own acceptance criteria were satisfiable by a non-partition, which is how enclosures covering
    222% of Berlin's extent survived to Phase 6.5."""
    seeds, features = hongkong_seeds()

    patches, _ = merge_to_patches(seeds, features)

    assert patches.geometry.area.sum() == pytest.approx(seeds.geometry.area.sum(), rel=1e-9)
    assert patches.sjoin(patches, predicate="overlaps").empty
    check_units(patches)


def test_the_merge_is_deterministic_under_a_row_shuffle() -> None:
    """A greedy loop over a hash-backed adjacency structure is deterministic only if every
    iteration order is sorted. Phase 12 found `tiles.subset` discarding a canonical row order into
    `neatnet`, so this is a failure mode the project has already paid for once."""
    seeds, features = hongkong_seeds()
    shuffled = seeds.sample(frac=1.0, random_state=7)

    first, _ = merge_to_patches(seeds, features)
    second, _ = merge_to_patches(shuffled, features.reindex(shuffled.index))

    assert sorted(first.index) == sorted(second.index)
    assert first.geometry.area.sort_values().to_numpy() == pytest.approx(
        second.geometry.area.sort_values().to_numpy()
    )


def test_the_fixture_lands_in_the_patch_size_band() -> None:
    """The measurement the module exists for. Enclosures on this fixture are a median 0.04 ha;
    WUDAPT polygons across the sixteen study cities run 2.2-52 ha and a So2Sat patch is 10.24 ha."""
    seeds, features = hongkong_seeds()

    patches, report = merge_to_patches(seeds, features)

    seed_median = seeds.geometry.area.median()
    patch_median = patches.geometry.area.median()
    assert seed_median < 10_000.0  # under a hectare: a block, not a patch
    assert 20_000.0 < patch_median < 400_000.0  # 2-40 ha: the grain WUDAPT is drawn at
    assert report.n_patches < report.n_seeds
    assert report.seed_area_quantiles["p50"] == pytest.approx(seed_median)
    assert report.patch_area_quantiles["p50"] == pytest.approx(patch_median)


def test_patch_units_satisfies_the_strategy_protocol_and_keeps_its_report() -> None:
    crs = local_utm_crs(HONGKONG_BBOX)
    read = lambda name: gpd.read_parquet(HONGKONG_FIXTURES_DIR / f"{name}.parquet").to_crs(crs)  # noqa: E731
    barriers = assemble_barriers(
        filter_street_barriers(read("streets")), read("waterbodies"), rail=read("rail")
    )

    strategy = PatchUnits(buildings=read("buildings"))
    patches = strategy.generate(HONGKONG_BBOX, barriers)

    check_units(patches)
    assert strategy.report is not None
    assert strategy.report.n_seeds > strategy.report.n_patches


def test_without_buildings_the_merge_still_produces_a_partition() -> None:
    """Supported and worse, and the docstring says so. It must not be *broken*, because it is what
    a `VectorSource` with no usable building layer falls back to."""
    crs = local_utm_crs(HONGKONG_BBOX)
    read = lambda name: gpd.read_parquet(HONGKONG_FIXTURES_DIR / f"{name}.parquet").to_crs(crs)  # noqa: E731
    barriers = assemble_barriers(
        filter_street_barriers(read("streets")), read("waterbodies"), rail=read("rail")
    )

    patches = PatchUnits().generate(HONGKONG_BBOX, barriers)

    check_units(patches)
    assert len(patches) > 0


def test_seed_features_reports_zero_cover_and_null_height_where_no_building_stands() -> None:
    """A block with no buildings has a building surface fraction of 0.0, which is a measurement,
    and no height, which is an absence. Conflating them would merge empty ground into whatever is
    average."""
    seeds = strip((0, 0, 100, 100), (100, 0, 200, 100))
    buildings = gpd.GeoDataFrame({"height": [12.0]}, geometry=[box(10, 10, 40, 40)], crs=CRS)

    features = seed_features(seeds, buildings)

    assert features.loc["enclosure_0", "building_surface_fraction"] == pytest.approx(0.09)
    assert features.loc["enclosure_1", "building_surface_fraction"] == 0.0
    assert features.loc["enclosure_0", "height_of_roughness_elements_m"] == pytest.approx(12.0)
    assert pd.isna(features.loc["enclosure_1", "height_of_roughness_elements_m"])
