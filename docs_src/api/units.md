# Spatial units

Three strategies, all satisfying [`SpatialUnitStrategy`][lczkit.protocols.SpatialUnitStrategy].
`unit_strategy` is config; the default is `grid` and there is deliberately **no auto-selection**.

**Units must form a partition of the bbox.** Assert it explicitly — a validity test is not a
partition test, and enclosure faces formed outside the extent were measured at 222% of the bbox
on Berlin and 379% on Rotterdam, silently corrupting the denominator of every area-weighted
statistic downstream.

The three differ in scale, which is the thing to know before choosing one:

| | median unit |
|---|---:|
| `EnclosureUnits`, Hong Kong fixture | 0.04 ha — a *block* |
| `GridUnits`, 100 m | 1.00 ha |
| `PatchUnits` | 11.69 ha |
| a WUDAPT polygon, sixteen cities | 2.2–52 ha |
| a So2Sat patch | 10.24 ha |

An enclosure is a block; an LCZ patch is a neighbourhood. A thinner barrier set does not close
that gap — it stops subdividing big faces rather than enlarging small ones — so `PatchUnits` sets
the scale with a merge step instead.

::: lczkit.units

## Grid

::: lczkit.units.grid

## Enclosures

::: lczkit.units.enclosures

## Patches

::: lczkit.units.patches

## Aggregation

::: lczkit.units.aggregate
