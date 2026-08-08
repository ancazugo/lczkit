"""The three-arm harness: is lczkit's low agreement the spatial unit, or the numerator?

    uv run --active python scripts/unit_scale_experiment.py

Written for Phase 6.5, which rejected the unit-scale hypothesis, and **retained as a permanent
diagnostic** because its control arm is what distinguishes the two questions. Phase 6.6 re-ran it
after fixing what the control found; Phase 6.7 gave it a real reference. All three write-ups are
in `docs/experiments/`.

**Two references, and the distance between them.** Every arm is scored twice where labelled data
exists: against hand-labelled So2Sat LCZ42 polygons, which is the figure that means something, and
against `lcz_v3.tif`, which is a model output with its own error. The agreement *between those two*
is reported as the **ceiling** - the most any run could score against `lcz_v3` - and until Phase 6.7
it was neither measured nor suspected. It is 53.2% on Berlin, i.e. inside the 50-60% band lczkit was
being held to.

CLAUDE.md's original hypothesis was a **scale mismatch**: Stewart & Oke's ranges describe an LCZ
*patch*, a 100 m grid cell carries its share of street, and building surface fraction - which
carries roughly 47% of the distance metric - is therefore depressed. GeoClimate partitions into
street-bounded RSUs precisely because an RSU approximates a patch.

Three arms, on both committed fixtures, entirely offline:

- **A** - compute parameters on 100 m grid cells and classify. What the package does today.
- **B** - compute on enclosures and classify there, then project the labels onto the same 100 m
  grid by majority, for validation only. The RSU analogue, and the hypothesis under test.
- **C** - arm A with **raw Overture footprints** in place of `buildings_area`. A control, not a
  pipeline option and never proposed as one. It exists because A and B alone cannot distinguish
  "the unit is the wrong size" from "the numerator is too small", and CLAUDE.md's acceptance for
  Phase 6.5 asks for a recommendation *with the evidence* for it. It is what found the real cause:
  cleaning was removing a quarter of Berlin's building area, and arm C was 9.1 points ahead of the
  pipeline because of it. **A and C converging is now the regression test** - they should stay
  within noise of each other, and a gap reopening between them means area is being lost again.

The decisive output is not the agreement figure but the **distribution of building surface
fraction per class against the published range**, grouped by the *reference* class. Grouping by the
assigned class instead asks whether the labelling is self-consistent, which it is almost by
construction; grouping by the reference class asks whether the parameter can reach the prototype a
unit of known type should match, which is the question this phase exists to answer.

Writes a JSON record to `output/lczkit/<run_id>/` and prints the tables. Nothing outside that
directory is written and nothing under `input/` is read - the inputs are the committed fixtures.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely import make_valid

from lczkit.classify import PrototypeClassifier
from lczkit.classify.prototypes import ranges_for
from lczkit.cleaning.pipeline import CleanedVectors, clean_vectors
from lczkit.config import (
    CleaningConfig,
    HeightConfig,
    LandCoverConfig,
    Settings,
    UcpConfig,
    ValidationConfig,
)
from lczkit.heights.cascade import fill_heights
from lczkit.heights.inherit import inherit_heights
from lczkit.heights.tiers import build_cascade
from lczkit.landcover.local import LocalRasterSource
from lczkit.protocols import BBox, VectorSource
from lczkit.ucp import compute_parameters
from lczkit.units.aggregate import aggregate
from lczkit.units.enclosures import EnclosureUnits, assemble_barriers
from lczkit.units.grid import GridUnits
from lczkit.validation import agreement, labelled_lcz, parameter_ranges, reference_lcz
from lczkit.validation.ranges import weighted_quantile

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"

#: Same settings the Phase 6 integration tests use, so the arm-A numbers here are the ones already
#: reported rather than a differently-configured near-miss.
CLEANING = CleaningConfig(
    building_max_area_m2=50_000.0,
    building_min_area_m2=20.0,
    building_merge_limit_m2=200.0,
    building_overlap_limit=0.1,
    building_road_buffer_m=4.0,
    building_road_overlap_limit=0.5,
)
HEIGHTS = HeightConfig(overture_height_confidence=0.9, overture_num_floors_confidence=0.6)
LAND_COVER = LandCoverConfig()
UCP = UcpConfig()
VALIDATION = ValidationConfig()

TESTED_PARAMETER = "building_surface_fraction"
"""The parameter the hypothesis is about, and the one carrying ~47% of the built metric."""


@dataclass(frozen=True)
class Fixture:
    """One study area: its extent, a vector source, and the rasters keyed to it.

    `vectors` is a factory rather than a directory so the same harness runs over the committed
    fixtures and over a live `OvertureSource` (see `scripts/berlin_wide_validation.py`) without a
    second copy of `build_arms`.
    """

    name: str
    bbox: BBox
    vectors: Callable[[], VectorSource]
    worldcover: Path
    reference: Path
    """The Demuzere global map, clipped. A comparator, never the primary reference."""

    ground_truth: Path | None = None
    """Hand-labelled LCZ polygons (So2Sat LCZ42), where they exist for this extent. `None` means
    the city is scored against `lcz_v3` alone, and the run says so rather than implying otherwise.
    """


class FixtureVectors:
    """A `VectorSource` over the committed fixture parquet, bbox-filtered.

    Duplicated from `tests/conftest.py` rather than imported: a script under `scripts/` importing
    from the test suite would make the test layout part of the package's runtime surface, and this
    is six lines.
    """

    def __init__(self, directory: Path) -> None:
        self._layers = {
            name: gpd.read_parquet(directory / f"{name}.parquet")
            for name in (
                "buildings",
                "streets",
                "rail",
                "waterlines",
                "waterbodies",
                "land_use",
            )
        }

    def _clip(self, name: str, bbox: BBox) -> gpd.GeoDataFrame:
        minx, miny, maxx, maxy = bbox
        return self._layers[name].cx[minx:maxx, miny:maxy].reset_index(drop=True)

    def buildings(self, bbox: BBox) -> gpd.GeoDataFrame:
        return self._clip("buildings", bbox)

    def streets(self, bbox: BBox) -> gpd.GeoDataFrame:
        return self._clip("streets", bbox)

    def rail(self, bbox: BBox) -> gpd.GeoDataFrame:
        return self._clip("rail", bbox)

    def water(self, bbox: BBox) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
        return self._clip("waterlines", bbox), self._clip("waterbodies", bbox)

    def land_use(self, bbox: BBox) -> gpd.GeoDataFrame:
        return self._clip("land_use", bbox)


FIXTURE_CITIES = (
    Fixture(
        name="berlin",
        bbox=(13.3789, 52.5057, 13.4231, 52.5327),
        vectors=partial(FixtureVectors, FIXTURES / "overture"),
        worldcover=FIXTURES / "landcover" / "worldcover_berlin.tif",
        reference=FIXTURES / "lcz" / "lcz_reference_berlin.tif",
        ground_truth=FIXTURES / "lcz" / "so2sat_berlin.parquet",
    ),
    Fixture(
        name="rotterdam",
        # So2Sat LCZ42 covers 52 cities and Rotterdam is not one of them - Amsterdam is the nearest
        # labelled city, 60 km away. Rotterdam therefore stays on `lcz_v3` with no ceiling of its
        # own, and Berlin's ceiling is the only measured one.
        bbox=(4.3000, 51.8850, 4.3400, 51.9050),
        vectors=partial(FixtureVectors, FIXTURES / "overture_industry"),
        worldcover=FIXTURES / "landcover" / "worldcover_rotterdam.tif",
        reference=FIXTURES / "lcz" / "lcz_reference_rotterdam.tif",
    ),
)


@dataclass(frozen=True)
class Arm:
    """One arm's units, parameters and labels, on whatever unit system it computed in."""

    name: str
    units: gpd.GeoDataFrame
    parameters: pd.DataFrame
    classification: pd.DataFrame
    description: str

    @property
    def area(self) -> pd.Series:
        return self.units.geometry.area

    @property
    def labels(self) -> pd.Series:
        return self.classification["lcz_primary"]


def raw_footprints(source: VectorSource, bbox: BBox, crs: Any) -> gpd.GeoDataFrame:
    """Overture footprints with validity fixed and multipolygons exploded, and nothing else.

    Deliberately *not* the cleaning pipeline: this is arm C's whole point. Geometries are made
    valid and exploded because an invalid or multipart footprint would fail the overlay for
    mechanical reasons unrelated to the question, but no feature is dropped, merged, absorbed or
    trimmed. The result overlaps itself where Overture's conflation left duplicates, so its
    building surface fraction is an *upper* bound rather than a corrected value - which is the
    right shape for a control: it brackets the truth together with arm A rather than replacing it.
    """
    frame = source.buildings(bbox).to_crs(crs)
    frame = frame.set_geometry(gpd.GeoSeries(make_valid(frame.geometry.values), crs=crs))
    frame = frame.explode(index_parts=False)
    return frame[frame.geom_type == "Polygon"].reset_index(drop=True)


def build_arms(fixture: Fixture) -> tuple[list[Arm], CleanedVectors, dict[str, Any]]:
    """Run all three arms on one fixture, returning them with the cleaning provenance."""
    source = fixture.vectors()
    cleaned = clean_vectors(source, fixture.bbox, CLEANING)
    tiers = build_cascade(HEIGHTS, lambda name: FIXTURES / "landcover")

    cleaned_buildings, _ = fill_heights(cleaned.buildings_area, tiers)
    topo_buildings = inherit_heights(cleaned.buildings_topo, cleaned_buildings)
    raw_buildings, _ = fill_heights(raw_footprints(source, fixture.bbox, cleaned.crs), tiers)

    grid = GridUnits().generate(fixture.bbox)
    rail = source.rail(fixture.bbox).to_crs(cleaned.crs)
    barriers = assemble_barriers(cleaned.streets, cleaned.waterbodies, rail=rail)
    enclosures = EnclosureUnits().generate(fixture.bbox, barriers)

    classifier = PrototypeClassifier()

    def arm(name: str, units: gpd.GeoDataFrame, buildings: gpd.GeoDataFrame, why: str) -> Arm:
        fractions = LocalRasterSource(
            LAND_COVER.dataset(UCP.land_cover_dataset), fixture.worldcover
        ).fractions(units)
        parameters = compute_parameters(
            units,
            buildings,
            topo_buildings,
            cleaned.streets,
            cleaned.land_use,
            fractions,
            config=UCP,
            land_cover_config=LAND_COVER,
        )
        return Arm(name, units, parameters, classifier.classify(parameters), why)

    arms = [
        arm("A", grid, cleaned_buildings, "100 m grid, buildings_area (current pipeline)"),
        arm("B", enclosures, cleaned_buildings, "enclosures, buildings_area"),
        arm("C", grid, raw_buildings, "100 m grid, raw Overture footprints (control)"),
    ]
    provenance = {
        "buildings_raw": int(len(raw_buildings)),
        "buildings_area": int(len(cleaned_buildings)),
        "buildings_topo": int(len(topo_buildings)),
        "building_area_raw_m2": float(raw_buildings.geometry.area.sum()),
        "building_area_cleaned_m2": float(cleaned_buildings.geometry.area.sum()),
        "buildings_area_retention": cleaned.report.area_retention("buildings_area"),
        "is_planar_enforced": next(
            (
                step.detail["is_planar_enforced"]
                for step in cleaned.report.steps
                if step.operation == "validate_planarity"
            ),
            None,
        ),
        "cleaning_steps": [step.model_dump() for step in cleaned.report.steps],
    }
    return arms, cleaned, provenance


def project(arm: Arm, grid: gpd.GeoDataFrame) -> pd.Series:
    """An arm's labels on the 100 m grid, so every arm is validated against the same reference.

    Arms computing on the grid already are returned untouched. Arm B goes through
    `aggregate(..., "majority")`, which gives each cell the label of the enclosure covering most
    of it. That is deliberately not "the areally dominant label" - the two differ only when two
    enclosures sharing a label jointly outweigh a third, and the largest-overlap reading is what
    keeps the projection a pure lookup rather than a second classification.
    """
    if arm.units.index.equals(grid.index):
        return arm.labels
    labelled = arm.units[["geometry"]].join(arm.classification[["lcz_primary"]])
    return aggregate(labelled, grid, "majority")["lcz_primary"]


def ground_truth_labels(
    fixture: Fixture, grid: gpd.GeoDataFrame
) -> tuple[pd.DataFrame, dict[str, Any]] | None:
    """The labelled reference on the 100 m grid, with how its patches matched. `None` where the
    city has no labelled coverage."""
    if fixture.ground_truth is None:
        return None
    patches = gpd.read_parquet(fixture.ground_truth)
    labels, match = labelled_lcz(grid, patches)
    return labels, {"file": fixture.ground_truth.name, **vars(match)}


def lcz8_diagnostic(
    fixture: Fixture,
    arms: list[Arm],
    grid_reference: pd.DataFrame,
    buildings: gpd.GeoDataFrame,
) -> dict[str, Any]:
    """Phase 6.7 item 3: why the cells a reference calls LCZ 8 are not classified as LCZ 8.

    `bsf_by_reference_class` already answers the specified question - Rotterdam's median is 0.126
    against a published 0.30-0.50, so **outside** - and arms A and C being numerically identical
    already rules out footprint loss. What is left is separating two readings of "outside", and
    they call for opposite responses:

    - **the 100 m cell is too small to hold the fabric.** A working port is sheds and apron in
      alternation, so cells land near 0 or near 1 and the median says nothing about either. The
      signature is a *bimodal* distribution, and enclosures - whole port basins - recovering the
      published range where cells do not.
    - **the reference is over-assigning LCZ 8 to open ground.** The signature is a distribution
      uniformly low, with the range unreachable at any unit size, and a predicted-class
      distribution dominated by the sparse and paved types.

    The share of cells holding no building at all separates them more sharply than the median: LCZ
    8 is "large low-rise", and a cell of it with zero buildings is not a scale artefact.
    """
    published_min, published_max = ranges_for(8).get(TESTED_PARAMETER, (None, None))
    low, high = published_min or 0.0, published_max or 1.0

    arm_a = next(arm for arm in arms if arm.name == "A")
    grid = arm_a.units
    covered = grid_reference["reference_coverage"] >= VALIDATION.min_reference_coverage
    cells = grid.index[((grid_reference["reference_lcz"] == 8) & covered).fillna(False)]

    hits = gpd.sjoin(buildings[["geometry"]], grid.loc[cells, ["geometry"]], predicate="intersects")
    with_a_building = hits["unit_id"].nunique()

    diagnostic: dict[str, Any] = {
        "n_cells": int(len(cells)),
        "published_min": published_min,
        "published_max": published_max,
        **_bsf_shape(arm_a, cells, low, high),
        "n_buildings_in_cells": int(len(hits)),
        "share_cells_with_no_building": (
            float(1.0 - with_a_building / len(cells)) if len(cells) else None
        ),
        "predicted_class_counts": {
            str(int(code)): int(count)
            for code, count in arm_a.labels.reindex(cells).dropna().value_counts().items()
        },
        "enclosure": None,
    }

    # The same ground measured on enclosures, which asks the scale question directly rather than
    # inferring it from the shape of the grid distribution.
    arm_b = next((arm for arm in arms if arm.name == "B"), None)
    if arm_b is not None:
        native = reference_lcz(arm_b.units, fixture.reference, VALIDATION.reference)
        native_covered = native["reference_coverage"] >= VALIDATION.min_reference_coverage
        eights = arm_b.units.index[((native["reference_lcz"] == 8) & native_covered).fillna(False)]
        unit_area = arm_b.units.loc[eights].geometry.area
        diagnostic["enclosure"] = {
            "n_units": int(len(eights)),
            **_bsf_shape(arm_b, eights, low, high),
            "total_area_m2": float(unit_area.sum()),
            "median_unit_area_m2": float(unit_area.median()) if len(eights) else None,
        }
    return diagnostic


def _bsf_shape(arm: Arm, units: pd.Index, low: float, high: float) -> dict[str, Any]:
    """The distribution of `TESTED_PARAMETER` over `units`, **area-weighted**.

    Area-weighted, like `parameter_ranges` and `agreement`, and for the same reason: on enclosures
    a count-weighted median is a statement about slivers. Rotterdam's enclosures carrying a
    reference class of LCZ 8 have a *median* area of 0.1 ha, so the unweighted median reads 0.000
    while the area-weighted one reads 0.175 — the two answer different questions and only one of
    them is about the port.
    """
    values = arm.parameters[TESTED_PARAMETER].reindex(units).dropna()
    if values.empty:
        return {
            "median": None,
            "deciles": [],
            "share_zero_bsf": None,
            "share_in_published_range": None,
            "share_above_published_min": None,
        }
    weight = arm.area.reindex(values.index).to_numpy(dtype="float64")
    value = values.to_numpy(dtype="float64")
    total = float(weight.sum())

    def share(mask: Any) -> float:
        return float(weight[mask].sum() / total) if total > 0 else 0.0

    return {
        "median": weighted_quantile(value, weight, 0.5),
        "deciles": [
            round(weighted_quantile(value, weight, index / 10) or 0.0, 4) for index in range(11)
        ],
        "share_zero_bsf": share(value <= 0.0),
        "share_in_published_range": share((value >= low) & (value <= high)),
        "share_above_published_min": share(value >= low),
    }


def evaluate(
    fixture: Fixture,
    arms: list[Arm],
    provenance: dict[str, Any],
    buildings: gpd.GeoDataFrame,
) -> dict[str, Any]:
    """Agreement and BSF-versus-published-range for every arm, on one fixture."""
    grid = next(arm.units for arm in arms if arm.name == "A")
    grid_reference = reference_lcz(grid, fixture.reference, VALIDATION.reference)
    grid_area = grid.geometry.area
    truth = ground_truth_labels(fixture, grid)

    results: dict[str, Any] = {
        "fixture": fixture.name,
        "bbox": list(fixture.bbox),
        "reference_file": fixture.reference.name,
        "reference_citation": VALIDATION.reference_citation,
        "n_grid_cells": int(len(grid)),
        "cleaning": provenance,
        "ground_truth": None,
        "reference_ceiling": None,
        "arms": {},
    }
    if truth is not None:
        labels, match = truth
        results["ground_truth"] = {**match, "citation": VALIDATION.ground_truth_citation}
        # The ceiling: `lcz_v3` scored as if it were a run, against the labels. Every figure in
        # `agreement` below is bounded by this one, and until Phase 6.7 nobody knew what it was.
        results["reference_ceiling"] = agreement(
            grid_reference["reference_lcz"],
            labels["reference_lcz"],
            grid_area,
            coverage=labels["reference_coverage"],
            config=VALIDATION,
            reference_file=str(fixture.ground_truth and fixture.ground_truth.name),
        ).model_dump()

    for arm in arms:
        projected = project(arm, grid)
        report = agreement(
            projected,
            grid_reference["reference_lcz"],
            grid_area,
            coverage=grid_reference["reference_coverage"],
            config=VALIDATION,
            reference_file=fixture.reference.name,
        )
        # The range test runs on the arm's *own* units, not the projection: it asks whether the
        # parameter as computed reaches the published range, and projecting first would average
        # that parameter across a unit boundary before testing it.
        native_reference = (
            grid_reference
            if arm.units.index.equals(grid.index)
            else reference_lcz(arm.units, fixture.reference, VALIDATION.reference)
        )
        covered = native_reference["reference_coverage"] >= VALIDATION.min_reference_coverage
        results["arms"][arm.name] = {
            "description": arm.description,
            "n_units": int(len(arm.units)),
            "agreement": report.model_dump(),
            "agreement_ground_truth": (
                agreement(
                    projected,
                    truth[0]["reference_lcz"],
                    grid_area,
                    coverage=truth[0]["reference_coverage"],
                    config=VALIDATION,
                    reference_file=str(fixture.ground_truth and fixture.ground_truth.name),
                ).model_dump()
                if truth is not None
                else None
            ),
            "bsf_by_reference_class": parameter_ranges(
                arm.parameters[TESTED_PARAMETER],
                native_reference["reference_lcz"].where(covered),
                arm.area,
                column=TESTED_PARAMETER,
                grouped_by="reference",
            ).model_dump(),
            "bsf_by_assigned_class": parameter_ranges(
                arm.parameters[TESTED_PARAMETER],
                arm.labels,
                arm.area,
                column=TESTED_PARAMETER,
                grouped_by="assigned",
            ).model_dump(),
        }
    results["lcz8"] = lcz8_diagnostic(fixture, arms, grid_reference, buildings)
    return results


def show(results: dict[str, Any]) -> None:
    """Print the tables the written comparison is built from."""
    print(f"\n{'=' * 78}\n{results['fixture'].upper()}  ({results['n_grid_cells']} grid cells)")
    clean = results["cleaning"]
    lost = 1.0 - clean["building_area_cleaned_m2"] / clean["building_area_raw_m2"]
    print(
        f"  buildings {clean['buildings_raw']} raw -> {clean['buildings_area']} area layer "
        f"({clean['buildings_topo']} topo); {clean['building_area_raw_m2'] / 1e6:.3f} -> "
        f"{clean['building_area_cleaned_m2'] / 1e6:.3f} km2 ({lost:.1%} of area removed, "
        f"retention {clean['buildings_area_retention']:.2%}); "
        f"planar={clean['is_planar_enforced']}"
    )

    truth = results["ground_truth"]
    if truth is None:
        print("\n  NO LABELLED GROUND TRUTH for this city — every figure below is against")
        print(f"  {results['reference_file']}, which is an estimate with its own unmeasured error.")
    else:
        ceiling = results["reference_ceiling"]
        print(
            f"\n  ground truth: {truth['file']}, {truth['n_units_labelled']} of "
            f"{results['n_grid_cells']} cells labelled from {truth['n_patches']} patches "
            f"({truth['n_centres_ambiguous']} ambiguous, {truth['n_units_multi_label']} split)"
        )
        print(
            f"  CEILING — {results['reference_file']} against those labels: "
            f"{ceiling['overall_agreement']:.1%} over {ceiling['n_compared']} cells "
            f"(built {ceiling['built_agreement']:.1%}, natural share "
            f"{ceiling['natural_share']:.1%}). No run can beat this against that file."
        )

    print(
        f"\n  {'arm':<4} {'units':>7} {'vs truth':>9} {'built':>7} "
        f"{'vs lcz_v3':>10} {'built':>7} {'nat share':>10}   description"
    )
    for name, arm in results["arms"].items():
        report = arm["agreement"]
        gt = arm["agreement_ground_truth"]
        truth_cells = (
            f"{gt['overall_agreement']:>8.1%} {gt['built_agreement']:>7.1%}" if gt else f"{'—':>16}"
        )
        print(
            f"  {name:<4} {arm['n_units']:>7} {truth_cells} "
            f"{report['overall_agreement']:>10.1%} {report['built_agreement']:>7.1%} "
            f"{report['natural_share']:>10.1%}   {arm['description']}"
        )

    print("\n  confusion axes, as a share of all disagreement:")
    for name, arm in results["arms"].items():
        report = arm["agreement"]
        height = sum(entry["share_of_disagreement"] for entry in report["height_axis"])
        compact = sum(entry["share_of_disagreement"] for entry in report["compactness_axis"])
        print(
            f"    {name}: height (1-2-3, 4-5-6) {height:>6.1%}    "
            f"compactness (1-4, 2-5, 3-6) {compact:>6.1%}    "
            f"n_disagree={report['n_disagree']}"
        )

    print(f"\n  {TESTED_PARAMETER} on units of KNOWN reference class")
    print("  (area-weighted median, and the area share inside the published range)")
    header = "".join(f"{f'arm {name}':>20}" for name in results["arms"])
    print(f"  {'ref':>4} {'published':>13}{header}")
    codes = sorted(
        {
            entry["code"]
            for arm in results["arms"].values()
            for entry in arm["bsf_by_reference_class"]["per_class"]
        }
    )
    for code in codes:
        cells = ""
        published = ""
        for arm in results["arms"].values():
            found = [
                entry
                for entry in arm["bsf_by_reference_class"]["per_class"]
                if entry["code"] == code
            ]
            if not found:
                cells += f"{'-':>20}"
                continue
            entry = found[0]
            published = (
                f"{entry['published_min'] or 0:.2f}-{entry['published_max'] or 1:.2f}"
                f"{'' if entry['published_max'] else '+'}"
            )
            cells += f"{entry['median']:>11.3f} ({entry['share_in_range']:>3.0%}) n={entry['n']:<3}"
        print(f"  {code:>4} {published:>13}{cells}")

    show_lcz8(results["lcz8"])


def show_lcz8(diagnostic: dict[str, Any]) -> None:
    """The LCZ 8 measurement, printed so the two readings of "outside the range" are separable."""
    if not diagnostic["n_cells"]:
        print("\n  LCZ 8: the reference assigns no cell to it here.")
        return

    low, high = diagnostic["published_min"], diagnostic["published_max"]
    print(
        f"\n  LCZ 8 on {diagnostic['n_cells']} cells the reference calls LCZ 8 "
        f"(published {low:.2f}-{high:.2f}):"
    )
    print(
        f"    median {diagnostic['median']:.3f}   "
        f"in range {diagnostic['share_in_published_range']:.1%}   "
        f"at or above {low:.2f} {diagnostic['share_above_published_min']:.1%}"
    )
    print(
        f"    zero BSF {diagnostic['share_zero_bsf']:.1%} of cells; "
        f"{diagnostic['share_cells_with_no_building']:.1%} hold no building at all "
        f"({diagnostic['n_buildings_in_cells']} footprints across them)"
    )
    print(f"    deciles {diagnostic['deciles']}")
    enclosure = diagnostic["enclosure"]
    if enclosure and enclosure["median"] is not None:
        print(
            f"    on enclosures ({enclosure['n_units']} units, median "
            f"{enclosure['median_unit_area_m2'] / 1e4:.2f} ha, total "
            f"{enclosure['total_area_m2'] / 1e6:.2f} km2): median "
            f"{enclosure['median']:.3f}, in range {enclosure['share_in_published_range']:.1%}, "
            f"at or above {low:.2f} {enclosure['share_above_published_min']:.1%}"
        )
    print(f"    lczkit predicted: {diagnostic['predicted_class_counts']}")


def main() -> None:
    settings = Settings.load()
    started = time.time()
    record: dict[str, Any] = {
        "experiment": "phase-6.7-instrument-diagnostics",
        "run_id": settings.run_id,
        "config": {
            "cleaning": CLEANING.model_dump(mode="json"),
            "heights": HEIGHTS.model_dump(mode="json"),
            "ucp": UCP.model_dump(mode="json"),
            "validation": VALIDATION.model_dump(mode="json"),
            "classification": PrototypeClassifier().describe(),
        },
        "fixtures": [],
    }
    for fixture in FIXTURE_CITIES:
        print(f"running {fixture.name}...", file=sys.stderr, flush=True)
        arms, cleaned, provenance = build_arms(fixture)
        results = evaluate(fixture, arms, provenance, cleaned.buildings_area)
        record["fixtures"].append(results)
        show(results)

    record["elapsed_s"] = round(time.time() - started, 1)
    destination = settings.run_dir / "unit_scale_experiment.json"
    destination.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nwrote {destination}")


if __name__ == "__main__":
    main()
