"""Confidence intervals for the agreement figures, by spatial block bootstrap.

**Why an interval at all.** Every headline this package reports - `overall_agreement`,
`built_agreement`, both axis `lift`s - is a point estimate, and the sixteen-city work compares them
across cities, differences them between arms, and orders the next lever by which is larger. None of
that is readable without knowing how much of the difference is noise. `axis_reconciliation.py`
compares `max_over_median_lift` against a hard `< 5.0` as though it were a test statistic.

**Why blocks rather than units.** The units are not independent draws. So2Sat patches are 320 m
squares sampled on a 100 m stride, so neighbouring patches overlap about sevenfold and the labelled
cells of a city are one contiguous, strongly autocorrelated sheet. Resampling cells independently
would treat 9 627 near-duplicate observations as 9 627 independent ones and return an interval far
too narrow - the classic effective-sample-size error. Resampling contiguous *blocks* keeps the
local correlation inside the resampling unit, which is what a block bootstrap is for.

The block size is a judgement, not a measurement: it has to be larger than the correlation length
and small enough to leave many blocks. The default is 1 km, comfortably above the 320 m patch width
that generates most of the dependence, and it is reported in the output so a reader can see what it
was rather than infer it.

**What this does not do.** It quantifies sampling variability under the labels this run was scored
against. It says nothing about the label support mismatch (a 320 m patch label attributed to a 1 ha
cell), which is a bias rather than a variance and does not shrink with more cells.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from pydantic import BaseModel

from lczkit.config import ValidationConfig
from lczkit.crs import assert_projected_crs
from lczkit.validation.agreement import AgreementReport, agreement


class Interval(BaseModel):
    """A point estimate with a percentile bootstrap interval around it."""

    point: float
    lower: float
    upper: float

    @property
    def width(self) -> float:
        """`upper - lower`, in the units of the figure — the interval's span, not a half-width."""
        return self.upper - self.lower


class BootstrapReport(BaseModel):
    """Intervals for the figures the project actually compares across cities and arms."""

    n_resamples: int
    confidence: float
    block_size_m: float
    n_blocks: int
    """Blocks resampled with replacement. This, not the unit count, is the effective sample size -
    and the gap between the two is the whole reason this module exists."""

    n_units: int

    overall_agreement: Interval
    built_agreement: Interval
    built_natural_agreement: Interval
    height_lift: Interval
    compactness_lift: Interval


def spatial_blocks(units: gpd.GeoDataFrame, block_size_m: float) -> pd.Series:
    """Assign each unit to a square block of side `block_size_m`, keyed by `unit_id`.

    Blocks are anchored on the projected CRS origin rather than on the data's own bounding box, for
    the reason `GridUnits` uses the same anchor: two runs over overlapping extents then agree about
    which block a unit is in, so their intervals are computed over comparable partitions.

    Uses a representative point rather than a centroid so a concave enclosure lands in a block it
    actually occupies.
    """
    assert_projected_crs(units, "units")
    if block_size_m <= 0:
        raise ValueError(f"block_size_m must be positive; got {block_size_m}")

    points = units.geometry.representative_point()
    col = np.floor(points.x.to_numpy() / block_size_m).astype("int64")
    row = np.floor(points.y.to_numpy() / block_size_m).astype("int64")
    return pd.Series(
        [f"block_{c}_{r}" for c, r in zip(col, row, strict=True)],
        index=units.index,
        name="block",
    )


def _statistics(report: AgreementReport) -> dict[str, float]:
    height = report.height_axis_summary
    compactness = report.compactness_axis_summary
    return {
        "overall_agreement": report.overall_agreement,
        "built_agreement": report.built_agreement,
        "built_natural_agreement": report.built_natural_agreement,
        "height_lift": height.lift if height is not None else float("nan"),
        "compactness_lift": compactness.lift if compactness is not None else float("nan"),
    }


def bootstrap_agreement(
    predicted: pd.Series,
    reference: pd.Series,
    area_m2: pd.Series,
    blocks: pd.Series,
    *,
    coverage: pd.Series | None = None,
    config: ValidationConfig | None = None,
    n_resamples: int = 200,
    confidence: float = 0.95,
    seed: int = 0,
    block_size_m: float = float("nan"),
) -> BootstrapReport:
    """Percentile bootstrap over spatial blocks, resampled with replacement.

    `blocks` is a `unit_id`-indexed block label, from `spatial_blocks()`. Every input is aligned on
    `unit_id` first, so a caller cannot silently pair a prediction with another unit's block.

    `seed` is fixed by default: an interval that moves between two runs of the same data is not a
    property of the data, and this package treats reproducibility as a feature rather than an
    afterthought. `block_size_m` is carried through for the record only - the blocks themselves
    arrive already formed, so nothing here depends on it being right, but a reported interval whose
    block size a reader has to guess is not much of a record.
    """
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must lie in (0, 1); got {confidence}")
    if n_resamples < 1:
        raise ValueError(f"n_resamples must be at least 1; got {n_resamples}")

    frame = pd.DataFrame(
        {
            "predicted": predicted,
            "reference": reference,
            "area": area_m2,
            "block": blocks,
            "coverage": 1.0 if coverage is None else coverage,
        }
    ).dropna(subset=["block"])

    def score(sample: pd.DataFrame) -> dict[str, float]:
        """The tracked agreement figures for one resample, as a flat name-to-value mapping."""
        # A resample repeats blocks, so the index carries duplicate unit_ids. `agreement()` joins
        # its inputs by position through a DataFrame constructor, but a duplicated label would make
        # any later reindex ambiguous, so the resample gets a fresh unique index.
        indexed = sample.reset_index(drop=True)
        indexed.index = pd.Index([f"r{i}" for i in range(len(indexed))], name="unit_id")
        return _statistics(
            agreement(
                indexed["predicted"],
                indexed["reference"],
                indexed["area"],
                coverage=indexed["coverage"],
                config=config,
            )
        )

    point = score(frame)
    members = {name: group for name, group in frame.groupby("block", sort=True)}
    names = list(members)
    rng = np.random.default_rng(seed)

    draws: list[dict[str, float]] = []
    for _ in range(n_resamples):
        picked = rng.choice(len(names), size=len(names), replace=True)
        draws.append(score(pd.concat([members[names[i]] for i in picked])))

    tail = 100.0 * (1.0 - confidence) / 2.0

    def interval(name: str) -> Interval:
        """The percentile interval for one figure across the draws, around its point estimate.

        Non-finite draws are dropped rather than propagated: a resample can miss a class
        entirely, which makes that class's figure undefined for that draw and not for the city.
        An interval with no usable draws is returned as NaN bounds rather than invented.
        """
        values = np.asarray([draw[name] for draw in draws], dtype="float64")
        usable = values[np.isfinite(values)]
        if usable.size == 0:
            return Interval(point=point[name], lower=float("nan"), upper=float("nan"))
        return Interval(
            point=point[name],
            lower=float(np.percentile(usable, tail)),
            upper=float(np.percentile(usable, 100.0 - tail)),
        )

    return BootstrapReport(
        n_resamples=n_resamples,
        confidence=confidence,
        block_size_m=block_size_m,
        n_blocks=len(names),
        n_units=int(len(frame)),
        overall_agreement=interval("overall_agreement"),
        built_agreement=interval("built_agreement"),
        built_natural_agreement=interval("built_natural_agreement"),
        height_lift=interval("height_lift"),
        compactness_lift=interval("compactness_lift"),
    )
