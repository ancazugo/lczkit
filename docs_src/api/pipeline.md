# Pipeline

The end-to-end chain: clean vectors, generate units, fill heights, read land cover, compute
parameters, classify, write outputs. `run_pipeline` is the only place the stages are wired
together, and the command line calls it rather than restating any of it.

::: lczkit.pipeline

## Raster windows

Clipping a raster to a study window, and checking that what came back actually covers it. The check
matters because neither half fails loudly on its own: `read(window=…)` returns a *smaller array*
rather than raising when the window runs off the edge of a raster, and units the raster never
reached come back as all-`NaN` fractions by design. Together that is a partly missing map with
nothing raised.

::: lczkit.raster_window
