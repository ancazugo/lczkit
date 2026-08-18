"""Making an already-written run openable in a GIS, without re-running it.

`write_run` emits `units.gpkg` and records the CRS in the manifest, but every run written before
that did neither — and a metropolitan run is ten minutes, so re-running one to change how it is
packaged would be the wrong trade. This converts a run directory in place.

**It reads only what the run already wrote and adds only what was missing.** No parameter is
recomputed, no geometry is moved, and nothing that exists is overwritten except a `units.gpkg`
this function itself produced. The manifest gains `crs`, `crs_wkt`, an `extent` and a mention in
`outputs`; every other field is left exactly as the run wrote it, because a manifest is the record
of what was measured and this is not a re-measurement.

The extent is reconstructed from the units' own bounds and tagged `kind="recovered"` rather than
presented as what the run was asked for. A reconstruction is bounded by the units that were
written, which is not the same rectangle as the window that was requested — a grid overhangs its
bbox by up to a cell on each side — and there is nothing on disk that says which city was named.
Recording it under a distinct kind is what stops a later reader treating the two as equivalent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
from pyproj import CRS

from lczkit.output.extent import ExtentRecord
from lczkit.output.writer import GPKG_FILE, MANIFEST_FILE, UNITS_FILE, write_gpkg


@dataclass(frozen=True)
class GisExport:
    """What `export_gis` found and what it wrote."""

    run_dir: Path
    units_gpkg: Path
    crs: str | None
    """The authority code, or `None` where the CRS carries none — see `RunManifest.crs`."""

    n_units: int

    extent: ExtentRecord | None
    """The window recovered from the units' bounds, or `None` where the manifest already had one.

    Never overwrites a recorded extent: a run that stated where it was knows better than a
    reconstruction from the units it happened to write.
    """

    manifest_updated: bool
    """False where the manifest already carried the CRS and the extent, or where there is no
    manifest."""


def export_gis(run_dir: Path) -> GisExport:
    """Write `units.gpkg` beside an existing run's `units.parquet` and record its CRS.

    Raises `FileNotFoundError` naming the path when the run has no `units.parquet`, because the
    alternative is a `pyarrow` error several frames down that does not say which directory was
    wrong — and the likeliest mistake here is pointing at `output/lczkit/` rather than at one run.
    """
    units_path = run_dir / UNITS_FILE
    if not units_path.exists():
        raise FileNotFoundError(f"no {UNITS_FILE} in {run_dir}; this is not a run directory")

    table = gpd.read_parquet(units_path)
    gpkg_path = write_gpkg(run_dir, table)
    epsg = None if table.crs is None else table.crs.to_epsg()
    crs = None if epsg is None else f"EPSG:{epsg}"
    extent = _recover_extent(table)
    updated, recorded = _backfill_manifest(run_dir, crs, table.crs, extent)
    return GisExport(
        run_dir=run_dir,
        units_gpkg=gpkg_path,
        crs=crs,
        n_units=len(table),
        extent=recorded,
        manifest_updated=updated,
    )


def _recover_extent(table: gpd.GeoDataFrame) -> ExtentRecord | None:
    """The lon/lat window the written units cover, or `None` where they carry no CRS.

    Reprojecting the *bounds* rather than the geometry: this is a rectangle in a UTM zone being
    described in degrees, so the answer is approximate at the corners by construction, and that is
    the right amount of precision for a field whose purpose is to say roughly where a run was.
    """
    if table.crs is None or table.empty:
        return None
    minx, miny, maxx, maxy = table.to_crs("EPSG:4326").total_bounds
    return ExtentRecord(kind="recovered", bbox=(float(minx), float(miny), float(maxx), float(maxy)))


def _backfill_manifest(
    run_dir: Path, crs: str | None, projection: CRS | None, extent: ExtentRecord | None
) -> tuple[bool, ExtentRecord | None]:
    """Add `crs`, `crs_wkt`, `extent` and `units.gpkg` to a manifest that predates them.

    Edited as JSON rather than round-tripped through `RunManifest`, deliberately. Validating an
    old manifest against today's model would rewrite it to today's schema — filling defaults for
    fields the run never had and dropping any it carried that the model has since renamed — which
    would quietly make an archived run look like it was produced by code that did not produce it.
    """
    path = run_dir / MANIFEST_FILE
    if not path.exists():
        return False, None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    recorded = manifest.get("extent")
    missing_extent = recorded is None and extent is not None
    if (
        manifest.get("crs") == crs
        and GPKG_FILE in manifest.get("outputs", [])
        and not missing_extent
    ):
        return False, None
    manifest["crs"] = crs
    manifest["crs_wkt"] = None if projection is None else projection.to_wkt()
    if missing_extent:
        assert extent is not None
        manifest["extent"] = extent.model_dump(mode="json")
    outputs = list(manifest.get("outputs", []))
    if GPKG_FILE not in outputs:
        # After the three files a run always writes, before the `layers/` entries, matching the
        # order `write_run` builds the list in so a backfilled run and a fresh one agree.
        insert_at = min(len(outputs), 3)
        outputs.insert(insert_at, GPKG_FILE)
    manifest["outputs"] = outputs
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return True, extent if missing_extent else None
