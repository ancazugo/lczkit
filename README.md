# lczkit

Maps a city into [Local Climate Zones](https://doi.org/10.1175/BAMS-D-11-00019.1)
(Stewart & Oke 2012) from open vector and raster data — anywhere in the world, from data that is
already public.

It follows the conceptual approach of GeoClimate — partition into spatial units, compute urban
canopy parameters, classify by distance to LCZ prototypes — as an independent implementation with a
pluggable data layer: **Overture Maps** for vector data, **ESA WorldCover** for land cover, and a
tiered cascade of global products for building height. It is not a machine-learning model; nothing
here is trained, and the classification is the published prototype distance with the parameters
lczkit can actually measure.

**Building height completeness, and reporting it honestly, is a first-class output.** In much of
the world Overture carries footprints and no heights — 1% of building area in Cairo against 80% in
Berlin — and the height a run used therefore comes from a 90 m raster far more often than not.
Every run says so, per unit, in a column you can put on a map.

---

## Quick start

```sh
lczkit cities cambridge                  # find the extent, and what it will cost
lczkit run --city cambridge --country GBR
lczkit site serve <run_dir>              # then open the address it prints
```

`lczkit cities` searches 5 558 urban regions from NASA/JRC's GUPPD gazetteer and prints each one's
bounding box and area, because the area is the one number that predicts how long a run takes — the
median region is 80 km² and a few minutes, and the largest is 17 661 km². `lczkit run` covers the
region you name, writes `$DATA_DIR/output/lczkit/<run_id>/`, and builds a map site from it.

Three ways to name an extent, and they mean different ground:

| | what it covers | needs |
|---|---|---|
| `--bbox W,S,E,N` | exactly that window | nothing on disk |
| `--city NAME [--country ISO]` | that urban region | the GUPPD bounds table, 564 KB |
| `--city NAME --so2sat-window` | the densest 30 km window of that city's So2Sat labels | the So2Sat archive |

The third is the specialist one. It reproduces the extent every recorded agreement figure in this
project was measured over, works for 28 cities, and has to be asked for — a run that fell back to
it silently would look comparable with a published number while covering different ground. The run
manifest records which locator was used, along with the bbox and its area.

Useful flags: `--extent-km N` trims any extent to a concentric square, which is the first thing to
do with a new city; `--dry-run` resolves the whole configuration and writes nothing, including the
run directory; `--config FILE` overlays a JSON file on any settings section, and **a run manifest
works there**, so a run can be reproduced from its own output.

## What a run writes

```
output/lczkit/<run_id>/
├── units.parquet        # GeoParquet: geometry, the 17-way distance vector, every parameter
├── units.gpkg           # the same table, for a GIS whose GDAL lacks the Parquet driver
├── units_viz.parquet    # rounded, scaled, break-precomputed — what the site reads
├── manifest.json        # the full config, source versions, extent, CRS, and every report
├── layers/              # the cleaned streets, water, land use and buildings the run used
└── site/                # a self-contained MapLibre site, with its own serve.py
```

The classification is the **full 17-way distance vector**, not a label. `lcz_primary`,
`lcz_secondary` and `uniqueness` are conveniences on top of it, in the LCZ Generator's integer
codes and Demuzere's colour table, so results drop into existing tooling.

`manifest.json` is the point of the whole design: the serialised config, the pinned Overture
release, the resolved versions of `momepy`/`neatnet`/`geopandas`, the cleaning report with feature
counts **and footprint areas** in and out of every operation, the height-tier distribution, and the
extent and CRS. A run can be traced back to what produced it.

## What it will not tell you

Stated here rather than in a footnote, because two of these bound every number the package emits.

- **Sky view factor and roughness length are not computed.** SVF is the most expensive component
  and is strongly correlated with aspect ratio, which is computed. The active weight preset is
  named `bernard2024_partial` for this reason: it applies 17 of the published 21.5 weight units,
  and the manifest records which dimensions were dropped and how the rest were renormalised.
- **Building surface fraction carries roughly half the metric.** With three non-zero dimensions,
  `FB` dominates. Read it, and read `height_completeness` beside it.
- **Heights outside Europe and North America are mostly from 90–100 m rasters.** An areal product
  assigns a neighbourhood mean to individual buildings, which cannot separate low-rise from
  mid-rise inside a heterogeneous cell. `height_tier_fractions` distinguishes "90% real heights"
  from "90% coarse fallback"; they produce the same label with very different trustworthiness.
- **LCZ 10 cannot be separated from LCZ 8 on morphology**, and Overture exposes one `industrial`
  value with no heavy/light split. LCZ 10 is assigned functionally, at a threshold calibrated
  against a reference rather than picked, and the manifest records how often the rule fired.
- **A 100 m cell is not an LCZ patch.** Stewart & Oke's parameter ranges describe a patch of
  hundreds of metres, and on a grid the within-class spread is wider than the published bands can
  hold — one class of ten reaches its published BSF range. `units.strategy = "patch"` builds larger
  organic units if that matters for your use; the grid is the default because it is what every
  existing LCZ map, validation dataset and WRF workflow uses.

## On validating the output

The repository ships loaders for three LCZ references — So2Sat LCZ42, WUDAPT, and the Demuzere
global map — and they are **research instruments, not a quality gate you should run over your own
city.** Two reasons, both measured here:

- They do not cover most cities. So2Sat has 51; WUDAPT is wider but irregular and uneven.
- **They do not agree with each other.** Over 28 cities, two independent expert label sets agree at
  a median 79.7%, ranging from 26.3% (Cairo — *below* what a constant predictor scores there) to
  97.7%. Where two references disagree, no map can match both, and an agreement figure without that
  context is not interpretable.

Nothing in `lczkit run` touches any of them, and no threshold in the package is fitted to them.
Judge a run the way you would judge any map: look at it, read `height_completeness` and
`building_tag_coverage` beside the labels, and check the manifest for what the run could not
measure. If you do have labels for your city, `lczkit.validation` will score against them and
report per-class agreement and a confusion matrix rather than a single number — see
[`docs/status.md`](docs/status.md) for what that machinery is for and what it has found.

## Setup

This project runs on a shared HPC system. The Python environment lives outside the repo and
already exists — do not create a new one:

```sh
source /maps/acz25/envs/lczkit-env/bin/activate
uv add --active <package>       # the only way dependencies get added
```

Never run `uv sync`, `uv venv`, `pip install`, or `conda install` against this environment.

Point uv's and pip's caches away from the home directory quota (add to your shell profile, not
to this repo):

```sh
export UV_CACHE_DIR=/maps/acz25/.cache/uv
export XDG_CACHE_HOME=/maps/acz25/.cache
```

Copy `.env.example` to `.env` and set `DATA_DIR` to the shared data directory (see CLAUDE.md's
"Environment and paths" section for the expected `input/`/`output/` layout). `lczkit` only ever
reads from `input/` via source-specific subdirectories and writes under `output/lczkit/<run_id>/`.

The map site needs `tippecanoe`, installed by the `viz` extra. Without it a run still writes
everything else — the site is the last stage — and says so, naming `lczkit site build <run_dir>`
to finish it later.

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

Every stage is separately usable and every one of them is a join on `unit_id`:
`lczkit.cleaning`, `lczkit.heights`, `lczkit.units`, `lczkit.landcover`, `lczkit.ucp`,
`lczkit.classify`, `lczkit.output`, `lczkit.viz`. The five data-source seams are
`typing.Protocol`s in `lczkit.protocols`.

## Tests

```sh
pytest
```

Tests do not require `DATA_DIR` to be set and never touch the network — fixtures live under
`tests/fixtures/`.

**The primary fixture is a 3 km window over Kowloon, Hong Kong**, not Berlin. Berlin's labelled
cells hold two classes and both are mid-rise, so the height confusion axis has no pair to confuse
on and cannot be measured there at all. Hong Kong's window carries LCZ 1, 2, 3, 4 and 5. Berlin and
Rotterdam stay: every figure before Phase 11 is against Berlin, and Rotterdam is the industrial
fixture for the LCZ 10 rule. See [`tests/fixtures/README.md`](tests/fixtures/README.md).

Network-dependent tests are marked `@pytest.mark.network` and skipped by default:

```sh
pytest -m network
```

These hit live Overture and live Earth Engine. The Earth Engine ones additionally need
`GEE_PROJECT_NAME` and working credentials (`earthengine authenticate`); they skip rather than
fail when the project is unset, so a checkout without Earth Engine access can still run them.

## More

- **[`docs/status.md`](docs/status.md)** — what has been built, phase by phase, with the
  measurement behind each decision. This was the bulk of this README.
- **[`CLAUDE.md`](CLAUDE.md)** — the specification, the locked architectural decisions, and the
  table of resolved discrepancies. The authority for anything the two disagree about.
- **`docs/experiments/`** — the write-up behind each measured claim.
- **`docs/references/tables/`** — hand-checked transcriptions of the published parameter tables.
  A checkout without them cannot reproduce a classification.
- **API reference** — `mkdocs serve`, or the published site.

## Licence

MIT. See [`LICENSE`](LICENSE).

This package is an independent implementation from the published literature. It contains no code
derived from GeoClimate (LGPL-3.0) or UMEP (GPL-3.0), and every dependency is permissively
licensed. Data carries its own terms: Overture is ODbL/CDLA depending on theme, ESA WorldCover is
CC BY 4.0, and WUDAPT's polygons are CC BY-SA or CC BY-NC-SA per polygon — a run's record states
them from the data rather than asserting them.
