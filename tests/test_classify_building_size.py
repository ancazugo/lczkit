"""`mean_building_area_m2` as a metric dimension — shipped disabled, and why it exists.

LCZ 7 is *lightweight* low-rise and LCZ 8 is *large* low-rise. Nothing in the metric measured how
big a building is, and measured over built cells of four runs the two came out swapped: LCZ 8
landing on 55-93 m² footprints and LCZ 7 on 7 000-13 000 m² ones, in Berlin, Istanbul, Bogotá and
Nairobi alike. That is internally contradictory and needs no external reference to call wrong.

These tests pin two things that have to hold together: that the dimension is **completely inert**
in every shipped configuration, because neither its weight nor its bounds has been swept, and that
it **does the job it was added for** the moment a sweep turns it on. Either alone would be a weaker
statement — an inert dimension nobody has shown to work, or a working one shipped uncalibrated.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from lczkit.classify.classifier import PrototypeClassifier
from lczkit.classify.prototypes import DIMENSIONS
from lczkit.classify.weights import BERNARD2024, WeightPreset

#: A warehouse district and an informal settlement, built to be unambiguous on everything the
#: metric already measures — and to be told apart only by the size of a building.
SHED = {
    "building_surface_fraction": 0.42,
    "impervious_surface_fraction": 0.45,
    "pervious_surface_fraction": 0.13,
    "height_of_roughness_elements_m": 6.0,
    "aspect_ratio": 0.2,
    "tree_fraction": 0.0,
    "water_fraction": 0.0,
    "mean_building_area_m2": 4000.0,
}
SHACK = {**SHED, "mean_building_area_m2": 40.0}


def _units(**rows: dict[str, float]) -> pd.DataFrame:
    frame = pd.DataFrame(rows).T
    frame["industrial_fraction_of_building_area"] = 0.0
    # Zero, so the shipped LCZ 8 semantic rule cannot fire: these units are meant to be told apart
    # by building size alone, and a functional rule reaching them would decide the answer instead.
    frame["sem_large_lowrise_buildings_of_building_area"] = 0.0
    frame["sem_lightweight_buildings_of_building_area"] = 0.0
    frame.index.name = "unit_id"
    return frame


def _enabled(weight: float) -> WeightPreset:
    """`bernard2024_partial` with the building-size dimension switched on at `weight`.

    Built here rather than shipped as a third preset: a preset is a named, reproducible choice and
    this weight has not been chosen. A sweep constructs its own vectors the same way.
    """
    return WeightPreset(
        name="swept",
        built={**BERNARD2024.built, "mean_building_area_m2": weight},
        natural=dict(BERNARD2024.natural),
        description="test only",
    )


def test_the_dimension_is_inert_in_the_shipped_configuration() -> None:
    """Two units differing *only* in building area must classify identically by default.

    This is the ruling made testable. A dimension whose bounds were invented and whose weight was
    never swept must not be able to move a label, and the shipped presets are what guarantee it.
    """
    result = PrototypeClassifier().classify(_units(shed=SHED, shack=SHACK))

    assert result.loc["shed", "lcz_primary"] == result.loc["shack", "lcz_primary"]
    distances = [column for column in result.columns if column.startswith("lcz_d")]
    assert np.allclose(
        result.loc["shed", distances].to_numpy(dtype="float64"),
        result.loc["shack", distances].to_numpy(dtype="float64"),
    )


def test_a_swept_weight_separates_the_shed_from_the_shack() -> None:
    """And in the right direction: the big-footprint unit takes LCZ 8, the small one does not.

    The evidence that the dimension is worth sweeping rather than merely worth adding. Without it
    both units land on the same class, which is the inversion this exists to remove.
    """
    classifier = PrototypeClassifier()
    classifier.weights = _enabled(6.0)

    result = classifier.classify(_units(shed=SHED, shack=SHACK))

    assert result.loc["shed", "lcz_primary"] == 8
    assert result.loc["shack", "lcz_primary"] != 8


def test_a_unit_with_no_buildings_is_not_penalised_for_having_no_building_size() -> None:
    """`mean_building_area_m2` is null wherever a unit holds no building, and a null dimension
    leaves both sides of the renormalisation — so a park is not pushed anywhere by its absence,
    even with the weight turned up."""
    park = {
        "building_surface_fraction": 0.0,
        "impervious_surface_fraction": 0.02,
        "pervious_surface_fraction": 0.98,
        "height_of_roughness_elements_m": np.nan,
        "aspect_ratio": np.nan,
        "tree_fraction": 0.8,
        "water_fraction": 0.0,
        "mean_building_area_m2": np.nan,
    }
    frame = _units(park=park)

    default = PrototypeClassifier().classify(frame)
    swept = PrototypeClassifier()
    swept.weights = _enabled(6.0)

    assert swept.classify(frame).loc["park", "lcz_primary"] == default.loc["park", "lcz_primary"]


def test_the_dimension_is_in_the_metric_space_even_though_it_carries_no_weight() -> None:
    """Zero weight, not absent. It has to be a real dimension for a sweep to reach it, and the
    parameter table has to carry it — which is what makes `distances()` refuse a frame without it
    rather than quietly scoring one dimension short."""
    assert "mean_building_area_m2" in DIMENSIONS
    assert BERNARD2024.built["mean_building_area_m2"] == 0.0
