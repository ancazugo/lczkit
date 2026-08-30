"""Any city in the world, by name — the general locator a run's extent comes from.

A run needs an extent. `--bbox` has always been the general answer and needs nothing on disk, and
`lczkit.cities` is the other end of the range: 28 named cities whose windows are pinned to where
the So2Sat labels are dense, so a run is comparable with a recorded agreement figure. Neither is
what someone wanting a map of their own city reaches for — the first asks them to find four numbers
and the second only knows 28 places, and only if the label archive is on disk.

This module is the middle. NASA/JRC's **GUPPD** ships one small table of every urban region on
earth — 5 558 of them across 173 countries, with a name, an ISO code, a country and a bounding box
— and it is 564 KB. Nothing in this package read it until now.

**It is a locator, not a reference.** Nothing here labels, validates or measures anything; it turns
a name into four numbers and records which row it came from. The hand-labelled LCZ sets stay where
they are, in `lczkit.validation`, reached by the sweep scripts and not by anything on the path from
a city name to a map.

**Sizing, because it decides whether a plain `--city` run is a sensible default.** Measured over
the shipped table: the median urban region is **80 km²**, the 90th percentile 412 km², and only 239
of 5 558 exceed 900 km² — the extent Berlin's 9.8-minute benchmark was measured over. So the
ordinary case is minutes and the tail is real: Jakarta's region is 17 661 km². `shrink` is how a
caller trims one, and the command line says the area before it starts.
"""

from __future__ import annotations

import csv
import math
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from lczkit.config import Settings
from lczkit.protocols import BBox

GUPPD_SOURCE_DIR_NAME = "NASA"
"""Subdirectory under `input/`. GUPPD is filed under the agency rather than under its own name."""

GUPPD_BOUNDS = Path("GUPPD") / "guppd_bounds.csv"
"""The post-processed bounds table within `input/NASA/`, keyed on `SMOD_ID`.

The full GUPPD release beside it is a 117 MB GeoPackage of urban-region polygons. Reading the CSV
rather than the polygons is deliberate: a locator needs a rectangle, and the rectangle is what the
CSV holds, so resolving a name costs a 564 KB read rather than opening a spatial file.
"""

_FIELDS = ("SMOD_ID", "JRC_NAME_MAIN", "ISO", "CNTRY_NAME", "minx", "miny", "maxx", "maxy")


@dataclass(frozen=True)
class Place:
    """One GUPPD urban region: what it is called, where it is, and which row said so."""

    smod_id: str
    """GUPPD's own identifier, e.g. `"30_3528"`. Recorded in the run manifest, because a name is
    ambiguous — 149 of the 5 558 names are shared by more than one region — and this is not."""

    name: str

    iso: str
    """ISO 3166-1 alpha-3, e.g. `"DEU"`. What `--country` matches against, alongside the name."""

    country: str

    bbox: BBox
    """The region's bounding box in lon/lat degrees, as `(west, south, east, north)`."""

    @property
    def area_km2(self) -> float:
        """Roughly how much ground the bbox covers, for deciding whether to shrink it.

        A cosine-corrected rectangle rather than a projected area: the answer is used to print an
        order of magnitude and to decide whether to mention `--extent-km`, and reprojecting 5 558
        rectangles to answer that would be work spent on a digit nobody reads.
        """
        west, south, east, north = self.bbox
        mid = math.radians((south + north) / 2.0)
        return (east - west) * 111.32 * math.cos(mid) * (north - south) * 110.57

    @property
    def label(self) -> str:
        """`"Berlin, Germany (DEU)"` — how a place is named in output and error messages."""
        return f"{self.name}, {self.country} ({self.iso})"


def normalise(value: str) -> str:
    """A name reduced to what two spellings of it have in common.

    Accents are stripped, case is folded and everything that is not alphanumeric collapses away, so
    `bogota` finds `Bogota`, `sao paulo` finds `São Paulo` and `washington d.c.` finds
    `Washington D.C.`. Applied to both sides, never to stored data — the table keeps its own
    spelling, which is what gets printed back.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", stripped.casefold())


def bounds_path(settings: Settings) -> Path:
    """Where the GUPPD bounds table lives under `input/`."""
    return settings.source_dir(GUPPD_SOURCE_DIR_NAME) / GUPPD_BOUNDS


def load_places(settings: Settings) -> tuple[Place, ...]:
    """Every GUPPD urban region, in file order.

    Raises `FileNotFoundError` naming the path when the table is not on disk, and saying that
    `--bbox` needs nothing — the alternative is a bare `csv` error several frames down that names
    neither the dataset nor the way round it.
    """
    return _load(bounds_path(settings))


@lru_cache(maxsize=4)
def _load(path: Path) -> tuple[Place, ...]:
    """Parse the bounds table, cached on the path so repeated lookups read it once."""
    if not path.exists():
        raise FileNotFoundError(
            f"no GUPPD bounds table at {path}. Naming a city reads input/"
            f"{GUPPD_SOURCE_DIR_NAME}/{GUPPD_BOUNDS}; pass --bbox instead if it is not on disk."
        )
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [field for field in _FIELDS if field not in (reader.fieldnames or ())]
        if missing:
            raise ValueError(f"{path} has no {', '.join(missing)}; expected {', '.join(_FIELDS)}")
        return tuple(_place(row) for row in reader)


def _place(row: dict[str, str]) -> Place:
    """One CSV row as a `Place`."""
    return Place(
        smod_id=row["SMOD_ID"],
        name=row["JRC_NAME_MAIN"],
        iso=row["ISO"],
        country=row["CNTRY_NAME"],
        bbox=(
            float(row["minx"]),
            float(row["miny"]),
            float(row["maxx"]),
            float(row["maxy"]),
        ),
    )


def in_country(places: tuple[Place, ...], country: str | None) -> tuple[Place, ...]:
    """`places` narrowed to one country, matched on the ISO code or the country name.

    Either in full or as a prefix, under `normalise` — so `GBR`, `gb` and `"united kingdom"` all
    reach the United Kingdom. `None` returns everything, so a caller can pass an optional flag
    through without branching.
    """
    if country is None:
        return places
    key = normalise(country)
    if not key:
        return places
    return tuple(
        entry
        for entry in places
        if normalise(entry.iso).startswith(key) or normalise(entry.country).startswith(key)
    )


def find(places: tuple[Place, ...], query: str, *, country: str | None = None) -> list[Place]:
    """Regions whose name matches `query`, exact matches first.

    Two tiers rather than a score: a name that *is* the query outranks every name that merely
    contains it, so `london` returns London GBR and London CAN ahead of East London ZAF, and
    `cambridge` returns both Cambridges and nothing else. Within a tier the file's order is kept,
    so the answer does not depend on a sort that was never specified.

    An empty query returns every region in `country`, so `lczkit cities --country KEN` is a
    listing rather than a no-op. `in_country` is what narrows it.
    """
    candidates = in_country(places, country)
    wanted = normalise(query)
    if not wanted:
        return list(candidates)
    exact = [entry for entry in candidates if normalise(entry.name) == wanted]
    partial = [
        entry
        for entry in candidates
        if normalise(entry.name) != wanted and wanted in normalise(entry.name)
    ]
    return exact + partial


def place(places: tuple[Place, ...], query: str, *, country: str | None = None) -> Place:
    """The single region `query` names, or a `LookupError` saying why there is not one.

    An ambiguous query **is an error**, and the message lists the candidates with their countries.
    Silently taking the first would put a run over the wrong continent and record a manifest that
    looks entirely correct — there are two Cambridges and three Londons in this table, and nothing
    about a bbox afterwards would say which one was meant.
    """
    matches = find(places, query, country=country)
    if not matches:
        where = f" in {country}" if country else ""
        raise LookupError(
            f"no urban region called {query!r}{where} in GUPPD. Names come from the JRC's own "
            "gazetteer, so a local spelling may differ; `lczkit cities <part of the name>` "
            "searches, and --bbox takes an explicit window."
        )
    # One exact match ahead of substring matches is not ambiguity: `london` means London, not
    # East London. Only a tie between regions of the *same* name needs the caller to choose, and
    # only those are listed — naming East London in the error would suggest it was a candidate.
    wanted = normalise(query)
    tied = [entry for entry in matches if normalise(entry.name) == wanted] or matches
    if len(tied) > 1:
        listed = "; ".join(entry.label for entry in tied[:8])
        more = "" if len(tied) <= 8 else f"; and {len(tied) - 8} more"
        raise LookupError(
            f"{query!r} names {len(tied)} urban regions: {listed}{more}. "
            "Add --country to choose one."
        )
    return matches[0]
