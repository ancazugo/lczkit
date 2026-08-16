"""Converting a run that is already on disk, without re-running it.

The property under test is restraint: `export_gis` must add what was missing and change nothing
else. A run directory is an archived measurement, and a packaging step that silently rewrote it to
today's schema would make an old run look like it came from code that did not produce it.
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import box

from lczkit.output import GPKG_FILE, GPKG_LAYER, MANIFEST_FILE, UNITS_FILE, export_gis

CRS = "EPSG:32633"


@pytest.fixture
def legacy_run(tmp_path: Path) -> Path:
    """A run directory as written before `units.gpkg` and the manifest's `crs` field existed."""
    run_dir = tmp_path / "20260101T000000Z"
    run_dir.mkdir()
    units = gpd.GeoDataFrame(
        {"unit_id": [f"grid_{index}" for index in range(3)], "lcz_primary": [2, 5, 17]},
        geometry=[box(index * 100.0, 0.0, index * 100.0 + 100.0, 100.0) for index in range(3)],
        crs=CRS,
    ).set_index("unit_id")
    units.to_parquet(run_dir / UNITS_FILE)
    (run_dir / MANIFEST_FILE).write_text(
        json.dumps(
            {
                "run_id": "20260101T000000Z",
                "overture_release": "2026-07-22.0",
                "outputs": [UNITS_FILE, "units_viz.parquet", MANIFEST_FILE, "layers/water.parquet"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return run_dir


def test_an_existing_run_gains_a_geopackage_carrying_its_crs(legacy_run: Path) -> None:
    result = export_gis(legacy_run)

    stored = gpd.read_file(result.units_gpkg, layer=GPKG_LAYER)

    assert result.units_gpkg == legacy_run / GPKG_FILE
    assert result.crs == CRS
    assert result.n_units == 3
    assert stored.crs.to_epsg() == 32633
    assert sorted(stored["unit_id"]) == ["grid_0", "grid_1", "grid_2"]
    assert stored["lcz_primary"].to_list() == [2, 5, 17]


def test_the_manifest_gains_the_crs_and_keeps_everything_it_already_said(legacy_run: Path) -> None:
    """A manifest is the record of what was measured. Backfilling two absent fields is packaging;
    revalidating it against today's model would be a rewrite."""
    before = json.loads((legacy_run / MANIFEST_FILE).read_text(encoding="utf-8"))

    result = export_gis(legacy_run)
    after = json.loads((legacy_run / MANIFEST_FILE).read_text(encoding="utf-8"))

    assert result.manifest_updated
    assert after["crs"] == CRS
    assert "UTM zone 33N" in after["crs_wkt"]
    assert after["run_id"] == before["run_id"]
    assert after["overture_release"] == before["overture_release"]
    assert after["outputs"] == [
        UNITS_FILE,
        "units_viz.parquet",
        MANIFEST_FILE,
        GPKG_FILE,
        "layers/water.parquet",
    ]


def test_exporting_twice_leaves_the_manifest_alone_the_second_time(legacy_run: Path) -> None:
    export_gis(legacy_run)
    first = (legacy_run / MANIFEST_FILE).read_text(encoding="utf-8")

    result = export_gis(legacy_run)

    assert not result.manifest_updated
    assert (legacy_run / MANIFEST_FILE).read_text(encoding="utf-8") == first


def test_the_archival_parquet_is_not_touched(legacy_run: Path) -> None:
    before = (legacy_run / UNITS_FILE).read_bytes()

    export_gis(legacy_run)

    assert (legacy_run / UNITS_FILE).read_bytes() == before


def test_a_directory_that_is_not_a_run_says_so_rather_than_failing_further_down(
    tmp_path: Path,
) -> None:
    """The likely mistake is pointing at `output/lczkit/` rather than at one run inside it."""
    with pytest.raises(FileNotFoundError, match="not a run directory"):
        export_gis(tmp_path)


def test_a_run_with_no_manifest_still_gets_its_geopackage(legacy_run: Path) -> None:
    (legacy_run / MANIFEST_FILE).unlink()

    result = export_gis(legacy_run)

    assert result.units_gpkg.exists()
    assert not result.manifest_updated
