"""One-off script: clip the So2Sat LCZ42 labelled patches for each fixture city into
`tests/fixtures/lcz/`.

    uv run --active python scripts/build_so2sat_fixture.py
    uv run --active python scripts/build_so2sat_fixture.py so2sat_hongkong.parquet

CLAUDE.md chose Berlin as the Phase 0 fixture city *because* labelled LCZ polygons exist for it,
and until Phase 6.7 validation never used them - it measured against `lcz_v3.tif`, which is an
estimate carrying its own error, and reported the disagreement as lczkit's. These patches are the
primary reference; `lcz_v3` becomes a secondary comparator, and the agreement between the two is
the **ceiling** on what lczkit can score against `lcz_v3`.

Phase 11 added Hong Kong and made it the primary fixture: Berlin's labels here hold two classes,
both mid-rise, so the height confusion axis cannot be tested on it at all.

Like `build_lcz_reference_fixture.py` this reads from `DATA_DIR` rather than over HTTPS - the
dataset is already on this system under `input/So2Sat-LCZ42/`. It is read only. Nothing under
`input/` is created, modified or deleted.

**Geometries are written unclipped.** The reduction in `lczkit.validation.labelled` anchors each
label on its patch *centre*, and clipping a patch at the bbox edge would move that centre. Patches
are kept whole and selected by intersection instead; a patch whose centre falls outside the study
area simply contributes no label.

So2Sat LCZ42 is CC-BY-4.0; attribution is recorded in `tests/fixtures/README.md`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

from lczkit.config import Settings
from lczkit.validation.labelled import LABEL_COLUMN

#: Match BERLIN_FIXTURE_BBOX / HONGKONG_FIXTURE_BBOX in scripts/build_overture_fixture.py and the
#: bboxes in tests/conftest.py.
BERLIN_FIXTURE_BBOX = (13.3789, 52.5057, 13.4231, 52.5327)
HONGKONG_FIXTURE_BBOX = (114.1645, 22.3210, 114.1931, 22.3485)

#: Where the dataset lives under `DATA_DIR/input/`, and which version. Version 4 pairs the
#: culture-10 labels with geolocation, which is what makes the patches usable as polygons at all.
SOURCE_DIR_NAME = "So2Sat-LCZ42"
SOURCE_CITIES = Path("v4") / "cities"

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "lcz"

#: `output filename -> (So2Sat city directory, bbox)`. Hong Kong is the primary fixture from
#: Phase 11 — its labels hold LCZ 1, 2, 3, 4 and 5, so both confusion axes are testable at fixture
#: scale, where Berlin's two mid-rise classes make the height axis untestable by construction.
TARGETS = {
    "so2sat_berlin.parquet": ("Berlin", BERLIN_FIXTURE_BBOX),
    "so2sat_hongkong.parquet": ("Hong_Kong", HONGKONG_FIXTURE_BBOX),
}

KEEP_COLUMNS = ("patch_id", "dataset", LABEL_COLUMN, "geometry")


def build(settings: Settings, filename: str, city: str, bbox: tuple[float, ...]) -> None:
    source = settings.source_dir(SOURCE_DIR_NAME) / SOURCE_CITIES / city
    source = source / f"patches_reference_{city}.gpkg"
    if not source.is_file():
        raise FileNotFoundError(
            f"the So2Sat LCZ42 {city} patches are not at {source}. Place them there, or point "
            "SOURCE_DIR_NAME/SOURCE_CITIES at wherever they live."
        )

    patches = gpd.read_file(source, bbox=bbox)
    selected = patches.loc[patches.intersects(box(*bbox)), list(KEEP_COLUMNS)]
    selected = selected.reset_index(drop=True)

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    destination = FIXTURES_DIR / filename
    selected.to_parquet(destination)

    counts = selected[LABEL_COLUMN].value_counts().sort_index()
    size_kb = destination.stat().st_size / 1024
    print(f"{filename}: {len(selected)} patches, crs={selected.crs} ({size_kb:.0f} KB)")
    print(f"  classes: {dict(counts)}")


def main() -> None:
    settings = Settings.load()
    wanted = set(sys.argv[1:])
    unknown = wanted - set(TARGETS)
    if unknown:
        raise SystemExit(f"unknown outputs {sorted(unknown)}; try one of {sorted(TARGETS)}")
    for filename, (city, bbox) in TARGETS.items():
        # Parquet is not byte-stable, so rebuilding a fixture nobody asked about would show up as
        # a diff on a fixture nothing changed about.
        if wanted and filename not in wanted:
            continue
        build(settings, filename, city, bbox)


if __name__ == "__main__":
    main()
