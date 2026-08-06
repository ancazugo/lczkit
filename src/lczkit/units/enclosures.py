"""`EnclosureUnits`: `momepy.enclosures()`-based spatial units, the GeoClimate RSU analogue.

CLAUDE.md names streets, rail, waterbodies, and large vegetation patches as the barrier set.
Phase 1 only ever fetched streets and waterbodies; rail was added to `VectorSource` in Phase 2
(see `lczkit.sources.overture.OvertureSource.rail`) specifically for this. Large vegetation
patches have no source at all yet — that is Phase 4's land-cover raster work — so
`assemble_barriers` accepts `vegetation` as an optional layer and omits it from the barrier set
until a `RasterSource`-derived vegetation-patch layer exists to pass in.
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

        raw: gpd.GeoDataFrame = momepy.enclosures(barriers, limit=limit)
        raw["unit_id"] = "enclosure_" + raw["eID"].astype(str)
        return raw.set_index("unit_id")[["geometry"]]
