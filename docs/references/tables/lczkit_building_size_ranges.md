# Mean building area ranges for LCZ 7 and LCZ 8 — lczkit's own, NOT Stewart & Oke

**These are not Tier 1 numbers and must never be cited as such.** Stewart & Oke (2012) publish no
per-class range for building size; their ten surface properties do not include one, and
`stewart_oke_2012_properties.md` in this directory has no such column. This table exists because
two classes whose *published names* are claims about building size are separated by nothing in the
metric that measures building size — and the result is that they come out swapped.

## The measurement this exists to answer

`mean_building_area_m2` has been computed since Phase 5 and has never been a metric dimension.
Phase 14 recorded the omission from the metric's structure. Phase 25 measured what it costs, over
built cells (BSF > 0.05) of four runs on disk:

| city | LCZ 7 median footprint | LCZ 8 median footprint | ratio 8/7 |
|---|---:|---:|---:|
| Berlin | 13 419 m² | 767 m² | 0.06 |
| Istanbul | 13 172 m² | 462 m² | 0.04 |
| Bogotá | 6 756 m² | 55 m² | **0.01** |
| Nairobi | 3 749 m² | 93 m² | 0.02 |

**LCZ 8 is _large low-rise_ — warehouses, malls, hangars. LCZ 7 is _lightweight low-rise_ — the
informal-settlement class, small single-storey structures.** The map is assigning "large low-rise"
to cells of 55–93 m² buildings and "lightweight low-rise" to cells of 7 000–13 000 m² sheds, in
every city measured. **This needs no external reference to call wrong; it is internally
contradictory.** It also predicts, without reference to any run, Phase 6.7's LCZ 8 at 0.0% (n=224)
and Phase 13's LCZ 7 at 8.2% in range — the latter attributed at the time to Overture coverage of
informal settlements, which is at most half of it.

## Why the metric cannot separate them

Read from `stewart_oke_2012_properties.md`. On the three dimensions that carry weight under
`bernard2024_partial`:

| | H/W | BSF | Hr |
|---|---|---|---|
| LCZ 7 Lightweight low-rise | 1–2 | 0.60–0.90 | 2–4 m |
| LCZ 8 Large low-rise | 0.1–0.3 | 0.30–0.50 | 3–10 m |

A big flat warehouse has a high building surface fraction and a low height, which is LCZ 7's box on
two of three dimensions. A dense informal settlement has moderate BSF and — because Overture's
street network does not contain its alleys — a low measured H/W, which is LCZ 8's box. Neither
box mentions how big a building is, so nothing pulls either back.

The remaining dimension, H/W, is the one that would separate them, and it is the least reliable of
the three: null on 10.8% of Istanbul's built grid cells, and measured at 0.31 on Nairobi's densest
decile where the fabric it describes has alleys a metre or two wide.

## The ranges

`mean_building_area_m2` is the Phase 5 column of the same name: the mean footprint area of whole
buildings whose representative point falls in the unit. Blank means unbounded on that side.

| LCZ | Class name | mean building area m² (min) | mean building area m² (max) |
| :--- | :--- | ---: | ---: |
| LCZ 7 | Lightweight low-rise | | 100 |
| LCZ 8 | Large low-rise | 500 | |

**Only these two classes are constrained.** Every other class — built and natural — is unbounded on
both sides and takes no penalty in this dimension. That is deliberate and is the smallest change
that addresses what was measured: LCZ 7 and LCZ 8 are the only two classes whose Stewart & Oke
*name* asserts a building size, and they are the two that come out inverted. Giving LCZ 3 or LCZ 9
a range would be inventing a claim the published scheme does not make.

## Where the two numbers come from

**They are lczkit's, they are not measured, and the weight that would apply them ships at zero.**
This file records how they were arrived at so that the sweep which sets the weight can also move
them, rather than treating them as fixed.

- **500 m² for LCZ 8's floor.** A building large enough to be a warehouse, a supermarket, a school
  hall or a hangar rather than a house. Sits near the 90th percentile of built cells in the four
  runs measured — 13.8% to 22.2% of cells exceed it in Berlin, Istanbul and Bogotá, and 4.4% in
  Nairobi — so it selects a genuinely large-building minority rather than a plurality.
- **100 m² for LCZ 7's ceiling.** A single-storey lightweight dwelling. Below the median built cell
  in all four runs (medians 89–219 m²), and 49.7% of Nairobi's and 53.2% of Bogotá's built cells
  fall under it against 8.7% of Istanbul's — which is the right shape for a class that is common in
  some cities and absent from others.

**Neither number is calibrated, and the percentiles above are a sanity check on order of magnitude,
not a fit.** CLAUDE.md's standing ruling is that a threshold is swept against a reference and chosen
at an operating point, never picked — which is why this dimension carries weight 0.0 in every
shipped preset and changes no label until a sweep says what it should carry. Fitting the bounds to
the distributions above would encode one sample's fabric as a definition, which is what Phase 13
refused to do for the Stewart & Oke ranges and refuses here for lczkit's own.
