"""`compute_parameters()` — the four parameter blocks joined into one table per `unit_id`.

Pure transform. Every input is already in memory and already keyed on the unit of exchange, so
this phase reads no raster, opens no file and touches no network; it is the stage that turns
Phases 1-4's outputs into the vector Phase 6 measures against the LCZ prototypes.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from lczkit.config import LandCoverConfig, UcpConfig
from lczkit.ucp.buildings import building_metrics
from lczkit.ucp.industrial import industrial_metrics
from lczkit.ucp.registry import PARAMETER_COLUMNS
from lczkit.ucp.streets import street_metrics
from lczkit.ucp.surface import surface_fractions


def compute_parameters(
    units: gpd.GeoDataFrame,
    buildings_area: gpd.GeoDataFrame,
    buildings_topo: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    land_use: gpd.GeoDataFrame,
    land_cover: pd.DataFrame,
    *,
    config: UcpConfig,
    land_cover_config: LandCoverConfig,
) -> pd.DataFrame:
    """The full urban canopy parameter table, indexed by `unit_id` to match `units`.

    Both building layers must have been through `lczkit.heights.cascade.fill_heights()` — or, for
    `buildings_topo`, `lczkit.heights.inherit.inherit_heights()`. `land_cover` is a Phase 4
    fractions table for the dataset `config.land_cover_dataset` names. All vector layers must share
    `units`' projected CRS — Phase 1's `clean_vectors()` returns them that way, and
    `lczkit.ucp.registry.PARAMETERS` documents every column this returns.

    **Which layer feeds what.** `buildings_area` supplies every area statistic: building surface
    fraction, `Hr`, building count, mean building area, and the industrial fractions. Note the
    industrial columns are named for their denominator, which is not building area in both cases -
    see `lczkit.ucp.registry`. `buildings_topo` supplies only the street profile, because a
    footprint lying across a street centreline reports a canyon width of zero and drives up the
    aspect ratio — on
    the Berlin fixture 439 footprints did exactly that. `buildings_topo`'s facades have been trimmed
    back to the road-buffer edge, which is a plausible facade line; `buildings_area`'s have not,
    because trimming them would cost the footprint area they exist to preserve.

    Two of Stewart & Oke's seven morphological properties are absent by design: see
    `lczkit.ucp.registry.NOT_COMPUTED`.
    """
    dataset = land_cover_config.dataset(config.land_cover_dataset)

    morphology = building_metrics(buildings_area, units, config)
    # Recovered from the fraction rather than overlaid again: `building_metrics` has already put
    # every footprint against every unit, and repeating that is the expensive half of
    # `industrial_metrics` at metropolitan scale. Exact, and it guarantees the industrial
    # building-area share shares a denominator with `building_surface_fraction`.
    building_area_m2 = morphology["building_surface_fraction"] * units.geometry.area
    table = pd.concat(
        [
            morphology,
            street_metrics(streets, buildings_topo, units, config),
            surface_fractions(land_cover, morphology["building_surface_fraction"], dataset, config),
            industrial_metrics(
                buildings_area, land_use, units, config, building_area_m2=building_area_m2
            ),
        ],
        axis=1,
    )

    missing = [column for column in PARAMETER_COLUMNS if column not in table.columns]
    if missing:  # pragma: no cover - a registry/implementation mismatch, caught by its own test
        raise RuntimeError(f"parameter blocks did not produce: {', '.join(missing)}")
    result = table[list(PARAMETER_COLUMNS)]
    result.index.name = "unit_id"
    return result
