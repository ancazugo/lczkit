# Tree and water fraction ranges for the natural LCZ types — lczkit's own, NOT Stewart & Oke

**These are not Tier 1 numbers and must never be cited as such.** Stewart & Oke (2012) publish no
per-class range for tree cover or water cover; their seven surface properties do not include
either. This table exists because their published table cannot classify the natural types at all
with the parameters lczkit computes, and something has to.

## Why the published table is not enough

Read from `stewart_oke_2012_properties.md` in this directory. Across the seven natural classes:

- **A, B, C and D are separated only by sky view factor, aspect ratio and height of roughness
  elements.** All three are derived from buildings in lczkit — SVF is deferred entirely, `Hr` is
  the geometric mean of *building* height, and `aspect_ratio` comes from street profiles. In a
  park all three are null or zero, so the four classes collapse onto one point.
- **F (bare soil or sand) and G (water) differ in no published dimension whatsoever.** Both are
  ≤ 10% built, ≤ 10% impervious and ≥ 90% pervious, and G has no `Hr` range at all.
- **Only E (bare rock or paved) separates cleanly**, at ≥ 90% impervious.

Stewart & Oke themselves note that they count tree height within `Hr`; lczkit does not, and
neither does Bernard et al. (2024) — see footnote b of their Table 1. Bernard's answer was to add
two indicators outside the seven UCPs, `FW` (water fraction) and `FHV/A` (high-vegetation share of
vegetation), and route the natural types through a land-cover decision tree rather than the
distance metric. lczkit keeps the distance metric and adds the two dimensions to the prototype
table instead.

## The ranges

`tree_fraction` and `water_fraction` are the parameter columns of the same names. Blank means
unbounded on that side.

| LCZ | Class name | tree (min) | tree (max) | water (min) | water (max) |
| :--- | :--- | ---: | ---: | ---: | ---: |
| LCZ A | Dense trees | 0.50 | | | 0.10 |
| LCZ B | Scattered trees | 0.10 | 0.50 | | 0.10 |
| LCZ C | Bush, scrub | | 0.10 | | 0.10 |
| LCZ D | Low plants | | 0.10 | | 0.10 |
| LCZ E | Bare rock or paved | | 0.10 | | 0.10 |
| LCZ F | Bare soil or sand | | 0.10 | | 0.10 |
| LCZ G | Water | | 0.10 | 0.50 | |

The ten built types carry no constraint in either dimension, and are unbounded on both sides.

## Where the two numbers come from

**0.10 — "negligible".** The Stewart & Oke table uses 10% as its own negligible-cover boundary
throughout the natural rows: every one of A-G is ≤ 10% building surface fraction, and every one
except E is ≤ 10% impervious. Reusing that boundary keeps the added dimensions on the same footing
as the published ones rather than introducing a second convention.

**0.50 — "the majority of the unit".** The plainest reading of the class names "Dense trees" and
"Water": more than half the unit is that surface. It is deliberately not tuned against any city,
because tuning it against one city is how a threshold becomes quietly wrong everywhere else.

Both are `lczkit.config.ClassificationConfig` values and can be overridden per class.

## Known consequence: C and F are unreachable by default

C (bush, scrub), D (low plants) and F (bare soil or sand) are identical in this table, and
identical in the published one too once the building-derived dimensions drop out. Nothing in the
default land-cover mapping separates them: ESA WorldCover distinguishes shrubland (20), grassland
(30) and bare/sparse vegetation (60), but `lczkit.config.UcpConfig` folds all three into
`pervious`, because Stewart & Oke's surface fractions have no finer category.

Rather than let three tied prototypes be resolved by index order, the default reachable natural
set is **{A, B, D, E, G}**, with C and F recorded in the run manifest as unreachable and why. The
route to reaching them is a land-cover mapping that emits shrub and bare as their own classes, plus
a parameter carrying those fractions through — not attempted here.
