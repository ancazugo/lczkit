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
  surface fraction, `Hr`, building count, mean building area, `industrial_fraction` — plus the
  height cascade. It retains 99.5% of raw footprint area on the Berlin fixture.
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

- **Tiers 2–4 ship implemented but switched off.** None of those three products is on this
  system, so each tier's config carries no filename and is skipped; the cascade is simply
  shorter and buildings it cannot reach are tagged `unresolved` with a null height rather than
  given an invented one. Point `HeightConfig.areal_tiers` at a COG to switch a tier on.
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
| `h_mean_area_weighted`, `h_std` (secondary) | m | computed here |
| `aspect_ratio` | dimensionless | Stewart & Oke (2012), via `momepy.street_profile()` |
| `street_openness` | fraction | momepy |
| `street_width_m` | m | momepy |
| `building_count` | count | computed here |
| `mean_building_area_m2` | m² | computed here |
| `industrial_fraction` | fraction | computed here |
| `industrial_fraction_buildings`, `industrial_fraction_land_use` | fraction | computed here |
| `industrial_evidence` | category | computed here |

Five things about this phase are worth knowing before relying on it:

- **`Hr` is the geometric mean of building height, and only `Hr` may be classified on.** Stewart &
  Oke's height of roughness elements is `exp(mean(log h))` — Bernard et al. (2024) Table 1 — and
  the LCZ property ranges Phase 6 normalises against were defined for that quantity. The arithmetic
  mean sits above it whenever a unit mixes tall and short buildings, so substituting one for the
  other would bias exactly the heterogeneous units where classification is hardest, and would do it
  silently. `h_mean_area_weighted` and `h_std` ship as **secondary** columns for the deferred
  roughness work (Macdonald, Kanda); both are marked as such in the registry.
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
- **`industrial_fraction` is the only route to LCZ 10, and Overture cannot fully supply it.**
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
- **The `bernard2024` preset cannot be applied as published.** Its weights cover seven UCPs and
  lczkit computes five, so SVF (weight 4) and z₀ (0.5) — 4.5 of a published 21.5 — go unapplied
  and the effective built metric has three non-zero dimensions: `FB` 8, `Hr` 6, `H/W` 3. The
  manifest records the shortfall, because a comparison against a GeoClimate run is not a
  comparison of the same metric.
- **The LCZ 10 rule is implemented as specified and does not fire on real industrial data.** It
  relabels a unit whose two nearest prototypes are LCZ 8 and LCZ 10 and whose `industrial_fraction`
  clears a conservative threshold. On the Rotterdam fixture — 671 cells over a working port, 254
  industrial buildings, 75% of cells more than 90% industrial by area, and a reference map putting
  88 of them in LCZ 10 — **no unit has that pair as its two nearest prototypes at any threshold**,
  so the rule never gets the opportunity. Port plots are large and sparsely built, and the building
  surface fraction that dominates the built metric lands them on LCZ 9 instead. Every run's
  manifest reports the firing count so this is visible from the output rather than only here.
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

Measured on the Berlin fixture, over the 432 cells carrying both references:

| | agreement |
|---|---:|
| lczkit, against the labelled polygons | **40.9%** |
| `lcz_v3`, against the same labelled polygons — **the ceiling** | 53.2% |
| lczkit, against `lcz_v3` | 24.3% |

All 432 are built cells, so there is no natural cover inflating anything. Rotterdam has **no
labelled coverage** — So2Sat covers 52 cities and Rotterdam is not one of them — so it stays on
`lcz_v3` alone at 42.3% over 657 cells, of which 45.4% are natural: its water agrees at 95.5% while
its 359 built cells sit at 3.1%. That is the figure a built/natural split exists to stop anyone
quoting.

Three experiments in [`docs/experiments/`](docs/experiments/) record how those numbers got there.
[Phase 6.5](docs/experiments/phase-6.5-unit-scale.md) tests the obvious explanation for the original
17.7% — that Stewart & Oke's ranges describe an LCZ patch and a 100 m grid cell is not one — and
rejects it, finding instead that Phase 1 cleaning was destroying 23.5% of the footprint area behind
the metric. [Phase 6.6](docs/experiments/phase-6.6-footprint-attrition.md) fixes that.
[Phase 6.7](docs/experiments/phase-6.7-instrument-diagnostics.md) wires the real reference, measures
the ceiling, and **inverts the error diagnosis**: against `lcz_v3` the height axis carried 31.8% of
Berlin's disagreement, but against real labels it is compactness at 55.2% and height at 17.0%. Most
of the height-axis error attributed to lczkit was `lcz_v3`'s own tendency to read Berlin Mitte as
compact high-rise.

The remaining gap is 12.3 points against a real reference, and nothing downstream of it has been
tuned. It points at unit definition and footprint coverage first, the metric's missing
sky-view-factor dimension second, and the height cascade third.

**Enclosure-based computation leads the 100 m grid on Berlin against real labels** — 45.4% against
40.9%, the whole lead coming from LCZ 2 — but trails on Rotterdam, and Berlin's labelled cells hold
only two classes. It has not been adopted; the evidence and what is still missing are in the Phase
6.7 write-up.

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
`tests/fixtures/`. Network-dependent tests are marked `@pytest.mark.network` and skipped by
default:

```sh
pytest -m network
```

These hit live Overture and live Earth Engine. The Earth Engine ones additionally need
`GEE_PROJECT_NAME` and working credentials (`earthengine authenticate`); they skip rather than
fail when the project is unset, so a checkout without Earth Engine access can still run them.
