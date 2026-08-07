"""Agreement against a reference LCZ map, reported the way the LCZ literature reports it.

CLAUDE.md is specific that comparability matters more than a headline figure: per-class agreement
and a confusion matrix, lczexplore-style, not a single accuracy number. A single number hides the
thing a reader of an LCZ map actually needs to know, which is *which* classes are being confused
for which - Bernard et al. (2024) Sect. 3.2 read their own results exactly this way, noting that
their worst agreements sit on classes covering a negligible share of the area.

Two breakdowns beyond the standard ones are required here, and both exist to turn the Phase 3
height caveat into a measured quantity:

- **agreement by `height_completeness` decile**, so a city where tier-1 heights are near-absent
  can be judged rather than disclaimed; and
- **the height-axis confusion pairs 1<->4, 2<->5, 3<->6**, which is where CLAUDE.md predicts the
  error concentrates when heights come from an areal product - those pairs differ essentially
  only in height, so a height estimate that cannot resolve the <10 m / 10-25 m / >25 m bands
  within a heterogeneous unit moves a label along that axis and nowhere else.

Everything is area-weighted. On a regular grid that is the same as counting units; on enclosures
it is not, and weighting by count there would let a thousand courtyards outvote a district.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from lczkit.classify.labels import HEIGHT_AXIS_PAIRS, lcz
from lczkit.config import ValidationConfig


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
    reference."""


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


class HeightAxisConfusion(BaseModel):
    """One compact/open pair that differs essentially only in building height."""

    compact: int
    open: int
    n_compact_as_open: int
    n_open_as_compact: int
    n_total: int
    share_of_disagreement: float
    """`n_total` over all disagreeing units. The number CLAUDE.md's Phase 3 prediction is
    about: if areal height products are the limiting factor, these three pairs should hold a
    disproportionate share of the errors."""


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

    per_class: list[ClassAgreement] = Field(default_factory=list)
    confusion: list[ConfusionCell] = Field(default_factory=list)
    by_height_completeness: list[Stratum] = Field(default_factory=list)
    height_axis: list[HeightAxisConfusion] = Field(default_factory=list)

    n_disagree: int = 0


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

    report.per_class = _per_class(compared)
    report.confusion = _confusion(compared)
    report.height_axis = _height_axis(compared)
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
    """One row per reference class present, ascending by code."""
    rows: list[ClassAgreement] = []
    for code in sorted(compared["reference"].unique()):
        entry = lcz(int(code))
        group = compared[compared["reference"] == code]
        area = float(group["area"].sum())
        agreed = group[group["agree"]]
        rows.append(
            ClassAgreement(
                code=entry.code,
                label=entry.label,
                name=entry.name,
                n_reference=int(len(group)),
                area_reference_m2=area,
                n_agree=int(len(agreed)),
                area_agree_m2=float(agreed["area"].sum()),
                agreement=_share(float(agreed["area"].sum()), area),
            )
        )
    return rows


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


def _height_axis(compared: pd.DataFrame) -> list[HeightAxisConfusion]:
    """The 1<->4, 2<->5, 3<->6 pairs and their share of all disagreement."""
    disagreeing = int((~compared["agree"]).sum())
    rows: list[HeightAxisConfusion] = []
    for compact, open_ in HEIGHT_AXIS_PAIRS:
        forward = int(((compared["reference"] == compact) & (compared["predicted"] == open_)).sum())
        backward = int(
            ((compared["reference"] == open_) & (compared["predicted"] == compact)).sum()
        )
        rows.append(
            HeightAxisConfusion(
                compact=compact,
                open=open_,
                n_compact_as_open=forward,
                n_open_as_compact=backward,
                n_total=forward + backward,
                share_of_disagreement=_share(float(forward + backward), float(disagreeing)),
            )
        )
    return rows


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
