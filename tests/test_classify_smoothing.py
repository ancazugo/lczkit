"""`modal_filter` — the minimum mapping unit, shipped disabled.

Every unit in this package is classified independently of its neighbours, which is why an isolated
1 ha cell can carry a label the fabric around it does not. The LCZ literature's answer is a spatial
filter and lczkit has never had one; these tests pin the behaviour so a sweep can turn it on
knowing exactly what it does.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from lczkit.classify.rules import ROUTE_BUILT, ROUTE_SMOOTHED
from lczkit.classify.smoothing import modal_filter


def grid(side: int) -> gpd.GeoDataFrame:
    """A `side` x `side` grid of 100 m cells, indexed like the pipeline's."""
    cells = {
        f"grid_{x}_{y}": shapely.box(x * 100, y * 100, x * 100 + 100, y * 100 + 100)
        for x in range(side)
        for y in range(side)
    }
    frame = gpd.GeoDataFrame(
        {"unit_id": list(cells)}, geometry=gpd.GeoSeries(list(cells.values()), crs="EPSG:32633")
    ).set_index("unit_id")
    return frame


def labels(units: gpd.GeoDataFrame, odd_one_out: str | None, sea: int = 2, odd: int = 8):
    values = pd.Series(sea, index=units.index, dtype="int64")
    if odd_one_out is not None:
        values[odd_one_out] = odd
    return pd.DataFrame(
        {
            "lcz_primary": values,
            "label_route": pd.Categorical(
                [ROUTE_BUILT] * len(units), categories=[ROUTE_BUILT, ROUTE_SMOOTHED]
            ),
            "lcz10_rule_applied": False,
            "semantic_rule_applied": False,
        },
        index=units.index,
    )


def test_the_filter_is_off_by_default_and_says_so() -> None:
    """A threshold that has not been swept must not move a label. `enabled` is what makes "never
    fired" and "never configured" distinguishable in the report."""
    units = grid(3)

    out, report = modal_filter(units, labels(units, "grid_1_1"))

    assert report.enabled is False
    assert report.n_relabelled == 0
    assert out["lcz_primary"].equals(labels(units, "grid_1_1")["lcz_primary"])


def test_an_isolated_cell_takes_the_label_of_the_fabric_around_it() -> None:
    """The salt-and-pepper case the filter exists for: one LCZ 8 cell inside a field of LCZ 2."""
    units = grid(3)

    out, report = modal_filter(units, labels(units, "grid_1_1"), enabled=True)

    assert out.loc["grid_1_1", "lcz_primary"] == 2
    assert out.loc["grid_1_1", "label_route"] == ROUTE_SMOOTHED
    assert report.n_relabelled == 1


def test_a_functionally_assigned_label_is_never_smoothed_away() -> None:
    """An isolated LCZ 10 cell is a claim about an industrial parcel, not morphological noise.

    Smoothing it would silently undo the one part of the classifier that reads the data directly,
    and its threshold is the only one in the package that *has* been swept.
    """
    units = grid(3)
    frame = labels(units, "grid_1_1", odd=10)
    frame.loc["grid_1_1", "lcz10_rule_applied"] = True

    out, report = modal_filter(units, frame, enabled=True)

    assert out.loc["grid_1_1", "lcz_primary"] == 10
    assert report.n_relabelled == 0
    assert report.n_protected == 1


def test_a_uniform_map_is_left_completely_alone() -> None:
    units = grid(3)

    out, report = modal_filter(units, labels(units, None), enabled=True)

    assert report.n_relabelled == 0
    assert (out["label_route"] == ROUTE_BUILT).all()


def test_a_block_of_like_cells_survives_because_it_is_not_isolated() -> None:
    """The filter removes single cells, not small regions — a 2x2 block of one class inside
    another is a real patch at this scale and must not be erased."""
    units = grid(4)
    frame = labels(units, None)
    block = ["grid_1_1", "grid_1_2", "grid_2_1", "grid_2_2"]
    frame.loc[block, "lcz_primary"] = 8

    out, report = modal_filter(units, frame, enabled=True, min_like_neighbours=2)

    assert (out.loc[block, "lcz_primary"] == 8).all()
    assert report.n_relabelled == 0


def test_the_pass_reads_one_snapshot_so_the_result_does_not_depend_on_visit_order() -> None:
    """Two isolated cells adjacent to each other must both be judged against the *original* map.

    Applying reassignments in sequence would let the first change decide the second, and the answer
    would then depend on which unit_id sorted first — a silent dependence on naming.
    """
    units = grid(4)
    frame = labels(units, None)
    frame.loc[["grid_1_1", "grid_2_2"], "lcz_primary"] = 8

    forward, first = modal_filter(units, frame, enabled=True)
    reversed_units = units.iloc[::-1]
    backward, second = modal_filter(reversed_units, frame.loc[reversed_units.index], enabled=True)

    assert first.n_relabelled == second.n_relabelled
    assert forward["lcz_primary"].sort_index().equals(backward["lcz_primary"].sort_index())


def test_a_null_label_is_left_null_rather_than_given_a_neighbour_s() -> None:
    """A unit the metric could not score is unclassifiable. Filling it from its surroundings would
    invent a label from no measurement at all, which is the opposite of what this package does."""
    units = grid(3)
    frame = labels(units, None)
    frame["lcz_primary"] = frame["lcz_primary"].astype("float64")
    frame.loc["grid_1_1", "lcz_primary"] = np.nan

    out, report = modal_filter(units, frame, enabled=True)

    assert pd.isna(out.loc["grid_1_1", "lcz_primary"])
    assert report.n_relabelled == 0
