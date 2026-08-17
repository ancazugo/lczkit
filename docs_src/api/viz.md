# Map site

::: lczkit.viz
    options:
      members: []
      show_root_heading: false
      show_symbol_type_toc: false

A static site written to `output/lczkit/<run_id>/site/`: MapLibre GL over the PMTiles protocol,
a vendored front end, and `tippecanoe` — the pinned `lczkit[viz]` extra — invoked as a subprocess.

The site **opens with no network and no software the user must install**. It is served by its own
bundled `serve.py`, standard library only, over loopback.

!!! warning "`file://` does not work, and that is not fixable"

    PMTiles reads byte ranges through `fetch`, and the Fetch standard leaves `file:` URLs
    unhandled — Chrome and Firefox both return a network error. Every built site ships a
    `README.md` giving the working command, because opening `index.html` is the first thing a
    recipient tries and it is the thing that fails.

The basemap is the run's **own** cleaned Overture water and streets: already cached for the bbox,
ODbL-attributable, and the same linework the classification was computed from. An online raster
basemap is available opt-in via `VizConfig.online_basemap`; with it unset the emitted site names
no remote host anywhere, and that default is enforced by a test rather than promised in prose.

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
selected — the OSMF tile policy in particular is a donated resource, not a CDN.

::: lczkit.viz.basemaps

## Server

::: lczkit.viz.serve
