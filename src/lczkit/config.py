"""Pydantic configuration model for lczkit runs.

`DATA_DIR` is resolved exactly once, here, via `Settings.load()`. Every other module reaches
data through `settings.input_dir`, `settings.output_dir`, `settings.source_dir(name)`, and
`settings.run_dir` — nothing else reads `os.environ` or builds a path from `__file__` or the
current working directory.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator


def _default_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


class OvertureConfig(BaseModel):
    """Configuration for `OvertureSource`, the Overture Maps vector source."""

    release: str | None = None
    """Pinned Overture release string, e.g. "2026-07-22.0". Never "latest" — `OvertureSource`
    raises if this is unset."""

    source_dir_name: str = "Overture_Maps"
    """Name of the subdirectory under `input/` that `OvertureSource` caches into. Matches the
    directory already used by other projects sharing `DATA_DIR`, rather than the plain
    "Overture"."""


class CleaningConfig(BaseModel):
    """Configurable thresholds for the building-cleaning pipeline.

    None of these have a literature-derived default — Majer & Fleischmann (arXiv:2603.00132)
    Supplementary D, the cleaning specification these operations follow, describes them only
    qualitatively. They are left unset here; the cleaning pipeline raises if used before being
    explicitly configured.
    """

    building_max_area_m2: float | None = None
    """Footprints larger than this are dropped as implausible."""

    building_min_area_m2: float | None = None
    """Footprints smaller than this are dissolved into a touching larger neighbour on
    `buildings_topo`. Those touching nothing are kept: small is not spurious."""

    building_road_buffer_m: float | None = None
    """Half-width of the road buffer the `buildings_topo` street rule measures against, in metres.

    Derived from the fixtures rather than the literature. At 4.0 m the overlap fraction separates
    perimeter blocks from structures standing in the roadway; at 2.0 m the distribution is too
    compressed to separate anything (p95 = 0.46) and at 8.0 m it swallows the blocks (p90 = 0.98).
    """

    building_road_overlap_limit: float | None = None
    """Fraction of a footprint inside the road buffer above which it is dropped rather than trimmed.

    Also fixture-derived: 0.5 is where the median dropped footprint falls below the median building
    (230 m² on Berlin), recovering 95% of the area the old centreline rule destroyed. Both this and
    `building_road_buffer_m` were measured on two European cities and should be re-derived for a
    city whose fabric or road-centreline generalisation differs.
    """

    building_merge_limit_m2: float | None = None
    """`geoplanar.merge_overlaps`' `merge_limit` — overlapping polygons smaller than this are
    merged into a neighbour regardless of overlap size."""

    building_overlap_limit: float | None = None
    """`geoplanar.merge_overlaps`' `overlap_limit` (0-1 ratio) — polygons larger than
    `building_merge_limit_m2` are merged only if the shared overlap exceeds this fraction of
    their area."""

    street_tile_size_m: float | None = None
    """Edge length of the tiles street simplification is chunked into, in metres.

    `None` runs `neatnet` over the whole extent. Set it to engage the tiled path, which is
    required above roughly 50 km2, where whole-extent simplification stops completing in usable
    time (100 km2 measured at 50 minutes on one core, 256 km2 abandoned after 4h12m).

    2000.0 m is the fixture-derived working value: tiles small enough to keep the largest face-
    artifact component tractable, large enough that seam handling stays a small share of the work.
    """

    street_tile_buffer_m: float | None = None
    """Working margin added around each tile before simplification, in metres.

    Each tile is simplified over `core + buffer` and contributes only its core, so a feature at
    the seam is decided with its neighbourhood present. Measured on Berlin: raising this from
    300 m to 600 m cut spurious linework — geometry the tiled run invents that the whole-extent
    run does not have — from 1.23 km to 0.11 km, and 900 m bought nothing further. Below about
    300 m the buffer stops containing a dual carriageway's artifact and seams degrade sharply.
    """

    street_tile_workers: int | None = None
    """Processes to run tiles across. `None` uses every core the process is allowed."""

    street_artifact_threshold: float | None = None
    """Face-artifact index above which a face is ordinary fabric rather than a road artifact.

    `None` derives it from the data — pooled across tiles on the tiled path, whole-network on
    the untiled one. Setting it pins the value, which is what an A/B between two thresholds
    needs, and lets a recorded run restate its threshold instead of re-deriving it.

    A threshold on a `neatnet` index, not a fallback: `neatnet`'s own fallback for a distribution
    with no valley stays in `lczkit.cleaning.streets.ARTIFACT_THRESHOLD_FALLBACK`.
    """


class ArealTierConfig(BaseModel):
    """One areal raster tier of the height cascade (tiers 2-4).

    Areal products assign a *neighbourhood* mean to individual buildings, which is a
    categorically weaker measurement than a per-building height. Everything product-specific
    lives here rather than in code: none of these three products is present on this system, and
    none of their documentation is in `docs/references/datasets/`, so hardcoding a band number,
    a unit scale or a nodata value would be guessing at a product nobody has read the manual for.
    """

    name: str
    """The tier's `height_source` tag, e.g. `"ghsl"`. Must be unique within a cascade."""

    source_dir_name: str
    """Subdirectory under `input/` holding this product, resolved via `settings.source_dir()`."""

    enabled: bool = True
    """Whether this tier takes part in the default cascade.

    Deliberately distinct from `filename is None`, which says the product is *not there*. This
    says it is available and switched off, and the two must stay distinguishable in the manifest:
    a tier that never fired because nobody placed the data is a different fact from one that never
    fired because it was measured and rejected.
    """

    filename: str | None = None
    """COG filename within `input/<source_dir_name>/`. `None` means the product is not available
    and the tier is skipped entirely — the cascade is shorter, not broken."""

    band: int = 1
    """1-based raster band carrying height."""

    scale: float = 1.0
    """Multiplier converting raw raster values to metres (e.g. 0.1 for a decimetre product)."""

    nodata: float | None = None
    """Override the raster's own declared nodata value. `None` uses whatever the file declares."""

    min_height_m: float = 0.0
    """Sampled values at or below this are treated as "no building here" rather than as a
    height, so the next tier gets a chance. Zero is the neutral choice: an areal height product
    reports 0 for cells with no built-up volume.

    **It stays zero for every shipped tier, including Open Buildings 2.5D**, whose sampled heights
    are 19% below 2 m against about 1% for the coarse products. A floor tuned until that stopped
    hurting would be a threshold no documentation supports, and it would be copied into other
    pipelines and outlive its justification. It also treats the wrong thing: the measured damage
    is within-unit *dispersion* (CV 0.441 against reality's 0.195), and clipping one side of an
    over-wide distribution leaves the other side where it was. The route to rescuing a
    fine-resolution product is shrinkage toward the unit mean, which is not implemented.
    """

    confidence: float | None = None
    """`height_confidence` written for every building this tier resolves. No default: see
    `HeightConfig`."""


def _default_areal_tiers() -> list[ArealTierConfig]:
    """Tiers 2, 3 and 4 of the cascade, in order.

    **The default cascade is `coarse`.**

    `GHSL` is deliberately not the `input/GHS/` some systems already carry: that directory holds
    GHS-SMOD and GHS-UCDB for other purposes, and a new sibling costs nothing while writing into
    a shared directory risks something.

    The per-product raster parameters below are read from each product's own documentation —
    see `HeightProductsConfig` — not inferred from the files. `filename` stays `None`, because a
    tier's file is resolved per study area by `lczkit.sources.height_products` and a filename
    baked in here would be a filename for one city.

    **Open Buildings 2.5D ships `enabled=False`.** It is the finest tier, has the lowest
    per-building error of the three (MAE 5.39 m against 7.44 and 8.17) and is the only one with
    any within-unit skill (pooled Spearman +0.289 against +0.042 and +0.001) — and it makes the
    map *worse*: `coarse -> full` is −1.9 points of built-class agreement, positive in only 4 of
    9 cities, with Mumbai falling below its own tier-1-only baseline. `Hr`
    is a geometric mean, which dispersion depresses, and this product's within-unit spread is
    0.441 against reality's 0.195. Per-building accuracy is the wrong acceptance test for a height
    product feeding an LCZ map. The tier stays implemented and one flag from use.
    """
    return [
        ArealTierConfig(
            name="gob25d",
            source_dir_name="GOB25D",
            enabled=False,
            scale=1.0,
            min_height_m=0.0,
        ),
        ArealTierConfig(
            name="wsf3d", source_dir_name="WSF3D", scale=0.1, nodata=-32767.0, min_height_m=0.0
        ),
        ArealTierConfig(
            name="ghsl", source_dir_name="GHSL", scale=1.0, nodata=255.0, min_height_m=0.0
        ),
    ]


class Wsf3dConfig(BaseModel):
    """Tier 3 — WSF-3D V02 building height (DLR, TanDEM-X derived), CC-BY-4.0.

    Parameters from DLR's own `README_BuildingHeight.txt`: 2.8 arcsec (~90 m at the equator),
    "provided in meter with a gain factor of 0.1 for storage optimization (Int16)", nodata
    -32767. The gain is why the tier carries `scale=0.1`; reading it as metres would report a
    ten-storey block as a kerbstone.
    """

    tier_name: str = "wsf3d"
    source_dir_name: str = "WSF3D"
    version: str = "V02"
    filename: str = "WSF3D_V02_BuildingHeight.tif"
    url: str = "https://download.geoservice.dlr.de/WSF3D/files/global/WSF3D_V02_BuildingHeight.tif"
    """The global product, a tiled GeoTIFF with overviews — read by window, never clipped.

    A 2.1 GB download, once, and there is no alternative to it: WSF-3D is **not** in the Earth
    Engine public catalogue. `DLR/WSF` publishes only `WSF2015`, a 10 m binary settlement mask,
    which is not a height product. Since this tier answers for 92-99% of building area in the
    cities measured, no Earth Engine route can stand in for the cascade as a whole.
    """


class GhslProductConfig(BaseModel):
    """Tier 4 — GHS-BUILT-H ANBH R2023A (JRC), free reuse with attribution.

    ANBH, not the AGBH published beside it: the GHSL Data Package 2023 (p. 26) defines
    `ANBH = BUVOL / BUSURF`, building volume over *built-up* surface, so it is the mean height of
    the built fabric rather than a height averaged over open ground. Float32 metres, nodata 255,
    100 m World Mollweide (p. 36).

    This product *is* in the Earth Engine catalogue, as `JRC/GHSL/P2023A/GHS_BUILT_H/2018` band
    `built_height`, and it is the same numbers: sampled against these tiles at 180 points across
    two height strata it agrees to 0.000000 m. It is fetched over HTTP anyway, because a second
    route to an identical raster only adds a credential requirement — and because WSF-3D, the tier
    above it, has no Earth Engine asset at all. See `lczkit.sources.height_products`.
    """

    tier_name: str = "ghsl"
    source_dir_name: str = "GHSL"
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


class OpenBuildings25dConfig(BaseModel):
    """Tier 2 — Google Open Buildings 2.5D Temporal v1, CC-BY-4.0, via Earth Engine.

    The highest-value tier for exactly the regions where tier 1 fails, and the only one with no
    public bucket behind it. `building_height` is metres above terrain in `[0, 100]` at an
    effective 4 m resolution, annual 2016-2023, over Africa, South and South-East Asia, Latin
    America and the Caribbean.

    The two request caps are Earth Engine's, and they are here rather than in code because they
    are a property of the service, not of this package — when they move, this moves.
    """

    tier_name: str = "gob25d"
    source_dir_name: str = "GOB25D"
    collection: str = "GOOGLE/Research/open-buildings-temporal/v1"
    band: str = "building_height"
    year: int = 2023
    """Latest annual epoch. Pinned rather than "latest" for the same reason the Overture release
    is: a run that silently changes epoch is a run nobody can reproduce."""

    scale_m: float = 4.0
    """The product's effective resolution. Requesting the underlying 0.5 m grid would multiply
    the payload sixty-four-fold for detail the model does not carry."""

    max_pixels_per_request: int = 50_331_648
    max_bytes_per_request: int = 33_554_432


class HeightProductsConfig(BaseModel):
    """Where the areal height products come from, pinned for the manifest.

    Separate from `HeightConfig`, which says how a tier *reads* a raster. This says how the
    raster gets onto disk — release strings, URLs, the Earth Engine collection and epoch. Both
    are serialised into the run manifest; only together do they make a cascade reproducible.
    """

    wsf3d: Wsf3dConfig = Field(default_factory=Wsf3dConfig)
    ghsl: GhslProductConfig = Field(default_factory=GhslProductConfig)
    gob25d: OpenBuildings25dConfig = Field(default_factory=OpenBuildings25dConfig)


class HeightConfig(BaseModel):
    """Configuration for the building-height cascade.

    Tiers run in the order they appear: Overture attributes first, then `areal_tiers` in list
    order. Adding a fifth areal product is an entry in that list, not a code change.

    The three `*_confidence` values have no default for the same reason `CleaningConfig`'s
    thresholds have none: no published number defines them. `height_confidence` is an ordinal
    ranking of measurement quality, not a calibrated probability, and a plausible-looking invented
    default is the worst failure mode available here — nothing would crash, and the map would
    carry a quietly wrong quality claim. Set them explicitly and they are
    serialised into the run manifest, where the choice is visible and reproducible.
    """

    storey_height_m: float = 3.0
    """Metres per storey for the `num_floors` fallback. Varies regionally and is a real error
    source; 3.0 m is a conventional default and should be set per city where one is known."""

    overture_height_confidence: float | None = None
    """`height_confidence` for buildings resolved from Overture's `height` attribute — except
    where Overture itself supplies a per-building confidence, which is preferred over this."""

    overture_num_floors_confidence: float | None = None
    """`height_confidence` for buildings resolved from `num_floors x storey_height_m`."""

    areal_tiers: list[ArealTierConfig] = Field(default_factory=_default_areal_tiers)
    """Tiers 2-4, in cascade order. The default is `coarse` — see `_default_areal_tiers`."""


NodataPolicy = Literal["exclude", "assign"]
"""What a nodata cell means for a given land-cover product.

`"exclude"` — the product made no observation here, so the cell leaves the denominator entirely
and the remaining fractions still sum to 1.0. `"assign"` — the product deliberately masks this
surface, and the mask itself carries meaning, so the cell counts towards a named class.

The distinction is not cosmetic. Lang et al. (2023), `10.1038/s41559-023-02206-6`, mask built-up
areas, snow, ice and permanent water out of the ETH canopy height product and set those cells to
255. That is a deliberate removal of surfaces known to carry no canopy, not a gap in coverage:
over the Berlin test fixture 93% of built-up cells and 78% of the whole tile are 255, and reading
them as `"exclude"` reports central Berlin as ~96% tree cover instead of ~22%.
"""

UnmappedPolicy = Literal["exclude", "assign", "raise"]
"""What to do with a raster value no class mapping covers.

`"raise"` is the default: an unmapped value means the configured mapping does not match the
product actually on disk, and silently dropping or lumping those cells would produce a quietly
wrong map.
"""


GeeAssetType = Literal["image_collection", "image"]
"""Whether an Earth Engine asset is a collection to filter and mosaic, or a single image.

Both occur among the MVP datasets: ESA WorldCover is a catalogued `ImageCollection`, while ETH
canopy height is a single `Image` published as a user asset. Loading one as the other is an
immediate `EEException`, so the kind is declared rather than probed.
"""


class GeeAssetConfig(BaseModel):
    """Earth Engine coordinates for one land-cover dataset.

    Serialised verbatim into the run manifest, so the collection ID and date range a run used are
    part of its record.
    """

    collection_id: str | None = None
    """Full asset ID, e.g. `"ESA/WorldCover/v200"`. `None` means no Earth Engine asset has been
    verified for this dataset and `EarthEngineSource` refuses to guess at one."""

    asset_type: GeeAssetType = "image_collection"
    """See `GeeAssetType`."""

    band: str | None = None
    """Band name within the asset, e.g. `"Map"`."""

    start_date: str | None = None
    """Inclusive ISO date passed to `filterDate`. Required for an `image_collection`; recorded but
    not applied for a single `image`, which has no collection to filter."""

    end_date: str | None = None
    """Exclusive ISO date passed to `filterDate`. Same caveat as `start_date`."""

    scale_m: float | None = None
    """Reduction scale in metres. Should match the product's native resolution — a coarser scale
    silently resamples and changes every fraction."""

    def required_fields(self) -> tuple[str, ...]:
        """Fields `EarthEngineSource` cannot run without, given this asset's kind."""
        common = ("collection_id", "band", "scale_m")
        if self.asset_type == "image":
            return common
        return (*common, "start_date", "end_date")


class LandCoverDatasetConfig(BaseModel):
    """One land-cover product and the mapping from its raw values to fraction classes.

    Everything product-specific lives here rather than in code: the class-to-fraction mapping is
    config, never hardcoded. `LocalRasterSource` and `EarthEngineSource` read
    the same instance, which is what makes the two backends return schema-identical tables.

    A dataset is either *categorical* (`value_classes`) or *binned* (`bins` + `bin_classes`),
    never both. Classes are disjoint and their fractions sum to 1.0 over the cells that count.
    """

    name: str
    """Short identifier, e.g. `"worldcover"`. Used in cache filenames and error messages, and
    must be unique within `LandCoverConfig.datasets`."""

    source_dir_name: str
    """Subdirectory under `input/` holding this product, resolved via `settings.source_dir()`."""

    filename: str | None = None
    """COG filename within `input/<source_dir_name>/`. `None` means the product is not available
    locally; `LocalRasterSource.from_settings` refuses to build a source for it."""

    band: int = 1
    """1-based raster band to read from the local COG."""

    column_prefix: str = "frac_"
    """Prefixed to every class name to form the output column names. Distinct prefixes are how
    two datasets that both emit a `tree` class stay joinable on `unit_id` without collision."""

    classes: list[str]
    """The full, ordered output class list. Fixes the output schema to config rather than to
    whichever classes happen to occur in a given city, so a class with no cells still gets a
    column holding 0.0 and two cities produce the same columns. The height-tier fractions are
    fixed to the configured cascade for the same reason."""

    value_classes: dict[int, str] | None = None
    """Categorical mapping from raw raster value to class name."""

    bins: list[float] | None = None
    """Ascending breakpoints for a continuous product. A value `v` falls in bin `i` where
    `bins[i-1] <= v < bins[i]`, giving `len(bins) + 1` bins."""

    bin_classes: list[str] | None = None
    """Class name per bin, lowest first. Must be `len(bins) + 1` long."""

    nodata: float | None = None
    """Override the raster's own declared nodata value. `None` uses whatever the file declares."""

    nodata_policy: NodataPolicy = "exclude"
    """See `NodataPolicy`."""

    nodata_class: str | None = None
    """Class nodata cells count towards. Required when `nodata_policy` is `"assign"`, and
    forbidden otherwise."""

    unmapped_policy: UnmappedPolicy = "raise"
    """See `UnmappedPolicy`."""

    unmapped_class: str | None = None
    """Class unmapped values count towards. Required when `unmapped_policy` is `"assign"`, and
    forbidden otherwise."""

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


#: ESA WorldCover v200 raw value to class, from the transcribed class table
#: (`docs/references/tables/esa_worldcover_classes.md`, Zanaga et al.).
#:
#: Vegetation-led: only class 50 (Built up) is impervious. Stewart & Oke (2012) put LCZ F, "bare
#: soil or sand", at 90%+ *pervious*, so bare and sparsely vegetated ground reads as pervious
#: here. Class 60 is the one genuine ambiguity — it conflates bare rock (LCZ E, 90%+ impervious)
#: with bare soil, and the product user manual is not available on this system to resolve which
#: dominates. It contributes 107 of 171,720 cells over the Berlin fixture; in an arid city it
#: would matter a great deal, and is the first value to revisit there.
#:
#: Tree cover is carved *out* of pervious so that the classes stay disjoint and the fractions sum
#: to 1.0. Stewart & Oke count trees within pervious (LCZ A, dense trees, is 90%+ pervious), so a
#: consumer wanting their pervious surface fraction must add `frac_tree` back in.
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

#: Canopy height at or above which a cell counts as tree, in metres.
#:
#: Read from `docs/references/tables/stewart_oke_2012_properties.md`: LCZ C (bush, scrub) tops out
#: at 2 m height of roughness elements, and LCZ A and B (dense and scattered trees) both start at
#: 3 m. The LCZ scheme's own tree/scrub boundary therefore sits at 3 m, so this threshold is
#: derived from the classification this package targets rather than chosen for convenience.
#:
#: It also sits in the product's worst-calibrated band. Lang et al. (2023),
#: `10.1038/s41559-023-02206-6`, report that their map overestimates vegetation below 5 m and
#: carries roughly a 2 m positive bias between 5 and 20 m, traded deliberately for better accuracy
#: on tall canopies. A 3 m cut therefore over-calls tree, and `canopy_frac_tree` should be read as
#: an upper bound. This is one reason the WorldCover class-10 route is the default tree source.
_CANOPY_TREE_THRESHOLD_M = 3.0


def _default_land_cover_datasets() -> list[LandCoverDatasetConfig]:
    """The two default land-cover products, both inert until a COG is placed.

    `filename` is `None` for both, so `LocalRasterSource.from_settings` says the product is
    missing rather than failing obscurely.
    """
    return [
        LandCoverDatasetConfig(
            name="worldcover",
            source_dir_name="ESA_WorldCover",
            classes=["tree", "pervious", "impervious", "water"],
            value_classes=_WORLDCOVER_CLASSES,
            # 0 is WorldCover's declared nodata and genuinely means "unobserved". Stated here
            # rather than left to the file header so the local and Earth Engine paths agree: a
            # GeoTIFF declares its nodata, an Earth Engine asset does not.
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
            # Distinct prefix: this dataset's `tree` is a second, competing estimate of the same
            # quantity WorldCover's class 10 supplies, and both must be able to sit on one units
            # table for the parameter stage to choose between them.
            column_prefix="canopy_frac_",
            bins=[_CANOPY_TREE_THRESHOLD_M],
            bin_classes=["non_tree", "tree"],
            # 255 is the product's declared nodata, but Lang et al. (2023) use it to mask out
            # built-up areas, snow, ice and permanent water — surfaces removed on purpose, not
            # unobserved. All four are non-tree, so they are counted as such. See `NodataPolicy`.
            #
            # Note that Lang et al. define that mask *from ESA WorldCover*, so this dataset's tree
            # fraction is not independent of the `worldcover` dataset above: the cells this one
            # declines to measure are exactly the ones WorldCover calls built up, snow/ice or
            # water. Treating the two as corroborating estimates would be double-counting one
            # source of evidence.
            nodata=255.0,
            nodata_policy="assign",
            nodata_class="non_tree",
            # A canopy-height raster is continuous; every value falls in a bin by construction.
            unmapped_policy="raise",
            gee=GeeAssetConfig(
                # A user asset rather than a catalogued dataset, so it is absent from the public
                # STAC catalogue and was confirmed by loading it: a single `Image` with one band,
                # `b1`, not an `ImageCollection`.
                collection_id="users/nlang/ETH_GlobalCanopyHeight_2020_10m_v1",
                asset_type="image",
                band="b1",
                # Recorded for the manifest; a single image has no collection to filter by date.
                start_date="2020-01-01",
                end_date="2021-01-01",
                scale_m=10.0,
            ),
        ),
    ]


LandCoverBackend = Literal["local", "gee"]
"""Which `RasterSource` reduces the land cover for a run.

`"local"` mosaics the ESA WorldCover tiles the extent spans into the run directory and reduces
them with `exactextract`. `"gee"` reduces the configured Earth Engine asset server-side with
`reduceRegions` and brings back a table.

The two return schema-identical tables by design — that is the acceptance criterion the land-cover
phase was built against, and `tests/test_landcover_earthengine_live.py` measures it — so this
chooses where the arithmetic happens and not what is computed. They are not bit-identical:
`exactextract` weights each cell by the exact fraction of it a unit covers, while `reduceRegions`
counts whole pixels by centre, which is a single-percent disagreement on a 100 m unit against a
10 m product. A run records which one it used, so the two are never mistaken for each other.
"""


class LandCoverConfig(BaseModel):
    """Configuration for the land-cover fraction sources.

    Datasets are an ordered list so adding a third product is a config entry, not a code change —
    the same shape as `HeightConfig.areal_tiers`.
    """

    source: LandCoverBackend = "local"
    """Which backend supplies the fractions. See `LandCoverBackend`.

    Defaults to `"local"` because it is the path that needs nothing but HTTP: Earth Engine wants
    credentials, a billable project and a quota, and a default that silently required all three
    would make a first run fail on setup rather than on data. It is also the path continuous
    integration exercises, so it is the one known to be right on every checkout.

    Reasons to choose `"gee"`, and **wall time is not among them, because the two have never been
    benchmarked against each other**: a dataset with an Earth Engine asset and no local product,
    or a units layer whose covering window would exceed `max_raster_cells`, which is a ceiling the
    local read has and the server-side reduction does not. Every dataset needs `gee.collection_id`,
    `gee.band` and `gee.scale_m` set; `EarthEngineSource` refuses rather than guessing at an asset
    ID. `gee_max_units` is the corresponding ceiling on this side.
    """

    datasets: list[LandCoverDatasetConfig] = Field(default_factory=_default_land_cover_datasets)
    """The configured products, by `name`."""

    gee_project: str | None = None
    """Google Cloud project Earth Engine bills against. Read from `GEE_PROJECT_NAME` by
    `Settings.load()`."""

    gee_batch_size: int = 2000
    """Units per `reduceRegions` call. A few thousand keeps a request under Earth Engine's
    element-count and payload limits."""

    gee_max_units: int | None = None
    """Refuse an Earth Engine run covering more than this many units. `None` means no ceiling.

    `gee_batch_size` bounds each request; this bounds the whole run, and it is the one that
    matters once `source="gee"` puts a whole city through the backend — a GUPPD region's median
    80 km² is ~8 000 cells on a 100 m grid, and Berlin's 891 km² is ~89 000.
    """

    max_raster_cells: int = 200_000_000
    """Refuse a local read whose covering window exceeds this many cells, rather than exhausting
    memory. 200M cells is ~200 MB for a uint8 product, or a ~450 x 450 km extent at 10 m."""

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
    """One functional group of Overture attribute values, and which LCZ class it is evidence for.

    Transcribed from `docs/references/tables/overture_lcz_semantic_mapping.md`, which
    `tests/test_ucp_semantics.py` parses and asserts against cell for cell, in the same way the
    Stewart & Oke property table and the Bechtel similarity matrix are. Every value in it was taken
    from what is present in the pinned release rather than from the schema documentation.

    A group matches a building on `subtype` **or** `class` — the two are independently nullable and
    a feature carrying only one is still classifiable. Groups are not a partition and their
    fractions do not sum to one: `retail` is genuinely evidence for both large-low-rise form and
    commercial function, and appears in both.
    """

    name: str
    lcz_hint: str = ""
    """Which LCZ class this group is evidence for, for the manifest and the docs. Documentation
    only — nothing keys behaviour off it, because a group is evidence and not a label."""

    building_subtypes: list[str] = Field(default_factory=list)
    building_classes: list[str] = Field(default_factory=list)
    land_use_subtypes: list[str] = Field(default_factory=list)
    land_use_classes: list[str] = Field(default_factory=list)


def _default_semantic_groups() -> list[SemanticGroupConfig]:
    """The committed crosswalk. See that table for why each value is where it is."""
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
    """Configuration for the urban canopy parameters.

    Two kinds of value live here. The `*_classes` lists are vocabulary — which land-cover class
    feeds which Stewart & Oke surface fraction, and which Overture attribute values count as
    industrial — and they belong in config rather than in code. The two `street_profile_*` values
    are momepy's own defaults, restated so they reach the run manifest instead of staying implicit
    in a library signature.
    """

    street_profile_distance_m: float = 10.0
    """Spacing between the perpendicular ticks `momepy.street_profile()` measures along. momepy's
    own default."""

    street_profile_tick_length_m: float = 50.0
    """Length of each tick. A tick reaching no building reports this as the street width, so it is
    also the assumed width of an open street. momepy's own default."""

    min_building_height_m: float = 0.1
    """Lower bound applied to building height before taking logs for the geometric mean.

    A numerical guard, not a scientific threshold: `log(0)` is negative infinity and would take a
    whole unit's height of roughness elements to zero on the strength of one bad row. Overture
    heights are not validated upstream and a zero or negative value does occur. 0.1 m sits below
    any plausible building, so the floor changes nothing except in the case it exists to catch —
    but it *is* the value such a building is then counted as, which is why it is configurable
    rather than buried in the code.
    """

    measure_on: Literal["units", "enclosures"] = "units"
    """Which units the parameters are *measured* on, as distinct from classified on.

    `"units"` measures on whatever `UnitsConfig.strategy` produced, and is what every published
    figure was computed with. `"enclosures"` measures on street-bounded enclosures and moves the
    result onto the target units, area-weighted.

    **The reason is `aspect_ratio`.** A street canyon has to be measured against streets, and a
    100 m grid cell is not bounded by any — so H/W, which is 3 of the 17 applied weight units and
    the only dimension separating LCZ 8 from LCZ 3 and 6, is null on 10.8% of one Istanbul extent's
    built grid cells against 0.9% of its enclosures. On the densest decile the enclosures also put
    82.2% of cells inside LCZ 2's published H/W band against the grid's 70.2%.

    Defaults to `"units"` because **no accuracy claim is attached**: this has not been calibrated
    against a reference, so turning it on makes a run incomparable with one at the defaults.
    """

    land_cover_dataset: str = "worldcover"
    """Which `LandCoverConfig.datasets` entry supplies the surface fractions. The ETH canopy
    dataset is a second, competing tree estimate rather than a full land-cover product and reads
    high, so WorldCover is the default."""

    tree_classes: list[str] = Field(default_factory=lambda: ["tree"])
    """Land-cover classes counting as tree cover."""

    pervious_classes: list[str] = Field(default_factory=lambda: ["pervious"])
    """Land-cover classes counting as pervious *before* tree and water are folded in — see
    `lczkit.ucp.surface`."""

    impervious_classes: list[str] = Field(default_factory=lambda: ["impervious"])
    """Land-cover classes counting as impervious, buildings included. The building share is
    subtracted in `lczkit.ucp.surface`, since a raster's built-up class contains the roofs."""

    water_classes: list[str] = Field(default_factory=lambda: ["water"])
    """Land-cover classes counting as water."""

    industrial_building_subtypes: list[str] = Field(default_factory=lambda: ["industrial"])
    """Overture building `subtype` values counting as industrial."""

    industrial_building_classes: list[str] = Field(default_factory=lambda: ["industrial"])
    """Overture building `class` values counting as industrial.

    `warehouse` is deliberately absent. The problem this parameter exists to solve is that a
    distribution warehouse and a refinery are geometrically identical — the warehouse being the
    LCZ 8 case and the refinery the LCZ 10 one. Counting warehouses as industrial would push
    exactly the units the rule is meant to keep apart towards LCZ 10.
    """

    industrial_land_use_subtypes: list[str] = Field(default_factory=list)
    """Overture land-use `subtype` values counting as industrial. Empty by default: Overture files
    industrial parcels under `subtype='developed'`, which also covers commercial and retail, so the
    subtype alone carries no industrial signal."""

    industrial_land_use_classes: list[str] = Field(default_factory=lambda: ["industrial"])
    """Overture land-use `class` values counting as industrial.

    `brownfield` — disused industrial land — is the obvious candidate to add and is deliberately
    left out: it describes what a parcel *was*, and a brownfield site has no heat output, no
    industrial buildings and often no buildings at all. Add it only for a city where derelict
    industry is still the dominant surface.
    """

    semantic_groups: list[SemanticGroupConfig] = Field(default_factory=_default_semantic_groups)
    """Functional groups read out of Overture's `subtype` and `class`.

    The four `industrial_*` vocabularies above are **not** replaced by this and are not derived from
    it. They feed `industrial_fraction_of_building_area`, which is the column the calibrated LCZ 10
    threshold of 0.45 was swept against, and repointing that at a differently-scoped group would
    silently invalidate the calibration. `heavy_industry` here is the same idea with a slightly
    wider vocabulary (`storage_tank`, `silo`, land-use `works`) and it is reported beside the
    original rather than in place of it.

    Set to `[]` to skip the semantic layer entirely, which costs one overlay per group.
    """


class SemanticRuleConfig(BaseModel):
    """One functional assignment rule keyed on a semantic evidence column.

    The same mechanism as the LCZ 10 rule, generalised: a unit over `min_fraction` takes `lcz`
    whatever the distance metric said, and the displaced answer is kept as `lcz_secondary`.

    **A rule ships enabled only once its threshold has been calibrated**, and disabled otherwise.
    A threshold here is swept against a reference and chosen at an operating point, never picked
    because it looks reasonable, so an uncalibrated rule would put an invented number into a
    published label. Each rule's `reason` states which of the two it is and on what measurement.
    """

    name: str
    lcz: int
    column: str
    """The parameter column to threshold, e.g. `sem_lightweight_buildings_of_building_area`."""

    min_fraction: float = 0.5
    enabled: bool = False

    min_mean_building_area_m2: float | None = None
    max_mean_building_area_m2: float | None = None
    """Optional gates on `mean_building_area_m2`.

    Available to a *rule* although it is not a metric dimension: `mean_building_area_m2` carries
    zero weight in every preset, so the distance metric cannot act on it. A rule is not the metric,
    and "large low-rise" is a claim about building size that the semantic evidence alone cannot
    make.
    """

    reason: str = ""
    """Why this rule exists, for the manifest. A rule with no recorded reason is one nobody can
    audit later."""


def _default_semantic_rules() -> list[SemanticRuleConfig]:
    """The two functional rules, both swept against eight cities: LCZ 8 enabled, LCZ 7 refused.

    Order is most-general to most-specific, since a later rule overrides an earlier one on a unit
    both would fire on.
    """
    return [
        SemanticRuleConfig(
            name="large_lowrise",
            lcz=8,
            column="sem_large_lowrise_buildings_of_building_area",
            min_fraction=0.70,
            min_mean_building_area_m2=None,
            enabled=True,
            reason=(
                "LCZ 8 fails by construction in the distance metric, not by tuning: its "
                "building-surface band overlaps LCZ 3 and 6, its Hr band is identical to LCZ 3, 6 "
                "and 9, so aspect ratio is its only separator — and aspect ratio is null exactly "
                "where large setbacks stop streets reaching buildings, which is most of an LCZ 8 "
                "unit. Measured 0.0% agreement over 224 Rotterdam cells. A functional route is the "
                "only evidence available that does not depend on a parameter the class nullifies. "
                "Threshold calibrated over 19 settings x 6 size gates against So2Sat hand labels "
                "in eight cities: at 0.70 the rule relabels 662 labelled cells, 72.2% of which the "
                "reference calls LCZ 8 against 14.8% for the morphological label it displaced, and "
                "LCZ 8's precision, recall, F1 and built-class agreement all rise in all eight. "
                "Six of 114 settings clear the acceptance criteria, all of them here in 0.70-0.95. "
                "The mean-footprint gate this rule shipped with was measured harmful and is off: "
                "the denominator is already the unit's whole building area, so untagged area "
                "counts against the fraction and the gate charges for size a second time. It cut "
                "reach at all 95 gated settings, and at the operating point a 1000 m gate takes "
                "662 relabelled cells to 237 while raising the displaced label's accuracy from "
                "14.8% to 24.5%; no gated setting passes at any threshold. Against WUDAPT, the "
                "secondary reference, LCZ 8's "
                "F1 still rises in all eight cities but no setting clears the criteria — precision "
                "falls in Berlin and Milan while recall roughly doubles."
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
                "Disabled on measurement, not pending one. LCZ 7 is the informal-settlement class "
                "and a tag-based rule cannot detect it: Overture has no slum/shanty/ger/tent "
                "value, so `lightweight` maps to an outbuilding vocabulary — hut, shed, cabin, "
                "roof, kiosk, carport, guardhouse. Swept over 19 thresholds x 5 size gates against "
                "both reference sets in eight cities, and refused at all 95 settings under both. "
                "What refuses every one of them is the second criterion: the rule is wrong more "
                "often than the label it overwrote at 95 of 95 settings under both references. "
                "The tagged evidence sits in Berlin, Milan and Vancouver, "
                "which carry no reference LCZ 7 cells at all, and is near-absent in the five "
                "cities that do: the best any setting reached was 2 correct LCZ 7 labels against "
                "So2Sat and 7 against WUDAPT, while displacing 93 and 160 labels the metric had "
                "right. The binding limit is tag coverage rather than the threshold — tagged "
                "building area runs 48.6% across Europe and North America against 13.6% "
                "elsewhere, Rio at 3.1%, because Google Open Buildings and Microsoft ML supply "
                "footprint geometry with no attributes and Overture's conflation is "
                "winner-takes-all per building. So even a calibrated tag rule would fire where "
                "Overture is well described and not where informal settlement is, and "
                "`building_tag_coverage` is what makes that shortfall legible rather than "
                "invisible."
            ),
        ),
    ]


class ClassificationConfig(BaseModel):
    """Configuration for the prototype-distance classifier.

    Every threshold the classifier applies lives here and is serialised into the run manifest.
    Two of them - `natural_dominant_fraction` and `natural_negligible_fraction` - move the
    prototype table itself, because the tree and water ranges they generate are lczkit's own
    rather than Stewart & Oke's and there is no published value to defer to.
    """

    weight_preset: str = "bernard2024_partial"
    """Named entry in `lczkit.classify.weights.PRESETS`. `"bernard2024_partial"` is Bernard et al.
    (2024)'s published built-type default with the dimensions this package cannot compute left
    out; `"equal"` is the uniform comparison.

    The `_partial` is load-bearing rather than decorative: SVF (weight 4) and z0 (weight 0.5) are
    deferred and FI/FP are zero-weighted, so 17 of the published 21.5 weight units are applied and
    the effective metric has three non-zero dimensions, of which FB is roughly 47%. Calling it
    `bernard2024` would claim a metric this package does not implement. The unapplied dimensions
    are recorded in the run manifest."""

    built_min_building_fraction: float = 0.10
    """Building surface fraction at or above which a unit is classified against the built
    prototypes rather than the natural ones.

    Not an invented number. Every built class in Stewart & Oke's table has a building surface
    fraction of at least 10%, and every natural class at most 10%, so 10% is the boundary the
    published table draws itself. It is configurable because a city's footprint completeness can
    shift the measured fraction even where the real one is unchanged.
    """

    reachable_natural_classes: list[str] = Field(default_factory=lambda: ["A", "B", "D", "E", "G"])
    """Which natural classes the gate may assign, by Stewart & Oke label.

    C (bush, scrub), D (low plants) and F (bare soil or sand) are mutually indistinguishable in
    open ground with the parameters this package computes: the published table separates them only
    by sky view factor, aspect ratio and height of roughness elements, all building-derived and all
    null where nothing is built, and the default WorldCover mapping folds shrubland, grassland and
    bare ground into a single `pervious` class. Rather than let tied prototypes be resolved by index
    order, C and F are excluded and the exclusion is recorded in the manifest. Distances to the
    excluded classes are still computed and reported.

    **The two exclusions are not the same kind of thing, and only one of them is a policy choice.**

    C is genuinely excluded by this setting: its box differs from D's on aspect ratio (0.25-1.0
    against at most 0.1) and on Hr (at most 2 m against at most 1 m), both of which carry weight 1.0
    in the natural vector. Where those two are non-null C wins outright, so adding it back here
    changes labels. The tie is real only where both are null, which for a buildingless unit is the
    common case - hence the exclusion.

    F is excluded by **arithmetic, not by this list**. D's box contains F's in every dimension -
    identical on aspect ratio, building, impervious, pervious, tree and water, and wider on Hr (at
    most 1 m against at most 0.25 m) - so d(F) >= d(D) for every possible unit, and ties break to
    the lower code. **Adding "F" here cannot make F reachable.** Reaching it needs a land-cover
    mapping that emits bare ground separately and a surface fraction carrying it, not a config
    change. The manifest records F as dominated rather than excluded, so the distinction survives
    into the run record.
    """

    natural_dominant_fraction: float = 0.50
    """Tree or water cover at which a unit reads as LCZ A or LCZ G. See
    `docs/references/tables/lczkit_natural_class_ranges.md` - lczkit's own, not Tier 1."""

    semantic_rules: list[SemanticRuleConfig] = Field(default_factory=_default_semantic_rules)
    """Functional rules read off Overture's semantic attributes, each enabled only if its threshold
    has been swept against a reference and cleared the acceptance criteria there. LCZ 8 is enabled
    at 0.70; LCZ 7 is disabled because the same sweep refused it. See `SemanticRuleConfig`, and
    `lczkit.classify.rules.apply_semantic_rules`."""

    natural_negligible_fraction: float = 0.10
    """Tree or water cover a natural class treats as absent. Reuses the 10% boundary Stewart &
    Oke apply to building and impervious cover throughout their natural rows."""

    lcz10_industrial_column: str = "industrial_fraction_of_building_area"
    """Which industrial share the LCZ 10 rule reads.

    Named explicitly because the two are not interchangeable and the threshold below is calibrated
    against one of them.

    `industrial_fraction_of_building_area` is Bernard et al. (2024)'s `FIND/B`, so their published
    0.33 transfers to it directly. It is the default on both theory and measurement: on the
    Rotterdam fixture it selects 95 cells against a reference of 88, where the unit-area share
    selects 196 at its own best operating point. Getting the *rate* right matters when precision
    cannot be improved (see the threshold below), because the remaining choice is how much of the
    map to label.

    The unit-area share is the alternative, and is the more saturated of the two at a 100 m cell —
    42.6% of cells holding any industrial ground read exactly 1.0, against 12.6% for `FIND/B`.
    """

    lcz10_min_industrial_fraction: float = 0.45
    """`lcz10_industrial_column` above which a unit is assigned LCZ 10.

    Deliberately set to under-trigger: Overture cannot distinguish heavy from light industry, so a
    missing LCZ 10 is a visible gap while a light-industrial estate mislabelled as heavy industry
    is an invisible error that propagates into any model consuming the map.

    **Calibrated, not picked.** It was swept over nineteen settings against the Rotterdam
    reference, and the precision/recall curve is written into the run record. 0.45 is that sweep's
    operating point, the precision maximum over `FIND/B`. Bernard's published 0.33 sits just below
    it and performs comparably (22.4% precision, 27.3% recall against 23.2% and 25.0%), so this is
    not a number in tension with the paper it comes from.

    **Read the curve before trusting it.** Precision is roughly flat — 16.7% to 23.2% across the
    whole range — so this threshold governs how much of the map carries LCZ 10 and not how often
    that label is right. The rule fires plausibly, not accurately, and it is scored against
    `lcz_v3`, a comparator carrying its own error and coarser than the ground in this very city.
    """

    lcz1_min_height_m: float | None = None
    """Optional floor on `Hr` below which the LCZ 1 (compact high-rise) distance is discarded.

    Bernard et al. (2024) Sect. 2.3 apply the equivalent constraint on mean building levels,
    reporting that without it GeoClimate produced LCZ 1 across European cities where no urban
    researcher would place any. lczkit has no reliable per-unit storey count, so the hook is
    exposed against `Hr` instead and defaults to off - an untested constraint applied by default
    would be a worse failure than the over-prediction it guards against.
    """

    modal_filter: bool = False
    """Whether to replace an isolated unit's label with the modal label of its neighbours.

    **Off, and that is deliberate rather than cautious.** Every unit is classified independently of
    its neighbours, so a cell whose parameters wobble across a prototype boundary takes a different
    label from the fabric it sits in — salt-and-pepper at a grain Stewart & Oke never intended a
    class to be read at, given an LCZ patch is a neighbourhood and a So2Sat patch is 320 m across.
    A spatial filter is the standard answer in this literature.

    It stays off because `modal_filter_min_like_neighbours` has not been calibrated against a
    reference, and because **every published figure was measured without one**. A run with it on
    is not comparable with a run at the defaults.

    See `lczkit.classify.smoothing`.
    """

    modal_filter_min_like_neighbours: int = 2
    """A unit with fewer than this many contiguous neighbours sharing its label is isolated.

    A placeholder marking where a swept number goes, not a calibrated value. Two is the weakest
    setting that does anything at all on a Queen-contiguous grid, chosen so a caller who enables
    the filter without sweeping it does the smallest thing rather than the boldest.
    """

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
    """Configuration for what a run writes into `output/lczkit/<run_id>/`."""

    break_count: int = 7
    """Number of classification breaks precomputed per continuous variable. The map site renders
    choropleths from these and never recomputes a quantile at site-build time."""

    break_method: Literal["quantile"] = "quantile"
    """How the breaks are derived. Only quantiles are implemented; the field exists so the
    manifest states the method rather than leaving a consumer to assume one."""

    viz_significant_figures: int = 3
    """Significant figures floats are rounded to in `units_viz.parquet`."""

    viz_distance_scale: int = 1000
    """Multiplier applied to the 17-way distance vector before it is stored as `int16` in
    `units_viz.parquet`. Distances are small positive reals, so 1000 keeps three decimal places
    inside the int16 range."""

    gis_format: Literal["none", "gpkg"] = "gpkg"
    """A second copy of the unit table in a format every GDAL build reads, written beside the
    GeoParquet rather than instead of it.

    **`units.parquet` is not the problem this solves.** It is valid GeoParquet 1.0.0 and carries
    the run's CRS as PROJJSON with an EPSG authority code — verified on the published Bogota and
    Nairobi runs, both `EPSG:32618`/`EPSG:32737`. What varies is the *reader*: GDAL's Parquet
    driver is an optional build component, so a QGIS built without it opens the file as a
    non-spatial table or not at all, and the failure looks like a missing CRS rather than a
    missing driver. GeoPackage has no such conditional — it is SQLite, in GDAL's core, and its
    CRS lives in a table rather than in file metadata a driver has to know how to parse.

    Cost, measured on the 116 491-unit Bogota run at four extents before this was made the
    default: 0.22 s / 5.6 MB at 10 000 units to **1.83 s / 67.3 MB at 116 491**, exponent 0.86 —
    sublinear, and 0.3% of a run that takes ten minutes. Set `"none"` to skip it.

    Only the unit table. The context layers under `layers/` stay GeoParquet-only: they are the
    site's basemap material, they carry the same CRS, and `buildings.parquet` alone is 477 MB on
    that run."""

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
    """Configuration for the static map site `lczkit.viz.build_site` writes into a run.

    Zoom ranges are here rather than derived because they have to be *chosen
    deliberately* and recorded — a tileset is only reproducible if the zooms that made it are
    written down, and tippecanoe's cost and the site's size both scale with the range.
    """

    unit_min_zoom: int = 10
    unit_max_zoom: int = 14
    """Zooms for the unit tileset. A 100 m cell is about 21 px at z14 and 1 px at z10, so z14 is
    where the grid stops gaining detail and z10 is where a whole metropolitan extent fits on a
    screen. MapLibre overzooms past the maximum for free, so z14 is not a limit on how far in a
    reader can go."""

    basemap_min_zoom: int = 9
    basemap_max_zoom: int = 13
    """The basemap stops one zoom short of the units. It is a flat wash drawn *under* a translucent
    unit fill, so its detail at z14 is invisible and expensive — dropping the top level halved a
    measured land-use tileset, 2.66 MB to 1.45 MB, because the maximum-zoom level is the one
    tippecanoe keeps at full precision. MapLibre overzooms it for free past the maximum."""

    basemap_simplification: int = 10
    """tippecanoe's `--simplification` for the basemap only. Context geometry is the one thing in
    the site that carries no measurement, so it is the only thing that may be simplified for
    display; the unit and building tilesets are left at tippecanoe's faithful default."""

    basemap_layers: list[str] = Field(default_factory=lambda: ["water", "streets"])
    """Which persisted context layers to draw, in draw order.

    **Land use is available and off by default, on a measurement.** At 9 km² it was 1 864 polygons
    carrying 401 162 vertices — 94% of the basemap's bytes and most of its build time — for a dark
    wash underneath an 82%-opacity unit fill. Water and streets are what actually orient a reader
    on a city map: rivers and arterials. Add `"land_use"` back if a run wants it."""

    building_min_zoom: int = 14
    building_max_zoom: int = 16
    """Buildings are only ever seen extruded, which is a high-zoom view; tiling them from z10
    would triple the tileset for pixels nobody looks at."""

    include_buildings: bool = False
    """Whether to tile the building footprints. **Off by default, and the default is measured:**
    891 994 Berlin footprints tile to tens of megabytes, two to three times the rest of the site
    combined. A reader who wants extrusions can turn it on and pay for it knowingly."""

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
            # The column the LCZ 10 rule actually thresholds, so the map shows the evidence behind
            # the label rather than a second industrial share that does not decide anything.
            "industrial_fraction_of_building_area",
        ]
    )
    """Attributes carried at *every* zoom, because a choropleth needs them while the map is zoomed
    out. Everything else in the viz table rides in a second tileset built at the maximum zoom only.

    The split exists because MVT repeats the whole attribute table in every tile at every zoom: at
    metropolitan scale a 38-column unit table costs more tiled than 892 000 building footprints do.
    Columns named here that a run did not produce are skipped rather than raising — a run over a
    small extent can legitimately lack a parameter."""

    render_column_prefixes: list[str] = Field(default_factory=lambda: ["height_frac_"])
    """Column *families* carried at every zoom, named by prefix because their members are not known
    until a run has chosen a cascade.

    The height tier fractions are `height_frac_<source>` for whichever sources fired — `wsf3d`,
    `ghsl`, `unresolved`, and the two Overture tiers — so `render_columns` cannot name them without
    naming a cascade. They belong at every zoom rather than in the click-detail tileset because
    they are first-class *layers* and not diagnostics: a selectable layer must paint while the map
    is zoomed out, and it must paint from tiles already in memory, since a view change that
    refetched would make the site slow."""

    detail_max_features: int = 200_000
    """Above this many units the click-detail tileset is skipped and the sidebar falls back to the
    render attributes. A guard on the one part of the site whose size is unbounded in extent."""

    online_basemaps: list[str] = Field(default_factory=list)
    """Remote raster grounds the site offers, by key from `lczkit.viz.basemaps.PROVIDERS`.

    **Empty by default, and that default is load-bearing rather than cautious.** A built site opens
    with no network and stays valid years from now, which is what makes one archivable beside a
    paper; a remote tile source breaks both of those, and outlives the run only as long as the
    provider chooses to serve it. With this empty the emitted site contains no external reference
    at all, and a test asserts it.

    Name one or several and the site gains a base-map picker: each is a selectable ground under the
    units, drawn beneath everything else, hidden until chosen, with the provider's attribution shown
    and its tiles treated as fallible — a failure leaves every other layer working and says so. The
    run's own Overture water and streets stay in the site and stay switched on, so an archived copy
    opened offline still shows the linework the classification was computed from.

    Order is the order they appear in the picker. Selecting a provider takes on its tile usage
    policy, and two of them need an API key — see each one's `terms`.
    """

    online_basemap: str | None = None
    """Deprecated single-value spelling of `online_basemaps`, folded into the front of it.

    Kept because it is what runs before this field existed recorded in their manifests, and
    `build_site` re-validates an archived manifest to rebuild a site. Pydantic ignores unknown
    fields by default, so dropping this would make an archived run's configured ground disappear on
    rebuild with nothing raised — a silent change to an artefact, which is worse than a stale name.
    Read `basemap_keys`, never this field.
    """

    maptiler_key: str | None = Field(default=None, exclude=True)
    """The MapTiler API key, resolved from `MAPTILER_API_KEY` by `Settings.load()`.

    **`exclude=True` is the whole point of the field's shape.** The manifest is
    `settings.model_dump()` verbatim, and `lczkit.viz.build_site` copies the manifest into the
    published site, so an ordinary field would put the key in two shipped files rather than the one
    that needs it. Excluded, it reaches `style.json`'s tile URLs and nothing else, and a test
    asserts the manifest never carries it.

    That bounds the exposure; it does not remove it. MapLibre fetches tiles from the browser, so the
    key is in plain text in any site built with a MapTiler ground, and anyone holding the directory
    holds the key. Restrict it by origin at the provider, or hand out a site built without one.
    """

    @property
    def basemap_keys(self) -> list[str]:
        """The configured provider keys in picker order, with the deprecated singular folded in.

        The single place the two spellings are reconciled, so nothing downstream has to know that
        `online_basemap` exists.
        """
        keys = [self.online_basemap] if self.online_basemap else []
        keys.extend(self.online_basemaps)
        return list(dict.fromkeys(key for key in keys if key))

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
            # An empty prefix matches every column, which would put the whole attribute table at
            # every zoom — the exact cost the render/detail split was measured to avoid.
            raise ValueError("render_column_prefixes must not contain an empty string")
        allowed = {"land_use", "water", "streets"}
        unknown = sorted(set(self.basemap_layers) - allowed)
        if unknown:
            raise ValueError(
                f"unknown basemap layers {', '.join(unknown)}; "
                f"choose from {', '.join(sorted(allowed))}"
            )
        if self.basemap_keys:
            # Imported here rather than at module scope: `lczkit.viz` pulls in the tile builder and
            # the style module, and the config layer is imported by everything.
            from lczkit.viz.basemaps import PROVIDERS

            for key in self.basemap_keys:
                if key not in PROVIDERS:
                    raise ValueError(
                        f"unknown basemap {key!r}; choose from {', '.join(sorted(PROVIDERS))}"
                    )
        return self


def _default_reference_dataset() -> LandCoverDatasetConfig:
    """The Demuzere global LCZ map, described as a categorical raster product.

    Deliberately a `LandCoverDatasetConfig`: the reduction the validation module needs - areal
    class fractions per unit, then the majority - is exactly what `LocalRasterSource` already
    does, including the CRS handling, the covering window and the nodata policy. Describing the
    reference map this way reuses all of it instead of growing a second `exactextract` path that
    could drift.

    `filename` is unset because the product is not part of the repo; place it under
    `input/<source_dir_name>/` and set the name. `nodata=0` is the product's own convention.

    Nodata is *assigned* to its own class rather than excluded, which is the only difference from
    how a land-cover product would be described. Excluding it would renormalise the fractions over
    the covered cells and lose the one number the validation module cannot do without: how much of
    each unit the reference map actually reaches. A unit half outside the map would otherwise
    report a confident majority computed from a corner of itself.
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


class UnitsConfig(BaseModel):
    """Which spatial units the pipeline computes on.

    **There is no auto-selection, and in particular none by region.** Enclosures lead the grid on
    both criteria outside Europe and North America and lose inside it, but region is not the
    mechanism — natural-class share and patch heterogeneity are — so a rule keyed on continent
    would be wrong at every boundary. The trade-off is documented, the choice is the caller's, and
    which strategy ran is recorded in the manifest.
    """

    strategy: UnitStrategy = "grid"
    """`grid` (default), `enclosure`, or `patch`.

    - **`grid`** — 100 m cells. What every published LCZ map, validation dataset and WRF workflow
      uses, and what every published figure here is measured on.
    - **`enclosure`** — street-, rail- and water-bounded blocks. Measured against the grid over
      fifteen cities and not adopted: built-class agreement +3.8 (12/15) but overall −0.2 (8/15),
      and adoption required a lead on both.
    - **`patch`** — enclosure seeds merged to LCZ-patch scale. See `lczkit.units.patches`; the
      block is a much smaller object than a patch (median 0.04 ha against WUDAPT's 2.2–52 ha), and
      this is the strategy that addresses that rather than assuming a thinner barrier set will.
    """

    cell_size_m: float = 100.0
    """Grid cell side. 100 m is not arbitrary — it is what the validation references and the
    downstream WRF tooling assume — so moving it makes a run incomparable with a published
    figure."""

    patch_min_area_m2: float = 50_000.0
    """`strategy="patch"` only. A floor, not a centre: the median lands near twice it."""

    patch_max_area_m2: float | None = 500_000.0
    """`strategy="patch"` only. `None` removes the ceiling, which lets a merge chain swallow a whole
    estate into one unit."""

    patch_merge_on_morphology: bool = True
    """Whether the patch merge compares neighbours on building surface fraction and height, or
    merges on size alone. On costs one overlay against the building layer and is what makes a patch
    homogeneous rather than merely large; off is supported and worse, and needs no buildings."""

    drop_pedestrian_barriers: bool = True
    """Exclude footway/steps/path/cycleway/bridleway from the barrier set for `enclosure` and
    `patch`. On by default: these are 50–73% of the mapped network in Berlin, Hong Kong and Milan
    and 3.5–7.5% elsewhere, so leaving them in makes the partition largely a measure of how
    thoroughly a city's footpaths have been surveyed. Ignored by `grid`, which takes no barriers."""

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
    """The WUDAPT LCZ training areas, the third reference and the only globally available one.

    A vector product rather than a raster, so unlike `_default_reference_dataset` it is not a
    `LandCoverDatasetConfig` — there is no `exactextract` path to reuse. See
    `lczkit.validation.wudapt` for what each of these gates costs.
    """

    source_dir_name: str = "WUDAPT"
    """Subdirectory under `input/` holding the WUDAPT export."""

    filename: str | None = None
    """The LCZ Generator export, e.g. `LCZ-Generator_training_areas_2024-10-01.gpkg`.

    Unset by default and deliberately not defaulted to whatever is on disk, for the same reason
    `OvertureConfig.release` refuses to track "latest": the export is dated, contributors keep
    adding to it, and a validation figure that does not name the export it was measured against
    cannot be reproduced. A caller pins it.
    """

    layer: str | None = None
    """GeoPackage layer. `None` takes the first, which is correct for the published export — its
    only other layer is a QGIS `layer_styles` table carrying no geometry."""

    class_column: str = "class"
    """WUDAPT's own LCZ column. Integer, agreeing with Demuzere's coding over 1-17."""

    require_qc: bool = False
    """Keep only polygons passing all three LCZ Generator QC flags.

    Off by default, and **measured rather than assumed**. The gate is expensive — over 200 000
    polygons the three flags pass individually at 62.3% / 84.0% / 81.5% and jointly at 48.2%, so it
    halves the reference — and what it buys, measured against So2Sat labels on the 30 km windows,
    is Cairo 26.3% → 26.7%, Mumbai 47.4% → 50.3%, Jakarta 70.7% → **68.8%**. Inert on two
    cities and harmful on the third, for half the labelled ground.

    `WudaptSelection.qc_pass_fraction` reports the rate whether or not the gate is on, so the cost
    of changing this is visible without a second run.
    """

    min_oa: float | None = None
    """Minimum LCZ Generator overall accuracy for the polygon's *submission*. `None` disables.

    A property of the submission, not of the polygon — see `wudapt.priority_order` — and it does
    not select for what a validation reference needs. Gating at 0.7 moves agreement
    with So2Sat by Cairo 26.3% → **19.1%**, Mumbai 47.4% → 47.3%, Jakarta 70.7% → 69.6%: worse on
    all three, and much worse on the city that needed help most. The LCZ Generator's cross-validated
    accuracy scores a submission against *itself*, so a high `oa` means a self-consistent
    contributor rather than one who agrees with an independent expert.
    """

    min_area_m2: float = 0.0
    """Drop polygons below this. 4.7% of the file is under 1000 m², smaller than a 100 m cell,
    and five features have exactly zero area."""

    max_area_m2: float | None = None
    """Drop polygons above this. The largest in the file is 18 680 km² — a whole sea digitised as
    one LCZ G polygon — which is a legitimate label and a poor reference for a city window."""

    citation: str = "10.3390/ijgi4010199"
    """Bechtel et al. (2015), *IJGI* 4(1), 199-219 — the WUDAPT Level 0 protocol.

    Recorded apart from `reference_citation` and `ground_truth_citation` because which file filled
    the reference role is part of the measurement. **WUDAPT is additionally not independent of
    `lcz_v3`** — these training areas
    are the training data behind the Demuzere global map — so agreement between the two is not a
    ceiling in the sense So2Sat gives one.
    """

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
    """Configuration for agreement against a reference LCZ map.

    Agreement is reported in the style of the `lczexplore` package: per-class figures and a
    confusion matrix, never a single headline number.
    """

    reference: LandCoverDatasetConfig = Field(default_factory=_default_reference_dataset)
    """The reference map, described as a categorical raster. See `_default_reference_dataset`."""

    reference_citation: str = "10.5194/essd-14-3835-2022"
    """Demuzere et al. (2022), *ESSD* 14, 3835-3873. Recorded separately from the file actually
    read: the copy on this system is version 3 of the map and the paper describes an earlier one,
    so conflating the two in the manifest would misstate what a run was validated against."""

    ground_truth_citation: str = "10.1109/MGRS.2020.2964708"
    """Zhu et al. (2020), *IEEE GRSM* 8(3), 76-89. So2Sat LCZ42, the hand-labelled reference.

    Recorded apart from `reference_citation` because the two are not the same kind of thing:
    `lcz_v3` is a model output with its own error, these are human labels. Where both are
    available the labels are primary and `lcz_v3` is a comparator whose agreement with them is the
    ceiling on any score against it."""

    wudapt: WudaptConfig = Field(default_factory=WudaptConfig)
    """The WUDAPT training areas — hand labels too, but a different kind of object from So2Sat:
    irregular, overlapping, spanning four decades, and covering every city this package has been
    run on rather than the 51 So2Sat sampled. See `WudaptConfig` and `lczkit.validation.wudapt`."""

    min_reference_coverage: float = 0.5
    """Fraction of a unit the reference map must actually cover for that unit to enter the
    agreement statistics. A unit half outside the map's extent would otherwise contribute a
    majority computed from a corner of itself."""

    height_completeness_deciles: int = 10
    """Strata for the height-completeness breakdown. Deciles by default, configurable so a run
    with few units can widen the bins rather than report noise."""

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
    """Configuration for the 2D urban-morphometrics stage (Majer & Fleischmann 2026).

    Off by default, like `ClassificationConfig.modal_filter` and the WUDAPT QC gate: this is a
    new whole-extent operation computed on a finer unit set (enclosed tessellation cells) than
    the pipeline's classification units, and it ships opt-in until its scaling is measured on a
    real extent — not because it is expected to be wrong, but because the project's standing rule
    against shipping an unmeasured whole-extent operation as a default applies to it precisely.

    Output is a wholly separate run artefact (`morphometrics.parquet`, and `morphometrics.tif` if
    `raster_resolution_m` is set) — never joined to `units.parquet` or fed into classification.
    """

    enabled: bool = False

    tessellation_shrink: float = 0.4
    """Passed straight through to `momepy.enclosed_tessellation`; momepy's own default."""

    tessellation_segment: float = 0.5
    """Passed straight through to `momepy.enclosed_tessellation`; momepy's own default."""

    tessellation_threshold: float | None = 0.05
    """Passed straight through to `momepy.enclosed_tessellation`; momepy's own default."""

    building_neighborhood_distances_m: list[float] = Field(
        default_factory=lambda: [20.0, 100.0, 200.0]
    )
    """Distance-band neighbourhoods for building-scale metrics — the paper's own scales."""

    building_knn_values: list[int] = Field(default_factory=lambda: [10, 20, 30])
    """Nearest-neighbour counts for building-scale mean-distance metrics — the paper's own
    scales."""

    etc_topological_steps: list[int] = Field(default_factory=lambda: [1, 2, 3])
    """Fuzzy-contiguity neighbourhood depths for ETC-scale metrics — the paper's own scales."""

    street_node_radii_m: list[float] = Field(default_factory=lambda: [5.0, 400.0])
    """Network-distance radii for the node/edge connectivity metrics. See
    `lczkit.morphometrics.streets` for why these are read as network distance
    (`distance="mm_len"`) rather than as topological hops."""

    street_profile_distance_m: float = 10.0
    """Mirrors `UcpConfig.street_profile_distance_m`, kept as a separate field rather than shared:
    this stage's street profile always runs on 2D geometry alone (no `height` argument), and a
    caller tuning one should not silently retune the other."""

    street_profile_tick_length_m: float = 50.0
    """See `street_profile_distance_m`."""

    contextual: bool = False
    """The opt-in 25th/50th/75th-percentile expansion to up to 321 attributes. Off by default:
    a config flag, not a second code path chosen by extent size. Primary attributes are kept
    when this is enabled — unlike the paper, which drops them once the expansion is computed."""

    contextual_steps: int = 3
    contextual_quantiles: list[int] = Field(default_factory=lambda: [25, 50, 75])

    max_tessellation_cells: int = 50_000
    """Refuse the stage rather than let it run for hours, per `scripts/morphometrics_scaling.py`'s
    measurement on four concentric Berlin extents (1/4/9/16 km²): the primary-attribute stage
    took 51 s at 5 406 ETCs and **1 029 s at 12 322** — a ~20x time increase for 2.3x more cells,
    reproduced in an isolated re-run to rule out measurement noise from a concurrent process.
    momepy's own `weighted_character`/`percentile` warn they are markedly slower without `numba`
    (not currently an lczkit dependency), which is the most likely mechanism; a 16 km² extent also
    had ~10x more enclosures than the three smaller ones, a plausible correlate not yet isolated
    as a cause. Set well below the largest measured point rather than extrapolated from it — this
    project's own history is that power-law extrapolations from small extents run optimistic."""

    max_contextual_cells: int = 20_000
    """A second, tighter ceiling than `max_tessellation_cells`, same reasoning: the higher-order
    contiguity graph the contextual expansion runs `momepy.percentile` over is denser than the
    base tessellation graph, once per primary attribute, and the primary stage's own measured
    superlinearity has not been separately re-measured for this one."""

    raster_resolution_m: float | None = None
    """`None` disables raster generation at run time. Set via `--morphometrics-resolution`, or
    regenerate later at a different resolution with `lczkit morphometrics raster`."""

    max_raster_cells: int = 50_000_000
    """Mirrors `LandCoverConfig.max_raster_cells`: refuses a resolution whose grid would be
    unreasonably large for the extent, rather than silently taking minutes and gigabytes."""

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
        for name, values in (
            ("building_neighborhood_distances_m", self.building_neighborhood_distances_m),
            ("building_knn_values", self.building_knn_values),
            ("etc_topological_steps", self.etc_topological_steps),
            ("street_node_radii_m", self.street_node_radii_m),
            ("contextual_quantiles", self.contextual_quantiles),
        ):
            if not values:
                raise ValueError(f"{name} must not be empty")
            if any(v <= 0 for v in values):
                raise ValueError(f"{name} must be positive, got {values}")
        if self.contextual_steps < max(self.etc_topological_steps):
            raise ValueError(
                "contextual_steps must be at least the largest etc_topological_steps entry "
                f"({max(self.etc_topological_steps)}), got {self.contextual_steps} — a contextual "
                "expansion narrower than a primary attribute's own highest-order weighting would "
                "be an inconsistent configuration"
            )
        if self.raster_resolution_m is not None and self.raster_resolution_m <= 0:
            raise ValueError(
                f"raster_resolution_m must be positive, got {self.raster_resolution_m}"
            )
        if self.max_tessellation_cells <= 0 or self.max_contextual_cells <= 0:
            raise ValueError("max_tessellation_cells and max_contextual_cells must be positive")
        if self.max_raster_cells <= 0:
            raise ValueError(f"max_raster_cells must be positive, got {self.max_raster_cells}")
        return self


class Settings(BaseModel):
    """Resolved configuration for a single lczkit run.

    Construct via `Settings.load()`, not directly — that is what resolves `DATA_DIR` from
    the environment and creates the run's output directory.
    """

    data_dir: Path
    run_id: str = Field(default_factory=_default_run_id)
    overture: OvertureConfig = Field(default_factory=OvertureConfig)
    cleaning: CleaningConfig = Field(default_factory=CleaningConfig)
    morphometrics: MorphometricsConfig = Field(default_factory=MorphometricsConfig)
    heights: HeightConfig = Field(default_factory=HeightConfig)
    height_products: HeightProductsConfig = Field(default_factory=HeightProductsConfig)
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
        """Refuse a run whose enabled semantic rules read a column no configured group emits.

        `ucp.semantic_groups` may be set to `[]` to skip the semantic layer, and `large_lowrise`
        ships enabled — so the two settings can be individually reasonable and jointly impossible.
        The classifier already raises on the missing column with a message naming both halves, but
        classification is the *last* stage of a run: on a metropolitan extent that is a ten-minute
        wait for an answer this check gives at config load.
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
        """`$DATA_DIR/input/` — organised by data origin, owned by other projects too."""
        return self.data_dir / "input"

    @property
    def output_dir(self) -> Path:
        """`$DATA_DIR/output/` — organised by the tool that produced the results."""
        return self.data_dir / "output"

    @property
    def run_dir(self) -> Path:
        """`$DATA_DIR/output/lczkit/<run_id>/` — this run's own output directory."""
        return self.output_dir / "lczkit" / self.run_id

    @property
    def tile_cache_dir(self) -> Path:
        """`$DATA_DIR/output/lczkit/_cache/tiles/` — memoised per-tile street simplification.

        **Not under `input/`, deliberately.** Writes to `input/` are confined to the source
        implementation owning each subdirectory, and nothing else in the package writes there at
        all. A simplified tile is derived by lczkit's own cleaning from data a source already
        fetched — it is not source data, and `input/` may be shared with other projects that must
        not have to reason about lczkit's intermediates.

        The cache therefore lives in lczkit's own output tree, a sibling of the run directories
        rather than inside any one of them, since a tile outlives the run that computed it. Cache
        keys carry the same discipline `OvertureSource` uses — see
        `lczkit.cleaning.pipeline.tile_fingerprint`.
        """
        return self.output_dir / "lczkit" / "_cache" / "tiles"

    def source_dir(self, name: str) -> Path:
        """Return `input/<name>/`, the directory a source implementation owns.

        Only the source implementation for `name` writes here; nothing else in the package
        writes under `input/` at all.
        """
        return self.input_dir / name

    @classmethod
    def load(
        cls,
        *,
        run_id: str | None = None,
        dotenv_path: Path | str | None = None,
        create_run_dir: bool = True,
    ) -> Settings:
        """Load `.env`, resolve `DATA_DIR`, and create `output/lczkit/<run_id>/` if absent.

        Also picks up `GEE_PROJECT_NAME` into `land_cover.gee_project`, and `MAPTILER_API_KEY` into
        `viz.maptiler_key`. Unlike `DATA_DIR` both are optional — only the Earth Engine backend and
        the MapTiler base maps need them, and each raises its own message when it is missing — so an
        absent value is not an error here. **An absent variable leaves whatever is already
        configured alone**: assigning `os.environ.get(...)` unconditionally would overwrite a value
        supplied by a config file with `None`, which is a silent discard rather than a precedence
        rule.

        `create_run_dir=False` resolves everything and touches nothing, for callers that only want
        to *read* the resolved configuration — `lczkit run --dry-run`. The default creates it,
        because every caller that goes on to run a pipeline needs it to exist.

        Never creates or modifies anything under `input/`. Raises `ValueError` with a clear
        message if `DATA_DIR` is unset; raises a `pydantic.ValidationError` (also with a
        clear message) if it is set but does not exist.
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
    """`MAPTILER_API_KEY` from the environment, stripped, or `None` if it is unset or blank.

    Separate from `Settings.load` because `lczkit site build` needs the key and does **not** need
    `DATA_DIR`: it works off a run directory given on the command line, and `Settings.load` raises
    without `DATA_DIR`. Requiring one to get the other would make rebuilding an archived site
    depend on an unrelated variable. `Settings.load` calls this too, so there is one definition of
    where the key comes from.

    The strip is not cosmetic. A trailing space in a `.env` line is invisible in an editor and
    survives into the tile URL, where it makes every request 403 — a broken base map whose cause is
    unreadable from the symptom.

    It reads the environment, which the rest of the package must not do: `os.environ` is touched
    in this module and nowhere else.
    """
    load_dotenv(dotenv_path=dotenv_path)
    raw = os.environ.get("MAPTILER_API_KEY")
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None
