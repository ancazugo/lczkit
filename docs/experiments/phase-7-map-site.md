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

## 5. Two Phase 8 numbers this run appeared to contradict — and what more data did to them

The first end-to-end metropolitan run through `write_run` produced two figures that did not match
Phase 8's. Both were written down before being explained. The 891 km² threshold A/B finished
afterwards and, between its two arms, supplied three more measurements of the same quantities — which
shrank one to nothing and the other by a factor of forty. Recording the sequence is the point: the
first reading of a discrepancy is not usually the right one.

**`clean_vectors` at 4 469.1 s against Phase 8's 585.6 s — an outlier, not a regression.** The street
step reported `"cached": true` and the identical pooled threshold, so simplification was nearly free
and the run was still 7.6× slower. Two independent cold runs of the same cleaning over the same
891 km² then came in at **456 s** and **551 s**, bracketing the 585.6 s benchmark. Nothing is wrong
with the code. The site build overlapped with the peak of a 10-hour single-core whole-network
`fix_topology` job on a node also carrying several other users' work, and that is the most likely
cause — but it is a coincidence in time, not a measurement, and it is recorded as such.

**The feature count differs by 0.04%, not 1.7%.** `simplify_streets_tiled` reported `n_out = 198 879`
against the Phase 8 run's `195 508`, which looked like a 1.7% gap from an identical cache. It is not
the right comparison: the Phase 8 run predates the road-rule and pooled-threshold work in the same
phase. The three post-fix runs at this extent report **198 698** (whole-threshold arm, cold),
**198 804** (pooled arm, cold) and **198 879** (this run, pooled, cached). The first two differ
because their thresholds differ, which is expected. The last two share a threshold and differ by
**75 features in 198 804 — 0.04%** — one cached, one cold.

That residual is small and it is still a residual: a cached run and a cold run are not producing
byte-identical linework. `_stitch` concatenates the per-tile parts and runs
`neatnet.remove_interstitial_nodes` over the result, and a cache read need not return tiles in the
order a cold run computed them, so ordering is the first thing to check. Not chased here — it
belongs to Phase 8, and it was only visible because Phase 7 was the first thing to run the whole
pipeline end to end at this extent.

---

## 6. What was not built

Nothing from the deferred list, and no run-comparison views. The `--drop-densest-as-needed` choice
is deliberate and recorded per tileset, except on the click-detail tileset, where a dropped feature
is a unit whose sidebar silently comes up empty — there the right failure is a large tile, and the
flags are the opposite ones.

*(§5's cached-versus-cold residual was closed in Phase 9 at `040be15`. Both halves of the diagnosis
above are wrong: the two runs shared no cache, and `pool.map` preserves job order. The real cause was
`OvertureSource._fetch` scanning remote parquet with no `ORDER BY`.)*

---

## 7. Completion — the site was built here, and finished four days later

Everything above shipped in `6ebaca2` on 2026-08-09, **during Phase 8**. The phase was never
recorded as concluded, so CLAUDE.md went on calling Phase 7 "the only outstanding deliverable" for
fourteen commits, and the three user rulings in §1 lived only in this file. That is the process
finding: **a phase is not concluded until the spec says so**, and a deliverable built out of order is
the easiest kind to leave half-finished, because the code exists and looks done.

Three things were genuinely missing.

### 7.1 The selector order was inherited, not chosen

`build_views` emitted views in whatever order the manifest's `breaks` arrived in, which is
`writer.py`'s `continuous` — every numeric column in DataFrame order. Only `lcz` was placed
deliberately. On the built Berlin site that produced:

```
0 lcz · 1–10 the UCP choropleths · 11 uniqueness · 12 height_completeness
```

CLAUDE.md names exactly one position in the selector, and this is the one it names: height
provenance is a first-class layer and sits **second**, above the UCP choropleths. It was last of
thirteen.

Now ranked by `style.selector_rank`: LCZ, height provenance, the UCPs, `uniqueness`. Ties keep the
manifest's order, so a parameter added later lands among the UCPs without an edit. Five tests cover
it, including one asserting the order does not move when the breaks are reversed — the defect was
precisely that it did.

### 7.2 The tier fractions were not layers at all

`height_tier_fractions` reached the sidebar through `height_prefixes` and had **no menu entry**,
because a selectable layer has to be in the render set and `render_columns` is a static list while
the columns are named after whichever cascade fired — `height_frac_wsf3d`, `height_frac_ghsl`,
`height_frac_unresolved`, and the two Overture tiers. Naming them would have meant naming a cascade.

`VizConfig.render_column_prefixes` carries the family instead. They belong at every zoom rather than
in the click-detail tileset because a view change must paint from tiles already in memory; putting
them in the detail tileset would have made switching to one a refetch.

**Measured, because attributes at every zoom are the site's dominant cost.** On the 172 181-unit
Berlin extent, three tier-fraction columns took `units.pmtiles` from **28.09 MB to 30.20 MB —
+2.12 MB, +7.5%, about 0.71 MB per column.** Worth paying for a layer the spec makes first-class,
and small next to the 22% the render/detail split saves.

A tier fraction that is constant across a run still earns no view: `build_views` skips a column with
fewer than two break boundaries, so a layer that could only paint one colour does not appear.

### 7.3 Three cities published, and the third one found a bug

CLAUDE.md asks for at least two sites, one high-coverage and one low tier-1. Three were published,
chosen on measured coverage rather than reputation:

| city | run | built cells | site | wall |
|---|---|---:|---:|---:|
| Berlin | `20260814T094116Z-berlin` | 59 152 | 36.12 MB | 12.8 min |
| Hong Kong | `20260814T101702Z-hong_kong` | 25 233 | 20.43 MB | 12.7 min |
| Cairo | `20260814T101702Z-cairo` | 56 456 | 27.20 MB | 9.9 min |

Buildings off, per the measured default. Each is ~91 000 grid cells over its So2Sat window — the
same extent every validation sweep since Phase 9 has used, so a site is comparable with the
agreement figures already recorded for that city.

**Height provenance across the three, over cells containing buildings:**

| city | tier-1 | WSF-3D | GHS-BUILT-H | unresolved |
|---|---:|---:|---:|---:|
| Berlin | **0.797** | 0.191 | 0.008 | 0.003 |
| Hong Kong | 0.308 | 0.547 | 0.120 | 0.026 |
| Cairo | **0.010** | 0.835 | 0.122 | 0.032 |

Berlin's 0.797 reproduces Phase 10's ~80% and Cairo's 0.010 its 1%. **83.5% of Cairo's building area
takes its height from a 90 m TanDEM-X raster**, and that is now a layer a reader can select rather
than a number in a table. This is the comparison the site exists to carry.

**Publishing a second city found a real defect.** `run_and_publish` clipped ESA WorldCover from a
single hardcoded tile inherited from `berlin_wide_validation` — `N51E012`. Berlin's window needs
exactly that one tile; Hong Kong's spans two and Cairo's spans two, so both raised
`RasterioIOError: Attempt to create 0x0 dataset`. `clip_worldcover` already existed and resolves and
mosaics whichever tiles a bbox spans; the driver simply was not using it.

Its docstring had predicted the failure — *"a single-tile guess would fail as a band of nodata down
one side of the map rather than as an error"* — and the outcome here was the better one, an error
rather than a silent band, only because Berlin's tile does not touch either city at all. A city one
tile-width away would have published a map with a quarter of its land cover missing and no
complaint. **The bug was reachable the moment the driver left Berlin, and nothing but publishing a
second city would have found it.**

Berlin's site is unaffected: `worldcover_tiles` resolves its window to `N51E012`, the same raster the
hardcoded URL named.

### 7.4 The default view had never rendered

Reported on first opening a published site: the LCZ map was blank squares. It was not a regression
from §7.1 or §7.2 — **the site's default layer had painted every cell as no-data since `6ebaca2`.**

Diagnosed by decoding the tiles rather than reading the code. In one feature:

```
"unit_id": "grid_3794_58044"
"lcz_primary": "12"          <- string
"uniqueness": 1              <- number
"tree_fraction": 0.224       <- number
```

`tippecanoe-decode` does not quote numbers, so `lcz_primary` genuinely *is* a string in the MVT. The
GeoParquet has it as `Int8` and `pyogrio` writes it to FlatGeobuf as `int16`, both correct, so the
conversion had to be tippecanoe's. Isolated on a three-feature probe:

| written to FlatGeobuf | int16 | int32 | int64 | uint8 | float64 |
|---|---|---|---|---|---|
| read back from the MVT | `"1"` | `"1"` | `"1"` | `"1"` | `1` |

**tippecanoe's FlatGeobuf reader stringifies every integer attribute, at every width.** The paint
expression is `["match", ["get", "lcz_primary"], 1, "#8c0000", …]`, matching integer labels; a string
matches none of them, so every cell took `NODATA_COLOUR` — `#3a3a3a`, a uniform dark grey.
`lcz_primary` is the only integer column the site renders, which is why the fourteen float-valued
choropleths were fine and nothing looked broken.

Fixed by coercing in the expression: `["match", ["to-number", ["get", column]], …]`. Coercing there
rather than casting the column to float in `write_flatgeobuf` keeps a class code an integer
everywhere it is read, and confines the fix to the one place that depends on the tiler's type
handling. A missing value coerces to 0, matches no label, and still takes `NODATA_COLOUR`.

**Why thirty-seven tests missed it, which is the more useful finding.** `test_viz_style.py` asserted
the expression carries exactly `classify.labels.legend()`. `test_viz_site.py` asserted every tileset
is a valid PMTiles archive. Both passed, both were correct, and **neither asserted that the type in
the tiles is a type the expression can match** — the producer and the consumer were each tested
against their own assumption, and the defect lived in the gap between them.

The closing test decodes the built `units.pmtiles`, collects the `lcz_primary` values as they appear
in the MVT, and evaluates the real paint expression against them through the same coercion MapLibre
would apply. It fails 6 of 6 values without the fix. All three published sites were rebuilt: 15
classes painting real Demuzere colours each, zero no-data.

### 7.5 What the acceptance criteria now read against

| criterion | result |
|---|---|
| opens with no network, no install | `serve.py`, standard library only; verified 206 + byte-exact `Content-Range` against a real 28 MB tileset |
| layer switching does not refetch | every view paints `units-fill` via `setPaintProperty`; all 19 render columns ride in `units.pmtiles` |
| portable to static hosting unchanged | relative sources only; asserted by test |
| height provenance first-class | positions 1–6 of 18 in all three published sites |
| at least two cities | three |

`file://` is not among them, and cannot be — see §1.2.
