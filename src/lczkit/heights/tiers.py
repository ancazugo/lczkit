"""The tiers of the Phase 3 height cascade.

Two `HeightSource` implementations cover CLAUDE.md's four tiers: `OvertureAttributeTier` is
tier 1, and `ArealRasterTier` is tiers 2, 3 and 4 — Google Open Buildings 2.5D, WSF-3D and
GHS-BUILT-H differ only in which file they read and how its values scale, which is why they are
three configured instances of one class rather than three classes. Adding a fifth areal product
is an entry in `HeightConfig.areal_tiers`, not a new implementation.

Tiers 2-4 are areal products: they assign a *neighbourhood* mean to individual buildings. That
is a categorically weaker measurement than tier 1, and the per-building `height_source` and
per-unit tier fractions exist so the output says so rather than presenting one number as if it
were the other.

Every tier claims only rows no earlier tier tagged, so the cascade order in
`HeightConfig.areal_tiers` is what makes the result correct. Run them through
`lczkit.heights.cascade.fill_heights` rather than calling `fill` by hand.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from lczkit.config import ArealTierConfig, HeightConfig
from lczkit.crs import assert_projected_crs
from lczkit.heights.provenance import height_attribution
from lczkit.heights.raster import zonal_mean
from lczkit.protocols import HeightSource

OVERTURE_HEIGHT = "overture_height"
"""`height_source` tag for a height taken from Overture's own `height` attribute."""

OVERTURE_NUM_FLOORS = "overture_num_floors"
"""`height_source` tag for a height derived from `num_floors x storey_height_m`."""


def numeric_column(buildings: gpd.GeoDataFrame, name: str) -> pd.Series:
    """`buildings[name]` coerced to float, or an all-null float Series if the column is absent.

    Overture's `height` is float and `num_floors` a nullable integer, and either can be missing
    entirely from a non-Overture layer. Every read of both goes through here so that "column
    absent" and "column present but null" behave identically — neither is an error at this
    layer, and a tier that crashed on the first would be the pretence of completeness CLAUDE.md
    warns against.
    """
    if name not in buildings.columns:
        return pd.Series(np.nan, index=buildings.index, dtype="float64")
    return pd.to_numeric(buildings[name], errors="coerce").astype("float64")


def prepare(buildings: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Copy `buildings` with the cascade's three output columns present and correctly typed.

    Idempotent, so a tier run standalone gets the same frame shape the cascade would give it.
    A row is "unresolved" exactly when `height_source` is null — not when `height` is null,
    because tier 1 reads a `height` that is already there and must still tag its provenance.
    """
    out = buildings.copy()
    out["height"] = numeric_column(out, "height")
    if "height_source" not in out.columns:
        out["height_source"] = pd.Series(pd.NA, index=out.index, dtype="object")
    if "height_confidence" not in out.columns:
        out["height_confidence"] = pd.Series(np.nan, index=out.index, dtype="float64")
    return out


def _require_confidence(value: float | None, name: str) -> float:
    if value is None:
        raise ValueError(
            f"settings.heights.{name} is not set. height_confidence is an ordinal ranking of "
            "measurement quality with no published value behind it, so this package will not "
            "invent one — set it explicitly and it is recorded in the run manifest."
        )
    return value


class OvertureAttributeTier:
    """Tier 1: Overture's `height`, else `num_floors x storey_height_m`.

    The strongest tier available, and still not a guarantee of a surveyed measurement — a
    quarter of the tier-1 heights in the Berlin test fixture are Microsoft ML values conflated
    onto OSM footprints (see `lczkit.heights.provenance`). Where Overture attaches its own
    per-building confidence to a height, that real number is written to `height_confidence` in
    preference to the configured one, so the distinction survives into the output.

    The `num_floors` path is a weaker measurement than the `height` path — storey height varies
    regionally and is a real error source — which is why it gets its own `height_source` tag and
    its own confidence rather than being folded into the first.
    """

    def __init__(
        self,
        *,
        storey_height_m: float,
        height_confidence: float | None,
        num_floors_confidence: float | None,
    ) -> None:
        if storey_height_m <= 0:
            raise ValueError(f"storey_height_m must be positive, got {storey_height_m}")
        self.storey_height_m = storey_height_m
        self.height_confidence = _require_confidence(
            height_confidence, "overture_height_confidence"
        )
        self.num_floors_confidence = _require_confidence(
            num_floors_confidence, "overture_num_floors_confidence"
        )

    @property
    def name(self) -> str:
        return "overture"

    @property
    def height_sources(self) -> tuple[str, ...]:
        """Two tags, not one — the `height` and `num_floors` routes are different measurements
        and the output must keep them apart. See the class docstring."""
        return (OVERTURE_HEIGHT, OVERTURE_NUM_FLOORS)

    def fill(self, buildings: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        out = prepare(buildings)
        todo = out["height_source"].isna()

        # A non-positive or non-finite height is not a measurement; clear it so a later tier
        # sees an unresolved row rather than a zero-height building.
        from_height = todo & out["height"].gt(0) & np.isfinite(out["height"])
        out.loc[todo & ~from_height, "height"] = np.nan

        _, overture_confidence = height_attribution(out)
        out.loc[from_height, "height_source"] = OVERTURE_HEIGHT
        out.loc[from_height, "height_confidence"] = (
            overture_confidence.loc[from_height].fillna(self.height_confidence).astype("float64")
        )

        floors = numeric_column(out, "num_floors")
        from_floors = todo & ~from_height & floors.ge(1).fillna(False)
        out.loc[from_floors, "height"] = floors.loc[from_floors] * self.storey_height_m
        out.loc[from_floors, "height_source"] = OVERTURE_NUM_FLOORS
        out.loc[from_floors, "height_confidence"] = self.num_floors_confidence
        return out


class ArealRasterTier:
    """Tiers 2-4: a neighbourhood mean read out of a local height raster.

    One class for Google Open Buildings 2.5D, WSF-3D and GHS-BUILT-H, configured per product
    (`lczkit.config.ArealTierConfig`). Nothing product-specific is hardcoded — band, unit scale,
    nodata and minimum valid height are all config, because none of these products is present on
    the system this was written against and guessing at one is exactly the failure mode that
    produces a quietly wrong map.

    Values at or below `min_height_m` are read as "no built volume in this cell" and left for the
    next tier, rather than written out as a zero-height building.
    """

    def __init__(
        self,
        *,
        name: str,
        path: Path,
        confidence: float | None,
        band: int = 1,
        scale: float = 1.0,
        nodata: float | None = None,
        min_height_m: float = 0.0,
    ) -> None:
        self.name = name
        self.path = path
        self.confidence = _require_confidence(confidence, f"areal_tiers[{name!r}].confidence")
        self.band = band
        self.scale = scale
        self.nodata = nodata
        self.min_height_m = min_height_m

    @property
    def height_sources(self) -> tuple[str, ...]:
        return (self.name,)

    @classmethod
    def from_config(cls, config: ArealTierConfig, path: Path) -> ArealRasterTier:
        return cls(
            name=config.name,
            path=path,
            confidence=config.confidence,
            band=config.band,
            scale=config.scale,
            nodata=config.nodata,
            min_height_m=config.min_height_m,
        )

    def fill(self, buildings: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        out = prepare(buildings)
        assert_projected_crs(out, "buildings")
        todo = out["height_source"].isna()
        if not todo.any():
            return out

        sampled = zonal_mean(
            self.path,
            out.loc[todo].geometry,
            band=self.band,
            nodata=self.nodata,
        )
        heights = sampled * self.scale
        usable = np.isfinite(heights) & (heights > self.min_height_m)
        resolved = out.index[todo][usable]

        out.loc[resolved, "height"] = heights[usable]
        out.loc[resolved, "height_source"] = self.name
        out.loc[resolved, "height_confidence"] = self.confidence
        return out


def build_cascade(config: HeightConfig, source_dir: Callable[[str], Path]) -> list[HeightSource]:
    """Assemble the ordered tier list from config.

    `source_dir` is `Settings.source_dir` in a real run; taking the callable rather than
    `Settings` keeps tests able to point tiers at a temporary directory without `DATA_DIR`.

    An areal tier with no `filename` is skipped — the product is simply not available, and a
    shorter cascade with an honest `height_completeness` beats a failure. A tier that *names* a
    file which is not there raises, because that is a misconfiguration rather than an absence.
    """
    tiers: list[HeightSource] = [
        OvertureAttributeTier(
            storey_height_m=config.storey_height_m,
            height_confidence=config.overture_height_confidence,
            num_floors_confidence=config.overture_num_floors_confidence,
        )
    ]
    seen = {OVERTURE_HEIGHT, OVERTURE_NUM_FLOORS}
    for tier_config in config.areal_tiers:
        if tier_config.name in seen:
            raise ValueError(f"duplicate height tier name: {tier_config.name!r}")
        seen.add(tier_config.name)
        if tier_config.filename is None:
            continue
        path = source_dir(tier_config.source_dir_name) / tier_config.filename
        if not path.is_file():
            raise FileNotFoundError(
                f"Height tier {tier_config.name!r} is configured to read {path}, which does not "
                "exist. Place the product there, or clear its `filename` to skip the tier."
            )
        tiers.append(ArealRasterTier.from_config(tier_config, path))
    return tiers
