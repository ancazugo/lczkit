# Land cover

::: lczkit.landcover
    options:
      members: []
      show_root_heading: false
      show_symbol_type_toc: false

[`RasterSource`][lczkit.protocols.RasterSource] returns a **fractions table keyed by `unit_id`** —
never pixels. Two implementations behind one interface: a local COG read with `exactextract`,
which is what CI tests against, and an Earth Engine reduction computed server-side.

The class-to-fraction mapping is **config, never hardcoded**. Reading a product's own class
definitions and putting them in config is the difference between a reproducible run and a
plausible-looking wrong one.

This layer is also what supplies every dimension separating the natural classes A–G, so a raster
short of its window is not a cosmetic problem: it produces `NaN` fractions rather than an error.

::: lczkit.landcover.local

## Earth Engine

Computed server-side with `reduceRegions`, returning tables rather than pixels. Units are chunked
into batches to stay under Earth Engine's element-count and payload limits, and results are cached
on a hash of the unit geometries, collection ID, date range and reducer together.

::: lczkit.landcover.earthengine

## Class mapping and assembly

::: lczkit.landcover.classify

::: lczkit.landcover.table
