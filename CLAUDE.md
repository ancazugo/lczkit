# CLAUDE.md — Project Specification

> Package name: **`lczkit`**. PyPI distribution name and import name are the same.

## What this is

A Python library that maps a city into **Local Climate Zones** (Stewart & Oke 2012) from
open vector and raster data. It follows the *conceptual approach* of GeoClimate
(partition into spatial units → compute urban canopy parameters → classify by distance to
LCZ prototypes) but is an independent implementation with a pluggable data layer:
Overture Maps for vector, Google Earth Engine / STAC / local rasters for land cover, and a
tiered cascade for building heights.

The design bet: **GeoClimate's weakest point is building height completeness, and the
honest reporting of it.** Everything about height provenance in this spec is load-bearing,
not incidental.

---

## Non-negotiable constraints

Read this section before writing any code. Violations here are expensive to unwind.

### Licensing — this is the important one

- This package ships under a **permissive licence (MIT or Apache-2.0)**.
- **Do NOT read, copy, port, or transliterate source code from GeoClimate (LGPL-3.0) or
  UMEP / the `umep` PyPI package (GPL-3.0).** Implement from the published literature only —
  see the References section below, and `docs/references/README.md` for the paper-to-phase
  index.
- If you are ever unsure whether a piece of logic is derived from copyleft source, **stop and
  ask** rather than guessing.
- Do not add any GPL or LGPL dependency without flagging it first. Check the licence of every
  new dependency before adding it and note it in the PR description.

### Scope discipline

- Do not build features from the "Deferred" list without being asked.
- Do not add a CLI, a web UI, plotting helpers, or notebook tooling in the MVP.
- Do not add abstraction for plurality that does not yet exist. One implementation per
  protocol is correct for the MVP; the seam is the point, not the number of implementations.

### Process

- **Work one phase at a time. Stop at the end of each phase and report** — do not roll
  straight into the next phase.
- Each phase ends with: tests passing, `ruff` and `mypy` clean, and a short written summary
  of what was built, what was deferred, and any decision you had to make that the spec did
  not cover.
- Ask before making a decision the spec leaves ambiguous. Do not silently pick.

---

## Locked architectural decisions

These were decided deliberately. Do not revisit them without raising it explicitly.

**CRS policy.** All internal computation happens in a projected CRS obtained via
`gdf.estimate_utm_crs()`. Lat/lon appears only at ingestion and export boundaries. Enforce
with a decorator or a validation helper that asserts a projected CRS on entry, not with a
docstring convention.

**The unit of exchange.** A `GeoDataFrame` indexed by a stable string `unit_id`. Every stage
after unit generation is a join on `unit_id` — parameters, land cover fractions,
classification, provenance, validation. This is the main thing that makes the pipeline
testable in isolation; do not introduce a second exchange format.

**Config.** A single pydantic model. It is serialised verbatim into an output manifest
alongside the data, along with: the pinned Overture release string, GEE collection IDs and
date ranges, resolved package versions (`momepy`, `neatnet`, `geopandas`), and a run timestamp.
Reproducibility is a feature of this package, not an afterthought.

**Protocols, not ABCs.** Use `typing.Protocol` for `VectorSource`, `HeightSource`,
`RasterSource`, `SpatialUnitStrategy`, `Classifier`.

**momepy 1.0+ only.** Write against the functional API and `libpysal.graph`. The class-based
API and `Queen`/`W` objects are deprecated — do not use them, including in examples or tests.

**Heavy spatial work in DuckDB** (spatial extension) where it is a filter/join over
GeoParquet. GeoDataFrames at the boundaries of each stage. Do not prematurely add dask.

### Environment and paths — HPC constraints

This project runs on an HPC system with a small home-directory quota. Two consequences that
you must respect in every phase:

**The Python environment lives outside the repo and already exists.**

- It is at **`/maps/acz25/envs/lczkit-env`**.
- Install dependencies with **`uv add --active <package>`** only.
- **Never** run `uv sync`, `uv venv`, `pip install`, or `conda install`. Never create a virtual
  environment. Never write to `.venv/` in the repo.
- If a command fails because the environment is not active, stop and report it — do not
  attempt to create or repair an environment yourself.

**All data lives outside the repo, at the path in `DATA_DIR`.**

- A `.env` file at the repo root defines `DATA_DIR` (and possibly other paths). Load it with
  `python-dotenv` in the config layer.
- `DATA_DIR` is resolved **once**, in the pydantic config model, and every path used anywhere
  else derives from `settings.data_dir`. No module reads `os.environ` directly. No module
  builds a path relative to `__file__` or the current working directory.
- **This layout already exists and is shared with other projects. Respect it.** `input/` is
  organised by data origin; `output/` is organised by the tool that produced the results.
  `lczkit` owns `output/lczkit/` and nothing else — it must never write outside that directory.

  ```
  $DATA_DIR/
  ├── input/
  │   ├── Overture/        # keyed on (release, bbox, theme)
  │   ├── OSM/             # deferred alternative vector source
  │   ├── GEE/             # keyed on (units hash, collection, date range, reducer)
  │   ├── ESA_WorldCover/
  │   ├── GHSL/            # GHS-BUILT-H, height tier 4
  │   ├── GOB25D/          # Google Open Buildings 2.5D, height tier 2
  │   ├── WSF3D/           # WSF-3D, height tier 3
  │   ├── So2Sat-LCZ42/    # v4 — primary validation reference, see below
  │   └── ETH_CanopyHeight/
  └── output/
      └── lczkit/
          └── <run_id>/    # GeoParquet + manifest + cleaning report
  ```

- **So2Sat LCZ42 is available in full**, locally, at `$DATA_DIR/input/So2Sat-LCZ42/v4`. All tiles
  are in `patches_reference_rxr.gpkg`; per-city subsets are at
  `cities/<city name>/patches_reference_<city name>.gpkg`. Prefer the per-city file when working
  a single fixture. No download step is needed — this is the primary validation reference.

- **There is no separate cache directory.** Downloaded and derived source data is cached in
  place under `input/<Source>/`, with the cache key expressed as the file or subdirectory name.
  Caching is therefore indistinguishable from ingestion — a cache hit is just a file that is
  already there.
- Config exposes `settings.input_dir`, `settings.output_dir`, and a
  `settings.source_dir(name)` helper returning `input/<name>/`. Source implementations use the
  helper; they do not join paths themselves.
- Writes to `input/` are confined to the source implementation that owns that subdirectory.
  Nothing else in the package writes under `input/` at all.
- **Other projects read from `input/`.** Never delete, move, rename, or rewrite an existing
  file there. New files only. If a cached file looks stale or malformed, report it and stop —
  do not silently overwrite it.
- Runs are written to `output/lczkit/<run_id>/` so they do not clobber each other. Default
  `run_id` to a UTC timestamp, overridable in config.
- Also point package-external caches away from home in the documented setup:
  `UV_CACHE_DIR` and `XDG_CACHE_HOME`. Document this in the README; do not set it in code.
- **Exception:** test fixtures stay in the repo under `tests/fixtures/`, small and clipped, so
  CI works on a clean checkout with no `DATA_DIR`. Tests must not depend on `DATA_DIR` being
  set. If a fixture grows beyond a few MB, clip it further rather than moving it out.
- Fail loudly and early if `DATA_DIR` is unset or does not exist. A clear error at config load
  is much better than a confusing one three stages in.

---

## Test strategy

- **Fixture city**: a ~3×3 km bbox from a DFC2017 city (Berlin or Rome) so ground-truth LCZ
  polygons are available for free. Cache the Overture extract and a clipped land cover raster
  as files under `tests/fixtures/` so **CI never hits the network**.
- Unit tests per stage against the fixture. One end-to-end integration test that runs the
  full pipeline on the fixture and asserts on shape, schema, and CRS — not on exact values.
- Network-dependent tests (live Overture, live GEE) marked `@pytest.mark.network` and skipped
  by default.
- Property tests where cheap: e.g. land cover fractions sum to ~1.0 per unit; every
  `unit_id` present in the parameter table is present in the output.

---

## Phase plan

### Phase 0 — Skeleton (~2 days)

`pyproject.toml`, package layout, ruff + mypy config, pre-commit, pytest, GitHub Actions
running tests offline. Define all five Protocols with full type signatures and docstrings but
**no implementations**. Write the CRS assertion helper. Build the test fixture and commit it.

The pydantic config model is the main deliverable here. It must: load `.env` via
`python-dotenv`, resolve and validate `DATA_DIR`, expose `input_dir`, `output_dir`,
`source_dir(name)` and the resolved `run_dir`, create `output/lczkit/<run_id>/` if absent, and
fail with a clear message if `DATA_DIR` is unset or unreachable. It must **not** create or
modify anything under `input/`. Commit a `.env.example`.

`.gitignore` must ignore **PDFs, not the references directory**. Copyrighted PDFs stay out;
`docs/references/README.md`, `references.bib` and **everything in `docs/references/tables/`**
are committed. The transcribed tables are the authority for numeric lookups — a checkout
without them is a checkout that cannot reproduce a classification.

```gitignore
.env
docs/references/**/*.pdf
docs/references/datasets/
!docs/references/tables/
```

*Acceptance:* `pytest` runs green on an empty test suite with no `DATA_DIR` set; CI passes on a
clean checkout; protocols import cleanly; config round-trips to and from JSON; config raises a
clear error when `DATA_DIR` is missing.

---

### Phase 1 — Vector ingestion and cleaning (~5 days)

This phase determines whether everything downstream works. Expect it to overrun.

`OvertureSource` implementing `VectorSource`: DuckDB spatial reading bbox-filtered GeoParquet
from Overture's S3, with a local cache keyed on `(release, bbox, theme)`. Pin the release
string from config — never "latest".

Layers to pull:
- `buildings/building` — geometry, `height`, `num_floors`, `subtype`, `class`, `sources`.
  **`subtype`, `class` and `sources` must be retained through cleaning**, not dropped after
  geometry work. `class` carries usage type (residential / commercial / industrial) and is the
  only route to LCZ 10; `sources` carries dataset provenance and drives the Phase 3 diagnostic.
- `transportation/segment` where `subtype = 'road'`, dropping `class = 'service'`
- `base/water` — split linestrings (waterlines) from polygons (waterbodies); filter out
  underground/aboveground features and subtypes `human-made`, `reservoir`, `spring`,
  `wastewater`
- `base/land_use` — polygons, retaining `subtype` and `class`. Used **only** for functional
  semantics in Phase 6 (industrial fraction per unit). It is **not** a barrier in Phase 2 and
  **not** a land cover source in Phase 4 — rasters own land cover. Do not let it leak into
  either role.

Overture conflation is geometry-level and priority-ordered (OSM → Esri → high-precision Google
Open Buildings → Microsoft ML → lower-precision Google Open Buildings), and it is winner-takes-
all: a footprint's attributes come from whichever source won it. Attributes are **not** fused
across sources, and `height` is parsed only from OSM tags. Expect near-complete geometry with
very sparse heights in ML-dominated areas. Never treat a null height as an error in this phase
— Phase 3 owns that problem.

**Cleaning produces TWO building layers, not one.** This is the most important structural rule
in the phase. The original single-layer design was lifted from Majer & Fleischmann, where
cleaning exists to produce a valid planar partition for tessellation and losing building area is
irrelevant. Here building surface fraction carries roughly half the classification metric, so
cleaning optimised for topology silently destroyed the numerator: **measured 23.5% of Berlin's
footprint area lost, 3.148 → 2.408 km², worth 9.1 points of agreement.**

- **`buildings_topo`** — planar, non-overlapping. Feeds enclosure generation and anything needing
  a valid partition. Destructive operations permitted.
- **`buildings_area`** — area-preserving. Feeds building surface fraction and **every area
  statistic**. Only geometry validity fixes, multipolygon explosion, non-polygon removal,
  implausibly-large-footprint removal, and genuine duplicate removal. No absorption, no
  street-based dropping.

Both derive from the same source and share a building ID, so statistics remain joinable.

Shared operations: fix invalid geometries, explode multipolygons, drop non-polygon features,
drop implausibly large footprints (configurable threshold), merge and trim overlapping
footprints. Use `geoplanar` for planar enforcement on `buildings_topo`.

`buildings_topo` only:
- **`absorb_small_buildings` must DISSOLVE, not delete.** Union the small footprint into its
  neighbour. Deleting it discards area that was never spurious. If the current implementation
  drops, that is a bug, not a policy.
- **`drop_buildings_on_streets` must not delete on centreline intersection.** A perimeter block
  fronting a street routinely touches the centreline; that is normal European fabric, not an
  error. Drop only where overlap with a **road buffer** exceeds a configurable fraction of the
  footprint; trim rather than drop below that threshold.

Street simplification with `neatnet`, passing `buildings_topo` as the exclusion mask. This is
required, not optional — unsimplified dual carriageways and roundabouts destroy enclosure
generation downstream.

Cross-layer topology: apply water-based dropping to `buildings_topo`; drop waterlines passing
through buildings.

Emit a **cleaning report** recording, per operation, both feature counts **and total footprint
area** in and out. Area is the load-bearing number — the 23.5% loss above survived to Phase 6.5
precisely because only counts were tracked. Include it in the output manifest, and assert total
area retention on `buildings_area` in tests.

*Acceptance:* fixture city produces both layers and a simplified network; `buildings_area`
retains ≥99% of input footprint area after validity fixes; cleaning report is populated with
counts and areas; before/after values asserted in tests.

---

### Phase 2 — Spatial units (~2 days)

- `EnclosureUnits`: `momepy.enclosures()` with streets, rail, waterbodies and large vegetation
  patches as barriers, **clipped to the bbox**. This is the GeoClimate RSU analogue.
- `GridUnits`: 100 m regular grid in the local UTM CRS. Mandatory — it is what every existing
  LCZ map, validation dataset, and WRF workflow uses.
- `aggregate(from_units, to_units, method)` supporting `"majority"` and `"area_weighted"`.

**Units must form a partition of the bbox.** `momepy.enclosures()` defaults to `clip=False` and
will return faces formed outside the extent — measured at 222% of the bbox on Berlin and 379% on
Rotterdam, which silently corrupts the denominator of every area-weighted statistic downstream.
The original acceptance criteria were satisfiable by such a set, which is why it survived to
Phase 6.5.

*Acceptance:* both strategies produce units with stable unique `unit_id`s; aggregation between
them round-trips sensibly on the fixture; **and the union of units equals the bbox to within a
small tolerance, with no pairwise overlaps.** Assert both explicitly — this is a partition test,
not a validity test.

---

### Phase 3 — Height cascade (~5 days)

**This is the phase that differentiates `lczkit` from GeoClimate-on-OSM.** Overture solves
footprint coverage; it does not solve height. In ML-dominated areas — much of the Global South,
but also plenty of developed cities outside the centre — tier-1 heights will be near-absent.
The package's answer is a graded cascade plus honest reporting, not a pretence of completeness.

**Tiers**, in order. Build the cascade so adding a tier is a registration, not a rewrite:

1. Overture `height`; else `num_floors × storey_height` (storey height **configurable**,
   default 3.0 m — varies regionally and is a real error source)
2. **Google Open Buildings 2.5D** — fine-resolution heights across Africa, South and Southeast
   Asia, and Latin America. The highest-value tier for exactly the regions where tier 1 fails.
3. **WSF-3D** (DLR, TanDEM-X derived) — global ~90 m building height and volume
4. **GHS-BUILT-H** — global 100 m mean building height

Tiers 2–4 are areal products: they assign a neighbourhood mean to individual buildings. That is
a categorically weaker measurement than tier 1, and the output must say so.

**Per-building attributes:** `height`, `height_source` (which tier fired), `height_confidence`.

**Per-unit attributes:**
- `height_completeness` — area fraction of buildings with **tier-1** heights
- `height_tier_fractions` — the full distribution across tiers, not just tier 1. "90% real
  heights" and "90% coarse raster fallback" must be distinguishable in the output; they produce
  the same LCZ label with very different trustworthiness.

Both must appear in the final output. They are primary deliverables, not diagnostics.

**Source-availability diagnostic.** Report non-null `height` and `num_floors` counts grouped by
Overture source dataset, for the study area. This answers "is this city viable?" empirically
before anyone waits for a full run. Write it into the manifest.

**Expected degradation — document, do not treat as a bug.** LCZ separates low-rise (<10 m),
mid-rise (10–25 m) and high-rise (>25 m) largely on height. Areal height products cannot
resolve those bands within a heterogeneous unit, so error concentrates along the height axis
*within* a compactness category — 1↔4, 2↔5, 3↔6 — rather than scattering randomly. If Phase 6
validation shows that pattern in a low-`height_completeness` city, it is the data behaving as
expected.

**Raster access in this phase.** Tiers 2–4 need raster reads, but the `RasterSource` protocol
and its GEE backend are Phase 4. Do **not** pull Phase 4 forward. Implement a minimal local
zonal read here — the user places the product as a COG under `input/GOB25D/`, `input/WSF3D/` or
`input/GHSL/` — and let Phase 4 generalise it behind the protocol afterwards. This keeps Phase 3
unblocked, offline, and testable in CI. Structure the tier implementations so that swapping the
raster read for a `RasterSource` call in Phase 4 touches one function per tier.

*Acceptance:* every building has a non-null height and a source tag; `height_completeness` and
`height_tier_fractions` are computed per unit and present in the output schema; the
source-availability diagnostic appears in the manifest; a fixture-city test covers the case
where tier 1 is entirely absent.

---

### Phase 4 — Raster and land cover (~4 days)

`RasterSource` protocol returns a **fractions table keyed by `unit_id`** — not pixels.

Implement in this order:

1. **`LocalRasterSource`** first — user supplies a COG, zonal fractions via `exactextract`.
   This is what CI tests against; GEE auth in CI is not worth the pain.
2. **`EarthEngineSource`** second, identical interface. Compute server-side with
   `reduceRegions`, return tables. Chunk units into batches of a few thousand to stay under
   element-count and payload limits. Cache on a hash of
   `(unit geometries, collection ID, date range, reducer)`.

MVP datasets: ESA WorldCover v200 (pervious / impervious / water) and ETH 10 m canopy height
(tree fractions). The class → fraction mapping is **config, not hardcoded**.

*Acceptance:* both sources return schema-identical tables on the fixture; fractions sum to
~1.0; GEE path is skipped in offline CI.

---

### Phase 5 — Urban canopy parameters (~5 days)

From momepy:
- aspect ratio and street openness via `momepy.street_profile()` with heights attached

Computed here (momepy 1.0 has no functional equivalent for these):
- **building surface fraction** — from an overlay of **`buildings_area`** (never
  `buildings_topo`) against units, not `momepy.AreaRatio`, which was class-API and is gone in
  1.0. Using the topology layer here discards ~23% of footprint area and is the single largest
  known source of classification error. The overlay is required regardless, to match the
  building splitting rule established in Phase 3.
- **`Hr`, height of roughness elements — the GEOMETRIC mean of building heights**, per Stewart
  & Oke and Bernard et al. (2024) Table 1. **Not** the area-weighted arithmetic mean. The two
  diverge materially in units mixing tall and short buildings, and the Stewart & Oke ranges
  that Phase 6 normalises against were defined for the geometric mean — using the arithmetic
  mean would introduce a systematic, silent bias precisely in heterogeneous units. Floor
  heights at a small positive value before taking logs.
- `h_mean_area_weighted` and `h_std` as **secondary** columns. They are not `Hr` and must not be
  used for classification, but the deferred roughness work (Macdonald, Kanda) needs them.
- pervious / impervious / tree fractions from Phase 4
- building count, mean building area
- **`industrial_fraction`** — **share of building area** that is industrial, from Overture
  building `class` and the `base/land_use` layer. Denominator is building area, not unit area,
  matching Bernard et al. so his published threshold transfers. Retain the unit-area version as
  a secondary column. This is a *functional* attribute, not a morphological one. It exists
  because LCZ 8 and LCZ 10 are geometrically near-identical, and because **anthropogenic heat
  output is the only published Stewart & Oke property that separates them directly** (300+ vs
  ≤50 W m⁻²) — a property lczkit cannot measure. Record which evidence source contributed.

  **Known limitation, must be documented in the field docs and the manifest:** Overture exposes
  a single `industrial` value, with no heavy/light split. GeoClimate keys LCZ 10 on OSM's
  `HEAVY INDUSTRY` against light industry and commercial; that distinction does not survive
  Overture's schema normalisation. A light-industrial estate and a refinery are therefore
  indistinguishable here. This is the cost of Overture's normalised enums — the same
  normalisation that removes the need for a tag-mapping table also discards semantic detail
  OSM carried. `warehouse` stays excluded; it is an LCZ 8 example.

**Sky view factor is explicitly deferred.** It is the single most expensive component and is
strongly correlated with aspect ratio, which we have. Document this omission prominently in
the README — do not omit it silently.

*Acceptance:* a parameter table keyed by `unit_id` with every field documented, including
units and the source paper for each.

---

### Phase 6 — Classification, output, validation (~4 days)

**Classifier.** Prototype-distance, implemented from the Stewart & Oke parameter table.
Normalise each parameter against its LCZ-defined range, compute distance to each of the 17
prototypes, return the **full 17-way distance vector** plus `lcz_primary`, `lcz_secondary`,
and a `uniqueness` measure. Hard labelling is a downstream convenience function — the
distance vector is the primary output.

**Per-parameter weights are config, not assumptions.** The metric must accept a weight vector.
Ship two presets and make the active one appear in the manifest:
- `bernard2024_partial` (default) — the published defaults are SVF 4, H/W 3, `FB` 8, `FI` 0,
  `FP` 0, `Hr` 6, z₀ 0.5, totalling 21.5. **lczkit can apply only 17 of those units**: SVF and
  z₀ are deferred, and `FI`/`FP` are zero-weighted, leaving three non-zero dimensions. `FB`
  therefore carries roughly 47% of the metric on its own. The preset is named `_partial` for
  this reason — it is not Bernard's metric. Record the unapplied dimensions and the
  renormalisation in the manifest.
- `equal` — uniform weights, for comparison.

**This weighting interacts badly with the scale issue below.** The single parameter carrying
half the metric (`FB`) is also the one systematically biased by unit choice. Treat any
conclusion about classifier quality as provisional until the unit-scale experiment resolves.
When SVF arrives from deferred it takes weight 4 and materially reshuffles the metric — this
raises SVF's priority above the other deferred items.

**Resolved:** Bernard et al. (2024) §2.5, p. 2085 states the weights apply only to built types;
natural types go through a separate branch (Figs. 2–3). Phase 4's raster pipeline is therefore
**the only thing that classifies A–G at all** — the opposite of decorative.

**Null parameter policy.** Some units legitimately have null parameters — `aspect_ratio` is null
wherever no street reaches a building, which occurs in a small but nonzero share of units.
Handle by **weighted partial distance**: sum over available parameters only, renormalising by
the sum of their weights, so units are compared on a common scale. Do not impute, and do not
drop the unit. Record per unit: `n_params_used`, and the names of the missing parameters. Units
falling below a configurable minimum parameter count are labelled but flagged low-confidence via
`uniqueness`. This policy is shared with the LCZ 10 rule below and with validation.

**LCZ 10 assignment — supersedes the pair-gated rule.** The original design gated on LCZ 8 and
LCZ 10 being a unit's two nearest prototypes. **This was measured inert on the Rotterdam fixture
at every threshold from 0.05 to 0.5** — 671 cells of working port, 254 industrial buildings, 75%
of cells over 90% industrial by area, 88 placed in LCZ 10 by the reference map, and the pair
never opened. Port plots are large and sparsely built, so building surface fraction lands them
on LCZ 9. The threshold was never the binding constraint.

Follow Bernard et al. and **remove LCZ 10 from the distance metric entirely**, assigning it
functionally from `industrial_fraction`.

**Calibrate the threshold, do not pick it.** A naive `industrial_fraction > t` rule labels
roughly 500 of Rotterdam's 671 cells against a reference of 88 — failing in the opposite
direction to the old rule. Sweep the threshold against the Rotterdam reference, report the
**precision/recall curve in the manifest**, and choose the operating point. Expect to land
high-precision, low-recall, which is correct given Overture cannot separate heavy from light
industry: a missing LCZ 10 is a visible gap, a mislabelled light-industrial estate is an
invisible error that propagates into any consuming model.

**Diverge from Bernard on LCZ 8: keep it in the distance metric.** Bernard excludes it too, but
LCZ 8's defining character — large, low, sparse buildings — is genuinely morphological and mean
building area captures it. Excluding it would leave it assignable only functionally, which is
worse. Document the divergence.

Bernard's LCZ 1 building-levels constraint stays **exposed but off by default**; lczkit has no
reliable storey count.

Record per unit whether the functional assignment changed the label, and a per-run firing count
in the manifest — a rule that never fires must be distinguishable from one never configured.

**Output.** GeoParquet using LCZ Generator integer codes (1–10 built, 11–17 for A–G) and the
standard Demuzere colour table, so results drop into existing tooling. Plus a JSON manifest
containing the full serialised config, all source versions, and the cleaning report.

Also write a **viz-ready attribute table** (`units_viz.parquet`) alongside the GeoParquet:
floats rounded to three significant figures, the 17-way distance vector stored as scaled
integers, and precomputed classification breaks for every continuous variable written into the
manifest. This makes Phase 7 a pure transform of run outputs — the site build must never
recompute a parameter or a quantile.

**Validation module.** Agreement against the Demuzere global LCZ map (`lcz_v3.tif` — record the
version separately in the manifest; the Tier 1 citation describes an earlier one) on the 100 m
grid, reported lczexplore-style: per-class agreement and a sparse confusion matrix, not a single
accuracy number.

**Validate against labelled ground truth, not against another model.** `lcz_v3.tif` is an
estimate carrying its own error; measuring against it compares two models and reports the
disagreement as lczkit's error. Where labelled LCZ polygons exist for a fixture — So2Sat LCZ42 /
DFC2017, which is why Berlin was chosen in Phase 0 — **those are the primary reference** and
`lcz_v3` is a secondary comparator only.

**Measure and record the ceiling.** Compute agreement between `lcz_v3` and the labelled polygons
on the same fixture cells. That figure bounds what lczkit can score against `lcz_v3`, and every
residual gap must be interpreted against it before being treated as a defect. Put it in the
manifest. Do not pursue further classifier work until this number exists.

**Report built-class agreement separately from overall agreement**, always, with the natural-class
share of cells stated alongside. Rotterdam's headline 42.5% is 266 water cells agreeing at 95.9%
while LCZ 8 sits at 0.0% (n=224) and LCZ 10 at 1.1% (n=87). An overall figure dominated by
trivially-classified water says nothing about the classifier and must never be the reported
number.

**`lcz_v3.tif` is not ground truth.** GeoClimate's ~55% comparator was measured against a
national reference database; the Demuzere global map carries its own error, so agreement with it
has a ceiling materially below 100% even for a perfect map. Quantify that ceiling before treating
any remaining gap as a defect.

Report agreement stratified by `height_completeness` band (**equal-width bands, not
equal-count**, so they compare across cities), and break out **both** confusion axes separately.
The spec previously conflated them; they are different instruments:

- **Height axis — 1↔2↔3 and 4↔5↔6.** Compactness held fixed, height band varies. This is the
  diagnostic for areal height products, and the one that pairs with `height_completeness`.
- **Compactness axis — 1↔4, 2↔5, 3↔6.** Height held fixed, building surface fraction varies.
  This is the diagnostic for footprint coverage and unit definition.

*Acceptance:* end-to-end run produces a valid GeoParquet, `units_viz.parquet` and manifest; both
confusion axes reported separately; LCZ 10 precision/recall curve present for the Rotterdam
fixture.
### Phase 6.5 — Unit-scale experiment — CONCLUDED

**Result: the scale hypothesis was wrong. Do not re-run.** Enclosure-based computation does not
recover BSF: Berlin 17.7% (grid) → 17.3% (enclosure→grid), Rotterdam 42.5% → 42.2%. Rotterdam
moves backwards on its built classes, where enclosures are whole port basins. Arm B was given a
fair test — 78% of Berlin's enclosures are sub-1000 m² slivers but they hold only 4.1% of area,
the median cell takes its label from a 23,516 m² enclosure, and no cell is decided by one under
500 m². No sliver-merging was needed.

**The control arm found the real cause.** Arm C — grid units with *raw* Overture footprints —
reaches 26.8% on Berlin, +9.1 points. Phase 1 cleaning was destroying 23.5% of footprint area
before BSF was computed. The confusion axes carry the causal signature: restoring footprints
moves error off the compactness axis (2↔5 falls 216 → 146 units) and onto the height axis (1↔2
rises 49 → 111), which is what a corrected footprint deficit looks like. Arm B produced no such
shift.

**Retain the three-arm harness** as a permanent diagnostic. A control arm distinguishing "wrong
unit size" from "wrong numerator" is worth keeping, and its absence is why the earlier
pre-registered fallback pointed the wrong way.

**Range recalibration remains blocked.** Recalibrating Stewart & Oke against a parameter biased
by upstream data loss would encode that loss into the package's own definition of an LCZ and
forfeit comparability with the literature.
### Phase 6.6 — Footprint attrition remediation — CONCLUDED

`buildings_area` retains 99.49% (Berlin) / 100.00% (Rotterdam). Berlin arm A rose 17.7% → 24.3%
and converged with the raw-footprint control, which now has nothing left to recover. LCZ 1's BSF
entered its published range for the first time (0.326 → 0.437 against 0.40–0.60). Error moved off
the compactness axis (29.4% → 25.8%) and onto the height axis (19.9% → 31.8%), from the pipeline
rather than a control arm.

Findings worth keeping:
- The entire loss was `drop_buildings_on_streets` — 439 footprints, 0.704 km², mean 1603 m²
  against 531 m² for what it kept. `absorb_small_buildings` was worth 0.12%; fixed as a bug, not
  because it paid.
- Threshold: road half-width 4.0 m, overlap limit 0.5, derived from the monotone collapse in
  footprint size across the overlap range (1652 m² lowest decile → 60 m² highest, fixture median
  230 m²) rather than a gap. Narrower cannot separate (p95 = 0.46 at 2 m); wider swallows blocks
  (p90 = 0.98 at 8 m).
- **The rule is not an ML-noise filter.** Berlin's fixture is 6105 OSM footprints against 88
  Microsoft ML; the high-overlap tail is OSM kiosks and garages. It separates small structures
  standing in the roadway from blocks fronting it. The docstring must say so.

**Residual: 24.3% against the 50–60% imagery-based maps reach. Not closed.**
### Phase 6.7 — Instrument diagnostics — CONCLUDED

**The ceiling is 53.2%.** On the 432 Berlin fixture cells carrying both references, `lcz_v3.tif`
agrees with So2Sat labels 53.2% of the time. The 50–60% band lczkit was held to is a band the
comparator does not itself clear here.

| Berlin, same run, same cells | agreement |
|---|---|
| lczkit arm A vs So2Sat labels | **40.9%** |
| `lcz_v3` vs So2Sat labels — the ceiling | 53.2% |
| lczkit arm A vs `lcz_v3` | 24.3% |

**The residual is 12.3 points, not 26.** lczkit beats `lcz_v3` outright on LCZ 5 (32.1% vs 18.8%)
and trails on LCZ 2 (43.7% vs 63.7%). Nothing was tuned to achieve this.

**The error diagnosis inverted.** Against `lcz_v3`, Berlin's height axis carried 31.8% of
disagreement and compactness 25.8%. Against real labels it is compactness 55.2%, height 17.0% —
most of the apparent height error was `lcz_v3` reading Mitte as compact high-rise. Phase 6.6
promoted height estimation on evidence taken against the wrong reference. **Revised candidate
order: unit definition / footprint coverage → SVF → height.**

Also resolved: `is_planar_enforced: True` (three zero-area-overlap footprint pairs cleared by a
1 µm buffer subtraction, 4.5×10⁻⁵ m² of 3.13 km², running after `absorb_small_buildings`).
`eps_m` correctly kept as a module constant — a floating-point tolerance is not a domain
threshold.

**Rotterdam is no longer a validation city.** LCZ 8 median BSF 0.126 against a published
0.30–0.50, bimodal shed/apron rather than flat low, arms A and C identical so cleaning removes
nothing — and **10.7% of reference LCZ 8 cells contain no building at all.** The reference is
coarser than the ground. With no So2Sat coverage either, its agreement figure carries no signal.
Retain Rotterdam as the industrial fixture for the LCZ 10 rule only; drop it from quality
reporting.

**A vs B: do not adopt enclosures.** B leads Berlin against labels 45.4% vs 40.9% and lowers the
compactness axis 55.2% → 49.0%, but the entire lead lives in one class of one city and it still
trails Rotterdam. Revisit only with metropolitan-scale evidence.

---

## MVP COMPLETE — baseline recorded

**Berlin 40.9% against So2Sat ground truth, ceiling 53.2%.** 77% of the comparator's performance,
outperforming it on LCZ 5. This is the baseline. **Stop optimising agreement.**

The remaining 12.3 points are no longer a mystery to be investigated: SVF is weight 4 in a metric
currently running on three dimensions, and the compactness axis points at unit definition. Both
are scoped deferred work. Do not open further diagnostic phases against the 9 km² fixture.

---

### Phase 8 — Scaling — CONCLUDED

**Berlin's full 891 km² administrative extent cleans end to end in 9.8 minutes** (585.6 s),
267 021 → 195 508 streets over 594 tiles on 256 workers, retaining 99.947% of footprint area —
against a 15h14m run that never finished. Every remaining whole-extent step is sub-linear (max
exponent 0.93, `clean_buildings`).

**Pooled artifact threshold: ADOPTED.** The pre-registered bar — "does not move any
classification" — was **wrong, and is superseded.** It presumed the whole-network threshold is
reference truth. It is not: both are estimators of the same heuristic cut point, and neither has a
claim to correctness. Six differing cells is two estimators disagreeing, not six errors.

The corrected bar, and the measurements against it:

| criterion | result |
|---|---|
| no systematic bias | both estimators converge; pooled returns 8.187586 three consecutive extents, whole-network settles at 8.191828 — 4 parts in 10 000 |
| deviation not growing with extent | **shrinks**: 0.0257 (256 km²) → 0.0042 (400, 484 km²) |
| flips confined to adjacent classes | yes — 5→4 ×2, 9→5 ×2, 8→6, 12→11 |
| flip rate below enterprise noise | 6 / 26 040 = 0.023%, against a package agreement of 40.9% versus a 53.2% ceiling |
| cost | **~8.6 h → ~70 s**, up to 193× at 484 km² |

Conditions: the 891 km² A/B is still to be reported; a materially higher flip rate there reopens
this decision.

**Per-seam stitching: built, measured, REVERTED.** Its premise was false. At 891 km² the global
stitch is **17.4 s, not 6h50m**; per-seam was 24% slower, diverged in linework (23.5 km of 19 078,
0.12%), and left `aspect_ratio` twice as far from the whole-extent answer (mean |Δ| 0.150 vs
0.072). The 6h50m had been attributed to `_stitch` by inference — it is the next thing the code
does — and a fix built on that inference without checking.

**The real second bookend, found by systematic sweep:** `resolve_buildings_on_streets` intersected
every footprint against one unioned road geometry — 87.8 s for 9 563 footprints at 16 km² against
2.1 s to build the union, extrapolating to ~75 h over Berlin. It had never surfaced because no run
had ever reached it. Index-bounding is **exact**: 39.3× faster, symmetric difference 0.0 m².

`forkserver` note: a forkserver child re-executes the parent entry point like a spawn child does.
`__main__`'s `__file__` and `__spec__` are hidden for the life of the pool.

**The tiling core is validated.** 891 km² of Berlin, 594 tiles, simplified in **7.5 minutes**
against ~28 hours projected untiled. Building cleaning is near-linear — 76.2 s for 303k footprints
at 400 km², so ~4 min at 892k — and is not a problem; the earlier suspicion there was wrong.

**Two serial bookends around the tiling are quadratic**, and together account for the entire
15-hour runtime:

| step | scaling | cost at metropolitan scale |
|---|---|---|
| `resolve_artifact_threshold` → `neatnet.fix_topology` on the whole network | exponent **2.0** in feature count (measured at 64/144/256/484 km²) | ~8.6 h extrapolated, ~8h15m observed |
| `_stitch` → `remove_interstitial_nodes` on the full stitched network | quadratic | 6h50m and not completing |

A whole-network step was introduced **to make seams correct** and reintroduced the quadratic that
Phase 8 exists to remove. This is the third time in this project a correctness mechanism has
created a defect that took a phase to find.

**Three fixes, in this order:**

1. **`mp_context="forkserver"`** on the process pool. The default `fork` deadlocks when the parent
   has already run threaded native libraries — observed as parent and all 32 workers at zero CPU.
   Also set `OMP_NUM_THREADS=1` and the MKL/OpenBLAS equivalents in workers; 32 workers each
   spawning their own thread pool is the same root cause one step later. Do this first — it
   unblocks measuring the other two in parallel.
2. **Pin the artifact threshold from pooled per-tile distributions**, not the whole network. Each
   tile already runs `fix_topology` on its own window inside `neatify`; pooling the per-tile
   face-artifact-index distributions costs k × (n/k)² and parallelises.
3. **Stitch per seam, not globally.** `remove_interstitial_nodes` only needs to run on linework
   near a seam; tile interiors are already healed.

**Fixes 2 and 3 each replace a global operation with a local one, and in both cases the
correctness argument is "the interior is already handled." That argument must be measured, not
asserted.** Required validation for each:

- **Fix 2:** compute the tile-pooled threshold at 64, 144, 256 and 484 km² and compare against the
  whole-network thresholds already measured at those extents. Faces spanning seams are split or
  absent from every tile's distribution, so the pooled distribution is an approximation with an
  unbounded error until measured. Adopt only if deviation does not move any classification, and
  record the measured deviation. Divergence growing with extent is disqualifying.
- **Fix 3:** compare per-seam stitched output against globally stitched output at 64 km², where
  global remains tractable. The existing seam metric (99.97%) is the instrument.

*Acceptance:* a full Berlin metropolitan extent completes end to end within a documented wall
time; both equivalence tests pass with recorded deviations; per-tile results cached; no remaining
whole-extent operation with an unmeasured scaling exponent.

**lczkit cannot currently process a city.** `neatnet` is superlinear in extent: 9 km² cleans in
~1 minute, 144 km² ran 1h35m and 256 km² 2h35m without completing. This has been invisible for
seven phases because the fixture is 9 km², while three phases were spent chasing agreement points
on that fixture. A package scoring 40.9% that runs on a whole city is worth far more than one
scoring 45% on a tile it cannot leave.

Everything else — Phase 7, SVF, unit definition, height tiers — is downstream of this.

1. **Profile first.** Confirm the cost is `neatnet` itself and not the exclusion mask or an
   upstream join. Do not optimise on assumption.
2. **Spatial chunking with buffered overlap**: tile the extent, simplify per tile, stitch at the
   seams. Superlinearity is what makes this pay — k tiles is much cheaper than one extent.
   Seam correctness is the hard part; test that a road crossing a tile boundary simplifies
   identically to the untiled case.
3. **Parallelise across tiles.** This is an HPC deployment with idle cores.
4. **Cache per-tile results** under `input/`, keyed like every other cache.
5. Re-run the metropolitan A/B comparison once it completes — that decision is gated on this,
   not on the classifier.

*Acceptance:* a full Berlin metropolitan extent completes end to end within a documented wall
time; tiled and untiled simplification agree on a fixture-scale extent; per-tile results cached.

---

**891 km² A/B — adoption CONFIRMED.** Whole-network 8.140679 (38 372 s / 10h39m) against pooled
8.131236 (~70 s): deviation 0.009443, **10 of 172 181 cells moved (0.0058%)** — a four-fold fall
from 0.0230% at 256 km². The reopening condition is not met. Note the exponent-2.0 fit projected
~8.6 h against a measured 10h39m: **power-law extrapolations from small extents run optimistic**,
so treat such fits as lower bounds when deciding feasibility. Downstream pipeline arms took 456 s
and 551 s.

Three of the ten moves involve LCZ 10, which the distance metric never assigns. The path is real
and unverified: `resolve_buildings_on_streets` consumes the simplified network, so a different
threshold trims different footprints and every building-area parameter — including
`industrial_fraction` — moves with it. **Check this first if those transitions ever matter.**

**Open, low-cost, fix before the paper:** cached and cold runs differ by 75 of ~198 800 features.
The pipeline is therefore not run-to-run deterministic and **the cache is not transparent** — a
cache that changes results is a different object from one that skips work. This holes the
reproducibility claim that the pinned manifest exists to make. Stitch ordering is the suspect;
likely an unsorted set or dict iteration.

---

### Phase 9 — Multi-city validation — NEXT

**Everything known about lczkit's accuracy comes from one city.** 40.9% against a 53.2% ceiling on
Berlin may be typical, fortunate or unfortunate, and this project's history is of
single-measurement conclusions turning out to be artefacts. The economics have inverted: a full
city runs in ~8–9 minutes and **So2Sat's 42 cities are already on local disk** at
`$DATA_DIR/input/So2Sat-LCZ42/v4/cities/`. Ten cities is an afternoon.

Run ≥10 So2Sat cities end to end. For each, report: per-city ceiling (`lcz_v3` vs labels), lczkit
agreement vs labels, built-class agreement separately, both confusion axes, and
`height_tier_fractions`.

This resolves three open questions in one pass:

1. **A vs B.** Deferred twice because the lead lived in one class of one city. Unit definition is
   55.2% of Berlin's disagreement — the largest available lever. Decide it here.
2. **Generalisation.** One number becomes a distribution, which is what the paper needs regardless.
3. **The founding premise.** The height cascade was built for cities where OSM heights fail and has
   never run outside Europe. **Include São Paulo and at least one South/Southeast Asian city.**
   `height_tier_fractions` there is the first real test of the argument this package was started to
   make.

**Do this before SVF.** SVF is weeks and answers one question; this is a day and answers three —
including whether SVF is the right next lever at all. If the residual is compactness-dominated
across cities, unit definition matters more than a fourth metric dimension.

*Acceptance:* a per-city table of the metrics above for ≥10 cities including ≥2 outside Europe; an
A/B recommendation with multi-city evidence; a stated recommendation for the next accuracy lever
based on which confusion axis dominates across cities.

---

### Phase 7 — Static map site (~5 days, post-MVP)

Build **after** the MVP is complete. The deliverable is a self-contained, archivable directory
that opens with no server and no network access — it is a paper supplement, not a dev tool.

**Do not build a Python web app.** No Streamlit, no Dash, no Panel, no marimo, no kepler.gl
embed. No live kernel, no callbacks, no CDN links, no basemap API keys. If the design starts
requiring a running Python process to view a map, it has gone wrong.

`lczkit.viz.build_site(run_dir)` writes:

```
output/lczkit/<run_id>/site/
├── index.html
├── assets/               # maplibre-gl + pmtiles protocol, VENDORED not CDN
├── tiles/
│   ├── units.pmtiles
│   ├── basemap.pmtiles   # Protomaps extract clipped to city bbox
│   └── buildings.pmtiles # optional, config flag, default OFF
└── manifest.json         # copied from the run
```

**Tile generation.** `tippecanoe` as an optional extra (`lczkit[viz]`), pinned, invoked as a
subprocess — never linked or vendored. Chain: GeoParquet → **FlatGeobuf** via `pyogrio` →
tippecanoe → PMTiles. Do not route through GeoJSON; at buildings scale it is dramatically
slower. Choose zoom ranges and `--drop-densest-as-needed` deliberately and record the exact
tippecanoe invocation in the manifest.

**Rendering.** MapLibre GL with the PMTiles protocol, over HTTP range requests. Layer
switching is a client-side style expression over already-loaded tiles — never a refetch and
never a re-render of the source.

Layers:
- LCZ primary class (default view, Demuzere colour table)
- any single UCP as a choropleth, using the precomputed breaks from the manifest
- `uniqueness`
- `height_completeness`
- buildings as MapLibre native `fill-extrusion` driven by the `height` attribute, optionally
  coloured by `height_source`. **Use `fill-extrusion`, not deck.gl** — no extra bundle is
  justified unless a requirement appears that MapLibre genuinely cannot meet.

**Per-unit inspection.** Click a unit → sidebar showing `lcz_primary`, `lcz_secondary`,
`uniqueness`, a small bar chart of the 17-way distance vector, every UCP with its unit of
measurement, and the height-provenance breakdown for that unit.

**Permalink.** Encode map centre, zoom, active layer and selected `unit_id` in the URL hash, so
a specific unit can be cited directly.

*Acceptance:* the site directory opens correctly from `file://` with networking disabled, and
serves correctly from `python -m http.server` behind an SSH tunnel; layer switching does not
refetch tiles; the whole directory is portable to static hosting unchanged.

---

## References

PDFs live in `docs/references/`. They are present on disk but **gitignored and not committed**
(licensing, not size). Treat them as read-only local reference material: read them freely, never
`git add` them, and never quote more than a short phrase into code comments or docs. If a PDF
you need is absent, say so rather than proceeding from memory on anything in Tier 1.

Transcribed parameter tables live in `docs/references/tables/` as markdown. **Prefer these over
the PDFs** for any numeric lookup: they are hand-checked, cheaper to read, and not subject to
PDF table-extraction errors. If a table you need is not transcribed, ask before reading the
PDF and inferring it.

### Tier 1 — authoritative numbers. Never invent these; read the source.

| Reference | DOI / ID | Used by |
|---|---|---|
| Stewart & Oke (2012), *BAMS* 93(12), 1879–1900 | `10.1175/BAMS-D-11-00019.1` | Phase 6 — LCZ definitions and the full property-range table. The most important document in the repo. |
| Stewart, Oke & Krayenhoff (2014), *Int. J. Climatol.* 34(4), 1062–1080 | `10.1002/joc.3746` | Phase 6 — refined per-class UCP values |
| Bernard et al. (2024), *GMD* 17, 2077–2107 | `10.5194/gmd-17-2077-2024` | Phases 2, 5, 6 — RSU partitioning, the 14 UCPs, normalisation and distance-to-prototype classification. Open access. |
| Bernard et al. (2022), *GMD* 15, 7505–7532 | `10.5194/gmd-15-7505-2022` | Phase 3 — missing building height estimation. Open access. |
| Demuzere et al. (2022), *ESSD* 14, 3835–3873 | `10.5194/essd-14-3835-2022` | Phase 6 — integer coding convention, colour table, validation target |
| Davenport et al. (2000), AMS 12th Conf. Applied Climatology | — | **Deferred** — terrain roughness class lookup. Requires z₀, which is deferred; not satisfiable in Phase 5. |

### Tier 2 — deferred algorithms, included ahead of need

| Reference | DOI / ID | Used by |
|---|---|---|
| Bernard et al. (2018), *Climate* 6(3), 60 | `10.3390/cli6030060` | Deferred — vector ray-launching SVF. **Preferred route for this package.** Open access. |
| Lindberg & Grimmond (2010), *Climate Research* 42, 177–183 | `10.3354/cr00882` | Deferred — raster SVF alternative |
| Zakšek, Oštir & Kokalj (2011), *Remote Sensing* 3(2), 398–415 | `10.3390/rs3020398` | Deferred — cheaper raster SVF approximation |
| Macdonald, Griffiths & Hall (1998), *Atmos. Environ.* 32(11), 1857–1864 | `10.1016/S1352-2310(97)00403-2` | Deferred — z₀ / z_d from plan and frontal area index |
| Kanda et al. (2013), *Boundary-Layer Meteorol.* 148, 357–377 | `10.1007/s10546-013-9818-x` | Deferred — improved z₀ / z_d for heterogeneous surfaces. Preferred over Macdonald here. |
| Grimmond & Oke (1999), *J. Appl. Meteorol.* 38, 1262–1292 | `10.1175/1520-0450(1999)038<1262:APOUA>2.0.CO;2` | Deferred — framing for morphometric roughness methods |

### Tier 3 — methodology and design context

| Reference | DOI / ID | Used by |
|---|---|---|
| Majer & Fleischmann, arXiv:2603.00132 | `arXiv:2603.00132` | Phase 1 — Supplementary D is the cleaning spec. Supplementary A is a morphometrics menu. |
| Fleischmann (2019), *JOSS* 4(43), 1807 | `10.21105/joss.01807` | Phases 2, 5 — momepy |
| Fleischmann et al. (2026), *CEUS* 123, 102354 | `10.1016/j.compenvurbsys.2025.102354` | Phase 1 — neatnet street simplification |
| Arribas-Bel & Fleischmann (2022), *Habitat International* 128, 102641 | `10.1016/j.habitatint.2022.102641` | Phase 2 — enclosed tessellation and barrier logic |
| Quan & Bansal (2021), *Building & Environment* 196, 107791 | `10.1016/j.buildenv.2021.107791` | Phase 6 — how thresholds are chosen in practice |
| Bechtel et al. (2015), *IJGI* 4(1), 199–219 | `10.3390/ijgi4010199` | Context — WUDAPT Level 0 protocol |
| Demuzere, Kittner & Bechtel (2021), *Front. Environ. Sci.* 9, 637455 | `10.3389/fenvs.2021.637455` | Context — LCZ Generator |
| Fonte et al. (2019), *Urban Climate* 28, 100456 | `10.1016/j.uclim.2019.100456` | Context — OSM for LCZ |
| Huang et al. (2023), *RSE* 292, 113573 | `10.1016/j.rse.2023.113573` | Context — LCZ mapping review |
| Gousseff et al., lczexplore | `10.5281/zenodo.7646866` | Phase 6 — agreement-metric reporting format |

### Tier 4 — dataset documentation (`docs/references/datasets/`)

Class definitions here become **config values**, so read them rather than assuming.

| Source | Used by |
|---|---|
| ESA WorldCover v200 Product User Manual (Zanaga et al.) | Phase 4 — pervious / impervious / water class mapping |
| Lang et al. (2023), *Nat. Ecol. Evol.* 7, 1778–1789, `10.1038/s41559-023-02206-6` | Phase 4 — ETH global canopy height |
| GHSL GHS-BUILT-H technical documentation (Pesaresi et al., JRC) | Phase 3 — height fallback tier |
| Overture Maps schema reference (buildings, transportation, base) | Phase 1 — pin the schema version |

### Deferred-tier sources

Kamath et al. (2024), *Sci. Data* 11, 886 — UT-GLOBUS ·
Zhu et al. (2025), *ESSD* 17, 6647 — GlobalBuildingAtlas ·
Milojevic-Dupont et al. (2020), *PLOS ONE* 15(12), e0242010 — height from urban form ·
Demuzere et al. (2022), *JOSS* 7(76), 4432 — W2W / WRF export

---

## Resolved discrepancies

Where this spec and a source paper disagreed, the ruling is recorded here so it is not
relitigated each session. **When a new discrepancy appears, flag it and stop — do not
reconcile silently.** That flagging behaviour is working; keep it.

| Issue | Ruling | Phase |
|---|---|---|
| `Hr` — spec said area-weighted arithmetic mean; Bernard et al. (2024) Table 1 says geometric mean | **Paper wins.** Geometric mean. The Stewart & Oke ranges were defined for it; the arithmetic mean biases heterogeneous units silently. Area-weighted mean retained as a secondary column for deferred roughness work. | 5 |
| `momepy.AreaRatio` removed in momepy 1.0 | Compute building surface fraction from a building/unit overlay. The overlay was required anyway to match Phase 3's splitting rule. Spec corrected — momepy's genuine role in Phase 5 is `street_profile()`. | 5 |
| `docs/references/` gitignored wholesale, hiding committed `tables/` | Spec bug, corrected. Ignore PDFs, not the directory. `tables/`, `README.md` and `references.bib` are committed. | 0 |
| Null `aspect_ratio` where no street reaches a building | Weighted partial distance with renormalisation. No imputation, no dropping. | 6 |
| Overture has no heavy/light industry split | Accepted limitation, documented, conservative threshold. Not solvable within Overture's schema. | 5, 6 |
| `momepy.describe_agg` unused | Correct call — it requires numba (absent) and offers only one-building-to-one-unit semantics. | 5 |
| `gpd.overlay` `keep_geom_type` warning | Correct not to silence package-wide, which would mask real geometry-type problems. If the noise becomes a problem, scope suppression to the specific call site with a comment explaining why it is benign there. | 3, 5 |
| Confusion pairs 1↔4, 2↔5, 3↔6 labelled "height axis" | **Spec bug, corrected.** Those hold height fixed and vary compactness. The height axis is 1↔2↔3 and 4↔5↔6. Both are now reported, separately and correctly named. | 6 |
| Bernard weights — do they apply to natural types? | **Resolved from the paper**, §2.5 p. 2085: built types only; natural types are a separate branch. Phase 4's rasters are the sole classifier for A–G. | 6 |
| `bernard2024` preset only partially applicable | Renamed `bernard2024_partial`. 17 of 21.5 weight units applied; SVF and z₀ deferred; `FB` carries ~47% of the metric. Unapplied dimensions recorded in the manifest. | 6 |
| LCZ 10 pair-gated rule measured inert on Rotterdam | Rule replaced. LCZ 10 removed from the distance metric per Bernard; assigned functionally with a threshold **calibrated by precision/recall against the Rotterdam reference**, not chosen a priori. | 6 |
| LCZ 8 — Bernard also excludes it from the distance approach | **Diverge from Bernard: keep LCZ 8 in the metric.** Its character is genuinely morphological and mean building area captures it. Documented divergence. | 6 |
| `industrial_fraction` denominator | Changed to share of **building** area, matching Bernard, so his 0.33 transfers. Unit-area version retained as secondary. | 5 |
| Davenport terrain roughness class in Phase 5 | **Spec bug, corrected.** Requires z₀, which is deferred. Moved to deferred alongside the roughness work. | 5 |
| Anti-pattern "don't commit anything from `docs/references/`" contradicting Phase 0 | **Spec bug, corrected** (third occurrence). PDFs are ignored; `tables/`, `README.md`, `references.bib` are committed. | 0 |
| Stewart & Oke cannot classify the natural family | **Accepted for MVP.** A–D separate only on building-derived parameters; F and G differ in no published dimension. lczkit-defined `tree_fraction`/`water_fraction` ranges tagged `source="lczkit"`; C and F recorded unreachable in the manifest. Reading Bernard's natural branch (Figs. 2–3) and feeding canopy height as the natural roughness element is **deferred**, not rejected. | 6 |
| Five of ten Stewart & Oke properties never reach the metric | Accepted and documented. Anthropogenic heat is the only published property separating LCZ 10 from 8 directly (300+ vs ≤50 W m⁻²) and is unmeasurable here — the standing justification for a functional attribute. | 6 |
| Global LCZ map is `lcz_v3.tif`; Tier 1 citation describes an earlier version | Record both in the manifest. Update the references README to cite v3. | 6 |
| Stale Overture cache entry for a discarded bbox | Correct not to delete. Mark superseded entries with a `<name>.discarded` sidecar. | 1 |
| Phase 1 cleaning destroyed 23.5% of footprint area | **Spec bug, corrected.** The cleaning pipeline was lifted from Majer & Fleischmann, where it serves tessellation and area loss is irrelevant; here BSF carries ~half the metric. Split into `buildings_topo` and `buildings_area`. | 1, 5 |
| `absorb_small_buildings` deletes rather than dissolves | Bug, not policy. Must union the small footprint into its neighbour. | 1 |
| `drop_buildings_on_streets` deletes on centreline intersection | Wrong for perimeter blocks, which routinely touch the centreline. Use road-buffer overlap fraction; trim rather than drop below threshold. | 1 |
| Cleaning report tracked counts but not area | **Spec bug, corrected.** Area is the load-bearing number; its absence let a 23.5% loss survive four phases. | 1 |
| `momepy.enclosures(clip=False)` returned faces outside the bbox | Defect found in Phase 6.5: 222% of extent on Berlin, 379% on Rotterdam. Units were not a partition, so every area-weighted denominator was wrong. Phase 2 acceptance now asserts partition explicitly — the original criteria were satisfiable by a non-partition. **All pre-fix enclosure statistics are void.** | 2 |
| Rotterdam's 42.5% headline is water | Validation must report built-class agreement separately, with natural-class share stated. LCZ 8 was 0.0% (n=224), LCZ 10 1.1% (n=87). | 6 |
| BSF grouped by assigned class appeared to validate the ranges | Circular — the classifier placed those units near that prototype. Only the reference-class grouping is a test. Both stay in the JSON. | 6.5 |
| Worktree tests ran against the installed source, not the worktree | Unsound bisect method, self-caught and redone with `PYTHONPATH` pinned. Pin `PYTHONPATH` to the worktree whenever bisecting or testing in one. | — |
| Validation ran against `lcz_v3.tif` as if it were ground truth | **Spec bug, corrected.** It is an estimate with its own error. Labelled So2Sat/DFC2017 polygons are the primary reference where they exist; `lcz_v3` is secondary, and the two must be compared to establish the ceiling. | 6, 6.7 |
| `drop_buildings_on_streets` framed as an ML-artefact filter | Wrong framing on my side. Berlin's fixture is 6105 OSM vs 88 Microsoft ML footprints; the rule separates small structures standing in the roadway from blocks fronting it. Threshold: half-width 4.0 m, overlap 0.5, derived from monotone size collapse rather than a gap. | 1 |
| `geoplanar.merge_touching` silently deletes isolated polygons | Cannot be configured off; deleted 1043 of 1186 sub-20 m² Berlin footprints. Isolates now held back and concatenated in. Worth 0.12% of area — fixed as a bug, not for the gain. | 1 |
| Phase 6.5's rejection of the scale hypothesis | **No longer stands.** It was measured over a broken numerator. With footprints restored, arm B leads Berlin 28.4% vs 24.3%. Decision deferred to 6.7 pending the planarity fix and a real reference — not reversed, re-opened. | 6.5, 6.7 |
| `buildings_area` — trim overlaps but do not merge | Confirmed. BSF sums overlay pieces, so overlaps double-count. Resolves the contradiction between the shared-operations sentence and the `buildings_area` list. | 1, 5 |
| `street_profile` layer choice | Confirmed: `street_profile` reads `buildings_topo`; every area statistic reads `buildings_area`. | 5 |
| Target of 50–60% agreement | **Wrong target.** `lcz_v3` itself reaches only 53.2% against So2Sat labels on the Berlin fixture. lczkit's 40.9% is 77% of the comparator, beating it on LCZ 5. Baseline accepted; agreement optimisation stopped. | 6.7 |
| Height promoted to first candidate cause in 6.6 | **Reversed.** That evidence was taken against `lcz_v3`, whose own error inflated the height axis. Against labels: compactness 55.2%, height 17.0%. Order is now unit definition → SVF → height. | 6.6, 6.7 |
| Rotterdam treated as a validation city | Dropped from quality reporting. 10.7% of its reference LCZ 8 cells contain no building; no So2Sat coverage. Retained as the industrial fixture for the LCZ 10 rule only. | 6.7 |
| Enclosure-vs-grid BSF comparison on Berlin | Self-corrected: the two sets covered different ground (0.15 vs 0.29 km²). Covered area must be printed beside any such comparison. Rotterdam's comparable sets show enclosures moving LCZ 8 *further* out of range. | 6.7 |
| `eps_m` as config | No — a floating-point tolerance is not a domain threshold. Module constant. | 1 |
| `neatnet` superlinearity | **Existential, now the top priority.** 144 km² did not complete in 1h35m. Invisible for seven phases because the fixture is 9 km². Phase 8. | 1, 8 |
| Whole-network `fix_topology` in `resolve_artifact_threshold` | Quadratic (exponent 2.0), ~8.6 h at metropolitan scale. Replaced by pooled per-tile distributions, **subject to an equivalence test** against the whole-network thresholds already measured at 64/144/256/484 km². | 8 |
| Global `remove_interstitial_nodes` in `_stitch` | Quadratic, 6h50m without completing. Replaced by per-seam stitching, subject to equivalence testing at 64 km². | 8 |
| `ProcessPoolExecutor` default `fork` context | Deadlocks after threaded native libs run in the parent. Use `forkserver`, and pin `OMP_NUM_THREADS=1` in workers to prevent thread oversubscription across 32 processes. | 8 |
| Building cleaning suspected as a scaling problem | **Wrong.** Near-linear: 76.2 s for 303k footprints at 400 km², ~4 min at 892k. | 1, 8 |
| Pooled-threshold bar "must not move any classification" | **My bar was wrong, superseded.** It presumed the whole-network threshold is truth; both are estimators. Adopted on the corrected bar: no bias, deviation shrinking with extent, adjacent-class flips only, 0.023% rate, 440× cost. | 8 |
| Per-seam stitching | Built, measured at the extent it was designed for, **reverted**. Global stitch is 17.4 s not 6h50m; per-seam was slower and less accurate. Premise was an unmeasured inference. | 8 |
| 6h50m stall attributed to `_stitch` | Wrong by inference-from-adjacency. Real cause was `resolve_buildings_on_streets` intersecting every footprint against one unioned road geometry, ~75 h extrapolated. Index-bounding is exact: 39.3× faster, 0.0 m² symmetric difference. | 8 |
| `forkserver` child re-executes the parent entry point | Like spawn. Hide `__main__`'s `__file__` and `__spec__` for the life of the pool. | 8 |
| Pooled threshold at 891 km² | **Adoption confirmed.** 10 of 172 181 cells (0.0058%), four-fold below the 256 km² rate. Whole-network cost measured at 10h39m against ~70 s. | 8 |
| `clean_vectors` at 4 469 s | **Outlier, not regression.** Two cold runs over the same extent gave 456 s and 551 s, bracketing the 585.6 s benchmark. Overlapped a 10-hour single-core job on a shared node — plausible cause, recorded as coincidence in time rather than measurement. | 8 |
| Feature-count gap of 1.7% | **Wrong baseline.** 195 508 predates this phase's road-rule and threshold fixes. Post-fix runs give 198 698 / 198 804 / 198 879 — a 0.04% gap. | 8 |
| Cached and cold runs differ by 75 features | **Open.** The pipeline is not run-to-run deterministic and the cache is not transparent, which holes the manifest's reproducibility claim. Fix before the paper. Stitch ordering; suspect unsorted set or dict iteration. | 8 |
| Power-law extrapolation of runtime | Ran 24% optimistic (8.6 h projected, 10h39m measured). Treat such fits as lower bounds when deciding feasibility. | 8 |

---

## Deferred — do not build unless asked

**Priority order within deferred: SVF first.** It carries weight 4 in Bernard's scheme and is
the largest single missing dimension in the current metric; adding it materially reshuffles
classification.

Vector ray-cast sky view factor · roughness length and displacement height (Macdonald / Kanda)
**and the Davenport terrain roughness class lookup, which depends on z₀** · Bernard's natural-type
branch (Figs. 2–3), with ETH canopy height as the natural roughness element — Stewart & Oke treat
trees as the roughness elements for A–D, so canopy height should recover A and B properly and
push D toward near-zero canopy · additional height tiers (UT-GLOBUS, GlobalBuildingAtlas,
EUBUCCO, morphology-based ML imputation) · ML classifier trained on So2Sat LCZ42 / DFC2017 ·
fuzzy or continuous LCZ output · W2W / WRF export · OSM as an alternative `VectorSource` ·
tessellation-based building-level units · dask-geopandas scaling · CLI · deck.gl overlay for buildings (only if MapLibre
`fill-extrusion` proves insufficient) · run-comparison views in the site · OSM `industrial=*`
subtags as supplementary heavy/light industry evidence (arrives with the deferred OSM source;
the only realistic route to the distinction Overture discards)

---

## Anti-patterns

- Don't optimise before the walking skeleton runs end to end.
- **Don't introduce a whole-extent operation without measuring its scaling exponent at three or
  more extents.** `neatify` was profiled that way and tiling worked; the threshold-pinning step
  was not, and cost 15 hours. This applies to any operation over the full network, the full
  building set, or the full unit set — including ones added to guarantee correctness.
- Don't assert that a local operation is equivalent to the global one it replaces. Measure the
  deviation at an extent where the global version is still tractable, and record it.
- **Don't attribute cost by adjacency in the call graph.** Reading the source shows the shape of
  a cost and nothing about its size. A 6h50m stall was attributed to `_stitch` because it runs
  next; the global stitch is 17 seconds and the real culprit was two functions away. Profile the
  sweep, don't reason about the neighbour.
- Don't treat the incumbent implementation as ground truth when validating a replacement. If both
  are estimators of the same heuristic quantity, a disagreement is a disagreement, not an error —
  set the acceptance bar against the noise floor of the enterprise, not against exact identity.
- Don't add a dependency to save fewer than ~50 lines.
- Don't run `uv sync`, `uv venv`, `pip install`, or create a venv. `uv add --active` only.
- Don't read `os.environ` outside the config module, or build paths from `__file__` or `cwd`.
- Don't write data, caches, or downloads anywhere inside the repo. Everything goes under
  `DATA_DIR`, with `tests/fixtures/` as the sole exception.
- Don't write outside `output/lczkit/<run_id>/`, except for a source implementation adding new
  files under its own `input/<Source>/`. Never modify or delete an existing file in `input/` —
  it is shared with other projects.
- Don't commit PDFs from `docs/references/`, or `.env`. **`docs/references/README.md`,
  `references.bib` and `tables/` ARE committed** — see Phase 0. A checkout without `tables/`
  cannot reproduce a classification.
- Don't delete anything under `input/`. To mark a cache entry as superseded, write a
  `<name>.discarded` sidecar next to it; never remove the entry itself.
- Don't inline data into `index.html`, link a CDN, or use a basemap requiring an API key. The
  site must open offline from `file://` and remain valid years from now.
- Don't recompute parameters or classification breaks at site-build time. Phase 7 reads
  `units_viz.parquet` and the manifest; it does not do analysis.
- Don't hardcode dataset class mappings, thresholds, or storey heights — they go in config.
- Don't return a bare LCZ integer anywhere in the core API; carry the distance vector.
- Don't write a parameter to the output without a documented unit and source reference.
- Don't reproduce a Tier 1 numeric range from memory. Read `docs/references/tables/`, or say
  the reference is unavailable. A plausible-looking wrong threshold is the worst failure mode
  this package has.
- Don't let `getInfo()` payloads or `reduceRegions` element counts go unbounded.
- Don't silently coerce or drop features during cleaning without recording it in the report.