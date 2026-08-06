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

## `landcover/`

Two real 10 m global products clipped to the same bbox as the Overture extract, built by
`scripts/build_landcover_fixture.py`. Both are EPSG:4326 uint8, 530x324, and total ~31 KB.

- `worldcover_berlin.tif` — ESA WorldCover v200 (2021), nodata 0. Holds classes 10, 30, 40, 50,
  60 and 80; 82% of the tile is class 50 (Built up).
- `eth_canopy_berlin.tif` — ETH global canopy height (2020), nodata 255. **78% of this tile is
  nodata**: Lang et al. mask built-up areas, snow, ice and permanent water out of the product and
  set them to 255 rather than reporting zero canopy there, so 93% of the cells WorldCover calls
  built up, and 93% of the water, come back as nodata. That is why
  `LandCoverDatasetConfig.nodata_policy` exists, and `tests/test_landcover_fixture.py` asserts the
  difference it makes. Note that Lang et al. define that mask *from ESA WorldCover*, so these two
  fixtures are not independent measurements of the same ground.

Unlike the Phase 3 height rasters — synthesised in-test, because no tier 2-4 product exists
anywhere to clip — these are committed, because a real product does exist and the clip is small.
That is what CLAUDE.md's test strategy asks for.

Both are **CC-BY-4.0** and are redistributed here under that licence:

- ESA WorldCover 10 m 2021 v200, © ESA WorldCover project 2021 / Contains modified Copernicus
  Sentinel data (2021) processed by ESA WorldCover consortium. `10.5281/zenodo.7254221`.
- Lang, N., Jetz, W., Schindler, K., Wegner, J. D. (2023), *A high-resolution canopy height model
  of the Earth*, Nature Ecology & Evolution 7, 1778-1789. `10.1038/s41559-023-02206-6`.
