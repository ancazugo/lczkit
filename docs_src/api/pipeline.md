# Pipeline

The end-to-end chain: clean vectors, generate units, fill heights, read land cover, compute
parameters, classify, write outputs. `run_pipeline` is the only place the stages are wired
together, and the command line calls it rather than restating any of it.

::: lczkit.pipeline

## Raster windows

Clipping a raster to a study window, and asserting that what came back actually covers it. The
assertion is the point: `read(window=…)` returns a *smaller array* rather than raising when the
window runs off the edge of a raster, and units the raster never reached come back as all-`NaN`
fractions by design. Two individually correct behaviours composing into a quarter-missing map is
the failure this module exists to make loud.

::: lczkit.raster_window
