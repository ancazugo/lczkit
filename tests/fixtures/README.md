# Test fixtures

**`overture_hongkong/` is the primary fixture** from Phase 11. `overture/` (Berlin) remains, and
every figure recorded before Phase 11 is against it, but it is no longer the one a new diagnostic
should be run on — see below for why.

## `overture_hongkong/` — the primary fixture, added in Phase 11

A real ~3x3 km Overture extract over Kowloon, Hong Kong, release `2026-07-22.0`, built by
`scripts/build_overture_fixture.py`. Same six layers as `overture/`: 5448 buildings, 5252 streets,
29 rail, 37 waterlines, 15 waterbodies, 1754 land-use polygons, 2.4 MB in total.

**It exists because the Berlin fixture cannot test the height confusion axis.** Berlin's labelled
cells hold LCZ 2 and LCZ 5 — two classes, and both mid-rise — so 1↔2↔3 and 4↔5↔6 have no pair to
confuse on and the axis is untestable there by construction. Phase 6.7 ranked the axes from that
fixture anyway and put compactness first; the ranking stood for three phases until Phase 9 reversed
it across fifteen cities, where height dominates roughly three to one. A fixture that cannot measure
something is not neutral about it.

This window's labels hold **LCZ 1, 2, 3, 4 and 5** — compact high, mid and low-rise beside open
high and mid-rise — so both axes have pairs: height 1↔2↔3 and 4↔5, compactness 1↔4 and 2↔5.
`tests/test_validation_labelled.py` asserts that property rather than describing it.

Chosen by search, not by eye: every ~3–4 km window in Hong Kong was scored against the So2Sat
patches for classes carrying at least ten patches, under a footprint budget that keeps the
committed tree near Berlin's size. **Hong Kong's thirteen classes are a property of the 30 km
validation window** used in Phases 9–11; no 3 km window anywhere in the city holds more than six.

Two differences from `overture/`, both recorded in `TARGETS` in the build script:

- **`waterbodies.parquet` is clipped to the bbox**, as `land_use.parquet` is in both fixtures.
  Nineteen unclipped sea polygons carried 237k vertices and 3.7 MB — 62% of the fixture — for
  ground that is almost entirely outside it. Which layers are clipped is a property of each
  fixture, so rebuilding Berlin still reproduces Berlin.
- **`buildings_area` retains 98.40% of the *summed* raw footprint area here, against Berlin's
  99.49%**, and that is not attrition: no feature is dropped (5449 → 5449) and the whole difference
  is `trim_overlaps`. Hong Kong's raw Overture footprints **double-count 7.52% of their own summed
  area** (2 113 744 m² summed against 1 954 770 m² of ground) versus Berlin's 0.61% —
  podium-and-tower stacks and conflated duplicates — and building surface fraction sums overlay
  pieces, so leaving that in would inflate the numerator.

  This fixture is why Phase 12 restated the criterion against the **union** of raw footprints: a
  city whose sources overlap themselves by more than 1% cannot meet a ≥99%-of-sum bar without
  keeping double-counted area, so the sum-based criterion and "trim overlaps but do not merge" were
  jointly unsatisfiable here. `raw_self_overlap_fraction` is now reported in its own right — it is a
  source-quality signal, not just a denominator correction. Berlin cannot exercise any of this,
  which is why the union tests live against synthetic geometry in `test_cleaning_buildings.py`.

The window carries no natural class, so it gets WorldCover but no ETH canopy clip, for the same
reason Rotterdam does not have one.

## `overture/`

The Phase 0 fixture, and the primary one until Phase 11 replaced it with Kowloon above. Retained:
every figure in this project between Phases 1 and 10 was measured against it, and dozens of tests
assert its counts.

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

Four real 10 m global products clipped to the fixture bboxes, built by
`scripts/build_landcover_fixture.py`. All EPSG:4326 uint8, ~43 KB in total.

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
- `worldcover_hongkong.tif` — ESA WorldCover v200 (2021), nodata 0, 343x330, over the primary
  fixture. No canopy counterpart either: that window's labels carry no natural class at all.

Unlike the Phase 3 height rasters — synthesised in-test, because no tier 2-4 product exists
anywhere to clip — these are committed, because a real product does exist and the clip is small.
That is what CLAUDE.md's test strategy asks for.

## `lcz/`

The Demuzere global LCZ map clipped to every fixture bbox, built by
`scripts/build_lcz_reference_fixture.py`. EPSG:4326 uint8 at ~100 m, nodata 0, ~3 KB each.

- `lcz_reference_hongkong.tif` — 32x31, holding classes 1, 2, 3, 4, 5, 6, 8, 10, 11 and 12. Ten
  classes where So2Sat labels five over the same ground, which is a statement about the comparator
  rather than about the city: `lcz_v3` reaches 57.2% against those labels here.
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

### `so2sat_hongkong.parquet` — the primary ground truth, added in Phase 11

169 hand-labelled So2Sat LCZ42 (v4) patches intersecting the Hong Kong fixture bbox, EPSG:4326,
18 KB, built the same way and with the same columns as the Berlin file below.

They cover **152 of the fixture's 959 cells and hold LCZ 1 (14), 2 (56), 3 (15), 4 (76) and 5 (8)**
— the five built types that make both confusion axes measurable. The 1:1 centre-to-cell alignment
Berlin has holds here too, on a second continent and a second UTM zone, because it is a property of
anchoring both grids on the local UTM origin rather than a property of Berlin.

Against these labels, arm A reaches 23.7% over 152 cells with a `lcz_v3` ceiling of 57.2%, and its
disagreement splits **18.1% height / 27.6% compactness** — against Berlin's 17.0% / 55.2%. That is
not a reversal: compactness still leads, by 1.5x rather than 3.2x. Berlin's figure was structurally
inflated, because with only LCZ 2 and 5 in the reference the compactness pair 2-5 has both members
available to confuse while every height pair can contribute only the one member the reference
holds. Five classes put both axes on equal footing.

### `so2sat_berlin.parquet` — the ground truth, added in Phase 6.7

473 hand-labelled So2Sat LCZ42 (v4) patches intersecting the Berlin fixture bbox, EPSG:4326, 34 KB,
built by `scripts/build_so2sat_fixture.py` from the copy under `input/So2Sat-LCZ42/`. Columns
`patch_id`, `dataset`, `LCZ_class`.

**This is the validation reference for Berlin**; `lcz_reference_berlin.tif` is a secondary
comparator. Phase 6.7 exists because validation had been treating the latter as ground truth — it
is a model output with its own error, and measured against these labels it is right **53.2%** of
the time on this extent. That figure is a small-sample artefact of 432 cells: at Berlin's full
metropolitan window the same comparison is **75.2% over 9 627 cells** (Phase 9).

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
`scripts/berlin_wide_validation.py` exists — it is not committed and not run in CI — and, in the
end, why Phase 11 replaced this fixture as the primary one. Two classes at one height cannot
confuse on the height axis, so a diagnostic run here could only ever find compactness.

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
