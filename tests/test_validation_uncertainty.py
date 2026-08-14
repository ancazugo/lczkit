"""Spatial block bootstrap, on hand-built cases where the right answer is arguable on paper.

The property that matters is not the exact interval but that blocks are the resampling unit. A
bootstrap over cells would treat a sheet of correlated observations as independent draws and return
an interval far too narrow, which is the failure this module exists to avoid.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from lczkit.validation.uncertainty import bootstrap_agreement, spatial_blocks

CRS = "EPSG:32633"


def grid(n_cols: int, n_rows: int, cell: float = 100.0) -> gpd.GeoDataFrame:
    ids, geoms = [], []
    for col in range(n_cols):
        for row in range(n_rows):
            ids.append(f"grid_{col}_{row}")
            geoms.append(box(col * cell, row * cell, (col + 1) * cell, (row + 1) * cell))
    return gpd.GeoDataFrame(geometry=geoms, index=pd.Index(ids, name="unit_id"), crs=CRS)


def labels(units: gpd.GeoDataFrame, predicted: list[int], reference: list[int]):
    return (
        pd.Series(predicted, index=units.index, dtype="Int8"),
        pd.Series(reference, index=units.index, dtype="Int8"),
        pd.Series(10_000.0, index=units.index, dtype="float64"),
    )


def test_blocks_are_anchored_on_the_crs_origin_not_the_data() -> None:
    """Same anchor as `GridUnits`, so two runs over overlapping extents agree about which block a
    unit is in and their intervals are computed over comparable partitions."""
    units = grid(4, 1)

    blocks = spatial_blocks(units, block_size_m=200.0)

    assert blocks.loc["grid_0_0"] == blocks.loc["grid_1_0"]
    assert blocks.loc["grid_2_0"] == blocks.loc["grid_3_0"]
    assert blocks.loc["grid_0_0"] != blocks.loc["grid_2_0"]
    # Anchored absolutely: the first block is the one containing x in [0, 200), not "block zero of
    # this extent". Shifting the study area must not renumber a cell's block.
    assert blocks.loc["grid_0_0"] == "block_0_0"
    assert blocks.loc["grid_2_0"] == "block_1_0"


def test_a_block_size_below_the_cell_size_gives_one_block_per_cell() -> None:
    units = grid(3, 1)

    blocks = spatial_blocks(units, block_size_m=50.0)

    assert blocks.nunique() == 3


def test_the_interval_contains_the_point_estimate() -> None:
    units = grid(6, 6)
    predicted, reference, area = labels(units, [2] * 18 + [5] * 18, [2] * 24 + [5] * 12)

    result = bootstrap_agreement(
        predicted,
        reference,
        area,
        spatial_blocks(units, 200.0),
        n_resamples=60,
        block_size_m=200.0,
    )

    assert result.overall_agreement.lower <= result.overall_agreement.point
    assert result.overall_agreement.point <= result.overall_agreement.upper
    assert result.n_blocks == 9
    assert result.n_units == 36
    assert result.block_size_m == 200.0


def test_a_run_that_agrees_everywhere_has_no_spread() -> None:
    """A degenerate case worth pinning: if every resample scores 1.0, the interval must be a point
    rather than an artefact of the percentile call."""
    units = grid(4, 4)
    predicted, reference, area = labels(units, [2] * 16, [2] * 16)

    result = bootstrap_agreement(
        predicted, reference, area, spatial_blocks(units, 200.0), n_resamples=40
    )

    assert result.overall_agreement.point == pytest.approx(1.0)
    assert result.overall_agreement.width == pytest.approx(0.0)


def test_larger_blocks_do_not_report_a_narrower_interval_than_single_cells() -> None:
    """The reason the module exists. Correlated observations resampled independently look like more
    information than they are, so the cell-wise interval is the optimistic one; blocking must not
    be *tighter* than it. Asserted as an inequality rather than a ratio because the exact widths
    depend on the resample draw."""
    units = grid(8, 8)
    # A spatially structured error: the whole left half is wrong. Resampling cells breaks that
    # structure up; resampling blocks keeps it, which is what the ground actually looks like.
    predicted, reference, area = labels(
        units,
        [5 if unit.split("_")[1] in {"0", "1", "2", "3"} else 2 for unit in units.index],
        [2] * 64,
    )

    per_cell = bootstrap_agreement(
        predicted, reference, area, spatial_blocks(units, 100.0), n_resamples=120
    )
    per_block = bootstrap_agreement(
        predicted, reference, area, spatial_blocks(units, 400.0), n_resamples=120
    )

    assert per_block.n_blocks < per_cell.n_blocks
    assert per_block.overall_agreement.width >= per_cell.overall_agreement.width


def test_the_seed_is_fixed_so_two_runs_of_one_dataset_agree() -> None:
    """An interval that moves between two runs of the same data is not a property of the data."""
    units = grid(5, 5)
    predicted, reference, area = labels(units, [2] * 13 + [5] * 12, [2] * 25)
    blocks = spatial_blocks(units, 200.0)

    first = bootstrap_agreement(predicted, reference, area, blocks, n_resamples=30)
    second = bootstrap_agreement(predicted, reference, area, blocks, n_resamples=30)

    assert first.overall_agreement.lower == second.overall_agreement.lower
    assert first.overall_agreement.upper == second.overall_agreement.upper


def test_an_unprojected_unit_frame_is_refused() -> None:
    units = grid(2, 2).to_crs("EPSG:4326")

    with pytest.raises(ValueError, match="projected"):
        spatial_blocks(units, 200.0)


def test_a_nonsense_block_size_or_confidence_is_refused() -> None:
    units = grid(2, 2)
    predicted, reference, area = labels(units, [2] * 4, [2] * 4)

    with pytest.raises(ValueError, match="block_size_m"):
        spatial_blocks(units, 0.0)
    with pytest.raises(ValueError, match="confidence"):
        bootstrap_agreement(
            predicted, reference, area, spatial_blocks(units, 200.0), confidence=1.0
        )
