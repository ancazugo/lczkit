# Local Climate Zone map

A self-contained map of one `lczkit` run. Everything it needs is in this directory — there is no
CDN, no basemap API key, and nothing here reaches the network.

## Opening it

```sh
python serve.py
```

Then open <http://127.0.0.1:8000/>. Any Python 3 interpreter will do; `serve.py` imports only the
standard library and takes the directory it lives in as its default, so the bare command works from
anywhere. `--port` and `--directory` are available if you need them.

**Opening `index.html` directly will not work, and that is a browser limitation rather than a
choice made here.** The map's data is stored as [PMTiles](https://protomaps.com/docs/pmtiles),
which reads slices of one large file using HTTP range requests issued through `fetch`. The Fetch
standard leaves `file:` URLs unhandled, so `fetch` against one returns a network error in both
Chrome and Firefox. A local server is the smallest thing that satisfies it. `serve.py` implements
`Range` itself, because `http.server`'s built-in handler does not and would re-send the whole
tileset for every tile it is asked for.

Offline is fully satisfied — the server is local and the assets are vendored. What is given up is
opening the file with no process at all, which range-requested tiles make impossible in a current
browser.

## What is in here

| path | what it is |
|---|---|
| `index.html` | the page |
| `serve.py` | the local server described above; standard library only |
| `tiles/` | the map data as PMTiles archives |
| `style.json` | the MapLibre style, including every layer's colours and class breaks |
| `manifest.json` | the run's full configuration, source versions and cleaning report |
| `site.json` | what this site build did — tilesets, columns carried, anything skipped |
| `assets/` | the vendored front end, and `LICENSES.md` for it |

`manifest.json` is the provenance record: the pinned Overture release, the height cascade that ran,
the classifier weights, and the package versions. A figure taken from this map should cite it.

## Reading the map

The layer selector runs LCZ classification first, then **height provenance**, then the urban canopy
parameters, then `uniqueness`.

Height provenance is worth looking at before trusting any height-dependent class. It reports where
each unit's building heights actually came from — measured heights from Overture, or a coarse areal
raster standing in for them. The two produce the same LCZ label with very different reliability, and
the gap between cities is large: Berlin takes 79.7% of its building area from measured heights,
Cairo 1.0%.

Clicking a unit opens its full attribute table. The URL hash tracks the view, so a link shares the
exact position, zoom and active layer.
