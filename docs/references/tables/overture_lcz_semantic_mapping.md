# Overture attribute values to LCZ semantic groups

The Overture-native counterpart of `osm_lcz_tag_mapping.md`, which is written against OSM tags.
This file is the authority `lczkit.ucp.semantics` transcribes and `tests/test_ucp_semantics.py`
parses cell for cell, in the same way `stewart_oke_2012_properties.md` and
`lcz_class_similarity.md` are.

**Why a separate table rather than the OSM one.** Overture normalises OSM's open-ended tags into a
closed vocabulary, so the OSM mapping does not transfer value for value: `building=slum`,
`building=shanty`, `building=ger` and `building=tent` all exist in OSM and none survives into
Overture, while Overture's `subtype=outbuilding` has no single OSM equivalent. Every value below
was taken from what is **actually present** in the pinned release rather than from the schema
documentation — counted over the cached extracts for Berlin, Cairo, Jakarta, Mumbai, Nairobi and
Rio, release `2026-07-22.0`, ~5.8 M buildings.

---

## The coverage problem, which is the point

| city | tagged building **area** | tagged **count** | `land_use` parcel cover | dominant source |
|---|---:|---:|---:|---|
| Berlin | **64.4%** | 46.6% | 78.7% | OpenStreetMap |
| Milan | 62.2% | 45.4% | 106.6% | OpenStreetMap |
| Hong Kong | 58.1% | 44.5% | 41.3% | OpenStreetMap |
| Mumbai | 18.1% | 5.4% | 30.5% | Google Open Buildings |
| Jakarta | 7.5% | 1.4% | 55.8% | OpenStreetMap |
| Cairo | 5.7% | 1.0% | 37.6% | Microsoft ML Buildings |
| Nairobi | 5.2% | 1.0% | 35.6% | OpenStreetMap |
| Rio de Janeiro | **3.1%** | 0.4% | 64.5% | Google Open Buildings |

Europe + N. America hold **48.6% mean / 50.3% median** of building area tagged against **13.6% /
7.1%** elsewhere. Building attributes collapse outside Europe exactly as tier-1 height does, and for
a mechanism the diagnostic makes visible: wherever an ML source wins the footprints its tagged share
is *exactly 0.0%*, because Google Open Buildings and Microsoft ML supply geometry and no attributes.

**Land-use parcels do not collapse**, holding 30–65% even where building tags are near-absent, which
is why they are the evidence that generalises and why the two are reported separately rather than
fused. Area coverage also runs well above count coverage everywhere — tagged buildings are
systematically the larger ones — so the area share is the reported one, since it is the denominator
every semantic fraction divides by.

Milan exceeding 100% is not an error: `lczkit.cleaning.land_use` applies `make_valid` and no overlap
resolution, so parcels self-overlap. Anything dividing by unit area must dissolve first.

---

## Groups

`buildings` matches on `subtype` **or** `class` — the two are independently nullable and a feature
carrying only one is still classifiable. `land_use` matches on `class` unless a subtype is listed.

| group | LCZ | building `subtype` | building `class` | land use `subtype` | land use `class` |
|---|---|---|---|---|---|
| `lightweight` | 7 | outbuilding | hut, shed, cabin, roof, kiosk, carport, guardhouse | — | — |
| `large_lowrise` | 8 | — | warehouse, retail, supermarket, hangar, stadium, train_station, transportation, parking, sports_centre, sports_hall, service | — | retail |
| `heavy_industry` | 10 | industrial | industrial, storage_tank, silo | — | industrial, works |
| `residential` | 1–6 context | residential | apartments, house, detached, semidetached_house, terrace, bungalow, residential, dormitory, allotment_house | residential | residential |
| `commercial` | 1–3, 8 context | commercial | commercial, office, retail, hotel, supermarket | developed | commercial, retail |

Design notes, each of which is a decision that could have gone the other way:

- **`lightweight` is thin on purpose, and it will under-report.** Overture has no `slum`, `shanty`,
  `ger` or `tent`; `hut` is 1 939 rows across 5.8 M buildings. LCZ 7 is the class the founding
  premise is most about and the class Overture is least able to see, and this table cannot fix
  that — it can only make the shortfall measurable, which is what `building_tag_coverage` is for.
  A `lightweight` fraction of 0.0 in Nairobi means "no tagged lightweight buildings" over a city
  where **94.8% of building area carries no tag at all**.
- **`roof` and `carport` are in `lightweight`.** An open-sided roofed structure is lightweight
  construction by Stewart & Oke's description of LCZ 7, and `roof` is 6 872 rows — more than `hut`.
- **`warehouse` is in `large_lowrise` and not in `heavy_industry`.** The same decision
  `UcpConfig.industrial_building_classes` makes, restated here so the two vocabularies cannot
  drift: Stewart & Oke give a warehouse as an LCZ 8 example.
- **`retail` and `supermarket` appear in two groups.** Groups are not a partition and are not
  claimed to be — a big-box store is genuinely evidence for both LCZ 8 and commercial function.
  Anything treating the fractions as summing to one is misreading them.
- **`brownfield`, `construction`, `quarry` and `landfill` are in no group.** They are surface
  states, not building function, and the raster owns land cover.
- **Nothing here maps to LCZ A–G.** Land use is functional-only and rasters own land cover.
  `park`, `forest`, `grass` and `farmland` are all present in the
  vocabulary and are all deliberately unused.

---

## Values present and deliberately unmapped

Counted in the same six cities, so that "absent from the table" is distinguishable from
"overlooked". Building `class`: garage (28 632), garages (4 635), school (8 397), mosque (4 267),
church (1 344), hospital (1 651), university (1 288), kindergarten (2 503), greenhouse (569),
farm_auxiliary (217), stable (159), barn (118), toilets (184), civic (662), government (419),
public (313), fire_station (235), library (102), post_office (107), temple (246), chapel (194),
college (500), boathouse (61), grandstand (106), religious (75), outbuilding (75).

These describe *institutional* function, which no LCZ class is defined by: a school may be LCZ 5 or
LCZ 8 depending on its form, and Stewart & Oke separate them on morphology. Mapping them would add
evidence that does not discriminate.

---

## References

- Stewart, I.D. and Oke, T.R. (2012), *BAMS* 93(12), 1879–1900. `10.1175/BAMS-D-11-00019.1`
- Bernard, J. et al. (2024), *GMD* 17, 2077–2107. `10.5194/gmd-17-2077-2024` — `FIND/B`, the
  industrial-share-of-building-area quantity `heavy_industry` reproduces.
- Fonte, C. et al. (2019), *Urban Climate* 28, 100456. `10.1016/j.uclim.2019.100456` — the OSM→LCZ
  correspondences this table is the Overture translation of.
- Overture Maps schema reference, buildings and base themes, release `2026-07-22.0`.
