"""Agreement against a reference LCZ map, reported the way the LCZ literature reports it.

Comparability matters more than a headline figure: per-class agreement and a confusion matrix,
in the style of the `lczexplore` package, not a single accuracy number. A single number hides the
thing a reader of an LCZ map actually needs to know, which is *which* classes are being confused
for which - Bernard et al. (2024) Sect. 3.2 read their own results exactly this way, noting that
their worst agreements sit on classes covering a negligible share of the area.

Four breakdowns beyond the standard ones are required here:

- **built-class agreement, separately from overall**, with the natural-class share stated beside
  it. An overall figure carried by water is not a statement about the classifier;
- **agreement by `height_completeness` band**, so a city where tier-1 heights are near-absent can
  be judged rather than disclaimed;
- **the height axis**, 1<->2<->3 and 4<->5<->6, holding compactness fixed. This is where error
  concentrates when heights come from an areal product, since such a product cannot
  resolve the <10 m / 10-25 m / >25 m bands within a heterogeneous unit. It is the axis that pairs
  with the stratification above; and
- **the compactness axis**, 1<->4, 2<->5, 3<->6, holding height fixed. This is the diagnostic for
  building footprint coverage and for whether the spatial unit is the right size to hold an LCZ
  patch at all.

The two are different instruments and are reported separately. An earlier revision of the spec
named the second set the height axis, which inverted what a reader would conclude from it: a
disagreement between LCZ 2 and LCZ 5 says nothing about heights, both being midrise.

Agreement is area-weighted throughout. On a regular grid that is the same as counting units; on
enclosures it is not, and weighting by count there would let a thousand courtyards outvote a
district. **The axes are the exception, and deliberately carry both weightings**: every axis figure
published between Phases 6.7 and 11 is count-based, so `share_of_disagreement` keeps that definition
and `share_of_disagreement_area` is reported beside it. Redefining the field in place would have
silently moved every stored arm-B number while leaving arm A untouched, which is the hardest kind of
change to notice.

Raw axis shares are **not comparable across cities**, which is easy to get wrong.
Their denominator is all disagreement, so a city whose reference carries a large natural
share dilutes both axes, while an all-built fixture dilutes neither; and which pairs can fire at all
depends on which classes the reference happens to contain. `axis_summary()` below reports the raw
share alongside two corrections for exactly this - see its docstring.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from lczkit.classify.labels import (
    COMPACTNESS_AXIS_PAIRS,
    HEIGHT_AXIS_PAIRS,
    NATURAL_CODES,
    lcz,
)
from lczkit.config import ValidationConfig
from lczkit.validation.similarity import SIMILARITY

AXIS_ELIGIBLE_CODES: frozenset[int] = frozenset(
    code for pair in HEIGHT_AXIS_PAIRS + COMPACTNESS_AXIS_PAIRS for code in pair
)
"""LCZ 1-6. The only reference classes that can place a unit on either axis.

Both axis definitions are built from the compact (1-3) and open (4-6) types, so a unit whose
reference is LCZ 7-10 or a natural class contributes to the denominator of a raw axis share while
being unable to contribute to its numerator.
"""


class ClassAgreement(BaseModel):
    """Agreement for one reference class."""

    code: int
    label: str
    name: str
    n_reference: int
    """Units the reference map assigns to this class."""

    area_reference_m2: float
    n_agree: int
    area_agree_m2: float

    agreement: float
    """`area_agree_m2 / area_reference_m2`, or 0.0 where the class is absent from the
    reference. This is **producer's accuracy** (recall): of the ground the reference calls this
    class, how much did lczkit agree on."""

    n_predicted: int = 0
    """Units *lczkit* assigns to this class. The denominator of `user_accuracy`."""

    area_predicted_m2: float = 0.0

    user_accuracy: float = 0.0
    """`area_agree_m2 / area_predicted_m2`, or 0.0 where the class is never predicted.

    The complement of `agreement`, and the reason both are needed: producer's accuracy alone
    cannot see over-prediction. A classifier that labels every cell LCZ 5 scores 100% producer's
    accuracy on LCZ 5 while being useless, and nothing in this report would have said so.
    Demuzere et al. (2021) report the pair through F1 for exactly this reason.
    """

    f1: float = 0.0
    """Harmonic mean of `user_accuracy` and `agreement`, 0.0 where either is zero.

    The class-wise metric Demuzere et al. (2021), Sect. 2.4 use, following Verdonck et al. (2017):
    "the F1 metric, which is a harmonic mean of the user's and producer's accuracy". Reported so
    lczkit's per-class figures are directly comparable to published LCZ maps.
    """


class ConfusionCell(BaseModel):
    """One (reference, predicted) pair with a non-zero count."""

    reference: int
    predicted: int
    n: int
    area_m2: float


class Stratum(BaseModel):
    """Agreement within one band of a stratifying variable."""

    index: int
    lower: float
    upper: float
    n: int
    area_m2: float
    agreement: float


class AxisConfusion(BaseModel):
    """One pair of classes differing along a single axis, counted in both directions."""

    a: int
    b: int
    n_a_as_b: int
    """Units the reference calls `a` and the run called `b`."""

    n_b_as_a: int
    n_total: int
    share_of_disagreement: float
    """`n_total` over all disagreeing units. If one axis is the limiting factor, its pairs should
    hold a disproportionate share of the errors - which is the whole reason for reporting the two
    axes apart rather than pooled."""

    area_m2: float = 0.0
    share_of_disagreement_area: float = 0.0
    """The same share, area-weighted. Identical to `share_of_disagreement` on a regular grid, where
    every unit is one cell; different on enclosures, where units vary in size by orders of
    magnitude."""


class AxisSummary(BaseModel):
    """One axis pooled over its pairs, with the denominators that make cities comparable.

    Three shares of the same numerator, in increasing order of correction:

    - `share_of_disagreement` is the raw figure Phases 6.7-11 published. Its denominator is *all*
      disagreement, so it is deflated by whatever built<->natural confusion a city happens to carry
      and cannot be compared across cities with different class composition;
    - `share_of_axis_eligible` restricts the denominator to units whose reference is LCZ 1-6, the
      only classes that can land on either axis. Transparent, and enough to remove the natural-share
      dilution;
    - `lift` divides by `expected_share`, what the axis would hold if misclassification ignored the
      axes entirely. This is the one that removes *class composition*: a reference carrying only
      LCZ 2 and 5 affords the compactness pair both its directions while giving each height pair
      only one, so the two axes are not on equal footing before it is applied.

    `lift` is the figure to compare across cities. 1.0 means the axis holds exactly the share its
    reference affords it; above 1.0 means error concentrates there beyond what composition explains.
    """

    axis: str
    n_total: int
    share_of_disagreement: float
    share_of_disagreement_area: float
    n_axis_eligible: int
    share_of_axis_eligible: float
    expected_share: float
    """Share the axis would hold under a null that keeps each unit's reference class and the
    observed distribution of *wrong* labels, but breaks the association between them."""

    lift: float
    """`share_of_disagreement / expected_share`, or 0.0 where the null affords the axis nothing."""


class AgreementReport(BaseModel):
    """The full comparison against one reference map."""

    reference_citation: str
    reference_file: str | None = None

    n_units: int
    """Units in the run."""

    n_compared: int
    """Units that survived the coverage filter and carry both a prediction and a reference."""

    excluded_no_prediction: int
    excluded_no_reference: int
    excluded_low_coverage: int

    min_reference_coverage: float

    overall_agreement: float
    """Area-weighted share of compared units whose label matches the reference."""

    area_compared_m2: float

    built_agreement: float = 0.0
    """Agreement over the units the *reference* calls built (LCZ 1-10).

    Reported separately from `overall_agreement` always, because an overall figure
    can be dominated by trivially-classified natural cover and then says nothing about the
    classifier: Rotterdam's headline 42.5% was 266 water cells agreeing at 95.9% while LCZ 8 sat at
    0.0% over 224. The denominator is the reference's family, not the run's - grouping by what the
    run predicted would let a classifier improve its built score by predicting water.
    """

    natural_agreement: float = 0.0
    """Agreement over the units the reference calls natural (LCZ A-G, codes 11-17)."""

    n_built: int = 0
    n_natural: int = 0

    natural_share: float = 0.0
    """Area share of the compared units the reference calls natural. Stated alongside the headline
    so a figure carried by water is recognisable as one."""

    weighted_agreement: float = 0.0
    """`OA_w`: overall accuracy with partial credit for a near-miss, per Bechtel et al. (2020).

    Every other agreement figure here treats calling a compact midrise cell "open midrise" as
    exactly as wrong as calling it "water". For a scheme whose classes lie on a near-continuum of
    built form that is plainly false, and it is the reason this module reports the two confusion
    axes apart in the first place. `OA_w` weights the confusion matrix by class similarity, so an
    adjacent-class error scores most of a correct one and a cross-family error scores little.

    A generalisation of `overall_agreement` rather than a rival to it: plain OA is the same sum with
    a similarity matrix of ones on the diagonal and zeros off it, so the two coincide exactly when
    the matrix is the identity. Reported beside it, never instead of it — and the LCZ literature
    reports both, which is what makes lczkit's numbers comparable to a published map's.

    Count-weighted, matching the confusion matrix it is computed from. `overall_agreement` is
    area-weighted; on a grid the two coincide, on enclosures they do not.
    """

    built_natural_agreement: float = 0.0
    """`OA_bu`: agreement on the built-versus-natural distinction alone, ignoring which built or
    which natural class.

    Demuzere et al. (2021) Sect. 2.4 and Demuzere et al. (2022) Sect. 2.4 both report it beside
    OA and OA_u, and it separates two failures this report otherwise conflates: a city where lczkit
    finds the built fabric and misjudges its form, and one where it does not find the built fabric
    at all. `overall_agreement` charges both the same. It is also the one accuracy figure here that
    a height-blind pipeline can still score well on, which is the point when tier-1 coverage is 1%.
    """

    per_class: list[ClassAgreement] = Field(default_factory=list)
    confusion: list[ConfusionCell] = Field(default_factory=list)
    by_height_completeness: list[Stratum] = Field(default_factory=list)

    height_axis: list[AxisConfusion] = Field(default_factory=list)
    """1<->2<->3 and 4<->5<->6: compactness fixed, height band varies."""

    compactness_axis: list[AxisConfusion] = Field(default_factory=list)
    """1<->4, 2<->5, 3<->6: height fixed, building surface fraction varies."""

    height_axis_summary: AxisSummary | None = None
    compactness_axis_summary: AxisSummary | None = None
    """The two axes pooled, with the normalised denominators. Compare cities on `lift`, never on
    `share_of_disagreement`, which is not comparable across cities whose references carry
    different classes."""

    n_disagree: int = 0
    n_disagree_axis_eligible: int = 0
    """Disagreeing units whose reference is LCZ 1-6. The denominator of `share_of_axis_eligible`."""


def agreement(
    predicted: pd.Series,
    reference: pd.Series,
    area_m2: pd.Series,
    *,
    coverage: pd.Series | None = None,
    height_completeness: pd.Series | None = None,
    config: ValidationConfig | None = None,
    reference_file: str | None = None,
) -> AgreementReport:
    """Compare `predicted` against `reference`, both indexed by `unit_id`.

    Units missing either label, or whose reference coverage falls below the configured minimum,
    are excluded and counted separately rather than silently dropped - a run comparing a tenth of
    its units against the reference is a different claim from one comparing all of them.
    """
    settings = config or ValidationConfig()
    frame = pd.DataFrame(
        {
            "predicted": pd.to_numeric(predicted, errors="coerce"),
            "reference": pd.to_numeric(reference, errors="coerce"),
            "area": pd.to_numeric(area_m2, errors="coerce"),
        }
    )
    frame["coverage"] = 1.0 if coverage is None else pd.to_numeric(coverage, errors="coerce")

    no_prediction = frame["predicted"].isna()
    no_reference = frame["reference"].isna()
    low_coverage = (
        ~no_prediction & ~no_reference & (frame["coverage"] < settings.min_reference_coverage)
    ).fillna(True)

    compared = frame[~no_prediction & ~no_reference & ~low_coverage].copy()
    compared["agree"] = compared["predicted"] == compared["reference"]
    total_area = float(compared["area"].sum())

    report = AgreementReport(
        reference_citation=settings.reference_citation,
        reference_file=reference_file,
        n_units=int(len(frame)),
        n_compared=int(len(compared)),
        excluded_no_prediction=int(no_prediction.sum()),
        excluded_no_reference=int((~no_prediction & no_reference).sum()),
        excluded_low_coverage=int(low_coverage.sum()),
        min_reference_coverage=settings.min_reference_coverage,
        overall_agreement=_share(compared.loc[compared["agree"], "area"].sum(), total_area),
        area_compared_m2=total_area,
        n_disagree=int((~compared["agree"]).sum()),
    )
    if compared.empty:
        return report

    is_natural = compared["reference"].isin(NATURAL_CODES)
    built, natural = compared[~is_natural], compared[is_natural]
    report.n_built = int(len(built))
    report.n_natural = int(len(natural))
    report.built_agreement = _share(
        float(built.loc[built["agree"], "area"].sum()), float(built["area"].sum())
    )
    report.natural_agreement = _share(
        float(natural.loc[natural["agree"], "area"].sum()), float(natural["area"].sum())
    )
    report.natural_share = _share(float(natural["area"].sum()), total_area)
    # OA_bu: collapse both sides to the built/natural dichotomy and score that alone.
    same_family = is_natural == compared["predicted"].isin(NATURAL_CODES)
    report.built_natural_agreement = _share(
        float(compared.loc[same_family, "area"].sum()), total_area
    )

    report.per_class = _per_class(compared)
    report.confusion = _confusion(compared)
    report.weighted_agreement = weighted_agreement(report.confusion)
    report.height_axis = axis_pairs(report.confusion, HEIGHT_AXIS_PAIRS)
    report.compactness_axis = axis_pairs(report.confusion, COMPACTNESS_AXIS_PAIRS)
    report.height_axis_summary = axis_summary(report.confusion, HEIGHT_AXIS_PAIRS, axis="height")
    report.compactness_axis_summary = axis_summary(
        report.confusion, COMPACTNESS_AXIS_PAIRS, axis="compactness"
    )
    report.n_disagree_axis_eligible = report.height_axis_summary.n_axis_eligible
    if height_completeness is not None:
        report.by_height_completeness = _strata(
            compared,
            pd.to_numeric(height_completeness, errors="coerce").reindex(compared.index),
            settings.height_completeness_deciles,
        )
    return report


def _share(part: float, whole: float) -> float:
    return float(part / whole) if whole > 0 else 0.0


def _per_class(compared: pd.DataFrame) -> list[ClassAgreement]:
    """One row per class the reference or the prediction uses, ascending by code.

    Both sides, not just the reference: a class lczkit predicts and the reference never assigns has
    a user's accuracy of zero and is exactly the over-prediction that producer's accuracy alone
    cannot see. Grouping by reference only would drop it from the report entirely.
    """
    codes = sorted(set(compared["reference"].unique()) | set(compared["predicted"].unique()))
    rows: list[ClassAgreement] = []
    for code in codes:
        entry = lcz(int(code))
        group = compared[compared["reference"] == code]
        predicted = compared[compared["predicted"] == code]
        area = float(group["area"].sum())
        predicted_area = float(predicted["area"].sum())
        agreed = group[group["agree"]]
        agreed_area = float(agreed["area"].sum())
        producer = _share(agreed_area, area)
        user = _share(agreed_area, predicted_area)
        rows.append(
            ClassAgreement(
                code=entry.code,
                label=entry.label,
                name=entry.name,
                n_reference=int(len(group)),
                area_reference_m2=area,
                n_agree=int(len(agreed)),
                area_agree_m2=agreed_area,
                agreement=producer,
                n_predicted=int(len(predicted)),
                area_predicted_m2=predicted_area,
                user_accuracy=user,
                f1=(2 * user * producer / (user + producer)) if (user + producer) > 0 else 0.0,
            )
        )
    return rows


def weighted_agreement(
    confusion: Sequence[ConfusionCell],
    weights: Mapping[tuple[int, int], float] | None = None,
) -> float:
    """`OA_w` — Bechtel et al. (2020) Eq. 1: `sum(w_ij * c_ij) / N`.

    `w` is the **similarity** matrix from `docs/references/tables/lcz_class_similarity.md`, one on
    the diagonal. Passing the complement would invert the measure without raising, which is why the
    default is not a parameter a caller has to get right and why `similarity._check()` refuses a
    matrix whose diagonal is not one.

    Computed from the stored confusion list, so a manifest written before this existed can be
    re-scored without re-running the pipeline.
    """
    table = SIMILARITY if weights is None else weights
    total = sum(cell.n for cell in confusion)
    if total == 0:
        return 0.0
    scored = sum(table.get((cell.reference, cell.predicted), 0.0) * cell.n for cell in confusion)
    return float(scored / total)


def _confusion(compared: pd.DataFrame) -> list[ConfusionCell]:
    """Every (reference, predicted) pair that occurs, as a sparse list.

    Sparse rather than a 17x17 dense matrix: most cells are empty in any real city, and a list of
    the pairs that happened is both smaller in the manifest and easier to read.
    """
    grouped = (
        compared.groupby(["reference", "predicted"], sort=True)["area"]
        .agg(n="size", area_m2="sum")
        .reset_index()
    )
    return [
        ConfusionCell(
            reference=int(reference), predicted=int(predicted), n=int(n), area_m2=float(area)
        )
        for reference, predicted, n, area in zip(
            grouped["reference"].to_numpy(dtype="int64"),
            grouped["predicted"].to_numpy(dtype="int64"),
            grouped["n"].to_numpy(dtype="int64"),
            grouped["area_m2"].to_numpy(dtype="float64"),
            strict=True,
        )
    ]


def _partners(pairs: tuple[tuple[int, int], ...]) -> dict[int, frozenset[int]]:
    """For each class on the axis, the classes it can be confused with along it."""
    grouped: dict[int, set[int]] = {}
    for a, b in pairs:
        grouped.setdefault(a, set()).add(b)
        grouped.setdefault(b, set()).add(a)
    return {code: frozenset(others) for code, others in grouped.items()}


def axis_pairs(
    confusion: Sequence[ConfusionCell], pairs: tuple[tuple[int, int], ...]
) -> list[AxisConfusion]:
    """One axis' pairs and their share of all disagreement, counted in both directions.

    Derived from the confusion matrix rather than from the compared units, so that re-analysing a
    stored run cannot drift from what the run itself reported: the confusion list is what a run
    persists, and it holds exactly the counts and areas this needs.
    """
    disagreeing = [cell for cell in confusion if cell.reference != cell.predicted]
    n_disagree = float(sum(cell.n for cell in disagreeing))
    area_disagree = float(sum(cell.area_m2 for cell in disagreeing))
    counts = {(cell.reference, cell.predicted): cell for cell in disagreeing}

    rows: list[AxisConfusion] = []
    for a, b in pairs:
        forward, backward = counts.get((a, b)), counts.get((b, a))
        n_forward = forward.n if forward else 0
        n_backward = backward.n if backward else 0
        area = (forward.area_m2 if forward else 0.0) + (backward.area_m2 if backward else 0.0)
        rows.append(
            AxisConfusion(
                a=a,
                b=b,
                n_a_as_b=n_forward,
                n_b_as_a=n_backward,
                n_total=n_forward + n_backward,
                share_of_disagreement=_share(float(n_forward + n_backward), n_disagree),
                area_m2=area,
                share_of_disagreement_area=_share(area, area_disagree),
            )
        )
    return rows


def axis_summary(
    confusion: Sequence[ConfusionCell],
    pairs: tuple[tuple[int, int], ...],
    *,
    axis: str,
) -> AxisSummary:
    """Pool one axis over its pairs and normalise it for the reference's class composition.

    The null behind `expected_share` keeps each disagreeing unit's *reference* class and the
    observed distribution of wrong labels, but breaks the association between them: a unit whose
    reference is `r` takes a wrong label drawn from the run's own error distribution, conditioned on
    not being `r`. Formally, for axis X with partner sets `P`,

        E[X] = sum_r (n_r / N) * (sum_{p in P(r)} q_p) / (1 - q_r)

    with `n_r` the disagreeing units the reference calls `r`, `N` the disagreeing units in total,
    and `q` the distribution of predicted labels across them.

    Keeping `q` from the run rather than assuming it uniform matters: a classifier that
    over-predicts LCZ 5 raises the chance of landing on 2<->5 for reasons that have nothing to do
    with compactness being the limiting axis, and the null has to be able to absorb that or `lift`
    would just rediscover the prediction histogram.
    """
    rows = axis_pairs(confusion, pairs)
    disagreeing = [cell for cell in confusion if cell.reference != cell.predicted]
    n_disagree = float(sum(cell.n for cell in disagreeing))
    n_eligible = sum(cell.n for cell in disagreeing if cell.reference in AXIS_ELIGIBLE_CODES)
    n_total = sum(row.n_total for row in rows)

    partners = _partners(pairs)
    predicted_marginal: dict[int, float] = {}
    reference_counts: dict[int, int] = {}
    for cell in disagreeing:
        predicted_marginal[cell.predicted] = predicted_marginal.get(cell.predicted, 0.0) + cell.n
        reference_counts[cell.reference] = reference_counts.get(cell.reference, 0) + cell.n
    if n_disagree > 0:
        predicted_marginal = {code: n / n_disagree for code, n in predicted_marginal.items()}

    expected = 0.0
    for code, count in reference_counts.items():
        remaining = 1.0 - predicted_marginal.get(code, 0.0)
        if remaining <= 0.0:
            continue
        reachable = sum(predicted_marginal.get(other, 0.0) for other in partners.get(code, ()))
        expected += (count / n_disagree) * (reachable / remaining)

    observed = _share(float(n_total), n_disagree)
    return AxisSummary(
        axis=axis,
        n_total=n_total,
        share_of_disagreement=observed,
        share_of_disagreement_area=sum(row.share_of_disagreement_area for row in rows),
        n_axis_eligible=int(n_eligible),
        share_of_axis_eligible=_share(float(n_total), float(n_eligible)),
        expected_share=expected,
        lift=_share(observed, expected),
    )


def _strata(compared: pd.DataFrame, values: pd.Series, n_bins: int) -> list[Stratum]:
    """Agreement within equal-width bands of `values` over [0, 1].

    Equal-width, not equal-count: `height_completeness` is a fraction with a meaning attached to
    its absolute level - a decile boundary at 0.3 says something, one at "the 40th percentile of
    this city" says something only about this city, and the point of the breakdown is to compare
    cities. Bands with no units are still reported, so a run with no well-measured units cannot be
    mistaken for one that was not stratified.
    """
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    usable = values.notna()
    rows: list[Stratum] = []
    for index in range(n_bins):
        lower, upper = float(edges[index]), float(edges[index + 1])
        last = index == n_bins - 1
        in_band = usable & (values >= lower) & ((values <= upper) if last else (values < upper))
        band = compared[in_band]
        area = float(band["area"].sum())
        rows.append(
            Stratum(
                index=index,
                lower=lower,
                upper=upper,
                n=int(len(band)),
                area_m2=area,
                agreement=_share(float(band.loc[band["agree"], "area"].sum()), area),
            )
        )
    return rows
