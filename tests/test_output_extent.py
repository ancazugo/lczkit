"""A run directory says what ground it covered.

Before `ExtentRecord` existed it could not. The extent is an argument to `run_pipeline`, so it is
in no `Settings` field and therefore in none of the `config` block the manifest serialises —
checked across every run on this system at the time: no bbox, no place name, nothing. It is the
same structural gap Phase 19 closed for the CRS, and the same rule closes it.
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import box

from lczkit.output.extent import ExtentRecord, bbox_area_km2
from lczkit.output.gis import export_gis
from lczkit.output.writer import MANIFEST_FILE, UNITS_FILE

BERLIN = (13.120923, 52.376261, 13.665359, 52.658830)


def test_the_area_is_derived_from_the_bbox_rather_than_supplied() -> None:
    """Two fields that could disagree are one field and a derivation."""
    record = ExtentRecord(kind="bbox", bbox=BERLIN, area_km2=1.0)

    assert record.area_km2 == pytest.approx(bbox_area_km2(BERLIN))
    assert 1_000 < record.area_km2 < 1_300


def test_shrinking_keeps_the_locator_and_records_the_window_it_came_from() -> None:
    record = ExtentRecord(kind="guppd", bbox=BERLIN, name="Berlin", iso="DEU", smod_id="30_3528")
    small = record.shrunk((13.37, 52.50, 13.42, 52.53), 3.0)

    assert small.kind == "guppd"
    assert small.name == "Berlin"
    assert small.smod_id == "30_3528"
    assert small.extent_km == 3.0
    assert small.source_bbox == BERLIN
    assert small.area_km2 < record.area_km2


def test_shrinking_twice_still_names_the_original_window() -> None:
    """`source_bbox` is the region, not the previous trim, so a re-trimmed run still says how big
    the place it is a sample of was."""
    record = ExtentRecord(kind="guppd", bbox=BERLIN, name="Berlin")
    once = record.shrunk((13.30, 52.45, 13.50, 52.55), 10.0)
    twice = once.shrunk((13.37, 52.50, 13.42, 52.53), 3.0)

    assert twice.source_bbox == BERLIN


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (ExtentRecord(kind="bbox", bbox=BERLIN), "bbox"),
        (ExtentRecord(kind="recovered", bbox=BERLIN), "recovered extent"),
        (ExtentRecord(kind="guppd", bbox=BERLIN, name="Berlin", iso="DEU"), "Berlin (DEU)"),
        (
            ExtentRecord(kind="so2sat_window", bbox=BERLIN, name="Berlin", side_km=30.0),
            "Berlin So2Sat 30 km window",
        ),
    ],
)
def test_the_label_says_which_locator_produced_the_window(
    record: ExtentRecord, expected: str
) -> None:
    """A GUPPD region and a So2Sat window over the same city are different ground, and the label
    is what a reader sees first."""
    assert record.label == expected


def test_the_record_round_trips_through_json() -> None:
    """It goes into the manifest, which is JSON and is the run's own description of itself."""
    record = ExtentRecord(kind="guppd", bbox=BERLIN, name="São Paulo", query="sao paulo", iso="BRA")
    restored = ExtentRecord.model_validate(json.loads(record.model_dump_json()))

    assert restored == record
    assert restored.name == "São Paulo"


# --------------------------------------------------------------------------- backfill


def _archived_run(tmp_path: Path, *, extent: dict | None = None) -> Path:
    """A minimal run directory of the shape `lczkit export` has to cope with."""
    run_dir = tmp_path / "20260101T000000Z"
    run_dir.mkdir()
    units = gpd.GeoDataFrame(
        {"lcz_primary": [2, 5]},
        geometry=[
            box(390_000, 5_819_000, 390_100, 5_819_100),
            box(390_100, 5_819_000, 390_200, 5_819_100),
        ],
        crs="EPSG:32633",
    )
    units.index.name = "unit_id"
    units.to_parquet(run_dir / UNITS_FILE)
    manifest = {"run_id": "20260101T000000Z", "outputs": [UNITS_FILE, MANIFEST_FILE]}
    if extent is not None:
        manifest["extent"] = extent
    (run_dir / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return run_dir


def test_export_recovers_an_extent_for_a_run_that_recorded_none(tmp_path: Path) -> None:
    run_dir = _archived_run(tmp_path)

    result = export_gis(run_dir)
    manifest = json.loads((run_dir / MANIFEST_FILE).read_text(encoding="utf-8"))

    assert result.extent is not None
    assert manifest["extent"]["kind"] == "recovered"
    west, south, east, north = manifest["extent"]["bbox"]
    assert -180 <= west < east <= 180
    assert -90 <= south < north <= 90


def test_a_recovered_extent_is_never_labelled_as_a_recorded_one(tmp_path: Path) -> None:
    """A reconstruction is bounded by the units that were written, not by the window requested —
    a grid overhangs its bbox by up to a cell — and nothing on disk says which city was named.
    The distinct kind is what stops the two being read as equivalent.
    """
    run_dir = _archived_run(tmp_path)
    before = json.loads((run_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
    assert "extent" not in before

    export_gis(run_dir)
    recovered = json.loads((run_dir / MANIFEST_FILE).read_text(encoding="utf-8"))["extent"]

    assert recovered["kind"] == "recovered"
    assert recovered["name"] is None
    assert recovered["smod_id"] is None


def test_export_never_overwrites_an_extent_the_run_recorded(tmp_path: Path) -> None:
    """A run that stated where it was knows better than a reconstruction from its own output."""
    recorded = ExtentRecord(
        kind="guppd", bbox=BERLIN, name="Berlin", iso="DEU", smod_id="30_3528"
    ).model_dump(mode="json")
    run_dir = _archived_run(tmp_path, extent=recorded)

    result = export_gis(run_dir)
    manifest = json.loads((run_dir / MANIFEST_FILE).read_text(encoding="utf-8"))

    assert result.extent is None
    assert manifest["extent"]["name"] == "Berlin"
    assert manifest["extent"]["kind"] == "guppd"


def test_export_leaves_the_archival_parquet_byte_identical(tmp_path: Path) -> None:
    """The GeoParquet is the archive. Packaging a run for a GIS must not rewrite it."""
    run_dir = _archived_run(tmp_path)
    before = (run_dir / UNITS_FILE).read_bytes()

    export_gis(run_dir)

    assert (run_dir / UNITS_FILE).read_bytes() == before


def test_export_is_idempotent(tmp_path: Path) -> None:
    run_dir = _archived_run(tmp_path)

    first = export_gis(run_dir)
    after_first = (run_dir / MANIFEST_FILE).read_text(encoding="utf-8")
    second = export_gis(run_dir)

    assert first.manifest_updated is True
    assert second.manifest_updated is False
    assert (run_dir / MANIFEST_FILE).read_text(encoding="utf-8") == after_first
