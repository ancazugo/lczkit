"""Pluggable-source protocols for the lczkit pipeline.

Every stage after spatial-unit generation exchanges data as a `GeoDataFrame` indexed by a
stable string `unit_id` (CLAUDE.md's "unit of exchange" decision). These five protocols are
the seams between the pipeline and its data sources — there is exactly one implementation per
protocol in the MVP; the seam is the point, not the number of implementations.

No implementations live here. Method signatures are inferred from the phase descriptions in
CLAUDE.md and may be refined once each phase actually implements against them.
"""

from __future__ import annotations

from typing import Protocol

import geopandas as gpd
import pandas as pd

BBox = tuple[float, float, float, float]
"""A bounding box as (minx, miny, maxx, maxy) in EPSG:4326."""


class VectorSource(Protocol):
    """Supplies cleaned vector layers for a bounding box.

    Implementations own their cache under `settings.source_dir(<name>)` and must pin any
    upstream release/version explicitly rather than tracking "latest".
    """

    def buildings(self, bbox: BBox) -> gpd.GeoDataFrame:
        """Return building footprints intersecting `bbox`.

        Columns include at least `geometry`, `height` (nullable), `num_floors` (nullable),
        and `sources` (upstream provenance metadata).
        """
        ...

    def streets(self, bbox: BBox) -> gpd.GeoDataFrame:
        """Return road-network segments intersecting `bbox`, as LineStrings."""
        ...

    def water(self, bbox: BBox) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
        """Return `(waterlines, waterbodies)` intersecting `bbox`.

        Waterlines are LineStrings, waterbodies are Polygons.
        """
        ...


class HeightSource(Protocol):
    """One tier of the building-height cascade.

    A cascade runs a sequence of `HeightSource` tiers over the same buildings layer; each
    tier fills `height` only for the rows it can resolve, tagging every row it touches with
    `height_source` (the tier's name) and `height_confidence`.
    """

    def fill(self, buildings: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Return `buildings` with `height`, `height_source`, and `height_confidence`
        populated for every row this tier can resolve.

        Rows this tier cannot resolve are returned unchanged (still nullable) for the next
        tier in the cascade.
        """
        ...


class RasterSource(Protocol):
    """Supplies zonal land-cover fractions keyed by `unit_id` — never raw pixels."""

    def fractions(self, units: gpd.GeoDataFrame) -> pd.DataFrame:
        """Return a table indexed by `unit_id` with one fraction column per land-cover
        class. Fractions must sum to ~1.0 per unit. The class-to-fraction mapping is a
        config value, never hardcoded.
        """
        ...


class SpatialUnitStrategy(Protocol):
    """Partitions a city into the spatial units the rest of the pipeline joins on."""

    def generate(self, bbox: BBox, barriers: gpd.GeoDataFrame | None = None) -> gpd.GeoDataFrame:
        """Return unit polygons indexed by a stable string `unit_id`, covering `bbox`.

        `barriers` (streets, rail, waterbodies, large vegetation patches) constrain
        enclosure-based strategies; grid-based strategies may ignore it.
        """
        ...


class Classifier(Protocol):
    """Classifies spatial units into Local Climate Zones by distance to LCZ prototypes."""

    def classify(self, parameters: pd.DataFrame) -> pd.DataFrame:
        """Return a table indexed by `unit_id` carrying the full 17-way distance vector to
        each LCZ prototype, plus `lcz_primary`, `lcz_secondary`, and `uniqueness`.

        Never collapse to a bare integer label here — that is a downstream convenience
        function, not part of the core classification output.
        """
        ...
