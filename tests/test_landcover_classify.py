"""Tests for the raw-value to class-index mapping and its policies.

Pure numpy, no raster involved — which is the point of `classify.py` existing separately. Nodata
and unmapped handling are the two things most likely to make a land-cover map quietly wrong, so
they are tested where the answer is a small array anyone can check by eye.
"""

from __future__ import annotations

import numpy as np
import pytest

from lczkit.config import LandCoverDatasetConfig
from lczkit.landcover.classify import EXCLUDED, ClassIndex


def _categorical(**overrides: object) -> LandCoverDatasetConfig:
    kwargs: dict[str, object] = {
        "name": "test",
        "source_dir_name": "Test",
        "classes": ["tree", "pervious", "impervious"],
        "value_classes": {10: "tree", 30: "pervious", 50: "impervious"},
    }
    kwargs.update(overrides)
    return LandCoverDatasetConfig(**kwargs)  # type: ignore[arg-type]


def _binned(**overrides: object) -> LandCoverDatasetConfig:
    kwargs: dict[str, object] = {
        "name": "test",
        "source_dir_name": "Test",
        "classes": ["tree", "non_tree"],
        "bins": [3.0],
        "bin_classes": ["non_tree", "tree"],
    }
    kwargs.update(overrides)
    return LandCoverDatasetConfig(**kwargs)  # type: ignore[arg-type]


def test_categorical_values_map_to_their_class_position() -> None:
    index = ClassIndex(_categorical())

    result = index.apply(np.array([10, 30, 50], dtype="uint8"), nodata=None)

    assert result.tolist() == [0, 1, 2]
    assert result.dtype == np.dtype("int16")


def test_binned_values_split_at_the_threshold() -> None:
    """3.0 m is the LCZ scheme's own tree/scrub boundary — LCZ C tops out at 2 m, LCZ A and B
    start at 3 m — so the boundary value itself must count as tree."""
    index = ClassIndex(_binned())

    result = index.apply(np.array([0, 2, 2.99, 3.0, 30], dtype="float32"), nodata=None)

    assert result.tolist() == [1, 1, 1, 0, 0]


def test_nodata_exclude_drops_the_cell_from_the_denominator() -> None:
    index = ClassIndex(_categorical())

    result = index.apply(np.array([10, 0, 50], dtype="uint8"), nodata=0)

    assert result.tolist() == [0, EXCLUDED, 2]


def test_nodata_assign_routes_the_cell_to_a_named_class() -> None:
    """The ETH case. Its 255 masks built-up land rather than marking it unobserved, so those cells
    are non-tree measurements, not absent ones — excluding them reports central Berlin as
    essentially pure canopy."""
    index = ClassIndex(_binned(nodata=255.0, nodata_policy="assign", nodata_class="non_tree"))

    result = index.apply(np.array([255, 10, 255], dtype="uint8"), nodata=255.0)

    assert result.tolist() == [1, 0, 1]


def test_nodata_outranks_a_colliding_class_mapping() -> None:
    """A raster's own declaration that a cell is not a measurement beats a mapping entry that
    happens to use the same number."""
    index = ClassIndex(_categorical())

    result = index.apply(np.array([10, 50], dtype="uint8"), nodata=50)

    assert result.tolist() == [0, EXCLUDED]


def test_nodata_assign_applies_to_a_binned_product_before_the_threshold_chain() -> None:
    """Order matters: 255 is above every threshold, so classifying first would make every masked
    cell the tallest bin."""
    config = _binned(nodata=255.0, nodata_policy="assign", nodata_class="non_tree")

    result = ClassIndex(config).apply(np.array([255], dtype="uint8"), nodata=255.0)

    assert result.tolist() == [ClassIndex(config).index_of("non_tree")]


def test_non_finite_cells_are_excluded_whatever_the_raster_declares() -> None:
    index = ClassIndex(_binned())

    result = index.apply(np.array([np.nan, np.inf, 5.0], dtype="float64"), nodata=None)

    assert result.tolist() == [EXCLUDED, EXCLUDED, 0]


def test_an_unmapped_value_raises_by_default() -> None:
    """Silently dropping or lumping an unmapped value is how a mapping that does not match the
    product on disk produces a plausible-looking wrong map."""
    index = ClassIndex(_categorical())

    with pytest.raises(ValueError, match="not covered by value_classes"):
        index.apply(np.array([10, 99], dtype="uint8"), nodata=None)


def test_an_unmapped_value_can_be_excluded() -> None:
    index = ClassIndex(_categorical(unmapped_policy="exclude"))

    result = index.apply(np.array([10, 99], dtype="uint8"), nodata=None)

    assert result.tolist() == [0, EXCLUDED]


def test_an_unmapped_value_can_be_assigned() -> None:
    index = ClassIndex(_categorical(unmapped_policy="assign", unmapped_class="pervious"))

    result = index.apply(np.array([10, 99], dtype="uint8"), nodata=None)

    assert result.tolist() == [0, 1]


def test_mapping_works_for_a_float_raster_holding_integer_class_codes() -> None:
    index = ClassIndex(_categorical())

    result = index.apply(np.array([[10.0, 30.0], [50.0, 10.0]], dtype="float64"), nodata=None)

    assert result.tolist() == [[0, 1], [2, 0]]


def test_shape_is_preserved() -> None:
    index = ClassIndex(_categorical())

    assert index.apply(np.full((3, 4), 10, dtype="uint8"), nodata=None).shape == (3, 4)


def test_an_empty_array_yields_an_empty_result() -> None:
    index = ClassIndex(_categorical())

    assert index.apply(np.array([], dtype="uint8"), nodata=0).tolist() == []


def test_remap_pairs_are_sorted_and_aligned() -> None:
    """Earth Engine gets the same mapping as the local path, built from the same object rather
    than transcribed a second time."""
    from_values, to_indices = ClassIndex(_categorical()).remap_pairs()

    assert from_values == [10.0, 30.0, 50.0]
    assert to_indices == [0, 1, 2]


def test_remap_pairs_refuses_a_binned_dataset() -> None:
    with pytest.raises(ValueError, match="binned"):
        ClassIndex(_binned()).remap_pairs()
