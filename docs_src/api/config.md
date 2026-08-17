# Configuration

One pydantic model, serialised verbatim into every run's manifest alongside the pinned Overture
release, the Earth Engine collection IDs and date ranges, the resolved versions of `momepy`,
`neatnet` and `geopandas`, and a run timestamp.

`DATA_DIR` is resolved **once**, here. No other module reads `os.environ`, builds a path relative
to `__file__`, or joins its own paths — sources ask for `settings.source_dir(name)` instead. A
missing or unreachable `DATA_DIR` fails at config load, which is a much better place to find out
than three stages in.

Almost every field on this page carries its own docstring giving the value's provenance: a
published threshold and its paper, or a fixture measurement and what it separates. Where a
threshold was swept rather than chosen, the docstring says which sweep and at what operating
point.

::: lczkit.config

## Presets

A `Settings` produced by `Settings.load()` is deliberately not runnable — it has no bbox and no
release. Presets close that gap with the exact constants a published figure was produced under.

::: lczkit.presets

## City registry

The study cities the validation sweeps run over, with the window resolution used to pick a
comparable extent in each. The command line's `--city` resolves against this same registry, and
a test asserts the sweep imports it rather than defining its own.

::: lczkit.cities
