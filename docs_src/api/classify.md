# Classification

::: lczkit.classify
    options:
      members: []
      show_root_heading: false
      show_symbol_type_toc: false

**Prototype-distance classification**, implemented from the Stewart & Oke parameter table. Each of
the seventeen classes has a published range for every surface property, so a class is a box in
parameter space and a unit is a point; the distance is the gap from the point to the box, zero
inside it, and the nearest class wins. Terms are defined in the [glossary](../glossary.md).

**The distance vector is the primary output.** Every unit carries its full 17-way distance to
each prototype, plus `lcz_primary`, `lcz_secondary` and a `uniqueness` measure. Hard labelling is
a downstream convenience — nothing in the core API returns a bare LCZ integer.

## Weights are config, not assumptions

Two presets ship, and the active one appears in the manifest:

- **`bernard2024_partial`** (default). Bernard's published weights, in his notation, are sky view
  factor 4, aspect ratio 3, building surface fraction (`FB`) 8, impervious fraction (`FI`) 0,
  pervious fraction (`FP`) 0, height of roughness elements (`Hr`) 6 and roughness length (z₀) 0.5 —
  21.5 units in total. `lczkit` can apply only 17 of them: sky view factor and roughness length are
  not computed, and the impervious and pervious fractions carry zero weight in Bernard's own
  scheme, leaving three parameters with any weight at all. Building surface fraction therefore
  carries roughly 47% of the result on its own. The preset is named `_partial` for
  exactly that reason; it is not Bernard's metric, and the unapplied dimensions and the
  renormalisation are recorded in the manifest.
- **`equal`** — uniform weights, for comparison.

## Null parameters

Some units legitimately have null parameters: `aspect_ratio` is null wherever no street reaches a
building. These are handled by **weighted partial distance** — sum over available parameters only,
renormalising by the sum of their weights, so units stay comparable on a common scale. Nothing is
imputed and no unit is dropped. Each unit records `n_params_used` and which parameters were
missing.

## Two classes are not assigned by distance

**LCZ 10** is removed from the metric entirely and assigned functionally from
`industrial_fraction_of_building_area`, at a threshold **calibrated by a precision/recall sweep**
against the Rotterdam reference rather than picked. **LCZ F** is unreachable by arithmetic rather
than by configuration — LCZ D's prototype box contains F's in every dimension, so `d(F) >= d(D)`
always. The manifest records *dominated* separately from *excluded*.

::: lczkit.classify.classifier

## Distance and normalisation

::: lczkit.classify.distance

## Prototypes

Transcribed from `docs/references/tables/`. The three ranges `lczkit` defines itself are tagged
`source="lczkit"` rather than attributed to Stewart & Oke: `tree_fraction` and `water_fraction`,
without which the natural classes cannot be separated at all, and `mean_building_area_m2`, without
which **LCZ 7 and LCZ 8 come out swapped** — measured over built cells, "large low-rise" landing on
55–93 m² footprints and "lightweight low-rise" on 7 000–13 000 m² ones, in every city checked. The
building-size dimension carries weight 0.0 in every shipped preset and so changes no label; its
weight and its two bounds are for a sweep to set.

::: lczkit.classify.prototypes

## Weights

::: lczkit.classify.weights

## Functional rules

::: lczkit.classify.rules

## Two things worth reading per unit

`n_params_used` says how many of the weighted parameters the unit actually had a value for — a
unit scored on two dimensions and one scored on seven are not comparable, and this is what tells
them apart. `n_tied_classes` counts the classes sitting at *exactly* the minimum distance: two or
more means the unit fell inside more than one class's box and the label was settled by an
arbitrary tie-break rather than by any measurement.

Both differ from `uniqueness`, which measures how far the runner-up was from the winner. That is a
statement about the metric's geometry; these two are statements about what the unit had to be
scored on.

## Spatial smoothing

Every unit is classified independently of its neighbours, so an isolated cell can carry a label the
fabric around it does not — salt-and-pepper at a grain Stewart & Oke never intended a class to be
read at. A spatial filter is the standard answer in this literature and lczkit has never had one.
**It ships disabled**, because its threshold has not been swept and every stored figure in this
project was measured without it.

::: lczkit.classify.smoothing

## Labels and colours

LCZ Generator integer codes (1–10 built, 11–17 for A–G) and the standard Demuzere colour table,
so results drop into existing tooling.

::: lczkit.classify.labels
