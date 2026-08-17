# Sources

::: lczkit.sources
    options:
      members: []
      show_root_heading: false
      show_symbol_type_toc: false

Ingestion. Everything here writes into `input/<Source>/` and nowhere else, and nothing here ever
modifies or deletes a file that is already there — that directory is shared with other projects.
There is no separate cache directory: a cache hit is just a file that is already on disk, with
the cache key expressed as the filename.

::: lczkit.sources.overture

## Areal height products

Fetchers for the rasters that tiers 2–4 of the height cascade read. None of these implements
`HeightSource` — they resolve a path, and `ArealRasterTier` reads it. Keeping fetch and read
apart is what lets the tier stay offline and testable, and what lets a user who has already
placed a product by hand skip these entirely.

::: lczkit.sources.height_products

## Land cover

::: lczkit.sources.worldcover
