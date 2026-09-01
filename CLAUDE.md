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
  lifted by explicit request in Phase 15** and the CLI built. **`mkdocs-jupyter` was added by
  explicit request in Phase 20**, and **Phase 22 wrote the notebook it renders** — notebook tooling
  in the *docs build*, not in the package. **matplotlib arrived with it, in the `dev` group**, on
  the same request: it draws two figures in that notebook and is imported nowhere in `src/`, so
  the package still ships no plotting helper and the docs build never installs it. No web UI, and
  no plotting in the package; the rest of this bullet stands.
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

  **Built in Phase 23**: `lczkit.places` reads `guppd_bounds.csv` — 5 558 urban regions, 173
  countries, 564 KB — and it is what `lczkit run --city` and `lczkit cities` resolve against. A
  **locator, not a reference**: nothing there labels or validates anything, which is the point,
  since the only city locator before it read the So2Sat label archive and therefore knew 28
  places. The 117 MB polygon GeoPackage beside it is not read; a locator needs a rectangle.

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
Full write-up in `notes/experiments/phase-16-wudapt-reference.md`.

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

**Re-measured twice on an enlarged registry — and the grouping reorganised once, then held.** The
registry grew 16 → 20 → 28, each time to fix a region of **n = 1**, which cannot separate a regional
effect from one city. The headline is remarkably stable across all three: median **79.9% / 79.9% /
79.7%**, range 26.3%–97.7%.

**First enlargement (North America, Vancouver alone → four).** The grouping this file leans on three
times did not survive it:

| | n | mean | median | above baseline |
|---|---:|---:|---:|---:|
| Europe | 6 | **91.0%** | 92.5% | 0.87 |
| South America | 3 | 85.6% | 85.3% | 0.77 |
| North America | 4 | **70.8%** | 74.9% | 0.55 |

North America is indistinguishable from "everywhere else" (70.9%), and South America sits nearer
Europe than North America does. Vancouver was carrying a continent — it is now second of four,
behind Washington D.C., with New York at 50.8%.

**Second enlargement (East Asia, Hong Kong alone → six; Oceania and West Asia opened).** The
corrected line *held*, over twenty-eight cities:

| region | n | mean | median | mean ceiling |
|---|---:|---:|---:|---:|
| **Europe** | 6 | **91.0%** | 92.5% | 72.2% |
| Oceania | 1 | 87.5% | 87.5% | 59.7% |
| South America | 3 | 85.6% | 85.3% | 73.5% |
| East Asia | 6 | 72.3% | 74.1% | 52.1% |
| North America | 4 | 70.8% | 74.9% | 51.4% |
| Southeast Asia | 1 | 70.7% | 70.7% | 59.0% |
| West Asia | 2 | 69.2% | 69.2% | 51.8% |
| Africa | 3 | 61.8% | 79.1% | 48.6% |
| South Asia | 2 | 59.5% | 59.5% | 34.0% |

**Europe 91.0% against everything else 71.6%** — a 19.4-point gap, against 11.2 for the old
"Europe + N. America" cut. East Asia at 72.3% lands with the elsewhere bloc, exactly as North
America did. **The line is Europe against everywhere else**, and it has now been tested by
quadrupling one of the groups that was supposed to be inside it and sextupling one that was not.

Two further readings moved with the sample and are recorded because they contradict figures
committed at n = 16:

- **`corr(contested share, agreement)` runs −0.14 (16 cities) → −0.13 (20) → −0.36 (28).** The flat
  refutation recorded below softens rather than reverses: Tehran contests 25.31% and reaches 40.6%,
  Beijing 16.15% and 64.2%. Weak negative, not a proxy, and no longer "no relationship at all".
- **`corr(label reproducibility, ceiling)` runs +0.69 → +0.58.** Same sign, weaker.

**Caveats that travel with the regional table.** Southeast Asia and Oceania are **n = 1 and cannot
be fixed from the data on disk** — Manila carries 246 patches of one class, and Melbourne passes
So2Sat comfortably but WUDAPT holds *one* polygon there. West Asia is n = 2 with a **57-point
internal spread** (Istanbul 97.7%, Tehran 40.6%), which is two cities rather than a region. Any
figure grouped by those three should say so.

**Six European cities also qualify and were deliberately left out** — Madrid 97.5%, Amsterdam 83.5%,
Zurich 88.1%, Lisbon 76.8%, Munich 76.6%, Moscow 99.6%. Europe is already over-represented at six,
and adding six more would weaken the very comparison the enlargement exists to test. Moscow is
additionally excluded on its own merits: 99.6% on an overlap of **225 cells**, because its two
references drew different parts of the city, and a near-perfect figure on a thin non-random
intersection is the kind that gets quoted and then retracted.

**This re-measures one of the four sightings, not all four.** Phase 11's A/B advantage, Phase 12's
compactness lift and Phase 18's tag coverage were all measured over the original sixteen with North
America at n = 1 and East Asia at n = 1, and none is re-measured — the Overture extracts for the
twelve added cities are not on disk, so that is a fetch and a sweep rather than a re-analysis. Treat
the other three as measured over sixteen, not as confirmed.

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
`notes/experiments/phase-17-patch-units.md`.

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
`notes/experiments/phase-18-semantic-evidence.md`.

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

**The city registry went from sixteen to twenty to twenty-eight**, on request, after the reference
comparison showed North America was **n = 1** in a grouping this file leans on three times — and
then that East Asia was n = 1 too, with Oceania and West Asia empty. The second batch is Beijing,
Guangzhou, Nanjing, Tokyo and Wuhan (East Asia, 1 → 6), Istanbul and Tehran (West Asia, 0 → 2) and
Sydney (Oceania, 0 → 1); all eight pass the same screen and carry both references, and they are
spread across the reproducibility range — Nanjing 83.2% down to Guangzhou 58.7%, Tehran at 40.6% —
rather than picked from its top. Two good So2Sat cities have **zero** WUDAPT and stay out for that
reason alone: Osaka/Kyoto (5 134 patches, 13 classes) and Dongying (1 936, 10).

The first batch, and the reasoning that also governs the second: Added: Los Angeles, New
York, Washington D.C. (North America) and Santiago (South America) — every So2Sat city in the
Americas that passes the 500-patch / 4-class screen and carries both references. **New York was added
*because* it reproduces badly** (50.8%): keeping the North American city that agrees and dropping the
ones that do not is how a regional split gets manufactured rather than tested. Seven American cities
were refused because So2Sat barely covers them — Chicago 48 patches of one class, Salvador 1, Buenos
Aires 5 — though all seven carry real WUDAPT, so they are now reachable as WUDAPT-only cities with no
ceiling and no reproducibility figure, and a record would have to say so.

> **Every stored figure predates the last four cities.** Anything comparing a new sweep against a
> stored record must intersect the city sets first. Phase 13 already reported 6.6% of deviation that
> was 0.0% once the populations were restricted to what both records held.

**And the registry was defined twice.** `scripts/multi_city_validation.py` carried its own `City`,
`CITIES`, `BY_KEY`, `WINDOW_KM` and `densest_window` — Phase 15 lifted them into `lczkit.cities` for
the CLI and left the originals in place. The same "two constants with the same name" failure recorded
for `CLEANING`, and worse-placed: adding four cities to the package would have left **the sweep, which
is the half that produces every published figure, still running sixteen**. Found by needing it, not by
auditing. The script now imports them, and a test asserts identity rather than equality — two tuples
that happen to match today is exactly the state it exists to rule out.

---

### Phase 19 — a run a GIS can open — CONCLUDED

**Reported from outside the repository, which is the only place it was visible.** A run's units
"had no CRS" in QGIS. They did: every geometry-bearing file every run has ever written is valid
GeoParquet 1.0.0 carrying the extent's `estimate_utm_crs()` result as PROJJSON *with an EPSG
authority code* — verified across all ten runs on disk, `EPSG:32618` (Bogotá) through `EPSG:32737`
(Nairobi), `units.parquet` and all four `layers/*.parquet` alike. Nothing was wrong with the files.

**The format is standard; the reader is optional.** GDAL's Parquet driver is a build component, not
core, so a QGIS built without it opens a correct file as a non-spatial table — and the symptom is
"this layer has no CRS", which points at the producer. This is the **`file://` finding again**: an
artefact that is formally correct and that the recipient's first move fails on. Phase 7 answered
that by shipping `serve.py`; the answer here is the same shape.

- **`units.gpkg`**, the same unit table, written by default beside the GeoParquet and never instead
  of it. GeoPackage is SQLite, in GDAL's core, and stores its CRS in a table rather than in file
  metadata a driver must know how to parse. Measured at four extents on the 116 491-unit Bogotá run
  before being made the default: 0.22 s / 5.6 MB at 10 000 units to **1.83 s / 67.3 MB at 116 491,
  exponent 0.86** — sublinear, 0.3% of a ten-minute run. `output.gis_format = "none"` skips it.
  Units only: the `layers/` context geometry is the site's basemap material and `buildings.parquet`
  alone is 477 MB on that run.
- **`manifest.crs` and `crs_wkt`** — a real gap, and the more interesting half. The CRS is *derived
  from the extent*, so `config` cannot carry it and never did. A run directory could not state its
  own CRS without a GeoParquet reader, which is precisely the tool the reader who needs telling does
  not have. The manifest is the run's self-description and this was missing from it.
- **`lczkit export <run_dir>`** converts a run already on disk: it reads only what the run wrote,
  adds `units.gpkg`, and backfills the two manifest fields. It edits the manifest **as JSON, not
  through `RunManifest`** — revalidating an archived run against today's model would fill defaults
  for fields that run never had and make it look like it came from code that did not produce it.
  Idempotent, and the parquet is asserted byte-identical afterwards.

All ten runs on disk were converted, ~418 MB added to a 2.1 GB tree. No measurement moved: no
parameter is recomputed, no geometry is transformed, and the archival GeoParquet is untouched.

---

### Phase 20 — the API reference — CONCLUDED

**Built on explicit request, and it is item 9's first half arriving early** — "Cleanup — docs,
release". Not a diagnostic phase: it opened no question and moved no measurement. It arrived as a
`.github/workflows/docs.yml` added from outside, running `uv sync --group docs` and
`mkdocs gh-deploy --force` against a repository that had neither a `docs` group nor an
`mkdocs.yml`. Shipped in `1e4306a`.

**The docstring gap was narrow and shaped, which is the finding.** Module docstrings were already
80/80 and public classes 93/93; the whole gap was 68 `ruff --select D` violations across 20 files,
and almost all of it was one pattern:

> **Protocol-implementation members and trivial accessors are undocumented; everything else is
> documented.** `GridUnits.generate`, `EnclosureUnits.generate`, `PatchUnits.generate`, both
> `HeightSource.fill`s, all three `HeightProductSource.ensure`s — the single member that *is* the
> implementation, blank in each case, because the contract is stated once on the Protocol.

**Docstring inheritance does not rescue this, and that was checked rather than assumed.** The
implementations satisfy the Protocols *structurally* and subclass nothing, so griffe has no base
to inherit from and a generated page would have shown those methods blank. Written out properly,
each saying what its implementation does differently rather than restating the interface.

Also 13 `__init__` docstrings, 19 summary-line reflows (clause-preserving — the remainder of a
wrapped summary moves into the body, nothing is rewritten), and two stubs that something *reads*:
`cli.main_callback`, which Typer renders as `lczkit --help` output, and `Normalisation.as_dict`,
which named its consumer instead of its return.

**`D` in CI, with the convention chosen on measurement.** `convention = "google"` takes `src/`
from 137 to 68 by disabling D401 non-imperative-mood, which fires 67 times against a codebase that
deliberately opens with a claim about what a thing is rather than with a verb. It also resolves
D203/D211 and D212/D213 without an explicit ignore list, and it is what mkdocstrings-python
assumes, so linter and renderer read the docstrings the same way. Measured alternatives: `numpy`
leaves 123, `pep257` leaves 136. `tests/**` and `scripts/**` are exempt — tests alone carry 1 146
violations, saying in a docstring what 785 prose-sentence test names already say.

The config was **checked to discriminate rather than assumed to**: `src/lczkit/probe.py` flags
D103; `tests/probe.py` and `scripts/probe.py` do not. So does `src/lczkit/_probe.py` — ruff treats
an underscore-prefixed module as private, which is why `cli/_options.py` and `cli/_render.py` are
outside the enforced surface and the coverage test exempts them by the same rule.

**`docs_dir` is `docs_src/`, not `docs/`, and the reason is containment.** `docs/` is this
project's internal record and is **205 MB on disk** — 27 gitignored PDFs plus
`docs/references/datasets/`. A CI checkout sees only the 23 committed files, but a local
`mkdocs gh-deploy` would push every one of those PDFs to GitHub Pages. **A `docs_dir` that cannot
contain a PDF is a stronger guarantee than an `exclude_docs` rule that has to stay correct**, and
the site is API-reference-only, so it shares nothing with that directory anyway.

The reference is organised **per module because it has to be**: `lczkit/__init__.py` is three
lines with no re-exports, and `cleaning`, `heights`, `landcover` and `sources` have no `__all__`
at all, so `::: lczkit` renders an empty page. Package docstrings open each page with
`members: []`, so a re-exported symbol is documented once, under the module that defines it.

`tests/test_docs_api_coverage.py` is the guard, in four parts — every public module reaches a
page, every page names a module that exists, nothing in `docs_dir` is gitignored, every page is in
the nav. **It found a real gap on its first run**: eight subpackage docstrings no page carried.

Site builds `--strict` clean: 15 pages, 708 documented symbols, 7.4 MB, zero PDFs. Attribute
docstrings render, which matters more here than usual — **367 of them carry the majority of this
package's prose, 119 in `config.py` alone.**

**Two workflow defects, and a third that had been hiding behind one:**

- **`ci.yml` triggered on `main`, which does not exist** — neither locally nor on the remote. The
  *remote* is named `main` and its only branch is `master`, which is what makes it easy to
  misread. **CI had therefore never fired at all, since Phase 0** — corrected in Phase 24
  from the Actions API: the workflow has 4 runs in the repository's history, all `push`,
  all after this fix, and **this repository has never had a pull request**. "Fired only on
  pull requests" was an inference from the trigger, and the stronger true statement was one
  API call away.
- **`ruff format --check .` was already failing**, on two Python files and on
  `docs/references/tables/osm_lcz_tag_mapping.md` — ruff 0.16 formats Python fences *inside
  Markdown*. Unseen for exactly the reason above. The Python files are formatted; the table is
  excluded from the formatter, because its value is that it is a faithful transcription.
- **`docs.yml` syncs `--only-group docs`, on both steps.** mkdocstrings reads the source
  statically through griffe and never imports `lczkit`, so the build needs neither the package nor
  duckdb / geopandas / rasterio / exactextract / neatnet / earthengine-api — verified by loading
  `lczkit.units.grid` through griffe with `search_paths=["src"]` alone. The flag is repeated on
  `uv run` deliberately: **`uv run` re-syncs before running**, and without it that re-sync
  reinstalls everything the sync step exists to skip.

Dependencies added to a new `docs` group: **mkdocs (BSD-2-Clause), mkdocs-material (MIT),
mkdocstrings[python] (ISC) and mkdocs-jupyter (Apache-2.0)**. All permissive, none GPL/LGPL.
`mkdocs-jupyter` was requested and is wired, and there are **no notebooks in the repository**, so
it currently renders nothing — recorded rather than dropped silently.

**Not done, and left for item 9.** The README is untouched: 733 lines, 13 relative links into
`docs/` that the site does not publish, and a `## Status` section that is 64% of the file.
`docs_src/index.md` is a purpose-built landing page instead, and the README stays the repository's
front door. Splitting it is release work, not documentation-build work.

---

### Phase 21 — base maps a reader can choose — CONCLUDED

**Built on explicit request, and it strikes a committed anti-pattern rather than working around
it.** The request was for more grounds — OSM, satellite, MapTiler hybrid and topo — behind a
dropdown. "Don't use a basemap requiring an API key" had been in the anti-pattern list since Phase
0; it is struck above, in place, per the Canonical spec rule, and the guarantee it was protecting is
unchanged: **the default build still names no remote host anywhere, and the test that says so is
untouched.** Not a diagnostic phase; it moved no measurement.

**No Google tiles, and the refusal is the licensing decision this package's first rule implies.**
`mt{0-3}.google.com/vt` is undocumented and using it outside a Google Maps API breaks Google's
terms, so it can record no licence — and every entry in the provider table records one, which is
what the table is for. Satellite comes from **Esri World Imagery** (no key, attribution-required)
and **MapTiler**. A test asserts every provider carries a licence and an attribution, so the next
person to add a ground has to answer the same question.

**The measurement that set three constants, taken before they were written.** One request per
template, since a wrong map ID 404s per tile rather than raising:

| provider | tiles | max zoom, and why |
|---|---|---|
| `esri-satellite` | 256 px, `{z}/{y}/{x}` | **19** — z21 and z22 return an identical 2 521-byte placeholder |
| `maptiler-hybrid` | 256 px | **20** — imagery; z21+ are served but are server-side upsampling |
| `maptiler-topo` | 256 px | **22** — rendered from vector data, so every level is a real render |

**Esri's axis order was settled by reading pixels, because both orderings return 200.** It is the
one URL here that is not `{z}/{x}/{y}`, and transposing it returns valid imagery of the wrong place
— which renders cleanly, raises nothing, and defeats a status-code check. At z5 the shipped
`{z}/{y}/{x}` gives mean RGB (1, 53, 73) mid-Pacific and (238, 208, 158) over the Sahara — ocean and
sand; the transposition puts the Sahara at (1, 45, 66), in the sea. Pinned by its own test.

**One source and one layer per provider, which is forced rather than chosen.** `maxzoom` and
`tileSize` live on a MapLibre source and differ per provider, so several grounds cannot share one
source whose tiles are swapped at runtime. The rasters therefore form a contiguous hidden block
directly above the background. `test_the_raster_basemap_is_hidden_until_a_reader_asks_for_it`
pinned `index == 1`; it now pins the block, which is the same guarantee — nothing paints over the
classification — generalised rather than relaxed.

**The key is confined by a field flag, not by a promise.** MapLibre fetches tiles from the browser,
so a MapTiler key must be in `style.json` in plain text; the question was how many files it reaches.
The manifest is `settings.model_dump()` verbatim and `build_site` copies it into the site, so an
ordinary config field would have published it three times. `VizConfig.maptiler_key` is
`exclude=True`, and a test greps every file a build wrote. **That bounds the exposure and does not
remove it** — the built directory still carries the key, and `.env.example`, the site's own
`README.md` and the CLI's `terms` output all say so at the moment it matters.

- **A trailing space in `.env`, found by the first request failing.** `MAPTILER_API_KEY` had one;
  the URL was rejected before it reached MapTiler. Invisible in an editor, and it would otherwise
  have reached the tile URL and made every request 403 for no readable reason. `maptiler_key()`
  strips, and a test passes `"a-key  "`.
- **`Settings.load` could not be the only reader.** `lczkit site build` takes a run directory and
  must keep working without `DATA_DIR`, which `Settings.load` raises without. `config.maptiler_key()`
  is the single definition both call.
- **An excluded field cannot round-trip, and `test_json_round_trip` asserted it would.** It passed
  only because the variable happens not to be exported in a shell; exporting it fails the test with
  a diff that names no cause. It now clears the variable and says why, beside a test that states
  the non-round-trip as the intended behaviour.

**Two seams that were guessing at each other, both now checked against the producer.** `app.js` read
four `raster_*` scalars that no longer exist, and its tile-failure handler matched the source id
`"basemap-raster"` as a literal. The replacement checks **membership in the ids the style declared**
rather than their shared prefix — the run's own layers are `basemap-*` too, and collecting a set by
prefix once already put the remote raster into the choice that exists to avoid the network. The new
test builds a style and asserts `app.js` mentions every key it emits, computed from the producer so
a renamed key cannot pass by being forgotten in the test as well.

**The two `--basemap` implementations were one flag with two meanings**, found by needing to change
both: `run` checked `PROVIDERS` directly, `site build` round-tripped the config, and only `site
build` accepted `none` — so the same argument was an error in one command and an instruction in the
other. Both go through `cli._options.parse_basemaps` now, which is repeatable, comma-separated,
`all`, and `none`. `None` and `[]` stay distinguishable: not passing the flag leaves what the run
recorded alone, `--basemap none` clears it, and a flag that could not express the first would make
an online ground unremovable on rebuild.

**The run's own linework became an overlay rather than a competing choice**, on the user's call: the
dropdown picks the ground, a checkbox draws the run's water and streets over it. Satellite tells a
reader what is there, the run's linework tells them what the classification was computed from, and
the old exclusive radios could not show both.

#### The default was flipped afterwards, and the guarantee narrowed with it

**Shipped opt-in first, and that was wrong in use.** Every ground was off unless `--basemap` named
one, which preserved the offline property exactly — and meant a plain `lczkit site build` produced
no picker at all. Reported from outside as "the dropdown is not available", on a site built the
ordinary way. **A feature reachable only through a flag nobody was told about is not shipped**, and
the opt-in default had been chosen to protect a guarantee rather than to serve a reader.

The ruling, on the user's call: **the command line offers the keyless grounds by default; the
library does not.**

| | default | reaches a tile host |
|---|---|---|
| `VizConfig()` / `build_site(run_dir)` | none | no — test unchanged |
| `lczkit run`, `lczkit site build` | OSM, Carto ×2, Esri | yes |
| `--basemap none` | none | no |

**The line is drawn at `requires_key`, and derived rather than listed.** `DEFAULT_BASEMAP_KEYS` is
`tuple(k for k, p in PROVIDERS.items() if not p.requires_key)`, so a keyless ground added later
joins the defaults by being keyless and a keyed one **cannot join by being forgotten** — which is
the property that matters, since a keyed ground publishes an API key into every site built with it.
A test asserts no default provider requires a key.

**What was given up, stated plainly rather than argued away.** A site built by the ordinary command
now names four tile hosts in its `style.json`, where before it named none. What is *not* given up:
the site still opens and works offline — the grounds are hidden until chosen and the run's own
linework is still the ground that draws without a network — and no key is published unless asked
for. The no-external-reference test is untouched and still passes, because it pins the library
default, which is now what that guarantee means. **Anyone building an archival site must pass
`--basemap none`,** and that is a real regression in defaults for archival use, accepted knowingly.

**Rebuilding does not redecide.** A run that recorded grounds keeps them; the default fills in only
where a run recorded none, which is the case that made this visible — every site on disk predated
the change and none of them could show a picker until it was rebuilt.

No dependency was added. The deprecated `online_basemap` singular is kept and folded into
`basemap_keys`: pydantic ignores unknown fields, so dropping it would make an archived run's
configured ground disappear on rebuild with nothing raised.

---

### Phase 22 — a notebook that runs, and a map inside the page — CONCLUDED

**Built on explicit request, and it is Phase 20's `mkdocs-jupyter` finally rendering something.**
That phase wired the plugin against a repository holding zero `.ipynb` files and recorded the fact
rather than dropping the dependency, "so a future notebook has somewhere to go". Not a diagnostic
phase — it opened no question and moved no measurement. Its value is four defects, three of which
exist only once a notebook and a documentation build are in the picture.

**`OvertureSource` could not be constructed inside a Jupyter kernel, and had not been since Phase 1.**
`__init__` ran `SET s3_region = '…'; SET enable_progress_bar = false;`, and DuckDB reinitialises its
display when that setting is *assigned* — so in a kernel without `ipywidgets` it raises
`InvalidInputException: required package 'ipywidgets' is missing`, for an assignment whose whole
purpose is to draw nothing. Every code path that reads Overture went with it.

Measured on duckdb 1.5.5, because the obvious workarounds do not work either:

| form | result |
|---|---|
| `SET enable_progress_bar = false` | raises — what shipped |
| `SET enable_progress_bar_print = false` first, then the above | raises |
| `duckdb.connect(config={"enable_progress_bar": …})` | raises differently — "cannot be set as a global option" |
| **`PRAGMA disable_progress_bar`** | **succeeds, and does not touch the display** |

Fixed with the `PRAGMA`, and with failure tolerated: the right response to being unable to switch
off a progress bar is to carry on without one. The guard is a **source assertion**, because the
defect is invisible everywhere a test normally runs — under pytest there is no kernel, DuckDB draws
nothing, and the assignment succeeds. It reads the module's string literals through `ast` rather
than its lines, so the docstring that must name the forbidden form in order to explain it is not
itself a finding; verified to fail when the bad form is restored.

> **The probe that diagnosed it first returned the opposite answer.** Run through
> `jupytext --execute` with no kernel named, it reported `ipywidgets PRESENT` and every form
> succeeding — because jupytext had silently picked a kernel from *another environment*. A
> notebook's `kernelspec` decides which interpreter answers, and a probe that does not pin it is
> measuring an unknown machine. Same shape as the `.env`-dependent test Phase 21 caught:
> **agreeing with your machine is not passing.**

**Two more defects, both found by building rather than by reasoning.** A run's map site is copied
into `docs_src/demo/` whole, and two of its files break `mkdocs build --strict`:

- **`serve.py` is matched by mkdocs-jupyter's default `include`** (`["*.py", "*.ipynb", "*.md"]`),
  so the plugin treated it as a notebook, rendered it as a page and *relocated* it to
  `demo/<site>/serve/serve.py`. Narrowed to `include: ["*.ipynb"]`.
- **`README.md` collides with the site's own `index.html`** — mkdocs drops it and warns, which
  `strict: true` turns into a failed build.

Both are correct in a run directory, which is a copy someone downloads and opens offline; neither
applies to one already being served. `scripts/publish_demo_sites.py` strips them from the published
copy only, and a test pins that. `not_in_nav: demo/*/**` covers the vendored `LICENSES.md`.

**`.gitignore`'s `site/` matches at any depth.** Copying `<run_dir>/site/` across under its own name
would have produced a directory git silently ignores and `gh-deploy` never publishes — a map simply
absent, with nothing raising. Destinations are `bogota-grid/` and `bogota-patch/`; Phase 20's
existing `docs_src` gitignore guard is what would have caught it.

**GitHub Pages serves PMTiles, measured rather than assumed** — `HTTP 206`, `accept-ranges: bytes`,
`access-control-allow-origin: *`. Phase 7 established that `file://` cannot work because the Fetch
standard leaves `file:` unhandled; a Range-honouring host is what the bundled `serve.py` provides
locally, and Pages is one. Every reference in a built site is relative (`fetch("style.json")`,
`pmtiles://./tiles/…`), so a site drops into any subdirectory and works in an `<iframe>` unmodified.

**`mkdocs serve` does not honour Range, so the embedded maps are blank under it — and this is the
`file://` finding for a third time.** Measured: `200 OK`, whole body, no `Accept-Ranges`. That is
not a soft degradation, because `pmtiles.js` *raises* rather than guessing — "Server returned no
content-length header or content-length exceeding request. Check that your storage backend supports
HTTP Byte Serving." So the published page is correct and the preview a contributor reaches for is
the thing that fails, which is exactly the shape of the `file://` and QGIS-Parquet findings.

The answer was already in the package: `lczkit.viz.serve` is a generic Range-capable static server,
and pointing it at the built docs site returns `206` with the right `Content-Range`. The notebook
says so on the page, next to the maps, because the reader who needs telling is the one looking at
two blank frames:

```bash
mkdocs build && python -c "from lczkit.viz import serve; serve('site')"
```

**mkdocs' Markdown extensions do not reach a notebook's markdown cells.** `!!! note` shipped as
literal text in the built page, because nbconvert renders those cells with its own Markdown
renderer before mkdocs sees the result — the same seam that makes `execute: false` safe also means
`admonition`, `pymdownx.*` and mkdocs' link rewriting are all unavailable inside a cell. Rewritten
as a blockquote. This is why the page's outgoing link is written as the built URL `../../api/`
rather than `../api/index.md`: the `.md` form would ship unrewritten and 404.

#### The demonstration

`docs_src/demo/bogota.ipynb`, authored as a jupytext percent script at `scripts/notebooks/bogota.py`
and committed with its outputs. **`execute: false` is set explicitly because it is load-bearing**:
the docs workflow runs `uv sync --only-group docs`, so the build environment has neither lczkit nor
the geo stack nor a `DATA_DIR`, and could not execute it. A test asserts the two files have not
diverged — the same "two copies of one thing" shape as the twin `CLEANING` constants and the twin
city registries, fixed the same way.

**Bogotá, and it is not a registry city.** So2Sat covers it with **8 patches, all LCZ 7**, against
the 500-patch/4-class screen all 28 registry cities pass — so `lczkit run --city bogota` does not
exist and the notebook supplies GUPPD's `SMOD_ID 30_3370` extent directly. **Bogotá was deliberately
not added to `CITIES`**: a 29th city changes the population every stored figure is measured over,
against the standing rule to intersect city sets before differencing records.

The window is `densest_window(WUDAPT Bogotá, side_km=5.0)` — the helper the multi-city sweep uses,
pointed at the reference so the window lands where the evidence is rather than in the middle of a
bounding box. Measured alternatives: 4 km → 1 681 cells / 15 polygons, 6 km → 3 721 / 18.

| | grid arm | patch arm |
|---|---:|---:|
| units | 2 601 | **251** |
| median unit area | 1.00 ha | **8.61 ha** (p10 5.41, p90 15.67) |
| merge | — | 2 882 seeds → 251, 2 631 merges, 0 isolates, 0 blocked |
| wall time | 2.7 min | 2.6 min |

The patch median lands inside WUDAPT's 2.2–52 ha band and beside So2Sat's 10.24 ha patch, from a
50 000 m² floor — `min_area_m2` is a floor and not a target, and the overshoot is the mechanism.

**The window reproduces the whole city's founding-premise figure.** Of 114 945 buildings, Overture
answers for **602 — 0.52%** (570 `num_floors`, 32 `height`), WSF-3D for 114 177 (99.33%),
GHS-BUILT-H for 165, one unresolved. The full 1 169 km² run on disk reads 0.50% / 97.8%. Bogotá is
close to the worst case for the constraint this package exists to report, which is why it is the
example.

**No accuracy claim is made, and none is available.** The notebook calls `agreement()` against
WUDAPT — 17 polygons inside the window, from two submissions — because `run_pipeline` deliberately
never runs validation, and it says on the page that this demonstrates the instrument rather than
producing a result. **No ceiling is reported, because Bogotá's 8 single-class So2Sat patches cannot
produce one.** Everywhere else this project reports agreement it reports the ceiling beside it;
here there is nothing honest to put there, and saying so is the point. The polygons covering this
window are **CC BY-NC-SA 4.0** — non-commercial, printed from the data rather than asserted.

Dependency added: **matplotlib (PSF-style matplotlib licence, permissive — not GPL/LGPL)**, to the
**dev** group, since CI's docs build is `--only-group docs` and never executes the notebook. This
narrows the "no plotting helpers" scope bullet again; patched above rather than departed from
silently, as the CLI was in Phase 15 and `mkdocs-jupyter` in Phase 20.

`scripts/notebooks/**` is exempt from `E402`: a jupytext percent script is a document whose cell
order is semantic, and its first cell must install warning filters *before* the imports they apply
to — otherwise a `TqdmWarning` about the same missing `ipywidgets` is the first thing on the page.

---

### Phase 23 — one overlay, any city, and a run that says where it was — CONCLUDED

**Built on explicit request: "clean repeated code and improve on what's already written", against
the package's stated purpose — a decent LCZ map for any city in the world, quickly, from open
data.** Not a diagnostic phase. It opened no scientific question and **moved no measurement**: the
one change that could have moved a number is pinned to 1e-9 against the values recorded before it.

Three things were out of line with that purpose, and the second is the one nobody had noticed.

#### The locator was gated on validation data

`--city` resolved **28 So2Sat cities** and read `input/So2Sat-LCZ42/` to do it. For every other
city on earth the interface was "find four numbers yourself". Meanwhile
`input/NASA/GUPPD/guppd_bounds.csv` — **5 558 urban regions, 173 countries, name, ISO, country and
bbox, 564 KB** — had been on disk unread since Phase 0, named in this file's layout diagram and in
no `.py` file. The same shape as WUDAPT sitting unread for sixteen phases and the height cascade
specified in Phase 3 and built in Phase 10: a capability the spec assumes and the code does not
have is invisible until something asks for it.

`lczkit.places` reads it; `lczkit cities` searches it; `--city` resolves against it.

**The sizing is why a whole-region run is a sensible default**, and it was measured before the
default was chosen rather than after:

| GUPPD urban region | km² |
|---|---:|
| median | **80** |
| 90th percentile | 412 |
| above 900 km² (Berlin's 9.8-minute benchmark extent) | **239 of 5 558** |
| largest (Jakarta) | 17 661 |

So the ordinary case is minutes. `lczkit cities` prints each region's area and both commands name
`--extent-km` above 900 km², because the area is the only thing in the interface that predicts a
run's wall time.

**Ruling: an ambiguous name is refused, never resolved to the first match.** 149 of the 5 558 names
are shared — two Londons, two Cambridges, two Yorks — and taking the first would run the wrong
continent and record a manifest that looks entirely correct. Nothing downstream of a bbox could
tell. An exact match still outranks a substring one, so `london` means London and not East London;
only a tie between regions of the *same* name asks the caller for `--country`, and the message
lists only the tied candidates.

**Ruling: `--so2sat-window` is a flag, not a fallback.** The GUPPD region and the densest 30 km
So2Sat window of the same city are different ground — Berlin 1 152 km² against 899 — and only the
second makes a run comparable with a recorded agreement figure. A locator that fell back to it, or
silently past it, is how a run comes to look comparable with a published number while covering
something else. Naming a city with no labelled window is an error that says to drop the flag.

#### A run directory could not say what ground it covered

**Checked before anything was built: 0 of the 18 manifests on disk carry an extent, a bbox, a
window or a place name, and no key in any of them mentions one.** The cause is structural, not an
oversight — the extent is an argument to `run_pipeline`, so it is in no `Settings` field and
therefore in none of the `config` block the manifest serialises verbatim.

**This is the Phase 19 CRS gap exactly, still open for the extent**, and the same rule closes it: a
derived property has to be recorded somewhere the derivation is not. It matters more now that
`--city` reaches 5 558 regions rather than 28.

`RunManifest.extent` records the window, its area, and the locator that produced it — `bbox`,
`guppd` (with the `SMOD_ID`, which is unambiguous where the name is not), or `so2sat_window` (with
the registry key and the side length). A trim keeps the locator and records what it was trimmed
from, because a 3 km trial over Cambridge is still a run about Cambridge and a directory of
anonymous rectangles is unreadable.

`lczkit export` backfills it for archived runs from the units' own bounds, tagged
**`kind="recovered"`**. Deliberately a distinct value: a reconstruction is bounded by the units
that were written rather than by the window requested — a grid overhangs its bbox by up to a cell —
and nothing on disk says which city was named.

#### Seventeen overlays to answer questions about two layers

`ucp.industrial` carried three copies of "intersect a layer with the units, measure the pieces, sum
by `unit_id`" and `ucp.semantics` two. Measured on the Hong Kong fixture — 5 449 buildings, 1 754
parcels, 959 cells:

| | overlays | rows pushed through `gpd.overlay` |
|---|---:|---:|
| `semantic_metrics` | 12 | 15 692 |
| `industrial_metrics` | 5 | 5 539 |
| rows actually present | — | **7 203** |

Twelve is one tagged-buildings overlay, one whole-land-use overlay, and **one per configured
semantic group per layer** — so the count grew with the configuration rather than with the city.

`lczkit.units.overlay` is the one definition. `ucp.parameters` intersects each layer once and hands
the pieces to every block, which is the move it already made for `building_area_m2` and for the
same reason. Group selection is now a mask over pieces that exist. **Seventeen overlays to two**,
and the seventeen is measured against the pre-consolidation implementation on the fixture, since
that pattern no longer exists to run.

**The dissolved-coverage path changed implementation, and that is the part worth recording.**
`industrial` reached it through a whole-layer `union_all`; `semantics` through clip-then-dissolve
per unit. The second is the form this file's anti-pattern list requires — the global union is
superlinear *and* raises `GEOSException: side location conflict` over real Overture land use even
after `make_valid`. `industrial` survived only because it ran on a few dozen parcels, and nothing
about the helper's name said so. One definition means it cannot be reused onto a whole layer by
someone who did not read that argument.

**Equality is pinned, not argued.** The union of the clipped pieces inside a unit is the clip of
the global union — equal by construction, and this project's record is full of constructions that
measured differently. `tests/fixtures/ucp/*_evidence.parquet` holds the values **recorded from the
implementation as it stood before the rewrite**, on all three fixtures, and
`test_ucp_evidence_equivalence.py` asserts the shipped code reproduces every column to **1e-9**.
Regenerating them is a separate script and deliberately not a `--update` flag: a pin a failing test
can refresh is not a pin.

**Honest sizing, stated because the headline invites overreading:** the two blocks are 1.3 s of a
90 s fixture run. `clean_vectors` dominates and is untouched. The saving scales with city size and
with the number of configured semantic groups, not with the fixture.

`scripts/ucp_overlay_scaling.py` measures both call patterns at four extents, per the standing
anti-pattern — "fewer, larger overlays" is exactly the shape of change that can be faster on a
fixture and steeper at metropolitan extent.

**Measured at four concentric Berlin extents, and the exponent is the answer that mattered.** The
two arms are `shared` (what `ucp.parameters` does) and `separate` (what a direct caller gets — each
block intersecting the layers it needs, five overlays). **`separate` is not the pre-consolidation
code**: that pattern no longer exists to run, because group selection is now a mask over pieces, so
the seventeen is measured on the fixture against the old implementation and the table below
measures the two live paths.

| km² | units | buildings | parcels | separate | shared | | overlay rows, separate → shared |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 16 | 1 695 | 12 361 | 2 888 | 3.44 s | 1.89 s | 1.82× | 42 859 → 15 249 |
| 64 | 6 611 | 43 315 | 10 203 | 11.46 s | 6.51 s | 1.76× | 150 351 → 53 518 |
| 144 | 14 751 | 99 587 | 20 472 | 24.34 s | 13.77 s | 1.77× | 339 705 → 120 059 |
| 256 | 26 106 | 182 466 | 30 648 | 40.32 s | 23.48 s | 1.72× | 608 694 → 213 114 |

**Exponent in extent: 0.890 separate against 0.908 shared.** Both sublinear, and the same to within
two parts in a hundred — so concentrating the work into two large intersections does *not* make the
stage steeper, which is the failure mode this measurement exists to rule out. The speed-up is flat
across a sixteen-fold range of extent rather than decaying, which is what a constant-factor saving
looks like. Re-runnable from `scripts/ucp_overlay_scaling.py`, which writes the full record as
JSON into its own run directory; the numbers above are the whole of it.

#### Duplication removed elsewhere

- **The configuration constants.** `scripts/berlin_metropolitan.CLEANING`/`RELEASE` and
  `scripts/unit_scale_experiment.AREAL_CONFIDENCE`/`HEIGHTS` were copies of what `lczkit.presets`
  holds, guarded by two tests asserting the copies still matched. They now derive from the preset —
  copied rather than aliased, since several drivers build variants by mutation and a mutation
  reaching the preset would reconfigure every later run in the process. Every script keeps its name
  and entry point, so the nine sibling importers are untouched. The guard tests lost their subject
  and were replaced: one pins the eight metropolitan values as literals, which is what the
  comparison was standing in for; the other pins that the derivation is still in place.
  **`scripts/unit_scale_experiment.CLEANING` stays**, because it is a genuinely different measured
  configuration for the 9 km² arms rather than a second copy of one.
- **Six copies of `load_script`** across the test suite, and **seven copies of two
  `CleaningConfig`s** — the fast-path `SMALL_CLEANING` (three files) and the fixture-scale
  `FIXTURE_CLEANING` (four), which stay two constants because their values differ deliberately and
  merging them would change what six tests exercise while looking like tidying.

#### Three defects, each found by a check rather than by reading

- **The two locators collided on a name, and the worse half was silent.** `lczkit cities` marks
  the rows `--so2sat-window` works for, and matching on the name alone marked London, Ontario, Los
  Ángeles, Chile and Santiago, Philippines — none of which carry So2Sat labels. Worse:
  `--city london --country CAN --so2sat-window` resolved the registry by name and **ignored
  `--country`**, so it would have run London, UK's window while the caller was disambiguating away
  from it. `City` gained an `iso`; the marker keys on (name, country) and the flag now checks the
  country rather than ignoring it. Found by asking how many GUPPD rows the marker would light up —
  31, for 28 cities.
- **`unit_pieces` called `rename_geometry` unconditionally**, and geopandas refuses to rename a
  column to the name it already has — so the shared helper raised for every ordinary layer in the
  package. Found by the equivalence test on its first run, which is what that test is for.
- **`tests/test_docs_api_coverage.py` caught all five new modules** the first time it ran, exactly
  as it caught eight subpackages on its first run in Phase 20. A coverage guard that has now fired
  twice on real gaps is worth more than the page it protects.

**And one found by writing a sentence about the code and then checking it.** The README draft said
a run without tippecanoe "completes and reports the site as skipped rather than failing". It did
not: the error propagated out of `run_pipeline`, the command line turned it into an exit code, and
**the line naming the run directory was never printed** — so a ten-minute city whose only problem
was an absent tool reported as a run that produced nothing, when every file but the site was
already on disk. `PipelineResult.site`'s own docstring had claimed the skip behaviour since Phase
15. The behaviour was changed to match the docstring rather than the other way round: the site is
the last stage, `site_skipped` records why there is none, and the CLI names the run directory and
`lczkit site build` before exiting non-zero.

#### The README, and what it was hiding

750 lines, of which `## Status` was 650 — a phase-by-phase research log as the front door of a
package whose purpose is to make a map. Moved **verbatim** to `notes/status.md` (asserted verbatim,
with only the `notes/experiments/` links rebased for the file's new depth), and the README rewritten
as: what it is, the three locators and what each covers, what a run writes, what it will *not* tell
you, **and a section saying not to use the bundled labels as a quality gate over your own city** —
they reach 51 cities at most and two expert label sets agree at a median 79.7%, so an agreement
figure without that context is not interpretable. This is the README half of the release item; the docs half
landed as Phase 20 and the notebook half as Phase 22.

---

### Phase 24 — the argument, not the environment — CONCLUDED

**Opened by CI, which had just started running for the first time.** Not a diagnostic phase; it
moved no measurement. Phase 20 fixed a workflow trigger that named a branch this repository does
not have, and the first thing the newly-live gate reported was a defect that had been sitting in
`lczkit run` since Phase 15.

**The defect.** `lczkit run --bbox 1,2,3` on a machine with no `DATA_DIR` answered *"DATA_DIR is
not set"*. `_load_settings` ran before `parse_bbox` and `parse_basemaps`, so every argument error
that needs nothing on disk arrived as a config error — blaming the environment for a typo, at the
one moment the reader has configured neither and cannot tell which is really wrong. `--basemap`
and `--extent-km` misreported the same way.

`site build` has always had the right shape, so the fix is `run` catching up to a sibling command
rather than a new idea. The city locators stay behind the environment deliberately: they read
`guppd_bounds.csv` and the So2Sat archive through `settings.source_dir`, so there `DATA_DIR`
genuinely is the blocker and saying so is correct.

**Why 987 local passes proved less than they looked.**
`test_a_malformed_bbox_is_refused_with_the_reason` pins exactly the right behaviour in six
parametrisations, and **all six passed locally and failed in CI**. `_clean_data_dir_env` deletes
`DATA_DIR` from the environment and stops; `Settings.load` then calls `load_dotenv()`, whose
upward search starts at `src/lczkit/config.py` and finds the repository's own `.env`, putting it
straight back. The fixture guarded the variable and not the file.

The answer was already in the repository and had been applied once —
`test_a_missing_data_dir_is_a_message_and_not_a_traceback` neutralised `load_dotenv` inline, with
a docstring explaining precisely this mechanism — and was never made the default. It is autouse
now.

**Scope, measured rather than assumed.** A full suite run in a `.env`-free extracted tree, which
is what CI sees: **6 failed, 979 passed, 2 skipped**. The six are the bbox parametrisations and
nothing else, so closing the leak has no collateral. The two skips are the test that reads
`REPO/.env` off disk, which the extracted tree does not have; the working tree still runs it, at
**988 passed**.

**Pre-existing, checked rather than asserted.** The same six fail against an extracted `38bce20`,
so this is not a regression from the Phase 23 commits.

**The Actions API also corrected a committed claim.** Phase 20 recorded that CI "had only ever
fired on pull requests"; the history says **4 runs ever, all `push`, all after that fix, all
failed, and zero pull requests ever opened**. CI had never fired at all, and this repository has
never had a green run. The stronger true statement was one API call from the one that was
inferred — the same shape as attributing a cost by adjacency in a call graph.

---

---

### Phase 25 — the dimensions the metric was missing — CONCLUDED

**Opened by a scientific review on request, not by a defect report**, and it turned into the first
diagnostic phase since the stop rule because the review measured something the record does not
contain. Two tiers, agreed in advance: instruments first, then the metric — the Phase 14 ordering
and deliberately not the Phase 9→10 one, where the intervention invalidated the evidence that had
ordered the levers.

Everything below was measured on this package's own runs on disk — Berlin 91 242 cells, Bogotá
116 491, Nairobi 68 353, Istanbul 455 538 across three unit strategies on one extent — and on the
shipped prototype table. **One obvious fix was tested and refuted**, and is recorded as such.

#### The finding: LCZ 7 and LCZ 8 are inverted on building size

| built cells, BSF > 0.05 | LCZ 7 median footprint | LCZ 8 median footprint | ratio 8/7 |
|---|---:|---:|---:|
| Berlin | 13 419 m² | 767 m² | 0.06 |
| Istanbul | 13 172 m² | 462 m² | 0.04 |
| Bogotá | 6 756 m² | 55 m² | **0.01** |
| Nairobi | 3 749 m² | 93 m² | 0.02 |

**LCZ 8 is _large low-rise_ — warehouses, malls, hangars. LCZ 7 is _lightweight low-rise_ — the
informal-settlement class.** The map assigns "large low-rise" to cells of 55–93 m² buildings and
"lightweight low-rise" to cells of 7 000–13 000 m² sheds, in every city measured. **This needs no
external reference to call wrong: it is internally contradictory.**

The mechanism is structural, not tuning. A big flat warehouse has a high building surface fraction
and a low height, which is LCZ 7's box on two of three weighted dimensions; a dense informal
settlement has moderate BSF and — because Overture's network does not contain its alleys — a low
measured H/W, which is LCZ 8's box. **Neither box mentions how big a building is**, and
`mean_building_area_m2` has been computed since Phase 5 and has never been a metric dimension.
Phase 14 found the omission in the metric's structure; this measures what it costs.

It also predicts, from the prototype table alone, **Phase 6.7's LCZ 8 at 0.0% (n=224)** and
**Phase 13's LCZ 7 at 8.2% in range** — the latter attributed at the time to Overture coverage of
informal settlements, which is at most half of it.

#### Six further measurements

**A height error moves 53% of the metric, not 35%.** `Hr` carries weight 6 of 17 *and* is
`momepy.street_profile`'s numerator for `aspect_ratio` (weight 3). Every error budget this project
has written treats them as independent dimensions. They share an input.

**The adopted areal tiers compress within-unit height variance**, which is the Phase 10 mechanism
running backwards. Cells with BSF > 0.05 and ≥ 3 buildings, by dominant source:

| source | city | median `h_std` | median CV | constant units |
|---|---|---:|---:|---:|
| Overture `height` | Berlin | 1.52 m | **0.266** | 0.1% |
| WSF-3D | Nairobi | 0.88 m | **0.192** | 1.3% |
| GHS-BUILT-H | Bogotá | 0.36 m | **0.112** | **23.6%** |

Phase 10 rejected Open Buildings 2.5D for spread of 0.441 against reality's 0.195. What shipped has
too *little*, and `Hr` is a geometric mean, so compression biases it upward.

**LCZ 7 is unreachable by arithmetic, not only by coverage.** Assigned to 0.1% of Nairobi's and
0.3% of Bogotá's built cells. Its box wants H/W 1–2 *with* `Hr` 2–4 m — canyon widths of **1–4 m**,
which neither a 100 m cell nor Overture's street network contains. Per-dimension satisfaction on
built cells carrying all three parameters: H/W is met by 1.4–2.2% for LCZ 7, 3.2–6.9% for LCZ 2 and
3, against 40.2–70.0% for LCZ 8.

> **Tested and refuted, recorded so it is not retried.** The network-free canyon ratio
> `H/W = λf/(1−λp)` with `λf = λp·Hr/√A_bldg` gives Berlin **0.14** and Istanbul **0.27** against
> momepy's 0.35 and 0.53 — *worse*. On the densest decile it is better (Bogotá 0.35 → 1.24), so the
> relation is not wrong; the whole-sample deficit is in `Hr`, not in the width. The obvious fix does
> not work as a straight substitution.

**The metric's geometric prior is uneven and was unreported.** The built boxes are essentially
disjoint on the three weighted dimensions — only 3~7 overlap, **which is the opposite of the
intuition and was checked rather than assumed**. But 86.8% of the plausible cube lies outside every
box, so nearly every label is set by the normalisation, and the nearest-box partition gives LCZ 2
**38.8%** of the reachable space against LCZ 8's **3.4%**.

**The confusion axes fall out of the box geometry alone.** Dropping `Hr` ties {2,3}, {2,7}, {3,7}
and {5,6} — the height axis exactly; dropping `aspect_ratio` ties {3,8} and {6,8}. No city required.

**The unit strategies are complementary and the record treats them as rivals.** Istanbul, one
extent: `aspect_ratio` null on **10.8%** of built grid cells against **0.9%** of enclosures, and on
the densest decile the enclosures put **82.2%** of cells inside LCZ 2's published H/W band against
the grid's 70.2%. An enclosure is a block and not an LCZ patch — rejected as a classification unit
three times, correctly — and it is still the better thing to *measure* a canyon on.

**`patch_max_area_m2` was a merge guard wearing a ceiling's name.** It refused to *combine* two
seeds into something oversized and had no way to divide a seed that already exceeded it. Istanbul:
**807 patches over the 50 ha setting holding 72.7% of the extent**, largest 1 072.7 km² (23.6% of
the extent), and one 98 km² unit holding **1 310 buildings** at a uniqueness of 0.12.

#### What shipped

**Tier A — six instruments, and none of them moves a label.** Verified by re-classifying the three
post-Phase-14 runs on disk: **0 labels moved, bit-identical distances and uniqueness on 195 787
cells.** Berlin's stored run is *not* a valid baseline and that was checked rather than assumed — it
predates Phase 14, so its runner-up can be LCZ 10, which that phase removed from the metric.

- `classification.height_dependent_weight` — the 9-of-17 figure, derived from
  `PropertySpec.reads_building_height` and the active preset rather than written down.
- `height_dispersion` — median `h_std`, median CV and the constant-unit share per tier.
- `classification.indistinguishable_classes` — the tie table, per family and per dropped dimension.
- `classification.geometric_prior` — each class's share of the parameter cube, by Monte Carlo at a
  fixed seed, with the sampling bounds beside it because they set what "the space" means.
- `n_tied_classes` per unit — threshold-free, and the per-cell counterpart of the tie table.
  Deliberately *not* "within a tolerance of the minimum": that is a threshold, and the near-miss
  case is already `uniqueness`.
- `impervious_clipped` per unit — `building + impervious + pervious` is exactly 1.0 by construction
  except where the clip fires, and it fires where vector footprints cover more ground than a 10 m
  product calls built-up. Nullable, because "the clip did not fire" and "nothing was measured" are
  different statements — **which the existing tests caught when the first version answered False**.

**Tier B — four changes, three of them inert by default.**

- **`mean_building_area_m2` is a metric dimension**, tagged `source=LCZKIT`, transcribed from
  `docs/references/tables/lczkit_building_size_ranges.md` and asserted against it cell for cell.
  **Weight 0.0 in every preset including `equal`**, so it changes no label; a swept weight of 6.0
  puts the shed on LCZ 8 and the shack elsewhere, which is the test that says it is worth sweeping.
  Only LCZ 7 and LCZ 8 are constrained — the two classes whose published *name* asserts a size.
- **`UcpConfig.measure_on = "enclosures"`** computes the parameters on street-bounded enclosures
  and transfers them to the target units. Default `"units"`, so no stored figure moves.
- **`ClassificationConfig.modal_filter`** — the minimum mapping unit this package never had, and
  which the LCZ Generator applies. Default off. A functionally assigned label is never smoothed
  away: the industrial rule places a unit on evidence, and its threshold is the only one in the
  package that *has* been swept.
- **Oversized patch seeds are split** before merging, so `max_area_m2` means what its name says.
  A regular grid cut anchored on each seed's bounds — deliberately the dullest thing that works,
  because it needs no building layer and most oversized seeds are unmapped hinterland. Verified to
  preserve area exactly and produce no overlaps.

**The `app.js` route guard fired, which is its fourth catch and the point of it.** Adding
`modal_filter` to `rules.ROUTES` without teaching the front end left a cell that would print its
raw token in the sidebar. That test was written in Phase 15 after the third instance of a consumer
guessing at a producer's enum; it is now the thing that stops the fourth.

**A design error caught by a test I wrote to check the design.** `transfer_parameters` first
delegated its numeric pass to `units.aggregate`, whose docstring I read as excluding nulls from the
weight. It does not: `groupby.sum()` skips the null in the numerator while the denominator is the
*total* overlap area, so a null piece drags the mean toward zero. Harmless where every column is
populated and wrong for the one column the module exists to move — `aspect_ratio` is null exactly
where no street reached a building. The transfer now weights per column over the pieces that
carried a value; `aggregate` is untouched, because its normalisation is what every stored arm-B
projection was computed under.

**Rulings:**

1. **A class whose published *name* asserts a property may be given an lczkit-owned range for it,
   and only then.** `mean_building_area_m2` constrains LCZ 7 and LCZ 8 because "lightweight" and
   "large" are claims about building size; giving LCZ 3 or LCZ 9 a range would invent a claim the
   scheme does not make. The same discipline as the tree/water ranges, applied to a built type for
   the first time.
2. **A dimension whose weight has not been swept ships at weight zero in every preset, `equal`
   included.** `equal` means "uniform over every available dimension", and this is a departure from
   it recorded in its own description rather than left to be discovered. The alternative is an
   invented number reaching a label in the preset people reach for when they want neutrality.
3. **Nothing here has an accuracy claim, and the sweeps are pre-registered.** For
   `mean_building_area_m2`: Nairobi's and Bogotá's densest deciles should move off LCZ 8 toward
   LCZ 3/7 and built-class agreement should rise where LCZ 8 is over-called; a fall anywhere and it
   stays disabled. For `measure_on="enclosures"`: Phase 12 named unit definition the lever at a
   compactness lift of 1.16 against height's 0.86, so **the compactness lift should fall toward
   1.0** — plain enclosures as classification units *raised* it to 2.33, so a rise is a refutation.

**Not built, and recorded rather than dropped.** Frontal area index, z₀ and z_d by Kanda et al.
(2013) — which needs only λp, λf, H_max and σ_H, and `h_std` and BSF already ship — and an LCZ-code
GeoTIFF. **A run currently writes no raster at all**, so W2W (Demuzere et al. 2022) has nothing to
ingest and the stated WRF path does not close. Deferred by scope, not by judgement.

**Also worth the paper's attention: "faster than GeoClimate" is claimed and has never been
measured.** There is no head-to-head anywhere in the repository.

---

### Phase 26 — documentation, not a build log — CONCLUDED

**Built on explicit request: remove the traces of this plan from the documentation, and keep the
language simple.** Not a diagnostic phase. It opened no question and **moved no measurement** — the
one edit that touches numbers rewrites description strings and is applied from the live registry
rather than by hand.

**The size of the leak, measured before anything was changed.** The published API reference is
generated from source docstrings with `show_docstring_attributes: true`, so all 367 attribute
docstrings publish — 119 from `config.py` alone. Inside docstrings there were **178 "Phase N"
references and 115 "CLAUDE.md" references across 76 files**. A reader of the API reference met
*"Configuration for the Phase 3 building-height cascade"* and *"CLAUDE.md requires a threshold to
be swept"*, both pointing at a file they cannot see.

**And it reached runtime output, which is the part nobody had looked at.** `ucp/registry.py`
parameter descriptions, `classify/prototypes.py` notes, `classify/rules.py` reasons, `config.py`
disabled-rule reasons and `presets.py` descriptions are **serialised into every run's
`manifest.json` and rendered in the map site's sidebar**. Nineteen such strings said "Phase 5",
"Phase 14" or "CLAUDE.md". The two committed demo sites carried them too, and were corrected by
re-deriving the affected fields from the live constants rather than by hand — 21 strings per site,
with `ensure_ascii` matched to each writer so nothing else in the files moved.

**The research record moved out of `docs/`.** `docs/status.md` → `notes/status.md` and
`docs/experiments/` → `notes/experiments/`, by `git mv`, with a `notes/README.md` saying it is the
development record and that nothing user-facing links to it. **`docs/references/` did not move** —
its transcribed tables are parsed directly by five test modules. Contents unchanged; only the
prose around the tables lost its phase numbering, and the parsers were re-run to confirm it.

**The editing rule, applied uniformly: remove the framing, keep the fact.** A default justified by
a measurement keeps its measurement — "Open Buildings 2.5D is disabled: lowest per-building error
of the three and it still makes the map worse, because `Hr` is a geometric mean and its within-unit
spread is 0.441 against reality's 0.195" is documentation. "Phase 10 measured…" is not.

**What was left alone, deliberately.** `scripts/` and `tests/` keep their phase vocabulary: they
are the research drivers and their own test names, not documentation, and rewriting them would
churn the record for no reader. This file keeps everything but its paths.

**One thing the README was hiding: it had no `pip install` anywhere.** The `## Setup` section
documented one specific cluster — an environment path, `uv add --active` only, and a pointer to
this file's "Environment and paths" section — so an outside reader had no install instruction at
all. It is now `## Install`, above `## Quick start`, with the shared-cluster rules in a collapsed
contributor note. `docs_src/index.md` had the `pip install` all along, which is how it went
unnoticed.

---

### Phase 27 — the land-cover backend nothing could reach — CONCLUDED

**Opened by an audit, on explicit request.** Not a diagnostic phase: it moved no measurement, and
**every default is unchanged**, so nothing stored is superseded. `EarthEngineSource` has been in
the package since Phase 4 — protocol-correct, batched, cached, and schema-identical to
`LocalRasterSource` by that phase's own acceptance criterion, which its live tests measure — and
**no chain could reach it.** `run_pipeline` held a literal `LocalRasterSource`, so
`GEE_PROJECT_NAME` had no effect on `lczkit run` at all.

That is the sixth instance of the pattern: WUDAPT named the secondary reference in Phase 0 and
built in Phase 16, the height cascade specified in Phase 3 and built in Phase 10, `unit_strategy`
ruled in Phase 11 and applied in Phase 17, GUPPD on disk unread since Phase 0, `mean_building_area_m2`
computed from Phase 5 and never read by the metric. Here the code existed *and* the acceptance
criterion had been measured; only the seam was missing, which is the least visible version of it.

#### The seam

- **`LandCoverConfig.source`**, `Literal["local", "gee"]`, default `"local"` — the path that needs
  nothing but HTTP and the one CI exercises. It is an ordinary field, so it reaches the manifest by
  being one, and a reader can tell which backend answered.
- **`--land-cover-source`**, parsed by `cli._options.parse_land_cover_source` in the shape
  `parse_basemaps` established: `None` means "I did not say" and leaves the preset's and
  `--config`'s answer alone, which is what makes the flag and a config file composable rather than
  exclusive. Its accepted values are `get_args(LandCoverBackend)` rather than a second list.
  Refused before `DATA_DIR` is read, per Phase 24 — a mistyped backend is not an environment
  problem.
- **`pipeline.land_cover_source`** is the one dispatch. The local branch keeps `clip_worldcover`,
  which mosaics whichever 3° tiles the extent spans; the Earth Engine branch fetches nothing
  locally, and a test pins that choosing it does not also spend the download it exists to avoid.
- **`check_asset`** lifted out of `EarthEngineSource.__init__` so the precondition is askable
  before anything is spent. Land cover is the fourth stage of nine and the two before it are the
  long ones. `run_pipeline` and the command line both call it rather than restating it; without it
  a `--dry-run` naming the backend with no project printed *"as project None"* and exited zero,
  which is the one command that must not.

**The two backends are not bit-identical and the docstrings say so**: `exactextract` weights each
cell by the exact fraction of it a unit covers, `reduceRegions` counts whole pixels by centre, so a
100 m unit against a 10 m product disagrees by a single percent on its ~40-cell boundary ring. The
live tolerance is 0.08. **The choice is where the arithmetic happens, not what is computed.**

#### Two defects the seam exposed rather than introduced

**`RunPreset.apply` discarded `gee_project`, and had since Phase 15.** It replaced the whole
`land_cover` section with a copy of the preset's, whose `gee_project` is `None` — so every
`lczkit run` cleared the value `Settings.load` had read from `GEE_PROJECT_NAME` moments earlier.
Reproduced directly against unmodified code, not inferred: `Settings.load` gives the project,
`apply_preset` gives `None`. **All 24 manifests on disk record `gee_project: null`.** This is the
same silent-discard failure `Settings.load` documents in the other direction — an absent value must
leave what is there alone — one layer up, and it was invisible for exactly as long as nothing
downstream read the field.

> A consequence stated rather than left to be found: the field now reaches every manifest and any
> site built from one. That is designed behaviour and a Google Cloud project ID names a tenancy
> rather than authorising anything, unlike `VizConfig.maptiler_key`, which is `exclude=True`
> because it is a credential — but it is the same three-files-deep path Phase 21 opened, so it is
> written down.

**`land_cover.max_raster_cells` was unreachable from a run.** The stage built
`LocalRasterSource(dataset, worldcover)` without it, so only the constructor default ever applied.
The two happen to be equal at 200 000 000, which is why nothing noticed.

#### Are WSF-3D and GHS-BUILT-H queryable Earth Engine assets? Measured, not assumed

| product | in the Earth Engine public catalogue |
|---|---|
| GHS-BUILT-H ANBH | **yes** — `JRC/GHSL/P2023A/GHS_BUILT_H/2018`, an `Image`, band `built_height` |
| WSF-3D building height | **no** — `projects/earthengine-public/assets/DLR/WSF` lists exactly one child, `WSF2015/v1`, band `WSF`, a 10 m settlement mask |

So an Earth Engine route serves at most one of the two default tiers, **and not the one that
matters**: WSF-3D answers for 92–99% of building area in the cities measured, with GHS-BUILT-H the
fallback beneath it. A backend switch meaning "the whole cascade" in one place and "the fallback
tier alone" in another is a configuration whose meaning changes with the city.

**And for GHS-BUILT-H it would be a second route to the same numbers.** Measured twice, on
different tiles and different strata, cell centres reprojected out of Mollweide: 180 points across
a low-rise window and a tall tail reaching 32.31 m, which is the figure the `GhslProductConfig` and
`sources.height_products` docstrings carry, and then independently 80 cells on tile `R4_C20` — 50
at 2.5–8.54 m and 30 at 12.09–18.50 m. The Earth Engine band and the local ANBH raster agree to
**0.000000 m** both times, mean and max. Worth stating precisely because the name alone
could not settle it: GHSL publishes ANBH (`BUVOL / BUSURF`) beside the gross AGBH, the two differ
by the built-up share, this package reads ANBH deliberately, and **neither the asset ID nor its
Earth Engine metadata says which one the band carries**. Only sampling both did.

**Ruling: both height tiers stay on plain HTTP, and the asymmetry is documented rather than left
looking like an oversight.** There is nothing to gain and a credential requirement to add. Open
Buildings 2.5D is the exception and already goes through Earth Engine, because it has **no public
bucket at all** — and it is off by default on measurement, not on availability.

#### Scaling, stated because the anti-pattern requires it

**No whole-extent operation is added.** The switch selects between two implementations that both
existed; `EarthEngineSource` already bounds each `reduceRegions` call at `gee_batch_size` and the
whole run at `gee_max_units`. What is worth knowing before choosing it: a GUPPD region's median
80 km² is ~8 000 cells on a 100 m grid and Berlin's 891 km² is ~89 000, and with
`UcpConfig.measure_on = "enclosures"` the stage reduces **twice**, once per unit set.

**The two backends have never been benchmarked against each other, and the config docstring says
so rather than implying otherwise.** The reasons to choose the remote one are a dataset with an
asset and no local product, and a covering window that would exceed `max_raster_cells` — a ceiling
the local read has and the server-side reduction does not. Wall time is not one of them, because
nobody has measured it; a plausible-sounding performance claim in a docstring is the kind that
gets quoted.

No dependency was added — `earthengine-api` has been declared since Phase 4.

**Verified against live Earth Engine**, not only in the offline suite: all seven `network` tests
pass, including the new one that goes through `land_cover_source` and checks the table it gets back
is the one the local backend would have produced.

### Phase 28 — the two rules that were never swept — CONCLUDED

**The outstanding item on the deferred list, taken on request.** Phase 18 shipped the LCZ 7 and
LCZ 8 semantic rules **disabled**, and said so as a ruling rather than as caution: a threshold is
swept against a reference and chosen at an operating point, never picked. Phase 25 then measured
what the omission costs — LCZ 7 and LCZ 8 come out **inverted on building size** in every city
looked at — and left the sweep undone. This is that sweep, on the same methodology as
`scripts/lcz10_threshold_sweep.py`: nineteen thresholds, precision and recall against a real
reference, the whole curve reported, an operating point chosen by a rule stated in advance.

**One rule is enabled and one is refused, and the refusal is the more interesting half.**

`scripts/lcz78_threshold_sweep.py`; record archived at
`output/lczkit/lcz78-sweep/lcz78_threshold_sweep.json`. Re-running the sweep stage over the stored
evidence reproduces every curve, every candidate and both verdicts **bit-identically** — the
expensive half is `--build`, and the sweep over it is minutes.

**One field does move on a re-run, and it is supposed to.** `verify_amortisation` runs at
`_shipped_gate(rule_name)`, which reads the *current* config — so the archived checks record
`size_gate: 1000.0`, the placeholder that was still shipping when the record was written, and a
re-run today records `None`, the gate this phase removed. The mismatch counts are 0 at both, so the
check passes either way and now verifies the amortisation at the gate that actually ships. Recorded
because the next person to re-run this will see one field differ and needs to know which half moved:
**a self-referential check tracks the config it validates, so it cannot be bit-identical across the
change it was run to justify.**

#### Eight cities, chosen for the axis under test

The rules read a fraction whose denominator is building area and whose numerator is *tagged*
building area, so tag coverage is the thing under test and the sample has to span it. Arm A, grid
units, cascade `coarse`, Overture `2026-07-22.0`, each city's 30 km So2Sat window — the same
`build_arms` every published multi-city figure came through.

| city | region | tagged building area | So2Sat LCZ 8 cells | So2Sat LCZ 7 cells |
|---|---|---:|---:|---:|
| Berlin | Europe | 62.3% | 911 | **0** |
| Milan | Europe | 51.7% | 708 | **0** |
| Vancouver | North America | 50.1% | 2 126 | **0** |
| Mumbai | South Asia | 13.9% | 138 | 242 |
| Cape Town | Africa | 11.3% | 1 280 | 295 |
| Jakarta | Southeast Asia | 7.7% | 508 | 121 |
| Nairobi | Africa | 3.5% | 722 | 444 |
| Islamabad | South Asia | 2.8% | 258 | 846 |

**Eight of the twenty-eight registry cities, not sixteen.** Building the evidence took 8–35 minutes
a city (median 14, recorded per city in its own `evidence_<city>.json`) and the sweep over it is
seconds, so the population is what the time budget bought rather than a selection. Anything
differencing a later sweep against this record must intersect the city sets first.

#### LCZ 8 — enabled at 0.70, no size gate

**Six of 114 settings clear all four criteria, and they are a contiguous band** — thresholds 0.70
through 0.95, every one of them with the size gate off. Pooled over the eight cities, gate off:

| threshold | relabelled | rule right | displaced label right | mean Δ built | worst Δ built |
|---:|---:|---:|---:|---:|---:|
| 0.05 | 2 023 | 41.7% | 20.3% | +1.35 | **−0.80** |
| 0.30 | 1 182 | 58.2% | 18.0% | +1.40 | +0.05 |
| 0.50 | 891 | 65.3% | 15.7% | +1.31 | +0.05 |
| **0.70** | **662** | **72.2%** | **14.8%** | **+1.11** | **+0.03** |
| 0.95 | 396 | 81.1% | 11.6% | +0.72 | +0.00 |

At the operating point **every one of the eight cities improves on every measure** — LCZ 8's
user's accuracy, recall, F1, built-class agreement and overall agreement all rise, with no
exception. F1 moves +5.0 points on average (Berlin 10.1 → 21.7, Vancouver 20.3 → 29.4, Milan
6.0 → 11.3, Islamabad 7.3 → 7.5) and built-class agreement +1.11 (Vancouver +2.81, Jakarta +2.35,
Islamabad +0.03).

**Precision is *not* flat, which is the contrast with the LCZ 10 sweep and worth recording as
one.** There, precision moved six points over a nineteen-fold change in threshold and the
conclusion was that the threshold governs the *rate* and not the accuracy. Here the rule's own
precision runs **41.7% → 81.1%** across the same grid while reach falls 2 023 → 396: a real
trade-off, and the threshold is buying correctness. The two rules are not the same kind of object,
and reading either one's shape onto the other would have been wrong.

**The `mean_building_area_m2` gate the rule shipped with is measured harmful and is removed.** It
cuts reach at every one of the 95 gated settings, and at 91 of them it also raises the accuracy of
the label it displaces — the four exceptions are all at the widest 4 000 m² gate and move it by at
most 0.5 points, so the direction is not universal but its shape is. At the operating point it is:
1 000 m² at 0.70 takes 662 relabelled cells to 237, the rule's precision from 72.2% to 67.1%, and
the displaced label's from 14.8% to 24.5%, and **no gated setting passes at any threshold.** The
mechanism is in the column's own name:
`sem_large_lowrise_buildings_of_building_area` divides by the unit's **whole** building area, so
untagged and small-building area already counts against the fraction and the gate re-charges for
size a second time.

**The rule's reach is a map of Overture's tag coverage, and that is what makes it safe where the
evidence is thin.** It relabels 2.0% of Berlin's cells and 0.04% of Islamabad's, a fifty-fold
spread across the same denominator — because untagged building area counts against the fraction, a
city Overture cannot describe simply does not trip it.

**WUDAPT disagrees, and it is recorded rather than set aside.** So2Sat decides, per the standing
ruling that it is primary where it exists, and that was pre-registered before the sweep ran. But
against WUDAPT **zero of 114 settings clear the criteria**: LCZ 8's F1 still rises in all eight
cities and the rule still beats the label it displaced at *every one* of the 114 settings
(58.1% against 17.6% at 0.70), yet class precision falls in Berlin (67.8 → 59.2) and Milan
(65.4 → 63.5) while recall roughly doubles, and Mumbai loses 0.016 points of built agreement. The
substantive direction is the same under both references; the strict no-loss-anywhere bar is met
under one and not the other.

#### It does not repair the size inversion, and that is checked rather than assumed

Phase 25's finding is that LCZ 8 — *large* low-rise — lands on cells of small buildings while LCZ 7
lands on sheds. It would be easy to read an enabled LCZ 8 rule as closing that, and **it does not.**
Median `mean_building_area_m2` on built cells (BSF > 0.05), rule off → rule on:

| | LCZ 7 median | LCZ 8 median | ratio 8/7 |
|---|---:|---:|---:|
| Berlin | 12 975 → 9 115 | 739 → 798 | 0.0569 → **0.0875** |
| Milan | 15 985 → 15 982 | 699 → 780 | 0.0437 → 0.0488 |
| Mumbai | 5 716 → 3 588 | 141 → 143 | 0.0246 → 0.0399 |
| Jakarta | 2 090 → 2 286 | 106 → 106 | 0.0505 → 0.0464 |
| Cape Town | 11 084 → 8 193 | 119 → 119 | 0.0107 → 0.0145 |
| Vancouver | 19 053 → 14 991 | 208 → 219 | 0.0109 → 0.0146 |
| Islamabad | 6 226 → 6 226 | 168 → 168 | 0.0270 → 0.0271 |
| Nairobi | 3 789 → 3 776 | 95 → 95 | 0.0250 → 0.0251 |

**All eight are listed, and the ratio is given at four decimals, because two decimals cannot carry
this comparison.** Nairobi moves by 0.00016 and crosses a rounding boundary while doing it, so at
2 dp it prints `0.02 → 0.03` and looks like the third-largest mover; Cape Town and Vancouver move
twenty times further and print `0.01 → 0.01`. Rounding decided the ranking rather than the data.

The ratio rises in seven of eight and falls in Jakarta, and **in every city LCZ 8's median footprint
stays 11× to 93× below LCZ 7's** — Berlin moves furthest, from 17.6× inverted to 11.4×, and is still
inverted. The reason is structural: **a semantic rule
can only add LCZ 8, never remove it.** The small-footprint cells the metric wrongly calls LCZ 8 are
untouched, because nothing in the rule looks at what the metric already decided. The rule buys
agreement; it does not buy the dimension the metric is blind on, and the thing that would is the
`mean_building_area_m2` weight, which remains unswept and at zero.

Berlin and Nairobi are the two cities this and Phase 25 share, and the rule-off figures reproduce
that phase's independently: 12 975 / 739 against its 13 419 / 767 on Berlin (ratio 0.0569 against
0.0572) and 3 789 / 95 against 3 749 / 93 on Nairobi (0.0250 against 0.0248) — different runs over
different extents in Nairobi's case, and the ratios agree to three decimal places in both.

#### LCZ 7 — refused, and not by a margin

**All 95 settings are refused, against both references, and criterion 2 is what refuses every one
of them** — the rule is wrong more often than the label it overwrote at **95 of 95 settings under
both**, which is the sharp instrument the criterion was written to be. The other three are failed
widely but not universally, and the difference is worth stating rather than rounding to "all four":
under So2Sat, C1 passes at 1 setting, C3 at 13 and C4 at 7; under WUDAPT C4 passes at 88, because
firing widely is easy where the thing being counted is wrong. Only 74 of 95 (So2Sat) and 7 of 95
(WUDAPT) fail all four at once.

The best any setting anywhere reached was **2 correct LCZ 7 labels** against So2Sat and 7 against
WUDAPT — while displacing 93 and 160 labels the metric had right. Not a threshold that needs
moving: a rule that destroys forty to seventy correct labels for each one it creates.

**The mechanism is two-sided, and neither side is the threshold.**

- **Overture's `lightweight` vocabulary is outbuildings, not settlements.** There is no `slum`,
  `shanty`, `ger` or `tent` value in the schema, so the crosswalk maps
  *hut, shed, cabin, roof, kiosk, carport, guardhouse*. What it finds in a well-described city is
  garden sheds and carports.
- **So the tagged evidence sits in the three cities that carry no LCZ 7 at all.** At its widest
  setting the rule fires on 1 223 scored cells in Berlin, 472 in Vancouver and 108 in Milan, whose
  reference LCZ 7 counts are 0, 0 and 0 — and on 4 cells in Islamabad against 846 reference LCZ 7
  cells, 6 in Mumbai against 242, 18 in Nairobi against 444.

**The cities with the tags have no informal settlement and the cities with informal settlement have
no tags.** Phase 18 predicted the second half — "this rule will mostly not fire where it matters" —
and the first half is what makes it worse than under-firing: the rule is not weak, it is pointed at
the wrong ground. It is disabled on that measurement, which is a **result and not a placeholder**,
and `building_tag_coverage` is what keeps the shortfall legible.

#### What the instrument cost, and two defects in it

**The sweep classifies each city once and applies the rule to the result.** `apply_semantic_rules`
is the *last* thing `PrototypeClassifier.classify` does to the ranking, so a run with the rule on
differs from one with it off only by that call — and the distance metric, which is 8.4 s on a
91 000-cell city, does not depend on the threshold at all. Re-deriving it per setting is 220
classifies a city and **~4.1 hours**; amortised it is **~1 minute** for the whole sweep.

That is a local operation standing in for a global one, so it is measured and not asserted: at one
setting per city per rule, the amortised labels are checked against a full `classify` with the rule
configured. **16 checks, 0 mismatches**, on `lcz_primary`, `lcz_secondary` and the fired mask.

Two criteria did not match the prose that defined them, both found by reading the code against its
own docstring before running it:

- **Criterion 4 counted the wrong thing.** "The rule relabels a non-trivial share of the class" was
  implemented as `n_predicted`, which is every cell carrying the label *including the ones the
  metric assigned* — so a rule that fired on nothing would pass wherever the metric already
  over-predicted. It counts cells the rule relabelled now.
- **Criteria 1 and 3 failed on equality.** Written as "must exceed the baseline in every city",
  they are unsatisfiable the moment one city's tag coverage stops the rule firing there, since the
  city's figure is then unchanged rather than better. Restated as no-loss-anywhere plus a gain
  somewhere — the same vacuous-comparison trap as `all()` over an empty sequence, which the same
  file had already been fixed for one criterion along.

Criterion 4 also asks the class to be reached in **one** city rather than all of them, and the
reason is on the record before the sweep ran: the committed tag-coverage measurement — 48.6% of
building area tagged across Europe and North America against 13.6% elsewhere — already predicts
that a tag-reading rule cannot fire where the tags are absent. Requiring it everywhere would make
the criterion a test of Overture's coverage rather than of the rule, and would have refused both
rules before a threshold was tried.

#### Rulings

1. **A rule ships enabled once its threshold has been swept, and disabled otherwise — and both
   halves are now demonstrated by the same sweep.** Phase 18's "disabled is a ruling, not caution"
   named the *only* reason those rules were off. That reason is discharged for LCZ 8 and replaced
   by a stronger one for LCZ 7, which is now disabled on measurement rather than pending it. The
   config docstrings, `apply_semantic_rules`, `docs_src/index.md` and the two test files say which
   is which, because a ruling is not applied until the code says so.
2. **Every stored figure in this project predates an enabled LCZ 8 rule.** It relabels 0.04%–2.0%
   of a city's cells and moves built-class agreement by up to +2.8 points, so a run at today's
   defaults is not comparable with a stored one. Any comparison must set
   `large_lowrise.enabled=False` or re-baseline, exactly as `modal_filter` and
   `measure_on="enclosures"` require — with the difference that this one is **on** by default.
3. **A tag-driven rule is not a global instrument, and the documentation now says so where a
   reader meets it.** `docs_src/index.md` states the 48.6%/13.6% split, names the mechanism
   (Google Open Buildings and Microsoft ML supply geometry with no attributes, and Overture's
   conflation is winner-takes-all per building), and tells the reader to read
   `building_tag_coverage` beside anything that depends on a tag. A class 7 share of zero where
   95% of building area carries no tag is not evidence of absence.

**Not done, and recorded rather than dropped.** The `mean_building_area_m2` weight sweep Phase 25
pre-registered is a separate measurement and is not in this phase: this one changes what a *rule*
does and leaves the metric's weights untouched, so the two do not confound each other and the
weight sweep is still outstanding on the deferred list.

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
7. ~~**Phase 19 — a run a GIS can open.**~~ **Concluded**, on a report from outside the repository.
   Packaging, not measurement: `units.gpkg` and the manifest's derived CRS. Nothing recomputed, no
   stored figure moved.
8. ~~**Phase 20 — the API reference.**~~ **Concluded**, on explicit request. Documentation and
   tooling, not measurement: every public symbol documented, `D` enforced in CI, and an MkDocs
   site published from a `docs_dir` that cannot leak the reference PDFs. It found that CI had
   never fired on a push.
9. ~~**Phase 21 — base maps a reader can choose.**~~ **Concluded**, on explicit request. Front end
    and packaging, not measurement: six grounds behind a dropdown, no Google tiles on licensing,
    and an API key confined to `style.json` by a field flag and a test. It struck the "no basemap
    requiring an API key" anti-pattern in place rather than working around it.
10. ~~**Phase 22 — the demonstration notebook.**~~ **Concluded**, on explicit request. Documentation
    and packaging, not measurement: Bogotá on the grid and on patch units, with both map sites
    embedded in the page. It found that `OvertureSource` could not be constructed inside a Jupyter
    kernel at all, and had not been since Phase 1.
11. ~~**Phase 23 — one overlay, any city, and a run that says where it was.**~~ **Concluded**, on
    explicit request. Cleanup and packaging, not measurement, and the one change that could have
    moved a number is pinned to 1e-9 against the values recorded before it. It found that no
    manifest on disk records what ground its run covered, and that the only city locator read the
    So2Sat label archive and therefore knew 28 places out of 5 558.
12. ~~**Phase 24 — the argument, not the environment.**~~ **Concluded**, opened by CI rather than
    by request. Not measurement: an ordering defect in `lczkit run`, and the `.env` leak that kept
    the six tests pinning it green on every machine that had one. It found that CI has never had a
    green run in this repository's history, and had never fired at all before Phase 20.
13. ~~**Phase 25 — the dimensions the metric was missing.**~~ **Concluded**, on a scientific review
    requested by the user rather than on a defect report. Six instruments that move no label and
    four metric changes, three of them inert by default. It found that **LCZ 7 and LCZ 8 come out
    inverted on building size in every city measured** — "large low-rise" landing on 55-93 m²
    footprints and "lightweight low-rise" on 7 000-13 000 m² sheds — and that `mean_building_area_m2`
    has been computed since Phase 5 and never reached the metric.
14. ~~**Phase 26 — documentation, not a build log.**~~ **Concluded**, on explicit request. Not
    measurement: the phase vocabulary and every reference to this file were removed from the
    README, the published site, every source docstring and the strings that reach a run's
    manifest and the map site's sidebar. It found that the README carried no `pip install` at
    all, and that 19 description strings naming phases were being serialised into every run.
15. ~~**Phase 27 — the land-cover backend nothing could reach.**~~ **Concluded**, on explicit
    request after an audit. Not measurement, and no default moved: `LandCoverConfig.source` and
    `--land-cover-source` give `run_pipeline` a way to select the Earth Engine backend that had
    been protocol-correct and unreachable since Phase 4. It found that `RunPreset.apply` cleared
    `gee_project` moments after `Settings.load` read it, so all 24 manifests on disk record it as
    null — and that **WSF-3D is not in the Earth Engine catalogue at all**, which is why the
    height tiers keep fetching over HTTP.
16. ~~**Phase 28 — the two rules that were never swept.**~~ **Concluded**, on explicit request, and
    it is the outstanding deferred calibration rather than a new question. Eight cities, nineteen
    thresholds crossed with the size gate, both references. **LCZ 8's rule is enabled at 0.70 with
    no size gate** — every one of the eight cities improves on precision, recall, F1, built-class
    and overall agreement — and **LCZ 7's is refused**, because Overture's lightweight vocabulary
    is outbuildings and the tagged evidence sits in the three cities that carry no LCZ 7 at all.
    It found that the size gate the rule shipped with was harmful, and that this threshold buys
    correctness where the LCZ 10 one did not.
17. **The paper.**
18. **Cleanup** — release. **The docs half landed as Phase 20, the notebook half as Phase 22, the
    README split as Phase 23 and the de-narrativising pass as Phase 26**; what is left here is the
    release itself.

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
`notes/experiments/phase-7-map-site.md`. Completing it fixed two gaps and published three cities.

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
| "Europe + N. America" as a grouping | **Does not survive n > 1 in its North American half, and the corrected line then held.** It carried three phases on Vancouver alone. At twenty cities: Europe 91.0%, South America 85.6%, **North America 70.8% against "everywhere else" 70.9%**. At twenty-eight, with East Asia taken from Hong Kong alone to six: **Europe 91.0% against everything else 71.6%**, East Asia landing at 72.3% with the elsewhere bloc. The line is Europe against everywhere else, not Global North against Global South. **Re-measured for one of the four sightings only** — Phase 11's A/B, Phase 12's compactness lift and Phase 18's tag coverage were all measured at n = 1 in both regions and are untested. Ruling: check the smallest cell before a grouping carries an argument. | 11, 12, 16, 18 |
| A region represented by one city | **Not a region, and it has already produced a wrong reading.** North America was Vancouver for three phases; when it grew to four the grouping reorganised. East Asia was Hong Kong. Southeast Asia (Jakarta) and Oceania (Sydney) remain n = 1 and **cannot be fixed from the data on disk** — Manila carries 246 patches of one class, Melbourne has exactly one WUDAPT polygon — so they are pinned by name in a test rather than tolerated silently. West Asia is n = 2 with a 57-point internal spread, which is two cities. | 16, 18 |
| `corr(contested share, label agreement)` = −0.14 | **Measured at n = 16 and softened by the sample.** −0.14 (16) → −0.13 (20) → **−0.36 (28)**: Tehran contests 25.31% and reaches 40.6%, Beijing 16.15% and 64.2%. The flat refutation no longer holds cleanly; it is a weak negative relationship, still not a proxy for anything. Recorded because the original figure is committed below. | 16 |
| Two city registries, one in the package and one in the sweep | Phase 15 lifted `City`/`CITIES`/`BY_KEY`/`WINDOW_KM`/`densest_window` into `lczkit.cities` for the CLI and left the originals in `scripts/multi_city_validation.py`. They agreed until someone edited one — and the one that produces every published figure is the *script*, so adding four cities to the package would have left the sweep running sixteen. Same failure as `CLEANING`. The script imports them now and a test asserts **identity**, since equality passes right up until the moment it matters. | 15, 18 |
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
| No notebook tooling, per the same bullet | **Partially lifted by explicit request, Phase 20**, and patched here rather than departed from silently. `mkdocs-jupyter` (Apache-2.0) is in the `docs` group, so it is notebook tooling in the *documentation build* and not in the package or its runtime dependencies. It renders nothing today — the repository holds **zero** `.ipynb` files — and is recorded rather than dropped, so a future notebook has somewhere to go. No web UI and no plotting helpers. | 0, 15, 20 |
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
| Uncalibrated functional rules for LCZ 7 and 8 | **Shipped disabled in Phase 18, swept in Phase 28, and the two rules parted company.** LCZ 8's is **enabled at `min_fraction=0.70` with no size gate**: 6 of 114 settings clear the four pre-registered criteria, they form a contiguous 0.70–0.95 band, and at the operating point all eight cities gain on precision, recall, F1, built-class and overall agreement (F1 +5.0 mean, built +1.11). LCZ 7's is **refused at all 95 settings against both references** and is now disabled *on* measurement rather than pending it. Phase 18's "the sweep needs a city where the class exists *and* is tagged" was right and is measured: the three cities with tags carry **zero** reference LCZ 7 cells, and the five with LCZ 7 carry 2.8–13.9% tagged building area. | 6, 14, 18, 28 |
| The `mean_building_area_m2` gate on the LCZ 8 rule | **Measured harmful and removed.** It cut reach at all 95 gated settings and raised the accuracy of the label being displaced at 91 of them (the four exceptions are at the widest 4 000 m² gate, ≤0.5 points), and **no gated setting passes at any threshold** — 1 000 m² at 0.70 takes 662 relabelled cells to 237, the rule's precision 72.2% → 67.1%, the displaced label's 14.8% → 24.5%. The mechanism is in the column's own name: `sem_large_lowrise_buildings_of_building_area` divides by the unit's **whole** building area, so untagged and small-building area already counts against the fraction and the gate charges for size twice. **A quantity's denominator belongs in its name, and reading it is what explains the result.** | 18, 25, 28 |
| Reading the LCZ 10 sweep's flat precision as the shape a functional threshold has | **Not general, and the contrast is the finding.** LCZ 10's precision moves six points over a nineteen-fold change in threshold, so there the knob governs the rate. The LCZ 8 rule's own precision runs **41.7% → 81.1%** over the same grid while reach falls 2 023 → 396 — a real trade-off, and the threshold is buying correctness. Two functional rules on one instrument are not thereby the same kind of object. | 14, 28 |
| So2Sat and WUDAPT disagreeing about whether to enable a rule | **So2Sat decides, pre-registered before the sweep ran, and the disagreement is recorded rather than set aside.** Against WUDAPT **zero of 114 settings** clear the criteria — LCZ 8's F1 still rises in all eight cities and the rule beats the label it displaced at *every* setting, but class precision falls in Berlin (67.8 → 59.2) and Milan (65.4 → 63.5) while recall roughly doubles, and Mumbai loses 0.016 points of built agreement. Same substantive direction under both; the strict no-loss-anywhere bar is met under one. Which reference produced which figure is in the record, per the standing rule that "the reference" must name a file and not a role. | 16, 28 |
| Amortising the distance metric across a threshold sweep | The metric does not depend on the rule — `apply_semantic_rules` is the last thing `classify` does to the ranking — so the sweep classifies each city once and applies the rule 220 times: **~4.1 h to ~1 min**. A local operation standing in for a global one, so it is **measured, not asserted**: at one setting per city per rule the amortised labels are checked against a full `classify`, **16 checks, 0 mismatches** on primary, secondary and the fired mask. | 8, 12, 28 |
| Acceptance criteria that fail on equality, and one that counted the wrong column | Both found by reading the sweep's code against its own docstring before running it. "Must exceed the baseline in **every** city" is unsatisfiable the moment one city's tag coverage stops the rule firing there, since that city is unchanged rather than better — restated as no-loss-anywhere plus a gain somewhere. And "the rule relabels a non-trivial share of the class" was implemented as `n_predicted`, which counts the *metric's* assignments too, so a rule firing on nothing would pass wherever the metric already over-predicted. **The vacuous-comparison trap, twice more, in a file already fixed for it once.** | 28 |
| Nothing asserted that a clipped raster covers its window | The silent variant was one line away and would not have raised: `clip_raster` windows with `from_bounds` and `read(window=…)`, which **returns a smaller array** rather than erroring, and `LocalRasterSource.fractions` turns uncovered units into **all-`NaN`** by design. Two correct behaviours composing into a quarter-missing map. `clip_worldcover` now reopens what it wrote and raises, naming the short side; `coverage_shortfall` ignores sub-pixel gaps because every real clip has one. The last `WORLDCOVER_URL` call sites were retired — Berlin-only, so no stored result moves. | 4, 7, 13 |
| Pooling a partial sweep against a complete stored record | Reported the difference between two city lists as a pipeline deviation (6.6%). Stability comparisons now intersect the city sets; restricted, the deviation is 0.0%. | 13 |
| Superseded text left in concluded phase blocks | Phase 8's block opened with a nine-minute runtime and later asserted the package could not process a city; Phase 3 still carried the corrected-away axis pairing; deferred still listed SVF first. **Concluded phases keep measurements and rulings and drop imperatives.** | 3, 6, 8, 13 |
| Run outputs reported as having no CRS in QGIS | **Not a defect in the files, and checked before anything was changed.** All ten runs on disk carry valid GeoParquet 1.0.0 with the extent's UTM CRS as PROJJSON *and an EPSG authority code*, in `units.parquet` and every `layers/*.parquet` — `EPSG:32618` Bogotá through `EPSG:32737` Nairobi. GDAL's Parquet driver is an **optional build component**, so a QGIS without it opens a correct file as a non-spatial table and the symptom names the producer. `units.gpkg` ships beside the GeoParquet by default (measured 0.86 exponent, 1.83 s / 67.3 MB at 116 491 units), never instead of it. **The archival GeoParquet and its CRS are unchanged** — the export CRS was *not* switched to lat/lon, because that would move every stored run's geometry and make every area statistic in this file incomparable. | 6, 19 |
| The run CRS recorded nowhere | Derived by `estimate_utm_crs()` from the extent, so it is in no config and was in no manifest — a run directory could state its own CRS only through the file format the complaining reader could not open. `manifest.crs` and `crs_wkt` added; `lczkit export` backfills them for runs already written, editing the JSON directly rather than round-tripping through `RunManifest`, which would fill today's defaults into an archived run. | 0, 6, 19 |
| `ci.yml` triggered on a branch that does not exist | `push: branches: [main]` since Phase 0, against a repository whose only branch is `master` — the *remote* is named `main`, which is what makes it misread. **CI had never fired at all**, which is why a `ruff format --check` failure sat unnoticed in the tree. Fixed to `master`. A workflow that never runs is indistinguishable from one that passes. **Phase 20 wrote "fired only on pull requests" and Phase 24 measured it**: 4 runs in the repository's history, all `push`, all after the fix, and **zero pull requests ever opened**. The claim was an inference from reading the trigger, and checking it costs one API call — the same shape as attributing cost by adjacency in a call graph. | 0, 20, 24 |
| `ruff format` reads Python fences inside Markdown | ruff 0.16 formats ```` ```python ```` blocks in `.md`, so `docs/references/tables/osm_lcz_tag_mapping.md` — a hand-checked Tier 1 transcription — was a standing `ruff format --check` failure. Excluded via `[tool.ruff.format] exclude`, not reformatted: the file's whole value is that it is a faithful copy, and `ruff check` does not read `.md` at all, so the two commands disagree about what a "Python file" is. | 20 |
| pydocstyle convention for a prose-docstring codebase | **`google`, chosen on measurement.** No `Args:`/`Parameters` section exists anywhere in the package, so no convention's *section* rules apply and the choice only decides which nuisance rules switch off. `google` leaves 68 in `src/` against `numpy`'s 123 and `pep257`'s 136, by disabling D401 non-imperative-mood — 67 hits against docstrings that deliberately open with a claim rather than a verb — and it is mkdocstrings-python's own default, so linter and renderer read the docstrings the same way. `tests/**` and `scripts/**` exempt. | 20 |
| Protocol implementations documented only on the Protocol | The one member that *is* the implementation was blank in ten places — `generate`, `fill`, `ensure`, `name`. Defensible as authorial intent, and **not recoverable by a doc generator**: the implementations satisfy the Protocols structurally and subclass nothing, so there is no base to inherit a docstring from. Written out, each stating what it does differently rather than restating the interface. Checked before relying on it, not after. | 20 |
| `docs/` as the MkDocs `docs_dir` | **Refused.** That directory is the internal record and is 205 MB on disk — 27 gitignored PDFs plus `references/datasets/`. CI sees only the 23 committed files, but a local `gh-deploy` would publish every PDF. `docs_dir` is `docs_src/`, holding the landing page and the API pages only. **A directory that cannot contain a PDF is a stronger guarantee than an `exclude_docs` rule that has to stay correct**, and a test asserts nothing under it is gitignored. | 0, 20 |
| `uv run` undoing `uv sync --only-group` | `uv run` re-syncs the environment before running, so `uv sync --only-group docs` followed by a bare `uv run mkdocs` reinstalls the project and the whole geo stack the first step exists to skip. The flag is repeated on both steps. mkdocstrings needs neither — griffe reads the source statically via `paths: [src]`, verified by loading a module with `search_paths=["src"]` and nothing installed. | 20 |
| "No basemap requiring an API key", vs a request for MapTiler | **Struck by explicit request, in place rather than departed from silently** — third time this bullet has been narrowed, after the `file://` amendment and Phase 15's online basemaps. The guarantee it protected is unchanged and still enforced: the default build names no remote host, and that test is untouched. What changed is that "no key, ever" is now "no key unless a caller asks, and then in one file that a test names". | 0, 7, 15, 21 |
| Google as the satellite provider | **Refused on licensing, and a substitute shipped.** `mt{0-3}.google.com/vt` is undocumented and using it outside a Google Maps API breaks Google's terms, so it can record no licence — and every entry in the provider table records one, which is the table's purpose under this project's first non-negotiable. Esri World Imagery gives keyless satellite; MapTiler gives hybrid and topo. A test asserts every provider carries a licence and an attribution, so the question has to be answered again for the next ground added. | 21 |
| An API key in a manifest the site publishes | The manifest is `settings.model_dump()` verbatim **and `build_site` copies it into the site**, so an ordinary config field would have published the key three times over. `VizConfig.maptiler_key` is `exclude=True` and a test greps every file a build wrote. It bounds the exposure rather than removing it — the browser fetches the tiles, so `style.json` carries the key in plain text and whoever holds the directory holds the key. Said in `.env.example`, in the site's own `README.md`, and by the CLI at the moment the provider is chosen. | 19, 21 |
| An excluded field and a round-trip assertion | `test_json_round_trip` asserts `restored == settings`, which a deliberately non-serialising field cannot satisfy. It passed only because `MAPTILER_API_KEY` happens not to be exported in a shell — exporting it fails the test with a diff naming no cause. The variable is cleared explicitly there now, beside a test stating the non-round-trip as intended. **A test that depends on the ambient environment is not passing, it is agreeing with your machine.** | 21 |
| One raster layer pinned at `layers.index() == 1` | Generalised, not relaxed. Several grounds cannot share one source — `maxzoom` and `tileSize` live on the source and differ per provider — so there are N raster layers, and the guarantee "nothing paints over the classification" becomes a contiguous hidden block directly above the background. | 7, 21 |
| Two `--basemap` implementations | One flag, two meanings, found by needing to change both: `run` checked `PROVIDERS` directly, `site build` round-tripped the config, and only `site build` accepted `none`, so the same argument was an error in one command and an instruction in the other. Unified in `cli._options.parse_basemaps`. `None` and `[]` stay distinct — no flag leaves what the run recorded alone, `--basemap none` clears it — because a flag that cannot express the first makes an online ground unremovable on rebuild. | 15, 21 |
| A trailing space in a `.env` value | Found by the first verification request failing before it left the machine. Invisible in an editor, and it would otherwise have reached the tile URL and made every request 403 with a symptom that names nothing. `maptiler_key()` strips, and a test passes a value with trailing whitespace. | 21 |
| Base maps shipped opt-in, and the picker never appeared | **The default was wrong in use, and the report came from outside the repository.** Every ground was off unless `--basemap` named one, so a plain `lczkit site build` produced no picker — and every site on disk predated the change, so none could show one until rebuilt. A feature reachable only through an undocumented flag is not shipped. **Ruling: the CLI offers the keyless grounds by default, the library still offers none.** The line is `requires_key`, derived rather than listed, so a keyed provider cannot join the defaults by being forgotten. Cost, accepted knowingly: an ordinary CLI-built site now names four tile hosts where it named none, and an archival build must pass `--basemap none`. The site still opens and works offline either way, and no key is published unless asked for. | 7, 15, 21 |
| One guarantee, two defaults | The no-external-reference test now pins `VizConfig()` and `build_site()`, not what the command line produces — a narrowing, so it is written down rather than left to be inferred from a test that kept passing. Both defaults are tested and both are documented; the distinction is that the archival path must be network-clean without being asked, and the interactive one should show a reader a map. **A guarantee that quietly changes scope while its test still passes is the failure this row exists to prevent.** | 7, 21 |
| `SET enable_progress_bar = false` in `OvertureSource.__init__` | **Took the whole source out of Jupyter, and had since Phase 1.** DuckDB reinitialises its display when that setting is *assigned*, so in a kernel without `ipywidgets` it raises for an assignment whose purpose is to draw nothing — and every code path that reads Overture raised with it. Measured on duckdb 1.5.5: the assignment fails, assigning `enable_progress_bar_print` first fails, and `duckdb.connect(config=…)` fails differently. **`PRAGMA disable_progress_bar` succeeds and does not touch the display**, and the failure is tolerated besides. Guarded by a source assertion over the module's string literals via `ast` — under pytest there is no kernel and the bad form succeeds, so only the source can be checked. | 1, 22 |
| A probe run without pinning its kernel | **Returned the opposite answer and would have been believed.** `jupytext --execute` with no kernel named picked one from another environment, reporting `ipywidgets PRESENT` and every form working. A notebook's `kernelspec` decides which interpreter answers. Same shape as Phase 21's environment-dependent test: **agreeing with your machine is not passing.** | 21, 22 |
| A run's `site/` copied into `docs_dir` under its own name | Three ways to be silently wrong at once. `.gitignore`'s `site/` matches **at any depth**, so the directory would be ignored and never published; `README.md` collides with the site's own `index.html` and mkdocs drops it with a warning that `strict` makes fatal; and `serve.py` is matched by **mkdocs-jupyter's default `include`**, which renders it as a page and *moves* it to `<site>/serve/serve.py`. Destinations are renamed, the two archive-only files are stripped from the published copy only, and `include` is narrowed to `*.ipynb`. | 20, 22 |
| Is a demonstration notebook re-executed at build time? | **No, and it could not be.** The docs workflow runs `uv sync --only-group docs`, so the build environment has neither lczkit nor the geo stack nor `DATA_DIR`. `execute: false` is the plugin default and is set **explicitly**, because here it is load-bearing rather than incidental. The notebook is committed with outputs from a local run, paired with a jupytext percent script, and a test asserts the two have not diverged. | 20, 22 |
| Bogotá as a 29th registry city | **Refused.** So2Sat covers it with 8 patches of a single class against the 500-patch/4-class screen, so it cannot be validated — and adding a city changes the population every stored figure is measured over, against the standing rule to intersect city sets before differencing records. The notebook supplies GUPPD's `SMOD_ID 30_3370` extent directly and states that it is doing so. | 16, 18, 22 |
| `mkdocs serve` and the embedded PMTiles maps | **Third instance of "correct artefact, failing reader".** Pages honours Range (`206`, measured); `mkdocs serve` returns `200` with the whole body, and `pmtiles.js` *raises* rather than degrading — so the published page is right and the local preview is two blank frames. The fix was already in the package: `lczkit.viz.serve` is a generic Range-capable server and handles the built docs site. Said on the page beside the maps, because the person who needs it is looking at the failure. | 7, 19, 22 |
| mkdocs Markdown extensions inside a notebook cell | **Unavailable.** nbconvert renders markdown cells with its own renderer before mkdocs sees them, so `!!! note` shipped as literal text and a `../api/index.md` link would ship unrewritten and 404. Notebook cells get plain Markdown and built-site URLs; the admonition became a blockquote. The same seam that makes `execute: false` safe is what excludes the extensions. | 20, 22 |
| Five copies of "overlay a layer against the units" | **Consolidated into `lczkit.units.overlay`, and the parameter stage went from 17 unit-vs-layer intersections to 2.** Three copies sat in `ucp.industrial` and two in `ucp.semantics`, and they disagreed about the thing that matters: one reached its dissolved coverage through a whole-layer `union_all`, which is the operation the anti-pattern list warns about, and survived only because it ran on a few dozen industrial parcels. Clip-then-dissolve per unit is exact — the union of the clipped pieces inside a unit is the clip of the global union — and **the recorded values for all three fixtures reproduce to 1e-9**, pinned in `tests/fixtures/ucp/` from before the rewrite. `semantic_metrics` alone ran twelve overlays, one per configured group per layer, so its cost grew with the configuration rather than with the city. | 5, 18, 23 |
| `--city` resolved 28 So2Sat cities and no others | **The one easy locator was gated on validation data**, and `input/NASA/GUPPD/guppd_bounds.csv` — 5 558 urban regions, 173 countries, 564 KB — had been on disk unread since Phase 0, named in the layout diagram and in no `.py` file. Same shape as WUDAPT unread for sixteen phases. `lczkit.places` reads it and `lczkit cities` searches it. **Ruling: an ambiguous name is refused, not resolved to the first match** — 149 names are shared, and taking the first would run the wrong continent under a manifest that looks entirely correct. **Ruling: `--so2sat-window` is a flag, not a fallback** — a GUPPD region and a 30 km So2Sat window of the same city are different ground (Berlin 1 152 km² against 899), and only the second is comparable with a recorded figure. | 0, 16, 23 |
| A run directory could not say what ground it covered | **Checked before building anything: 0 of 18 manifests on disk carry an extent, a bbox or a place name, and no key in any of them mentions one.** Structural rather than an oversight — the extent is an argument to `run_pipeline`, so it is in no `Settings` field and therefore in none of the `config` block the manifest serialises. **The Phase 19 CRS gap exactly, still open for the extent**, and closed the same way. `lczkit export` backfills archived runs from the units' own bounds under `kind="recovered"`, a distinct value because a reconstruction is bounded by the units written rather than by the window requested. | 19, 23 |
| `app.js` described every map as a 100 m grid | `config.viz ? "grid, 100 m" : null` — a string that predates `UnitsConfig`, so Phase 17 made the strategy configurable and the front end went on asserting the old answer. A patch-units run misdescribed itself on its own page. **Fourth instance of a consumer restating what the producer already answers**, after the `label_route` vocabulary, the four `raster_*` scalars and the tippecanoe type coercion. Reads `config.units` now, and the guard strips JavaScript comments before matching — the comment explaining the removal contains the removed string, which is Phase 22's `ast` problem from the other side. | 15, 17, 21, 23 |
| Two `CleaningConfig`s and six `load_script`s in the tests, and script constants copied from `lczkit.presets` | The preset copies are gone: the scripts derive from `lczkit.presets`, copied rather than aliased since several build variants by mutation. The two guard tests lost their subject and were replaced — one pins the eight metropolitan values as literals, which is what comparing two copies was standing in for. **`scripts/unit_scale_experiment.CLEANING` stays**: a genuinely different measured configuration is not a duplicate, and the two named test constants stay two for the same reason. | 15, 18, 23 |
| The two locators collided on a name | **Found by checking the marker, and the worse half was silent.** `lczkit cities` marks the 28 rows `--so2sat-window` works for, and matching on the name alone marked **London, Ontario**, **Los Ángeles, Chile** and **Santiago, Philippines** — none of which carry So2Sat labels. The consequential half: `--city london --country CAN --so2sat-window` resolved the registry by name and ignored `--country`, so it would have run *London, UK's* window while the caller was disambiguating away from it. Silent wrong ground, reachable through the flag whose whole purpose is to keep ground straight. `City` carries an `iso` now; the marker keys on (name, country) and the flag checks the country rather than ignoring it. | 16, 18, 23 |
| A run without tippecanoe reported as a run that produced nothing | The site is the **last** stage and every other file is written before it starts, but `TippecanoeMissingError` propagated out of `run_pipeline` and became an exit code *before* the line naming the run directory was printed. A ten-minute city whose only problem was an absent tool looked like a failure. `PipelineResult.site` had documented the skip behaviour since Phase 15 and the code never had it — so the behaviour was changed to match the docstring, not the reverse. `site_skipped` records the reason, the CLI names the run directory and `lczkit site build`, and the exit code stays non-zero because a site was asked for and not produced. **Found by writing a README sentence about it and then checking whether the sentence was true.** | 7, 15, 23 |
| `lczkit run` loaded the environment before it read its own arguments | **`--bbox 1,2,3` with no `DATA_DIR` answered "DATA_DIR is not set"** — it blamed the environment for a typo, at the one moment the reader has configured neither and cannot tell which is really wrong. `_load_settings` ran before `parse_bbox` and `parse_basemaps`, so every argument error that needs nothing on disk arrived as a config error. **`site build` had always had the right shape** — parse the argument, then touch the environment — so the fix is `run` catching up to a sibling command rather than a new idea. The city locators stay behind the wall deliberately: they read `guppd_bounds.csv` and the So2Sat archive through `settings.source_dir`, so there the environment genuinely is the blocker. `--preset` is **not** hoisted, because validating the name early would be a second copy of the membership check `apply_preset` already owns. | 15, 24 |
| The test suite could not see it, because it was reading the developer's `.env` | **`test_a_malformed_bbox_is_refused_with_the_reason` pins exactly the right behaviour in six parametrisations, and all six passed here and failed in CI.** `_clean_data_dir_env` deletes `DATA_DIR` from the environment and stops — then `Settings.load` calls `load_dotenv()`, whose upward search starts at `src/lczkit/config.py`, finds the repository's own `.env` and puts it straight back. The fixture guarded the variable and not the file, and its docstring claimed a guarantee the CLI tests cannot honour, since they invoke `app` and cannot pass `dotenv_path`. **The repository already knew the answer and had applied it once** — `test_a_missing_data_dir_is_a_message_and_not_a_traceback` neutralised `load_dotenv` inline, with a docstring explaining precisely this — and never made it the default. Now autouse, so every test says what it depends on. Third instance: **agreeing with your machine is not passing.** | 0, 15, 21, 22, 24 |
| LCZ 7 and LCZ 8 swapped on building size | **Measured in Phase 25 and internally contradictory, so no reference is needed to call it wrong.** LCZ 8 (*large* low-rise) lands on cells of 55-93 m² footprints and LCZ 7 (*lightweight* low-rise) on cells of 7 000-13 000 m² sheds, ratio 0.01-0.06 across Berlin, Istanbul, Bogotá and Nairobi. Structural, not tuning: a big flat warehouse is LCZ 7's box on two of three weighted dimensions, a dense informal settlement is LCZ 8's, and **no box mentions building size**. `mean_building_area_m2` has been computed since Phase 5 and never reached the metric — Phase 14 found the omission, Phase 25 measured the cost. It predicts Phase 6.7's LCZ 8 at 0.0% and Phase 13's LCZ 7 at 8.2% from the prototype table alone; the latter was attributed to Overture coverage, which is at most half of it. Added as an lczkit-owned dimension at **weight 0.0 in every preset**, pending a sweep. | 5, 6.7, 13, 14, 25 |
| `Hr` and `aspect_ratio` treated as independent dimensions | **They share an input and always have.** `Hr` carries weight 6 of 17 and is also `momepy.street_profile`'s numerator for H/W, weight 3 — so a height error moves **53%** of the built metric, not the 35% the `Hr` weight alone suggests. Every error budget this project has written assumed independence. Now derived into the manifest from `PropertySpec.reads_building_height` rather than stated, so a new dimension or preset updates it. | 3, 5, 9, 10, 25 |
| Areal height tiers assumed to preserve within-unit spread | **They compress it, which is Phase 10's mechanism running backwards.** Median CV 0.266 for real Overture heights in Berlin against 0.192 for WSF-3D in Nairobi and **0.112** for GHS-BUILT-H in Bogotá, where 23.6% of units carry a single height throughout. Phase 10 rejected Open Buildings for spread of 0.441 against reality's 0.195; what shipped has too little, and `Hr` is a geometric mean, so compression biases it up. Reported per run in `manifest.height_dispersion`, which is also the target the deferred shrinkage work aims at. | 10, 25 |
| LCZ 7 blamed on Overture coverage of informal settlements | **At most half of it — the rest is arithmetic.** LCZ 7's box wants H/W 1-2 *with* `Hr` 2-4 m, i.e. canyon widths of **1-4 m**, which neither a 100 m cell nor Overture's street network contains. H/W is satisfied by 1.4-2.2% of built cells for LCZ 7 against 40.2-70.0% for LCZ 8. Perfect footprints would not fix it. Phase 13's finding stands as a coverage result; its causal attribution does not. | 13, 25 |
| A network-free canyon ratio as the H/W fix | **Tested and refuted as a straight substitution, recorded so it is not retried.** `H/W = λf/(1−λp)` with `λf = λp·Hr/√A_bldg` gives Berlin 0.14 and Istanbul 0.27 against momepy's 0.35 and 0.53 — *worse* over the whole built set, though better on the densest decile (Bogotá 0.35 → 1.24). The relation is sound; the whole-sample deficit is in `Hr`, not in the width. | 25 |
| Grid, enclosure and patch units treated as rivals | **Complementary, and the difference is measurable.** A canyon has to be measured against streets and a grid cell is bounded by none: `aspect_ratio` is null on **10.8%** of one Istanbul extent's built grid cells against **0.9%** of its enclosures, and on the densest decile enclosures put 82.2% of cells inside LCZ 2's published H/W band against the grid's 70.2%. An enclosure remains the wrong *classification* unit — a block, not a patch, rejected three times correctly — and is the better *measurement* unit. `UcpConfig.measure_on` exposes the split, default `"units"`, no accuracy claim, sweep pre-registered. | 6.5, 9, 11, 17, 25 |
| `patch_max_area_m2` as a ceiling on a unit | **It was a merge guard wearing a ceiling's name.** It refused to combine two seeds into something oversized and could not divide a seed already over it — and enclosure seeds routinely are, a face bounded by nothing but the study edge being as large as the unmapped ground it covers. Istanbul: 807 patches over the 50 ha setting holding **72.7% of the extent**, largest 1 072.7 km², one 98 km² unit holding 1 310 buildings at uniqueness 0.12. Oversized seeds are now split before merging, by a grid cut that needs no building layer and preserves area exactly. | 17, 25 |
| No minimum mapping unit anywhere in the package | Every unit is classified independently of its neighbours, so an isolated 1 ha cell can carry a label the fabric around it does not — salt-and-pepper at a grain Stewart & Oke never intended, given a So2Sat patch is 320 m. A spatial filter is standard in this literature and the LCZ Generator applies one. `ClassificationConfig.modal_filter` ships **off**, because its threshold has not been swept and **every stored figure in this project was measured without one**. A functionally assigned label is never smoothed away. | 6, 13, 25 |
| The metric's per-class geometric prior | Unreported until Phase 25, and uneven: LCZ 2 claims **38.8%** of the reachable parameter cube against LCZ 8's **3.4%**, before any city is seen. Not a defect — the classes are genuinely different sizes in UCP space — but per-class recall is not comparable across classes without it. Also checked and **contrary to intuition**: the built boxes are essentially disjoint on the three weighted dimensions, only 3~7 overlapping, so there is no pervasive tie problem. And **the confusion axes fall out of the box geometry alone** — dropping `Hr` ties {2,3}, {2,7}, {3,7}, {5,6}; dropping `aspect_ratio` ties {3,8}, {6,8}. | 6, 9, 12, 25 |
| `units.aggregate` read as excluding nulls from its weight | **It does not**, and a test written to check the design caught it before it shipped. `groupby.sum()` skips a null in the numerator while the denominator stays the *total* overlap area, so a null piece drags the mean toward zero — harmless where every column is populated, wrong for `aspect_ratio`, which is null exactly where no street reached a building. `transfer_parameters` weights per column over the pieces that carried a value; `aggregate` is untouched, since its normalisation is what every stored arm-B projection used. | 2, 12, 25 |
| CI red on `master`, and red before the cleanup pass too | Checked rather than assumed, by running the same test against an extracted `38bce20`: **identical failures, so this predates the nine commits and is not their regression.** The Actions API gives the fuller picture: **4 CI runs in the repository's history, all `push`, all after Phase 20 fixed the trigger, all failed** — this repository has never had a green CI run, and before Phase 20 it had none at all. **A gate turned on after the fact reports the past, not just the future**, and the first thing it says is usually not about the change that turned it on. | 20, 24 |
| `EarthEngineSource` protocol-correct, measured against its acceptance criterion, and unreachable | **Sixth instance of "the capability exists and the seam does not", and the least visible one** — here the code *and* the live measurement existed; `run_pipeline` simply named `LocalRasterSource` outright, so setting `GEE_PROJECT_NAME` did nothing to a run. `LandCoverConfig.source` and `--land-cover-source` select it, default `"local"`, and `pipeline.land_cover_source` is the single dispatch. The two backends are schema-identical and **not** bit-identical — `exactextract` area-weights each cell, `reduceRegions` counts whole pixels by centre, a single percent on a 100 m unit's boundary ring — so the field records which one answered. | 4, 15, 27 |
| `RunPreset.apply` cleared `gee_project` | It replaced the whole `land_cover` section with the preset's copy, whose value is `None`, so every run discarded what `Settings.load` had just read from `GEE_PROJECT_NAME` — **all 24 manifests on disk record it as null**, and the discard reproduces directly against unmodified code. The same silent-discard failure `Settings.load` documents in the other direction, one layer up, and invisible for exactly as long as nothing downstream read the field. Preserved on the copy; precedence is preset, then environment. Consequence written down rather than left to be found: the value now reaches every manifest and any site built from one, which is designed behaviour, since a Google Cloud project ID names a tenancy and authorises nothing — unlike `maptiler_key`, which is `exclude=True` because it does. | 4, 15, 21, 27 |
| Is there an Earth Engine route for the height tiers? | **One of the two, and not the one that matters — checked against the catalogue rather than assumed.** GHS-BUILT-H is `JRC/GHSL/P2023A/GHS_BUILT_H/2018` band `built_height`; `projects/earthengine-public/assets/DLR/WSF` lists exactly one child, `WSF2015/v1`, a 10 m settlement mask and not a height product, and WSF-3D answers for 92–99% of building area. And GHS-BUILT-H would be a **second route to identical numbers**: sampled twice against the tiles this package downloads, on different tiles and strata — 180 points and then 80 — max and mean |Δ| **0.000000 m** both times. The name could not settle that — GHSL publishes ANBH beside gross AGBH and neither the asset ID nor its metadata says which the band carries. Both tiers stay on HTTP; the asymmetry with land cover is documented in `sources.height_products` rather than left looking like an oversight. Open Buildings 2.5D is Earth Engine-only because it has no public bucket, and is off by default on measurement. | 3, 10, 11, 27 |
| `land_cover.max_raster_cells` unreachable from a run | The stage built `LocalRasterSource(dataset, worldcover)` without it, so the configured ceiling never applied and only the constructor default did. **The two happen to be equal at 200 000 000**, which is why nothing noticed — the same shape as the twin `CLEANING` constants, where agreeing today is what hides the second definition. | 4, 15, 27 |
| Does GeoClimate's SVF need a DSM? | **No — vector-only, checked from the documentation and the methods paper rather than the source, and the answer is the opposite of what a feature checklist invites.** GeoClimate computes `GROUND_SKY_VIEW_FACTOR` from building footprints alone: H2GIS `ST_SVF`, 100 m rays in 60 directions, sample points scattered over free ground at 0.008 pt/m², with Bernard et al. (2018) cited for those settings — Bernard et al. (2024), `10.5194/gmd-17-2077-2024`, Table 1, p. 2081, and [RSU indicators](https://geoclimate.readthedocs.io/en/latest/RSU-indicators.html), "only buildings are considered as obstructing the atmosphere". The same paper states what that excludes, p. 2084: "SVF does not take into account vegetation nor elevation". So **no auxiliary raster separates the two tools**, and the deferred note's "no DSM required" of Bernard 2018 is exactly the route GeoClimate already takes. The gap is real and it is in what lczkit *builds*, not in the data it has; the README and landing page say so rather than leaving cost as the only stated reason. **Caught while checking it:** `prototypes.UNUSED_PROPERTIES` called SVF's weight of 4 "second only to building surface fraction" — it is **third**, behind `FB` 8 and `Hr` 6 (p. 2085), which `weights.py` has encoded correctly all along. That string is serialised into every run's manifest and was published in both committed demo sites; corrected in all four places by re-deriving from the live constant. | 5, 6 |

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
normalised vocabulary at all)

*(**The LCZ 7 and LCZ 8 calibration sweeps were removed from this list in Phase 28**, run on
explicit request. LCZ 8's rule is calibrated and enabled; LCZ 7's is refused on measurement. The
"needs a city where the class exists *and* is tagged" caveat was correct and is now measured: of
eight cities, the three carrying tags carry no LCZ 7 and the five carrying LCZ 7 carry almost no
tags.)*

**The `mean_building_area_m2` weight sweep** pre-registered in Phase 25 is still outstanding, and
is a different measurement from the rule sweep above: it moves the metric rather than a rule, and
Phase 28 measured that the LCZ 8 rule does **not** close the size inversion — a semantic rule can
only add LCZ 8, never remove it, so the small-footprint cells the metric wrongly calls LCZ 8 are
untouched.

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
- Don't inline data into `index.html` or link a CDN. The **default** site must open with no network
  and no software the user must install, and remain valid years from now. It is served by its own
  bundled `serve.py` over loopback — `file://` is not satisfiable, because PMTiles reads byte ranges
  through `fetch` and the Fetch standard leaves `file:` URLs unhandled. Every built site carries a
  `README.md` saying so, since the first thing a recipient tries is opening `index.html` and it
  fails with an unexplained network error. **"Or use a basemap requiring an API key" was struck in
  Phase 21 by explicit request** — MapTiler is opt-in, off by default, and its key is confined to
  `style.json` by a test; the default build still names no remote host anywhere.
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
- **A parameter the package computes but the metric never reads is not a spare column — it is a
  dimension the classification is blind on.** `mean_building_area_m2` shipped from Phase 5 and
  reached nothing, and the two classes it would have separated came out *inverted* in every city:
  "large low-rise" on 55-93 m² footprints, "lightweight low-rise" on 7 000-13 000 m² sheds. Phase 14
  found the omission by reading the metric's structure and left it there. When a registry documents
  a column no consumer reads, ask what would be different if it were read.
- **Check whether two metric dimensions share an input before treating their weights as
  independent.** `Hr` is weight 6 and is also H/W's numerator at weight 3, so a height error moves
  53% of the built metric and not 35%. Nothing in the code said so and every error budget assumed
  otherwise; it is one `grep` for what a function is passed.
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
- **A correct file is not a readable file, and correctness is not what the recipient measures.**
  Twice now an artefact has been formally right and unopenable: the site's PMTiles over `file://`,
  and `units.parquet` in a QGIS whose GDAL lacks the *optional* Parquet driver. Both report as a
  defect in the producer — an unexplained network error, a layer "with no CRS" — because the
  recipient cannot see which half failed. Ship the format whose reader is unconditional, and when a
  capability is conditional in the consumer, do not treat validity in the producer as the test.
- **A derived property has to be recorded somewhere the derivation is not.** The run CRS comes from
  `estimate_utm_crs()` on the extent, so it is in no config, no preset and no argument — and it was
  in no manifest either, leaving a run directory unable to state its own CRS except through the one
  file format the reader could not open. Anything computed at runtime that a consumer must know is
  a manifest field, not an implicit property of an artefact.
- **A check that never runs is indistinguishable from a check that passes.** `ci.yml` triggered on
  a `main` branch that has never existed in this repository — the *remote* is named `main`, the
  branch is `master` — so from Phase 0 it fired only on pull requests, and a `ruff format --check`
  failure sat in the tree unseen. Before trusting a gate, confirm it has actually run: a green
  history and an empty history look the same from the outside.
- **Prefer a structure that cannot hold the bad state over a rule that forbids it.** The MkDocs
  `docs_dir` is `docs_src/` and not `docs/`, because `docs/` holds 205 MB of gitignored reference
  PDFs and one `mkdocs gh-deploy` from a working tree would publish them. An `exclude_docs` rule
  would have worked and would have had to keep working, silently, forever. Same shape as the two
  `CLEANING` constants: the fix is to remove the opportunity, not to document it.
- **Check whether a generator can recover what the source omits, before relying on it.** Ten
  members were undocumented because their contract lives on a Protocol, which looks like something
  `inherited_members` fixes — except the implementations satisfy the Protocols *structurally* and
  subclass nothing, so there is no base to inherit from and the page would have rendered blank. The
  question "will the tool fill this in?" has an answer that is cheap to test and expensive to
  assume.
- **A tool's idea of which files it owns may not be yours.** `ruff format` reads Python fences
  inside Markdown and `ruff check` does not read `.md` at all, so one committed reference
  transcription was a standing format failure that no lint run would ever mention. When adding a
  formatter or linter to a repository, look at what it actually globbed, not at what it is for.
  **Second instance, and it moved a file rather than just complaining about one:** mkdocs-jupyter's
  default `include` is `["*.py", "*.ipynb", "*.md"]`, so a copied map site's `serve.py` was
  rendered as a notebook page and relocated out from under the relative path that loads it.
- **A whole execution environment can be unsupported without a single test noticing.**
  `OvertureSource` could not be constructed inside a Jupyter kernel from Phase 1 to Phase 22,
  because a cosmetic `SET enable_progress_bar = false` raises there when `ipywidgets` is absent.
  Under pytest there is no kernel, DuckDB draws nothing, and the assignment succeeds — so the
  entire suite agreed the code was fine. Where a defect is a property of the *host* rather than of
  the inputs, the only thing a test can check is the source, and that is worth doing.
- **A test that can read the developer's `.env` is not testing a clean checkout.** Deleting the
  variable is half the guard: `load_dotenv()` searches *upward from the module that calls it*, so
  from anywhere inside a checkout it finds the repository's own `.env` and restores what the
  fixture just removed. Six tests pinning the right CLI behaviour passed here and failed in CI for
  that reason, hiding a real defect for as long as they did. Neutralise the loader, not just the
  variable — and note the failure is one-directional: the machine with the `.env` is the one that
  cannot see the problem, so "it passes locally" is the symptom rather than the reassurance.
- **Pin the kernel before believing a notebook.** A probe written to diagnose the above reported
  the opposite of the truth, because `jupytext --execute` with no kernel named silently chose one
  from a different environment with different package versions. `kernelspec` is the notebook's
  equivalent of which interpreter is on `PATH`, and it is not visible in the output.
- **Never edit a source file while a tool is reading it.** jupytext refused to write a notebook
  with `SynchronousModificationError` after the percent script it was executing changed mid-run —
  which is the good outcome, since the alternative is outputs silently attributed to source that
  never produced them. Queue the edit; do not race the run.
- **A document embedded in another renderer keeps its own renderer's rules.** mkdocs' Markdown
  extensions do not reach a notebook's markdown cells — nbconvert has already turned them into
  HTML by the time mkdocs sees the page — so `!!! note` ships as literal text and a `.md` link
  ships unrewritten. The same boundary that makes `execute: false` safe is the one that excludes
  the extensions, and it is easy to assume it runs only one way.
