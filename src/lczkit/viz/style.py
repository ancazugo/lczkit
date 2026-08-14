"""The MapLibre style, built in Python from a run manifest.

**Why the style is generated here and not in JavaScript.** CLAUDE.md's binding constraint on Phase 7
is that the site never recomputes a parameter or a quantile — it renders what the run already
decided. Building the style in Python makes that constraint *testable*: a test can assert that every
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

from typing import Any

from lczkit.classify.classifier import DISTANCE_COLUMNS
from lczkit.classify.labels import LCZ_CLASSES, NODATA_CODE
from lczkit.heights.completeness import FRACTION_PREFIX

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
view is a paint change over tiles already in memory, which is what CLAUDE.md asks for."""

HEIGHT_COMPLETENESS_COLUMN = "height_completeness"
UNIQUENESS_COLUMN = "uniqueness"


def selector_rank(column: str) -> tuple[int, int]:
    """Where `column` sits in the layer selector.

    **The order is chosen here, not inherited.** `build_views` used to emit views in whatever order
    the manifest's `breaks` arrived in, which is `writer.py`'s `continuous` — every numeric column
    in DataFrame order. That is incidental, and it put height provenance *last*, below ten urban
    canopy parameters, in the one place where CLAUDE.md names a position: `height_completeness` and
    `height_tier_fractions` are first-class layers and sit second in the selector, above the UCP
    choropleths. They are the visible form of the project's central result — Cairo at 0.4% tier-1
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
    views: list[dict[str, Any]] = [
        {
            "id": "lcz",
            "column": "lcz_primary",
            "label": "LCZ class",
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
        continuous.append(
            {
                "id": column,
                "column": column,
                "label": column.replace("_", " "),
                "unit": units.get(column, ""),
                "description": descriptions.get(column, ""),
                "kind": "continuous",
                "method": entry.get("method", "quantile"),
                "paint": choropleth_expression(column, boundaries),
                "legend": [
                    {"colour": colour, "label": f"{low:.3g} – {high:.3g}"}
                    for colour, low, high in zip(colours, edges[:-1], edges[1:], strict=True)
                ],
            }
        )
    # Stable, so columns of equal rank keep the manifest's order.
    continuous.sort(key=lambda view: selector_rank(str(view["column"])))
    views.extend(continuous)
    return views


def build_style(
    manifest: dict[str, Any],
    *,
    columns: list[str],
    bounds: tuple[float, float, float, float],
    centre: tuple[float, float],
    has_detail: bool,
    basemap_layers: tuple[str, ...],
    has_buildings: bool,
) -> dict[str, Any]:
    """The complete style document, ready to be written as `style.json`.

    `columns` is what the unit tileset actually carries, so a manifest listing breaks for a column
    that did not make it into the tiles produces no menu entry rather than a blank map. Likewise
    `basemap_layers` is what the basemap tileset actually contains: a style layer naming a
    `source-layer` that is not in the tileset renders nothing and reports nothing, which is the
    hardest kind of blank map to diagnose.
    """
    has_basemap = bool(basemap_layers)
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

    layers: list[dict[str, Any]] = [
        {"id": "background", "type": "background", "paint": {"background-color": BACKGROUND_COLOUR}}
    ]
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
            }
        },
    }


def _building_colour_expressions() -> dict[str, Any]:
    """Paint expressions for the two ways a reader can colour the extrusions.

    Colouring by `height_source` is the one CLAUDE.md names, and it is the point of the layer: a
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
