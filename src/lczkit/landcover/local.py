"""`LocalRasterSource`: land-cover fractions from a COG on disk.

CLAUDE.md's first `RasterSource` implementation, and the one CI tests against — Earth Engine
authentication in CI is not worth the pain, so the offline path is the one that has to be right.

The reduction is `exactextract`, which weights each cell by the exact fraction of it the unit
polygon covers. That is a real improvement over the `all_touched` rasterization Phase 3's height
cascade uses: a 100 m unit against a 10 m product has ~40 boundary cells out of ~100, and counting
each of those as either wholly in or wholly out would be a several-percent error on every unit.

The user supplies the COG; nothing here downloads, and nothing here writes under `input/`.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from exactextract import exact_extract
from exactextract.raster import NumPyRasterSource
from pyproj import CRS

from lczkit.config import LandCoverDatasetConfig, Settings
from lczkit.landcover.classify import EXCLUDED, ClassIndex
from lczkit.landcover.table import fractions_table
from lczkit.raster_window import covering_window
from lczkit.units import check_units


class LocalRasterSource:
    """Zonal land-cover fractions for a units layer, from one local raster."""

    def __init__(
        self,
        config: LandCoverDatasetConfig,
        path: Path,
        *,
        max_raster_cells: int = 200_000_000,
    ) -> None:
        """Bind the source to one raster and the class mapping to read it through.

        `max_raster_cells` caps how much of the raster a single read may pull into memory; it is
        a guard against a units layer whose bounds quietly span a continental product, not a
        tuning knob.
        """
        self.config = config
        self.path = path
        self.max_raster_cells = max_raster_cells
        self._classes = ClassIndex(config)

    @property
    def name(self) -> str:
        """The dataset name, which is what the fraction columns are prefixed with downstream."""
        return self.config.name

    @classmethod
    def from_settings(cls, settings: Settings, name: str) -> LocalRasterSource:
        """Build the source for the configured dataset `name`.

        Raises the same way `build_cascade` does for a height tier: an unset `filename` means the
        product is simply not available and there is nothing to build; a `filename` naming a file
        that is not there is a misconfiguration and says so.
        """
        config = settings.land_cover.dataset(name)
        if config.filename is None:
            raise ValueError(
                f"Land-cover dataset {name!r} has no filename configured, so no local raster "
                f"exists to read. Place the product under "
                f"{settings.source_dir(config.source_dir_name)} and set "
                f"`settings.land_cover.dataset({name!r}).filename`."
            )
        path = settings.source_dir(config.source_dir_name) / config.filename
        if not path.is_file():
            raise FileNotFoundError(
                f"Land-cover dataset {name!r} is configured to read {path}, which does not exist."
            )
        return cls(config, path, max_raster_cells=settings.land_cover.max_raster_cells)

    def fractions(self, units: gpd.GeoDataFrame) -> pd.DataFrame:
        """Class fractions per `unit_id`, one column per class in `config.classes`.

        Fractions sum to 1.0 for every unit with counted cells; units the raster cannot answer for
        — outside its extent, or covering only nodata — come out all-`NaN`.

        Coverage is computed in the *raster's* CRS rather than the units' projected one, because
        `exactextract` does not reproject and warping a categorical raster would resample classes.
        That is safe here specifically because the output is a ratio of coverage within a single
        unit: cell area varies with latitude, but negligibly across the span of one unit, so it
        cancels. It would not be safe if this returned areas.
        """
        check_units(units)
        empty = fractions_table(pd.DataFrame(), self.config, units.index)
        if units.empty:
            return empty

        with rasterio.open(self.path) as src:
            if src.crs is None:
                raise ValueError(f"{self.path} declares no CRS; cannot align it to the units.")
            projected = gpd.GeoSeries(units.geometry).to_crs(CRS.from_user_input(src.crs.to_wkt()))
            # A null or empty unit geometry is not an error — it simply has no coverage, and
            # `exactextract` refuses to parse it — so it is dropped here and reappears as an
            # all-null row when `fractions_table` reindexes back onto `units.index`.
            usable = gpd.GeoSeries(projected.loc[projected.notna() & ~projected.is_empty])
            if usable.empty:
                return empty

            window = covering_window(src, np.asarray(usable.total_bounds))
            if window is None:
                return empty
            cells = int(window.width) * int(window.height)
            if cells > self.max_raster_cells:
                raise ValueError(
                    f"Reading {self.path} over these units needs a {window.width}x{window.height} "
                    f"= {cells:,} cell window, over the {self.max_raster_cells:,} cell limit. "
                    "Raise `settings.land_cover.max_raster_cells` or process fewer units at once."
                )
            values = src.read(self.config.band, window=window)
            nodata = self.config.nodata
            if nodata is None:
                nodata = src.nodatavals[self.config.band - 1]
            bounds = src.window_bounds(window)
            srs_wkt = src.crs.to_wkt()

        indices = self._classes.apply(values, nodata=nodata)
        raster = NumPyRasterSource(indices, *bounds, nodata=EXCLUDED, srs_wkt=srs_wkt)
        extracted = exact_extract(
            raster,
            gpd.GeoDataFrame(geometry=usable),
            ["unique", "frac"],
            output="pandas",
        )
        return fractions_table(
            _counts_from_extract(extracted, usable.index, len(self._classes.names)),
            self.config,
            units.index,
        )


def _counts_from_extract(extracted: pd.DataFrame, index: pd.Index, n_classes: int) -> pd.DataFrame:
    """`unique`/`frac` parallel arrays to a `unit_id` x class-index frame.

    The parallel arrays are read rather than `exactextract`'s per-value `frac_<value>` columns,
    whose naming is not stable across features — a class absent from one unit does not
    necessarily get a placeholder column in that unit's row.

    `frac` already sums to 1.0 per unit over non-nodata cells, so it is passed straight through as
    the count; `fractions_table` renormalising it is a no-op that keeps one code path for both
    backends. A unit with no covered cells yields empty arrays and therefore an all-zero row,
    which `fractions_table` turns into the all-`NaN` row callers see.
    """
    counts = np.zeros((len(index), n_classes), dtype="float64")
    for row, (unique, frac) in enumerate(zip(extracted["unique"], extracted["frac"], strict=True)):
        for class_index, share in zip(np.asarray(unique), np.asarray(frac), strict=True):
            counts[row, int(class_index)] = float(share)
    return pd.DataFrame(counts, index=index, columns=pd.Index(range(n_classes)))
