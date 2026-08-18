# Configuration

One pydantic model, serialised verbatim into every run's manifest alongside the pinned Overture
release, the Google Earth Engine collection identifiers and date ranges, the resolved versions of
`momepy`, `neatnet` and `geopandas`, and a run timestamp.

`DATA_DIR` is resolved **once**, here. No other module reads `os.environ`, builds a path relative
to `__file__`, or joins its own paths — sources ask for `settings.source_dir(name)` instead. A
missing or unreachable `DATA_DIR` fails at config load, which is a much better place to find out
than three stages in.

Almost every field on this page carries its own docstring giving the value's provenance: a
published threshold and its paper, or a fixture measurement and what it separates. Where a
threshold was swept rather than chosen, the docstring says which sweep and at what operating
point.

!!! note "Two options ship switched off, and why"

    A threshold in this package is *swept* against a reference and chosen at an operating point,
    never picked because it looks reasonable. Anything whose threshold has not been swept ships
    disabled, and two options are currently in that state:

    - **`ucp.measure_on = "enclosures"`** measures the parameters on street-bounded blocks and
      transfers them to the units being classified. A street canyon has to be measured against
      streets, and a grid cell is bounded by none — on one Istanbul extent the aspect ratio is
      missing from 10.8% of built grid cells against 0.9% of enclosures. Default `"units"`.
    - **`classification.modal_filter`** replaces an isolated unit's label with the one most of its
      neighbours carry — a minimum mapping unit, standard in this literature. Default off.

    Every figure this project has recorded was measured with both off, so switching either on makes
    a run incomparable with a published number until the corresponding sweep has been run.

::: lczkit.config

## Presets

A `Settings` produced by `Settings.load()` is deliberately not runnable — it has no bbox and no
release. Presets close that gap with the exact constants a published figure was produced under.

::: lczkit.presets

## Places — the general locator

Every urban region on earth, by name, from the Global Urban Polygons and Points Dataset (GUPPD) —
a gazetteer from NASA's Socioeconomic Data and Applications Center and the European Commission's
Joint Research Centre: 5 558 regions across 173 countries, in one 564 KB table. This is what
`lczkit run --city` and `lczkit cities` resolve against, and it is a **locator, not a reference** —
nothing here labels or validates anything.

A name is not unique (149 of the 5 558 are shared), so an ambiguous query is refused with the
candidates rather than answered with the first match. Getting that wrong would run the wrong
continent and record a manifest that looks entirely correct.

::: lczkit.places

## City registry — the comparable-extent locator

The 28 study cities the validation sweeps run over — those with enough hand-drawn So2Sat LCZ42
labels to validate against — with the window resolution used to pick a comparable extent in each.
Reached by `lczkit run --city ... --so2sat-window`, which is a flag rather than a fallback: this
window and the GUPPD region of the same city are different ground, and only this one makes a run
comparable with a recorded agreement figure. A test asserts the sweep imports this registry rather
than defining its own.

::: lczkit.cities
