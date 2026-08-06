"""Unit tests for `LocalRasterSource`, against hand-built rasters with checkable arithmetic."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from conftest import write_class_raster
from shapely.geometry import box

from lczkit.config import LandCoverDatasetConfig, Settings
from lczkit.landcover.local import LocalRasterSource

CRS = "EPSG:32633"
COLUMNS = ["frac_tree", "frac_pervious", "frac_impervious"]


def _config(**overrides: object) -> LandCoverDatasetConfig:
    kwargs: dict[str, object] = {
        "name": "test",
        "source_dir_name": "Test",
        "classes": ["tree", "pervious", "impervious"],
        "value_classes": {10: "tree", 30: "pervious", 50: "impervious"},
    }
    kwargs.update(overrides)
    return LandCoverDatasetConfig(**kwargs)  # type: ignore[arg-type]


def _units(*geoms: object) -> gpd.GeoDataFrame:
    ids = [f"unit_{i}" for i in range(len(geoms))]
    return gpd.GeoDataFrame({"unit_id": ids}, geometry=list(geoms), crs=CRS).set_index("unit_id")


@pytest.fixture
def raster(tmp_path: Path) -> Path:
    """A 4x4 grid of 10 m cells covering (0, 0)-(40, 40). Left half tree, right half impervious,
    with one nodata cell in the bottom-right."""
    return write_class_raster(
        tmp_path / "cover.tif",
        np.array(
            [
                [10, 10, 50, 50],
                [10, 10, 50, 50],
                [10, 10, 50, 50],
                [10, 10, 50, 0],
            ]
        ),
        origin=(0.0, 40.0),
        cell_size_m=10.0,
        crs=CRS,
        nodata=0.0,
    )


def test_fractions_sum_to_one_and_split_by_covered_area(raster: Path) -> None:
    units = _units(box(0, 10, 40, 40))  # the three fully-valid rows: 6 tree, 6 impervious

    result = LocalRasterSource(_config(), raster).fractions(units)

    assert list(result.columns) == COLUMNS
    assert result.loc["unit_0"].tolist() == pytest.approx([0.5, 0.0, 0.5])
    assert result.sum(axis=1).iloc[0] == pytest.approx(1.0)


def test_partial_cell_coverage_is_weighted_exactly(raster: Path) -> None:
    """The reason this uses `exactextract` rather than Phase 3's `all_touched` rasterization.

    The unit covers one whole tree cell (100 m^2) and half an impervious one (50 m^2), so the
    split is 2:1. `all_touched` would count both cells whole and report 0.5 / 0.5 — a 17-point
    error, and a 100 m unit against a 10 m product has ~40 boundary cells out of ~100.
    """
    units = _units(box(10, 20, 25, 30))

    result = LocalRasterSource(_config(), raster).fractions(units)

    assert result.loc["unit_0"].tolist() == pytest.approx([2 / 3, 0.0, 1 / 3])


def test_nodata_leaves_the_denominator(raster: Path) -> None:
    """A unit over one impervious cell and one nodata cell is 100% impervious, not 50%."""
    units = _units(box(20, 0, 40, 10))

    result = LocalRasterSource(_config(), raster).fractions(units)

    assert result.loc["unit_0"].tolist() == pytest.approx([0.0, 0.0, 1.0])


def test_a_class_absent_from_the_data_still_gets_a_column(raster: Path) -> None:
    """Phases 6 and 7 need a schema fixed by config, not by which classes a city happens to hold —
    the same argument Phase 3's `height_frac_*` columns make."""
    result = LocalRasterSource(_config(), raster).fractions(_units(box(0, 0, 20, 40)))

    assert list(result.columns) == COLUMNS
    assert result.loc["unit_0", "frac_pervious"] == 0.0


def test_a_unit_outside_the_raster_is_null_not_zero(raster: Path) -> None:
    """ "The raster does not cover this unit" and "0% of it is tree" are different statements —
    the same call `height_metrics` makes for a unit holding no buildings."""
    units = _units(box(0, 0, 40, 40), box(1000, 1000, 1040, 1040))

    result = LocalRasterSource(_config(), raster).fractions(units)

    assert np.isfinite(result.loc["unit_0"]).all()
    assert result.loc["unit_1"].isna().all()


def test_a_unit_covering_only_nodata_is_null(raster: Path) -> None:
    result = LocalRasterSource(_config(), raster).fractions(_units(box(31, 1, 39, 9)))

    assert result.loc["unit_0"].isna().all()


def test_every_unit_is_returned_in_the_original_order(raster: Path) -> None:
    units = _units(box(0, 0, 10, 10), box(1000, 1000, 1010, 1010), box(20, 20, 30, 30))

    result = LocalRasterSource(_config(), raster).fractions(units)

    assert result.index.equals(units.index)
    assert result.index.name == "unit_id"
    assert isinstance(result, pd.DataFrame)


def test_units_are_reprojected_to_the_rasters_crs(tmp_path: Path) -> None:
    """The raster owns the CRS: `exactextract` does not reproject, and warping a categorical
    raster would resample class codes into values that mean nothing."""
    raster = write_class_raster(
        tmp_path / "geographic.tif",
        np.array([[10, 50]]),
        origin=(13.0, 53.0),
        cell_size_m=0.001,
        crs="EPSG:4326",
        nodata=0.0,
    )
    units = gpd.GeoDataFrame(
        {"unit_id": ["unit_0"]}, geometry=[box(13.0, 52.999, 13.002, 53.0)], crs="EPSG:4326"
    ).to_crs("EPSG:32633")
    units = units.set_index("unit_id")

    result = LocalRasterSource(_config(), raster).fractions(units)

    assert result.loc["unit_0"].tolist() == pytest.approx([0.5, 0.0, 0.5], abs=0.01)


def test_a_geographic_units_crs_raises(raster: Path) -> None:
    units = _units(box(0, 0, 40, 40)).to_crs("EPSG:4326")

    with pytest.raises(ValueError, match="projected"):
        LocalRasterSource(_config(), raster).fractions(units)


def test_units_must_be_indexed_by_unit_id(raster: Path) -> None:
    units = _units(box(0, 0, 40, 40)).reset_index()

    with pytest.raises(ValueError, match="unit_id"):
        LocalRasterSource(_config(), raster).fractions(units)


def test_a_duplicate_unit_id_raises(raster: Path) -> None:
    units = _units(box(0, 0, 40, 40), box(0, 0, 40, 40))
    units.index = pd.Index(["a", "a"], name="unit_id")

    with pytest.raises(ValueError, match="unique"):
        LocalRasterSource(_config(), raster).fractions(units)


def test_an_empty_units_layer_gives_an_empty_but_correctly_shaped_table(raster: Path) -> None:
    result = LocalRasterSource(_config(), raster).fractions(_units())

    assert list(result.columns) == COLUMNS
    assert result.empty


def test_an_oversized_window_raises_rather_than_exhausting_memory(raster: Path) -> None:
    source = LocalRasterSource(_config(), raster, max_raster_cells=4)

    with pytest.raises(ValueError, match="max_raster_cells"):
        source.fractions(_units(box(0, 0, 40, 40)))


def test_an_unmapped_raster_value_raises(tmp_path: Path) -> None:
    raster = write_class_raster(
        tmp_path / "surprise.tif",
        np.array([[10, 77]]),
        origin=(0.0, 10.0),
        cell_size_m=10.0,
        crs=CRS,
        nodata=0.0,
    )

    with pytest.raises(ValueError, match="not covered by value_classes"):
        LocalRasterSource(_config(), raster).fractions(_units(box(0, 0, 20, 10)))


def test_from_settings_reports_an_unavailable_product_plainly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The normal state of both MVP datasets: the product is simply not on this system."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings = Settings.load(dotenv_path=tmp_path / "absent.env")

    with pytest.raises(ValueError, match="no filename configured"):
        LocalRasterSource.from_settings(settings, "worldcover")


def test_from_settings_raises_when_a_configured_file_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Naming a file that is not there is a misconfiguration, not an absence — the same
    distinction `build_cascade` draws for a height tier."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings = Settings.load(dotenv_path=tmp_path / "absent.env")
    settings.land_cover.dataset("worldcover").filename = "absent.tif"

    with pytest.raises(FileNotFoundError, match="absent.tif"):
        LocalRasterSource.from_settings(settings, "worldcover")


def test_from_settings_resolves_the_path_through_source_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raster: Path
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings = Settings.load(dotenv_path=tmp_path / "absent.env")
    target = settings.source_dir("ESA_WorldCover")
    target.mkdir(parents=True)
    (target / "cover.tif").write_bytes(raster.read_bytes())
    settings.land_cover.dataset("worldcover").filename = "cover.tif"

    source = LocalRasterSource.from_settings(settings, "worldcover")

    assert source.path == target / "cover.tif"
    assert source.max_raster_cells == settings.land_cover.max_raster_cells
