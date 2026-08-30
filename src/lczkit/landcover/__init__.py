"""Land cover: zonal class fractions per `unit_id`, never pixels.

Two interchangeable backends behind the `RasterSource` protocol — `LocalRasterSource` over a COG
on disk, `EarthEngineSource` over `reduceRegions` — returning schema-identical tables because both
reduce the *same* class-index mapping declared once in `LandCoverDatasetConfig`.

Classes within one dataset are disjoint and their fractions sum to 1.0 over the cells that count.
That matters for one thing in particular: the default WorldCover mapping carves `tree` out of
`pervious`, whereas Stewart & Oke (2012) count trees *within* the pervious surface fraction (LCZ
A, dense trees, is 90%+ pervious). A consumer reproducing their parameter must add `frac_tree`
back into `frac_pervious`.
"""
