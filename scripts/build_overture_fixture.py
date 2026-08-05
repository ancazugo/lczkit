"""One-off script: fetch a real Overture extract for the Phase 1 test fixture city (Berlin)
and write raw copies into `tests/fixtures/overture/`.

Run manually once, or whenever the fixture needs refreshing:

    uv run --active python scripts/build_overture_fixture.py

Not a pytest test — a test that writes into the committed fixture tree as a side effect is
fragile. This also populates the real `Overture_Maps` cache under `DATA_DIR` as a side effect,
which is fine ("a cache hit is just a file that's already there").

`tests/fixtures/` is CLAUDE.md's one explicit exception to "never build a path from `__file__`
or `DATA_DIR`-independence" — fixtures live in the repo precisely so tests don't need
`DATA_DIR` set, so this script's own output path is deliberately `__file__`-relative.
"""

from __future__ import annotations

from pathlib import Path

from lczkit.config import Settings
from lczkit.sources.overture import OvertureSource

# Central Berlin (Mitte), ~3x3 km, spanning the Spree river / Museum Island / Alexanderplatz —
# dense historic buildings, complex street junctions, and both waterlines and waterbodies.
BERLIN_FIXTURE_BBOX = (13.3789, 52.5057, 13.4231, 52.5327)

RELEASE = "2026-07-22.0"

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "overture"


def main() -> None:
    settings = Settings.load()
    settings.overture.release = RELEASE

    source = OvertureSource(settings)
    buildings = source.buildings(BERLIN_FIXTURE_BBOX)
    streets = source.streets(BERLIN_FIXTURE_BBOX)
    waterlines, waterbodies = source.water(BERLIN_FIXTURE_BBOX)

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    buildings.to_parquet(FIXTURES_DIR / "buildings.parquet")
    streets.to_parquet(FIXTURES_DIR / "streets.parquet")
    waterlines.to_parquet(FIXTURES_DIR / "waterlines.parquet")
    waterbodies.to_parquet(FIXTURES_DIR / "waterbodies.parquet")

    print(f"buildings:   {len(buildings)}")
    print(f"streets:     {len(streets)}")
    print(f"waterlines:  {len(waterlines)}")
    print(f"waterbodies: {len(waterbodies)}")
    print(f"wrote fixture layers to {FIXTURES_DIR}")


if __name__ == "__main__":
    main()
