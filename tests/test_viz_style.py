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
from lczkit.viz.basemaps import PROVIDERS
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
            "label": "Building surface fraction",
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
    assert expression[1] == ["to-number", ["get", "lcz_primary"]], (
        "the class code must be coerced: tippecanoe emits integer attributes as strings"
    )
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


ORDERED_BREAKS = [
    # Deliberately in the order `writer.py` would emit them — every numeric column in DataFrame
    # order, which is what put height provenance last in the built Berlin site.
    {"column": "building_surface_fraction", "breaks": [0.0, 0.3, 0.9], "method": "quantile"},
    {"column": "aspect_ratio", "breaks": [0.1, 0.4, 1.9], "method": "quantile"},
    {"column": "uniqueness", "breaks": [0.0, 0.5, 1.0], "method": "quantile"},
    {"column": "height_frac_wsf3d", "breaks": [0.0, 0.4, 1.0], "method": "quantile"},
    {"column": "height_completeness", "breaks": [0.0, 0.2, 1.0], "method": "quantile"},
    {"column": "height_frac_ghsl", "breaks": [0.0, 0.1, 1.0], "method": "quantile"},
]

ORDERED_COLUMNS = ["unit_id", "lcz_primary", *[entry["column"] for entry in ORDERED_BREAKS]]


def view_ids(breaks: list[dict[str, Any]], columns: list[str]) -> list[str]:
    return [view["id"] for view in build_views(breaks, columns, [])]


def test_height_provenance_is_the_second_layer_in_the_selector() -> None:
    """CLAUDE.md names one position in the selector and this is it: `height_completeness` and the
    tier fractions sit second, above the UCP choropleths, because they are the visible form of the
    project's central result rather than a diagnostic. The built Berlin site had them last."""
    ids = view_ids(ORDERED_BREAKS, ORDERED_COLUMNS)

    assert ids[0] == "lcz"
    assert ids[1] == "height_completeness"
    assert set(ids[2:4]) == {"height_frac_wsf3d", "height_frac_ghsl"}
    assert ids.index("height_frac_ghsl") < ids.index("building_surface_fraction"), (
        "a tier fraction must not sit below a UCP choropleth"
    )


def test_uniqueness_sorts_after_the_urban_canopy_parameters() -> None:
    """It describes the classification rather than the surface, so it reads as a coda."""
    ids = view_ids(ORDERED_BREAKS, ORDERED_COLUMNS)

    assert ids[-1] == "uniqueness"
    assert ids.index("aspect_ratio") < ids.index("uniqueness")


def test_a_tier_fraction_earns_a_view_and_not_only_a_sidebar_field() -> None:
    """`height_tier_fractions` is specified as a first-class layer. Before this it reached the
    sidebar through `height_prefixes` and had no menu entry at all, because the columns never
    entered the render set."""
    ids = view_ids(ORDERED_BREAKS, ORDERED_COLUMNS)

    assert "height_frac_wsf3d" in ids
    assert "height_frac_ghsl" in ids


def test_the_selector_order_does_not_depend_on_the_order_the_breaks_arrive_in() -> None:
    """The defect being fixed is that the order was inherited from the manifest, so reversing the
    breaks must not move a view between groups.

    Within a group the manifest's order is kept deliberately, so the two tier fractions may swap;
    what must not change is that both stay above every UCP.
    """
    forward = view_ids(ORDERED_BREAKS, ORDERED_COLUMNS)
    backward = view_ids(list(reversed(ORDERED_BREAKS)), ORDERED_COLUMNS)

    for ids in (forward, backward):
        assert ids[0] == "lcz"
        assert ids[1] == "height_completeness"
        assert set(ids[2:4]) == {"height_frac_wsf3d", "height_frac_ghsl"}
        assert ids[-1] == "uniqueness"


def test_columns_of_equal_rank_keep_the_manifests_order() -> None:
    """So that adding a parameter lands it among the UCPs without an edit to the rank function."""
    ids = view_ids(ORDERED_BREAKS, ORDERED_COLUMNS)

    assert ids.index("building_surface_fraction") < ids.index("aspect_ratio")


# ------------------------------------------------------------------ labels and grouping


def test_a_view_is_named_by_the_registry_and_not_by_its_column() -> None:
    """`column.replace("_", " ")` produced "height of roughness elements m" on every published map.

    The label belongs beside the definition in `ucp.registry`, so the name a reader sees and the
    description they can read cannot disagree.
    """
    views = build_views(BREAKS, COLUMNS, MANIFEST["parameters"])
    bsf = next(view for view in views if view["column"] == "building_surface_fraction")

    assert bsf["label"] == "Building surface fraction"


def test_a_column_the_registry_does_not_describe_still_gets_a_readable_label() -> None:
    """A run may carry a column no version of this package describes — an experiment's own output,
    or one added after the site code was written. A slightly ugly label beats a missing one, so
    underscore-stripping survives as the last resort rather than as the rule.

    Deliberately *not* `aspect_ratio`: that is a registered parameter, and using it here only
    appeared to test the fallback because the manifest fixture happened to omit it.
    """
    breaks = [{"column": "some_future_column", "method": "quantile", "breaks": [0.0, 0.5, 1.0]}]
    views = build_views(breaks, ["unit_id", "lcz_primary", "some_future_column"], [])

    unknown = next(view for view in views if view["column"] == "some_future_column")
    assert unknown["label"] == "some future column"


def test_a_registered_parameter_is_named_even_when_the_manifest_omits_it() -> None:
    """`aspect_ratio` is in the registry, so it gets its published name whether or not the run
    that produced the map happened to list it."""
    views = build_views(BREAKS, COLUMNS, MANIFEST["parameters"])
    aspect = next(view for view in views if view["column"] == "aspect_ratio")

    assert aspect["label"] == "Aspect ratio (H/W)"


def test_height_tier_fractions_are_named_for_the_product_they_came_from() -> None:
    """`height_frac_wsf3d` tells a reader nothing. "WSF-3D, 90 m raster" tells them the thing the
    package exists to report — that this cell's heights are a coarse areal mean."""
    breaks = [
        {"column": "height_frac_wsf3d", "method": "quantile", "breaks": [0.0, 0.5, 1.0]},
        {"column": "height_frac_ghsl", "method": "quantile", "breaks": [0.0, 0.5, 1.0]},
    ]
    columns = ["unit_id", "lcz_primary", "height_frac_wsf3d", "height_frac_ghsl"]
    views = build_views(breaks, columns, [])

    labels = {view["column"]: view["label"] for view in views if view["column"] != "lcz_primary"}
    assert labels["height_frac_wsf3d"] == "WSF-3D, 90 m raster"
    assert labels["height_frac_ghsl"] == "GHS-BUILT-H, 100 m raster"


def test_every_view_declares_the_group_it_belongs_to() -> None:
    """The selector groups exist to make `selector_rank`'s order visible, not to reorder it."""
    breaks = [
        {"column": "height_completeness", "method": "quantile", "breaks": [0.0, 0.5, 1.0]},
        {"column": "building_surface_fraction", "method": "quantile", "breaks": [0.0, 0.5, 1.0]},
        {"column": "uniqueness", "method": "quantile", "breaks": [0.0, 0.5, 1.0]},
    ]
    columns = [
        "unit_id",
        "lcz_primary",
        "height_completeness",
        "building_surface_fraction",
        "uniqueness",
    ]
    views = build_views(breaks, columns, MANIFEST["parameters"])

    groups = [view["group"] for view in views]
    assert groups == [
        "Classification",
        "Height provenance",
        "Urban canopy parameters",
        "Confidence",
    ], "groups must follow the committed selector order"


def test_a_continuous_legend_says_what_grey_means() -> None:
    """A null parameter is a reportable state — `aspect_ratio` is null wherever no street reaches a
    building — and every layer paints it the same grey. Without a row for it, the reader has no way
    to learn that grey is "no value" rather than "low"."""
    views = build_views(BREAKS, COLUMNS, MANIFEST["parameters"])
    bsf = next(view for view in views if view["column"] == "building_surface_fraction")

    nodata = [entry for entry in bsf["legend"] if entry.get("nodata")]
    assert len(nodata) == 1
    assert nodata[0]["colour"] == NODATA_COLOUR
    assert nodata[0]["label"] == "no value"


def test_the_categorical_legend_has_no_nodata_row() -> None:
    """The LCZ legend already names every class it can paint, and `NODATA_COLOUR` there would be a
    class that does not exist rather than a value that is missing."""
    views = build_views(BREAKS, COLUMNS, MANIFEST["parameters"])

    assert [entry for entry in views[0]["legend"] if entry.get("nodata")] == []


# ---------------------------------------------------------------------- online basemap


def test_no_online_basemap_means_no_remote_source() -> None:
    """The default. Everything the style names is a relative path."""
    document = style()

    for source in document["sources"].values():
        assert source["type"] != "raster"
        assert "tiles" not in source


def test_an_online_basemap_carries_its_attribution_into_the_source() -> None:
    """MapLibre reads attribution off the source, so a provider that requires it — all of them —
    is only correctly used if it travels with the tiles rather than being written into the page."""
    document = style(online_basemaps=["osm"])
    source = document["sources"]["basemap-raster-osm"]

    assert source["type"] == "raster"
    assert "OpenStreetMap" in source["attribution"]
    assert source["tiles"] == ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"]


def test_an_unknown_basemap_is_refused_by_name() -> None:
    with pytest.raises(KeyError, match="unknown basemap"):
        style(online_basemaps=["not-a-provider"])


def test_the_run_basemap_choice_does_not_include_the_remote_rasters() -> None:
    """The picker offers the remote grounds; the run's own linework is a separate overlay.

    Both the vector layers and the rasters are named `basemap-*`, so collecting the offline set by
    prefix silently put the remote tiles into the offline choice — selecting "run's own linework"
    would then fetch the network, which is the one thing that choice exists to avoid.
    """
    document = style(online_basemaps=["osm", "esri-satellite"], basemap_layers=("water", "streets"))
    base = document["metadata"]["lczkit"]["basemap"]

    assert base["run_layers"] == ["basemap-water", "basemap-streets"]
    ids = [entry["id"] for entry in base["rasters"]]
    assert ids == ["basemap-raster-osm", "basemap-raster-esri-satellite"]
    assert set(ids).isdisjoint(base["run_layers"])


def test_each_provider_gets_its_own_source_carrying_its_own_zoom_and_tile_size() -> None:
    """The reason several grounds cannot share one source whose tiles are swapped at runtime.

    `maxzoom` and `tileSize` live on the source, and they differ per provider — Esri's imagery has
    global coverage to z19 while MapTiler's topo renders to z22. One source would have to pick one
    pair of numbers and be wrong for every provider but that one.
    """
    document = style(online_basemaps=["esri-satellite", "carto-positron"])

    esri = document["sources"]["basemap-raster-esri-satellite"]
    carto = document["sources"]["basemap-raster-carto-positron"]
    assert esri["maxzoom"] == 19
    assert carto["maxzoom"] == 20
    assert [layer["source"] for layer in document["layers"] if layer["type"] == "raster"] == [
        "basemap-raster-esri-satellite",
        "basemap-raster-carto-positron",
    ]


def test_the_rasters_keep_the_order_they_were_configured_in() -> None:
    """It is the order they appear in the reader's dropdown, so it is a decision, not incidental."""
    keys = ["carto-dark", "osm", "esri-satellite"]
    base = style(online_basemaps=keys)["metadata"]["lczkit"]["basemap"]

    assert [entry["key"] for entry in base["rasters"]] == keys


def test_a_keyed_provider_without_a_key_is_refused_rather_than_left_unsubstituted() -> None:
    """The failure this replaces is silent: `{key}` left in a tile URL is a well-formed URL that
    403s on every request, so the site builds cleanly and shows an empty ground with no cause."""
    with pytest.raises(ValueError, match="MAPTILER_API_KEY"):
        style(online_basemaps=["maptiler-hybrid"], maptiler_key=None)


def test_a_key_reaches_the_tile_urls_and_leaves_the_tile_coordinates_alone() -> None:
    """Only `{key}` is substituted — `{z}`, `{x}` and `{y}` belong to MapLibre, and filling them
    here would produce one hard-coded tile repeated across the whole map."""
    document = style(online_basemaps=["maptiler-topo"], maptiler_key="a-test-key")
    (url,) = document["sources"]["basemap-raster-maptiler-topo"]["tiles"]

    assert "key=a-test-key" in url
    assert "{key}" not in url
    assert "{z}" in url and "{x}" in url and "{y}" in url


def test_no_tile_url_anywhere_keeps_a_placeholder() -> None:
    """Every provider at once, so a new one added with a placeholder no code substitutes cannot
    reach a built site by being left out of the test above."""
    document = style(online_basemaps=sorted(PROVIDERS), maptiler_key="a-test-key")

    for name, source in document["sources"].items():
        for url in source.get("tiles", []):
            assert "{key}" not in url, name


def test_a_run_written_before_labels_existed_still_gets_them_on_rebuild() -> None:
    """The three published sites are runs whose manifests predate `ParameterSpec.label`.

    Rebuilding one with a newer lczkit is the natural way to pick up a front-end fix, and if the
    label lookup stopped at the manifest those rebuilds would keep showing exactly the labels the
    fix was for. The packaged registry answers when the run cannot.
    """
    old_manifest_parameters: list[dict[str, str]] = [
        {
            "name": "building_surface_fraction",
            "unit": "fraction",
            "description": "share of unit area under building footprint",
            "reference": "10.1175/BAMS-D-11-00019.1",
        }
    ]

    views = build_views(BREAKS, COLUMNS, old_manifest_parameters)
    bsf = next(view for view in views if view["column"] == "building_surface_fraction")

    assert bsf["label"] == "Building surface fraction"
    assert bsf["unit"] == "fraction", "the run's own unit must still come from the manifest"


def test_a_label_the_run_recorded_beats_the_packaged_one() -> None:
    """The registry is a fallback, not an override. A manifest that named a column differently
    described what that run actually computed, and the site reports the run."""
    renamed = [{"name": "building_surface_fraction", "label": "BSF as this run defined it"}]

    views = build_views(BREAKS, COLUMNS, renamed)
    bsf = next(view for view in views if view["column"] == "building_surface_fraction")

    assert bsf["label"] == "BSF as this run defined it"
