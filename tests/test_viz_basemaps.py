"""The base-map provider table, and the config that selects from it.

**Why a whole file for a table of constants.** Every entry here is a promise about somebody else's
server, and three of the promises are load-bearing in ways nothing else would catch: `hosts` is what
the site's no-external-reference test iterates, so a provider that forgets it silently stops being
covered by the guarantee it exists under; `licence` is what the CLI prints, and this package refuses
to ship a ground it cannot name a licence for; and `{key}` is the difference between a working base
map and one that 403s per tile while the build reports success.
"""

from __future__ import annotations

import pytest

from lczkit.config import VizConfig
from lczkit.viz.basemaps import PROVIDERS, external_hosts, provider, tile_urls


def test_every_provider_records_a_licence_and_an_attribution() -> None:
    """The reason this package ships no Google tiles.

    `mt*.google.com/vt` is undocumented and using it outside a Google Maps API breaks their terms,
    so it has no licence string to put here — and a table whose point is that every ground records
    one cannot carry an entry that does not.
    """
    for key, entry in PROVIDERS.items():
        assert entry.licence.strip(), key
        assert entry.attribution.strip(), key
        assert entry.key == key


def test_every_provider_names_the_hosts_it_contacts() -> None:
    """`external_hosts()` is what `test_viz_site` iterates to assert the site reaches this provider
    and nothing else. A provider with an empty `hosts` passes that test by not being in it."""
    for key, entry in PROVIDERS.items():
        assert entry.hosts, f"{key} names no hosts, so nothing checks where it reaches"
        for url in entry.tiles:
            assert any(host in url for host in entry.hosts), f"{key}: {url}"

    assert external_hosts() == {host for entry in PROVIDERS.values() for host in entry.hosts}


def test_a_keyed_provider_says_which_variable_holds_its_key() -> None:
    """So the error names the thing the reader has to set, rather than saying a key is missing."""
    for key, entry in PROVIDERS.items():
        assert entry.requires_key == ("{key}" in "".join(entry.tiles)), key
        if entry.requires_key:
            assert entry.key_name, key


def test_tile_urls_substitutes_only_the_key() -> None:
    urls = tile_urls(provider("maptiler-hybrid"), "a-key")

    assert urls == ["https://api.maptiler.com/maps/hybrid/256/{z}/{x}/{y}.jpg?key=a-key"]


def test_tile_urls_refuses_a_keyed_provider_with_no_key() -> None:
    """Named, so the message says what to set. An empty string counts as absent: a `.env` line with
    nothing after the `=` is a likelier mistake than a provider that wants a blank key."""
    for missing in (None, ""):
        with pytest.raises(ValueError, match="MAPTILER_API_KEY"):
            tile_urls(provider("maptiler-topo"), missing)


def test_tile_urls_leaves_a_keyless_provider_alone() -> None:
    assert tile_urls(provider("osm"), None) == ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"]


def test_the_esri_endpoint_keeps_its_transposed_axis_order() -> None:
    """Pinned because it is the one URL here that is not `{z}/{x}/{y}`, and transposing it returns
    valid imagery of the wrong place — an error that renders cleanly and raises nothing."""
    (url,) = provider("esri-satellite").tiles

    assert url.endswith("/tile/{z}/{y}/{x}")


# ------------------------------------------------------------------- selecting them in config


def test_no_basemap_is_the_default() -> None:
    """The default the whole offline guarantee rests on."""
    assert VizConfig().basemap_keys == []


def test_basemap_keys_keeps_the_configured_order() -> None:
    keys = ["carto-dark", "osm", "maptiler-topo"]

    assert VizConfig(online_basemaps=keys).basemap_keys == keys


def test_the_deprecated_singular_is_folded_in_rather_than_ignored() -> None:
    """It is what runs built before the list existed recorded in their manifests, and `build_site`
    re-validates an archived manifest to rebuild a site. Pydantic ignores unknown fields, so
    dropping the field would make an archived run's ground disappear on rebuild with nothing said.
    """
    assert VizConfig(online_basemap="osm").basemap_keys == ["osm"]
    assert VizConfig(online_basemap="osm", online_basemaps=["carto-dark"]).basemap_keys == [
        "osm",
        "carto-dark",
    ]
    # Naming the same provider both ways is one entry, not a duplicated dropdown row.
    assert VizConfig(online_basemap="osm", online_basemaps=["osm"]).basemap_keys == ["osm"]


def test_an_unknown_basemap_is_refused_at_config_time() -> None:
    """Before a run rather than after it: the site is the last stage, so a typo caught here costs
    nothing and a typo caught there costs the whole pipeline."""
    with pytest.raises(ValueError, match="unknown basemap"):
        VizConfig(online_basemaps=["osm", "not-a-provider"])

    with pytest.raises(ValueError, match="unknown basemap"):
        VizConfig(online_basemap="not-a-provider")
