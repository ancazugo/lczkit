# Phase 7 — the static map site

Phase 7 was specified as post-MVP work and deferred until the MVP was complete. What changed is not
the specification but the subject: before Phase 8, `clean_vectors` over Berlin did not finish, so a
site would have shown a 9 km² tile. It now shows the whole 891 km² city, which turns tile sizing
from a formality into the phase's main engineering decision.

The deliverable is `lczkit.viz.build_site(run_dir)`, writing a directory that opens in a browser,
reaches no network, and is meant to be archived beside a paper.

---

## 1. Three spec details checked against the machine before anything was built

CLAUDE.md's Phase 7 section is unusually prescriptive — it names the tiler, the file chain, the
renderer and the basemap source. Each was checked rather than assumed. One held; two did not.

### 1.1 tippecanoe — the spec holds, and my first reading of it was wrong

I initially reported that tippecanoe could not be used here: it is a C++ binary, it was not on
`PATH`, and the environment rules forbid `conda`, `apt` and anything but `uv add --active`. That was
wrong, and the user corrected it. **`tippecanoe` 2.72.0 is on PyPI** as manylinux wheels shipping
the real upstream binaries — `tippecanoe`, `tile-join`, `tippecanoe-overzoom` and the rest — under
`tippecanoe.BIN_DIR`, BSD-3-Clause packaging over BSD-2-Clause upstream. `uv add --active --optional
viz tippecanoe==2.72.0` works, it is pinnable, and the spec's chain stands unchanged.

The lesson is narrow and worth writing down: *"not on PATH and not obviously packaged"* is not the
same as *"not installable"*, and I had checked one plausible package name (`pytippecanoe`) rather
than the obvious one.

The binary is resolved through `tippecanoe.BIN_DIR` rather than `PATH`, so the version the manifest
records is the version the lockfile pinned.

### 1.2 `file://` — the acceptance criterion is not satisfiable as written

CLAUDE.md asks for both PMTiles over HTTP range requests *and* a directory that "opens correctly
from `file://` with networking disabled". These are mutually exclusive in a current browser. PMTiles
reads byte ranges through `fetch`, and the Fetch standard leaves `file:` URLs unhandled, so both
Chrome and Firefox return a network error. MapLibre's glyph and sprite loading has the same
constraint, which is why the style names neither.

**Ruled by the user: PMTiles plus a shipped server.** The criterion is amended to *"opens with no
network and no software the user must install"*. `site/serve.py` is standard library only.

That server had to implement `Range` itself. `http.server.SimpleHTTPRequestHandler` **does not
support it at all** — verified by reading the class rather than by assuming — so it answers 200 with
the whole body for every request. Under PMTiles that means re-sending a 60 MB tileset per tile,
which presents as "the map is slow" rather than as an error. Forty lines of subclass, and
`test_viz_serve.py` asserts 206, `Content-Range`, byte-exact bodies, suffix ranges and the
416 case.

### 1.3 The basemap — a Protomaps extract is not reachable here

CLAUDE.md specifies "a Protomaps extract clipped to city bbox". Extracting one needs either the Go
`pmtiles` CLI, which the environment rules do not admit, or a ~120 GB global download.

**Ruled by the user: build it from the run's own layers.** They are already cached for the exact
bbox, cost nothing extra, are correctly attributable (ODbL), and show the reader the same linework
the classification was computed from — which for a paper supplement is more informative than a
generic street map.

---

## 2. The size problem is attributes, not geometry

Sizing was measured before the design was fixed, on the real 891 km² Berlin layers. GDAL's PMTiles
writer was used for the survey because it needs no external tool; the numbers are indicative rather
than final, and the shipped tilesets are tippecanoe's.

| layer | features | zooms | attrs | size |
|---|---:|---|---:|---:|
| buildings | 891 994 | z14–16 | 3 | 60.9 MB |
| **units, full attribute table** | 172 181 | z10–14 | 38 | **115.5 MB** |
| units, full attribute table | 172 181 | z14 only | 38 | 42.2 MB |
| units, render attributes only | 172 181 | z10–14 | 8 | 34.4 MB |
| basemap streets | 267 021 | z10–14 | 2 | 20.0 MB |
| basemap water | 5 983 | z8–14 | 2 | 1.5 MB |

**The unit layer costs more than 892 000 building footprints, and its geometry is 172 181
rectangles.** MVT repeats a feature's whole attribute table in every tile at every zoom, so 38
columns across five zoom levels dominates everything else in the site. Dropping to the eight
render-driving columns takes the same geometry from 115.5 MB to 34.4 MB.

Hence the split that ships: the render attributes ride at every zoom, and everything else — the
17-way distance vector, the tier fractions, the parameters the sidebar lists — rides once at the
maximum zoom, where the only thing that reads them is a click. Above a configurable unit count the
detail tileset is declined outright and recorded in `site.json` as declined, because it is the one
part of the site whose size is unbounded in extent.

Two smaller findings from the same measurement:

- **Overture's `id` is 32 characters, and the basemap was carrying it.** Stripping the context
  layers to geometry alone took a 9 km² basemap from 6.43 MB to 4.00 MB. They are painted flat,
  carry no labels and answer no click, so every attribute on them was dead weight.
- **Land use was then 94% of what remained** — 1 864 polygons carrying 401 162 vertices — for a dark
  wash drawn *underneath* an 82%-opacity unit fill. It is off by default and available in config.
  With water and streets only, at `--simplification=10` and one zoom level below the units, the
  9 km² basemap is 0.158 MB and builds in 3.8 s rather than 65.6 s.

Context geometry is the one thing in the site that carries no measurement, which is why it is the
only thing simplified for display. The unit and building tilesets keep tippecanoe's faithful
default.

### 2.1 What actually ships, measured

The whole 891 km² site — 172 181 units, 892 014 buildings — builds in **67 seconds**:

| tileset | zooms | features | size | build |
|---|---|---:|---:|---:|
| `units.pmtiles` — 12 render attributes | z10–14 | 172 181 | 28.09 MB | 9.5 s |
| `units_detail.pmtiles` — the other 40 | z14 | 172 181 | 18.46 MB | 8.9 s |
| `basemap.pmtiles` — water + streets | z9–13 | 201 144 | 9.24 MB | 6.2 s |
| **default site** | | | **55.79 MB** | |
| `buildings.pmtiles` | z14–16 | 892 014 | 76.85 MB | 38.3 s |
| with buildings | | | 132.63 MB | 67.1 s |

**The buildings default was decided on this number.** At 76.85 MB they are 58% of the full site on
their own, against 55.79 MB for everything else together. CLAUDE.md already specified them off by
default; the measurement confirms rather than revises it.

**The split was decided on this one, and it is smaller than the survey implied.** Tiling all 52
columns in a single z10–14 tileset costs **59.82 MB** against the split's **46.55 MB** — a 22%
saving, not the ~70% the GDAL survey suggested, because tippecanoe encodes repeated attributes far
better than GDAL's MVT writer does. The split is kept anyway, and the stronger reason is not the
total: it halves what a reader has to fetch to pan around, since `units_detail` is touched only by a
click at maximum zoom. Recording the weaker-than-expected saving matters more than the decision,
which did not change.

---

## 3. tippecanoe fails on a 256-core machine

Every tileset failed on first run with:

```
Internal error: 745 shards not a power of 2
```

raised from tippecanoe's radix sort while reordering geometry. Sweeping `TIPPECANOE_MAX_THREADS`:

| threads | 8 | 16 | 32 | 48 | 64 | 96 | 128 | 192 | 256 |
|---|---|---|---|---|---|---|---|---|---|
| result | ok | ok | ok | ok | ok | ok | ok | ok | **fails** |

Only the top of the range fails, and lowering `ulimit -n` instead produces a different failure
(`Too many open files`), so the shard arithmetic — not the file limit — is what breaks.

Decoding two tilesets built at 8 and 128 threads showed **identical tile content**: the only bytes
that differ are the output filename tippecanoe records in its own metadata. So capping costs nothing
but wall time, and tile generation is minutes. `TIPPECANOE_MAX_THREADS` is set to
`min(len(sched_getaffinity(0)), 32)` unless an operator has already set it, and the effective value
is recorded per tileset.

This is the third defect in this project that is invisible on a laptop and fatal on the machine the
package runs on, after Phase 8's `fork` deadlock and its thread oversubscription. The pattern is
worth naming: **a default tuned for a workstation is not a default at 256 cores.**

---

## 4. What makes "the site does not recompute anything" checkable

CLAUDE.md's binding constraint is that the site is a pure transform of run outputs — it must never
recompute a parameter or a quantile. That is a claim that can be asserted or tested, and the design
choice that makes it testable is generating the **MapLibre style in Python**.

`viz/style.py` builds `style.json` from the manifest's `legend` and `breaks`. `tests/test_viz_style.py`
then asserts that every LCZ colour equals `classify.labels.legend()` — read from the module, not
restated, so a test that passed while the map drifted is impossible — and that every choropleth's
class boundaries are the manifest's own numbers in the manifest's own order. The same claims made
about `app.js` would be claims about a string.

`app.js` is left with what only a browser can do: pan, click, toggle. Switching a view is
`setPaintProperty` on one already-loaded fill layer, so no view change refetches a tile; the
selection highlight is a `feature-state` rather than a filter, for the same reason.

Two supporting pieces:

- **`write_run(layers=)`** persists the cleaned streets, water, land use and buildings under
  `layers/`. Without it the basemap and the extrusions would have to come from `input/` at
  site-build time, and an archived run directory could not rebuild its own map.
- **`promoteId: "unit_id"`** on the unit source. `setFeatureState` needs a feature id and tippecanoe
  assigns none unless asked, so without it a click would highlight nothing and report no error. It
  also makes the map key selection on the same identifier every other stage joins on.

The offline guarantee is tested at the level where it is real: `index.html`'s `src`/`href`
attributes are all relative, every `url()` in every stylesheet is a `data:` URI or relative, and no
authored file names a remote host. What the vendored MapLibre requests at runtime is decided by the
style document, and the style test asserts that names no glyphs, no sprite, and only relative
`pmtiles://./tiles/` sources.

---

## 5. Two Phase 8 discrepancies this run surfaced

The first end-to-end metropolitan run through `write_run` produced two numbers that do not match
Phase 8's. Both are recorded here and **not** reconciled — neither has been diagnosed, and guessing
at a cause is the anti-pattern this project has paid for three times.

**`clean_vectors` took 4 469.1 s against Phase 8's 585.6 s, with a *warm* tile cache.** The street
step reports `"cached": true`, 594 tiles, and the identical pooled threshold 8.131236, so
simplification — the 7.5 minutes that dominated the Phase 8 run — was essentially free this time and
the run was still 7.6× slower. That points at the serial building-cleaning prefix, which Phase 8
measured as near-linear and inferred at roughly two minutes for 892 000 footprints. The run shared
the node with a nine-hour whole-network threshold job and with several other users' jobs, which is a
plausible confound and not a measurement. Nothing here was profiled; the honest statement is that
the figure is unexplained.

**The same cache produced a different feature count.** `simplify_streets_tiled` reports
`n_out = 198 879` where the Phase 8 run that *wrote* that cache reported `195 508` — 1.7% apart,
from identical per-tile inputs and an identical threshold. The candidate worth checking first is
order: `_stitch` concatenates the parts and runs `neatnet.remove_interstitial_nodes` over the
result, and a cache read need not return tiles in the order a cold run computed them. If that is it,
the tiled path is order-dependent at the seams, which matters more than 1.7% of a line count
suggests — it would mean a cached run and a cold run are not the same run.

Both belong to Phase 8 rather than to the map site, and both were found only because Phase 7 was the
first thing to run the whole pipeline end to end at this extent.

---

## 6. What was not built

Nothing from the deferred list, and no run-comparison views. The `--drop-densest-as-needed` choice
is deliberate and recorded per tileset, except on the click-detail tileset, where a dropped feature
is a unit whose sidebar silently comes up empty — there the right failure is a large tile, and the
flags are the opposite ones.
