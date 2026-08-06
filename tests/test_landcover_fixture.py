"""`LocalRasterSource` against the real committed Berlin land-cover rasters.

The hand-built rasters in `test_landcover_local.py` prove the arithmetic. These prove the thing
arithmetic cannot: that the configured defaults match the products as they actually ship, and that
central Berlin comes out looking like central Berlin.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from conftest import FIXTURE_BBOX, LANDCOVER_FIXTURES_DIR

from lczkit.config import LandCoverConfig
from lczkit.landcover.local import LocalRasterSource
from lczkit.units.grid import GridUnits


@pytest.fixture(scope="module")
def units() -> gpd.GeoDataFrame:
    return GridUnits().generate(FIXTURE_BBOX)


def _source(name: str, filename: str, **overrides: object) -> LocalRasterSource:
    config = LandCoverConfig().dataset(name)
    if overrides:
        config = config.model_copy(update=overrides)
    return LocalRasterSource(config, LANDCOVER_FIXTURES_DIR / filename)


@pytest.fixture(scope="module")
def worldcover(units: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return _source("worldcover", "worldcover_berlin.tif").fractions(units)


def test_the_shipped_worldcover_mapping_covers_the_real_raster(
    worldcover: gpd.GeoDataFrame,
) -> None:
    """`unmapped_policy` defaults to `"raise"`, so simply getting a result here is the assertion:
    every value in a real v200 tile is in the shipped mapping."""
    assert list(worldcover.columns) == [
        "frac_tree",
        "frac_pervious",
        "frac_impervious",
        "frac_water",
    ]


def test_fractions_sum_to_one_for_every_covered_unit(worldcover: gpd.GeoDataFrame) -> None:
    """CLAUDE.md names this as the property test for this phase."""
    covered = worldcover.dropna(how="all")

    assert len(covered) > 900
    assert covered.sum(axis=1).to_numpy() == pytest.approx(1.0)


def test_central_berlin_reads_as_overwhelmingly_impervious(
    worldcover: gpd.GeoDataFrame,
) -> None:
    """A sanity check on the mapping's orientation, not on a specific number: this bbox is Mitte —
    dense historic blocks, Alexanderplatz, and the Spree."""
    means = worldcover.mean()

    assert means["frac_impervious"] > 0.7
    assert means["frac_tree"] > 0.05
    assert 0.0 < means["frac_water"] < 0.1


def test_units_beyond_the_clipped_raster_are_null(worldcover: gpd.GeoDataFrame) -> None:
    """`GridUnits` keeps cells whole and includes any that intersect the bbox, so the grid reaches
    slightly past the raster's edge. Those units must be null rather than zero."""
    assert worldcover.isna().all(axis=1).sum() > 0


def test_canopy_fractions_are_plausible_under_the_assign_policy(
    units: gpd.GeoDataFrame,
) -> None:
    canopy = _source("eth_canopy", "eth_canopy_berlin.tif").fractions(units)

    assert list(canopy.columns) == ["canopy_frac_tree", "canopy_frac_non_tree"]
    assert canopy["canopy_frac_tree"].mean() < 0.4
    assert canopy.dropna(how="all").sum(axis=1).to_numpy() == pytest.approx(1.0)


def test_excluding_the_canopy_mask_would_report_berlin_as_pure_canopy(
    units: gpd.GeoDataFrame,
) -> None:
    """The finding that drove `NodataPolicy`, asserted rather than left as a comment.

    Lang et al. (2023), `10.1038/s41559-023-02206-6`, mask built-up areas, snow, ice and permanent
    water out of the product and set those cells to 255 — a deliberate removal of surfaces known to
    carry no canopy. Over this fixture that is 93% of the built-up cells and 78% of the whole tile.
    Read instead as "no observation", almost every unit's *surviving* cells are the vegetated ones,
    and central Berlin reports as essentially pure tree cover.
    """
    assigned = _source("eth_canopy", "eth_canopy_berlin.tif").fractions(units)
    excluded = _source(
        "eth_canopy", "eth_canopy_berlin.tif", nodata_policy="exclude", nodata_class=None
    ).fractions(units)

    assert excluded["canopy_frac_tree"].mean() > 0.95
    assert assigned["canopy_frac_tree"].mean() < 0.4


def test_the_two_tree_estimates_are_independently_joinable(units: gpd.GeoDataFrame) -> None:
    """Both datasets estimate tree cover and Phase 5 chooses between them, so both have to sit on
    one units table at once without collision."""
    worldcover = _source("worldcover", "worldcover_berlin.tif").fractions(units)
    canopy = _source("eth_canopy", "eth_canopy_berlin.tif").fractions(units)

    joined = worldcover.join(canopy, how="outer")

    assert len(joined.columns) == len(worldcover.columns) + len(canopy.columns)
    assert joined.index.equals(units.index)
    # A ~3 m canopy threshold picks up more than WorldCover's "tree cover" class does, and Lang et
    # al. report their map overestimates vegetation below 5 m — so the canopy route reads higher.
    # Correlated but not equal, which is why the choice is left to Phase 5. The two are *not*
    # independent estimates, though: Lang et al. derive their mask from ESA WorldCover itself.
    both = joined[["frac_tree", "canopy_frac_tree"]].dropna()
    assert np.corrcoef(both["frac_tree"], both["canopy_frac_tree"])[0, 1] > 0.5
    assert not np.allclose(both["frac_tree"], both["canopy_frac_tree"])
    assert both["canopy_frac_tree"].mean() > both["frac_tree"].mean()
