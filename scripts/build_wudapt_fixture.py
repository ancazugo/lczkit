"""One-off script: clip the WUDAPT LCZ Generator training areas for each fixture city into
`tests/fixtures/lcz/`.

    uv run --active python scripts/build_wudapt_fixture.py
    uv run --active python scripts/build_wudapt_fixture.py wudapt_hongkong.parquet

CLAUDE.md has named WUDAPT the secondary validation reference since Phase 0 — "and the first if
So2Sat doesn't have sufficient labels for a ROI" — and until Phase 16 no code read it. It is the
only LCZ reference that reaches every city this package has been run on.

Like `build_so2sat_fixture.py` and `build_lcz_reference_fixture.py` this reads from `DATA_DIR`
rather than over HTTPS; the export is already on this system under `input/WUDAPT/`. It is read
only. Nothing under `input/` is created, modified or deleted.

**Geometries are written whole and unfiltered.** `lczkit.validation.wudapt.prepare_wudapt` is what
repairs, gates and de-overlaps them, and a fixture that arrived pre-cleaned would leave every one
of those steps untested. Both windows carry the states that matter: overlapping polygons (Berlin
26 pairs, Hong Kong 236), of which some carry *different* classes (4 and 84), several submissions,
both licences, and — Hong Kong only — two self-intersecting polygons.

`area` is kept in the fixture despite being unusable: it is km² computed in Web Mercator, and
`test_validation_wudapt.py` asserts nothing reads it. A column that is never written down cannot
be asserted against.

Classes 18 and 19 exist in the file (633 polygons globally) and in neither window, so the test for
dropping them constructs the case rather than the fixture carrying a doctored row.

The training areas are contributor-submitted under `CC BY-SA` and `CC BY-NC-SA 4.0` — the second
is **non-commercial**. That constrains the data, not this MIT-licensed package; attribution and
terms are recorded in `tests/fixtures/README.md`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

from lczkit.config import Settings
from lczkit.validation.wudapt import READ_COLUMNS, WUDAPT_SOURCE_DIR_NAME

#: Match BERLIN_FIXTURE_BBOX / HONGKONG_FIXTURE_BBOX in scripts/build_overture_fixture.py and the
#: bboxes in tests/conftest.py.
BERLIN_FIXTURE_BBOX = (13.3789, 52.5057, 13.4231, 52.5327)
HONGKONG_FIXTURE_BBOX = (114.1645, 22.3210, 114.1931, 22.3485)

#: The dated export. Pinned here rather than globbed: contributors keep adding to the LCZ
#: Generator, so "whatever gpkg is in that directory" would silently rebuild the fixture against a
#: different reference. `WudaptConfig.filename` refuses to default for the same reason.
SOURCE_FILENAME = "LCZ-Generator_training_areas_2024-10-01.gpkg"

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "lcz"

TARGETS = {
    "wudapt_berlin.parquet": BERLIN_FIXTURE_BBOX,
    "wudapt_hongkong.parquet": HONGKONG_FIXTURE_BBOX,
}

#: What the loader reads, plus `area` so its uselessness is testable, plus geometry. The export's
#: other 30 columns are 17 per-class F1 scores and submitter names, which a fixture has no use for.
KEEP_COLUMNS = (*READ_COLUMNS, "area", "geometry")


def build(settings: Settings, filename: str, bbox: tuple[float, ...]) -> None:
    source = settings.source_dir(WUDAPT_SOURCE_DIR_NAME) / SOURCE_FILENAME
    if not source.is_file():
        raise FileNotFoundError(
            f"the WUDAPT training areas are not at {source}. Place the LCZ Generator export "
            f"there, or point SOURCE_FILENAME at whichever export you mean to pin."
        )

    polygons = gpd.read_file(source, bbox=bbox, columns=[*KEEP_COLUMNS[:-1]])
    selected = polygons.loc[polygons.intersects(box(*bbox)), list(KEEP_COLUMNS)]
    selected = selected.reset_index(drop=True)

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    destination = FIXTURES_DIR / filename
    selected.to_parquet(destination)

    counts = selected["class"].value_counts().sort_index()
    size_kb = destination.stat().st_size / 1024
    print(f"{filename}: {len(selected)} polygons, crs={selected.crs} ({size_kb:.0f} KB)")
    print(f"  classes: {dict(counts)}")
    print(f"  submissions: {selected['submission_id'].nunique()}")
    print(f"  invalid geometries: {int((~selected.is_valid).sum())}")
    print(f"  licences: {dict(selected['license'].value_counts())}")


def main() -> None:
    settings = Settings.load(create_run_dir=False)
    wanted = set(sys.argv[1:])
    unknown = wanted - set(TARGETS)
    if unknown:
        raise SystemExit(f"unknown outputs {sorted(unknown)}; try one of {sorted(TARGETS)}")
    for filename, bbox in TARGETS.items():
        # Parquet is not byte-stable, so rebuilding a fixture nobody asked about would show up as
        # a diff on a fixture nothing changed about.
        if wanted and filename not in wanted:
            continue
        build(settings, filename, bbox)


if __name__ == "__main__":
    main()
