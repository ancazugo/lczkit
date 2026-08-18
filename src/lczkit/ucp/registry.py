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

from collections.abc import Iterable
from dataclasses import dataclass

from lczkit.config import SemanticGroupConfig

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

    label: str
    """Short human-readable name, for a legend or a sidebar row.

    Here rather than in the front end because a display name is part of what a parameter *is*, and
    the alternative — `column.replace("_", " ")` in JavaScript — produced "height of roughness
    elements m" and "industrial fraction of building area" on every published map. Carries no unit;
    `unit` is appended separately so the two cannot disagree.
    """

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
        label="Building surface fraction",
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
        label="Impervious surface fraction",
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
        label="Pervious surface fraction",
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
        label="Tree cover fraction",
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
        label="Water fraction",
        unit="fraction",
        description=(
            "Water-covered fraction of the unit, from the Phase 4 land-cover table. Also counted "
            "inside `pervious_surface_fraction`; kept separately because it is the only route to "
            "LCZ G."
        ),
        reference=BERNARD_2024,
    ),
    ParameterSpec(
        name="impervious_clipped",
        label="Impervious fraction was clipped",
        unit="category",
        description=(
            "True where the building surface fraction exceeded the raster's impervious class, so "
            "the subtraction that separates roofs from other sealed ground was clipped at zero. "
            "`building + impervious + pervious` is exactly 1.0 by construction everywhere else; "
            "here it exceeds 1.0, because the vector footprints cover more ground than a 10 m "
            "land-cover product calls built-up. That is dense low-rise mapped from imagery — the "
            "same fabric the height cascade is weakest in — so the flag is not a rare corner and "
            "is reported per unit rather than absorbed."
        ),
        reference=COMPUTED_HERE,
    ),
    ParameterSpec(
        name="height_of_roughness_elements_m",
        label="Height of roughness elements",
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
        label="Height, geometric mean, area-weighted",
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
        label="Height, arithmetic mean, area-weighted",
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
        label="Height, standard deviation",
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
        label="Aspect ratio (H/W)",
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
        label="Street openness",
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
        label="Street width",
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
        label="Building count",
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
        label="Mean building area",
        unit="m2",
        description=(
            "Mean footprint area of the buildings counted by `building_count`, measured over the "
            "whole footprint rather than the part inside the unit. Null for a unit holding none."
        ),
        reference=COMPUTED_HERE,
    ),
    ParameterSpec(
        name="industrial_fraction_of_building_area",
        label="Industrial share of building area",
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
        label="Industrial share of unit area",
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
        label="Industrial share (deprecated alias)",
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
        label="Industrial share, from building class",
        unit="fraction",
        description="Unit area share covered by industrial building footprints alone.",
        reference=COMPUTED_HERE,
    ),
    ParameterSpec(
        name="industrial_fraction_land_use",
        label="Industrial share, from land use",
        unit="fraction",
        description="Unit area share covered by industrial land-use parcels alone.",
        reference=COMPUTED_HERE,
    ),
    ParameterSpec(
        name="industrial_evidence",
        label="Industrial evidence source",
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
"""Column order of the table `compute_parameters()` returns, up to the semantic block.

The Phase 18 semantic columns are **not** here, because their names depend on the configured
groups. `semantic_specs()` builds their specs from the same config the columns come from, so a
group added in config cannot end up in the output with no documented unit or reference — which is
the state a static list would produce silently.
"""

COVERAGE_SPECS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        name="building_tag_coverage",
        label="Building attribute coverage",
        unit="fraction",
        description=(
            "Share of the unit's building area whose Overture `subtype` or `class` is present and "
            "not 'unknown'. **Read every semantic fraction against this.** Building attributes are "
            "48.6% of building area across Europe and North America and 13.6% elsewhere — Rio "
            "reaches 3.1% — so a semantic fraction of 0.0 usually means 'untagged', not 'absent'. "
            "Wherever an ML source wins the footprints its tagged share is exactly 0.0%. The role "
            "`height_completeness` plays for the height cascade, on a second attribute that "
            "collapses in the same places."
        ),
        reference=COMPUTED_HERE,
    ),
    ParameterSpec(
        name="land_use_coverage",
        label="Land-use parcel coverage",
        unit="fraction",
        description=(
            "Share of the unit's area under any Overture land-use parcel, dissolved so "
            "self-overlapping parcels count once. Holds 30-65% in the cities where building tags "
            "are near-absent, which is why parcel and building evidence are reported apart."
        ),
        reference=COMPUTED_HERE,
    ),
)


def semantic_specs(groups: Iterable[SemanticGroupConfig]) -> tuple[ParameterSpec, ...]:
    """`ParameterSpec` for every column the semantic layer emits for `groups`.

    Built from config rather than transcribed, for the reason `PARAMETER_COLUMNS` gives: a static
    list and a configurable group set drift, and CLAUDE.md's rule is that no parameter reaches the
    output without a documented unit and source reference.
    """
    specs: list[ParameterSpec] = []
    for group in groups:
        hint = f" Evidence for LCZ {group.lcz_hint}." if group.lcz_hint else ""
        specs.append(
            ParameterSpec(
                name=f"sem_{group.name}_buildings_of_building_area",
                label=f"{group.name.replace('_', ' ').capitalize()} share of building area",
                unit="fraction",
                description=(
                    f"Share of the unit's building area whose Overture `subtype` or `class` places "
                    f"it in the '{group.name}' group.{hint} Null where the unit holds no building "
                    "area. Bernard et al.'s FIND/B quantity, generalised beyond industry. Groups "
                    "are not a partition and these do not sum to one."
                ),
                reference=BERNARD_2024,
            )
        )
    for group in groups:
        hint = f" Evidence for LCZ {group.lcz_hint}." if group.lcz_hint else ""
        specs.append(
            ParameterSpec(
                name=f"sem_{group.name}_parcels_of_unit_area",
                label=f"{group.name.replace('_', ' ').capitalize()} share of unit area",
                unit="fraction",
                description=(
                    f"Share of the unit's area under land-use parcels of the '{group.name}' "
                    f"group, dissolved before measuring.{hint} A different numerator *and* "
                    "denominator from the building column of the same group; the two are not "
                    "comparable and their names say so."
                ),
                reference=COMPUTED_HERE,
            )
        )
    return (*specs, *COVERAGE_SPECS)


_BY_NAME = {parameter.name: parameter for parameter in PARAMETERS}


def spec(name: str, groups: Iterable[SemanticGroupConfig] | None = None) -> ParameterSpec:
    """The `ParameterSpec` for column `name`, or a `KeyError` naming what exists.

    `groups` extends the lookup over the configured semantic columns, whose names are not knowable
    without it.
    """
    if name in _BY_NAME:
        return _BY_NAME[name]
    for candidate in semantic_specs(groups or []):
        if candidate.name == name:
            return candidate
    raise KeyError(f"no parameter named {name!r}; known: {', '.join(PARAMETER_COLUMNS)}")


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
