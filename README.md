# lczkit

Maps a city into [Local Climate Zones](https://doi.org/10.1175/BAMS-D-11-00019.1)
(Stewart & Oke 2012) from open vector and raster data. It follows the conceptual approach of
GeoClimate — partition into spatial units, compute urban canopy parameters, classify by
distance to LCZ prototypes — as an independent implementation with a pluggable data layer:
Overture Maps for vector data, Google Earth Engine / STAC / local rasters for land cover, and
a tiered cascade for building heights.

Building height completeness, and reporting it honestly, is a first-class output of this
package, not a diagnostic.

See `CLAUDE.md` for the full project specification and phase plan.

## Command line

```sh
lczkit run --bbox 13.29,52.45,13.52,52.59      # any window, needs nothing on disk
lczkit run --city berlin --extent-km 4         # a So2Sat city, shrunk to try it out
lczkit site build <run_dir>                    # rebuild the map site from a finished run
lczkit site serve <run_dir>                    # then open the address it prints
```

`lczkit run` writes `$DATA_DIR/output/lczkit/<run_id>/` and builds its map site. It is the same
chain the published sites went through — `lczkit.pipeline.run_pipeline`, which
`scripts/berlin_metropolitan_run.py` and `scripts/publish_sites.py` also call, so a run from the
command line and a published run cannot be configured differently by accident. A test asserts that.

Three things worth knowing:

- **`--city` needs So2Sat on disk; `--bbox` needs nothing.** A city key resolves to the same 30 km
  window every validation sweep since Phase 9 has used, which is what makes a run comparable with
  the agreement figures already recorded for it. `--extent-km` shrinks either locator concentrically,
  because a full window is a multi-hour run and the first thing anyone does with a new command is
  try it on something small.
- **`--dry-run` resolves everything and writes nothing**, including the run directory. Use it to see
  the configuration a run would use before spending the download.
- **`--config` takes a JSON file overriding any settings section, and a run manifest works**, since
  a manifest nests its settings under `config`. So a run can be reproduced from its own output.
  `data_dir` and `run_id` are refused there — they come from the environment and `--run-id`, and a
  file that could move either would make the same command write to two different places.

The library API is unchanged and the command line is not privileged: everything it does is a call
into `lczkit.pipeline` or `lczkit.viz` that any caller can make.

## Status

Phase 0 (skeleton) — project layout, the five pluggable-source `Protocol`s, the CRS
enforcement helper, and the `Settings` config model.

Phase 1 (vector ingestion and cleaning) — `OvertureSource` (DuckDB-backed, reading
bbox-filtered GeoParquet from Overture's S3), the building-cleaning pipeline, street
simplification via `neatnet`, cross-layer topology cleanup, and a structured cleaning report
recording feature counts **and footprint area** in and out of every operation. Buildings retain
`subtype`/`class` (usage type) and `sources` (per-feature dataset provenance) through cleaning
— they are what later phases classify heavy industry and audit height coverage with. A
`land_use` layer is ingested and carried through with geometry repair only; it supplies
functional semantics to Phase 5 and is deliberately neither a spatial-unit barrier nor a
land-cover source.

**Cleaning produces two building layers, not one.** They share a `building_id` and diverge after
a common prefix of geometry repair, multipolygon explosion, and non-polygon and oversized-footprint
removal:

- **`buildings_area`** adds overlap *trimming* only, and feeds every area statistic — building
  surface fraction, `Hr`, building count, mean building area, the industrial shares — plus the
  height cascade. Retention is measured against the **union** of raw footprints, not their sum,
  because Overture's sources overlap themselves: Kowloon's raw footprints double-count 7.52% of
  their summed area against Berlin's 0.61%, so trimming that away reads as attrition against the sum
  and is not. The cleaning report carries `raw_self_overlap_fraction` beside the retention figure,
  and a residual overlap left in the layer is reported rather than assumed away — building surface
  fraction sums overlay pieces, so it would inflate the numerator.
- **`buildings_topo`** adds overlap merging, small-building dissolution, a road-buffer rule and a
  final planarity pass, and feeds the `neatnet` exclusion mask and `momepy.street_profile`.
  Destructive by design, and **verifiably planar** — `momepy.enclosures()` requires that, and the
  cleaning report asserts it rather than recording it.

The split exists because a single layer cleaned for topology destroyed 23.5% of Berlin's footprint
area before building surface fraction — roughly 47% of the classification metric — was computed.
See [`docs/experiments/phase-6.6-footprint-attrition.md`](docs/experiments/phase-6.6-footprint-attrition.md).
Footprints are dropped for lying inside a road buffer, never for touching a street centreline: a
perimeter block fronting a street routinely crosses a generalised centreline, and treating that as
an error removed 439 Berlin footprints averaging three times the size of the ones it kept.

Planarity is enforced explicitly at the end, because trimming alone cannot reach it: overlaps whose
intersection has collapsed to *zero area* satisfy the `overlaps` predicate while `difference` on
them is a no-op, so `geoplanar.trim_overlaps` leaves them however many times it runs. Three such
pairs on Berlin held the layer non-planar for two phases. Subtracting a one-micrometre buffer clears
them for 4.5×10⁻⁵ m² of 3.13 km² — see
[`docs/experiments/phase-6.7-instrument-diagnostics.md`](docs/experiments/phase-6.7-instrument-diagnostics.md).

**Street simplification is tiled above roughly 50 km².** `neatnet` is superlinear in extent — the
exponent in area climbs from 0.95 at 1–4 km² to 1.67 at 36–64 km², because face artifacts percolate
into a single rook-contiguous component holding 93–96% of them, and clusters are simplified one
component at a time. 100 km² takes 50 minutes on one core; 256 km² was abandoned after 4h12m. Set
`street_tile_size_m` and `street_tile_buffer_m` to engage `simplify_streets_tiled`, which splits the
extent, pins one face-artifact threshold across all tiles so they cannot disagree about what an
artifact is, and runs tiles across processes. Unset, the whole-extent path runs exactly as before,
so every figure recorded before Phase 8 stays reproducible. On 16 km² of Berlin a 2×2 tiling with a
600 m buffer agrees with the whole-extent result to **99.97%**.

**Tiling the work was not enough on its own.** A 7.5-minute tiled simplification of Berlin's 891 km²
still sat inside a fifteen-hour run that never finished, because two *other* steps were quadratic in
extent: the threshold pinning that makes tiles agree, and the road-buffer rule in cross-layer
topology, which intersected every footprint against one unioned road geometry and would have taken
about 75 hours on its own. Both are now derived locally, each measured against the global operation
it replaces. The road rule is exact — 39× faster, symmetric difference 0.0 m². The pooled threshold
is an approximation, and is reported as one: measured at six concentric extents its deviation from
the whole-network value **does not grow** with extent (0.026 → 0.004), the two converge to four
parts in ten thousand, and the label difference *falls* as the extent widens — 6 of 26 040 cells at
256 km², **10 of 172 181 at the full 891 km²**, 0.023% down to 0.0058%. The whole-network
alternative takes **10 h 39 m** at that extent against about 70 seconds. **Berlin's full 891 km² administrative extent now cleans end to end in 9.8 minutes**,
retaining 99.947% of footprint area. A third "fix", restricting the seam stitch, was built and then
discarded when measurement showed the bottleneck it targeted did not exist — see
[`docs/experiments/phase-8-scaling.md`](docs/experiments/phase-8-scaling.md).

**Building heights are sparse, and that is the data, not a defect.** Overture conflates
footprints winner-takes-all, so in machine-learning dominated areas heights are near-absent —
26% of footprints in the Berlin test fixture carry one. Nothing in ingestion or cleaning treats
a null height as an error; the Phase 3 cascade fills them and reports how well it managed.

Provenance in Overture is recorded per *attribute*, not per feature, and heights are conflated
across datasets even where footprints are not: a quarter of the Berlin fixture's heights sit on
OpenStreetMap footprints but come from Microsoft ML Buildings, each with its own confidence
score. A tier-1 height is therefore not a synonym for a surveyed one, and the diagnostic below
reports the difference rather than averaging it away.

Phase 2 (spatial units) — `EnclosureUnits` (`momepy.enclosures()` over streets, rail, and
waterbodies as barriers; `assemble_barriers` accepts a `vegetation` layer, but nothing derives
one yet — Phase 4 supplies the land-cover source it would come from, and wiring the two together
is Phase 2 work still outstanding), `GridUnits` (a 100 m regular grid aligned to the local UTM CRS's
own coordinate origin, not to the query bbox, so the same real-world cell always gets the same
`unit_id`), and `aggregate()` (`"majority"` / `"area_weighted"`) for moving attribute columns
between the two. `OvertureSource` gained a `rail()` layer in this phase, alongside its existing
`buildings`/`streets`/`water`.

Phase 3 (height cascade) — every building comes out with a `height`, a `height_source` naming
the tier that resolved it, and a `height_confidence`; every unit comes out with
`height_completeness` (the tier-1 share of building footprint area) and a `height_frac_*`
column per tier. Four tiers in order: Overture `height`, `num_floors × storey_height`, then
Google Open Buildings 2.5D, WSF-3D and GHS-BUILT-H read as local COGs. A source-availability
diagnostic reports height and floor-count coverage per upstream dataset — twice, once by the
dataset that won the footprint and once by the dataset that supplied the height — which answers
"is this city viable?" before anyone waits for a full run.

Three things about this phase are worth knowing before relying on it:

- **The default cascade is `coarse`: WSF-3D and GHS-BUILT-H on, Open Buildings 2.5D off.**
  `lczkit.sources.height_products` fetches and places each enabled product for a study area, and
  `resolve_areal_tiers()` hands `build_cascade` a config with the files resolved. A tier whose
  product does not cover the window is dropped rather than failed — the cascade is shorter, and
  buildings it cannot reach are tagged `unresolved` with a null height rather than given an
  invented one.

  Open Buildings ships `enabled=False` on measured evidence, not on availability. It is the
  finest tier, has the lowest per-building error of the three (MAE 5.39 m against 7.44 and 8.17)
  and is the only one with any within-unit skill — and across nine cities it *lowered* built-class
  agreement by 1.9 points, positive in only 4. `Hr` is a geometric mean, which dispersion
  depresses, and this product's within-unit spread is 0.441 against reality's 0.195. **Per-building
  accuracy is the wrong acceptance test for a height product feeding an LCZ map**; evaluate a new
  tier on within-unit dispersion. See
  [Phase 10](docs/experiments/phase-10-height-cascade.md). One flag switches it back on.
- **`height_confidence` has no default and the cascade raises without one.** It is an ordinal
  ranking of measurement quality, not a calibrated probability, and no published number defines
  it — so it is set explicitly in config and recorded in the manifest rather than guessed at
  here. Where Overture supplies a real per-building confidence, that value is used instead.
- **Areal tiers degrade along the height axis, by construction.** A ~100 m product cannot
  resolve low-rise from mid-rise from high-rise within a heterogeneous unit, so classification
  error concentrates on the LCZ pairs that differ mainly in height — 1↔2↔3 among the compact
  types and 4↔5↔6 among the open ones — rather than scattering. In a city with low
  `height_completeness` that pattern is the data behaving as documented, not a bug. Phase 6's
  validation measures it directly, and reports it separately from the compactness axis
  (1↔4, 2↔5, 3↔6), which is a footprint-coverage diagnostic rather than a height one.

Phase 4 (raster and land cover) — the `RasterSource` protocol, with two backends returning a
fractions table keyed by `unit_id`: `LocalRasterSource` (a COG on disk, reduced with
`exactextract`'s exact cell-coverage weighting) and `EarthEngineSource` (`reduceRegions` with
`frequencyHistogram`, batched, cached under `input/GEE/`). Both reduce the same class mapping
declared once in config, so their tables are schema-identical by construction. Two MVP datasets
ship configured: ESA WorldCover v200 and ETH 10 m canopy height. The class-to-fraction mapping is
config, never hardcoded.

Three things about this phase are worth knowing before relying on it:

- **`frac_tree` is carved *out* of `frac_pervious`, not contained in it.** The protocol requires
  fractions summing to 1.0, so the classes are disjoint. Stewart & Oke (2012) count trees *within*
  the pervious surface fraction — LCZ A, dense trees, is 90%+ pervious — so anything reproducing
  their parameter must add the two together. This is the easiest place in the package to
  undercount silently.
- **ETH canopy height masks built-up land and water, and that is not the same as "unobserved".**
  Lang et al. (2023) mask built-up areas, snow, ice and permanent water out of the product and set
  those cells to 255. Over the Berlin fixture that is 93% of built-up cells and 78% of the whole
  tile. Dropping them from the denominator reports central Berlin as ~96% tree cover; counting them
  as non-tree, which is what the mask means, gives ~22%. Each dataset therefore declares a
  `nodata_policy`.
- **The two tree estimates are not independent, and `canopy_frac_tree` reads high.** Lang et al.
  derive that mask *from ESA WorldCover*, so the cells the canopy product declines to measure are
  exactly the ones WorldCover calls built up, snow/ice or water — treating the two columns as
  corroborating evidence would be double-counting one source. They also report their map
  overestimates vegetation below 5 m and carries roughly a 2 m positive bias from 5 to 20 m,
  traded deliberately for accuracy on tall canopies, so a 3 m tree threshold over-calls tree.
  Tree cover therefore defaults to WorldCover's own class 10, and `canopy_frac_tree` is best read
  as an upper bound.
- **The local path needs a COG you supply; the Earth Engine path needs credentials.** Neither
  product is on this system, so each dataset's config carries no `filename` until you place one —
  `LocalRasterSource.from_settings` says so plainly rather than failing obscurely. Both datasets
  do carry a verified Earth Engine asset, so `EarthEngineSource` works out of the box given
  `GEE_PROJECT_NAME` and Earth Engine credentials.

The two backends agree on the fixture to within ~1-2 percentage points per class, which is the
expected cost of their different reduction semantics rather than an error in either:
`exactextract` weights each cell by the exact fraction of it a unit covers, while `reduceRegions`
counts whole pixels by centre. `tests/test_landcover_earthengine_live.py` measures this against
live Earth Engine; those tests are marked `network` and skipped by default, so CI stays offline.

Phase 5 (urban canopy parameters) — `lczkit.ucp.compute_parameters()` returns one row per
`unit_id` carrying sixteen columns, every one of them described in `lczkit.ucp.registry` with its
unit of measurement and the source that defines it. A test asserts the registry and the
implementation agree in both directions, so a column cannot be added without documenting it.

| Parameter | Unit | Source |
|---|---|---|
| `building_surface_fraction` | fraction | Stewart & Oke (2012) |
| `impervious_surface_fraction` | fraction | Stewart & Oke (2012) |
| `pervious_surface_fraction` | fraction | Stewart & Oke (2012) |
| `tree_fraction`, `water_fraction` | fraction | Bernard et al. (2024) Table 1 |
| `height_of_roughness_elements_m` | m | Bernard et al. (2024) Table 1 |
| `h_geometric_area_weighted`, `h_mean_area_weighted`, `h_std` (secondary) | m | computed here |
| `aspect_ratio` | dimensionless | Stewart & Oke (2012), via `momepy.street_profile()` |
| `street_openness` | fraction | momepy |
| `street_width_m` | m | momepy |
| `building_count` | count | computed here |
| `mean_building_area_m2` | m² | computed here |
| `industrial_fraction_of_building_area` | fraction | Bernard et al. (2024) `FIND/B` |
| `industrial_fraction_of_unit_area` | fraction | computed here |
| `industrial_fraction` (deprecated alias) | fraction | computed here |
| `industrial_fraction_buildings`, `industrial_fraction_land_use` | fraction | computed here |
| `industrial_evidence` | category | computed here |

Five things about this phase are worth knowing before relying on it:

- **`Hr` is the geometric mean of building height, and only `Hr` may be classified on.** Stewart &
  Oke's height of roughness elements is `exp(mean(log h))` — Bernard et al. (2024) Table 1 — and
  the LCZ property ranges Phase 6 normalises against were defined for that quantity. The arithmetic
  mean sits above it whenever a unit mixes tall and short buildings, so substituting one for the
  other would bias exactly the heterogeneous units where classification is hardest, and would do it
  silently. `h_geometric_area_weighted`, `h_mean_area_weighted` and `h_std` ship as **secondary**
  columns; all three are marked as such in the registry. The first is the same geometric mean
  weighted by footprint area, emitted because the unweighted form gives a 5 m2 shed the same vote
  as a tower block — measurable, without changing what `Hr` means. The other two exist for the
  deferred roughness work (Macdonald, Kanda). One building gets one vote regardless of how many
  MultiPolygon parts it arrived in.
- **Two of Stewart & Oke's seven morphological properties are not computed.** *Sky view factor* is
  deferred as the single most expensive component, and it is strongly correlated with aspect ratio,
  which this phase does compute; Bernard et al. (2018), `10.3390/cli6030060`, is the preferred
  route when it is picked up, because vector ray-launching needs no DSM. *Terrain roughness* is
  deferred too: the Davenport et al. (2000) table maps a roughness class to a roughness length z₀,
  and deriving z₀ from morphology is a separate piece of work — one that Bernard et al. weight at
  0.5 in their distance metric against 8 for building fraction and 6 for mean height, so its
  absence costs the classification little. Both omissions are recorded in
  `lczkit.ucp.registry.NOT_COMPUTED`, so they reach the manifest rather than living only here.
- **The surface fractions are not Phase 4's fractions.** Phase 4 emits disjoint classes summing to
  1.0, because the `RasterSource` protocol requires it. Stewart & Oke do not partition the surface
  the same way, and this phase re-partitions to match them: tree cover and water fold into
  `pervious_surface_fraction` (their table puts both LCZ A and LCZ G at 90%+ pervious, so neither
  class is otherwise reachable), and the building share comes *out* of `impervious_surface_fraction`
  (a 10 m built-up class is measured from above and contains the roofs). Building, impervious and
  pervious then sum to 1.0. The exception is a unit carrying more footprint than the raster calls
  built up, where the subtraction clips at zero and the three sum above 1.0 — a visible signal that
  the vector and raster layers disagree there.
- **Buildings reach units two different ways, and that is deliberate.** Area quantities split
  footprints at unit boundaries, matching what Phase 3's `height_completeness` already does, so a
  building straddling two grid cells contributes to both in proportion. Object quantities —
  `building_count` and `mean_building_area_m2` — move whole buildings to the unit containing their
  representative point, because half a building is not a building. On a 100 m grid the two
  populations genuinely differ, and a test asserts they still do.
- **The industrial share is the only route to LCZ 10, and Overture cannot fully supply it.**
  GeoClimate separates heavy industry from light industry and commercial; Overture offers a single
  `industrial` value across both `subtype` and `class`, so a light-industrial estate and a refinery
  are indistinguishable here. `warehouse` is deliberately *not* counted as industrial — it is the
  LCZ 8 case CLAUDE.md names. The Berlin fixture holds 36 industrial buildings of 6195 and 2
  industrial parcels of 1559, enough to exercise the plumbing and not enough to validate the rule.

Phase 6 (classification, output, validation) — `lczkit.classify.PrototypeClassifier` turns the
parameter table into a 17-way distance vector plus `lcz_primary`, `lcz_secondary`, `uniqueness`
and a record of how each label was reached; `lczkit.output.write_run()` writes the run to
`output/lczkit/<run_id>/`; `lczkit.validation` measures agreement against a reference LCZ map.
The distance vector is the primary output and a label is a convenience over it — no core API
returns a bare LCZ integer.

```
output/lczkit/<run_id>/
├── units.parquet       # GeoParquet: geometry, parameters, labels, provenance, land cover
├── units_viz.parquet   # no geometry, floats to 3 s.f., distances as scaled int16
└── manifest.json       # config, versions, reports, prototypes, breaks, legend, validation
```

Six things about this phase are worth knowing before relying on it:

- **The natural classes do not go through the distance metric alone, because they cannot.**
  Bernard et al. (2024) §2.5 is explicit that their weights "are only used in the closest-distance
  approach for LCZ built types", and the reason is visible in the published table: LCZ A, B, C and
  D are separated *only* by sky view factor, aspect ratio and height of roughness elements — all
  building-derived, all null or zero in open ground — and F and G differ in no published dimension
  at all. So a configurable land-cover gate picks the family first (`building_surface_fraction`
  ≥ 10%, which is the boundary Stewart & Oke's own table draws), and the weighted distance then
  runs within it. The full 17-way vector is still reported, but the two halves are measured under
  different weight vectors, so the gate rather than the argmin decides the family. `label_route`
  records which mechanism produced every label.
- **Two prototype dimensions are lczkit's, not Stewart & Oke's.** `tree_fraction` and
  `water_fraction` ranges are tagged `source="lczkit"` throughout, documented at length in
  `docs/references/tables/lczkit_natural_class_ranges.md`, and driven by two configurable
  thresholds. Without them LCZ G is unreachable, since water and bare soil are identical in the
  published table. **LCZ C (bush, scrub) and LCZ F (bare soil) remain unreachable by default** and
  are recorded as such in the manifest: nothing separates them from LCZ D once the default
  WorldCover mapping folds shrubland, grassland and bare ground into one `pervious` class.
- **Five of Stewart & Oke's ten properties do not reach the metric.** Sky view factor and terrain
  roughness are Phase 5 deferrals; surface admittance, albedo and anthropogenic heat output are
  not derivable from open vector and raster data at all. The manifest lists all five with reasons.
  Note that anthropogenic heat output is the only published property that would separate LCZ 10
  from LCZ 8 directly — 300+ W m⁻² against at most 50 — which is why a functional attribute has to.
- **The `bernard2024_partial` preset cannot be applied as published, which is what the name
  says.** Its weights cover seven UCPs and lczkit computes five, so SVF (weight 4) and z₀ (0.5) — 4.5 of a published 21.5 — go unapplied
  and the effective built metric has three non-zero dimensions: `FB` 8, `Hr` 6, `H/W` 3. The
  manifest records the shortfall, because a comparison against a GeoClimate run is not a
  comparison of the same metric.
- **LCZ 10 is not in the distance metric. It is assigned functionally, and the threshold is
  calibrated rather than chosen.** Following Bernard et al., LCZ 10 is scored and reported in the
  seventeen-way vector but can never win the argmin; the industrial evidence is its only route.

  The rule it replaced gated on LCZ 8 and LCZ 10 being a unit's two nearest prototypes, and was
  **measured inert on the Rotterdam fixture at every threshold from 0.05 to 0.5** — 671 cells of
  working port, 254 industrial buildings, three quarters of cells over 90% industrial by area, a
  reference putting 88 of them in LCZ 10, and the pair never opened once. Port plots are large and
  sparsely built, so building surface fraction lands them on LCZ 9 and LCZ 10 is nowhere near
  second.

  `scripts/lcz10_threshold_sweep.py` sweeps the replacement and writes the precision/recall curve
  into the run record. **Read it before trusting the threshold.** Precision is flat at 24–27% across
  the whole range on both denominators, so the threshold governs how much of the map carries LCZ 10
  and not how often that label is right. Every run's manifest reports the firing count, so a rule
  that never fires is distinguishable from one never configured.
- **Two industrial shares ship, each named for what it divides by.**
  `industrial_fraction_of_building_area` is Bernard's `FIND/B` and is what the LCZ 10 rule reads;
  `industrial_fraction_of_unit_area` is the share of the cell's ground. They answer different
  questions — a sparsely-built working port scores high on the first and low on the second — and a
  single column called `industrial_fraction` was contradicted three ways inside this repository
  about which one it was. The bare name survives one release as a deprecated alias for the
  unit-area column.
- **Null parameters renormalise rather than dropping the unit.** A unit missing `aspect_ratio`
  is compared on the weights it does have, and `n_params_used` and `missing_parameters` say what
  it was judged on. No imputation anywhere.

### Validation, and what it is measured against

There are two references, and the distinction is load-bearing. **Hand-labelled So2Sat LCZ42 /
DFC2017 polygons are the primary reference** where they exist. The Demuzere global map
(`lcz_v3.tif`) is a secondary comparator — it is a model output carrying its own error, and
scoring against it as though it were ground truth reports the *disagreement between two models* as
lczkit's error. The agreement between the two is reported as the **ceiling**: the most any run
could score against the global map.

Everything is reported lczexplore-style — per-class agreement and a confusion matrix, never a
single accuracy figure — plus built-class agreement separately from overall with the natural-class
share stated beside it, agreement stratified by `height_completeness` band, and **both** confusion
axes, apart because they are different instruments: the height axis (1↔2↔3, 4↔5↔6) diagnoses the
height estimate, the compactness axis (1↔4, 2↔5, 3↔6) diagnoses footprint coverage and unit size.

**Per class, both directions.** Producer's accuracy (recall) alone cannot see over-prediction — a
map that labelled every cell LCZ 5 would score 100% on LCZ 5 — so `user_accuracy` and `f1` ship
beside it, following Demuzere et al. (2021), and a class the run predicts but the reference never
assigns gets a row rather than vanishing. `OA_bu`, the built-versus-natural accuracy ignoring
internal differentiation, separates "found the built fabric and misjudged its form" from "did not
find it", which the headline charges alike.

**`OA_w` is not implemented**, deliberately. Both Demuzere papers define it and attribute the
class-similarity matrix to Bechtel et al. (2017, 2020) without printing it, and neither is in
`docs/references/`. A plausible-looking invented weight matrix is the worst failure mode this
package has, so the metric waits for the source.

**Every figure is a point estimate over units that are not independent.** So2Sat patches are 320 m
squares on a 100 m stride, so a city's labelled cells are one contiguous, correlated sheet and the
effective sample size is far below the nominal one. `lczkit.validation.uncertainty` provides a
**spatial block bootstrap** — resampling contiguous blocks, not cells — for agreement and both axis
lifts. Read `lift` as conservative in any case: its null draws wrong labels from the run's own error
distribution, so a real concentration on one axis inflates the expectation it is measured against.

**Compare axes on `lift`, never on the raw share.** An axis's raw share of disagreement is not
comparable across cities — its denominator is all disagreement, so a city's natural-class share
dilutes it — and it is not comparable *between the axes* either: the height axis has six pairs to
compactness's three, so a null model that never looks at an axis still awards height most of the
error. `AxisSummary` therefore reports the raw share, a share restricted to references that could
reach an axis at all (LCZ 1–6), and `lift` against a null that keeps each unit's reference class and
the run's own distribution of wrong labels but breaks the association. `lift = 1.0` means the axis
holds exactly the share its reference affords it. Record the cascade alongside: filling heights
halves the height axis, so an axis figure without its cascade is half a measurement.

Measured on metropolitan Berlin, over the **9 627 cells** carrying both references:

| | agreement |
|---|---:|
| lczkit, against the labelled polygons | **35.3%** |
| `lcz_v3`, against the same labelled polygons — **the ceiling** | 75.2% |

**Do not use the 432-cell figures this table used to carry** — 40.9% against a 53.2% ceiling. Both
came from the 9 km² fixture, whose labelled cells span two classes and both mid-rise, and the
ceiling in particular was a small-sample artefact: `lcz_v3` reaches 75.2% on the full cell set, not
53.2%. [Phase 9](docs/experiments/phase-9-multi-city.md) re-measured both.

**Never quote agreement as a percentage of the ceiling.** Vancouver scores 41.8% against a 36.7%
ceiling — 114% — because the comparator is another estimator, not an upper bound, and lczkit beats
it in places. Ceilings across the fifteen cities measured run from 22.8% (Mumbai) to 83.2% (Rio),
so raw agreement is not comparable between cities without its ceiling beside it.

Rotterdam has **no
labelled coverage** — So2Sat covers 52 cities and Rotterdam is not one of them — so it stays on
`lcz_v3` alone at 42.3% over 657 cells, of which 45.4% are natural: its water agrees at 95.5% while
its 359 built cells sit at 3.1%. That is the figure a built/natural split exists to stop anyone
quoting.

**Where the parameters sit against Stewart & Oke.** `parameter_ranges` asks, for cells whose class is
*known*, whether a computed parameter reaches the interval published for that class — which is the
question no agreement figure answers. Group by the reference class, never the assigned one: the
classifier put those units near that prototype, so grouping by its own output is circular. And
`RangeReport` records `reference_file`, because "the reference" names a role that two different
files can fill: on the sixteen cities, grouping by `lcz_v3` rather than by the labels moves
class-level figures by up to 18 points.

Measured across sixteen cities at `coarse`
([Phase 13](docs/experiments/phase-13-bsf-published-ranges.md)): **building surface fraction does not
transfer to a 100 m cell, and the failure is dispersion rather than bias.** Six of ten built classes
have a median within 0.13 interval-widths of their published band and two sit inside it, but only one
class has more than half its area inside — the empirical p10–p90 runs 0.19–0.69 against a published
0.40–0.60 for LCZ 1, and 0.05–0.61 against 0.30–0.50 for LCZ 8. Stewart & Oke's ranges describe an
LCZ *patch*, which is homogeneous by construction; a grid cell is a sample that cuts across fabric.
Both intervals are reported side by side and **the published values are not recalibrated** —
`prototypes.py` transcribes `docs/references/tables/` and nothing writes back into it.

The write-ups in [`docs/experiments/`](docs/experiments/) record how those numbers got there.
[Phase 6.5](docs/experiments/phase-6.5-unit-scale.md) tests the obvious explanation for the original
17.7% — that Stewart & Oke's ranges describe an LCZ patch and a 100 m grid cell is not one — and
rejects it, finding instead that Phase 1 cleaning was destroying 23.5% of the footprint area behind
the metric. [Phase 6.6](docs/experiments/phase-6.6-footprint-attrition.md) fixes that.
[Phase 6.7](docs/experiments/phase-6.7-instrument-diagnostics.md) wires the real reference and
measures the ceiling.

**Two of those diagnoses did not survive a wider extent, and the fixture is why.** Over 144 km² of
Berlin — 14,625 cells, 2744 labelled across eight classes, against a 65.7% ceiling — arm A reaches
40.8%. The error axes read height 22.7% and compactness 13.7%, where the 9 km² fixture had said
compactness 55.2% and height 17.0% against the same reference. Switching reference inverted that
diagnosis once, and widening the extent inverted it back. Neither axis should be treated as
established until a second city at metropolitan scale says so.

**Enclosure-based computation has not been adopted, and the reason is now regional rather than
global.** Measured three times on the same fifteen cities, the enclosure-minus-grid gap has closed
to nothing while the built-class lead has grown:

| | overall B − A | built B − A |
|---|---:|---:|
| tier-1 heights only (Phase 9) | −1.5 (ahead in 5/15) | +2.4 (9/15) |
| with the `coarse` cascade (Phase 11) | **−0.2 (8/15)** | **+3.8 (12/15)** |

Enclosures gain more from filled heights than the grid does, which is what an LCZ-patch analogue
should do once `Hr` exists. The global mean hides the real structure, though:

| | overall B − A | built B − A |
|---|---:|---:|
| Europe + North America (7) | −2.1 | +2.8 |
| everywhere else (9) | **+1.3** | **+4.3** |

**Outside Europe and North America enclosures lead on both criteria.** They approximate an LCZ
patch in built fabric and smear the natural classes, which are large and heterogeneous — Jakarta
gives them +10.3 overall, Rio −11.3. The grid stays the default because overall agreement over the
whole set is what a user gets, but a per-region or configurable unit strategy is the live option,
and the case is no longer "the lead lives in one class of one city".
See [Phase 11](docs/experiments/phase-11-unit-decision.md).

[Phase 8](docs/experiments/phase-8-scaling.md) is what made that measurable, and is the reason the
fixture stopped being the only evidence.

## Phase 7 — the map site

`lczkit.viz.build_site(run_dir)` turns a run into `output/lczkit/<run_id>/site/` — a directory that
opens in a browser, reaches no network, and is meant to be archived beside a paper rather than run
as a tool. It needs the `viz` extra, which is one pinned wheel:

```sh
uv add --active --optional viz tippecanoe
lczkit site build <run_dir>
lczkit site serve <run_dir>           # then open the address it prints
```

`build_site(run_dir)` remains the library entry point, and `python <run_dir>/site/serve.py` still
works — the site ships its own server precisely so a recipient needs nothing installed.

```
site/
├── index.html          # no inlined data, no CDN link, no API key
├── style.json          # built from the run's legend and breaks, in Python
├── serve.py            # standard library only
├── assets/vendor/      # maplibre-gl 5.24.0 + pmtiles 4.4.1, both BSD-3-Clause, committed
├── tiles/*.pmtiles     # units, click detail, basemap, optionally buildings
└── manifest.json       # copied from the run, byte for byte
```

Four things about it are worth knowing before relying on it:

- **It is a pure transform of run outputs, and that is enforced rather than intended.** The style's
  LCZ colours are `classify.labels.legend()` and its choropleth boundaries are the manifest's own
  `breaks`; a test asserts both. The style is generated in Python precisely so those assertions are
  possible — the same claims made about `app.js` would be claims about a string. `write_run` gained
  a `layers=` argument so the basemap and the extrusions come from geometry the *run* persisted,
  which is what lets an archived run directory rebuild its own map with no access to `input/`.
- **It needs a local server, and that is a browser constraint rather than a design choice.** PMTiles
  reads byte ranges over `fetch`, and the Fetch standard leaves `file:` URLs unhandled, so a
  `file://` open fails in both Chrome and Firefox. The shipped `serve.py` is standard library only —
  including its own `Range`/206 support, because `SimpleHTTPRequestHandler` has none and would
  re-send a whole tileset per tile. Nothing reaches the network: no CDN, no glyph endpoint, no
  basemap key. What is given up is opening the file directly; what is kept is opening it offline.
  Every built site carries a `README.md` giving the working command (`python serve.py`, then
  <http://127.0.0.1:8000/>) and saying why the obvious one does not, since opening `index.html` is
  the first thing a recipient tries and it fails with an unexplained network error.
- **The basemap is the run's own Overture layers, not a Protomaps extract.** A Protomaps extract
  needs a Go CLI or a ~120 GB download; the run's water and streets are already there, are correctly
  attributable, and show the reader the same linework the classification was computed from. Land use
  is available and off by default: at 9 km² it was 94% of the basemap's bytes, for a wash drawn
  under a translucent fill.
- **Height provenance is the second layer in the selector, above the urban canopy parameters.**
  `height_completeness` and the `height_frac_*` tier fractions are first-class layers rather than
  diagnostics — they are the visible form of the package's central result. The tier fractions reach
  the render set through `viz.render_column_prefixes`, because their column names depend on which
  cascade a run chose; carrying them at every zoom costs about 0.71 MB per column at metropolitan
  scale, which is what a layer that must paint from already-loaded tiles is worth.
- **Buildings are off by default, and the default is measured.** See the table below.

Three cities are published, chosen on measured tier-1 coverage. Over cells containing buildings:

| city | built cells | tier-1 | WSF-3D | GHS-BUILT-H | unresolved | tiles |
|---|---:|---:|---:|---:|---:|---:|
| Berlin | 59 152 | **0.797** | 0.191 | 0.008 | 0.003 | 36.12 MB |
| Hong Kong | 25 233 | 0.308 | 0.547 | 0.120 | 0.026 | 20.43 MB |
| Cairo | 56 456 | **0.010** | 0.835 | 0.122 | 0.032 | 27.20 MB |

**83.5% of Cairo's building area takes its height from a 90 m TanDEM-X raster, against 79.7% of
Berlin's coming from real per-building heights.** That contrast is the founding premise, and on the
site it is a layer you can select rather than a number in a table. `scripts/publish_sites.py` builds
all three.

Site size at Berlin's full 891 km² — 172 181 units, 892 014 buildings — which is the scale that
makes this a decision. The whole site builds in **67 seconds**:

| tileset | zooms | features | size |
|---|---|---:|---:|
| `units.pmtiles` — render attributes | z10–14 | 172 181 | 28.09 MB |
| `units_detail.pmtiles` — everything else | z14 | 172 181 | 18.46 MB |
| `basemap.pmtiles` — water + streets | z9–13 | 201 144 | 9.24 MB |
| **default site** | | | **55.79 MB** |
| `buildings.pmtiles` — off by default | z14–16 | 892 014 | 76.85 MB |
| with buildings | | | 132.63 MB |

**Buildings are 58% of the site on their own**, which is why they are opt-in.

- **Attributes, not geometry, are what a unit tileset costs.** MVT repeats a feature's whole
  attribute table in every tile at every zoom. Tiling all 52 columns across z10–14 in one tileset
  costs 59.82 MB against the split's 46.55 MB — a 22% saving, and more to the point it halves what
  a reader fetches to pan around, since the detail tileset is touched only by a click at z14.

## Setup

This project runs on a shared HPC system. The Python environment lives outside the repo and
already exists — do not create a new one:

```sh
source /maps/acz25/envs/lczkit-env/bin/activate
uv add --active <package>       # the only way dependencies get added
```

Never run `uv sync`, `uv venv`, `pip install`, or `conda install` against this environment.

Point uv's and pip's caches away from the home directory quota (add to your shell profile, not
to this repo):

```sh
export UV_CACHE_DIR=/maps/acz25/.cache/uv
export XDG_CACHE_HOME=/maps/acz25/.cache
```

Copy `.env.example` to `.env` and set `DATA_DIR` to the shared data directory (see CLAUDE.md's
"Environment and paths" section for the expected `input/`/`output/` layout). `lczkit` only
ever reads from `input/` via source-specific subdirectories and writes under
`output/lczkit/<run_id>/`.

## Tests

```sh
pytest
```

Tests do not require `DATA_DIR` to be set and never touch the network — fixtures live under
`tests/fixtures/`.

**The primary fixture is a 3 km window over Kowloon, Hong Kong**, not Berlin. Berlin's labelled
cells hold two classes and both are mid-rise, so the height confusion axis has no pair to confuse
on and cannot be measured there at all — and Phase 6.7 ranked the axes from that fixture anyway,
putting compactness first, a ranking that stood for three phases until fifteen cities reversed it.
Hong Kong's window carries LCZ 1, 2, 3, 4 and 5, so both axes have complete pairs. Measured against
the labels, its disagreement splits 18.1% height / 27.6% compactness against Berlin's 17.0% / 55.2%
— compactness still leads, but Berlin's share was inflated by a reference that could contribute
both members of a compactness pair and only one member of any height pair. Berlin and Rotterdam
stay: every figure before Phase 11 is against Berlin, and Rotterdam is the industrial
fixture for the LCZ 10 rule. See [`tests/fixtures/README.md`](tests/fixtures/README.md).

Network-dependent tests are marked `@pytest.mark.network` and skipped by default:

```sh
pytest -m network
```

These hit live Overture and live Earth Engine. The Earth Engine ones additionally need
`GEE_PROJECT_NAME` and working credentials (`earthengine authenticate`); they skip rather than
fail when the project is unset, so a checkout without Earth Engine access can still run them.
