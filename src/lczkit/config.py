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
    """Configuration for `OvertureSource` (Phase 1)."""

    release: str | None = None
    """Pinned Overture release string, e.g. "2026-07-22.0". Never "latest" — `OvertureSource`
    raises if this is unset."""

    source_dir_name: str = "Overture_Maps"
    """Name of the subdirectory under `input/` that `OvertureSource` caches into. Matches the
    directory already used by other projects sharing `DATA_DIR`, not CLAUDE.md's diagram
    spelling ("Overture")."""


class CleaningConfig(BaseModel):
    """Configurable thresholds for the Phase 1 building-cleaning pipeline.

    None of these have a literature-derived default — Majer & Fleischmann (arXiv:2603.00132)
    Supplementary D, the paper CLAUDE.md names as the cleaning spec, describes the
    corresponding operations only qualitatively. They are left unset here; the cleaning
    pipeline raises if used before being explicitly configured.
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
    city whose fabric or road-centreline generalisation differs — see
    `docs/experiments/phase-6.6-footprint-attrition.md`.
    """

    building_merge_limit_m2: float | None = None
    """`geoplanar.merge_overlaps`' `merge_limit` — overlapping polygons smaller than this are
    merged into a neighbour regardless of overlap size."""

    building_overlap_limit: float | None = None
    """`geoplanar.merge_overlaps`' `overlap_limit` (0-1 ratio) — polygons larger than
    `building_merge_limit_m2` are merged only if the shared overlap exceeds this fraction of
    their area."""


class ArealTierConfig(BaseModel):
    """One areal raster tier of the Phase 3 height cascade (tiers 2-4).

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
    reports 0 for cells with no built-up volume."""

    confidence: float | None = None
    """`height_confidence` written for every building this tier resolves. No default: see
    `HeightConfig`."""


def _default_areal_tiers() -> list[ArealTierConfig]:
    """CLAUDE.md's tiers 2, 3 and 4, in cascade order, all inert until a COG is placed.

    `source_dir_name` follows CLAUDE.md's `input/` diagram. Note that none of these three
    directories exists on the system this was developed against — `input/GHS/` is present but
    holds GHS-SMOD and GHS-UCDB, not GHS-BUILT-H — so expect to override the name as
    `OvertureConfig.source_dir_name` already does for `Overture_Maps`.
    """
    return [
        ArealTierConfig(name="gob25d", source_dir_name="GOB25D"),
        ArealTierConfig(name="wsf3d", source_dir_name="WSF3D"),
        ArealTierConfig(name="ghsl", source_dir_name="GHSL"),
    ]


class HeightConfig(BaseModel):
    """Configuration for the Phase 3 building-height cascade.

    Tiers run in the order they appear: Overture attributes first, then `areal_tiers` in list
    order. Adding a fifth areal product is an entry in that list, not a code change.

    The three `*_confidence` values have no default for the same reason `CleaningConfig`'s
    thresholds have none: no published number defines them. `height_confidence` is an ordinal
    ranking of measurement quality, not a calibrated probability, and inventing plausible-looking
    defaults is the failure mode CLAUDE.md warns about most sharply — nothing would crash, the
    map would just carry a quietly wrong quality claim. Set them explicitly and they are
    serialised into the run manifest, where the choice is visible and reproducible.
    """

    storey_height_m: float = 3.0
    """Metres per storey for the `num_floors` fallback. Varies regionally and is a real error
    source; 3.0 m is the default CLAUDE.md states."""

    overture_height_confidence: float | None = None
    """`height_confidence` for buildings resolved from Overture's `height` attribute — except
    where Overture itself supplies a per-building confidence, which is preferred over this."""

    overture_num_floors_confidence: float | None = None
    """`height_confidence` for buildings resolved from `num_floors x storey_height_m`."""

    areal_tiers: list[ArealTierConfig] = Field(default_factory=_default_areal_tiers)
    """Tiers 2-4, in cascade order."""


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
wrong map — the failure mode CLAUDE.md warns about most sharply.
"""


GeeAssetType = Literal["image_collection", "image"]
"""Whether an Earth Engine asset is a collection to filter and mosaic, or a single image.

Both occur among the MVP datasets: ESA WorldCover is a catalogued `ImageCollection`, while ETH
canopy height is a single `Image` published as a user asset. Loading one as the other is an
immediate `EEException`, so the kind is declared rather than probed.
"""


class GeeAssetConfig(BaseModel):
    """Earth Engine coordinates for one land-cover dataset.

    Serialised verbatim into the run manifest, which is where CLAUDE.md requires the collection
    ID and date range to appear.
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

    Everything product-specific lives here rather than in code, per CLAUDE.md: the class-to-
    fraction mapping is config, never hardcoded. `LocalRasterSource` and `EarthEngineSource` read
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
    whichever classes happen to occur in a given city — a class with no cells still gets a column
    holding 0.0, which is what Phases 6 and 7 need. Same argument as `height_frac_*` in Phase 3."""

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
    """CLAUDE.md's two MVP land-cover products, both inert until a COG is placed.

    Neither directory exists on the system this was developed against, so `filename` is `None` for
    both and `LocalRasterSource.from_settings` will say so plainly rather than failing obscurely.
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
            # table for Phase 5 to choose between them.
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


class LandCoverConfig(BaseModel):
    """Configuration for the Phase 4 land-cover fraction sources.

    Datasets are an ordered list so adding a third product is a config entry, not a code change —
    the same shape as `HeightConfig.areal_tiers`.
    """

    datasets: list[LandCoverDatasetConfig] = Field(default_factory=_default_land_cover_datasets)
    """The configured products, by `name`."""

    gee_project: str | None = None
    """Google Cloud project Earth Engine bills against. Read from `GEE_PROJECT_NAME` by
    `Settings.load()`."""

    gee_batch_size: int = 2000
    """Units per `reduceRegions` call. CLAUDE.md's "chunk units into batches of a few thousand to
    stay under element-count and payload limits"."""

    gee_max_units: int | None = None
    """Refuse an Earth Engine run covering more than this many units. `None` means no ceiling."""

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


class UcpConfig(BaseModel):
    """Configuration for the Phase 5 urban canopy parameters.

    Two kinds of value live here. The `*_classes` lists are vocabulary — which land-cover class
    feeds which Stewart & Oke surface fraction, and which Overture attribute values count as
    industrial — and CLAUDE.md requires those in config rather than in code. The two
    `street_profile_*` values are momepy's own defaults, restated so they reach the run manifest
    instead of staying implicit in a library signature.
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

    land_cover_dataset: str = "worldcover"
    """Which `LandCoverConfig.datasets` entry supplies the surface fractions. The ETH canopy
    dataset is a second, competing tree estimate rather than a full land-cover product, and Phase 4
    documents why it reads high — so the WorldCover route is the default."""

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

    `warehouse` is deliberately absent. CLAUDE.md's own statement of the problem this parameter
    exists to solve is that a distribution warehouse and a refinery are geometrically identical —
    the warehouse being the LCZ 8 case and the refinery the LCZ 10 one. Counting warehouses as
    industrial would push exactly the units the rule is meant to keep apart towards LCZ 10.
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


class ClassificationConfig(BaseModel):
    """Configuration for the Phase 6 prototype-distance classifier.

    Every threshold the classifier applies lives here and is serialised into the run manifest.
    Two of them - `natural_dominant_fraction` and `natural_negligible_fraction` - move the
    prototype table itself, because the tree and water ranges they generate are lczkit's own
    rather than Stewart & Oke's and there is no published value to defer to.
    """

    weight_preset: str = "bernard2024"
    """Named entry in `lczkit.classify.weights.PRESETS`. `"bernard2024"` is the published default
    for the built types; `"equal"` is the uniform comparison."""

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

    C (bush, scrub), D (low plants) and F (bare soil or sand) are mutually indistinguishable with
    the parameters this package computes: the published table separates them only by sky view
    factor, aspect ratio and height of roughness elements, all building-derived and all absent in
    open ground, and the default WorldCover mapping folds shrubland, grassland and bare ground
    into a single `pervious` class. Rather than let three tied prototypes be resolved by index
    order, C and F are excluded and the exclusion is recorded in the manifest. Reaching them needs
    a land-cover mapping that emits shrub and bare separately, and a Phase 5 fraction carrying
    them. Distances to the excluded classes are still computed and reported.
    """

    natural_dominant_fraction: float = 0.50
    """Tree or water cover at which a unit reads as LCZ A or LCZ G. See
    `docs/references/tables/lczkit_natural_class_ranges.md` - lczkit's own, not Tier 1."""

    natural_negligible_fraction: float = 0.10
    """Tree or water cover a natural class treats as absent. Reuses the 10% boundary Stewart &
    Oke apply to building and impervious cover throughout their natural rows."""

    lcz10_min_industrial_fraction: float = 0.50
    """`industrial_fraction` above which a unit whose two nearest prototypes are LCZ 8 and LCZ 10
    is relabelled LCZ 10.

    Deliberately set to under-trigger, per CLAUDE.md: Overture cannot distinguish heavy from light
    industry, so a missing LCZ 10 is a visible gap while a light-industrial estate mislabelled as
    heavy industry is an invisible error that propagates into any model consuming the map. A
    majority of the unit's area has to be industrial before the rule fires. Note the denominator
    differs from Bernard et al. (2024)'s `FIND/B`, which is a share of building area rather than
    of unit area, so their 0.33 does not transfer.
    """

    lcz1_min_height_m: float | None = None
    """Optional floor on `Hr` below which the LCZ 1 (compact high-rise) distance is discarded.

    Bernard et al. (2024) Sect. 2.3 apply the equivalent constraint on mean building levels,
    reporting that without it GeoClimate produced LCZ 1 across European cities where no urban
    researcher would place any. lczkit has no reliable per-unit storey count, so the hook is
    exposed against `Hr` instead and defaults to off - an untested constraint applied by default
    would be a worse failure than the over-prediction it guards against.
    """

    @model_validator(mode="after")
    def _check_thresholds(self) -> ClassificationConfig:
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
    """Number of classification breaks precomputed per continuous variable. Phase 7 renders
    choropleths from these and must never recompute a quantile at site-build time."""

    break_method: Literal["quantile"] = "quantile"
    """How the breaks are derived. Only quantiles are implemented; the field exists so the
    manifest states the method rather than leaving a consumer to assume one."""

    viz_significant_figures: int = 3
    """Significant figures floats are rounded to in `units_viz.parquet`."""

    viz_distance_scale: int = 1000
    """Multiplier applied to the 17-way distance vector before it is stored as `int16` in
    `units_viz.parquet`. Distances are small positive reals, so 1000 keeps three decimal places
    inside the int16 range."""

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


class ValidationConfig(BaseModel):
    """Configuration for agreement against a reference LCZ map.

    CLAUDE.md's target is the Demuzere global map on the 100 m grid, reported lczexplore-style:
    per-class agreement and a confusion matrix, never a single headline number.
    """

    reference: LandCoverDatasetConfig = Field(default_factory=_default_reference_dataset)
    """The reference map, described as a categorical raster. See `_default_reference_dataset`."""

    reference_citation: str = "10.5194/essd-14-3835-2022"
    """Demuzere et al. (2022), *ESSD* 14, 3835-3873. Recorded separately from the file actually
    read: the copy on this system is version 3 of the map and the paper describes an earlier one,
    so conflating the two in the manifest would misstate what a run was validated against."""

    min_reference_coverage: float = 0.5
    """Fraction of a unit the reference map must actually cover for that unit to enter the
    agreement statistics. A unit half outside the map's extent would otherwise contribute a
    majority computed from a corner of itself."""

    height_completeness_deciles: int = 10
    """Strata for the height-completeness breakdown. CLAUDE.md asks for deciles specifically;
    configurable so a run with few units can widen the bins rather than report noise."""

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


class Settings(BaseModel):
    """Resolved configuration for a single lczkit run.

    Construct via `Settings.load()`, not directly — that is what resolves `DATA_DIR` from
    the environment and creates the run's output directory.
    """

    data_dir: Path
    run_id: str = Field(default_factory=_default_run_id)
    overture: OvertureConfig = Field(default_factory=OvertureConfig)
    cleaning: CleaningConfig = Field(default_factory=CleaningConfig)
    heights: HeightConfig = Field(default_factory=HeightConfig)
    land_cover: LandCoverConfig = Field(default_factory=LandCoverConfig)
    ucp: UcpConfig = Field(default_factory=UcpConfig)
    classification: ClassificationConfig = Field(default_factory=ClassificationConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)

    @field_validator("data_dir")
    @classmethod
    def _validate_data_dir(cls, value: Path) -> Path:
        if not value.is_dir():
            raise ValueError(
                f"DATA_DIR does not exist or is not a directory: {value}. "
                "Set DATA_DIR in .env to the shared data directory."
            )
        return value

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

    def source_dir(self, name: str) -> Path:
        """Return `input/<name>/`, the directory a source implementation owns.

        Only the source implementation for `name` writes here; nothing else in the package
        writes under `input/` at all.
        """
        return self.input_dir / name

    @classmethod
    def load(cls, *, run_id: str | None = None, dotenv_path: Path | str | None = None) -> Settings:
        """Load `.env`, resolve `DATA_DIR`, and create `output/lczkit/<run_id>/` if absent.

        Also picks up `GEE_PROJECT_NAME` into `land_cover.gee_project`. Unlike `DATA_DIR` it is
        optional — only the Earth Engine backend needs it, and that backend raises its own message
        when it is missing — so an absent value is not an error here.

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
        settings.land_cover.gee_project = os.environ.get("GEE_PROJECT_NAME")
        settings.run_dir.mkdir(parents=True, exist_ok=True)
        return settings
