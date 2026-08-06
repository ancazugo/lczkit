"""Tests for reading per-attribute provenance out of Overture's `sources` column.

The interesting cases come from the real fixture rather than hand-built frames: the whole point
of this module is that Overture's actual behaviour differs from CLAUDE.md's description of it,
so asserting against a synthetic frame would only test my reading of the spec.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from conftest import FIXTURES_DIR
from shapely.geometry import box

from lczkit.heights.provenance import (
    FOOTPRINT_PROPERTY,
    HEIGHT_PROPERTY,
    footprint_datasets,
    height_attribution,
)

CRS = "EPSG:32633"


@pytest.fixture(scope="module")
def fixture_buildings() -> gpd.GeoDataFrame:
    return gpd.read_parquet(FIXTURES_DIR / "buildings.parquet")


def test_overture_attributes_height_to_a_different_dataset_than_the_footprint(
    fixture_buildings: gpd.GeoDataFrame,
) -> None:
    """CLAUDE.md states Overture does not fuse attributes across sources and parses `height`
    only from OSM tags. On release 2026-07-22.0 that is not what the data does, and Phase 3's
    diagnostic depends on the difference — so it is pinned here."""
    footprint = footprint_datasets(fixture_buildings)
    height_dataset, confidence = height_attribution(fixture_buildings)

    conflated = footprint.notna() & (height_dataset != footprint)
    assert conflated.any(), "expected at least one height attributed away from its footprint"
    assert set(footprint[conflated].unique()) == {"OpenStreetMap"}
    assert set(height_dataset[conflated].unique()) == {"Microsoft ML Buildings"}

    # every conflated row carries a real height and Overture's own confidence for it
    assert fixture_buildings.loc[conflated, "height"].notna().all()
    assert confidence[conflated].notna().all()
    assert confidence[conflated].between(0.0, 1.0).all()


def test_height_dataset_falls_back_to_the_footprints_own(
    fixture_buildings: gpd.GeoDataFrame,
) -> None:
    footprint = footprint_datasets(fixture_buildings)
    height_dataset, confidence = height_attribution(fixture_buildings)

    no_entry = confidence.isna()
    assert no_entry.any()
    assert (height_dataset[no_entry] == footprint[no_entry]).all()


def _frame(sources: list[object]) -> gpd.GeoDataFrame:
    geoms = [box(i, 0, i + 1, 1) for i in range(len(sources))]
    return gpd.GeoDataFrame({"sources": sources}, geometry=geoms, crs=CRS)


def test_footprint_entry_is_selected_by_its_property() -> None:
    frame = _frame(
        [
            [
                {"property": HEIGHT_PROPERTY, "dataset": "Microsoft ML Buildings"},
                {"property": FOOTPRINT_PROPERTY, "dataset": "OpenStreetMap"},
            ]
        ]
    )

    assert footprint_datasets(frame).tolist() == ["OpenStreetMap"]
    dataset, confidence = height_attribution(frame)
    assert dataset.tolist() == ["Microsoft ML Buildings"]
    assert np.isnan(confidence.iloc[0])


def test_a_null_property_is_read_as_the_footprint_entry() -> None:
    """Overture writes `''`, but a source that writes `None` means the same thing and must not
    silently become an unmatched attribute entry."""
    frame = _frame([[{"property": None, "dataset": "Esri Community Maps"}]])

    assert footprint_datasets(frame).tolist() == ["Esri Community Maps"]


def test_missing_sources_column_degrades_to_nulls() -> None:
    frame = gpd.GeoDataFrame({"height": [10.0]}, geometry=[box(0, 0, 1, 1)], crs=CRS)

    dataset, confidence = height_attribution(frame)

    assert footprint_datasets(frame).isna().all()
    assert dataset.isna().all()
    assert confidence.isna().all()


def test_null_and_malformed_source_values_do_not_raise() -> None:
    frame = _frame([None, np.nan, [], ["not a dict"], [{"dataset": "OpenStreetMap"}]])

    dataset, confidence = height_attribution(frame)

    assert footprint_datasets(frame).iloc[:4].isna().all()
    assert dataset.iloc[4] == "OpenStreetMap"
    assert confidence.isna().all()


def test_confidence_is_numeric_even_when_overture_omits_it() -> None:
    frame = _frame(
        [
            [{"property": HEIGHT_PROPERTY, "dataset": "X", "confidence": 0.5}],
            [{"property": HEIGHT_PROPERTY, "dataset": "X", "confidence": None}],
        ]
    )

    _, confidence = height_attribution(frame)

    assert pd.api.types.is_float_dtype(confidence)
    assert confidence.iloc[0] == pytest.approx(0.5)
    assert np.isnan(confidence.iloc[1])
