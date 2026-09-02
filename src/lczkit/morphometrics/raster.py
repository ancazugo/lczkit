"""Rasterizing morphometric attributes to a multiband GeoTIFF at a user-defined resolution.

Not part of the paper — Majer & Fleischmann (2026) never rasterize their 2D attributes, only the
20-attribute subset feeding their fusion schemes (out of scope here, see the module docstring of
`lczkit.morphometrics`). This is a new lczkit capability: one GeoTIFF, one band per attribute,
each pixel the **area-weighted mean** of whichever ETCs overlap it.

Reuses `lczkit.units.overlay.unit_pieces` rather than a new vector-to-raster library — the
overlay-and-measure primitive already in the package is exactly what "which ETCs does this pixel
cover, and how much of each" is. A local, purpose-built grid builder is used rather than stretching
`GridUnits` to a second contract: `GridUnits` takes a lon/lat `bbox` and estimates its own CRS,
which is the wrong shape for a grid built directly over an already-projected ETC layer's own
bounds at an arbitrary resolution.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from lczkit.crs import assert_projected_crs
from lczkit.output.writer import MANIFEST_FILE, MORPHOMETRICS_FILE
from lczkit.units.overlay import PIECE_AREA, unit_pieces

RASTER_FILE = "morphometrics.tif"


@dataclass(frozen=True)
class RasterExportReport:
    """What `rasterize_attributes` wrote, for the run manifest."""

    resolution_m: float
    n_rows: int
    n_cols: int
    band_names: tuple[str, ...]


def _pixel_grid(
    bounds: tuple[float, float, float, float], resolution_m: float
) -> tuple[gpd.GeoDataFrame, int, int]:
    """A regular `resolution_m` grid covering `bounds`, one row per pixel, `row`/`col` attached.

    Row 0 is the **top** row (highest y), matching `rasterio`'s array convention and
    `rasterio.transform.from_origin`'s own origin-at-top-left contract — so the array this module
    builds from `unit_id -> (row, col)` needs no vertical flip before it is written.
    """
    minx, miny, maxx, maxy = bounds
    n_cols = max(1, math.ceil((maxx - minx) / resolution_m))
    n_rows = max(1, math.ceil((maxy - miny) / resolution_m))

    rows: list[int] = []
    cols: list[int] = []
    geoms = []
    for row in range(n_rows):
        y1 = maxy - row * resolution_m
        y0 = y1 - resolution_m
        for col in range(n_cols):
            x0 = minx + col * resolution_m
            geoms.append(box(x0, y0, x0 + resolution_m, y1))
            rows.append(row)
            cols.append(col)

    unit_ids = [f"px_{r}_{c}" for r, c in zip(rows, cols, strict=True)]
    grid = gpd.GeoDataFrame(
        {"unit_id": unit_ids, "row": rows, "col": cols}, geometry=geoms
    ).set_index("unit_id")
    return grid, n_rows, n_cols


def _area_weighted_mean(pieces: pd.DataFrame, column: str, grid_index: pd.Index) -> pd.Series:
    """Area-weighted mean of `column` per `unit_id`, over pieces where `column` is not null.

    Null pieces are dropped from **both** the numerator and the denominator — the weight total
    used is the area that actually carried a value, not the pixel's full covered area. Weighting
    by the full area while summing only non-null values would silently bias every mean toward
    zero wherever an attribute was null on part of a pixel, which is common: several morphometric
    columns are null exactly where an ETC has no qualifying neighbour.
    """
    valid = pieces.loc[pieces[column].notna(), ["unit_id", column, PIECE_AREA]]
    if valid.empty:
        return pd.Series(np.nan, index=grid_index, dtype="float64")
    weighted_sum = (valid[column] * valid[PIECE_AREA]).groupby(valid["unit_id"]).sum()
    weight_total = valid.groupby("unit_id")[PIECE_AREA].sum()
    mean = weighted_sum / weight_total.where(weight_total > 0)
    return mean.reindex(grid_index)


def rasterize_attributes(
    gdf: gpd.GeoDataFrame,
    resolution_m: float,
    out_path: Path,
    *,
    columns: list[str] | None = None,
    max_cells: int = 50_000_000,
) -> RasterExportReport:
    """Write `out_path` as a multiband GeoTIFF, one band per attribute of `gdf`, area-weighted.

    `columns` defaults to every non-geometry column of `gdf`. Raises `ValueError` before building
    the grid if it would exceed `max_cells` — refusing is cheap; an unbounded allocation is not.
    """
    assert_projected_crs(gdf, "gdf")
    if resolution_m <= 0:
        raise ValueError(f"resolution_m must be positive, got {resolution_m}")
    assert gdf.crs is not None  # narrows for mypy; assert_projected_crs already guarantees this
    attribute_columns = (
        columns if columns is not None else [c for c in gdf.columns if c != "geometry"]
    )

    bounds = gdf.total_bounds
    grid, n_rows, n_cols = _pixel_grid((bounds[0], bounds[1], bounds[2], bounds[3]), resolution_m)
    if n_rows * n_cols > max_cells:
        raise ValueError(
            f"a {resolution_m} m grid over this extent would be {n_rows}x{n_cols} = "
            f"{n_rows * n_cols} cells, over the configured ceiling of {max_cells} "
            "(MorphometricsConfig.max_raster_cells)"
        )
    grid = grid.set_geometry(grid.geometry, crs=gdf.crs)

    pieces = unit_pieces(grid, gdf, columns=attribute_columns)
    row_by_unit = grid["row"]
    col_by_unit = grid["col"]

    minx, _, _, maxy = gdf.total_bounds
    transform = from_origin(minx, maxy, resolution_m, resolution_m)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        out_path,
        "w",
        driver="GTiff",
        height=n_rows,
        width=n_cols,
        count=len(attribute_columns),
        dtype="float32",
        crs=gdf.crs.to_wkt(),
        transform=transform,
        nodata=np.nan,
    ) as dst:
        for band_index, column in enumerate(attribute_columns, start=1):
            values = _area_weighted_mean(pieces, column, grid.index)
            array = np.full((n_rows, n_cols), np.nan, dtype="float32")
            array[row_by_unit.to_numpy(), col_by_unit.to_numpy()] = values.to_numpy()
            dst.write(array, band_index)
            dst.set_band_description(band_index, column)

    return RasterExportReport(
        resolution_m=resolution_m, n_rows=n_rows, n_cols=n_cols, band_names=tuple(attribute_columns)
    )


def refresh_raster(
    run_dir: Path,
    resolution_m: float,
    *,
    columns: list[str] | None = None,
    max_cells: int = 50_000_000,
) -> RasterExportReport:
    """Re-derive `morphometrics.tif` from an already-written run's `morphometrics.parquet`.

    The one function both `run_pipeline` (when `--morphometrics-resolution` is given) and
    `lczkit morphometrics raster` call — a run gets the same raster whether it was produced at
    run time or requested afterwards at a different resolution, because both paths go through
    this. Patches the manifest as JSON, the same way `lczkit.output.gis`'s backfill does: this can
    run against a manifest written by an older version of `RunManifest`, and round-tripping it
    through today's model would rewrite fields the run never had.
    """
    morphometrics_path = run_dir / MORPHOMETRICS_FILE
    if not morphometrics_path.exists():
        raise FileNotFoundError(
            f"no {MORPHOMETRICS_FILE} in {run_dir} — this run has no morphometrics to rasterize"
        )
    gdf = gpd.read_parquet(morphometrics_path)
    report = rasterize_attributes(
        gdf, resolution_m, run_dir / RASTER_FILE, columns=columns, max_cells=max_cells
    )

    manifest_path = run_dir / MANIFEST_FILE
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["morphometrics_raster"] = {
            "resolution_m": report.resolution_m,
            "n_rows": report.n_rows,
            "n_cols": report.n_cols,
            "band_names": list(report.band_names),
        }
        outputs = list(manifest.get("outputs", []))
        if RASTER_FILE not in outputs:
            outputs.append(RASTER_FILE)
        manifest["outputs"] = outputs
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return report
