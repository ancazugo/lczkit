"""Tests for `clean_land_use()` — geometry repair and nothing else."""

from __future__ import annotations

import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon, box

from lczkit.cleaning.land_use import clean_land_use

_CRS = "EPSG:32633"

#: A self-intersecting "bowtie" — invalid, and repaired by `make_valid()` into two lobes.
_BOWTIE = Polygon([(0, 0), (10, 10), (10, 0), (0, 10), (0, 0)])


def _land_use(geoms: list, **cols: list) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({**cols, "geometry": geoms}, crs=_CRS)


def test_repairs_invalid_geometry_without_changing_feature_count() -> None:
    land_use = _land_use([_BOWTIE, box(100, 100, 110, 110)], subtype=["developed", "park"])

    cleaned, step = clean_land_use(land_use)

    assert cleaned.geometry.is_valid.all()
    assert len(cleaned) == len(land_use)
    assert step.n_in == step.n_out == 2
    assert step.detail["n_invalid_before"] == 1


def test_step_is_recorded_under_the_land_use_stage() -> None:
    cleaned, step = clean_land_use(_land_use([box(0, 0, 10, 10)]))

    assert step.stage == "land_use"
    assert step.operation == "fix_invalid_geometries"
    assert len(cleaned) == 1


def test_multipolygons_are_preserved_not_exploded() -> None:
    """A land-use parcel is legitimately multipart, and Phase 5's area overlays handle that.
    Exploding here would inflate the feature count and split one parcel's `class` across rows.
    """
    multi = MultiPolygon([box(0, 0, 10, 10), box(50, 50, 60, 60)])
    land_use = _land_use([multi], **{"class": ["industrial"]})

    cleaned, step = clean_land_use(land_use)

    assert len(cleaned) == 1
    assert cleaned.geometry.iloc[0].geom_type == "MultiPolygon"
    assert step.n_out == 1


def test_attribute_columns_survive() -> None:
    land_use = _land_use([_BOWTIE], subtype=["developed"], **{"class": ["industrial"]})

    cleaned, _ = clean_land_use(land_use)

    assert cleaned["subtype"].tolist() == ["developed"]
    assert cleaned["class"].tolist() == ["industrial"]


def test_input_is_not_mutated() -> None:
    land_use = _land_use([_BOWTIE])

    clean_land_use(land_use)

    assert not land_use.geometry.iloc[0].is_valid
