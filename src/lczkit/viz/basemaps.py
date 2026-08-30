"""Optional online raster base layers, and the attribution each one obliges the site to carry.

**Read this before enabling one.** A built site opens with no network and no software the reader
must install, and stays valid years from now. That is not a preference — it is what makes a site
archivable beside a paper. Everything here breaks it, so nothing here is on by default.

`VizConfig.online_basemaps` is empty unless a caller asks, and with it empty the emitted site
contains no external reference at all — a test asserts exactly that, and a second test asserts that
when one *is* configured the only file mentioning a remote host is `style.json`. The front end
treats each raster as a layer that may fail: tiles that do not load leave every other layer working
and say so, rather than producing a blank map.

Configuring several is normal and costs nothing until one is chosen: each becomes its own hidden
source and layer, and the page's base picker switches between them. Sizes and zoom limits differ per
provider, which is why they cannot share one source whose tiles are swapped at runtime.

**Two providers need an API key, and the key ships in the site.** MapLibre fetches tiles from the
browser, so `style.json` carries the key in plain text and anyone holding the directory holds the
key. It is deliberately kept out of the run manifest — see `VizConfig.maptiler_key` — but that
bounds the exposure rather than removing it, and a key used this way should be origin-restricted at
the provider.

**A site built with one of these is not archival.** The provider outlives the run only as long as it
chooses to. The run's own Overture linework stays available in the same site and remains the default
ground, so a reader who opens an old site offline still sees the geometry the classification was
computed from.

**Tile usage policies are the caller's obligation, not this module's.** Each provider records its
licence and the terms in its own docstring. The OpenStreetMap Foundation's tile servers in
particular are a donated resource with an explicit usage policy: fine for reading a map, not for
bulk or automated fetching, and a heavy consumer is expected to run its own tiles.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BasemapProvider:
    """One remote raster tile source, with everything the style and the page need to use it."""

    key: str

    label: str
    """What the layer is called in the front end's base picker."""

    tiles: tuple[str, ...]
    """Tile URL templates. More than one is a subdomain rotation."""

    attribution: str
    """Shown by MapLibre's attribution control. Required by every provider here, and the reason
    the control is switched on whenever a raster basemap is configured."""

    licence: str

    max_zoom: int = 19

    tile_size: int = 256

    terms: str = ""
    """The usage constraint a caller takes on by selecting this provider."""

    dark: bool = False
    """Whether the tiles are dark. The unit fill and the LCZ palette are built for a dark ground,
    so a light basemap needs the fill drawn more opaquely to stay legible."""

    hosts: tuple[str, ...] = field(default_factory=tuple)
    """The hosts this provider contacts, so a test can assert the site reaches nothing else."""

    requires_key: bool = False
    """Whether `tiles` carry a `{key}` placeholder that must be filled before the site is written.

    `lczkit.viz.style` substitutes it and raises when it cannot, because the failure is otherwise
    silent: a tile URL still containing `{key}` is a well-formed URL that returns 403 per tile, and
    MapLibre reports that as an empty basemap rather than as a configuration error."""

    key_name: str = ""
    """The environment variable holding this provider's key, named in the error when it is absent.

    Documentation only — nothing in this module reads the environment. Every environment read
    happens in the config layer, so `lczkit.config.maptiler_key()` is what actually resolves
    it."""


OPENSTREETMAP = BasemapProvider(
    key="osm",
    label="OpenStreetMap",
    tiles=("https://tile.openstreetmap.org/{z}/{x}/{y}.png",),
    attribution=(
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    ),
    licence="ODbL 1.0 (data), CC-BY-SA 2.0 (tiles)",
    max_zoom=19,
    terms=(
        "The OSMF tile servers are a donated resource under an explicit usage policy: acceptable "
        "for a person reading a map, not for bulk or automated downloading. A site that will be "
        "opened often should point at its own tiles instead."
    ),
    hosts=("tile.openstreetmap.org",),
)
"""The obvious choice, and the one to be most careful with — see `terms`."""

CARTO_POSITRON = BasemapProvider(
    key="carto-positron",
    label="Carto Positron (light)",
    tiles=(
        "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
        "https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
        "https://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
    ),
    attribution=(
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, '
        '© <a href="https://carto.com/attributions">CARTO</a>'
    ),
    licence="ODbL 1.0 (data), CC-BY 3.0 (style)",
    max_zoom=20,
    dark=False,
    hosts=("a.basemaps.cartocdn.com", "b.basemaps.cartocdn.com", "c.basemaps.cartocdn.com"),
)
"""Deliberately muted, which is the point: a basemap under a choropleth should not compete with it.
Light, so the front end raises the unit fill's opacity to keep the LCZ palette readable over it."""

CARTO_DARK_MATTER = BasemapProvider(
    key="carto-dark",
    label="Carto Dark Matter",
    tiles=(
        "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
    ),
    attribution=(
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, '
        '© <a href="https://carto.com/attributions">CARTO</a>'
    ),
    licence="ODbL 1.0 (data), CC-BY 3.0 (style)",
    max_zoom=20,
    dark=True,
    hosts=("a.basemaps.cartocdn.com", "b.basemaps.cartocdn.com", "c.basemaps.cartocdn.com"),
)
"""The best fit for this site's palette, which was built for a light figure on a dark ground."""

ESRI_WORLD_IMAGERY = BasemapProvider(
    key="esri-satellite",
    label="Esri World Imagery (satellite)",
    # Note the axis order: this endpoint is `{z}/{y}/{x}`, not the `{z}/{x}/{y}` every other
    # provider here uses. Transposing it returns valid imagery of the wrong place, which is the
    # kind of error that survives review because nothing raises.
    tiles=(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/"
        "MapServer/tile/{z}/{y}/{x}",
    ),
    attribution=(
        'Imagery © <a href="https://www.esri.com">Esri</a>, Maxar, Earthstar Geographics, '
        "and the GIS User Community"
    ),
    licence="Esri Terms of Use — free to use with attribution",
    # Measured, not assumed: z20 returns real imagery over Berlin, while z21 and z22 return an
    # identical 2 521-byte placeholder, so 19 is the last level with global coverage behind it.
    max_zoom=19,
    terms=(
        "Esri's World Imagery service is free to use in a map that carries its attribution, which "
        "this site does. It is not a bulk imagery source and Esri may rate-limit or withdraw it."
    ),
    hosts=("server.arcgisonline.com",),
)
"""Satellite imagery without a key, and the reason this package ships no Google tiles.

Google's `mt*.google.com/vt` endpoint is undocumented and using it outside a Google Maps API breaks
their terms of service, so it cannot carry a licence string and has no place in a table whose point
is that every ground records one."""

MAPTILER_HYBRID = BasemapProvider(
    key="maptiler-hybrid",
    label="MapTiler Satellite Hybrid",
    tiles=("https://api.maptiler.com/maps/hybrid/256/{z}/{x}/{y}.jpg?key={key}",),
    attribution=(
        '© <a href="https://www.maptiler.com/copyright/">MapTiler</a> '
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    ),
    licence="MapTiler Cloud terms — requires an API key",
    # Imagery, so it stops resolving before the vector-derived maps do: z21 and z22 are served but
    # are server-side upsampling, which MapLibre does for free from z20.
    max_zoom=20,
    terms=(
        "Requires a MapTiler API key, which is written into the site's style.json in plain text "
        "because the browser fetches the tiles. Anyone given the site directory has the key: "
        "restrict it by origin in the MapTiler console, or hand out a site built without it."
    ),
    hosts=("api.maptiler.com",),
    requires_key=True,
    key_name="MAPTILER_API_KEY",
)
"""Satellite imagery with roads and place names over it — the closest thing here to what people
mean by "Google satellite", from a provider whose terms permit it."""

MAPTILER_TOPO = BasemapProvider(
    key="maptiler-topo",
    label="MapTiler Topo",
    tiles=("https://api.maptiler.com/maps/topo-v2/256/{z}/{x}/{y}.png?key={key}",),
    attribution=(
        '© <a href="https://www.maptiler.com/copyright/">MapTiler</a> '
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    ),
    licence="MapTiler Cloud terms — requires an API key",
    # Rendered from vector data rather than photographed, so every level is a real render.
    max_zoom=22,
    terms=(
        "Requires a MapTiler API key, which is written into the site's style.json in plain text "
        "because the browser fetches the tiles. Anyone given the site directory has the key: "
        "restrict it by origin in the MapTiler console, or hand out a site built without it."
    ),
    hosts=("api.maptiler.com",),
    requires_key=True,
    key_name="MAPTILER_API_KEY",
)
"""Terrain shading and contours. The one ground here that shows relief, which is the context an LCZ
map most often lacks: a valley floor and a hillside classify alike and behave differently."""

PROVIDERS: dict[str, BasemapProvider] = {
    provider.key: provider
    for provider in (
        OPENSTREETMAP,
        CARTO_POSITRON,
        CARTO_DARK_MATTER,
        ESRI_WORLD_IMAGERY,
        MAPTILER_HYBRID,
        MAPTILER_TOPO,
    )
}


DEFAULT_BASEMAP_KEYS: tuple[str, ...] = tuple(
    key for key, entry in PROVIDERS.items() if not entry.requires_key
)
"""What `lczkit run` and `lczkit site build` offer when the caller names nothing.

**Derived from `requires_key` rather than listed, because that is the rule.** A ground that needs no
key costs a reader nothing to be offered and publishes no secret; a keyed one writes an API key into
the built site, which is a decision someone has to make on purpose. A keyless provider added later
joins this set by being keyless, and a keyed one cannot join it by being forgotten.

**This is a command-line default, not the library's.** `VizConfig.online_basemaps` is still empty by
default, so `build_site()` and a rebuild of an archived manifest reach no network unless told to —
that is the property the no-external-reference test pins, and it is unchanged. A site built by the
command line names these tile hosts in its `style.json`; a site built through the library names
none. Pass `--basemap none` for an archival build.
"""


def provider(key: str) -> BasemapProvider:
    """The provider called `key`, or a `KeyError` naming the ones that exist."""
    try:
        return PROVIDERS[key]
    except KeyError:
        raise KeyError(f"unknown basemap {key!r}; choose from {sorted(PROVIDERS)}") from None


def tile_urls(entry: BasemapProvider, api_key: str | None) -> list[str]:
    """`entry`'s tile templates with `{key}` filled in, or a `ValueError` naming the variable.

    `{z}`, `{x}` and `{y}` are left alone — MapLibre substitutes those per tile, and only `{key}`
    is replaced here. Raising when a keyed provider has no key is the point of the function: an
    unsubstituted template is a well-formed URL that 403s on every tile, so the site would build
    cleanly and show an empty basemap with nothing anywhere saying why.
    """
    if not entry.requires_key:
        return list(entry.tiles)
    if not api_key:
        raise ValueError(
            f"base map {entry.key!r} needs an API key; set {entry.key_name} in your .env "
            f"(or drop {entry.key!r} from the configured base maps)"
        )
    return [url.replace("{key}", api_key) for url in entry.tiles]


def external_hosts() -> frozenset[str]:
    """Every host any provider can contact.

    Exists so `tests/test_viz_site.py` can assert that a site configured with one of these reaches
    that provider and nothing else, rather than dropping the no-external-reference guarantee.
    """
    return frozenset(host for entry in PROVIDERS.values() for host in entry.hosts)
