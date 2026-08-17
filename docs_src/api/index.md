# API reference

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

All internal computation happens in a projected CRS obtained via `gdf.estimate_utm_crs()`.
Lat/lon appears only at ingestion and export boundaries, and the invariant is enforced by
[`lczkit.crs.assert_projected_crs`][lczkit.crs.assert_projected_crs] rather than by convention.

## The pipeline, in order

| Stage | Page | What it produces |
|---|---|---|
| Ingestion | [Sources](sources.md) | raw Overture layers, height products, land-cover rasters |
| Cleaning | [Cleaning](cleaning.md) | `buildings_topo` and `buildings_area`, a simplified network |
| Units | [Spatial units](units.md) | a partition of the bbox indexed by `unit_id` |
| Heights | [Height cascade](heights.md) | a height and a provenance tag per building |
| Land cover | [Land cover](landcover.md) | zonal fractions per `unit_id` |
| Parameters | [Urban canopy parameters](ucp.md) | the parameter table Phase 6 measures |
| Classification | [Classification](classify.md) | the full 17-way distance vector per unit |
| Validation | [Validation](validation.md) | agreement against labelled references |
| Output | [Output](output.md) | GeoParquet, GeoPackage, viz table, manifest |
| Map site | [Map site](viz.md) | a static MapLibre site over PMTiles |

[Pipeline](pipeline.md) is the chain itself, plus the presets and city registry the command line
resolves against. [Command line](cli.md) is the thin layer over it.

## Package

::: lczkit
