"""Phase 7: a self-contained, archivable map site built from one run's outputs.

`build_site(run_dir)` writes `<run_dir>/site/` — an HTML page, a vendored MapLibre front end,
PMTiles tilesets and a copy of the run manifest. It opens with a Python interpreter and nothing
else, reaches no network, and needs no API key.

See `lczkit.viz.site` for what it contains and why, and `lczkit.viz.serve` for why a local server
is required rather than a bare `file://` open.
"""

from __future__ import annotations

from lczkit.viz.serve import RangeRequestHandler, serve
from lczkit.viz.site import SITE_DIR, SiteReport, build_site
from lczkit.viz.tiles import TilesetReport, TippecanoeMissingError, tippecanoe_available

__all__ = [
    "SITE_DIR",
    "RangeRequestHandler",
    "SiteReport",
    "TilesetReport",
    "TippecanoeMissingError",
    "build_site",
    "serve",
    "tippecanoe_available",
]
