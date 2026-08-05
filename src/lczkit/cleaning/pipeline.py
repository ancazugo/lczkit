"""Top-level orchestration: fetch raw vectors from a `VectorSource` and run the full Phase 1
cleaning pipeline against them.
"""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
from pyproj import CRS
from shapely.geometry import box

from lczkit.cleaning.buildings import clean_buildings
from lczkit.cleaning.report import CleaningReport, CleaningStep
from lczkit.cleaning.streets import simplify_streets
from lczkit.cleaning.topology import apply_cross_layer_topology
from lczkit.config import CleaningConfig
from lczkit.protocols import BBox, VectorSource


def reproject_to_local_utm(
    bbox: BBox,
    buildings: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    waterlines: gpd.GeoDataFrame,
    waterbodies: gpd.GeoDataFrame,
) -> tuple[CRS, gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Compute one UTM CRS from `bbox` and reproject every layer into it.

    Computed once from the bbox itself, not from any individual layer — `estimate_utm_crs()`
    can differ between layers covering nearly the same area (e.g. near a UTM zone boundary),
    which would silently break cross-layer topology if each layer picked its own zone.
    """
    target = gpd.GeoSeries([box(*bbox)], crs="EPSG:4326").estimate_utm_crs()
    return (
        target,
        buildings.to_crs(target),
        streets.to_crs(target),
        waterlines.to_crs(target),
        waterbodies.to_crs(target),
    )


@dataclass(frozen=True)
class CleanedVectors:
    """The cleaned output of `clean_vectors()`. Holds live GeoDataFrames for in-process use —
    never itself serialized; that's Phase 6's job on the eventual output GeoParquet."""

    buildings: gpd.GeoDataFrame
    streets: gpd.GeoDataFrame
    waterlines: gpd.GeoDataFrame
    waterbodies: gpd.GeoDataFrame
    report: CleaningReport
    crs: CRS


def _require(value: float | None, name: str) -> float:
    if value is None:
        raise ValueError(
            f"settings.cleaning.{name} is not set; the cleaning pipeline has no "
            "literature-derived default for it and refuses to guess. Set it explicitly."
        )
    return value


def clean_vectors(source: VectorSource, bbox: BBox, config: CleaningConfig) -> CleanedVectors:
    """Fetch raw vector layers from `source` and run the full Phase 1 cleaning pipeline.

    `source` is typed against the `VectorSource` protocol, not any concrete implementation, so
    this stays source-agnostic — usable with `OvertureSource` or any future `VectorSource`.
    """
    max_area_m2 = _require(config.building_max_area_m2, "building_max_area_m2")
    min_area_m2 = _require(config.building_min_area_m2, "building_min_area_m2")
    merge_limit_m2 = _require(config.building_merge_limit_m2, "building_merge_limit_m2")
    overlap_limit = _require(config.building_overlap_limit, "building_overlap_limit")

    raw_buildings = source.buildings(bbox)
    raw_streets = source.streets(bbox)
    raw_waterlines, raw_waterbodies = source.water(bbox)

    crs, buildings, streets, waterlines, waterbodies = reproject_to_local_utm(
        bbox, raw_buildings, raw_streets, raw_waterlines, raw_waterbodies
    )

    steps: list[CleaningStep] = []

    buildings, building_steps = clean_buildings(
        buildings,
        max_area_m2=max_area_m2,
        min_area_m2=min_area_m2,
        merge_limit_m2=merge_limit_m2,
        overlap_limit=overlap_limit,
    )
    steps.extend(building_steps)

    streets, street_step = simplify_streets(streets, buildings)
    steps.append(street_step)

    buildings, streets, waterlines, waterbodies, topology_steps = apply_cross_layer_topology(
        buildings, streets, waterlines, waterbodies
    )
    steps.extend(topology_steps)

    return CleanedVectors(
        buildings=buildings,
        streets=streets,
        waterlines=waterlines,
        waterbodies=waterbodies,
        report=CleaningReport(steps=steps),
        crs=crs,
    )
