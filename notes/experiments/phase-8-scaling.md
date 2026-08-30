# Phase 8 — scaling

lczkit could not process a city. This phase profiles why, fixes it by tiling, and measures what
the fix costs in fidelity.

The problem had been invisible for seven phases because the fixture is 9 km². Three phases were
spent chasing agreement points on that fixture while the pipeline could not leave it.

---

## 1. Profile first

CLAUDE.md's first instruction for this phase was to confirm the cost is `neatnet` itself and not
the exclusion mask or an upstream join. It is `neatnet`, and not by a small margin.

Measured on cached Overture streets for Berlin, concentric windows on the same centre, one core:

| extent | streets | `get_artifacts` | `neatify` | artifacts | largest component |
|---:|---:|---:|---:|---:|---:|
| 1 km² | 706 | 0.1 s | 9.6 s | 561 | 538 |
| 4 km² | 2 898 | 0.4 s | 35.7 s | 2 101 | 2 009 |
| 9 km² | 6 428 | 0.7 s | 93.4 s | 3 886 | 3 658 |
| 16 km² | 10 558 | 1.1 s | 185.2 s | 6 369 | 5 878 |
| 36 km² | 21 168 | 2.5 s | 580.3 s | 14 228 | 13 348 |
| 64 km² | 36 382 | 4.4 s | 1 518.3 s | 24 893 | 23 232 |
| 100 km² | 51 682 | 6.4 s | 2 983.3 s | 35 293 | 32 966 |

**The exclusion mask is exonerated.** `get_artifacts` includes the building exclusion sjoin and is
**0.21%** of `neatify` at 100 km² (6.4 s of 2 983 s). Face-artifact detection as a whole is under a
quarter of one percent of the cost.

**Building cleaning is exonerated.** `clean_buildings` is linear and cheap — 97 073 footprints over
144 km² in **34.9 s**, against 2.3 s for 5 370 over 9 km². Exponent 0.98 in feature count.

**The exponent in area climbs with extent**, which is the signature of the real mechanism:

| interval | exponent in area |
|---|---:|
| 1 → 4 km² | 0.95 |
| 4 → 9 km² | 1.19 |
| 9 → 16 km² | 1.19 |
| 16 → 36 km² | 1.41 |
| 36 → 64 km² | 1.67 |
| 64 → 100 km² | 1.52 |

### The mechanism: face artifacts percolate

`neatify_loop` groups face artifacts into rook-contiguous components and dispatches singletons,
pairs and clusters separately. Clusters are handled one *component* at a time — `union_all()` over
the component's polygons, then a single Voronoi skeletonisation of the result.

Those components percolate. The largest one holds **93–96% of all artifacts at every extent
measured**, and it grows linearly with area: 538 artifacts at 1 km², 32 966 at 100 km². Extent does
not merely add work — it enlarges the single largest indivisible piece of work.

Per-stage, at two extents:

| stage | 9 km² | 36 km² | growth for 4× area |
|---|---:|---:|---:|
| `neatify_singletons` | 3.5 s | 15.4 s | 4.4× |
| `neatify_pairs` | 5.0 s | 26.1 s | 5.2× |
| **`neatify_clusters`** | **16.4 s** | **145.1 s** | **8.8×** |

Singletons and pairs are near-linear. Clusters are not, and they dominate absolutely as well as
asymptotically.

**This is why tiling pays.** Splitting an extent into *k* tiles cuts the largest component roughly
*k*-fold, so the total shrinks by about *k*^(1−p) for exponent *p* — a superlinear saving *before*
any tile runs in parallel.

### What it cost in practice

- 144 km²: completed in roughly **five hours**.
- 256 km²: ran **4h12m** inside `neatify_singletons` / `_best_link` and terminated without output,
  at 7.9 GB resident.

Extrapolating the measured curve at exponent ≈1.6, Land Berlin's 891 km² projects to **around 28
hours** on one core, before memory.

---

## 2. The seam

### The bug pinning fixes

`neatnet` derives its face-artifact threshold from the *distribution* of face-artifact-index values
across whatever network it is handed — a kernel-density valley. A tile therefore computes a
different threshold from the whole extent. On a 2×2 tiling of 16 km² of Berlin:

| network | threshold |
|---|---|
| whole extent | no valley → fallback **7.00** |
| tile (0,0) | no valley → 7.00 |
| tile (0,1) | no valley → 7.00 |
| tile (1,0) | **8.10** |
| tile (1,1) | **7.58** |

A face indexing at 7.5 is an artifact in tile (1,0) and ordinary urban fabric in the run beside it.
`simplify_streets_tiled` therefore pins one threshold across every tile and passes it in via
`neatify`'s `artifact_threshold`.

The first implementation computed it once on the full network, on the reasoning that detection is
0.2% of `neatify`'s cost and so nearly free. **That reasoning was wrong, and §2.5 is what it cost.**
Detection is indeed cheap; the `fix_topology` preprocessing it needs before it can index anything
is not, and it is quadratic. The threshold is now pooled from the tiles instead, and §4.1 measures
that replacement against the whole-network value.

**It must be measured on the preprocessed network.** `neatify` runs `fix_topology` and then
`consolidate_nodes` before indexing any face, and those change which faces exist — an unnoded
crossing encloses nothing. Measuring on the raw input pins a threshold taken from a different
network than the one it is applied to, which is the failure pinning exists to prevent.

### Two bugs the tests caught

**Seam-coincident linework was emitted twice.** Cores partition by *area* but share their boundary
*lines*, so a road running along a seam lies inside both neighbours' closed cores. Clipping each
tile to its core produced **30.9 km of output from 24.0 km of input** on a grid aligned to the
tiling — not a contrived case, since tiles are axis-aligned to the CRS origin and so are a great
many streets. Fixed by `tiles.shared_edges`: every shared edge belongs to the lower-indexed tile,
and each tile drops the linework along its right and top edges.

**Degenerate tiles.** An extent whose maximum falls exactly on a tile boundary — which is every
extent snapped to a round grid — spawned a column of tiles meeting it along a line and holding no
area. Those tiles then failed artifact detection outright. `build_tiles` now rejects a tile that
merely `touches` the extent.

### What tiling can and cannot guarantee

It cannot be exact everywhere. The largest artifact component spans the whole extent, so no tiling
of any size contains it; tiling necessarily cuts it. A test asserting tiled ≡ untiled would be
asserting something false.

What it does guarantee, measured on 16 km² of real Berlin with a 2×2 tiling:

| buffer | missing | extra | agreement |
|---:|---:|---:|---:|
| 300 m | 0.862 km | 1.226 km | 99.77% |
| **600 m** | **0.125 km** | **0.110 km** | **99.97%** |
| 900 m | 0.182 km | 0.116 km | 99.95% |

Against 377.5 km of network. **600 m is the knee** — 300 m is visibly worse and 900 m buys nothing,
so the buffer is chosen from where the curve flattens rather than picked.

Pinning is worth roughly an order of magnitude on spurious linework: unpinned, "extra" runs
8.3–9.4 km instead of 0.11 km.

**One measurement correction.** The first pass at this reported 88.6% agreement. That was the
metric's own trap: a whole-extent run keeps streets that merely *intersect* its window, so its
result reaches past the edge, while the tiled run is clipped to cores. The 48 km gap was the
perimeter overhang, not seam error. `seam_disagreement` now intersects both to common ground, and
`test_seam_disagreement_compares_only_common_ground` guards it.

---

## 2.5 What tiling did not remove

Tiling worked and the first metropolitan attempt still took fifteen hours without finishing. The
tile cache timestamps say where the time went:

| stage | wall time |
|---|---|
| fetch, building cleaning, **threshold resolution** | ~8h 15m |
| **594 tiles simplified** | **7.5 min** |
| everything after the tiles | 6h 50m, killed without completing |

The tiling itself is a 7.5-minute step over 891 km². The two bookends around it took the rest.

**The first bookend was diagnosed correctly; the second was not.** The threshold resolution really
is a whole-network quadratic, and §4.1 replaces it. The 6h50m after the tiles were written was
attributed to the stitch, because `_stitch` is the next thing the code does and the run was
somewhere past the tiles — an inference, not a measurement. §4.3 measures it: the stitch over
Berlin's 209 553 features takes **17.4 seconds**. The six hours and fifty minutes were
`resolve_buildings_on_streets`, several steps later, which §5.1 measures at roughly 75 hours before
it was fixed. That the earlier attribution was never checked is the same failure this phase is
about, committed while diagnosing it.

### The measurements

`resolve_artifact_threshold` spends effectively all of its time in `neatnet.fix_topology`:

| extent | streets | `fix_topology` | `consolidate_nodes` | `FaceArtifacts` | threshold |
|---:|---:|---:|---:|---:|---|
| 64 km² | 33 849 | 481.7 s | 22.1 s | 1.4 s | none → 7.0 |
| 144 km² | 67 187 | 1 916.9 s | 70.4 s | 3.0 s | none → 7.0 |
| 256 km² | 106 717 | 5 004.6 s | 160.6 s | 5.1 s | 8.159813 |
| 484 km² | 168 525 | 12 392.6 s | 369.6 s | 8.3 s | 8.191828 |

Exponent **2.0** in feature count, projecting to ~8.6 h at the metropolitan network's 267 021
streets — which is the 8h15m above. Note the shape of the cost: **detection is 8.3 s and the
preprocessing it needs is 12 392 s.** The expensive part is not the question being asked.

`_stitch`'s `remove_interstitial_nodes` *looks* like the other one, and reading `neatnet` 0.1.6
(BSD-3-Clause) seems to locate it exactly — the function ends in

```python
for ix in np.unique(loop_ix):
    target_nodes = nodes[node_ix[loop_ix == ix]]
```

a Python loop that re-masks the *entire* node-to-loop intersection array once per loop, which is
quadratic in the input.

**It is quadratic and it does not matter.** Measured at 17.4 s over Berlin's 209 553 stitched
features (§4.3). A quadratic with a small constant over a small n is not a bottleneck, and reading
the source told us the shape of the cost while saying nothing about its size. Deciding it was the
culprit on that basis — and then building, testing and documenting a fix for it — is the mistake
recorded in §4.3.

**Building cleaning was suspected and is exonerated** — 76.2 s for 303k footprints at 400 km²,
near-linear, so roughly four minutes at the metropolitan 892k.

### Fix 1 — the pool never ran at all

Separately, the 32-worker comparison run sat for 14h50m with the parent and every worker at zero
CPU. `ProcessPoolExecutor` defaults to the `fork` start method, and by the time simplification runs
the parent has been through DuckDB, GEOS and NumPy; a lock held by a thread that does not exist in
the child is never released. `forkserver` starts a clean interpreter to fork from and cannot inherit
one. `OMP_NUM_THREADS` and its BLAS equivalents are pinned to 1 **in the parent**, before the pool
is built, because the forkserver daemon inherits `environ` when it starts and the native libraries
read their thread counts at library init — later than any pool `initializer` of ours could run.

One consequence worth recording: a `forkserver` child re-executes the parent's entry point, the way
a `spawn` child does, so that a callable defined there can be unpickled. Nothing here needs that —
the only function sent to a worker is `_simplify_window`, referenced by qualified name — and it is
actively harmful, since every worker would re-import the entry script and an entry point without a
real file fails outright. `__main__`'s `__file__` and `__spec__` are hidden for the life of the
pool, leaving the children on a bare `__mp_main__`.

---

## 3. What was built

- **`lczkit/cleaning/tiles.py`** — `Tile`, `build_tiles`, `shared_edges`, `layer_extent`, `subset`.
  Tiles align to the projected CRS's own origin, the same convention `GridUnits` uses, so two
  overlapping extents produce identical tiles where they overlap and a cached tile is reusable
  across runs with different bboxes.
- **`simplify_streets_tiled`** in `cleaning/streets.py` — pinned threshold, buffered windows,
  core-clipped output, a `forkserver` process pool across tiles, and a stitch that heals the nodes
  clipping introduced.
- **`pooled_artifact_threshold`** — the threshold assembled from the per-tile windows instead of
  the whole network, replacing an 8.6-hour step with a parallel one. `_threshold_from_index`
  restates `neatnet.FaceArtifacts`'s kernel-density valley search so a *pooled* distribution can be
  fed to it; restating invites drift, so `test_threshold_from_index_reproduces_face_artifacts`
  asserts exact equality against `neatnet`'s own result rather than approximate agreement.
  A face is attributed to the tile whose **core** holds its representative point, so overlapping
  windows cannot count it twice, and any face touching a window boundary is **dropped rather than
  indexed** — a cut face indexes as a small compact one, which is a fictitious artifact. The number
  and area share of what was dropped is the approximation's error term and travels into the
  cleaning report as `threshold_n_faces_dropped` and `threshold_dropped_area_fraction`.
- **`CleaningConfig.street_artifact_threshold`** — an explicit pin, `None` meaning "derive it".
  What the A/B in §4 needs, and independently it lets a recorded run restate its threshold rather
  than spend hours re-deriving it.
- **`CleaningConfig.street_tile_size_m` / `street_tile_buffer_m` / `street_tile_workers`** —
  `None` keeps the whole-extent path, so every figure recorded before Phase 8 stays reproducible.
  Tiling is a recorded choice, not something that switches itself on past a hidden extent.
- **Per-tile cache** keyed on a fingerprint covering the whole of `CleaningConfig`, the `neatnet`
  version, the resolved threshold, and `TILE_RESULT_VERSION`. The threshold has to be in the key:
  it depends on the full extent, so the same tile genuinely simplifies differently under a
  different study area. The version constant covers the other half — a change to what
  `_simplify_window` writes, which no amount of config hashing would notice.
- **`_road_near_each`** in `cleaning/topology.py` — the road-buffer rule bounded by the spatial
  index instead of by the size of the city. Exact rather than approximate, and 39.3× faster on the
  fixture with byte-identical output; see §5.1 for what it replaced.
- **Degenerate-tile tolerance.** A tile `neatnet` cannot process passes through preprocessed rather
  than raw — matching what `neatify` returns when it finds no artifacts — is flagged per edge with
  `_simplified = False`, and is counted in the cleaning report as `n_tiles_unsimplified`. One bad
  tile must not end a run over a whole city, and a silently unsimplified one would surface
  downstream as a strange enclosure with no way back to its cause.

### A second bug that only scale could find

The first metropolitan attempt did not fail in `neatnet`. It failed in `enforce_planarity` — Phase
6.7's code — with one overlapping footprint pair it could not clear in eight passes.

The cause is that the epsilon was *fixed*. A pair the buffer fails to separate at one micrometre
fails at one micrometre however many passes it is given, so the loop could only ever spin to its
bound and raise. On the 9 km² fixture all three pairs clear on the first pass, so every pass after
the first was dead code that only ever ran on already-solved input, and the defect was
unobservable.

The epsilon now grows tenfold per pass to a ceiling of one millimetre — three orders of magnitude
below survey precision, so escalating this far cannot move a building. A pair surviving even that
is dropped from `buildings_topo` and counted as `n_dropped_unresolvable`: `topo` is the destructive
layer and the one `momepy.enclosures()` needs planar, while `buildings_area` carries every area
statistic and is untouched. One pathological pair among a city's footprints should cost that pair,
not the run — and the count is in the cleaning report, so the gap is never silent.

This is the phase's thesis in miniature: a defect sat in tested, reviewed code for two phases
because the only input it ever saw was too small to exercise it.

### A deliberate departure from the spec

CLAUDE.md's Phase 8 item 4 says to cache per-tile results under `input/`. That collides with the
standing constraint two sections earlier: writes to `input/` are confined to the source
implementation owning that subdirectory, and nothing else in the package writes there at all. A
simplified tile is derived by lczkit's own cleaning from data a source already fetched — it is not
source data, and `input/` is shared with other projects.

Resolved on the safe side: `Settings.tile_cache_dir` is `output/lczkit/_cache/tiles/`, a sibling of
the run directories since a tile outlives the run that computed it. **Flagged rather than
reconciled silently** — if the intent was genuinely to widen who may write under `input/`, this is
a one-line change to the property.

---

## 4. Measuring the two replacements

Two fixes each replaced a global operation with a local one, and in both cases the correctness
argument was *"the interior is already handled."* An argument of that shape is exactly what this
project has repeatedly got wrong, so both were measured against the global version, with the
acceptance condition fixed **before** the numbers came in. No buffer, tile size or pooling filter
was tuned in response to a result.

**One survived and one did not**, which is the case for running the test at all.

### 4.1 The pooled threshold — `scripts/phase8_threshold_equivalence.py`

Six concentric windows on the metropolitan centre, at the production tiling (2000 m tiles, 600 m
buffer). Each extent runs as its own process because the whole-network side takes hours.

| extent | streets | whole-network | pooled | deviation | faces flipped | faces dropped |
|---:|---:|---|---|---:|---:|---|
| 64 km² | 33 849 | none → 7.000000 · 534.5 s | 7.000000 · 54.0 s | **0.000000** | 0 | 0 (0.00% area) |
| 144 km² | 67 187 | none → 7.000000 · 2 267.3 s | 7.000000 · 56.3 s | **0.000000** | 0 | 1 (0.06% area) |
| 256 km² | 106 717 | 8.159813 · 5 420.0 s | 8.134131 · 55.2 s | 0.025681 | 92 (0.112%) | 2 (0.39% area) |
| 324 km² | 127 287 | 8.162454 · 7 699.6 s | 8.187586 · 56.5 s | 0.025131 | 88 (0.090%) | 5 (1.63% area) |
| 400 km² | 149 272 | 8.191828 · 10 516.0 s | 8.187586 · 57.9 s | **0.004242** | 14 (0.012%) | 7 (2.26% area) |
| 484 km² | 168 525 | 8.191828 · 13 476.6 s | 8.187586 · 69.8 s | **0.004242** | 16 (0.012%) | 6 (1.29% area) |

**The deviation does not grow with extent. It shrinks** — 0.0257, 0.0251, 0.0042, 0.0042 — and so
does the share of faces whose artifact status it moves, from 0.112% to 0.012%. Divergence growing
with extent was the disqualifying signature, and this is its opposite.

Both sides *converge*, which is why. Pooled returns 8.187586 at 324, 400 and 484 km² — the same
value to six decimals three times — and the whole network settles at 8.191828 from 400 km² on. Two
estimators of the same quantity, arriving from different directions at a gap of 0.004 on a
threshold of 8.19: four parts in ten thousand.

**The error term grows, and it is not the one that matters.** Faces dropped for touching a window
boundary rise as a share of face area — 0.00%, 0.06%, 0.39%, 1.63%, 2.26%, then 1.29% at 484 km²
and 3.66% over the full 891 km². Not monotone, because it depends on how much parkland, water and
rail land a given window happens to contain, but the trend across an order of magnitude of extent
is clearly upward. Those are the large faces, exactly as designed. They do not move the threshold,
because a kernel-density valley is set by where the bulk of the distribution parts and not by its
tail. Worth stating plainly: **the approximation gets worse with extent on its own terms while the
number it produces gets better.** Only measuring both distinguishes that from luck.

**The cost curve is the other half of the point.** The whole-network side runs 534.5 s → 13 476.6 s
across the series; the pooled side is 54.0 s → 69.8 s, near flat, because it is k × (n/k)² spread
over the same pool the tiles use. That is 9.9× at 64 km² and **193× at 484 km²**, and the ratio
widens with extent, which is the shape of a quadratic being replaced by a parallel near-linear one.

**The two smallest extents are not threshold comparisons, and the table says so.** At 64 and
144 km² the whole network finds no kernel-density valley and `neatify` falls back to 7.0 — and
pooling finds no valley either, so they agree by both reaching the same fallback. Worth knowing,
since it shows pooling does not *manufacture* a valley where the whole network sees none, but it is
not evidence about where a valley lands.

**One criterion down.** Divergence growing with extent was disqualifying on its own, and it does not
grow. The other criterion — that the remaining deviation moves no classification — is §4.2.

### 4.2 Does it move an LCZ label? — `scripts/phase8_threshold_labels.py`

CLAUDE.md's condition is that the deviation *"does not move any classification"*, and the
classification that matters is the LCZ label rather than the artifact status of a face. Two arms
over the same window, tiled both times, differing in exactly one value —
`street_artifact_threshold` — compared cell by cell on the 100 m grid.

| | |
|---|---|
| window | 256 km², centred on the metropolitan extent |
| arm *whole* | threshold 8.137442, 194 s, 68 718 streets out |
| arm *pooled* | threshold 8.165583, 245 s, 68 677 streets out |
| deviation | 0.028141 |
| **cells whose `lcz_primary` moved** | **6 of 26 040 — 0.0230%** |
| transitions | 5→4 (2), 9→5 (2), 8→6 (1), 12→11 (1) |

**Against the pre-registered bar this fails. The bar was zero, and six is not zero.**

That was the verdict as measured, and it was reported as a failure with nothing tuned — the tile
size, the buffer and the face filters were exactly what they had been before the run. Making six
cells go away by widening the buffer until they did was the move the phase instructions ruled out,
and it would have replaced a measured property with a fitted one.

#### The bar was wrong, and has been superseded

The bar presumed that the whole-network threshold is the reference and the pooled one is an
approximation of it. **It is not.** Both are estimators of the same heuristic quantity — the valley
in a kernel density estimate over face-artifact indices — and neither has a claim to correctness.
`neatnet` picks that valley to separate road artifacts from urban fabric; there is no true value it
is converging on. Six differing cells are two estimators disagreeing, not six errors, and a bar of
exact identity was asking one estimator to reproduce the other's arbitrary choices.

This is the same anti-pattern the phase's own list already names — *don't treat the incumbent
implementation as ground truth when validating a replacement* — applied to a bar written before that
entry existed. The acceptance test should have been set against the noise floor of the enterprise.

**The corrected bar, and the measurements against it:**

| criterion | result |
|---|---|
| no systematic bias | both estimators converge — pooled returns 8.187586 at 324, 400 and 484 km², whole-network settles at 8.191828 from 400 km² on: 4 parts in 10 000 |
| deviation does not grow with extent | it **shrinks** — 0.0257, 0.0251, 0.0042, 0.0042 (§4.1) |
| flips confined to adjacent classes | yes, all six — 5→4 ×2, 9→5 ×2, 8→6, 12→11 |
| flip rate below enterprise noise | 6 / 26 040 = **0.023%**, against a package that agrees with ground truth 40.9% of the time versus a 53.2% ceiling |
| cost | **~8.6 h → ~70 s**, up to 193× at 484 km² |

Six cells is 0.06 km² of 260 km². The package's own uncertainty against hand-labelled ground truth
is three orders of magnitude larger, and the pooled threshold is the only reason a city completes at
all — it is what stood between Berlin and the 9.8-minute run in §6.

**Adopted**, on the corrected bar, by the user. Both the original bar and its failure are left
standing above deliberately: the bar was fixed before the numbers came in, the measurement was
reported as a failure rather than argued into acceptability, and the decision to change the bar was
taken separately and by someone other than the party being measured. That sequence is the part worth
preserving.

#### The 891 km² A/B — the condition attached to the adoption

The adoption carried one condition: a materially higher flip rate at the full extent reopens it.
That measurement has now been made, at the extent the pooled threshold exists for.

| | 256 km² | **891 km²** |
|---|---|---|
| whole-network threshold | 8.159813 | **8.140679** — 38 372 s, **10 h 39 m** over 267 021 streets |
| pooled threshold | 8.134131 | **8.131236** — ~70 s |
| deviation | 0.025681 | **0.009443** |
| cells | 26 040 | 172 181 |
| **cells whose `lcz_primary` moved** | 6 — 0.0230% | **10 — 0.0058%** |
| transitions | 5→4 ×2, 9→5 ×2, 8→6, 12→11 | 11→12 ×3, 10→6 ×2, 12→14 ×2, 10→5, 10→8, 12→11 |

**The flip rate falls by a factor of four, and the condition is not met.** The adoption stands.

Two things are worth stating precisely rather than being folded into that.

**The cost figure was optimistic, not pessimistic.** The ~8.6 h extrapolated from the exponent-2.0
fit is in fact **10 h 39 m** measured. Against ~70 s for the pooled equivalent that is roughly
**550×** at the extent that matters — and it is the difference between a city that completes and one
that does not, since each of the two pipeline arms downstream took only 456 s and 551 s.

**Three of the ten moves involve LCZ 10, which the distance metric does not assign.** LCZ 10 is
assigned functionally from `industrial_fraction`, a building-area quantity, so a street threshold
should not reach it. The route it does have is real and worth naming: `resolve_buildings_on_streets`
consumes the *simplified* network, so a different simplification drops and trims different
footprints, and every building-area parameter — `industrial_fraction` included — moves with it. That
is a mechanism, not a measurement; it has not been verified, and it is recorded here as the first
thing to check if these transitions ever matter.

### 4.3 Per-seam stitching — built, measured, and thrown away

This is the fix that did not survive its own equivalence test, and the reason to run one.

The premise was that `neatnet.remove_interstitial_nodes` over the whole stitched network is
quadratic and cost 6h50m at metropolitan scale. Reading `neatnet` 0.1.6 supports the first half:
the function ends in a Python loop that re-masks the entire node-to-loop intersection array once
per loop. The replacement restricted the heal to the chains a seam actually broke, identified
through `neatnet.nodes.get_components` so the grouping was neatnet's own.

At tractable extents it looked good — identical linework, and faster:

| extent | tiles | global | per-seam | symmetric difference | agreement |
|---:|---:|---:|---:|---|---:|
| 64 km² | 42 | 1.8 s | 1.0 s | 0.000000000 m | 1.000000 |
| 144 km² | 72 | 5.1 s | 2.4 s | 0.000000000 m | 1.000000 |

**Then it was measured at the extent it was built for.** Berlin's 594 cached tiles, 209 553
features, both stitchers in one process, and run again with the order swapped to rule out a warm
cache:

| | global | per-seam |
|---|---:|---:|
| stitch time (per-seam first) | **17.0 s** | 21.7 s |
| stitch time (global first) | **17.4 s** | 21.6 s |
| features out | 198 879 | 195 508 |
| total length | 19 077.900486 km | 19 077.900486 km |
| symmetric difference | — | **23 500 m** (0.12%) |

**The global stitch is 17 seconds, not six hours.** The restriction is 24% *slower*, because
`get_components` over the full network — which the restriction needs in order to know what to
restrict to — costs more than simply healing everything. And at metropolitan scale the two no
longer agree: 23.5 km of the 19 078 km network is placed differently, where at 64 and 144 km² they
were bit-identical. The extents where the comparison was cheap were the extents where it could not
see the disagreement.

There was a second cost too. Global healing also merges degree-2 chains inside tile interiors;
per-seam leaves them, and `momepy.street_profile` is a per-segment measurement, so the difference
reaches Phase 5. Against the whole-extent result that tiling approximates, on the committed
fixture:

| parameter | global vs untiled | per-seam vs untiled |
|---|---:|---:|
| `aspect_ratio`, mean abs. difference | 0.0721 | **0.1497** |
| `street_openness`, mean abs. difference | 0.00618 | **0.00944** |
| `building_surface_fraction` | identical | identical |

Twice as far from the whole-extent answer on a parameter carrying weight 3, for a step that was
slower anyway.

**Reverted.** `_stitch` heals globally, `_seam_broken_components` and `SEAM_EPS_M` are gone, and
`scripts/phase8_stitch_equivalence.py` went with them — a script whose only job was to compare
against a deleted code path is not a standing check. The measurement stays here, because the
finding is worth more than the code was: **an optimisation was designed, implemented, tested and
documented against a bottleneck that did not exist**, and only measuring it at full scale caught
that. The stitch's own scaling is now known — 1.8 s, 5.1 s, 17.4 s at ~30k, ~60k and ~210k
features, an exponent of about 1.16 — so it is a whole-extent operation with a measured exponent,
which is what the acceptance criterion actually asks for.

---

## 5. What is left that runs over the whole extent

CLAUDE.md's acceptance requires that **no whole-extent operation is left with an unmeasured scaling
exponent**, and the anti-pattern list requires three or more extents before an exponent may be
claimed. `scripts/phase8_step_scaling.py` is the standing check.

### 5.1 It immediately found a third quadratic, in `resolve_buildings_on_streets`

The rule that decides whether a footprint stands in the roadway did this:

```python
road = streets.geometry.buffer(buffer_m).union_all()
inside = buildings.geometry.intersection(road).area
```

Every footprint intersected against **one** unioned road geometry, which costs
O(footprints × road complexity) with both factors growing with area. Split into its parts at
16 km² of Berlin:

| step | 16 km², 9 563 footprints |
|---|---:|
| `buffer` | 0.14 s |
| `union_all` | 2.07 s |
| **`intersection`** | **87.76 s** |

**The union was never the cost.** A second point confirms the exponent: at 64 km² the same code ran
past 25 minutes without finishing, against 23.4 minutes predicted by squaring from 16 km².
Extrapolating to Berlin's 892k footprints gives roughly **75 hours** — on its own more than the
whole failed run, and a good match for the 6h50m the killed run had accumulated when it was
stopped.

It had never appeared in any profile for a simple reason: **no run had ever reached it.** Every
other measurement was taken on the 9 km² fixture, where it costs a second.

(Both this and §5.2 time the rule on *unsimplified* streets, which is more than the pipeline hands
it. That makes the absolute numbers an upper bound; the exponent, which is what the acceptance
criterion is about, is unaffected because both sides scale the same way with extent.)

The replacement asks the spatial index which road buffers each footprint actually meets and unions
only those. It is exact rather than approximate — a piece of roadway a footprint does not touch
changes neither its intersection nor its difference — and on the committed fixture it is **39.3×
faster with identical output**: same 5 482 footprints, same `building_id` set, symmetric difference
of 0.0 m², total area agreeing to ten significant figures.
`test_the_road_rule_is_bounded_by_the_index_not_by_the_city` holds it there, comparing against the
replaced implementation restated verbatim rather than against a re-derived expectation.

### 5.2 The remaining exponents

With the road rule bounded, **every whole-extent step left in `clean_vectors` is sub-linear.**
Four extents, one process, concentric windows on Berlin:

| step | 64 km² | 144 km² | 256 km² | 484 km² | exponent |
|---|---:|---:|---:|---:|---:|
| buildings | 41 198 | 95 522 | 183 338 | 374 386 | |
| `clean_buildings` | 14.68 s | 33.89 s | 61.81 s | 113.55 s | **0.93** |
| `resolve_buildings_on_streets` | 5.00 s | 9.30 s | 14.11 s | 21.00 s | **0.65** |
| `enforce_planarity` | 1.19 s | 2.47 s | 4.30 s | 7.31 s | **0.83** |
| `clean_land_use` | 0.07 s | 0.13 s | 0.19 s | 0.29 s | 0.64 |
| `drop_buildings_on_waterbodies` | 0.11 s | 0.20 s | 0.35 s | 0.57 s | 0.75 |
| `drop_waterlines_through_buildings` | 0.03 s | 0.06 s | 0.11 s | 0.21 s | 0.88 |

Exponents are least-squares fits in log-log space against building count. `clean_buildings`
reproduces its independently measured 0.98 as 0.93, which is the harness checking itself: a
different answer there would have meant the measurement was wrong rather than the step.

The sub-linearity is not mysterious — these are index-bounded operations whose per-feature cost
falls slightly as the index deepens. What matters is that **nothing here is above 1.0**, so the
acceptance condition holds: no whole-extent operation is left with an unmeasured exponent, and
none of the measured ones grows faster than the data.

---

## 6. Metropolitan acceptance

`scripts/berlin_metropolitan.py` runs Land Berlin's full administrative extent — 891 km², the whole
city — end to end, with `--extent` for a reduced comparison and an `untiled` mode so the
pre-Phase-8 baseline is reproducible rather than asserted.

### **585.6 s — nine minutes and fifty seconds.**

| | |
|---|---|
| extent | Land Berlin, 891 km² |
| wall time | **9.8 min** (against 15h14m, killed without finishing) |
| streets | 267 021 in → 195 508 out |
| tiles | 594, across 256 workers, 34 passed through unsimplified |
| `buildings_area` | 892 014 |
| `buildings_topo` | 854 163 |
| **footprint area retention** | **99.947%** (Phase 1 requires ≥99%) |
| pooled artifact threshold | 8.131236, from 192 675 faces over 460 tiles |
| faces dropped at a window edge | 49, carrying 3.66% of face area |

The cleaning report survives the trip intact: 138.98 km² of footprint enters, 138.80 km² leaves
`buildings_area`, and every destructive step on `buildings_topo` is accounted for — the road rule
takes 138.61 → 135.42 km², the waterbody rule 135.42 → 135.25 km².

**The error term is reported rather than hidden.** 49 faces were dropped from the pooled
distribution for touching a tile window boundary, and although that is 0.03% of faces by count it
is **3.66% by area** — the dropped ones are exactly the large faces, which is what dropping
anything wider than the 600 m buffer means. That asymmetry is the honest shape of this
approximation and is why §4.1 measures the threshold against the whole-network value rather than
arguing from the count.

34 of 594 tiles (5.7%) were passed through unsimplified because `neatnet` raised on them. They are
flagged per edge with `_simplified = False` and counted in the report, so the gap is traceable
rather than silent.

---

## 7. Four fixes, three kept

| # | fix | outcome |
|---|---|---|
| 1 | `forkserver` process pool, native thread pools pinned in the parent | **kept** — the pool had never run at all; 32 workers at zero CPU for 14h50m |
| 2 | artifact threshold pooled from per-tile face distributions | **adopted** — passes §4.1 outright; fails the pre-registered §4.2 bar, which was then superseded as wrong. No bias, deviation shrinking, adjacent-class flips only at 0.023%, 193× cheaper |
| 3 | stitch restricted to seam-broken chains | **reverted** — the bottleneck it targeted does not exist (17.4 s, not 6h50m), and it was slower and less faithful |
| 4 | `resolve_buildings_on_streets` bounded by the spatial index | **kept** — the real second bookend, ~75 h → 21 s at 484 km² |

Fix 4 was not on the list. It was found because the acceptance criterion required sweeping every
remaining whole-extent operation, and fix 3 was discarded because the criterion required measuring
the replacement against the thing replaced **at the extent it was built for**. Neither would have
surfaced from reasoning about the code.

Fix 2 is the one whose *criterion* turned out to be the defect rather than the fix. A bar of exact
identity with the incumbent is only meaningful when the incumbent is a reference; here both sides
estimate the same heuristic cut point. The failure was still worth reporting as a failure — changing
the bar after seeing the number is only legitimate when someone other than the measured party does
it, and for a stated reason about what the bar was measuring.

---

## 8. What this changes

The candidate-cause order from Phase 6.7 should not be re-derived from a single extent. Both
instruments have now been shown to move it: switching reference inverted it once (§6.7), and
widening the extent from 9 km² to 144 km² inverted it back. Compactness 55.2% / height 17.0% on the
fixture becomes height 22.7% / compactness 13.7% at 144 km², against the same reference.

That is the deeper lesson of this phase, and it is not really about `neatnet`. **A 9 km² fixture was
load-bearing for seven phases of conclusions, and it was not big enough to carry them.** The A/B
enclosure decision reversed on the wider extent; so did the axis diagnosis. Scaling is not only a
throughput problem — it is what makes the measurements mean anything.
