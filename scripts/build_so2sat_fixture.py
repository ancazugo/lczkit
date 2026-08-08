"""One-off script: clip the So2Sat LCZ42 labelled patches for Berlin into `tests/fixtures/lcz/`.

    uv run --active python scripts/build_so2sat_fixture.py

CLAUDE.md chose Berlin as the Phase 0 fixture city *because* labelled LCZ polygons exist for it,
and until Phase 6.7 validation never used them - it measured against `lcz_v3.tif`, which is an
estimate carrying its own error, and reported the disagreement as lczkit's. These patches are the
primary reference; `lcz_v3` becomes a secondary comparator, and the agreement between the two is
the **ceiling** on what lczkit can score against `lcz_v3`.

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

from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

from lczkit.config import Settings
from lczkit.validation.labelled import LABEL_COLUMN

#: Matches BERLIN_FIXTURE_BBOX in scripts/build_overture_fixture.py and FIXTURE_BBOX in
#: tests/conftest.py.
BERLIN_FIXTURE_BBOX = (13.3789, 52.5057, 13.4231, 52.5327)

#: Where the dataset lives under `DATA_DIR/input/`, and which version. Version 4 pairs the
#: culture-10 labels with geolocation, which is what makes the patches usable as polygons at all.
SOURCE_DIR_NAME = "So2Sat-LCZ42"
SOURCE_RELATIVE = Path("v4") / "cities" / "Berlin" / "patches_reference_Berlin.gpkg"

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "lcz"
DESTINATION = FIXTURES_DIR / "so2sat_berlin.parquet"

KEEP_COLUMNS = ("patch_id", "dataset", LABEL_COLUMN, "geometry")


def main() -> None:
    settings = Settings.load()
    source = settings.source_dir(SOURCE_DIR_NAME) / SOURCE_RELATIVE
    if not source.is_file():
        raise FileNotFoundError(
            f"the So2Sat LCZ42 Berlin patches are not at {source}. Place them there, or point "
            "SOURCE_DIR_NAME/SOURCE_RELATIVE at wherever they live."
        )

    patches = gpd.read_file(source, bbox=BERLIN_FIXTURE_BBOX)
    selected = patches.loc[patches.intersects(box(*BERLIN_FIXTURE_BBOX)), list(KEEP_COLUMNS)]
    selected = selected.reset_index(drop=True)

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    selected.to_parquet(DESTINATION)

    counts = selected[LABEL_COLUMN].value_counts().sort_index()
    size_kb = DESTINATION.stat().st_size / 1024
    print(f"{DESTINATION.name}: {len(selected)} patches, crs={selected.crs} ({size_kb:.0f} KB)")
    print(f"  classes: {dict(counts)}")


if __name__ == "__main__":
    main()
