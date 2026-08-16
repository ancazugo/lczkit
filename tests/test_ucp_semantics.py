"""Functional evidence from Overture attributes, and the coverage that makes it readable.

The module's whole argument is that a semantic fraction is meaningless without its coverage beside
it — 0.0 in Nairobi means "99% of footprints carry no tag", not "no informal settlement". So the
tests that matter most are the ones asserting the two states are distinguishable in the output, and
that the vocabulary matches the committed crosswalk rather than the author's memory of it.
"""

from __future__ import annotations

import re
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from conftest import INDUSTRY_BBOX, INDUSTRY_FIXTURES_DIR
from shapely.geometry import box

from lczkit.config import UcpConfig
from lczkit.crs import local_utm_crs
from lczkit.ucp.industrial import industrial_metrics
from lczkit.ucp.semantics import group_columns, semantic_metrics
from lczkit.ucp.tag_diagnostic import tag_availability

CRS = "EPSG:32633"
TABLE = Path(__file__).resolve().parent.parent / "docs" / "references" / "tables"
CROSSWALK = TABLE / "overture_lcz_semantic_mapping.md"


def units() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"unit_id": ["a", "b"]},
        geometry=[box(0, 0, 100, 100), box(100, 0, 200, 100)],
        crs=CRS,
    ).set_index("unit_id")


def buildings(*specs: tuple[str | None, str | None, tuple[float, ...]]) -> gpd.GeoDataFrame:
    """`(subtype, class, bounds)` -> a cleaned-buildings-shaped frame."""
    return gpd.GeoDataFrame(
        {
            "subtype": [s for s, _, _ in specs],
            "class": [c for _, c, _ in specs],
        },
        geometry=[box(*b) for _, _, b in specs],
        crs=CRS,
    )


def parcels(*specs: tuple[str | None, str | None, tuple[float, ...]]) -> gpd.GeoDataFrame:
    return buildings(*specs)


def empty_parcels() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"subtype": [], "class": []}, geometry=[], crs=CRS)


# --------------------------------------------------------------------------------------------
# The committed crosswalk is the authority
# --------------------------------------------------------------------------------------------


def parse_crosswalk() -> dict[str, dict[str, set[str]]]:
    """The group table out of the markdown, as `group -> field -> values`."""
    fields = ("building_subtypes", "building_classes", "land_use_subtypes", "land_use_classes")
    groups: dict[str, dict[str, set[str]]] = {}
    for line in CROSSWALK.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\|\s*`(\w+)`\s*\|([^|]*)\|(.*)\|\s*$", line.strip())
        if not match:
            continue
        cells = [cell.strip() for cell in match.group(3).split("|")]
        if len(cells) != len(fields):
            continue
        groups[match.group(1)] = {
            field: set()
            if cell == "—"
            else {value.strip() for value in cell.split(",") if value.strip()}
            for field, cell in zip(fields, cells, strict=True)
        }
    return groups


def test_the_shipped_vocabulary_is_the_committed_table_cell_for_cell() -> None:
    """The same treatment `stewart_oke_2012_properties.md` and `lcz_class_similarity.md` get. A
    vocabulary that lives only in Python is one nobody can check against a source."""
    table = parse_crosswalk()
    assert table, f"parsed no groups out of {CROSSWALK}"

    for group in UcpConfig().semantic_groups:
        assert group.name in table, f"{group.name} is configured and absent from the crosswalk"
        expected = table[group.name]
        assert set(group.building_subtypes) == expected["building_subtypes"], group.name
        assert set(group.building_classes) == expected["building_classes"], group.name
        assert set(group.land_use_subtypes) == expected["land_use_subtypes"], group.name
        assert set(group.land_use_classes) == expected["land_use_classes"], group.name

    assert set(table) == {g.name for g in UcpConfig().semantic_groups}


def test_warehouse_is_large_lowrise_and_not_heavy_industry() -> None:
    """The ruling `UcpConfig.industrial_building_classes` already records, restated here because two
    vocabularies for the same idea are exactly what drifts. Stewart & Oke give a warehouse as an
    LCZ 8 example."""
    groups = {g.name: g for g in UcpConfig().semantic_groups}

    assert "warehouse" in groups["large_lowrise"].building_classes
    assert "warehouse" not in groups["heavy_industry"].building_classes
    assert "warehouse" not in UcpConfig().industrial_building_classes


def test_nothing_maps_to_a_natural_class() -> None:
    """CLAUDE.md's locked decision: land use is functional-only and rasters own land cover. `park`,
    `forest`, `grass` and `farmland` are all in Overture's vocabulary and all deliberately unused,
    so a future edit that reaches for them fails here rather than in a validation table."""
    land_cover_values = {"park", "forest", "grass", "farmland", "meadow", "water", "wood"}
    for group in UcpConfig().semantic_groups:
        assert not land_cover_values & set(group.land_use_classes), group.name
        assert not land_cover_values & set(group.land_use_subtypes), group.name


# --------------------------------------------------------------------------------------------
# The coverage columns, which are the point
# --------------------------------------------------------------------------------------------


def test_an_untagged_city_and_an_empty_one_are_distinguishable() -> None:
    """**The reason this module exists.** Both units report `sem_lightweight_... = 0.0`; only
    `building_tag_coverage` says that one of them was never asked."""
    tagged = buildings(("residential", "apartments", (10, 10, 50, 50)))
    untagged = buildings((None, None, (110, 10, 150, 50)))
    config = UcpConfig()

    frame = semantic_metrics(
        pd.concat([tagged, untagged]).pipe(gpd.GeoDataFrame, crs=CRS),
        empty_parcels(),
        units(),
        config,
    )

    column = "sem_lightweight_buildings_of_building_area"
    assert frame.loc["a", column] == 0.0
    assert frame.loc["b", column] == 0.0
    assert frame.loc["a", "building_tag_coverage"] == pytest.approx(1.0)
    assert frame.loc["b", "building_tag_coverage"] == pytest.approx(0.0)


def test_overtures_unknown_sentinel_does_not_count_as_a_tag() -> None:
    """`unknown` is a recorded absence of knowledge, not a category. Counting it would report
    coverage the data does not have — the exact failure the column exists to prevent."""
    frame = semantic_metrics(
        buildings(("unknown", "unknown", (10, 10, 50, 50))), empty_parcels(), units(), UcpConfig()
    )

    assert frame.loc["a", "building_tag_coverage"] == pytest.approx(0.0)


def test_a_unit_with_no_buildings_gets_a_null_share_never_a_zero() -> None:
    """ "No industrial buildings here" and "no buildings here" are different statements, and the
    same distinction `building_surface_fraction` versus a null height already makes."""
    frame = semantic_metrics(
        buildings(("industrial", "industrial", (10, 10, 50, 50))),
        empty_parcels(),
        units(),
        UcpConfig(),
    )

    assert frame.loc["a", "sem_heavy_industry_buildings_of_building_area"] == pytest.approx(1.0)
    assert pd.isna(frame.loc["b", "sem_heavy_industry_buildings_of_building_area"])


def test_parcel_shares_are_dissolved_so_they_cannot_exceed_one() -> None:
    """`lczkit.cleaning.land_use` applies `make_valid` and no overlap resolution — Milan's parcels
    sum to 106.6% of its bbox — so anything dividing by unit area has to dissolve first."""
    overlapping = parcels(
        (None, "industrial", (0, 0, 100, 100)),
        (None, "industrial", (0, 0, 100, 100)),
        (None, "industrial", (0, 0, 100, 100)),
    )

    frame = semantic_metrics(
        buildings(("residential", "house", (10, 10, 20, 20))), overlapping, units(), UcpConfig()
    )

    assert frame.loc["a", "sem_heavy_industry_parcels_of_unit_area"] == pytest.approx(1.0)
    assert frame.loc["a", "land_use_coverage"] == pytest.approx(1.0)


def test_groups_are_not_a_partition_and_the_columns_do_not_sum_to_one() -> None:
    """A big-box store is genuinely evidence for both large-low-rise form and commercial function.
    Anything reading these as a composition is misreading them, and this pins that they overlap."""
    frame = semantic_metrics(
        buildings((None, "retail", (0, 0, 100, 100))), empty_parcels(), units(), UcpConfig()
    )

    assert frame.loc["a", "sem_large_lowrise_buildings_of_building_area"] == pytest.approx(1.0)
    assert frame.loc["a", "sem_commercial_buildings_of_building_area"] == pytest.approx(1.0)


def test_a_building_matches_on_subtype_or_class_not_both() -> None:
    """The two are independently nullable; a feature carrying only one is still classifiable."""
    frame = semantic_metrics(
        buildings(("industrial", None, (0, 0, 50, 100)), (None, "industrial", (50, 0, 100, 100))),
        empty_parcels(),
        units(),
        UcpConfig(),
    )

    assert frame.loc["a", "sem_heavy_industry_buildings_of_building_area"] == pytest.approx(1.0)


def test_the_column_set_follows_the_configured_groups() -> None:
    """A group added in config must appear in the output schema, not silently vanish."""
    config = UcpConfig(semantic_groups=[])

    frame = semantic_metrics(
        buildings(("residential", "house", (10, 10, 50, 50))), empty_parcels(), units(), config
    )

    assert list(frame.columns) == ["building_tag_coverage", "land_use_coverage"]
    assert group_columns(config.semantic_groups) == ("building_tag_coverage", "land_use_coverage")


# --------------------------------------------------------------------------------------------
# Against the real industrial fixture
# --------------------------------------------------------------------------------------------


def rotterdam() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    crs = local_utm_crs(INDUSTRY_BBOX)
    build = gpd.read_parquet(INDUSTRY_FIXTURES_DIR / "buildings.parquet").to_crs(crs)
    land_use = gpd.read_parquet(INDUSTRY_FIXTURES_DIR / "land_use.parquet").to_crs(crs)
    from lczkit.units.grid import GridUnits

    return build, land_use, GridUnits().generate(INDUSTRY_BBOX)


def test_heavy_industry_tracks_the_calibrated_industrial_column_without_replacing_it() -> None:
    """`industrial_fraction_of_building_area` is the column the shipped 0.45 threshold was swept
    against, so it keeps its own narrower vocabulary. `heavy_industry` is the same idea slightly
    widened, and the two must move together — if they ever diverged sharply, one of the two
    vocabularies would be wrong."""
    build, land_use, grid = rotterdam()
    config = UcpConfig()

    old = industrial_metrics(build, land_use, grid, config)
    new = semantic_metrics(build, land_use, grid, config)

    a = old["industrial_fraction_of_building_area"]
    b = new["sem_heavy_industry_buildings_of_building_area"]
    both = a.notna() & b.notna()
    assert both.sum() > 50
    # Widened, never narrowed: every value the original finds, the group finds too.
    assert (b[both] >= a[both] - 1e-9).all()
    assert a[both].corr(b[both]) > 0.99


def test_the_diagnostic_reports_coverage_by_upstream_dataset() -> None:
    """The counterpart of `source_availability`, and the same reason: the mechanism rather than
    just the outcome. Nairobi is untagged *because* its footprints were won by an attribute-less
    source."""
    build, land_use, _ = rotterdam()

    report = tag_availability(build, land_use)

    assert report.n_buildings == len(build)
    assert 0.0 <= report.tagged_area_fraction <= 1.0
    assert report.by_footprint_dataset
    assert sum(row.n_buildings for row in report.by_footprint_dataset) == len(build)
    # Sorted most-populated first, like the height diagnostic.
    counts = [row.n_buildings for row in report.by_footprint_dataset]
    assert counts == sorted(counts, reverse=True)
    assert set(report.distinct_values) == {"subtype", "class"}
    assert "unknown" not in {v.lower() for v in report.distinct_values["class"]}


def test_the_diagnostic_degrades_rather_than_raising_without_overture_columns() -> None:
    """A non-Overture `VectorSource` should produce a diagnostic saying it supplies no attributes,
    not an exception three stages in."""
    bare = gpd.GeoDataFrame(geometry=[box(0, 0, 10, 10)], crs=CRS)

    report = tag_availability(bare, None)

    assert report.n_buildings == 1
    assert report.n_with_either == 0
    assert report.tagged_area_fraction == 0.0
    assert report.distinct_values == {}


def test_no_whole_extent_union_is_taken_over_the_land_use_layer() -> None:
    """CLAUDE.md's standing anti-pattern, and this one was caught by running the diagnostic over a
    real city rather than a fixture: a global `union_all` over Overture land use is superlinear
    *and* raises `GEOSException: side location conflict` even after `make_valid`, because
    per-feature validity does not make a collection unionable. The dissolve happens after the
    clip to units, where every union is bounded by one unit's worth of parcels and is exact."""
    source = Path(__file__).resolve().parent.parent / "src" / "lczkit" / "ucp"
    for name in ("semantics.py", "tag_diagnostic.py"):
        body = (source / name).read_text(encoding="utf-8")
        code = "\n".join(
            line for line in body.splitlines() if not line.strip().startswith(("#", '"""', "*"))
        )
        assert "union_all()" not in code, name
