"""The packaged prototype table against the committed markdown it was transcribed from.

This is the most important test in the package. CLAUDE.md names Stewart & Oke (2012) as the most
important document in the repo and singles out reproducing one of its numbers from memory as the
worst failure mode lczkit has — nothing would crash, the map would just be quietly wrong. The
transcription has to ship in the wheel, so it cannot read `docs/` at import time; this test is what
stops the two copies drifting.
"""

from __future__ import annotations

import pytest
import reference_tables as rt

from lczkit.classify.labels import BUILT_CODES, LCZ_CLASSES, NATURAL_CODES, code_of, lcz
from lczkit.classify.prototypes import (
    _RANGES,
    DEFAULT_DOMINANT_FRACTION,
    DEFAULT_NEGLIGIBLE_FRACTION,
    DIMENSIONS,
    LCZKIT,
    PROPERTIES,
    PROTOTYPES,
    STEWART_OKE_2012,
    UNUSED_PROPERTIES,
    _natural_cover,
    build_prototypes,
    property_of,
    ranges_for,
)
from lczkit.ucp import PARAMETER_COLUMNS


def test_the_published_ranges_match_the_committed_table_cell_for_cell() -> None:
    assert _RANGES == rt.stewart_oke_ranges()


def test_the_lczkit_ranges_match_their_committed_table_too() -> None:
    """The tree and water ranges are not Stewart & Oke's, and are transcribed from a table that
    says so at length. They get the same treatment: the defaults are checked against the file."""
    generated = _natural_cover(DEFAULT_DOMINANT_FRACTION, DEFAULT_NEGLIGIBLE_FRACTION)

    assert generated == rt.lczkit_natural_ranges()


def test_every_dimension_is_a_real_phase_5_parameter_column() -> None:
    """A prototype dimension naming a column Phase 5 does not emit would silently never match."""
    assert set(DIMENSIONS) <= set(PARAMETER_COLUMNS)


def test_percentages_are_converted_and_metres_are_not() -> None:
    """The table is in percent for the three surface fractions and metres for height; the
    parameter columns are fractions and metres. The conversion lives in one place, so it is worth
    pinning one value on each side of it."""
    lcz1 = ranges_for(code_of("1"))

    assert lcz1["building_surface_fraction"] == (0.40, 0.60)
    assert lcz1["height_of_roughness_elements_m"] == (25.0, None)
    assert property_of("building_surface_fraction").scale == 0.01
    assert property_of("height_of_roughness_elements_m").scale == 1.0


def test_an_open_ended_range_stays_open() -> None:
    """Blank cells are unbounded, not zero. LCZ 1 is "25 m and above" and LCZ A "up to 0.4" sky
    view factor; reading either blank as a number would put a hard wall where none exists."""
    assert ranges_for(code_of("1"))["height_of_roughness_elements_m"] == (25.0, None)
    assert ranges_for(code_of("D"))["aspect_ratio"] == (None, 0.1)


def test_lcz_g_has_no_height_range_at_all() -> None:
    """A property of the published table, not an omission here — and the reason the distance
    metric has to treat an unconstrained dimension as unbounded rather than as missing."""
    assert "height_of_roughness_elements_m" not in ranges_for(code_of("G"))


def test_lczkit_ranges_are_tagged_and_constrain_only_the_natural_types() -> None:
    """`source` is what stops an lczkit number being cited as Stewart & Oke's. The built types
    carry no tree or water range at all, so those dimensions never penalise them."""
    lczkit_ranges = [p for p in PROTOTYPES if p.source == LCZKIT]

    assert {p.column for p in lczkit_ranges} == {"tree_fraction", "water_fraction"}
    assert {p.code for p in lczkit_ranges} <= set(NATURAL_CODES)
    assert not {p.code for p in lczkit_ranges} & set(BUILT_CODES)
    assert all(p.source == STEWART_OKE_2012 for p in PROTOTYPES if p not in lczkit_ranges)


def test_building_surface_fraction_is_where_the_family_gate_belongs() -> None:
    """The 10% gate is not invented: every built class starts at or above it and every natural
    class stops at or below it. If this ever fails the gate's default has lost its justification."""
    for code in BUILT_CODES:
        low, _ = ranges_for(code)["building_surface_fraction"]
        assert low is not None and low >= 0.10, lcz(code).name
    for code in NATURAL_CODES:
        _, high = ranges_for(code)["building_surface_fraction"]
        assert high is not None and high <= 0.10, lcz(code).name


def test_the_thresholds_move_the_table_rather_than_contradicting_it() -> None:
    """Config owns the two lczkit numbers, so building with different ones has to produce
    different ranges — otherwise config could only disagree with the prototypes, not change them."""
    moved = {
        (p.code, p.column): (p.lo, p.hi)
        for p in build_prototypes(dominant_fraction=0.8, negligible_fraction=0.05)
        if p.column == "tree_fraction"
    }

    assert moved[(code_of("A"), "tree_fraction")] == (0.8, None)
    assert moved[(code_of("B"), "tree_fraction")] == (0.05, 0.8)


def test_an_incoherent_pair_of_thresholds_is_refused() -> None:
    with pytest.raises(ValueError, match="negligible_fraction"):
        build_prototypes(dominant_fraction=0.1, negligible_fraction=0.5)


def test_the_five_unused_properties_are_recorded_with_a_reason() -> None:
    """Half of Stewart & Oke's ten properties do not reach the distance metric. That is a material
    caveat on every label the package emits, and it belongs in the manifest as data."""
    unused = dict(UNUSED_PROPERTIES)
    computed = {spec.name for spec in PROPERTIES if spec.column is not None}

    assert set(unused) == {spec.name for spec in PROPERTIES if spec.column is None}
    assert not set(unused) & computed
    for name, reason in unused.items():
        assert len(reason) > 100, name


def test_every_class_has_a_prototype_and_every_prototype_a_class() -> None:
    assert {p.code for p in PROTOTYPES} == {entry.code for entry in LCZ_CLASSES}
