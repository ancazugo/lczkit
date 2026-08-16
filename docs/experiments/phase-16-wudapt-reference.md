# Phase 16 — WUDAPT as a reference, and what it says about the other two

CLAUDE.md has named WUDAPT the secondary validation reference since Phase 0 — "and the first if
So2Sat doesn't have sufficient labels for a ROI" — and until this phase `grep -rni wudapt` over the
repository returned prose only. No loader, no config entry, no source-dir constant, zero `.py` hits.

Built here, and turned on the other two references before being turned on the package. That
ordering is deliberate: it is the inverse of Phase 9→10, where the intervention invalidated the
evidence that had ordered the levers, and it is what Phase 14 concluded should have happened.

**Cost: minutes, not hours.** `scripts/reference_comparison.py` runs no pipeline. It compares
references to references on the same 100 m grid and the same 30 km windows every sweep since
Phase 9 has used — sixteen cities in about four minutes, against the 5–9 hours a pipeline sweep
costs.

---

## 1. The question nobody had asked

Every ceiling this project has quoted compares a **model** to labels: `lcz_v3` against So2Sat, 75.2%
on Berlin, 22.8% on Mumbai. Nobody had measured whether the labels themselves reproduce.

They do not, and the spread is enormous.

| city | region | n | WUDAPT vs So2Sat | majority baseline | above baseline | ceiling (`lcz_v3` vs So2Sat) |
|---|---|---:|---:|---:|---:|---:|
| paris | Europe | 2 530 | **96.3%** | 47.9% | 0.93 | 81.3% |
| cologne | Europe | 1 753 | 95.4% | 24.4% | 0.94 | 66.9% |
| rome | Europe | 3 511 | 93.4% | 34.7% | 0.90 | 62.7% |
| berlin | Europe | 7 670 | 91.6% | 29.2% | 0.88 | 75.2% |
| milan | Europe | 1 029 | 89.7% | 41.5% | 0.82 | 79.9% |
| rio de janeiro | S. America | 3 005 | 89.4% | 57.0% | 0.75 | 83.2% |
| são paulo | S. America | 8 237 | 82.1% | 28.9% | 0.75 | 74.1% |
| cape town | Africa | 2 318 | 79.9% | 37.3% | 0.68 | 64.2% |
| london | Europe | 2 490 | 79.9% | 24.7% | 0.73 | 67.5% |
| nairobi | Africa | 1 277 | 79.1% | 21.6% | 0.73 | 38.9% |
| hong kong | E. Asia | 2 279 | 77.7% | 22.9% | 0.71 | 45.9% |
| vancouver | N. America | 2 945 | 77.3% | 40.7% | 0.62 | 36.7% |
| islamabad | S. Asia | 1 208 | 71.5% | 24.9% | 0.62 | 45.1% |
| jakarta | SE Asia | 1 035 | 70.7% | 44.4% | 0.47 | 59.0% |
| mumbai | S. Asia | 728 | 47.4% | 33.1% | 0.21 | 22.8% |
| **cairo** | Africa | 1 492 | **26.3%** | **52.1%** | **−0.54** | 42.5% |

**Median 79.9%, range 26.3%–96.3%.**

> **This is a floor under every residual this package reports.** Where two expert label sets
> disagree about a fifth of the ground, no classifier can agree with both. It is a second
> unquantified floor of exactly the kind the stop-rule already records for patch-versus-cell, and
> it is larger.

`above baseline` is `(agreement − majority-class share) / (1 − majority-class share)`: 1.0 is
perfect, 0.0 is no better than always guessing the commonest class. It is reported because a raw
agreement figure is no more comparable across cities here than it is against a map — Rio's window
carries a 57.0% baseline and Nairobi's a 21.6% one. **It is deliberately not called `lift`**: this
project already has a `lift` with a different null, and two quantities sharing a name inside one
repository is the failure recorded for `CLEANING` and for `industrial_fraction`'s denominator.

### The instrument reproduces the committed record

Berlin's ceiling comes out at **75.2%** on 9 620 cells, against CLAUDE.md's committed 75.2% on
9 627. Cairo 42.5%, Vancouver 36.7%, Mumbai 22.8%, Rio 83.2% all reproduce their Phase 9–11 values.
The new reference is bolted onto an instrument that has not moved.

---

## 2. Cairo: two expert label sets that agree less than chance

26.3% against a 52.1% baseline. The two references are not merely noisy about Cairo; they are
**anti-correlated** with respect to a constant predictor.

Three explanations were available and two are refuted by measurement.

**Age — refuted.** WUDAPT's Cairo polygons span 1990-12-31 to 2023-04-12, which looks like the
answer for a city that transformed across that period. It is not: **1 014 of 1 030 polygons
postdate 2018**, and only 16 predate it. There is no old cohort to blame.

**Contributor quality — refuted, in the informative direction.** Neither gate the format offers
helps:

| gate | polygons kept | Cairo | Mumbai | Jakarta |
|---|---|---:|---:|---:|
| none (shipped default) | 978 / 361 / 935 | 26.3% | 47.4% | 70.7% |
| all three QC flags | 638 / 255 / 376 | 26.7% | 50.3% | **68.8%** |
| submission `oa` ≥ 0.7 | 411 / 331 / 274 | **19.1%** | 47.3% | 69.6% |

The QC gate is inert on two cities and harmful on the third, for half the labelled ground. The
accuracy gate is **worse on all three, and much worse on Cairo** — the city that needed help most.
That is not a null result: the LCZ Generator's `oa` is a cross-validated score of a submission
against *itself*, so a high value marks a self-consistent contributor rather than one who agrees
with an independent expert. Both defaults (`require_qc=False`, `min_oa=None`) are now measured
rather than assumed, and the numbers are in the config docstrings.

**Systematic interpretation difference — supported.** The confusion is structured, not scattered.
Rows are So2Sat, columns WUDAPT, Cairo, n=1 492:

| So2Sat | 1 | 2 | 3 | 4 | 5 | 7 | 8 | 10 | 15 | 16 | 17 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **2** (n=777) | 233 | 113 | 134 | 56 | 191 | 3 | 44 | | | | |
| **8** (n=400) | 5 | 4 | 27 | 4 | 2 | | 54 | **302** | 3 | 3 | |
| **16** (n=104) | | | | | | | | | 41 | 63 | |
| **17** (n=135) | 2 | | | | | | | | | | 133 |

Two relabels carry almost all of it. So2Sat lays a blanket **LCZ 2** over ground WUDAPT contributors
split six ways, and **302 of 400** So2Sat LCZ 8 cells are called LCZ 10 by WUDAPT — the large
low-rise / heavy industry boundary that Stewart & Oke separate only by anthropogenic heat output,
which neither team can measure and lczkit cannot either.

Berlin, by contrast, is near-diagonal: 2→2 1 019/1 019, 4→4 417/418, 6→6 2 091/2 242, 8→8 647,
11→11 383, 17→17 536, and what disagreement there is sits on adjacent classes.

> Cairo scores 3.4% overall and 1.3% built in Phase 9's table, and it is the flagship case for the
> founding premise — 1% tier-1 height coverage. It now turns out its ground truth is the least
> reproducible of the sixteen. **The premise still holds** — the height correlation was measured
> *within* cities in Phase 10 and does not depend on this — but Cairo's specific number was
> measured against a reference another expert team disagrees with more than chance would predict.

---

## 3. The seven-against-nine split, a third time — and this time it is in the reference

> **Superseded in part by the addendum at the end of this file.** North America here is Vancouver
> alone and East Asia is Hong Kong alone. Enlarged to four and six respectively, the grouping
> reorganises: both land with "everywhere else", and the line becomes Europe against everything.
> The measurement below stands over the sixteen cities it was taken on; the *grouping* it is read
> through does not generalise.

| | label reproducibility (mean) | (median) |
|---|---:|---:|
| Europe + N. America (7) | **89.1%** | 91.6% |
| Everywhere else (9) | **69.3%** | 77.7% |

CLAUDE.md records this split twice as an unexplained regularity: Phase 11's enclosure A/B advantage
and Phase 12's compactness lift, both splitting seven against nine along the same line. This is a
third independent sighting, and it is the first that lies **outside lczkit entirely** — it is a
property of the reference data, measured with no pipeline involved.

That does not explain the other two, and it is not offered as doing so. It does change what kind of
hypothesis is admissible: an explanation that only concerns lczkit's morphology now has to account
for why the labels split the same way.

**`corr(label reproducibility, ceiling) = +0.69.`** The cities where two expert teams agree are the
cities where `lcz_v3` agrees with So2Sat. A common cause — how ambiguous the city is to label at all
— fits that better than `lcz_v3` being differently accurate in different places.

---

## 4. Reach: WUDAPT labels 2.7× more ground

| | So2Sat cells | WUDAPT cells | ratio | WUDAPT km² drawn | mean coverage |
|---|---:|---:|---:|---:|---:|
| hong kong | 4 131 | 33 227 | 8.04 | 262.5 | 0.79 |
| mumbai | 1 706 | 13 086 | 7.67 | 95.4 | 0.73 |
| milan | 2 633 | 18 118 | 6.88 | 113.0 | 0.62 |
| jakarta | 2 552 | 16 435 | 6.44 | 112.4 | 0.68 |
| são paulo | 10 161 | 50 248 | 4.95 | 450.9 | 0.90 |
| cape town | 4 415 | 19 744 | 4.47 | 145.0 | 0.73 |
| … | | | | | |
| vancouver | 16 517 | 11 090 | **0.67** | 88.8 | 0.80 |
| **total** | **100 414** | **275 024** | **2.74** | | |

WUDAPT labels more cells in **15 of 16 cities**. Vancouver is the exception, and it is the city
with the densest So2Sat sampling in the set.

The gain is largest exactly where So2Sat is thinnest — Mumbai's 1 706 labelled cells were the
smallest sample in every sweep since Phase 9 and are now 13 086. That matters more than the
headline: Mumbai's figures were the ones most likely to be sampling artefacts.

---

## 5. What was built

`src/lczkit/validation/wudapt.py`, exporting the same three-column contract as `reference_lcz` and
`labelled_lcz` so `agreement()` consumes any of the three without knowing which.

**The reduction is areal, not centroid-anchored.** `labelled_lcz`'s centre rule is justified by a
property WUDAPT does not have — uniform 320 m squares on a 100 m stride. WUDAPT polygons span 0 m²
to 18 680 km² with a median of 4.8 ha, so a centroid rule would let a 4.8 ha polygon and a 1 000 km²
polygon each label exactly one cell. `reference_coverage` is therefore genuinely fractional here,
where `labelled_lcz` reports it as a deliberate binary.

**Overlaps are resolved before the overlay, not during it.** In a 15 × 12 km Kowloon window, 803
polygons form 3 330 overlapping pairs of which 560 carry different classes. `resolve_overlaps`
gives each piece of ground to exactly one polygon — most recent `representative_date`, then higher
submission accuracy, then the smaller (more specific) polygon, then the index — and reports what
that cost. The three areas satisfy `raw = labelled + duplicate + conflict` **exactly**: on the
Berlin fixture, 13 595 047.0 m² both ways.

*Duplicate* is ground yielded to an agreeing polygon, *conflict* to a disagreeing one. Cities
contest 0.09% (Vancouver) to 19.48% (São Paulo) of everything drawn.

**`corr(contested share, label agreement) = −0.14` — hypothesis refuted.** It was reasonable to
expect a reference that contradicts itself to also disagree with an independent one. It does not:
São Paulo contests 19.48% and still reaches 82.1%; Vancouver contests 0.09% and reaches 77.3%. The
internal disagreement rate is worth reporting and is not a proxy for anything.

### Two traps in the file, both now tested against

- **The stored `area` column is unusable.** It is km² computed in Web Mercator, so it is inflated by
  1/cos²(latitude) — the median ratio to true area is 1 004 995 against Mollweide's 744 899. A test
  replaces the column with `-1` and `NaN` and asserts nothing in the output moves.
- **`class` runs to 19, not 17.** 633 polygons globally carry codes 18 and 19, outside the
  Demuzere/So2Sat coding used everywhere else. They are dropped and counted, never folded into a
  neighbour. `_default_reference_dataset` would have raised on them, which is the good failure; the
  bad one was available too, since `unmapped_policy` is a per-dataset setting.

### Smaller decisions

- **Layer resolution is explicit.** The export carries a second layer, `layer_styles`, a QGIS style
  table with no geometry. `read_wudapt` resolves the first *geometry-bearing* layer rather than
  letting the driver pick, which works today and reads the style table the day the order changes.
- **Both spellings of the QC flags.** The file encodes them as `'True'`/`'False'` *and* `'T'`/`'F'`.
  Parsing one would read the other as null and gate on it silently.
- **An unparseable date costs a polygon its priority, not its label.** 9.7% of
  `representative_date` does not parse; those polygons still describe real ground.
- **`OVERLAP_EPS_M2` is a module constant, not config**, per the Phase 1 `eps_m` ruling. The cuts
  leave coordinate-noise slivers around 1e-8 m², so the resolution is exact in *area* and not in
  *topology*; the test asserts on area, and says why.
- **`WudaptConfig.filename` refuses to default.** Contributors keep adding to the LCZ Generator, so
  "whichever gpkg is in that directory" would silently change the reference between runs — the same
  reason `OvertureConfig.release` refuses to track "latest".

### Licensing

The training areas are contributed under `CC BY-SA` and `CC BY-NC-SA 4.0`, per polygon, and both
appear in every window measured. The second is **non-commercial**. That constrains the data, not
this MIT package, which contains no part of it. `WudaptSelection.licences` reads the licences out of
whatever window a run actually used rather than restating a constant, so a manifest states the terms
of what it was scored against.

---

## 6. What is reported and is not a ceiling

`lcz_v3` vs WUDAPT is computed and carries an `independent: False` flag and a written reason,
because **the LCZ Generator's training areas are the training data behind the Demuzere global map**.
It compares a model against a subset of its own training set. It is here so that nobody computes it
elsewhere and reads it as So2Sat's ceiling's equivalent — the mistake Phase 6.7 was opened for, in a
new place where it would look freshly plausible.

The figures bear that out: Vancouver 86.8% and Cologne 80.5% against those cities' real ceilings of
36.7% and 66.9%.

---

## 7. Rulings

1. **Label reproducibility is a reported quantity, not a footnote.** Every agreement figure this
   package emits for a city should be readable beside the number for how much its own references
   agree with each other. Median 79.9% and a floor of 26.3% is not a caveat, it is a term in the
   error budget.
2. **A reference's own quality metrics are not a validation filter.** WUDAPT's QC flags and `oa`
   both fail to improve agreement with independent labels, and `oa` makes it worse. Anything that
   scores a source against itself measures self-consistency, and self-consistency is what a
   *second* reference is for. Defaults stay off, with the measurement in the docstring.
3. **So2Sat stays primary where it exists.** WUDAPT adds reach and support, not authority: it is
   contributor-drawn exemplars against a designed sample. Where both exist, both are reported, and
   `reference_file` names which produced which figure — the standing anti-pattern, and the reason
   this phase could measure anything at all.

---

## Addendum — re-measured over twenty cities, and the grouping reorganised

Added after the fact, on request, and kept separate from the sections above because **those figures
stand over the original sixteen** and must not be quietly restated over a different population.

Section 3 read the seven-against-nine split off a "Europe + N. America" group in which North America
was **Vancouver alone**. A group of one cannot separate a regional effect from one city, so every
So2Sat city in the Americas was screened: **Los Angeles, New York, Washington D.C. and Santiago**
pass the 500-patch / 4-class screen and carry both references, and were added. New York was added
*because* it reproduces badly — keeping the North American city that agrees and dropping the ones
that do not is how a split gets manufactured rather than tested.

Seven more American cities were refused, and not for a windowing reason: So2Sat barely covers them.
Chicago has 48 patches of a single class, Philadelphia 2, Salvador 1, Buenos Aires 5, Bogotá 8,
Caracas 12, Lima 48 — all one class each, which reads as targeted single-class supplements rather
than mapped cities. All seven carry substantial WUDAPT (59–296 polygons, 12–17 classes), so they are
now runnable as **WUDAPT-only** cities with no ceiling and no reproducibility figure. That is new
reach this phase bought, and any record using it has to say which reference it had.

### The headline does not move; the grouping does

Median 79.9% and range 26.3%–96.3% are unchanged at twenty.

| | n | mean | median | above baseline | mean ceiling |
|---|---:|---:|---:|---:|---:|
| Europe | 6 | **91.0%** | 92.5% | 0.87 | 72.2% |
| South America | 3 | 85.6% | 85.3% | 0.77 | 73.5% |
| North America | 4 | **70.8%** | 74.9% | 0.55 | 51.4% |
| "Europe + N. America", as claimed | 10 | 82.9% | 86.2% | 0.74 | 63.9% |
| "everywhere else", as claimed | 10 | 70.9% | 78.4% | 0.52 | 53.9% |
| Europe against everything else | 6 / 14 | 91.0% / 70.9% | 92.5% / 77.5% | 0.87 / 0.53 | 72.2% / 53.2% |

**North America at 70.8% is indistinguishable from "everywhere else" at 70.9%, and South America at
85.6% sits nearer Europe than North America does.** On this quantity the line is **Europe against
everywhere else** — not Global North against Global South, and not the seven-against-nine grouping
this project has used three times. Vancouver, the city the grouping rested on, is now second of four:

| city | agree | above baseline | ceiling |
|---|---:|---:|---:|
| washington_dc | 82.6% | 0.74 | 64.6% |
| vancouver | 77.3% | 0.62 | 36.7% |
| los_angeles | 72.5% | 0.54 | 51.1% |
| new_york | 50.8% | 0.32 | 53.0% |

### What this does and does not settle

It re-measures **one of the four sightings**. Phase 11's enclosure A/B advantage, Phase 12's
compactness lift and Phase 18's tag coverage were all measured over the original sixteen, all with
North America at n = 1, and none is re-measured here — the Overture extracts for the four new cities
are not on disk, so it is a fetch and a sweep rather than a re-analysis.

So the honest statement is narrower than the one above and should be the one that travels: **the
label-reproducibility instance of the regional regularity reorganises when its smallest cell grows
from one city to four.** The other three are untested at n = 4 and should be described as measured
over sixteen, not as confirmed.

It is also a property of the *references*, not of lczkit: it says which cities two expert teams
agree about, not which cities the package maps well.

**Ruling: a regional grouping measured at n = 1 in one of its halves is not a finding.** Check the
smallest cell before a grouping carries an argument.


---

## Second addendum — twenty-eight cities, and the corrected line holds

The first addendum fixed North America at n = 1 and the grouping reorganised. The same defect was
then found twice more: **East Asia was Hong Kong alone**, and Oceania and West Asia were empty. All
51 So2Sat cities were screened against both references; eighteen more qualify, and eight were added:
**Beijing, Guangzhou, Nanjing, Tokyo, Wuhan** (East Asia, 1 → 6), **Istanbul, Tehran** (West Asia,
0 → 2) and **Sydney** (Oceania, 0 → 1).

They are spread across the reproducibility range deliberately — Nanjing 83.2% down to Guangzhou
58.7%, with Tehran at 40.6% — for the reason New York went in: taking a region's agreeable cities
and leaving its disagreeable ones manufactures the split rather than testing it.

### The headline is stable; the corrected grouping holds

| registry | n | median | range |
|---|---:|---:|---|
| original | 16 | 79.9% | 26.3%–96.3% |
| + Americas | 20 | 79.9% | 26.3%–96.3% |
| + East Asia, W. Asia, Oceania | 28 | **79.7%** | 26.3%–**97.7%** |

| region | n | mean | median | above baseline | mean ceiling |
|---|---:|---:|---:|---:|---:|
| **Europe** | 6 | **91.0%** | 92.5% | 0.87 | 72.2% |
| Oceania | 1 | 87.5% | 87.5% | 0.75 | 59.7% |
| South America | 3 | 85.6% | 85.3% | 0.77 | 73.5% |
| East Asia | 6 | 72.3% | 74.1% | 0.60 | 52.1% |
| North America | 4 | 70.8% | 74.9% | 0.55 | 51.4% |
| Southeast Asia | 1 | 70.7% | 70.7% | 0.47 | 59.0% |
| West Asia | 2 | 69.2% | 69.2% | 0.55 | 51.8% |
| Africa | 3 | 61.8% | 79.1% | 0.29 | 48.6% |
| South Asia | 2 | 59.5% | 59.5% | 0.42 | 34.0% |

| cut | n | mean | gap |
|---|---|---:|---:|
| Europe against everything else | 6 / 22 | 91.0% / 71.6% | **19.4 pts** |
| "Europe + N. America" against the rest | 10 / 18 | 82.9% / 71.7% | 11.2 pts |

**East Asia lands at 72.3%, with the elsewhere bloc, exactly as North America did.** The
Europe-against-everywhere-else line has now been tested by quadrupling one group that was supposed
to be inside the old cut and sextupling one that was outside it, and it holds — and it separates
more cleanly than the grouping it replaced.

### Two committed correlations moved with the sample

- **`corr(contested share, agreement)`: −0.14 (16) → −0.13 (20) → −0.36 (28).** Section 5 records
  this hypothesis as *refuted* at sixteen cities. At twenty-eight the flat refutation softens into a
  weak negative — Tehran contests 25.31% and reaches 40.6%, Beijing 16.15% and 64.2%. It is still
  not a proxy for anything, and it is no longer "no relationship at all". Recorded because the
  original figure is committed.
- **`corr(label reproducibility, ceiling)`: +0.69 → +0.58.** Same sign, weaker, same reading.

### What is still n = 1, and cannot be fixed

**Southeast Asia is Jakarta** — the only other So2Sat city in the region is Manila, at 246 patches of
a single class. **Oceania is Sydney** — Melbourne passes So2Sat comfortably (5 506 patches, 7
classes) but WUDAPT holds *one* polygon there. Both are pinned by name in
`tests/test_multi_city_validation.py` rather than tolerated, so a new singleton fails and so does one
of these becoming fixable and not being fixed.

**West Asia is n = 2 with a 57-point internal spread** — Istanbul 97.7%, Tehran 40.6%. That is two
cities, not a region, and no figure should be grouped by it without saying so.

### Deliberately not added

Six European cities qualify — Moscow 99.6%, Madrid 97.5%, Zurich 88.1%, Amsterdam 83.5%, Lisbon
76.8%, Munich 76.6%. Europe is already over-represented at six of twenty-eight, and adding six more
would weaken the very comparison this enlargement exists to test. **Moscow is excluded on its own
merits as well**: its 99.6% rests on an overlap of 225 cells, because its two references drew
different parts of the city, and a near-perfect figure on a thin non-random intersection is the kind
that gets quoted and then retracted.

Two cities pass So2Sat well and have **no WUDAPT at all** — Osaka/Kyoto (5 134 patches, 13 classes)
and Dongying (1 936, 10). They are So2Sat-only, with no reproducibility figure available.

Ten more fail on So2Sat, every one with a single class: Bogotá, Buenos Aires, Caracas, Chicago,
Dhaka, Karachi, Lima, Manila, Philadelphia, Salvador. All ten carry real WUDAPT, so they are
reachable as WUDAPT-only cities with no ceiling — and a record using them would have to say which
reference it had.
