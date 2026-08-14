"""Calibrate the LCZ 10 industrial threshold against the Rotterdam reference.

**Why this exists rather than a number in the config.** CLAUDE.md: "Calibrate the threshold, do not
pick it." The rule this replaces was pair-gated - LCZ 10 was swapped in only where it already sat
second behind LCZ 8 - and that rule was measured **inert on this fixture at every threshold from
0.05 to 0.5**. 671 cells of working port, 254 industrial buildings, three quarters of cells over
90% industrial by area, 88 cells placed in LCZ 10 by the reference, and the pair never opened once.
The threshold was never the binding constraint, so tuning it could not have helped and did not.

With LCZ 10 removed from the distance metric and assigned functionally, the threshold *is* the
binding constraint, and a naive high-recall rule fails in the opposite direction: labelling roughly
500 of 671 cells against a reference of 88. So it has to be chosen against measured precision and
recall rather than assumed.

**Which reference, and why this one.** Rotterdam has no So2Sat coverage, so this scores against
`lcz_v3.tif`. That is normally forbidden - it is a comparator carrying its own error, never ground
truth - and CLAUDE.md grants exactly one exemption: "Retain Rotterdam as the industrial fixture for
the LCZ 10 rule only." It is the only fixture on disk carrying real heavy industry at all, so the
alternative is not a better reference but no measurement.

**Which way to err.** High precision, low recall. Overture exposes a single `industrial` value with
no heavy/light split, so a light-industrial estate and a refinery are indistinguishable here. A
missing LCZ 10 is a visible gap in the map; a light-industrial estate mislabelled heavy industry is
an invisible error that propagates into any model consuming it.

**MEASURED, and it refutes the expectation above.** High precision is not reachable at any
threshold on either column. On `FIND/B` precision runs 16.7% to 23.2% across the whole range
0.05-0.95 - about six points, over a nineteen-fold change in threshold. The threshold is not the
binding constraint, for the second time and by a different mechanism from the pair-gated rule's.

What it *does* control is how much of the map carries LCZ 10, and that is worth getting right:
`FIND/B` at the selected 0.45 labels 95 cells against a reference of 88, where the unit-area share
at its own best operating point labels 196. The rate matches on one column and not the other, which
is what decides the default when precision cannot be improved.

> **A correction, recorded because it was nearly shipped as a finding.** An earlier version of this
> sweep measured `FIND/B` saturating - 84% of cells reading exactly 1.0 - and concluded that
> Bernard's quantity does not survive the move from an RSU to a 100 m cell, a third instance of
> Phase 13's patch-versus-cell result. **That was an artefact of the numerator, not a property of
> `FIND/B`.** The numerator counted every building standing inside an industrial *parcel* as
> industrial; parcels are large and swallow whole cells, so any cell touching one read 1.0.
> Counting industrial *buildings*, which is what `FIND/B` means, gives 12.6% at 1.0, a median of
> 0.66 and a tenth percentile of 0.11 - real spread. The unit-area share is the more saturated of
> the two, at 42.6%. A scale finding and a numerator bug look identical from the distribution
> alone; only changing the definition and re-measuring separated them.

The residual over-prediction - 95 predictions against 88 reference cells, but only 22 of them
agreeing - is a precision problem rather than a rate problem, and `lcz_v3` carries its own error:
CLAUDE.md already records this particular reference as coarser than the ground here, with 10.7% of
its LCZ 8 cells containing no building at all. Rotterdam is a working port. What the sweep can
settle is the *threshold*, not the reference.

Everything this reads is committed under `tests/fixtures/`, so it runs offline.

    python scripts/lcz10_threshold_sweep.py [--out run.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from conftest import (  # noqa: E402
    INDUSTRY_BBOX,
    INDUSTRY_FIXTURES_DIR,
    LANDCOVER_FIXTURES_DIR,
    LCZ_FIXTURES_DIR,
    FixtureVectorSource,
)

from lczkit.classify import PrototypeClassifier  # noqa: E402
from lczkit.cleaning.pipeline import clean_vectors  # noqa: E402
from lczkit.config import (  # noqa: E402
    ClassificationConfig,
    CleaningConfig,
    HeightConfig,
    LandCoverConfig,
    UcpConfig,
    ValidationConfig,
)
from lczkit.heights.cascade import fill_heights  # noqa: E402
from lczkit.heights.inherit import inherit_heights  # noqa: E402
from lczkit.heights.tiers import build_cascade  # noqa: E402
from lczkit.landcover.local import LocalRasterSource  # noqa: E402
from lczkit.ucp import compute_parameters  # noqa: E402
from lczkit.units.grid import GridUnits  # noqa: E402
from lczkit.validation import reference_lcz  # noqa: E402

LCZ10 = 10

#: The same cleaning the fixture's own tests use, so the sweep and the tests describe one pipeline.
CLEANING = CleaningConfig(
    building_max_area_m2=50_000.0,
    building_min_area_m2=20.0,
    building_merge_limit_m2=200.0,
    building_overlap_limit=0.1,
    building_road_buffer_m=4.0,
    building_road_overlap_limit=0.5,
)
HEIGHTS = HeightConfig(overture_height_confidence=0.9, overture_num_floors_confidence=0.6)

THRESHOLDS: tuple[float, ...] = tuple(round(0.05 * step, 2) for step in range(1, 20))
"""0.05 to 0.95. Deliberately spans the range the pair-gated rule was tested over, so the two
rules are compared on the same grid rather than on one chosen to flatter the replacement."""


@dataclass(frozen=True)
class Point:
    """One threshold's confusion against the reference, on the cells carrying both labels."""

    threshold: float
    n_predicted: int
    n_reference: int
    true_positive: int
    false_positive: int
    false_negative: int
    precision: float
    recall: float
    f1: float


def _share(part: float, whole: float) -> float:
    return float(part / whole) if whole > 0 else 0.0


def build() -> tuple[pd.DataFrame, pd.Series]:
    """The fixture's parameter table and the reference LCZ label per unit."""
    source = FixtureVectorSource(INDUSTRY_FIXTURES_DIR)
    cleaned = clean_vectors(source, INDUSTRY_BBOX, CLEANING)
    units: gpd.GeoDataFrame = GridUnits().generate(INDUSTRY_BBOX)

    tiers = build_cascade(HEIGHTS, lambda name: LANDCOVER_FIXTURES_DIR)
    buildings, _ = fill_heights(cleaned.buildings_area, tiers)
    land_cover = LocalRasterSource(
        LandCoverConfig().dataset("worldcover"),
        LANDCOVER_FIXTURES_DIR / "worldcover_rotterdam.tif",
    ).fractions(units)

    parameters = compute_parameters(
        units,
        buildings,
        inherit_heights(cleaned.buildings_topo, buildings),
        cleaned.streets,
        cleaned.land_use,
        land_cover,
        config=UcpConfig(),
        land_cover_config=LandCoverConfig(),
    )
    reference = reference_lcz(
        units, LCZ_FIXTURES_DIR / "lcz_reference_rotterdam.tif", ValidationConfig().reference
    )
    return parameters, reference["reference_lcz"]


def sweep(parameters: pd.DataFrame, reference: pd.Series, column: str) -> list[Point]:
    """Precision and recall for LCZ 10 at each threshold, on cells carrying a reference label."""
    truth = reference.reindex(parameters.index)
    scored = truth.notna()
    is_reference = (truth == LCZ10) & scored

    points: list[Point] = []
    for threshold in THRESHOLDS:
        config = ClassificationConfig(
            lcz10_industrial_column=column, lcz10_min_industrial_fraction=threshold
        )
        labels = PrototypeClassifier(config).classify(parameters)["lcz_primary"]
        is_predicted = (labels == LCZ10) & scored

        true_positive = int((is_predicted & is_reference).sum())
        false_positive = int((is_predicted & ~is_reference).sum())
        false_negative = int((~is_predicted & is_reference).sum())
        precision = _share(true_positive, true_positive + false_positive)
        recall = _share(true_positive, true_positive + false_negative)
        points.append(
            Point(
                threshold=threshold,
                n_predicted=int(is_predicted.sum()),
                n_reference=int(is_reference.sum()),
                true_positive=true_positive,
                false_positive=false_positive,
                false_negative=false_negative,
                precision=precision,
                recall=recall,
                f1=_share(2 * precision * recall, precision + recall),
            )
        )
    return points


def choose(points: list[Point], min_precision: float = 0.5) -> Point | None:
    """The highest-recall point that still clears `min_precision`, else the most precise one.

    Not the F1 maximum. F1 weights a false positive and a false negative equally, and here they are
    not equal: a missing LCZ 10 is a visible gap, a light-industrial estate mislabelled as heavy
    industry is an invisible error that propagates into any consuming model. So precision is a
    constraint and recall is what is maximised subject to it.
    """
    qualifying = [point for point in points if point.precision >= min_precision]
    if qualifying:
        return max(qualifying, key=lambda point: (point.recall, point.precision))
    return max(points, key=lambda point: (point.precision, point.recall), default=None)


def show(record: dict) -> None:
    print(f"\n  reference LCZ 10 cells: {record['n_reference']} of {record['n_scored']} scored")
    print(f"  column: {record['column']}\n")
    print(f"  {'thresh':>7}{'pred':>7}{'TP':>6}{'FP':>6}{'FN':>6}{'prec':>8}{'recall':>8}{'F1':>8}")
    for point in record["curve"]:
        print(
            f"  {point['threshold']:>7.2f}{point['n_predicted']:>7}{point['true_positive']:>6}"
            f"{point['false_positive']:>6}{point['false_negative']:>6}"
            f"{point['precision']:>8.1%}{point['recall']:>8.1%}{point['f1']:>8.1%}"
        )
    chosen = record["operating_point"]
    if chosen is None:
        print("\n  No threshold produces a single true positive — the rule cannot fire usefully.")
        return
    print(
        f"\n  OPERATING POINT: {chosen['threshold']:.2f} — "
        f"precision {chosen['precision']:.1%}, recall {chosen['recall']:.1%} "
        f"({chosen['true_positive']} of {chosen['n_reference']} found, "
        f"{chosen['false_positive']} false)"
    )


def main() -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None, help="write the record as JSON")
    parser.add_argument(
        "--column",
        default=ClassificationConfig().lcz10_industrial_column,
        help="which industrial share to threshold on",
    )
    parser.add_argument("--min-precision", type=float, default=0.5)
    args = parser.parse_args()

    parameters, reference = build()
    points = sweep(parameters, reference, args.column)
    chosen = choose(points, args.min_precision)
    scored = reference.reindex(parameters.index).notna()

    record = {
        "fixture": "rotterdam_waalhaven",
        "reference_file": "lcz_reference_rotterdam.tif",
        "reference_caveat": (
            "lcz_v3, not ground truth. Rotterdam has no So2Sat coverage; CLAUDE.md permits this "
            "comparator for the LCZ 10 rule only."
        ),
        "column": args.column,
        "min_precision": args.min_precision,
        "n_units": int(len(parameters)),
        "n_scored": int(scored.sum()),
        "n_reference": int(((reference.reindex(parameters.index) == LCZ10) & scored).sum()),
        "curve": [asdict(point) for point in points],
        "operating_point": asdict(chosen) if chosen else None,
    }
    show(record)
    if args.out:
        args.out.write_text(json.dumps(record, indent=2))
        print(f"\n  written to {args.out}")
    return record


if __name__ == "__main__":
    main()
