"""The LCZ prototype table: per class, the range each property is allowed to take.

Stewart & Oke (2012) Table 3 defines seventeen classes as ranges over ten properties. In the
closest-distance approach a class is a hypercube in that space and a unit is a point, so this
table is the entire basis of classification. Every number here is transcribed from
`docs/references/tables/`, never reproduced from memory: a plausible-looking wrong threshold is
the worst failure mode this package has.

Every value here is transcribed from `docs/references/tables/stewart_oke_2012_properties.md`,
**verbatim and in the table's own units**, including the properties this package cannot compute.
`test_classify_prototypes.py` parses that markdown and asserts cell-for-cell agreement, so the
committed table stays the authority and this module is a copy of it that ships in the wheel.
Percent-to-fraction conversion happens in `PropertySpec.scale`, in one place, rather than being
folded into the transcription where a test could not see it.

Three properties are lczkit's own and are marked `source=LCZKIT`. `tree_fraction` and
`water_fraction` come from `docs/references/tables/lczkit_natural_class_ranges.md` and exist
because the published table cannot separate the natural classes at all with the parameters this
package computes — see that file for the full argument, and `UNUSED_PROPERTIES` below for the
properties whose absence causes it.

`mean_building_area_m2` comes from `docs/references/tables/lczkit_building_size_ranges.md` and
exists because LCZ 7 and LCZ 8 — *lightweight* low-rise and *large* low-rise — are separated by
nothing in the metric that measures how big a building is, and consequently come out **swapped**:
measured over built cells, LCZ 8 lands on 55-93 m² footprints and LCZ 7 on 7 000-13 000 m² ones, in
every city checked. **It carries weight 0.0 in every shipped preset and therefore changes no
label**, because its weight has not been calibrated against a reference.
"""

from __future__ import annotations

from dataclasses import dataclass

from lczkit.classify.labels import LCZ_CLASSES, code_of

STEWART_OKE_2012 = "10.1175/BAMS-D-11-00019.1"
"""Stewart & Oke (2012), *BAMS* 93(12), 1879-1900, Table 3."""

LCZKIT = "lczkit"
"""Not from any publication. See `docs/references/tables/lczkit_natural_class_ranges.md`."""


@dataclass(frozen=True)
class PropertySpec:
    """One axis of the prototype space."""

    name: str
    """Property name as it appears in the transcribed table, lower-cased and underscored."""

    column: str | None
    """The `lczkit.ucp` parameter column carrying it, or `None` if this package does not
    compute it. A `None` column drops the property out of the distance metric entirely."""

    table_unit: str
    """Unit the transcribed values are in: `"percent"`, `"m"`, `"fraction"` or `"class"`."""

    scale: float
    """Multiplier converting a transcribed value into the column's unit. 0.01 for the three
    percentage properties, 1.0 elsewhere."""

    source: str
    """`STEWART_OKE_2012` or `LCZKIT`."""

    reads_building_height: bool = False
    """Whether computing this dimension consumes the building height.

    Two do, and only one of them is obviously a height: `height_of_roughness_elements_m` is the
    geometric mean of building heights, and `aspect_ratio` is `momepy.street_profile(...,
    height=buildings["height"])`, whose numerator is that same column. So a height error does not
    perturb one dimension of the metric, it perturbs two — and under `bernard2024_partial` those
    two carry 9 of the 17 applied weight units between them.

    Recorded as data rather than as prose because the manifest states the figure, and a
    hand-written constant would go stale the moment a weight preset or a dimension changed.
    """


PROPERTIES: tuple[PropertySpec, ...] = (
    PropertySpec("sky_view_factor", None, "fraction", 1.0, STEWART_OKE_2012),
    PropertySpec(
        "aspect_ratio",
        "aspect_ratio",
        "fraction",
        1.0,
        STEWART_OKE_2012,
        reads_building_height=True,
    ),
    PropertySpec(
        "building_surface_fraction", "building_surface_fraction", "percent", 0.01, STEWART_OKE_2012
    ),
    PropertySpec(
        "impervious_surface_fraction",
        "impervious_surface_fraction",
        "percent",
        0.01,
        STEWART_OKE_2012,
    ),
    PropertySpec(
        "pervious_surface_fraction", "pervious_surface_fraction", "percent", 0.01, STEWART_OKE_2012
    ),
    PropertySpec(
        "height_of_roughness_elements",
        "height_of_roughness_elements_m",
        "m",
        1.0,
        STEWART_OKE_2012,
        reads_building_height=True,
    ),
    PropertySpec("terrain_roughness_class", None, "class", 1.0, STEWART_OKE_2012),
    PropertySpec("surface_admittance", None, "J m-2 s-1/2 K-1", 1.0, STEWART_OKE_2012),
    PropertySpec("surface_albedo", None, "fraction", 1.0, STEWART_OKE_2012),
    PropertySpec("anthropogenic_heat_output", None, "W m-2", 1.0, STEWART_OKE_2012),
    PropertySpec("tree_fraction", "tree_fraction", "fraction", 1.0, LCZKIT),
    PropertySpec("water_fraction", "water_fraction", "fraction", 1.0, LCZKIT),
    PropertySpec("mean_building_area", "mean_building_area_m2", "m2", 1.0, LCZKIT),
)

PROPERTY_NAMES: tuple[str, ...] = tuple(spec.name for spec in PROPERTIES)

_BY_PROPERTY = {spec.name: spec for spec in PROPERTIES}

#: `label -> property -> (min, max)`, verbatim from the transcribed tables. `None` is a blank
#: cell, meaning the class is unbounded on that side. A property absent from a class's dict is
#: unbounded on *both* sides — LCZ G has no published height range at all, and the ten built types
#: carry no tree or water range.
_RANGES: dict[str, dict[str, tuple[float | None, float | None]]] = {
    "1": {
        "sky_view_factor": (0.2, 0.4),
        "aspect_ratio": (2, None),
        "building_surface_fraction": (40, 60),
        "impervious_surface_fraction": (40, 60),
        "pervious_surface_fraction": (None, 10),
        "height_of_roughness_elements": (25, None),
        "terrain_roughness_class": (8, 8),
        "surface_admittance": (1500, 1800),
        "surface_albedo": (0.10, 0.20),
        "anthropogenic_heat_output": (50, 300),
    },
    "2": {
        "sky_view_factor": (0.3, 0.6),
        "aspect_ratio": (0.75, 2),
        "building_surface_fraction": (40, 70),
        "impervious_surface_fraction": (30, 50),
        "pervious_surface_fraction": (None, 20),
        "height_of_roughness_elements": (10, 25),
        "terrain_roughness_class": (6, 7),
        "surface_admittance": (1500, 2200),
        "surface_albedo": (0.10, 0.20),
        "anthropogenic_heat_output": (None, 75),
    },
    "3": {
        "sky_view_factor": (0.2, 0.6),
        "aspect_ratio": (0.75, 1.5),
        "building_surface_fraction": (40, 70),
        "impervious_surface_fraction": (20, 50),
        "pervious_surface_fraction": (None, 30),
        "height_of_roughness_elements": (3, 10),
        "terrain_roughness_class": (6, 6),
        "surface_admittance": (1200, 1800),
        "surface_albedo": (0.10, 0.20),
        "anthropogenic_heat_output": (None, 75),
    },
    "4": {
        "sky_view_factor": (0.5, 0.7),
        "aspect_ratio": (0.75, 1.25),
        "building_surface_fraction": (20, 40),
        "impervious_surface_fraction": (30, 40),
        "pervious_surface_fraction": (30, 40),
        "height_of_roughness_elements": (25, None),
        "terrain_roughness_class": (7, 8),
        "surface_admittance": (1400, 1800),
        "surface_albedo": (0.12, 0.25),
        "anthropogenic_heat_output": (None, 50),
    },
    "5": {
        "sky_view_factor": (0.5, 0.8),
        "aspect_ratio": (0.3, 0.75),
        "building_surface_fraction": (20, 40),
        "impervious_surface_fraction": (30, 50),
        "pervious_surface_fraction": (20, 40),
        "height_of_roughness_elements": (10, 25),
        "terrain_roughness_class": (5, 6),
        "surface_admittance": (1400, 2000),
        "surface_albedo": (0.12, 0.25),
        "anthropogenic_heat_output": (None, 25),
    },
    "6": {
        "sky_view_factor": (0.6, 0.9),
        "aspect_ratio": (0.3, 0.75),
        "building_surface_fraction": (20, 40),
        "impervious_surface_fraction": (20, 50),
        "pervious_surface_fraction": (30, 60),
        "height_of_roughness_elements": (3, 10),
        "terrain_roughness_class": (5, 6),
        "surface_admittance": (1200, 1800),
        "surface_albedo": (0.12, 0.25),
        "anthropogenic_heat_output": (None, 25),
    },
    "7": {
        "sky_view_factor": (0.2, 0.5),
        "aspect_ratio": (1, 2),
        "building_surface_fraction": (60, 90),
        "impervious_surface_fraction": (None, 20),
        "pervious_surface_fraction": (None, 30),
        "height_of_roughness_elements": (2, 4),
        "terrain_roughness_class": (4, 5),
        "surface_admittance": (800, 1500),
        "surface_albedo": (0.15, 0.35),
        "anthropogenic_heat_output": (None, 35),
    },
    "8": {
        "sky_view_factor": (0.7, None),
        "aspect_ratio": (0.1, 0.3),
        "building_surface_fraction": (30, 50),
        "impervious_surface_fraction": (40, 50),
        "pervious_surface_fraction": (None, 20),
        "height_of_roughness_elements": (3, 10),
        "terrain_roughness_class": (5, 5),
        "surface_admittance": (1200, 1800),
        "surface_albedo": (0.15, 0.25),
        "anthropogenic_heat_output": (None, 50),
    },
    "9": {
        "sky_view_factor": (0.8, None),
        "aspect_ratio": (0.1, 0.25),
        "building_surface_fraction": (10, 20),
        "impervious_surface_fraction": (None, 20),
        "pervious_surface_fraction": (60, 80),
        "height_of_roughness_elements": (3, 10),
        "terrain_roughness_class": (5, 6),
        "surface_admittance": (1000, 1800),
        "surface_albedo": (0.12, 0.25),
        "anthropogenic_heat_output": (None, 10),
    },
    "10": {
        "sky_view_factor": (0.6, 0.9),
        "aspect_ratio": (0.2, 0.5),
        "building_surface_fraction": (20, 30),
        "impervious_surface_fraction": (20, 40),
        "pervious_surface_fraction": (40, 50),
        "height_of_roughness_elements": (5, 15),
        "terrain_roughness_class": (5, 6),
        "surface_admittance": (1000, 2500),
        "surface_albedo": (0.12, 0.20),
        "anthropogenic_heat_output": (300, None),
    },
    "A": {
        "sky_view_factor": (None, 0.4),
        "aspect_ratio": (1, None),
        "building_surface_fraction": (None, 10),
        "impervious_surface_fraction": (None, 10),
        "pervious_surface_fraction": (90, None),
        "height_of_roughness_elements": (3, 30),
        "terrain_roughness_class": (8, 8),
        "surface_albedo": (0.10, 0.20),
        "anthropogenic_heat_output": (0, 0),
    },
    "B": {
        "sky_view_factor": (0.5, 0.8),
        "aspect_ratio": (0.25, 0.75),
        "building_surface_fraction": (None, 10),
        "impervious_surface_fraction": (None, 10),
        "pervious_surface_fraction": (90, None),
        "height_of_roughness_elements": (3, 15),
        "terrain_roughness_class": (5, 6),
        "surface_admittance": (1000, 1800),
        "surface_albedo": (0.15, 0.25),
        "anthropogenic_heat_output": (0, 0),
    },
    "C": {
        "sky_view_factor": (0.7, 0.9),
        "aspect_ratio": (0.25, 1.0),
        "building_surface_fraction": (None, 10),
        "impervious_surface_fraction": (None, 10),
        "pervious_surface_fraction": (90, None),
        "height_of_roughness_elements": (None, 2),
        "terrain_roughness_class": (4, 5),
        "surface_admittance": (700, 1500),
        "surface_albedo": (0.15, 0.30),
        "anthropogenic_heat_output": (0, 0),
    },
    "D": {
        "sky_view_factor": (0.9, None),
        "aspect_ratio": (None, 0.1),
        "building_surface_fraction": (None, 10),
        "impervious_surface_fraction": (None, 10),
        "pervious_surface_fraction": (90, None),
        "height_of_roughness_elements": (None, 1),
        "terrain_roughness_class": (3, 4),
        "surface_admittance": (1200, 1600),
        "surface_albedo": (0.15, 0.25),
        "anthropogenic_heat_output": (0, 0),
    },
    "E": {
        "sky_view_factor": (0.9, None),
        "aspect_ratio": (None, 0.1),
        "building_surface_fraction": (None, 10),
        "impervious_surface_fraction": (90, None),
        "pervious_surface_fraction": (None, 10),
        "height_of_roughness_elements": (None, 0.25),
        "terrain_roughness_class": (1, 2),
        "surface_admittance": (1200, 2500),
        "surface_albedo": (0.15, 0.30),
        "anthropogenic_heat_output": (0, 0),
    },
    "F": {
        "sky_view_factor": (0.9, None),
        "aspect_ratio": (None, 0.1),
        "building_surface_fraction": (None, 10),
        "impervious_surface_fraction": (None, 10),
        "pervious_surface_fraction": (90, None),
        "height_of_roughness_elements": (None, 0.25),
        "terrain_roughness_class": (1, 2),
        "surface_admittance": (600, 1400),
        "surface_albedo": (0.20, 0.35),
        "anthropogenic_heat_output": (0, 0),
    },
    "G": {
        "sky_view_factor": (0.9, None),
        "aspect_ratio": (None, 0.1),
        "building_surface_fraction": (None, 10),
        "impervious_surface_fraction": (None, 10),
        "pervious_surface_fraction": (90, None),
        "terrain_roughness_class": (1, 1),
        "surface_admittance": (1500, 1500),
        "surface_albedo": (0.02, 0.10),
        "anthropogenic_heat_output": (0, 0),
    },
}

#: `label -> property -> (min, max)`, transcribed verbatim from
#: `docs/references/tables/lczkit_building_size_ranges.md`. **lczkit's own, not Stewart & Oke** —
#: their table has no building-size column at all. Only the two classes whose published *name*
#: asserts a building size are constrained; every other class is unbounded on both sides and takes
#: no penalty here, because giving LCZ 3 or LCZ 9 a range would invent a claim the scheme does not
#: make. The dimension carries weight 0.0 in every shipped preset, so none of this moves a label
#: until a sweep says what weight it should carry.
_BUILDING_SIZE: dict[str, dict[str, tuple[float | None, float | None]]] = {
    "7": {"mean_building_area": (None, 100.0)},
    "8": {"mean_building_area": (500.0, None)},
}

DEFAULT_DOMINANT_FRACTION = 0.50
"""Tree or water cover at which a natural class is "dense trees" or "water" - the majority of
the unit. lczkit's own, from `docs/references/tables/lczkit_natural_class_ranges.md`."""

DEFAULT_NEGLIGIBLE_FRACTION = 0.10
"""Tree or water cover a natural class treats as absent. Reuses the 10% boundary the Stewart &
Oke table itself applies to building and impervious cover throughout its natural rows."""


def _natural_cover(
    dominant: float, negligible: float
) -> dict[str, dict[str, tuple[float | None, float | None]]]:
    """The lczkit-owned tree and water ranges, as a function of the two thresholds.

    Parameterised rather than transcribed so `ClassificationConfig` can move both numbers and the
    prototype table follows, instead of the defaults being frozen into a literal that config can
    only contradict. The built types appear nowhere here: they are unbounded in both dimensions.
    """
    absent = {"tree_fraction": (None, negligible), "water_fraction": (None, negligible)}
    return {
        "A": {"tree_fraction": (dominant, None), "water_fraction": (None, negligible)},
        "B": {"tree_fraction": (negligible, dominant), "water_fraction": (None, negligible)},
        "C": dict(absent),
        "D": dict(absent),
        "E": dict(absent),
        "F": dict(absent),
        "G": {"tree_fraction": (None, negligible), "water_fraction": (dominant, None)},
    }


@dataclass(frozen=True)
class PrototypeRange:
    """One class's allowed interval in one dimension, in the *column's* unit.

    `lo` or `hi` of `None` is an open end: the class is unbounded on that side and a unit beyond
    it is never penalised there. A dimension missing from a class entirely is open on both sides.
    """

    code: int
    """LCZ integer code 1-17."""

    property_name: str
    """Entry in `PROPERTIES`."""

    column: str
    """The `lczkit.ucp` parameter column, always non-`None` here."""

    lo: float | None
    hi: float | None

    source: str
    """`STEWART_OKE_2012` or `LCZKIT`."""


def build_prototypes(
    *,
    dominant_fraction: float = DEFAULT_DOMINANT_FRACTION,
    negligible_fraction: float = DEFAULT_NEGLIGIBLE_FRACTION,
) -> tuple[PrototypeRange, ...]:
    """The prototype table, with the two lczkit-owned thresholds substituted in.

    Called with no arguments this reproduces `PROTOTYPES` exactly. `ClassificationConfig` calls it
    with the configured thresholds, so moving them moves the table rather than leaving config and
    prototypes disagreeing.
    """
    if not 0.0 < negligible_fraction < dominant_fraction <= 1.0:
        raise ValueError(
            "expected 0 < negligible_fraction < dominant_fraction <= 1, got "
            f"{negligible_fraction} and {dominant_fraction}"
        )
    cover = _natural_cover(dominant_fraction, negligible_fraction)
    ranges: list[PrototypeRange] = []
    for entry in LCZ_CLASSES:
        by_property = {
            **_RANGES[entry.label],
            **cover.get(entry.label, {}),
            **_BUILDING_SIZE.get(entry.label, {}),
        }
        for spec in PROPERTIES:
            if spec.column is None or spec.name not in by_property:
                continue
            lo, hi = by_property[spec.name]
            ranges.append(
                PrototypeRange(
                    code=entry.code,
                    property_name=spec.name,
                    column=spec.column,
                    lo=None if lo is None else lo * spec.scale,
                    hi=None if hi is None else hi * spec.scale,
                    source=spec.source,
                )
            )
    return tuple(ranges)


PROTOTYPES: tuple[PrototypeRange, ...] = build_prototypes()
"""Every (class, dimension) interval the distance metric can use, in column units."""

DIMENSIONS: tuple[str, ...] = tuple(spec.column for spec in PROPERTIES if spec.column is not None)
"""The parameter columns classification runs over, in `PROPERTIES` order."""

HEIGHT_DEPENDENT_DIMENSIONS: tuple[str, ...] = tuple(
    spec.column for spec in PROPERTIES if spec.column is not None and spec.reads_building_height
)
"""Dimensions whose value moves when the height cascade does. See
`PropertySpec.reads_building_height` — there are two, and one of them is not called a height."""


def ranges_for(code: int) -> dict[str, tuple[float | None, float | None]]:
    """`column -> (lo, hi)` for one class, omitting dimensions it does not constrain."""
    return {
        prototype.column: (prototype.lo, prototype.hi)
        for prototype in PROTOTYPES
        if prototype.code == code
    }


def property_of(column: str) -> PropertySpec:
    """The `PropertySpec` whose `column` is `column`."""
    for spec in PROPERTIES:
        if spec.column == column:
            return spec
    raise KeyError(f"no prototype dimension for column {column!r}; have {', '.join(DIMENSIONS)}")


UNUSED_PROPERTIES: tuple[tuple[str, str], ...] = (
    (
        "sky_view_factor",
        "Not computed: the single most expensive component, and strongly correlated with "
        "aspect ratio, which is computed. Its absence is the main reason the published table "
        "cannot separate LCZ A, B, C and D: it is one of only three dimensions distinguishing "
        "them, and the other two are also building-derived. Bernard et al. (2024) Sect. 2.5, "
        "p. 2085 weight it at 4 of 21.5 — third of the seven, behind building surface fraction "
        "at 8 and height of roughness elements at 6.",
    ),
    (
        "terrain_roughness_class",
        "Not computed. Davenport et al. (2000) map the class to a roughness length z0, and "
        "deriving z0 from morphology (Macdonald, Kanda) is not implemented, so the lookup has no "
        "input. Bernard et al. (2024) weight z0 at 0.5 of 21.5, the least influential dimension "
        "in their scheme.",
    ),
    (
        "surface_admittance",
        "A thermal property of the materials, not a morphological one. Nothing in the open vector "
        "or raster data this package ingests measures it, and no proxy for it is proposed. "
        "Stewart & Oke publish it as a descriptive attribute of each class rather than as a "
        "classification input, and Bernard et al. (2024) assign it no weight.",
    ),
    (
        "surface_albedo",
        "As for surface admittance: a radiative property of the materials. Deriving it would need "
        "a multispectral product and a narrowband-to-broadband conversion, which is a different "
        "package.",
    ),
    (
        "anthropogenic_heat_output",
        "An energy-use quantity, not a surface one. Estimating it needs population, traffic and "
        "building-energy data none of which this package ingests. Note that it is the only "
        "property in the published table that would separate LCZ 10 from LCZ 8 directly - 300+ "
        "W m-2 against at most 50 - which is why the LCZ 10 rule has to reach for a functional "
        "attribute instead.",
    ),
)
"""Stewart & Oke properties present in the transcribed table but absent from the distance metric.

Recorded as data so the run manifest can say which dimensions of the LCZ definition a run
actually measured. Five of the ten are unused, which is a material caveat on every label this
package emits and must not be discoverable only by reading the source.
"""


def _check() -> None:
    """Fail at import if the transcription is internally inconsistent."""
    labels = {entry.label for entry in LCZ_CLASSES}
    if set(_RANGES) != labels:
        raise RuntimeError(f"prototype labels {set(_RANGES) ^ labels} do not match LCZ_CLASSES")
    for label, by_property in _RANGES.items():
        unknown = set(by_property) - set(PROPERTY_NAMES)
        if unknown:
            raise RuntimeError(f"LCZ {label}: unknown properties {sorted(unknown)}")
        for name, (lo, hi) in by_property.items():
            if lo is not None and hi is not None and lo > hi:
                raise RuntimeError(f"LCZ {label} {name}: min {lo} exceeds max {hi}")
            if lo is None and hi is None:
                raise RuntimeError(
                    f"LCZ {label} {name}: both ends blank; omit the property instead"
                )
    # Scoped to the land-cover pair rather than to every lczkit-owned property. Tree and water
    # cover exist to separate the *natural* classes and constraining a built type with them would
    # silently change what LCZ 1-10 mean; `mean_building_area` is lczkit's too and is deliberately
    # the opposite — it constrains two built types and no natural one.
    natural_only = {"tree_fraction", "water_fraction"}
    built = {code_of(entry.label) for entry in LCZ_CLASSES if entry.label.isdigit()}
    for prototype in PROTOTYPES:
        if prototype.property_name in natural_only and prototype.code in built:
            raise RuntimeError(
                f"{prototype.property_name} is lczkit's and must not constrain a built type"
            )
        if prototype.property_name == "mean_building_area" and prototype.code not in built:
            raise RuntimeError("mean_building_area must not constrain a natural type")
    if code_of("G") not in {prototype.code for prototype in PROTOTYPES}:
        raise RuntimeError("LCZ G produced no prototype ranges")


_check()
