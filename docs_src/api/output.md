# Output

::: lczkit.output
    options:
      members: []
      show_root_heading: false
      show_symbol_type_toc: false

A run directory is written to `output/lczkit/<run_id>/` and contains:

| Artefact | What it is |
|---|---|
| `units.parquet` | the archival GeoParquet, in the run's projected CRS |
| `units.gpkg` | the same table in GeoPackage, written **beside** it and never instead |
| `units_viz.parquet` | the viz-ready attribute table the map site reads |
| `manifest.json` | the full serialised config, source versions and cleaning report |

!!! note "Why both Parquet and GeoPackage"

    Every run's GeoParquet is valid 1.0.0 carrying the extent's UTM CRS as PROJJSON with an EPSG
    authority code. But GDAL's Parquet driver is an **optional build component**, so a QGIS built
    without it opens a correct file as a non-spatial table and reports "this layer has no CRS" —
    naming the producer for a gap in the reader. GeoPackage is SQLite and is in GDAL's core.
    A correct file is not a readable file, and correctness is not what the recipient measures.

The manifest also carries `crs` and `crs_wkt`. The CRS is *derived* from the extent via
`estimate_utm_crs()`, so it is in no config and no argument — which left a run directory unable to
state its own CRS except through the one format the complaining reader could not open. Anything
computed at runtime that a consumer must know is a manifest field.

::: lczkit.output.writer

## Manifest

::: lczkit.output.manifest

## GIS export

::: lczkit.output.gis

## Classification breaks

Precomputed here and written into the manifest, so the map site is a pure transform of run
outputs. The site build must never recompute a parameter or a quantile.

::: lczkit.output.breaks

## Extent

What ground a run covered, and how that ground was chosen. Derived rather than configured — the
extent is an argument to `run_pipeline`, so it reaches no `Settings` field — which is why it needs
a manifest slot of its own, exactly as the run CRS does.

::: lczkit.output.extent
