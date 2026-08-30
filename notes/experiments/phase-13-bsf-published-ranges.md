# Phase 13 — BSF against the published ranges

The last diagnostic. Phase 12 named unit definition and footprint coverage as the next lever, on a
normalised compactness lift of 1.16 against height's 0.86, and found that lift **higher in Europe**
(2.37) than elsewhere (1.15). Europe has the best footprint coverage in the sample, so a coverage
explanation predicts the opposite ordering. This phase asks the parameter directly, on cells whose
class is known: **is building surface fraction inside the Stewart & Oke interval, and does the
answer differ by region?**

Three outcomes were pre-registered in the spec, each of which ends the diagnostic sequence:

- **inside** — the issue is the classifier's boundary placement, not the parameter.
- **depressed, worse in Europe** — unit definition is the cause; a structural limit of grid-based
  LCZ mapping, and a paper result rather than a bug.
- **depressed uniformly** — the published ranges do not transfer to 100 m cells; report the
  published-range result and an empirical recalibration side by side, and do not silently
  recalibrate.

---

## 1. The phase could not be the cheap re-analysis it was scoped as

The brief scoped this as "the same cheap shape as Phase 12: re-analysis of stored records, seconds
not hours". Two things were wrong with that premise, and the second one is the phase's first result.

**The stored table is more current than the brief assumed.** The brief says the test "was last run
on Berlin and Rotterdam before the cleaning fix, the union fix and the height cascade — all three
change BSF". In fact it ran on all sixteen cities in Phase 11 (`20260812T184810Z`), *after* the
cleaning fix and after the cascade, and the union fix changed only retention reporting — Phase 12
deliberately did not touch `trim_overlaps`, so BSF did not move. Good news, and irrelevant, because:

**The stored table is grouped by the wrong reference.** `unit_scale_experiment.evaluate` built
`bsf_by_reference_class` from `fixture.reference`, whose own docstring reads:

> The Demuzere global map, clipped. **A comparator, never the primary reference.**

`fixture.ground_truth` — the hand-labelled So2Sat patches CLAUDE.md makes primary wherever they
exist — went unused by the range test. The scale of the substitution, on Berlin: the stored BSF
table covers **91 158 cells** of another model's estimate of the class, where **9 627** carry a hand
label.

This is the second reference mix-up. Phase 12 caught the first in
`unit_scale_experiment.show()`, which printed `lcz_v3` axes under an unlabelled heading. That one
did not contaminate published figures. This one is the instrument the phase was to be decided on.

Per-unit BSF is not persisted — only the per-class aggregate — so the labels-grouped table had to be
computed, and the sixteen cities were re-run at `coarse` to get it. Both groupings are reported side
by side, because whether they agree is itself a result.

---

## 2. What was built

**`RangeReport.reference_file`** (`src/lczkit/validation/ranges.py`). The mix-up was possible
because a range report did not name what it grouped by: `grouped_by` said `"reference"`, which is a
*role*, and two very different files can fill it. A table that does not name its reference cannot be
compared with another one, and the failure is invisible because both look like "the reference
class". `grouped_by` now also admits `"ground_truth"`, and the module docstring records that the two
disagree and that Phase 6.7 measured the substitution inverting a diagnosis.

**`bsf_by_ground_truth_class`** (`scripts/unit_scale_experiment.py`), beside the existing two
groupings, computed on the **arm's own units** — mirroring the `native_reference` pattern directly
above it, so arm B's enclosures get labels matched natively rather than through the grid projection.
`None` where a city has no labelled coverage, so Rotterdam says so rather than implying otherwise.

**`scripts/bsf_published_ranges.py`**, the phase driver. Sixteen cities, `coarse` only, arm A
headline, reusing `prepare`/`run_city` exactly as Phase 11's driver does, with the same
write-after-every-city resilience so an interrupted sweep is still evidence.

### 2.1 The decision statistic is `share_in_range`, not the median

A share is exactly poolable across cities: it is inside-area over total-area, so a cell-weighted
mean of per-city shares *is* the pooled share. A median is not — "the median of sixteen medians" is
not a quantity anyone can interpret, and the cities differ in size by an order of magnitude
(Vancouver 16 517 labelled cells against Mumbai's 1 706). The share is also the more literal reading
of the question the phase asks. Per-city medians are still reported, as the area-weighted mean of
city medians and labelled as such, so nobody reads one as a pooled median.

Everything is pooled by area rather than by city, for the reason `ranges` and `agreement` are:
a mean of per-city means lets the small cities outvote the large ones.

### 2.2 The verdict rule was fixed before the sweep ran

So the outcome is not chosen after seeing it. A class **reaches** its range when more than half its
area falls inside (`REACHES_RANGE = 0.5`). Then:

- **inside** — classes holding at least half the built cells reach their range.
- **worse_in_europe** — Europe and North America trail the rest by at least `REGIONAL_GAP = 0.05`
  in pooled share, in a majority of the classes both hold.
- **depressed_uniformly** — otherwise.

The rule is unit-tested against constructed inputs for each of the three branches, including the
case where Europe *leads*, because a sign error there would invert the phase's conclusion.

### 2.3 Pre-registered expectations, and the disclosure that goes with them

These were formed **after** inspecting the stored `lcz_v3`-grouped table, which was the only one
that existed. They are predictions about the labels-grouped table, which did not exist when they
were written. Recorded in the run JSON alongside the disclosure.

- **P1** — BSF is depressed: classes holding most built cells have a pooled `share_in_range` below
  0.5.
- **P2** — the depression is **not** worse in Europe and North America, refuting the mechanism the
  brief proposes (street area inside the 100 m cell biting hardest on compact perimeter-block
  fabric).
- **P3** — the two groupings disagree materially, as Phase 6.7 measured them doing.

---

## 3. Results

Sixteen cities, `coarse`, arm A, **5.09 h**, no city skipped or failed. Run
`20260813T161048Z`.

### 3.1 The harness is stable, and that is worth recording

Every city's `lcz_v3` table reproduces Phase 11's **exactly** — max |Δ| **0.0%** across ten built
classes, on both the median and the share, and bit-identical class by class on Berlin. Phase 12
bumped `TILE_RESULT_VERSION` to 3, so every tile in this run regenerated cold, and the answer did
not move. That is an independent confirmation of the row-order determinism fix, taken over sixteen
metropolitan extents rather than one.

### 3.2 The outcome: **depressed uniformly** — the third pre-registered outcome

Grouped by So2Sat labels, arm A, `coarse`, pooled area-weighted across sixteen cities:

| LCZ | class | published | mean of city medians | gap (widths) | in range |
|---|---|---|---|---:|---:|
| 1 | Compact high-rise | 0.40–0.60 | 0.431 | 0.00 | 34.2% |
| 2 | Compact midrise | 0.40–0.70 | 0.376 | −0.08 | 42.3% |
| 3 | Compact low-rise | 0.40–0.70 | 0.360 | −0.13 | 35.4% |
| 4 | Open high-rise | 0.20–0.40 | 0.186 | −0.07 | 31.5% |
| 5 | Open midrise | 0.20–0.40 | 0.227 | 0.00 | **53.5%** |
| 6 | Open low-rise | 0.20–0.40 | 0.192 | −0.04 | 39.7% |
| 7 | Lightweight low-rise | 0.60–0.90 | 0.417 | −0.61 | 8.2% |
| 8 | Large low-rise | 0.30–0.50 | 0.293 | −0.04 | 27.6% |
| 9 | Sparsely built | 0.10–0.20 | 0.082 | −0.18 | 29.6% |
| 10 | Heavy industry | 0.20–0.30 | 0.138 | −0.62 | 15.0% |

Only **LCZ 5** reaches its range under the pre-registered bar, and it holds 11.9% of built cells —
far below the half the "inside" outcome requires. Grouped by `lcz_v3` instead, **no class reaches
at all**. So the outcome is the third one, under both references.

### 3.3 The shape of it is dispersion, not bias — and that is the useful part

The medians are close. Six of ten classes sit within 0.13 interval-widths of their published band,
and LCZ 1 and LCZ 5 sit **inside** it. A parameter that was systematically wrong would not do that.
What fails is the spread. Published interval against the empirical one, both reported per the
outcome-3 ruling:

| LCZ | published | empirical p10–p90 | published width | empirical width |
|---|---|---|---:|---:|
| 1 | 0.40–0.60 | 0.19–0.69 | 0.20 | 0.50 |
| 2 | 0.40–0.70 | 0.19–0.54 | 0.30 | 0.35 |
| 4 | 0.20–0.40 | 0.03–0.43 | 0.20 | 0.40 |
| 8 | 0.30–0.50 | 0.05–0.61 | 0.20 | 0.56 |
| 10 | 0.20–0.30 | 0.01–0.44 | 0.10 | 0.43 |

**Caveat, stated because the comparison invites over-reading:** p10–p90 is an 80% interval, while
Stewart & Oke's ranges are typical-value ranges with no stated coverage. The two are not the same
kind of object, so the width ratio is indicative rather than a test. What *is* a test is
`share_in_range`, and it says the mass leaks out of the band.

Which way it leaks separates two groups:

- **Dispersed** — LCZ 1, 4, 8, 9, 10, whose p90 sits *above* the published maximum while the p10
  sits far below. Mass escapes both sides. These cells are not too empty; they are too varied.
- **Genuinely depressed** — LCZ 2, 3, 7, whose p90 is below the published maximum (0.54 against
  0.70, 0.47 against 0.70, 0.56 against 0.90). Here the whole distribution sits low.

This is the Phase 6.5 hypothesis returning — that Stewart & Oke's ranges describe an LCZ *patch*,
which is homogeneous by construction, and a 100 m cell is not one — but arrived at from the
opposite direction. Phase 6.5 rejected it while measuring over a numerator that was losing 23.5% of
its footprints. With the footprints restored, the cascade filled and the right reference in place,
the central tendency is roughly right and the within-class variance is what the published bands
cannot accommodate.

### 3.4 LCZ 7 is a coverage finding, not a range finding

Lightweight low-rise sits at 0.417 against a published 0.60–0.90, with **8.2%** of area in range —
the worst class in the table, and low on both tails. LCZ 7 is informal settlement, and 0.417 against
a floor of 0.60 is the signature of footprints that are present but under-drawn. Five cities carry
it, all outside Europe and North America. Worth naming as an Overture coverage limit in its own
right; it is not evidence about the 100 m cell.

---

## 4. Expectations

**P1 — CONFIRMED.** BSF is depressed. One class of ten reaches its range, holding 11.9% of built
cells against the 50% the "inside" outcome needs; under `lcz_v3`, none reaches.

**P2 — CONFIRMED, and the brief's mechanism is refuted.** Europe and North America trail the rest
on **2 of 9** shared classes (LCZ 3 and 6), not the majority the rule requires. They *lead*
substantially elsewhere — LCZ 2 by **+35.4 points** (56.3% against 20.9%), LCZ 5 by +9.6, LCZ 1 by
+9.4. Europe's compact midrise is the single best-performing region-class cell in the whole table.

The brief proposed that BSF is depressed by street area inside the 100 m cell and that "Europe's
compact perimeter-block fabric is where that bites hardest". It bites *least* there. The one real
European anomaly runs the other way and is thin: LCZ 3 in Europe sits at 0.249 with 1.5% in range,
but on two cities and 3 591 cells.

**P3 — PARTIAL, and the honest reading is the smaller one.** The two groupings do disagree
materially class by class: mean |Δ| **6.7 points** over ten classes, reaching **18.2 points** on
LCZ 9 (29.6% against 11.4%) and 10.0 on LCZ 4. They disagree on whether LCZ 5 reaches its range,
which is the one class that does. **But they give the same phase outcome.**

So the reference substitution was a real defect, worth the fix and worth the five hours to find out
— and it did not change this phase's conclusion. Reporting it the other way round would be the
same over-claiming this project has caught itself in repeatedly. What the fix buys is that the
class-level figures are now against the reference CLAUDE.md makes primary, and that the next person
to use `RangeReport` cannot make the substitution silently.

---

## 5. The ruling, and the sequence closes

**Outcome 3: the published ranges do not transfer to 100 m cells.** Per the pre-registered
response, the run JSON carries the published interval and an empirical one side by side, the
empirical one tagged `source: "lczkit_empirical"` with its definition attached.

**Nothing is recalibrated.** `prototypes.py` still transcribes
`docs/references/tables/stewart_oke_2012_properties.md` and nothing writes back into it. The
comparability argument that blocked recalibration in Phase 6.5 is unchanged: a package that quietly
redefines an LCZ against its own measurements forfeits the ability to be compared with the
literature, and the empirical intervals here are wide enough that fitting to them would encode this
sample's heterogeneity as a definition.

**The diagnostic sequence is closed.** Per the stop rule, no further diagnostic phases. Remaining
work is Phase 7, the paper, then cleanup.

### 5.1 What this says about the lever

Phase 12 named unit definition and footprint coverage, and this phase sharpens it without
overturning it. The compactness lift being higher in Europe is not explained by depressed BSF in
Europe — Europe's BSF is the *healthiest* in the sample. What the table shows instead is that the
100 m cell delivers a within-class spread the published bands were never drawn for, which is a unit
statement rather than a coverage one. It is also **not** an argument for enclosures: Phase 12
measured arm B raising the compactness lift, and Phase 11 declined them on their own evidence three
times.

That is a paper result about the method, not a defect list for the package.

---

## 6. Acceptance

| criterion | result |
|---|---|
| per-region, per-class BSF-versus-published table, sixteen cities at `coarse` | yes, §3.2, and per region in the run JSON |
| a stated outcome among the three | **depressed uniformly**, under both references |
| statement that the diagnostic sequence is closed | §5 |
| do not silently recalibrate | nothing written back to `prototypes.py`; empirical intervals tagged and confined to the JSON |
| ruff, `ruff format`, mypy clean; pytest green offline | yes |

Two things this phase leaves for someone else. **LCZ 7's 8.2%** is an Overture coverage limit on
informal settlements and deserves its own measurement, not a range test. And the **dispersion
finding suggests a per-cell heterogeneity measure** — the spread of BSF within a unit's
neighbourhood — would say more about whether a cell can hold an LCZ than any recalibration would.
Neither is opened here; the stop rule applies.
