# Phase 10 — height cascade completion

Phase 3 specified a four-tier building-height cascade. Only tier 1 was ever built.

Not for want of code: `ArealRasterTier` and `build_cascade` have been complete and tested since
Phase 3, and `HeightConfig` has shipped inert entries for `gob25d`, `wsf3d` and `ghsl` the whole
time. What was missing was the **data**. Every areal tier was skipped at every run, for seven
phases, and nothing said so loudly enough to notice — a skipped tier looks exactly like a tier
whose product happens not to cover the study area.

Phase 9 measured what that costs. Tier-1 height coverage is 64.3% across Europe and North America
and 9.6% everywhere else; Cairo, Nairobi and Islamabad sit at 1%. Built-class agreement tracks
tier-1 coverage at r = 0.67. Where `Hr` is null nearly everywhere the distance metric runs on
building surface fraction alone, and the built types stop being separable *in principle* rather
than merely being classified inaccurately.

---

## 1. What was built

Three fetchers in `src/lczkit/sources/height_products.py`, each owning one directory under
`input/` the way `OvertureSource` owns `input/Overture_Maps/`.

| tier | product | access | grid / CRS | encoding | licence |
|---|---|---|---|---|---|
| 2 | Open Buildings 2.5D Temporal v1 | Earth Engine `GOOGLE/Research/open-buildings-temporal/v1` | 4 m effective (0.5 m raster), per-UTM-zone | `building_height`, float, metres, [0, 100] | CC-BY-4.0 |
| 3 | WSF-3D V02 Building Height | DLR, global 2.14 GB tiled COG with overviews | 2.8″ (~90 m), EPSG:4326 | int16, **gain 0.1**, nodata −32767 | CC-BY-4.0 |
| 4 | GHS-BUILT-H ANBH R2023A | JRC per-tile zips, `R{row}_C{col}` | 100 m, ESRI:54009 Mollweide | float32, metres, nodata 255 | free reuse w/ attribution |

Every one of those raster parameters is read from the product's own documentation, now in
`docs/references/datasets/` — the GHSL Data Package 2023 and DLR's `README_BuildingHeight.txt` —
rather than inferred from the files. The two that would have been silently wrong if guessed:

- **WSF-3D's 0.1 gain.** Heights are stored in decimetres. Read as metres, a ten-storey block
  becomes a kerbstone, every `Hr` collapses, and nothing downstream flags it.
- **ANBH, not AGBH.** GHSL publishes both. The Data Package (p. 26) defines
  `ANBH = BUVOL / BUSURF` — volume over *built-up* surface — against AGBH's volume over the whole
  cell. Only ANBH is the mean height of the built fabric; AGBH would report a sparsely built cell
  as uniformly low.

**A departure from the letter of Phase 3, stated rather than smuggled.** The spec has the *user*
place each product as a COG. That was written when tiers 2–4 were a specification; here it would
mean placing 27 windows by hand across nine cities and three products. The fetchers do it, under
the rule the spec states two sections earlier: writes to `input/` are confined to the source
implementation owning that subdirectory. Downloads land on a `.partial` sibling and are renamed
only when complete, so a truncated file can never be mistaken for a cache hit; nothing existing
under `input/` is modified or removed.

GHS-BUILT-H goes to a new `input/GHSL/`, per CLAUDE.md's diagram and the existing config default,
rather than into the `input/GHS/` that already holds GHS-SMOD and GHS-UCDB for other projects.

---

## 2. Two defects found while building, both invisible from the code

### 2.1 The GHS-BUILT-H tile grid is uniform; the tiles are not

Tile `R{row}_C{col}` is placed by simple arithmetic from a global origin, and nine of ten study
cities resolved correctly on the first attempt. Cape Town did not: the verification step reported
tile `R14_C20`'s upper-left corner at x = 1 559 000 where the grid put it at 959 000.

The grid is fine. **Tiles are cropped to their valid data extent.** `R14_C20` is 4000 × 3000 cells
rather than 10000 × 10000, because most of its nominal square is ocean outside the Mollweide world
ellipse; `R14_C19` is not published at all. The fix is that `_verify_tile_position` checks
*containment* in the nominal square rather than equality with its corner, and a 404 is read as
"this product has no data here" — the same statement a nodata cell makes.

Worth recording because of what the check bought. An origin wrong by one tile returns heights from
the wrong continent, all finite, all plausible, with no symptom anywhere downstream. The check was
written on the assumption it would never fire, and it fired on the fifth city.

### 2.2 Hong Kong's `orientationIndex` crash — Overture ships ocean-scale land use

Phase 9 lost Hong Kong to `GEOSException: IllegalArgumentException: CGAlgorithmsDD::orientationIndex
encountered NaN/Inf numbers` and recorded it as an unexplained robustness gap.

The cause: **two Overture `base/land_use` features are marine protected areas spanning the full
360° of longitude** — `species_management_area` polygons with bounds −180…180 that legitimately
intersect the Hong Kong window and so are correctly returned by the bbox filter. A UTM zone is 6°
wide. Projecting them into UTM 50N produced **663 non-finite coordinates out of 3 802**, and the
first operation to touch one — `make_valid()` in `clean_land_use` — died.

The repair is in `reproject_to_local_utm`: any feature whose projection is non-finite is clipped
back to the study extent and reprojected. Clipping rather than dropping, because the part inside
the study area is real and is the only part any statistic uses. It is recorded in the cleaning
report as an `ingestion` step, because a feature that has been changed and not reported is the
failure mode this project's own history keeps producing.

Two details worth keeping:

- **The detection carries no threshold.** A coordinate is finite or it is not. Anything keyed on
  "how many degrees is too wide" would have been a guess about projections rather than a
  measurement of one.
- **The first version of the regression test passed against the broken code.** A polygon spanning
  −180…180 at Hong Kong's own latitude projects perfectly finitely; transverse Mercator diverges
  90° from its central meridian, worst at the equator. The real failing vertices sit near 158°W at
  3°S. A test built from the plausible-sounding shape rather than from the observed coordinates
  would have locked in a fix nobody could rely on.

---

## 3. Method

Same harness as Phase 9 — same 30 km windows, same So2Sat references, same metrics — so
before/after is comparable cell for cell. The one structural change is that `build_arms` was split
so cleaning happens once per city and several cascades are scored against it
(`clean_for_arms` → `build_arms(..., tiers=, prepared=)`). That removes the confound: a
before/after whose two sides cleaned separately would measure the cascade *and* any run-to-run
difference in the vectors beneath it, and the two cannot be separated afterwards.

Three cascade variants:

| variant | tiers |
|---|---|
| `none` | tier 1 only — reproduces Phase 9, and is the comparability check |
| `coarse` | + WSF-3D (~90 m), GHS-BUILT-H (100 m) |
| `full` | + Open Buildings 2.5D (4 m), where it has coverage |

Nine cities: the eight Phase 9 measured below 50% tier-1 coverage, plus **Berlin as a
high-coverage control**. Berlin gets no Open Buildings — the product stops at Europe — but the two
coarse products are global and 20.3% of Berlin's building area was still unresolved, so it is a
real test. It is also the only city with enough tier-1 heights to hold a large held-out set.

### 3.1 The predictions, registered before the sweep

Both are CLAUDE.md's, and both are written into the report JSON before any city runs, so the
verdict cannot be composed after the numbers are in.

**P1 — filling `Hr` is necessary but may not be sufficient.** Areal products assign a
*neighbourhood* mean and cannot resolve height bands within a unit, which is the axis Phase 9
found dominating. GOB 2.5D at 4 m should discriminate inside a 100 m cell; GHS-BUILT-H at 100 m
should not. Measured three ways: within-unit height dispersion by the tier that supplied the
height; held-out per-building fidelity against the tier-1 heights each product would have
replaced, reported as a **within-unit** Spearman correlation; and the built-class agreement step
from `coarse` to `full`.

**P2 — GHS-BUILT-H at 100 m matches the 100 m grid and is coarser than most enclosures**, so it
favours arm A. Measured as the enclosure-size distribution against one 100 m cell, and as the
change in B's built-class lead over A once the coarse tiers fill heights.

### 3.2 One decision left open, deliberately

`min_height_m` stays at **0.0** for all three products — each product's own "no built volume"
sentinel, and the only value not invented. The risk it carries is a product handing a real
building a fraction of a metre, which drags the geometric-mean `Hr` down without anything looking
wrong. Measured over Cairo's 579 867 footprints before the sweep:

| product | median | share below 2 m |
|---|---:|---:|
| GHS-BUILT-H | 13.22 m | 0.0% |
| WSF-3D | 8.70 m | 0.1% |
| Open Buildings 2.5D | 6.45 m | **20.0%** |

That last figure is reported per city rather than thresholded away. Choosing a floor here would
mean picking a number no documentation supports, on the very axis this phase exists to measure.

---
