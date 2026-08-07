"""Per-dimension weights for the prototype-distance metric.

Bernard et al. (2024) Sect. 2.3 make the weight vector an explicit degree of freedom rather than
an assumption, for three stated reasons: the input data may not represent reality well, the method
used for a given UCP may not match Stewart & Oke's definition, and a user may simply disagree that
the seven properties matter equally. CLAUDE.md follows them - weights are config, the active
preset appears in the manifest.

**Their weights are for the built types only.** Sect. 2.5, p. 2085: "Those weights are only used
in the closest-distance approach for LCZ built types." The natural types never touch the distance
metric in GeoClimate at all; they go through a land-cover decision tree. That is why `WeightPreset`
carries two vectors, and why the natural half of `bernard2024` is marked as lczkit's rather than
as published.
"""

from __future__ import annotations

from dataclasses import dataclass

from lczkit.classify.prototypes import DIMENSIONS

BERNARD_2024 = "10.5194/gmd-17-2077-2024"
"""Bernard et al. (2024), *GMD* 17, 2077-2107, Sect. 2.5."""


@dataclass(frozen=True)
class WeightPreset:
    """A named pair of weight vectors, one per LCZ family."""

    name: str

    built: dict[str, float]
    """Weight per dimension for LCZ 1-10. Zero means the dimension is ignored entirely - it
    leaves both the numerator and the denominator of the distance."""

    natural: dict[str, float]
    """Weight per dimension for LCZ A-G."""

    description: str

    def for_family(self, family: str) -> dict[str, float]:
        """The vector for `"built"` or `"natural"`."""
        if family == "built":
            return self.built
        if family == "natural":
            return self.natural
        raise KeyError(f"unknown family {family!r}; expected 'built' or 'natural'")


#: Weights Bernard et al. publish for properties this package does not compute, and so cannot
#: apply. Recorded rather than dropped: a reader comparing an lczkit run against a GeoClimate one
#: needs to know that 4.5 of the published 21.5 total weight is unrepresented here, not infer it.
UNAPPLIED_BERNARD_WEIGHTS: tuple[tuple[str, float, str], ...] = (
    ("sky_view_factor", 4.0, "deferred in Phase 5"),
    ("effective_terrain_roughness_length", 0.5, "deferred in Phase 5"),
)

_BERNARD_BUILT: dict[str, float] = {
    "aspect_ratio": 3.0,
    "building_surface_fraction": 8.0,
    "impervious_surface_fraction": 0.0,
    "pervious_surface_fraction": 0.0,
    "height_of_roughness_elements_m": 6.0,
    "tree_fraction": 0.0,
    "water_fraction": 0.0,
}

_UNIFORM: dict[str, float] = dict.fromkeys(DIMENSIONS, 1.0)

BERNARD2024 = WeightPreset(
    name="bernard2024",
    built=_BERNARD_BUILT,
    natural=dict(_UNIFORM),
    description=(
        "Bernard et al. (2024) Sect. 2.5 defaults for the built types: H/W 3, FB 8, FI 0, FP 0, "
        "Hr 6. Impervious and pervious fractions carry zero weight on their stated grounds that "
        "they are secondary characteristics and often inaccurate in urban areas. Their SVF (4) "
        "and z0 (0.5) weights cannot be applied because this package computes neither, so the "
        "effective built metric has three non-zero dimensions rather than five. The natural "
        "vector is uniform and is lczkit's own: the paper classifies the natural types by a "
        "land-cover decision tree and defines no distance metric for them."
    ),
)

EQUAL = WeightPreset(
    name="equal",
    built=dict(_UNIFORM),
    natural=dict(_UNIFORM),
    description=(
        "Uniform weights over every available dimension, for comparison against bernard2024. "
        "Gives the impervious and pervious fractions real influence over the built types, which "
        "is the right choice where the land-cover input is trusted more than Bernard's was."
    ),
)

PRESETS: tuple[WeightPreset, ...] = (BERNARD2024, EQUAL)

_BY_NAME = {preset.name: preset for preset in PRESETS}


def preset(name: str) -> WeightPreset:
    """The preset called `name`, or a `KeyError` naming what exists."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"no weight preset named {name!r}; available: {', '.join(_BY_NAME)}"
        ) from None


def _check() -> None:
    for entry in PRESETS:
        for family in ("built", "natural"):
            vector = entry.for_family(family)
            if set(vector) != set(DIMENSIONS):
                missing = set(DIMENSIONS) ^ set(vector)
                raise RuntimeError(f"{entry.name}/{family}: dimensions {sorted(missing)} mismatch")
            if any(weight < 0 for weight in vector.values()):
                raise RuntimeError(f"{entry.name}/{family}: negative weight")
            if not any(weight > 0 for weight in vector.values()):
                raise RuntimeError(f"{entry.name}/{family}: every weight is zero")


_check()
