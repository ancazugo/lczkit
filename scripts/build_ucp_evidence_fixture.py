"""One-off script: record the functional evidence columns for each fixture city into
`tests/fixtures/ucp/`.

    uv run --active python scripts/build_ucp_evidence_fixture.py
    uv run --active python scripts/build_ucp_evidence_fixture.py rotterdam

`tests/test_ucp_evidence_equivalence.py` asserts the shipped code reproduces these tables to
1e-9. They were first written from the implementation as it stood *before* `ucp.industrial` and
`ucp.semantics` were rewritten onto `lczkit.units.overlay`, which is what makes them evidence that
the rewrite changed no answer rather than a snapshot of whatever the code does today.

**That is why regenerating them is a separate command and not a `--update` flag on the test.** A
pin that a failing test can refresh is not a pin. Rerun this only when the fixture extracts, the
cleaning thresholds or the parameter definitions genuinely change, and say so in the commit — the
diff is the claim that the numbers were supposed to move.

Writes into `tests/fixtures/`, which CLAUDE.md names as the one exception to everything living
under `DATA_DIR`. Needs no `DATA_DIR`, no network, and nothing under `input/`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))

from conftest import (  # noqa: E402 - reached only after the path insertion above
    FIXTURE_BBOX,
    FIXTURE_CLEANING,
    FIXTURES_DIR,
    HONGKONG_BBOX,
    HONGKONG_FIXTURES_DIR,
    INDUSTRY_BBOX,
    INDUSTRY_FIXTURES_DIR,
    FixtureVectorSource,
)

from lczkit.cleaning.pipeline import clean_vectors  # noqa: E402
from lczkit.config import UcpConfig  # noqa: E402
from lczkit.ucp.buildings import building_metrics  # noqa: E402
from lczkit.ucp.industrial import industrial_metrics  # noqa: E402
from lczkit.ucp.semantics import semantic_metrics  # noqa: E402
from lczkit.units.grid import GridUnits  # noqa: E402

DESTINATION = REPO / "tests" / "fixtures" / "ucp"

CASES = {
    "hongkong": (HONGKONG_FIXTURES_DIR, HONGKONG_BBOX),
    "berlin": (FIXTURES_DIR, FIXTURE_BBOX),
    "rotterdam": (INDUSTRY_FIXTURES_DIR, INDUSTRY_BBOX),
}

SYNTHETIC_HEIGHT_M = 10.0
"""A constant height, matching the test. The evidence columns are area shares and never read it;
`building_metrics` refuses a layer without the column, so something has to be there and a round
number nobody can mistake for a measurement is the right something."""


def build(name: str) -> Path:
    """Write one city's evidence table, returning where it went."""
    directory, bbox = CASES[name]
    cleaned = clean_vectors(FixtureVectorSource(directory), bbox, FIXTURE_CLEANING)
    units = GridUnits(cell_size_m=100.0).generate(bbox, None)
    buildings = cleaned.buildings_area.assign(height=SYNTHETIC_HEIGHT_M)
    config = UcpConfig()

    morphology = building_metrics(buildings, units, config)
    building_area_m2 = morphology["building_surface_fraction"] * units.geometry.area
    table = pd.concat(
        [
            morphology[["building_surface_fraction"]],
            industrial_metrics(
                buildings, cleaned.land_use, units, config, building_area_m2=building_area_m2
            ),
            semantic_metrics(
                buildings, cleaned.land_use, units, config, building_area_m2=building_area_m2
            ),
        ],
        axis=1,
    )
    # Categorical round-trips through parquet as a dictionary type whose category order depends on
    # what occurred, so a city carrying three of the four evidence values would not compare equal
    # to one carrying four. Stored as plain strings; the categorical is asserted elsewhere.
    table["industrial_evidence"] = table["industrial_evidence"].astype("string")

    destination = DESTINATION / f"{name}_evidence.parquet"
    table.to_parquet(destination)
    print(
        f"{name}: {table.shape[0]} units x {table.shape[1]} columns -> "
        f"{destination.relative_to(REPO)} ({destination.stat().st_size / 1024:.1f} KB)"
    )
    return destination


def main() -> None:
    """Rebuild every city's table, or only the ones named on the command line."""
    DESTINATION.mkdir(parents=True, exist_ok=True)
    wanted = sys.argv[1:] or sorted(CASES)
    unknown = [name for name in wanted if name not in CASES]
    if unknown:
        raise SystemExit(f"unknown fixture {', '.join(unknown)}; choose from {sorted(CASES)}")
    for name in wanted:
        build(name)


if __name__ == "__main__":
    main()
