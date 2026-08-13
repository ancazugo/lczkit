"""Phase 13: does building surface fraction reach its published range on cells of known class?

The last diagnostic. Phase 12 named unit definition and footprint coverage as the next lever, on a
normalised compactness lift of 1.16 against height's 0.86 — and found that lift *higher* in Europe
(2.37) than elsewhere (1.15). Europe has the best footprint coverage in the sample, so a coverage
explanation predicts the opposite ordering. This phase asks the parameter directly: for cells whose
class is known, is BSF inside the Stewart & Oke interval, and does the answer differ by region?

**Why this could not be a re-analysis of the stored records.** Phase 11 stored a
BSF-versus-published table per city, and it groups by `lcz_v3` — `evaluate` built it from
`fixture.reference`, whose own docstring reads "A comparator, never the primary reference", while
`fixture.ground_truth` went unused. On Berlin that is 91 158 cells of another model's estimate where
9 627 carry a hand label. CLAUDE.md makes the labels primary wherever they exist, and Phase 6.7
measured this exact substitution inverting a diagnosis. So the labels-grouped table had to be
computed, and this script runs the sixteen cities to get it. Both groupings are reported side by
side, because their disagreement is itself a result.

**The decision statistic is `share_in_range`, not the median.** A share is exactly poolable across
cities — it is inside-area over total-area, so a cell-weighted mean of per-city shares is the pooled
share — whereas medians are not, and a "median of medians" across sixteen cities of very different
size is not a quantity anyone can interpret. The share is also a more literal reading of the
phase's question. Per-city medians are still reported, as the area-weighted mean of city medians,
labelled as such so nobody reads it as a pooled median.

Area-weighted throughout, and pooled across cities by area rather than by city, for the reason
`ranges` and `agreement` are: Vancouver carries 16 517 labelled cells against Mumbai's 1 706, and a
mean of per-city means lets the small cities outvote the large ones.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lczkit.classify import PrototypeClassifier
from lczkit.classify.prototypes import property_of
from lczkit.config import Settings

sys.path.insert(0, str(Path(__file__).resolve().parent))

from axis_reconciliation import EUROPE_AND_NORTH_AMERICA_CITIES  # noqa: E402 - sibling script
from berlin_metropolitan import CLEANING, RELEASE  # noqa: E402 - sibling script
from height_tier_experiment import run_city  # noqa: E402 - sibling script
from multi_city_validation import BY_KEY, CITIES, prepare  # noqa: E402 - sibling script
from unit_scale_experiment import HEIGHTS, UCP, VALIDATION  # noqa: E402 - sibling script

#: `coarse` only. The package has shipped it since Phase 10, and Phase 12's ruling is that a
#: diagnostic measured under a configuration the package does not ship is half a measurement.
VARIANTS = ("coarse",)

#: Arm A is the shipped pipeline — 100 m grid, `buildings_area`. B and C come along because
#: `run_city` computes all three from one cleaning, so they cost nothing extra and let the
#: unit-size reading be checked rather than assumed.
HEADLINE_ARM = "A"

GROUPINGS = {
    "bsf_by_ground_truth_class": "so2sat_labels",
    "bsf_by_reference_class": "lcz_v3",
}
"""The two references that can fill the "known class" role, primary first. `bsf_by_assigned_class`
is deliberately absent: grouping by the label this package itself produced is circular, and
CLAUDE.md records it as such."""

BUILT_CODES = tuple(range(1, 11))

EXPECTATIONS = {
    "disclosure": (
        "Formed after inspecting the stored lcz_v3-grouped table from Phase 11 "
        "(20260812T184810Z), which is the only one that existed. They are predictions about the "
        "labels-grouped table, which did not exist when they were written."
    ),
    "P1": (
        "BSF is depressed against the published ranges: classes holding most built cells have a "
        "pooled share_in_range below 0.5."
    ),
    "P2": (
        "The depression is NOT worse in Europe and North America, refuting the mechanism the "
        "phase brief proposes (street area inside the 100 m cell biting hardest on compact "
        "perimeter-block fabric). Stored lcz_v3 medians are equal or higher in Europe in seven of "
        "eight shared classes."
    ),
    "P3": (
        "The two groupings disagree materially, as Phase 6.7 measured them doing, confirming the "
        "reference choice was load-bearing rather than incidental."
    ),
}

#: A class counts as reaching its published range when more than half its area falls inside.
REACHES_RANGE = 0.5

#: Europe must trail the rest by at least this much, in pooled share, before the gap is called
#: regional rather than noise.
REGIONAL_GAP = 0.05


@dataclass(frozen=True)
class ClassRow:
    """One city's answer for one class, under one grouping — enough to pool exactly."""

    city: str
    region: str
    europe_or_na: bool
    arm: str
    cascade: str
    grouping: str
    reference_file: str | None
    code: int
    name: str
    n: int
    area_m2: float
    median: float | None
    p10: float | None
    p90: float | None
    share_in_range: float
    published_min: float | None
    published_max: float | None

    @property
    def inside_area_m2(self) -> float:
        """The part of this class' area that lands in the published interval. Poolable; the share
        is not, until divided by a pooled total."""
        return self.share_in_range * self.area_m2


def normalised_gap(row_median: float | None, lo: float | None, hi: float | None) -> float | None:
    """How far `row_median` sits below the published interval, in interval widths.

    Zero inside the interval, negative below it, positive above. Expressed in widths so LCZ 2's
    0.40-0.70 and LCZ 1's 0.40-0.60 can be averaged without the wider band dominating. `None`
    where either end is open, since a distance to an unbounded edge is not defined.
    """
    if row_median is None or lo is None or hi is None or hi <= lo:
        return None
    width = hi - lo
    if row_median < lo:
        return (row_median - lo) / width
    if row_median > hi:
        return (row_median - hi) / width
    return 0.0


def collect(record: dict[str, Any]) -> list[ClassRow]:
    """Every (city, arm, cascade, grouping, class) answer in a run record."""
    rows: list[ClassRow] = []
    for city in record.get("cities", []):
        key = city["fixture"]
        region = city.get("window", {}).get("region", "unknown")
        for cascade, payload in city.get("cascades", {}).items():
            for arm, arm_payload in payload.get("arms", {}).items():
                for field, grouping in GROUPINGS.items():
                    report = arm_payload.get(field)
                    if report is None:
                        continue
                    for entry in report["per_class"]:
                        rows.append(
                            ClassRow(
                                city=key,
                                region=region,
                                europe_or_na=key in EUROPE_AND_NORTH_AMERICA_CITIES,
                                arm=arm,
                                cascade=cascade,
                                grouping=grouping,
                                reference_file=report.get("reference_file"),
                                code=entry["code"],
                                name=entry["name"],
                                n=entry["n"],
                                area_m2=entry["area_m2"],
                                median=entry["median"],
                                p10=entry["p10"],
                                p90=entry["p90"],
                                share_in_range=entry["share_in_range"],
                                published_min=entry["published_min"],
                                published_max=entry["published_max"],
                            )
                        )
    return rows


def pool(rows: Sequence[ClassRow]) -> dict[str, Any] | None:
    """Pool a group of rows exactly where the statistic allows, and say so where it does not."""
    rows = [r for r in rows if r.area_m2 > 0]
    if not rows:
        return None
    area = sum(r.area_m2 for r in rows)
    share = sum(r.inside_area_m2 for r in rows) / area

    def area_weighted(attribute: str) -> float | None:
        pairs = [
            (getattr(r, attribute), r.area_m2) for r in rows if getattr(r, attribute) is not None
        ]
        if not pairs:
            return None
        return sum(value * weight for value, weight in pairs) / sum(w for _, w in pairs)

    mean_of_medians = area_weighted("median")
    first = rows[0]
    return {
        "code": first.code,
        "name": first.name,
        "published_min": first.published_min,
        "published_max": first.published_max,
        "n_cities": len({r.city for r in rows}),
        "n_cells": sum(r.n for r in rows),
        "area_m2": area,
        "share_in_range": share,
        "reaches_range": share >= REACHES_RANGE,
        "mean_of_city_medians": mean_of_medians,
        "normalised_gap": normalised_gap(mean_of_medians, first.published_min, first.published_max),
        # The outcome-3 ruling requires the published interval and an empirical one side by side.
        # This is an area-weighted mean of per-city deciles, not a pooled decile, for the same
        # reason `mean_of_city_medians` is not a pooled median — and it is tagged, so it can never
        # be mistaken for a published range or silently substituted for one. Nothing writes it back
        # into `prototypes.py`.
        "empirical_range": {
            "source": "lczkit_empirical",
            "definition": "area-weighted mean of per-city p10 and p90, not a pooled decile",
            "p10": area_weighted("p10"),
            "p90": area_weighted("p90"),
        },
    }


def by_class(
    rows: Iterable[ClassRow],
    *,
    grouping: str,
    arm: str,
    cascade: str,
    europe: bool | None = None,
    cities: frozenset[str] | None = None,
) -> dict[int, dict[str, Any]]:
    """Pooled answer per class, filtered to one grouping/arm/cascade and optionally one region.

    `cities` restricts the pool to a named set, which is what makes two records comparable: pooling
    eleven cities against sixteen and calling the difference a deviation would be measuring the
    city list, not the pipeline.
    """
    selected = [
        r
        for r in rows
        if r.grouping == grouping
        and r.arm == arm
        and r.cascade == cascade
        and r.code in BUILT_CODES
        and (cities is None or r.city in cities)
        and (europe is None or r.europe_or_na is europe)
    ]
    out: dict[int, dict[str, Any]] = {}
    for code in sorted({r.code for r in selected}):
        pooled = pool([r for r in selected if r.code == code])
        if pooled is not None:
            out[code] = pooled
    return out


def verdict(rows: Sequence[ClassRow], *, grouping: str, arm: str, cascade: str) -> dict[str, Any]:
    """Which of the three pre-registered outcomes the numbers land on.

    The rule is fixed before the sweep runs so the outcome is not chosen after seeing it:

    - **inside** — classes holding at least half the built cells reach their range.
    - **worse_in_europe** — Europe and North America trail the rest by at least `REGIONAL_GAP` in
      pooled share, in a majority of the classes both hold.
    - **depressed_uniformly** — otherwise.
    """
    overall = by_class(rows, grouping=grouping, arm=arm, cascade=cascade)
    if not overall:
        return {
            "outcome": None,
            "meaning": "no rows for this grouping — the record carries no table against it",
            "grouping": grouping,
            "arm": arm,
            "cascade": cascade,
        }

    cells = sum(entry["n_cells"] for entry in overall.values())
    reaching = sum(entry["n_cells"] for entry in overall.values() if entry["reaches_range"])
    inside = cells > 0 and reaching / cells >= 0.5

    europe = by_class(rows, grouping=grouping, arm=arm, cascade=cascade, europe=True)
    other = by_class(rows, grouping=grouping, arm=arm, cascade=cascade, europe=False)
    shared = sorted(set(europe) & set(other))
    gaps = {code: europe[code]["share_in_range"] - other[code]["share_in_range"] for code in shared}
    europe_worse = [code for code, gap in gaps.items() if gap <= -REGIONAL_GAP]
    regional = bool(shared) and len(europe_worse) > len(shared) / 2

    if inside:
        outcome = "inside"
        meaning = (
            "BSF reaches the published ranges; the residual is the classifier's boundary "
            "placement, not the parameter."
        )
    elif regional:
        outcome = "worse_in_europe"
        meaning = (
            "Unit definition is the cause. A structural limit of grid-based LCZ mapping, and a "
            "paper result rather than a bug."
        )
    else:
        outcome = "depressed_uniformly"
        meaning = (
            "The published ranges do not transfer to 100 m cells. Report the published-range "
            "result and an empirical recalibration side by side; do not silently recalibrate."
        )

    return {
        "outcome": outcome,
        "meaning": meaning,
        "grouping": grouping,
        "arm": arm,
        "cascade": cascade,
        "share_of_built_cells_in_reaching_classes": (reaching / cells) if cells else None,
        "classes_reaching": [code for code, e in overall.items() if e["reaches_range"]],
        "regional_gap_share": gaps,
        "classes_where_europe_trails": europe_worse,
        "n_shared_classes": len(shared),
    }


def compare_groupings(rows: Sequence[ClassRow], *, arm: str, cascade: str) -> dict[str, Any]:
    """P3: how far apart the two references put the same parameter, class by class."""
    truth = by_class(rows, grouping="so2sat_labels", arm=arm, cascade=cascade)
    v3 = by_class(rows, grouping="lcz_v3", arm=arm, cascade=cascade)
    shared = sorted(set(truth) & set(v3))
    per_class = {
        code: {
            "share_in_range_labels": truth[code]["share_in_range"],
            "share_in_range_lcz_v3": v3[code]["share_in_range"],
            "share_delta": truth[code]["share_in_range"] - v3[code]["share_in_range"],
            "median_labels": truth[code]["mean_of_city_medians"],
            "median_lcz_v3": v3[code]["mean_of_city_medians"],
            "verdict_differs": truth[code]["reaches_range"] != v3[code]["reaches_range"],
        }
        for code in shared
    }
    deltas = [abs(e["share_delta"]) for e in per_class.values()]
    return {
        "per_class": per_class,
        "n_shared_classes": len(shared),
        "mean_abs_share_delta": (sum(deltas) / len(deltas)) if deltas else None,
        "n_classes_where_verdict_differs": sum(
            1 for e in per_class.values() if e["verdict_differs"]
        ),
    }


def harness_stability(rows: Sequence[ClassRow], stored: Path | None) -> dict[str, Any] | None:
    """This run's `lcz_v3` grouping against the stored Phase 11 one, in the Phase 11 style.

    Not an equivalence assertion: Phase 12 bumped `TILE_RESULT_VERSION`, so every city regenerates
    tiles cold and the two runs are not expected to be bit-identical. The deviation is the point.

    Restricted to the cities both records hold. Without that, a partially-complete sweep compares
    its own eleven cities against the stored sixteen and reports the difference between two city
    lists as a pipeline deviation — which it did, at 6.6%, until this was fixed.
    """
    if stored is None or not stored.exists():
        return None
    old = collect(json.loads(stored.read_text(encoding="utf-8")))
    shared_cities = frozenset({r.city for r in rows}) & frozenset({r.city for r in old})
    new_by = by_class(
        rows, grouping="lcz_v3", arm=HEADLINE_ARM, cascade="coarse", cities=shared_cities
    )
    old_by = by_class(
        old, grouping="lcz_v3", arm=HEADLINE_ARM, cascade="coarse", cities=shared_cities
    )
    shared = sorted(set(new_by) & set(old_by))
    deltas = {
        code: new_by[code]["share_in_range"] - old_by[code]["share_in_range"] for code in shared
    }
    return {
        "stored_record": str(stored),
        "n_shared_classes": len(shared),
        "share_in_range_delta": deltas,
        "max_abs_delta": max((abs(d) for d in deltas.values()), default=None),
    }


def analyse(record: dict[str, Any], stored: Path | None = None) -> dict[str, Any]:
    """Everything the phase concludes, from a run record."""
    rows = collect(record)
    analysis: dict[str, Any] = {
        "expectations": EXPECTATIONS,
        "decision_statistic": "pooled share_in_range, area-weighted across cities",
        "reaches_range_threshold": REACHES_RANGE,
        "regional_gap_threshold": REGIONAL_GAP,
        "n_rows": len(rows),
        "groupings_present": sorted({r.grouping for r in rows}),
        "reference_files": sorted({r.reference_file or "none" for r in rows}),
        "by_grouping": {},
    }
    for grouping in GROUPINGS.values():
        analysis["by_grouping"][grouping] = {
            "all_cities": by_class(rows, grouping=grouping, arm=HEADLINE_ARM, cascade="coarse"),
            "europe_and_north_america": by_class(
                rows, grouping=grouping, arm=HEADLINE_ARM, cascade="coarse", europe=True
            ),
            "elsewhere": by_class(
                rows, grouping=grouping, arm=HEADLINE_ARM, cascade="coarse", europe=False
            ),
            "verdict": verdict(rows, grouping=grouping, arm=HEADLINE_ARM, cascade="coarse"),
        }
    analysis["grouping_comparison"] = compare_groupings(rows, arm=HEADLINE_ARM, cascade="coarse")
    analysis["harness_stability"] = harness_stability(rows, stored)
    analysis["headline"] = analysis["by_grouping"]["so2sat_labels"]["verdict"]
    return analysis


def show(analysis: dict[str, Any]) -> None:
    """The tables the written conclusion is built from."""
    for grouping, payload in analysis["by_grouping"].items():
        print(f"\n{'=' * 92}")
        print(f"BSF vs published range — grouped by {grouping.upper()}, arm A, coarse")
        print(f"{'=' * 92}")
        header = (
            f"{'LCZ':4}{'name':22}{'published':>12}{'mean med':>10}"
            f"{'in range':>10}{'gap(w)':>8}{'cities':>7}{'cells':>9}"
        )
        for scope in ("all_cities", "europe_and_north_america", "elsewhere"):
            entries = payload[scope]
            if not entries:
                continue
            print(f"\n  {scope.replace('_', ' ')}")
            print("  " + header)
            for code, e in entries.items():
                lo, hi = e["published_min"], e["published_max"]
                band = f"{lo:.2f}-{hi:.2f}" if lo is not None and hi is not None else "-"
                raw = e["mean_of_city_medians"]
                med = "-" if raw is None else f"{raw:.3f}"
                gap = "-" if e["normalised_gap"] is None else f"{e['normalised_gap']:+.2f}"
                print(
                    f"  {code:<4}{e['name'][:21]:22}{band:>12}{med:>10}"
                    f"{e['share_in_range']:>9.1%}{gap:>8}{e['n_cities']:>7}{e['n_cells']:>9}"
                )
        v = payload["verdict"]
        print(f"\n  OUTCOME: {v['outcome']} — {v['meaning']}")

    cmp = analysis["grouping_comparison"]
    print(f"\n{'=' * 92}\nP3 — do the two references agree? (arm A, coarse)\n{'=' * 92}")
    print(f"{'LCZ':5}{'labels':>10}{'lcz_v3':>10}{'delta':>9}{'verdict differs':>18}")
    for code, e in cmp["per_class"].items():
        print(
            f"{code:<5}{e['share_in_range_labels']:>9.1%}{e['share_in_range_lcz_v3']:>10.1%}"
            f"{e['share_delta']:>+9.1%}{str(e['verdict_differs']):>18}"
        )
    if cmp["mean_abs_share_delta"] is None:
        print("  only one grouping present — no comparison to make")
    else:
        print(
            f"\n  mean |delta| {cmp['mean_abs_share_delta']:.1%} over {cmp['n_shared_classes']} "
            f"classes; the two references disagree on whether the range is reached in "
            f"{cmp['n_classes_where_verdict_differs']} of them"
        )

    stability = analysis.get("harness_stability")
    if stability and stability["max_abs_delta"] is not None:
        print(
            f"\n  harness stability vs stored Phase 11 lcz_v3 table: "
            f"max |delta| {stability['max_abs_delta']:.1%} over "
            f"{stability['n_shared_classes']} classes"
        )

    headline = analysis["headline"]["outcome"]
    print(f"\n  HEADLINE OUTCOME (labels, the primary reference): {headline}")


#: Flags that consume the argument after them, so it is not mistaken for a city key.
VALUED_FLAGS = ("--report", "--stored")


def parse_args(argv: Sequence[str]) -> tuple[list[str], dict[str, Path]]:
    """City keys and valued flags, keeping a flag's value out of the key list.

    Written out rather than reaching for `argparse` because the sibling scripts all parse this way
    and consistency across them is worth more here than the few lines it would save.
    """
    values: dict[str, Path] = {}
    positional: list[str] = []
    skip = False
    for index, token in enumerate(argv):
        if skip:
            skip = False
            continue
        if token in VALUED_FLAGS:
            if index + 1 >= len(argv):
                raise SystemExit(f"{token} needs a path")
            values[token] = Path(argv[index + 1])
            skip = True
        elif not token.startswith("--"):
            positional.append(token)
    return positional, values


def main() -> None:
    requested, values = parse_args(sys.argv[1:])
    stored = values.get("--stored")

    if "--report" in values:
        record = json.loads(values["--report"].read_text(encoding="utf-8"))
        show(analyse(record, stored))
        return

    selected = [c.key for c in CITIES] if not requested else requested
    unknown = [k for k in selected if k not in BY_KEY]
    if unknown:
        raise SystemExit(f"unknown city keys {unknown}")

    settings = Settings.load()
    settings.overture.release = RELEASE
    settings.cleaning = CLEANING.model_copy()

    started = time.time()
    record: dict[str, Any] = {
        "experiment": "phase-13-bsf-published-ranges",
        "run_id": settings.run_id,
        "overture_release": RELEASE,
        "variants": list(VARIANTS),
        "headline_arm": HEADLINE_ARM,
        "expectations": EXPECTATIONS,
        # Transcribed in `docs/references/tables/stewart_oke_2012_properties.md` and read from
        # `prototypes.py`; never reproduced from memory, per CLAUDE.md.
        "published_ranges_source": property_of("building_surface_fraction").source,
        "config": {
            "cleaning": settings.cleaning.model_dump(mode="json"),
            "heights": HEIGHTS.model_dump(mode="json"),
            "height_products": settings.height_products.model_dump(mode="json"),
            "ucp": UCP.model_dump(mode="json"),
            "validation": VALIDATION.model_dump(mode="json"),
            "classification": PrototypeClassifier().describe(),
        },
        "cities": [],
        "skipped": [],
    }
    destination = settings.run_dir / "bsf_published_ranges.json"

    for key in selected:
        try:
            prepared = prepare(BY_KEY[key], settings)
            if prepared is None:
                record["skipped"].append({"city": key, "reason": "screened"})
                results = None
            else:
                results = run_city(
                    key, settings, variants=VARIANTS, diagnostics_on=None, prepared=prepared
                )
        except Exception as error:  # noqa: BLE001 - one city must not end the sweep
            print(f"  {key}: FAILED — {type(error).__name__}: {error}", file=sys.stderr)
            record["skipped"].append({"city": key, "error": f"{type(error).__name__}: {error}"})
            results = None
        if results is not None:
            record["cities"].append(results)
        # Written after every city, so a sweep interrupted at city eight is eight cities of
        # evidence rather than none.
        record["elapsed_s"] = round(time.time() - started, 1)
        destination.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")

    analysis = analyse(record, stored)
    record["analysis"] = analysis
    destination.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
    show(analysis)
    print(f"\nwrote {destination}")


if __name__ == "__main__":
    main()
