"""`GridUnits`: a 100 m regular grid in the local UTM CRS.

Mandatory per CLAUDE.md — it is the format every existing LCZ map, validation dataset, and WRF
workflow uses, and Phase 6's validation module joins against the Demuzere global LCZ map on
this same 100 m grid.
"""

from __future__ import annotations

import math

import geopandas as gpd
from shapely.geometry import Polygon, box

from lczkit.crs import local_utm_crs
from lczkit.protocols import BBox

DEFAULT_CELL_SIZE_M = 100.0


class GridUnits:
    """A regular `cell_size_m` grid, aligned to the local UTM CRS's own coordinate origin —
    not to `bbox`. Two overlapping bboxes therefore assign the *same* `unit_id` to the same
    real-world cell, which is what makes grid `unit_id`s meaningfully "stable" across runs and
    across cities sharing a UTM zone, unlike `EnclosureUnits`' barrier-dependent ids.

    Cells are kept whole (never clipped to `bbox`) and are included if they intersect `bbox` at
    all, so the returned grid can extend slightly beyond `bbox`'s edges. `barriers` is accepted
    for `SpatialUnitStrategy` conformance but ignored, per the protocol's own docstring.
    """

    def __init__(self, cell_size_m: float = DEFAULT_CELL_SIZE_M) -> None:
        if cell_size_m <= 0:
            raise ValueError(f"cell_size_m must be positive, got {cell_size_m}")
        self.cell_size_m = cell_size_m

    def generate(self, bbox: BBox, barriers: gpd.GeoDataFrame | None = None) -> gpd.GeoDataFrame:
        del barriers  # grid cells ignore barriers; see SpatialUnitStrategy protocol docstring
        crs = local_utm_crs(bbox)
        bbox_utm = gpd.GeoSeries([box(*bbox)], crs="EPSG:4326").to_crs(crs).iloc[0]
        minx, miny, maxx, maxy = bbox_utm.bounds
        cell = self.cell_size_m

        col_start, col_end = math.floor(minx / cell), math.floor(maxx / cell)
        row_start, row_end = math.floor(miny / cell), math.floor(maxy / cell)

        unit_ids: list[str] = []
        geoms: list[Polygon] = []
        for col in range(col_start, col_end + 1):
            x0 = col * cell
            for row in range(row_start, row_end + 1):
                y0 = row * cell
                cell_geom = box(x0, y0, x0 + cell, y0 + cell)
                if cell_geom.intersects(bbox_utm):
                    unit_ids.append(f"grid_{col}_{row}")
                    geoms.append(cell_geom)

        return gpd.GeoDataFrame({"unit_id": unit_ids}, geometry=geoms, crs=crs).set_index("unit_id")
