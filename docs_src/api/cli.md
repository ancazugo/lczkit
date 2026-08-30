# Command line

`lczkit cities`, `lczkit run`, `lczkit site build|serve`, and `lczkit export`. Installed as the
`lczkit` console script.

The command line is deliberately thin. It configures a run through `apply_preset` rather than by
restating any setting of its own, so there is one definition of what a preset means and the command
line cannot drift from it.

```bash
lczkit cities cambridge                     # find an extent, and what it will cost
lczkit run --city cambridge --country GBR
lczkit run --city berlin --so2sat-window    # the extent the recorded figures were measured over
lczkit run --bbox 13.29,52.45,13.52,52.59   # needs nothing on disk
lczkit run --city berlin --dry-run          # resolve the config, create nothing
lczkit site build output/lczkit/<run_id>
lczkit site serve output/lczkit/<run_id>
lczkit export output/lczkit/<run_id>        # add units.gpkg to a run already on disk
```

**Three locators, and they mean different ground.** `--city` names one of GUPPD's 5 558 urban
regions and covers it. `--so2sat-window` takes the densest 30 km window of that city's So2Sat
labels instead — the extent the published agreement figures were measured over — and works for 28
cities. The second is a flag rather than a fallback: a run that reached it by accident, or silently
failed to, would look comparable with a published figure while covering different ground. Whichever
was used is recorded in the run manifest's `extent`.

`lczkit export` reads only what a run already wrote, adds `units.gpkg`, and backfills the
manifest's `crs`, `crs_wkt` and `extent` — the last reconstructed from the units' own bounds and
tagged `kind="recovered"`, never presented as the window the run was asked for. It edits the manifest **as JSON rather than through `RunManifest`**: revalidating an archived run
against today's model would fill in defaults for fields that run never had, and make it look like
it came from code that did not produce it. It is idempotent, and the archival GeoParquet is
byte-identical afterwards.

::: lczkit.cli

## Run

::: lczkit.cli.run

## Site

::: lczkit.cli.site

## Export

::: lczkit.cli.export

## `lczkit cities`

::: lczkit.cli.cities
