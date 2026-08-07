# Phase 6.6 — footprint attrition remediation

**Result: the attrition is closed. Berlin's built-class agreement goes 17.7% → 24.3%, and arms A
and C have converged to the same figure — the control that used to be 9.1 points ahead of the
pipeline now has nothing left to prove. `buildings_area` retains 99.49% of raw footprint area on
Berlin and 100.00% on Rotterdam.**

**The gap is not closed.** 24.3% still sits far below the 50–60% imagery-based LCZ maps reach.
Footprint attrition was *a* cause, and the error it was hiding is now visible on the height axis.

Reproduce with `uv run --active python scripts/unit_scale_experiment.py`. Runs offline from the
committed fixtures. Numbers below are run `20260807T233734Z`; the Phase 6.5 comparison figures are
run `20260807T140628Z`, recorded in [phase-6.5-unit-scale.md](phase-6.5-unit-scale.md).

---

## 1. What was measured before anything was changed

CLAUDE.md named two suspects. They are not the same size.

### `absorb_small_buildings` deletes — and it never mattered

`geoplanar.merge_touching` deletes any polygon sharing no boundary segment with a neighbour, its
documented behaviour, with no way to turn it off. So the operation did delete, and per CLAUDE.md
that is a bug. The recoverable area is trivial:

| | footprints < 20 m² | isolated → deleted | touching → dissolved | area lost |
|---|---:|---:|---:|---:|
| Berlin | 1186 | 1043 | 143 | 3800 m² — **0.12%** |
| Rotterdam | 120 | 95 | 25 | 1200 m² — 0.17% |

The −1177 features CLAUDE.md attributes to this step are real and are now recovered in full. They
were worth an eighth of one percent. **Fixed because it is a bug, not because it paid.**

### `drop_buildings_on_streets` was the whole of it

| Berlin | area | n | mean footprint |
|---|---:|---:|---:|
| entering topology | 3.1247 km² | 4981 | — |
| `drop_buildings_on_streets` | **−0.7036 km²** | 439 | **1603 m²** |
| `drop_buildings_on_waterbodies` | −0.0133 km² | 6 | — |
| final | 2.4078 km² | 4536 | 531 m² |

439 features carrying 22.5% of all building area, at three times the mean footprint of what
survived. A rule deleting things three times larger than average is not removing artefacts.
Rotterdam lost 0.0567 km² to **three** buildings averaging 18,890 m² — port sheds crossed by a
service road.

### Picking the road-buffer threshold from the fixture

Overlap fraction of each dropped Berlin footprint against a road buffer of half-width 4 m:

| overlap | n | area | median footprint |
|---|---:|---:|---:|
| [0.0, 0.1) | 162 | 448,808 m² | **1652 m²** |
| [0.1, 0.2) | 107 | 130,906 m² | 814 m² |
| [0.2, 0.3) | 55 | 56,277 m² | 476 m² |
| [0.3, 0.4) | 40 | 25,101 m² | 313 m² |
| [0.4, 0.5) | 21 | 7,501 m² | 213 m² |
| [0.5, 0.6) | 15 | 20,551 m² | 169 m² |
| [0.6, 0.7) | 9 | 5,411 m² | 129 m² |
| [0.7, 0.8) | 7 | 2,835 m² | 84 m² |
| [0.8, 0.9) | 5 | 1,474 m² | 78 m² |
| [0.9, 1.0] | 15 | 4,628 m² | **60 m²** |

There is **no gap in the counts** — the two populations are separated by the monotone collapse in
footprint size, 1652 m² to 60 m², against a fixture-wide median building of 230 m². The operating
point is **half-width 4.0 m, overlap limit 0.5**: the last bin whose members are still the size of
a building. It recovers 95% of the lost area.

Half-width by the same test: at 2 m the distribution is too compressed to separate anything
(p95 = 0.46, so nothing is droppable at any limit); at 8 m it swallows the blocks (p90 = 0.98).

**What the rule is not.** Berlin's fixture is 6105 OpenStreetMap footprints against 88 Microsoft
ML, so the high-overlap tail is overwhelmingly OSM kiosks, shelters and garages. This separates
small structures standing in the roadway from blocks fronting it. Calling it an ML-noise filter
would be wrong on this data.

---

## 2. The change

Cleaning forks after a shared prefix, and the two products have different contracts:

```
raw
 └─ fix_invalid → explode → drop_non_polygons → drop_oversized → assign building_id
    ├─ buildings_area = + trim_overlaps                    ← every area statistic
    └─ buildings_topo = + merge_overlaps + trim_overlaps   ← topology
                        + absorb_small_buildings (dissolving, keeping isolates)
                        + road-buffer drop/trim
                        + waterbody drop
```

`buildings_area` gets overlap **trimming** but not merging. This resolves the spec's own conflict
between its "shared operations" sentence and the `buildings_area` list, and it is a correctness
requirement rather than a topological one: building surface fraction sums overlay pieces, so two
footprints overlapping by 50 m² contribute that area twice and BSF can exceed 1.0. Trimming removes
exactly the double count while keeping both features, so `building_count`, `mean_building_area_m2`
and the `building_id` join stay 1:1.

`compute_parameters` now takes both layers: `buildings_area` for BSF, `Hr`, count, mean area and
`industrial_fraction`; `buildings_topo` for `momepy.street_profile` only, because a footprint lying
across a centreline reports a canyon width of zero. The height cascade runs **once**, on
`buildings_area`, and `lczkit.heights.inherit.inherit_heights` carries the result onto
`buildings_topo` by largest overlap — not by `building_id`, which on a dissolved feature names an
arbitrary constituent.

### Retention

| | features | raw area | `buildings_area` | retention |
|---|---:|---:|---:|---:|
| Berlin | 6193 → 6193 | 3.1476 km² | 3.1316 km² | **99.49%** |
| Rotterdam | 1680 → 1680 | 0.7136 km² | 0.7136 km² | **100.00%** |

`buildings_topo` ends at 5533 features / 2.9134 km² on Berlin and 1639 / 0.6902 km² on Rotterdam,
which is what a topological layer is supposed to cost.

---

## 3. Re-run: the three arms

**Berlin**, 957 cells compared, 99.5% of them built:

| arm | Phase 6.5 | **now** | Δ |
|---|---:|---:|---:|
| A — 100 m grid, cleaned | 17.7% | **24.3%** | +6.6 |
| B — enclosures → grid | 17.3% | **28.4%** | +11.1 |
| C — 100 m grid, raw footprints (control) | 26.8% | **24.3%** | −2.5 |

**A and C have converged**, which is this phase's acceptance criterion: the control has no
remaining advantage, so the pipeline is no longer throwing away the numerator. They differ now only
in the self-overlap arm C leaves in, worth 0.51% of Berlin's area and not one flipped label.

*Arm C's definition shifted slightly and its −2.5 is not a regression.* `street_profile` now reads
`buildings_topo` in every arm, so arm C is raw footprints for BSF and the topological layer for
aspect ratio. Previously it fed raw, untrimmed footprints to both, which overstated aspect ratio.
The arm is a cleaner control for its one question than it was.

**Rotterdam**, 657 cells compared, 45.4% of them natural:

| arm | Phase 6.5 | now |
|---|---:|---:|
| A | 42.5% | 42.3% |
| B | 42.2% | 42.0% |
| C | 42.5% | 42.3% |

Unmoved, because Rotterdam's attrition was 8.8% against Berlin's 23.5% and its dominant failure is
elsewhere. Its headline is still mostly water: **89.6% over 298 natural cells against 3.1% over 359
built ones.** Berlin is 99.5% built, so its 24.3% is a built-class figure as it stands.

Per-class agreement, Berlin arm A:

| ref | class | n | Phase 6.5 | now |
|---|---|---:|---:|---:|
| 1 | Compact high-rise | 161 | 1.2% | **0.6%** |
| 2 | Compact midrise | 439 | 25.7% | **39.2%** |
| 4 | Open high-rise | 174 | 9.2% | 8.0% |
| 5 | Open midrise | 92 | 39.1% | **45.7%** |
| 8 | Large low-rise | 29 | 0.0% | 6.9% |
| 10 | Heavy industry | 57 | 0.0% | 0.0% |

## 4. Building surface fraction against the published ranges

Area-weighted median on Berlin units of **known reference class**, area share inside the published
Stewart & Oke interval in brackets:

| ref | published | Phase 6.5 (arm A) | **now (arm A)** |
|---|---|---|---|
| 1 | 0.40–0.60 | 0.326 (34%) | **0.437 (50%)** — inside |
| 2 | 0.40–0.70 | 0.314 (27%) | 0.388 (45%) |
| 4 | 0.20–0.40 | 0.153 (27%) | 0.191 (40%) |
| 5 | 0.20–0.40 | 0.139 (23%) | 0.161 (32%) |
| 8 | 0.30–0.50 | 0.057 (14%) | 0.148 (31%) |
| 10 | 0.20–0.30 | 0.201 (12%) | 0.382 (18%) |

LCZ 1's median now falls **inside** its published range, where before it sat a third of the way
below the floor. LCZ 2 reaches 0.388 against a floor of 0.40 — close, and the remaining shortfall
is no longer attributable to cleaning.

## 5. The confusion axes confirm the mechanism

Share of all disagreement, Berlin arm A:

| | Phase 6.5 | now |
|---|---:|---:|
| height axis (1↔2↔3, 4↔5↔6) | 19.9% | **31.8%** |
| compactness axis (1↔4, 2↔5, 3↔6) | 29.4% | **25.8%** |
| 2↔5 pair | 216 | **173** |
| 1↔2 pair | 49 | **89** |

This is the signature Phase 6.5 predicted for a corrected footprint deficit, now produced by the
pipeline itself rather than by a control arm: error moves *off* the compactness axis — the
footprint-coverage diagnostic — and *onto* the height axis, where the errors underneath become
visible. LCZ 1 falling to 0.6% is the same fact from the other side: compact high-rise is now
overwhelmingly called compact midrise, a pure height-band error.

---

## Residual, and what to go after next

**24.3% against 50–60%.** Roughly two-thirds of the gap is still open, and CLAUDE.md is explicit
that ~27% must not be read as closure. Three candidates, ranked by what the re-run now shows:

1. **The height estimate — promoted to first by this run.** The height axis is now the largest
   single share of disagreement (31.8%, up from 19.9%), 1↔2 alone accounts for 89 cells, and LCZ 1
   collapsed to 0.6%. That is the pattern CLAUDE.md's Phase 3 describes for areal height products,
   and it is measurable directly against `height_completeness`. It was previously masked by the
   footprint deficit.
2. **The metric's missing dimensions.** SVF carries weight 4 and z₀ 0.5 of Bernard's 21.5; lczkit
   applies 17 of those units, leaving `FB` with ~47% of a metric it was never meant to dominate.
   SVF is already first in the deferred priority order, and it correlates with exactly the
   compactness distinctions still failing.
3. **The reference map's own error ceiling.** `lcz_v3.tif` is not ground truth. CLAUDE.md requires
   this ceiling be quantified before the residual is called a defect, and it has not been.

**Range recalibration remains blocked**, and this run does not change that.

## Flagged, not acted on

**Arm B now beats arm A on Berlin — 28.4% against 24.3%.** Phase 6.5 concluded the scale hypothesis
was unsupported on evidence that was, it turns out, taken over a broken numerator: with footprints
restored, enclosures gain 11.1 points against the grid's 6.6 and pull ahead. Enclosure BSF also
lands closer to the published ranges (LCZ 1 at 0.480, LCZ 2 at 0.401 — inside its band).

This does not overturn the Phase 6.5 conclusion by itself. Arm B is still *behind* on Rotterdam
(42.0% vs 42.3%), still worse on its industrial classes, and adopting enclosures as the computation
unit is a pipeline-ordering rule that CLAUDE.md reserves as an explicit decision. It is recorded
here as evidence for that decision, and nothing was changed on the strength of it.

**`buildings_topo` reports `is_planar_enforced: False` on Berlin.** Pre-existing — it comes out of
`resolve_overlaps` that way and did so before this phase, on both the old and new absorb behaviour.
The report records it honestly. Not investigated here; it is outside Phase 6.6's scope.

**Not touched:** prototype ranges, per-parameter weights, the LCZ 10 rule and threshold, the
`bernard2024` → `bernard2024_partial` rename.
