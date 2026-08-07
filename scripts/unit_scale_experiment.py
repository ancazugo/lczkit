"""Phase 6.5: does the spatial unit explain lczkit's low agreement?

    uv run --active python scripts/unit_scale_experiment.py

Measured agreement is Berlin 17.7% and Rotterdam 42.5%, against ~55% for GeoClimate's own
OSM-versus-national-database comparison. CLAUDE.md's hypothesis is a **scale mismatch**: Stewart &
Oke's ranges describe an LCZ *patch*, a 100 m grid cell carries its share of street, and building
surface fraction - which carries roughly 47% of the distance metric - is therefore depressed.
GeoClimate partitions into street-bounded RSUs precisely because an RSU approximates a patch.

Three arms, on both committed fixtures, entirely offline:

- **A** - compute parameters on 100 m grid cells and classify. What the package does today.
- **B** - compute on enclosures and classify there, then project the labels onto the same 100 m
  grid by majority, for validation only. The RSU analogue, and the hypothesis under test.
- **C** - arm A with **raw Overture footprints** in place of cleaned ones. A control, not a
  pipeline option and never proposed as one. It exists because A and B alone cannot distinguish
  "the unit is the wrong size" from "the numerator is too small", and CLAUDE.md's acceptance for
  this phase asks for a recommendation *with the evidence* for it. Phase 1 cleaning removes about
  a quarter of the building area, and whether that matters more than the unit is exactly what a
  reader has to be able to check.

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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely import make_valid

from lczkit.classify import PrototypeClassifier
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
from lczkit.heights.tiers import build_cascade
from lczkit.landcover.local import LocalRasterSource
from lczkit.protocols import BBox
from lczkit.ucp import compute_parameters
from lczkit.units.aggregate import aggregate
from lczkit.units.enclosures import EnclosureUnits, assemble_barriers
from lczkit.units.grid import GridUnits
from lczkit.validation import agreement, parameter_ranges, reference_lcz

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"

#: Same settings the Phase 6 integration tests use, so the arm-A numbers here are the ones already
#: reported rather than a differently-configured near-miss.
CLEANING = CleaningConfig(
    building_max_area_m2=50_000.0,
    building_min_area_m2=20.0,
    building_merge_limit_m2=200.0,
    building_overlap_limit=0.1,
)
HEIGHTS = HeightConfig(overture_height_confidence=0.9, overture_num_floors_confidence=0.6)
LAND_COVER = LandCoverConfig()
UCP = UcpConfig()
VALIDATION = ValidationConfig()

TESTED_PARAMETER = "building_surface_fraction"
"""The parameter the hypothesis is about, and the one carrying ~47% of the built metric."""


@dataclass(frozen=True)
class Fixture:
    """One committed city: its extent and the three rasters keyed to it."""

    name: str
    bbox: BBox
    vectors: Path
    worldcover: Path
    reference: Path


FIXTURE_CITIES = (
    Fixture(
        name="berlin",
        bbox=(13.3789, 52.5057, 13.4231, 52.5327),
        vectors=FIXTURES / "overture",
        worldcover=FIXTURES / "landcover" / "worldcover_berlin.tif",
        reference=FIXTURES / "lcz" / "lcz_reference_berlin.tif",
    ),
    Fixture(
        name="rotterdam",
        bbox=(4.3000, 51.8850, 4.3400, 51.9050),
        vectors=FIXTURES / "overture_industry",
        worldcover=FIXTURES / "landcover" / "worldcover_rotterdam.tif",
        reference=FIXTURES / "lcz" / "lcz_reference_rotterdam.tif",
    ),
)


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


def raw_footprints(source: FixtureVectors, bbox: BBox, crs: Any) -> gpd.GeoDataFrame:
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
    source = FixtureVectors(fixture.vectors)
    cleaned = clean_vectors(source, fixture.bbox, CLEANING)
    tiers = build_cascade(HEIGHTS, lambda name: FIXTURES / "landcover")

    cleaned_buildings, _ = fill_heights(cleaned.buildings, tiers)
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
            cleaned.streets,
            cleaned.land_use,
            fractions,
            config=UCP,
            land_cover_config=LAND_COVER,
        )
        return Arm(name, units, parameters, classifier.classify(parameters), why)

    arms = [
        arm("A", grid, cleaned_buildings, "100 m grid, cleaned buildings (current pipeline)"),
        arm("B", enclosures, cleaned_buildings, "enclosures, cleaned buildings"),
        arm("C", grid, raw_buildings, "100 m grid, raw Overture footprints (control)"),
    ]
    provenance = {
        "buildings_raw": int(len(raw_buildings)),
        "buildings_cleaned": int(len(cleaned_buildings)),
        "building_area_raw_m2": float(raw_buildings.geometry.area.sum()),
        "building_area_cleaned_m2": float(cleaned_buildings.geometry.area.sum()),
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


def evaluate(fixture: Fixture, arms: list[Arm], provenance: dict[str, Any]) -> dict[str, Any]:
    """Agreement and BSF-versus-published-range for every arm, on one fixture."""
    grid = next(arm.units for arm in arms if arm.name == "A")
    grid_reference = reference_lcz(grid, fixture.reference, VALIDATION.reference)
    grid_area = grid.geometry.area

    results: dict[str, Any] = {
        "fixture": fixture.name,
        "bbox": list(fixture.bbox),
        "reference_file": fixture.reference.name,
        "n_grid_cells": int(len(grid)),
        "cleaning": provenance,
        "arms": {},
    }
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
    return results


def show(results: dict[str, Any]) -> None:
    """Print the tables the written comparison is built from."""
    print(f"\n{'=' * 78}\n{results['fixture'].upper()}  ({results['n_grid_cells']} grid cells)")
    clean = results["cleaning"]
    lost = 1.0 - clean["building_area_cleaned_m2"] / clean["building_area_raw_m2"]
    print(
        f"  buildings {clean['buildings_raw']} raw -> {clean['buildings_cleaned']} cleaned; "
        f"{clean['building_area_raw_m2'] / 1e6:.3f} -> "
        f"{clean['building_area_cleaned_m2'] / 1e6:.3f} km2 ({lost:.1%} of area removed)"
    )

    print(f"\n  {'arm':<4} {'units':>7} {'agreement':>10} {'compared':>9}   description")
    for name, arm in results["arms"].items():
        report = arm["agreement"]
        print(
            f"  {name:<4} {arm['n_units']:>7} {report['overall_agreement']:>9.1%} "
            f"{report['n_compared']:>9}   {arm['description']}"
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


def main() -> None:
    settings = Settings.load()
    started = time.time()
    record: dict[str, Any] = {
        "experiment": "phase-6.5-unit-scale",
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
        arms, _cleaned, provenance = build_arms(fixture)
        results = evaluate(fixture, arms, provenance)
        record["fixtures"].append(results)
        show(results)

    record["elapsed_s"] = round(time.time() - started, 1)
    destination = settings.run_dir / "unit_scale_experiment.json"
    destination.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nwrote {destination}")


if __name__ == "__main__":
    main()
