"""Source-availability diagnostic: is this city viable before anyone waits for a full run?

CLAUDE.md asks for non-null `height` and `num_floors` counts grouped by Overture source dataset
over the study area. This module reports that grouping twice, because the data forces it: once
by the dataset that won the *footprint*, and once by the dataset that supplied the *height*.

Those two tables disagree, and the disagreement is the useful part. In the Berlin test fixture,
grouping by footprint reports 1509 heights on OpenStreetMap footprints — but 394 of those
heights are Microsoft ML Buildings values conflated onto an OSM footprint. Read the first table
alone and a quarter of the city's tier-1 heights look surveyed when they are predicted.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
from pydantic import BaseModel, Field

from lczkit.heights.provenance import footprint_datasets, height_attribution
from lczkit.heights.tiers import numeric_column

UNKNOWN_DATASET = "(unknown)"
"""Stand-in for a row carrying no usable provenance, so it is counted rather than dropped."""


class DatasetAvailability(BaseModel):
    """Height and floor-count availability for one upstream dataset."""

    dataset: str
    n_buildings: int
    n_with_height: int
    n_with_num_floors: int


class HeightProvenance(BaseModel):
    """How many heights one upstream dataset actually supplied."""

    dataset: str
    n_with_height: int


class SourceAvailability(BaseModel):
    """The full diagnostic for one study area, for the output manifest."""

    n_buildings: int
    n_with_height: int
    n_with_num_floors: int

    by_footprint_dataset: list[DatasetAvailability] = Field(default_factory=list)
    """Grouped by the dataset that won each footprint's geometry — CLAUDE.md's literal ask."""

    by_height_dataset: list[HeightProvenance] = Field(default_factory=list)
    """Heights only, grouped by the dataset that supplied the `height` value rather than the one
    that won the footprint.

    Deliberately narrower than the table above. Provenance in Overture is per attribute, and the
    only attribute conflated away from its footprint is `height`; reporting a building's
    `num_floors` under the dataset that supplied its height would credit a dataset with a value
    it never provided. Rows with no height contribute nothing here, which is why these counts do
    not sum to `n_buildings`."""


def source_availability(buildings: gpd.GeoDataFrame) -> SourceAvailability:
    """Count height and floor availability by upstream dataset over `buildings`.

    Reads Overture's `sources` column. A layer without one still returns valid totals, with
    every row grouped under `"(unknown)"` — the diagnostic degrades rather than blocking a
    non-Overture `VectorSource`.
    """
    height = numeric_column(buildings, "height")
    floors = numeric_column(buildings, "num_floors")
    has_height = height.notna() & height.gt(0)
    has_floors = floors.notna() & floors.ge(1)

    footprint = footprint_datasets(buildings)
    height_dataset, _ = height_attribution(buildings)

    return SourceAvailability(
        n_buildings=len(buildings),
        n_with_height=int(has_height.sum()),
        n_with_num_floors=int(has_floors.sum()),
        by_footprint_dataset=_by_footprint(footprint, has_height, has_floors),
        by_height_dataset=_by_height(height_dataset[has_height]),
    )


def _labels(dataset: pd.Series) -> pd.Series:
    return dataset.fillna(UNKNOWN_DATASET).astype(str)


def _by_footprint(
    dataset: pd.Series, has_height: pd.Series, has_floors: pd.Series
) -> list[DatasetAvailability]:
    frame = pd.DataFrame(
        {
            "dataset": _labels(dataset),
            "has_height": has_height.astype(int),
            "has_floors": has_floors.astype(int),
        }
    )
    grouped = frame.groupby("dataset", observed=True).agg(
        n_buildings=("dataset", "size"),
        n_with_height=("has_height", "sum"),
        n_with_num_floors=("has_floors", "sum"),
    )
    # Most-populated first: the question this answers is "what is this city made of?", and a
    # long alphabetical tail of one-building datasets buries the answer.
    return [
        DatasetAvailability(
            dataset=str(name),
            n_buildings=int(row.n_buildings),
            n_with_height=int(row.n_with_height),
            n_with_num_floors=int(row.n_with_num_floors),
        )
        for name, row in grouped.sort_values("n_buildings", ascending=False).iterrows()
    ]


def _by_height(dataset: pd.Series) -> list[HeightProvenance]:
    counts = _labels(dataset).value_counts()
    return [
        HeightProvenance(dataset=str(name), n_with_height=int(count))
        for name, count in counts.items()
    ]
