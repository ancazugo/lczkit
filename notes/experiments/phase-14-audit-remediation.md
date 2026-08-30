# Phase 14 — Audit remediation

Not a diagnostic phase. It opened no new question. It came out of an external audit of the
classification, parameter, height, cleaning and validation layers, and its job was to close the gap
between what `CLAUDE.md` records as decided and what the code does.

The audit's headline was that the package is in good *engineering* health — 664 tests passing,
`ruff` and `mypy` clean, the Stewart & Oke transcription exact when diffed programmatically against
the committed table, and the genuinely hard parts of the distance metric (open bounds,
unconstrained dimensions, null renormalisation, the family gate) correct and well tested.

The defects were semantic, and they had one shape.

---

## 1. The spec moved and the code did not

`git log` dates the whole problem. The classify layer was last touched in `3931bbe`. The rulings
that superseded its behaviour were applied to `CLAUDE.md` in `f374e4e`, seven days later. Nothing
reconciled the two, in either direction, and nothing could have: no test compared a ruling against
the code implementing it.

Four rulings recorded as decided were not implemented:

| ruling | recorded | code state when audited |
|---|---|---|
| LCZ 10 pair gate "measured inert, replaced" | Phase 6 | pair gate present verbatim, 8 phases later |
| threshold "calibrated, not picked" | Phase 6 | picked a priori at 0.50 |
| `bernard2024` → `bernard2024_partial` | Phase 6 | never renamed |
| `industrial_fraction` denominator | Phase 5 | contradicted three ways at once |

The denominator is the one worth dwelling on, because it was not a lag — it was a live
disagreement *inside the repository*. `CLAUDE.md`'s resolved-discrepancy table and
`ucp/parameters.py`'s docstring both said building area. `ucp/industrial.py`, `config.py` and
`ucp/registry.py` all said unit area, and `config.py` argued for it explicitly, stating that
Bernard's 0.33 therefore does not transfer. Any reader of a stored `industrial_fraction` column was
reading one of two quantities with no way to tell which.

**Two further rulings were being actively violated by live code**, which is a different failure from
a lag — the ruling was applied everywhere except the place that mattered:

- `multi_city_validation.py:256` summed `share_of_disagreement` across sixteen cities and took
  medians of it. Phase 12 Ruling 1 retired that quantity outright — "removed from reporting", not
  "use with care" — and this script was the reporting path never migrated. `unit_scale_experiment.py`
  was a third reader.
- The same script printed **"% of ceiling"** in two places, which Phase 9 recorded as broken
  (Vancouver scores 41.8% against a 36.7% ceiling, which reads as 114%).

`axis_reconciliation.py` keeps its raw-share column and is exempt: printing the broken quantity
beside what replaces it *is* the Phase 12 measurement.

---

## 2. LCZ 10, calibrated — and the threshold is not the binding constraint, again

`scripts/lcz10_threshold_sweep.py`. Nineteen thresholds from 0.05 to 0.95, both denominators,
against the Rotterdam reference. Everything it reads is committed under `tests/fixtures/`, so it
runs offline; and Rotterdam is the one place `CLAUDE.md` permits scoring against `lcz_v3` rather
than labels, for this rule only, because no So2Sat coverage exists there.

**Reference: 88 LCZ 10 cells of 658 scored.**

`industrial_fraction_of_building_area` (Bernard's `FIND/B`) — the shipped column:

| threshold | predicted | TP | FP | precision | recall |
|---:|---:|---:|---:|---:|---:|
| 0.05 | 135 | 28 | 107 | 20.7% | 31.8% |
| 0.30 | 107 | 24 | 83 | 22.4% | 27.3% |
| **0.45** | **95** | **22** | **73** | **23.2%** | **25.0%** |
| 0.95 | 30 | 5 | 25 | 16.7% | 5.7% |

`industrial_fraction_of_unit_area`:

| threshold | predicted | TP | FP | precision | recall |
|---:|---:|---:|---:|---:|---:|
| 0.05 | 332 | 81 | 251 | 24.4% | 92.0% |
| 0.50 | 243 | 63 | 180 | 25.9% | 71.6% |
| 0.80 | 196 | 52 | 144 | 26.5% | 59.1% |
| 0.95 | 174 | 45 | 129 | 25.9% | 51.1% |

### The rule fires. The pair-gated one never did.

That much is the ruling working: functional assignment reaches the port at every threshold, where
the pair gate produced zero LCZ 10 cells at 0.05, 0.25 and 0.5 alike.

### But `CLAUDE.md`'s stated expectation is refuted

The spec says to "expect to land high-precision, low-recall". **High precision is not reachable at
any threshold on either column.** On `FIND/B` precision moves about six points across a nineteen-fold
change in threshold. What the threshold governs is *how much* of the map carries LCZ 10.

That is what decides the default. `FIND/B` at 0.45 labels **95 cells against a reference of 88**;
the unit-area share at its own best operating point labels 196. When precision cannot be improved,
matching the rate is what is left to get right — and Bernard's published 0.33 sits just below the
selected point and performs comparably (22.4% / 27.3%), so the shipped threshold is not in tension
with the paper it comes from.

### A retraction, recorded at length because it was nearly shipped

The first pass through this measured something else entirely, and concluded something wrong.

It measured `FIND/B` **saturating**: 83.9% of cells holding any industrial building area reading
exactly 1.0, with a median cell holding two buildings. The conclusion drawn was that a share over a
two-element denominator is not a share, that Bernard defines `FIND/B` over an RSU and it does not
survive the move to a cell, and that this was **a third independent instance of Phase 13's
patch-versus-cell finding** — a genuinely interesting result that promotes a single measurement into
a general claim about the method. It was written into `CLAUDE.md`, the paper's argument, the README
and the config docstring before anything checked it.

**It was an artefact of the numerator.** That numerator counted every building standing inside an
industrial *parcel* as industrial. Parcels are large and swallow whole cells, so any cell touching
one read 1.0 regardless of what stood in it. Counting industrial *buildings* — which is what
`FIND/B` means, and what the paper's `IND` typology refers to — gives:

| | cells | at 1.0 | p10 | median |
|---|---:|---:|---:|---:|
| `FIND/B`, as first built (buildings ∪ parcels) | 311 | **83.9%** | 0.894 | 1.000 |
| `FIND/B`, corrected (industrial buildings) | 143 | **12.6%** | 0.113 | 0.660 |
| `industrial_fraction_of_unit_area` | 366 | 42.6% | 0.088 | 0.906 |

Real spread, and the unit-area share is the *more* saturated of the two — the opposite of what was
concluded. The `FIND/B` instance of patch-versus-cell is void. The other two stand, and one of them
(the So2Sat labels) is independent of any of this.

**What is worth keeping from the episode.** A scale finding and a definition bug produce the same
distribution, and cannot be told apart from the distribution alone. The scale story is the more
interesting of the two, which is precisely why it was believed first and propagated into four
documents before the numerator was questioned. What separated them was changing the definition and
re-measuring — not more careful reading of the same numbers.

It also surfaced the second defect below, because both live in the same function.

---

## 2b. A performance regression, in the phase auditing for regressions

Berlin's 891 km² extent stopped completing inside 50 minutes, having previously run end to end in
under ten. The cause was in the same `industrial_metrics` change, and it was three whole-extent
geometric operations added at once:

- `union_all()` over industrial buildings, where `buildings_area` is already non-overlapping and
  needs no dissolve;
- a second `union_all()` over the combined evidence, for the intersection below;
- `buildings.geometry.intersection(...)` over **every footprint in the city** — 892k at Berlin —
  against that dissolved geometry.

Plus a full `units × buildings` overlay duplicating one `building_metrics` had already run.

All four are gone. The numerator overlays the industrial subset alone (a few hundred features on the
fixtures), and the denominator is handed down from `building_metrics` as
`building_surface_fraction × unit_area` — exact, free, and it guarantees the ratio shares a
denominator with `building_surface_fraction`.

The standing anti-pattern is explicit about this: *"Don't introduce a whole-extent operation without
measuring its scaling exponent at three or more extents"*, and *"don't assume a geometric set
operation is cheap because its result is a scalar"* — the latter written after Phase 12 measured
`unary_union` over Berlin's footprints at 711 s. **The fixtures are 9 km² and reported nothing.**
This phase broke the rule while auditing the codebase for broken rules.

---

## 3. LCZ 8 fails by construction

Diagnosed from the metric's structure, without reference to any run.

`CLAUDE.md` justifies keeping LCZ 8 in the distance metric — a documented divergence from Bernard,
who excludes it — on the grounds that "its character is genuinely morphological and mean building
area captures it". **`mean_building_area_m2` is not one of the metric's dimensions.** It never has
been; `PROPERTIES` carries twelve entries and that is not among them, because Stewart & Oke publish
no such property.

So what actually separates LCZ 8? Reading the transcribed table:

| | BSF | Hr (m) | aspect ratio |
|---|---|---|---|
| LCZ 3 compact low-rise | 0.40–0.70 | 3–10 | 0.75–1.5 |
| LCZ 6 open low-rise | 0.20–0.40 | 3–10 | 0.3–0.75 |
| **LCZ 8 large low-rise** | **0.30–0.50** | **3–10** | **0.1–0.3** |
| LCZ 9 sparsely built | 0.10–0.20 | 3–10 | 0.1–0.25 |

LCZ 8's BSF band overlaps both LCZ 3 and LCZ 6. Its `Hr` band is **identical** to LCZ 3, 6 and 9.
The only dimension that separates it from LCZ 3 and 6 is `aspect_ratio` — and `aspect_ratio` is
null precisely where large setbacks mean no street tick reaches a building, which is the definition
of large low-rise fabric.

**The ruling stands; its stated reason was wrong.** LCZ 8 is retained in the metric because
excluding it would leave it assignable only functionally, which is worse. But it is separable only
on a parameter that is missing in the fabric it describes, which predicts Phase 6.7's measured
**LCZ 8 = 0.0% (n=224)** on Rotterdam from structure alone rather than from a run.

---

## 4. LCZ F is unreachable by arithmetic, not by configuration

`config.py` framed the exclusion of LCZ C and LCZ F from `reachable_natural_classes` as one policy
choice covering both. It is two different things.

C is genuinely excluded by the setting: it differs from D on aspect ratio (0.25–1.0 against ≤0.1)
and on `Hr` (≤2 m against ≤1 m), both weight 1.0 in the natural vector, so where those are non-null
C wins outright. The tie is real only where both are null, which for a buildingless unit is the
common case — hence the exclusion.

F is excluded by containment. D's prototype box contains F's in **every** dimension — identical on
aspect ratio, building, impervious, pervious, tree and water, wider on `Hr` (≤1 m against ≤0.25 m).
A contained box can never be strictly nearer than its container, so `d(F) >= d(D)` for every
possible unit, and ties break to the lower code. **Adding `"F"` back to the config cannot make F
assignable.** A docstring calling that a policy choice invites someone to try and get silence; the
manifest now records *dominated* separately from *excluded*.

---

## 5. `OA_w` is blocked, and was not guessed

The plan called for the LCZ-community weighted accuracy, which scores 1↔2 as a smaller error than
1↔G and is what makes per-class figures comparable to published LCZ maps.

Both Demuzere papers on disk define it and neither prints the matrix:

> "The weighted accuracy (OA w) is obtained by applying weights to the confusion matrix and
> accounts for the (dis)similarity between LCZ types (**Bechtel et al., 2017, 2020**)."
> — Demuzere et al. (2021), §2.4, p. 6; near-identical wording in Demuzere et al. (2022), §2.4

`docs/references/papers/` holds `bechtel_2015_wudapt.pdf` and neither of the cited papers. Per the
standing anti-pattern — *"Don't reproduce a Tier 1 numeric range from memory. Read
`docs/references/tables/`, or say the reference is unavailable"* — no matrix was inferred and the
metric was not built.

**To unblock: place Bechtel et al. (2017) or (2020) under `docs/references/papers/` and transcribe
the matrix into `docs/references/tables/lcz_class_similarity.md`.** `tests/reference_tables.py`
already has the pattern that keeps such a table and its code in lockstep.

What did ship: per-class **user's accuracy** and **F1** (Demuzere's own class-wise metric,
"a harmonic mean of the user's and producer's accuracy"), and **`OA_bu`**, the built-versus-natural
accuracy ignoring internal differentiation. `OA` and `OA_u` were already present.

---

## 6. Uncertainty, at last

Every headline this package reports has been a point estimate, compared across cities, differenced
between arms, and used to order the next lever. `axis_reconciliation.py:569` compares
`max_over_median_lift` against a hard `< 5.0` as though it were a test statistic.

`lczkit.validation.uncertainty` adds a **spatial block bootstrap** over `overall_agreement`,
`built_agreement`, `built_natural_agreement` and both axis lifts.

Blocks, not cells, and the reason is measured elsewhere in this repo: So2Sat patches are 320 m
squares on a **100 m stride**, so neighbours overlap about sevenfold and a city's labelled cells are
one contiguous, strongly autocorrelated sheet. Resampling cells independently would treat ~9 600
near-duplicate observations as 9 600 independent draws and return an interval far too narrow. The
test suite asserts the direction: blocking must not report a *narrower* interval than cell-wise
resampling on spatially structured error.

The default block is 1 km, comfortably above the 320 m patch width that generates the dependence,
anchored on the CRS origin like `GridUnits` so two runs over overlapping extents partition
comparably, and reported in the output rather than left to be inferred.

**What it does not do:** it quantifies sampling variability. The label support mismatch below is a
*bias*, and does not shrink with more cells.

---

## 7. Patch versus cell — one new instance, not two

Phase 13 concluded that Stewart & Oke's parameter ranges describe an LCZ patch and do not transfer
to a 100 m cell. This phase adds **one** further instance. It briefly claimed two; see §2's
retraction for why the `FIND/B` one is void.

1. **The parameter ranges** (Phase 13). Medians are close — six of ten within 0.13 interval-widths
   — and the *spread* is what the published bands cannot hold.
2. **The So2Sat labels themselves.** A 320 × 320 m patch label — 10.24 ha — is attributed to one
   1 ha cell whose centre sits systematically ~22 m from the patch centre. A 100 m cell inside a
   compact-midrise patch can legitimately be a courtyard.

The second is the consequential one, and it had not been stated anywhere. **Both the parameter
ranges and the ground truth are patch-scale objects, and lczkit is the only cell-scale thing in the
comparison.** That is an unquantified floor under the 35.3%-against-75.2% Berlin gap, and it
reframes part of that residual as a units-of-measurement mismatch rather than classifier error.

It is also worth noting what makes this instance trustworthy where the retracted one was not: it
rests on the *geometry of the sampling design* — patch width, stride and offset, all measurable
from the fixture without reference to any parameter lczkit computes — rather than on the shape of a
distribution this package produced. A finding about the reference is harder to contaminate with a
bug in the code being evaluated.

It also, incidentally, corrects a claim in `labelled.py`'s docstring: the 1:1 patch-to-cell property
holds, but not because "the patch grid and `GridUnits` are both aligned to the local UTM origin".
Measured on the Berlin fixture in EPSG:32633, the patch centres sit at a fixed phase offset of
**(40.0, 70.0) m** from the cell corners. The property is robust for a better reason than the one
recorded — that offset is far from both 0 and 50 m, so no centre can land on a boundary.

---

## 8. `Hr`: one building, one vote

Phase 1's shared prefix runs `explode_multipolygons` *before* the two building layers fork. A
courtyard block or a multi-wing complex that Overture supplies as a MultiPolygon therefore reaches
Phase 5 as N rows carrying one height — and `Hr` is an **unweighted** mean of logs, so that is N
equal terms where there should be one. A multi-part footprint outvoted its single-part neighbours N
to one, for a reason about data encoding rather than about the city.

`FEATURE_ID` is now stamped before the explode and the parts collapse on it. The same fix applies to
`building_count` (inflated) and `mean_building_area_m2` (deflated).

`h_geometric_area_weighted` also ships, **secondary and unused by classification**. `Hr` stays
unweighted because Bernard's Table 1 specifies that form and the Stewart & Oke ranges Phase 6
normalises against were defined for it — weighting it would change the definition of an LCZ
silently. But the unweighted mean gives a 5 m² shed the same vote as a tower block, and Phase 10
already established that `Hr`'s sensitivity to dispersion is exactly what made the *most accurate*
height product degrade the map. This column makes the size of that effect measurable without moving
a published number.

---

## 9. Smaller corrections

- **`eps_final_m` misreported.** Derived after the loop by dividing the escalated value back down,
  which is wrong precisely where the escalation stops: once `eps` saturates at the 1 mm ceiling, two
  passes share a width and the division reports one never used. Exactly the kind of provenance the
  module exists to record.
- **`industrial_fraction_land_use` could exceed 1.0.** Its no-dissolve branch justified itself on
  Phase 1 having removed within-layer overlaps — true of `buildings_area`, and false of `land_use`,
  which `cleaning/land_use.py` states outright gets "no overlap resolution" of any kind.
- **An empty land-cover group answered 0.0 for units the raster never reached**, contradicting the
  module's own "a null land-cover fraction is not zero cover".
- **`aggregate("area_weighted")` reported no coverage.** It normalises by summed overlap area, not
  target area, so a target one tenth covered was indistinguishable from a fully measured one. The
  normalisation is left alone — changing it would move every arm-B projection — and coverage is now
  reported beside the value.
- **`FootprintCoverage`'s ratios were `@property`**, so `union_retention` — Phase 1's acceptance
  criterion — appeared in no serialised artefact. A reader of a manifest saw four raw areas and had
  to know the formula.
- **`n_params_used` mixed two scales silently:** 3 for a built unit under the default preset, 7 for
  a natural one, because zero-weighted dimensions leave both sides of the renormalisation.
  `n_params_available` now says which.
- **Distance columns were renamed positionally**, assuming each family's frame comes back in code
  order. True today; a mislabelled distance vector would have been silent.

---

## 10. Rulings

1. **A ruling is not applied until the code says so.** This is Phase 7's failure in the opposite
   direction: there, code shipped and the spec did not know; here, the spec ruled and the code did
   not follow. Both were invisible for the same reason — nothing checked the two against each other.
   The regression tests added here are that check for the rulings that had already drifted: no
   script reads the retired axis share, no script prints "% of ceiling", and the shipped LCZ 10
   threshold is the one the sweep selects.
2. **A quantity's denominator belongs in its name.** A column whose meaning is contested cannot be
   fixed by documenting it harder. Both industrial shares are emitted, each named for what it
   divides by, with the bare `industrial_fraction` kept one release as a deprecated alias so no
   stored figure changes meaning underneath a reader.
3. **Change the definition and re-measure before calling a degenerate distribution a scale finding.**
   The `FIND/B` saturation result was interesting, general, and consistent with the phase before it,
   which is exactly why it reached four documents before anyone questioned the numerator. Nothing
   about the distribution could have distinguished it from the bug that produced it. The check that
   works is not reading the numbers more carefully — it is perturbing the definition and seeing
   whether the finding survives.
4. **Fixtures do not measure scaling.** The same change made Berlin stop completing, and the 9 km²
   fixtures ran green throughout. The standing anti-pattern already says to measure a whole-extent
   operation's exponent at three or more extents; this phase broke it while auditing for broken
   rules, which is about as clear a demonstration of its necessity as the repository has.
