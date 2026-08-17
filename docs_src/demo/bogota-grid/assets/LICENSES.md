# Vendored front-end assets

These files are third-party source, committed into the repository and shipped in the wheel. They are
**vendored, not fetched**: CLAUDE.md requires the site to open with no CDN link and no network, and
a `<script src="https://...">` would break that on the first day a host went away.

Both are permissive and compatible with lczkit's own MIT licence. Neither is a Python dependency —
nothing in the package imports them — so neither appears in `pyproject.toml`.

| file | package | version | SPDX | source |
|---|---|---|---|---|
| `vendor/maplibre-gl.js`, `vendor/maplibre-gl.css` | maplibre-gl | 5.24.0 | BSD-3-Clause | <https://github.com/maplibre/maplibre-gl-js> |
| `vendor/maplibre-gl.LICENSE.txt` | maplibre-gl | 5.24.0 | BSD-3-Clause | as above |
| `vendor/pmtiles.js` | pmtiles | 4.4.1 | BSD-3-Clause | <https://github.com/protomaps/PMTiles> |
| `vendor/pmtiles.LICENSE` | pmtiles | 4.4.1 | BSD-3-Clause | as above |

The PMTiles *specification* is public domain / CC0; the BSD-3-Clause text covers the reference
implementations, of which `pmtiles.js` is one.

## Why MapLibre 5 rather than 6

MapLibre 6 ships ESM only — `maplibre-gl.mjs` plus a shared chunk and a separate worker module, all
resolved at load time through the module graph. MapLibre 5 ships a single UMD bundle with the worker
inlined, loaded by one classic `<script>` tag.

For a directory that has to still render years from now, after being copied, zipped, and served from
somewhere nobody anticipated, one file with no resolution step is worth more than the newer major
version. It is also the difference between a site whose asset list can be checked by looking at it
and one whose asset list is an implication of a bundler's output.

## Regenerating

```sh
V=5.24.0; P=4.4.1
curl -sSfL -o vendor/maplibre-gl.js          https://unpkg.com/maplibre-gl@$V/dist/maplibre-gl.js
curl -sSfL -o vendor/maplibre-gl.css         https://unpkg.com/maplibre-gl@$V/dist/maplibre-gl.css
curl -sSfL -o vendor/maplibre-gl.LICENSE.txt https://unpkg.com/maplibre-gl@$V/dist/LICENSE.txt
curl -sSfL -o vendor/pmtiles.js              https://unpkg.com/pmtiles@$P/dist/pmtiles.js
curl -sSfL -o vendor/pmtiles.LICENSE         https://raw.githubusercontent.com/protomaps/PMTiles/main/LICENSE
```

Then strip the trailing `sourceMappingURL` comment from each `.js` and `.css`: the `.map` files are
not shipped, and a comment pointing at an absent sibling is a dangling reference that
`test_site_has_no_external_references` would have to special-case.
