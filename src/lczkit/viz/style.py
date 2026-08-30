"""The MapLibre style, built in Python from a run manifest.

**Why the style is generated here and not in JavaScript.** The site never recomputes a parameter or
a quantile — it renders what the run already decided. Building the style in Python makes that
constraint *testable*: a test can assert that every
LCZ colour equals `classify.labels.legend()` and that every choropleth's class boundaries are the
manifest's own `breaks`, with nothing derived at draw time. The same assertions written against
`app.js` would be assertions about a string.

It also keeps the browser code to what only the browser can do — pan, click, and toggle. `app.js`
loads `style.json`, and switching a view calls `setPaintProperty` on one already-loaded layer, so
no view change ever refetches a tile.

**No `glyphs` and no `sprite`.** MapLibre fetches both over HTTP when a style names them, and a
style with neither is a style that cannot reach for anything outside the directory. The cost is that
the map carries no text labels; for a class map with a legend that is a small price, and it is the
difference between a directory that renders in ten years and one that renders until a font endpoint
moves.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from lczkit.classify.classifier import DISTANCE_COLUMNS
from lczkit.classify.labels import LCZ_CLASSES, NODATA_CODE
from lczkit.heights.completeness import FRACTION_PREFIX
from lczkit.ucp.registry import PARAMETERS
from lczkit.viz import basemaps

#: Nine-stop perceptually-uniform sequential ramp (a viridis subsample), used for every continuous
#: choropleth. Colourblind-safe and monotone in lightness, so a reader can rank classes from a
#: greyscale print. A presentation constant, not a domain threshold — it goes here rather than in
#: config for the same reason the LCZ colours do.
SEQUENTIAL_RAMP: tuple[str, ...] = (
    "#440154",
    "#472d7b",
    "#3b528b",
    "#2c728e",
    "#21918c",
    "#28ae80",
    "#5ec962",
    "#addc30",
    "#fde725",
)

NODATA_COLOUR = "#3a3a3a"
"""Units with no value for the active variable. Deliberately not a ramp colour and not the
background: a null parameter is a real and reportable state — `aspect_ratio` is null wherever no
street reaches a building — and painting it as though it were a low value would hide that."""

BACKGROUND_COLOUR = "#111418"
WATER_COLOUR = "#1b2a3a"
LAND_USE_COLOUR = "#1a2019"
STREET_COLOUR = "#39414d"
UNIT_OUTLINE_COLOUR = "#000000"

UNITS_SOURCE = "units"
UNITS_DETAIL_SOURCE = "units_detail"
BASEMAP_SOURCE = "basemap"
BUILDINGS_SOURCE = "buildings"

UNITS_FILL_LAYER = "units-fill"
"""The single layer every view paints. One layer rather than one per variable so that switching a
view is a paint change over tiles already in memory rather than a refetch."""

HEIGHT_COMPLETENESS_COLUMN = "height_completeness"
UNIQUENESS_COLUMN = "uniqueness"

RASTER_BASEMAP_PREFIX = "basemap-raster-"
"""Leading string of every remote raster's source and layer id, which are the same string.

**Only `raster_id` may use it, and nothing may match on it.** The site's own linework layers are
also `basemap-*`, and collecting them by prefix once put the remote raster into the choice that
exists precisely to avoid the network. Both sets are built from the decision that separates them —
see `metadata.lczkit.basemap` below."""

GROUP_CLASSIFICATION = "Classification"
GROUP_PROVENANCE = "Height provenance"
GROUP_PARAMETERS = "Urban canopy parameters"
GROUP_CONFIDENCE = "Confidence"
"""Selector groups, in the order `selector_rank` already puts their members in.

The groups are named here rather than derived in the front end for the same reason the labels are:
the ordering is a decision this package made and a test asserts, and a second copy of it in
JavaScript would be a second place for it to be wrong.
"""

#: Display names for the columns the parameter registry does not describe, because they are not
#: urban canopy parameters — they are classification outputs and height provenance. Everything else
#: takes its label from `ParameterSpec.label`, beside the definition.
DISPLAY_LABELS: dict[str, str] = {
    "lcz_primary": "LCZ class",
    "lcz_secondary": "LCZ class, second nearest",
    "uniqueness": "Uniqueness",
    "n_params_used": "Parameters used",
    "label_route": "How the label was assigned",
    HEIGHT_COMPLETENESS_COLUMN: "Height completeness (tier 1)",
}

#: Height tier fractions are `height_frac_<source>` for whichever sources a run's cascade fired, so
#: they cannot be named in a static list without naming a cascade. The *sources* can be, and saying
#: what each one is — rather than printing "wsf3d" — is the difference between a layer a reader can
#: interpret and one they cannot.
HEIGHT_SOURCE_LABELS: dict[str, str] = {
    "overture_height": "Overture height, measured",
    "overture_num_floors": "Overture storeys × storey height",
    "gob25d": "Open Buildings 2.5D, 4 m",
    "wsf3d": "WSF-3D, 90 m raster",
    "ghsl": "GHS-BUILT-H, 100 m raster",
    "unresolved": "No height resolved",
}

REGISTRY_LABELS: dict[str, str] = {spec.name: spec.label for spec in PARAMETERS}
"""`ParameterSpec.label` for every parameter this version of the package knows about.

Consulted when a run's own manifest carries no label, which older runs do — including the three
published ones. Without it, rebuilding an archived site with a newer lczkit
would keep showing the labels the rebuild was meant to fix.
"""


def display_label(column: str, parameters: dict[str, str]) -> str:
    """The human-readable name for `column`, or a readable fallback.

    `parameters` maps a column to the `label` the *run* recorded. A run written before labels
    existed carries none, so the packaged registry answers next — otherwise rebuilding an archived
    run's site with a newer lczkit would still show "height of roughness elements m", and the three
    published sites are exactly such runs.

    That is not the site recomputing something the run decided. A display name is presentation, not
    a measurement: the values, the breaks and the colours still come from the manifest, and
    `DISPLAY_LABELS` and `HEIGHT_SOURCE_LABELS` below already answer from the package. The run's own
    label still wins where it has one, so a manifest that named a column differently keeps its name.
    """
    if column in parameters:
        return parameters[column]
    if column in REGISTRY_LABELS:
        return REGISTRY_LABELS[column]
    if column in DISPLAY_LABELS:
        return DISPLAY_LABELS[column]
    if column.startswith(FRACTION_PREFIX):
        source = column[len(FRACTION_PREFIX) :]
        return HEIGHT_SOURCE_LABELS.get(source, source.replace("_", " "))
    return column.replace("_", " ")


def selector_group(column: str) -> str:
    """Which selector group `column` belongs to. Follows `selector_rank`, not a second ordering."""
    if column == "lcz_primary":
        return GROUP_CLASSIFICATION
    if column == HEIGHT_COMPLETENESS_COLUMN or column.startswith(FRACTION_PREFIX):
        return GROUP_PROVENANCE
    if column == UNIQUENESS_COLUMN:
        return GROUP_CONFIDENCE
    return GROUP_PARAMETERS


def selector_rank(column: str) -> tuple[int, int]:
    """Where `column` sits in the layer selector.

    **The order is chosen here, not inherited.** `build_views` used to emit views in whatever order
    the manifest's `breaks` arrived in, which is `writer.py`'s `continuous` — every numeric column
    in DataFrame order. That is incidental, and it put height provenance *last*, below ten urban
    canopy parameters. `height_completeness` and
    `height_tier_fractions` are first-class layers and sit second in the selector, above the UCP
    choropleths. They are the visible form of what this package reports — Cairo at 0.4% tier-1
    coverage against Berlin at 68.9% is the comparison the site exists to make legible.

    Ties keep the manifest's order, so a parameter added later lands among the UCPs without needing
    an edit here.
    """
    if column == HEIGHT_COMPLETENESS_COLUMN:
        return (0, 0)
    if column.startswith(FRACTION_PREFIX):
        return (0, 1)
    if column == UNIQUENESS_COLUMN:
        # Not a parameter but a property of the classification, so it reads as a coda to the
        # parameters rather than one of them.
        return (2, 0)
    return (1, 0)


def ramp_colours(n: int) -> list[str]:
    """`n` colours sampled evenly from `SEQUENTIAL_RAMP`, endpoints included."""
    if n <= 0:
        return []
    if n == 1:
        return [SEQUENTIAL_RAMP[-1]]
    last = len(SEQUENTIAL_RAMP) - 1
    return [SEQUENTIAL_RAMP[round(index * last / (n - 1))] for index in range(n)]


def lcz_colour_expression(column: str = "lcz_primary") -> list[Any]:
    """A `match` expression mapping LCZ integer codes to the Demuzere colours.

    Read from `classify.labels`, which a test already asserts equal to the committed reference
    table — so the map's colours and the output raster's colours cannot drift apart.

    **`to-number` is load-bearing, not defensive.** tippecanoe's FlatGeobuf reader emits every
    integer attribute as a *string* — measured at int16, int32, int64 and uint8, while float64 comes
    through as a number. `lcz_primary` is the only integer column the site renders, so a `match` on
    the raw value found no label, every cell fell through to `NODATA_COLOUR`, and the default view
    of every published site was a field of blank grey squares. Coercing here rather than casting
    the column to float in `write_flatgeobuf` keeps a class code an integer everywhere it is read,
    and keeps the fix at the one place that depends on the type.

    A missing value coerces to 0, which matches no label and so still takes `NODATA_COLOUR`.
    """
    expression: list[Any] = ["match", ["to-number", ["get", column]]]
    for entry in LCZ_CLASSES:
        expression += [entry.code, entry.colour]
    expression.append(NODATA_COLOUR)
    return expression


def choropleth_expression(column: str, breaks: list[float]) -> list[Any]:
    """A `step` expression over the run's precomputed break points.

    `breaks` are the `k + 1` boundaries `output.breaks` wrote, so the interior boundaries are
    `breaks[1:-1]` and the number of classes is one more than that. Nothing is quantised, binned or
    quantiled here; the boundaries arrive already decided.

    Guarded by `has` so a unit missing the parameter paints as missing rather than as the lowest
    class — the distinction the null-parameter policy exists to preserve.
    """
    interior = breaks[1:-1]
    colours = ramp_colours(len(interior) + 1)
    step: list[Any] = ["step", ["to-number", ["get", column]], colours[0]]
    for boundary, colour in zip(interior, colours[1:], strict=True):
        step += [boundary, colour]
    return ["case", ["has", column], step, NODATA_COLOUR]


def build_views(
    breaks: list[dict[str, Any]], columns: list[str], parameters: list[dict[str, str]]
) -> list[dict[str, Any]]:
    """One view per renderable variable, LCZ first and height provenance second.

    A variable earns a view only if it is *both* in the tiles (`columns`) and has breaks in the
    manifest. Anything else would be a menu entry that paints nothing.

    The continuous views are ordered by `selector_rank` rather than by the order the breaks arrive
    in — see that function for why the inherited order was wrong.
    """
    units = {entry["name"]: entry.get("unit", "") for entry in parameters}
    descriptions = {entry["name"]: entry.get("description", "") for entry in parameters}
    labels = {entry["name"]: entry["label"] for entry in parameters if entry.get("label")}
    views: list[dict[str, Any]] = [
        {
            "id": "lcz",
            "column": "lcz_primary",
            "label": "LCZ class",
            "group": GROUP_CLASSIFICATION,
            "unit": "",
            "description": "Primary Local Climate Zone, Demuzere et al. (2022) colours",
            "kind": "categorical",
            "paint": lcz_colour_expression(),
            "legend": [
                {"colour": entry.colour, "label": f"{entry.label} — {entry.name}"}
                for entry in LCZ_CLASSES
            ],
        }
    ]

    available = set(columns)
    continuous: list[dict[str, Any]] = []
    for entry in breaks:
        column = entry["column"]
        if column not in available or not entry.get("breaks"):
            continue
        boundaries = [float(value) for value in entry["breaks"]]
        if len(boundaries) < 2:
            continue
        interior = boundaries[1:-1]
        colours = ramp_colours(len(interior) + 1)
        edges = [boundaries[0], *interior, boundaries[-1]]
        legend: list[dict[str, Any]] = [
            {"colour": colour, "label": f"{low:.3g} – {high:.3g}"}
            for colour, low, high in zip(colours, edges[:-1], edges[1:], strict=True)
        ]
        # A null parameter is a reportable state, not an absence — `aspect_ratio` is null wherever
        # no street reaches a building, which is most of LCZ 8. Without a row for it the reader
        # sees grey cells in the same shade on every layer and no way to learn what grey means.
        legend.append({"colour": NODATA_COLOUR, "label": "no value", "nodata": True})
        continuous.append(
            {
                "id": column,
                "column": column,
                "label": display_label(column, labels),
                "group": selector_group(column),
                "unit": units.get(column, ""),
                "description": descriptions.get(column, ""),
                "kind": "continuous",
                "method": entry.get("method", "quantile"),
                "paint": choropleth_expression(column, boundaries),
                "legend": legend,
            }
        )
    # Stable, so columns of equal rank keep the manifest's order.
    continuous.sort(key=lambda view: selector_rank(str(view["column"])))
    views.extend(continuous)
    return views


def raster_id(entry: basemaps.BasemapProvider) -> str:
    """The style id of `entry`'s source and layer, which are deliberately the same string.

    One id per provider, because each carries its own tile size and maximum zoom and a MapLibre
    source carries both — so several grounds cannot share one source whose tiles are swapped.
    """
    return f"{RASTER_BASEMAP_PREFIX}{entry.key}"


def build_style(
    manifest: dict[str, Any],
    *,
    columns: list[str],
    bounds: tuple[float, float, float, float],
    centre: tuple[float, float],
    has_detail: bool,
    basemap_layers: tuple[str, ...],
    has_buildings: bool,
    online_basemaps: Sequence[str] = (),
    maptiler_key: str | None = None,
) -> dict[str, Any]:
    """The complete style document, ready to be written as `style.json`.

    `columns` is what the unit tileset actually carries, so a manifest listing breaks for a column
    that did not make it into the tiles produces no menu entry rather than a blank map. Likewise
    `basemap_layers` is what the basemap tileset actually contains: a style layer naming a
    `source-layer` that is not in the tileset renders nothing and reports nothing, which is the
    hardest kind of blank map to diagnose.

    `online_basemaps` names remote raster grounds to add beneath everything, in picker order. They
    are the only thing in this document that reaches outside the directory, and there are none
    unless a caller asks — see `lczkit.viz.basemaps` for why that default is load-bearing rather
    than cautious. Each gets its own source and layer rather than sharing one whose tiles are
    swapped: tile size and maximum zoom differ per provider and a source carries both.
    """
    has_basemap = bool(basemap_layers)
    rasters = [basemaps.provider(key) for key in online_basemaps]
    views = build_views(manifest.get("breaks", []), columns, manifest.get("parameters", []))

    sources: dict[str, Any] = {
        UNITS_SOURCE: {
            "type": "vector",
            "url": "pmtiles://./tiles/units.pmtiles",
            # `unit_id` *is* the feature identity everywhere else in this package, so promoting it
            # makes the map agree with the rest of the pipeline. It also makes the selection
            # highlight work at all: `setFeatureState` needs an id, and tippecanoe assigns none
            # unless asked, so without this a click would silently highlight nothing.
            "promoteId": "unit_id",
        }
    }
    if has_detail:
        sources[UNITS_DETAIL_SOURCE] = {
            "type": "vector",
            "url": "pmtiles://./tiles/units_detail.pmtiles",
        }
    if has_basemap:
        sources[BASEMAP_SOURCE] = {"type": "vector", "url": "pmtiles://./tiles/basemap.pmtiles"}
    if has_buildings:
        sources[BUILDINGS_SOURCE] = {
            "type": "vector",
            "url": "pmtiles://./tiles/buildings.pmtiles",
        }
    for entry in rasters:
        sources[raster_id(entry)] = {
            "type": "raster",
            # Raises rather than shipping an unsubstituted `{key}`, which would 403 per tile and
            # look like an empty base map instead of a missing key.
            "tiles": basemaps.tile_urls(entry, maptiler_key),
            "tileSize": entry.tile_size,
            "maxzoom": entry.max_zoom,
            # MapLibre's attribution control reads this. Every provider here requires attribution,
            # which is why configuring one also switches that control on in the front end.
            "attribution": entry.attribution,
        }

    layers: list[dict[str, Any]] = [
        {"id": "background", "type": "background", "paint": {"background-color": BACKGROUND_COLOUR}}
    ]
    for entry in rasters:
        # Beneath everything, and all hidden at first: the run's own linework is the default ground,
        # so an archived site opened offline looks the way it always did until a reader asks for
        # tiles. They sit in one block directly above the background, so whichever the reader picks
        # is under the classification rather than over it.
        layers.append(
            {
                "id": raster_id(entry),
                "type": "raster",
                "source": raster_id(entry),
                "layout": {"visibility": "none"},
                "paint": {"raster-opacity": 1.0},
            }
        )
    # The layers the *run* persisted, as opposed to the remote raster. The base picker switches
    # between the two sets, so they have to be distinguishable by more than a name prefix.
    run_basemap_layers: list[str] = []
    if "land_use" in basemap_layers:
        layers.append(
            {
                "id": "basemap-land-use",
                "type": "fill",
                "source": BASEMAP_SOURCE,
                "source-layer": "land_use",
                "paint": {"fill-color": LAND_USE_COLOUR},
            }
        )
        run_basemap_layers.append("basemap-land-use")
    if "water" in basemap_layers:
        layers.append(
            {
                "id": "basemap-water",
                "type": "fill",
                "source": BASEMAP_SOURCE,
                "source-layer": "water",
                "paint": {"fill-color": WATER_COLOUR},
            }
        )
        run_basemap_layers.append("basemap-water")

    layers.append(
        {
            "id": UNITS_FILL_LAYER,
            "type": "fill",
            "source": UNITS_SOURCE,
            "source-layer": "units",
            "paint": {"fill-color": views[0]["paint"], "fill-opacity": 0.82},
        }
    )
    layers.append(
        {
            "id": "units-outline",
            "type": "line",
            "source": UNITS_SOURCE,
            "source-layer": "units",
            "minzoom": 13,
            "paint": {"line-color": UNIT_OUTLINE_COLOUR, "line-opacity": 0.25, "line-width": 0.5},
        }
    )

    if "streets" in basemap_layers:
        layers.append(
            {
                "id": "basemap-streets",
                "type": "line",
                "source": BASEMAP_SOURCE,
                "source-layer": "streets",
                "paint": {
                    "line-color": STREET_COLOUR,
                    "line-opacity": 0.75,
                    "line-width": ["interpolate", ["linear"], ["zoom"], 10, 0.3, 16, 1.8],
                },
            }
        )
        run_basemap_layers.append("basemap-streets")

    if has_buildings:
        layers.append(
            {
                "id": "buildings-3d",
                "type": "fill-extrusion",
                "source": BUILDINGS_SOURCE,
                "source-layer": "buildings",
                "minzoom": 14,
                "layout": {"visibility": "none"},
                "paint": {
                    "fill-extrusion-height": ["coalesce", ["to-number", ["get", "height"]], 3],
                    "fill-extrusion-base": 0,
                    "fill-extrusion-opacity": 0.9,
                    "fill-extrusion-color": "#c8cdd4",
                },
            }
        )

    # The selection highlight reads a feature-state rather than a filter, so clicking never
    # invalidates the tile and never triggers a re-request.
    layers.append(
        {
            "id": "units-selected",
            "type": "line",
            "source": UNITS_SOURCE,
            "source-layer": "units",
            "paint": {
                "line-color": "#ffffff",
                "line-width": ["case", ["boolean", ["feature-state", "selected"], False], 3, 0],
            },
        }
    )

    return {
        "version": 8,
        "name": f"lczkit {manifest.get('run_id', '')}".strip(),
        "sources": sources,
        "layers": layers,
        "metadata": {
            "lczkit": {
                "run_id": manifest.get("run_id"),
                "views": views,
                "fill_layer": UNITS_FILL_LAYER,
                "units_source": UNITS_SOURCE,
                "units_source_layer": "units",
                "detail_source": UNITS_DETAIL_SOURCE if has_detail else None,
                # Column names are passed to the browser rather than reconstructed there. The
                # distance columns are `lcz_d1..17` and the tier fractions are named after
                # whichever height sources fired, so a hardcoded list in JavaScript would be a
                # second definition of a schema that already has one.
                "distance_columns": list(DISTANCE_COLUMNS),
                "distance_labels": [entry.label for entry in LCZ_CLASSES],
                "height_prefixes": ["height_completeness", FRACTION_PREFIX],
                "buildings_layer": "buildings-3d" if has_buildings else None,
                "building_colour_by": _building_colour_expressions() if has_buildings else {},
                "bounds": list(bounds),
                "centre": list(centre),
                "nodata_code": NODATA_CODE,
                "nodata_colour": NODATA_COLOUR,
                # Which grounds the reader can choose between. `run_layers` is always present
                # because the run persisted its own water and streets, and it is an *overlay*: it
                # composes over whichever raster is chosen rather than replacing it. `rasters` is
                # empty unless a caller configured one, and an empty list is what makes the page
                # show no base-map picker at all.
                "basemap": {
                    # Collected as they were appended rather than matched on the "basemap-" prefix,
                    # which the raster layers also carry — prefix-matching here put the remote
                    # tiles into the offline choice and made "run's own linework" fetch the network.
                    "run_layers": run_basemap_layers,
                    "rasters": [
                        {
                            "id": raster_id(entry),
                            "key": entry.key,
                            "label": entry.label,
                            "licence": entry.licence,
                            # Drives the front end's opacity floor: the LCZ palette is a light
                            # figure on a dark ground, so over a light or busy ground the unit fill
                            # has to be drawn more opaquely to stay readable.
                            "dark": entry.dark,
                        }
                        for entry in rasters
                    ],
                },
                # The sidebar renders one row per parameter and used to title each with its column
                # name. These are `ParameterSpec.label`, plus the classification and provenance
                # columns the registry does not describe.
                "labels": {
                    **{
                        entry["name"]: entry["label"]
                        for entry in manifest.get("parameters", [])
                        if entry.get("label")
                    },
                    **DISPLAY_LABELS,
                },
                "height_source_labels": dict(HEIGHT_SOURCE_LABELS),
                "groups": [
                    GROUP_CLASSIFICATION,
                    GROUP_PROVENANCE,
                    GROUP_PARAMETERS,
                    GROUP_CONFIDENCE,
                ],
            }
        },
    }


def _building_colour_expressions() -> dict[str, Any]:
    """Paint expressions for the two ways a reader can colour the extrusions.

    Colouring by `height_source` is the point of the layer: a
    block of towers is a different claim when its heights came from OSM tags than when they came
    from a 100 m raster mean, and only this view shows the difference building by building.
    """
    tiers = {
        "overture": "#f0f0f0",
        "gob25d": "#7fb3d5",
        "wsf3d": "#e59866",
        "ghsl": "#c0392b",
    }
    match: list[Any] = ["match", ["get", "height_source"]]
    for tier, colour in tiers.items():
        match += [tier, colour]
    match.append(NODATA_COLOUR)
    return {
        "uniform": "#c8cdd4",
        "height_source": match,
        "height_source_legend": [
            {"colour": colour, "label": tier} for tier, colour in tiers.items()
        ],
    }
