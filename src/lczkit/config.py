"""Pydantic configuration model for lczkit runs.

`DATA_DIR` is resolved exactly once, here, via `Settings.load()`. Every other module reaches data
through `settings.input_dir`, `settings.output_dir`, `settings.source_dir(name)` and
`settings.run_dir`; nothing else reads `os.environ` or builds a path from `__file__` or the working
directory.

The whole model is serialised verbatim into each run's manifest, so every threshold a run used is
part of its record. Thresholds with no published value (cleaning limits, height confidences)
default to `None` and raise when used: `lczkit.presets` supplies the measured values.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator


def _default_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


class OvertureConfig(BaseModel):
    """Configuration for `OvertureSource`, the Overture Maps vector source."""

    release: str | None = None
    """Pinned Overture release, e.g. `"2026-07-22.0"`. Never "latest": `OvertureSource` raises if
    this is unset."""

    source_dir_name: str = "Overture_Maps"
    """Subdirectory under `input/` that `OvertureSource` caches into."""

    duckdb_threads: int | None = None
    """Threads each DuckDB connection may use; `None` is DuckDB's default (every core).

    DuckDB ignores `OMP_NUM_THREADS`, so inside a worker pool this is the only way to keep N
    workers from using N x (host cores) threads during ingestion.
    """


class CleaningConfig(BaseModel):
    """Thresholds for the building and street cleaning pipeline.

    Majer & Fleischmann (arXiv:2603.00132) Supplementary D describes these operations only
    qualitatively, so there are no literature defaults: every field is `None` and the cleaning
    pipeline raises if it is used unset. `lczkit.presets` holds the fixture-derived values.
    """

    building_max_area_m2: float | None = None
    """Footprints larger than this are dropped as implausible."""

    building_min_area_m2: float | None = None
    """On `buildings_topo`, footprints smaller than this are dissolved into a touching neighbour.
    Those touching nothing are kept: small is not spurious."""

    building_road_buffer_m: float | None = None
    """Half-width of the road buffer the `buildings_topo` street rule measures against, in metres.
    Fixture-derived: 4.0 m separates perimeter blocks from structures standing in the roadway."""

    building_road_overlap_limit: float | None = None
    """Share of a footprint inside the road buffer above which it is dropped rather than trimmed.
    Fixture-derived (0.5); re-derive for a city whose road generalisation differs."""

    building_merge_limit_m2: float | None = None
    """`geoplanar.merge_overlaps`' `merge_limit`: overlapping polygons smaller than this are merged
    into a neighbour regardless of overlap size."""

    building_overlap_limit: float | None = None
    """`geoplanar.merge_overlaps`' `overlap_limit`: larger polygons merge only if the shared overlap
    exceeds this fraction of their area."""

    street_tile_size_m: float | None = None
    """Tile edge for chunked street simplification, in metres. `None` runs `neatnet` over the whole
    extent, which stops completing in usable time above roughly 50 km²."""

    street_tile_buffer_m: float | None = None
    """Margin simplified around each tile core, in metres. Seam artefacts fall sharply up to
    ~600 m and not beyond; below ~300 m a dual carriageway no longer fits in the buffer."""

    street_tile_workers: int | None = None
    """Processes to run tiles across. `None` uses every core the process may use."""

    street_artifact_threshold: float | None = None
    """Face-artifact index separating road artefacts from ordinary fabric. `None` derives it from
    the data (pooled across tiles on the tiled path); setting it pins the value for an A/B."""


class Wsf3dProduct(BaseModel):
    """WSF-3D V02 building height (DLR, TanDEM-X), CC-BY-4.0: one global tiled GeoTIFF.

    Int16 decimetres, nodata -32767 (`README_BuildingHeight.txt`), hence the tier's `scale=0.1`.
    Not in the Earth Engine catalogue (`DLR/WSF` holds only a 10 m settlement mask), so it is a
    one-off 2.1 GB HTTP download read by window thereafter.
    """

    kind: Literal["wsf3d"] = "wsf3d"
    version: str = "V02"
    filename: str = "WSF3D_V02_BuildingHeight.tif"
    url: str = "https://download.geoservice.dlr.de/WSF3D/files/global/WSF3D_V02_BuildingHeight.tif"


class GhslProduct(BaseModel):
    """GHS-BUILT-H ANBH R2023A (JRC), free reuse with attribution: 1000 km Mollweide tiles.

    ANBH (`BUVOL / BUSURF`) is the mean height of the built fabric rather than the gross AGBH
    averaged over open ground. Float32 metres, nodata 255, 100 m (GHSL Data Package 2023, p. 36).
    Also in Earth Engine as `JRC/GHSL/P2023A/GHS_BUILT_H/2018`, with identical values, so it is
    fetched over HTTP and needs no credential.
    """

    kind: Literal["ghsl"] = "ghsl"
    release: str = "R2023A"
    epoch: str = "E2018"
    product: str = "ANBH"
    crs: str = "ESRI:54009"
    tile_template: str = "GHS_BUILT_H_ANBH_E2018_GLOBE_R2023A_54009_100_V1_0_R{row}_C{column}"
    url_template: str = (
        "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_BUILT_H_GLOBE_R2023A/"
        "GHS_BUILT_H_ANBH_E2018_GLOBE_R2023A_54009_100/V1-0/tiles/{name}.zip"
    )
    citation: str = "Pesaresi, M. & Politis, P. (2023), GHS-BUILT-H R2023A, JRC"


class OpenBuildings25dProduct(BaseModel):
    """Google Open Buildings 2.5D Temporal v1, CC-BY-4.0, exported per window from Earth Engine.

    Metres above terrain at an effective 4 m, annual 2016-2023, over Africa, South and South-East
    Asia, Latin America and the Caribbean. No public bucket exists. The request caps are Earth
    Engine's own.
    """

    kind: Literal["gob25d"] = "gob25d"
    collection: str = "GOOGLE/Research/open-buildings-temporal/v1"
    band: str = "building_height"
    year: int = 2023
    """Pinned epoch, never "latest"."""

    scale_m: float = 4.0
    """The product's effective resolution; the 0.5 m serving grid carries no more detail."""

    max_pixels_per_request: int = 50_331_648
    max_bytes_per_request: int = 33_554_432


HeightProduct = Annotated[
    Wsf3dProduct | GhslProduct | OpenBuildings25dProduct, Field(discriminator="kind")
]
"""Where an areal tier's raster comes from. See `lczkit.sources.height_products`."""


class ArealTierConfig(BaseModel):
    """One areal raster tier of the height cascade: where its raster comes from and how to read it.

    Areal products assign a *neighbourhood* mean to each building, a categorically weaker
    measurement than a per-building height, and the output tags every building with the tier that
    resolved it.
    """

    name: str
    """The tier's `height_source` tag, e.g. `"ghsl"`. Unique within a cascade."""

    source_dir_name: str
    """Subdirectory under `input/` holding this product."""

    enabled: bool = True
    """Whether the tier takes part in the cascade. Distinct from `filename is None` (product not
    available): a tier measured and switched off must stay distinguishable from one never placed."""

    filename: str | None = None
    """Raster filename within `input/<source_dir_name>/`. Filled per study area by
    `lczkit.sources.height_products.resolve_areal_tiers` when `product` is set; set it by hand for a
    raster you placed yourself. `None` skips the tier."""

    product: HeightProduct | None = None
    """How to fetch the raster. `None` means it is placed by hand."""

    band: int = 1
    """1-based raster band carrying height."""

    scale: float = 1.0
    """Multiplier from raw raster values to metres (0.1 for a decimetre product)."""

    nodata: float | None = None
    """Override the raster's declared nodata. `None` uses the file's own."""

    min_height_m: float = 0.0
    """Values at or below this read as "no building here" and pass to the next tier.

    Zero for every shipped tier, Open Buildings 2.5D included. Its damage is within-unit
    *dispersion* (CV 0.441 against reality's 0.195), which a floor on one tail does not fix.
    """

    confidence: float | None = None
    """`height_confidence` for every building this tier resolves. No default: see `HeightConfig`."""


def _default_areal_tiers() -> list[ArealTierConfig]:
    """The `coarse` cascade: WSF-3D then GHS-BUILT-H, with Open Buildings 2.5D present but off.

    Open Buildings 2.5D has the lowest per-building error of the three (MAE 5.39 m against 7.44 and
    8.17) and still makes the map worse: −1.9 points of built-class agreement, positive in 4 of 9
    cities. `Hr` is a geometric mean and this product's within-unit spread is 0.441 against
    reality's 0.195, so per-building accuracy is the wrong acceptance test here.
    """
    return [
        ArealTierConfig(
            name="gob25d",
            source_dir_name="GOB25D",
            enabled=False,
            product=OpenBuildings25dProduct(),
        ),
        ArealTierConfig(
            name="wsf3d",
            source_dir_name="WSF3D",
            scale=0.1,
            nodata=-32767.0,
            product=Wsf3dProduct(),
        ),
        ArealTierConfig(
            name="ghsl",
            source_dir_name="GHSL",
            nodata=255.0,
            product=GhslProduct(),
        ),
    ]


class HeightConfig(BaseModel):
    """The building-height cascade: Overture attributes first, then `areal_tiers` in list order.

    Adding an areal product is an entry in `areal_tiers`, not a code change. The confidences have
    no default because no published number defines them: `height_confidence` is an ordinal ranking,
    and an invented default would put a quality claim nobody chose into every manifest.
    """

    storey_height_m: float = 3.0
    """Metres per storey for the `num_floors` fallback. Varies regionally; set it per city where
    known."""

    overture_height_confidence: float | None = None
    """`height_confidence` for Overture's `height`, unless Overture supplies its own per-building
    confidence, which is preferred."""

    overture_num_floors_confidence: float | None = None
    """`height_confidence` for heights derived as `num_floors x storey_height_m`."""

    areal_tiers: list[ArealTierConfig] = Field(default_factory=_default_areal_tiers)
    """Areal tiers in cascade order."""


NodataPolicy = Literal["exclude", "assign"]
"""What a nodata cell means for a land-cover product.

`"exclude"`: no observation, so the cell leaves the denominator. `"assign"`: the product masks this
surface on purpose, so the cell counts towards a named class. ETH canopy height sets built-up,
snow, ice and water to 255; reading those as `"exclude"` reports central Berlin as ~96% tree cover
instead of ~22%.
"""

UnmappedPolicy = Literal["exclude", "assign", "raise"]
"""What to do with a raster value no class mapping covers. `"raise"` (the default) because an
unmapped value means the mapping does not match the product on disk."""

GeeAssetType = Literal["image_collection", "image"]
"""Whether an Earth Engine asset is a collection to filter and mosaic, or a single image."""


class GeeAssetConfig(BaseModel):
    """Earth Engine coordinates for one land-cover dataset, recorded in the run manifest."""

    collection_id: str | None = None
    """Full asset ID, e.g. `"ESA/WorldCover/v200"`. `None`: no verified asset, and
    `EarthEngineSource` refuses to guess one."""

    asset_type: GeeAssetType = "image_collection"

    band: str | None = None
    """Band name within the asset, e.g. `"Map"`."""

    start_date: str | None = None
    """Inclusive ISO date for `filterDate`. Required for a collection; recorded for an image."""

    end_date: str | None = None
    """Exclusive ISO date for `filterDate`. Same caveat as `start_date`."""

    scale_m: float | None = None
    """Reduction scale in metres. Match the native resolution: a coarser one resamples silently."""

    def required_fields(self) -> tuple[str, ...]:
        """Fields `EarthEngineSource` cannot run without, given this asset's kind."""
        common = ("collection_id", "band", "scale_m")
        if self.asset_type == "image":
            return common
        return (*common, "start_date", "end_date")


class LandCoverDatasetConfig(BaseModel):
    """One land-cover product and the mapping from its raw values to fraction classes.

    `LocalRasterSource` and `EarthEngineSource` read the same instance, which is what makes the two
    backends schema-identical. A dataset is either categorical (`value_classes`) or binned (`bins`
    + `bin_classes`), never both; classes are disjoint and sum to 1.0 over the cells that count.
    """

    name: str
    """Short identifier, unique within `LandCoverConfig.datasets`."""

    source_dir_name: str
    """Subdirectory under `input/` holding this product."""

    filename: str | None = None
    """COG filename within `input/<source_dir_name>/`; `None` if not available locally."""

    band: int = 1
    """1-based band to read from the local COG."""

    column_prefix: str = "frac_"
    """Prefixed to every class name to form output columns, so two datasets that both emit `tree`
    can share a units table."""

    classes: list[str]
    """The full, ordered output class list. A class with no cells still gets a 0.0 column, so two
    cities produce the same schema."""

    value_classes: dict[int, str] | None = None
    """Categorical mapping from raw value to class name."""

    bins: list[float] | None = None
    """Ascending breakpoints for a continuous product: `v` falls in bin `i` where
    `bins[i-1] <= v < bins[i]`."""

    bin_classes: list[str] | None = None
    """Class per bin, lowest first; `len(bins) + 1` entries."""

    nodata: float | None = None
    """Override the raster's declared nodata. `None` uses the file's own."""

    nodata_policy: NodataPolicy = "exclude"

    nodata_class: str | None = None
    """Class nodata counts towards; required exactly when `nodata_policy` is `"assign"`."""

    unmapped_policy: UnmappedPolicy = "raise"

    unmapped_class: str | None = None
    """Class unmapped values count towards; required exactly when `unmapped_policy` is
    `"assign"`."""

    gee: GeeAssetConfig = Field(default_factory=GeeAssetConfig)
    """Earth Engine coordinates for the same product."""

    @model_validator(mode="after")
    def _check_class_mapping(self) -> LandCoverDatasetConfig:
        name = self.name
        if not self.classes:
            raise ValueError(f"{name}: classes must not be empty")
        if len(set(self.classes)) != len(self.classes):
            raise ValueError(f"{name}: classes contains duplicates: {self.classes}")

        categorical = self.value_classes is not None
        binned = self.bins is not None
        if categorical == binned:
            raise ValueError(f"{name}: set exactly one of value_classes or bins")

        referenced: list[tuple[str, str | None]] = [
            ("nodata_class", self.nodata_class),
            ("unmapped_class", self.unmapped_class),
        ]
        if binned:
            bins = self.bins or []
            if self.bin_classes is None:
                raise ValueError(f"{name}: bins requires bin_classes")
            if len(self.bin_classes) != len(bins) + 1:
                raise ValueError(
                    f"{name}: bin_classes must have len(bins) + 1 = {len(bins) + 1} entries, "
                    f"got {len(self.bin_classes)}"
                )
            if any(b >= a for b, a in zip(bins, bins[1:], strict=False)):
                raise ValueError(f"{name}: bins must be strictly ascending, got {bins}")
            referenced += [("bin_classes", c) for c in self.bin_classes]
        else:
            if self.bin_classes is not None:
                raise ValueError(f"{name}: bin_classes is only valid alongside bins")
            referenced += [("value_classes", c) for c in (self.value_classes or {}).values()]

        for field, value in referenced:
            if value is not None and value not in self.classes:
                raise ValueError(f"{name}: {field} names {value!r}, which is not in classes")

        for policy, class_field, value in [
            ("nodata_policy", "nodata_class", self.nodata_class),
            ("unmapped_policy", "unmapped_class", self.unmapped_class),
        ]:
            assigns = getattr(self, policy) == "assign"
            if assigns and value is None:
                raise ValueError(f"{name}: {policy} is 'assign' but {class_field} is not set")
            if not assigns and value is not None:
                raise ValueError(f"{name}: {class_field} is set but {policy} is not 'assign'")
        return self


#: ESA WorldCover v200 value to class, from `docs/references/tables/esa_worldcover_classes.md`.
#:
#: Only class 50 (built up) is impervious; bare and sparse ground (60) reads as pervious, following
#: Stewart & Oke's LCZ F. Class 60 also covers bare rock (LCZ E, impervious) and is the first value
#: to revisit in an arid city. Herbaceous wetland (90) and mangroves (95) read as water, which is a
#: choice rather than a transcription: mangroves are tree cover by WorldCover's own definition, so
#: a mangrove coast pushes toward LCZ G rather than A. Tree cover is carved out of pervious so the
#: classes stay disjoint: a consumer wanting Stewart & Oke's pervious fraction adds `frac_tree`
#: back.
_WORLDCOVER_CLASSES = {
    10: "tree",  # Tree cover
    20: "pervious",  # Shrubland
    30: "pervious",  # Grassland
    40: "pervious",  # Cropland
    50: "impervious",  # Built up
    60: "pervious",  # Bare / sparse vegetation
    70: "pervious",  # Snow and ice
    80: "water",  # Permanent water bodies
    90: "water",  # Herbaceous wetland
    95: "water",  # Mangroves
    100: "pervious",  # Moss and lichen
}

#: Canopy height at or above which a cell counts as tree, in metres. Stewart & Oke's LCZ C tops out
#: at 2 m and LCZ A and B start at 3 m, so the scheme's own tree/scrub boundary is 3 m. The ETH
#: product over-calls vegetation below 5 m (Lang et al. 2023), so `canopy_frac_tree` is an upper
#: bound, which is one reason WorldCover is the default tree source.
_CANOPY_TREE_THRESHOLD_M = 3.0


def _default_land_cover_datasets() -> list[LandCoverDatasetConfig]:
    """ESA WorldCover (the default) and ETH canopy height (a second, competing tree estimate)."""
    return [
        LandCoverDatasetConfig(
            name="worldcover",
            source_dir_name="ESA_WorldCover",
            classes=["tree", "pervious", "impervious", "water"],
            value_classes=_WORLDCOVER_CLASSES,
            # WorldCover's declared nodata, stated here so the local and Earth Engine paths agree:
            # an Earth Engine asset declares no nodata.
            nodata=0.0,
            nodata_policy="exclude",
            unmapped_policy="raise",
            gee=GeeAssetConfig(
                collection_id="ESA/WorldCover/v200",
                band="Map",
                start_date="2021-01-01",
                end_date="2022-01-01",
                scale_m=10.0,
            ),
        ),
        LandCoverDatasetConfig(
            name="eth_canopy",
            source_dir_name="ETH_CanopyHeight",
            classes=["tree", "non_tree"],
            column_prefix="canopy_frac_",
            bins=[_CANOPY_TREE_THRESHOLD_M],
            bin_classes=["non_tree", "tree"],
            # 255 masks built-up, snow, ice and water on purpose (Lang et al. 2023), all non-tree.
            # The mask is derived from WorldCover, so this tree fraction is not independent of it.
            nodata=255.0,
            nodata_policy="assign",
            nodata_class="non_tree",
            unmapped_policy="raise",
            gee=GeeAssetConfig(
                # A user asset (a single `Image`, band `b1`), confirmed by loading it.
                collection_id="users/nlang/ETH_GlobalCanopyHeight_2020_10m_v1",
                asset_type="image",
                band="b1",
                start_date="2020-01-01",
                end_date="2021-01-01",
                scale_m=10.0,
            ),
        ),
    ]


LandCoverBackend = Literal["local", "gee"]
"""Which `RasterSource` reduces the land cover for a run.

`"local"` mosaics the ESA WorldCover tiles the extent spans and reduces them with `exactextract`;
`"gee"` reduces the configured Earth Engine asset server-side with `reduceRegions`. The tables are
schema-identical but not bit-identical: `exactextract` weights partial cells, `reduceRegions`
counts whole pixels by centre, about a one-percent difference on a 100 m unit.
"""


class LandCoverConfig(BaseModel):
    """The land-cover fraction sources."""

    source: LandCoverBackend = "local"
    """Which backend supplies the fractions. `"local"` needs nothing but HTTP and is what CI tests.
    Choose `"gee"` for a dataset with no local product, or a window too large for
    `max_raster_cells`. The two have not been benchmarked against each other for speed."""

    datasets: list[LandCoverDatasetConfig] = Field(default_factory=_default_land_cover_datasets)
    """The configured products, by `name`."""

    gee_project: str | None = None
    """Google Cloud project Earth Engine bills against. Read from `GEE_PROJECT_NAME`."""

    gee_batch_size: int = 2000
    """Units per `reduceRegions` call, keeping each request under Earth Engine's limits."""

    gee_max_units: int | None = None
    """Refuse an Earth Engine run over more than this many units. `None` means no ceiling."""

    max_raster_cells: int = 200_000_000
    """Refuse a local read whose window exceeds this many cells (~450 x 450 km at 10 m)."""

    @model_validator(mode="after")
    def _check_unique_names(self) -> LandCoverConfig:
        names = [dataset.name for dataset in self.datasets]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate land-cover dataset names: {duplicates}")
        return self

    def dataset(self, name: str) -> LandCoverDatasetConfig:
        """The configured dataset called `name`, or a `KeyError` naming what is available."""
        for dataset in self.datasets:
            if dataset.name == name:
                return dataset
        available = ", ".join(repr(d.name) for d in self.datasets) or "(none configured)"
        raise KeyError(f"no land-cover dataset named {name!r}; configured: {available}")


class SemanticGroupConfig(BaseModel):
    """One functional group of Overture attribute values, and the LCZ class it is evidence for.

    Transcribed from `docs/references/tables/overture_lcz_semantic_mapping.md`, which a test parses
    and asserts against. A building matches on `subtype` **or** `class`. Groups are not a partition:
    `retail` is evidence for both large-low-rise form and commercial function.
    """

    name: str
    lcz_hint: str = ""
    """The LCZ class this group is evidence for. Documentation only; nothing keys off it."""

    building_subtypes: list[str] = Field(default_factory=list)
    building_classes: list[str] = Field(default_factory=list)
    land_use_subtypes: list[str] = Field(default_factory=list)
    land_use_classes: list[str] = Field(default_factory=list)


def _default_semantic_groups() -> list[SemanticGroupConfig]:
    """The committed crosswalk; see that table for why each value is where it is."""
    return [
        SemanticGroupConfig(
            name="lightweight",
            lcz_hint="7",
            building_subtypes=["outbuilding"],
            building_classes=["hut", "shed", "cabin", "roof", "kiosk", "carport", "guardhouse"],
        ),
        SemanticGroupConfig(
            name="large_lowrise",
            lcz_hint="8",
            building_classes=[
                "warehouse",
                "retail",
                "supermarket",
                "hangar",
                "stadium",
                "train_station",
                "transportation",
                "parking",
                "sports_centre",
                "sports_hall",
                "service",
            ],
            land_use_classes=["retail"],
        ),
        SemanticGroupConfig(
            name="heavy_industry",
            lcz_hint="10",
            building_subtypes=["industrial"],
            building_classes=["industrial", "storage_tank", "silo"],
            land_use_classes=["industrial", "works"],
        ),
        SemanticGroupConfig(
            name="residential",
            lcz_hint="1-6 context",
            building_subtypes=["residential"],
            building_classes=[
                "apartments",
                "house",
                "detached",
                "semidetached_house",
                "terrace",
                "bungalow",
                "residential",
                "dormitory",
                "allotment_house",
            ],
            land_use_subtypes=["residential"],
            land_use_classes=["residential"],
        ),
        SemanticGroupConfig(
            name="commercial",
            lcz_hint="1-3, 8 context",
            building_subtypes=["commercial"],
            building_classes=["commercial", "office", "retail", "hotel", "supermarket"],
            land_use_subtypes=["developed"],
            land_use_classes=["commercial", "retail"],
        ),
    ]


class UcpConfig(BaseModel):
    """The urban canopy parameters.

    Which land-cover classes and Overture values feed which parameter, plus momepy's street-profile
    settings restated so they reach the manifest.
    """

    street_profile_distance_m: float = 10.0
    """Spacing of `momepy.street_profile()`'s perpendicular ticks. momepy's default."""

    street_profile_tick_length_m: float = 50.0
    """Tick length; also the width reported for a street no building walls. momepy's default."""

    min_building_height_m: float = 0.1
    """Floor applied to heights before taking logs for the geometric mean, so one zero-height row
    cannot take a unit's `Hr` to zero. A numerical guard, below any plausible building."""

    measure_on: Literal["units", "enclosures"] = "units"
    """Units the parameters are *measured* on, as distinct from classified on.

    `"enclosures"` measures on street-bounded blocks and moves the result to the target units,
    area-weighted. It exists for `aspect_ratio`, which a grid cell no street crosses cannot measure:
    null on 10.8% of one Istanbul extent's built grid cells against 0.9% of its enclosures. Not
    calibrated against a reference, so a run with it on is not comparable with the defaults.
    """

    land_cover_dataset: str = "worldcover"
    """Which `LandCoverConfig.datasets` entry supplies the surface fractions."""

    tree_classes: list[str] = Field(default_factory=lambda: ["tree"])
    pervious_classes: list[str] = Field(default_factory=lambda: ["pervious"])
    """Pervious *before* tree and water are folded in; see `lczkit.ucp.surface`."""

    impervious_classes: list[str] = Field(default_factory=lambda: ["impervious"])
    """Impervious, roofs included; the building share is subtracted in `lczkit.ucp.surface`."""

    water_classes: list[str] = Field(default_factory=lambda: ["water"])

    industrial_building_subtypes: list[str] = Field(default_factory=lambda: ["industrial"])
    """Overture building `subtype` values counting as industrial."""

    industrial_building_classes: list[str] = Field(default_factory=lambda: ["industrial"])
    """Overture building `class` values counting as industrial. `warehouse` is excluded on purpose:
    it is the LCZ 8 case the LCZ 10 rule must keep apart."""

    industrial_land_use_subtypes: list[str] = Field(default_factory=list)
    """Overture land-use `subtype` values counting as industrial. Empty: industrial parcels sit
    under `developed`, which also covers commercial and retail."""

    industrial_land_use_classes: list[str] = Field(default_factory=lambda: ["industrial"])
    """Overture land-use `class` values counting as industrial. `brownfield` is excluded: it says
    what a parcel was, not what it does."""

    semantic_groups: list[SemanticGroupConfig] = Field(default_factory=_default_semantic_groups)
    """Functional groups read from Overture's `subtype` and `class`. Set `[]` to skip the layer.

    Independent of the `industrial_*` lists above, which feed the column the LCZ 10 threshold was
    calibrated on; `heavy_industry` is a slightly wider vocabulary reported beside it.
    """


class SemanticRuleConfig(BaseModel):
    """A functional assignment rule: a unit over `min_fraction` of `column` takes `lcz`.

    The displaced label is kept as `lcz_secondary`. A rule ships enabled only once its threshold
    has been swept against a reference; `reason` records the measurement either way.
    """

    name: str
    lcz: int
    column: str
    """The parameter column to threshold, e.g. `sem_lightweight_buildings_of_building_area`."""

    min_fraction: float = 0.5
    enabled: bool = False

    min_mean_building_area_m2: float | None = None
    max_mean_building_area_m2: float | None = None
    """Optional gates on `mean_building_area_m2`, which a rule may read although the metric
    does not weight it."""

    reason: str = ""
    """Why the rule exists and how it was calibrated, for the manifest."""


def _default_semantic_rules() -> list[SemanticRuleConfig]:
    """LCZ 8 enabled at 0.70 and LCZ 7 refused, both swept over eight cities.

    Most general first: a later rule overrides an earlier one on a unit both fire on. Bernard et al.
    (2024) guard their LCZ 8 rule with fewer than three storeys, SVF above 0.7 and vegetation below
    0.2, and require large low-rise to exceed the industrial and residential shares; none of those
    conditions is applied here, and the sweep was run without them.
    """
    return [
        SemanticRuleConfig(
            name="large_lowrise",
            lcz=8,
            column="sem_large_lowrise_buildings_of_building_area",
            min_fraction=0.70,
            enabled=True,
            reason=(
                "LCZ 8 is separable in the distance metric only by aspect ratio, which is null "
                "exactly where large setbacks keep streets from reaching buildings, so a "
                "functional route is needed. Swept over 19 thresholds x 6 size gates against "
                "So2Sat labels in eight cities: at 0.70 the rule relabels 662 labelled cells, "
                "72.2% of them LCZ 8 in the reference against 14.8% for the label it displaced, "
                "and LCZ 8 precision, recall, F1 and built-class agreement rise in all eight. No "
                "size gate: it cut reach at every gated setting and no gated setting passed. "
                "Against WUDAPT, F1 still rises everywhere but precision falls in Berlin and "
                "Milan."
            ),
        ),
        SemanticRuleConfig(
            name="lightweight",
            lcz=7,
            column="sem_lightweight_buildings_of_building_area",
            min_fraction=0.5,
            max_mean_building_area_m2=100.0,
            enabled=False,
            reason=(
                "Disabled on measurement. Overture has no slum or shanty value, so `lightweight` "
                "is an outbuilding vocabulary (hut, shed, kiosk, carport...). Swept over 95 "
                "settings against both references in eight cities and refused at every one: the "
                "rule was wrong more often than the label it overwrote. The tags sit in Berlin, "
                "Milan and Vancouver, which carry no reference LCZ 7, and are near-absent where "
                "LCZ 7 is (tagged building area 48.6% in Europe and North America against 13.6% "
                "elsewhere). Read `building_tag_coverage` beside any tag-based evidence."
            ),
        ),
    ]


class ClassificationConfig(BaseModel):
    """The prototype-distance classifier. Every threshold it applies lives here."""

    weight_preset: str = "bernard2024_partial"
    """Entry in `lczkit.classify.weights.PRESETS`.

    `"bernard2024_partial"` is Bernard et al. (2024)'s built-type default with the dimensions this
    package cannot compute left out: SVF (4) and z0 (0.5) are not computed, so 17 of the published
    21.5 weight units apply and building surface fraction carries ~47% of the metric. `"equal"` is
    the uniform comparison.
    """

    built_min_building_fraction: float = 0.10
    """Building surface fraction at or above which a unit is classified as a built type. Stewart &
    Oke's table draws this line itself: every built class is at least 10%, every natural class at
    most 10%."""

    reachable_natural_classes: list[str] = Field(default_factory=lambda: ["A", "B", "D", "E", "G"])
    """Natural classes the classifier may assign, by Stewart & Oke label.

    C is excluded because where nothing is built it ties with D on every computed parameter. F is
    not excluded by this list but by arithmetic: D's prototype box contains F's in every dimension,
    so adding "F" here cannot make it reachable. Distances to both are still reported.
    """

    natural_dominant_fraction: float = 0.50
    """Tree or water cover at which a unit reads as LCZ A or G. lczkit's own; see
    `docs/references/tables/lczkit_natural_class_ranges.md`."""

    natural_negligible_fraction: float = 0.10
    """Tree or water cover a natural class treats as absent (Stewart & Oke's 10% boundary)."""

    semantic_rules: list[SemanticRuleConfig] = Field(default_factory=_default_semantic_rules)
    """Functional rules read off Overture's attributes, applied after the LCZ 10 rule."""

    lcz10_industrial_column: str = "industrial_fraction_of_building_area"
    """The industrial share the LCZ 10 rule reads: Bernard et al. (2024)'s `FIND/B`, so their
    published 0.33 transfers to it. The threshold below was calibrated on this column."""

    lcz10_min_industrial_fraction: float = 0.45
    """`lcz10_industrial_column` above which a unit is LCZ 10.

    Swept over nineteen settings against the Rotterdam reference; 0.45 is the precision maximum and
    Bernard's 0.33 performs comparably. Precision is roughly flat (16.7-23.2%) across the range, so
    this sets how much of the map carries LCZ 10 more than how often the label is right: Overture
    cannot tell heavy from light industry.

    A threshold only. Bernard et al. (2024) Sect. 2.3 also require the industrial share to exceed
    the residential and large-low-rise shares; that condition is not applied, and the sweep was run
    without it. The rule also fires whatever the family gate decided, so a nearly unbuilt cell
    holding one industrial building reads 1.0 and becomes LCZ 10.
    """

    lcz1_min_height_m: float | None = None
    """Optional `Hr` floor below which LCZ 1 is not assignable. Bernard et al. (2024) apply the
    equivalent on storey counts; lczkit has no reliable storey count, so this is off."""

    modal_filter: bool = False
    """Replace an isolated unit's label with its neighbours' modal label.

    Off: the minimum-neighbour threshold has not been swept, and every stored figure was measured
    without a filter. See `lczkit.classify.smoothing`.
    """

    modal_filter_min_like_neighbours: int = 2
    """A unit with fewer contiguous neighbours sharing its label is isolated. A placeholder for a
    swept value, set to the weakest setting that does anything."""

    @model_validator(mode="after")
    def _check_thresholds(self) -> ClassificationConfig:
        if self.modal_filter_min_like_neighbours < 1:
            raise ValueError(
                "modal_filter_min_like_neighbours must be at least 1, got "
                f"{self.modal_filter_min_like_neighbours}; zero would make every unit isolated"
            )
        if not 0.0 < self.natural_negligible_fraction < self.natural_dominant_fraction <= 1.0:
            raise ValueError(
                "expected 0 < natural_negligible_fraction < natural_dominant_fraction <= 1, got "
                f"{self.natural_negligible_fraction} and {self.natural_dominant_fraction}"
            )
        for name in ("built_min_building_fraction", "lcz10_min_industrial_fraction"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be a fraction in [0, 1], got {value}")
        if not self.reachable_natural_classes:
            raise ValueError(
                "reachable_natural_classes must not be empty; a run that can assign no natural "
                "class would label every park and lake as a built type."
            )
        return self


class OutputConfig(BaseModel):
    """What a run writes into `output/lczkit/<run_id>/`."""

    break_count: int = 7
    """Classification breaks precomputed per continuous variable, for the map site."""

    break_method: Literal["quantile"] = "quantile"
    """How the breaks are derived. Only quantiles are implemented."""

    viz_significant_figures: int = 3
    """Significant figures floats are rounded to in `units_viz.parquet`."""

    viz_distance_scale: int = 1000
    """Multiplier applied to the 17 distances before they are stored as `int16`."""

    gis_format: Literal["none", "gpkg"] = "gpkg"
    """Also write the unit table as `units.gpkg`.

    `units.parquet` is valid GeoParquet with its CRS, but GDAL's Parquet driver is optional, so some
    QGIS builds open it without a CRS. GeoPackage is in GDAL's core. Costs 1.8 s and 67 MB at
    116 491 units.
    """

    @model_validator(mode="after")
    def _check(self) -> OutputConfig:
        if self.break_count < 2:
            raise ValueError(f"break_count must be at least 2, got {self.break_count}")
        if self.viz_significant_figures < 1:
            raise ValueError(
                f"viz_significant_figures must be at least 1, got {self.viz_significant_figures}"
            )
        if self.viz_distance_scale < 1:
            raise ValueError(f"viz_distance_scale must be positive, got {self.viz_distance_scale}")
        return self


class VizConfig(BaseModel):
    """The static map site `lczkit.viz.build_site` writes into a run.

    Zoom ranges are recorded because a tileset is only reproducible if the zooms that made it are.
    """

    unit_min_zoom: int = 10
    unit_max_zoom: int = 14
    """Unit tileset zooms. A 100 m cell is ~21 px at z14; MapLibre overzooms beyond."""

    basemap_min_zoom: int = 9
    basemap_max_zoom: int = 13
    """One zoom short of the units: the basemap sits under a translucent fill, and dropping z14
    halved a measured land-use tileset."""

    basemap_simplification: int = 10
    """tippecanoe `--simplification` for the basemap only. Unit and building tilesets are left at
    tippecanoe's faithful default."""

    basemap_layers: list[str] = Field(default_factory=lambda: ["water", "streets"])
    """Persisted context layers to draw, in order. `"land_use"` is available and off: it was 94% of
    the basemap's bytes at 9 km²."""

    building_min_zoom: int = 14
    building_max_zoom: int = 16

    include_buildings: bool = False
    """Tile the building footprints for extrusion. Off: at metropolitan scale they cost two to three
    times the rest of the site."""

    render_columns: list[str] = Field(
        default_factory=lambda: [
            "lcz_primary",
            "lcz_secondary",
            "uniqueness",
            "height_completeness",
            "building_surface_fraction",
            "impervious_surface_fraction",
            "pervious_surface_fraction",
            "tree_fraction",
            "water_fraction",
            "height_of_roughness_elements_m",
            "aspect_ratio",
            "street_openness",
            "mean_building_area_m2",
            "industrial_fraction_of_building_area",
        ]
    )
    """Attributes tiled at every zoom, for choropleths. Everything else rides in a detail tileset
    at maximum zoom only, because MVT repeats a feature's attributes in every tile at every zoom.
    Names a run did not produce are skipped."""

    render_column_prefixes: list[str] = Field(default_factory=lambda: ["height_frac_"])
    """Column families tiled at every zoom, by prefix: the height tier fractions are named after
    whichever cascade ran."""

    detail_max_features: int = 200_000
    """Above this many units the detail tileset is skipped and the sidebar shows render attributes
    only."""

    online_basemaps: list[str] = Field(default_factory=list)
    """Remote raster grounds offered in the site's picker, by key from
    `lczkit.viz.basemaps.PROVIDERS`.

    Empty by default, so a library-built site names no remote host and works offline years from
    now. The command line offers the keyless grounds unless told `--basemap none`.
    """

    maptiler_key: str | None = Field(default=None, exclude=True)
    """MapTiler API key, from `MAPTILER_API_KEY`.

    Excluded from serialisation so it never reaches the manifest (which the site copies); it
    reaches only `style.json`'s tile URLs, where the browser needs it in plain text.
    """

    @model_validator(mode="before")
    @classmethod
    def _fold_deprecated_singular(cls, data: Any) -> Any:
        """Read `online_basemap`, the singular field manifests written before the list recorded."""
        if isinstance(data, dict) and "online_basemap" in data:
            data = dict(data)
            singular = data.pop("online_basemap")
            if singular:
                data["online_basemaps"] = [singular, *data.get("online_basemaps", [])]
        return data

    @model_validator(mode="after")
    def _check(self) -> VizConfig:
        for low, high, name in (
            (self.unit_min_zoom, self.unit_max_zoom, "unit"),
            (self.basemap_min_zoom, self.basemap_max_zoom, "basemap"),
            (self.building_min_zoom, self.building_max_zoom, "building"),
        ):
            if not 0 <= low <= high <= 24:
                raise ValueError(
                    f"{name} zooms must satisfy 0 <= min <= max <= 24, got {low} and {high}"
                )
        if self.detail_max_features < 1:
            raise ValueError(
                f"detail_max_features must be positive, got {self.detail_max_features}"
            )
        if self.basemap_simplification < 0:
            raise ValueError(
                f"basemap_simplification must not be negative, got {self.basemap_simplification}"
            )
        if any(not prefix for prefix in self.render_column_prefixes):
            # An empty prefix matches every column and would tile the whole table at every zoom.
            raise ValueError("render_column_prefixes must not contain an empty string")
        allowed = {"land_use", "water", "streets"}
        unknown = sorted(set(self.basemap_layers) - allowed)
        if unknown:
            raise ValueError(
                f"unknown basemap layers {', '.join(unknown)}; "
                f"choose from {', '.join(sorted(allowed))}"
            )
        self.online_basemaps = list(dict.fromkeys(key for key in self.online_basemaps if key))
        if self.online_basemaps:
            # Imported here: `lczkit.viz` pulls in the tile builder, and everything imports config.
            from lczkit.viz.basemaps import PROVIDERS

            for key in self.online_basemaps:
                if key not in PROVIDERS:
                    raise ValueError(
                        f"unknown basemap {key!r}; choose from {', '.join(sorted(PROVIDERS))}"
                    )
        return self


def _default_reference_dataset() -> LandCoverDatasetConfig:
    """The Demuzere global LCZ map, described as a categorical raster.

    Validation then reuses `LocalRasterSource`'s zonal reduction.
    Nodata is assigned to its own class rather than excluded, so each unit's coverage by the map
    survives and a unit half outside it is not scored on a corner of itself.
    """
    return LandCoverDatasetConfig(
        name="demuzere_lcz",
        source_dir_name="Demuzere_2022_complete",
        classes=[*(f"lcz_{code}" for code in range(1, 18)), "nodata"],
        value_classes={code: f"lcz_{code}" for code in range(1, 18)},
        column_prefix="ref_",
        nodata=0.0,
        nodata_policy="assign",
        nodata_class="nodata",
        unmapped_policy="raise",
    )


UnitStrategy = Literal["grid", "enclosure", "patch"]

RasterFormat = Literal["gtiff", "cog", "zarr"]
"""Morphometrics raster format.

`"gtiff"` is a plain GeoTIFF; `"cog"` the same file tiled with overviews for partial HTTP reads.
`"zarr"` is written through `xarray`/`rioxarray` rather than GDAL's `Zarr` driver, which stores
the CRS only in a GDAL `pam.aux.xml` sidecar that a plain `zarr`/`xarray` reader cannot see.
"""


class UnitsConfig(BaseModel):
    """Which spatial units the pipeline classifies.

    No automatic choice, by region or otherwise: the trade-off is documented and the strategy that
    ran is recorded in the manifest.
    """

    strategy: UnitStrategy = "grid"
    """`grid` (default), `enclosure` or `patch`.

    - **`grid`**: 100 m cells, what every LCZ map, validation dataset and WRF workflow uses.
    - **`enclosure`**: street-, rail- and water-bounded blocks. Over fifteen cities built-class
      agreement was +3.8 points and overall −0.2, so not adopted as the default.
    - **`patch`**: enclosures merged to LCZ-patch scale; a block (median 0.04 ha) is much smaller
      than a WUDAPT patch (2.2-52 ha). See `lczkit.units.patches`.
    """

    cell_size_m: float = 100.0
    """Grid cell side. Other sizes are comparable with no published figure or reference."""

    patch_min_area_m2: float = 50_000.0
    """`patch` only. A floor, not a centre: the median lands near twice it."""

    patch_max_area_m2: float | None = 500_000.0
    """`patch` only. Oversized seeds are split to this before merging; `None` removes it."""

    patch_merge_on_morphology: bool = True
    """`patch` only: merge towards the neighbour most similar in building surface fraction and
    height, rather than on size alone."""

    drop_pedestrian_barriers: bool = True
    """Leave footway/steps/path/cycleway/bridleway out of the barrier set for `enclosure` and
    `patch`. They are 50-73% of the mapped network in Berlin, Hong Kong and Milan and 3.5-7.5%
    elsewhere, so keeping them measures footpath survey effort rather than the city."""

    @model_validator(mode="after")
    def _check(self) -> UnitsConfig:
        if self.cell_size_m <= 0:
            raise ValueError(f"cell_size_m must be positive, got {self.cell_size_m}")
        if self.patch_min_area_m2 <= 0:
            raise ValueError(f"patch_min_area_m2 must be positive, got {self.patch_min_area_m2}")
        if self.patch_max_area_m2 is not None and self.patch_max_area_m2 < self.patch_min_area_m2:
            raise ValueError(
                f"patch_max_area_m2 ({self.patch_max_area_m2}) must be at least "
                f"patch_min_area_m2 ({self.patch_min_area_m2}); a ceiling below the floor would "
                "block every merge"
            )
        return self


class WudaptConfig(BaseModel):
    """The WUDAPT LCZ training areas: the globally available hand-labelled reference.

    Note these polygons are the training data behind the Demuzere global map, so agreement between
    the two is not an independent ceiling. See `lczkit.validation.wudapt`.
    """

    source_dir_name: str = "WUDAPT"
    """Subdirectory under `input/` holding the WUDAPT export."""

    filename: str | None = None
    """The dated LCZ Generator export, e.g. `LCZ-Generator_training_areas_2024-10-01.gpkg`. Must be
    pinned: contributors keep adding to it, so an unpinned name changes the reference."""

    layer: str | None = None
    """GeoPackage layer; `None` takes the first, which is right for the published export."""

    class_column: str = "class"
    """WUDAPT's LCZ column, coded 1-17 as in Demuzere."""

    require_qc: bool = False
    """Keep only polygons passing all three QC flags. Off: it halves the reference and moved
    agreement with So2Sat by +0.4, +2.9 and −1.9 points on Cairo, Mumbai and Jakarta."""

    min_oa: float | None = None
    """Minimum LCZ Generator accuracy of the polygon's *submission*. Off: at 0.7 it made agreement
    with So2Sat worse on all three test cities, because `oa` scores a submission against itself."""

    min_area_m2: float = 0.0
    """Drop polygons below this area."""

    max_area_m2: float | None = None
    """Drop polygons above this area. The largest is an 18 680 km² sea."""

    citation: str = "10.3390/ijgi4010199"
    """Bechtel et al. (2015), *IJGI* 4(1), 199-219: the WUDAPT Level 0 protocol."""

    @model_validator(mode="after")
    def _check(self) -> WudaptConfig:
        if self.min_oa is not None and not 0.0 <= self.min_oa <= 1.0:
            raise ValueError(f"min_oa must be in [0, 1], got {self.min_oa}")
        if self.min_area_m2 < 0.0:
            raise ValueError(f"min_area_m2 must be non-negative, got {self.min_area_m2}")
        if self.max_area_m2 is not None and self.max_area_m2 <= self.min_area_m2:
            raise ValueError(
                f"max_area_m2 ({self.max_area_m2}) must exceed min_area_m2 ({self.min_area_m2})"
            )
        return self


class ValidationConfig(BaseModel):
    """Agreement against reference LCZ maps, reported per class and as a confusion matrix."""

    reference: LandCoverDatasetConfig = Field(default_factory=_default_reference_dataset)
    """The Demuzere global map, described as a categorical raster."""

    reference_citation: str = "10.5194/essd-14-3835-2022"
    """Demuzere et al. (2022). The file in use is `lcz_v3.tif`, a later version than the paper
    describes; the two are recorded separately."""

    ground_truth_citation: str = "10.1109/MGRS.2020.2964708"
    """Zhu et al. (2020), So2Sat LCZ42: hand labels, and the primary reference where they exist.
    `lcz_v3` is a model with its own error and only a comparator."""

    wudapt: WudaptConfig = Field(default_factory=WudaptConfig)
    """The WUDAPT training areas."""

    min_reference_coverage: float = 0.5
    """Share of a unit the reference must cover for the unit to be scored."""

    height_completeness_deciles: int = 10
    """Equal-width strata for the height-completeness breakdown."""

    @model_validator(mode="after")
    def _check(self) -> ValidationConfig:
        if not 0.0 <= self.min_reference_coverage <= 1.0:
            raise ValueError(
                f"min_reference_coverage must be in [0, 1], got {self.min_reference_coverage}"
            )
        if self.height_completeness_deciles < 2:
            raise ValueError(
                "height_completeness_deciles must be at least 2, got "
                f"{self.height_completeness_deciles}"
            )
        return self


class MorphometricsConfig(BaseModel):
    """The 2D morphometrics stage (Majer & Fleischmann 2026), a descriptive output only.

    Computed on enclosed tessellation cells and written as `morphometrics.parquet` (and a raster if
    `raster_resolution_m` is set); never joined to `units.parquet` or read by the classifier. Off by
    default because its cost rises steeply with extent. The neighbourhood scales are the paper's
    and live in `lczkit.morphometrics.compute`, since the registry names every column after them.
    """

    enabled: bool = False

    tessellation_shrink: float = 0.4
    """`momepy.enclosed_tessellation` `shrink`; momepy's default."""

    tessellation_segment: float = 0.5
    """`momepy.enclosed_tessellation` `segment`; momepy's default."""

    tessellation_threshold: float | None = 0.05
    """`momepy.enclosed_tessellation` `threshold`; momepy's default."""

    tessellation_n_jobs: int = -1
    """Processes `momepy.enclosed_tessellation` may spawn; `-1` is every core. Set `1` inside your
    own process pool: thread pinning does not cap processes, and 8 workers left at `-1` measured
    2 923 processes on a 256-core node."""

    street_profile_distance_m: float = 10.0
    """Tick spacing for the 2D street profile. Separate from `UcpConfig`'s so tuning one does not
    retune the other."""

    street_profile_tick_length_m: float = 50.0

    contextual: bool = False
    """Add the 25th/50th/75th percentile of each attribute over neighbouring cells. Unlike the
    paper, the primary attributes are kept alongside."""

    contextual_steps: int = 3
    """Topological steps the contextual neighbourhood spans."""

    contextual_quantiles: list[int] = Field(default_factory=lambda: [25, 50, 75])

    max_tessellation_cells: int = 50_000
    """Refuse the stage above this many cells. Measured on Berlin: 51 s at 5 406 cells and
    1 029 s at 12 322, so the ceiling is set well below any extrapolation."""

    max_contextual_cells: int = 20_000
    """A tighter ceiling for the contextual expansion, whose graph is denser."""

    raster_resolution_m: float | None = None
    """Rasterise the attributes at this resolution; `None` skips. `lczkit morphometrics raster`
    regenerates it later at another resolution."""

    max_raster_cells: int = 50_000_000
    """Refuse a raster grid larger than this."""

    raster_format: RasterFormat = "gtiff"

    raster_tile_deg: float | None = None
    """Split the raster into a geographic tile grid of this size, named `grid_{lon:.2f}_{lat:.2f}`
    after each tile's centre as `geotessera` does. `None` writes one file. Empty tiles are
    dropped."""

    max_raster_bytes: int = 4_000_000_000
    """Refuse a band stack (`bands x rows x cols x 4` bytes) above this. An arithmetic memory
    ceiling, not a measured one."""

    @model_validator(mode="after")
    def _check(self) -> MorphometricsConfig:
        if self.tessellation_shrink <= 0 or self.tessellation_segment <= 0:
            raise ValueError("tessellation_shrink and tessellation_segment must be positive")
        if (
            self.tessellation_threshold is not None
            and not 0.0 <= self.tessellation_threshold <= 1.0
        ):
            raise ValueError(
                f"tessellation_threshold must be in [0, 1] or None, got "
                f"{self.tessellation_threshold}"
            )
        if not self.contextual_quantiles or any(not 0 < q < 100 for q in self.contextual_quantiles):
            raise ValueError(
                f"contextual_quantiles must be non-empty and within (0, 100), got "
                f"{self.contextual_quantiles}"
            )
        if self.contextual_steps < 1:
            raise ValueError(f"contextual_steps must be at least 1, got {self.contextual_steps}")
        if self.raster_resolution_m is not None and self.raster_resolution_m <= 0:
            raise ValueError(
                f"raster_resolution_m must be positive, got {self.raster_resolution_m}"
            )
        for name in (
            "max_tessellation_cells",
            "max_contextual_cells",
            "max_raster_cells",
            "max_raster_bytes",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive, got {getattr(self, name)}")
        if self.raster_tile_deg is not None and self.raster_tile_deg <= 0:
            raise ValueError(f"raster_tile_deg must be positive, got {self.raster_tile_deg}")
        return self


class Settings(BaseModel):
    """Resolved configuration for one run. Construct with `Settings.load()`."""

    data_dir: Path
    run_id: str = Field(default_factory=_default_run_id)
    overture: OvertureConfig = Field(default_factory=OvertureConfig)
    cleaning: CleaningConfig = Field(default_factory=CleaningConfig)
    morphometrics: MorphometricsConfig = Field(default_factory=MorphometricsConfig)
    heights: HeightConfig = Field(default_factory=HeightConfig)
    land_cover: LandCoverConfig = Field(default_factory=LandCoverConfig)
    units: UnitsConfig = Field(default_factory=UnitsConfig)
    ucp: UcpConfig = Field(default_factory=UcpConfig)
    classification: ClassificationConfig = Field(default_factory=ClassificationConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    viz: VizConfig = Field(default_factory=VizConfig)

    @field_validator("data_dir")
    @classmethod
    def _validate_data_dir(cls, value: Path) -> Path:
        if not value.is_dir():
            raise ValueError(
                f"DATA_DIR does not exist or is not a directory: {value}. "
                "Set DATA_DIR in .env to the shared data directory."
            )
        return value

    @model_validator(mode="after")
    def _semantic_rules_have_their_evidence(self) -> Settings:
        """Refuse enabled semantic rules reading a column no configured group emits.

        Checked at config load rather than at the end of a long run.
        """
        from lczkit.ucp.semantics import group_columns

        available = set(group_columns(self.ucp.semantic_groups))
        missing = {
            rule.name: rule.column
            for rule in self.classification.semantic_rules
            if rule.enabled and rule.column not in available
        }
        if missing:
            named = ", ".join(
                f"{name} reads {column!r}" for name, column in sorted(missing.items())
            )
            raise ValueError(
                f"enabled semantic rules read columns no configured group emits: {named}. "
                "Add the group to `ucp.semantic_groups`, or disable the rule in "
                "`classification.semantic_rules`."
            )
        return self

    @property
    def input_dir(self) -> Path:
        """`$DATA_DIR/input/`: organised by data origin, shared with other projects."""
        return self.data_dir / "input"

    @property
    def output_dir(self) -> Path:
        """`$DATA_DIR/output/`: organised by the tool that produced the results."""
        return self.data_dir / "output"

    @property
    def run_dir(self) -> Path:
        """`$DATA_DIR/output/lczkit/<run_id>/`: this run's own directory."""
        return self.output_dir / "lczkit" / self.run_id

    @property
    def tile_cache_dir(self) -> Path:
        """`$DATA_DIR/output/lczkit/_cache/tiles/`: memoised per-tile street simplification.

        Under lczkit's own output tree rather than `input/`, because a simplified tile is derived
        by lczkit, not source data, and it outlives the run that computed it.
        """
        return self.output_dir / "lczkit" / "_cache" / "tiles"

    def source_dir(self, name: str) -> Path:
        """`input/<name>/`, the directory the source implementation for `name` owns."""
        return self.input_dir / name

    @classmethod
    def load(
        cls,
        *,
        run_id: str | None = None,
        dotenv_path: Path | str | None = None,
        create_run_dir: bool = True,
    ) -> Settings:
        """Load `.env`, resolve `DATA_DIR`, and create `output/lczkit/<run_id>/` unless told not to.

        Also reads the optional `GEE_PROJECT_NAME` and `MAPTILER_API_KEY`. An absent variable leaves
        any configured value alone rather than overwriting it with `None`. Never touches `input/`.
        Raises `ValueError` if `DATA_DIR` is unset, and a `ValidationError` if it does not exist.
        """
        load_dotenv(dotenv_path=dotenv_path)
        raw_data_dir = os.environ.get("DATA_DIR")
        if raw_data_dir is None:
            raise ValueError(
                "DATA_DIR is not set. Copy .env.example to .env and point DATA_DIR at the "
                "shared data directory."
            )
        settings = (
            cls(data_dir=Path(raw_data_dir), run_id=run_id)
            if run_id is not None
            else cls(data_dir=Path(raw_data_dir))
        )
        gee_project = os.environ.get("GEE_PROJECT_NAME")
        if gee_project is not None:
            settings.land_cover.gee_project = gee_project
        api_key = maptiler_key(dotenv_path=dotenv_path)
        if api_key is not None:
            settings.viz.maptiler_key = api_key
        if create_run_dir:
            settings.run_dir.mkdir(parents=True, exist_ok=True)
        return settings


def maptiler_key(*, dotenv_path: Path | str | None = None) -> str | None:
    """`MAPTILER_API_KEY` from the environment, stripped, or `None` if unset or blank.

    Separate from `Settings.load` because `lczkit site build` needs the key without `DATA_DIR`. The
    strip matters: a trailing space in `.env` would otherwise make every tile request 403.
    """
    load_dotenv(dotenv_path=dotenv_path)
    raw = os.environ.get("MAPTILER_API_KEY")
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None
