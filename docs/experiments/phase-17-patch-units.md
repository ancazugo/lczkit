# Phase 17 — organic patch units

Built on explicit request: units that follow the city's own structure — streets, rail, water — at
the grain WUDAPT contributors actually draw at, rather than a regular grid. `GridUnits` is not
modified and remains the default.

## 1. The measurement that set the design

The obvious answer was "use enclosures, they are already there". Measured first, and it is wrong —
an enclosure is a **block**, and an LCZ patch is a **neighbourhood**.

| | median unit |
|---|---:|
| `EnclosureUnits` on the Hong Kong fixture | **0.04 ha** |
| 100 m grid cell | 1.00 ha |
| WUDAPT polygon, sixteen study cities | 2.2 – 52 ha (median ~5 ha) |
| So2Sat patch (320 m square) | 10.24 ha |

Phase 6.5 had the same from the other direction on Berlin: 78% of its enclosures are sub-1000 m²
slivers.

The second obvious answer was "use a thinner barrier set". Measured at four settings, and it is
also wrong:

| barriers (HK fixture) | seeds | median | p90 | max | % < 0.1 ha |
|---|---:|---:|---:|---:|---:|
| all streets | 4095 | 0.04 ha | 0.36 ha | 673 ha | 72.9% |
| drop footway/steps/path | 769 | 0.11 ha | 2.52 ha | 691 ha | 48.6% |
| major + tertiary | 509 | 0.07 ha | 3.85 ha | 692 ha | 56.2% |
| major only | 397 | 0.07 ha | 2.96 ha | 692 ha | 57.9% |

**Every barrier set is bimodal** — slivers plus a handful of very large faces — and the median
barely moves. A thinner network does not enlarge small faces; it only stops subdividing big ones.
The scale is set by a merge step or it is not set at all.

## 2. What was built

`src/lczkit/units/patches.py`. Two stages.

**Seeds** are `EnclosureUnits` unchanged, over a barrier set with the pedestrian classes removed.
`filter_street_barriers` drops `footway`, `steps`, `path`, `cycleway`, `bridleway` — a footpath
through a housing estate is not a boundary between two LCZ patches, and these are **72.7% of
Berlin's segments, 72.8% of Hong Kong's and 50.6% of Milan's** against 3.5–7.5% in cities where
pedestrian mapping is sparser. Left in, the partition is largely a measure of how thoroughly a
city's footpaths have been surveyed. `pedestrian` is deliberately *kept*: Overture uses it for
plazas and pedestrianised streets, which are real breaks at the width a street has.

**The merge** takes the smallest surviving unit and folds it into the contiguous neighbour closest
to it in building surface fraction and geometric-mean height, subject to an area ceiling, until
every unit reaches `min_area_m2`.

- Contiguity from `libpysal.graph.Graph.build_contiguity`, lifted once into a plain adjacency dict
  so a merge updates in O(degree) rather than rebuilding a graph. **`libpysal` is now a declared
  dependency** — it was present only transitively, via momepy and esda.
- Features are deliberately the two cheap ones. Both come from `buildings_area` with a single
  overlay: no land cover, no street profile, no second `compute_parameters`. Between them they
  carry the two axes LCZ separates built types on.
- A missing dimension is compared on what is left, never imputed — the same policy the classifier
  applies to a null parameter, for the same reason: a block with no measured building has no
  height, and giving it the mean would merge it into whatever happens to be average.
- Deterministic: smallest-area-first with ties on `unit_id`, candidates scanned sorted, equal
  distances broken on `unit_id`. Asserted under a row shuffle on the fixture.

### `min_area_m2`, not `target_area_m2`

Named for what it does after the first run showed what it does. Merging stops when a unit
*reaches* the minimum and the merge that gets it there overshoots, so on the Hong Kong fixture a
5 ha setting gives p10 5.75, median 10.5, p90 24.5 ha. It is a floor; set it to roughly half the
grain wanted. Calling it a target would have invited exactly the misreading the first draft made.

### Results at each strategy, Hong Kong fixture

| strategy | units | median | total |
|---|---:|---:|---:|
| grid | 959 | 1.00 ha | 9.590 km² |
| enclosure | 618 | 0.15 ha | 8.984 km² |
| **patch** | **62** | **11.69 ha** | 8.984 km² |

618 seeds, 556 merges, 0 isolates, 0 units left below the minimum. The patch median lands inside
the WUDAPT band; the grid total exceeds the others because grid cells are kept whole and overhang
the bbox by design.

## 3. Scaling — measured before shipping, per the standing anti-pattern

The contiguity build and the merge loop are both whole-extent operations. Phase 12's footprint
union looked like a cheap scalar and ran 711 s at Berlin's extent, so this is not optional.

| seeds | extent | seconds | patches |
|---:|---:|---:|---:|
| 3 600 | 9 km² | 0.85 | 99 |
| 10 000 | 25 km² | 2.39 | 266 |
| 19 600 | 49 km² | 4.85 | 513 |
| 40 000 | 100 km² | 9.30 | 1 077 |
| 78 400 | 196 km² | 21.30 | 2 125 |

**Exponent 1.03 in seed count** (pairwise 1.02, 1.05, 0.91, 1.23) — linear, with no hazard.
Extrapolating to Berlin's 891 km² gives roughly 100 s, against a whole-run 9.8 minutes. Measured on
synthetic seeds so the extents scale cleanly and the fit is about the algorithm rather than about
how one city happens to be shaped; power-law extrapolation ran 24% optimistic in Phase 8, so treat
that 100 s as a lower bound.

## 4. The ruling this closes, six phases late

Phase 11 concluded: *"expose `unit_strategy` as config, default `grid`, no auto-selection."*
Nothing was exposed. `pipeline.run_pipeline` constructed `GridUnits()` as a literal and **never
assembled barriers at all**, so enclosures were unreachable from the chain — available only by
importing from `scripts/`. That is a fifth instance of the pattern Phase 14 was opened for, found
by needing the seam rather than by auditing for it.

`UnitsConfig` now carries `strategy`, `cell_size_m`, the two patch areas,
`patch_merge_on_morphology` and `drop_pedestrian_barriers`. The choice reaches the manifest through
the config dump; the *outcome* reaches it as `PatchReport`, which is a separate thing — a run
recording `patch_min_area_m2=50000` says what was asked for, and `seed_area_quantiles` beside
`patch_area_quantiles` says what was got.

**No auto-selection, and in particular none by region.** Phase 11 ruled that explicitly and the
ruling stands: region is not the mechanism, natural-class share and patch heterogeneity are, and a
rule keyed on continent is wrong at every boundary.

## 5. A caveat that must travel with any figure measured on patch units

The merge reads building surface fraction and height, and those are two of the seven dimensions the
classifier then scores. That is the standard shape of a regionalisation — SKATER, AZP and the rest
all work this way — and it is still a form of circularity: a patch is more homogeneous in BSF than a
cell partly because it was *built* to be.

It cannot inflate agreement with an external reference, which is what validation measures. It does
mean `bsf_by_reference_class` on patch units is a weaker test than the same table on a grid, so
**Phase 13's conclusions stay on the grid.**

## 6. What this phase did not do

**No sixteen-city A/B sweep.** Phase 11 measured grid against enclosures three times over 8.9 hours
and the pre-registered rule required a lead on both overall and built-class agreement. Repeating
that for patch units is the right next measurement and it is a sweep, not a build; `agreement_wudapt`
and arm D are wired and `scripts/unit_scale_experiment.py` runs it. Until it is run, `patch`
is an available strategy with no accuracy claim attached, and this write-up makes none.

The pre-registered reading, recorded now so it cannot be chosen afterwards: Phase 12 named unit
definition the lever at compactness lift 1.16 against height 0.86, so if patch units are the answer
the **compactness lift should fall toward 1.0**. Standing caution — plain enclosures *raised* it to
2.33, so "bigger units" is not automatically the fix, and that is exactly what the sweep would test.
