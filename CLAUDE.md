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
- Do not add a web UI, plotting helpers, or notebook tooling in the MVP. **The CLI prohibition was
  lifted by explicit request in Phase 15** and the CLI built; the rest of this bullet stands.
- Do not add abstraction for plurality that does not yet exist. One implementation per
  protocol is correct for the MVP; the seam is the point, not the number of implementations.

### Process

- **Work one phase at a time. Stop at the end of each phase and report** — do not roll
  straight into the next phase.
- Each phase ends with: tests passing, `ruff` and `mypy` clean, and a short written summary
  of what was built, what was deferred, and any decision you had to make that the spec did
  not cover.
- **A phase is not concluded until its own block in this file says so.** Phase 7 shipped in
  `6ebaca2` during Phase 8, and the spec went on calling it "the only outstanding deliverable" for
  fourteen commits while three of its rulings lived only in the experiment write-up. Code that
  exists and looks done is the easiest kind to leave half-finished. Writing the block is the last
  step of the phase, not a tidy-up afterwards.
- Ask before making a decision the spec leaves ambiguous. Do not silently pick.

---

### Canonical spec

`CLAUDE.md` in the repository is the single source of truth. Rulings arrive as patches to be
applied and committed, never as a replacement file from outside the repo. An externally-maintained
copy drifted across twelve phases and silently reverted a closed Phase 9 determinism ruling back to
a diagnosis that phase had disproved.

**If a supplied edit contradicts a committed record, flag it and stop.** The committed record wins;
it was written with the measurement in front of it.

**Concluded phases keep measurements and rulings; they drop imperatives and acceptance criteria.**
Phase 8's block accumulated its own pre-conclusion text and ended up opening with a nine-minute
runtime and later asserting the package could not process a city. When a phase concludes, delete
the instructions it was working from.

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
  │   ├── GOB25D/          # Google Open Buildings 2.5D, height tier 2 (retired, Phase 11)
  │   ├── WSF3D/           # WSF-3D, height tier 3
  │   ├── So2Sat-LCZ42/    # v4 — primary validation reference, see below
  │   ├── WUDAPT/          # secondary validation reference, see below
  │   ├── NASA/GUPPD       # reference for bounds and cities
  │   └── ETH_CanopyHeight/
  └── output/
      └── lczkit/
          └── <run_id>/    # GeoParquet + manifest + cleaning report
  ```

- **So2Sat LCZ42 is available in full**, locally, at `$DATA_DIR/input/So2Sat-LCZ42/v4`. All tiles
  are in `patches_reference_rxr.gpkg`; per-city subsets are at
  `cities/<city name>/patches_reference_<city name>.gpkg`. Prefer the per-city file when working
  a single fixture. No download step is needed — this is the primary validation reference.

- **WUDAPT is available globally in full**, locally, at `$DATA_DIR/input/WUDAPT`. This is a single 
  vector file with the manual labels submitted by the community to train LCZs in different parts 
  of the world. These labels originate from different years and do not represent patches, but irregular
  polygons that may be overlapping and might not coincide. However, this is the single largest source
  of LCZ labels globally. No download is necessary, but some cleaning might be - this is the secondary 
  validation reference and the first if So2sat doesn't have sufficient labels for a ROI.

  **Built in Phase 16**: `lczkit.validation.wudapt`, `WudaptConfig` under `ValidationConfig`,
  fixtures at `tests/fixtures/lcz/wudapt_{berlin,hongkong}.parquet`. The export is
  `LCZ-Generator_training_areas_2024-10-01.gpkg`, 630 311 polygons, and `WudaptConfig.filename`
  refuses to default to it — contributors keep adding, so an unpinned name changes the reference
  between runs, exactly as `OvertureConfig.release` refuses "latest". The polygons are **CC BY-SA
  and CC BY-NC-SA 4.0**, per polygon: non-commercial in the second case, which constrains the data
  and not this MIT package, and which a run's record states from the data rather than a constant.

- **GUPPD boundaries for all urban regions in the world**, locally, at `$DATA_DIR/input/NASA/GUPPD`.
  This folder contains the release of the GUPPD dataset for all urban regions around the world.
  A post processed csv file is available for all cities, including their names, countries and 
  bounding boxes. Use this as reference when I ask for a specific city to analyze.

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
- **Primary fixture is Hong Kong** (Phase 10): 13 classes, the richest set on disk. Berlin's
  fixture carried two mid-rise classes only, which made the height axis near-untestable by
  construction and produced a wrong lever ordering that survived three phases. Berlin is retained
  as a secondary fixture. **Rotterdam is the industrial fixture for the LCZ 10 rule only and is
  not a validation city** (Phase 6.7).
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
area** in and out. Area is the load-bearing number — a 23.5% loss survived to Phase 6.5 precisely
because only counts were tracked. Include it in the output manifest.

**Measure retention against the UNION of raw footprints, not their sum.** Sources self-overlap:
Kowloon's raw Overture footprints double-count 7.52% of summed area against Berlin's 0.61%, so
`trim_overlaps` takes summed retention to 98.40% without dropping a single feature. The original
"≥99% of summed area" criterion and "trim overlaps but do not merge" are jointly unsatisfiable
wherever self-overlap exceeds 1%. The union is the ground actually covered by buildings, which is
what BSF measures. Also report **`raw_self_overlap_fraction`** per city — it is a real
source-quality signal.

*Acceptance:* fixture city produces both layers and a simplified network; `buildings_area` retains
≥99% of the **union** of input footprint area after validity fixes; cleaning report is populated
with counts, areas and self-overlap; before/after values asserted in tests.

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
   Asia, and Latin America. **Retired from the default cascade in Phase 11** — measured harmful.
   Code and tier interface retained; see Phase 10 for why per-building accuracy was the wrong
   acceptance test.
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
resolve those bands within a heterogeneous unit, so error concentrates on the **height axis —
1↔2↔3 and 4↔5↔6** (compactness fixed, height band varies). Do **not** confuse this with the
compactness axis (1↔4, 2↔5, 3↔6), which holds height fixed and varies building surface fraction;
an earlier version of this spec had the two swapped. If Phase 6 validation shows the height
pattern in a low-`height_completeness` city, it is the data behaving as expected — **but read it
as pair-normalised lift, never as a raw share** (Phase 12).

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

`FB` carrying roughly half the metric was the entry point for two separate defects — Phase 1's
footprint attrition (Phases 6.5/6.6) and the 100 m cell's spread against the published bands
(Phase 13). Both are now measured; neither is open. **SVF's priority is not raised** — see the
deferred list, where unit definition and footprint coverage lead.

**Resolved:** Bernard et al. (2024) §2.5, p. 2085 states the weights apply only to built types;
natural types go through a separate branch (Figs. 2–3). Phase 4's raster pipeline is therefore
**what supplies every dimension that separates A–G** — the opposite of decorative.

*(Corrected in Phase 14: this previously read "the only thing that classifies A–G at all", which is
not what the code does. lczkit classifies A–G by the same prototype-distance metric as the built
types, over seven dimensions, two of which — `tree_fraction` and `water_fraction` — are lczkit's own
and tagged `source="lczkit"`. Bernard's separate land-cover decision tree was not implemented. The
divergence is defensible and honestly tagged in the prototype table; it was simply never recorded.)*

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

**Report both only as pair-normalised lift against a composition-preserving null** (Phase 12).
The raw share is retired: the height axis affords six pairs to compactness's three, so a null
that never looks at the data awards height 3.9× more error.

*Acceptance:* end-to-end run produces a valid GeoParquet, `units_viz.parquet` and manifest; both
confusion axes reported separately as normalised lift; LCZ 10 precision/recall curve present for
the Rotterdam fixture.

---

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

*(Superseded in part by Phase 13: the patch-versus-cell hypothesis returns and is supported,
reached from the opposite direction once the numerator was fixed.)*

---

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

*(The axis movement reported here was read from raw shares and is superseded by Phase 12.)*

---

### Phase 6.7 — Instrument diagnostics — CONCLUDED

**The ceiling is 53.2%.** On the 432 Berlin fixture cells carrying both references, `lcz_v3.tif`
agrees with So2Sat labels 53.2% of the time. The 50–60% band lczkit was held to is a band the
comparator does not itself clear here. **Superseded by Phase 9: that was a small-sample artefact;
the real Berlin ceiling is 75.2% on 9 627 cells.**

| Berlin, same run, same cells (432) | agreement |
|---|---|
| lczkit arm A vs So2Sat labels | 40.9% |
| `lcz_v3` vs So2Sat labels — the ceiling | 53.2% |
| lczkit arm A vs `lcz_v3` | 24.3% |

lczkit beats `lcz_v3` outright on LCZ 5 (32.1% vs 18.8%) and trails on LCZ 2 (43.7% vs 63.7%).
Nothing was tuned to achieve this.

**The error diagnosis inverted** — against `lcz_v3`, Berlin's height axis carried 31.8% of
disagreement and compactness 25.8%; against real labels, compactness 55.2% and height 17.0%.
Phase 6.6 promoted height estimation on evidence taken against the wrong reference. **Both
readings were later shown by Phase 12 to have been taken through a broken instrument** — the raw
share cannot compare the axes at all.

Also resolved: `is_planar_enforced: True` (three zero-area-overlap footprint pairs cleared by a
1 µm buffer subtraction, 4.5×10⁻⁵ m² of 3.13 km², running after `absorb_small_buildings`).
`eps_m` correctly kept as a module constant — a floating-point tolerance is not a domain
threshold.

**Rotterdam is no longer a validation city.** LCZ 8 median BSF 0.126 against a published
0.30–0.50, bimodal shed/apron rather than flat low, arms A and C identical so cleaning removes
nothing — and **10.7% of reference LCZ 8 cells contain no building at all.** The reference is
coarser than the ground. With no So2Sat coverage either, its agreement figure carries no signal.
Retain Rotterdam as the industrial fixture for the LCZ 10 rule only.

---

## MVP COMPLETE — baseline recorded

**Berlin 35.3% against a 75.2% ceiling, 9 627 cells** (Phase 10, independently reproduced). This
supersedes the 40.9% / 53.2% figures the original MVP framing rested on — both came from the same
432-cell sample. The gap is 40 points, not 12.

The decision to stop optimising agreement stands, but on the correct grounds: the remaining causes
are scoped work rather than mysteries. It was **not** because the package was near its ceiling.

**Never report "% of ceiling" as a metric.** Vancouver scores 41.8% against a 36.7% ceiling — 114%.
The comparator is another estimator, not an upper bound, and lczkit beats it in places. Report raw
agreement and ceiling side by side, or their difference. Ceilings range 22.8% (Mumbai) to 83.2%
(Rio), so raw agreement is not comparable across cities without its ceiling beside it.

Do not open further diagnostic phases against the 9 km² fixture.

---

### Phase 8 — Scaling — CONCLUDED

**Berlin's full 891 km² administrative extent cleans end to end in 9.8 minutes** (585.6 s),
267 021 → 195 508 streets over 594 tiles on 256 workers, retaining 99.947% of footprint area —
against a 15h14m run that never finished. Every remaining whole-extent step is sub-linear (max
exponent 0.93, `clean_buildings`).

The two quadratic bookends that produced the 15-hour runtime, and their fates:

| step | scaling | outcome |
|---|---|---|
| `resolve_artifact_threshold` → whole-network `neatnet.fix_topology` | exponent 2.0 in feature count | replaced by pooled per-tile distributions; ~8.6 h → ~70 s |
| `resolve_buildings_on_streets` → every footprint against one unioned road geometry | ~75 h extrapolated over Berlin | index-bounded, exact, 39.3× faster, 0.0 m² symmetric difference |

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
| flip rate below enterprise noise | 6 / 26 040 = 0.023% |
| cost | **~8.6 h → ~70 s**, up to 193× at 484 km² |

**891 km² A/B — adoption CONFIRMED.** Whole-network 8.140679 (38 372 s / 10h39m) against pooled
8.131236 (~70 s): deviation 0.009443, **10 of 172 181 cells moved (0.0058%)** — a four-fold fall
from 0.0230% at 256 km². Note the exponent-2.0 fit projected ~8.6 h against a measured 10h39m:
**power-law extrapolations from small extents run optimistic**, so treat such fits as lower bounds
when deciding feasibility. Downstream pipeline arms took 456 s and 551 s.

Three of the ten moves involve LCZ 10, which the distance metric never assigns. The path is real
and unverified: `resolve_buildings_on_streets` consumes the simplified network, so a different
threshold trims different footprints and every building-area parameter — including
`industrial_fraction` — moves with it. **Check this first if those transitions ever matter.**

**Per-seam stitching: built, measured, REVERTED.** Its premise was false. At 891 km² the global
stitch is **17.4 s, not 6h50m**; per-seam was 24% slower, diverged in linework (23.5 km of 19 078,
0.12%), and left `aspect_ratio` twice as far from the whole-extent answer (mean |Δ| 0.150 vs
0.072). The 6h50m had been attributed to `_stitch` by inference — it is the next thing the code
does — and a fix built on that inference without checking.

`forkserver` note: a forkserver child re-executes the parent entry point like a spawn child does.
`__main__`'s `__file__` and `__spec__` are hidden for the life of the pool. Workers also pin
`OMP_NUM_THREADS=1` and the MKL/OpenBLAS equivalents, on both the serial and parallel branches.

**Cached and cold runs differ by 75 of ~198 800 features — CLOSED in Phase 9 at `040be15`.** Both
halves of the original diagnosis were inference from adjacency and both were wrong. The cache was
transparent (the two runs shared none: `phase8_threshold_labels.py` passes `cache_dir=None`), and
stitch ordering was innocent (`pool.map` preserves job order). The real unsorted iteration was at
the front door: `OvertureSource._fetch` runs a DuckDB scan over many remote parquet files with no
`ORDER BY`, so row order was whatever the parallel readers finished in. Every layer now arrives
sorted by GERS id. Phase 12 closed two residuals in the same claim — see its write-up.

---

### Phase 9 — Multi-city validation — CONCLUDED

**The founding premise is confirmed, and it is the binding constraint.**

| | tier-1 height | overall | built-class |
|---|---|---|---|
| Europe + N. America (7 cities) | 64.3% | 42.6% | 25.5% |
| Everywhere else (8 cities) | 9.6% | 21.7% | 5.7% |

Cairo 1%, Nairobi 1%, Islamabad 1%, Mumbai 3%, Cape Town 4%, Jakarta 7% tier-1 coverage — 92–99%
of building area with no height at all. **corr(tier-1 completeness, built-class agreement) = 0.67.**
São Paulo is the discriminating case: 48% coverage, agreement sitting with the European cities.

The mechanism, stated precisely: with `Hr` null nearly everywhere the metric runs on building
surface fraction alone and **the built types stop being separable in principle** — not inaccurate,
not separable. Cairo: 3.4% overall, 1.3% built.

**A vs B: split verdict, not adopted.** B ahead in 5/15 overall (mean −1.5 pts) but **9/15 on built
classes (mean +2.4 pts)**. Enclosures approximate an LCZ patch in built fabric and smear the natural
classes, which are large and heterogeneous (Rio: −13.8 overall, −0.9 built).

*(This phase's "height dominates 15.5% vs 2.6%" reading is retired — see Phase 12. It was a raw
share, measured at cascade `none`, through an instrument that awards height 3.9× on affordance
alone.)*

Caveats for the paper: Hong Kong failed on a GEOS predicate (`orientationIndex` encountered
NaN/Inf) — since fixed, see Phase 10. Windows retain a median 51% of each city's patches, so these
are **urban cores, not whole cities**.

---

### Phase 10 — Height cascade completion — CONCLUDED

**The cascade works: built-class agreement improves in 9 of 9 cities, mean +6.5 points**, coverage
0.8–79.7% → 91.6–99.7%. **corr(coverage gained, agreement gained) = +0.68** — Cairo gains 13.7
points from 1% coverage, Berlin 1.1 from 80%. Phase 9 inferred the founding premise from a
cross-city correlation; this measures it *within* each city with only the cascade changed.

**DEFAULT: `coarse`.** GHS-BUILT-H and WSF-3D only. Open Buildings 2.5D remains implemented and
available, **off by default**.

**P1 — confirmed at the mechanism, refuted at the outcome.** Coarse products have no within-unit
skill as predicted: GHS-BUILT-H's pooled within-unit ρ against real heights is +0.001, with 42–75%
of units receiving a literally constant height, against +0.289 for Open Buildings at 4 m. But
`full > coarse > none` **fails** — `coarse→full` is −1.9 points, positive in only 4 of 9, and
Mumbai drops below its own tier-1-only baseline.

**The finding to keep, and the paper's second methodological contribution:** Open Buildings has the
lowest per-building error and the only within-unit skill, **and still makes the map worse**. `Hr` is
a geometric mean; dispersion depresses it. GOB's within-unit spread is 0.441 against reality's
0.195, so over half is noise, and 19% of its values fall below 2 m.

> **Per-building accuracy is the wrong acceptance test for a height product feeding an LCZ map.**
> Testing MAE alone would have adopted the tier that hurts. Any new height tier must be evaluated
> on **within-unit dispersion against reality**, not just per-building error.

**P2 — refuted in the opposite direction.** Enclosures are smaller than a 100 m cell as predicted
(68.6%), but B's built-class lead **widens** with heights filled: +1.7 → +4.1.

**No `min_height_m` for Open Buildings.** A threshold no documentation supports, tuned so one
product stops hurting, will be copied into other pipelines and outlive its justification. It also
treats the wrong thing: the problem is dispersion, not a low tail — clipping at 2 m removes 19% of
values while leaving the other side of an over-wide distribution intact.

Hong Kong completes in 14.9 min with **13 classes — the richest class set on disk**, and the
antidote to the two-mid-rise-class fixture that distorted Phase 6.7. It is the primary fixture.

**Berlin at full sample: 35.3% against a 75.2% ceiling on 9 627 cells**, independently reproduced.
The honest framing is "here is what constrains this class of method," not "here is a good map."

---

### Phase 11 — Unit decision and cascade ordering — CONCLUDED

**E1 — split verdict, enclosures not adopted (third time, same reason).** Fifteen cities at
`coarse`: built +3.8 (12/15), overall −0.2 (8/15). The pre-registered rule required both.

The comparability check is the valuable part: Phase 9 and Phase 11 at `none` agree to the decimal
(−1.5 overall / +2.4 built, 5/15 and 9/15), confirming the harness is stable across phases.

**The split is regional, not by class:**

| | overall | built |
|---|---|---|
| Europe + N. America (7) | −2.1 | +2.8 |
| Everywhere else (9) | +1.3 | +4.3 |

Outside Europe and N. America enclosures lead on **both** criteria. The global −0.2 is seven cities
pulling against nine. Jakarta +10.3, Rio −11.3 — a 21-point swing driven by natural-class share,
since enclosures approximate a patch in built fabric and smear large heterogeneous natural classes.

**Ruling: expose `unit_strategy` as config, default `grid`, no auto-selection.** Do not switch on
region — region is not the mechanism, natural-class share and patch heterogeneity are, and a rule
keyed on continent is wrong at every boundary and indefensible in a paper. Record the choice in the
manifest and document the trade-off so users choose knowingly.

**E2 — refuted, and the question was ill-posed.** `full_reversed` is not between `coarse` and
`full`; it **is** `coarse`, bit-identical in six of eight cities. A cascade is winner-takes-all per
building, and WSF-3D plus GHS-BUILT-H answer for 92–99% of building area, leaving Open Buildings
0.3–6.4% to claim instead of 50–93%. **Cascade order is a selection switch, not a blending knob —
no intermediate configuration is reachable by reordering.**

**Open Buildings 2.5D is retired from the cascade.** It hurts running first and claims nothing
running last. Keep the code and the tier interface; document it as measured-harmful. Shrinkage
toward the unit mean remains the only route back, on the deferred list.

The cascade improves **all sixteen cities**, +3.7 overall / +4.8 built, including the seven
Europe/N. America cities Phase 10 never ran — Milan +6.6 built from an already-69% starting
coverage.

---

### Phase 12 — Axis reconciliation — CONCLUDED

**The medians were right. The instrument was not.** 15.5% / 2.6% reproduces exactly from the stored
Phase 9 record and every published axis figure is against So2Sat labels, so the like-for-like
hypothesis is refuted. Class composition is real but is not the important half.

**The raw axis share cannot carry a comparison in either direction** — not across cities, where the
denominator is all disagreement and the natural-class share ranges 3.5%–54.1% across the sixteen,
and, the part nobody had, **not between the two axes**. The height axis has six pairs to
compactness's three and more reachable directions, so a null that never looks at the data still
awards height most of the error:

| cascade `none` | height | compactness | ratio |
|---|---|---|---|
| what composition affords | 10.9% | 2.8% | 3.9× |
| observed | 14.1% | 2.9% | 4.9× |

Phase 9's "height dominates roughly three to one in 11 of 15 cities" is mostly the instrument. The
excess over affordance is 1.26×, and per-city normalisation puts compactness ahead of the median at
`none` too.

**A third confound, and the consequential one: Phase 9 measured at `none`, and the package has
shipped `coarse` since Phase 10.** The same sixteen cities give 6.0% / 6.4% at `coarse` against
14.1% / 2.9% at `none`. Filling heights halves the height axis — the cascade working as designed.
**Phase 10 was itself the intervention that invalidated the evidence ordering the levers.**

**The lever.** Normalised lift against a composition-preserving null, arm A, `coarse`: compactness
**1.16** against height **0.86**, leading in 11 of 16. Height sits below 1.0. **Next lever is unit
definition and footprint coverage.**

It is region-shaped: compactness lift 2.37 in Europe/N. America against 1.15 elsewhere, height flat
at 0.85/0.87. That is the **same seven-against-nine split** where Phase 11 found enclosures losing —
two independent measurements pointing the same way, not yet a mechanism. **The lever is not "adopt
enclosures": arm B raises the compactness lift to 2.33, against 1.64 for height.**

E1 partial — compactness leads at `coarse` as predicted, but the ordering does not reverse at `none`
once normalised (1.34 against 1.22, leading 9/16). The lever never flipped; the raw share was never
measuring what it was read as measuring, at either setting. E2 confirmed, spread 15.6× → 6.9×,
max/median 3.5.

Cost: a re-analysis of stored records, not a re-run. 2 592 stored axis pairs reproduced with 0
mismatches — sixteen cities in seconds against Phase 11's 8.9 hours.

**Three near-assertions caught before shipping**, all by the existing anti-patterns:
- The footprint union looked like a cheap scalar and is superlinear — 711 s at Berlin's 891 km²
  against a 9.8-minute whole run. Replaced with a component-wise union: sublinear, 8.6 s, exact to
  0.0000 m².
- The row-order fix was expected to move the pooled threshold and invalidate the tile cache. The
  threshold is bit-identical, and the cache would have served pre-fix tiles silently — **the same
  "cache that changes results" failure the Phase 8 entry was opened for, nearly reintroduced by its
  own fix.** `TILE_RESULT_VERSION` bumped.
- A test attributed tiled order-sensitivity to `neatnet`. On the fixture it was `subset`'s own;
  untiled, that network simplifies identically under a shuffle. The property is real — the
  6 159-street Berlin fixture does differ — but the test recorded the wrong cause.

**Rulings:**

1. **The raw axis share is retired.** Not "use with care" — removed from reporting. Every figure
   derived from it since Phase 9 is void. Only pair-normalised lift against a composition-preserving
   null appears in output, docs or the paper.
2. **Re-baseline the manifest at `coarse`.** Any stored diagnostic measured at `none` is superseded,
   not only the axis figures. **Tag every stored record with its cascade setting** so this cannot
   recur.

---

### Phase 13 — BSF against published ranges — CONCLUDED

**Outcome 3: the published ranges do not transfer to 100 m cells — and the failure is dispersion,
not bias.** Sixteen cities, `coarse`, arm A, 5.09 h, none skipped.

**It was not a re-analysis, because the stored instrument was grouped by the wrong reference.**
`bsf_by_reference_class` was built from `fixture.reference` — whose own docstring reads "A comparator,
never the primary reference" — while `fixture.ground_truth` went unused. On Berlin that is 91 158
cells of `lcz_v3` where 9 627 carry a hand label. The second reference mix-up, in the instrument this
phase turns on. `RangeReport` now carries `reference_file`, so it cannot recur silently.

| grouped by So2Sat labels | published | median | in range |
|---|---|---:|---:|
| 1 Compact high-rise | 0.40–0.60 | 0.431 | 34.2% |
| 2 Compact midrise | 0.40–0.70 | 0.376 | 42.3% |
| 5 Open midrise | 0.20–0.40 | 0.227 | **53.5%** |
| 8 Large low-rise | 0.30–0.50 | 0.293 | 27.6% |
| 10 Heavy industry | 0.20–0.30 | 0.138 | 15.0% |

**One class of ten reaches its range**, holding 11.9% of built cells; under `lcz_v3` none does.

**The medians are close — six of ten within 0.13 interval-widths, LCZ 1 and 5 inside.** What fails is
spread: empirical p10–p90 runs 0.19–0.69 against a published 0.40–0.60 on LCZ 1, and 0.05–0.61
against 0.30–0.50 on LCZ 8. LCZ 1, 4, 8, 9 and 10 leak out *both* sides — too varied, not too empty;
LCZ 2, 3 and 7 sit genuinely low. **This is Phase 6.5's patch-versus-cell hypothesis returning,
reached from the opposite direction** — 6.5 rejected it over a numerator losing 23.5% of its
footprints.

**P2 confirmed, and the brief's mechanism refuted.** Europe trails on 2 of 9 shared classes, not a
majority, and *leads* by +35.4 points on LCZ 2. Depressed BSF in Europe cannot explain Europe's higher
compactness lift, because Europe's BSF is the healthiest in the sample.

**P3 partial, stated the smaller way.** The groupings differ by a mean 6.7 points and up to 18.2
(LCZ 9), and disagree on the one class that reaches — **but give the same outcome.** The fix was
worth making; it did not change the answer.

**Nothing is recalibrated.** Empirical intervals are tagged `lczkit_empirical` and confined to the run
JSON; `prototypes.py` still transcribes the table. Fitting to a spread this wide would encode one
sample's heterogeneity as a definition.

Also measured: every city's `lcz_v3` table reproduces Phase 11 **bit-identically** (max |Δ| 0.0%)
though Phase 12's `TILE_RESULT_VERSION` bump regenerated every tile cold — the determinism fix
confirmed over sixteen extents. And **LCZ 7 sits at 8.2% in range** (0.417 against 0.60–0.90), low on
both tails across five non-European cities: an Overture coverage limit on informal settlements, not a
range finding.

**The diagnostic sequence is closed.**

---

### Phase 14 — Audit remediation — CONCLUDED

**Not a diagnostic phase. It opened no new question — it closed the gap between what this file
records as decided and what the code does**, and it found that gap to be four rulings wide.

**The shape of the problem: the spec moved and the code did not.** The classify layer was last
touched in `3931bbe`; the rulings superseding its behaviour were applied to this file in `f374e4e`,
seven days later, and nothing reconciled the two. So `rules.py` carried the pair-gated LCZ 10 rule
verbatim for eight phases after this file recorded it as measured inert and replaced; the
`bernard2024` → `bernard2024_partial` rename was ruled in Phase 6 and never applied; and
`industrial_fraction`'s denominator was contradicted **three ways inside the repository at once** —
this file and `ucp/parameters.py` saying building area, the code, `config.py` and the registry
saying unit area and arguing for it.

Two committed rulings were also being actively violated by live code:
`multi_city_validation.py` medianed the **retired raw axis share** across sixteen cities (Phase 12
Ruling 1: "removed from reporting", not "use with care"), and printed **"% of ceiling"** in two
places, which Phase 9 recorded as a broken metric. `unit_scale_experiment.py` was a third raw-share
reader. `axis_reconciliation.py` keeps its raw-share column and is exempt: showing the broken
quantity beside what replaces it *is* the Phase 12 measurement.

#### Measurements

**LCZ 10, calibrated at last — and the threshold is not the binding constraint, for the second time
by a different mechanism.** `scripts/lcz10_threshold_sweep.py`, 19 thresholds, both denominators,
against the Rotterdam reference (`lcz_v3`, permitted for this rule only):

| | precision range over 0.05–0.95 | recall at 0.05 → 0.95 | predicted at operating point |
|---|---|---|---|
| `industrial_fraction_of_building_area` (`FIND/B`) | 16.7% – 23.2% | 31.8% → 5.7% | **95** |
| `industrial_fraction_of_unit_area` | 24.4% – 26.5% | 92.0% → 51.1% | 196 |

**Precision is flat.** CLAUDE.md predicted landing high-precision/low-recall; high precision is not
reachable at any setting on either column — six points of movement on `FIND/B` over a nineteen-fold
change in threshold. The rule now fires, which the pair-gated one never did, but the threshold
governs *how much* of the map carries LCZ 10, not how often that label is right.

Operating point: **`FIND/B` at 0.45**, the precision maximum. It is the default on both theory and
rate: Bernard's published 0.33 sits just below it and performs comparably (22.4% / 27.3% against
23.2% / 25.0%), and it labels 95 cells against a reference of 88 where the unit-area share labels
196. When precision cannot be improved, matching the rate is what is left to get right.

> **A correction, recorded because it was nearly shipped as a finding.** The first pass measured
> `FIND/B` saturating — 83.9% of cells reading exactly 1.0 — and concluded that Bernard's quantity
> does not survive the move from an RSU to a 100 m cell: a third instance of Phase 13's
> patch-versus-cell result, and it was written into this file, the paper's argument and the README
> before it was checked. **It was an artefact of the numerator.** That numerator counted every
> building standing inside an industrial *parcel* as industrial, and parcels swallow whole cells, so
> any cell touching one read 1.0. Counting industrial *buildings* — which is what `FIND/B` means —
> gives 12.6% at 1.0, median 0.66, p10 0.11. The unit-area share is the more saturated of the two at
> 42.6%. **A scale finding and a numerator bug are indistinguishable from the distribution alone**;
> only changing the definition and re-measuring separated them. The `FIND/B` instance of
> patch-versus-cell is void; the other two stand.

**LCZ 8's separability, diagnosed from the metric's structure.** `mean_building_area_m2` is not a
metric dimension, so this file's stated reason for keeping LCZ 8 in the distance metric described a
parameter that never reaches it. LCZ 8's BSF band overlaps LCZ 3 and 6, and its `Hr` band is
*identical* to LCZ 3, 6 and 9 — so the only dimension separating it is `aspect_ratio`, which is null
exactly where large setbacks stop streets reaching buildings. **LCZ 8 fails by construction, not by
tuning**, which predicts Phase 6.7's measured 0.0% (n=224) without reference to any run.

**LCZ F is unreachable by arithmetic, not by configuration.** LCZ D's prototype box contains LCZ F's
in every dimension, so `d(F) >= d(D)` always and ties break to the lower code. The config docstring
framed the exclusion as a policy choice, which would invite someone to "re-enable" F and get
silence. The manifest now records *dominated* separately from *excluded*.

#### `OA_w`: blocked, reported rather than guessed, then closed

**It was not implementable from what was on disk.** Demuzere et al. (2021) §2.4 and (2022) §2.4 both
define it and both attribute the weight matrix to **Bechtel et al. (2017, 2020)**; neither prints the
matrix, and neither paper was in `docs/references/papers/`. Per the standing anti-pattern, no matrix
was inferred and the metric was left unbuilt with the missing source named.

**Closed once Bechtel et al. (2020) was supplied.** The 17×17 matrix is transcribed in
`docs/references/tables/lcz_class_similarity.md` and asserted against the code cell for cell, and
`OA_w` is reported beside `OA`, never instead of it.

Two things about that table are load-bearing. It holds the similarity matrix **and its complement**,
under identical headers, and `OA_w` uses the similarity one: substituting the other makes a perfect
map score 0.00 and every cross-city comparison rank backwards, without raising. So the parse selects
by section heading, `similarity._check()` refuses a matrix whose diagonal is not one, and a test
asserts the direction. And the paper's framing supplies the consistency check for free — plain `OA`
*is* `OA_w` with ones on the diagonal and zeros off it, so `OA_w` under an identity matrix must
equal `OA`.

#### What shipped

Instruments first, deliberately, so the changes could be read through the better instrument rather
than the one that hid the problem — the inverse of the Phase 9→10 ordering, where the intervention
invalidated the evidence that ordered the levers.

- **Validation**: per-class **user's accuracy and F1** (recall alone cannot see over-prediction; a
  class the map invents wholesale previously had no row at all), **`OA_bu`**, and a **spatial-block
  bootstrap** giving confidence intervals on agreement and both axis lifts. Blocks, not cells: So2Sat
  patches are 320 m on a 100 m stride, so a city's labelled cells are one correlated sheet and
  cell-wise resampling would report an interval far too narrow.
- **`Hr`, one building one vote.** Phase 1 explodes multipolygons before either layer forks, so a
  courtyard block reached the geometric mean as N equal terms — a multi-part footprint outvoting its
  neighbours N to one for a reason about data encoding, not about the city. `FEATURE_ID` is now
  stamped before the explode and the parts collapse on it. Also fixes `building_count` and
  `mean_building_area_m2`.
- **`h_geometric_area_weighted`** as a secondary column. `Hr` stays unweighted — Bernard's Table 1
  specifies that form and the Stewart & Oke ranges were defined for it — but the unweighted mean
  gives a 5 m² shed the same vote as a tower block, and Phase 10 established that `Hr`'s sensitivity
  to dispersion is what made the most accurate height product degrade the map. This makes the size
  of that effect measurable without moving a published number.
- Smaller: `eps_final_m` misreported at the escalation ceiling; `industrial_fraction_land_use` able
  to exceed 1.0 because `land_use` gets no overlap resolution; an empty land-cover group answering
  0.0 for units the raster never reached; `aggregate()` reporting no coverage; `FootprintCoverage`'s
  ratios — including Phase 1's acceptance criterion — absent from every serialised artefact because
  they were plain `@property`; `n_params_used` silently mixing a built maximum of 3 with a natural
  maximum of 7.

#### Rulings

1. **A ruling is not applied until the code says so.** This is the same failure as Phase 7 shipping
   unrecorded, in the opposite direction: there, code existed and the spec did not know; here, the
   spec ruled and the code did not follow. Both were invisible for the same reason — nothing checked
   the two against each other. The regression tests added here (no script reads the retired share, no
   script prints "% of ceiling", the shipped threshold is the one the sweep selects) are that check,
   for the specific rulings that had already drifted.
2. **A quantity's denominator belongs in its name.** `industrial_fraction` was unreadable under a
   three-way disagreement about what it divided by, and no amount of documentation fixes a column
   whose meaning is contested. Both are emitted, each named for its denominator.

*(The re-baseline this phase's label-moving changes require is recorded below, separately, because it
is a measurement and not a remediation.)*

---

### Phase 15 — Command line — CONCLUDED (part 1 of 2)

**Not a diagnostic phase, and a deliberate departure from committed scope.** The MVP rule said "do
not add a CLI" and the deferred list carried one; both were lifted by explicit user request. Recorded
here as a patch rather than done silently, per the Canonical spec rule. The UI half of the same
request — base layers and legibility — is part 2 and is **not** covered by this block.

**The CLI is thin. What it cost was that the pipeline did not exist as a callable thing.** Before
this phase the only end-to-end chain in the repository was `run_and_publish` in
`scripts/berlin_metropolitan_run.py`: no `__init__.py`, reached by `sys.path` insertion, outside
`mypy src` in CI, and importing its configuration constants and its land-cover fetcher from two
*other* scripts. Three partial re-implementations sat beside it. A single-city run meant editing a
module constant — the bbox was hardcoded and the only "pick a place" interface was a 16-entry tuple.

What moved into the package, all verbatim so no measured behaviour changes:

| now | was | why it had to move |
|---|---|---|
| `pipeline.run_pipeline` | `berlin_metropolitan_run.run_and_publish` | the chain itself |
| `sources/worldcover.py` | `berlin_wide_validation.py` | a run's land cover cannot come from `scripts/` |
| `raster_window.clip_raster`, `coverage_shortfall` | same | they are what `clip_worldcover` is built on |
| `presets.py` | `berlin_metropolitan.py` + `unit_scale_experiment.py` | `Settings.load()` cannot produce a runnable config by design |
| `cities.py` | `multi_city_validation.py` | `--city` resolves the same 30 km window every sweep used |

`run_and_publish` and `configure` keep their names and signatures and now delegate, so
`publish_sites.py` is untouched and the phase write-ups that cite these scripts by path still hold.
`berlin_wide_validation.py` re-exports the moved helpers under their original names because
`tests/test_multi_city_validation.py` loads it by path and calls them through it.

**Two config defects the CLI exposed rather than introduced:**

- `Settings.load()` created `run_dir` as a side effect, so any command whose purpose is *not* to act
  would still leave a directory behind. Now `create_run_dir=True` by default, `False` for `--dry-run`.
- `land_cover.gee_project` was assigned `os.environ.get("GEE_PROJECT_NAME")` **unconditionally**, so
  an absent variable overwrote a configured value with `None`. A silent discard, not a precedence
  rule. Now assigned only when the variable is present.

**A `.env` subtlety worth knowing and not fixed here.** `Settings.load` calls `load_dotenv` with
dotenv's upward search, so running anything from inside a checkout picks up the repository's `.env`
regardless of the working directory. `override=False` means an already-set `DATA_DIR` still wins,
which is why the test fixture sets the variable rather than writing a file — but a test for the
*unset* path has to neutralise `load_dotenv` outright. Pre-existing behaviour; noted because it is
invisible until something tries to test the failure branch.

**Ruling: one preset, and it is guarded against the constants it came from.** `PRESETS["published"]`
holds what the three published sites were built with — Phase 8's *metropolitan* cleaning values
(`building_max_area_m2=100_000`, `merge_limit=50`, plus the street tiling), **not** the 9 km²
fixture values of the same name in `unit_scale_experiment.py`. Two `CleaningConfig` constants called
`CLEANING` exist with different numbers, and taking the wrong one would make `lczkit run` silently
irreproducible against every published figure. `tests/test_cli.py` asserts the preset still equals
`berlin_metropolitan.CLEANING`/`RELEASE` and that `AREAL_CONFIDENCE` still equals the experiments'.

Dependencies added: **typer 0.27.1 (MIT)** and **rich 15.0.0 (MIT)**, pulling `annotated-doc` (MIT),
`shellingham` (ISC), `markdown-it-py` (MIT), `mdurl` (MIT) and `pygments` (BSD-2-Clause). All
permissive, none GPL/LGPL. Note typer 0.27 no longer depends on `click`; `click` remains present via
`rasterio`/`cligj` independently. This crosses the "don't add a dependency to save fewer than ~50
lines" bar knowingly, on the user's choice of stack.

---

### Phase 15 — Map site legibility and base layers — CONCLUDED (part 2 of 2)

**The offline guarantee survives as the default, and the exception is bounded by a test rather than
by a promise.** The request was for OSM-style base layers, which contradicts the committed
anti-pattern that a site must open with no network — an anti-pattern that is also an *enforced test*,
not just prose. Ruling: `VizConfig.online_basemap` defaults to `None`; with it unset the emitted site
names no remote host anywhere, which is the guarantee unchanged. Set it and the site gains a
selectable raster ground, hidden until chosen, degrading to a notice rather than a blank map.

The test **split rather than relaxed**, and that is the part worth keeping:

| test | asserts |
|---|---|
| `..._comes_from_outside_the_directory` | default build: no remote reference in `index.html`, CSS, `app.js`, `style.json`, `serve.py` |
| `an_online_basemap_reaches_its_provider_and_nothing_else` | with `osm`: remote hosts appear in **`style.json` only** |
| `the_raster_basemap_is_hidden_until_a_reader_asks_for_it` | `visibility: none`, and directly above the background |

Providers: OpenStreetMap, Carto Positron, Carto Dark Matter. Each records its licence and its usage
terms, and the CLI prints them when one is selected — the OSMF tile policy in particular is a
donated resource, not a CDN, and a caller opting in takes that on.

**Two defects found by measuring rather than reasoning, both in the seam between two components:**

- **`run_layers` included the remote raster.** The offline layer set was collected by matching the
  `basemap-` prefix, which `basemap-raster` also carries — so selecting "the run's own linework"
  would have fetched the network, which is the single thing that choice exists to avoid. Collected
  explicitly now. *A name prefix is not a category.*
- **`app.js` invented the `label_route` vocabulary.** It mapped `distance`, `lcz10_rule` and
  `lcz1_constraint`; the classifier emits `distance_built`, `distance_natural`, `industrial_rule`.
  Every cell would have fallen through to printing its raw token. A consumer guessing at a
  producer's enum fails exactly this quietly — the same shape as the tippecanoe type defect, one
  layer up.

**`app.js` had no test of any kind, and a syntax error there is silent.** The IIFE never runs, so the
`catch` that prints "could not load the site" never installs either: a blank panel beside a blank
map. `tests/test_viz_app_js.py` adds a delimiter-balance check (verified to discriminate), an
assertion that every `el(id)` the script reaches for exists in the markup and vice versa, and one
that the metadata keys it dereferences are the keys `style.py` emits. Deliberately weak — a balance
check, not a parser — but it catches what an edit actually breaks. It is what found the route bug.

**Legibility.** `ParameterSpec` gained a `label`, so the human name lives beside the definition
rather than being reconstructed as `column.replace("_", " ")` in JavaScript — which is what produced
"height of roughness elements m" and "industrial fraction of building area" on all three published
maps. Non-parameter columns take theirs from `DISPLAY_LABELS`, and the height tier fractions from
`HEIGHT_SOURCE_LABELS`, so `height_frac_wsf3d` reads "WSF-3D, 90 m raster" — the thing the package
exists to report. Selector grouped by `selector_group`, which follows `selector_rank` rather than
introducing a second ordering, so the committed order tests still pass unchanged.

Also: a **"no value" legend row** on every continuous layer, because `NODATA_COLOUR` is otherwise
indistinguishable from a low band and `aspect_ratio` is null across most of an industrial estate; a
**hover readout**, since matching a shade to a band is what a sequential ramp is worst at; a
**low-confidence badge** when `n_params_used` ≤ 2, since a cell classified on two dimensions and one
classified on seven paint identically; a **layer-opacity slider**, which the raster ground requires;
and an **"About this map"** block reading the cascade, weights and release out of the manifest.

---

### Phase 16 — WUDAPT as a reference — CONCLUDED

**Built on explicit request, and turned on the other two references before the package.** CLAUDE.md
has named WUDAPT the secondary reference since Phase 0; until now `grep -rni wudapt` returned prose
only — no loader, no config, zero `.py` hits. `src/lczkit/validation/wudapt.py` exports the same
three-column contract as `reference_lcz` and `labelled_lcz`, so `agreement()` takes any of the three.
Full write-up in `docs/experiments/phase-16-wudapt-reference.md`.

**The question nobody had asked: do the labels reproduce?** Every ceiling this project has quoted
compares a *model* to labels. Two independent human label sets, same ground, sixteen cities, 100 m
grid, ~4 minutes with no pipeline run:

| | median | range |
|---|---:|---:|
| WUDAPT vs So2Sat | **79.9%** | 26.3% – 96.3% |

> **A second unquantified floor, and it is larger than the patch-versus-cell one.** Where two expert
> label sets disagree, no classifier can agree with both. This is a term in the error budget, not a
> caveat.

**The seven-against-nine split, third independent sighting — and the first outside lczkit.**
Europe + N. America 89.1% mean / 91.6% median against 69.3% / 77.7% elsewhere, measured with no
pipeline involved. It does not explain Phase 11's A/B split or Phase 12's compactness lift, and it
is not offered as doing so; it does mean an explanation concerning only lczkit's morphology now has
to account for the labels splitting the same way. **`corr(label reproducibility, ceiling) = +0.69`**
— a common cause (how ambiguous the city is to label) fits better than `lcz_v3` being differently
accurate in different places.

**Cairo: 26.3% against a 52.1% baseline — two expert label sets agreeing less than a constant
predictor.** Two explanations refuted by measurement, one supported:

- *Age* — refuted. 1 014 of 1 030 polygons postdate 2018.
- *Contributor quality* — refuted, informatively. The QC gate moves Cairo 26.3% → 26.7%, Mumbai
  47.4% → 50.3%, Jakarta 70.7% → **68.8%**, for half the labelled ground; `oa ≥ 0.7` gives
  **19.1%** / 47.3% / 69.6% — worse on all three, worst on the city that needed help most.
- *Systematic interpretation difference* — supported. So2Sat lays a blanket LCZ 2 over ground WUDAPT
  splits six ways, and **302 of 400** So2Sat LCZ 8 cells are WUDAPT's LCZ 10 — the 8/10 boundary
  Stewart & Oke separate only by anthropogenic heat, which neither team can measure. Berlin's
  equivalent matrix is near-diagonal.

Cairo's 3.4% / 1.3% remains on the record; the founding premise is untouched, since Phase 10
measured the height correlation *within* cities. But Cairo's specific number was taken against a
reference another expert team disagrees with more than chance.

**Reach: 275 024 labelled cells against So2Sat's 100 414 — 2.7×, and more in 15 of 16 cities.**
Largest where So2Sat is thinnest: Mumbai 1 706 → 13 086, Hong Kong 4 131 → 33 227. Vancouver is the
sole exception (0.67×).

**The instrument reproduces the committed record**: Berlin's ceiling 75.2% on 9 620 cells against
the committed 75.2% on 9 627; Cairo 42.5%, Vancouver 36.7%, Mumbai 22.8%, Rio 83.2% all reproduce.

Other measurements worth keeping:

- **`raw = labelled + duplicate + conflict` exactly** — 13 595 047.0 m² both ways on the Berlin
  fixture. Cities contest 0.09% (Vancouver) to 19.48% (São Paulo) of drawn ground.
- **`corr(contested share, label agreement) = −0.14` — hypothesis refuted.** A reference that
  contradicts itself is not thereby one that disagrees with an independent set. São Paulo contests
  19.48% and reaches 82.1%; Vancouver contests 0.09% and reaches 77.3%.
- **`lcz_v3` vs WUDAPT is not a ceiling and carries `independent: False` in the record.** These
  polygons are that map's training data. Vancouver reads 86.8% against a real ceiling of 36.7%.

**Rulings:**

1. **A reference's own quality metrics are not a validation filter.** WUDAPT's QC flags and `oa`
   both fail to improve agreement with independent labels and `oa` makes it worse — it scores a
   submission against *itself*, and self-consistency is precisely what a second reference is for.
   `require_qc=False` and `min_oa=None`, with the measurement in the config docstrings.
2. **So2Sat stays primary where it exists.** WUDAPT adds reach and support, not authority:
   contributor-drawn exemplars against a designed sample. Where both exist both are reported, and
   `reference_file` names which produced which figure.

---

### Phase 17 — organic patch units — CONCLUDED

**Built on explicit request.** `GridUnits` is untouched and remains the default. Full write-up in
`docs/experiments/phase-17-patch-units.md`.

**The measurement that set the design: an enclosure is a block, an LCZ patch is a neighbourhood.**

| | median unit |
|---|---:|
| `EnclosureUnits`, Hong Kong fixture | **0.04 ha** |
| 100 m grid cell | 1.00 ha |
| WUDAPT polygon, sixteen cities | 2.2–52 ha (median ~5) |
| So2Sat patch | 10.24 ha |

And **a thinner barrier set does not fix it** — measured at four settings, every one bimodal
(slivers plus a few very large faces), median barely moving: all streets 0.04 ha, drop
footway/path 0.11, major+tertiary 0.07, major only 0.07. A thinner network does not enlarge small
faces, it only stops subdividing big ones. **The scale is set by a merge step or not at all.**

`src/lczkit/units/patches.py`: `EnclosureUnits` seeds over a barrier set with the pedestrian classes
removed, then a contiguity-constrained greedy merge into the most morphologically similar neighbour
until `min_area_m2`. Hong Kong fixture: grid 959 units / 1.00 ha median, enclosure 618 / 0.15,
**patch 62 / 11.69** — inside the WUDAPT band, 556 merges, 0 isolates, 0 left below the floor.

- **Pedestrian classes are 72.7% of Berlin's segments, 72.8% of Hong Kong's, 50.6% of Milan's** and
  3.5–7.5% elsewhere. Left in the barrier set, the partition is largely a measure of how thoroughly
  a city's footpaths have been surveyed. `pedestrian` itself is kept — Overture uses it for plazas.
- **`min_area_m2`, not `target_area_m2`.** A floor: merging stops when a unit *reaches* it and the
  merge overshoots, so 5 ha gives a 10.5 ha median. Named for what it does after the first run
  showed what it does.
- **Scaling measured at five extents before shipping**, per the standing anti-pattern: 3 600 →
  78 400 seeds, 0.85 s → 21.3 s, **exponent 1.03** (pairwise 1.02/1.05/0.91/1.23). Linear.
  Berlin's 891 km² extrapolates to ~100 s — a lower bound, since Phase 8 measured such fits running
  24% optimistic.
- `libpysal` is now a **declared** dependency; it was present only transitively via momepy/esda.

**The Phase 11 ruling, applied six phases late.** "Expose `unit_strategy` as config, default `grid`,
no auto-selection" was ruled and never applied: `pipeline.run_pipeline` held a literal `GridUnits()`
and **never assembled barriers at all**, so enclosures were unreachable from the chain. A fifth
instance of the Phase 14 pattern, found by needing the seam rather than by auditing for it.
`UnitsConfig` now carries it; `PatchReport` records the outcome separately from the config that
asked for it.

**Caveat that travels with any figure on patch units.** The merge reads BSF and height, two of the
seven dimensions the classifier scores — the standard shape of a regionalisation, and still a mild
circularity. It cannot inflate agreement with an external reference, but it does make
`bsf_by_reference_class` a weaker test on patches than on cells. **Phase 13's conclusions stay on
the grid.**

**No accuracy claim is attached, and none is made.** The sixteen-city A/B sweep is wired
(`agreement_wudapt`, arm D) and not run — it is a sweep, not a build. Pre-registered reading,
recorded now so it cannot be chosen afterwards: Phase 12 named unit definition the lever at
compactness lift 1.16 against height 0.86, so if patch units are the answer the **compactness lift
falls toward 1.0**. Plain enclosures *raised* it to 2.33, so "bigger units" is not automatically the
fix — which is what the sweep would test.

---

### Phase 18 — Overture semantic evidence — CONCLUDED

**Built on explicit request.** The package computed twenty parameters and exactly one read a
semantic attribute — `industrial_fraction`, a literal `isin(["industrial"])`. Overture ingests
`subtype`/`class` on every building and parcel and cleaning is test-pinned to retain them, so the
vocabulary had been there and unread since Phase 1. Full write-up in
`docs/experiments/phase-18-semantic-evidence.md`.

**Overture-native, not OSM.** `osm-rasterizer` and `osmnx` are neither installed nor declared and
both need live Overpass — unpinned and unreproducible against a design that fixes a release string
in every manifest. `docs/references/tables/overture_lcz_semantic_mapping.md` ports the knowledge in
`osm_lcz_tag_mapping.md` into a committed crosswalk, parsed and asserted cell for cell.

**The measurement, and it is the founding premise on a second attribute:**

| tagged building **area** | mean | median |
|---|---:|---:|
| Europe + N. America (7) | **48.6%** | 50.3% |
| Everywhere else (9) | **13.6%** | 7.1% |

Rio 3.1%, Islamabad 4.5%, Nairobi 5.2%, Cairo 5.7% against Berlin 64.4%. Phase 9 measured tier-1
height at 64.3% / 9.6% on the same split — **a fourth sighting of the seven-against-nine regional
line**, after Phase 11's A/B, Phase 12's compactness lift and Phase 16's label reproducibility.

**The mechanism, which the diagnostic makes visible rather than inferred: wherever an ML source
wins the footprints its tagged share is _exactly_ 0.0%.** Google Open Buildings and Microsoft ML
supply geometry and no attributes, and Overture's conflation is winner-takes-all per footprint, so
a city those sources won has nothing to read however well mapped it is in OSM.

**Land-use parcels do not collapse** — 30–65% where building tags are near-absent against 79–107%
in Europe — so they are the evidence that generalises, and the two are reported as separate columns
rather than fused. **Area coverage runs well above count coverage everywhere** (Berlin 64.4% vs
46.6%, Mumbai 18.1% vs 5.4%): tagged buildings are systematically the larger ones, and the area
share is reported because it is the denominator every semantic fraction divides by.

`src/lczkit/ucp/semantics.py` emits, per group, `sem_<group>_buildings_of_building_area` and
`sem_<group>_parcels_of_unit_area` — each name carrying a numerator *and* a denominator — plus
**`building_tag_coverage`** and **`land_use_coverage`**, which are the point: without them a
`lightweight` fraction of 0.0 in Nairobi cannot be told from 94.8% of building area carrying no tag.
Five groups; scope held to the built types, with a test asserting no group reaches `park`, `forest`,
`grass` or `farmland` — rasters own land cover, and that decision stays locked.

**`industrial_fraction_of_building_area` is not repointed.** It carries the swept 0.45 threshold, so
widening what it selects would silently invalidate the calibration. `heavy_industry` is reported
beside it and a test pins that the two never diverge on Rotterdam (superset by construction, ρ>0.99).

**Two rules ship, both disabled** — LCZ 8 from `large_lowrise` gated on `mean_building_area_m2`
(which a *rule* may read although the metric cannot), and LCZ 7 from `lightweight`. Disabled is a
ruling, not caution: a threshold is swept and chosen at an operating point, never picked, and these
have not been swept. `label_route` gains `semantic_rule`, kept distinct from `industrial_rule` so
that rule's cited firing count does not change meaning.

**Two defects found by measuring rather than reasoning:**

- **A whole-extent `union_all` over the land-use layer**, in the first draft of both the coverage
  column and the diagnostic. The standing anti-pattern, already paid for twice — and it also *does
  not work*: over real Overture land use it raises `GEOSException: side location conflict` **even
  after `make_valid`**, because per-feature validity does not make a collection unionable.
  `industrial.py` survives it by unioning a few dozen parcels; this ran on Berlin's 70 509. Replaced
  by clip-then-dissolve-per-unit: bounded, well-conditioned, exactly equal. Caught by running the
  diagnostic over a real city rather than a fixture.
- **Selection by index over a layer with no uniqueness guarantee** — `.loc[an_index]` returns extra
  rows on a duplicated index, which reported `building_tag_coverage = 1.0` for an untagged unit. All
  selection is positional now. Caught by the one test written to prove tagged and untagged are
  distinguishable: the property the module exists for was the property that failed.

**No sweep, so no rule fires and no accuracy claim is made.** For LCZ 7 the sweep needs a city where
the class exists *and* is tagged, which the coverage table suggests may not exist — itself the
finding, since the rule's value then lies in making that measurable rather than in firing.

---

### STOP RULE — applies after Phase 13

**No further diagnostic phases.** Thirteen phases in, the finding rate remains high but the returns
are now scientific rather than engineering: each phase yields a better-understood limit rather than
a better map. That is the paper's material, not the package's.

Remaining work, in order:

1. ~~**Phase 7 — the static map site.**~~ **Concluded** — three cities published.
2. ~~**Phase 14 — audit remediation.**~~ **Concluded** — four unapplied rulings closed, two live
   ruling violations fixed. Not a diagnostic phase; it opened no new question.
3. ~~**Phase 15 — command line and UI.**~~ **Concluded**, both parts, on explicit request and
   outside the diagnostic sequence. It opened no scientific question; it found four engineering
   defects, two of them in seams no test spanned.
4. ~~**Phase 16 — WUDAPT as a reference.**~~ **Concluded**, on explicit request. An instrument
   phase, not a lever phase — it changed no label. It produced a finding the paper needs: the
   ground truth's own reproducibility, median 79.9% and as low as 26.3%.
5. ~~**Phase 17 — organic patch units.**~~ **Concluded**, on explicit request. `PatchUnits` ships;
   no accuracy claim is attached, because the A/B sweep is a sweep and was not run.
6. ~~**Phase 18 — Overture semantic evidence.**~~ **Concluded**, on explicit request. The evidence
   layer and its coverage columns ship; both functional rules ship **disabled** pending a threshold
   sweep, per the standing calibrate-don't-pick ruling.
7. **The paper.**
8. **Cleanup** — docs, release.

**`OA_w` was blocked and is now closed.** Bechtel, Demuzere & Stewart (2020) supplied both the
class-similarity matrix and the definition; the matrix is transcribed in
`docs/references/tables/lcz_class_similarity.md` and asserted against the code cell for cell. `OA`,
`OA_u`, `OA_bu`, per-class F1 and `OA_w` are all present, so lczkit's per-class figures are now
directly comparable to published LCZ maps.

**The argument is already complete and does not depend on the next lever landing:**

1. Height data availability is the binding constraint on morphology-based LCZ classification outside
   Europe — measured *within* cities, r = +0.68.
2. Per-building accuracy is the wrong acceptance test for a height product feeding an LCZ map — the
   most accurate product degrades the result, because `Hr` is a geometric mean and punishes
   dispersion.
3. Validating against another map is not validation — ceilings range 22.8% to 83.2%, one city
   exceeds its own, and a 432-cell sample understated Berlin's by 22 points.
4. Confusion-axis shares are not comparable without pair normalisation — a null awards height 3.9×
   on affordance alone.
5. **The LCZ patch and the 100 m cell are different objects, and the comparison spans both ends.**
   - *Stewart & Oke's parameter ranges* describe a patch and do not transfer to a cell (Phase 13).
     Not because the central tendency is wrong, which it largely is not — six of ten medians fall
     within 0.13 interval-widths — but because the within-class spread on a grid is wider than the
     published bands can hold.
   - *The So2Sat labels are patch-scale too* (Phase 14). A 320 × 320 m label — 10.24 ha — is
     attributed to one 1 ha cell whose centre sits ~22 m off the patch centre. A cell inside a
     compact-midrise patch can legitimately be a courtyard.

   The second had not been stated anywhere, and it is the consequential one: **both the parameter
   ranges and the ground truth are patch-scale objects, and lczkit is the only cell-scale thing in
   the comparison.** That is an unquantified floor under the 35.3%-against-75.2% gap, and it
   reframes part of the residual as a units-of-measurement mismatch rather than classifier error.

   A third instance was claimed in Phase 14 and **retracted** — Bernard's `FIND/B` appeared to
   saturate at a 100 m cell, and the saturation was an artefact of how that phase built the
   numerator rather than a property of the quantity. Two instances, not three. The retraction is
   worth as much as the claim: a scale finding and a numerator bug produce the same distribution.
6. **The ground truth does not reproduce, and the gap is region-shaped** (Phase 16). Two independent
   expert label sets over sixteen cities agree at a median 79.9%, ranging 26.3% (Cairo, *below* its
   own 52.1% majority-class baseline) to 96.3% (Paris) — 89.1% mean across Europe and N. America
   against 69.3% elsewhere. Every ceiling in this literature, this project's included, compares a
   *model* to labels; nobody had measured whether the labels themselves agree.

   This is the **second unquantified floor** under the 35.3%-against-75.2% gap and it is larger than
   the patch-versus-cell one. It also bears directly on claim 1: the cities where the founding
   premise bites hardest are the cities whose ground truth is least reproducible, and
   `corr(label reproducibility, ceiling) = +0.69` says the two references and the global map are all
   struggling with the same thing. The premise itself is unaffected — Phase 10 measured the height
   correlation *within* cities with only the cascade changed — but a paper that reports Cairo at
   3.4% without reporting that Cairo's two reference sets agree at 26.3% is reporting half of it.

Plus, as an unexplained regularity worth reporting rather than resolving: **the compactness lift and
the enclosure A/B advantage split along the same seven-against-nine regional line, twice measured,
mechanism unknown.**

None required lczkit to score well. They required provenance tracking and sixteen cities, which
nothing else in this space has done.

#### One bounded exception, for the paper only — not a new diagnostic phase

**LCZ 7 (lightweight low-rise / informal settlements) at 8.2% in range** — 0.417 against a published
0.60–0.90, low on both tails across five non-European cities — is an Overture coverage limit on the
class that matters most in exactly the cities the founding premise concerns. A paper arguing that
open-data availability constrains LCZ mapping in the Global South cannot omit the informal-settlement
result: it is where a reader will look first.

Measure it from existing records — LCZ 7 coverage, BSF and agreement by region — and report it. One
class, no lever hunt, no new phase.

**Per-cell heterogeneity measure: future work, do not build.** It would say more than any
recalibration and belongs in the discussion as a proposal. It is a new parameter carrying its own
validation burden, and the argument does not need it.

---

### Phase 7 — Static map site — CONCLUDED

`lczkit.viz.build_site(run_dir)` writes `output/lczkit/<run_id>/site/` — MapLibre GL over the
PMTiles protocol, a vendored front end, `tippecanoe` as the pinned `lczkit[viz]` extra invoked as a
subprocess, GeoParquet → FlatGeobuf → tippecanoe → PMTiles. Selector order: LCZ, **height
provenance**, the UCP choropleths, `uniqueness`, and buildings as `fill-extrusion`. Per-unit sidebar,
permalink in the URL hash.

**Three spec details did not survive contact and were ruled on:**

- **`file://` is not satisfiable.** PMTiles reads byte ranges through `fetch`, and the Fetch standard
  leaves `file:` URLs unhandled, so Chrome and Firefox both return a network error. Amended to *"opens
  with no network and no software the user must install"*: `site/serve.py` is standard library only
  and implements `Range` itself, because `SimpleHTTPRequestHandler` has none and would re-send a
  whole tileset per tile.
- **The basemap is the run's own Overture layers, not a Protomaps extract.** An extract needs a Go
  CLI or a ~120 GB download. The run's water and streets are already cached for the bbox, are ODbL-
  attributable, and show the reader the linework the classification was computed from.
- **tippecanoe fails at 256 cores** — `Internal error: 745 shards not a power of 2`, from its radix
  sort. Capped at `min(cpus, 32)`; tiles built at 8 and 128 threads are byte-identical but for the
  filename in the metadata. Third defect in this project invisible on a laptop and fatal on the
  machine the package runs on.

**Attributes, not geometry, are what a unit tileset costs.** MVT repeats a feature's whole attribute
table in every tile at every zoom, so at 172 181 units a 38-column table costs more to tile than
892 000 building footprints — 115 MB against 61 MB. Hence the render/detail split: render attributes
at every zoom, the rest once at maximum zoom where only a click reads them. Buildings are 58% of a
full site on their own, which is why they stay off by default.

**The phase shipped in `6ebaca2` during Phase 8 and was not recorded**, so this spec called it "the
only outstanding deliverable" for fourteen commits and the three rulings above lived only in
`docs/experiments/phase-7-map-site.md`. Completing it fixed two gaps and published three cities.

**Selector order was inherited, not chosen.** `build_views` emitted views in the manifest's `breaks`
order — every numeric column in DataFrame order — putting `height_completeness` twelfth of thirteen
and giving the tier fractions no entry at all. Now ranked deliberately; ties keep the manifest's
order. `height_tier_fractions` reaches the render set through `VizConfig.render_column_prefixes`,
because its columns are named after whichever cascade fired and a static list cannot name them
without naming a cascade. Carrying them at every zoom costs **+2.12 MB, +7.5%, ~0.71 MB per column**
at 172 181 units — measured, and the price of a layer that must paint from tiles already in memory.

**Three cities published**, ~91 000 grid cells each over their So2Sat windows, buildings off:

| city | built cells | tier-1 | WSF-3D | GHS-BUILT-H | unresolved | tiles |
|---|---:|---:|---:|---:|---:|---:|
| Berlin | 59 152 | **0.797** | 0.191 | 0.008 | 0.003 | 36.12 MB |
| Hong Kong | 25 233 | 0.308 | 0.547 | 0.120 | 0.026 | 20.43 MB |
| Cairo | 56 456 | **0.010** | 0.835 | 0.122 | 0.032 | 27.20 MB |

Berlin's 0.797 reproduces Phase 10's ~80% and Cairo's 0.010 its 1%. **83.5% of Cairo's building area
takes its height from a 90 m TanDEM-X raster**, and that is now a selectable layer rather than a
number in a table.

**The default view never rendered until someone opened it.** tippecanoe's FlatGeobuf reader emits
integer attributes as strings at every width, while floats pass through as numbers, so the LCZ
`match` expression found no label and painted every cell `NODATA_COLOUR` — a field of blank grey
squares in every published site, from `6ebaca2` onwards. `lcz_primary` is the only integer column the
site renders, which is exactly why the choropleths looked fine and nothing seemed wrong. Fixed with
`to-number` in the expression, keeping a class code an integer everywhere else it is read.

**Thirty-seven tests could not see it**, because the style test asserted the expression carried the
committed colours and the site test asserted the tileset was a valid archive: each half checked
against its own assumption, and the defect lived in the gap. The test that closes it decodes the
built tiles and evaluates the real paint expression against the real values, and fails 6 of 6
without the fix.

**Publishing a second city found a real defect.** The driver clipped ESA WorldCover from one
hardcoded tile (`N51E012`, Berlin's). Hong Kong and Cairo each span two, so both raised
`RasterioIOError: Attempt to create 0x0 dataset`. `clip_worldcover` already resolved and mosaicked
correctly; the driver was not calling it. Its docstring had predicted the failure mode — *"a
single-tile guess would fail as a band of nodata down one side of the map rather than as an error"* —
and only Berlin's tile missing both cities entirely made it loud. **A city one tile-width away would
have published a map with a quarter of its land cover silently missing.** Berlin's site is unaffected;
its window resolves to the same tile.

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
| Demuzere et al. (2022), *ESSD* 14, 3835–3873 | `10.5194/essd-14-3835-2022` | Phase 6 — integer coding convention, colour table, validation target. **Cite v3** — the map in use is `lcz_v3.tif`. |
| Bechtel, Demuzere & Stewart (2020), *Remote Sens.* 12(11), 1769 | `10.3390/rs12111769` | Phase 6 — the weighted accuracy `OA_w` and its class-similarity matrix, the metric that makes per-class figures comparable to published LCZ maps. Open access. |
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
| WSF-3D (DLR, TanDEM-X derived) product documentation | Phase 3 — height tier 3 |
| Overture Maps schema reference (buildings, transportation, base) | Phase 1 — pin the schema version |
| So2Sat LCZ42 v4 documentation | Phase 6+ — primary validation reference |

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
| Confusion pairs 1↔4, 2↔5, 3↔6 labelled "height axis" | **Spec bug, corrected.** Those hold height fixed and vary compactness. The height axis is 1↔2↔3 and 4↔5↔6. Both are now reported, separately and correctly named. **Phase 3's copy of the same error was corrected later, in the Phase 13 consistency sweep.** | 3, 6 |
| Bernard weights — do they apply to natural types? | **Resolved from the paper**, §2.5 p. 2085: built types only; natural types are a separate branch. Phase 4's rasters are the sole classifier for A–G. | 6 |
| `bernard2024` preset only partially applicable | Renamed `bernard2024_partial`. 17 of 21.5 weight units applied; SVF and z₀ deferred; `FB` carries ~47% of the metric. Unapplied dimensions recorded in the manifest. **The rename was ruled in Phase 6 and only applied in Phase 14** — the code shipped `bernard2024` for eight phases, and `output/manifest.py` keyed `unapplied_weights` off that literal, so renaming it anywhere but both places at once would have emitted `[]` in silence. The key now reads the preset constant. | 6, 14 |
| LCZ 10 pair-gated rule measured inert on Rotterdam | Rule replaced. LCZ 10 removed from the distance metric per Bernard; assigned functionally with a threshold **calibrated by precision/recall against the Rotterdam reference**, not chosen a priori. **Ruled in Phase 6, implemented in Phase 14** — `rules.py` carried the pair gate verbatim for eight phases after the spec recorded it as superseded, with a threshold picked a priori at 0.50. | 6, 14 |
| LCZ 8 — Bernard also excludes it from the distance approach | **Diverge from Bernard: keep LCZ 8 in the metric.** Ruling stands; **its stated reason was wrong and is corrected in Phase 14.** `mean_building_area_m2` is not a metric dimension and never has been, so it cannot be what captures LCZ 8. The real separator is `aspect_ratio` — 0.1–0.3 against LCZ 3's 0.75–1.5 and LCZ 6's 0.3–0.75 — since LCZ 8's BSF band overlaps both and its `Hr` band is identical to LCZ 3, 6 and 9. That is also why LCZ 8 scores 0.0% (n=224) on Rotterdam: `aspect_ratio` is null exactly where large setbacks stop streets reaching buildings. | 6, 14 |
| `industrial_fraction` denominator | **Contradicted three ways at once, resolved in Phase 14 by emitting both.** This row said building area; `ucp/parameters.py`'s docstring said building area; the code, `config.py` and the registry said unit area and argued for it. Now `industrial_fraction_of_building_area` (Bernard's `FIND/B`) and `industrial_fraction_of_unit_area` ship as separate named columns, with the bare name a deprecated alias for the unit-area one. **The LCZ 10 rule reads `FIND/B`, and Bernard's 0.33 does transfer** — the shipped 0.45 is the sweep's own pick and the two perform comparably. An intermediate Phase 14 reading that `FIND/B` saturates at a 100 m cell was a numerator artefact and is retracted. | 5, 14 |
| Davenport terrain roughness class in Phase 5 | **Spec bug, corrected.** Requires z₀, which is deferred. Moved to deferred alongside the roughness work. | 5 |
| Anti-pattern "don't commit anything from `docs/references/`" contradicting Phase 0 | **Spec bug, corrected** (third occurrence). PDFs are ignored; `tables/`, `README.md`, `references.bib` are committed. | 0 |
| Stewart & Oke cannot classify the natural family | **Accepted for MVP.** A–D separate only on building-derived parameters; F and G differ in no published dimension. lczkit-defined `tree_fraction`/`water_fraction` ranges tagged `source="lczkit"`; C and F recorded unreachable in the manifest. Reading Bernard's natural branch (Figs. 2–3) and feeding canopy height as the natural roughness element is **deferred**, not rejected. | 6 |
| Five of ten Stewart & Oke properties never reach the metric | Accepted and documented. Anthropogenic heat is the only published property separating LCZ 10 from 8 directly (300+ vs ≤50 W m⁻²) and is unmeasurable here — the standing justification for a functional attribute. | 6 |
| Global LCZ map is `lcz_v3.tif`; Tier 1 citation describes an earlier version | Record both in the manifest. References README and Tier 1 row cite v3. | 6, 13 |
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
| Target of 50–60% agreement | **Wrong target.** `lcz_v3` itself reaches only 53.2% against So2Sat labels on the 432-cell Berlin fixture. Baseline accepted; agreement optimisation stopped. Superseded by the 75.2% full-sample ceiling. | 6.7, 9 |
| Height promoted to first candidate cause in 6.6 | **Reversed**, then the reversal itself superseded — both readings came from raw axis shares. See Phase 12. | 6.6, 6.7, 12 |
| Rotterdam treated as a validation city | Dropped from quality reporting. 10.7% of its reference LCZ 8 cells contain no building; no So2Sat coverage. Retained as the industrial fixture for the LCZ 10 rule only. | 6.7 |
| Enclosure-vs-grid BSF comparison on Berlin | Self-corrected: the two sets covered different ground (0.15 vs 0.29 km²). Covered area must be printed beside any such comparison. Rotterdam's comparable sets show enclosures moving LCZ 8 *further* out of range. | 6.7 |
| `eps_m` as config | No — a floating-point tolerance is not a domain threshold. Module constant. | 1 |
| `neatnet` superlinearity | **Existential when found.** 144 km² did not complete in 1h35m. Invisible for seven phases because the fixture is 9 km². Resolved by tiling in Phase 8. | 1, 8 |
| Whole-network `fix_topology` in `resolve_artifact_threshold` | Quadratic (exponent 2.0), ~8.6 h at metropolitan scale. Replaced by pooled per-tile distributions after an equivalence test at 64/144/256/324/400/484 km². | 8 |
| `ProcessPoolExecutor` default `fork` context | Deadlocks after threaded native libs run in the parent. Use `forkserver`, and pin `OMP_NUM_THREADS=1` in workers to prevent thread oversubscription. | 8 |
| Building cleaning suspected as a scaling problem | **Wrong.** Near-linear: 76.2 s for 303k footprints at 400 km², ~4 min at 892k. | 1, 8 |
| Pooled-threshold bar "must not move any classification" | **My bar was wrong, superseded.** It presumed the whole-network threshold is truth; both are estimators. Adopted on the corrected bar: no bias, deviation shrinking with extent, adjacent-class flips only, 0.023% rate, 440× cost. | 8 |
| Per-seam stitching | Built, measured at the extent it was designed for, **reverted**. Global stitch is 17.4 s not 6h50m; per-seam was slower and less accurate. Premise was an unmeasured inference. | 8 |
| 6h50m stall attributed to `_stitch` | Wrong by inference-from-adjacency. Real cause was `resolve_buildings_on_streets` intersecting every footprint against one unioned road geometry, ~75 h extrapolated. Index-bounding is exact: 39.3× faster, 0.0 m² symmetric difference. | 8 |
| `forkserver` child re-executes the parent entry point | Like spawn. Hide `__main__`'s `__file__` and `__spec__` for the life of the pool. | 8 |
| Pooled threshold at 891 km² | **Adoption confirmed.** 10 of 172 181 cells (0.0058%), four-fold below the 256 km² rate. Whole-network cost measured at 10h39m against ~70 s. | 8 |
| `clean_vectors` at 4 469 s | **Outlier, not regression.** Two cold runs over the same extent gave 456 s and 551 s, bracketing the 585.6 s benchmark. Overlapped a 10-hour single-core job on a shared node — recorded as coincidence in time rather than measurement. | 8 |
| Feature-count gap of 1.7% | **Wrong baseline.** 195 508 predates the road-rule and threshold fixes. Post-fix runs give 198 698 / 198 804 / 198 879 — a 0.04% gap. | 8 |
| Cached and cold runs differ by 75 features | **Closed at `040be15`.** Not the cache (those runs shared none) and not stitch ordering (`pool.map` preserves job order) — both were inference from adjacency. `OvertureSource._fetch` scanned remote parquet with no `ORDER BY`, and `neatnet` re-nodes in receipt order. Layers now arrive sorted by GERS id. **A working-tree edit later reverted this record to "Open"; flagged in Phase 12 and restored.** | 8, 9, 12 |
| Power-law extrapolation of runtime | Ran 24% optimistic (8.6 h projected, 10h39m measured). Treat such fits as lower bounds when deciding feasibility. | 8 |
| Berlin's 53.2% ceiling | **Small-sample artefact of 432 cells. Real ceiling is 75.2% on 9 627.** The MVP-complete framing rested on it. | 6.7, 9 |
| "% of ceiling" as a metric | **Broken.** Vancouver: 41.8% against a 36.7% ceiling = 114%. The comparator is another estimator, not a bound. Report raw agreement and ceiling side by side. | 9 |
| SVF as the next accuracy lever | **Dropped.** Weight 4 added to a metric that could not fill its weight-6 `Hr` dimension across most of the world. Height tiers first; then Phase 12 named unit definition. | 9, 10, 12 |
| Height cascade tiers 2–4 | **Specified in Phase 3, never built.** Phase 9 shows this is the binding constraint outside Europe. Built in Phase 10. | 3, 10 |
| Height tier acceptance tested on per-building error | **Wrong test.** Open Buildings has the lowest per-building error and the only within-unit skill, and still degrades the map: `Hr` is a geometric mean and GOB's within-unit spread is 0.441 against reality's 0.195. Evaluate new height tiers on **within-unit dispersion**, not MAE. | 10 |
| `full` cascade (with GOB 2.5D) as default | **Refuted.** `coarse→full` is −1.9 points, positive in only 4 of 9 cities. Default is `coarse`. | 10 |
| `min_height_m` floor for Open Buildings | **Rejected.** Undocumented threshold tuned to stop one product hurting; would be copied and outlive its justification. Also treats the wrong thing — the problem is dispersion, not a low tail. | 10 |
| P2: coarse products favour the grid over enclosures | **Refuted in the opposite direction.** B's built-class lead widens with heights filled (+1.7 → +4.1). Phase 9 handicapped enclosures by measuring them with `Hr` mostly null. | 10 |
| Berlin baseline 40.9% / 53.2% ceiling | **Superseded.** Full-sample: 35.3% against 75.2% on 9 627 cells, independently reproduced. The gap is 40 points, not 12. | 6.7, 9, 10 |
| Berlin as primary fixture | **Hong Kong is better** — 13 classes, the richest on disk, and the antidote to the two-mid-rise-class fixture that distorted Phase 6.7. Test strategy updated. | 10, 13 |
| A vs B, three measurements | Not adopted, three times, same pre-registered rule (needs both overall and built). Phase 11's third pass: built +3.8 (12/15), overall −0.2 (8/15), **split regionally** — enclosures lead on both criteria outside Europe/N. America. Ruling: `unit_strategy` as config, default `grid`, **no auto-selection by region** — region is not the mechanism. **Ruled in Phase 11, applied in Phase 17** — for six phases `pipeline.run_pipeline` held a literal `GridUnits()` and never assembled barriers, so enclosures were unreachable from the chain at all. Fifth instance of "a ruling is not applied until the code says so", and found by needing the seam rather than by auditing for it. | 9, 11, 17 |
| Enclosures as the organic-unit answer | **Measured and refused.** An enclosure is a block: median 0.04 ha on the Hong Kong fixture, against WUDAPT's 2.2–52 ha and a So2Sat patch's 10.24 ha. A thinner barrier set does not fix it either — four settings measured, all bimodal, median moving 0.04 → 0.11 ha at best, because a thinner network stops subdividing big faces rather than enlarging small ones. **`PatchUnits` sets the scale with a merge step**; the barrier filter alone would not have. | 6.5, 11, 17 |
| Pedestrian ways as enclosure barriers | Dropped by default. `footway`/`steps`/`path`/`cycleway`/`bridleway` are **72.7% of Berlin's segments, 72.8% of Hong Kong's, 50.6% of Milan's** and 3.5–7.5% elsewhere, so leaving them in makes the partition largely a measure of footpath survey completeness rather than of the city. `pedestrian` is kept — Overture uses it for plazas, which are real breaks. | 17 |
| Units defined using parameters the classifier then scores | **Accepted, documented, and bounded.** Standard for a regionalisation (SKATER, AZP), and still mild circularity: a patch is homogeneous in BSF partly because it was built to be. It cannot inflate agreement with an external reference, so validation is unaffected; it does weaken `bsf_by_reference_class` on patches. **Phase 13's conclusions stay on the grid.** | 13, 17 |
| Cascade order as a blending knob | **Ill-posed.** Winner-takes-all per building; `full_reversed` is bit-identical to `coarse` in 6 of 8 cities. Order is a selection switch and no intermediate configuration is reachable by reordering. | 11 |
| Open Buildings 2.5D | **Retired from the cascade.** Hurts first, claims 0.3–6.4% last. Code and tier interface kept, documented as measured-harmful. | 10, 11 |
| Retention measured against summed raw footprint area | **Spec bug, corrected and implemented.** Sources self-overlap (Kowloon 7.52%, Berlin 0.61%), making ≥99%-of-sum and trim-not-merge jointly unsatisfiable. Measured against the **union**, one-sided; `FootprintCoverage` reports `raw_self_overlap_fraction` and a residual, since `union_retention` above 1.0 means the BSF numerator still double-counts. | 1, 11, 12 |
| Whole-footprint `union_all` for the union denominator | **Rejected on measurement, exactly as the anti-pattern requires.** Superlinear (exponent 1.26→1.80), **711 s at Berlin's 891 km²** against a 9.8-minute whole run. Replaced by a component-wise union over genuinely overlapping footprints: sublinear (max 0.84), **8.6 s at 891 km², 83×**, and exact — agrees with the global union to **0.0000 m²** at 64/144/256 km². | 12 |
| Confusion-axis shares across cities | **Retired — the raw share cannot carry a comparison in either direction.** Not across cities (denominator is all disagreement; natural share ranges 3.5%–54.1%) and **not between the axes** (height has six pairs to compactness's three, so a null awards it 3.9× more). Only pair-normalised `lift` against a composition-preserving null is reported, with the cascade and reference named. **All raw-share figures since Phase 9 are void.** | 9, 10, 12 |
| Phase 9's "height dominates 15.5% vs 2.6%, three to one" | **Mostly instrument — close to what it returns when nothing is happening.** Affordance alone gives 3.9×, observed 4.9×, excess only 1.26×. Normalised, height sits at 0.86 and compactness at 1.16, and compactness leads at *both* cascades. Both readings this project took from the raw share, Phase 6.7's and Phase 9's, were taken through a broken instrument. | 6.7, 9, 12 |
| Axis figures recorded without their cascade | **Half a measurement, and the lever ordering is superseded by it.** `none` gives 14.1% / 2.9%, `coarse` gives 6.0% / 6.4% on the same sixteen cities — filling heights halves the height axis, which is the cascade working. The package has shipped `coarse` since Phase 10, so Phase 9's medians describe a configuration it stopped shipping — **Phase 10 was itself the intervention invalidating the evidence.** Tag every stored diagnostic with its cascade setting. | 9, 10, 12 |
| Next accuracy lever | **Unit definition and footprint coverage** — normalised compactness lift 1.16 against height 0.86, leading 11 of 16 at `coarse`. Not "adopt enclosures": arm B *raises* the compactness lift (2.33 vs 1.64). | 12 |
| `_axis` count-weighted while the module docstring said everything was area-weighted | Both now reported; the count-based field keeps its definition so no stored arm-B figure moves silently. Identical on a grid, which is how it survived to Phase 11. | 6, 12 |
| `unit_scale_experiment.show()` printed `lcz_v3` axes under an unlabelled heading | Fixed. It sat four lines below a table whose columns *are* labelled. Did not contaminate published figures, but the two references disagree by more than the quantity measured — Cairo 7.2% vs 24.7% compactness. | 12 |
| `tiles.subset()` discarded the canonical row order | `sindex.query` is documented as unordered, and its result went straight to `neatnet` and to the pooled threshold that keys the tile cache. Sorted. **On the fixture the order-sensitivity that `test_simplification_depends_on_input_row_order` attributed to `neatnet` was `subset`'s own** — untiled, that network simplifies identically under a shuffle. | 8, 9, 12 |
| Pooled-threshold thread environment asymmetric | The serial branch ran unpinned while the parallel branch ran pinned, and `n_workers` follows `os.sched_getaffinity` — so the same extent on a differently-sized node could land on a different cache key. Both branches now pinned. | 8, 12 |
| Regional split, second independent sighting | Compactness lift 2.37 Europe/N. America vs 1.15 elsewhere; same seven-against-nine split as Phase 11's A/B. Finding in its own right; **mechanism still unknown, and the proposed street-area mechanism is refuted** (Phase 13). Report as an unexplained regularity. | 11, 12, 13 |
| Row-order fix vs tile cache | Threshold bit-identical, but the cache would have served pre-fix tiles silently. `TILE_RESULT_VERSION` bumped. | 8, 12 |
| Determinism / "stitch ordering" | **Closed in Phase 9 at `040be15`.** An external CLAUDE.md copy reverted this record to the disproved diagnosis; committed text restored. Residuals closed with deviation measured: ~1.2% of linework at different split points, total length unchanged to four decimal places. | 8, 9, 12 |
| Externally-maintained CLAUDE.md copy | **Retired.** The committed file is canonical; rulings arrive as patches. If a supplied edit contradicts a committed record, flag and stop. | — |
| `bsf_by_reference_class` grouped by `lcz_v3`, not by labels | **The second reference mix-up, in the instrument Phase 13 turns on.** `evaluate` built it from `fixture.reference`, whose own docstring says "a comparator, never the primary reference", while `fixture.ground_truth` went unused — 91 158 Berlin cells against 9 627 labelled. `RangeReport` now carries `reference_file`; `bsf_by_ground_truth_class` added, on the arm's own units. Class figures move up to 18.2 points; **the phase outcome does not.** Fix before any paper figure is generated. | 6.5, 11, 13 |
| Phase 13 as "a re-analysis of stored records, seconds not hours" | **Not satisfiable.** Per-unit BSF is not persisted and the stored aggregate was against the wrong reference, so the sixteen cities were re-run at `coarse` — 5.09 h. The brief also said the test last ran on Berlin and Rotterdam pre-fixes; it ran on all sixteen in Phase 11, post-cleaning-fix and post-cascade. | 13 |
| BSF against the published ranges | **Outcome 3 — the ranges do not transfer to 100 m cells.** One class of ten reaches, holding 11.9% of built cells. Medians are close (six of ten within 0.13 widths, LCZ 1 and 5 inside); **spread is what fails.** Published and empirical intervals reported side by side, empirical tagged `lczkit_empirical`. **Not recalibrated.** | 6.5, 13 |
| "BSF depressed, worse in Europe" as the expected mechanism | **Refuted.** Europe trails on 2 of 9 classes and leads LCZ 2 by +35.4 points. Europe's BSF is the healthiest in the sample, so it cannot explain Europe's higher compactness lift. | 12, 13 |
| Phase 6.5's patch-versus-cell hypothesis | **Returns, and is now supported** — from the opposite direction. 6.5 rejected it over a numerator losing 23.5% of footprints; with those restored the medians are right and the within-class variance is what the published bands cannot hold. | 6.5, 13 |
| LCZ 7 at 8.2% in range | 0.417 against a published 0.60–0.90, low on both tails, five non-European cities. An **Overture coverage limit on informal settlements**, not evidence about the 100 m cell. **Opened as a bounded exception, paper scope only** — measured from existing records, no new phase. It is the class the founding premise is about. | 13 |
| Per-cell heterogeneity measure | Future work, discussion section only. Do not build. | 13 |
| Phase 7 built during Phase 8 and never recorded as concluded | The site shipped in `6ebaca2` (2026-08-09) while this spec went on calling it "the only outstanding deliverable" for fourteen commits, and three user rulings lived only in the experiment write-up. **A phase is not concluded until CLAUDE.md says so** — a deliverable built out of order is the easiest to leave half-finished, because the code exists and looks done. | 7, 8 |
| Phase 7 `file://` acceptance criterion | **Not satisfiable, amended.** PMTiles reads byte ranges through `fetch`; the Fetch standard leaves `file:` URLs unhandled, so Chrome and Firefox both error. Criterion is now "opens with no network and no software the user must install". `site/serve.py` is standard library only and implements `Range`, which `SimpleHTTPRequestHandler` does not. **The amendment reached the anti-pattern list late** — that bullet still demanded a `file://` open after the criterion had been retired in two other places, which is how a superseded acceptance test survives. Every built site now ships a `README.md` giving the working command, because the recipient's first move is the one that fails. | 7 |
| Phase 7 basemap as a Protomaps extract | **Not reachable here, replaced.** An extract needs a Go CLI or a ~120 GB download. Built from the run's own cleaned water and streets: already cached for the bbox, ODbL-attributable, and the same linework the classification used. | 7 |
| tippecanoe at 256 cores | Fails with `745 shards not a power of 2` from its radix sort. Capped at `min(cpus, 32)`; output byte-identical across thread counts. Third defect invisible on a laptop and fatal on the deployment machine, after Phase 8's `fork` deadlock and thread oversubscription. | 7, 8 |
| Selector order inherited from the manifest's `breaks` | Break order is DataFrame column order — incidental. It put `height_completeness` twelfth of thirteen and gave `height_tier_fractions` no entry at all, in the one place the spec names a position. Ordered deliberately; tier fractions reach the render set by prefix, since their columns are named after whichever cascade fired. **+2.12 MB, +7.5%** at 172 181 units, measured. | 7 |
| The LCZ layer painted every cell as no-data | **The site's default view never rendered, from `6ebaca2` until it was looked at.** tippecanoe's FlatGeobuf reader emits integer attributes as *strings* — measured at int16, int32, int64 and uint8, while float64 survives as a number — so `["match", ["get", "lcz_primary"], 1, …]` found no label and fell through to `NODATA_COLOUR`. `lcz_primary` is the only integer column the site renders, which is why the choropleths were fine. Coerced with `to-number`. | 7 |
| Style and tiles each tested against their own assumption | The style test asserted the expression carries the committed colours; the site test asserted the tileset is a valid archive. **Nothing asserted that the type in the tiles is a type the expression can match**, so a defect in the gap between them was invisible to 37 tests. A test now decodes the built tiles and evaluates the real paint expression against the real values — it fails 6 of 6 without the fix. | 7 |
| WorldCover clipped from one hardcoded tile | Berlin's `N51E012`, inherited by the publish driver. Hong Kong and Cairo span two tiles each and both failed with `RasterioIOError: 0x0 dataset`. `clip_worldcover` already resolved and mosaicked correctly. **Found only by publishing a second city** — a city one tile-width away would have lost a quarter of its land cover silently. | 7 |
| Did the Phase 9–13 validation runs share that hardcoded path? | **No — checked against the persisted rasters, and clean.** `multi_city_validation` never imported `WORLDCOVER_URL`; `prepare` has always called the mosaicking `clip_worldcover`. All four stored runs verified: 15/9/16/16 cities, **worst shortfall 0.45 px**, no raster missing, nodata 0.000% bar a one-row clip edge on Cologne and Rome. **Six of sixteen cities span two tiles** — London, Cologne, Rome, Cairo, Hong Kong, Vancouver — so the mosaic path was exercised by real inputs, not merely present. No re-run needed. | 9–13 |
| The site must reach no network, vs. a request for OSM base layers | **Both, by making the exception opt-in and bounded.** `VizConfig.online_basemap` defaults to `None` and the default build still names no remote host anywhere. The enforcing test **split rather than relaxed**: one asserts the default reaches nothing, a second asserts that a configured provider's URLs appear in `style.json` and in no other file. A site built with one is no longer archival and its own `README.md` says so. | 7, 15 |
| `run_layers` collected by the `basemap-` prefix | The remote raster layer is `basemap-raster` and matched too, so "the run's own linework" — the choice that exists precisely to avoid the network — would have fetched it. Collected explicitly as the layers are appended. **A name prefix is not a category.** | 15 |
| `app.js` mapped `label_route` values the classifier never emits | It explained `distance`, `lcz10_rule`, `lcz1_constraint`; `rules.ROUTES` is `distance_built`, `distance_natural`, `industrial_rule`. Every cell would have printed its raw token. Found by the first test ever written against `app.js`, not by reading. **A consumer that guesses at a producer's enum fails silently** — the tippecanoe type defect one layer up. | 7, 15 |
| `app.js` had no test of any kind | Phase 7 argued assertions about it "would be claims about a string", which is right about behaviour and wrong about syntax: a syntax error means the IIFE never runs, so the `catch` that reports load failure never installs, and the page is blank with no message. `tests/test_viz_app_js.py` checks delimiter balance, that every `el(id)` exists in the markup and vice versa, and that the metadata keys it reads are the ones `style.py` writes. | 7, 15 |
| Sidebar and selector labels built as `column.replace("_", " ")` | Produced "height of roughness elements m" and "industrial fraction of building area" on all three published maps. `ParameterSpec.label` puts the display name beside the definition; `DISPLAY_LABELS` covers the classification columns the registry does not describe, and `HEIGHT_SOURCE_LABELS` turns `height_frac_wsf3d` into "WSF-3D, 90 m raster". | 7, 15 |
| `NODATA_COLOUR` indistinguishable from a low band | A null parameter is a reportable state — `aspect_ratio` is null wherever no street reaches a building, which is most of LCZ 8 — and every layer painted it the same grey with nothing saying what grey meant. Continuous legends now carry an explicit "no value" row; the categorical legend does not, since there the colour would name a class that does not exist. | 6, 15 |
| No CLI, per MVP scope discipline | **Lifted by explicit request, Phase 15.** Removed from the Deferred list and from the scope bullet, both patched here rather than departed from silently. `lczkit run` and `lczkit site build\|serve`; the rest of that bullet — no web UI, no plotting helpers, no notebook tooling — stands. | 0, 15 |
| The end-to-end pipeline lived in `scripts/` | **Moved to `lczkit.pipeline.run_pipeline` in Phase 15.** It was unimportable (no `__init__.py`, reached by `sys.path` insertion), outside `mypy src`, and pulled its config constants and land-cover fetcher from two *other* scripts, with three partial re-implementations beside it. A bbox was a module constant, so a new city meant editing a script. `run_and_publish` and `configure` keep their names and delegate, so `publish_sites.py` and the phase write-ups that cite these paths still hold. | 8, 15 |
| Two `CleaningConfig` constants both named `CLEANING` | `berlin_metropolitan.py` carries the metropolitan values the published sites used (`max_area 100_000`, `merge_limit 50`, plus street tiling); `unit_scale_experiment.py` carries the 9 km² fixture values (`50_000` / `200`, no tiling). `configure()` took the former. `presets.PRESETS["published"]` therefore takes the former, and **a test asserts it still equals it** — taking the other would make `lczkit run` silently irreproducible against every published figure. | 8, 15 |
| `Settings.load()` created `run_dir` as a side effect | Fine while every caller went on to run a pipeline; wrong as soon as a command exists whose purpose is *not* to act. `create_run_dir=True` by default, `False` for `--dry-run`. | 0, 15 |
| `land_cover.gee_project` overwritten with `None` | `settings.land_cover.gee_project = os.environ.get("GEE_PROJECT_NAME")` ran unconditionally, so an absent variable discarded a configured value. A silent discard, not a precedence rule. Assigned only when the variable is present. Invisible until `--config` made it possible to configure the field. | 4, 15 |
| `Settings.load` finds the repository `.env` from anywhere in a checkout | dotenv's upward search, not the working directory. `override=False` means an already-set `DATA_DIR` wins, so tests set the variable rather than writing a file — but a test of the *unset* branch must neutralise `load_dotenv` outright, since the repo's own `.env` would otherwise satisfy it. Pre-existing; recorded because it is invisible until something tests the failure path. | 0, 15 |
| WUDAPT named the secondary reference in Phase 0, never built | **Sixteen phases unread.** `grep -rni wudapt` returned prose only — no loader, no config entry, no source-dir constant, zero `.py` hits — while the file sat on disk covering every city the package had been run on. Built in Phase 16, on explicit request. The same shape as the height cascade being specified in Phase 3 and built in Phase 10: a capability the spec assumes and the code does not have is invisible until something asks for it. | 0, 16 |
| Do the ground-truth labels themselves reproduce? | **Never asked until Phase 16, and they do not.** Two independent expert label sets over the same ground: median 79.9%, range 26.3%–96.3%, Europe + N. America 89.1% mean against 69.3% elsewhere. Cairo sits *below* its own majority-class baseline. A floor under every residual this package reports, larger than the patch-versus-cell floor, and it must be stated beside any per-city figure. | 16 |
| WUDAPT's QC flags and `oa` as a quality filter | **Rejected on measurement.** The QC gate costs half the polygons and moves agreement with So2Sat by +0.4 / +2.9 / **−1.9** points on Cairo / Mumbai / Jakarta; `oa ≥ 0.7` gives **−7.2** / −0.1 / −1.1. `oa` is a submission scored against *itself*, so it selects self-consistent contributors, not ones who agree with an independent expert — which is the whole job of a second reference. Defaults off, measurement in the config docstrings. | 16 |
| `lcz_v3` vs WUDAPT as a second ceiling | **Not independent, and flagged as such in the record.** The LCZ Generator's training areas are that map's training data, so the figure compares a model against a subset of its own training set — Vancouver reads 86.8% against a real ceiling of 36.7%. Computed and reported with `independent: False` and a written reason, precisely so nobody recomputes it elsewhere and reads it as So2Sat's equivalent. | 6.7, 16 |
| WUDAPT's stored `area` column | **Unusable: km² in Web Mercator**, inflated by 1/cos²(latitude) — median ratio to true area 1 004 995 against Mollweide's 744 899. Every filter and statistic recomputes from geometry; a test corrupts the column and asserts nothing moves. | 16 |
| WUDAPT `class` runs to 19 | 633 polygons globally carry codes 18 and 19, outside the Demuzere coding. Dropped and counted, never folded into a neighbouring class — this package has no definition for them and inventing one would put a label into the reference no contributor drew. | 16 |
| Overture's `subtype`/`class` unread for eighteen phases | One parameter of twenty read a semantic attribute. Built in Phase 18 on request: `sem_*` group fractions plus `building_tag_coverage` and `land_use_coverage`. **Tagged building area is 48.6% across Europe/N. America against 13.6% elsewhere** — the founding premise on a second attribute, and a fourth sighting of the seven-against-nine split. Mechanism measured, not inferred: wherever an ML source wins the footprints its tagged share is exactly 0.0%. | 1, 18 |
| `osm-rasterizer` / OSM tags as the semantic source | **Declined, on reproducibility.** Neither it nor `osmnx` is installed or declared, and both need live Overpass — unpinned, unreproducible, and it would introduce a second footprint set that cannot be joined to `buildings_area`. The knowledge in `osm_lcz_tag_mapping.md` is ported into an Overture-native crosswalk instead. OSM's `industrial=*` heavy/light split remains unreachable and stays on the deferred list with the OSM `VectorSource`. | 5, 18 |
| Semantic fractions without a coverage column | **Unreadable, and the reason the layer exists.** A `lightweight` fraction of 0.0 in Nairobi is 94.8% of building area carrying no tag, not an absence of informal settlement — the same distinction `height_tier_fractions` draws for the cascade. `building_tag_coverage` is **area**-weighted, not count: tagged buildings are systematically larger (Berlin 64.4% vs 46.6%) and area is the denominator every fraction divides by. | 3, 18 |
| Whole-extent `union_all` over the land-use layer | **Caught before shipping, third instance of the anti-pattern** — and this one does not merely cost time: over real Overture land use it raises `GEOSException: side location conflict` **even after `make_valid`**, because per-feature validity does not make a collection unionable. `industrial.py` survives by unioning a few dozen parcels; the coverage column ran on Berlin's 70 509. Clip to units first, dissolve per unit: bounded, exact. Found by running the diagnostic over a real city rather than a fixture. | 12, 18 |
| `.loc[an_index]` over a building layer | Returns extra rows on a duplicated index, reporting `building_tag_coverage = 1.0` for an untagged unit. The building layer carries no uniqueness guarantee; all selection is positional now. Found by the one test written to prove the module's central property. | 18 |
| Uncalibrated functional rules for LCZ 7 and 8 | **Shipped disabled, and that is the ruling.** A threshold is swept against a reference and chosen at an operating point, never picked — the LCZ 10 sweep ran nineteen settings and Phase 14 found the threshold was not even the binding constraint there. Shipped values are placeholders. For LCZ 7 the sweep needs a city where the class exists *and* is tagged, which the coverage table suggests may not exist — itself the finding. | 6, 14, 18 |
| Nothing asserted that a clipped raster covers its window | The silent variant was one line away and would not have raised: `clip_raster` windows with `from_bounds` and `read(window=…)`, which **returns a smaller array** rather than erroring, and `LocalRasterSource.fractions` turns uncovered units into **all-`NaN`** by design. Two correct behaviours composing into a quarter-missing map. `clip_worldcover` now reopens what it wrote and raises, naming the short side; `coverage_shortfall` ignores sub-pixel gaps because every real clip has one. The last `WORLDCOVER_URL` call sites were retired — Berlin-only, so no stored result moves. | 4, 7, 13 |
| Pooling a partial sweep against a complete stored record | Reported the difference between two city lists as a pipeline deviation (6.6%). Stability comparisons now intersect the city sets; restricted, the deviation is 0.0%. | 13 |
| Superseded text left in concluded phase blocks | Phase 8's block opened with a nine-minute runtime and later asserted the package could not process a city; Phase 3 still carried the corrected-away axis pairing; deferred still listed SVF first. **Concluded phases keep measurements and rulings and drop imperatives.** | 3, 6, 8, 13 |

---

## Deferred — do not build unless asked

**Priority order within deferred: unit definition and footprint coverage first** (Phase 12:
normalised compactness lift 1.16 against height 0.86, leading 11 of 16 at `coarse`). **`PatchUnits`
exists as of Phase 17 and its sixteen-city A/B sweep is the outstanding measurement** — wired, not
run, with the reading pre-registered in that block so it cannot be chosen afterwards. **SVF is not
the next lever** — it is weight 4 added to a metric whose weight-6 `Hr` dimension the cascade only
recently filled. Standing caution: "adopt enclosures" is *not* the unit-definition answer, since
arm B raises the compactness lift rather than lowering it.

**Shrinkage of fine-resolution height products toward the unit mean** — the principled route to
rescuing GOB 2.5D, attacking within-unit variance directly rather than trimming a tail. Speculative;
only worth it if `Hr` dispersion becomes the binding residual.

Vector ray-cast sky view factor · roughness length and displacement height (Macdonald / Kanda)
**and the Davenport terrain roughness class lookup, which depends on z₀** · Bernard's natural-type
branch (Figs. 2–3), with ETH canopy height as the natural roughness element — Stewart & Oke treat
trees as the roughness elements for A–D, so canopy height should recover A and B properly and
push D toward near-zero canopy · additional height tiers (UT-GLOBUS, GlobalBuildingAtlas,
EUBUCCO, morphology-based ML imputation) · ML classifier trained on So2Sat LCZ42 / DFC2017 ·
fuzzy or continuous LCZ output · W2W / WRF export · OSM as an alternative `VectorSource` ·
tessellation-based building-level units · dask-geopandas scaling · deck.gl overlay for
buildings (only if MapLibre `fill-extrusion` proves insufficient) · run-comparison views in the
site · OSM `industrial=*` subtags as supplementary heavy/light industry evidence (arrives with the
deferred OSM source; the only realistic route to the distinction Overture discards, and reaffirmed
in Phase 18 — an Overture-native crosswalk cannot recover it, because the values are not in the
normalised vocabulary at all) · **calibration sweeps for the Phase 18 LCZ 7 and LCZ 8 rules**, which
ship disabled precisely because a threshold is swept and not picked; note the LCZ 7 sweep needs a
city where the class exists *and* is tagged, and the coverage table suggests there may not be one

*(**CLI removed from this list in Phase 15**, built on explicit request. `lczkit run` and
`lczkit site build|serve`.)*

---

## Anti-patterns

- Don't optimise before the walking skeleton runs end to end.
- **Don't introduce a whole-extent operation without measuring its scaling exponent at three or
  more extents.** `neatify` was profiled that way and tiling worked; the threshold-pinning step
  was not, and cost 15 hours. This applies to any operation over the full network, the full
  building set, or the full unit set — including ones added to guarantee correctness. It has now
  paid twice: Phase 12's footprint union looked like a cheap scalar and was superlinear at 711 s
  over Berlin, caught before it shipped rather than after.
- **When a fix changes what a cached artefact contains, bump the cache version — do not assume the
  key notices.** Phase 12's row-order fix left the pooled threshold bit-identical, so the key would
  not have moved while tile contents did, serving pre-fix tiles to a post-fix run. That is the same
  "cache that changes results" failure the Phase 8 entry was opened for, nearly reintroduced by its
  own fix.
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
- Don't inline data into `index.html`, link a CDN, or use a basemap requiring an API key. The site
  must open with no network and no software the user must install, and remain valid years from now.
  It is served by its own bundled `serve.py` over loopback — `file://` is not satisfiable, because
  PMTiles reads byte ranges through `fetch` and the Fetch standard leaves `file:` URLs unhandled.
  Every built site carries a `README.md` saying so, since the first thing a recipient tries is
  opening `index.html` and it fails with an unexplained network error.
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
- **Don't compare two error axes by raw share when they afford different numbers of confusable
  pairs.** Normalise against a composition-preserving null. A null that never looks at the data
  awards the height axis 3.9× on affordance alone.
- **Don't carry a diagnostic forward across a configuration change without re-measuring it.** Phase
  9's lever ordering was measured at cascade `none`; Phase 10 shipped `coarse` and halved the height
  axis. Tag every stored diagnostic with the configuration it was measured under.
- **Don't assume a geometric set operation is cheap because its result is a scalar.** `unary_union`
  over a city's footprints is superlinear — 711 s at 891 km² against a 9.8-minute whole run.
  Component-wise union is sublinear and exact. **And it is not only a cost problem**: Phase 18 found
  a global union over real Overture land use raises `GEOSException: side location conflict` *even
  after `make_valid`*, because validity per feature does not make a collection unionable. Clip to
  the units first and dissolve per unit — bounded, well-conditioned, and exactly equal.
- **A helper that is safe on a subset is not thereby safe on the whole layer.**
  `industrial._covered_fraction(dissolve=True)` has unioned globally since Phase 5 and is fine
  there, because it runs on a few dozen industrial parcels. Reusing it for *all* land use put a
  70 509-parcel union in the hot path. Check what a reused helper is about to be handed, not just
  what it does.
- **Don't select rows by index from a layer with no uniqueness guarantee.** `buildings.loc[idx]`
  over a duplicated index silently returns extra rows — a wrong number, not an error. The building
  layers carry no such guarantee; select positionally, or pass geometries rather than an index.
- **Don't let "the reference" name a role instead of a file.** `lcz_v3` and the So2Sat labels can
  both fill it, they disagree by up to 18 points, and a table that does not record which one it
  used is indistinguishable from one that used the other. Both reference mix-ups this project
  found were invisible for exactly this reason.
- **Don't compare two records pooled over different populations.** A partial sixteen-city sweep
  compared against a complete one reports the difference between two city lists as a deviation —
  6.6% of it, until the comparison was restricted to the cities both records hold, where it is
  0.0%. Intersect the populations before differencing them.
- **Don't leave superseded instructions in a concluded phase block.** Keep the measurements and the
  rulings; delete the imperatives and acceptance criteria the phase was working from. Phase 8's
  block ended up asserting both that Berlin runs in 9.8 minutes and that the package cannot process
  a city.
- **A phase is not concluded until this file says so.** Phase 7 shipped during Phase 8 and went
  unrecorded for fourteen commits, with three of its user rulings living only in its experiment
  write-up. Code that exists and looks done is the easiest kind to leave half-finished.
- **A ruling is not applied until the code says so, either.** The mirror of the line above, and it
  cost more: four rulings sat in this file as decided while the code did the superseded thing, the
  largest for eight phases — `rules.py` kept a pair-gated LCZ 10 rule this file recorded as measured
  inert and replaced. Nothing checked the two against each other in either direction. When a ruling
  lands, either apply it or record explicitly that it is deferred and why.
- **A quantity's denominator belongs in its name.** `industrial_fraction` was contradicted three ways
  inside one repository — this file and one docstring saying building area, the code, config and
  registry saying unit area and arguing for it. A column whose meaning is contested cannot be fixed
  by documenting it harder; emit both, each named for what it divides by.
- **Don't retire a quantity by writing "retired" — retire the code that reads it.** Phase 12 removed
  the raw axis share "from reporting" and two scripts went on medianing it across sixteen cities.
  The field has to stay (stored records depend on its definition), so the guard belongs on the
  *reading*: a test that fails when a reporting path touches it. The same applies to "% of ceiling",
  ruled broken in Phase 9 and still printed in two places by the same script.
- **A quantity defined over a patch may not transfer to a 100 m cell.** Two instances: Stewart &
  Oke's parameter ranges (Phase 13) and the So2Sat labels themselves (a 320 m patch attributed to a
  1 ha cell). Before transferring a published threshold, check that the cell is large enough to be
  the object the quantity describes.
- **Before calling a degenerate distribution a scale finding, change the numerator and re-measure.**
  Phase 14 measured Bernard's `FIND/B` saturating at 84% of cells reading exactly 1.0, concluded the
  quantity does not survive an RSU-to-cell move, and wrote that into this file, the paper's argument
  and the README. It was the numerator: it counted every building standing inside an industrial
  *parcel* as industrial, and parcels swallow whole cells. The real figure is 12.6%. **A scale
  finding and a definition bug are indistinguishable from the distribution alone**, and the scale
  story is the more interesting one, which is exactly why it gets believed first.
- **A performance regression can hide behind a correctness fix.** The same change added three
  whole-extent geometric operations — two extra `union_all` calls and an intersection of every
  footprint against a dissolved industrial geometry — and Berlin stopped completing inside 50
  minutes. The fixtures are 9 km² and said nothing. This is the standing scaling anti-pattern being
  broken by the very work that was auditing the codebase for broken rulings.
- **Don't run a generalised driver over one input and call it general.** The publish driver clipped
  land cover from a single hardcoded tile: correct for Berlin, a hard error for the next two cities,
  and — for a city one tile-width away — a quarter of the map silently missing. The second input is
  the one that tests the abstraction, which is why the spec asks for two cities and not one.
- **Assert the precondition where a missing input would go quiet rather than loud.** Land cover is
  the sole classifier for A–G, and a raster short of its window produces `NaN` fractions, not an
  error. Wherever two individually-correct behaviours compose into silence — a read that truncates,
  a lookup that returns null — the guard has to be written explicitly; nothing else will notice.
- **Don't test a producer and a consumer only against their own assumptions.** The style test
  asserted the paint expression was right and the tile test asserted the tileset was valid, and the
  site's default view painted blank grey in every city because nothing asserted the *type in the
  tiles* was a type the *expression* could match. Where two components agree by convention rather
  than by a shared definition, the test has to span both — decode the artefact and run the real
  consumer against it.
- **Don't assume a format conversion preserves types.** tippecanoe's FlatGeobuf reader turns every
  integer attribute into a string, at every width, while floats pass through. The GeoParquet was
  right, the FlatGeobuf was right, and the tiles were wrong.
- **Two constants with the same name and different values will eventually be confused.** `CLEANING`
  existed twice — metropolitan values in one script, 9 km² fixture values in another — and only one
  of them is what the published sites went through. Nothing about either name says which. When a
  value is promoted out of a script, assert it still equals the constant it came from; the assertion
  is the only thing that notices when one of the two moves.
- **A convenience wrapper must not become a second definition of the thing it wraps.** The command
  line configures a run by calling the same `apply_preset` the publish driver calls, rather than by
  listing the same settings again. Anything a CLI restates is a place two answers can diverge, and
  the divergence shows up as a map that disagrees with a published figure for no visible reason.
- **A name prefix is not a category.** The offline basemap layers were collected by matching
  `basemap-`, and the *remote* raster layer is `basemap-raster`, so the one choice that exists to
  avoid the network contained it. When two sets are meaningfully different, build them from the
  decision that separates them, not from what their names happen to share.
- **Don't relax a guarantee to make room for an exception — split the test.** The site's
  no-network property is enforced, not merely documented. An opt-in online basemap kept it by
  leaving the default assertion untouched and adding a second that pins exactly where a remote host
  is allowed to appear (`style.json`, and nowhere else). A guarantee with a bounded, tested
  exception is still a guarantee; one loosened to accommodate a flag is not.
- **Code nothing executes still needs a syntax check.** `app.js` went seven phases with no test on
  the argument that assertions about it would be claims about a string. True of its behaviour, false
  of its syntax: a syntax error stops the IIFE running, so the error handler that would have
  reported it never installs, and the page is blank in silence. A delimiter balance and a
  producer/consumer key check are weak, cheap, and caught a real defect the first time they ran.
