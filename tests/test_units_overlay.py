"""The one definition of "intersect a layer with the units and measure the pieces".

Five near-identical private helpers used to spell this out, in `ucp.industrial` and
`ucp.semantics`. What they disagreed about is what these tests pin: whether overlapping features
are dissolved before their area is counted, and whether a unit nothing reaches reports zero or
null.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, box

from lczkit.units.overlay import (
    PIECE_AREA,
    area_in_units,
    covered_fraction,
    share_of,
    unit_pieces,
)

CRS = "EPSG:32633"


@pytest.fixture
def units() -> gpd.GeoDataFrame:
    """Two adjacent 100 x 100 m cells, indexed as the unit of exchange requires."""
    frame = gpd.GeoDataFrame(geometry=[box(0, 0, 100, 100), box(100, 0, 200, 100)], crs=CRS)
    frame.index = pd.Index(["a", "b"], name="unit_id")
    return frame


def layer(*geometries: object, **columns: list) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(columns, geometry=list(geometries), crs=CRS)


# --------------------------------------------------------------------------- the intersection


def test_a_feature_straddling_a_boundary_contributes_its_share_to_each_side(
    units: gpd.GeoDataFrame,
) -> None:
    """The Phase 3 splitting rule, and the reason every fraction here shares a denominator with
    `building_surface_fraction`: assigning a whole footprint to one side would make two parameters
    describe subtly different populations."""
    pieces = unit_pieces(units, layer(box(50, 0, 150, 100)))

    assert dict(pieces.groupby("unit_id")[PIECE_AREA].sum()) == pytest.approx(
        {"a": 5_000.0, "b": 5_000.0}
    )


def test_the_requested_attributes_come_through(units: gpd.GeoDataFrame) -> None:
    """Selecting a semantic group is then a mask over pieces that already exist, rather than a
    second intersection of the whole layer."""
    pieces = unit_pieces(
        units,
        layer(box(10, 10, 20, 20), box(110, 10, 120, 20), subtype=["industrial", "retail"]),
        columns=("subtype", "class"),
    )

    assert list(pieces["subtype"]) == ["industrial", "retail"]
    assert "class" not in pieces.columns  # absent on the layer, so skipped rather than raised


def test_a_layer_whose_geometry_column_is_not_called_geometry_still_works(
    units: gpd.GeoDataFrame,
) -> None:
    """geopandas refuses to rename a column to the name it already has, so the rename has to be
    conditional. Unconditional, this raised for every ordinary layer in the package."""
    renamed = layer(box(10, 10, 20, 20)).rename_geometry("geom")

    assert len(unit_pieces(units, renamed)) == 1
    assert len(unit_pieces(units, layer(box(10, 10, 20, 20)))) == 1


def test_a_geoseries_is_accepted_as_well_as_a_frame(units: gpd.GeoDataFrame) -> None:
    series = gpd.GeoSeries([box(10, 10, 20, 20)], crs=CRS)

    assert area_in_units(units, unit_pieces(units, series))["a"] == pytest.approx(100.0)


def test_an_empty_layer_gives_an_empty_frame_with_the_right_columns(
    units: gpd.GeoDataFrame,
) -> None:
    """Callers branch on `.empty`, never on `None`, so the empty case has to be the same shape."""
    pieces = unit_pieces(units, layer(), columns=("subtype",))

    assert pieces.empty
    assert "unit_id" in pieces.columns and PIECE_AREA in pieces.columns


def test_a_layer_that_misses_the_units_entirely_gives_no_pieces(
    units: gpd.GeoDataFrame,
) -> None:
    assert unit_pieces(units, layer(box(1_000, 1_000, 1_100, 1_100))).empty


def test_lines_are_dropped_unless_the_caller_keeps_them(units: gpd.GeoDataFrame) -> None:
    """`keep_geom_type` defaults to keeping polygons, because an area statistic over a line is
    zero and silently so. `ucp.streets` is the one caller that wants the other behaviour."""
    lines = layer(LineString([(0, 50), (200, 50)]))

    assert unit_pieces(units, lines).empty
    assert not unit_pieces(units, lines, keep_geom_type=False).empty


# --------------------------------------------------------------------------- the reductions


def test_a_unit_nothing_reaches_reports_zero_area_rather_than_null(
    units: gpd.GeoDataFrame,
) -> None:
    """ "Nothing of this layer is here" is a measurement, unlike a land-cover fraction over ground
    the raster never covered."""
    pieces = unit_pieces(units, layer(box(10, 10, 20, 20)))
    areas = area_in_units(units, pieces)

    assert areas["a"] == pytest.approx(100.0)
    assert areas["b"] == 0.0
    assert not areas.isna().any()


def test_dissolving_counts_shared_ground_once(units: gpd.GeoDataFrame) -> None:
    """The property the land-use path exists for. Milan's parcels sum to 106.6% of its bbox, so a
    fraction that does not dissolve can exceed 1.0 — which is not a number a share can take."""
    overlapping = layer(box(0, 0, 80, 100), box(20, 0, 100, 100))

    pieces = unit_pieces(units, overlapping)
    assert covered_fraction(units, pieces, dissolve=False)["a"] == pytest.approx(1.6)
    assert covered_fraction(units, pieces, dissolve=True)["a"] == pytest.approx(1.0)


def test_dissolving_changes_nothing_for_a_layer_that_does_not_overlap_itself(
    units: gpd.GeoDataFrame,
) -> None:
    """Which is why `buildings_area` does not pay for it: `trim_overlaps` has already made it
    disjoint, and a union is superlinear."""
    disjoint = layer(box(0, 0, 40, 100), box(60, 0, 100, 100))
    pieces = unit_pieces(units, disjoint)

    assert covered_fraction(units, pieces, dissolve=False)["a"] == pytest.approx(
        covered_fraction(units, pieces, dissolve=True)["a"]
    )


def test_dissolving_per_unit_equals_dissolving_the_whole_layer_first(
    units: gpd.GeoDataFrame,
) -> None:
    """The equality that lets the safe form replace the unsafe one.

    `ucp.industrial` reached this quantity through a whole-layer `union_all`, which is superlinear
    and — over real Overture land use — raises `GEOSException: side location conflict` even after
    `make_valid`. The union of the clipped pieces inside a unit is the clip of the global union, so
    clipping first is not an approximation.
    """
    overlapping = layer(box(0, 0, 80, 100), box(20, 0, 120, 100), box(90, 0, 200, 100))

    per_unit = covered_fraction(units, unit_pieces(units, overlapping), dissolve=True)
    globally = covered_fraction(
        units,
        unit_pieces(units, gpd.GeoSeries([overlapping.union_all()], crs=CRS)),
        dissolve=False,
    )

    pd.testing.assert_series_equal(per_unit, globally, atol=1e-12)


def test_a_share_of_nothing_is_null_rather_than_zero() -> None:
    """0.0 tells a downstream rule that a cell definitely is not industrial; null tells it there
    was nothing to judge. The LCZ 10 rule reads this distinction."""
    numerator = pd.Series([0.0, 5.0], index=["a", "b"])
    denominator = pd.Series([0.0, 10.0], index=["a", "b"])

    result = share_of(numerator, denominator)

    assert pd.isna(result["a"])
    assert result["b"] == pytest.approx(0.5)


def test_a_zero_area_unit_does_not_produce_an_infinite_fraction(
    units: gpd.GeoDataFrame,
) -> None:
    degenerate = units.copy()
    degenerate.geometry = [box(0, 0, 0, 0), box(100, 0, 200, 100)]
    pieces = unit_pieces(degenerate, layer(box(100, 0, 150, 100)))

    fraction = covered_fraction(degenerate, pieces, dissolve=False)

    assert pd.isna(fraction["a"])
    assert fraction["b"] == pytest.approx(0.5)


def test_a_frame_that_is_not_the_unit_of_exchange_is_refused_here(
    units: gpd.GeoDataFrame,
) -> None:
    """The entry contract, checked at the entry rather than several lines in.

    Everything downstream groups by `unit_id`, so a differently-indexed frame fails with a
    `KeyError` naming a column the caller never mentioned — and a geographic CRS does not fail at
    all, it reports areas in square degrees.
    """
    renamed = units.copy()
    renamed.index = renamed.index.rename("cell")
    with pytest.raises(ValueError, match="unit_id"):
        unit_pieces(renamed, layer(box(10, 10, 20, 20)))

    geographic = units.to_crs("EPSG:4326")
    with pytest.raises(ValueError):
        unit_pieces(geographic, layer(box(10, 10, 20, 20)).to_crs("EPSG:4326"))
