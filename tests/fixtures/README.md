# Test fixtures

## `overture/`

A real ~3x3 km Overture extract for central Berlin (Mitte — spans the Spree river, Museum
Island, and Alexanderplatz), release `2026-07-22.0`, built by `scripts/build_overture_fixture.py`.
Five raw, uncleaned, EPSG:4326 GeoParquet layers: `buildings.parquet`, `streets.parquet`,
`rail.parquet`, `waterlines.parquet`, `waterbodies.parquet`. `rail.parquet` was added in Phase 2
for `EnclosureUnits`' barrier set (201 features in the full extent, 8 within `SMALL_BBOX`).
Re-run that script to refresh the fixture (e.g. against a newer release).

This bbox has **not** been cross-checked against official DFC2017 tile boundaries — it was
chosen as a real, feature-dense Berlin extract sufficient for Phase 1's cleaning-pipeline
tests. Phase 6 (validation against the Demuzere global LCZ map / DFC2017 ground truth) should
confirm alignment before relying on it for accuracy reporting, not just structural testing.

Land-cover raster fixture is still deferred to Phase 4. See CLAUDE.md's "Test strategy"
section.
