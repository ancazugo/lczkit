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
`neatnet`, cross-layer topology cleanup, and a structured cleaning report.

No spatial-unit generation, height cascade, land cover, or classification exists yet.

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
