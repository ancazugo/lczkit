"""The MapLibre style: does it draw what the run decided, and nothing it decided for itself?

CLAUDE.md's constraint on Phase 7 is that the site never recomputes a parameter or a quantile.
That is a claim about the style document, and it is checkable: every LCZ colour must equal the
committed legend, and every choropleth boundary must be a number the manifest already contained.
Building the style in Python rather than JavaScript is what makes these assertions possible.
"""

from __future__ import annotations

from typing import Any

import pytest

from lczkit.classify.labels import LCZ_CLASSES, legend
from lczkit.viz.style import (
    NODATA_COLOUR,
    UNITS_FILL_LAYER,
    build_style,
    build_views,
    choropleth_expression,
    lcz_colour_expression,
    ramp_colours,
)

BREAKS = [
    {
        "column": "building_surface_fraction",
        "method": "quantile",
        "k": 7,
        "breaks": [0.0, 0.05, 0.12, 0.21, 0.33, 0.44, 0.58, 0.91],
        "n_valid": 400,
        "minimum": 0.0,
        "maximum": 0.91,
    },
    {
        "column": "aspect_ratio",
        "method": "quantile",
        "k": 7,
        "breaks": [0.1, 0.4, 1.9],
        "n_valid": 120,
        "minimum": 0.1,
        "maximum": 1.9,
    },
    {
        "column": "constant_everywhere",
        "method": "quantile",
        "k": 7,
        "breaks": [],
        "n_valid": 0,
        "minimum": None,
        "maximum": None,
    },
]

MANIFEST: dict[str, Any] = {
    "run_id": "test-run",
    "breaks": BREAKS,
    "legend": legend(),
    "parameters": [
        {
            "name": "building_surface_fraction",
            "unit": "fraction",
            "description": "share of unit area under building footprint",
            "reference": "10.1175/BAMS-D-11-00019.1",
        }
    ],
}

COLUMNS = ["unit_id", "lcz_primary", "building_surface_fraction", "aspect_ratio"]


def style(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "columns": COLUMNS,
        "bounds": (13.0, 52.3, 13.8, 52.7),
        "centre": (13.4, 52.5),
        "has_detail": True,
        "basemap_layers": ("water", "streets"),
        "has_buildings": False,
    }
    kwargs.update(overrides)
    return build_style(MANIFEST, **kwargs)


def test_the_lcz_colours_are_the_committed_legend_and_nothing_else() -> None:
    """The map, the output raster and the reference table must agree on what colour LCZ 2 is.
    Reading `LCZ_CLASSES` here rather than restating the hex codes is the point: a test that
    repeated them would pass while the map drifted."""
    expression = lcz_colour_expression()

    assert expression[0] == "match"
    assert expression[1] == ["get", "lcz_primary"]
    pairs = dict(zip(expression[2:-1:2], expression[3:-1:2], strict=True))
    assert pairs == {entry.code: entry.colour for entry in LCZ_CLASSES}
    assert expression[-1] == NODATA_COLOUR, "an unclassified unit must not borrow a class colour"


def test_a_choropleth_uses_the_manifest_breaks_verbatim() -> None:
    """No quantile is computed at site-build time; the boundaries arrive already decided."""
    boundaries = [0.0, 0.05, 0.12, 0.21, 0.33, 0.44, 0.58, 0.91]

    expression = choropleth_expression("building_surface_fraction", boundaries)

    assert expression[0] == "case"
    step = expression[2]
    assert step[0] == "step"
    stops = step[3::2]
    assert stops == boundaries[1:-1], "interior boundaries only, in the manifest's own order"
    assert len(step[2::2]) == len(stops) + 1, "one more colour than interior boundaries"


def test_a_missing_value_paints_as_missing_rather_than_as_the_lowest_class() -> None:
    """`aspect_ratio` is legitimately null wherever no street reaches a building. Painting those
    units at the bottom of the ramp would turn a reportable absence into a plausible reading."""
    expression = choropleth_expression("aspect_ratio", [0.1, 0.4, 1.9])

    assert expression[0] == "case"
    assert expression[1] == ["has", "aspect_ratio"]
    assert expression[3] == NODATA_COLOUR


def test_ramp_colours_are_distinct_and_span_the_ramp() -> None:
    for n in range(2, 10):
        colours = ramp_colours(n)
        assert len(colours) == n
        assert len(set(colours)) == n, f"{n} classes collapsed onto fewer colours"
        assert colours[0] != colours[-1]


def test_a_column_absent_from_the_tiles_gets_no_menu_entry() -> None:
    """A view that cannot paint is worse than a view that is not offered: it looks like a result."""
    views = build_views(BREAKS, ["unit_id", "lcz_primary"], MANIFEST["parameters"])

    assert [view["id"] for view in views] == ["lcz"]


def test_a_variable_with_no_breaks_gets_no_menu_entry() -> None:
    """`quantile_breaks` returns an empty list for an all-null or constant variable rather than
    raising, so the style has to decline it rather than emit a one-class ramp."""
    views = build_views(BREAKS, [*COLUMNS, "constant_everywhere"], MANIFEST["parameters"])

    assert "constant_everywhere" not in {view["id"] for view in views}


def test_views_carry_the_parameter_unit_from_the_manifest() -> None:
    """CLAUDE.md: never write a parameter without a documented unit. That extends to the sidebar."""
    views = build_views(BREAKS, COLUMNS, MANIFEST["parameters"])

    bsf = next(view for view in views if view["id"] == "building_surface_fraction")
    assert bsf["unit"] == "fraction"
    assert bsf["description"]


def test_every_view_paints_the_same_single_layer() -> None:
    """Switching a view must be a paint change over loaded tiles, never a source swap. One fill
    layer for every view is the structural guarantee of that."""
    document = style()

    fill_layers = [layer for layer in document["layers"] if layer["type"] == "fill"]
    unit_fills = [layer for layer in fill_layers if layer["source"] == "units"]
    assert [layer["id"] for layer in unit_fills] == [UNITS_FILL_LAYER]
    assert document["metadata"]["lczkit"]["fill_layer"] == UNITS_FILL_LAYER


def test_the_style_names_no_glyphs_and_no_sprite() -> None:
    """MapLibre fetches both over HTTP when a style names them. A style with neither cannot reach
    outside the directory, which is the whole offline guarantee."""
    document = style()

    assert "glyphs" not in document
    assert "sprite" not in document
    assert not any(layer["type"] == "symbol" for layer in document["layers"])


def test_every_source_is_a_relative_pmtiles_path() -> None:
    document = style(has_buildings=True)

    urls = [source["url"] for source in document["sources"].values()]
    assert urls, "a style with no sources would render an empty page"
    for url in urls:
        assert url.startswith("pmtiles://./tiles/"), url


def test_absent_tilesets_produce_no_source_and_no_layer() -> None:
    """A site built from a run that persisted no context layers must not reference a basemap it
    does not have — MapLibre would report a network error on every tile."""
    document = style(has_detail=False, basemap_layers=(), has_buildings=False)

    assert set(document["sources"]) == {"units"}
    sources = {layer.get("source") for layer in document["layers"]} - {None}
    assert sources == {"units"}
    assert document["metadata"]["lczkit"]["detail_source"] is None
    assert document["metadata"]["lczkit"]["buildings_layer"] is None


def test_the_unit_source_promotes_unit_id_so_selection_works() -> None:
    """`setFeatureState` needs a feature id and tippecanoe assigns none unless asked, so without
    `promoteId` a click would highlight nothing and report no error. Promoting `unit_id` also makes
    the map key selection on the same identifier every other stage of the pipeline joins on."""
    document = style()

    assert document["sources"]["units"]["promoteId"] == "unit_id"
    selected = next(layer for layer in document["layers"] if layer["id"] == "units-selected")
    assert "feature-state" in str(selected["paint"]["line-width"])
    assert "filter" not in selected, "a filter would invalidate the layer and re-read the source"


def test_the_style_names_only_basemap_layers_the_tileset_contains() -> None:
    """A style layer naming a `source-layer` absent from the tileset renders nothing and reports
    nothing — the hardest kind of blank map to diagnose. Land use is off by default (it was 94% of
    the basemap's bytes under a translucent fill), so this is the ordinary case, not an edge one."""
    document = style(basemap_layers=("water", "streets"))

    named = {
        layer["source-layer"] for layer in document["layers"] if layer.get("source") == "basemap"
    }
    assert named == {"water", "streets"}

    with_land_use = style(basemap_layers=("land_use", "water", "streets"))
    named = {
        layer["source-layer"]
        for layer in with_land_use["layers"]
        if layer.get("source") == "basemap"
    }
    assert named == {"land_use", "water", "streets"}


def test_the_buildings_layer_is_fill_extrusion_driven_by_height() -> None:
    """CLAUDE.md is specific: MapLibre native `fill-extrusion`, not deck.gl."""
    document = style(has_buildings=True)

    layer = next(layer for layer in document["layers"] if layer["id"] == "buildings-3d")
    assert layer["type"] == "fill-extrusion"
    assert "height" in str(layer["paint"]["fill-extrusion-height"])
    assert layer["layout"]["visibility"] == "none", "buildings are opt-in, not the default view"

    colouring = document["metadata"]["lczkit"]["building_colour_by"]
    assert set(colouring) >= {"uniform", "height_source"}


def test_the_metadata_carries_the_distance_columns_the_sidebar_reads() -> None:
    """The sidebar's bar chart must read the same seventeen columns, in the same order, that the
    classifier wrote. Passing them through the style keeps one definition of that ordering."""
    from lczkit.classify.classifier import DISTANCE_COLUMNS

    meta = style()["metadata"]["lczkit"]

    assert meta["distance_columns"] == list(DISTANCE_COLUMNS)
    assert meta["distance_labels"] == [entry.label for entry in LCZ_CLASSES]


@pytest.mark.parametrize("boundaries", [[0.0, 1.0], [0.0, 0.5, 1.0]])
def test_a_two_boundary_variable_still_produces_a_usable_ramp(boundaries: list[float]) -> None:
    """A variable that is zero over most of a city collapses to few distinct quantiles. That is a
    truthful result and must not crash the style builder."""
    expression = choropleth_expression("sparse", boundaries)

    assert expression[0] == "case"
    assert expression[2][0] == "step"
