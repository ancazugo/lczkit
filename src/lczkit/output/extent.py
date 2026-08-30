"""What ground a run covered, and how that ground was chosen.

**A run directory could not say where it was.** Checked across every manifest written before this
module existed: no bbox, no place name, no extent of any kind. The reason is structural rather than
an oversight — the extent is an argument to `run_pipeline`, so it is in no `Settings` field, no
preset and no command-line default, and `Settings.model_dump()` is what the manifest serialises. It
is the same shape as the run CRS, and the same rule closes it: a derived property has to be
recorded somewhere the derivation is not.

It matters more now that `--city` reaches 5 558 urban regions rather than 28. Two runs of "Berlin"
can legitimately mean the GUPPD urban region or the densest 30 km window of its So2Sat labels;
those are different ground, and a bbox alone does not say which was asked for or why.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field

from lczkit.protocols import BBox

ExtentKind = Literal["bbox", "guppd", "so2sat_window", "recovered"]
"""How an extent was arrived at.

`recovered` is reserved for `lczkit export`, which reconstructs an extent from an archived run's
own geometry. It is deliberately a distinct value rather than a best guess at the original: a
reconstruction is bounded by the units that were written, not by what was requested, and the two
differ wherever the unit grid overhangs or falls short of the window.
"""


def bbox_area_km2(bbox: BBox) -> float:
    """Roughly how much ground a lon/lat window covers.

    A cosine-corrected rectangle, matching `lczkit.places.Place.area_km2`, because both feed the
    same decision — whether this is a minutes run or an hours one — and a projected area would
    disagree with the figure `lczkit cities` printed for the same place.
    """
    west, south, east, north = bbox
    mid = math.radians((south + north) / 2.0)
    return (east - west) * 111.32 * math.cos(mid) * (north - south) * 110.57


class ExtentRecord(BaseModel):
    """The window a run covered, with the locator that produced it."""

    kind: ExtentKind

    bbox: tuple[float, float, float, float]
    """The window actually run, in lon/lat degrees, after any `extent_km` shrink."""

    name: str | None = None
    """The place as the gazetteer spells it — `"São Paulo"`, not the query that found it."""

    query: str | None = None
    """What the caller typed, kept beside `name` because they differ under normalisation and the
    query is what has to be retyped to reproduce the run."""

    iso: str | None = None
    country: str | None = None

    smod_id: str | None = None
    """GUPPD's own identifier for the region. Unambiguous where the name is not — 149 of the 5 558
    names are shared — so this is what identifies the extent when the record is read back."""

    city_key: str | None = None
    """The `lczkit.cities` registry key, where the extent came from a So2Sat window."""

    side_km: float | None = None
    """Side of the So2Sat search window, in kilometres. 30 for every recorded sweep."""

    extent_km: float | None = None
    """The `--extent-km` shrink applied, if any. `source_bbox` is what it was applied to."""

    source_bbox: tuple[float, float, float, float] | None = None
    """The window before the shrink, so a trimmed trial run still records the whole region it was
    trimmed from."""

    area_km2: float = Field(default=0.0)
    """Area of `bbox`, precomputed so a reader needs no geodesy to size the run."""

    def model_post_init(self, _context: object) -> None:
        """Fill `area_km2` from `bbox`, so the two cannot disagree."""
        object.__setattr__(self, "area_km2", bbox_area_km2(tuple(self.bbox)))  # type: ignore[arg-type]

    @property
    def label(self) -> str:
        """A short name for this extent, for progress output and the run's own log line."""
        if self.kind == "bbox":
            return "bbox"
        if self.kind == "recovered":
            return "recovered extent"
        parts = [self.name or self.city_key or "city"]
        if self.iso:
            parts.append(f"({self.iso})")
        if self.kind == "so2sat_window":
            parts.append(f"So2Sat {self.side_km:g} km window" if self.side_km else "So2Sat window")
        return " ".join(parts)

    def shrunk(self, bbox: BBox, extent_km: float) -> ExtentRecord:
        """The same locator over a concentric `extent_km` window of it.

        The locator is preserved rather than replaced by a bare bbox: a 3 km trial over Cambridge
        is still a run about Cambridge, and losing that on the way into the manifest is how a
        directory full of trial runs becomes unreadable.
        """
        return self.model_copy(
            update={
                "bbox": tuple(bbox),
                "source_bbox": tuple(self.source_bbox or self.bbox),
                "extent_km": extent_km,
                "area_km2": bbox_area_km2(bbox),
            }
        )
