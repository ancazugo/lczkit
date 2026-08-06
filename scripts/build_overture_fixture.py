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

import geopandas as gpd
from shapely.geometry import box

from lczkit.config import Settings
from lczkit.sources.overture import OvertureSource

# Central Berlin (Mitte), ~3x3 km, spanning the Spree river / Museum Island / Alexanderplatz —
# dense historic buildings, complex street junctions, and both waterlines and waterbodies.
BERLIN_FIXTURE_BBOX = (13.3789, 52.5057, 13.4231, 52.5327)

RELEASE = "2026-07-22.0"

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "overture"


def _clip(gdf: gpd.GeoDataFrame, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """Clip polygon geometries to `bbox`, dropping anything that clips away to nothing.

    Applied to `land_use` only. A bbox query returns whole features that merely *intersect* the
    box, and Overture's `protected` land use includes region-scale boundaries — two of them
    grazed the Berlin bbox and carried 355k of the layer's 393k vertices, pushing the committed
    fixture past 8 MB on their own. CLAUDE.md's instruction for an oversized fixture is to clip
    it further rather than move it out of the repo, so that is what this does. The other layers
    are city-scale features that never span more than a few blocks and are left untouched.

    `OvertureSource.land_use()` itself does *not* clip — it returns intersecting features like
    every other layer. This is a property of the fixture, not of the source.
    """
    clipped = gdf.copy()
    clipped["geometry"] = clipped.geometry.intersection(box(*bbox)).make_valid()
    keep = (~clipped.geometry.is_empty) & clipped.geometry.geom_type.isin(
        ["Polygon", "MultiPolygon"]
    )
    return clipped.loc[keep].reset_index(drop=True)


def main() -> None:
    settings = Settings.load()
    settings.overture.release = RELEASE

    source = OvertureSource(settings)
    buildings = source.buildings(BERLIN_FIXTURE_BBOX)
    streets = source.streets(BERLIN_FIXTURE_BBOX)
    rail = source.rail(BERLIN_FIXTURE_BBOX)
    waterlines, waterbodies = source.water(BERLIN_FIXTURE_BBOX)
    land_use = _clip(source.land_use(BERLIN_FIXTURE_BBOX), BERLIN_FIXTURE_BBOX)

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    buildings.to_parquet(FIXTURES_DIR / "buildings.parquet")
    streets.to_parquet(FIXTURES_DIR / "streets.parquet")
    rail.to_parquet(FIXTURES_DIR / "rail.parquet")
    waterlines.to_parquet(FIXTURES_DIR / "waterlines.parquet")
    waterbodies.to_parquet(FIXTURES_DIR / "waterbodies.parquet")
    land_use.to_parquet(FIXTURES_DIR / "land_use.parquet")

    print(f"buildings:   {len(buildings)}")
    print(f"streets:     {len(streets)}")
    print(f"rail:        {len(rail)}")
    print(f"waterlines:  {len(waterlines)}")
    print(f"waterbodies: {len(waterbodies)}")
    print(f"land_use:    {len(land_use)}")
    print(f"wrote fixture layers to {FIXTURES_DIR}")


if __name__ == "__main__":
    main()
