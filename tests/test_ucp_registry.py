"""The parameter registry against the blocks that actually produce the columns.

CLAUDE.md's acceptance criterion for Phase 5 is a parameter table where every field is documented
with its unit and its source. That is only true if the registry and the implementation agree, and
the cheapest way for them to disagree is for someone to add a column and forget the entry — which
nothing else in the package would notice.
"""

from __future__ import annotations

import pytest

from lczkit.ucp import buildings, industrial, streets, surface
from lczkit.ucp.registry import (
    COMPUTED_HERE,
    LIMITATIONS,
    NOT_COMPUTED,
    PARAMETER_COLUMNS,
    PARAMETERS,
    UNITS,
    spec,
)

SECONDARY = ("h_mean_area_weighted", "h_std")

_BLOCKS = (buildings.COLUMNS, streets.COLUMNS, surface.COLUMNS, industrial.COLUMNS)


def test_the_registry_and_the_blocks_describe_the_same_columns() -> None:
    produced = {column for block in _BLOCKS for column in block}

    assert produced == set(PARAMETER_COLUMNS)


def test_no_column_is_produced_by_two_blocks() -> None:
    """Two blocks emitting the same name would silently drop one in the `concat`."""
    produced = [column for block in _BLOCKS for column in block]

    assert len(produced) == len(set(produced))


def test_every_parameter_has_a_unit_from_the_controlled_vocabulary() -> None:
    assert {parameter.unit for parameter in PARAMETERS} <= set(UNITS)


def test_every_parameter_has_a_description_and_a_source() -> None:
    """CLAUDE.md's anti-pattern list: never write a parameter without a documented unit and
    source reference. A DOI, or an explicit admission that no publication defines it."""
    for parameter in PARAMETERS:
        assert len(parameter.description) > 40, parameter.name
        assert parameter.reference == COMPUTED_HERE or parameter.reference.startswith("10."), (
            parameter.name
        )


def test_parameter_names_are_unique_and_ordered_as_the_table_is() -> None:
    assert len(set(PARAMETER_COLUMNS)) == len(PARAMETER_COLUMNS)
    assert PARAMETER_COLUMNS == tuple(parameter.name for parameter in PARAMETERS)


def test_spec_looks_up_by_name_and_says_what_exists() -> None:
    assert spec("aspect_ratio").unit == "dimensionless"

    with pytest.raises(KeyError, match="building_surface_fraction"):
        spec("sky_view_factor")


def test_the_two_deferred_properties_are_recorded_rather_than_merely_absent() -> None:
    """Sky view factor and terrain roughness are two of Stewart & Oke's seven morphological
    properties. A consumer needs to know they are missing, not infer it from silence — so the
    omission is data that reaches the manifest, not just prose in the README."""
    deferred = dict(NOT_COMPUTED)

    assert set(deferred) == {"sky_view_factor", "terrain_roughness_class"}
    assert not set(deferred) & set(PARAMETER_COLUMNS)
    for name, reason in deferred.items():
        assert len(reason) > 80, name


def test_the_secondary_height_columns_are_marked_as_such() -> None:
    """`Hr` is the geometric mean and is what Phase 6 classifies on. The area-weighted mean and the
    spread ship alongside it for the deferred roughness work, and reading either as `Hr` would bias
    exactly the heterogeneous units where classification is hardest — so the distinction lives in
    the machine-readable description, not only in a module docstring."""
    for name in SECONDARY:
        assert spec(name).description.startswith("SECONDARY, not for classification.")
    assert "GEOMETRIC" in spec("height_of_roughness_elements_m").description


def test_known_limitations_reach_the_manifest_as_data() -> None:
    """CLAUDE.md requires the Overture heavy/light industry limitation in the field docs *and* the
    manifest. A docstring satisfies the first and not the second."""
    limitations = dict(LIMITATIONS)

    assert "industrial_fraction" in limitations
    assert "warehouse" in limitations["industrial_fraction"]
    assert any(name in key for key in limitations for name in SECONDARY)
    for name, text in limitations.items():
        assert len(text) > 120, name
