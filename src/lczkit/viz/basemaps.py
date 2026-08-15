"""Optional online raster base layers, and the attribution each one obliges the site to carry.

**Read this before enabling one.** CLAUDE.md's anti-pattern list requires the site to open "with no
network and no software the user must install, and remain valid years from now", and that is not a
preference — it is what makes a built site archivable beside a paper. Everything here breaks it, so
nothing here is on by default.

`VizConfig.online_basemap` is `None` unless a caller asks, and with it unset the emitted site
contains no external reference at all — a test asserts exactly that, and a second test asserts that
when one *is* configured the only file mentioning a remote host is `style.json`. The front end
treats the raster as a layer that may fail: tiles that do not load leave every other layer working
and say so, rather than producing a blank map.

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

PROVIDERS: dict[str, BasemapProvider] = {
    provider.key: provider for provider in (OPENSTREETMAP, CARTO_POSITRON, CARTO_DARK_MATTER)
}


def provider(key: str) -> BasemapProvider:
    """The provider called `key`, or a `KeyError` naming the ones that exist."""
    try:
        return PROVIDERS[key]
    except KeyError:
        raise KeyError(f"unknown basemap {key!r}; choose from {sorted(PROVIDERS)}") from None


def external_hosts() -> frozenset[str]:
    """Every host any provider can contact.

    Exists so `tests/test_viz_site.py` can assert that a site configured with one of these reaches
    that provider and nothing else, rather than dropping the no-external-reference guarantee.
    """
    return frozenset(host for entry in PROVIDERS.values() for host in entry.hosts)
