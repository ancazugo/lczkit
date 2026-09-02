<!--
Source: Majer & Fleischmann (2026), "Predicting Local Climate Zones using Urban Morphometrics
and Satellite Imagery", arXiv:2603.00132.
Table: Supplementary Material A ("Urban Morphometrics calculation details"), the full list of
107 primary morphometric attributes computed via momepy over Enclosed Tessellation Cells (ETCs).
Transcribed: 2026-09-02, from the PDF at docs/references/papers/majer_2026_lcz_morphometrics.pdf.
Checked: cross-tallied by section (62 Dimensional & Shape + 23 Spatial Distribution & Intensity
+ 22 Street Descriptors & Connectivity = 107) before any implementation code was written against
it, and again by `tests/test_morphometrics_registry_matches_menu.py`, which parses this table
cell-for-cell against `lczkit.morphometrics.registry.PARAMETERS`.
-->

# Majer & Fleischmann (2026) — 107 primary 2D morphometric attributes

This is the authoritative implementation checklist for `lczkit.morphometrics` (Phase 29). Each
row is one column `lczkit.morphometrics.compute.compute_morphometrics` emits, before the opt-in
contextual (percentile) expansion. `name` is lczkit's own column name, chosen to be
self-describing (object + scale) rather than reproducing the paper's prose labels verbatim; the
`momepy 1.0+ call` column is what `lczkit.morphometrics` actually calls, verified against the
**installed** momepy 1.0.0 rather than assumed from the paper or from the reference repository
(github.com/majerhugo/lcz_morphometrics), whose own momepy version is unpinned.

**These are 2D-only.** No height data is read anywhere in this table — the paper's own framing
(§3.1) and the package's stated scope for this feature. lczkit's existing `Hr` (height of
roughness elements) and the height cascade are untouched by this module.

**"ETC" is an Enclosed Tessellation Cell** — `momepy.enclosed_tessellation`, generated from
building footprints with streets/waterlines/waterbodies as barriers, then restricted to cells
with a parent building (see `lczkit.units.tessellation.TessellationUnits`). An ETC's index *is*
its parent building's index, so "Building" and "ETC" values below share `unit_id` directly —
computing one does not require re-joining to compute the other.

**Weighted variants** are area-weighted means over a stated neighbourhood, via
`momepy.weighted_character`, per the paper's own definition (§3.1): "area-weighted variants for
selected building and ETC shape and dimension characters to reflect the dominant local built
environment and minimize the influence of smaller insignificant objects."

**5 m / 400 m street radii are network-distance, not topological hops** — confirmed against the
installed momepy: `mean_node_degree`/`node_density`/`edge_node_ratio`/`cds_length`/`cyclomatic`/
`gamma`/`meshedness` all read `radius` as topological hops **unless** `distance` names an edge
attribute, in which case `radius` is measured along that attribute. lczkit passes
`distance="mm_len"` (the length attribute `momepy.gdf_to_nx` writes by default) with
`radius=5`/`radius=400`, since 5 and 400 topological hops would be a nonsensical pairing on any
real street network while 5 m and 400 m are exactly the two street-canyon-to-neighbourhood scales
the paper's other tables use.

---

## Dimensional & Shape (62)

| name | object | momepy 1.0+ call | scale |
|---|---|---|---|
| `area_building` | Building | momepy area (`geometry.area`) | — |
| `area_etc` | ETC | momepy area (`geometry.area`) | — |
| `courtyard_area_building` | Building | `momepy.courtyard_area` | — |
| `courtyard_index_building` | Building | `momepy.courtyard_index` | — |
| `perimeter_wall_building` | Building | `momepy.perimeter_wall` (queen contiguity) | — |
| `perimeter_wall_building_w100m` | Building | `momepy.weighted_character` over `perimeter_wall` | 100 m distance band |
| `perimeter_wall_building_w200m` | Building | `momepy.weighted_character` over `perimeter_wall` | 200 m distance band |
| `longest_axis_length_building` | Building | `momepy.longest_axis_length` | — |
| `longest_axis_length_etc` | ETC | `momepy.longest_axis_length` | — |
| `longest_axis_length_building_w100m` | Building | `momepy.weighted_character` over `longest_axis_length` | 100 m distance band |
| `longest_axis_length_building_w200m` | Building | `momepy.weighted_character` over `longest_axis_length` | 200 m distance band |
| `longest_axis_length_etc_w3steps` | ETC | `momepy.weighted_character` over `longest_axis_length` | 3 topological steps (fuzzy contiguity) |
| `circular_compactness_building` | Building | `momepy.circular_compactness` | — |
| `circular_compactness_etc` | ETC | `momepy.circular_compactness` | — |
| `circular_compactness_building_w100m` | Building | `momepy.weighted_character` over `circular_compactness` | 100 m distance band |
| `circular_compactness_building_w200m` | Building | `momepy.weighted_character` over `circular_compactness` | 200 m distance band |
| `circular_compactness_etc_w3steps` | ETC | `momepy.weighted_character` over `circular_compactness` | 3 topological steps (fuzzy contiguity) |
| `square_compactness_building` | Building | `momepy.square_compactness` | — |
| `square_compactness_etc` | ETC | `momepy.square_compactness` | — |
| `square_compactness_building_w100m` | Building | `momepy.weighted_character` over `square_compactness` | 100 m distance band |
| `square_compactness_building_w200m` | Building | `momepy.weighted_character` over `square_compactness` | 200 m distance band |
| `square_compactness_etc_w3steps` | ETC | `momepy.weighted_character` over `square_compactness` | 3 topological steps (fuzzy contiguity) |
| `compactness_weighted_axis_building` | Building | `momepy.compactness_weighted_axis` | — |
| `compactness_weighted_axis_etc` | ETC | `momepy.compactness_weighted_axis` | — |
| `compactness_weighted_axis_building_w100m` | Building | `momepy.weighted_character` over `compactness_weighted_axis` | 100 m distance band |
| `compactness_weighted_axis_building_w200m` | Building | `momepy.weighted_character` over `compactness_weighted_axis` | 200 m distance band |
| `compactness_weighted_axis_etc_w3steps` | ETC | `momepy.weighted_character` over `compactness_weighted_axis` | 3 topological steps (fuzzy contiguity) |
| `convexity_building` | Building | `momepy.convexity` | — |
| `convexity_etc` | ETC | `momepy.convexity` | — |
| `convexity_building_w100m` | Building | `momepy.weighted_character` over `convexity` | 100 m distance band |
| `convexity_building_w200m` | Building | `momepy.weighted_character` over `convexity` | 200 m distance band |
| `convexity_etc_w3steps` | ETC | `momepy.weighted_character` over `convexity` | 3 topological steps (fuzzy contiguity) |
| `elongation_building` | Building | `momepy.elongation` | — |
| `elongation_etc` | ETC | `momepy.elongation` | — |
| `elongation_building_w100m` | Building | `momepy.weighted_character` over `elongation` | 100 m distance band |
| `elongation_building_w200m` | Building | `momepy.weighted_character` over `elongation` | 200 m distance band |
| `elongation_etc_w3steps` | ETC | `momepy.weighted_character` over `elongation` | 3 topological steps (fuzzy contiguity) |
| `equivalent_rectangular_index_building` | Building | `momepy.equivalent_rectangular_index` | — |
| `equivalent_rectangular_index_etc` | ETC | `momepy.equivalent_rectangular_index` | — |
| `equivalent_rectangular_index_building_w100m` | Building | `momepy.weighted_character` over `equivalent_rectangular_index` | 100 m distance band |
| `equivalent_rectangular_index_building_w200m` | Building | `momepy.weighted_character` over `equivalent_rectangular_index` | 200 m distance band |
| `equivalent_rectangular_index_etc_w3steps` | ETC | `momepy.weighted_character` over `equivalent_rectangular_index` | 3 topological steps (fuzzy contiguity) |
| `facade_ratio_building` | Building | `momepy.facade_ratio` | — |
| `facade_ratio_etc` | ETC | `momepy.facade_ratio` | — |
| `facade_ratio_building_w100m` | Building | `momepy.weighted_character` over `facade_ratio` | 100 m distance band |
| `facade_ratio_building_w200m` | Building | `momepy.weighted_character` over `facade_ratio` | 200 m distance band |
| `facade_ratio_etc_w3steps` | ETC | `momepy.weighted_character` over `facade_ratio` | 3 topological steps (fuzzy contiguity) |
| `fractal_dimension_building` | Building | `momepy.fractal_dimension` | — |
| `fractal_dimension_etc` | ETC | `momepy.fractal_dimension` | — |
| `fractal_dimension_building_w100m` | Building | `momepy.weighted_character` over `fractal_dimension` | 100 m distance band |
| `fractal_dimension_building_w200m` | Building | `momepy.weighted_character` over `fractal_dimension` | 200 m distance band |
| `fractal_dimension_etc_w3steps` | ETC | `momepy.weighted_character` over `fractal_dimension` | 3 topological steps (fuzzy contiguity) |
| `rectangularity_building` | Building | `momepy.rectangularity` | — |
| `rectangularity_etc` | ETC | `momepy.rectangularity` | — |
| `rectangularity_building_w100m` | Building | `momepy.weighted_character` over `rectangularity` | 100 m distance band |
| `rectangularity_building_w200m` | Building | `momepy.weighted_character` over `rectangularity` | 200 m distance band |
| `rectangularity_etc_w3steps` | ETC | `momepy.weighted_character` over `rectangularity` | 3 topological steps (fuzzy contiguity) |
| `shape_index_building` | Building | `momepy.shape_index` | — |
| `shape_index_etc` | ETC | `momepy.shape_index` | — |
| `shape_index_building_w100m` | Building | `momepy.weighted_character` over `shape_index` | 100 m distance band |
| `shape_index_building_w200m` | Building | `momepy.weighted_character` over `shape_index` | 200 m distance band |
| `shape_index_etc_w3steps` | ETC | `momepy.weighted_character` over `shape_index` | 3 topological steps (fuzzy contiguity) |

## Spatial Distribution & Intensity (23)

| name | object | momepy 1.0+ call | scale |
|---|---|---|---|
| `building_adjacency_200m` | Building | `momepy.building_adjacency` | 200 m distance band neighbourhood |
| `mean_interbuilding_distance_200m` | Building | `momepy.mean_interbuilding_distance` | 200 m distance band neighbourhood |
| `shared_walls_building` | Building | `momepy.shared_walls` | — |
| `street_alignment_building` | Building | `momepy.street_alignment` | vs. nearest street (`momepy.get_nearest_street`) |
| `street_alignment_building_w100m` | Building | `momepy.weighted_character` over `street_alignment` | 100 m distance band |
| `street_alignment_building_w200m` | Building | `momepy.weighted_character` over `street_alignment` | 200 m distance band |
| `coverage_area_ratio_etc` | ETC | `building_area / etc_area` (direct division; ETC index is the parent building's) | — |
| `coverage_area_ratio_etc_w3steps` | ETC | `momepy.weighted_character` over `coverage_area_ratio` | 3 topological steps (fuzzy contiguity) |
| `etc_granularity_1step` | ETC | self-weighted `Graph.lag` over ETC area | 1 topological step incl. self |
| `neighbors_building_20m` | Building | `momepy.neighbors` | 20m distance band |
| `neighbors_building_100m` | Building | `momepy.neighbors` | 100m distance band |
| `neighbors_building_200m` | Building | `momepy.neighbors` | 200m distance band |
| `neighbors_etc_1steps` | ETC | `momepy.neighbors` | 1 topological step (fuzzy contiguity) |
| `neighbors_etc_2steps` | ETC | `momepy.neighbors` | 2 topological steps (fuzzy contiguity) |
| `neighbors_etc_3steps` | ETC | `momepy.neighbors` | 3 topological steps (fuzzy contiguity) |
| `mean_dist_neighbors_building_20m` | Building | `momepy.neighbor_distance` | 20m distance band |
| `mean_dist_neighbors_building_100m` | Building | `momepy.neighbor_distance` | 100m distance band |
| `mean_dist_neighbors_building_200m` | Building | `momepy.neighbor_distance` | 200m distance band |
| `mean_dist_neighbors_building_knn10` | Building | `momepy.neighbor_distance` | 10 nearest neighbours |
| `mean_dist_neighbors_building_knn20` | Building | `momepy.neighbor_distance` | 20 nearest neighbours |
| `mean_dist_neighbors_building_knn30` | Building | `momepy.neighbor_distance` | 30 nearest neighbours |
| `mean_dist_neighbors_etc_2steps` | ETC | `momepy.neighbor_distance` | 2 topological steps (fuzzy contiguity) |
| `mean_dist_neighbors_etc_3steps` | ETC | `momepy.neighbor_distance` | 3 topological steps (fuzzy contiguity) |

## Street Descriptors & Connectivity (22)

| name | object | momepy 1.0+ call | scale |
|---|---|---|---|
| `street_length` | Street segment | `geometry.length` | — |
| `street_linearity` | Street segment | `momepy.linearity` | — |
| `street_width` | Street segment | `momepy.street_profile` | tick spacing/length are config |
| `street_width_deviation` | Street segment | `momepy.street_profile` | tick spacing/length are config |
| `street_openness` | Street segment | `momepy.street_profile` | tick spacing/length are config |
| `node_degree` | Street node | `momepy.node_degree` | — |
| `mean_node_degree_r5m` | Street node | `momepy.mean_node_degree` | network-distance radius 5m (`distance='mm_len'`) |
| `mean_node_degree_r400m` | Street node | `momepy.mean_node_degree` | network-distance radius 400m (`distance='mm_len'`) |
| `mean_node_distance` | Street node | `momepy.mean_node_dist` | — |
| `node_density_r5m` | Street node | `momepy.node_density` | network-distance radius 5m (`distance='mm_len'`) |
| `node_density_r400m` | Street node | `momepy.node_density` | network-distance radius 400m (`distance='mm_len'`) |
| `node_clustering` | Street node | `momepy.clustering` | — |
| `edge_node_ratio_r5m` | Street node | `momepy.edge_node_ratio` | network-distance radius 5m (`distance='mm_len'`) |
| `edge_node_ratio_r400m` | Street node | `momepy.edge_node_ratio` | network-distance radius 400m (`distance='mm_len'`) |
| `cds_length_r5m` | Street node | `momepy.cds_length` | network-distance radius 5m (`distance='mm_len'`) |
| `cds_length_r400m` | Street node | `momepy.cds_length` | network-distance radius 400m (`distance='mm_len'`) |
| `cyclomatic_r5m` | Street node | `momepy.cyclomatic` | network-distance radius 5m (`distance='mm_len'`) |
| `cyclomatic_r400m` | Street node | `momepy.cyclomatic` | network-distance radius 400m (`distance='mm_len'`) |
| `gamma_index_r5m` | Street node | `momepy.gamma` | network-distance radius 5m (`distance='mm_len'`) |
| `gamma_index_r400m` | Street node | `momepy.gamma` | network-distance radius 400m (`distance='mm_len'`) |
| `meshedness_r5m` | Street node | `momepy.meshedness` | network-distance radius 5m (`distance='mm_len'`) |
| `meshedness_r400m` | Street node | `momepy.meshedness` | network-distance radius 400m (`distance='mm_len'`) |

---

## What this table does not cover

- The **contextual expansion** (25th/50th/75th percentile of each of the 107 over ETCs within 3
  topological steps, via `momepy.percentile`) — opt-in, config-gated, generated programmatically
  by `lczkit.morphometrics.registry.contextual_specs()` rather than listed here row by row, since
  its 321 column names are `{name}_p25`/`_p50`/`_p75` mechanically derived from this table.
- The paper's classification schemes (S1–S4: RandomForest and CNN LCZ prediction) — out of scope
  for this feature, which ports only the morphometric attribute computation.
- Data preparation (Supplementary Material D) — a subset of lczkit's own Phase 1 cleaning;
  `lczkit.morphometrics` reuses `lczkit.cleaning.pipeline.clean_vectors`'s output directly rather
  than re-implementing it.
