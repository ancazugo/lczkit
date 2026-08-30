# Phase 12 — axis reconciliation

**The contradiction is resolved, and the resolution disqualifies the instrument that produced it.**

CLAUDE.md opened this phase on three figures that could not all be true of the same world:

| | height | compactness |
|---|---|---|
| Phase 9, 15-city median | 15.5% | 2.6% |
| Berlin, vs labels | 17.0% | 55.2% |
| Hong Kong, vs labels | 18.1% | 27.6% |

The spec offered two explanations: either the medians were computed differently from the per-city
comparisons, or class composition drives the compactness share so strongly that a cross-city median
of it is meaningless.

**The first is refuted and the second is true — but it is not the whole answer, and it is not the
important part.** The raw axis share is not comparable across cities, which was suspected. It is
also **not comparable between the two axes**, which was not: the height axis has six pairs to
compactness's three, so a null model that never looks at an axis at all hands height most of the
disagreement.

At `none` — the setting Phase 9 measured — that null awards height **3.9×** the compactness share
before any error is looked at. The observed ratio was 4.9×. So "height dominates roughly three to
one, in 11 of 15 cities" is mostly the instrument: the excess over affordance is 1.26×, and once
each city is normalised individually **compactness leads the median at `none` too** (1.34 vs 1.22).

**Recommended next lever: unit definition and footprint coverage.** Evidence in §6.

---

## 1. What was built

- **`axis_summary()` in `lczkit.validation.agreement`** — pools an axis over its pairs and reports
  three denominators: the raw `share_of_disagreement` (unchanged, so Phases 6.7–11 stay readable),
  `share_of_axis_eligible` (reference in LCZ 1–6 only), and `lift` against a composition-preserving
  null. Computed from the confusion matrix alone.
- **`AxisConfusion.area_m2` / `share_of_disagreement_area`** — the axes were the one part of the
  module that was count-weighted while its docstring claimed everything was area-weighted. Added
  beside the count-based field rather than replacing it; see §4.2.
- **`scripts/axis_reconciliation.py`** — the re-analysis. Reads pinned run records, audits their
  provenance, reproduces the published medians, isolates each confound, and prints the normalised
  table.
- **`FootprintCoverage`** on the cleaning report — union-based retention and
  `raw_self_overlap_fraction`, over a component-wise union that is exact and sublinear where the
  obvious one is superlinear (§7).
- **Two determinism fixes**, a cache-version bump they turned out to need, and a test that was
  pinning a defect and calling it a property of the library (§8).

## 2. Method: a re-analysis, not a re-run

Every run persists its full sparse confusion matrix, and `axis_summary` is a function of that matrix
and nothing else. So a figure recomputed from a stored record is the computation the run performed,
not a lookalike — which is what makes re-analysis legitimate rather than a second implementation.

Verified two ways before anything was concluded from it:

- **2 592 stored axis pairs across 16 cities, 4 cascade variants, 3 arms and both references
  reproduce with 0 mismatches.**
- `test_the_axis_summary_reads_the_same_confusion_matrix_a_run_persists` pins the equivalence in CI.

Sixteen cities cost seconds against Phase 11's 8.9 h. The records are pinned by run id rather than
discovered by glob, because "the newest file matching a pattern" is how a re-analysis silently
changes population between one reading and the next.

## 3. Like-for-like, verified first

CLAUDE.md's instruction was to verify like-for-like before comparing anything, because a prior
version of this comparison mixed `lcz_v3` and label references and was caught pre-commit.

**Every published axis figure is against So2Sat labels.** `multi_city_validation.py:342-344` reads
`agreement_ground_truth`; so do the Berlin and Hong Kong fixture figures. And the published medians
reproduce exactly:

| Phase 9, 15 cities, arm A, So2Sat labels | published | recomputed |
|---|---|---|
| height | 15.5% | **15.5%** |
| compactness | 2.6% | **2.6%** |

So the first explanation — "the medians were computed differently" — is refuted. They were computed
correctly. They were then read as if they were comparable, which they are not.

### 3.1 The hazard that survived in code

`scripts/unit_scale_experiment.py` computed its printed axes from `arm["agreement"]` — **`lcz_v3`** —
under the bare heading "confusion axes", four lines below a table whose columns *are* labelled "vs
truth" and "vs lcz_v3". Phase 9's console log therefore printed lcz_v3 axes per city and label-based
axes in its summary, both under the same phrase.

It did not contaminate the published figures, which come from a different function. It is fixed
anyway, and the audit shows why the difference is not a rounding error — the two references disagree
by more than the quantity being measured:

| city | lcz_v3 h / c | labels h / c |
|---|---|---|
| cairo | 2.5% / 7.2% | 1.2% / **24.7%** |
| rome | 3.5% / 3.4% | 7.7% / **21.9%** |
| milan | 5.0% / 4.7% | 4.3% / **16.4%** |
| cologne | 5.2% / 1.1% | **19.0%** / 3.2% |

They also cover different populations: ~91 000 `lcz_v3` cells against ~9 600 labelled ones in Berlin.

## 4. Three confounds, none of them reference type

### 4.1 Cascade variant — the consequential one

Phase 9's medians were measured at cascade `none`. **lczkit has shipped `coarse` since Phase 10.**
Same sixteen cities, same reference, same arm:

| cascade | height | compactness |
|---|---|---|
| `none` | 14.1% | 2.9% |
| `coarse` | **6.0%** | **6.4%** |

Filling heights halves the height axis and doubles the compactness share, which is exactly what a
working height cascade should do. The evidence that set the candidate order therefore describes a
configuration the package no longer ships — and **Phase 10 was itself the intervention that
invalidated it.** Recording an axis figure without its cascade is recording half a measurement.

### 4.2 Denominator population

The denominator is *all* disagreement, including built↔natural confusion, which can land on neither
axis. Median natural share of compared area across the sixteen cities is 24.5%, and it ranges from
3.5% to 54.1% — so the dilution is uneven, and an all-built fixture suffers none of it.

| denominator, `coarse` | height | compactness |
|---|---|---|
| all disagreement | 6.0% | 6.4% |
| reference in LCZ 1–6 | 9.3% | 8.7% |

Separately: the axes were **count-weighted** while `overall_agreement`, `built_agreement`,
`per_class` and the strata are all area-weighted, and the module docstring said "everything is
area-weighted". On a regular grid the two coincide, which is how it survived to Phase 11; on
enclosures they do not. Both are now reported, and the count-based field keeps its definition so no
stored arm-B figure moves silently.

### 4.3 Extent and class composition

The controlled test: one city, two extents, same reference, same arm, everything else fixed.

| city | extent | cells | ref classes | height | compactness |
|---|---|---|---|---|---|
| berlin | fixture | 438 | 2 | 17.0% | **55.2%** |
| berlin | 30 km window | 9 627 | 10 | 11.9% | **12.5%** |
| hongkong | fixture | 152 | 5 | 18.1% | **27.6%** |
| hong_kong | 30 km window | 4 131 | 13 | 9.5% | **13.2%** |

Compactness falls sharply as the reference gains classes — 2 classes → 55.2%, 5 → 27.6%, then flat
at 12.5% and 13.2% for 10 and 13 — while height barely moves. Berlin's 55.2% was never a statement
about Berlin's footprints; it was a statement about a reference containing LCZ 2 and LCZ 5 and
nothing else. Note the levelling: the distortion is severe for a two- or five-class reference and
essentially gone by ten, which is why the sixteen-city windows can be compared with each other and
neither fixture belongs in that table.

## 5. The finding the phase was not looking for

Normalisation asks what each axis would hold if misclassification ignored the axes entirely — the
reference's own class distribution, the run's own distribution of wrong labels, and no association
between them. That expected share is a property of the reference and the classifier's error
histogram, before any axis is measured:

| cascade | expected h / c | ratio | observed h / c | ratio |
|---|---|---|---|---|
| `none` | 10.9% / 2.8% | **3.9×** | 14.1% / 2.9% | 4.9× |
| `coarse` | 5.5% / 3.9% | 1.4× | 6.0% / 6.4% | 0.9× |

At `none` a null that never looks at an axis already awards height **3.9× more disagreement than
compactness**, because the height axis has six pairs to compactness's three and more reachable
directions from any given reference class. The observed 4.9× is barely above it.

> **Phase 9's headline — height 15.5% against compactness 2.6%, "roughly three to one, in 11 of 15
> cities" — is close to what the instrument returns when nothing is happening.** The raw axis share
> was never comparable *between the axes*, quite apart from being incomparable between cities. Both
> readings that this project has taken from it, Phase 6.7's and Phase 9's, were taken through it.

## 6. The normalised table, and the lever

Sixteen cities, arm A, So2Sat labels, cascade `coarse` — what the package ships. `lift` is the
comparable figure; 1.0 means the axis holds exactly the share its reference affords it.

| city | ref cls | nat | h raw | h lift | c raw | c lift | lever |
|---|---:|---:|---:|---:|---:|---:|---|
| berlin | 10 | 17.8% | 11.1% | 0.85 | 13.1% | **3.31** | compactness |
| cairo | 11 | 13.0% | 1.2% | 0.32 | 24.7% | **1.67** | compactness |
| cape_town | 14 | 14.3% | 1.1% | 0.56 | 2.4% | **0.59** | compactness |
| cologne | 10 | 32.9% | 19.0% | **1.57** | 3.2% | 0.92 | height |
| hong_kong | 13 | 51.0% | 9.1% | 1.76 | 12.7% | **4.06** | compactness |
| islamabad | 14 | 25.2% | 0.4% | **1.10** | 2.9% | 0.89 | height |
| jakarta | 14 | 23.1% | 1.8% | 0.39 | 5.0% | **0.87** | compactness |
| london | 13 | 25.4% | 16.8% | **2.86** | 2.7% | 0.94 | height |
| milan | 6 | 32.8% | 4.3% | 0.63 | 16.4% | **2.48** | compactness |
| mumbai | 14 | 21.0% | 11.6% | 1.48 | 10.8% | **2.85** | compactness |
| nairobi | 13 | 32.6% | 0.9% | 0.87 | 2.3% | **0.88** | compactness |
| paris | 8 | 21.5% | 7.9% | 0.72 | 12.7% | **2.73** | compactness |
| rio_de_janeiro | 10 | 52.8% | 0.0% | 0.00 | 1.6% | **1.16** | compactness |
| rome | 8 | 12.5% | 7.7% | 0.60 | 21.9% | **2.37** | compactness |
| sao_paulo | 12 | 23.9% | 9.3% | **1.33** | 7.9% | 1.15 | height |
| vancouver | 16 | 54.1% | 2.6% | **1.87** | 2.6% | 1.06 | height |
| **median** | | | **6.0%** | **0.86** | **6.4%** | **1.16** | compactness, 11/16 |

**Compactness leads on eleven of sixteen cities and on the median, 1.16 against 0.86.** Height sits
*below* 1.0 — at `coarse`, height confusion is less common than composition alone would predict,
which is the height cascade working.

The five cities where height leads are Cologne, London, Vancouver, São Paulo and Islamabad. That is
**not** "the high-tier-1-coverage ones" — only three of the seven Europe/North America cities are in
it, and Berlin, Paris, Rome and Milan lead on compactness.

The regional split that does exist runs the other way, and lines up with Phase 11's:

| median lift, `coarse` | height | compactness |
|---|---:|---:|
| Europe + N. America (7) | 0.85 | **2.37** |
| everywhere else (9) | 0.87 | **1.15** |

Height is flat across the two groups. **Compactness concentrates twice as hard in Europe and North
America** — the same seven cities where Phase 11 found enclosures losing, against nine where they
led on both criteria. Two independent measurements now point at unit definition being a
region-shaped problem, which is worth noting and is not yet a mechanism.

**On arm B (enclosures) compactness leads more strongly: 2.33 against 1.64.** Enclosures do not
reduce compactness error; they raise both axes relative to their nulls. That is worth stating
plainly, because "compactness error means the unit is wrong" would predict the opposite, and it
means the lever is not simply "adopt enclosures" — which Phase 11 declined on separate grounds.

## 6.1 Expectations

**E1 — PARTIAL, and the half that failed is the informative one.**

| half | prediction | measured | verdict |
|---|---|---|---|
| compactness leads at `coarse` | yes | **1.16 vs 0.86, 11/16** | confirmed |
| ordering reverses at `none` | yes | **1.34 vs 1.22, compactness still leads 9/16** | refuted |

The raw shares reverse dramatically at `none` (height 14.1% against compactness 2.9%). **The
normalised ones do not** — compactness leads at both cascades, narrowly at `none` and clearly at
`coarse`. So the lever did not *flip* when the default cascade changed; the raw share was never
measuring what it was read as measuring, at either setting. E1 predicted the right conclusion for
the wrong reason, and the correction is stronger than the claim.

**E2 — CONFIRMED.** Compactness spread across cities falls from **15.6× raw to 6.9× on lift**, a
2.2× reduction against a registered bar of 2×; max/median lift is 3.5 against a bar of 5. A median
of normalised shares is a reportable quantity. A median of raw shares is not, and the two published
ones should not be quoted again.

## 7. Union-based retention

Your ruling, from the Kowloon finding. `CleaningReport.footprints` now carries
`raw_summed_area_m2`, `raw_union_area_m2`, `area_summed_m2`, `area_union_m2`, and derives
`raw_self_overlap_fraction`, `residual_self_overlap_fraction`, `union_retention` and
`ground_retention`. It is embedded verbatim in the manifest, so no plumbing was needed.

Measured on the committed fixtures:

| | Kowloon | Berlin |
|---|---|---|
| raw summed area | 2 113 744 m² | — |
| raw union area | 1 954 770 m² | — |
| `raw_self_overlap_fraction` | **7.5210%** | 0.61% |

`trim_overlaps` removes 1.60% of Kowloon's summed area, so against the sum it reads as attrition and
against the union it is not. The acceptance criterion is **one-sided** — ≥99% of the union, i.e. no
ground lost — with residual double-counting reported separately rather than folded into a number
that cannot distinguish losing ground from counting it twice. `union_retention` above 1.0 means the
BSF numerator still double-counts, which matters because building surface fraction sums overlay
pieces.

### 7.1 The anti-pattern earned its keep

`union_area()` is a whole-extent operation, so its scaling exponent was measured at five Berlin
extents before adoption. **The obvious implementation — one `shapely.union_all` over every
footprint — is superlinear and was rejected:**

| extent | footprints | `union_all` | exponent | component-wise | exponent |
|---|---:|---:|---:|---:|---:|
| 64 km² | 41 862 | 7.6 s | | **1.02 s** | |
| 144 km² | 94 956 | 21.4 s | 1.26 | **2.03 s** | 0.84 |
| 256 km² | 183 704 | 54.5 s | 1.41 | **3.10 s** | 0.64 |
| 484 km² | 375 672 | 197.5 s | 1.80 | **4.69 s** | 0.58 |
| 891 km² | 891 994 | **711.3 s** | 1.48 | **8.59 s** | 0.70 |

At Berlin's full extent the global union costs 11.9 minutes against a total `clean_vectors` run of
9.8 minutes — it would have **roughly doubled the metropolitan runtime** to compute one scalar, and
nothing in the pipeline would have reported why.

The replacement unions only within connected components of genuinely overlapping footprints and
sums the rest. **Exact, not approximate**: area is additive over disjoint sets, and two footprints in
different components share none by construction. Verified against the global union at the three
extents where the global one is tractable — **agreement to 0.0000 m² in all three**, on totals of 15
to 50 km². Sublinear throughout, maximum exponent 0.84, **83× faster at 891 km²**.

Two details that carry the saving: pairs are filtered on *positive intersection area* rather than on
`intersects`, or a terrace row sharing boundaries becomes one component; and the pair search reuses
the spatial index, which is the same index-bounding that made `resolve_buildings_on_streets` 39×
faster in Phase 8. Berlin's raw footprints overlap themselves by only 0.19% of summed area at
metropolitan extent, so almost every footprint is its own component — the global union was doing
enormous work to discover exactly that.

## 8. Determinism

**The 75-feature divergence was closed in Phase 9 at `040be15`, and the working-tree CLAUDE.md had
reverted that record.** Flagged rather than reconciled; the committed text is restored. Both halves
of the original diagnosis were wrong: the two compared runs shared no cache
(`phase8_threshold_labels.py` passes `cache_dir=None`), and `pool.map` preserves job order so stitch
ordering was innocent. The real cause was `OvertureSource._fetch` scanning remote parquet with no
`ORDER BY`.

Two real residuals in the same claim are now closed:

- **`tiles.subset()` discarded the canonical order.** Phase 9 sorted every layer by GERS id so two
  runs of a city agree, and `subset` then re-permuted the rows into `sindex.query` order — which
  geopandas documents as unordered — before `neatnet` saw them. The tiled path's output was
  therefore a property of the installed GEOS build rather than of the data, and it fed
  `pooled_artifact_threshold`, whose value is the tile cache key.
- **The pooled threshold's thread environment was asymmetric.** The serial branch ran without
  `_single_threaded_children()` while the parallel branch ran with it, and `n_workers` follows
  `os.sched_getaffinity`. The same extent on a differently-sized node could land on a different
  cache key and silently rebuild every tile.

### 8.1 A test was pinning the defect and calling it a property of the library

`test_simplification_depends_on_input_row_order` ran the *tiled* path over an ordered and a shuffled
copy of a 14-feature grid, asserted the linework differed, and attributed that to `neatnet` re-noding
in receipt order. Fixing `subset` made it fail, so the attribution was measured rather than argued:

| measurement | result |
|---|---|
| untiled, 14-feature grid, ordered vs shuffled | **identical** |
| `subset` unsorted — preserves layer order? | **no** |
| `subset` sorted — preserves layer order? | yes |
| tiled with unsorted `subset`, ordered vs shuffled | differ |
| tiled with sorted `subset`, ordered vs shuffled | **identical** |
| untiled, **real 6159-street Berlin fixture**, ordered vs shuffled | **differ** (same 3735 features, different splits) |

So neatnet's order-sensitivity is real — the canonical-order requirement on `VectorSource` stands —
but this fixture is far too small to show it, and what the test actually measured was `subset`
scrambling the two inputs differently. It now pins the invariant the fix establishes and which holds
whichever way `neatnet` behaves: **tiling contributes no order-sensitivity beyond the simplifier's
own.**

This is the fourth time in this project a defect has hidden inside something that looked like a
recorded property. It is also the second time a test's *failure* was the finding.

### 8.2 Measured deviation of the fix

Both orderings are estimators of the same heuristic simplification, so the bar is Phase 8's — small,
not growing with extent — not identity.

| Berlin extent | features (sorted / not) | total length | symmetric difference | count Δ | length Δ | pooled threshold |
|---|---|---|---|---|---|---|
| 64 km² | 22 154 / 22 155 | 1 448 968.4 m | 15 554 m = **1.07%** | −1 (0.0045%) | −0.2 m (0.0000%) | identical (7.0) |
| 144 km² | 43 128 / 43 123 | 2 868 452.7 m | 35 476 m = **1.24%** | +5 (0.0116%) | +24.9 m (0.0009%) | identical (8.190721422677772) |

Total length is unchanged to four decimal places while ~1.2% of the linework sits at different split
points — the same signature the Phase 8 pooled-threshold A/B produced, and what "two estimators of
the same heuristic cut" looks like. The deviation grows mildly with extent (1.07% → 1.24%) over two
extents, which is worth watching and is not the runaway the Phase 8 bar disqualifies on.

### 8.3 The measurement caught a cache-correctness problem that assuming would have missed

I expected the threshold to move and the cache to invalidate itself. **It does not move** — the
pooled threshold is bit-identical under both orderings at both extents. So the cache key would have
been unchanged while tile *contents* changed, and a warm run after this fix would have served
pre-fix tiles with nothing reporting it: precisely the "cache that changes results" failure the
Phase 8 entry was opened for, reintroduced by its own fix.

`TILE_RESULT_VERSION` is bumped 2 → 3, which is the field that exists for this. Cached tiles
regenerate; the Phase 9–11 records become historical rather than bit-for-bit re-runnable. They
remain internally consistent, which is all §2's re-analysis relies on.

## 9. What this leaves open

- **The lever is named but not built.** "Unit definition and footprint coverage" is where the
  evidence points; what to *do* about it is the next decision, and Phase 11 already declined the
  obvious move (enclosures) on separate grounds — and §6 shows enclosures raise the compactness
  lift rather than lowering it.
- **`residual_self_overlap_fraction` may be non-zero on stacked fabric.** `trim_overlaps` resolves
  overlapping pairs and does not claim to resolve stacks. Measured and reported; not fixed, per your
  ruling.
- **Five cities still lead on height.** The recommendation is a median, not a universal. A per-city
  lever choice is defensible and is not what this phase proposes.

## 10. Acceptance

| CLAUDE.md asks for | delivered |
|---|---|
| like-for-like verification, same reference / cells / denominator | §3, §4 — every figure audited against its reference, cascade, arm and cell set; published medians reproduced exactly |
| both axes normalised by confusable pairs available in each reference | §5, §6 — `share_of_axis_eligible` and `lift` |
| re-reported across all sixteen cities | §6 |
| a stated recommendation for the next lever, with evidence | §6 — unit definition / footprint coverage |
| union-based retention with `raw_self_overlap_fraction` | §7 — with the whole-extent union's scaling exponent measured at five extents before adoption, and the superlinear implementation rejected |
| the Phase 8 determinism item | §8 — already closed at `040be15`; the record was restored and two real residuals in the same claim closed with measured deviation |

## 11. Three things that were nearly asserted rather than measured

Worth recording together, because each was a place where the cheap move was to reason and the
correct move was to run something:

1. **"The union is just a scalar, it must be cheap."** It costs 711 s at Berlin's full extent —
   more than the entire rest of the run.
2. **"The row-order fix will move the threshold, so the cache invalidates itself."** The threshold
   is bit-identical under both orderings. The cache would have served pre-fix tiles silently.
3. **"`neatnet` is order-sensitive, so the tiled A/B difference is neatnet's."** On the fixture the
   difference was entirely `subset`'s. The property is real, but not at that size, and a test had
   been recording the wrong cause for three phases.

All three follow the same anti-pattern CLAUDE.md already carries — *don't attribute cost or cause by
adjacency* — applied to correctness rather than to profiling.
