"""Raw raster values to class indices, and the policies that govern the awkward cells.

Pure numpy with no I/O, so nodata and unmapped handling — the two things most likely to make a
land-cover map quietly wrong — are unit-testable without a raster anywhere in sight.

`LocalRasterSource` applies this array-wise. `EarthEngineSource` sends the same mapping to the
server as a `remap()`; `ClassIndex.remap_pairs()` exists so the two are built from one source of
truth rather than being written out twice and drifting.
"""

from __future__ import annotations

import numpy as np

from lczkit.config import LandCoverDatasetConfig

EXCLUDED = -1
"""Class index for a cell that must not count towards a unit's denominator.

Distinct from "unobserved" only in intent: a cell is excluded either because the product made no
observation there, or because the configured policy says so. Both leave the fractions of the
remaining cells summing to 1.0.
"""

INDEX_DTYPE = "int16"
"""Class indices are small and signed — signed because `EXCLUDED` is negative."""


class ClassIndex:
    """The class mapping for one dataset, compiled once and applied per raster window.

    Holds no raster state, so a single instance is safe to reuse across windows and units.
    """

    def __init__(self, config: LandCoverDatasetConfig) -> None:
        self._config = config
        self.names: tuple[str, ...] = tuple(config.classes)
        self._position = {name: index for index, name in enumerate(self.names)}
        self._nodata_index = (
            self._position[config.nodata_class]
            if config.nodata_policy == "assign" and config.nodata_class is not None
            else EXCLUDED
        )
        self._unmapped_index = (
            self._position[config.unmapped_class]
            if config.unmapped_policy == "assign" and config.unmapped_class is not None
            else EXCLUDED
        )

    @property
    def config(self) -> LandCoverDatasetConfig:
        return self._config

    def index_of(self, name: str) -> int:
        """Position of `name` in `names`, i.e. the class index the reducers count."""
        return self._position[name]

    def remap_pairs(self) -> tuple[list[float], list[int]]:
        """`(from_values, to_indices)` for a categorical mapping, for Earth Engine's `remap()`.

        Raises for a binned dataset, which has no finite value list to enumerate — the Earth
        Engine backend expresses those as a threshold chain instead.
        """
        if self._config.value_classes is None:
            raise ValueError(
                f"{self._config.name}: remap_pairs() is only defined for a categorical dataset; "
                "this one is binned."
            )
        items = sorted(self._config.value_classes.items())
        return [float(value) for value, _ in items], [self._position[name] for _, name in items]

    def apply(self, values: np.ndarray, *, nodata: float | None) -> np.ndarray:
        """Map raw raster `values` to class indices, as an `int16` array of the same shape.

        `nodata` is the value the raster declares, already overridden by
        `LandCoverDatasetConfig.nodata` if that is set. Pass `None` when there is none.

        Nodata is resolved before the class mapping, so a nodata value that also appears in
        `value_classes` is treated as nodata. That ordering is deliberate: the raster's own
        declaration of "this cell is not a measurement" outranks a mapping entry that happens to
        collide with the sentinel.
        """
        out = np.full(values.shape, EXCLUDED, dtype=INDEX_DTYPE)
        if values.size == 0:
            return out

        as_float = values.astype("float64", copy=False)
        is_nodata = _matches(as_float, nodata)
        todo = ~is_nodata

        if self._config.bins is not None:
            # np.digitize with right=False returns 0 for v < bins[0], len(bins) for v >= bins[-1],
            # which is exactly the bin_classes ordering: lowest bin first.
            bin_classes = self._config.bin_classes or []
            bin_index = np.digitize(as_float[todo], np.asarray(self._config.bins, dtype="float64"))
            lookup = np.array([self._position[name] for name in bin_classes], dtype=INDEX_DTYPE)
            out[todo] = lookup[bin_index]
        else:
            out[todo] = self._apply_categorical(as_float[todo])

        out[is_nodata] = self._nodata_index
        return out

    def _apply_categorical(self, values: np.ndarray) -> np.ndarray:
        mapping = self._config.value_classes or {}
        known = np.array(sorted(mapping), dtype="float64")
        targets = np.array(
            [self._position[mapping[int(value)]] for value in known], dtype=INDEX_DTYPE
        )

        # searchsorted then verify, rather than a value-range lookup table: it costs one extra
        # comparison per cell and works for any numeric dtype, including a float product whose
        # class codes are stored as 10.0, 20.0 and so on.
        slot = np.searchsorted(known, values)
        slot_clipped = np.clip(slot, 0, max(len(known) - 1, 0))
        matched = (len(known) > 0) & (known[slot_clipped] == values)

        out = np.full(values.shape, self._unmapped_index, dtype=INDEX_DTYPE)
        out[matched] = targets[slot_clipped[matched]]

        if self._config.unmapped_policy == "raise" and not matched.all():
            unexpected = np.unique(values[~matched])
            raise ValueError(
                f"{self._config.name}: raster holds values not covered by value_classes: "
                f"{unexpected[:10].tolist()}"
                f"{' ...' if unexpected.size > 10 else ''}. Either the configured mapping does "
                "not match the product on disk, or extend it — this package will not guess which "
                "class an unknown value belongs to."
            )
        return out


def _matches(values: np.ndarray, sentinel: float | None) -> np.ndarray:
    """Cells equal to `sentinel`, plus any non-finite cell.

    A NaN is never a measurement whatever the product declares, and `values == np.nan` is always
    false, so it needs handling separately from the sentinel comparison.
    """
    invalid: np.ndarray = ~np.isfinite(values)
    if sentinel is None or not np.isfinite(sentinel):
        return invalid
    return np.asarray(invalid | (values == sentinel))
