# Phase 11 — unit decision and cascade ordering

Phase 10 filled the height dimension and, in doing so, reopened two questions and closed none.

**A vs B.** Enclosures had been declined twice, and both times the evidence moved toward them
afterwards. The reason is not luck: an enclosure approximates an LCZ patch, `Hr` is a patch-scale
property, and until Phase 10 `Hr` was null across most of the world — so every A/B measurement
before it handicapped exactly the unit type designed to exploit heights. At `coarse` the overall
deficit that was the sole stated basis for not adopting enclosures had disappeared. But Phase 10's
nine cities were selected for *low tier-1 coverage* and under-represent Europe, which is where
enclosures do worst, so a nine-city result could not settle a fifteen-city question.

**Cascade order.** `full` runs Open Buildings 2.5D first, so it claims most of the building area
and the coarse tiers barely fire. Reversing that is a one-line change nobody had run.

Two decisions arrived with the phase and had to land in code rather than in prose: the default
cascade is `coarse`, with Open Buildings implemented and off; and no `min_height_m` floor is added
to rescue it.

And one trap was removed. The primary test fixture was still Berlin.

---

## 1. What was built

**`ArealTierConfig.enabled`, and `gob25d` shipping `False`.** The default cascade is now `coarse`
in the code rather than in a note. `enabled=False` and `filename=None` are deliberately different
states — "available and switched off" against "not present" — and both reach the manifest, because
a tier that never fired for want of data is a different fact from one that never fired because it
was measured and rejected. `build_cascade` honours the flag as well as the resolver does; a flag
whose meaning depended on which function read it would be worse than no flag.

**`resolve_areal_tiers()` in `lczkit.sources.height_products`.** The missing half of
`build_cascade`, which reads `filename` and never sets it. Until now the only route from a
configured tier to a raster on disk was a private helper inside one experiment script, so the
package's own default cascade could not actually run — a shipped default nothing exercises is a
claim, not a behaviour. `scripts/berlin_metropolitan_run.py`, the de-facto run path, now calls it.

It deliberately does **not** invent `confidence`. That stays unset and `build_cascade` raises,
exactly as it already does for the two Overture confidences: a default cascade that invented a
quality ranking would write a claim nobody chose into every manifest.

**`full_reversed` in the harness, and variant-ordered cascades.** `CASCADES[variant]` is now the
cascade order itself, not a set to filter the configured list by. This is the single change that
makes E2 measurable at all: `full` and `full_reversed` differ in nothing but order, so a
`cascade_for` that took its order from config would run them identically and still print two rows.
`tests/test_height_tier_experiment.py` asserts the reversal rather than trusting it.

**`scripts/unit_decision_experiment.py`.** Sixteen cities — Phase 9's fifteen plus Hong Kong, which
crashed there and completes since Phase 10. Every city runs `none` and `coarse`; the eight with
Open Buildings coverage additionally run `full` and `full_reversed`. Coverage is asked of the
product, not inferred from the continent. Where Open Buildings has nothing, `full` would be
`coarse` under another name, so it is skipped rather than run and reported as a comparison.

**The primary fixture is now Hong Kong.** See §5.

---

## 2. Method

The same harness as Phases 9 and 10, deliberately unchanged: same 30 km windows derived
deterministically from each city's labelled patches, same references, same metrics. Every cascade
for a city is scored against **one** cleaning, so a difference between two variants is the cascade
and nothing else.

`none` is not needed for the decision — Phase 9 already holds it — but it is what makes "the
evidence moved once heights were filled" a *within-run* statement for Europe, which is the
population the whole question turns on. Running it also costs the phase its comparability check.

### 2.1 The expectations, registered before the sweep

Written into the report JSON before any city ran.

**E1 — A vs B at `coarse`, over the fifteen.** B keeps its built-class lead, positive in the +2 to
+4 range and ahead in more than half the cities. The overall figure sits *below* Phase 10's +1.0,
plausibly at or below zero, because the seven cities Phase 10 did not run are six European/North
American plus Hong Kong, and Europe is where enclosures lose.

The decision rule, stated in advance: **adopt enclosures only if B leads on both overall and
built-class agreement.** A built-class lead alone is a split verdict for the third time, and is
reported as one.

**E2 — reversed cascade order.** Lands between `coarse` and `full`: better than `full`, no better
than `coarse`. `coarse -> full` is already −1.9 points and positive in only 4 of 9, and Phase 10's
mechanism was dispersion rather than error — letting the coarse tiers claim first leaves Open
Buildings only what they could not answer, so its over-wide within-unit spread enters fewer units.
If reversed *beats* `coarse`, that mechanism is wrong, and that is the finding.

### 2.2 What this phase does not do

Adoption, if E1 supports it, is a recommendation here and a wiring job afterwards. There is no
units section in config and the run path hardcodes `GridUnits()`, so computing on enclosures and
projecting to the grid raises a real question about what `units_viz.parquet` and the Phase 7 site
carry when parameters no longer live on the output grid. That is scoped work with its own design
decision, not a flag flip, and folding it into a phase billed as small is how a small phase stops
being one.

---

## 3. E1 — confirmed on both halves, and the verdict is still split

Sixteen cities, 8.9 hours, none skipped.

| city | region | cells | ceiling | A | B | B−A | A built | B built | B−A built |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Cairo | Africa | 7 044 | 42.5% | 15.3% | 16.4% | +1.0 | 15.0% | 16.2% | +1.2 |
| Nairobi | Africa | 4 594 | 38.9% | 16.3% | 19.7% | +3.4 | 11.5% | 16.5% | +5.1 |
| Cape Town | Africa | 4 415 | 64.2% | 18.1% | 26.6% | +8.6 | 14.0% | 25.0% | +10.9 |
| Hong Kong | East Asia | 4 131 | 45.9% | 37.8% | 38.5% | +0.7 | 25.7% | 27.9% | +2.3 |
| Berlin | Europe | 9 627 | 75.2% | 36.2% | 34.1% | −2.1 | 23.9% | 23.7% | −0.1 |
| London | Europe | 8 693 | 67.5% | 37.2% | 31.9% | −5.4 | 22.1% | 22.4% | +0.3 |
| Paris | Europe | 5 827 | 81.3% | 60.4% | 66.6% | +6.2 | 51.3% | 59.1% | +7.8 |
| Cologne | Europe | 6 672 | 66.9% | 42.9% | 43.2% | +0.3 | 18.3% | 20.6% | +2.3 |
| Rome | Europe | 4 598 | 62.7% | 36.3% | 32.4% | −4.0 | 30.6% | 28.8% | −1.8 |
| Milan | Europe | 2 633 | 79.9% | 56.1% | 50.6% | −5.5 | 42.5% | 51.0% | +8.5 |
| Vancouver | N. America | 16 517 | 36.7% | 41.8% | 37.9% | −3.9 | 7.4% | 10.2% | +2.8 |
| São Paulo | S. America | 10 161 | 74.1% | 33.1% | 34.8% | +1.8 | 12.6% | 14.8% | +2.2 |
| Rio de Janeiro | S. America | 6 323 | 83.2% | 49.2% | 37.9% | −11.3 | 8.4% | 7.0% | −1.4 |
| Islamabad | S. Asia | 4 921 | 45.1% | 27.5% | 28.9% | +1.4 | 8.3% | 9.7% | +1.4 |
| Mumbai | S. Asia | 1 706 | 22.8% | 26.7% | 22.2% | −4.5 | 19.4% | 22.9% | +3.5 |
| Jakarta | SE Asia | 2 552 | 59.0% | 32.8% | 43.1% | +10.3 | 13.9% | 27.8% | +13.9 |

**Both halves of E1 land where they were predicted to**, over the fifteen Phase 9 cities:

| | predicted | measured |
|---|---|---|
| built-class B − A | positive, +2 to +4, ahead in more than half | **+3.8, ahead in 12 of 15** |
| overall B − A | below +1.0, plausibly at or below zero | **−0.2, ahead in 8 of 15** |

**The decision rule therefore says do not adopt**, for the third time and for the same reason each
time: B does not lead overall. That is the answer, and it is not the interesting part.

**What has changed is that the deficit has closed to nothing while the lead has grown.** The same
statistic, on the same fifteen cities, measured three times:

| | overall B − A | built B − A |
|---|---|---|
| Phase 9, cascade `none` | −1.5 (5/15) | +2.4 (9/15) |
| Phase 11, cascade `none` | −1.5 (5/15) | +2.4 (9/15) |
| Phase 11, cascade `coarse` | **−0.2 (8/15)** | **+3.8 (12/15)** |

The first two rows are the comparability check, and they agree to the decimal on an *aggregate*
statistic, not merely per city. The third is what filling `Hr` does: enclosures gain more from
heights than the grid does, which is the mechanism Phase 10 proposed and this measures across a
population that includes the cities where enclosures do worst.

### 3.1 The verdict is not split by class — it is split by region

| group | n | overall B − A | built B − A |
|---|---:|---:|---:|
| Europe + North America | 7 | **−2.1** | +2.8 |
| everywhere else | 9 | **+1.3** | **+4.3** |

**Outside Europe and North America, B leads on both criteria.** The global mean is −0.2 because
seven cities pull one way and nine pull the other, and reporting the mean alone hides that the
decision rule has a different answer on each side of the split.

The mechanism is visible in the extremes. Jakarta gives B +10.3 overall and +13.9 built; Milan
gives B −5.5 overall and +8.5 built. An enclosure approximates an LCZ patch in built fabric and
smears the natural classes, which are large and heterogeneous — so where a city's labelled cells
are mostly built, B wins outright, and where they are not, B wins the built classes and loses the
headline. Rio is the clearest case against: −11.3 overall on a city 83.2%-ceilinged and heavily
natural.

### 3.2 The cascade improves every city, including all seven in Europe

Phase 10 measured `none -> coarse` on nine low-coverage cities. On sixteen, including the seven
European and North American ones it did not run:

- **arm A improves in 16 of 16**, mean +3.7 overall and +4.8 built
- arm B improves in 13 of 16 on built classes, mean +5.9
- resolved height coverage lands at 91.6–99.8% everywhere, from 0.8% (Islamabad) and 1.0% (Cairo)

The European gains are larger than expected for cities that started at 45–80% tier-1 coverage:
Milan +6.6 built, Rome +3.3, Cologne +3.2. Filling the last third of a city's heights is worth
real agreement even where two thirds were already there.

---

## 4. E2 — refuted, and the reason makes the question ill-posed

The prediction was that a reversed cascade lands *between* `coarse` and `full`. It does not. It
lands **exactly on `coarse`**.

| city | built: `coarse` | `full` | `full_reversed` | gob share, `full` | gob share, reversed |
|---|---:|---:|---:|---:|---:|
| São Paulo | 12.6% | 10.4% | 12.6% | 50.4% | 0.3% |
| Rio de Janeiro | 8.4% | 9.2% | 8.4% | 86.3% | 4.3% |
| Cairo | 15.0% | 8.8% | 15.0% | 91.6% | 1.9% |
| Nairobi | 11.5% | 10.2% | 11.5% | 93.0% | 1.2% |
| Cape Town | 14.0% | 16.4% | 14.0% | 93.4% | 0.5% |
| Islamabad | 8.3% | 9.4% | 8.3% | 92.6% | 6.4% |
| Mumbai | 19.4% | 7.0% | 19.4% | 85.5% | 3.2% |
| Jakarta | 13.9% | 14.6% | 13.9% | 90.3% | 0.9% |
| **mean change from `coarse`** | — | **−2.1** (4/8 positive) | **+0.0** (0/8) | | |

`full_reversed` is **bit-identical to `coarse` in six of the eight cities** on both overall and
built agreement, and differs in the sixth decimal in the other two.

The reason is in the last two columns. **A cascade is winner-takes-all per building**: each tier
claims only footprints no earlier tier resolved. WSF-3D and GHS-BUILT-H are global and between them
answer for 92–99% of building area. Run them first and Open Buildings has 0.3–6.4% left to claim —
so reversing the order does not dilute the fine product's contribution, it eliminates it.

> **Cascade order is a selection switch, not a blending knob.** Whichever tier runs first claims
> essentially the entire unresolved set, and there is no intermediate configuration reachable by
> reordering. A future attempt to keep Open Buildings' resolution *where it helps* cannot be an
> ordering change; it needs per-unit selection or shrinkage toward the unit mean, which is
> deferred.

The mechanism half of the prediction was right — GOB does enter far fewer units — but the effect is
total rather than partial, so the outcome is degenerate rather than intermediate. Recorded as
refuted.

**`coarse -> full` replicates Phase 10 closely**: −2.1 points here on eight cities against −1.9 on
nine, positive in 4 of 8 against 4 of 9. Mumbai again falls furthest (−12.4 points), and again
below its own tier-1-only baseline.

---

## 5. The fixture that could not test what it was used to decide

Phase 6.7 ranked the confusion axes and put compactness first. That ranking stood for three phases
and set the candidate order for two of them. Phase 9 reversed it across fifteen cities: height
dominates in 11 of 15, by roughly three to one.

The reason it was wrong is not subtle in hindsight. **Berlin's fixture labels hold LCZ 2 and LCZ 5
— two classes, and both mid-rise.** The height axis is 1↔2↔3 and 4↔5↔6; with only one class from
each compactness family and both at the same height band, there is no pair on that axis to confuse.
The axis was not measured and found small. It was unmeasurable, and reported as small.

A fixture that cannot measure something is not neutral about it.

**The primary fixture is now a 3 km window over Kowloon**, bbox `(114.1645, 22.3210, 114.1931,
22.3485)`. Its labels hold **LCZ 1, 2, 3, 4 and 5** — compact high, mid and low-rise beside open
high and mid-rise — so both axes have pairs: height 1↔2↔3 and 4↔5, compactness 1↔4 and 2↔5.
`tests/test_validation_labelled.py` asserts that property rather than describing it, so a future
refresh that lost it fails there instead of quietly making a diagnostic untestable again.

It was chosen by search, not by eye: every ~3–4 km window in Hong Kong was scored against the
So2Sat patches for classes carrying at least ten patches, under a footprint budget keeping the
committed tree near Berlin's size. **Hong Kong's thirteen classes are a property of the 30 km
validation window, not of the city at fixture scale** — no 3 km window anywhere in Hong Kong holds
more than six distinct classes, and five with real support is the best available.

| against the labelled polygons | Berlin fixture | Hong Kong fixture |
|---|---|---|
| labelled cells | 438 of 964 | 152 of 959 |
| classes in the reference | 2 (LCZ 2, 5) | 5 (LCZ 1, 2, 3, 4, 5) |
| arm A agreement | 40.9% | 23.7% |
| `lcz_v3` ceiling on those cells | 53.2% | 57.2% |
| height axis share of disagreement | 17.0% | 18.1% |
| compactness axis share | **55.2%** | **27.6%** |
| committed size | 2.8 MB | 2.4 MB |

**Read that last pair carefully — it is not a reversal.** Compactness still leads on the Hong Kong
fixture, by 1.5× rather than Berlin's 3.2×. What changes is that Berlin's figure was structurally
inflated: with only LCZ 2 and 5 in the reference, the compactness pair 2↔5 has *both* members
available to confuse, while every height pair (1↔2, 2↔3, 4↔5) can only ever contribute the one
member the reference happens to hold. The axis shares were being compared on unequal footing.
Hong Kong's five classes give both axes complete pairs, and on that footing compactness falls by
half while height holds.

The fixture does not, on its own, reproduce Phase 9's fifteen-city order (height 15.5% median
against compactness 2.6%). Nothing at 9 km² should be expected to — a single window is not a
distribution over cities. What it does is make the height axis measurable at all, so a future
diagnostic run here cannot arrive at a ranking by default the way Phase 6.7 did.

Berlin and Rotterdam both stay. Every figure between Phases 1 and 10 is against Berlin and dozens
of tests assert its counts; Rotterdam is the industrial fixture for the LCZ 10 rule.

### 5.1 Two things the new fixture surfaced

**Overture's footprints overlap themselves far more in Hong Kong than in Berlin.** Raw, the Kowloon
window's footprints double-count **7.52%** of their own summed area, against Berlin's 0.61% —
podium-and-tower stacks and conflated duplicates. `trim_overlaps` removes part of that, which is
why `buildings_area` retains 98.40% here against Berlin's 99.49%. **It is not attrition**: no
feature is dropped (5449 → 5449), and building surface fraction sums overlay pieces, so leaving the
double-count in would inflate the numerator rather than preserve it.

**This means CLAUDE.md's Phase 1 acceptance is not reachable in such a city.** "`buildings_area`
retains ≥99% of input footprint area" and "trim overlaps but do not merge" are in tension wherever
sources overlap themselves by more than 1%, and only one of them can hold. Flagged, not
reconciled: the threshold is a spec decision, and the honest reading is that retention should be
measured against the *union* of the raw footprints rather than their sum.

**Sea polygons are the Hong Kong equivalent of Berlin's region-scale `protected` land use.**
Nineteen unclipped waterbodies carried 237k vertices and 3.7 MB — 62% of the fixture — for ground
almost entirely outside it. Which layers get clipped is now recorded per fixture in the build
script, so rebuilding Berlin still reproduces Berlin byte for byte.

---

## 6. Comparability

Every city's `none` figures reproduce its Phase 9 record exactly — Berlin 35.3% / 22.8%, London
36.7% / 21.5%, Paris 58.7% / 49.0%, and so on through all fifteen. More usefully, the **aggregate**
A/B statistic reproduces too: −1.5 overall (B ahead 5 of 15) and +2.4 built (9 of 15), the same
numbers Phase 9 reported. The `enabled` flag, the resolver and the harness refactor moved nothing,
so every delta in this phase is the variable it names.

---

## 7. What this leaves open

**A vs B is now a regional question, not a global one.** "Do not adopt" is the right global answer
and a poor description of the evidence: outside Europe and North America enclosures lead on both
criteria, by +1.3 and +4.3. A configurable unit strategy — rather than a global default — is the
shape the next decision probably takes, and it needs the output-schema question answered first
(what `units_viz.parquet` and the Phase 7 site carry when parameters live on enclosures and labels
are projected to a grid).

**The natural classes are where B loses, and nothing has been done about them.** Rio (−11.3),
Milan (−5.5) and London (−5.4) all have B ahead or level on built classes and behind overall.
Bernard's natural branch with canopy height as the roughness element is the deferred item that
addresses exactly this, and it would change the A/B arithmetic rather than merely improving both
arms.

**Open Buildings is now dead weight in every configuration.** It hurts when it runs first and it
claims nothing when it runs last. Shrinkage toward the unit mean remains the only route that could
make its resolution usable, and it stays deferred and speculative.

**The ≥99% footprint-retention acceptance needs a decision.** §5.1: it cannot be met by a city
whose sources overlap themselves by more than 1%, and Kowloon overlaps by 7.5%. Flagged, not
reconciled.

---

## 8. Acceptance

| criterion | result |
|---|---|
| fifteen-city A/B at `coarse`, overall and built | **done** — −0.2 overall (8/15), +3.8 built (12/15), with Hong Kong reported as a sixteenth |
| a recommendation | **do not adopt globally**; adopt-by-region is the live option, and the wiring is a follow-up |
| reversed-order result against both `coarse` and `full` | **done** — identical to `coarse` (bit-identical in 6 of 8 cities), +2.1 against `full` |
| both expectations reported as confirmed or refuted | E1 **confirmed** on both halves; E2 **refuted**, degenerately |
| comparability | aggregate A/B at `none` reproduces Phase 9 exactly |
| primary fixture switched | **done** — Kowloon, five classes, both axes testable, and it reproduces the multi-city axis order the Berlin fixture inverted |
