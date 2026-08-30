# Height cascade

::: lczkit.heights
    options:
      members: []
      show_root_heading: false
      show_symbol_type_toc: false

**This is what differentiates `lczkit` from an implementation running on OpenStreetMap alone.**
Overture Maps solves footprint coverage; it does not solve height. Overture merges several sources
winner-takes-all per building, and only OpenStreetMap among them carries heights — so wherever a
machine-learning footprint source won the geometry, there is no height at all. That is much of the
Global South, and plenty of developed cities outside the centre: Cairo, Nairobi and Islamabad each
carry a directly measured height for about 1% of their building area.

The answer is a graded **cascade** — a series of sources tried in order, each filling only what the
last left empty — plus honest reporting of which one answered. The tiers, in order:

1. Overture `height`, else `num_floors × storey_height`
2. Google Open Buildings 2.5D — **retired from the default cascade, measured harmful**
3. WSF-3D, global ~90 m
4. GHS-BUILT-H, global 100 m

Tiers 2–4 are *areal* products: a raster giving one value per cell, so every building inside a
cell is assigned the same neighbourhood average. That is a
categorically weaker measurement than tier 1 and the output says so, per building via
`height_source` and per unit via `height_tier_fractions` — because "90% real heights" and "90%
coarse raster fallback" produce the same label with very different trustworthiness.

!!! warning "Per-building accuracy is the wrong acceptance test for a height product"

    Open Buildings 2.5D has the lowest per-building error of the three and the only within-unit
    skill, **and still makes the map worse**. `Hr` is a geometric mean, and dispersion depresses
    it: GOB's within-unit spread is 0.441 against reality's 0.195, so over half is noise. Evaluate
    any new tier on **within-unit dispersion against reality**, not on MAE.

::: lczkit.heights.cascade

## Tiers

::: lczkit.heights.tiers

## Raster reads

::: lczkit.heights.raster

## Completeness and provenance

`height_completeness` and `height_tier_fractions` are primary deliverables, not diagnostics.

::: lczkit.heights.completeness

## Dispersion

Coverage is only half of what a substituted height does. `Hr` is a geometric mean, so it is
depressed by spread and rises as spread collapses — and the tiers that shipped **compress**
within-unit spread rather than inflating it, which is the opposite of the failure Open Buildings was
rejected for. Median coefficient of variation across whole-city runs: 0.266 for real Overture
heights in Berlin, 0.192 for WSF-3D in Nairobi, and 0.112 for GHS-BUILT-H in Bogotá, where 23.6% of
units carry a single height throughout. Each run reports its own figures in the manifest.

::: lczkit.heights.dispersion

::: lczkit.heights.provenance

::: lczkit.heights.diagnostic

::: lczkit.heights.inherit
