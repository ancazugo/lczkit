"""Tests for the source-availability diagnostic.

The headline assertion runs against the real Berlin fixture, because the behaviour that makes
this diagnostic worth having — Overture attributing a height to a dataset other than the one
that won the footprint — is a property of the data, not of any frame this file could invent.
"""

from __future__ import annotations

import geopandas as gpd
import pytest
from conftest import FIXTURES_DIR
from shapely.geometry import box

from lczkit.heights.diagnostic import UNKNOWN_DATASET, source_availability
from lczkit.heights.provenance import FOOTPRINT_PROPERTY, HEIGHT_PROPERTY

CRS = "EPSG:32633"


@pytest.fixture(scope="module")
def fixture_buildings() -> gpd.GeoDataFrame:
    return gpd.read_parquet(FIXTURES_DIR / "buildings.parquet")


def test_totals_match_the_fixture(fixture_buildings: gpd.GeoDataFrame) -> None:
    diagnostic = source_availability(fixture_buildings)

    assert diagnostic.n_buildings == len(fixture_buildings)
    assert diagnostic.n_with_height == int(fixture_buildings["height"].gt(0).sum())
    assert diagnostic.n_with_num_floors == int(fixture_buildings["num_floors"].ge(1).sum())


def test_every_building_is_counted_exactly_once_by_footprint_dataset(
    fixture_buildings: gpd.GeoDataFrame,
) -> None:
    table = source_availability(fixture_buildings).by_footprint_dataset
    diagnostic = source_availability(fixture_buildings)

    assert sum(row.n_buildings for row in table) == diagnostic.n_buildings
    assert sum(row.n_with_height for row in table) == diagnostic.n_with_height
    assert sum(row.n_with_num_floors for row in table) == diagnostic.n_with_num_floors


def test_every_height_is_attributed_exactly_once(fixture_buildings: gpd.GeoDataFrame) -> None:
    """The height table covers heights, not buildings — rows with no height contribute nothing,
    so it sums to `n_with_height` rather than to `n_buildings`."""
    diagnostic = source_availability(fixture_buildings)

    assert sum(row.n_with_height for row in diagnostic.by_height_dataset) == (
        diagnostic.n_with_height
    )


def test_grouping_by_height_dataset_reveals_heights_the_footprint_grouping_hides(
    fixture_buildings: gpd.GeoDataFrame,
) -> None:
    """This is the reason the diagnostic reports two tables. Grouped by footprint, Berlin looks
    like a city whose heights are overwhelmingly OpenStreetMap's; grouped by the dataset that
    actually supplied each height, a quarter of them turn out to be machine-learning values."""
    diagnostic = source_availability(fixture_buildings)
    by_footprint = {row.dataset: row for row in diagnostic.by_footprint_dataset}
    by_height = {row.dataset: row for row in diagnostic.by_height_dataset}

    assert by_height["Microsoft ML Buildings"].n_with_height > (
        by_footprint["Microsoft ML Buildings"].n_with_height
    )
    assert by_height["OpenStreetMap"].n_with_height < by_footprint["OpenStreetMap"].n_with_height
    conflated = (
        by_footprint["OpenStreetMap"].n_with_height - by_height["OpenStreetMap"].n_with_height
    )
    assert conflated / diagnostic.n_with_height > 0.2


def test_tables_are_ordered_most_populated_first(fixture_buildings: gpd.GeoDataFrame) -> None:
    diagnostic = source_availability(fixture_buildings)

    counts = [row.n_buildings for row in diagnostic.by_footprint_dataset]
    assert counts == sorted(counts, reverse=True)


def _frame(**cols: list) -> gpd.GeoDataFrame:
    n = len(next(iter(cols.values())))
    return gpd.GeoDataFrame(cols, geometry=[box(i, 0, i + 1, 1) for i in range(n)], crs=CRS)


def test_a_conflated_height_is_attributed_to_the_dataset_that_supplied_it() -> None:
    frame = _frame(
        height=[15.0],
        num_floors=[None],
        sources=[
            [
                {"property": FOOTPRINT_PROPERTY, "dataset": "OpenStreetMap"},
                {"property": HEIGHT_PROPERTY, "dataset": "Microsoft ML Buildings"},
            ]
        ],
    )

    diagnostic = source_availability(frame)

    assert [(r.dataset, r.n_with_height) for r in diagnostic.by_footprint_dataset] == [
        ("OpenStreetMap", 1)
    ]
    assert [(r.dataset, r.n_with_height) for r in diagnostic.by_height_dataset] == [
        ("Microsoft ML Buildings", 1)
    ]


def test_the_height_table_ignores_buildings_with_no_height() -> None:
    """A footprint with no height tells you nothing about any dataset's height coverage, and
    counting it would credit that dataset with a value it never supplied."""
    frame = _frame(
        height=[15.0, None],
        num_floors=[None, 6],
        sources=[
            [{"property": FOOTPRINT_PROPERTY, "dataset": "OpenStreetMap"}],
            [{"property": FOOTPRINT_PROPERTY, "dataset": "Microsoft ML Buildings"}],
        ],
    )

    diagnostic = source_availability(frame)

    assert [(r.dataset, r.n_with_height) for r in diagnostic.by_height_dataset] == [
        ("OpenStreetMap", 1)
    ]
    assert {r.dataset for r in diagnostic.by_footprint_dataset} == {
        "OpenStreetMap",
        "Microsoft ML Buildings",
    }


def test_a_layer_without_provenance_still_reports_totals() -> None:
    """A non-Overture VectorSource must not block the diagnostic entirely."""
    frame = _frame(height=[12.0, None], num_floors=[None, 3])

    diagnostic = source_availability(frame)

    assert (diagnostic.n_buildings, diagnostic.n_with_height) == (2, 1)
    assert [r.dataset for r in diagnostic.by_footprint_dataset] == [UNKNOWN_DATASET]
    assert diagnostic.by_footprint_dataset[0].n_with_num_floors == 1


def test_a_zero_height_does_not_count_as_available() -> None:
    """Consistent with tier 1, which refuses to treat a non-positive height as a measurement."""
    frame = _frame(height=[0.0, -1.0, 9.0], num_floors=[0, None, 2])

    diagnostic = source_availability(frame)

    assert diagnostic.n_with_height == 1
    assert diagnostic.n_with_num_floors == 1


def test_an_empty_layer_produces_empty_tables() -> None:
    frame = _frame(height=[], num_floors=[])

    diagnostic = source_availability(frame)

    assert diagnostic.n_buildings == 0
    assert diagnostic.by_footprint_dataset == []
    assert diagnostic.by_height_dataset == []
