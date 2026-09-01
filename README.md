# lczkit

Maps a city into **Local Climate Zones** from open data, anywhere in the world.

A [Local Climate Zone](https://doi.org/10.1175/BAMS-D-11-00019.1) (Stewart & Oke 2012) describes
the surface around a place — how much of the ground is building, how tall, how dense, how green —
using seventeen classes: ten built types numbered 1 to 10, and seven natural land-cover types
lettered A to G. The scheme exists so that temperature measurements from different cities can be
compared by the kind of surface they were taken over, rather than by the word "urban".

`lczkit` follows the approach of [GeoClimate](https://doi.org/10.5194/gmd-17-2077-2024), the
reference open-source implementation: cut the city into spatial units, measure the shape of the
surface in each one, and label each unit with the class whose published parameter ranges it sits
closest to. This is an **independent implementation from the published papers** — it contains no
GeoClimate code — with a pluggable data layer: **Overture Maps** for buildings, streets and water,
**ESA WorldCover** for land cover, and a tiered cascade of global products for building height.

It is **not a machine-learning model.** Nothing here is trained, and no threshold is fitted to a
label set.

**Building height completeness, and reporting it honestly, is a first-class output.** In much of
the world Overture carries building footprints and no heights — 1% of building area in Cairo
against 80% in Berlin — so the height a run used comes from a 90 m satellite radar raster far more
often than not. Every run says so, per unit, in a column you can put on a map.

Unfamiliar terms are defined in the **[glossary](docs_src/glossary.md)**.

---

## Install

```sh
pip install lczkit
pip install "lczkit[viz]"       # adds tippecanoe, which builds the map site
```

The map site is the only optional part. Without `tippecanoe` a run still writes everything else —
the site is the last stage — and says so, naming `lczkit site build <run_dir>` to finish it later.

`lczkit` reads every path from one environment variable. Copy `.env.example` to `.env` and set
`DATA_DIR` to a directory holding `input/` and `output/`:

```
DATA_DIR/
├── input/     # source data, one subdirectory per provider
└── output/    # lczkit writes only to output/lczkit/<run_id>/
```

`DATA_DIR` is resolved once, in `lczkit.config.Settings`, and read from the environment nowhere
else. A missing or unreachable `DATA_DIR` fails at config load rather than three stages in.
`lczkit` never modifies or deletes an existing file under `input/`.

<details>
<summary>Working on a shared cluster</summary>

The development environment lives outside the repository and already exists. Activate it rather
than creating one, and add dependencies with `uv add --active <package>` only — never `uv sync`,
`uv venv`, `pip install` or `conda install`. Point the tool caches away from a home-directory
quota, in your shell profile rather than in this repository:

```sh
export UV_CACHE_DIR=/path/to/scratch/.cache/uv
export XDG_CACHE_HOME=/path/to/scratch/.cache
```

</details>

## Quick start

```sh
lczkit cities cambridge                  # find the extent, and what it will cost
lczkit run --city cambridge --country GBR
lczkit site serve <run_dir>              # then open the address it prints
```

`lczkit cities` searches the Global Urban Polygons and Points Dataset (GUPPD), a gazetteer from
NASA's Socioeconomic Data and Applications Center and the European Commission's Joint Research
Centre. It covers 5 558 urban regions and prints each one's bounding box and area, because the
area is the one number that predicts how long a run takes — the median region is 80 km² and a few
minutes, and the largest is 17 661 km². `lczkit run` covers the region you name, writes
`$DATA_DIR/output/lczkit/<run_id>/`, and builds a map site from it.

Three ways to name an extent, and they mean different ground:

| | what it covers | needs |
|---|---|---|
| `--bbox W,S,E,N` | exactly that window, in longitude and latitude | nothing on disk |
| `--city NAME [--country ISO]` | that urban region; `ISO` is a three-letter country code | the GUPPD bounds table, 564 KB |
| `--city NAME --so2sat-window` | the densest 30 km window of that city's So2Sat labels | the So2Sat archive |

The third is the specialist one. So2Sat LCZ42 is a set of hand-drawn LCZ labels over 51 cities;
this flag reproduces the extent the published agreement figures were measured over, works for 28 of
them, and **has to be asked for** — a run that fell back to it silently would look comparable with a
published number while covering different ground. The run manifest records which locator was used,
along with the bounding box and its area.

Useful flags: `--extent-km N` trims any extent to a concentric square, which is the first thing to
do with a new city; `--dry-run` resolves the whole configuration and writes nothing, including the
run directory; `--config FILE` overlays a JSON file on any settings section, and **a run manifest
works there**, so a run can be reproduced from its own output.

## What a run fetches

Nothing has to be staged by hand. A run downloads what it needs and caches it under
`input/<provider>/`, where a cache hit is just a file that is already there — so the second city
in a region is faster than the first, and nothing existing is ever rewritten.

| what | from | size |
|---|---|---|
| Overture buildings, streets, water, land use | Overture's S3 bucket, at the pinned release | the extent |
| ESA WorldCover, for land cover | the ESA bucket, mosaicking whichever 3° tiles the extent spans | the extent |
| WSF-3D building height | one global GeoTIFF from DLR, read by window | 2.1 GB, once, ever |
| GHS-BUILT-H building height | the JRC tiles the extent covers | 1-40 MB per 1000 km tile |

Land cover can instead be reduced inside Google Earth Engine, with
`--land-cover-source gee`. The two backends return the same table — they disagree by about a
percent on a unit's boundary cells, because one weights each cell by the fraction the unit covers
and the other counts whole pixels by centre — so the choice is where the arithmetic happens, and
the run manifest records which one answered. It needs credentials and a billable project in
`GEE_PROJECT_NAME`; the default needs neither.

**The height products are not offered that way, and the reason is availability rather than
policy.** GHS-BUILT-H is in the Earth Engine catalogue and is byte-identical to the tiles fetched
above, so a second route to it would only add a credential requirement. WSF-3D is not in the
catalogue at all — Earth Engine publishes DLR's 2015 settlement mask, which is not a height
product — and it is the tier that answers for most building area outside Europe. Fine-resolution
Google Open Buildings 2.5D *is* Earth Engine-only, and is switched off by default because it was
measured to make the map worse.

## What a run writes

```
output/lczkit/<run_id>/
├── units.parquet        # geometry, the 17-way distance vector, every parameter
├── units.gpkg           # the same table as a GeoPackage, for software that cannot read Parquet
├── units_viz.parquet    # rounded, scaled, break-precomputed — what the map site reads
├── manifest.json        # the full config, source versions, extent, coordinate system, reports
├── layers/              # the cleaned streets, water, land use and buildings the run used
└── site/                # a self-contained web map, with its own serve.py
```

`units.parquet` is [GeoParquet](docs_src/glossary.md#outputs-and-tooling): a table with geometry
attached. `units.gpkg` holds the same rows as a GeoPackage, because GeoParquet support is an
optional component in GDAL and a geographic information system built without it opens a perfectly
valid file as a table with no location.

The classification is the **full 17-way distance vector**, not a label. `lcz_primary`,
`lcz_secondary` and `uniqueness` are conveniences on top of it, in the LCZ Generator's integer
codes and the standard colour table, so results drop into existing tooling. Alongside them,
`n_params_used` says how many parameters the unit was actually scored on, `n_tied_classes` flags a
unit where two classes were exactly equidistant so the label was arbitrary, and
`impervious_clipped` flags the one case where the surface shares do not sum to one.

`manifest.json` is the point of the whole design: the serialised configuration, the pinned Overture
release, the resolved versions of `momepy`/`neatnet`/`geopandas`, the cleaning report with feature
counts **and footprint areas** in and out of every operation, the height-tier distribution, the
extent and the coordinate system. A run can be traced back to what produced it.

## What it will not tell you

Stated here rather than in a footnote, because several of these bound every number the package
emits.

- **Sky view factor and roughness length are not computed.** Sky view factor — the share of sky
  visible from street level — is the most expensive parameter and is strongly correlated with
  aspect ratio, which is computed. Roughness length describes how much the surface slows the wind.
  The active weight preset is named `bernard2024_partial` for this reason: it applies 17 of the
  published 21.5 weight units, and the manifest records which dimensions were dropped and how the
  rest were renormalised. This is a gap in what `lczkit` builds, not in the data it has:
  [GeoClimate](https://doi.org/10.5194/gmd-17-2077-2024) computes sky view factor from vector
  building footprints alone — buildings as the only obstacles, no elevation model (Table 1) — so a
  comparison table showing it there and not here is reporting a real difference.
- **Building surface fraction carries roughly half the classification.** With only three
  weighted parameters left, the share of ground covered by building dominates. Read it, and read
  `height_completeness` beside it.
- **Heights outside Europe and North America are mostly from 90–100 m rasters.** Such a product
  assigns a neighbourhood average to individual buildings, which cannot separate low-rise from
  mid-rise inside a mixed cell. `height_tier_fractions` distinguishes "90% measured heights" from
  "90% coarse fallback"; they produce the same label with very different trustworthiness. The
  manifest also reports how much within-unit height variation each source preserved, because a
  raster that gives every building in a cell the same height has resolved nothing inside it.
- **Class 10 (heavy industry) cannot be separated from class 8 (large low-rise) on shape**, and
  Overture exposes one `industrial` value with no heavy/light split. Class 10 is assigned
  functionally, at a threshold calibrated against a reference rather than picked, and the manifest
  records how often the rule fired.
- **Classes 7 and 8 come out inverted on building size in the distance metric.** Class 8 is *large*
  low-rise — warehouses and malls — and class 7 is *lightweight* low-rise, the informal-settlement
  class. Across the four cities checked, the units the metric alone labels 8 hold buildings of
  55–93 m² and those labelled 7 hold buildings of 7 000–13 000 m². `mean_building_area_m2` is
  present as a parameter and carries **zero weight** until its weight has been calibrated. Class 8
  has a second route around this by default: a unit over 70% tagged warehouse/hangar/retail-shed
  building area is labelled class 8 on that evidence, a threshold swept against hand-drawn labels
  in eight cities where it improved every measure in all eight. Class 7 has no equivalent — Overture
  has no slum/shanty/ger/tent vocabulary, the cities carrying the tags it does have are not the
  cities with informal settlement, and the same sweep was refused there. Read `building_tag_coverage`
  beside a class 7 share of zero: it may mean no informal settlement, or it may mean nobody tagged
  the buildings.
- **A 100 m cell is not an LCZ patch.** Stewart & Oke's parameter ranges describe a patch of
  hundreds of metres, and on a grid the within-class spread is wider than the published ranges can
  hold — one class of ten reaches its published building-surface-fraction range.
  `units.strategy = "patch"` builds larger organic units if that matters for your use; the grid is
  the default because it is what every existing LCZ map, reference label set and weather-model
  workflow uses.
- **The output is not yet a complete weather-model input.** The Weather Research and Forecasting
  model is the main downstream use for an LCZ map, and the tool that feeds it expects a raster.
  `lczkit` writes vector formats only, and does not compute roughness length or displacement
  height.

Two options exist and are **off by default**, because their thresholds have not been calibrated:
`ucp.measure_on = "enclosures"` measures street-canyon geometry on street-bounded blocks and
transfers it to the units being classified, and `classification.modal_filter` replaces an isolated
unit's label with the one its neighbours carry. Both change labels, so a run with either one on is
not comparable with a run at the defaults.

## On validating the output

The package ships loaders for three LCZ references — So2Sat LCZ42, WUDAPT, and the Demuzere global
map. They are **research instruments, not a quality gate to run over your own city**, for two
reasons:

- They do not cover most cities. So2Sat has 51. WUDAPT — the World Urban Database and Access
  Portal Tools, a community effort whose training areas are polygons drawn by contributors
  worldwide — is wider but irregular and uneven.
- **They do not agree with each other.** Over 28 cities, two independent expert label sets agree at
  a median 79.7%, ranging from 26.3% (Cairo — *below* what a constant predictor scores there) to
  97.7%. Where two references disagree, no map can match both, and an agreement figure without that
  context is not interpretable.

Nothing in `lczkit run` touches any of them, and no threshold in the package is fitted to them.
Judge a run the way you would judge any map: look at it, read `height_completeness` and
`building_tag_coverage` beside the labels, and check the manifest for what the run could not
measure. If you do have labels for your city, `lczkit.validation` will score against them and report
per-class agreement and a confusion matrix rather than a single number.

## Library use

The command line is not privileged; everything it does is a call any caller can make.

```python
from lczkit.config import Settings
from lczkit.pipeline import run_pipeline
from lczkit.presets import apply_preset

settings = apply_preset(Settings.load())
result = run_pipeline(settings, (0.081, 52.172, 0.190, 52.250))
print(result.run_dir, result.seconds)
```

`Settings.load()` deliberately cannot produce a runnable configuration on its own —
`CleaningConfig` and `HeightConfig` default their measured thresholds to `None` and raise at call
time, so an invented default cannot travel into a manifest looking like a measurement.
`apply_preset` is what fills them.

Every stage is separately usable and every one of them is a join on `unit_id`, the spatial unit's
identifier: `lczkit.cleaning`, `lczkit.heights`, `lczkit.units`, `lczkit.landcover`, `lczkit.ucp`,
`lczkit.classify`, `lczkit.output`, `lczkit.viz`. The five data-source seams are
`typing.Protocol`s in `lczkit.protocols`.

## Tests

```sh
pytest
```

Tests do not require `DATA_DIR` to be set and never touch the network — fixtures live under
`tests/fixtures/`.

**The primary fixture is a 3 km window over Kowloon, Hong Kong.** Berlin's labelled cells hold two
classes and both are mid-rise, so the height confusion axis — the pattern of errors that
distinguishes low-rise from mid-rise from high-rise — has no pair to confuse on and cannot be
measured there at all. Hong Kong's window carries classes 1, 2, 3, 4 and 5. Berlin and Rotterdam
are kept as secondary fixtures; Rotterdam is the industrial one, for the class 10 rule. See
[`tests/fixtures/README.md`](tests/fixtures/README.md).

Network-dependent tests are marked `@pytest.mark.network` and skipped by default:

```sh
pytest -m network
```

These hit live Overture and live Google Earth Engine. The Earth Engine ones additionally need
`GEE_PROJECT_NAME` and working credentials (`earthengine authenticate`); they skip rather than
fail when the project is unset, so a checkout without Earth Engine access can still run them.

## More

- **[Documentation](https://ancazugo.github.io/lczkit/)** — the API reference, the glossary and a
  worked example. Build it locally with `mkdocs serve`.
- **[`docs_src/glossary.md`](docs_src/glossary.md)** — every term and abbreviation, defined.
- **`docs/references/tables/`** — hand-checked transcriptions of the published parameter tables.
  A checkout without them cannot reproduce a classification.
- **[`tests/fixtures/README.md`](tests/fixtures/README.md)** — what each test fixture is and where
  it came from.

## Licence

MIT. See [`LICENSE`](LICENSE).

This package is an independent implementation from the published literature. It contains no code
derived from GeoClimate (LGPL-3.0) or UMEP (GPL-3.0), and every dependency is permissively
licensed. Data carries its own terms: Overture is ODbL or CDLA depending on the theme, ESA
WorldCover is CC BY 4.0, and WUDAPT's polygons are CC BY-SA or CC BY-NC-SA per polygon — the last
being non-commercial. A run's record states them from the data rather than asserting them.
