"""Reducing labelled LCZ patches to one ground-truth label per unit.

The whole reduction is one decision — anchor the label on the patch *centre*, not on its area —
and these tests pin what that decision buys and what it costs. So2Sat patches are 320 m squares on
a 100 m stride, so they overlap each other about sevenfold; the centre rule is what keeps a single
patch from labelling nine cells and a single cell from receiving nine votes.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from conftest import FIXTURE_BBOX, LCZ_FIXTURES_DIR
from shapely.geometry import box

from lczkit.classify.labels import CODES
from lczkit.units.grid import GridUnits
from lczkit.validation import labelled_lcz
from lczkit.validation.labelled import LABEL_COLUMN

CRS = "EPSG:32633"

#: Two 100 m cells side by side.
LEFT = (0.0, 0.0, 100.0, 100.0)
RIGHT = (100.0, 0.0, 200.0, 100.0)


def make_units() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"unit_id": ["left", "right"]}, geometry=[box(*LEFT), box(*RIGHT)], crs=CRS
    ).set_index("unit_id")


def make_patches(*specs: tuple[int, float, float, float]) -> gpd.GeoDataFrame:
    """`(class, centre_x, centre_y, half_width)` -> a patch frame in `CRS`."""
    return gpd.GeoDataFrame(
        {LABEL_COLUMN: [code for code, _, _, _ in specs]},
        geometry=[box(x - h, y - h, x + h, y + h) for _, x, y, h in specs],
        crs=CRS,
    )


def test_a_patch_labels_the_unit_holding_its_centre_not_the_ones_it_overlaps() -> None:
    """The point of the rule. This patch is 320 m across and covers both cells completely; it is
    one observation, and it is an observation about where its centre is."""
    patches = make_patches((2, 50.0, 50.0, 160.0))

    result, match = labelled_lcz(make_units(), patches)

    assert result.loc["left", "reference_lcz"] == 2
    assert pd.isna(result.loc["right", "reference_lcz"])
    assert match.n_centres_matched == 1


def test_a_unit_with_no_centre_gets_a_null_label_and_zero_coverage() -> None:
    """Never a sentinel: "no ground truth here" and "ground truth says class 0" must not look the
    same, and `agreement()` excludes on coverage rather than on the label."""
    result, match = labelled_lcz(make_units(), make_patches((5, 50.0, 50.0, 20.0)))

    assert pd.isna(result.loc["right", "reference_lcz"])
    assert result.loc["right", "reference_coverage"] == 0.0
    assert result.loc["left", "reference_coverage"] == 1.0
    assert match.n_units_labelled == 1


def test_a_centre_outside_every_unit_is_counted_rather_than_dropped_silently() -> None:
    """Patches are kept whole and selected by intersection, so a fixture legitimately carries
    patches centred outside the study area. That is not an error, but it is not nothing either —
    a run where most centres miss is a misaligned run."""
    patches = make_patches((2, 50.0, 50.0, 20.0), (5, -50.0, 50.0, 20.0))

    result, match = labelled_lcz(make_units(), patches)

    assert match.n_patches == 2
    assert match.n_centres_matched == 1
    assert match.n_centres_unmatched == 1
    assert result["reference_lcz"].notna().sum() == 1


def test_several_centres_in_one_unit_are_decided_by_majority_with_its_support_reported() -> None:
    """Only reachable on units larger than the patch stride — enclosures, not the 100 m grid. The
    majority fraction is what says whether such a unit was cleanly labelled or split."""
    patches = make_patches((2, 20.0, 20.0, 10.0), (2, 50.0, 50.0, 10.0), (5, 80.0, 80.0, 10.0))

    result, match = labelled_lcz(make_units(), patches)

    assert result.loc["left", "reference_lcz"] == 2
    assert result.loc["left", "reference_majority_fraction"] == pytest.approx(2 / 3)
    assert match.n_units_multi_label == 1


def test_a_centre_on_a_shared_boundary_labels_neither_unit() -> None:
    """`within`, not `intersects`. Counting it in both would let one patch label two cells, which
    is exactly the double counting the centre rule exists to avoid."""
    result, match = labelled_lcz(make_units(), make_patches((2, 100.0, 50.0, 10.0)))

    assert result["reference_lcz"].isna().all()
    assert match.n_centres_unmatched == 1


def test_patches_are_reprojected_before_the_centroid_is_taken() -> None:
    """The centroid of a lat/lon polygon is not the projection of the centroid, and this one
    decides which cell the label lands in. Fixtures are stored in EPSG:4326 like every other
    vector fixture, so this path is the normal one rather than an edge case."""
    projected = make_patches((2, 50.0, 50.0, 20.0))

    result, _ = labelled_lcz(make_units(), projected.to_crs("EPSG:4326"))

    assert result.loc["left", "reference_lcz"] == 2


def test_a_missing_class_column_is_refused_by_name() -> None:
    patches = make_patches((2, 50.0, 50.0, 20.0)).rename(columns={LABEL_COLUMN: "lcz"})

    with pytest.raises(ValueError, match="LCZ_class"):
        labelled_lcz(make_units(), patches)


def test_the_berlin_fixture_maps_one_patch_centre_to_one_grid_cell() -> None:
    """The measurement the design rests on, asserted against the committed fixture: 473 So2Sat
    patches over the Berlin bbox, 438 centres, **438 distinct cells, no cell labelled twice and no
    centre ambiguous**. It holds because the So2Sat patch grid and `GridUnits` are both aligned to
    the local UTM origin at 100 m. If a future fixture breaks that alignment this fails here rather
    than degrading a headline figure quietly.
    """
    units = GridUnits().generate(FIXTURE_BBOX)
    patches = gpd.read_parquet(LCZ_FIXTURES_DIR / "so2sat_berlin.parquet")

    result, match = labelled_lcz(units, patches)

    assert match.n_patches == 473
    assert match.n_centres_matched == 438
    assert match.n_centres_ambiguous == 0
    assert match.n_units_labelled == 438
    assert match.n_units_multi_label == 0
    assert (result["reference_majority_fraction"].dropna() == 1.0).all()

    # So2Sat's own coding is Demuzere's: 1-10 built, 11-17 for A-G. No translation table, and this
    # is what says so — a mismatch would silently compare class 11 against class A.
    present = set(result["reference_lcz"].dropna().astype(int))
    assert present <= set(CODES)
    assert present == {2, 5}
