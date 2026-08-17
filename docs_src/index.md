# lczkit

Map a city into **Local Climate Zones** (Stewart & Oke 2012) from open vector and raster data.

`lczkit` follows the conceptual approach of GeoClimate — partition into spatial units, compute
urban canopy parameters, classify by distance to LCZ prototypes — as an independent MIT-licensed
implementation with a pluggable data layer: Overture Maps for vector, Google Earth Engine, STAC or
local rasters for land cover, and a tiered cascade for building heights.

The design bet is that **building height completeness, and the honest reporting of it, is the
binding constraint** on morphology-based LCZ classification outside Europe. Every run records
which tier answered for each building, and what fraction of a unit's building area that covers.

## Install

```bash
pip install lczkit
```

The map site is an optional extra, because it invokes `tippecanoe`:

```bash
pip install "lczkit[viz]"
```

`lczkit` reads its paths from a `DATA_DIR` environment variable, resolved once in
[`lczkit.config.Settings`][lczkit.config.Settings] and never read again from the environment.
Put it in a `.env` file at your project root.

## A run

```bash
lczkit run --city berlin --preset published
lczkit site build output/lczkit/<run_id>
lczkit site serve output/lczkit/<run_id>
```

Or from Python:

```python
from lczkit.config import Settings
from lczkit.pipeline import run_pipeline

settings = Settings.load()
result = run_pipeline(settings, bbox=(13.30, 52.45, 13.50, 52.55))
print(result.run_dir)
```

Every run writes a GeoParquet of classified units, a GeoPackage beside it for GIS readers whose
GDAL lacks the optional Parquet driver, a viz-ready attribute table, and a JSON manifest carrying
the full serialised config, the pinned Overture release, the resolved package versions and the
cleaning report.

## What this documentation covers

The [API reference](api/index.md) is generated from the source and is the reference for every
public class and function.

Two things live in the repository rather than here, deliberately:

- **The full README**, which carries the project's measured status across nineteen phases — per
  city agreement, ceilings, and what each of them does and does not license you to conclude.
- **The phase write-ups** in `docs/experiments/`, which are the experimental record: what was
  predicted, what was measured, and which hypotheses were refuted.

Both are on [GitHub](https://github.com/ancazugo/lczkit).

## Known omissions

**Sky view factor is not computed.** It is the most expensive component and is strongly
correlated with aspect ratio, which is computed. This is a documented omission, not an oversight —
see the deferred list in the repository.

**Overture exposes a single `industrial` value**, with no heavy/light split, so a light-industrial
estate and a refinery are indistinguishable to the LCZ 10 rule. This is a limit of Overture's
normalised schema and is recorded in every run's manifest.

## Licence and citation

MIT. The reference data carries its own terms: Overture is ODbL, and WUDAPT's training polygons
are CC BY-SA and CC BY-NC-SA 4.0 *per polygon* — non-commercial in the second case. A run's
manifest states those from the data rather than from a constant.
