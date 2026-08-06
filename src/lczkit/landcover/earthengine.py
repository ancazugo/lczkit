"""`EarthEngineSource`: the same land-cover fractions, computed server-side.

Identical interface and identical output schema to `LocalRasterSource`, which is CLAUDE.md's
acceptance criterion for this phase. The two agree because they reduce the *same*
`LandCoverDatasetConfig`: the class mapping is applied here as a server-side `remap()` or
threshold chain built from `ClassIndex`, not written out a second time.

Reaching Earth Engine needs credentials and a billable project (`GEE_PROJECT_NAME` in `.env`), so
every test that makes a live call is marked `network` and skipped by default; CI stays offline.

The chunking, cache key, row placement and histogram normalisation are module-level pure
functions, so the logic that decides whether a live call is *correct* is testable without
credentials — and the live path itself is covered by
`tests/test_landcover_earthengine_live.py`, which checks it against `LocalRasterSource` on the
same units.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from lczkit.config import LandCoverDatasetConfig, Settings
from lczkit.landcover.classify import EXCLUDED, ClassIndex
from lczkit.landcover.table import fractions_table
from lczkit.units import check_units

REDUCER = "frequencyHistogram"
"""The only reducer this backend uses. Named explicitly because it is part of the cache key —
CLAUDE.md keys the Earth Engine cache on `(unit geometries, collection ID, date range, reducer)`.
"""

_UNMAPPED_SENTINEL = -2
"""Class index for a value the configured mapping does not cover, distinct from `EXCLUDED`.

Two sentinels rather than one so that `unmapped_policy="raise"` remains enforceable server-side:
if nodata and unmapped both collapsed to `EXCLUDED`, a histogram could not tell a masked pixel
from a value nobody mapped, and the policy would silently degrade to `"exclude"`.
"""

_MASK_FILL = 0
"""Filler for masked pixels, so the class expression has a concrete value to evaluate over them.

Its value is irrelevant, and deliberately in range: `unmask()` casts its argument into the band's
type, so an "impossible" out-of-range sentinel would clamp back into the valid range and match
nothing. Masked cells are identified from the image's mask instead, and every one of them is
overwritten before the reduction sees it.
"""

ROW_PROPERTY = "lczkit_row"
"""Feature property carrying a unit's row position out to Earth Engine and back.

Earth Engine does not document `reduceRegions` as order-preserving, so results are placed by this
rather than by arrival order. A silently permuted result would attach every unit's land cover to a
different unit, and nothing downstream would notice — every fraction would still sum to 1.0.
"""


def place_by_row(payload: dict[str, Any]) -> list[tuple[int, dict[str, Any] | None]]:
    """`(row, histogram)` pairs from a `reduceRegions` `getInfo()` payload.

    Raises if a feature comes back without its `ROW_PROPERTY`, which would mean Earth Engine
    dropped the property and positional recovery is no longer possible.
    """
    placed: list[tuple[int, dict[str, Any] | None]] = []
    for feature in payload.get("features", []):
        properties = feature.get("properties", {})
        if ROW_PROPERTY not in properties:
            raise RuntimeError(
                f"Earth Engine returned a feature with no {ROW_PROPERTY!r} property, so its "
                "result cannot be matched back to a unit."
            )
        placed.append((int(properties[ROW_PROPERTY]), properties.get("histogram")))
    return placed


def batched(items: Sequence[int], size: int) -> Iterator[Sequence[int]]:
    """Split `items` into consecutive chunks of at most `size`, preserving order.

    CLAUDE.md: "Chunk units into batches of a few thousand to stay under element-count and payload
    limits." Order is preserved so a batch's results align positionally with its inputs.
    """
    if size < 1:
        raise ValueError(f"batch size must be at least 1, got {size}")
    for start in range(0, len(items), size):
        yield items[start : start + size]


def cache_key(units: gpd.GeoDataFrame, config: LandCoverDatasetConfig) -> str:
    """Stable hash of everything that changes the answer.

    CLAUDE.md's key is `(unit geometries, collection ID, date range, reducer)`. The class mapping
    is folded in as well: without it, editing `value_classes` would return a stale table computed
    under the previous mapping, and nothing would look wrong.

    Geometries are hashed in `unit_id` order, so the same units in a different row order hit the
    same cache entry.
    """
    ordered = units.sort_index()
    payload = {
        "unit_ids": [str(unit_id) for unit_id in ordered.index],
        "geometries": [geom.wkb_hex if geom is not None else None for geom in ordered.geometry],
        "crs": ordered.crs.to_string() if ordered.crs is not None else None,
        "collection_id": config.gee.collection_id,
        "band": config.gee.band,
        "start_date": config.gee.start_date,
        "end_date": config.gee.end_date,
        "scale_m": config.gee.scale_m,
        "reducer": REDUCER,
        "classes": config.classes,
        "value_classes": config.value_classes,
        "bins": config.bins,
        "bin_classes": config.bin_classes,
        "nodata": config.nodata,
        "nodata_policy": config.nodata_policy,
        "nodata_class": config.nodata_class,
        "unmapped_policy": config.unmapped_policy,
        "unmapped_class": config.unmapped_class,
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def counts_from_histograms(
    histograms: Sequence[dict[str, Any] | None],
    index: pd.Index,
    n_classes: int,
    *,
    dataset_name: str = "",
) -> pd.DataFrame:
    """Earth Engine frequency histograms to the `unit_id` x class-index frame `fractions_table`
    consumes.

    Histogram keys are class indices as strings, values are pixel counts. `EXCLUDED` keys are
    dropped — they are the cells that must not reach the denominator — and an
    `_UNMAPPED_SENTINEL` key raises, which is how `unmapped_policy="raise"` is honoured on a
    server-side reduction.
    """
    counts = np.zeros((len(index), n_classes), dtype="float64")
    for row, histogram in enumerate(histograms):
        for key, value in (histogram or {}).items():
            class_index = int(key)
            if class_index == _UNMAPPED_SENTINEL:
                raise ValueError(
                    f"{dataset_name}: the Earth Engine collection holds values not covered by "
                    "value_classes. Either the configured mapping does not match the asset, or "
                    "extend it — this package will not guess which class an unknown value "
                    "belongs to."
                )
            if class_index == EXCLUDED:
                continue
            counts[row, class_index] = float(value)
    return pd.DataFrame(counts, index=index, columns=pd.Index(range(n_classes)))


class EarthEngineSource:
    """Zonal land-cover fractions for a units layer, computed by Earth Engine."""

    def __init__(
        self,
        config: LandCoverDatasetConfig,
        *,
        project: str | None,
        cache_dir: Path,
        batch_size: int = 2000,
        max_units: int | None = None,
    ) -> None:
        self.config = config
        self.cache_dir = cache_dir
        self.batch_size = batch_size
        self.max_units = max_units
        self._classes = ClassIndex(config)
        self._ee = _import_ee()

        if project is None:
            raise ValueError(
                "No Earth Engine project is set. Put GEE_PROJECT_NAME in .env, or set "
                "`settings.land_cover.gee_project` explicitly."
            )
        gee = config.gee
        missing = [field for field in gee.required_fields() if getattr(gee, field) is None]
        if missing:
            raise ValueError(
                f"Land-cover dataset {config.name!r} has no Earth Engine asset configured "
                f"(missing: {', '.join(missing)}). Set them on "
                f"`settings.land_cover.dataset({config.name!r}).gee`. This package will not guess "
                "an asset ID."
            )
        self.project = project
        self._ee.Initialize(project=project)

    @property
    def name(self) -> str:
        return self.config.name

    @classmethod
    def from_settings(cls, settings: Settings, name: str) -> EarthEngineSource:
        """Build the source for the configured dataset `name`, caching under `input/GEE/`."""
        land_cover = settings.land_cover
        return cls(
            land_cover.dataset(name),
            project=land_cover.gee_project,
            cache_dir=settings.source_dir("GEE"),
            batch_size=land_cover.gee_batch_size,
            max_units=land_cover.gee_max_units,
        )

    def cache_path(self, units: gpd.GeoDataFrame) -> Path:
        return self.cache_dir / f"{self.config.name}_{cache_key(units, self.config)}.parquet"

    def fractions(self, units: gpd.GeoDataFrame) -> pd.DataFrame:
        """Class fractions per `unit_id`, schema-identical to `LocalRasterSource.fractions()`.

        A cached result for these exact units, asset, date range, reducer and class mapping is
        returned without touching Earth Engine — a cache hit is just a file that is already there.
        Cached files are written once and never rewritten; `input/` is shared with other projects.
        """
        check_units(units)
        if units.empty:
            return fractions_table(pd.DataFrame(), self.config, units.index)
        if self.max_units is not None and len(units) > self.max_units:
            raise ValueError(
                f"{len(units)} units exceeds settings.land_cover.gee_max_units "
                f"({self.max_units}). Raise the ceiling or reduce the study area — an unbounded "
                "reduceRegions run is exactly what that setting exists to prevent."
            )

        path = self.cache_path(units)
        if path.exists():
            cached = pd.read_parquet(path)
            return cached.reindex(index=units.index)

        histograms = self._reduce(units)
        result = fractions_table(
            counts_from_histograms(
                histograms,
                units.index,
                len(self._classes.names),
                dataset_name=self.config.name,
            ),
            self.config,
            units.index,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        result.to_parquet(path)
        return result

    def _reduce(self, units: gpd.GeoDataFrame) -> list[dict[str, Any] | None]:
        """One `reduceRegions` call per batch, each followed by a single bounded `getInfo()`.

        Each feature carries its row position out and back in `ROW_PROPERTY`, and results are
        placed by that rather than by arrival order. Earth Engine does not document
        `reduceRegions` as order-preserving, and a silently permuted result would attach every
        unit's land cover to a different unit — wrong everywhere, and wrong in a way no downstream
        check would notice.
        """
        ee = self._ee
        image = self._classified_image()
        # Earth Engine works in WGS84; the reduction's `scale` keeps the sampling grid in metres,
        # so nothing here depends on the units' own projected CRS.
        geographic = gpd.GeoSeries(units.geometry).to_crs("EPSG:4326")

        histograms: list[dict[str, Any] | None] = [None] * len(units)
        seen: set[int] = set()
        for batch in batched(range(len(geographic)), self.batch_size):
            features = [
                ee.Feature(
                    ee.Geometry(geographic.iloc[position].__geo_interface__),
                    {ROW_PROPERTY: position},
                )
                for position in batch
            ]
            reduced = image.reduceRegions(
                collection=ee.FeatureCollection(features),
                reducer=ee.Reducer.frequencyHistogram(),
                scale=self.config.gee.scale_m,
            )
            for row, histogram in place_by_row(reduced.getInfo()):
                if row in seen:
                    raise RuntimeError(f"Earth Engine returned row {row} more than once.")
                seen.add(row)
                histograms[row] = histogram

        if len(seen) != len(units):
            missing = sorted(set(range(len(units))) - seen)[:10]
            raise RuntimeError(
                f"Earth Engine returned {len(seen)} results for {len(units)} units; "
                f"first missing rows: {missing}"
            )
        return histograms

    def _source_image(self) -> Any:
        """The raw single-band image, whichever kind of asset it lives in.

        Both kinds occur among the MVP datasets: ESA WorldCover is a catalogued `ImageCollection`
        to filter and mosaic, while ETH canopy height is a single user-asset `Image`. Loading one
        as the other raises immediately, so `asset_type` declares which it is.
        """
        ee = self._ee
        gee = self.config.gee
        if gee.asset_type == "image":
            return ee.Image(gee.collection_id).select(gee.band)
        return (
            ee.ImageCollection(gee.collection_id)
            .filterDate(gee.start_date, gee.end_date)
            .select(gee.band)
            .mosaic()
        )

    def _classified_image(self) -> Any:
        """The class-index image: the server-side twin of `ClassIndex.apply()`.

        Nodata comes from the image's own mask, not from a sentinel value. `unmask(v)` casts `v`
        into the band's type, so on a uint8 product an out-of-range sentinel silently clamps into
        the valid range and then matches nothing — the mask is the only reliable signal. Masked
        cells are filled with an arbitrary in-range value purely so the class expression has
        something to evaluate over them; every one is overwritten by the final `where`.

        Nodata is applied last but wins, matching `ClassIndex.apply()`, which resolves it first.
        The order matters most for a binned product: ETH canopy height uses 255 over the surfaces
        it masks, and letting that reach the threshold chain would classify every masked cell as
        the tallest bin — turning a mask over built-up land into 100% tree cover.
        """
        ee = self._ee
        config = self.config
        source = self._source_image()
        filled = source.unmask(_MASK_FILL)
        is_nodata = source.mask().Not()
        if config.nodata is not None:
            is_nodata = is_nodata.Or(filled.eq(config.nodata))
        raw = filled

        if config.bins is not None:
            bin_classes = config.bin_classes or []
            classified = ee.Image(self._classes.index_of(bin_classes[0]))
            for threshold, class_name in zip(config.bins, bin_classes[1:], strict=True):
                classified = classified.where(
                    raw.gte(threshold), self._classes.index_of(class_name)
                )
        else:
            from_values, to_indices = self._classes.remap_pairs()
            unmapped = (
                self._classes.index_of(config.unmapped_class)
                if config.unmapped_policy == "assign" and config.unmapped_class is not None
                else EXCLUDED
                if config.unmapped_policy == "exclude"
                else _UNMAPPED_SENTINEL
            )
            classified = raw.remap(from_values, to_indices, unmapped)

        nodata_index = (
            self._classes.index_of(config.nodata_class)
            if config.nodata_policy == "assign" and config.nodata_class is not None
            else EXCLUDED
        )
        return classified.where(is_nodata, nodata_index)


def _import_ee() -> Any:
    try:
        import ee
    except ImportError as error:  # pragma: no cover - only reachable on a broken install
        raise ImportError(
            "EarthEngineSource needs the `earthengine-api` package, which is a declared "
            "dependency of lczkit — its absence means the environment is incomplete rather than "
            "that a feature is switched off."
        ) from error
    return ee
