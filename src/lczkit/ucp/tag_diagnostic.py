"""Is this city's semantic evidence viable? Answered before anyone waits for a run.

The exact counterpart of `lczkit.heights.diagnostic.source_availability`, which answers "is this
city viable?" for *height* before a full run. The same question needs asking of the attributes,
and the answer has the same shape:

| city | tagged **area** | tagged **count** | dominant footprint source | its tagged share |
|---|---:|---:|---|---:|
| Berlin | 64.4% | 46.6% | OpenStreetMap (80%) | 51.3% |
| Milan | 62.2% | 45.4% | OpenStreetMap (85%) | 53.5% |
| Hong Kong | 58.1% | 44.5% | OpenStreetMap (60%) | 73.6% |
| Vancouver | 55.3% | 41.4% | OpenStreetMap (90%) | 46.1% |
| Mumbai | 18.1% | 5.4% | Google Open Buildings (56%) | **0.0%** |
| Cape Town | 13.3% | 4.8% | Microsoft ML Buildings (64%) | **0.0%** |
| Jakarta | 7.5% | 1.4% | OpenStreetMap (75%) | 1.8% |
| São Paulo | 7.1% | 1.2% | OpenStreetMap (56%) | 2.1% |
| Cairo | 5.7% | 1.0% | Microsoft ML Buildings (59%) | **0.0%** |
| Nairobi | 5.2% | 1.0% | OpenStreetMap (56%) | 1.7% |
| Islamabad | 4.5% | 1.1% | Google Open Buildings (70%) | **0.0%** |
| Rio de Janeiro | 3.1% | 0.4% | Google Open Buildings (49%) | **0.0%** |

Europe + N. America **48.6% mean / 50.3% median** of building area tagged, against **13.6% / 7.1%**
everywhere else — the same seven-against-nine split, on a fourth independent quantity.

**The mechanism is in the last column, not the first.** Wherever an ML source wins the footprints,
its tagged share is *exactly* 0.0%: Google Open Buildings and Microsoft ML supply geometry and no
attributes at all. The cities are not undertagged because nobody bothered; they are undertagged
because the source that won their footprints has no attributes to give. And note that area coverage
runs well above count coverage everywhere — tagged buildings are systematically the larger ones —
which is why `tagged_area_fraction` is the reported figure: it is the denominator every semantic
fraction actually divides by.

**This is the same limit on a second, independent attribute.** Tier-1 height coverage runs 64.3%
across Europe and North America against 9.6% everywhere else, which is what makes height
availability the binding constraint on morphology-based LCZ mapping outside Europe. Building
attributes collapse in the same places and for the same reason — those footprints are ML-derived
and carry geometry without tags — so a functional rule keyed on them inherits the constraint rather
than escaping it.

Grouped by upstream dataset, because that is what makes the mechanism visible rather than merely
the outcome — and it is what turned an observation into an explanation here.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
from pydantic import BaseModel, Field

from lczkit.heights.diagnostic import UNKNOWN_DATASET
from lczkit.heights.provenance import footprint_datasets

UNKNOWN_VALUE = "unknown"
"""Overture's sentinel for a recorded absence of knowledge.

Excluded from every "has a tag" test. Counting it would report coverage the data does not have,
which is the one failure this whole module exists to prevent.
"""


class DatasetTags(BaseModel):
    """Attribute availability for one upstream dataset."""

    dataset: str
    n_buildings: int
    n_with_subtype: int
    n_with_class: int
    n_with_either: int
    area_m2: float
    area_with_either_m2: float


class TagAvailability(BaseModel):
    """The full diagnostic for one study area, for the output manifest."""

    n_buildings: int
    n_with_subtype: int
    n_with_class: int
    n_with_either: int

    area_m2: float
    area_with_either_m2: float

    tagged_area_fraction: float
    """Share of building **area** carrying any usable attribute. The area share, not the count
    share, because that is the denominator every semantic fraction divides by — a city where the
    tagged buildings are the large ones is in a different position from one where they are the
    small ones, and the count cannot tell them apart."""

    n_land_use_parcels: int
    land_use_summed_area_m2: float
    """Parcel area **summed, not dissolved**, and named so.

    `lczkit.cleaning.land_use` gives the layer no overlap resolution, so this double-counts shared
    ground and Milan's exceeds its own bbox. It is reported as a summed figure rather than made
    exact because the exact version is a whole-extent `union_all`, which is ruled out —
    superlinear, and it raises `side location conflict` on real Overture
    land use even after `make_valid`. The per-unit `land_use_coverage` column is the dissolved
    quantity, and it gets there by clipping to units first."""

    by_footprint_dataset: list[DatasetTags] = Field(default_factory=list)
    """Grouped by the dataset that won each footprint, most populated first — the mechanism, not
    just the outcome."""

    distinct_values: dict[str, list[str]] = Field(default_factory=dict)
    """The `subtype` and `class` values actually present, sorted. A vocabulary the crosswalk does
    not cover shows up here rather than only as a fraction that is quietly lower than it should be.
    """


def _present(frame: gpd.GeoDataFrame, column: str) -> pd.Series:
    """True where `column` carries a usable value — present, and not the `unknown` sentinel."""
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    values = frame[column]
    return values.notna() & (values.astype("string").str.lower() != UNKNOWN_VALUE)


def tag_availability(
    buildings: gpd.GeoDataFrame, land_use: gpd.GeoDataFrame | None = None
) -> TagAvailability:
    """Count attribute availability by upstream dataset over `buildings`.

    Degrades rather than raising on a frame with no `sources`, no `subtype` or no `class`: a
    non-Overture `VectorSource` should produce a diagnostic saying it supplies no attributes, not
    an exception three stages in.
    """
    has_subtype = _present(buildings, "subtype")
    has_class = _present(buildings, "class")
    has_either = has_subtype | has_class
    area = (
        buildings.geometry.area
        if buildings.crs is not None and buildings.crs.is_projected
        else pd.Series(0.0, index=buildings.index)
    )
    total_area = float(area.sum())
    tagged_area = float(area[has_either].sum())

    dataset = footprint_datasets(buildings).fillna(UNKNOWN_DATASET)
    rows = [
        DatasetTags(
            dataset=str(name),
            n_buildings=int(len(index)),
            n_with_subtype=int(has_subtype.loc[index].sum()),
            n_with_class=int(has_class.loc[index].sum()),
            n_with_either=int(has_either.loc[index].sum()),
            area_m2=float(area.loc[index].sum()),
            area_with_either_m2=float(area.loc[index][has_either.loc[index]].sum()),
        )
        for name, index in buildings.groupby(dataset, sort=False).groups.items()
    ]
    rows.sort(key=lambda row: (-row.n_buildings, row.dataset))

    parcels = 0
    parcel_area = 0.0
    if land_use is not None and not land_use.empty:
        parcels = int(len(land_use))
        if land_use.crs is not None and land_use.crs.is_projected:
            parcel_area = float(land_use.geometry.area.sum())

    return TagAvailability(
        n_buildings=int(len(buildings)),
        n_with_subtype=int(has_subtype.sum()),
        n_with_class=int(has_class.sum()),
        n_with_either=int(has_either.sum()),
        area_m2=total_area,
        area_with_either_m2=tagged_area,
        tagged_area_fraction=tagged_area / total_area if total_area > 0 else 0.0,
        n_land_use_parcels=parcels,
        land_use_summed_area_m2=parcel_area,
        by_footprint_dataset=rows,
        distinct_values={
            column: sorted(
                {
                    str(value)
                    for value in buildings[column].dropna().unique()
                    if str(value).lower() != UNKNOWN_VALUE
                }
            )
            for column in ("subtype", "class")
            if column in buildings.columns
        },
    )
