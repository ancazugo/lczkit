# Map site

::: lczkit.viz
    options:
      members: []
      show_root_heading: false
      show_symbol_type_toc: false

A static web map written to `output/lczkit/<run_id>/site/`. It is drawn by MapLibre GL, a browser
mapping library, reading PMTiles — a single-file tile archive served over ordinary HTTP range
requests, so no tile server is needed. The tiles are built by `tippecanoe`, a command-line tool
installed by the `lczkit[viz]` extra and invoked as a subprocess. The front end is vendored, so the
site depends on nothing remote.

The site **opens with no network and no software the user must install**. It is served by its own
bundled `serve.py`, standard library only, over loopback.

!!! warning "`file://` does not work, and that is not fixable"

    PMTiles reads byte ranges through `fetch`, and the Fetch standard leaves `file:` URLs
    unhandled — Chrome and Firefox both return a network error. Every built site ships a
    `README.md` giving the working command, because opening `index.html` is the first thing a
    recipient tries and it is the thing that fails.

The basemap is the run's **own** cleaned Overture water and streets: already cached for the bbox,
ODbL-attributable, and the same linework the classification was computed from. Online raster grounds
are available opt-in via `VizConfig.online_basemaps`, one or several, offered to the reader as a
dropdown; with it empty the emitted site names no remote host anywhere, and that default is enforced
by a test rather than promised in prose. Two of the providers need an API key, which is written into
`style.json` and therefore travels with the built site — see `VizConfig.maptiler_key` for what that
does and does not bound.

::: lczkit.viz.site

## Tilesets

**Attributes, not geometry, are what a unit tileset costs.** MVT repeats a feature's whole
attribute table in every tile at every zoom, so at 172 181 units a 38-column table costs more to
tile than 892 000 building footprints. Hence the render/detail split: render attributes at every
zoom, the rest once at maximum zoom where only a click reads them.

::: lczkit.viz.tiles

## Style

::: lczkit.viz.style

## Basemaps

Each provider records its licence and its usage terms, and the CLI prints them when one is
selected — OpenStreetMap's own tile service in particular is a donated resource rather than a
commercial one, and its usage policy applies to whoever opts in.

::: lczkit.viz.basemaps

## Server

::: lczkit.viz.serve
