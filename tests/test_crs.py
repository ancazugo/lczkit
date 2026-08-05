"""Tests for lczkit.crs.assert_projected_crs."""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import Point

from lczkit.crs import assert_projected_crs


def _gdf(crs: str | None) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=[Point(0, 0)], crs=crs)


def test_passes_for_projected_crs() -> None:
    assert_projected_crs(_gdf("EPSG:32633"))  # UTM zone 33N


def test_raises_for_geographic_crs() -> None:
    with pytest.raises(ValueError, match="geographic CRS"):
        assert_projected_crs(_gdf("EPSG:4326"))


def test_raises_for_missing_crs() -> None:
    with pytest.raises(ValueError, match="no CRS"):
        assert_projected_crs(_gdf(None))
