"""Tests for `EarthEngineSource`'s testable surface.

No Earth Engine credentials exist on the system this was written against, so nothing here calls
Earth Engine and there is no `@pytest.mark.network` test to skip — the live path is genuinely
unverified, and pretending otherwise with a skipped test would be worse than saying so.

What *is* tested is everything that decides whether the live call is correct: the batching, the
cache key, the row placement that keeps each unit matched to its own result, and the histogram
normalisation that has to produce a table schema-identical to `LocalRasterSource`'s. Those are
module-level functions precisely so they can be reached without credentials.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from lczkit.config import LandCoverConfig, LandCoverDatasetConfig
from lczkit.landcover.classify import EXCLUDED
from lczkit.landcover.earthengine import (
    REDUCER,
    ROW_PROPERTY,
    batched,
    cache_key,
    counts_from_histograms,
    place_by_row,
)
from lczkit.landcover.table import fractions_table

CRS = "EPSG:32633"


def _config(**overrides: object) -> LandCoverDatasetConfig:
    kwargs: dict[str, object] = {
        "name": "test",
        "source_dir_name": "Test",
        "classes": ["tree", "pervious", "impervious"],
        "value_classes": {10: "tree", 30: "pervious", 50: "impervious"},
    }
    kwargs.update(overrides)
    return LandCoverDatasetConfig(**kwargs)  # type: ignore[arg-type]


def _units(n: int = 3) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"unit_id": [f"unit_{i}" for i in range(n)]},
        geometry=[box(100 * i, 0, 100 * i + 100, 100) for i in range(n)],
        crs=CRS,
    ).set_index("unit_id")


def test_batching_splits_without_losing_or_reordering() -> None:
    """CLAUDE.md: chunk into batches of a few thousand to stay under element-count and payload
    limits. Every unit must appear in exactly one batch."""
    batches = list(batched(range(7), 3))

    assert [list(b) for b in batches] == [[0, 1, 2], [3, 4, 5], [6]]


def test_batching_handles_an_exact_multiple_and_an_empty_input() -> None:
    assert [list(b) for b in batched(range(4), 2)] == [[0, 1], [2, 3]]
    assert list(batched(range(0), 2)) == []


def test_a_nonsense_batch_size_raises() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        list(batched(range(3), 0))


def test_the_cache_key_is_stable_across_row_order() -> None:
    """Same units in a different order are the same query and must hit the same cached file."""
    units = _units()

    assert cache_key(units, _config()) == cache_key(units.iloc[::-1], _config())


@pytest.mark.parametrize(
    "update",
    [
        {"gee": {"collection_id": "OTHER/ASSET"}},
        {"gee": {"start_date": "2019-01-01"}},
        {"gee": {"scale_m": 30.0}},
        {"value_classes": {10: "tree", 30: "pervious", 50: "pervious"}},
        {"classes": ["tree", "pervious", "impervious", "water"]},
        {"nodata_policy": "assign", "nodata_class": "pervious"},
    ],
)
def test_the_cache_key_changes_with_anything_that_changes_the_answer(update: dict) -> None:
    """CLAUDE.md keys this cache on (unit geometries, collection ID, date range, reducer). The
    class mapping is folded in too: without it, editing `value_classes` would return a table
    computed under the old mapping and nothing would look wrong."""
    base = _config(gee={"collection_id": "A/B", "start_date": "2021-01-01", "scale_m": 10.0})
    changed = _config(
        gee={"collection_id": "A/B", "start_date": "2021-01-01", "scale_m": 10.0}
        | update.pop("gee", {}),
        **update,
    )
    units = _units()

    assert cache_key(units, base) != cache_key(units, changed)


def test_the_cache_key_changes_with_the_units() -> None:
    config = _config()

    assert cache_key(_units(3), config) != cache_key(_units(4), config)
    assert cache_key(_units(3), config) != cache_key(_units(3).to_crs("EPSG:32634"), config)


def test_the_reducer_is_part_of_the_key_and_named_once() -> None:
    assert REDUCER == "frequencyHistogram"


def test_histograms_normalise_to_the_local_backends_schema() -> None:
    """The acceptance criterion for this phase: both sources return schema-identical tables."""
    config = _config()
    index = _units(2).index
    histograms: list[dict[str, object] | None] = [
        {"0": 30.0, "2": 70.0},
        {"1": 50.0, "2": 50.0},
    ]

    counts = counts_from_histograms(histograms, index, 3)
    result = fractions_table(counts, config, index)

    assert list(result.columns) == ["frac_tree", "frac_pervious", "frac_impervious"]
    assert result.loc["unit_0"].tolist() == pytest.approx([0.3, 0.0, 0.7])
    assert result.sum(axis=1).to_numpy() == pytest.approx(1.0)


def test_excluded_cells_leave_the_denominator() -> None:
    """A masked pixel must not count, exactly as nodata does not count locally."""
    index = _units(1).index

    counts = counts_from_histograms([{"0": 25.0, str(EXCLUDED): 75.0}], index, 3)
    result = fractions_table(counts, _config(), index)

    assert result.loc["unit_0"].tolist() == pytest.approx([1.0, 0.0, 0.0])


def test_a_unit_with_no_counted_pixels_is_null() -> None:
    index = _units(2).index

    counts = counts_from_histograms([{"0": 10.0}, None], index, 3)
    result = fractions_table(counts, _config(), index)

    assert np.isfinite(result.loc["unit_0"]).all()
    assert result.loc["unit_1"].isna().all()


def test_an_unmapped_value_raises_server_side_too() -> None:
    """`unmapped_policy="raise"` has to survive a server-side reduction. It does because unmapped
    values get their own sentinel, distinct from the one masked pixels get — otherwise a histogram
    could not tell the two apart and the policy would silently degrade to "exclude"."""
    with pytest.raises(ValueError, match="not covered by value_classes"):
        counts_from_histograms([{"0": 10.0, "-2": 5.0}], _units(1).index, 3, dataset_name="test")


def test_the_worldcover_default_carries_a_complete_earth_engine_asset() -> None:
    """Verified against the public Earth Engine STAC catalogue, unlike the ETH product, which is a
    user asset and ships with no ID at all."""
    gee = LandCoverConfig().dataset("worldcover").gee

    assert gee.collection_id == "ESA/WorldCover/v200"
    assert (gee.band, gee.scale_m) == ("Map", 10.0)
    assert (gee.start_date, gee.end_date) == ("2021-01-01", "2022-01-01")


def test_results_are_placed_by_row_not_by_arrival_order() -> None:
    """Earth Engine does not document `reduceRegions` as order-preserving. A permuted result would
    attach every unit's land cover to a different unit, and nothing downstream would notice — every
    row would still sum to 1.0."""
    payload = {
        "features": [
            {"properties": {ROW_PROPERTY: 2, "histogram": {"2": 1.0}}},
            {"properties": {ROW_PROPERTY: 0, "histogram": {"0": 1.0}}},
            {"properties": {ROW_PROPERTY: 1, "histogram": {"1": 1.0}}},
        ]
    }

    assert place_by_row(payload) == [
        (2, {"2": 1.0}),
        (0, {"0": 1.0}),
        (1, {"1": 1.0}),
    ]


def test_a_feature_without_its_row_property_raises() -> None:
    """Losing the property means positional recovery is gone, so this fails loudly rather than
    falling back to arrival order."""
    with pytest.raises(RuntimeError, match=ROW_PROPERTY):
        place_by_row({"features": [{"properties": {"histogram": {"0": 1.0}}}]})


def test_a_unit_earth_engine_returned_nothing_for_is_null() -> None:
    """`reduceRegions` omits `histogram` for a region with no unmasked pixels."""
    index = _units(1).index

    counts = counts_from_histograms(
        [h for _, h in place_by_row({"features": [{"properties": {ROW_PROPERTY: 0}}]})], index, 3
    )

    assert fractions_table(counts, _config(), index).loc["unit_0"].isna().all()


def test_an_unset_project_raises_before_any_earth_engine_call(tmp_path: object) -> None:
    """Checked ahead of `ee.Initialize` so the message names `.env`, not a Google auth failure."""
    from lczkit.landcover.earthengine import EarthEngineSource

    with pytest.raises(ValueError, match="GEE_PROJECT_NAME"):
        EarthEngineSource(
            _config(gee={"collection_id": "A/B", "band": "Map", "scale_m": 10.0}),
            project=None,
            cache_dir=Path("/nonexistent"),
        )


def test_an_incomplete_earth_engine_asset_raises_and_names_the_gaps() -> None:
    """A dataset with no verified asset ID is refused rather than guessed at."""
    from lczkit.landcover.earthengine import EarthEngineSource

    with pytest.raises(ValueError, match="collection_id"):
        EarthEngineSource(
            _config(),  # no `gee` block at all
            project="some-project",
            cache_dir=Path("/nonexistent"),
        )


def test_a_collection_asset_missing_its_date_range_is_refused() -> None:
    """`filterDate` needs both ends. A single `image` is exempt — it has no collection to filter —
    which is why the requirement is asked of the asset rather than hardcoded."""
    from lczkit.landcover.earthengine import EarthEngineSource

    with pytest.raises(ValueError, match="start_date"):
        EarthEngineSource(
            _config(gee={"collection_id": "A/B", "band": "Map", "scale_m": 10.0}),
            project="some-project",
            cache_dir=Path("/nonexistent"),
        )


def test_a_cached_table_is_returned_in_the_units_own_order(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A cache hit is just a file that is already there, and it must reindex to the caller's units
    rather than to whatever order it happened to be written in."""
    config = _config()
    units = _units(3)
    index = units.index
    written = fractions_table(
        counts_from_histograms([{"0": 1.0}, {"1": 1.0}, {"2": 1.0}], index, 3), config, index
    )
    path = tmp_path / "cached.parquet"
    written.to_parquet(path)

    reloaded = pd.read_parquet(path).reindex(index=units.iloc[::-1].index)

    assert list(reloaded.index) == ["unit_2", "unit_1", "unit_0"]
    assert reloaded.loc["unit_0", "frac_tree"] == 1.0
