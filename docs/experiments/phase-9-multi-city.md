# Phase 9 — multi-city validation

Everything known about lczkit's accuracy came from Berlin: 40.9% against So2Sat labels, against a
53.2% ceiling set by `lcz_v3` scored the same way on the same cells. One number. This project's
history is of single measurements turning out to be artefacts — the enclosure result of Phase 6.5,
the height diagnosis of Phase 6.6, the stitch attribution of Phase 8 — so a second city was always
going to be needed before any of it could be built on.

Phase 8 is what made it askable. A city cleans in minutes rather than never, and So2Sat LCZ42's
labelled patches for 51 cities are already on local disk.

---

## 1. What this phase is for

Three questions, chosen because one sweep answers all of them:

1. **A vs B — grid cells or enclosures.** Deferred twice. Enclosures led Berlin 45.4% to 40.9%
   against labels and lowered the compactness axis from 55.2% to 49.0%, but the entire lead lived
   in one class of one city, and B still trailed on Rotterdam. Unit definition is the largest
   single share of Berlin's disagreement, so this decides it or nothing does.
2. **A distribution, not a point estimate.** For agreement *and* for the ceiling. The ceiling is
   the part that is easy to forget: `lcz_v3` is a model carrying its own error, and on Berlin it
   clears only 53.2% against the labels it is being used to stand in for. A city where the ceiling
   is 40% and a city where it is 65% are not comparable on raw agreement.
3. **`height_tier_fractions` outside Europe.** The height cascade is the package's founding bet and
   had never run outside Europe. See §5 for what this run can and cannot establish.

---

## 2. Method

### 2.1 Which cities, and why not the obvious ones

Selected by measuring labelled-patch density in a 30 km window across all 51 So2Sat cities on
disk, rather than by picking recognisable names. That screen matters more than expected:

| city | patches | classes | verdict |
|---|---:|---:|---|
| Karachi | 1 140 | **1** | unusable |
| Quezon City / Manila | 384 | **1** | unusable |
| Dhaka | 30 | **1** | unusable |
| Chicago | 48 | 1 | unusable |
| Rawalpindi / Islamabad | 4 931 | 14 | **usable — South Asia** |
| Jakarta | 2 535 | 14 | **usable — Southeast Asia** |
| Mumbai | 1 704 | 14 | usable — South Asia |

A city with one labelled class has no confusion axis at all: its agreement figure is arithmetic,
not evidence. Three of the four South and Southeast Asian cities a reader would reach for first
fail this way, which is why the screen is in the script (`MIN_PATCHES`, `MIN_CLASSES`) and applied
to the window actually run rather than to the city's full extent.

### 2.2 Extent — a 30 km window, not the full So2Sat bbox

So2Sat's per-city bounding boxes run 3 800–9 100 km², four to ten times the 891 km² Berlin extent
that Phase 8 measured at 9.8 minutes. Running them whole is days, and enclosure generation — which
arm B needs — has never been measured above 16 km².

A 30 km window is ~900 km², directly comparable to the Berlin baseline. Centred on the densest
cluster of labelled patch centres it retains:

| window | retention, median over candidate cities | range |
|---|---:|---|
| 30 km | ~50% | 31% (London) – 95% (Nairobi) |
| 40 km | ~66% | 44% – 100% |
| 50 km | ~78% | 56% – 100% |

Even at 30 km that is 1 700–16 600 labelled cells per city, against the **432** the 40.9% Berlin
baseline was computed from. The binding constraint is representativeness — a 30 km window is the
urban core, and a city's periphery carries different classes — not sample size. It is recorded per
city as `patch_retention` so the bias is visible rather than assumed away.

The window is chosen by a deterministic grid search over quantiles of the patch centres. Optimality
matters less than reproducibility here: a window that moved between runs would make two runs of the
same city incomparable.

### 2.3 What is measured per city

The three-arm harness from Phase 6.5, unchanged in structure:

- **A** — 100 m grid cells, `buildings_area`. What the package does.
- **B** — enclosures, projected onto the same grid by majority for scoring. The hypothesis.
- **C** — grid cells with *raw* Overture footprints. The control that found the real cause in
  Phase 6.5; A and C staying converged is now the regression test against footprint loss.

Each arm is scored against **So2Sat labels** (primary) and against `lcz_v3` (secondary), with the
`lcz_v3`-versus-labels agreement reported as that city's ceiling. Both confusion axes are broken
out separately — height (1↔2↔3, 4↔5↔6) and compactness (1↔4, 2↔5, 3↔6) — and agreement is
stratified by `height_completeness` in equal-width bands.

---

## 3. Two defects found while building it

Neither was the object of the phase; both would have silently corrupted it.

### 3.1 The harness defaulted to untiled cleaning

`build_arms` took its cleaning config from a module-level constant sized for the 9 km² committed
fixtures, which has no tiling configured. Every caller before this phase worked at ≤16 km², where
that is correct and is what every pre-Phase-8 figure was produced with. At 900 km² it selects the
whole-extent `neatify` path — the superlinear one Phase 8 exists to remove — which does not finish,
and does not fail either.

Caught on the first city, from watching the clock rather than from an error. `build_arms` now takes
the config explicitly and its docstring says why the default is what it is.

### 3.2 The cache key rounded the threshold to six decimals

`simplify_streets_tiled` keyed its per-tile cache on `f"...thr{threshold:.6f}"`. The pooled
artifact threshold comes out of a kernel-density valley search, so it differs run to run well
beyond the sixth decimal — and two such runs hashed to the same directory, the second reading
tiles simplified against a threshold it had never used.

Nothing reported this, because both runs printed the same rounded value. The key now carries the
float at full precision.

---

## 4. The determinism question, and what it actually was

Phase 8 closed with an open item: cached and cold runs differing by 75 of ~198 800 features, written
up as "the cache is not transparent" with stitch ordering as the suspect. Both halves of that turn
out to be wrong, and the way they were wrong is the familiar one — a cause inferred from adjacency
rather than measured.

**The stitch-ordering hypothesis does not survive reading the code.** `pool.map` preserves the order
of its job list, and the job list is built from `tiles` in a fixed order, so tile order is identical
whether a tile was computed or replayed.

**The two runs shared no cache.** `scripts/phase8_threshold_labels.py` passes `cache_dir=None`; its
arms wrote nothing. What the 75-feature gap compares is a run replaying tiles written at 09:41 on
9 August against an independent cold computation at 14:36 — two cold runs, mediated by a cache,
not a cached run against a cold one.

**A cold run today reproduces the cached number exactly.** Two fresh cleans of the same 891 km²
extent, `cache_dir=None`:

| | n_in | n_out | threshold | tiles passed through |
|---|---:|---:|---|---:|
| cold run | 267 021 | **198 879** | 8.131236398845278 | 34 / 594 |
| the run that read the 09:41 cache | 267 021 | **198 879** | 8.131236398845278 | 34 / 594 |

So the cache and a fresh computation agree, and the outlier is the 14:36 arm — which differed in
configuration, not in cache state.

**But there is a real determinism defect underneath, and it is upstream of all of this.**
`neatnet` re-nodes and re-merges a network in the order it receives it. On the test grid a shuffled
input gives the *same feature count and the same total length* with the edges split at different
points — which reaches `momepy.street_profile` and so `aspect_ratio`. Meanwhile
`OvertureSource._fetch` runs a DuckDB scan across many remote parquet files with **no `ORDER BY`**,
so its row order is whatever the parallel readers finished in: nondeterministic between runs, and
different again from the order a cached file replays.

That is the unsorted iteration order. It is in a SQL result rather than a Python `set`, and it sits
at the pipeline's front door.

**Fix: canonical order at the source.** `OvertureSource` now returns every layer sorted by GERS
`id`. Sorting in Python rather than in SQL is deliberate — it costs one local sort instead of a
distributed one, and, the reason that matters, it applies to the cache-hit path too, so the files
already written under `input/Overture_Maps/` yield the canonical order **without being rewritten**.
Nothing under `input/` is modified.

Order-sensitivity inside `neatnet` is not something this package can fix, and a test asserting
order-invariance there would be asserting something false. It is pinned instead by a test that
asserts the sensitivity *exists*, so that if `neatnet` ever becomes order-invariant the constraint
on `VectorSource` is revisited deliberately rather than left in place forever.

### 4.1 What the tiled path now records

The old report carried `"cached": cache_dir is not None` — which says only that a directory was
configured, and was read as "this run reused tiles". That is how a run that computed all 594 of its
own tiles came to be described as a cached run. It is now two separate facts,
`cache_dir_configured` and `n_tiles_reused`, the latter counted before anything runs.

Tiles that `neatnet` cannot process are passed through unsimplified — 34 of Berlin's 594. The report
previously carried only a count, which cannot distinguish two runs that degraded on *different*
tiles. It now carries `{tile_key: exception_class}`, and the linework carries `_tile_key` so a
suspect enclosure resolves to one tile and one window. `MemoryError` is no longer swallowed with
the rest: every other exception there is a statement about the tile's geometry and means the same
thing on every run, whereas running out of memory is a statement about the machine, and swallowing
it makes the map depend on what else the node happened to be doing.

---

## 5. Height tiers — what this phase can and cannot test

CLAUDE.md has the **user** place tiers 2–4 as COGs under `input/GOB25D/`, `input/WSF3D/` or
`input/GHSL/`. None of those directories exists on this system, so `build_cascade` skips all three
and the cascade runs tier 1 alone. Buildings Overture cannot answer for are tagged `unresolved`
with a null height, and `height_frac_unresolved` is the share of building area in that state.

This measures the **premise** — that Overture's heights collapse outside Europe — for the first
time. It does **not** test the package's answer to that premise: no areal tier has ever fired
against real data. Those are two different claims and this run can only make the first.

The second is cheap to arrange when wanted: GHS-BUILT-H is reachable at ~42 MB per tile, and
`lczkit.heights.raster.zonal_mean` already reprojects footprints into the product's Mollweide grid,
so wiring tier 4 is a download and a config entry rather than new code. It is not done here because
placing a source product is the user's call, not the script's.

---

## 6. Results

The sixteen-city sweep runs at roughly 21 minutes per city. What follows is the first city, which
already carries a result worth recording on its own.

### 6.1 Berlin at 30 km does not look like Berlin at 9 km²

| | 9 km² fixture | 30 km window |
|---|---:|---:|
| labelled cells | 432 | **9 627** |
| ceiling — `lcz_v3` vs So2Sat labels | 53.2% | **75.2%** |
| lczkit arm A vs labels | 40.9% | 35.3% |
| arm B (enclosures) vs labels | 45.4% | **31.5%** |
| arm A, built classes only | — | 22.8% |
| arm A as a share of the ceiling | 77% | **47%** |

Two things follow, both provisional on one city until the sweep lands.

**The 53.2% ceiling was a small-sample artefact.** On 9 627 cells rather than 432, `lcz_v3` reaches
**75.2%** against the same labels, in the same city, through the same code path. The "lczkit is at
77% of the comparator" framing recorded at the end of Phase 6.7 does not survive the larger sample:
it is 47% here. That is a worse position than the MVP close-out claimed, and it is the more
trustworthy number — 432 cells carrying two classes was never enough to place a ceiling.

**Arm B's lead reverses.** Enclosures led Berlin by +4.5 points on the fixture and trail by **−3.8**
here (−0.4 on built classes alone). This is the third time the A/B comparison has changed sign when
the instrument changed, which is the substantive argument for not deciding it on one city — and the
reason the decision waits for the full sweep rather than being taken now in the other direction.

**Height provenance, Berlin:** 55.7% Overture `height`, 24.0% `num_floors`, 20.3% unresolved.

### 6.2 On reading the confusion axes at this scale

Berlin's axes come out near-even — height 11.9%, compactness 12.5% — against 17.0% and 55.2% on the
fixture. That is not a contradiction and must not be read as one. The fixture carried two classes,
so almost every disagreement it could express *was* on one of the two axes. The 30 km window carries
fifteen, and most disagreement is now off both axes entirely. Axis shares at the two scales are
different quantities, and only the multi-city figures are comparable with each other.

### 6.3 The full sweep — 15 cities, 4.8 hours

Hong Kong failed on a GEOS predicate (`orientationIndex encountered NaN/Inf`) and is excluded; the
other fifteen completed. Every figure is against So2Sat labels.

| city | region | cells | ceiling | A | B | A built | A/ceil | height ax | compact ax | tier 1 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| berlin | Europe | 9 627 | 75.2% | 35.3% | 31.5% | 22.8% | 47% | 11.9% | 12.5% | 80% |
| london | Europe | 8 693 | 67.5% | 36.7% | 31.8% | 21.5% | 54% | 19.9% | 2.6% | 66% |
| paris | Europe | 5 827 | 81.3% | 58.7% | 63.8% | 49.0% | 72% | 10.6% | 10.8% | 52% |
| cologne | Europe | 6 672 | 66.9% | 40.7% | 40.0% | 15.1% | 61% | 20.4% | 1.8% | 46% |
| rome | Europe | 4 598 | 62.7% | 33.4% | 29.3% | 27.3% | 53% | 9.0% | 18.9% | 67% |
| milan | Europe | 2 633 | 79.9% | 51.8% | 46.6% | 35.9% | 65% | 10.0% | 15.0% | 69% |
| vancouver | N. America | 16 517 | 36.7% | 41.8% | 36.8% | 7.2% | **114%** | 2.6% | 2.5% | 71% |
| sao_paulo | S. America | 10 161 | 74.1% | 31.3% | 32.5% | 10.3% | 42% | 16.9% | 3.7% | 48% |
| rio_de_janeiro | S. America | 6 323 | 83.2% | 47.3% | 33.6% | 4.8% | 57% | 22.0% | 0.1% | 11% |
| cairo | Africa | 7 044 | 42.5% | **3.4%** | 3.3% | 1.3% | 8% | 12.6% | 0.6% | **1%** |
| nairobi | Africa | 4 594 | 38.9% | 11.9% | 11.3% | 4.9% | 31% | 9.4% | 0.4% | **1%** |
| cape_town | Africa | 4 415 | 64.2% | 8.2% | 10.3% | 2.6% | 13% | 17.9% | 0.6% | **4%** |
| islamabad | S. Asia | 4 921 | 45.1% | 24.5% | 23.2% | 4.3% | 54% | 17.6% | 0.3% | **1%** |
| mumbai | S. Asia | 1 706 | 22.8% | 18.5% | 21.0% | 8.9% | 81% | 15.5% | 3.2% | **3%** |
| jakarta | SE Asia | 2 552 | 59.0% | 28.4% | 34.5% | 8.3% | 48% | 26.1% | 3.2% | **7%** |

---

## 7. The founding premise, answered

**This is the headline, and it is unambiguous.** Tier-1 height completeness, as a share of building
area:

| | tier 1 | overall agreement | built-class agreement |
|---|---:|---:|---:|
| Europe + North America (7 cities) | **64.3%** | 42.6% | **25.5%** |
| everywhere else (8 cities) | **9.6%** | 21.7% | **5.7%** |

Cairo 1%, Nairobi 1%, Islamabad 1%, Mumbai 3%, Cape Town 4%, Jakarta 7%. In those cities **92–99%
of building footprint area has no height at all** — Overture carries the geometry and not the
attribute, exactly as the package was founded on believing, and now measured rather than asserted.

**And it is the binding constraint on accuracy.** Across the fifteen cities, tier-1 completeness
correlates with built-class agreement at **r = 0.67**. Built-class agreement outside Europe and
North America averages **5.7%** against 25.5% inside it. Cairo, with 1% tier-1 coverage, scores
3.4% overall and 1.3% on built classes: with no height, `Hr` is null nearly everywhere, the
distance metric runs on building surface fraction alone, and the built types stop being separable
even in principle.

So the premise is confirmed twice over: Overture's heights do collapse outside Europe, **and** that
collapse is what stops the package working there. What has never been tested is the package's
answer to it — no areal tier has ever fired, because none is on disk. That is now the single
highest-value piece of work available, and §5 costs it at a download plus a config entry.

São Paulo is the instructive exception: 48% tier-1 coverage, and its overall agreement (31.3%) sits
with the European cities rather than the African ones. It is the one non-European city where OSM
building attribution is dense, and it behaves accordingly.

---

## 8. Which axis dominates — and the answer is neither of the two on offer

CLAUDE.md asks this to choose between SVF and unit definition. Across fifteen cities:

| axis | min / median / max | mean |
|---|---|---:|
| height — 1↔2↔3, 4↔5↔6 | 2.6% / 15.5% / 26.1% | **14.8%** |
| compactness — 1↔4, 2↔5, 3↔6 | 0.1% / 2.6% / 18.9% | **5.1%** |

**The height axis dominates in 11 of 15 cities, by roughly three to one.** This *reverses* Phase
6.7, which measured compactness at 55.2% against height at 17.0% and set the candidate order to
"unit definition → SVF → height". That measurement came from 432 cells carrying two classes, both
mid-rise — a fixture on which the height axis was very nearly untestable by construction. The four
cities where compactness still leads are Berlin, Rome, Milan and Paris: European, high tier-1
coverage, and the places where height is already known so the residual error has to be elsewhere.

The correlation runs the right way to confirm the mechanism: tier-1 completeness against height-axis
share is **r = −0.44**. Cities that know their heights make fewer height-band errors.

**Recommendation: the next accuracy lever is an areal height tier, not SVF and not unit
definition.** SVF carries weight 4 in a metric whose weight-6 dimension (`Hr`) is currently null
across most of the world; adding a fourth dimension to a metric that cannot populate its second is
the wrong order of work. Unit definition is worth less still — see §9.

---

## 9. A vs B — decided, and it is a split verdict

| | B ahead in | mean delta |
|---|---:|---:|
| overall agreement | 5 of 15 | **−1.5 points** |
| built classes only | **9 of 15** | **+2.4 points** |

Enclosures **help where the classification is morphological and hurt on the natural classes**. That
is a coherent mechanism rather than noise: an enclosure is bounded by streets, so in built fabric it
approximates the LCZ patch Stewart & Oke describes, while in parkland or water it is large and
heterogeneous and its majority label smears several natural classes into one. Rio is the extreme
case at −13.8 overall and −0.9 built.

**Do not adopt B as the default.** The overall figure is what a user gets, it is negative, and the
built-class gain of 2.4 points is small beside the 20-point regional gap that height data explains.
But the earlier reading — "the lead lives in one class of one city" — is now wrong in the other
direction: the built-class advantage is consistent across two-thirds of cities and three continents.
Enclosures are worth revisiting **after** an areal height tier lands, when built-class accuracy is
high enough for 2.4 points to be worth the natural-class cost.

---

## 10. The ceiling is not a constant, and once it is not a bound

`lcz_v3` against So2Sat labels ranges from **22.8%** (Mumbai) to **83.2%** (Rio) — mean 60.0%. Raw
agreement is not comparable between cities without it, which is the main reason this phase reports
both.

**Vancouver: lczkit 41.8% against a ceiling of 36.7% — 114%.** The comparator is not an upper bound
at all there, which retires the last of the framing in which `lcz_v3` stands in for truth. It is one
estimator among two, and on that city it is the worse one.

Berlin's 53.2% ceiling from Phase 6.7 was a small-sample artefact: 75.2% here, on 9 627 cells rather
than 432.

---

## 11. What this changes

1. **Place an areal height product.** GHS-BUILT-H (tier 4) at ~42 MB/tile is the cheap version and
   `zonal_mean` already reprojects into its Mollweide grid; Google Open Buildings 2.5D (tier 2) is
   the one CLAUDE.md singles out for these regions and is worth the extra work. Everything else in
   the deferred list is downstream of this.
2. **SVF drops below height in the deferred priority order.** It was first on the grounds of
   carrying weight 4; it is a fourth dimension for a metric that cannot fill its second.
3. **Berlin is not a representative fixture.** Agreement across cities spans 3.4–58.7% and Berlin's
   35.3% sits mid-pack, but its 80% tier-1 coverage is near the top of the range. Any future
   single-city conclusion should say which end of that distribution it was drawn from.
4. **Hong Kong's GEOS failure** is unexplained and worth a look before the paper — a city dropping
   out on a geometry predicate is a robustness gap, not a data gap.
