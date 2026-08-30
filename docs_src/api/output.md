# Output

::: lczkit.output
    options:
      members: []
      show_root_heading: false
      show_symbol_type_toc: false

A run directory is written to `output/lczkit/<run_id>/` and contains:

| Artefact | What it is |
|---|---|
| `units.parquet` | the archival table with geometry attached, in the run's projected coordinate system |
| `units.gpkg` | the same table as a GeoPackage, written **beside** it and never instead |
| `units_viz.parquet` | the display-ready attribute table the map site reads |
| `manifest.json` | the full serialised config, source versions and every report |

!!! note "Why both Parquet and GeoPackage"

    Every run's GeoParquet is valid 1.0.0 and carries the extent's coordinate reference system with
    an EPSG authority code. But the Parquet driver in GDAL — the format layer under most geographic
    software — is an **optional build component**, so a copy of QGIS built without it opens a
    correct file as a plain table and reports "this layer has no CRS". GeoPackage is SQLite and is
    in GDAL's core, so it opens everywhere.

The manifest also carries `crs` and `crs_wkt`. The CRS is *derived* from the extent via
`estimate_utm_crs()`, so it appears in no config and no argument — without these two fields a run
directory could state its own CRS only through the file format the reader who needs telling cannot
open.

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

What ground a run covered, and how that ground was chosen. Derived rather than configured: the
extent is an argument to `run_pipeline` and reaches no `Settings` field, so it needs a manifest slot
of its own, as the run CRS does.

::: lczkit.output.extent
