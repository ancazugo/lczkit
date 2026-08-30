"""The So2Sat study cities, and how each one's window is found.

A run needs an extent. `--bbox` is the general answer and needs nothing on disk; this module is the
convenience that lets a caller say `--city berlin` and get *the same 30 km window* the published
agreement figures were measured over, so a run stays comparable with them.

It reads `input/So2Sat-LCZ42/`, so it is the one locator that needs `DATA_DIR` populated. `--bbox`
does not, and `lczkit.places` covers every other city.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np

from lczkit.config import Settings
from lczkit.protocols import BBox

WINDOW_KM = 30.0
"""Side of the square window, in kilometres. ~900 km2, matching the measured Berlin extent."""

SO2SAT_SOURCE_DIR_NAME = "So2Sat-LCZ42"
SO2SAT_CITIES = Path("v4") / "cities"


@dataclass(frozen=True)
class City:
    """One So2Sat city: its labels, its country, and the region it speaks for."""

    key: str

    so2sat: str
    """Directory name under `input/So2Sat-LCZ42/v4/cities/`."""

    region: str

    iso: str
    """ISO 3166-1 alpha-3, so this registry can be matched against the GUPPD gazetteer.

    Added because the two locators otherwise collided on a name. Three of these keys name a city
    that exists in more than one country — **London** (GBR and CAN), **Santiago** (CHL and PHL) and
    **Los Angeles** (USA and Chile's Los Ángeles) — so `lczkit cities` marked rows that carry no
    So2Sat window at all, and `--city london --country CAN --so2sat-window` would have run
    *London, UK's* window while the caller asked for Canada. Silent wrong ground, which is the one
    failure the two-locator design exists to prevent.
    """


#: Chosen by measuring labelled-patch density inside a 30 km window across all 51 So2Sat cities,
#: not by picking recognisable names. Every one passes a 500-patch / 4-class screen and carries
#: both reference label sets. Europe is over-represented because that is where So2Sat's dense
#: coverage is, and the per-region breakdown in a report says so rather than averaging it away.
#:
#: The cities are spread deliberately across the range of how well the two reference label sets
#: agree with each other, rather than picked from its top — Nanjing 83.2% down to Guangzhou 58.7%,
#: with Tehran at 40.6% and New York at 50.8%. Keeping the cities of a region that agree and
#: dropping the ones that do not is how a regional split gets manufactured instead of tested.
#:
#: Every region carries more than one city, because a region represented by a single city cannot
#: separate a regional effect from that city.
#:
#: Moscow, Madrid, Amsterdam, Munich, Zurich and Lisbon also qualify and are deliberately **not**
#: here: Europe is already at six. Moscow additionally scores 99.6% on an overlap of only 225
#: cells, because its two references drew different parts of the city, and a near-perfect figure
#: on a thin, non-random intersection is not one to quote.
#:
#: Istanbul and Tehran are labelled `West Asia` rather than folded into Europe. Istanbul genuinely
#: straddles, and putting it in Europe would inflate the group whose distinctiveness is under test.
#:
#: Adding a city changes the population every published figure is measured over, so a new sweep
#: compared against a stored one must intersect the two city sets first.
CITIES = (
    City("berlin", "Berlin", "Europe", "DEU"),
    City("london", "London", "Europe", "GBR"),
    City("paris", "Paris", "Europe", "FRA"),
    City("cologne", "Cologne", "Europe", "DEU"),
    City("rome", "Rome", "Europe", "ITA"),
    City("milan", "Milan", "Europe", "ITA"),
    City("sao_paulo", "Sao_Paulo", "South America", "BRA"),
    City("rio_de_janeiro", "Rio_De_Janeiro", "South America", "BRA"),
    City("santiago", "Santiago", "South America", "CHL"),
    City("cairo", "Cairo", "Africa", "EGY"),
    City("nairobi", "Nairobi", "Africa", "KEN"),
    City("cape_town", "Cape_Town", "Africa", "ZAF"),
    City("islamabad", "Rawalpindi_[Islamabad]", "South Asia", "PAK"),
    City("mumbai", "Mumbai", "South Asia", "IND"),
    City("jakarta", "Jakarta", "Southeast Asia", "IDN"),
    City("hong_kong", "Hong_Kong", "East Asia", "CHN"),
    City("beijing", "Beijing", "East Asia", "CHN"),
    City("guangzhou", "Guangzhou", "East Asia", "CHN"),
    City("nanjing", "Nanjing", "East Asia", "CHN"),
    City("tokyo", "Tokyo", "East Asia", "JPN"),
    City("wuhan", "Wuhan", "East Asia", "CHN"),
    City("istanbul", "Istanbul", "West Asia", "TUR"),
    City("tehran", "Tehran", "West Asia", "IRN"),
    City("sydney", "Sydney", "Oceania", "AUS"),
    City("vancouver", "Vancouver", "North America", "CAN"),
    City("los_angeles", "Los_Angeles", "North America", "USA"),
    City("new_york", "New_York", "North America", "USA"),
    City("washington_dc", "Washington_D.C.", "North America", "USA"),
)

BY_KEY = {city.key: city for city in CITIES}


def city(key: str) -> City:
    """The city called `key`, or a `KeyError` naming the ones that exist."""
    try:
        return BY_KEY[key]
    except KeyError:
        raise KeyError(f"unknown city {key!r}; choose from {sorted(BY_KEY)}") from None


def densest_window(patches: gpd.GeoDataFrame, side_km: float = WINDOW_KM) -> BBox:
    """The `side_km` square holding the most labelled patch centres, as a lon/lat bbox.

    Searched over a quantile grid of candidate centres rather than optimised: the objective is
    piecewise constant and this is deterministic, which matters more here than optimality — a
    window that moved between runs would make two runs of the same city incomparable.

    Centres, not areas. So2Sat patches are 320 m squares on a 100 m stride and overlap about
    sevenfold, so counting area would measure the sampling density rather than the city; the same
    reason `lczkit.validation.labelled` anchors each label on its patch centre.
    """
    utm = patches.estimate_utm_crs()
    centres = patches.to_crs(utm).geometry.centroid
    x, y = centres.x.to_numpy(), centres.y.to_numpy()
    half = side_km * 1000.0 / 2.0

    best = (-1, float(np.median(x)), float(np.median(y)))
    grid = np.linspace(0.05, 0.95, 19)
    for candidate_x in np.quantile(x, grid):
        for candidate_y in np.quantile(y, grid):
            n = int(((np.abs(x - candidate_x) <= half) & (np.abs(y - candidate_y) <= half)).sum())
            if n > best[0]:
                best = (n, float(candidate_x), float(candidate_y))
    _, cx, cy = best

    centre = gpd.GeoSeries(gpd.points_from_xy([cx], [cy]), crs=utm).to_crs("EPSG:4326")
    lon, lat = float(centre.x.iloc[0]), float(centre.y.iloc[0])
    half_lat = side_km / 2.0 / 111.0
    half_lon = half_lat / max(math.cos(math.radians(lat)), 0.01)
    return (lon - half_lon, lat - half_lat, lon + half_lon, lat + half_lat)


def patches_path(target: City, settings: Settings) -> Path:
    """Where `target`'s labelled patches live under `input/`."""
    source = settings.source_dir(SO2SAT_SOURCE_DIR_NAME) / SO2SAT_CITIES / target.so2sat
    return source / f"patches_reference_{target.so2sat}.gpkg"


def so2sat_window(target: City, settings: Settings, side_km: float = WINDOW_KM) -> BBox:
    """`target`'s densest labelled window — the extent the published figures were measured over.

    Raises `FileNotFoundError` naming the path when So2Sat is not on disk, because the alternative
    is a `pyogrio` error several frames down that does not say which city or which directory.
    """
    path = patches_path(target, settings)
    if not path.exists():
        raise FileNotFoundError(
            f"no So2Sat patches for {target.key} at {path}. The --city locator reads "
            f"input/{SO2SAT_SOURCE_DIR_NAME}/; pass --bbox instead if it is not on disk."
        )
    return densest_window(gpd.read_file(path), side_km)


def shrink(bbox: BBox, extent_km: float) -> BBox:
    """A concentric window of roughly `extent_km` on a side.

    Kept because a full 30 km window is a multi-hour run, and the first thing anyone does with a
    new command line is try it on something small.
    """
    minx, miny, maxx, maxy = bbox
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    half_lat = extent_km / 2 / 111.0
    half_lon = half_lat / max(math.cos(math.radians(cy)), 0.01)
    return (cx - half_lon, cy - half_lat, cx + half_lon, cy + half_lat)
