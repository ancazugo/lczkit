# Phase 18 — Overture semantic evidence

Built on explicit request: use the tag information Overture carries as an add-on to differentiate
LCZ classes. The package computed twenty parameters and exactly **one** of them read a semantic
attribute — `industrial_fraction`, a literal `isin(["industrial"])` on `subtype` or `class`.
Everything else was geometry or raster. Overture ingests `subtype`, `class` and `sources` on every
building and `subtype`/`class` on every land-use parcel, and cleaning is *test-pinned* to retain
them, so the vocabulary had been there and unread since Phase 1.

**Overture-native, not OSM.** `osm-rasterizer` and `osmnx` are neither installed nor declared, and
both would pull live Overpass queries — unpinned, unreproducible, and against the design decision
that fixes an Overture release string in every manifest. The knowledge in
`osm_lcz_tag_mapping.md` is ported into a committed Overture crosswalk instead, and every value in
it was taken from what is present in release `2026-07-22.0` rather than from schema documentation.

## 1. The measurement, and it is the founding premise again

| city | tagged building **area** | tagged **count** | dominant footprint source | its tagged share |
|---|---:|---:|---|---:|
| Berlin | 64.4% | 46.6% | OpenStreetMap (80%) | 51.3% |
| Milan | 62.2% | 45.4% | OpenStreetMap (85%) | 53.5% |
| Hong Kong | 58.1% | 44.5% | OpenStreetMap (60%) | 73.6% |
| Vancouver | 55.3% | 41.4% | OpenStreetMap (90%) | 46.1% |
| London | 50.3% | 51.0% | OpenStreetMap (80%) | 63.8% |
| Cologne | 46.8% | 48.1% | OpenStreetMap (95%) | 50.4% |
| Paris | 37.1% | 15.5% | OpenStreetMap (97%) | 16.0% |
| Rome | 24.2% | 13.6% | OpenStreetMap (86%) | 15.8% |
| Mumbai | 18.1% | 5.4% | Google Open Buildings (56%) | **0.0%** |
| Cape Town | 13.3% | 4.8% | Microsoft ML Buildings (64%) | **0.0%** |
| Jakarta | 7.5% | 1.4% | OpenStreetMap (75%) | 1.8% |
| São Paulo | 7.1% | 1.2% | OpenStreetMap (56%) | 2.1% |
| Cairo | 5.7% | 1.0% | Microsoft ML Buildings (59%) | **0.0%** |
| Nairobi | 5.2% | 1.0% | OpenStreetMap (56%) | 1.7% |
| Islamabad | 4.5% | 1.1% | Google Open Buildings (70%) | **0.0%** |
| Rio de Janeiro | 3.1% | 0.4% | Google Open Buildings (49%) | **0.0%** |

**Europe + N. America 48.6% mean / 50.3% median of building area tagged, against 13.6% / 7.1%
elsewhere.** Phase 9 measured tier-1 height at 64.3% against 9.6% on the same split. This is the
same finding on a second, independent attribute — and a **fourth** sighting of the
seven-against-nine regional line after Phase 11's A/B split, Phase 12's compactness lift and Phase
16's label reproducibility.

**The mechanism is in the last column, and it is not "nobody bothered".** Wherever an ML source
wins the footprints, its tagged share is *exactly 0.0%*: Google Open Buildings and Microsoft ML
supply geometry and no attributes at all. Overture's conflation is winner-takes-all per footprint,
so a city whose footprints those sources won has no attributes to read regardless of how well
mapped it is in OSM. That is why the diagnostic groups by upstream dataset — it is what turned an
observation into an explanation.

**Land-use parcels do not collapse**: 30–65% coverage in the same cities where building tags are
near-absent (Rio 64.5%, Jakarta 55.8%, Cairo 37.6%, Nairobi 35.6%, Mumbai 30.5%), against 79–107%
in Europe. They are the evidence that generalises, and the reason the two are reported as separate
columns rather than fused into one blended fraction.

**Area coverage runs well above count coverage everywhere** — tagged buildings are systematically
the larger ones, Berlin 64.4% against 46.6% and Mumbai 18.1% against 5.4%. The area share is the
reported one because it is the denominator every semantic fraction actually divides by. Reporting
the count would have made every city look worse than it is, by a factor that varies by city.

## 2. What was built

`src/lczkit/ucp/semantics.py` generalises the industrial machinery, **importing** `_select` rather
than restating it so there is one definition of "which features match". Per configured group, two
columns whose names each carry a numerator *and* a denominator:

- `sem_<group>_buildings_of_building_area` — Bernard's `FIND/B`, generalised. Null where the unit
  holds no building area, never 0.0.
- `sem_<group>_parcels_of_unit_area` — dissolved parcel share of unit area.

Plus the two that make the rest readable: **`building_tag_coverage`** and **`land_use_coverage`**.
Without them a `lightweight` fraction of 0.0 in Nairobi cannot be told from 94.8% of building area
carrying no tag — the same distinction `height_tier_fractions` draws for the cascade, and the
reason it exists.

Five groups, transcribed from `docs/references/tables/overture_lcz_semantic_mapping.md` and
asserted against it cell for cell: `lightweight` (LCZ 7), `large_lowrise` (LCZ 8), `heavy_industry`
(LCZ 10), `residential` and `commercial`. `warehouse` sits in `large_lowrise` and not in
`heavy_industry`, restating the ruling `UcpConfig.industrial_building_classes` already carries so
the two vocabularies cannot drift.

**Scope held to the built types.** `park`, `forest`, `grass` and `farmland` are all in the
vocabulary and all deliberately unmapped: CLAUDE.md's locked decision is that rasters own land
cover. A test asserts no group reaches for them, so a future edit fails there rather than in a
validation table.

**`industrial_fraction_of_building_area` keeps its own narrower vocabulary and is not repointed.**
It is the column the shipped LCZ 10 threshold of 0.45 was swept against, and widening what it
selects would silently invalidate that calibration. `heavy_industry` is reported beside it, and a
test asserts the two never diverge on the Rotterdam fixture — the group is a superset by
construction, so it can only ever be larger, and it correlates above 0.99.

### The rules

`classify.rules.apply_semantic_rules` generalises `apply_lcz10_rule`: a unit over the threshold
takes the class whatever the morphology said, the displaced answer is kept as `lcz_secondary`, and
`min_distance` goes null because the label was not reached by distance. New `label_route` value
`semantic_rule`, kept distinct from `industrial_rule` so that rule's firing count — a figure phase
write-ups cite — does not change meaning.

Two candidates ship, **both disabled**:

- **LCZ 8 from `large_lowrise`**, gated on `mean_building_area_m2`. Phase 14 diagnosed LCZ 8 as
  failing *by construction*: its BSF band overlaps LCZ 3 and 6, its `Hr` band is identical to 3, 6
  and 9, so `aspect_ratio` is its only separator in the metric — and that is null exactly where
  setbacks stop streets reaching buildings, which is most of an LCZ 8 unit. Measured 0.0% over 224
  Rotterdam cells. A rule may read `mean_building_area_m2` although the metric cannot, which is the
  parameter Phase 14 found the LCZ 8 justification had wrongly credited.
- **LCZ 7 from `lightweight`.** Stated plainly: **this will mostly not fire where it matters.**
  Overture has no `slum`, `shanty`, `ger` or `tent` value, and tagged building area runs 13.6%
  outside Europe. That is a result to report, and `building_tag_coverage` is what makes the
  non-firing legible instead of invisible.

**Disabled is a ruling, not caution.** CLAUDE.md requires a threshold to be swept against a
reference and chosen at an operating point, never picked — the LCZ 10 threshold went through
nineteen settings against Rotterdam, and Phase 14 found the threshold was not even the binding
constraint there. The shipped values are placeholders marking where a swept number goes. Enabling
one before its sweep would put an invented number into a published label.

## 3. Two defects found by measuring rather than reasoning

**A whole-extent `union_all` over the land-use layer**, in the first draft of both the coverage
column and the diagnostic. It is the standing anti-pattern this project has already paid for twice
— Phase 12 measured 711 s at Berlin's 891 km² for a union whose result is a scalar — and it also
*does not work*: over real Overture land use it raises `GEOSException: side location conflict`
**even after `make_valid`**, because per-feature validity does not make a collection unionable.
`industrial.py` gets away with it because it unions the industrial subset, a few dozen parcels;
this ran on all 70 509 of Berlin's. Replaced by clipping to units first and dissolving per unit,
which is bounded, well-conditioned and exactly equal. Caught by running the diagnostic over a real
city rather than a fixture, and now guarded by a test that greps both modules.

**Selection by index, over a layer with no uniqueness guarantee.** `buildings.loc[selected.index]`
silently returns extra rows if the building index has duplicates, which inflated
`building_tag_coverage` to 1.0 for an untagged unit. Every selection is positional now. Caught by
the one test written specifically to prove tagged and untagged are distinguishable — the property
the module exists for was the property that failed.

## 4. What this phase did not do

**No threshold sweep, so no rule is enabled and no accuracy claim is made.** The sweep is the next
measurement, it follows `scripts/lcz10_threshold_sweep.py`'s shape, and it needs a reference the
rule's class is well represented in — Rotterdam for LCZ 8, and for LCZ 7 a city where the class
exists *and* is tagged, which the coverage table suggests may not exist. That last point is itself
a finding worth reporting: the class the founding premise is most about may not be reachable from
Overture attributes at all, in which case the rule's value is in making that measurable rather than
in firing.

**`industrial_fraction` was not refactored away.** It could be expressed as one semantic group, and
deliberately is not: it carries a calibrated threshold, six column names other code reads, and a
`industrial_evidence` categorical. The generalisation shares its selection helper, which is where
drift would actually occur, and leaves the calibrated path alone.
