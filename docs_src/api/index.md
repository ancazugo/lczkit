# API reference

Terms are defined in the [glossary](../glossary.md) — *spatial unit*, *prototype distance*,
*height cascade*, *urban canopy parameter* and the rest.

## How to read this

`lczkit`'s top-level `__init__` carries only `__version__`. There is no curated re-export layer,
so **every symbol is reached by its module path** — `from lczkit.pipeline import run_pipeline`,
`from lczkit.classify import PrototypeClassifier`. This reference is organised the same way: by
module, under the stage of the pipeline it belongs to.

Two pages are the anchors:

- **[Protocols](protocols.md)** — the five `typing.Protocol` definitions that are the package's
  seams. Every implementation is structural, so a class implementing one of these does not
  subclass it; the contract is stated once, here.
- **[Configuration](config.md)** — the single pydantic model, serialised verbatim into every run
  manifest alongside the pinned Overture release, the resolved package versions and a timestamp.
  Reproducibility is a feature of this package rather than an afterthought.

## The unit of exchange

Every stage after unit generation is a join on `unit_id`. The thing passed between stages is a
`GeoDataFrame` indexed by a stable string `unit_id` — parameters, land-cover fractions,
classification, provenance and validation all key on it. There is deliberately no second
exchange format.

All internal computation happens in a **projected coordinate reference system** — one whose
coordinates are metres, so that areas and distances mean what they say — obtained via
`gdf.estimate_utm_crs()`. Longitude and latitude appear only when data is read and written, and the
rule is enforced by [`lczkit.crs.assert_projected_crs`][lczkit.crs.assert_projected_crs] rather than
left to convention.

## The pipeline, in order

| Stage | Page | What it does |
|---|---|---|
| Ingestion | [Sources](sources.md) | fetches the buildings, streets, water and land use from Overture, and the height and land-cover rasters |
| Cleaning | [Cleaning](cleaning.md) | repairs and simplifies them, producing two building layers — one valid for topology, one that preserves area |
| Units | [Spatial units](units.md) | cuts the study area into the polygons everything is measured on, keyed by `unit_id` |
| Heights | [Height cascade](heights.md) | gives every building a height, and records which source it came from |
| Land cover | [Land cover](landcover.md) | measures what share of each unit is paved, vegetated, tree or water |
| Parameters | [Urban canopy parameters](ucp.md) | measures the shape of the surface in each unit — the inputs to the classification |
| Classification | [Classification](classify.md) | scores each unit against all seventeen classes and reports the full distance vector |
| Validation | [Validation](validation.md) | compares the result to a reference label set, where one exists |
| Output | [Output](output.md) | writes the tables, the manifest and the reports |
| Map site | [Map site](viz.md) | builds a self-contained web map from what was written |

[Pipeline](pipeline.md) is the chain itself, plus the presets and city registry the command line
resolves against. [Command line](cli.md) is the thin layer over it.

## Package

::: lczkit
