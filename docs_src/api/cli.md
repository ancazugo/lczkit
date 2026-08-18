# Command line

`lczkit cities`, `lczkit run`, `lczkit site build|serve`, and `lczkit export`. Installed as the
`lczkit` console script.

The CLI is deliberately thin. It configures a run by calling the same `apply_preset` the publish
driver calls, rather than by listing the same settings again — anything a command line restates
is a place two answers can diverge, and the divergence shows up as a map that disagrees with a
published figure for no visible reason.

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
regions and covers it; `--so2sat-window` takes the densest 30 km window of that city's So2Sat
labels instead, which is the extent every validation sweep since Phase 9 measured over and works
for 28 cities. The second is a flag rather than a fallback, because a run that reached it by
accident — or silently failed to — would look comparable with a published figure while covering
different ground. Whichever was used is recorded in the run manifest's `extent`.

`lczkit export` reads only what a run already wrote, adds `units.gpkg`, and backfills the
manifest's `crs`, `crs_wkt` and `extent` — the last reconstructed from the units' own bounds and
tagged `kind="recovered"`, never presented as the window the run was asked for. It edits the manifest **as JSON rather than through
`RunManifest`** — revalidating an archived run against today's model would fill in defaults for
fields that run never had, and make it look like it came from code that did not produce it. It is
idempotent, and the archival GeoParquet is asserted byte-identical afterwards.

::: lczkit.cli

## Run

::: lczkit.cli.run

## Site

::: lczkit.cli.site

## Export

::: lczkit.cli.export

## `lczkit cities`

::: lczkit.cli.cities
