# Land cover

::: lczkit.landcover
    options:
      members: []
      show_root_heading: false
      show_symbol_type_toc: false

[`RasterSource`][lczkit.protocols.RasterSource] returns a **table of land-cover shares per spatial
unit** — never pixels. Two implementations sit behind one interface: a local cloud-optimised
GeoTIFF read with `exactextract`, which is what continuous integration tests against, and a Google
Earth Engine reduction computed on Google's servers.

The class-to-fraction mapping is **config, never hardcoded**. Reading a product's own class
definitions and putting them in config is the difference between a reproducible run and a
plausible-looking wrong one.

This layer is also what supplies every parameter separating the natural classes A–G, so a raster
that does not cover the whole window is not a cosmetic problem: it produces missing values rather
than an error.

::: lczkit.landcover.local

## Earth Engine

Computed server-side with `reduceRegions`, returning tables rather than pixels. Units are chunked
into batches to stay under Earth Engine's element-count and payload limits, and results are cached
on a hash of the unit geometries, collection ID, date range and reducer together.

::: lczkit.landcover.earthengine

## Class mapping and assembly

::: lczkit.landcover.classify

::: lczkit.landcover.table
