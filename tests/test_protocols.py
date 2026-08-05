"""Smoke tests for the pluggable-source protocols.

These protocols have no implementations yet (Phase 0) — the tests only confirm they import
cleanly and expose the method names later phases will implement against.
"""

from __future__ import annotations

from typing import Protocol

from lczkit.protocols import (
    Classifier,
    HeightSource,
    RasterSource,
    SpatialUnitStrategy,
    VectorSource,
)


def test_vector_source_is_a_protocol_with_expected_methods() -> None:
    assert Protocol in VectorSource.__mro__
    assert {"buildings", "streets", "water"} <= set(dir(VectorSource))


def test_height_source_is_a_protocol_with_expected_methods() -> None:
    assert Protocol in HeightSource.__mro__
    assert "fill" in dir(HeightSource)


def test_raster_source_is_a_protocol_with_expected_methods() -> None:
    assert Protocol in RasterSource.__mro__
    assert "fractions" in dir(RasterSource)


def test_spatial_unit_strategy_is_a_protocol_with_expected_methods() -> None:
    assert Protocol in SpatialUnitStrategy.__mro__
    assert "generate" in dir(SpatialUnitStrategy)


def test_classifier_is_a_protocol_with_expected_methods() -> None:
    assert Protocol in Classifier.__mro__
    assert "classify" in dir(Classifier)
