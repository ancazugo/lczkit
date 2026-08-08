"""Cross-layer topology cleanup, applied to `buildings_topo` only.

Strictly sequential: the waterbody check runs against buildings *after* the road-buffer rule, not
against an independent snapshot of the layer.

`buildings_area` takes no part in any of this. Its contract is that footprint area survives, and
every operation here removes some.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np

from lczkit.cleaning.geometry import largest_part
from lczkit.cleaning.report import CleaningStep, Stage
from lczkit.crs import assert_projected_crs


def resolve_buildings_on_streets(
    buildings: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    *,
    buffer_m: float,
    overlap_limit: float,
) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Drop footprints mostly inside the roadway; trim those merely reaching into it.

    The operation this replaces dropped every footprint whose geometry touched a street
    *centreline*. That is wrong for the ordinary European perimeter block, which fronts the street
    and routinely crosses a generalised centreline by a metre or two: measured on the Berlin
    fixture it removed 439 footprints carrying **22.5% of all building area**, at a mean footprint
    of 1603 m² against 531 m² for those it kept — three times the size, which is the signature of a
    rule deleting blocks rather than artefacts.

    The replacement measures how much of a footprint lies inside a road buffer of half-width
    `buffer_m`:

    - above `overlap_limit`, the footprint is mostly roadway and is dropped
    - at or below it, the roadway part is subtracted and the rest kept

    **Choosing the two values.** On Berlin at `buffer_m=4.0` the overlap fraction spans the whole
    [0, 1] range with no gap in the counts, but the median footprint falls monotonically across it,
    from 1652 m² in the lowest decile to 60 m² in the highest, against a fixture-wide median
    building of 230 m². That collapse is the separator, and `overlap_limit=0.5` is where the
    features being dropped fall below the size of a typical building: it drops 54 footprints and
    recovers 95% of the lost area. Narrower buffers compress the distribution until nothing is
    droppable (p95 = 0.46 at 2 m); wider ones swallow the blocks (p90 = 0.98 at 8 m). Both values
    are configuration, and both were derived from two European fixtures — see
    `docs/experiments/phase-6.6-footprint-attrition.md`.

    Note what the rule does *not* do. Berlin's fixture is 6105 OpenStreetMap footprints against 88
    Microsoft ML, so the high-overlap tail is overwhelmingly OSM kiosks, shelters and garages. This
    separates small structures standing in the roadway from blocks fronting it; it is not an
    ML-noise filter.
    """
    assert_projected_crs(buildings, "buildings")
    if buildings.empty or streets.empty:
        return buildings, _passthrough(
            "resolve_buildings_on_streets",
            buildings,
            road_buffer_m=buffer_m,
            overlap_limit=overlap_limit,
        )
    assert_projected_crs(streets, "streets")

    road = streets.geometry.buffer(buffer_m).union_all()
    footprint_area = buildings.geometry.area
    inside = buildings.geometry.intersection(road).area
    fraction = inside.div(footprint_area.where(footprint_area > 0)).fillna(0.0)

    dropped = fraction > overlap_limit
    trimmed = (fraction > 0.0) & ~dropped

    kept = buildings.loc[~dropped].copy()
    to_trim = trimmed.loc[kept.index]
    if to_trim.any():
        kept.loc[to_trim, "geometry"] = largest_part(
            kept.loc[to_trim].geometry.difference(road)
        ).to_numpy()
        kept = kept.loc[kept.geometry.notna() & ~kept.geometry.is_empty]
    kept = kept.reset_index(drop=True)

    step = CleaningStep(
        stage="buildings_topo",
        operation="resolve_buildings_on_streets",
        n_in=len(buildings),
        n_out=len(kept),
        area_in_m2=float(footprint_area.sum()),
        area_out_m2=float(kept.geometry.area.sum()),
        detail={
            "road_buffer_m": buffer_m,
            "overlap_limit": overlap_limit,
            "n_dropped": int(dropped.sum()),
            "n_trimmed": int(trimmed.sum()),
            "area_dropped_m2": float(footprint_area[dropped].sum()),
            "median_dropped_footprint_m2": float(np.nanmedian(footprint_area[dropped]))
            if dropped.any()
            else None,
        },
    )
    return kept, step


def _passthrough(operation: str, layer: gpd.GeoDataFrame, **detail: object) -> CleaningStep:
    area = float(layer.geometry.area.sum()) if not layer.empty else 0.0
    return CleaningStep(
        stage="buildings_topo",
        operation=operation,
        n_in=len(layer),
        n_out=len(layer),
        area_in_m2=area,
        area_out_m2=area,
        detail=dict(detail),
    )


def _drop_intersecting(
    target: gpd.GeoDataFrame, other: gpd.GeoDataFrame, *, stage: Stage, operation: str, areal: bool
) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Drop every `target` feature intersecting `other`.

    `areal` says whether `target` carries footprint area worth reporting: buildings do, waterlines
    do not, and a linework layer reporting 0.0 is a fact about the layer rather than a gap.
    """
    assert_projected_crs(target, "target")
    if target.empty or other.empty:
        kept = target
    else:
        assert_projected_crs(other, "other")
        hits = gpd.sjoin(target, other[["geometry"]], predicate="intersects", how="inner")
        kept = target.loc[~target.index.isin(hits.index)]
    kept = kept.reset_index(drop=True)
    step = CleaningStep(
        stage=stage,
        operation=operation,
        n_in=len(target),
        n_out=len(kept),
        area_in_m2=float(target.geometry.area.sum()) if areal else 0.0,
        area_out_m2=float(kept.geometry.area.sum()) if areal else 0.0,
    )
    return kept, step


def drop_buildings_on_waterbodies(
    buildings: gpd.GeoDataFrame, waterbodies: gpd.GeoDataFrame
) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Drop buildings intersecting `waterbodies`.

    Still a plain intersection test, unlike the street rule: a footprint reaching into a river is a
    conflation error rather than a building fronting it, and the measured cost is 6 features and
    0.4% of area on Berlin rather than 439 and 22.5%.
    """
    return _drop_intersecting(
        buildings,
        waterbodies,
        stage="buildings_topo",
        operation="drop_buildings_on_waterbodies",
        areal=True,
    )


def drop_waterlines_through_buildings(
    waterlines: gpd.GeoDataFrame, buildings: gpd.GeoDataFrame
) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Drop waterlines that pass through `buildings`."""
    return _drop_intersecting(
        waterlines,
        buildings,
        stage="topology",
        operation="drop_waterlines_through_buildings",
        areal=False,
    )


CrossLayerResult = tuple[
    gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame, list[CleaningStep]
]


def apply_cross_layer_topology(
    buildings_topo: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    waterlines: gpd.GeoDataFrame,
    waterbodies: gpd.GeoDataFrame,
    *,
    road_buffer_m: float,
    road_overlap_limit: float,
) -> CrossLayerResult:
    """Run cross-layer topology cleanup on `buildings_topo`.

    `streets` and `waterbodies` pass through unchanged — only the topological building layer and
    `waterlines` are filtered, per CLAUDE.md's Phase 1 spec.
    """
    cleaned, street_step = resolve_buildings_on_streets(
        buildings_topo, streets, buffer_m=road_buffer_m, overlap_limit=road_overlap_limit
    )
    cleaned, water_step = drop_buildings_on_waterbodies(cleaned, waterbodies)
    cleaned_waterlines, waterline_step = drop_waterlines_through_buildings(waterlines, cleaned)
    return (
        cleaned,
        streets,
        cleaned_waterlines,
        waterbodies,
        [street_step, water_step, waterline_step],
    )
