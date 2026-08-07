"""One-off script: fetch a real Overture extract over an area of genuine heavy industry and
write it into `tests/fixtures/overture_industry/`.

    uv run --active python scripts/build_industry_fixture.py

CLAUDE.md requires a second fixture before the LCZ 8 / LCZ 10 rule can be claimed to work: the
Berlin fixture holds 36 industrial buildings of 6195 and 2 industrial land-use parcels of 1559,
which exercises the plumbing and cannot exercise the discrimination. Synthetic tests establish the
mechanism; only a real fixture establishes that it discriminates.

**Rotterdam** was chosen by measurement rather than by reputation. Counted on the Overture release
pinned below, over comparable extents:

| Candidate | industrial buildings | industrial land-use parcels |
|---|---|---|
| Rotterdam (port) | 258 of 1660 | 8 of 140 |
| Duisburg Bruckhausen | 152 of 7163 | 0 |
| Houston ship channel | 5 of 6291 | 9 |

Duisburg's industrial buildings sit among 7163 residential ones - it is a mixed district, not an
industrial one - and Houston's are barely tagged at all. Rotterdam is the only candidate carrying
both evidence sources, and therefore the only one that exercises the `both` branch of
`industrial_evidence` and the union rule behind `industrial_fraction`.

Within Rotterdam, four windows were counted before this one was picked. Botlek, the petrochemical
half, is the truer LCZ 10 landscape but carries only 33 industrial buildings against 44 parcels;
the Waalhaven basin below carries 258 buildings against 8 parcels. The building evidence is the
scarcer of the two in most cities and the one the rule leans on hardest, so the fixture goes where
the buildings are. Both evidence sources are present either way.

Same structure as `build_overture_fixture.py`, including the land-use clip: a bbox query returns
whole features that merely intersect the box, and a port's industrial parcels are large.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

from lczkit.config import Settings
from lczkit.sources.overture import OvertureSource

#: Rotterdam's Waalhaven and the industrial strip north of it, ~2.7 x 2.2 km: bulk terminals,
#: tank farms, warehousing and workshops around a working port basin. Deliberately close to the
#: Berlin fixture's extent but a quarter of its building count, so the committed parquet stays
#: small - CLAUDE.md's instruction for an oversized fixture is to clip it further rather than move
#: it out of the repo.
ROTTERDAM_FIXTURE_BBOX = (4.3000, 51.8850, 4.3400, 51.9050)

RELEASE = "2026-07-22.0"

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "overture_industry"


def _clip(gdf: gpd.GeoDataFrame, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """Clip polygon geometries to `bbox`, dropping anything that clips away to nothing."""
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
    buildings = source.buildings(ROTTERDAM_FIXTURE_BBOX)
    streets = source.streets(ROTTERDAM_FIXTURE_BBOX)
    rail = source.rail(ROTTERDAM_FIXTURE_BBOX)
    waterlines, waterbodies = source.water(ROTTERDAM_FIXTURE_BBOX)
    land_use = _clip(source.land_use(ROTTERDAM_FIXTURE_BBOX), ROTTERDAM_FIXTURE_BBOX)

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    buildings.to_parquet(FIXTURES_DIR / "buildings.parquet")
    streets.to_parquet(FIXTURES_DIR / "streets.parquet")
    rail.to_parquet(FIXTURES_DIR / "rail.parquet")
    waterlines.to_parquet(FIXTURES_DIR / "waterlines.parquet")
    waterbodies.to_parquet(FIXTURES_DIR / "waterbodies.parquet")
    land_use.to_parquet(FIXTURES_DIR / "land_use.parquet")

    industrial_buildings = int((buildings["class"] == "industrial").sum())
    industrial_parcels = int((land_use["class"] == "industrial").sum())
    print(f"buildings:   {len(buildings)} ({industrial_buildings} industrial)")
    print(f"streets:     {len(streets)}")
    print(f"rail:        {len(rail)}")
    print(f"waterlines:  {len(waterlines)}")
    print(f"waterbodies: {len(waterbodies)}")
    print(f"land_use:    {len(land_use)} ({industrial_parcels} industrial)")
    print(f"wrote fixture layers to {FIXTURES_DIR}")


if __name__ == "__main__":
    main()
