"""The So2Sat cities every validation sweep since Phase 9 has run, and how their windows are found.

A run needs an extent. `--bbox` is the general answer and needs nothing on disk; this module is the
convenience that lets a caller say `--city berlin` and get *the same 30 km window* the recorded
agreement figures were measured over. That is the point of it — a published site is a view of the
package's results, so it must not be a view of a different extent.

Lifted out of `scripts/multi_city_validation.py` in Phase 15. It reads `input/So2Sat-LCZ42/`, so it
is the one part of the CLI's locator that needs `DATA_DIR` populated; `--bbox` does not.
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
    """One So2Sat city: where its labels live and which continent it speaks for."""

    key: str

    so2sat: str
    """Directory name under `input/So2Sat-LCZ42/v4/cities/`."""

    region: str


#: Chosen by measuring labelled-patch density inside a 30 km window across all 51 cities on disk,
#: not by picking recognisable names. São Paulo is required by CLAUDE.md; Jakarta, Islamabad and
#: Mumbai are the viable South/Southeast Asian options, the obvious candidates having failed the
#: 500-patch / 4-class screen `scripts/multi_city_validation.py` applies. Europe is over-represented
#: because that is where So2Sat's dense coverage is, and the per-region breakdown in the report says
#: so rather than averaging it away.
#:
#: **Sixteen until Phase 18, then twenty, then twenty-eight — and every recorded figure predates
#: the last twelve.** Anything comparing a new sweep against a stored one must **intersect the city
#: sets first**: pooling twenty-eight against sixteen reports the difference between two populations
#: as a deviation, which CLAUDE.md records as a mistake this project has already made once.
#:
#: Both enlargements fixed the same defect — a regional group of **n = 1**, which cannot separate a
#: regional effect from one city — and the first of them showed the defect was real rather than
#: theoretical:
#:
#: - **North America was Vancouver alone**, in a "Europe + N. America" grouping the argument leans
#:   on three separate times. Los Angeles, New York, Washington D.C. and Santiago were added, and
#:   the grouping **reorganised**: North America landed with "everywhere else" and the line became
#:   Europe against everything. See the Phase 16 addendum.
#: - **East Asia was Hong Kong alone**, Oceania and West Asia were empty. Beijing, Guangzhou,
#:   Nanjing, Tokyo and Wuhan take East Asia to six; Istanbul and Tehran open West Asia; Sydney
#:   opens Oceania.
#:
#: Every one passes the same 500-patch / 4-class screen and carries both references. They are spread
#: deliberately across the label-reproducibility range rather than picked from its top — Nanjing
#: 83.2% down to Guangzhou 58.7%, with Tehran at 40.6%, New York at 50.8% — because keeping the
#: cities of a region that agree and dropping the ones that do not is how a regional split gets
#: manufactured instead of tested.
#:
#: Moscow, Madrid, Amsterdam, Munich, Zurich and Lisbon also qualify and are deliberately **not**
#: here: Europe is already over-represented at six, and adding six more would weaken the very
#: comparison the enlargement exists to test. Moscow additionally scores 99.6% on an overlap of only
#: 225 cells — its two references drew different parts of the city — and a near-perfect figure on a
#: thin, non-random intersection is the kind that gets quoted and then retracted.
#:
#: Istanbul and Tehran are labelled `West Asia` rather than folded into Europe. Istanbul genuinely
#: straddles, and putting it in Europe would inflate the group whose distinctiveness is under test.
CITIES = (
    City("berlin", "Berlin", "Europe"),
    City("london", "London", "Europe"),
    City("paris", "Paris", "Europe"),
    City("cologne", "Cologne", "Europe"),
    City("rome", "Rome", "Europe"),
    City("milan", "Milan", "Europe"),
    City("sao_paulo", "Sao_Paulo", "South America"),
    City("rio_de_janeiro", "Rio_De_Janeiro", "South America"),
    City("santiago", "Santiago", "South America"),
    City("cairo", "Cairo", "Africa"),
    City("nairobi", "Nairobi", "Africa"),
    City("cape_town", "Cape_Town", "Africa"),
    City("islamabad", "Rawalpindi_[Islamabad]", "South Asia"),
    City("mumbai", "Mumbai", "South Asia"),
    City("jakarta", "Jakarta", "Southeast Asia"),
    City("hong_kong", "Hong_Kong", "East Asia"),
    City("beijing", "Beijing", "East Asia"),
    City("guangzhou", "Guangzhou", "East Asia"),
    City("nanjing", "Nanjing", "East Asia"),
    City("tokyo", "Tokyo", "East Asia"),
    City("wuhan", "Wuhan", "East Asia"),
    City("istanbul", "Istanbul", "West Asia"),
    City("tehran", "Tehran", "West Asia"),
    City("sydney", "Sydney", "Oceania"),
    City("vancouver", "Vancouver", "North America"),
    City("los_angeles", "Los_Angeles", "North America"),
    City("new_york", "New_York", "North America"),
    City("washington_dc", "Washington_D.C.", "North America"),
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
    """`target`'s densest labelled window — the extent every sweep since Phase 9 has used.

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
