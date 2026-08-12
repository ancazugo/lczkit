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

### 3.3 A caveat that limits one of the three measurements

The held-out test masks tier-1 heights and asks each product what it would have said. In a city
with 1% tier-1 coverage, the buildings holding those heights are not a random sample: Cairo's
2 273 held-out footprints have a median height of 21 m against a city-wide GOB median of 6 m.
They are the tall, notable, OSM-mapped buildings.

So **the MAE and bias from that test describe tall buildings, not the city**, and should not be
read as a product's error over the whole fabric. The within-unit rank correlation is much less
exposed: it asks whether a product orders buildings correctly inside a cell, which does not
require the sample to be representative of the city. That is fortunate, because ρ is the
statistic P1 actually turns on.

---

## 4. The cascade works, and the size of the gain is the premise measured directly

Nine cities, 6.1 hours, no city skipped and no diagnostic failed.

| city | tier-1 | resolved after | built `none` | `coarse` | `full` | none→coarse |
|---|---:|---:|---:|---:|---:|---:|
| Cairo | 1.0% | 96.8% | 1.3% | **15.0%** | 8.8% | **+13.7** |
| Nairobi | 1.4% | 98.2% | 4.9% | **11.5%** | 10.2% | +6.6 |
| Islamabad | 0.8% | 91.6% | 4.3% | 8.3% | **9.4%** | +4.0 |
| Mumbai | 3.3% | 93.4% | 8.9% | **19.4%** | 7.0% | +10.5 |
| Cape Town | 3.9% | 98.9% | 2.6% | 14.0% | **16.4%** | +11.5 |
| Jakarta | 7.2% | 98.6% | 8.3% | 13.9% | **14.6%** | +5.7 |
| Rio de Janeiro | 10.7% | 94.4% | 4.8% | 8.4% | **9.2%** | +3.6 |
| São Paulo | 48.4% | 99.6% | 10.3% | **12.6%** | 10.4% | +2.3 |
| Berlin | 79.7% | 99.7% | 22.8% | **23.9%** | 23.9% | +1.1 |

**Built-class agreement improves in 9 of 9 cities**, mean +6.5 points, and overall agreement in 9 of
9, mean +5.2. Height coverage goes from 0.8–79.7% to 91.6–99.7%.

The number that matters most is not the mean but its shape: **corr(coverage gained, built-class
gained) = +0.68**. Cairo, which had 1% of its building area carrying a height, gains 13.7 points;
Berlin, which had 80%, gains 1.1. Phase 9 inferred the founding premise from a correlation across
cities that differed in many ways at once. This is the same claim measured *within* each city,
against its own cleaning, with only the cascade changed.

### 4.1 Two comparability checks

Cascade `none` reproduces Phase 9 exactly on both cities where it was checked — Cairo 3.4% / 1.3%
and Berlin 35.3% / 22.8% — at opposite ends of the coverage range. The `build_arms` split and the
unprojectable-geometry repair changed nothing. Berlin's `full` also equals its `coarse` to the
digit, which is the check that Open Buildings correctly reports *no coverage* in Europe rather than
quietly returning something.

---

## 5. P1 — confirmed at the mechanism, refuted at the outcome

**The middle expectation is confirmed decisively.** Held-out per-building fidelity, pooled across
cities:

| product | resolution | within-unit ρ | MAE |
|---|---|---:|---:|
| Open Buildings 2.5D | 4 m | **+0.289** (min +0.124, max +0.554) | 5.39 m |
| WSF-3D | ~90 m | +0.042 | 7.44 m |
| GHS-BUILT-H | 100 m | **+0.001** | 8.17 m |

The fine product ranks buildings correctly *inside* a 100 m cell in every city it covers. The two
coarse products carry no within-unit information whatsoever — GHS-BUILT-H's pooled ρ is one
thousandth. The within-unit dispersion measurement says the same thing from the other side:
GHS-BUILT-H's median coefficient of variation is **0.000**, with 42–75% of units receiving a
literally constant height.

**The first expectation is only partly right.** Predicted `tier1 > gob25d >> wsf3d > ghsl`;
measured `gob25d 0.441 > num_floors 0.211 > overture_height 0.195 > wsf3d 0.163 > ghsl 0.000`. The
bottom of the ordering holds exactly. The top is inverted: Open Buildings carries **more**
within-unit spread than reality does, not less.

**The third expectation is refuted.** Predicted `full > coarse > none` with `coarse → full` the
larger step. Measured: `none → coarse` is the large step (+6.5 points, 9/9 cities) and
`coarse → full` is **−1.9 points, positive in only 4 of 9**. Mumbai loses 12.4 points and lands
below its own tier-1-only baseline; Cairo loses 6.2.

### 5.1 Why the more accurate product produces the worse map

This is the finding worth keeping, because it is not what either the prediction or ordinary
intuition expects. Open Buildings has the **lowest per-building error of the three** (MAE 5.39 m
against 7.44 and 8.17) *and* the only real within-unit skill, and it still makes the classification
worse.

`Hr` is the **geometric** mean of building heights — Bernard et al. (2024) Table 1, and the form
the Stewart & Oke ranges were defined for. A geometric mean is depressed by dispersion: noise
around a true value lowers it even when the noise is unbiased, by Jensen's inequality. Open
Buildings' within-unit CV is 0.441 against reality's 0.195, so more than half of that spread is
noise rather than signal, and it pushes every unit's `Hr` down. On top of that, **19.1% of its
values fall below 2 m** (max 28.5%) against roughly 1% for either coarse product.

So the classifier does not consume per-building heights. It consumes a variance-sensitive
aggregate of them, and a product can improve the first while degrading the second. **Per-building
accuracy is the wrong acceptance test for a height product feeding an LCZ map**; the unit-level
`Hr` is the thing to measure, and this phase would have adopted the wrong tier had it tested only
MAE.

---

## 6. P2 — first half confirmed, second half refuted in the opposite direction

**Enclosures are indeed smaller than a GHS-BUILT-H cell**: 68.6% of them fall inside one 100 m cell
(56.0–81.4% across cities), though only 9.9% of enclosure *area* does — the large minority holds
most of the ground.

**The consequence drawn from that is wrong.** The prediction was that a 100 m product aligned to
the 100 m grid would favour arm A, narrowing B's built-class lead. Measured, B's built-class lead
over A **widens**:

| | mean B − A, built | B ahead |
|---|---:|---:|
| `none` (tier 1 only) | +1.7 | 5 / 9 |
| `coarse` | **+4.1** | **7 / 9** |
| `full` | +4.3 | 7 / 9 |

Enclosures gain *more* from filled heights than grid cells do, not less. The likely reason is the
opposite of the prediction's premise: because an enclosure is usually smaller than one 100 m cell,
it draws its height from a single cell and inherits that cell's value cleanly, where a grid cell
straddling the product's own grid mixes several.

---

## 7. A vs B — the question Phase 9 deferred until height landed

Phase 9 declined to adopt enclosures on the grounds that they led on built classes (9/15, +2.4)
but trailed overall (5/15, −1.5), and said explicitly to revisit after height. Height has landed,
and it moves the answer:

| | mean B − A | B ahead |
|---|---:|---:|
| overall, Phase 9 (`none`, 15 cities) | −1.5 | 5 / 15 |
| overall, here at `coarse` | **+1.0** | **6 / 9** |
| built-class, here at `coarse` | **+4.1** | **7 / 9** |

B's overall deficit is gone on this set of cities. The remaining large negative is Rio at −11.3
overall against −1.4 built, which is the natural-class smearing Phase 9 identified and not a new
effect. **This is now a live decision rather than a deferred one** — and it should be taken on the
full fifteen-city set at `coarse`, not on these nine, since the nine are selected for low tier-1
coverage and Europe is under-represented.

---

## 8. Hong Kong completes, and is the best-classed city on disk

Run through the *Phase 9* harness — the exact run that failed — Hong Kong now finishes in 14.9
minutes:

| | |
|---|---|
| labelled cells | 4 131 |
| classes in window | **13** (1, 2, 3, 4, 5, 6, 8, 10, 11, 12, 13, 14, 17) |
| arm A vs So2Sat labels | 36.6% overall, 23.4% built |
| ceiling, `lcz_v3` vs labels | 45.9% |
| tier-1 height coverage | 30.8% |
| unprojectable features clipped | **1** |

The repair fired **once**, on exactly the one feature the diagnosis predicted — the two
globe-spanning land-use polygons were examined individually beforehand and only one carried
non-finite coordinates after projection. A fix that repaired more than it should would have been
much harder to notice than one that repaired too little.

Worth noting for later work: **13 classes is the richest class set of any city in this study**, and
it includes LCZ 1, 2 and 3 — compact high-, mid- and low-rise together. Phase 6.7's diagnosis was
distorted by a fixture carrying two classes both mid-rise, on which the height axis was
near-untestable. Hong Kong is the opposite of that fixture and is now available.

---

## 9. What this leaves open

**The `min_height_m = 0.0` decision is now consequential and is not mine to settle.** Open
Buildings assigns sub-2 m heights to 19.1% of footprints on average, and §5.1 shows that tail is
part of why the fine tier degrades the map. A floor would suppress it — but it is a threshold no
documentation supports, and the honest alternatives (floor it, drop the tier, or reorder the
cascade so a coarse product wins ties) are different bets on the same evidence.

**The cascade order is a live question.** `full` runs Open Buildings first, so it claims 92% of
building area and the coarse products barely fire. Reversing that — coarse first, fine only where
coarse has nothing — is a one-line config change and was not tested here.


**The A/B decision should be re-measured on all fifteen cities at `coarse`.** These nine were
selected for low tier-1 coverage, so Europe is under-represented and the natural classes — where
enclosures lose — are unevenly sampled. The result here is strong enough to reopen the question and
not broad enough to settle it.

---

## 10. Acceptance

| criterion | result |
|---|---|
| tiers 2–4 implemented with provenance | three fetchers, per-building `height_source` and `height_confidence`, per-unit tier fractions, products pinned in the manifest |
| before/after built-class agreement for the eight low-coverage cities | §4 — improved in 9 of 9 including the Berlin control |
| the two predictions measured and stated | §5, §6 — P1 confirmed at the mechanism and refuted at the outcome; P2 confirmed then refuted in the opposite direction |
| Hong Kong completes | §8 — 14.9 min, 13 classes, one feature repaired |
| Berlin re-measured at full sample | 35.3% against a 75.2% ceiling on 9 627 cells, reproduced independently here |

**Candidate order after this phase.** Height is no longer the binding constraint: coverage is
91.6–99.7% everywhere and the remaining built-class agreement is 8–24%. The two levers this phase
puts in front of the next one are **unit definition**, which §7 reopens with real evidence, and the
**`Hr` aggregation itself**, which §5.1 shows is sensitive to a property of the input nobody was
measuring.
