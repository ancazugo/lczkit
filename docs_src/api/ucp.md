# Urban canopy parameters

The parameter table, keyed by `unit_id`. Every column is registered with a documented unit and a
source reference — see [the registry](#registry) — because a parameter written to the output
without those is a number nobody can check.

Two definitions are load-bearing and easy to get wrong:

- **`Hr`, height of roughness elements, is the *geometric* mean of building heights**, per Stewart
  & Oke and Bernard et al. (2024) Table 1 — not the area-weighted arithmetic mean. The two diverge
  materially in units mixing tall and short buildings, and the ranges classification normalises
  against were defined for the geometric mean. `h_mean_area_weighted`, `h_std` and
  `h_geometric_area_weighted` are secondary columns and are not used for classification.
- **Building surface fraction comes from `buildings_area`**, never `buildings_topo`. Using the
  topology layer discards roughly a quarter of footprint area and was the single largest known
  source of classification error.

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

**A quantity's denominator belongs in its name.** Both `industrial_fraction_of_building_area`
(Bernard's `FIND/B`, which the LCZ 10 rule reads) and `industrial_fraction_of_unit_area` are
emitted as separately named columns.

::: lczkit.ucp.industrial

## Semantic evidence

Overture's `subtype`/`class` vocabulary, read through a committed crosswalk. Each fraction ships
beside a **coverage** column, and that is the point: a `lightweight` fraction of 0.0 in Nairobi is
94.8% of building area carrying no tag at all, not an absence of informal settlement.

::: lczkit.ucp.semantics

::: lczkit.ucp.tag_diagnostic
