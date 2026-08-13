"""Top-level orchestration: fetch raw vectors from a `VectorSource` and run the full Phase 1
cleaning pipeline against them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from pyproj import CRS

from lczkit.cleaning.buildings import clean_buildings
from lczkit.cleaning.land_use import clean_land_use
from lczkit.cleaning.report import CleaningReport, CleaningStep
from lczkit.cleaning.streets import simplify_streets, simplify_streets_tiled
from lczkit.cleaning.topology import apply_cross_layer_topology
from lczkit.config import CleaningConfig
from lczkit.crs import local_utm_crs
from lczkit.protocols import BBox, VectorSource


def tile_fingerprint(config: CleaningConfig) -> str:
    """Short hash of everything that changes a cached tile's contents.

    Tile keys are aligned to the CRS origin and so are shared between runs over different
    bboxes — which is the point of the cache, and also why the key alone is not enough to
    identify a result. Anything that would make the same tile simplify differently has to move
    the fingerprint, or a later run silently reads an earlier run's answer.

    The whole of `CleaningConfig` goes in, not only the tiling fields: the exclusion mask is
    `buildings_topo`, so every building threshold reaches a tile's result too. `neatnet`'s
    version is included because its output is its algorithm. The pinned artifact threshold is
    *not* here — it depends on the full extent rather than on config, so `simplify_streets_tiled`
    folds it in once it has resolved it.
    """
    payload = {
        "cleaning": config.model_dump(mode="json"),
        "neatnet": version("neatnet"),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return digest[:12]


def reproject_to_local_utm(
    bbox: BBox, **layers: gpd.GeoDataFrame
) -> tuple[CRS, dict[str, gpd.GeoDataFrame], dict[str, int]]:
    """Compute one UTM CRS from `bbox`, reproject every layer into it, and guarantee finiteness.

    Computed once from the bbox itself, not from any individual layer — `estimate_utm_crs()`
    can differ between layers covering nearly the same area (e.g. near a UTM zone boundary),
    which would silently break cross-layer topology if each layer picked its own zone. Takes
    layers by keyword and returns them by name so that adding a layer cannot quietly reorder
    an unpacked tuple at a call site.

    The third return value counts, per layer, the features that had to be clipped to the study
    extent to survive the projection at all — see `_repair_unprojectable`. Zero for every city
    measured before Phase 10.
    """
    target = local_utm_crs(bbox)
    projected: dict[str, gpd.GeoDataFrame] = {}
    repaired: dict[str, int] = {}
    for name, layer in layers.items():
        frame, count = _repair_unprojectable(layer.to_crs(target), layer, bbox, target)
        projected[name] = frame
        repaired[name] = count
    return target, projected, repaired


def _repair_unprojectable(
    projected: gpd.GeoDataFrame, source: gpd.GeoDataFrame, bbox: BBox, target: CRS
) -> tuple[gpd.GeoDataFrame, int]:
    """Clip any feature whose projection is non-finite back to the study extent, and reproject.

    A UTM zone is 6 degrees wide; a geometry spanning the globe has no finite representation in
    one. Overture's `base/land_use` carries such features — two marine `species_management_area`
    polygons spanning the full 360 degrees of longitude intersect the Hong Kong window, and
    projecting them into UTM 50N produced 663 non-finite coordinates. The first thing to touch
    one was `make_valid()`, which failed with `CGAlgorithmsDD::orientationIndex encountered
    NaN/Inf numbers` and took the whole city down.

    Clipping rather than dropping: the part of such a feature inside the study area is real, and
    it is the only part any statistic here uses. A feature that is still unprojectable after
    clipping is dropped, because nothing else can be done with it.

    The test is exact and carries no threshold — a coordinate is finite or it is not. Anything
    keyed on "how many degrees is too many" would be a guess about projections rather than a
    measurement of them.
    """
    if projected.empty:
        return projected, 0
    coords = shapely.get_coordinates(projected.geometry.values)
    if np.isfinite(coords).all():
        return projected, 0

    finite = np.fromiter(
        (bool(np.isfinite(shapely.get_coordinates(geom)).all()) for geom in projected.geometry),
        dtype=bool,
        count=len(projected),
    )
    window = shapely.box(*bbox)
    clipped = source.loc[~finite].copy()
    clipped["geometry"] = shapely.intersection(clipped.geometry.values, window)
    clipped = clipped.to_crs(target)

    still_bad = np.fromiter(
        (
            geom is None
            or geom.is_empty
            or not bool(np.isfinite(shapely.get_coordinates(geom)).all())
            for geom in clipped.geometry
        ),
        dtype=bool,
        count=len(clipped),
    )
    repaired = pd.concat([projected.loc[finite], clipped.loc[~still_bad]])
    out = gpd.GeoDataFrame(repaired.loc[projected.index.intersection(repaired.index)], crs=target)
    return out, int((~finite).sum())


@dataclass(frozen=True)
class CleanedVectors:
    """The cleaned output of `clean_vectors()`. Holds live GeoDataFrames for in-process use —
    never itself serialized; that's Phase 6's job on the eventual output GeoParquet.

    There is no plain `buildings` attribute, deliberately. Which of the two layers a caller wants
    is never obvious from the name, and the single ambiguous layer that used to be here is what
    fed 23.5% of Berlin's footprint area into a statistic that needed all of it.
    """

    buildings_area: gpd.GeoDataFrame
    """Area-preserving. Building surface fraction, `Hr`, building count, mean building area and
    `industrial_fraction` all read this, and the Phase 3 height cascade runs on it."""

    buildings_topo: gpd.GeoDataFrame
    """Planar and non-overlapping. The `neatnet` exclusion mask and `momepy.street_profile` read
    this; it has been through the road-buffer rule, so its facades stand outside the roadway."""

    streets: gpd.GeoDataFrame
    waterlines: gpd.GeoDataFrame
    waterbodies: gpd.GeoDataFrame
    land_use: gpd.GeoDataFrame
    report: CleaningReport
    crs: CRS


def _require(value: float | None, name: str) -> float:
    if value is None:
        raise ValueError(
            f"settings.cleaning.{name} is not set; the cleaning pipeline has no "
            "literature-derived default for it and refuses to guess. Set it explicitly."
        )
    return value


def _simplify(
    streets: gpd.GeoDataFrame,
    buildings: gpd.GeoDataFrame,
    config: CleaningConfig,
    *,
    cache_dir: Path | None,
) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Dispatch to the tiled or whole-extent simplification, on `street_tile_size_m` alone.

    Unset means whole-extent, which is how every figure recorded before Phase 8 was produced.
    Tiling is a deliberate, recorded choice rather than something that switches itself on at
    some extent — a run whose answer changed because the study area grew past a hidden
    threshold would be very hard to explain afterwards.
    """
    if config.street_tile_size_m is None:
        return simplify_streets(streets, buildings)
    buffer_m = _require(config.street_tile_buffer_m, "street_tile_buffer_m")
    return simplify_streets_tiled(
        streets,
        buildings,
        tile_size_m=config.street_tile_size_m,
        buffer_m=buffer_m,
        workers=config.street_tile_workers,
        cache_dir=cache_dir,
        cache_fingerprint=tile_fingerprint(config),
        artifact_threshold=config.street_artifact_threshold,
    )


def clean_vectors(
    source: VectorSource,
    bbox: BBox,
    config: CleaningConfig,
    *,
    cache_dir: Path | None = None,
) -> CleanedVectors:
    """Fetch raw vector layers from `source` and run the full Phase 1 cleaning pipeline.

    `source` is typed against the `VectorSource` protocol, not any concrete implementation, so
    this stays source-agnostic — usable with `OvertureSource` or any future `VectorSource`.

    `cache_dir` memoises per-tile street simplification when tiling is configured; the caller
    resolves the path, since config owns every path in this package. `None` disables it.
    """
    max_area_m2 = _require(config.building_max_area_m2, "building_max_area_m2")
    min_area_m2 = _require(config.building_min_area_m2, "building_min_area_m2")
    merge_limit_m2 = _require(config.building_merge_limit_m2, "building_merge_limit_m2")
    overlap_limit = _require(config.building_overlap_limit, "building_overlap_limit")
    road_buffer_m = _require(config.building_road_buffer_m, "building_road_buffer_m")
    road_overlap_limit = _require(config.building_road_overlap_limit, "building_road_overlap_limit")

    raw_waterlines, raw_waterbodies = source.water(bbox)
    raw = {
        "buildings": source.buildings(bbox),
        "streets": source.streets(bbox),
        "waterlines": raw_waterlines,
        "waterbodies": raw_waterbodies,
        "land_use": source.land_use(bbox),
    }
    crs, layers, repaired = reproject_to_local_utm(bbox, **raw)
    buildings = layers["buildings"]
    streets = layers["streets"]
    waterlines = layers["waterlines"]
    waterbodies = layers["waterbodies"]

    steps: list[CleaningStep] = []
    if any(repaired.values()):
        # Recorded even though it is almost always zero: a feature clipped to the study extent
        # has been changed, and a change nobody can see in the report is the failure mode this
        # phase's own history keeps demonstrating.
        steps.append(
            CleaningStep(
                stage="ingestion",
                operation="clip_unprojectable_features",
                n_in=sum(len(frame) for frame in raw.values()),
                n_out=sum(len(frame) for frame in layers.values()),
                detail={name: count for name, count in repaired.items() if count},
            )
        )

    layers_out, building_steps = clean_buildings(
        buildings,
        max_area_m2=max_area_m2,
        min_area_m2=min_area_m2,
        merge_limit_m2=merge_limit_m2,
        overlap_limit=overlap_limit,
    )
    steps.extend(building_steps)

    # Land use takes no part in cross-layer topology — it is functional metadata, not a
    # physical surface that can conflict with a building or a street.
    land_use, land_use_step = clean_land_use(layers["land_use"])
    steps.append(land_use_step)

    # Simplification comes first: the road-buffer rule buffers the network, and buffering
    # unsimplified dual carriageways would cover the block between them.
    streets, street_step = _simplify(streets, layers_out.topo, config, cache_dir=cache_dir)
    steps.append(street_step)

    buildings_topo, streets, waterlines, waterbodies, topology_steps = apply_cross_layer_topology(
        layers_out.topo,
        streets,
        waterlines,
        waterbodies,
        road_buffer_m=road_buffer_m,
        road_overlap_limit=road_overlap_limit,
    )
    steps.extend(topology_steps)

    return CleanedVectors(
        buildings_area=layers_out.area,
        buildings_topo=buildings_topo,
        streets=streets,
        waterlines=waterlines,
        waterbodies=waterbodies,
        land_use=land_use,
        report=CleaningReport(steps=steps, footprints=layers_out.coverage),
        crs=crs,
    )
