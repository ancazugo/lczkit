"""The functional evidence columns still say what they said before the overlays were shared.

`industrial_metrics` and `semantic_metrics` were rewritten onto `lczkit.units.overlay`, which
collapsed five near-identical private helpers into one definition and took the parameter stage from
seventeen unit-vs-layer intersections to two. Two of those changes are not merely structural:

- `industrial`'s dissolved coverage moved from a whole-layer `union_all` to clip-then-dissolve per
  unit. The two are equal by construction — the union of the clipped pieces inside a unit is the
  clip of the global union — but "equal by construction" is an argument, and this project's own
  record is full of arguments that measured differently.
- Every group selection now happens on pieces rather than on the layer, so the intersection runs
  once against the whole layer instead of once per selection. Overlay is not associative in
  floating point even where it is in exact arithmetic.

So the answer is pinned rather than reasoned about. The parquet files beside this test were written
from the implementation as it stood before the rewrite, on the three committed fixtures, and are
regenerated only by `scripts/build_ucp_evidence_fixture.py` — deliberately a separate step, so a
change to the code cannot quietly move the thing that is supposed to be checking it.

`atol` is 1e-9 on quantities that are areas in square metres divided by areas in square metres. A
real difference in any of these is a fraction moving in its third decimal at least, so this
tolerance separates "the same answer" from "a different one" with several orders of magnitude to
spare.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from conftest import (
    FIXTURE_BBOX,
    FIXTURE_CLEANING,
    FIXTURES_DIR,
    HONGKONG_BBOX,
    HONGKONG_FIXTURES_DIR,
    INDUSTRY_BBOX,
    INDUSTRY_FIXTURES_DIR,
    FixtureVectorSource,
)
from pandas.testing import assert_series_equal

from lczkit.cleaning.pipeline import clean_vectors
from lczkit.config import UcpConfig
from lczkit.ucp.buildings import building_metrics
from lczkit.ucp.industrial import industrial_metrics
from lczkit.ucp.semantics import semantic_metrics
from lczkit.units.grid import GridUnits

EVIDENCE_DIR = Path(__file__).parent / "fixtures" / "ucp"

#: The three committed fixtures, each named by the file holding its recorded answer.
CASES = {
    "hongkong": (HONGKONG_FIXTURES_DIR, HONGKONG_BBOX),
    "berlin": (FIXTURES_DIR, FIXTURE_BBOX),
    "rotterdam": (INDUSTRY_FIXTURES_DIR, INDUSTRY_BBOX),
}

#: A constant so the fixtures are reproducible. The evidence columns never read height — they are
#: area shares — but `building_metrics` supplies the shared denominator and refuses a layer without
#: the column, so a value has to be present and it may as well be one nobody can mistake for data.
SYNTHETIC_HEIGHT_M = 10.0


def evidence_table(directory: Path, bbox: tuple[float, float, float, float]) -> pd.DataFrame:
    """The evidence columns for one fixture, by the path `compute_parameters` takes."""
    cleaned = clean_vectors(FixtureVectorSource(directory), bbox, FIXTURE_CLEANING)
    units = GridUnits(cell_size_m=100.0).generate(bbox, None)
    buildings = cleaned.buildings_area.copy()
    buildings["height"] = SYNTHETIC_HEIGHT_M
    config = UcpConfig()

    morphology = building_metrics(buildings, units, config)
    building_area_m2 = morphology["building_surface_fraction"] * units.geometry.area
    industrial = industrial_metrics(
        buildings, cleaned.land_use, units, config, building_area_m2=building_area_m2
    )
    semantic = semantic_metrics(
        buildings, cleaned.land_use, units, config, building_area_m2=building_area_m2
    )
    table = pd.concat([morphology[["building_surface_fraction"]], industrial, semantic], axis=1)
    table["industrial_evidence"] = table["industrial_evidence"].astype("string")
    return table


@pytest.fixture(scope="module", params=sorted(CASES))
def city(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def test_every_evidence_column_reproduces_its_recorded_value(city: str) -> None:
    recorded = pd.read_parquet(EVIDENCE_DIR / f"{city}_evidence.parquet")
    computed = evidence_table(*CASES[city])

    assert list(computed.columns) == list(recorded.columns)
    assert computed.index.equals(recorded.index)
    for column in recorded.columns:
        assert_series_equal(
            computed[column],
            recorded[column],
            check_exact=False,
            atol=1e-9,
            rtol=0.0,
            obj=f"{city}.{column}",
        )


def test_the_recorded_tables_cover_units_that_actually_carry_evidence(city: str) -> None:
    """A tolerance test over columns that are all zero would pass however wrong the code was.

    Rotterdam is the fixture with real industry — 259 industrial buildings of 1 681 — and Berlin
    and Hong Kong carry the semantic tags. This asserts each recorded table has something in it to
    disagree about, so the test above is a comparison rather than a formality.
    """
    recorded = pd.read_parquet(EVIDENCE_DIR / f"{city}_evidence.parquet")
    assert (recorded["building_tag_coverage"].fillna(0.0) > 0).sum() > 20
    assert (recorded["land_use_coverage"] > 0).sum() > 20
    assert (recorded["industrial_fraction_of_unit_area"] > 0).sum() > 0
    assert recorded["industrial_evidence"].nunique() > 1


def test_sharing_the_pieces_gives_the_same_answer_as_overlaying_per_block() -> None:
    """Handing pieces down must not change a number, only what it costs.

    The one place the two paths could diverge is the default: a direct caller who passes no pieces
    gets an overlay computed inside the block, and `compute_parameters` passes one computed outside
    it. If those disagreed, every test in this file would still pass — they all take the direct
    path — and only a full pipeline run would show it.
    """
    directory, bbox = CASES["rotterdam"]
    cleaned = clean_vectors(FixtureVectorSource(directory), bbox, FIXTURE_CLEANING)
    units = GridUnits(cell_size_m=100.0).generate(bbox, None)
    buildings = cleaned.buildings_area.assign(height=SYNTHETIC_HEIGHT_M)
    config = UcpConfig()

    from lczkit.ucp.attributes import ATTRIBUTES
    from lczkit.ucp.buildings import OVERLAY_COLUMNS
    from lczkit.units.overlay import unit_pieces

    building_pieces = unit_pieces(units, buildings, columns=OVERLAY_COLUMNS)
    land_use_pieces = unit_pieces(units, cleaned.land_use, columns=ATTRIBUTES)

    for block in (industrial_metrics, semantic_metrics):
        alone = block(buildings, cleaned.land_use, units, config)
        shared = block(
            buildings,
            cleaned.land_use,
            units,
            config,
            building_pieces=building_pieces,
            land_use_pieces=land_use_pieces,
        )
        pd.testing.assert_frame_equal(alone, shared, check_exact=False, atol=1e-12)


def test_the_land_use_coverage_never_exceeds_one() -> None:
    """The property the dissolve exists for, on the fixture with the most parcel overlap.

    Milan's land use sums to 106.6% of its bbox undissolved. Any path that stopped dissolving —
    including a future one that reused a helper meant for the already-disjoint building layer —
    shows up here rather than as a fraction above 1.0 in a published table.
    """
    for name in CASES:
        recorded = pd.read_parquet(EVIDENCE_DIR / f"{name}_evidence.parquet")
        for column in ("land_use_coverage", "industrial_fraction_of_unit_area"):
            assert recorded[column].max() <= 1.0 + 1e-9, f"{name}.{column}"


def test_the_committed_fixture_directories_are_the_ones_the_tables_were_built_from() -> None:
    """A recorded answer belongs to a recorded input, and neither says so on its own."""
    for name, (directory, _) in CASES.items():
        assert (EVIDENCE_DIR / f"{name}_evidence.parquet").exists()
        assert isinstance(gpd.read_parquet(directory / "buildings.parquet"), gpd.GeoDataFrame)
