"""What every parameter column means, in what unit, from which source.

CLAUDE.md's acceptance criterion for this phase is "a parameter table keyed by `unit_id` with
every field documented, including units and the source paper for each", and its anti-pattern list
forbids writing a parameter to the output without a documented unit and reference. Prose in a
docstring satisfies neither for a machine: Phase 6 serialises this into the run manifest and
Phase 7 renders "every UCP with its unit of measurement" in the per-unit sidebar. Keeping the
documentation in a registry makes the pairing a tested invariant rather than something that drifts
the first time a column is renamed.
"""

from __future__ import annotations

from dataclasses import dataclass

STEWART_OKE_2012 = "10.1175/BAMS-D-11-00019.1"
"""Stewart & Oke (2012), *BAMS* 93(12), 1879-1900. Defines the LCZ scheme and the property table
Phase 6 classifies against."""

BERNARD_2024 = "10.5194/gmd-17-2077-2024"
"""Bernard et al. (2024), *GMD* 17, 2077-2107. Table 1 gives operational definitions for the same
properties over vector data."""

MOMEPY = "10.21105/joss.01807"
"""Fleischmann (2019), *JOSS* 4(43), 1807. `momepy.street_profile()` is derived in turn from
Araldi & Fusco (2019), which momepy cites."""

COMPUTED_HERE = "computed here"
"""No published definition — a plain descriptive statistic, defined by its own description."""


@dataclass(frozen=True)
class ParameterSpec:
    """One column of the parameter table."""

    name: str
    """Column name in the table `compute_parameters()` returns."""

    unit: str
    """Unit of measurement. One of `UNITS`."""

    description: str
    """What the number is, precisely enough to reproduce it."""

    reference: str
    """DOI of the source that defines it, or `COMPUTED_HERE`."""


UNITS = ("m", "m2", "fraction", "count", "dimensionless", "category")
"""The controlled vocabulary `ParameterSpec.unit` draws on. `"fraction"` means a real in [0, 1]."""


PARAMETERS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        name="building_surface_fraction",
        unit="fraction",
        description=(
            "Building footprint area within the unit, over unit area. Footprints are split at "
            "unit boundaries, so a building straddling two units contributes to both in "
            "proportion. Zero — not null — for a unit holding no buildings."
        ),
        reference=STEWART_OKE_2012,
    ),
    ParameterSpec(
        name="impervious_surface_fraction",
        unit="fraction",
        description=(
            "Impervious land-cover fraction with the building share removed, clipped at zero. "
            "A raster's built-up class contains the roofs, and Stewart & Oke's building, "
            "impervious and pervious fractions partition the surface between them."
        ),
        reference=STEWART_OKE_2012,
    ),
    ParameterSpec(
        name="pervious_surface_fraction",
        unit="fraction",
        description=(
            "Pervious land-cover fraction with tree cover and water folded back in. Stewart & "
            "Oke put both LCZ A (dense trees) and LCZ G (water) at 90%+ pervious, so neither "
            "class is reachable unless both count here."
        ),
        reference=STEWART_OKE_2012,
    ),
    ParameterSpec(
        name="tree_fraction",
        unit="fraction",
        description=(
            "Tree-covered fraction of the unit, from the Phase 4 land-cover table. Also counted "
            "inside `pervious_surface_fraction`; kept separately because it separates LCZ A and "
            "B from the other pervious classes."
        ),
        reference=BERNARD_2024,
    ),
    ParameterSpec(
        name="water_fraction",
        unit="fraction",
        description=(
            "Water-covered fraction of the unit, from the Phase 4 land-cover table. Also counted "
            "inside `pervious_surface_fraction`; kept separately because it is the only route to "
            "LCZ G."
        ),
        reference=BERNARD_2024,
    ),
    ParameterSpec(
        name="height_of_roughness_elements_m",
        unit="m",
        description=(
            "Stewart & Oke's Hr: the unweighted GEOMETRIC mean of building height, exp(mean(log "
            "h)), over every building with a resolved height intersecting the unit. Heights are "
            "floored at a small positive value before the log. Buildings the Phase 3 cascade left "
            "unresolved are excluded. Null for a unit holding no building with a height."
        ),
        reference=BERNARD_2024,
    ),
    ParameterSpec(
        name="h_geometric_area_weighted",
        unit="m",
        description=(
            "SECONDARY, not for classification. The same geometric mean as Hr, but weighted by "
            "footprint area, so a 5 m2 shed no longer counts as much as a tower block. Hr itself "
            "stays unweighted because Bernard et al. (2024) Table 1 specifies that form and the "
            "Stewart & Oke ranges were defined for it — weighting it would change the definition "
            "silently. Emitted so the size of the difference is measurable: Phase 10 established "
            "that Hr's sensitivity to dispersion is what made the most accurate height product "
            "degrade the map, and the same mechanism acts on the unweighted mean itself."
        ),
        reference=COMPUTED_HERE,
    ),
    ParameterSpec(
        name="h_mean_area_weighted",
        unit="m",
        description=(
            "SECONDARY, not for classification. Arithmetic mean building height weighted by "
            "footprint area inside the unit. It is not Hr and sits above it wherever a unit mixes "
            "tall and short buildings; the Stewart & Oke ranges were defined for the geometric "
            "mean. Retained because the deferred roughness work (Macdonald, Kanda) needs it."
        ),
        reference=COMPUTED_HERE,
    ),
    ParameterSpec(
        name="h_std",
        unit="m",
        description=(
            "SECONDARY, not for classification. Area-weighted population standard deviation of "
            "building height, over the same weights and buildings as `h_mean_area_weighted`. Zero "
            "for a unit holding one building. Retained for the deferred roughness work, where "
            "Kanda et al. (2013) needs a height spread."
        ),
        reference=COMPUTED_HERE,
    ),
    ParameterSpec(
        name="aspect_ratio",
        unit="dimensionless",
        description=(
            "Street canyon height-to-width ratio: the street-length-weighted mean of "
            "`momepy.street_profile()`'s `hw_ratio` over the segments crossing the unit. Null "
            "where no street segment reaching a building crosses it."
        ),
        reference=STEWART_OKE_2012,
    ),
    ParameterSpec(
        name="street_openness",
        unit="fraction",
        description=(
            "Street-length-weighted mean of `momepy.street_profile()`'s `openness` — the share of "
            "perpendicular ticks along a segment that reach no building within the tick length. "
            "1.0 is a street with no built frontage."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="street_width_m",
        unit="m",
        description=(
            "Street-length-weighted mean of `momepy.street_profile()`'s `width` — the mean "
            "building-to-building distance across the street. A segment reaching no building "
            "reports the tick length as a theoretical maximum."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="building_count",
        unit="count",
        description=(
            "Buildings whose representative point falls inside the unit. Whole buildings, unlike "
            "the area quantities: half a building is not a building. Zero — not null — for a "
            "unit holding none."
        ),
        reference=COMPUTED_HERE,
    ),
    ParameterSpec(
        name="mean_building_area_m2",
        unit="m2",
        description=(
            "Mean footprint area of the buildings counted by `building_count`, measured over the "
            "whole footprint rather than the part inside the unit. Null for a unit holding none."
        ),
        reference=COMPUTED_HERE,
    ),
    ParameterSpec(
        name="industrial_fraction_of_building_area",
        unit="fraction",
        description=(
            "Share of the unit's BUILDING area that is industrial — footprint falling inside the "
            "dissolved industrial evidence, over all footprint. Bernard et al. (2024)'s FIND/B, so "
            "their published 0.33 threshold transfers to this column and not to the unit-area one. "
            "Null where the unit holds no buildings: a share of nothing is undefined, not zero. "
            "Functional, not morphological — Phase 6 applies it after the prototype distance."
        ),
        reference=BERNARD_2024,
    ),
    ParameterSpec(
        name="industrial_fraction_of_unit_area",
        unit="fraction",
        description=(
            "Share of the unit's GROUND that is industrial: industrial building footprints or "
            "industrial land-use parcels, the two dissolved into one geometry so overlapping "
            "evidence counts once. Sensitive to how much of the cell is built at all, which is "
            "why Bernard's threshold does not transfer to it."
        ),
        reference=COMPUTED_HERE,
    ),
    ParameterSpec(
        name="industrial_fraction",
        unit="fraction",
        description=(
            "DEPRECATED alias for `industrial_fraction_of_unit_area`, kept for one release. The "
            "bare name is the one whose denominator this repository contradicted itself about in "
            "three places at once; read one of the two named columns instead."
        ),
        reference=COMPUTED_HERE,
    ),
    ParameterSpec(
        name="industrial_fraction_buildings",
        unit="fraction",
        description="Unit area share covered by industrial building footprints alone.",
        reference=COMPUTED_HERE,
    ),
    ParameterSpec(
        name="industrial_fraction_land_use",
        unit="fraction",
        description="Unit area share covered by industrial land-use parcels alone.",
        reference=COMPUTED_HERE,
    ),
    ParameterSpec(
        name="industrial_evidence",
        unit="category",
        description=(
            "Which sources contributed area to `industrial_fraction`: 'none', 'buildings', "
            "'land_use' or 'both'. CLAUDE.md requires recording which evidence source fired, "
            "because the two are very differently reliable."
        ),
        reference=COMPUTED_HERE,
    ),
)

PARAMETER_COLUMNS: tuple[str, ...] = tuple(parameter.name for parameter in PARAMETERS)
"""Column order of the table `compute_parameters()` returns."""

_BY_NAME = {parameter.name: parameter for parameter in PARAMETERS}


def spec(name: str) -> ParameterSpec:
    """The `ParameterSpec` for column `name`, or a `KeyError` naming what exists."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"no parameter named {name!r}; known: {', '.join(PARAMETER_COLUMNS)}"
        ) from None


NOT_COMPUTED: tuple[tuple[str, str], ...] = (
    (
        "sky_view_factor",
        "Deferred by CLAUDE.md. The single most expensive component, and strongly correlated with "
        "aspect ratio, which this phase does compute. Bernard et al. (2018), 10.3390/cli6030060, "
        "is the preferred route when it is picked up: vector ray-launching, no DSM required.",
    ),
    (
        "terrain_roughness_class",
        "Deferred. CLAUDE.md asks for it via the Davenport et al. (2000) lookup, but that table "
        "maps a roughness class to a roughness length z0, and computing z0 from morphology is on "
        "the same document's deferred list. Bernard et al. (2024) weight z0 at 0.5 against 8 for "
        "building fraction and 6 for mean height, so it is the least influential parameter in "
        "their scheme — deferring it costs the classification little.",
    ),
)
"""Stewart & Oke properties this phase does not compute, and why.

Recorded here rather than only in the README so the omission reaches the run manifest: a consumer
reading the parameter table needs to know that two dimensions of the LCZ definition are absent, not
zero.
"""


LIMITATIONS: tuple[tuple[str, str], ...] = (
    (
        "industrial_fraction",
        "Overture exposes a single 'industrial' value with no heavy/light split. GeoClimate keys "
        "LCZ 10 on OSM's HEAVY INDUSTRY against light industry and commercial, and that "
        "distinction does not survive Overture's schema normalisation — the same normalisation "
        "that removes the need for a tag-mapping table also discards the semantic detail OSM "
        "carried. A light-industrial estate and a refinery are therefore indistinguishable here, "
        "so Phase 6's LCZ 10 threshold is set to under-trigger: a missing LCZ 10 is a visible "
        "gap, whereas a light-industrial estate mislabelled as heavy industry is an invisible "
        "error that propagates into any model consuming the map. 'warehouse' is excluded from the "
        "industrial vocabulary; it is an LCZ 8 example.",
    ),
    (
        "h_mean_area_weighted, h_std",
        "Secondary columns. They are not Stewart & Oke's height of roughness elements and must "
        "not be used for classification — Hr is the geometric mean, and the LCZ property ranges "
        "were defined for it. These exist for the deferred roughness work (Macdonald, Kanda).",
    ),
)
"""Known limitations of specific parameters, in the parameters' own terms.

CLAUDE.md requires the Overture heavy/light industry limitation to appear in the field docs *and*
the manifest, which means it has to be data rather than a docstring. Phase 6 serialises this
alongside `NOT_COMPUTED`.
"""
