# Urban canopy parameters

An **urban canopy parameter** is a number describing the shape of the urban surface inside one
spatial unit — how much of the ground is building, how tall the buildings are, how deep the street
canyons are. These are the inputs the classification runs on. Each is defined in the
[glossary](../glossary.md).

The parameter table, keyed by `unit_id`. Every column is registered with a documented unit and a
source reference — see [the registry](#registry) — because a parameter written to the output
without those is a number nobody can check.

Two definitions are load-bearing and easy to get wrong:

- **`Hr`, the height of roughness elements — the typical height of whatever sticks up into the
  wind — is the *geometric* mean of building heights**, per Stewart
  & Oke and Bernard et al. (2024) Table 1 — not the area-weighted arithmetic mean. The two diverge
  materially in units mixing tall and short buildings, and the ranges classification normalises
  against were defined for the geometric mean. `h_mean_area_weighted`, `h_std` and
  `h_geometric_area_weighted` are secondary columns and are not used for classification.
- **Building surface fraction — the share of a unit's ground covered by building — comes from
  `buildings_area`**, never `buildings_topo`. Cleaning produces two building layers: one made
  valid for topology, at the cost of some footprint area, and one that preserves area. Using the
  topology layer here discards roughly a quarter of the footprint area and was the single largest
  known source of classification error.

One further column is a flag rather than a measurement. `impervious_clipped` marks the units where
the building share exceeded the raster's built-up class, so the subtraction that separates roofs
from other sealed ground had to be clipped at zero. Everywhere else building, impervious and
pervious shares sum to exactly one; where this fires they exceed it. It fires wherever vector
footprints cover more ground than a 10 m land-cover product calls built-up, which is dense
low-rise mapped from imagery.

::: lczkit.ucp
    options:
      members: []

## Parameter assembly

::: lczkit.ucp.parameters

## Registry

The controlled vocabulary: one `ParameterSpec` per column, carrying its unit, its display label
and the paper it comes from.

::: lczkit.ucp.registry

## Buildings, streets, surface

::: lczkit.ucp.buildings

::: lczkit.ucp.streets

::: lczkit.ucp.surface

## Functional evidence

`industrial_fraction` exists because LCZ 8 and LCZ 10 are geometrically near-identical, and
because anthropogenic heat output — the only published Stewart & Oke property separating them
directly, at 300+ against ≤50 W m⁻² — is not something this package can measure.

Both `industrial_fraction_of_building_area` (Bernard's `FIND/B`, which the LCZ 10 rule reads) and
`industrial_fraction_of_unit_area` are emitted, each named for what it divides by.

## Overture attributes

::: lczkit.ucp.attributes

## Industrial

::: lczkit.ucp.industrial

## Semantic evidence

Overture's `subtype`/`class` vocabulary, read through a committed crosswalk. Each fraction ships
beside a **coverage** column, and that is the point: a `lightweight` fraction of 0.0 in Nairobi is
94.8% of building area carrying no tag at all, not an absence of informal settlement.

::: lczkit.ucp.semantics

::: lczkit.ucp.tag_diagnostic

## Measuring on one unit set and classifying on another

A street canyon has to be measured against streets, and a 100 m grid cell is not bounded by any —
so `aspect_ratio`, which is 3 of the 17 applied weight units and the only dimension separating
LCZ 8 from LCZ 3 and 6, is null on **10.8%** of one Istanbul extent's built grid cells against
**0.9%** of its enclosures. The two unit systems are complementary rather than rival: an enclosure
is a block and not an LCZ patch, and it is still the better thing to measure a canyon on.

`UcpConfig.measure_on` defaults to `"units"`. **No accuracy claim is attached**: the threshold has
not been calibrated against a reference, so switching it on makes a run incomparable with one at the
defaults.

::: lczkit.ucp.measure
