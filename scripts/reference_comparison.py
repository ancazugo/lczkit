"""Phase 16: what the three LCZ references say about each other, over the sixteen study cities.

    uv run --active python scripts/reference_comparison.py --all
    uv run --active python scripts/reference_comparison.py berlin hong_kong

**No pipeline runs here.** This compares references to references — So2Sat labels, WUDAPT training
areas, and `lcz_v3` — on the same 100 m grid and the same 30 km windows every sweep since Phase 9
has used. That makes it minutes rather than the 5-9 hours a sixteen-city pipeline sweep costs, and
it is the right order of work: an instrument is characterised before it is used, which is the
lesson Phase 14 drew from Phase 10 invalidating the evidence that had ordered the levers.

Three questions, and the first has never been asked:

1. **How much do two independent sets of human labels agree with each other?** Every ceiling this
   project has quoted compares a *model* to labels. Nobody measured whether the labels reproduce.
   If two expert label sets disagree about a fifth of the ground, then a fifth of every residual
   this package reports is the references arguing, not lczkit erring — and that is an unquantified
   floor under the 35.3%-against-75.2% gap, exactly like the patch-versus-cell mismatch is.

2. **Does WUDAPT reach where So2Sat does not, and with how much support?** So2Sat covers 51 cities
   in overlapping 320 m squares; WUDAPT covers every city this package has run on, in irregular
   polygons that tile ground rather than sampling it.

3. **How self-consistent is WUDAPT?** It is contributor-drawn over four decades and its polygons
   overlap in disagreeing classes. `prepare_wudapt` has to arbitrate that ground anyway, so the
   contested share is free — and it turns out to predict question 1.

**Two figures are reported that look like ceilings and are not.**

- `wudapt_vs_lcz_v3` is **not independent**: the LCZ Generator's training areas are the training
  data behind the Demuzere global map, so it compares a model against a subset of its own training
  set. It is computed here so that nobody computes it elsewhere and reads it as So2Sat's ceiling's
  equivalent.
- Every agreement is printed beside its **majority-class baseline**, because agreement between two
  label sets is no more comparable across cities than agreement against a map is. Berlin's fixture
  window carries two So2Sat classes and a 77.0% baseline; Hong Kong's carries five and a 37.3% one.
  A raw figure without that beside it repeats the "% of ceiling" mistake in a new place.

Writes a JSON record to `output/lczkit/<run_id>/` and prints the tables. Nothing under `input/` is
written, modified or removed.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from lczkit.cities import BY_KEY, CITIES, City, patches_path, so2sat_window
from lczkit.config import Settings, ValidationConfig
from lczkit.protocols import BBox
from lczkit.units.grid import GridUnits
from lczkit.validation import agreement, labelled_lcz, prepare_wudapt, reference_lcz, wudapt_lcz

sys.path.insert(0, str(Path(__file__).resolve().parent))

from berlin_wide_validation import (  # noqa: E402 - sibling script
    LCZ_SOURCE_DIR_NAME,
    LCZ_SOURCE_FILENAME,
    WUDAPT_SOURCE_DIR_NAME,
    WUDAPT_SOURCE_FILENAME,
    clip_raster,
)

VALIDATION = ValidationConfig()


def _baseline(labels: pd.Series) -> float:
    """Share of the largest class — what a constant predictor would score.

    Printed beside every agreement figure for the reason CLAUDE.md retired "% of ceiling" for: a
    number that is not comparable across cities must not be presented as if it were. Two classes
    and five classes are different problems, and the difference is most of the spread.
    """
    if labels.empty:
        return 0.0
    return float(labels.value_counts(normalize=True).iloc[0])


def _score(
    predicted: pd.Series,
    reference: pd.Series,
    area: pd.Series,
    coverage: pd.Series,
    *,
    reference_file: str,
) -> dict[str, Any]:
    report = agreement(
        predicted,
        reference,
        area,
        coverage=coverage,
        config=VALIDATION,
        reference_file=reference_file,
    )
    usable = (coverage >= VALIDATION.min_reference_coverage) & reference.notna()
    base = _baseline(reference[usable].dropna())
    return {
        **report.model_dump(),
        "majority_class_baseline": base,
        # Agreement expressed on the room left above a constant predictor: 1.0 is perfect, 0.0 is
        # no better than always guessing the commonest class, and negative is worse than that.
        #
        # **Deliberately not called `lift`.** This project already has a `lift`, and it is a
        # different quantity with a different null - `axis_summary`'s pair-normalised lift against
        # a composition-preserving null. Two quantities sharing a name inside one repository is the
        # failure CLAUDE.md records for `CLEANING` and for `industrial_fraction`'s denominator, and
        # it is cheaper to avoid than to document.
        "agreement_above_baseline": (
            (report.overall_agreement - base) / (1.0 - base) if base < 1.0 else 0.0
        ),
        "n_reference_classes": int(reference[usable].dropna().nunique()),
    }


def compare(city: City, settings: Settings) -> dict[str, Any] | None:
    """Every pairwise comparison the references support, for one city's 30 km window."""
    patches_file = patches_path(city, settings)
    if not patches_file.is_file():
        print(f"  {city.key}: no So2Sat patches at {patches_file}", file=sys.stderr)
        return None

    bbox: BBox = so2sat_window(city, settings)
    grid = GridUnits().generate(bbox)
    area = grid.geometry.area

    patches = gpd.read_file(patches_file, bbox=bbox)
    so2sat, so2sat_match = labelled_lcz(grid, patches)

    record: dict[str, Any] = {
        "city": city.key,
        "region": city.region,
        "bbox": list(bbox),
        "n_grid_cells": int(len(grid)),
        "so2sat": {"file": patches_file.name, **vars(so2sat_match)},
        "wudapt": None,
        "wudapt_vs_so2sat": None,
        "lcz_v3_vs_so2sat": None,
        "lcz_v3_vs_wudapt": None,
    }

    source = settings.source_dir(WUDAPT_SOURCE_DIR_NAME) / WUDAPT_SOURCE_FILENAME
    polygons = gpd.read_file(source, bbox=bbox) if source.is_file() else None
    wudapt: pd.DataFrame | None = None
    if polygons is not None and not polygons.empty:
        resolved, selection = prepare_wudapt(polygons, crs=grid.crs, config=VALIDATION.wudapt)
        wudapt, match = wudapt_lcz(grid, resolved)
        drawn = (
            selection.labelled_area_m2 + selection.duplicate_area_m2 + selection.conflict_area_m2
        )
        record["wudapt"] = {
            "file": source.name,
            **vars(selection),
            **vars(match),
            # The contributors' own disagreement rate, as a share of everything they drew. Free,
            # because the resolution has to arbitrate that ground regardless.
            "contested_share_of_drawn": float(selection.conflict_area_m2 / drawn) if drawn else 0.0,
        }
        # **The question nobody had asked.** Two independent sets of human labels, scored against
        # each other on the cells both reach. Restricted to those cells explicitly rather than
        # leaving `agreement` to drop them, so the n is the intersection and is stated as one.
        both = (so2sat["reference_coverage"] >= VALIDATION.min_reference_coverage) & (
            wudapt["reference_coverage"] >= VALIDATION.min_reference_coverage
        )
        record["wudapt_vs_so2sat"] = _score(
            wudapt["reference_lcz"],
            so2sat["reference_lcz"],
            area,
            so2sat["reference_coverage"].where(both, 0.0),
            reference_file=patches_file.name,
        )

    reference_file = settings.source_dir(LCZ_SOURCE_DIR_NAME) / LCZ_SOURCE_FILENAME
    if reference_file.is_file():
        clipped = clip_raster(
            str(reference_file), settings.run_dir / f"lcz_reference_{city.key}.tif", bbox
        )
        lcz_v3 = reference_lcz(grid, clipped, VALIDATION.reference)
        # The real ceiling: a model against hand labels.
        record["lcz_v3_vs_so2sat"] = _score(
            lcz_v3["reference_lcz"],
            so2sat["reference_lcz"],
            area,
            so2sat["reference_coverage"],
            reference_file=patches_file.name,
        )
        if wudapt is not None:
            record["lcz_v3_vs_wudapt"] = {
                "independent": False,
                "why_not": (
                    "WUDAPT LCZ Generator training areas are the training data behind lcz_v3. "
                    "This compares a model against a subset of its own training set, so it is "
                    "inflated by construction and is not a ceiling."
                ),
                **_score(
                    lcz_v3["reference_lcz"],
                    wudapt["reference_lcz"],
                    area,
                    wudapt["reference_coverage"],
                    reference_file=source.name,
                ),
            }
    return record


def show(record: dict[str, Any]) -> None:
    """Print one city's block."""
    print(f"\n{'=' * 92}\n{record['city'].upper()}  ({record['n_grid_cells']} grid cells)")
    so2sat = record["so2sat"]
    print(f"  so2sat : {so2sat['n_units_labelled']:>6} cells from {so2sat['n_patches']} patches")
    wudapt = record["wudapt"]
    if wudapt is None:
        print("  wudapt : none in this window")
    else:
        print(
            f"  wudapt : {wudapt['n_units_labelled']:>6} cells from {wudapt['n_kept']} of "
            f"{wudapt['n_read']} polygons, mean coverage {wudapt['mean_coverage']:.2f}, "
            f"{wudapt['labelled_area_m2'] / 1e6:.1f} km2 drawn"
        )
        print(
            f"           dates {wudapt['date_min']}..{wudapt['date_max']}, QC pass "
            f"{wudapt['qc_pass_fraction']:.0%}, contributors contest "
            f"{wudapt['contested_share_of_drawn']:.2%} of drawn ground"
        )

    print(f"\n  {'comparison':<24} {'n':>7} {'agree':>7} {'built':>7} {'baseline':>9} {'cls':>4}")
    for label, key in (
        ("WUDAPT vs So2Sat", "wudapt_vs_so2sat"),
        ("lcz_v3 vs So2Sat  [CEIL]", "lcz_v3_vs_so2sat"),
        ("lcz_v3 vs WUDAPT  [dep]", "lcz_v3_vs_wudapt"),
    ):
        entry = record.get(key)
        if entry is None:
            print(f"  {label:<24} {'—':>7}")
            continue
        print(
            f"  {label:<24} {entry['n_compared']:>7} {entry['overall_agreement']:>7.1%} "
            f"{entry['built_agreement']:>7.1%} {entry['majority_class_baseline']:>9.1%} "
            f"{entry['n_reference_classes']:>4}"
        )


def summarise(records: list[dict[str, Any]]) -> None:
    """The cross-city table the write-up is built from."""
    usable = [r for r in records if r.get("wudapt_vs_so2sat")]
    if not usable:
        print("\nno city produced a WUDAPT/So2Sat comparison", file=sys.stderr)
        return

    print(f"\n{'=' * 92}\nLABEL REPRODUCIBILITY — two independent human label sets, same ground")
    print(
        f"\n  {'city':<16} {'region':<15} {'n':>6} {'agree':>7} {'base':>7} {'>base':>6} "
        f"{'contest':>8} {'ceiling':>8}"
    )
    rows = []
    for record in sorted(usable, key=lambda r: -r["wudapt_vs_so2sat"]["overall_agreement"]):
        entry = record["wudapt_vs_so2sat"]
        ceiling = record.get("lcz_v3_vs_so2sat")
        rows.append((record, entry, entry["agreement_above_baseline"]))
        print(
            f"  {record['city']:<16} {record['region']:<15} {entry['n_compared']:>6} "
            f"{entry['overall_agreement']:>7.1%} {entry['majority_class_baseline']:>7.1%} "
            f"{entry['agreement_above_baseline']:>6.2f} "
            f"{record['wudapt']['contested_share_of_drawn']:>8.2%} "
            f"{(ceiling['overall_agreement'] if ceiling else float('nan')):>8.1%}"
        )

    agreements = [entry["overall_agreement"] for _, entry, _ in rows]
    contested = [r["wudapt"]["contested_share_of_drawn"] for r, _, _ in rows]
    print(
        f"\n  median agreement {pd.Series(agreements).median():.1%}, "
        f"range {min(agreements):.1%}-{max(agreements):.1%} over {len(rows)} cities"
    )
    if len(rows) > 2:
        print(
            "  corr(contested share, agreement) = "
            f"{pd.Series(contested).corr(pd.Series(agreements)):+.2f}"
        )
    print(
        "\n  Read this as a FLOOR under every residual this package reports: where two expert\n"
        "  label sets disagree, no classifier can agree with both."
    )


def main() -> None:
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if "--list" in flags:
        for city in CITIES:
            print(f"  {city.key:<16} {city.region}")
        return

    keys = [c.key for c in CITIES] if "--all" in flags or not argv else argv
    unknown = [k for k in keys if k not in BY_KEY]
    if unknown:
        raise SystemExit(f"unknown cities {unknown}; try --list")

    settings = Settings.load()
    records: list[dict[str, Any]] = []
    for key in keys:
        started = time.time()
        print(f"comparing {key}...", file=sys.stderr, flush=True)
        record = compare(BY_KEY[key], settings)
        if record is None:
            continue
        record["seconds"] = time.time() - started
        records.append(record)
        show(record)

    summarise(records)
    destination = settings.run_dir / "reference_comparison.json"
    destination.write_text(json.dumps({"cities": records}, indent=2, default=str))
    print(f"\nwrote {destination}", file=sys.stderr)


if __name__ == "__main__":
    main()
