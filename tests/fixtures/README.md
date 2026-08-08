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
tests. Phase 6 validates against the Demuzere global LCZ map (see `lcz/` below) rather than
against DFC2017 ground truth, so tile alignment has not become load-bearing.

## `overture_industry/`

A real ~2.7x2.2 km Overture extract over Rotterdam's Waalhaven, same release and same six layers,
built by `scripts/build_industry_fixture.py`. Added in Phase 6.

It exists because **the Berlin fixture cannot validate the LCZ 8 / LCZ 10 rule.** Mitte holds 36
industrial buildings of 6195 and 2 industrial land-use parcels of 1559 — enough to exercise the
plumbing, nowhere near enough for the discrimination to be observable, and
`test_ucp_integration.py` asserts that smallness so a green suite is not mistaken for evidence.
Rotterdam holds **259 industrial buildings of 1681 and 17 industrial parcels of 157**, which is
what makes the rule testable at all.

Rotterdam was chosen by measurement. Duisburg-Bruckhausen has more industrial buildings in
absolute terms (152) but 7163 residential ones alongside them — a mixed district, not an
industrial one — and Houston's ship channel is barely tagged (5 industrial buildings). Rotterdam
is the only candidate carrying both evidence sources, and therefore the only one that exercises
the `both` branch of `industrial_evidence`. Within Rotterdam, the Waalhaven basin was preferred
over the Botlek petrochemical complex: Botlek is the truer LCZ 10 landscape but carries only 33
industrial buildings against 44 parcels, and building evidence is the scarcer of the two in most
cities.

`land_use.parquet` is clipped to the bbox for the same reason Berlin's is.

## `landcover/`

Three real 10 m global products clipped to the fixture bboxes, built by
`scripts/build_landcover_fixture.py`. All EPSG:4326 uint8, ~36 KB in total.

- `worldcover_berlin.tif` — ESA WorldCover v200 (2021), nodata 0, 530x324. Holds classes 10, 30,
  40, 50, 60 and 80; 82% of the tile is class 50 (Built up).
- `eth_canopy_berlin.tif` — ETH global canopy height (2020), nodata 255, 530x324. **78% of this
  tile is nodata**: Lang et al. mask built-up areas, snow, ice and permanent water out of the
  product and set them to 255 rather than reporting zero canopy there, so 93% of the cells
  WorldCover calls built up, and 93% of the water, come back as nodata. That is why
  `LandCoverDatasetConfig.nodata_policy` exists, and `tests/test_landcover_fixture.py` asserts the
  difference it makes. Note that Lang et al. define that mask *from ESA WorldCover*, so these two
  fixtures are not independent measurements of the same ground.
- `worldcover_rotterdam.tif` — ESA WorldCover v200 (2021), nodata 0, 480x240, over the industry
  fixture. No canopy counterpart: the ETH product is a second, competing tree estimate that Phase 4
  documents as reading high, and tree cover is beside the point for the LCZ 8/10 rule.

Unlike the Phase 3 height rasters — synthesised in-test, because no tier 2-4 product exists
anywhere to clip — these are committed, because a real product does exist and the clip is small.
That is what CLAUDE.md's test strategy asks for.

## `lcz/`

The Demuzere global LCZ map clipped to both fixture bboxes, built by
`scripts/build_lcz_reference_fixture.py`. EPSG:4326 uint8 at ~100 m, nodata 0, ~3 KB each.

- `lcz_reference_berlin.tif` — 49x30, holding classes 1, 2, 4, 5, 6, 8, 10, 11, 12 and 15.
- `lcz_reference_rotterdam.tif` — 45x22, holding classes 1, 4, 5, 6, 8, 9, 10, 12, 14 and 17.
  Note that the reference map itself puts **LCZ 10 (heavy industry)** in this extent, which is what
  makes it a target the industry fixture can be judged against rather than merely compared to.

Both carry the product's own GDAL colormap, which is the authority
`docs/references/tables/demuzere_2022_lcz_codes.md` was transcribed from — so the transcription
stays checkable on a clean checkout with no `DATA_DIR`.

Unlike the other fixture scripts, this one reads from `DATA_DIR` rather than over HTTPS: the global
map is a 1.8 GB COG already present on this system under `input/`. It is read only; nothing there
is created, modified or deleted.

**The clipped copy is version 3 of the map**, while the Tier 1 citation below describes an earlier
version. A run manifest records the file and the citation separately rather than conflating them.

### `so2sat_berlin.parquet` — the ground truth, added in Phase 6.7

473 hand-labelled So2Sat LCZ42 (v4) patches intersecting the Berlin fixture bbox, EPSG:4326, 34 KB,
built by `scripts/build_so2sat_fixture.py` from the copy under `input/So2Sat-LCZ42/`. Columns
`patch_id`, `dataset`, `LCZ_class`.

**This is the primary validation reference for Berlin**; `lcz_reference_berlin.tif` is a secondary
comparator. Phase 6.7 exists because validation had been treating the latter as ground truth — it
is a model output with its own error, and measured against these labels it is right **53.2%** of
the time, which bounds any score against it.

Three properties that the reduction in `lczkit.validation.labelled` depends on:

- **Patches are 320 m squares on a 100 m stride**, so they overlap each other roughly sevenfold:
  48.4 km² of patch area over a 7.1 km² union inside this bbox, 16,560 overlapping pairs. Labels
  are therefore anchored on the patch **centre**, never overlaid areally.
- **Geometries are stored unclipped**, unlike `land_use.parquet` above. Clipping a patch at the
  bbox edge would move its centroid, and the centroid is what decides which cell the label lands
  in. Patches whose centre falls outside the study area simply contribute nothing.
- **Centres map 1:1 onto the 100 m grid** — 438 centres into 438 distinct cells, none ambiguous —
  because the So2Sat patch grid and `GridUnits` are both aligned to the local UTM origin.
  `tests/test_validation_labelled.py` asserts this rather than assuming it.

The labels here cover 438 of the fixture's 964 cells and hold only **LCZ 2 (332) and LCZ 5 (106)**,
where `lcz_v3` claims six classes over the same ground. That narrowness is why
`scripts/berlin_wide_validation.py` exists — it is not committed and not run in CI.

Rotterdam has no counterpart: So2Sat covers 52 cities and Rotterdam is not one of them (Amsterdam,
60 km away, is the nearest). The industry fixture stays on `lcz_v3` and every figure derived from
it carries that limitation.

## Licensing

All committed raster fixtures are **CC-BY-4.0** and are redistributed here under that licence:

- ESA WorldCover 10 m 2021 v200, © ESA WorldCover project 2021 / Contains modified Copernicus
  Sentinel data (2021) processed by ESA WorldCover consortium. `10.5281/zenodo.7254221`.
- Lang, N., Jetz, W., Schindler, K., Wegner, J. D. (2023), *A high-resolution canopy height model
  of the Earth*, Nature Ecology & Evolution 7, 1778-1789. `10.1038/s41559-023-02206-6`.
- Demuzere, M., Kittner, J., Martilli, A., Mills, G., Moede, C., Stewart, I. D., van Vliet, J.,
  Bechtel, B. (2022), *A global map of Local Climate Zones to support Earth system modelling and
  urban-scale environmental science*, Earth System Science Data 14, 3835-3873.
  `10.5194/essd-14-3835-2022`.
- Zhu, X. X. et al. (2020), *So2Sat LCZ42: A Benchmark Data Set for the Classification of Global
  Local Climate Zones*, IEEE Geoscience and Remote Sensing Magazine 8(3), 76-89.
  `10.1109/MGRS.2020.2964708`. Fourth version, via mediaTUM `1836598`.

The Overture extracts are from Overture Maps Foundation data, which carries the licences of its
upstream sources (ODbL for OSM-derived features, CDLA-Permissive-2.0 for the ML-derived ones).
