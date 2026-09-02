"""`TessellationUnits`: building-level enclosed tessellation cells (ETCs).

Built for `lczkit.morphometrics` (Phase 29), which ports the 2D morphometric attributes of
Majer & Fleischmann (2026) — computed over `momepy.enclosed_tessellation`, not over
`EnclosureUnits`'s coarser street-bounded blocks. This is the "tessellation-based building-level
units" strategy the project's deferred list named since Phase 0.

**Deliberately not exposed via `UnitsConfig.strategy`.** Adding `"tessellation"` there would let
ETCs become the pipeline's main classification unit, coupling a purpose-built morphometrics
strategy to classification and validation — a materially larger scope than what this module
exists for. `TessellationUnits` satisfies `SpatialUnitStrategy` structurally and can be wired in
later if that is asked for deliberately; nothing here assumes it is the only caller.

**Tessellation does not partition `bbox`, unlike `GridUnits`/`EnclosureUnits`.**
`momepy.enclosed_tessellation` assigns a negative index to any tessellation cell with no parent
building (an enclosure interior, or a sliver of one, that never reached the input geometry) —
those rows are dropped here, following Majer & Fleischmann (2026) §Supplementary A, which
excludes cells without a parent building from the morphometric computation entirely. So a road
median or an unbuilt block interior simply has no `unit_id`, which is correct for a strategy
whose whole purpose is per-building 2D shape description, not spatial coverage.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import geopandas as gpd
import momepy
import pandas as pd

from lczkit.crs import assert_projected_crs
from lczkit.protocols import BBox
from lczkit.units.enclosures import EnclosureUnits

DEFAULT_SHRINK = 0.4
DEFAULT_SEGMENT = 0.5
DEFAULT_THRESHOLD = 0.05
"""momepy's own `enclosed_tessellation` defaults, restated as module constants rather than left
implicit in a call site, so a run's manifest can record what actually ran."""


@dataclass(frozen=True)
class TessellationReport:
    """What tessellation produced, for the run manifest.

    A unit strategy that drops rows (unlike `GridUnits`/`EnclosureUnits`, which partition the
    bbox exactly) has to say how many and why, or a city with an unusually sparse building layer
    is indistinguishable from a tessellation bug.
    """

    n_enclosures: int
    n_buildings_in: int
    n_etc: int
    n_excluded_no_parent_building: int
    """Tessellation cells `momepy.enclosed_tessellation` returned with a negative index — an
    enclosure interior (or a sliver of one) with no matching building. Excluded per Majer &
    Fleischmann (2026)'s own rule: ETCs without a parent building carry no morphometric meaning
    and are dropped before any attribute is computed."""

    etc_area_quantiles: dict[str, float] = field(default_factory=dict)
    """p10/p50/p90 ETC area in m², after exclusion."""


def building_ids(buildings: gpd.GeoDataFrame) -> pd.Series:
    """One id string per row of `buildings`, aligned to its row order, guaranteed unique.

    Prefers `building_id` (`lczkit.cleaning.buildings.BUILDING_ID`), which is documented as
    unique on `buildings_area` — the layer this strategy is meant to be given — then Overture's
    own `id`, then lczkit's `feature_id`. The latter two are **not** trustworthy on their own:
    `feature_id` is stamped before cleaning explodes multipolygons specifically so height
    statistics can collapse split parts back together, which means the parts share it, and a raw
    Overture `id` behaves the same way after any explode. A duplicate `unit_id` would silently
    drop a cell at `set_index`, so whichever column is used is disambiguated with a per-group
    counter rather than trusted at face value; a building with none of these columns falls back
    to its row position, which is always unique.

    This is the same id scheme `TessellationUnits.generate` builds `unit_id` from — exported so
    `lczkit.morphometrics` can reindex the raw building layer onto the ETC `unit_id` axis without
    re-deriving the scheme, which is what makes a building-level momepy result (e.g.
    `momepy.circular_compactness(buildings)`) directly joinable to an ETC-level one.
    """
    for column in ("building_id", "id", "feature_id"):
        if column in buildings.columns:
            base = buildings[column].astype(str)
            break
    else:
        base = buildings.index.to_series().astype(str)
    base = pd.Series(base.to_numpy())
    order = base.groupby(base).cumcount()
    return base.where(order == 0, base + "_" + order.astype(str))


def buildings_for_etc(buildings: gpd.GeoDataFrame, etc: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """`buildings`, filtered to those with a matching ETC and reindexed onto `etc`'s `unit_id`.

    The frame every building-level momepy call in `lczkit.morphometrics` should be given: its
    index lines up with `etc.index` row for row, so a `Series` computed from one is directly
    alignable with one computed from the other — no separate join step, and no risk of the two
    silently drifting apart if a caller filtered one but not the other.
    """
    assert_projected_crs(buildings, "buildings")
    assert_projected_crs(etc, "etc")
    valid = buildings.loc[buildings.geometry.notna() & ~buildings.geometry.is_empty]
    keyed = valid.set_axis(pd.Index("etc_" + building_ids(valid).to_numpy(), name="unit_id"))
    # `etc.index` may hold repeats where `TessellationUnits` disambiguated a duplicate parent id
    # (`etc_<id>_1`, ...); `keyed`'s own duplicate suffixes were built the same way from the same
    # `building_ids`, so the two line up without a fuzzy join.
    return keyed.loc[etc.index]


class TessellationUnits:
    """Building-level enclosed tessellation cells, satisfying `SpatialUnitStrategy`.

    `buildings` is taken at construction rather than passed to `generate`, following the
    `PatchUnits` precedent (`lczkit.units.patches`) — `enclosed_tessellation` needs building
    footprints, and the protocol's `generate(bbox, barriers)` signature has no room for a second
    geometry layer without widening every strategy's interface for one caller.

    The last `TessellationReport` is kept on the instance, the same way `PatchUnits.report` is,
    so a caller can put it in the manifest without the protocol growing a second return value.
    """

    def __init__(
        self,
        *,
        buildings: gpd.GeoDataFrame,
        shrink: float = DEFAULT_SHRINK,
        segment: float = DEFAULT_SEGMENT,
        threshold: float | None = DEFAULT_THRESHOLD,
    ) -> None:
        """Set the building layer tessellation is generated from, and momepy's own tuning knobs.

        `buildings` should be `buildings_area` from `lczkit.cleaning.pipeline.clean_vectors` —
        the area-preserving layer, matching every other area statistic in this package.
        `shrink`/`segment`/`threshold` are passed straight through to
        `momepy.enclosed_tessellation`; the defaults are momepy's own.
        """
        assert_projected_crs(buildings, "buildings")
        self.buildings = buildings
        self.shrink = shrink
        self.segment = segment
        self.threshold = threshold
        self.report: TessellationReport | None = None

    def generate(self, bbox: BBox, barriers: gpd.GeoDataFrame | None = None) -> gpd.GeoDataFrame:
        """Enclosed tessellation over `barriers`, restricted to cells with a parent building.

        Same contract as the other strategies: `bbox` lon/lat, the returned frame in the
        projected CRS, indexed by `unit_id`. `barriers` is required, as for `EnclosureUnits` —
        tessellation is generated *within* enclosures, so there is nothing to tessellate without
        them.

        Extra columns `enclosure_index` and `parent_building_id` are carried alongside geometry,
        matching the precedent `PatchUnits` and `EnclosureUnits` set of returning more than a
        bare geometry frame where it is useful downstream — here, for joining ETC-level
        morphometrics back to the building that owns each cell.

        Sets `self.report` as a side effect.
        """
        enclosures = EnclosureUnits().generate(bbox, barriers)

        buildings = self.buildings.loc[
            self.buildings.geometry.notna() & ~self.buildings.geometry.is_empty
        ]
        source_ids = building_ids(buildings)
        # Positional reset: `enclosed_tessellation` requires a unique non-negative integer index,
        # and its result is indexed by that same integer — `source_ids` stays aligned to it by
        # construction, since both are built from `buildings` in the same row order.
        positioned = buildings[["geometry"]].reset_index(drop=True)

        # momepy names its enclosure-linking output column after `enclosures`'s own index name —
        # `EnclosureUnits` indexes by `unit_id`, so that column would otherwise be called
        # `unit_id` too and collide with the one this method sets on its own result below.
        # Renaming the axis first keeps the real enclosure `unit_id` values (e.g. "enclosure_12")
        # while giving the column an unambiguous name.
        tess = momepy.enclosed_tessellation(
            positioned,
            enclosures.geometry.rename_axis("enclosure_index"),
            shrink=self.shrink,
            segment=self.segment,
            threshold=self.threshold,
        )
        matched = tess.loc[tess.index >= 0]
        n_excluded = len(tess) - len(matched)

        if matched.index.duplicated().any():
            # momepy's own documented edge case: a cell can split into a MultiPolygon during
            # shrinking, which can surface as more than one row sharing an index. Dissolving
            # keeps `unit_id` unique without discarding area — the parts union back to one cell.
            matched = matched.dissolve(by=matched.index)

        parent_ids = source_ids.loc[matched.index]
        result = gpd.GeoDataFrame(
            {
                "unit_id": "etc_" + parent_ids.to_numpy(),
                "enclosure_index": matched["enclosure_index"].to_numpy(),
                "parent_building_id": parent_ids.to_numpy(),
            },
            geometry=matched.geometry.to_numpy(),
            crs=enclosures.crs,
        ).set_index("unit_id")

        area = result.geometry.area
        self.report = TessellationReport(
            n_enclosures=int(len(enclosures)),
            n_buildings_in=int(len(buildings)),
            n_etc=int(len(result)),
            n_excluded_no_parent_building=int(n_excluded),
            etc_area_quantiles={
                "p10": float(area.quantile(0.1)) if len(area) else 0.0,
                "p50": float(area.quantile(0.5)) if len(area) else 0.0,
                "p90": float(area.quantile(0.9)) if len(area) else 0.0,
            },
        )
        return result
