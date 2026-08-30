# Glossary

Every term and abbreviation this documentation uses, in one place. Pages expand an abbreviation on
first use as well, so you should not have to come here to read a sentence — this is for depth, and
for the terms that carry more than a sentence's worth of meaning.

## The classification scheme

**Local Climate Zone (LCZ)**
:   Stewart & Oke (2012) define these as *"regions of uniform surface cover, structure, material,
    and human activity that span hundreds of meters to several kilometers in horizontal scale"*.
    The scheme was built so that urban heat island measurements taken in different cities could be
    compared: instead of "urban" and "rural", a site is described by the kind of surface around it.

**The seventeen classes**
:   Ten **built** types, numbered 1 to 10, and seven **natural** land-cover types, lettered A to G.
    The built numbering is a grid of two ideas. *Compactness* — how much of the ground is
    building — separates compact (1, 2, 3) from open (4, 5, 6) from sparse (9). *Height* separates
    high-rise (1, 4) from midrise (2, 5) from low-rise (3, 6). The remaining three are named for
    what they are: **7 lightweight low-rise** (small, densely packed, often informal settlement),
    **8 large low-rise** (warehouses, malls, hangars), **10 heavy industry**. The natural types run
    A dense trees, B scattered trees, C bush or scrub, D low plants, E bare rock or paved, F bare
    soil or sand, G water.

**Patch**
:   The area an LCZ label is meant to describe: uniform, and hundreds of metres across. This
    matters because `lczkit` classifies 100 m cells by default, which are smaller than a patch —
    see *grid* below, and the note in [Known omissions](index.md#known-omissions).

**Prototype distance**
:   How `lczkit` assigns a class. Stewart & Oke publish, for each of the seventeen classes, the
    range each surface property is expected to fall in. A class is therefore a box in parameter
    space and a spatial unit is a point; the distance is the gap from the point to the box, zero
    inside it, and the class with the smallest distance wins. This is the approach GeoClimate
    takes, implemented independently here. Nothing is trained.

**Uniqueness**
:   How clearly the nearest class won, on a scale of 0 to 1. Zero means the two nearest classes
    were equidistant and the label is a coin toss; one means nothing rivalled it. It is a statement
    about the metric, not about the data — a unit can sit squarely inside its class and still be
    ambiguous, or far from every class and still be unambiguously nearest one.

## Surface parameters

**Urban canopy parameter (UCP)**
:   A number describing the shape of the urban surface in one spatial unit — how much of it is
    building, how tall the buildings are, how deep the street canyons are. These are the inputs the
    classification runs on, and the ones below are the ones `lczkit` computes.

**Building surface fraction (BSF)**
:   The share of a unit's ground covered by building footprint. It carries the largest single
    weight in the classification, so read it first.

**Height of roughness elements (`Hr`)**
:   The typical height of whatever sticks up into the wind — buildings, in a built zone. `lczkit`
    reports the **geometric** mean of building heights, which is what Stewart & Oke's published
    ranges were defined for. The geometric mean sits below the ordinary arithmetic mean whenever a
    unit mixes tall and short buildings, so the two are not interchangeable.

**Aspect ratio (H/W)**
:   Building height divided by street width — how deep and narrow the street canyons are. A high
    ratio means a canyon that traps heat and shades itself. `lczkit` measures it against the street
    network, so it has no value where no street reaches a building.

**Impervious and pervious surface fraction**
:   The shares of ground that water cannot and can soak through — paving against vegetation and
    bare soil. With building surface fraction they partition the surface: the three sum to one.

**Sky view factor (SVF)**
:   The share of the sky visible from street level, between zero (fully enclosed) and one (open
    ground). **`lczkit` does not compute it** — it is the most expensive parameter and is strongly
    correlated with aspect ratio, which is computed.

**Plan area index (λp) and frontal area index (λf)**
:   The share of ground covered by building, and the building wall area facing the wind per unit of
    ground. They are the standard inputs to roughness calculations. `lczkit` computes λp — it is
    building surface fraction — and does not compute λf.

**Roughness length (z₀) and displacement height (z_d)**
:   How much a surface slows the wind, and how far above the ground the wind profile effectively
    starts. Weather models need both. **`lczkit` computes neither**, which is why its output is not
    yet a complete input to a weather model.

## Spatial units

**Spatial unit**
:   The polygon everything is measured on and a class is assigned to. Every stage of the pipeline
    joins on its identifier, `unit_id`, and every choice below is a different way of cutting the
    study area into them.

**Partition**
:   The units must tile the study area exactly: no gaps, no overlaps. This is asserted rather than
    assumed, because units that overlap or spill outside the area silently corrupt the denominator
    of every share the package computes.

**Bounding box (bbox)**
:   The rectangle a run covers, given as west, south, east and north in longitude and latitude.

**Grid, enclosure and patch**
:   The three ways `lczkit` can cut units, differing mostly in size:

    | | median unit | what it is |
    |---|---:|---|
    | enclosure | 0.04 ha | a city block, bounded by streets |
    | grid, 100 m | 1.00 ha | a regular square cell — the default |
    | patch | 11.69 ha | blocks merged until they reach an area floor |
    | a WUDAPT polygon | 2.2–52 ha | for comparison: what a human draws |
    | a So2Sat patch | 10.24 ha | for comparison |

    The grid is the default because it is what published LCZ maps, the reference label sets and
    weather-model workflows all use. An enclosure is a *block*, which is smaller than an LCZ patch;
    patch units are built to land at patch scale.

## Data sources

**Overture Maps**
:   The open map data this package reads for buildings, streets, water and land use. It merges
    several sources — OpenStreetMap, Esri, Google Open Buildings, Microsoft's machine-learning
    footprints — **winner-takes-all per feature**: a building's attributes come from whichever
    source won its geometry, and are never blended. That is why a well-mapped city can still have
    almost no building heights: if a machine-learning source won the footprints, it supplied
    geometry and no attributes.

**OpenStreetMap (OSM)**
:   The volunteer-built global map. Inside Overture it is one contributing source among several,
    and the only one that carries building heights.

**ESA WorldCover**
:   A 10 m global land-cover map from the European Space Agency, used here for the impervious,
    pervious, tree and water shares.

**WSF-3D**
:   The World Settlement Footprint 3D building-height layer from DLR, the German Aerospace Centre,
    derived from TanDEM-X radar. About 90 m resolution, global. It is the third tier of the height
    cascade and, outside Europe and North America, the one that answers for most buildings.

**TanDEM-X**
:   The German radar satellite pair whose measurements WSF-3D is derived from.

**GHS-BUILT-H**
:   A 100 m global building-height layer from the Joint Research Centre of the European Commission,
    part of its Global Human Settlement Layer (GHSL). `lczkit` reads the ANBH band, which is
    building volume divided by *built-up* surface — the mean height of the built fabric rather than
    a height averaged over open ground.

**GUPPD**
:   The Global Urban Polygons and Points Dataset, from NASA's Socioeconomic Data and Applications
    Center and the Joint Research Centre. `lczkit` reads its bounds table — 5 558 urban regions
    across 173 countries, with a name, a country and a rectangle — to turn a city name into an
    extent. **`SMOD_ID`** is its identifier for a region, and it is unambiguous where a name is
    not: 149 of the 5 558 names are shared by more than one region.

## References and their metrics

Three independent LCZ maps or label sets ship with loaders. They are research instruments; see
[On validating the output](index.md) for why they are not a quality gate for your own city.

**So2Sat LCZ42**
:   A hand-labelled set of LCZ patches over 51 cities, produced for a machine-learning benchmark
    (Zhu et al. 2020). Each patch is 320 m square. It is the primary reference where it exists.

**WUDAPT**
:   The World Urban Database and Access Portal Tools — a community effort to describe cities by
    LCZ. Its training areas are polygons drawn by contributors worldwide: much wider coverage than
    So2Sat, and irregular, overlapping and of uneven vintage.

**The Demuzere global map (`lcz_v3.tif`)**
:   A global LCZ map produced from satellite imagery. It is **an estimate with its own error**, not
    ground truth, so agreement with it measures the disagreement between two models.

**Ceiling**
:   How well the Demuzere map itself agrees with hand labels on the same cells. It bounds what any
    map can score against that comparator, and it varies enormously by city — 22.8% in Mumbai,
    83.2% in Rio. A raw agreement figure is not comparable across cities without it beside it.

**Overall accuracy (OA) and weighted overall accuracy (OA_w)**
:   `OA` is the share of units whose label matches the reference exactly. `OA_w` gives partial
    credit by how similar the two classes are, using Bechtel, Demuzere & Stewart's (2020)
    similarity matrix, so calling a compact midrise an open midrise scores most of a point while
    calling it water scores near zero. `OA_w` above `OA` says the map is landing in *neighbouring*
    classes rather than at random. It is reported beside `OA` and never instead of it.

**Built-class agreement**
:   Agreement restricted to the built types, reported separately because an overall figure can be
    dominated by water and vegetation, which are easy, and then says nothing about the classifier.

**Confusion axes**
:   Two different ways a label can be wrong, and they diagnose different things. The **height axis**
    (1↔2↔3, 4↔5↔6) holds compactness fixed and varies the height band, so it tracks height-data
    quality. The **compactness axis** (1↔4, 2↔5, 3↔6) holds height fixed and varies building
    surface fraction, so it tracks footprint coverage and how units are drawn.

## Outputs and tooling

**GeoParquet**
:   A columnar file format that stores geometry alongside ordinary table columns. Compact and fast,
    but its reader is optional in some geographic software — which is why a GeoPackage is written
    beside it.

**GeoPackage**
:   A single-file geographic format built on SQLite, readable by essentially every geographic
    information system (GIS) without extra components.

**Coordinate reference system (CRS)**
:   How coordinates map to places on earth. `lczkit` computes in a **projected** system, where
    coordinates are metres, so areas and distances are meaningful; longitude and latitude appear
    only when reading and writing data. The projection used is a **UTM** (Universal Transverse
    Mercator) zone chosen from the extent, identified by an **EPSG** code such as `EPSG:32618`.

**GDAL**
:   The Geospatial Data Abstraction Library, the file-format layer underneath most geographic
    software including QGIS. Its GeoParquet support is an optional build component, so a correct
    file can still fail to open in a GIS that was built without it.

**PMTiles and MapLibre**
:   The map site's two halves. PMTiles is a single-file tile archive read over ordinary HTTP range
    requests; MapLibre is the browser library that draws it. Together they need no tile server.

**tippecanoe**
:   The command-line tool that turns the run's geometry into tiles. It is an optional dependency;
    without it a run writes everything except the map site.

**WRF and W2W**
:   The Weather Research and Forecasting model, a widely used atmospheric model, and the tool that
    converts an LCZ map into input for it. This is the main downstream use for an LCZ map — and
    `lczkit` does not yet write the raster W2W expects.

## Terms this documentation uses

**Height cascade, and tiers**
:   Building heights are filled from a series of sources in order, each tried only where the last
    left a gap. Tier 1 is Overture's own height or storey count; tiers 3 and 4 are the global
    rasters. Which tier answered is recorded **per building** and summarised **per unit**, because
    a height measured on the ground and a height read off a 90 m raster produce the same label with
    very different trustworthiness.

**Provenance**
:   Which source a value came from, carried alongside the value. The package's central claim is
    that for building heights this matters as much as the value.

**Preset**
:   A named bundle of configuration. `Settings.load()` deliberately cannot produce a runnable
    configuration on its own — several measured thresholds default to nothing and raise if used —
    so a preset is what fills them, and which preset ran is recorded in the manifest.

**Sweep**
:   Trying a threshold at many values against a reference and choosing an operating point from the
    result, rather than picking a plausible number. Any threshold in `lczkit` that has not been set
    this way ships **disabled**, which is why several options default to off.
