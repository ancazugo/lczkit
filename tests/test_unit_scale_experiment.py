"""The unit-scale harness' load-bearing helpers.

The script itself is not a test — `clean_vectors` on the full Berlin extent takes about ninety
seconds, and the experiment is a one-off analysis rather than a pipeline stage. What is tested here
is the pair of functions that decide whether the comparison is *fair*, because an error in either
would produce a plausible number rather than a failure:

- `project`, which puts every arm's labels on the same 100 m grid. If this leaked information —
  averaging labels, or letting a sliver decide a cell — arm B would be measured against a
  different reference population from arm A and the comparison would be meaningless.
- `raw_footprints`, arm C's input, which must not quietly do any of the cleaning it exists to
  bypass.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import MultiPolygon, Polygon, box

_CRS = "EPSG:32633"
_E, _N = 500_000.0, 5_700_000.0


def load_script() -> ModuleType:
    """Import `scripts/unit_scale_experiment.py` by path.

    By path rather than as a package: `scripts/` is deliberately not importable — it holds one-off
    analyses, not library code — and making it so to run a test would put the wrong thing on the
    package's runtime surface.
    """
    path = Path(__file__).resolve().parent.parent / "scripts" / "unit_scale_experiment.py"
    spec = importlib.util.spec_from_file_location("unit_scale_experiment", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script() -> ModuleType:
    return load_script()


def grid_units(n: int = 2) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"unit_id": [f"grid_{i}" for i in range(n)]},
        geometry=[box(_E + i * 100, _N, _E + (i + 1) * 100, _N + 100) for i in range(n)],
        crs=_CRS,
    ).set_index("unit_id")


def arm_of(script: ModuleType, name: str, units: gpd.GeoDataFrame, labels: list[int]):
    index = units.index
    return script.Arm(
        name=name,
        units=units,
        parameters=pd.DataFrame({"building_surface_fraction": [0.3] * len(index)}, index=index),
        classification=pd.DataFrame(
            {"lcz_primary": pd.Series(labels, index=index, dtype="Int8")}, index=index
        ),
        description=name,
    )


def test_a_grid_arm_is_projected_by_identity_not_by_re_aggregation(script: ModuleType) -> None:
    """Arms A and C already compute on the grid. Sending them through the overlay anyway would
    round-trip their labels through a spatial join for no reason, and any loss there would be
    charged to the arm rather than to the projection."""
    grid = grid_units()
    arm = arm_of(script, "A", grid, [2, 5])

    projected = script.project(arm, grid)

    assert projected.equals(arm.labels)


def test_enclosure_labels_reach_the_grid_by_largest_overlap(script: ModuleType) -> None:
    """Two enclosures meet inside the first cell, 70/30. The cell takes the label of the larger,
    and the second cell takes the label of the only enclosure reaching it."""
    grid = grid_units()
    enclosures = gpd.GeoDataFrame(
        {"unit_id": ["enclosure_0", "enclosure_1"]},
        geometry=[
            box(_E, _N, _E + 70, _N + 100),
            box(_E + 70, _N, _E + 200, _N + 100),
        ],
        crs=_CRS,
    ).set_index("unit_id")
    arm = arm_of(script, "B", enclosures, [2, 5])

    projected = script.project(arm, grid)

    assert projected.loc["grid_0"] == 2
    assert projected.loc["grid_1"] == 5
    assert projected.index.equals(grid.index)


def test_a_sliver_never_outvotes_the_enclosure_that_covers_the_cell(script: ModuleType) -> None:
    """Berlin's clipped enclosures are 78% sub-1000 m² street-margin slivers. If one of those
    could win a cell, arm B would be measuring the classifier on debris and its failure would say
    nothing about the unit-scale hypothesis this experiment exists to test."""
    grid = grid_units(1)
    enclosures = gpd.GeoDataFrame(
        {"unit_id": ["sliver", "block"]},
        geometry=[box(_E, _N, _E + 2, _N + 100), box(_E + 2, _N, _E + 100, _N + 100)],
        crs=_CRS,
    ).set_index("unit_id")
    arm = arm_of(script, "B", enclosures, [15, 2])

    assert script.project(arm, grid).loc["grid_0"] == 2


def test_a_cell_no_enclosure_reaches_is_null_rather_than_guessed(script: ModuleType) -> None:
    """Excluded from the agreement statistics and counted, which is what
    `AgreementReport.excluded_no_prediction` is for. A guessed label here would be indistinguishable
    from a real one in the confusion matrix."""
    grid = grid_units(2)
    enclosures = gpd.GeoDataFrame(
        {"unit_id": ["enclosure_0"]}, geometry=[box(_E, _N, _E + 100, _N + 100)], crs=_CRS
    ).set_index("unit_id")
    arm = arm_of(script, "B", enclosures, [2])

    projected = script.project(arm, grid)

    assert projected.loc["grid_0"] == 2
    assert pd.isna(projected.loc["grid_1"])


class StubSource:
    """The two calls `raw_footprints` makes on a `VectorSource`."""

    def __init__(self, buildings: gpd.GeoDataFrame) -> None:
        self._buildings = buildings

    def buildings(self, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
        del bbox
        return self._buildings


def test_raw_footprints_repairs_geometry_without_dropping_or_merging(script: ModuleType) -> None:
    """Arm C's whole claim is that nothing was removed. Validity repair and explosion are
    mechanical — an invalid or multipart footprint fails the overlay for reasons unrelated to the
    question — but a tiny building, an enormous one and two overlapping ones must all survive,
    since those are precisely what Phase 1 cleaning takes out.
    """
    bowtie = Polygon([(0, 0), (10, 10), (10, 0), (0, 10)])  # self-intersecting, invalid
    tiny = box(20, 20, 21, 21)  # 1 m2, below any min-area threshold
    huge = box(100, 100, 500, 500)  # 160,000 m2, above any max-area threshold
    overlapping = (box(50, 50, 60, 60), box(55, 55, 65, 65))
    multi = MultiPolygon([box(70, 70, 75, 75), box(80, 80, 85, 85)])
    raw = gpd.GeoDataFrame(
        geometry=[bowtie, tiny, huge, *overlapping, multi],
        crs=_CRS,
    ).to_crs("EPSG:4326")

    result = script.raw_footprints(StubSource(raw), (0.0, 0.0, 1.0, 1.0), _CRS)

    assert result.crs == _CRS
    assert (result.geom_type == "Polygon").all()
    assert result.geometry.is_valid.all()
    # 4 single-part inputs survive as themselves, the bowtie repairs into two triangles, and the
    # multipolygon explodes into two: 4 + 2 + 2.
    assert len(result) == 8
    areas = sorted(result.geometry.area.round(1))
    assert areas[0] == pytest.approx(1.0)  # the tiny building survived
    assert areas[-1] == pytest.approx(160_000.0)  # so did the huge one
    # And the overlap survived: the two 100 m2 squares still intersect.
    squares = result[result.geometry.area.round(1) == 100.0]
    assert len(squares) == 2
    assert squares.geometry.iloc[0].intersects(squares.geometry.iloc[1])


def test_the_three_arms_are_declared_with_the_control_marked_as_one(script: ModuleType) -> None:
    """Arm C is a diagnostic, never a pipeline option. Keeping that in the arm's own description
    means it travels into the JSON record and the printed table rather than living only in a
    docstring a reader of the output never sees."""
    assert {fixture.name for fixture in script.FIXTURE_CITIES} == {"berlin", "rotterdam"}
    assert script.TESTED_PARAMETER == "building_surface_fraction"
    for fixture in script.FIXTURE_CITIES:
        assert fixture.worldcover.is_file()
        assert fixture.reference.is_file()
        # `vectors` is a factory rather than a directory so the same harness runs over a live
        # `OvertureSource`; the committed fixtures still have to resolve to real files.
        assert Path(fixture.vectors.args[0]).is_dir()


def test_only_the_city_with_labelled_coverage_declares_ground_truth(script: ModuleType) -> None:
    """Berlin has So2Sat polygons and Rotterdam does not, and the difference must be structural
    rather than a caveat in prose: a `None` here is what makes the harness print that Rotterdam's
    figures are against an estimate, and what keeps a ceiling from being fabricated for it."""
    by_name = {fixture.name: fixture for fixture in script.FIXTURE_CITIES}

    assert by_name["berlin"].ground_truth is not None
    assert by_name["berlin"].ground_truth.is_file()
    assert by_name["rotterdam"].ground_truth is None


def test_a_shared_cleaning_gives_the_same_arms_as_cleaning_inline(script: ModuleType) -> None:
    """`build_arms(prepared=...)` must equal `build_arms()` — the whole before/after rests on it.

    Phase 10 scores three height cascades against one cleaning so that a difference between them
    is the cascade and nothing else. If reusing a cleaning changed anything at all, every
    before/after number in that phase would be measuring the refactor as well.
    """
    fixture = script.FIXTURE_CITIES[0]

    inline, _, inline_provenance, _ = script.build_arms(fixture)
    shared_input = script.clean_for_arms(fixture)
    shared, _, shared_provenance, _ = script.build_arms(fixture, prepared=shared_input)

    assert [arm.name for arm in shared] == [arm.name for arm in inline]
    for one, other in zip(inline, shared, strict=True):
        assert one.units.index.equals(other.units.index)
        pd.testing.assert_series_equal(one.labels, other.labels)
        pd.testing.assert_frame_equal(one.parameters, other.parameters)
    assert shared_provenance["building_area_cleaned_m2"] == pytest.approx(
        inline_provenance["building_area_cleaned_m2"]
    )
    assert shared_provenance["buildings_raw"] == inline_provenance["buildings_raw"]


def test_a_cascade_passed_in_is_the_one_that_runs(script: ModuleType) -> None:
    """Passing `tiers` must actually change the recorded provenance, not be quietly ignored.

    The failure this guards against is silent: an ignored `tiers` argument would make all three
    Phase 10 variants identical, and the phase would report a confident "no effect".
    """
    fixture = script.FIXTURE_CITIES[0]
    prepared = script.clean_for_arms(fixture)

    _, _, default_provenance, _ = script.build_arms(fixture, prepared=prepared)
    _, _, empty_provenance, _ = script.build_arms(fixture, tiers=[], prepared=prepared)

    assert default_provenance["height_sources"] == [
        "overture_height",
        "overture_num_floors",
        "unresolved",
    ]
    assert empty_provenance["height_sources"] == ["unresolved"]
    assert empty_provenance["height_fill"]["n_resolved"] == 0
