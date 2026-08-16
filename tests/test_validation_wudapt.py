"""WUDAPT training areas as a reference: cleaning, overlap resolution, and the areal reduction.

The whole module is one decision the So2Sat path did not have to make — WUDAPT polygons overlap
each other, in different classes, from different years — plus one it makes differently: the label
is assigned by *area*, not by a centroid, because WUDAPT polygons are hand-drawn and span seven
orders of magnitude in size.

These tests pin both, and pin the two traps the file carries: the stored `area` column is unusable,
and `class` does not stop at 17.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely
from conftest import FIXTURE_BBOX, HONGKONG_BBOX, LCZ_FIXTURES_DIR
from shapely.geometry import box

from lczkit.classify.labels import CODES
from lczkit.config import WudaptConfig
from lczkit.crs import local_utm_crs
from lczkit.units.grid import GridUnits
from lczkit.validation import agreement, prepare_wudapt, resolve_overlaps, wudapt_lcz
from lczkit.validation.wudapt import (
    CLASS_COLUMN,
    OVERLAP_EPS_M2,
    UNSUPPORTED_CLASSES,
    priority_order,
)

CRS = "EPSG:32633"

#: Two 100 m cells side by side, matching `test_validation_labelled.py`.
LEFT = (0.0, 0.0, 100.0, 100.0)
RIGHT = (100.0, 0.0, 200.0, 100.0)


def make_units() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"unit_id": ["left", "right"]}, geometry=[box(*LEFT), box(*RIGHT)], crs=CRS
    ).set_index("unit_id")


def make_polygons(
    *specs: tuple[int, tuple[float, float, float, float]],
    dates: list[str] | None = None,
    oa: list[float] | None = None,
    qc: str = "True",
) -> gpd.GeoDataFrame:
    """`(class, (minx, miny, maxx, maxy))` -> a WUDAPT-shaped frame in `CRS`."""
    n = len(specs)
    return gpd.GeoDataFrame(
        {
            CLASS_COLUMN: [code for code, _ in specs],
            "representative_date": dates if dates is not None else ["2020-01-01"] * n,
            "oa": oa if oa is not None else [0.7] * n,
            "qc_step1": [qc] * n,
            "qc_step2": [qc] * n,
            "qc_step3": [qc] * n,
            "license": ["CC BY-SA"] * n,
            "city": ["Testville"] * n,
            # Present and deliberately absurd: the real column is km2 in Web Mercator. Anything
            # that reads it will produce a number this wrong.
            "area": [1e9] * n,
        },
        geometry=[box(*bounds) for _, bounds in specs],
        crs=CRS,
    )


def fixture_polygons(name: str) -> gpd.GeoDataFrame:
    return gpd.read_parquet(LCZ_FIXTURES_DIR / f"wudapt_{name}.parquet")


# --------------------------------------------------------------------------------------------
# The two traps in the file itself
# --------------------------------------------------------------------------------------------


def test_the_stored_area_column_is_never_read() -> None:
    """It is km2 computed in Web Mercator — inflated by 1/cos^2(latitude), a median factor of
    1 004 995 against true area. Every filter and every statistic recomputes from the geometry, so
    replacing the column with nonsense must change nothing at all."""
    polygons = make_polygons((2, (0.0, 0.0, 50.0, 50.0)), (5, (60.0, 0.0, 100.0, 50.0)))
    corrupted = polygons.assign(area=[-1.0, np.nan])

    honest, honest_report = prepare_wudapt(polygons, crs=CRS)
    wrong, wrong_report = prepare_wudapt(corrupted, crs=CRS)

    assert honest_report.labelled_area_m2 == pytest.approx(wrong_report.labelled_area_m2)
    assert honest_report.n_kept == wrong_report.n_kept
    assert list(honest[CLASS_COLUMN]) == list(wrong[CLASS_COLUMN])


def test_classes_outside_the_demuzere_coding_are_dropped_and_counted() -> None:
    """`class` runs to 19, not 17 — 633 polygons globally. There is no lczkit definition for those
    codes, so they are dropped rather than folded into a neighbour: inventing a mapping would put a
    label into the reference that no contributor drew."""
    assert not set(UNSUPPORTED_CLASSES) & set(CODES)
    polygons = make_polygons(
        (2, (0.0, 0.0, 50.0, 50.0)),
        (UNSUPPORTED_CLASSES[0], (60.0, 0.0, 100.0, 50.0)),
        (UNSUPPORTED_CLASSES[1], (0.0, 60.0, 50.0, 100.0)),
    )

    kept, report = prepare_wudapt(polygons, crs=CRS)

    assert report.n_read == 3
    assert report.n_dropped_unsupported_class == 2
    assert list(kept[CLASS_COLUMN]) == [2]


# --------------------------------------------------------------------------------------------
# Cleaning and gating
# --------------------------------------------------------------------------------------------


def test_the_quality_gate_is_off_by_default_but_its_cost_is_reported_either_way() -> None:
    """Requiring all three QC flags costs 48.2% of the file. Reporting the pass rate whether or not
    the gate is on is what lets a caller price that without a second run."""
    polygons = pd.concat(
        [
            make_polygons((2, (0.0, 0.0, 50.0, 50.0)), qc="True"),
            make_polygons((5, (60.0, 0.0, 100.0, 50.0)), qc="False"),
        ],
        ignore_index=True,
    )
    polygons = gpd.GeoDataFrame(polygons, geometry="geometry", crs=CRS)

    _, open_gate = prepare_wudapt(polygons, crs=CRS)
    _, shut_gate = prepare_wudapt(polygons, crs=CRS, config=WudaptConfig(require_qc=True))

    assert open_gate.n_dropped_qc == 0
    assert open_gate.n_kept == 2
    assert shut_gate.n_dropped_qc == 1
    assert shut_gate.n_kept == 1
    assert open_gate.qc_pass_fraction == shut_gate.qc_pass_fraction == pytest.approx(0.5)


def test_both_spellings_of_the_quality_flags_are_understood() -> None:
    """The file encodes them as `'True'`/`'False'` *and* `'T'`/`'F'`. Parsing one spelling would
    read the other as null and gate on it silently."""
    long_form = make_polygons((2, (0.0, 0.0, 50.0, 50.0)), qc="True")
    short_form = make_polygons((2, (0.0, 0.0, 50.0, 50.0)), qc="T")

    _, long_report = prepare_wudapt(long_form, crs=CRS, config=WudaptConfig(require_qc=True))
    _, short_report = prepare_wudapt(short_form, crs=CRS, config=WudaptConfig(require_qc=True))

    assert long_report.n_kept == short_report.n_kept == 1
    assert long_report.qc_pass_fraction == short_report.qc_pass_fraction == 1.0


def test_an_unparseable_date_costs_a_polygon_its_priority_not_its_label() -> None:
    """9.7% of `representative_date` does not parse. Those polygons still describe real ground."""
    polygons = make_polygons(
        (2, (0.0, 0.0, 50.0, 50.0)), (5, (60.0, 0.0, 100.0, 50.0)), dates=["", "2020-01-01"]
    )

    kept, report = prepare_wudapt(polygons, crs=CRS)

    assert report.n_kept == 2
    assert list(priority_order(kept.to_crs(CRS)))[0] == 1  # the dated one outranks the undated


def test_a_self_intersecting_polygon_is_repaired_rather_than_dropped() -> None:
    """About 1.0% of the file self-intersects. `make_valid` recovers the ground; only geometry that
    cannot be made polygonal at all is dropped, and that is counted."""
    bowtie = shapely.Polygon([(0, 0), (100, 100), (100, 0), (0, 100)])
    polygons = make_polygons((2, (0.0, 0.0, 1.0, 1.0)))
    polygons = polygons.set_geometry(gpd.GeoSeries([bowtie], index=polygons.index, crs=CRS))

    kept, report = prepare_wudapt(polygons, crs=CRS)

    assert report.n_dropped_invalid == 0
    assert report.n_kept == 1
    assert kept.geometry.is_valid.all()


def test_min_area_drops_polygons_smaller_than_a_cell() -> None:
    """4.7% of the file is under 1000 m2 and five features have exactly zero area."""
    polygons = make_polygons((2, (0.0, 0.0, 100.0, 100.0)), (5, (150.0, 0.0, 151.0, 1.0)))

    _, report = prepare_wudapt(polygons, crs=CRS, config=WudaptConfig(min_area_m2=1000.0))

    assert report.n_dropped_area == 1
    assert report.n_kept == 1


# --------------------------------------------------------------------------------------------
# Overlap resolution
# --------------------------------------------------------------------------------------------


def test_the_more_recent_contributor_wins_contested_ground() -> None:
    """A WUDAPT polygon describes the city at `representative_date`, the dates span 1983-2025, and
    lczkit is classifying a current Overture release."""
    polygons = make_polygons(
        (2, (0.0, 0.0, 100.0, 100.0)),
        (5, (50.0, 0.0, 150.0, 100.0)),
        dates=["2005-01-01", "2023-01-01"],
    )

    resolved, report = resolve_overlaps(polygons)

    areas = dict(zip(resolved[CLASS_COLUMN], resolved.geometry.area, strict=True))
    assert areas[5] == pytest.approx(10_000.0)  # newer, keeps all of itself
    assert areas[2] == pytest.approx(5_000.0)  # older, yields the shared half
    assert report.n_conflicting_pairs == 1
    assert report.conflict_area_m2 == pytest.approx(5_000.0)


def test_accuracy_breaks_a_tie_on_date_and_the_smaller_polygon_breaks_a_tie_on_both() -> None:
    """`oa` is a property of the submission, not the polygon, which is why it ranks below recency.
    Smaller-wins-last encodes that a contributor drawing inside someone else's polygon was being
    more specific about that ground."""
    same_date = make_polygons(
        (2, (0.0, 0.0, 100.0, 100.0)),
        (5, (50.0, 0.0, 150.0, 100.0)),
        oa=[0.6, 0.9],
    )
    by_accuracy, _ = resolve_overlaps(same_date)
    assert dict(zip(by_accuracy[CLASS_COLUMN], by_accuracy.geometry.area, strict=True))[
        5
    ] == pytest.approx(10_000.0)

    same_everything = make_polygons(
        (2, (0.0, 0.0, 200.0, 100.0)),
        (5, (50.0, 0.0, 100.0, 100.0)),
    )
    by_size, _ = resolve_overlaps(same_everything)
    assert dict(zip(by_size[CLASS_COLUMN], by_size.geometry.area, strict=True))[5] == pytest.approx(
        5_000.0
    )


def test_agreeing_neighbours_are_counted_as_duplication_not_as_conflict() -> None:
    """Two contributors drawing the same class over the same ground is redundancy. Calling that a
    conflict would make the reference look far more self-contradictory than it is."""
    polygons = make_polygons(
        (2, (0.0, 0.0, 100.0, 100.0)),
        (2, (50.0, 0.0, 150.0, 100.0)),
        dates=["2005-01-01", "2023-01-01"],
    )

    _, report = resolve_overlaps(polygons)

    assert report.n_overlapping_pairs == 1
    assert report.n_conflicting_pairs == 0
    assert report.duplicate_area_m2 == pytest.approx(5_000.0)
    assert report.conflict_area_m2 == pytest.approx(0.0)


def test_every_drawn_square_metre_is_kept_duplicated_or_contested() -> None:
    """The invariant behind the whole report: `raw = labelled + duplicate + conflict`. Ground that
    fell out of all three would be ground the resolution lost without saying so."""
    for name, bbox in (("berlin", FIXTURE_BBOX), ("hongkong", HONGKONG_BBOX)):
        raw = fixture_polygons(name)
        crs = local_utm_crs(bbox)
        repaired = shapely.force_2d(shapely.make_valid(raw.to_crs(crs).geometry.to_numpy()))

        _, report = prepare_wudapt(raw, crs=crs)

        drawn = float(shapely.area(repaired).sum())
        accounted = report.labelled_area_m2 + report.duplicate_area_m2 + report.conflict_area_m2
        assert accounted == pytest.approx(drawn, rel=1e-9), name


def test_resolved_polygons_no_longer_share_area() -> None:
    """The point of the resolution. Asserted on *area* rather than on the `overlaps` predicate,
    which still fires on the coordinate-noise slivers `difference` leaves behind — measured at
    around 1e-8 m2, a hundredth of a square micrometre."""
    for name, bbox in (("berlin", FIXTURE_BBOX), ("hongkong", HONGKONG_BBOX)):
        resolved, _ = prepare_wudapt(fixture_polygons(name), crs=local_utm_crs(bbox))

        geometry = resolved.geometry.to_numpy()
        tree = shapely.STRtree(geometry)
        shared = 0.0
        for position, geom in enumerate(geometry):
            others = tree.query(geom, predicate="intersects")
            others = others[others > position]
            if others.size:
                shared += float(
                    shapely.area(shapely.intersection(geom, shapely.union_all(geometry[others])))
                )
        assert shared < OVERLAP_EPS_M2 * len(geometry), name


def test_a_polygon_entirely_covered_by_a_better_one_is_dropped() -> None:
    polygons = make_polygons(
        (2, (0.0, 0.0, 100.0, 100.0)),
        (5, (25.0, 25.0, 75.0, 75.0)),
        dates=["2023-01-01", "2005-01-01"],
    )

    resolved, _ = resolve_overlaps(polygons)

    assert list(resolved[CLASS_COLUMN]) == [2]


# --------------------------------------------------------------------------------------------
# The reduction onto units
# --------------------------------------------------------------------------------------------


def test_the_label_is_the_class_holding_most_of_the_unit() -> None:
    """Areal, not centroid-anchored: a WUDAPT polygon is a region, and the question a unit asks of
    it is how much of the unit it covers."""
    polygons = make_polygons((2, (0.0, 0.0, 70.0, 100.0)), (5, (70.0, 0.0, 100.0, 100.0)))

    result, match = wudapt_lcz(make_units(), polygons)

    assert result.loc["left", "reference_lcz"] == 2
    assert result.loc["left", "reference_coverage"] == pytest.approx(1.0)
    assert result.loc["left", "reference_majority_fraction"] == pytest.approx(0.7)
    assert match.n_units_multi_label == 1


def test_coverage_is_fractional_here_unlike_the_so2sat_path() -> None:
    """`labelled_lcz` reports a binary 1.0/0.0 because its patches are a sample. WUDAPT polygons
    tile ground, so a half-covered unit is a genuinely half-observed unit and
    `min_reference_coverage` must be able to see that."""
    polygons = make_polygons((2, (0.0, 0.0, 100.0, 40.0)))

    result, _ = wudapt_lcz(make_units(), polygons)

    assert result.loc["left", "reference_coverage"] == pytest.approx(0.4)
    assert result.loc["left", "reference_majority_fraction"] == pytest.approx(1.0)


def test_a_unit_no_polygon_reaches_gets_a_null_label_and_zero_coverage() -> None:
    """Never a sentinel — the same contract `reference_lcz` and `labelled_lcz` hold."""
    result, match = wudapt_lcz(make_units(), make_polygons((2, (0.0, 0.0, 100.0, 100.0))))

    assert pd.isna(result.loc["right", "reference_lcz"])
    assert result.loc["right", "reference_coverage"] == 0.0
    assert pd.isna(result.loc["right", "reference_majority_fraction"])
    assert match.n_units_labelled == 1


def test_the_column_contract_matches_the_other_two_references() -> None:
    """`agreement()` consumes any of the three without knowing which, so the three must agree on
    names and dtypes exactly."""
    from lczkit.validation.labelled import COLUMNS as LABELLED_COLUMNS
    from lczkit.validation.reference import COLUMNS as REFERENCE_COLUMNS
    from lczkit.validation.wudapt import COLUMNS as WUDAPT_COLUMNS

    assert WUDAPT_COLUMNS == LABELLED_COLUMNS == REFERENCE_COLUMNS

    result, _ = wudapt_lcz(make_units(), make_polygons((2, (0.0, 0.0, 100.0, 100.0))))
    assert list(result.columns) == list(WUDAPT_COLUMNS)
    assert result["reference_lcz"].dtype == "Int8"


def test_an_empty_reference_produces_the_schema_rather_than_raising() -> None:
    """A city window WUDAPT never reached is a legitimate state, and it must be visible as zero
    labelled units rather than as an exception three stages later."""
    empty = make_polygons((2, (0.0, 0.0, 1.0, 1.0))).iloc[:0]

    result, match = wudapt_lcz(make_units(), empty)

    assert list(result.columns) == [
        "reference_lcz",
        "reference_coverage",
        "reference_majority_fraction",
    ]
    assert result["reference_lcz"].isna().all()
    assert match.n_units_labelled == 0


def test_a_missing_class_column_is_refused_by_name() -> None:
    polygons = make_polygons((2, (0.0, 0.0, 100.0, 100.0))).rename(columns={CLASS_COLUMN: "lcz"})

    with pytest.raises(ValueError, match="class"):
        wudapt_lcz(make_units(), polygons)


# --------------------------------------------------------------------------------------------
# The fixtures, end to end
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("name", "bbox"), [("berlin", FIXTURE_BBOX), ("hongkong", HONGKONG_BBOX)])
def test_the_fixture_labels_a_grid_and_feeds_agreement(name: str, bbox: tuple) -> None:
    """The whole path, on real contributor data: read, clean, resolve, reduce, score."""
    units = GridUnits().generate(bbox)
    resolved, selection = prepare_wudapt(fixture_polygons(name), crs=units.crs)
    table, match = wudapt_lcz(units, resolved)

    assert selection.n_kept > 0
    assert selection.licences  # read from the data, not assumed
    assert selection.date_min is not None and selection.date_max is not None
    assert match.n_units_labelled > 0
    assert set(table["reference_lcz"].dropna().astype(int)) <= set(CODES)
    assert (table["reference_coverage"] <= 1.0).all()

    predicted = pd.Series(2, index=units.index, dtype="Int8")
    report = agreement(
        predicted,
        table["reference_lcz"],
        units.geometry.area,
        coverage=table["reference_coverage"],
        reference_file=f"wudapt_{name}.parquet",
    )
    assert report.reference_file == f"wudapt_{name}.parquet"
    assert report.n_compared > 0


def test_the_hong_kong_fixture_carries_the_states_the_cleaning_exists_for() -> None:
    """A fixture that never exercises a branch tests nothing about it. This one holds overlapping
    polygons in disagreeing classes, several submissions, and two self-intersections."""
    raw = fixture_polygons("hongkong")
    assert int((~raw.is_valid).sum()) == 2
    assert raw["submission_id"].nunique() > 1

    _, report = prepare_wudapt(raw, crs=local_utm_crs(HONGKONG_BBOX))

    assert report.n_overlapping_pairs > 0
    assert report.n_conflicting_pairs > 0
    assert report.conflict_area_m2 > 0.0
    assert len(report.licences) == 2
