"""Dimensional & Shape morphometrics — Majer & Fleischmann (2026), Supplementary A §1.

Every metric here is a direct 1:1 momepy 1.0+ call, computed once for buildings and once for ETCs
(enclosed tessellation cells), plus area-weighted variants over the neighbourhoods
`lczkit.morphometrics.graphs` builds. See
`docs/references/tables/majer_2026_morphometrics_menu.md` for the full attribute-to-momepy-call
mapping this module implements against.

`buildings` and `etc` must already share one index (`unit_id`) — `buildings_for_etc`
(`lczkit.units.tessellation`) produces that alignment — since every weighted variant here is a
plain `Series` operation across the two.
"""

from __future__ import annotations

from collections.abc import Callable

import geopandas as gpd
import momepy
import pandas as pd
from libpysal.graph import Graph

#: Shape/dimension metrics computed identically for buildings and ETCs, each carrying the same
#: three weighted variants (buildings 100 m, buildings 200 m, ETC 3 topological steps). One
#: signature (`geometry -> Series`) per metric, so adding a twelfth momepy call is one tuple entry
#: rather than a new function.
WEIGHTED_SHAPE_METRICS: tuple[tuple[str, Callable[[gpd.GeoDataFrame], pd.Series]], ...] = (
    ("longest_axis_length", momepy.longest_axis_length),
    ("circular_compactness", momepy.circular_compactness),
    ("square_compactness", momepy.square_compactness),
    ("compactness_weighted_axis", momepy.compactness_weighted_axis),
    ("convexity", momepy.convexity),
    ("elongation", momepy.elongation),
    ("equivalent_rectangular_index", momepy.equivalent_rectangular_index),
    ("facade_ratio", momepy.facade_ratio),
    ("fractal_dimension", momepy.fractal_dimension),
    ("rectangularity", momepy.rectangularity),
    ("shape_index", momepy.shape_index),
)

#: Metrics whose denominator's shape is mathematically guaranteed to contain the numerator's
#: (an enclosing circle, a convex hull, a bounding rectangle, or a comparison of two sides), so
#: any value outside [0, 1] is floating-point noise from the underlying GEOS computation, not a
#: real property — unlike `square_compactness`, which is *not* bounded above by construction (a
#: shape rounder than a square legitimately exceeds 1) and is deliberately excluded here.
#: Clipped rather than left to overshoot: found on real Nairobi data, `rectangularity_building`
#: reaching 1.000246 from the minimum-rotated-rectangle computation.
_BOUNDED_TO_UNIT_INTERVAL = frozenset(
    {"circular_compactness", "convexity", "elongation", "rectangularity", "shape_index"}
)


def dimensional_metrics(
    buildings: gpd.GeoDataFrame,
    etc: gpd.GeoDataFrame,
    *,
    building_contiguity: Graph,
    building_w100m: Graph,
    building_w200m: Graph,
    etc_w3steps: Graph,
) -> pd.DataFrame:
    """The 62 Dimensional & Shape columns, indexed like `buildings`/`etc` (`unit_id`).

    `building_contiguity` is queen contiguity over `buildings` — what `momepy.perimeter_wall`
    groups joined structures by. `building_w100m`/`building_w200m` are distance-band graphs over
    building centroids; `etc_w3steps` is the fuzzy-contiguity ETC graph expanded to 3 topological
    steps (`lczkit.morphometrics.graphs.etc_higher_order`).
    """
    area_building = buildings.geometry.area
    area_etc = etc.geometry.area
    columns: dict[str, pd.Series] = {
        "area_building": area_building,
        "area_etc": area_etc,
    }

    courtyard_area = momepy.courtyard_area(buildings)
    courtyard_index = momepy.courtyard_index(buildings, courtyard_area=courtyard_area).clip(
        lower=0.0, upper=1.0
    )
    # `momepy.courtyard_area` calls `shapely.get_exterior_ring`, which is defined only for a
    # single `Polygon` — on a `MultiPolygon` it returns `None`, silently making the "filled"
    # term of the courtyard-area formula 0 and the result `-area` instead of a real value.
    # `buildings_area` can legitimately hold MultiPolygons (small-building absorption dissolves
    # two non-adjacent footprints without erasing either), so this is nulled explicitly rather
    # than reported as a nonsensical negative — found on real Nairobi data, 3 of 7 214 buildings.
    multipart = buildings.geometry.geom_type == "MultiPolygon"
    courtyard_area = courtyard_area.mask(multipart)
    courtyard_index = courtyard_index.mask(multipart)
    columns["courtyard_area_building"] = courtyard_area
    columns["courtyard_index_building"] = courtyard_index

    perimeter_wall = momepy.perimeter_wall(buildings, graph=building_contiguity)
    columns["perimeter_wall_building"] = perimeter_wall
    columns["perimeter_wall_building_w100m"] = momepy.weighted_character(
        perimeter_wall, area_building, building_w100m
    )
    columns["perimeter_wall_building_w200m"] = momepy.weighted_character(
        perimeter_wall, area_building, building_w200m
    )

    for name, fn in WEIGHTED_SHAPE_METRICS:
        building_value = fn(buildings)
        etc_value = fn(etc)
        if name in _BOUNDED_TO_UNIT_INTERVAL:
            building_value = building_value.clip(lower=0.0, upper=1.0)
            etc_value = etc_value.clip(lower=0.0, upper=1.0)
        columns[f"{name}_building"] = building_value
        columns[f"{name}_etc"] = etc_value
        columns[f"{name}_building_w100m"] = momepy.weighted_character(
            building_value, area_building, building_w100m
        )
        columns[f"{name}_building_w200m"] = momepy.weighted_character(
            building_value, area_building, building_w200m
        )
        columns[f"{name}_etc_w3steps"] = momepy.weighted_character(etc_value, area_etc, etc_w3steps)

    return pd.DataFrame(columns, index=buildings.index)
