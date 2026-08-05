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

- Install dependencies with **`uv add --active <package>`** only.
- Python environment is available in `/maps/acz25/envs/lczkit-env`
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
  │   ├── GHSL/
  │   └── ETH_CanopyHeight/
  └── output/
      └── lczkit/
          └── <run_id>/    # GeoParquet + manifest + cleaning report
  ```

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
modify anything under `input/`. Add `.env` and `docs/references/` to `.gitignore`; commit a
`.env.example`.

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
- `buildings/building` — geometry, `height`, `num_floors`, `sources`
- `transportation/segment` where `subtype = 'road'`, dropping `class = 'service'`
- `base/water` — split linestrings (waterlines) from polygons (waterbodies); filter out
  underground/aboveground features and subtypes `human-made`, `reservoir`, `spring`,
  `wastewater`

Cleaning pipeline for buildings: fix invalid geometries, explode multipolygons, drop
non-polygon features, drop implausibly large footprints (configurable threshold), merge and
trim overlapping footprints, absorb small buildings into adjacent larger ones. Use `geoplanar`
for planar enforcement.

Street simplification with `neatnet`, passing cleaned buildings as the exclusion mask. This is
required, not optional — unsimplified dual carriageways and roundabouts destroy enclosure
generation downstream.

Cross-layer topology: drop buildings intersecting streets or waterbodies; drop waterlines
passing through buildings.

Emit a **cleaning report** — a structured record of feature counts in and out of every
operation. Include it in the output manifest.

*Acceptance:* fixture city produces a valid, planar building layer and a simplified network;
cleaning report is populated; before/after counts are asserted in tests.

---

### Phase 2 — Spatial units (~2 days)

- `EnclosureUnits`: `momepy.enclosures()` with streets, rail, waterbodies and large vegetation
  patches as barriers. This is the GeoClimate RSU analogue.
- `GridUnits`: 100 m regular grid in the local UTM CRS. Mandatory — it is what every existing
  LCZ map, validation dataset, and WRF workflow uses.
- `aggregate(from_units, to_units, method)` supporting `"majority"` and `"area_weighted"`.

*Acceptance:* both strategies produce units with stable unique `unit_id`s; aggregation between
them round-trips sensibly on the fixture.

---

### Phase 3 — Height cascade (~4 days)

Two tiers in the MVP, but build the cascade machinery properly so tiers are trivial to add.

1. Overture `height`; else `num_floors × storey_height` (storey height **configurable**,
   default 3.0 m — it varies regionally and is a real error source)
2. GHS-BUILT-H zonal mean as fallback

Every building carries `height_source` (which tier fired) and `height_confidence`. Aggregate
to units as **`height_completeness`** — the area fraction of buildings with tier-1 heights.

`height_completeness` must appear in the final output. It is the honest answer to "should I
trust this map here" and is a primary deliverable of the package, not a diagnostic.

*Acceptance:* every building has a non-null height and a source tag; `height_completeness`
is computed per unit and present in the output schema.

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
- building surface fraction (coverage area ratio)
- aspect ratio and street openness via `momepy.street_profile()` with heights attached

Computed here:
- height of roughness elements — area-weighted mean and standard deviation of building height
- pervious / impervious / tree fractions from Phase 4
- building count, mean building area
- terrain roughness class from the Davenport lookup

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

**Output.** GeoParquet using LCZ Generator integer codes (1–10 built, 11–17 for A–G) and the
standard Demuzere colour table, so results drop into existing tooling. Plus a JSON manifest
containing the full serialised config, all source versions, and the cleaning report.

Also write a **viz-ready attribute table** (`units_viz.parquet`) alongside the GeoParquet:
floats rounded to three significant figures, the 17-way distance vector stored as scaled
integers, and precomputed classification breaks for every continuous variable written into the
manifest. This makes Phase 7 a pure transform of run outputs — the site build must never
recompute a parameter or a quantile.

**Validation module.** Agreement against the Demuzere global LCZ map on the 100 m grid,
reported lczexplore-style: per-class agreement and a confusion matrix, not a single accuracy
number. Comparability with the existing literature matters more than a headline figure.

*Acceptance:* end-to-end run on the fixture city produces a valid GeoParquet, `units_viz.parquet`
and manifest; validation module reports per-class agreement against the global map.

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

PDFs live in `docs/references/papers`. They are present on disk but **gitignored and not committed**
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
| Davenport et al. (2000), AMS 12th Conf. Applied Climatology | — | Phase 5 — terrain roughness class lookup |

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

## Deferred — do not build unless asked

Vector ray-cast sky view factor · roughness length and displacement height (Macdonald / Kanda)
· additional height tiers (UT-GLOBUS, GlobalBuildingAtlas, EUBUCCO, morphology-based ML
imputation) · ML classifier trained on So2Sat LCZ42 / DFC2017 · fuzzy or continuous LCZ output
· W2W / WRF export · OSM as an alternative `VectorSource` · tessellation-based building-level
units · dask-geopandas scaling · CLI · deck.gl overlay for buildings (only if MapLibre
`fill-extrusion` proves insufficient) · run-comparison views in the site

---

## Anti-patterns

- Don't optimise before the walking skeleton runs end to end.
- Don't add a dependency to save fewer than ~50 lines.
- Don't run `uv sync`, `uv venv`, `pip install`, or create a venv. `uv add --active` only.
- Don't read `os.environ` outside the config module, or build paths from `__file__` or `cwd`.
- Don't write data, caches, or downloads anywhere inside the repo. Everything goes under
  `DATA_DIR`, with `tests/fixtures/` as the sole exception.
- Don't write outside `output/lczkit/<run_id>/`, except for a source implementation adding new
  files under its own `input/<Source>/`. Never modify or delete an existing file in `input/` —
  it is shared with other projects.
- Don't commit anything from `docs/references/` or `.env`.
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