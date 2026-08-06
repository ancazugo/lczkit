# Test fixtures

## `overture/`

A real ~3x3 km Overture extract for central Berlin (Mitte — spans the Spree river, Museum
Island, and Alexanderplatz), release `2026-07-22.0`, built by `scripts/build_overture_fixture.py`.
Six raw, uncleaned, EPSG:4326 GeoParquet layers: `buildings.parquet`, `streets.parquet`,
`rail.parquet`, `waterlines.parquet`, `waterbodies.parquet`, `land_use.parquet`.
Re-run that script to refresh the fixture (e.g. against a newer release).

- `rail.parquet` was added in Phase 2 for `EnclosureUnits`' barrier set (201 features in the
  full extent, 8 within `SMALL_BBOX`).
- `buildings.parquet` carries `subtype` and `class` (usage type) alongside `height`,
  `num_floors` and `sources`. Only 1595 of 6195 footprints have a `height` and 3886 a
  `num_floors` — sparse heights are a real property of the data, and the fixture is the place
  that keeps the Phase 3 cascade honest about it.
- `land_use.parquet` (1559 polygons) supplies functional semantics for Phase 5's
  `industrial_fraction`. **Its geometries are clipped to the fixture bbox**, unlike every other
  layer: two region-scale `protected` boundaries merely grazed the bbox and carried 355k of the
  layer's 393k vertices, taking the committed tree past 8 MB on their own. `OvertureSource`
  itself does not clip — this is a property of the fixture, per CLAUDE.md's instruction to clip
  an oversized fixture rather than move it out of the repo.

This bbox has **not** been cross-checked against official DFC2017 tile boundaries — it was
chosen as a real, feature-dense Berlin extract sufficient for Phase 1's cleaning-pipeline
tests. Phase 6 (validation against the Demuzere global LCZ map / DFC2017 ground truth) should
confirm alignment before relying on it for accuracy reporting, not just structural testing.

Land-cover raster fixture is still deferred to Phase 4. See CLAUDE.md's "Test strategy"
section.
