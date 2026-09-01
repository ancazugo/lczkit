# lczkit

Map a city into **Local Climate Zones** from open data, anywhere in the world.

A [Local Climate Zone](https://doi.org/10.1175/BAMS-D-11-00019.1) (Stewart & Oke 2012) describes
the surface around a place — how much of the ground is building, how tall, how dense, how green —
using seventeen classes: ten built types numbered 1 to 10, and seven natural land-cover types
lettered A to G. The scheme exists so that temperature measurements from different cities can be
compared by the kind of surface they were taken over, rather than by the word "urban".

`lczkit` follows the approach of [GeoClimate](https://doi.org/10.5194/gmd-17-2077-2024): cut the
city into spatial units, measure the shape of the surface in each one, and label each unit with the
class whose published parameter ranges it sits closest to. It is an **independent, MIT-licensed
implementation from the published papers**, with a pluggable data layer — Overture Maps for vector
data, Google Earth Engine, a SpatioTemporal Asset Catalog or local files for land-cover rasters,
and a tiered cascade of global products for building heights. Nothing here is trained.

**Building height completeness is the limit on this kind of classification, and reporting it is
part of the output.** Every run records which source answered for each building, and what share of
a unit's building area that source covers.

New to the vocabulary? The **[glossary](glossary.md)** defines every term and abbreviation used
here — spatial unit, prototype distance, height cascade, ceiling, and the rest.

## Install

```bash
pip install lczkit
```

The map site is an optional extra, because it invokes `tippecanoe`, a tile-building command-line
tool:

```bash
pip install "lczkit[viz]"
```

`lczkit` reads its paths from a `DATA_DIR` environment variable, resolved once in
[`lczkit.config.Settings`][lczkit.config.Settings] and never read again from the environment.
Put it in a `.env` file at your project root.

## A run

```bash
lczkit cities cambridge                    # 5 558 urban regions, with each one's area
lczkit run --city cambridge --country GBR
lczkit site serve output/lczkit/<run_id>
```

`lczkit cities` searches a gazetteer of urban regions and prints each one's bounding box and its
area in km², which is the one number that predicts how long a run takes — the median urban region
is 80 km² and a few minutes, and the largest is 17 661 km². `--extent-km N` trims any extent to a
concentric square.

Or from Python:

```python
from lczkit.config import Settings
from lczkit.pipeline import run_pipeline

settings = Settings.load()
result = run_pipeline(settings, bbox=(13.30, 52.45, 13.50, 52.55))
print(result.run_dir)
```

Every run writes a [GeoParquet](glossary.md#outputs-and-tooling) file of classified units — a table
with geometry attached — and a GeoPackage beside it, because GeoParquet support is optional in
GDAL, the format layer under most geographic software, and a program built without it opens a valid
file as a table with no location. Alongside those: a display-ready attribute table for the map
site, and a JSON manifest carrying the full serialised configuration, the pinned Overture release,
the resolved package versions and the cleaning report.

## What this documentation covers

The [demonstration](demo/bogota.ipynb) runs the whole pipeline over a window of Bogotá, twice —
once on the 100 m grid and once on organic patch units — and embeds the map site each run produced.
Bogotá shows the limit this package exists to report: **0.50%** of its building heights come from
Overture, and a 90 m satellite radar mosaic answers for the rest.

The [API reference](api/index.md) is generated from the source and documents every public class and
function.

## Known omissions

**Sky view factor is not computed.** That is the share of sky visible from street level, and it is
the most expensive parameter to derive. It is also strongly correlated with aspect ratio — building
height over street width — which *is* computed. A documented omission rather than an oversight; the
run manifest records which parameters were unavailable and how the remaining weights were
renormalised. It is a gap in what `lczkit` builds and not in the data it has —
[GeoClimate](https://doi.org/10.5194/gmd-17-2077-2024) derives it from vector building footprints
alone, with buildings the only obstacles and no elevation model (Table 1).

**Roughness length and displacement height are not computed either**, which is why a run's output
is not yet a complete input to a weather model.

**Overture exposes a single `industrial` value**, with no heavy/light split, so a light-industrial
estate and a refinery are indistinguishable to the rule that assigns class 10, heavy industry. This
is a limit of Overture's normalised schema and is recorded in every run's manifest.

**Classes 7 and 8 come out inverted on building size.** Class 8 is *large* low-rise and class 7 is
*lightweight* low-rise, the informal-settlement class. Neither one's published parameter ranges
mention building size, so nothing in the classification separates them on it — and across the four
cities checked, the units labelled 8 hold the *smaller* buildings, by a factor of 17 to 100. Treat
both labels with suspicion. `mean_building_area_m2` is computed and carries zero weight until its
weight has been calibrated.

**Two options ship switched off**, because their thresholds have not been calibrated against a
reference and this package does not pick thresholds. `ucp.measure_on = "enclosures"` measures
street-canyon geometry on street-bounded blocks, where a canyon can actually be measured, and
transfers it to the units being classified. `classification.modal_filter` replaces an isolated
unit's label with the one its neighbours carry, which is standard practice in this literature.
Both change labels, so a run with either one on is not comparable with a run at the defaults.

## Licence and citation

MIT. The reference data carries its own terms: Overture is ODbL, and the training polygons of
WUDAPT — the World Urban Database and Access Portal Tools — are CC BY-SA and CC BY-NC-SA 4.0 *per
polygon*, non-commercial in the second case. A run's manifest states those from the data it read
rather than from a constant.
