"""One-off script: fetch real Overture extracts for the test fixture cities and write raw copies
into `tests/fixtures/overture*/`.

Run manually once, or whenever a fixture needs refreshing:

    uv run --active python scripts/build_overture_fixture.py
    uv run --active python scripts/build_overture_fixture.py overture_hongkong

Naming a directory rebuilds only that one. Parquet is not byte-stable, so rebuilding a fixture
nobody asked about would show up as a diff on a fixture nothing changed about.

Not a pytest test — a test that writes into the committed fixture tree as a side effect is
fragile. This also populates the real `Overture_Maps` cache under `DATA_DIR` as a side effect,
which is fine ("a cache hit is just a file that's already there").

`tests/fixtures/` is CLAUDE.md's one explicit exception to "never build a path from `__file__`
or `DATA_DIR`-independence" — fixtures live in the repo precisely so tests don't need
`DATA_DIR` set, so this script's own output path is deliberately `__file__`-relative.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

from lczkit.config import Settings
from lczkit.sources.overture import OvertureSource

# Central Berlin (Mitte), ~3x3 km, spanning the Spree river / Museum Island / Alexanderplatz —
# dense historic buildings, complex street junctions, and both waterlines and waterbodies.
BERLIN_FIXTURE_BBOX = (13.3789, 52.5057, 13.4231, 52.5327)

#: Kowloon, ~3x3 km. **The primary fixture from Phase 11**, and Berlin's replacement in that role.
#:
#: Berlin's labelled cells hold LCZ 2 and LCZ 5 — two classes, both mid-rise — so the height
#: confusion axis is near-untestable on it by construction. Phase 6.7 ranked compactness above
#: height as the next lever on exactly that evidence, and the ranking survived three phases until
#: Phase 9 reversed it across fifteen cities. This window holds **LCZ 1, 2, 3, 4 and 5**: compact
#: high, mid and low-rise beside open high and mid-rise, so height (1-2-3, 4-5) and compactness
#: (1-4, 2-5) are both measurable here.
#:
#: Chosen by search rather than by eye: every ~3-4 km window in Hong Kong was scored against the
#: So2Sat patches for classes carrying at least ten patches, under a footprint budget that keeps
#: the committed tree near Berlin's size. Hong Kong's famous thirteen classes are a property of
#: the 30 km validation window — no 3 km window anywhere in the city holds more than six.
HONGKONG_FIXTURE_BBOX = (114.1645, 22.3210, 114.1931, 22.3485)

RELEASE = "2026-07-22.0"

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

#: `fixture directory -> (bbox, layers clipped to it)`.
#:
#: **Which layers are clipped is a property of the fixture, not of the source.** A bbox query
#: returns whole features that merely intersect the box, and every city has some region-scale
#: feature grazing its window: Berlin's are two `protected` land-use boundaries carrying 355k of
#: that layer's 393k vertices, and Hong Kong's is the sea — 19 waterbodies holding 237k vertices
#: and 3.7 MB, 62% of the fixture on their own. CLAUDE.md's instruction for an oversized fixture
#: is to clip it further rather than move it out of the repo.
#:
#: Listed per fixture rather than applied to everything so that rebuilding one reproduces it
#: byte for byte. Clipping Berlin's waterbodies would quietly change a committed fixture that
#: every figure in this project since Phase 1 was measured against, to fix a problem it does not
#: have.
TARGETS = {
    FIXTURES / "overture": (BERLIN_FIXTURE_BBOX, ("land_use",)),
    FIXTURES / "overture_hongkong": (HONGKONG_FIXTURE_BBOX, ("land_use", "waterbodies")),
}


def _clip(gdf: gpd.GeoDataFrame, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """Clip polygon geometries to `bbox`, dropping anything that clips away to nothing.

    Applied to whichever layers `TARGETS` names for a fixture — always `land_use`, and
    `waterbodies` where a city's window touches the sea. See `TARGETS` for why the set is per
    fixture. Layers not named there are city-scale features that never span more than a few
    blocks, and are left untouched.

    `OvertureSource` itself does *not* clip — it returns intersecting features on every layer.
    This is a property of the fixture, not of the source.
    """
    clipped = gdf.copy()
    clipped["geometry"] = clipped.geometry.intersection(box(*bbox)).make_valid()
    keep = (~clipped.geometry.is_empty) & clipped.geometry.geom_type.isin(
        ["Polygon", "MultiPolygon"]
    )
    return clipped.loc[keep].reset_index(drop=True)


def build(
    source: OvertureSource,
    directory: Path,
    bbox: tuple[float, float, float, float],
    clipped: tuple[str, ...],
) -> None:
    waterlines, waterbodies = source.water(bbox)
    layers = {
        "buildings": source.buildings(bbox),
        "streets": source.streets(bbox),
        "rail": source.rail(bbox),
        "waterlines": waterlines,
        "waterbodies": waterbodies,
        "land_use": _clip(source.land_use(bbox), bbox),
    }
    for name in clipped:
        if name != "land_use":  # already clipped above, where it is also filtered
            layers[name] = _clip(layers[name], bbox)

    directory.mkdir(parents=True, exist_ok=True)
    for name, layer in layers.items():
        layer.to_parquet(directory / f"{name}.parquet")
        print(f"{name + ':':13} {len(layer)}{'  (clipped)' if name in clipped else ''}")
    total = sum(path.stat().st_size for path in directory.glob("*.parquet"))
    print(f"wrote fixture layers to {directory} ({total / 1e6:.1f} MB)")


def main() -> None:
    settings = Settings.load()
    settings.overture.release = RELEASE

    wanted = set(sys.argv[1:])
    unknown = wanted - {directory.name for directory in TARGETS}
    if unknown:
        raise SystemExit(f"unknown fixture directories {sorted(unknown)}")

    source = OvertureSource(settings)
    for directory, (bbox, clipped) in TARGETS.items():
        if wanted and directory.name not in wanted:
            continue
        build(source, directory, bbox, clipped)


if __name__ == "__main__":
    main()
