# Cleaning

::: lczkit.cleaning
    options:
      members: []
      show_root_heading: false
      show_symbol_type_toc: false

Repairing and simplifying the raw Overture layers. Everything downstream depends on this, and the
building surface fraction it produces carries the largest single weight in the classification.

**Cleaning produces two building layers, not one.** This is the most important structural rule
in the package:

- **`buildings_topo`** — planar and non-overlapping, meaning no two footprints share any area. Feeds enclosure generation and anything
  needing a valid partition. Destructive operations are permitted.
- **`buildings_area`** — area-preserving. Feeds building surface fraction and **every area
  statistic**. Only validity fixes, multipolygon explosion, non-polygon removal,
  implausibly-large-footprint removal and genuine duplicate removal.

The split exists because building surface fraction carries roughly half the classification
metric. Cleaning a single layer for topology measured 23.5% of Berlin's footprint area away before
BSF was computed, which was worth 9.1 points of agreement. The cleaning report therefore records
total footprint **area** in and out of every operation, not just feature counts.

::: lczkit.cleaning.pipeline

## Buildings

::: lczkit.cleaning.buildings

## Streets

::: lczkit.cleaning.streets

## Tiling

Street simplification is superlinear in the size of the network, so a whole city does not finish
in usable time. This is how an extent is cut into tiles, simplified in parallel and stitched back.

::: lczkit.cleaning.tiles

## Geometry, topology, land use, reporting

::: lczkit.cleaning.geometry

::: lczkit.cleaning.topology

::: lczkit.cleaning.land_use

::: lczkit.cleaning.report
