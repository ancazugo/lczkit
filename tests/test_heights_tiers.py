"""Unit tests for the individual height tiers, against small hand-built geometries."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from conftest import write_height_raster
from shapely.geometry import box

from lczkit.config import ArealTierConfig, HeightConfig
from lczkit.heights.provenance import HEIGHT_PROPERTY
from lczkit.heights.tiers import (
    OVERTURE_HEIGHT,
    OVERTURE_NUM_FLOORS,
    ArealRasterTier,
    OvertureAttributeTier,
    build_cascade,
)

CRS = "EPSG:32633"


def _tier1(**overrides: float) -> OvertureAttributeTier:
    kwargs: dict[str, float] = {
        "storey_height_m": 3.0,
        "height_confidence": 0.9,
        "num_floors_confidence": 0.6,
    }
    kwargs.update(overrides)
    return OvertureAttributeTier(**kwargs)  # type: ignore[arg-type]


def _buildings(**cols: list) -> gpd.GeoDataFrame:
    n = len(next(iter(cols.values())))
    geoms = [box(100 * i, 0, 100 * i + 50, 50) for i in range(n)]
    return gpd.GeoDataFrame(cols, geometry=geoms, crs=CRS)


def test_tier1_prefers_height_over_num_floors() -> None:
    gdf = _buildings(height=[12.0], num_floors=[10])

    filled = _tier1().fill(gdf)

    assert filled["height"].tolist() == [12.0]
    assert filled["height_source"].tolist() == [OVERTURE_HEIGHT]
    assert filled["height_confidence"].tolist() == [0.9]


def test_tier1_derives_height_from_num_floors() -> None:
    gdf = _buildings(height=[None], num_floors=[4])

    filled = _tier1(storey_height_m=3.5).fill(gdf)

    assert filled["height"].tolist() == [14.0]
    assert filled["height_source"].tolist() == [OVERTURE_NUM_FLOORS]
    assert filled["height_confidence"].tolist() == [0.6]


def test_tier1_leaves_a_building_with_neither_attribute_unresolved() -> None:
    gdf = _buildings(height=[None], num_floors=[None])

    filled = _tier1().fill(gdf)

    assert filled["height"].isna().all()
    assert filled["height_source"].isna().all()


@pytest.mark.parametrize("bad_height", [0.0, -3.0, np.inf])
def test_tier1_treats_a_non_positive_height_as_absent(bad_height: float) -> None:
    """A zero or negative height is not a measurement. Clearing it matters: leaving it in place
    would hand the next tier a row that looks resolved and produce a zero-height building."""
    gdf = _buildings(height=[bad_height], num_floors=[None])

    filled = _tier1().fill(gdf)

    assert filled["height"].isna().all()
    assert filled["height_source"].isna().all()


def test_tier1_prefers_overtures_own_confidence_where_it_exists() -> None:
    """A quarter of the Berlin fixture's tier-1 heights are Microsoft ML values conflated onto
    OSM footprints, and Overture attaches a real confidence to each. That number is better than
    anything config can supply, so it wins."""
    gdf = _buildings(
        height=[15.0, 20.0],
        num_floors=[None, None],
        sources=[
            [{"property": HEIGHT_PROPERTY, "dataset": "Microsoft ML Buildings", "confidence": 0.7}],
            [{"property": "", "dataset": "OpenStreetMap"}],
        ],
    )

    filled = _tier1(height_confidence=0.9).fill(gdf)

    assert filled["height_confidence"].tolist() == [0.7, 0.9]
    assert filled["height_source"].tolist() == [OVERTURE_HEIGHT, OVERTURE_HEIGHT]


@pytest.mark.parametrize(
    ("missing", "expected"),
    [
        ("height_confidence", "overture_height_confidence"),
        ("num_floors_confidence", "overture_num_floors_confidence"),
    ],
)
def test_tier1_raises_when_a_confidence_is_unset(missing: str, expected: str) -> None:
    """`height_confidence` is an ordinal with no published value behind it, so an unset one is
    an error rather than a default — the same stance CleaningConfig takes on its thresholds."""
    with pytest.raises(ValueError, match=expected):
        _tier1(**{missing: None})  # type: ignore[arg-type]


def test_tier1_does_not_mutate_its_input() -> None:
    gdf = _buildings(height=[None], num_floors=[4])

    _tier1().fill(gdf)

    assert gdf["height"].isna().all()
    assert "height_source" not in gdf.columns


@pytest.fixture
def raster(tmp_path: Path) -> Path:
    # 2x2 grid of 100 m cells with its top-left at (0, 200)
    return write_height_raster(
        tmp_path / "areal.tif",
        np.array([[10.0, 20.0], [0.0, -9999.0]]),
        origin=(0.0, 200.0),
        cell_size_m=100.0,
        crs=CRS,
        nodata=-9999.0,
    )


def _at(x: float, y: float) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"height": [None]}, geometry=[box(x - 5, y - 5, x + 5, y + 5)], crs=CRS)


def test_areal_tier_fills_from_the_raster(raster: Path) -> None:
    tier = ArealRasterTier(name="ghsl", path=raster, confidence=0.3)

    filled = tier.fill(_at(50, 150))  # cell holding 10.0

    assert filled["height"].tolist() == [10.0]
    assert filled["height_source"].tolist() == ["ghsl"]
    assert filled["height_confidence"].tolist() == [0.3]


def test_areal_tier_applies_the_unit_scale(raster: Path) -> None:
    """Height products are not all in metres; the scale is config, never assumed."""
    tier = ArealRasterTier(name="ghsl", path=raster, confidence=0.3, scale=0.1)

    assert tier.fill(_at(50, 150))["height"].tolist() == [1.0]


def test_areal_tier_leaves_cells_at_or_below_the_minimum_unresolved(raster: Path) -> None:
    """A zero in an areal height product means "no built volume here", not "a building of zero
    height" — the row must fall through to the next tier."""
    tier = ArealRasterTier(name="ghsl", path=raster, confidence=0.3, min_height_m=0.0)

    filled = tier.fill(_at(50, 50))  # cell holding 0.0

    assert filled["height"].isna().all()
    assert filled["height_source"].isna().all()


def test_areal_tier_leaves_nodata_unresolved(raster: Path) -> None:
    tier = ArealRasterTier(name="ghsl", path=raster, confidence=0.3)

    assert tier.fill(_at(150, 50))["height_source"].isna().all()


def test_areal_tier_never_overwrites_an_earlier_tiers_answer(raster: Path) -> None:
    gdf = _at(50, 150)
    already = _tier1().fill(gdf.assign(height=[7.0]))

    filled = ArealRasterTier(name="ghsl", path=raster, confidence=0.3).fill(already)

    assert filled["height"].tolist() == [7.0]
    assert filled["height_source"].tolist() == [OVERTURE_HEIGHT]


def test_areal_tier_requires_a_projected_crs(raster: Path) -> None:
    tier = ArealRasterTier(name="ghsl", path=raster, confidence=0.3)

    with pytest.raises(ValueError, match="projected"):
        tier.fill(_at(50, 150).to_crs("EPSG:4326"))


def test_build_cascade_skips_tiers_with_no_file(tmp_path: Path) -> None:
    """The normal state of tiers 2-4: the product is simply not on this system. A shorter
    cascade with an honest height_completeness beats a failure."""
    config = HeightConfig(overture_height_confidence=0.9, overture_num_floors_confidence=0.6)

    tiers = build_cascade(config, lambda name: tmp_path / name)

    assert [tier.name for tier in tiers] == ["overture"]


def test_build_cascade_registers_configured_tiers_in_order(tmp_path: Path, raster: Path) -> None:
    config = HeightConfig(
        overture_height_confidence=0.9,
        overture_num_floors_confidence=0.6,
        areal_tiers=[
            ArealTierConfig(name="gob25d", source_dir_name="GOB25D"),  # no file: skipped
            ArealTierConfig(
                name="ghsl",
                source_dir_name="GHSL",
                filename=raster.name,
                confidence=0.3,
            ),
        ],
    )

    tiers = build_cascade(config, lambda name: raster.parent)

    assert [tier.name for tier in tiers] == ["overture", "ghsl"]


def test_build_cascade_raises_when_a_configured_file_is_missing(tmp_path: Path) -> None:
    """Naming a file that is not there is a misconfiguration, not an absence."""
    config = HeightConfig(
        overture_height_confidence=0.9,
        overture_num_floors_confidence=0.6,
        areal_tiers=[
            ArealTierConfig(
                name="ghsl", source_dir_name="GHSL", filename="absent.tif", confidence=0.3
            )
        ],
    )

    with pytest.raises(FileNotFoundError, match="absent.tif"):
        build_cascade(config, lambda name: tmp_path)


def test_build_cascade_rejects_a_duplicate_tier_name() -> None:
    config = HeightConfig(
        overture_height_confidence=0.9,
        overture_num_floors_confidence=0.6,
        areal_tiers=[
            ArealTierConfig(name="ghsl", source_dir_name="A"),
            ArealTierConfig(name="ghsl", source_dir_name="B"),
        ],
    )

    with pytest.raises(ValueError, match="duplicate"):
        build_cascade(config, lambda name: Path(name))


def test_build_cascade_skips_a_disabled_tier_even_with_its_file_present(raster: Path) -> None:
    """`enabled=False` means off, not "off unless the data happens to be there".

    The distinction that makes this worth a test: a tier with no `filename` is skipped because
    the product is absent, and a disabled one is skipped because Phase 10 measured it making the
    map worse. Both produce a shorter cascade, and the serialised config is what tells them
    apart — so the flag has to be read wherever a cascade is assembled, not only where the
    products are placed.
    """
    config = HeightConfig(
        overture_height_confidence=0.9,
        overture_num_floors_confidence=0.6,
        areal_tiers=[
            ArealTierConfig(
                name="gob25d",
                source_dir_name="GOB25D",
                enabled=False,
                filename=raster.name,
                confidence=0.5,
            ),
            ArealTierConfig(
                name="ghsl", source_dir_name="GHSL", filename=raster.name, confidence=0.25
            ),
        ],
    )

    tiers = build_cascade(config, lambda name: raster.parent)

    assert [tier.name for tier in tiers] == ["overture", "ghsl"]


def test_the_shipped_default_cascade_is_coarse() -> None:
    """Phase 11's decision, asserted rather than described.

    Open Buildings 2.5D has the lowest per-building error of the three areal products and the
    only within-unit skill, and Phase 10 measured it *lowering* built-class agreement in 5 of 9
    cities — `Hr` is a geometric mean and dispersion depresses it. It stays implemented and one
    flag from use.
    """
    tiers = {tier.name: tier for tier in HeightConfig().areal_tiers}

    assert set(tiers) == {"gob25d", "wsf3d", "ghsl"}
    assert tiers["gob25d"].enabled is False
    assert tiers["wsf3d"].enabled is True
    assert tiers["ghsl"].enabled is True
    # No floor on any of them: the Phase 10 damage was dispersion, not a low tail, and a
    # threshold tuned until one product stopped hurting would outlive its justification.
    assert [tier.min_height_m for tier in tiers.values()] == [0.0, 0.0, 0.0]
