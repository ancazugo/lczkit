"""`EnclosureUnits`: `momepy.enclosures()`-based spatial units, the GeoClimate RSU analogue.

CLAUDE.md names streets, rail, waterbodies, and large vegetation patches as the barrier set —
that list is exhaustive, not illustrative.

Phase 1 only ever fetched streets and waterbodies; rail was added to `VectorSource` in Phase 2
(see `lczkit.sources.overture.OvertureSource.rail`) specifically for this. Large vegetation
patches have no source at all yet — that is Phase 4's land-cover raster work — so
`assemble_barriers` accepts `vegetation` as an optional layer and omits it from the barrier set
until a `RasterSource`-derived vegetation-patch layer exists to pass in.

The one plausible-looking wrong answer: `VectorSource.land_use()` returns polygons that include
parks and green space, and it is tempting to reach for them as the missing vegetation barrier.
Do not. CLAUDE.md restricts land use to functional semantics (Phase 5's `industrial_fraction`)
and states explicitly that it is neither a barrier here nor a land-cover source in Phase 4 —
rasters own land cover, and the vegetation barrier must come from them.
"""

from __future__ import annotations

import geopandas as gpd
import momepy
import pandas as pd
from shapely.geometry import box

from lczkit.crs import assert_projected_crs
from lczkit.protocols import BBox


def assemble_barriers(
    streets: gpd.GeoDataFrame,
    waterbodies: gpd.GeoDataFrame,
    *,
    rail: gpd.GeoDataFrame | None = None,
    vegetation: gpd.GeoDataFrame | None = None,
) -> gpd.GeoDataFrame:
    """Combine barrier layers into the single `barriers` GeoDataFrame `EnclosureUnits.generate`
    expects: one geometry column, no attributes, all layers in the same projected CRS.

    `rail` and `vegetation` are optional — pass `None` (the default) when a layer isn't
    available; enclosures form from whatever barriers are given. All non-empty inputs must
    already share one CRS (typically the CRS Phase 1's `clean_vectors()` reprojected into);
    this function does not itself reproject anything.

    These four layers are the whole eligible barrier set. In particular, do not pass
    `CleanedVectors.land_use` as `vegetation` — see this module's docstring.
    """
    assert_projected_crs(streets, "streets")
    assert_projected_crs(waterbodies, "waterbodies")
    layers = [streets.geometry, waterbodies.geometry]
    crs = streets.crs
    for extra, name in ((rail, "rail"), (vegetation, "vegetation")):
        if extra is None or extra.empty:
            continue
        assert_projected_crs(extra, name)
        if extra.crs != crs:
            raise ValueError(f"{name}.crs ({extra.crs}) != streets.crs ({crs})")
        layers.append(extra.geometry)
    combined = pd.concat(layers, ignore_index=True)
    return gpd.GeoDataFrame(geometry=gpd.GeoSeries(combined, crs=crs))


class EnclosureUnits:
    """`momepy.enclosures()`-based spatial units.

    All barrier linework is unioned into one series before polygonization (see
    `momepy.elements.enclosures`'s source), so momepy's own `primary_barriers` /
    `additional_barriers` split — meaningful elsewhere for RSU semantics — makes no difference
    to the resulting enclosure geometries here; `barriers` is passed through as
    `primary_barriers` with no `additional_barriers`.

    `unit_id`s are `f"enclosure_{eid}"`, `eid` being the sequential integer `momepy.enclosures`
    assigns in polygonization order. This is deterministic for a fixed `barriers` input (same
    rows, same order, same library versions) but not stable against changes to the *set* of
    barriers — unlike `GridUnits`, whose ids are tied to absolute coordinates, an enclosure's id
    can shift if upstream barrier data changes. Documented, not fixed: no id scheme survives
    which regions of the barrier network happen to change.

    **Enclosures are restricted to `bbox`.** Barrier linework runs past the study area — a rail
    line entering the extent continues well beyond it — and polygonizing it produces faces lying
    wholly outside. Left in, those are returned as units: on the Berlin fixture the result covered
    222% of the requested extent and on Rotterdam 379%, so the units were not a partition and any
    area-weighted statistic over them was measured against the wrong denominator. `clip=True`
    keeps only the faces whose representative point falls inside `limit`, which is exact rather
    than approximate: `limit`'s boundary is part of the noded linework, so every face is already
    split at the extent's edge and none straddles it. No geometry is modified.
    """

    def generate(self, bbox: BBox, barriers: gpd.GeoDataFrame | None = None) -> gpd.GeoDataFrame:
        if barriers is None or barriers.empty:
            raise ValueError(
                "EnclosureUnits requires `barriers` (see `assemble_barriers`) — it has no "
                "barrier source of its own, unlike GridUnits, which barriers is optional for."
            )
        assert_projected_crs(barriers, "barriers")
        crs = barriers.crs
        assert crs is not None  # narrows for mypy; assert_projected_crs already guarantees this
        limit = gpd.GeoSeries([box(*bbox)], crs="EPSG:4326").to_crs(crs)

        raw: gpd.GeoDataFrame = momepy.enclosures(barriers, limit=limit, clip=True)
        raw["unit_id"] = "enclosure_" + raw["eID"].astype(str)
        return raw.set_index("unit_id")[["geometry"]]
