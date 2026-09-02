"""What every morphometric attribute column means, in what unit, from which source.

Reuses `lczkit.ucp.registry.ParameterSpec` rather than duplicating it — a column's shape (name,
label, unit, description, reference) doesn't change because the module computing it does. Every
one of the 107 primary attributes here has a `reference` of `MOMEPY` (the formula and, where the
paper's own choice of which momepy call and which scale to use is what's being credited,
`MAJER_2026`) or `COMPUTED_HERE` for the two lczkit-defined quantities (`area_*`,
`coverage_area_ratio_etc`) that have no separate published definition beyond arithmetic.

Generated against `docs/references/tables/majer_2026_morphometrics_menu.md` — every `name` below
must appear as a row `name` in that table, and `tests/test_morphometrics_registry_matches_menu.py`
asserts it does, cell for cell, so the two cannot silently drift apart.
"""

from __future__ import annotations

from collections.abc import Iterable

from lczkit.ucp.registry import COMPUTED_HERE, MOMEPY, ParameterSpec

MAJER_2026 = "arXiv:2603.00132"
"""Majer & Fleischmann (2026), "Predicting Local Climate Zones using Urban Morphometrics and
Satellite Imagery", arXiv. Credited where the paper's own choice of scale or neighbourhood
(rather than momepy's formula itself) is what a column represents — every weighted variant, and
the two lczkit-computed granularity/coverage quantities the paper specifies without naming a
momepy function."""


PARAMETERS: tuple[ParameterSpec, ...] = (
    ParameterSpec(
        name="area_building",
        label="Building footprint area",
        unit="m2",
        description="Building footprint area (`geometry.area`).",
        reference=COMPUTED_HERE,
    ),
    ParameterSpec(
        name="area_etc",
        label="ETC area",
        unit="m2",
        description="Enclosed tessellation cell area (`geometry.area`).",
        reference=COMPUTED_HERE,
    ),
    ParameterSpec(
        name="courtyard_area_building",
        label="Building courtyard area",
        unit="m2",
        description=(
            "Area of holes (courtyards) within the building footprint (`momepy.courtyard_area`). "
            "Null for a MultiPolygon building: momepy's formula calls "
            "`shapely.get_exterior_ring`, defined only for a single Polygon, and returns a "
            "nonsensical negative value for a MultiPolygon rather than raising."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="courtyard_index_building",
        label="Building courtyard index",
        unit="fraction",
        description=(
            "Courtyard area over total footprint area (`momepy.courtyard_index`). Null under the "
            "same MultiPolygon condition as `courtyard_area_building`."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="perimeter_wall_building",
        label="Perimeter wall length",
        unit="m",
        description=(
            "Perimeter length of the structure formed by joining contiguous buildings "
            "(`momepy.perimeter_wall`, queen contiguity)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="longest_axis_length_building",
        label="Longest axis length (building)",
        unit="m",
        description=(
            "Diameter of the minimal bounding circle around the geometry "
            "(`momepy.longest_axis_length`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="longest_axis_length_etc",
        label="Longest axis length (ETC)",
        unit="m",
        description=(
            "Diameter of the minimal bounding circle around the geometry "
            "(`momepy.longest_axis_length`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="circular_compactness_building",
        label="Circular compactness (building)",
        unit="fraction",
        description=(
            "Area over the area of the minimal enclosing circle (`momepy.circular_compactness`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="circular_compactness_etc",
        label="Circular compactness (ETC)",
        unit="fraction",
        description=(
            "Area over the area of the minimal enclosing circle (`momepy.circular_compactness`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="square_compactness_building",
        label="Square compactness (building)",
        unit="dimensionless",
        description=(
            "(4*sqrt(area)/perimeter)^2 (`momepy.square_compactness`). Exactly 1 for a perfect "
            "square; shapes rounder than a square exceed 1, so this is not bounded above."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="square_compactness_etc",
        label="Square compactness (ETC)",
        unit="dimensionless",
        description=(
            "(4*sqrt(area)/perimeter)^2 (`momepy.square_compactness`). Exactly 1 for a perfect "
            "square; shapes rounder than a square exceed 1, so this is not bounded above."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="compactness_weighted_axis_building",
        label="Compactness-weighted axis (building)",
        unit="m",
        description=(
            "Longest axis length scaled by a squareness term (`momepy.compactness_weighted_axis`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="compactness_weighted_axis_etc",
        label="Compactness-weighted axis (ETC)",
        unit="m",
        description=(
            "Longest axis length scaled by a squareness term (`momepy.compactness_weighted_axis`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="convexity_building",
        label="Convexity (building)",
        unit="fraction",
        description="Area over convex-hull area (`momepy.convexity`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="convexity_etc",
        label="Convexity (ETC)",
        unit="fraction",
        description="Area over convex-hull area (`momepy.convexity`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="elongation_building",
        label="Elongation (building)",
        unit="fraction",
        description=(
            "Ratio of the minimum rotated rectangle's shorter to longer side (`momepy.elongation`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="elongation_etc",
        label="Elongation (ETC)",
        unit="fraction",
        description=(
            "Ratio of the minimum rotated rectangle's shorter to longer side (`momepy.elongation`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="equivalent_rectangular_index_building",
        label="Equivalent rectangular index (building)",
        unit="dimensionless",
        description=(
            "Area/perimeter compared to an equal-area rectangle's "
            "(`momepy.equivalent_rectangular_index`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="equivalent_rectangular_index_etc",
        label="Equivalent rectangular index (ETC)",
        unit="dimensionless",
        description=(
            "Area/perimeter compared to an equal-area rectangle's "
            "(`momepy.equivalent_rectangular_index`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="facade_ratio_building",
        label="Facade ratio (building)",
        unit="m",
        description="Area over perimeter (`momepy.facade_ratio`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="facade_ratio_etc",
        label="Facade ratio (ETC)",
        unit="m",
        description="Area over perimeter (`momepy.facade_ratio`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="fractal_dimension_building",
        label="Fractal dimension (building)",
        unit="dimensionless",
        description="2*log(perimeter/4) over log(area) (`momepy.fractal_dimension`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="fractal_dimension_etc",
        label="Fractal dimension (ETC)",
        unit="dimensionless",
        description="2*log(perimeter/4) over log(area) (`momepy.fractal_dimension`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="rectangularity_building",
        label="Rectangularity (building)",
        unit="fraction",
        description="Area over minimum-bounding-rectangle area (`momepy.rectangularity`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="rectangularity_etc",
        label="Rectangularity (ETC)",
        unit="fraction",
        description="Area over minimum-bounding-rectangle area (`momepy.rectangularity`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="shape_index_building",
        label="Shape index (building)",
        unit="fraction",
        description="sqrt(area/pi) over half the longest axis (`momepy.shape_index`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="shape_index_etc",
        label="Shape index (ETC)",
        unit="fraction",
        description="sqrt(area/pi) over half the longest axis (`momepy.shape_index`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="perimeter_wall_building_w100m",
        label="Perimeter wall length (100 m weighted)",
        unit="m",
        description=(
            "`perimeter_wall_building`, area-weighted mean over buildings within 100 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="perimeter_wall_building_w200m",
        label="Perimeter wall length (200 m weighted)",
        unit="m",
        description=(
            "`perimeter_wall_building`, area-weighted mean over buildings within 200 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="longest_axis_length_building_w100m",
        label="Longest axis length (building, 100 m weighted)",
        unit="m",
        description=(
            "`longest_axis_length_building`, area-weighted mean over buildings within 100 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="longest_axis_length_building_w200m",
        label="Longest axis length (building, 200 m weighted)",
        unit="m",
        description=(
            "`longest_axis_length_building`, area-weighted mean over buildings within 200 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="longest_axis_length_etc_w3steps",
        label="Longest axis length (ETC, 3-step weighted)",
        unit="m",
        description=(
            "`longest_axis_length_etc`, area-weighted mean over ETCs within 3 topological steps "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="circular_compactness_building_w100m",
        label="Circular compactness (building, 100 m weighted)",
        unit="fraction",
        description=(
            "`circular_compactness_building`, area-weighted mean over buildings within 100 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="circular_compactness_building_w200m",
        label="Circular compactness (building, 200 m weighted)",
        unit="fraction",
        description=(
            "`circular_compactness_building`, area-weighted mean over buildings within 200 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="circular_compactness_etc_w3steps",
        label="Circular compactness (ETC, 3-step weighted)",
        unit="fraction",
        description=(
            "`circular_compactness_etc`, area-weighted mean over ETCs within 3 topological steps "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="square_compactness_building_w100m",
        label="Square compactness (building, 100 m weighted)",
        unit="dimensionless",
        description=(
            "`square_compactness_building`, area-weighted mean over buildings within 100 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="square_compactness_building_w200m",
        label="Square compactness (building, 200 m weighted)",
        unit="dimensionless",
        description=(
            "`square_compactness_building`, area-weighted mean over buildings within 200 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="square_compactness_etc_w3steps",
        label="Square compactness (ETC, 3-step weighted)",
        unit="dimensionless",
        description=(
            "`square_compactness_etc`, area-weighted mean over ETCs within 3 topological steps "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="compactness_weighted_axis_building_w100m",
        label="Compactness-weighted axis (building, 100 m weighted)",
        unit="m",
        description=(
            "`compactness_weighted_axis_building`, area-weighted mean over buildings within 100 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="compactness_weighted_axis_building_w200m",
        label="Compactness-weighted axis (building, 200 m weighted)",
        unit="m",
        description=(
            "`compactness_weighted_axis_building`, area-weighted mean over buildings within 200 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="compactness_weighted_axis_etc_w3steps",
        label="Compactness-weighted axis (ETC, 3-step weighted)",
        unit="m",
        description=(
            "`compactness_weighted_axis_etc`, area-weighted mean over ETCs within 3 topological "
            "steps (`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="convexity_building_w100m",
        label="Convexity (building, 100 m weighted)",
        unit="fraction",
        description=(
            "`convexity_building`, area-weighted mean over buildings within 100 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="convexity_building_w200m",
        label="Convexity (building, 200 m weighted)",
        unit="fraction",
        description=(
            "`convexity_building`, area-weighted mean over buildings within 200 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="convexity_etc_w3steps",
        label="Convexity (ETC, 3-step weighted)",
        unit="fraction",
        description=(
            "`convexity_etc`, area-weighted mean over ETCs within 3 topological steps "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="elongation_building_w100m",
        label="Elongation (building, 100 m weighted)",
        unit="fraction",
        description=(
            "`elongation_building`, area-weighted mean over buildings within 100 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="elongation_building_w200m",
        label="Elongation (building, 200 m weighted)",
        unit="fraction",
        description=(
            "`elongation_building`, area-weighted mean over buildings within 200 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="elongation_etc_w3steps",
        label="Elongation (ETC, 3-step weighted)",
        unit="fraction",
        description=(
            "`elongation_etc`, area-weighted mean over ETCs within 3 topological steps "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="equivalent_rectangular_index_building_w100m",
        label="Equivalent rectangular index (building, 100 m weighted)",
        unit="dimensionless",
        description=(
            "`equivalent_rectangular_index_building`, area-weighted mean over buildings within 100 "
            "m (`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="equivalent_rectangular_index_building_w200m",
        label="Equivalent rectangular index (building, 200 m weighted)",
        unit="dimensionless",
        description=(
            "`equivalent_rectangular_index_building`, area-weighted mean over buildings within 200 "
            "m (`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="equivalent_rectangular_index_etc_w3steps",
        label="Equivalent rectangular index (ETC, 3-step weighted)",
        unit="dimensionless",
        description=(
            "`equivalent_rectangular_index_etc`, area-weighted mean over ETCs within 3 topological "
            "steps (`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="facade_ratio_building_w100m",
        label="Facade ratio (building, 100 m weighted)",
        unit="m",
        description=(
            "`facade_ratio_building`, area-weighted mean over buildings within 100 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="facade_ratio_building_w200m",
        label="Facade ratio (building, 200 m weighted)",
        unit="m",
        description=(
            "`facade_ratio_building`, area-weighted mean over buildings within 200 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="facade_ratio_etc_w3steps",
        label="Facade ratio (ETC, 3-step weighted)",
        unit="m",
        description=(
            "`facade_ratio_etc`, area-weighted mean over ETCs within 3 topological steps "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="fractal_dimension_building_w100m",
        label="Fractal dimension (building, 100 m weighted)",
        unit="dimensionless",
        description=(
            "`fractal_dimension_building`, area-weighted mean over buildings within 100 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="fractal_dimension_building_w200m",
        label="Fractal dimension (building, 200 m weighted)",
        unit="dimensionless",
        description=(
            "`fractal_dimension_building`, area-weighted mean over buildings within 200 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="fractal_dimension_etc_w3steps",
        label="Fractal dimension (ETC, 3-step weighted)",
        unit="dimensionless",
        description=(
            "`fractal_dimension_etc`, area-weighted mean over ETCs within 3 topological steps "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="rectangularity_building_w100m",
        label="Rectangularity (building, 100 m weighted)",
        unit="fraction",
        description=(
            "`rectangularity_building`, area-weighted mean over buildings within 100 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="rectangularity_building_w200m",
        label="Rectangularity (building, 200 m weighted)",
        unit="fraction",
        description=(
            "`rectangularity_building`, area-weighted mean over buildings within 200 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="rectangularity_etc_w3steps",
        label="Rectangularity (ETC, 3-step weighted)",
        unit="fraction",
        description=(
            "`rectangularity_etc`, area-weighted mean over ETCs within 3 topological steps "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="shape_index_building_w100m",
        label="Shape index (building, 100 m weighted)",
        unit="fraction",
        description=(
            "`shape_index_building`, area-weighted mean over buildings within 100 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="shape_index_building_w200m",
        label="Shape index (building, 200 m weighted)",
        unit="fraction",
        description=(
            "`shape_index_building`, area-weighted mean over buildings within 200 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="shape_index_etc_w3steps",
        label="Shape index (ETC, 3-step weighted)",
        unit="fraction",
        description=(
            "`shape_index_etc`, area-weighted mean over ETCs within 3 topological steps "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="building_adjacency_200m",
        label="Building adjacency (200 m)",
        unit="fraction",
        description=(
            "Ratio of joined built-up structures to buildings within a 200 m neighbourhood "
            "(`momepy.building_adjacency`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="mean_interbuilding_distance_200m",
        label="Mean interbuilding distance (200 m)",
        unit="m",
        description=(
            "Mean distance between adjacent buildings within a 200 m neighbourhood "
            "(`momepy.mean_interbuilding_distance`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="shared_walls_building",
        label="Shared walls length",
        unit="m",
        description="Length of walls shared with adjacent buildings (`momepy.shared_walls`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="street_alignment_building",
        label="Street alignment",
        unit="dimensionless",
        description=(
            "Deviation, in degrees, of the building's orientation from its nearest street's "
            "orientation (`momepy.street_alignment`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="street_alignment_building_w100m",
        label="Street alignment (100 m weighted)",
        unit="dimensionless",
        description=(
            "`street_alignment_building`, area-weighted mean over buildings within 100 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="street_alignment_building_w200m",
        label="Street alignment (200 m weighted)",
        unit="dimensionless",
        description=(
            "`street_alignment_building`, area-weighted mean over buildings within 200 m "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="coverage_area_ratio_etc",
        label="Coverage area ratio",
        unit="dimensionless",
        description=(
            "Building footprint area over its own ETC's area. Usually in [0, 1] but not "
            "guaranteed to be: momepy's tessellation shrink/segment step does not guarantee a "
            "cell fully contains the building that seeded it (measured on 6.4% of ETCs in the "
            "Hong Kong fixture)."
        ),
        reference=COMPUTED_HERE,
    ),
    ParameterSpec(
        name="coverage_area_ratio_etc_w3steps",
        label="Coverage area ratio (3-step weighted)",
        unit="dimensionless",
        description=(
            "`coverage_area_ratio_etc`, area-weighted mean over ETCs within 3 topological steps "
            "(`momepy.weighted_character`)."
        ),
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="etc_granularity_1step",
        label="ETC granularity",
        unit="m2",
        description="Sum of ETC area within 1 topological step, the ETC's own area included.",
        reference=MAJER_2026,
    ),
    ParameterSpec(
        name="neighbors_building_20m",
        label="Neighbouring buildings (20m)",
        unit="count",
        description="Number of buildings within 20m (`momepy.neighbors`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="neighbors_building_100m",
        label="Neighbouring buildings (100m)",
        unit="count",
        description="Number of buildings within 100m (`momepy.neighbors`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="neighbors_building_200m",
        label="Neighbouring buildings (200m)",
        unit="count",
        description="Number of buildings within 200m (`momepy.neighbors`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="neighbors_etc_1steps",
        label="Neighbouring ETCs (1 step)",
        unit="count",
        description="Number of ETCs within 1 topological step(s) (`momepy.neighbors`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="neighbors_etc_2steps",
        label="Neighbouring ETCs (2 steps)",
        unit="count",
        description="Number of ETCs within 2 topological step(s) (`momepy.neighbors`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="neighbors_etc_3steps",
        label="Neighbouring ETCs (3 steps)",
        unit="count",
        description="Number of ETCs within 3 topological step(s) (`momepy.neighbors`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="mean_dist_neighbors_building_20m",
        label="Mean distance to neighbouring buildings (20m)",
        unit="m",
        description="Mean centroid distance to buildings within 20m (`momepy.neighbor_distance`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="mean_dist_neighbors_building_100m",
        label="Mean distance to neighbouring buildings (100m)",
        unit="m",
        description="Mean centroid distance to buildings within 100m (`momepy.neighbor_distance`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="mean_dist_neighbors_building_200m",
        label="Mean distance to neighbouring buildings (200m)",
        unit="m",
        description="Mean centroid distance to buildings within 200m (`momepy.neighbor_distance`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="mean_dist_neighbors_building_knn10",
        label="Mean distance to 10 nearest buildings",
        unit="m",
        description=(
            "Mean centroid distance to the 10 nearest buildings (`momepy.neighbor_distance`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="mean_dist_neighbors_building_knn20",
        label="Mean distance to 20 nearest buildings",
        unit="m",
        description=(
            "Mean centroid distance to the 20 nearest buildings (`momepy.neighbor_distance`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="mean_dist_neighbors_building_knn30",
        label="Mean distance to 30 nearest buildings",
        unit="m",
        description=(
            "Mean centroid distance to the 30 nearest buildings (`momepy.neighbor_distance`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="mean_dist_neighbors_etc_2steps",
        label="Mean distance to neighbouring ETCs (2 steps)",
        unit="m",
        description=(
            "Mean centroid distance to ETCs within 2 topological steps "
            "(`momepy.neighbor_distance`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="mean_dist_neighbors_etc_3steps",
        label="Mean distance to neighbouring ETCs (3 steps)",
        unit="m",
        description=(
            "Mean centroid distance to ETCs within 3 topological steps "
            "(`momepy.neighbor_distance`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="street_length",
        label="Street segment length",
        unit="m",
        description="Length of the nearest street segment (`geometry.length`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="street_linearity",
        label="Street linearity",
        unit="fraction",
        description=(
            "Ratio of straight-line to actual length of the nearest street segment "
            "(`momepy.linearity`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="street_width",
        label="Street width",
        unit="m",
        description=(
            "Estimated street width from perpendicular ticks against buildings "
            "(`momepy.street_profile`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="street_width_deviation",
        label="Street width deviation",
        unit="m",
        description="Standard deviation of the street width estimate (`momepy.street_profile`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="street_openness",
        label="Street openness",
        unit="fraction",
        description=(
            "Share of perpendicular ticks reaching no building within tick length "
            "(`momepy.street_profile`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="node_degree",
        label="Nearest node degree",
        unit="count",
        description="Degree of the nearest street network node (`momepy.node_degree`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="mean_node_degree_r5m",
        label="Mean node degree (5m)",
        unit="dimensionless",
        description=(
            "Mean node degree within a 5m network-distance radius of the nearest node "
            "(`momepy.mean_node_degree`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="mean_node_degree_r400m",
        label="Mean node degree (400m)",
        unit="dimensionless",
        description=(
            "Mean node degree within a 400m network-distance radius of the nearest node "
            "(`momepy.mean_node_degree`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="mean_node_distance",
        label="Mean node distance",
        unit="m",
        description=(
            "Mean distance to the nearest node's neighbouring nodes (`momepy.mean_node_dist`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="node_density_r5m",
        label="Node density (5m)",
        unit="dimensionless",
        description=(
            "Node density within a 5m network-distance radius of the nearest node "
            "(`momepy.node_density`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="node_density_r400m",
        label="Node density (400m)",
        unit="dimensionless",
        description=(
            "Node density within a 400m network-distance radius of the nearest node "
            "(`momepy.node_density`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="node_clustering",
        label="Node clustering",
        unit="fraction",
        description="Squares clustering coefficient of the nearest node (`momepy.clustering`).",
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="edge_node_ratio_r5m",
        label="Edge/node ratio (5m)",
        unit="dimensionless",
        description=(
            "Edges over nodes within a 5m network-distance radius of the nearest node "
            "(`momepy.edge_node_ratio`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="edge_node_ratio_r400m",
        label="Edge/node ratio (400m)",
        unit="dimensionless",
        description=(
            "Edges over nodes within a 400m network-distance radius of the nearest node "
            "(`momepy.edge_node_ratio`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="cds_length_r5m",
        label="Cul-de-sac length (5m)",
        unit="m",
        description=(
            "Total cul-de-sac length within a 5m network-distance radius of the nearest node "
            "(`momepy.cds_length`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="cds_length_r400m",
        label="Cul-de-sac length (400m)",
        unit="m",
        description=(
            "Total cul-de-sac length within a 400m network-distance radius of the nearest node "
            "(`momepy.cds_length`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="cyclomatic_r5m",
        label="Cyclomatic complexity (5m)",
        unit="dimensionless",
        description=(
            "Cyclomatic complexity within a 5m network-distance radius of the nearest node "
            "(`momepy.cyclomatic`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="cyclomatic_r400m",
        label="Cyclomatic complexity (400m)",
        unit="dimensionless",
        description=(
            "Cyclomatic complexity within a 400m network-distance radius of the nearest node "
            "(`momepy.cyclomatic`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="gamma_index_r5m",
        label="Gamma index (5m)",
        unit="fraction",
        description=(
            "Connectivity gamma index within a 5m network-distance radius of the nearest node "
            "(`momepy.gamma`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="gamma_index_r400m",
        label="Gamma index (400m)",
        unit="fraction",
        description=(
            "Connectivity gamma index within a 400m network-distance radius of the nearest node "
            "(`momepy.gamma`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="meshedness_r5m",
        label="Meshedness (5m)",
        unit="fraction",
        description=(
            "Meshedness coefficient within a 5m network-distance radius of the nearest node "
            "(`momepy.meshedness`)."
        ),
        reference=MOMEPY,
    ),
    ParameterSpec(
        name="meshedness_r400m",
        label="Meshedness (400m)",
        unit="fraction",
        description=(
            "Meshedness coefficient within a 400m network-distance radius of the nearest node "
            "(`momepy.meshedness`)."
        ),
        reference=MOMEPY,
    ),
)


PARAMETER_COLUMNS: tuple[str, ...] = tuple(p.name for p in PARAMETERS)
"""Column names `compute_morphometrics()` must emit, in registry order."""

_BY_NAME: dict[str, ParameterSpec] = {p.name: p for p in PARAMETERS}


def spec(name: str) -> ParameterSpec:
    """The `ParameterSpec` for `name`, raising `KeyError` if it is not a registered column."""
    return _BY_NAME[name]


CONTEXTUAL_QUANTILES: tuple[int, ...] = (25, 50, 75)
"""The paper's own percentiles for the contextual expansion."""


def contextual_specs(
    quantiles: Iterable[int] = CONTEXTUAL_QUANTILES,
) -> tuple[ParameterSpec, ...]:
    """`ParameterSpec`s for the opt-in contextual expansion: `{name}_p{q}` per primary attribute.

    Generated from `PARAMETERS` the same way `lczkit.ucp.registry.semantic_specs()` generates its
    config-driven columns — a description template referencing the primary spec's own
    description, rather than 321 hand-written entries that would drift from the 107 they mirror.
    """
    result: list[ParameterSpec] = []
    for primary in PARAMETERS:
        for q in quantiles:
            result.append(
                ParameterSpec(
                    name=f"{primary.name}_p{q}",
                    label=f"{primary.label} (p{q}, neighbouring ETCs)",
                    unit=primary.unit,
                    description=(
                        f"The {q}th percentile of `{primary.name}` across neighbouring ETCs "
                        '(`momepy.percentile`, linearly weighted, "hazen" interpolation). '
                        f"{primary.description}"
                    ),
                    reference=MAJER_2026,
                )
            )
    return tuple(result)
