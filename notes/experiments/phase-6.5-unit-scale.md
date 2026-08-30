# Phase 6.5 — the unit-scale experiment

**Result: the scale hypothesis is not supported. Computing on enclosures does not fix agreement.
But the pre-registered fallback — recalibrating the Stewart & Oke ranges — is the wrong next
action, because a measured, mundane cause sits upstream of the classifier.**

Reproduce with `uv run --active python scripts/unit_scale_experiment.py`. Runs offline from the
committed fixtures; writes `unit_scale_experiment.json` into `output/lczkit/<run_id>/`. The numbers
below are from run `20260807T140628Z`.

---

## The question

Measured agreement against the Demuzere global map was Berlin **17.7%** over 957 cells and
Rotterdam **42.5%** over 657. GeoClimate's own OSM-versus-national-database comparison runs ~55%
across French communes, and imagery-based LCZ maps typically reach 50–60%. 17.7% is systematic,
not a tuning problem.

CLAUDE.md's leading hypothesis was a **scale mismatch**. Stewart & Oke's ranges describe an LCZ
*patch*; GeoClimate partitions into street-bounded RSUs precisely because an RSU approximates one.
A 100 m grid cell carries its share of street, so building surface fraction — which carries roughly
47% of the built distance metric — should be systematically depressed.

## Method

| Arm | Computation unit | Buildings | |
|---|---|---|---|
| **A** | 100 m grid | cleaned | the current pipeline |
| **B** | enclosures, projected to the grid by majority for validation only | cleaned | the hypothesis under test |
| **C** | 100 m grid | **raw Overture footprints** | control, added by lczkit |

Arm C is not in CLAUDE.md's design and is not a pipeline option. It exists because A and B alone
cannot separate *"the unit is the wrong size"* from *"the numerator is too small"*, and this phase's
acceptance criterion asks for a recommendation **with the evidence** for it. It applies validity
repair and multipolygon explosion — mechanical steps, without which the overlay fails for reasons
unrelated to the question — and nothing else. Nothing is dropped, merged, absorbed or trimmed, so
its building surface fraction is an *upper* bound rather than a corrected value: A and C bracket
the truth.

The decisive measurement is not agreement but **building surface fraction against the published
range, grouped by the *reference* class**. Grouping by the assigned class asks whether the
labelling is self-consistent, which it is nearly by construction — the classifier put those units
near that prototype. Grouping by the reference class asks whether the parameter can *reach* the
prototype a unit of known type should match. The two give opposite answers on this data.

---

## 1. Agreement — arm B changes nothing

| | A (grid) | B (enclosure→grid) | C (raw footprints) |
|---|---:|---:|---:|
| **Berlin**, 957 cells compared | 17.7% | **17.3%** | **26.8%** |
| **Rotterdam**, 657 cells compared | 42.5% | **42.2%** | 42.5% |

Changing the spatial unit moves Berlin by −0.4 points and Rotterdam by −0.3. Restoring the building
footprints cleaning removed moves Berlin by **+9.1 points**.

Rotterdam is unmoved by either because its cleaning removes only 8.8% of building area against
Berlin's 23.5%. Its higher headline figure is also not what it looks like: 266 of its 657 cells are
water, agreeing at 95.9%. On the built classes it is *worse* than Berlin — LCZ 8 at 0.0% over 224
cells, LCZ 10 at 1.1% over 87.

Per-class agreement, Berlin:

| ref | class | n | A | B | C |
|---|---|---:|---:|---:|---:|
| 1 | Compact high-rise | 161 | 1.2% | 0.6% | **9.3%** |
| 2 | Compact midrise | 439 | 25.7% | 24.8% | **42.1%** |
| 4 | Open high-rise | 174 | 9.2% | 5.7% | 8.0% |
| 5 | Open midrise | 92 | 39.1% | **50.0%** | 42.4% |
| 8 | Large low-rise | 29 | 0.0% | 0.0% | 3.4% |
| 10 | Heavy industry | 57 | 0.0% | 0.0% | 0.0% |

## 2. Building surface fraction against the published ranges — the actual test

Area-weighted median on units of **known reference class**, with the area share falling inside the
published Stewart & Oke interval in brackets.

**Berlin**

| ref | published | A grid | B enclosure | C raw footprints |
|---|---|---|---|---|
| 1 | 0.40–0.60 | 0.326 (34%) | 0.337 (34%) | **0.437 (49%)** |
| 2 | 0.40–0.70 | 0.314 (27%) | 0.338 (32%) | **0.388 (45%)** |
| 4 | 0.20–0.40 | 0.153 (27%) | 0.161 (34%) | 0.191 (40%) |
| 5 | 0.20–0.40 | 0.139 (23%) | 0.154 (17%) | 0.161 (32%) |
| 8 | 0.30–0.50 | 0.057 (14%) | **0.269 (46%)** | 0.148 (31%) |
| 10 | 0.20–0.30 | 0.201 (12%) | 0.220 (28%) | 0.382 (18%) |

**Rotterdam**

| ref | published | A grid | B enclosure | C raw footprints |
|---|---|---|---|---|
| 4 | 0.20–0.40 | 0.140 (30%) | 0.271 (35%) | 0.192 (30%) |
| 8 | 0.30–0.50 | 0.091 (12%) | 0.121 (**4%**) | 0.126 (12%) |
| 10 | 0.20–0.30 | 0.146 (13%) | 0.475 (**0%**) | 0.147 (13%) |
| 17 | 0.00–0.10 | 0.000 (97%) | 0.000 (100%) | 0.000 (97%) |

Arm B moves Berlin's compact classes toward the published bands but does not reach them: LCZ 2's
median rises 0.314 → 0.338 against a floor of 0.40. Arm C reaches it for LCZ 1 (0.437, inside
0.40–0.60) and comes close for LCZ 2. On Rotterdam's two dominant built classes arm B moves the
**wrong way**, dropping LCZ 8 from 12% in-range to 4% and LCZ 10 from 13% to 0% — enclosures there
are whole port basins, and a parameter averaged over one is no closer to a patch than a grid cell
is.

## 3. Both confusion axes — the causal signature

Share of all disagreement, Berlin:

| arm | height axis (1↔2↔3, 4↔5↔6) | compactness axis (1↔4, 2↔5, 3↔6) |
|---|---:|---:|
| A | 19.9% | 29.4% |
| B | 25.0% | 29.2% |
| C | **34.0%** | **24.1%** |

This is the strongest single piece of evidence, and it is why the two axes had to be separated
before the experiment could be read. The compactness axis is the diagnostic for footprint coverage;
the height axis is the diagnostic for the height estimate. Restoring footprints moves error *off*
the compactness axis and *onto* the height axis — the 2↔5 pair alone falls from 216 units to 146,
while 1↔2 rises from 49 to 111.

That is what a footprint deficit looks like when it is corrected: the errors it was causing
disappear, and the height-estimate errors underneath become visible. Arm B produces no such shift,
which is what a hypothesis that is not the cause looks like.

## 4. Arm B got a fair test

Worth stating explicitly, because Berlin's enclosures look alarming: 3243 of them, 2527 under
1000 m², median area 91 m². These are street-margin slivers thrown off by unsimplified parallel
rail tracks — 78% of the count, but **4.1% of the area**.

They did not contaminate the result. The median grid cell takes its label from a 23,516 m²
enclosure, and **no cell is decided by an enclosure under 500 m²**. Area weighting and
largest-overlap projection neutralise them without a sliver-merging step. Arm B's failure is a
property of the hypothesis, not of the enclosures.

## 5. A Phase 2 defect found along the way — fixed

`EnclosureUnits.generate` called `momepy.enclosures` with the default `clip=False` and never
restricted the result to `bbox`. Barrier linework continues past the study area, so faces formed
entirely outside it were returned as units:

| | requested extent | enclosures returned | |
|---|---:|---:|---:|
| Berlin | 9.01 km² | 20.03 km² | **222%** |
| Rotterdam | 6.12 km² | 23.22 km² | **379%** |

The units were not a partition, so every area-weighted statistic over them had the wrong
denominator. Phase 2's acceptance criteria — stable unique `unit_id`s, aggregation round-tripping
sensibly — are both satisfied by such a set, which is why it survived. Fixed by passing
`clip=True`, which is exact rather than approximate: the limit's boundary is part of the noded
linework, so every face is already split at the extent's edge. Both fixtures now total exactly
100%, and `test_units_enclosures.py` asserts it.

---

## Recommendation

**Do not adopt enclosures as the computation unit.** The hypothesis is not supported: agreement
does not improve on either fixture, the parameter it predicted would improve moves only marginally
on Berlin and backwards on Rotterdam, and the confusion axes show no redistribution.

**Do not recalibrate the Stewart & Oke ranges.** CLAUDE.md offers this as the fallback if B fails,
and the measurements do not support taking it. There is a third reading it did not anticipate:

> **Phase 1 cleaning removes 23.5% of Berlin's building footprint area before `FB` is ever
> computed** — 3.148 km² down to 2.408 km², via `absorb_small_buildings` (−1177 features) and
> `drop_buildings_on_streets` (−439).

Restoring it is worth **+9.1 points of agreement**, roughly the whole gap that changing the unit
failed to close, and it moves the parameter into the published range for LCZ 1 where arm B does
not. The deficit is in the numerator, not the denominator — which is exactly why changing the unit
does not help.

Recalibrating published ranges against a parameter biased by an upstream data loss would encode
that loss into the package's definition of an LCZ, permanently and invisibly, and would forfeit
comparability with every LCZ map in the literature. The cheap, reversible action comes first.

**Suggested order.** Investigate the Phase 1 cleaning attrition — in particular whether
`drop_buildings_on_streets` should delete a building that merely touches a street centreline, which
is the normal case for a European perimeter block — then re-run this experiment. Several other
Phase 6 findings are downstream of `FB` and may look different afterwards.

This report stops here. Nothing in cleaning, the prototype ranges, the weights or the LCZ 10 rule
was changed.

---

## Deliberately not done

Range recalibration · weight retuning · the LCZ 10 threshold or its removal from the distance
metric · the cleaning attrition itself, which is a Phase 1 change and the main flag arising here ·
any pipeline ordering rule, since B failed and there is nothing to write.
