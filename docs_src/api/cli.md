# Command line

`lczkit run`, `lczkit site build|serve`, and `lczkit export`. Installed as the `lczkit`
console script.

The CLI is deliberately thin. It configures a run by calling the same `apply_preset` the publish
driver calls, rather than by listing the same settings again — anything a command line restates
is a place two answers can diverge, and the divergence shows up as a map that disagrees with a
published figure for no visible reason.

```bash
lczkit run --city berlin --preset published
lczkit run --city berlin --dry-run        # resolve the config, create nothing
lczkit site build output/lczkit/<run_id>
lczkit site serve output/lczkit/<run_id>
lczkit export output/lczkit/<run_id>      # add units.gpkg to a run already on disk
```

`lczkit export` reads only what a run already wrote, adds `units.gpkg`, and backfills the
manifest's `crs` and `crs_wkt`. It edits the manifest **as JSON rather than through
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
