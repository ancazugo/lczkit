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
bbox-filtered GeoParquet from Overture's S3), the building-cleaning pipeline (invalid-geometry
repair, multipolygon explosion, oversized-footprint and non-polygon removal, overlap
resolution and small-building absorption via `geoplanar`), street simplification via
`neatnet`, cross-layer topology cleanup, and a structured cleaning report. Buildings retain
`subtype`/`class` (usage type) and `sources` (per-feature dataset provenance) through cleaning
— they are what later phases classify heavy industry and audit height coverage with. A
`land_use` layer is ingested and carried through with geometry repair only; it supplies
functional semantics to Phase 5 and is deliberately neither a spatial-unit barrier nor a
land-cover source.

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
waterbodies as barriers — large vegetation patches are not yet a barrier, since no land-cover
source exists until Phase 4), `GridUnits` (a 100 m regular grid aligned to the local UTM CRS's
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
  error concentrates on the LCZ pairs that differ mainly in height — 1↔4, 2↔5, 3↔6 — rather
  than scattering. In a city with low `height_completeness` that pattern is the data behaving
  as documented, not a bug. Phase 6's validation measures it directly.

No land cover, urban canopy parameters, or classification exist yet.

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
default.
