"""`inherit_heights` — carrying the cascade's result from `buildings_area` onto `buildings_topo`.

The cascade runs once, on the complete layer. These tests pin the rule that gets its answers to the
other one, and in particular that the rule is *largest overlap* rather than the shared
`building_id`: a dissolved topological feature keeps one arbitrary constituent's id, and on real
data that constituent is as likely to be an absorbed shed as the block that absorbed it.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box

from lczkit.heights.inherit import INHERITED_COLUMNS, inherit_heights

CRS = "EPSG:32633"


def _source(geoms: list, heights: list[float | None], sources: list[str] | None = None):
    return gpd.GeoDataFrame(
        {
            "height": heights,
            "height_source": sources or ["overture_height"] * len(geoms),
            "height_confidence": [0.9] * len(geoms),
        },
        geometry=geoms,
        crs=CRS,
    )


def _target(geoms: list) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=geoms, crs=CRS)


def test_a_footprint_takes_the_height_of_what_it_overlaps_most() -> None:
    """The dissolve case in miniature: a topological feature covering a 400 m2 block and a 4 m2
    shed must read as the block. Under a `building_id` join it could read as either."""
    block = box(0, 0, 20, 20)
    shed = box(20, 0, 22, 2)
    dissolved = box(0, 0, 22, 20)  # what absorbing the shed into the block produces

    result = inherit_heights(_target([dissolved]), _source([block, shed], [30.0, 2.5]))

    assert result["height"].iloc[0] == pytest.approx(30.0)


def test_the_source_columns_all_travel_together() -> None:
    result = inherit_heights(
        _target([box(0, 0, 10, 10)]),
        _source([box(0, 0, 10, 10)], [12.0], ["ghsl"]),
    )

    assert list(INHERITED_COLUMNS) == ["height", "height_source", "height_confidence"]
    assert result["height_source"].iloc[0] == "ghsl"
    assert result["height_confidence"].iloc[0] == pytest.approx(0.9)


def test_a_footprint_overlapping_nothing_keeps_a_null_height_rather_than_being_dropped() -> None:
    """`street_profile` skips null-height buildings when averaging tick heights, so an unresolved
    footprint degrades the aspect ratio's coverage rather than its value. Dropping it would remove
    a wall from a canyon that has one."""
    result = inherit_heights(
        _target([box(0, 0, 10, 10), box(500, 500, 510, 510)]),
        _source([box(0, 0, 10, 10)], [12.0]),
    )

    assert len(result) == 2
    assert result["height"].iloc[0] == pytest.approx(12.0)
    assert result["height"].isna().iloc[1]


def test_a_null_source_height_stays_null_rather_than_falling_through_to_a_neighbour() -> None:
    """The cascade leaving a building unresolved is information. Inheriting a neighbour's height
    to fill the gap would be imputation, which Phase 3 refuses on purpose."""
    result = inherit_heights(
        _target([box(0, 0, 30, 10)]),
        _source([box(0, 0, 20, 10), box(20, 0, 30, 10)], [np.nan, 8.0]),
    )

    assert result["height"].isna().all()


def test_an_existing_height_column_on_the_target_is_replaced_not_duplicated() -> None:
    target = _target([box(0, 0, 10, 10)]).assign(height=99.0, height_source="stale")

    result = inherit_heights(target, _source([box(0, 0, 10, 10)], [12.0]))

    assert list(result.columns).count("height") == 1
    assert result["height"].iloc[0] == pytest.approx(12.0)


def test_a_source_that_has_not_been_through_the_cascade_is_refused() -> None:
    with pytest.raises(ValueError, match="fill_heights"):
        inherit_heights(_target([box(0, 0, 10, 10)]), _target([box(0, 0, 10, 10)]))


def test_mismatched_crs_is_refused_rather_than_silently_missing_every_overlap() -> None:
    source = _source([box(0, 0, 10, 10)], [12.0]).to_crs("EPSG:32634")

    with pytest.raises(ValueError, match="crs"):
        inherit_heights(_target([box(0, 0, 10, 10)]), source)


def test_an_empty_target_comes_back_empty_with_the_columns_present() -> None:
    result = inherit_heights(_target([]), _source([box(0, 0, 10, 10)], [12.0]))

    assert result.empty
    assert set(INHERITED_COLUMNS) <= set(result.columns)
