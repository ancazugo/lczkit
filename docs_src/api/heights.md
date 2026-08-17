# Height cascade

::: lczkit.heights
    options:
      members: []
      show_root_heading: false
      show_symbol_type_toc: false

**This is what differentiates `lczkit` from GeoClimate-on-OSM.** Overture solves footprint
coverage; it does not solve height. In ML-dominated areas — much of the Global South, but also
plenty of developed cities outside the centre — tier-1 heights are near-absent: Cairo, Nairobi and
Islamabad each carry tier-1 heights for about 1% of building area.

The answer is a graded cascade plus honest reporting, not a pretence of completeness. Tiers, in
order:

1. Overture `height`, else `num_floors × storey_height`
2. Google Open Buildings 2.5D — **retired from the default cascade, measured harmful**
3. WSF-3D, global ~90 m
4. GHS-BUILT-H, global 100 m

Tiers 2–4 are areal products: they assign a neighbourhood mean to individual buildings. That is a
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

::: lczkit.heights.provenance

::: lczkit.heights.diagnostic

::: lczkit.heights.inherit
