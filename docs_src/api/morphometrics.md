# Morphometrics

**A descriptive output, not classifier input.** Majer & Fleischmann (2026) computed 107 2D
morphometric attributes — dimensional and shape, spatial distribution and intensity, street
descriptors and connectivity — over enclosed tessellation cells (ETCs), and found that the
correspondence between 2D morphometrics alone and LCZ types is "selective and inconsistent".
This package ports the attribute computation, not the paper's RandomForest/CNN prediction
schemes, and none of it feeds [`PrototypeClassifier`](classify.md): the classifier stays the
existing prototype-distance metric over Stewart & Oke's urban canopy parameters.

An **ETC** is momepy's `enclosed_tessellation` — one cell per building, generated within
street-bounded enclosures — restricted to cells with a parent building. It is not a partition of
the bounding box, unlike [`GridUnits`/`EnclosureUnits`](units.md): a cell with no building is
dropped, since it carries no morphometric meaning. See [Tessellation](units.md#tessellation).

The full attribute-to-momepy-call mapping is transcribed in
`docs/references/tables/majer_2026_morphometrics_menu.md`, the authoritative checklist this
package's own test suite parses cell for cell against the registry below.

**Output ships as its own run artefact**, `morphometrics.parquet` — and `morphometrics.tif`, one
band per attribute, area-weighted, if a raster resolution is requested. Neither is joined into
`units.parquet` or the classification table: ETCs are a different, finer-grained unit set than
whatever the run's classification units are.

::: lczkit.morphometrics
    options:
      members: []

## Computing the attributes

The one function `lczkit.pipeline.run_pipeline` calls for this stage.

::: lczkit.morphometrics.compute

## Graphs

Every `libpysal.graph.Graph` the metric modules need, built once and shared. ETC contiguity is
**fuzzy**, not the plain queen contiguity used elsewhere in this package — momepy's own
documented requirement for `enclosed_tessellation` output, which does not form a precise
polygonal coverage.

::: lczkit.morphometrics.graphs

## Dimensional & shape

::: lczkit.morphometrics.dimensional

## Spatial distribution & intensity

**Coverage area ratio is not guaranteed to fall in [0, 1].** A building's footprint area over its
own ETC's area is usually near 1, but momepy's tessellation shrink/segment step does not
guarantee a cell fully contains the building that seeded it — measured on 6.4% of ETCs in the
Hong Kong fixture. Reported as measured, not clipped.

::: lczkit.morphometrics.distribution

## Street descriptors & connectivity

**5 m and 400 m are network-distance radii, not topological hops.** Every connectivity function
here reads its `radius` as a hop count unless an edge-length attribute is named — confirmed
against the installed momepy rather than assumed, since 5 or 400 *hops* would be a nonsensical
pairing on any real street network.

::: lczkit.morphometrics.streets

## Contextual expansion

Opt-in: the 25th/50th/75th percentile of each primary attribute across neighbouring ETCs, via
`momepy.percentile`. Off by default (`MorphometricsConfig.contextual`). Unlike the paper, primary
attributes are kept once the expansion is computed rather than dropped.

::: lczkit.morphometrics.contextual

## Registry

::: lczkit.morphometrics.registry

## Rasterizing to a GeoTIFF

Not part of the paper. Builds a fine grid over the ETC layer's own bounds at the requested
resolution, reusing [`lczkit.units.overlay`](units.md#overlay) rather than a new vector-to-raster
library — the overlay-and-measure primitive already in the package is exactly what "which ETCs
does this pixel cover, and how much of each" is.

::: lczkit.morphometrics.raster

## Report

::: lczkit.morphometrics.report
