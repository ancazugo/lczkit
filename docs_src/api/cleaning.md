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
metric. A single layer cleaned for topology measured 23.5% of Berlin's footprint area away
before BSF was computed — worth 9.1 points of agreement, and invisible for four phases because
the cleaning report tracked feature counts and not area.

::: lczkit.cleaning.pipeline

## Buildings

::: lczkit.cleaning.buildings

## Streets

::: lczkit.cleaning.streets

## Tiling

Street simplification is superlinear, which was existential at metropolitan scale and invisible
for seven phases because the test fixture is 9 km². This is how a whole extent is cut into
tiles, simplified in parallel and stitched back.

::: lczkit.cleaning.tiles

## Geometry, topology, land use, reporting

::: lczkit.cleaning.geometry

::: lczkit.cleaning.topology

::: lczkit.cleaning.land_use

::: lczkit.cleaning.report
