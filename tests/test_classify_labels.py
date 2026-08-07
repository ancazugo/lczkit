"""LCZ codes, names and colours against the committed table, and against the product itself.

The integer coding and the colour table are an interchange convention: a run that renumbered or
recoloured them would produce output that existing LCZ tooling reads as a different map. So both
are checked against the committed transcription, and the transcription in turn against the GDAL
colormap embedded in the reference raster — which is the artefact it was read from, and is in
`tests/fixtures/` precisely so this stays checkable offline.
"""

from __future__ import annotations

import pytest
import rasterio
import reference_tables as rt
from conftest import LCZ_FIXTURES_DIR

from lczkit.classify.labels import (
    BUILT_CODES,
    CODES,
    HEIGHT_AXIS_PAIRS,
    LCZ_CLASSES,
    NATURAL_CODES,
    NODATA_CODE,
    code_of,
    lcz,
    legend,
)

REFERENCE_RASTER = LCZ_FIXTURES_DIR / "lcz_reference_berlin.tif"


def test_codes_names_and_colours_match_the_committed_table() -> None:
    published = rt.demuzere_classes()

    assert len(published) == len(LCZ_CLASSES)
    for row, entry in zip(published, LCZ_CLASSES, strict=True):
        assert int(row["Code"]) == entry.code
        assert row["LCZ"] == f"LCZ {entry.label}"
        assert row["Class name"] == entry.name
        assert row["Colour"].strip("`") == entry.colour


def test_the_colours_match_the_published_raster_they_were_read_from() -> None:
    """The transcription's provenance, made checkable. CLAUDE.md's rule is to read a Tier 1 table
    rather than recall it; this reads the shipped product rather than a rendering of it."""
    with rasterio.open(REFERENCE_RASTER) as src:
        colormap = src.colormap(1)

    for entry in LCZ_CLASSES:
        red, green, blue, alpha = colormap[entry.code]
        assert f"#{red:02x}{green:02x}{blue:02x}" == entry.colour, entry.name
        assert alpha == 255
    assert colormap[NODATA_CODE][3] == 0


def test_the_families_partition_the_seventeen_classes() -> None:
    assert CODES == tuple(range(1, 18))
    assert BUILT_CODES == tuple(range(1, 11))
    assert NATURAL_CODES == tuple(range(11, 18))
    assert set(BUILT_CODES) | set(NATURAL_CODES) == set(CODES)
    assert not set(BUILT_CODES) & set(NATURAL_CODES)


def test_labels_round_trip_through_codes() -> None:
    for entry in LCZ_CLASSES:
        assert code_of(entry.label) == entry.code
        assert lcz(entry.code).label == entry.label


def test_the_reported_pairs_hold_height_fixed_and_vary_compactness() -> None:
    """The three pairs CLAUDE.md names, checked against what they actually are.

    Each pair shares a height band — "high-rise", "midrise", "low-rise" — and differs in
    compactness. They are a compactness axis, not the height axis the spec's name claims, and a
    reader drawing conclusions about areal height products from a disagreement here would be
    reading the wrong signal. Pinning it in a test keeps the discrepancy visible.
    """
    for compact, open_ in HEIGHT_AXIS_PAIRS:
        assert open_ - compact == 3
        assert lcz(compact).name.startswith("Compact")
        assert lcz(open_).name.startswith("Open")
        assert lcz(compact).name.split()[-1] == lcz(open_).name.split()[-1]


def test_the_legend_is_json_shaped_and_complete() -> None:
    entries = legend()

    assert set(entries) == {str(code) for code in CODES}
    assert entries["10"] == {
        "code": 10,
        "label": "10",
        "name": "Heavy industry",
        "colour": "#555555",
    }


def test_an_unknown_code_or_label_says_what_exists() -> None:
    with pytest.raises(KeyError, match="1-17"):
        lcz(NODATA_CODE)
    with pytest.raises(KeyError, match="labels are"):
        code_of("H")
