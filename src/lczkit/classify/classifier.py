"""`PrototypeClassifier` - the full 17-way distance vector and the labels drawn from it.

The output CLAUDE.md asks for is the *vector*, not the label: "Don't return a bare LCZ integer
anywhere in the core API; carry the distance vector." Hard labelling is a convenience over it, and
every label this module emits records which mechanism produced it in `label_route`, so no
consumer has to guess whether a unit was placed by morphology, by land cover or by the industrial
rule.

**The vector is computed under two metrics, one per family.** Bernard et al. (2024) apply their
weights to the built types only (Sect. 2.5) and route the natural types through land cover
entirely, and the reason shows up immediately in the numbers: with their published `FI` and `FP`
weights of zero, LCZ E, F and G become mutually indistinguishable, since impervious and pervious
cover are the only dimensions separating them. So `lcz_d1`-`lcz_d10` use the built weights and
`lcz_d11`-`lcz_d17` the natural ones. Both are on the same normalised scale, but they are *not*
the same metric, and the label comes from the argmin **within the gated family** rather than from
the argmin across all seventeen. The cross-family entries are reported because they are
informative about a unit near the boundary; they are not what decides it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from lczkit.classify import rules
from lczkit.classify.distance import PrototypeSpace, uniqueness
from lczkit.classify.labels import BUILT_CODES, CODES, NATURAL_CODES, code_of, lcz
from lczkit.classify.prototypes import build_prototypes
from lczkit.classify.weights import WeightPreset, preset
from lczkit.config import ClassificationConfig

DISTANCE_PREFIX = "lcz_d"
"""Distance columns are `lcz_d1` through `lcz_d17`, matching the integer codes."""

DISTANCE_COLUMNS: tuple[str, ...] = tuple(f"{DISTANCE_PREFIX}{code}" for code in CODES)

LABEL_COLUMNS: tuple[str, ...] = (
    "lcz_primary",
    "lcz_secondary",
    "min_distance",
    "uniqueness",
    "label_route",
    "lcz10_rule_applied",
    "semantic_rule_applied",
    "n_params_used",
    "n_params_available",
    "missing_parameters",
)

CLASSIFICATION_COLUMNS: tuple[str, ...] = (*DISTANCE_COLUMNS, *LABEL_COLUMNS)


class PrototypeClassifier:
    """Distance-to-prototype classification, satisfying the `Classifier` protocol.

    Stateless with respect to the data: build once from config, call `classify()` on any
    parameter table. The prototype space and the standardisation are derived at construction, so
    a run does not re-derive them per call and two runs sharing a config share a metric exactly.
    """

    def __init__(self, config: ClassificationConfig | None = None) -> None:
        """Derive the prototype space, the weights and the reachable class set from `config`.

        All three are fixed at construction, so `classify()` is a pure transform and two runs
        sharing a config share a metric exactly. `reachable_natural` is computed rather than
        configured: LCZ D's prototype box contains LCZ F's in every dimension, so F is
        unreachable by arithmetic and the manifest records *dominated* apart from *excluded*.
        """
        self.config = config or ClassificationConfig()
        self.weights: WeightPreset = preset(self.config.weight_preset)
        self.space = PrototypeSpace(
            build_prototypes(
                dominant_fraction=self.config.natural_dominant_fraction,
                negligible_fraction=self.config.natural_negligible_fraction,
            )
        )
        self.reachable_natural: tuple[int, ...] = tuple(
            code_of(label) for label in self.config.reachable_natural_classes
        )
        unreachable = set(NATURAL_CODES) - set(self.reachable_natural)
        self.unreachable_natural: tuple[int, ...] = tuple(sorted(unreachable))
        # LCZ 10 is scored and reported but never selected: it leaves the metric per Bernard et al.
        # and arrives only through the industrial rule. Kept as a derived tuple rather than a
        # literal so `lcz_d10` and the selection set cannot drift apart.
        self.semantic_firings: dict[str, int] = {}
        self.selectable_built: tuple[int, ...] = tuple(
            code for code in BUILT_CODES if code != FUNCTIONAL_ONLY_CODE
        )

    def classify(self, parameters: pd.DataFrame) -> pd.DataFrame:
        """Classify a Phase 5 parameter table, returning one row per `unit_id`.

        `parameters` must carry every prototype dimension plus `industrial_fraction`; the table
        `lczkit.ucp.compute_parameters()` returns does. Neither input nor index is mutated, and
        the result is indexed identically so it joins straight onto the units.
        """
        if parameters.index.name != "unit_id":
            raise ValueError("parameters must be indexed by unit_id")
        industrial_column = self.config.lcz10_industrial_column
        if industrial_column not in parameters.columns:
            raise ValueError(
                f"parameters has no {industrial_column!r} column, so LCZ 10 would be unreachable - "
                "it is not in the distance metric and the industrial rule is its only route. "
                "Pass the table lczkit.ucp.compute_parameters() returns, or point "
                "ClassificationConfig.lcz10_industrial_column at a column it carries."
            )

        built = self.space.distances(parameters, BUILT_CODES, self.weights.built)
        natural = self.space.distances(parameters, NATURAL_CODES, self.weights.natural)
        built_distances = rules.drop_lcz1_below_height(
            built.distances,
            parameters["height_of_roughness_elements_m"],
            self.config.lcz1_min_height_m,
        )

        is_built = (
            rules.family_of(
                parameters["building_surface_fraction"], self.config.built_min_building_fraction
            )
            == rules.BUILT
        )
        candidates = _combine(
            built_distances[list(self.selectable_built)],
            natural.distances[list(self.reachable_natural)],
            is_built,
        )
        ranked, fired = rules.apply_lcz10_rule(
            _two_closest(candidates),
            parameters[industrial_column],
            self.config.lcz10_min_industrial_fraction,
        )
        # After the industrial rule, so a unit both would claim keeps the calibrated answer. Every
        # semantic rule ships disabled, so by default this is a no-op that still records zeros —
        # "never fired" and "never configured" have to stay distinguishable.
        ranked, semantic_fired, self.semantic_firings = rules.apply_semantic_rules(
            ranked, parameters, self.config.semantic_rules
        )
        route = (
            pd.Series(
                np.where(is_built, rules.ROUTE_BUILT, rules.ROUTE_NATURAL),
                index=parameters.index,
                dtype="object",
            )
            .where(~fired, rules.ROUTE_INDUSTRIAL)
            .where(~semantic_fired, rules.ROUTE_SEMANTIC)
        )

        # Select by code before renaming. Concatenating and assigning column labels positionally
        # assumes each frame comes back in its family's code order - true today, since `distances`
        # builds its dict in `codes` order, but a mislabelled distance vector would be silent and
        # selecting by code costs nothing.
        vector = pd.concat(
            [built_distances[list(BUILT_CODES)], natural.distances[list(NATURAL_CODES)]],
            axis=1,
        )
        vector.columns = pd.Index(
            [f"{DISTANCE_PREFIX}{code}" for code in [*BUILT_CODES, *NATURAL_CODES]]
        )
        result = pd.concat(
            [
                vector[list(DISTANCE_COLUMNS)],
                pd.DataFrame(
                    {
                        "lcz_primary": ranked.primary.astype("Int8"),
                        "lcz_secondary": ranked.secondary.astype("Int8"),
                        "min_distance": ranked.closest,
                        "uniqueness": uniqueness(ranked.closest, ranked.runner_up),
                        "label_route": pd.Categorical(route, categories=list(rules.ROUTES)),
                        "lcz10_rule_applied": fired,
                        "semantic_rule_applied": semantic_fired,
                        "n_params_used": _pick(
                            built.n_params_used, natural.n_params_used, is_built
                        ),
                        "n_params_available": pd.Series(
                            np.where(
                                is_built, built.n_params_available, natural.n_params_available
                            ),
                            index=parameters.index,
                            dtype="int64",
                        ),
                        "missing_parameters": _pick(
                            built.missing_parameters, natural.missing_parameters, is_built
                        ),
                    },
                    index=parameters.index,
                ),
            ],
            axis=1,
        )
        result.index.name = "unit_id"
        return result[list(CLASSIFICATION_COLUMNS)]

    def describe(self) -> dict[str, object]:
        """The full classification setup, for the run manifest.

        Everything a reader needs to reproduce a label: the active weights per family, the
        normalisation the distances were measured in, every threshold, and - importantly - which
        classes could not be assigned and why.
        """
        return {
            "weight_preset": self.weights.name,
            "weight_preset_description": self.weights.description,
            "weights": {"built": dict(self.weights.built), "natural": dict(self.weights.natural)},
            "normalisation": self.space.normalisation.as_dict(),
            "prototypes": [
                {
                    "code": prototype.code,
                    "dimension": prototype.column,
                    "property": prototype.property_name,
                    "min": prototype.lo,
                    "max": prototype.hi,
                    "source": prototype.source,
                }
                for prototype in self.space.prototypes
            ],
            "semantic_rules": [
                {
                    "name": rule.name,
                    "lcz": rule.lcz,
                    "column": rule.column,
                    "min_fraction": rule.min_fraction,
                    "enabled": rule.enabled,
                    "reason": rule.reason,
                    "units_assigned": self.semantic_firings.get(rule.name, 0),
                }
                for rule in self.config.semantic_rules
            ],
            "thresholds": {
                "built_min_building_fraction": self.config.built_min_building_fraction,
                "lcz10_industrial_column": self.config.lcz10_industrial_column,
                "lcz10_min_industrial_fraction": self.config.lcz10_min_industrial_fraction,
                "lcz1_min_height_m": self.config.lcz1_min_height_m,
                "natural_dominant_fraction": self.config.natural_dominant_fraction,
                "natural_negligible_fraction": self.config.natural_negligible_fraction,
            },
            "unreachable_classes": {
                **{str(code): _unreachable_reason(code) for code in self.unreachable_natural},
                str(FUNCTIONAL_ONLY_CODE): (
                    "Functional only: removed from the distance metric per Bernard et al. (2024) "
                    "and assigned solely by the industrial rule, above "
                    f"{self.config.lcz10_min_industrial_fraction} of "
                    f"{self.config.lcz10_industrial_column}. The morphological rule it replaced "
                    "was measured inert on the Rotterdam fixture at every threshold from 0.05 to "
                    "0.5 - port plots are sparsely built, so building surface fraction places them "
                    "on LCZ 9 and LCZ 10 never came within reach of the argmin. Its distance is "
                    "still computed and reported as lcz_d10."
                ),
            },
        }


FUNCTIONAL_ONLY_CODE = 10
"""LCZ 10 (heavy industry): scored and reported, never selected by the metric.

Bernard et al. (2024) remove it from the closest-distance approach, and the measurement behind
following them is Rotterdam's: the pair-gated rule that assigned it morphologically was inert at
every threshold from 0.05 to 0.5 across 671 cells of working port. Its distance stays in the
seventeen-way vector because CLAUDE.md requires the full vector; only the argmin excludes it.
"""

DOMINATED_CLASSES: dict[int, int] = {16: 14}
"""Natural classes whose prototype box is contained in another's, and by which class.

LCZ F (bare soil or sand, 16) sits inside LCZ D (low plants, 14) in every dimension: identical on
aspect ratio, building, impervious, pervious, tree and water, and tighter on Hr - at most 0.25 m
against D's at most 1 m. A contained box can never be strictly nearer than its container, so
d(F) >= d(D) for every possible unit, and `_two_closest` breaks ties to the lower code.

**F is therefore unreachable by arithmetic, not by configuration**, and removing it from
`reachable_natural_classes` would not make it assignable. Recorded separately so the run manifest
distinguishes a class this package chose not to assign from one it cannot.
"""


def _unreachable_reason(code: int) -> str:
    """Why `code` is never assigned, distinguishing a policy exclusion from a dominated box."""
    dominator = DOMINATED_CLASSES.get(code)
    if dominator is not None:
        return (
            f"Dominated: the LCZ {lcz(code).label} prototype box is contained in "
            f"LCZ {lcz(dominator).label}'s in every dimension, so its distance can never be "
            "strictly smaller and ties break to the lower code. Unreachable by arithmetic rather "
            "than by configuration - adding it to reachable_natural_classes would not make it "
            "assignable. Reaching it needs a land-cover mapping that emits bare ground separately. "
            "Distances to it are reported but it is never assigned. See "
            "docs/references/tables/lczkit_natural_class_ranges.md."
        )
    return (
        "Excluded by configuration: not separable from LCZ D with the parameters this package "
        "computes, where no building stands. The published table distinguishes them only by sky "
        "view factor, aspect ratio and height of roughness elements, all building-derived, and the "
        "default land-cover mapping folds shrubland, grassland and bare ground into one pervious "
        "class. Distances to it are reported but it is never assigned. See "
        "docs/references/tables/lczkit_natural_class_ranges.md."
    )


def _combine(built: pd.DataFrame, natural: pd.DataFrame, is_built: pd.Series) -> pd.DataFrame:
    """Candidate distances per unit: the built columns for built units, natural for the rest.

    The two families are different metrics, so a unit is never offered a choice across the gate.
    Masking to NaN rather than dropping keeps one frame whose column set is the same for every
    row, which is what lets the argmin be a single vectorised operation.
    """
    candidates = pd.concat([built, natural], axis=1)
    for column in built.columns:
        candidates[column] = candidates[column].where(is_built)
    for column in natural.columns:
        candidates[column] = candidates[column].where(~is_built)
    return candidates


def _two_closest(candidates: pd.DataFrame) -> rules.Ranked:
    """The two nearest classes and their distances, from a frame of per-class distances.

    Ties are broken by column order, which is ascending LCZ code. That is deterministic but
    arbitrary, and it is exactly what `uniqueness` reports: a tie gives 0.0.
    """
    values = candidates.to_numpy(dtype="float64", na_value=np.nan)
    order = np.argsort(np.where(np.isnan(values), np.inf, values), axis=1, kind="stable")
    codes = np.asarray(candidates.columns, dtype="int64")

    def nth(rank: int) -> tuple[pd.Series, pd.Series]:
        """`(code, distance)` at zero-based `rank` in the sorted order, as aligned Series."""
        position = order[:, rank]
        rows = np.arange(len(candidates))
        distance = values[rows, position]
        code = np.where(np.isnan(distance), np.nan, codes[position])
        return (
            pd.Series(code, index=candidates.index, dtype="float64"),
            pd.Series(distance, index=candidates.index, dtype="float64"),
        )

    primary, closest = nth(0)
    secondary, runner_up = nth(1)
    return rules.Ranked(primary=primary, secondary=secondary, closest=closest, runner_up=runner_up)


def _pick(built: pd.Series, natural: pd.Series, is_built: pd.Series) -> pd.Series:
    """The built series where `is_built`, the natural one elsewhere."""
    return built.where(is_built, natural)


def classify_units(
    parameters: pd.DataFrame, config: ClassificationConfig | None = None
) -> pd.DataFrame:
    """Convenience wrapper: build a `PrototypeClassifier` from `config` and classify once."""
    return PrototypeClassifier(config).classify(parameters)
