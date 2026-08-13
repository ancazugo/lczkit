"""Placing the areal height products that the Phase 3 cascade's tiers 2-4 read.

CLAUDE.md's Phase 3 has the *user* place each product as a COG under `input/GOB25D/`,
`input/WSF3D/` or `input/GHSL/`. That was written when tiers 2-4 were a specification; Phase 10
runs them over nine cities and three products, and placing twenty-seven windows by hand is not
an instruction anyone can follow. These fetchers do the placing, and they own those three
directories the way `OvertureSource` owns `input/Overture_Maps/` — which is the rule the
departure is made under rather than against.

Every fetcher is cache-first: a file already on disk *is* the answer, and nothing existing is
rewritten, moved or removed. Downloads land on a `.partial` sibling and are renamed only once
complete, so an interrupted fetch can never be mistaken for a cache hit.

None of these classes implements `HeightSource`. They resolve a path; `ArealRasterTier` reads
it. Keeping fetch and read apart is what lets the tier stay offline and testable, and what lets
a user who *has* placed a product by hand skip these entirely.
"""

from __future__ import annotations

import math
import shutil
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import rasterio
from rasterio.merge import merge as merge_rasters

from lczkit.config import (
    GhslProductConfig,
    HeightConfig,
    OpenBuildings25dConfig,
    Settings,
    Wsf3dConfig,
)
from lczkit.protocols import BBox
from lczkit.sources.overture import bbox_key

MOLLWEIDE_TILE_M = 1_000_000.0
"""Side of one GHS-BUILT-H R2023A tile, in metres. Tiles are 10000x10000 cells at 100 m."""

MOLLWEIDE_ORIGIN_X = -18_041_000.0
MOLLWEIDE_ORIGIN_Y = 9_000_000.0
"""Upper-left corner of the R2023A *nominal* tile grid, in ESRI:54009 metres.

Not a guess: read off tile `R4_C19`, bounds `(-41000, 5000000, 959000, 6000000)`, and checked
against five more tiles across four continents.

**Tiles are cropped to their valid data extent, so a tile's own bounds are a subset of its
nominal square.** `R14_C20` is 4000x3000 cells rather than 10000x10000, and `R14_C19` is not
published at all — Mollweide puts both partly outside the world ellipse. That is why
`_verify_tile_position` checks containment rather than equality, and why a missing tile is
treated as "this product has no data here" rather than as an error. An origin wrong by one
whole tile would otherwise return heights from the wrong continent in silence.
"""

_DOWNLOAD_CHUNK = 1 << 22


class HeightProductSource(Protocol):
    """Resolves one areal height product to a local path, fetching it if it is not there.

    `bbox` is lon/lat, matching every other ingestion boundary in the package. Implementations
    return a path readable by `lczkit.heights.raster.zonal_mean`.

    `None` means the product has no coverage over `bbox` and the tier should be left out of the
    cascade — a shorter cascade with an honest `height_completeness`, not a failure. Only a
    regional product can answer that way; the two global ones raise instead, because for them an
    absent tile is a defect rather than a fact about the world.
    """

    @property
    def name(self) -> str:
        """The `height_source` tag of the tier this product backs."""
        ...

    def ensure(self, bbox: BBox) -> Path | None:
        """Local path to a raster covering `bbox`, fetching only what is missing."""
        ...


def _download(url: str, destination: Path) -> Path:
    """Fetch `url` to `destination`, atomically, skipping the work if it is already there.

    The `.partial` rename is the whole point. `input/` is shared with other projects and a
    truncated file that looks like a cache hit is worse than no file at all — the next run would
    read it, get a plausible-looking short raster, and never report a problem.
    """
    if destination.exists():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    with urllib.request.urlopen(url) as response, partial.open("wb") as handle:
        shutil.copyfileobj(response, handle, _DOWNLOAD_CHUNK)
    partial.replace(destination)
    return destination


class Wsf3dSource:
    """Tier 3: WSF-3D V02 building height, one global file.

    DLR publishes the global product as a tiled GeoTIFF with overviews, so there is nothing to
    clip: `zonal_mean`'s `covering_window` reads a city-sized window straight out of the 2.1 GB
    file. That is why `ensure` ignores its `bbox` — the same path answers for every city, and a
    per-window clip would be a second copy of data already on disk.

    Values are int16 decimetres with nodata -32767 (DLR, `README_BuildingHeight.txt`), which is
    why `ArealTierConfig` for this tier carries `scale=0.1`.
    """

    def __init__(self, settings: Settings, config: Wsf3dConfig | None = None) -> None:
        self.config = config or settings.height_products.wsf3d
        self.directory = settings.source_dir(self.config.source_dir_name)

    @property
    def name(self) -> str:
        return self.config.tier_name

    def ensure(self, bbox: BBox) -> Path:
        del bbox  # one global file answers for every window; see the class docstring
        return _download(self.config.url, self.directory / self.config.filename)


class GhslBuiltHSource:
    """Tier 4: GHS-BUILT-H ANBH R2023A, resolved to the Mollweide tiles covering a bbox.

    ANBH is `BUVOL / BUSURF` — building volume over *built-up* surface, so it is the mean height
    of the built fabric in a cell rather than a height smeared across open ground. That is the
    right quantity to hand a building, and the reason this reads ANBH and not the gross AGBH
    published alongside it. Float32 metres, nodata 255 (GHSL Data Package 2023, p. 36).

    Tiles are 1000 km square, so one tile covers a city window in the ordinary case and the
    fetcher returns it untouched. A window straddling a tile boundary gets a small merged clip
    instead — bbox-keyed, alongside the tiles it came from.
    """

    def __init__(self, settings: Settings, config: GhslProductConfig | None = None) -> None:
        self.config = config or settings.height_products.ghsl
        self.directory = settings.source_dir(self.config.source_dir_name)

    @property
    def name(self) -> str:
        return self.config.tier_name

    def tiles_for(self, bbox: BBox) -> list[tuple[int, int]]:
        """The `(row, col)` tiles covering `bbox`, in a stable order.

        The bbox is reprojected corner-wise and then densified along its edges: Mollweide is not
        a rectangle-preserving projection, so a lon/lat box maps to a curved quadrilateral whose
        extreme x can lie partway along an edge rather than at a corner. Sampling the edges is
        cheap insurance against dropping a tile the window genuinely touches.
        """
        from pyproj import CRS, Transformer

        transformer = Transformer.from_crs(
            CRS.from_epsg(4326), CRS.from_user_input(self.config.crs), always_xy=True
        )
        minx, miny, maxx, maxy = bbox
        steps = np.linspace(0.0, 1.0, 21)
        lons = np.concatenate([minx + (maxx - minx) * steps, np.full(21, minx), np.full(21, maxx)])
        lats = np.concatenate([np.full(21, miny), miny + (maxy - miny) * steps, np.full(21, maxy)])
        lons = np.concatenate([lons, minx + (maxx - minx) * steps])
        lats = np.concatenate([lats, np.full(21, maxy)])
        xs, ys = transformer.transform(lons, lats)

        columns = range(
            int(math.floor((float(np.min(xs)) - MOLLWEIDE_ORIGIN_X) / MOLLWEIDE_TILE_M)) + 1,
            int(math.floor((float(np.max(xs)) - MOLLWEIDE_ORIGIN_X) / MOLLWEIDE_TILE_M)) + 2,
        )
        rows = range(
            int(math.floor((MOLLWEIDE_ORIGIN_Y - float(np.max(ys))) / MOLLWEIDE_TILE_M)) + 1,
            int(math.floor((MOLLWEIDE_ORIGIN_Y - float(np.min(ys))) / MOLLWEIDE_TILE_M)) + 2,
        )
        return [(row, column) for row in rows for column in columns]

    def tile_name(self, row: int, column: int) -> str:
        return self.config.tile_template.format(row=row, column=column)

    def _fetch_tile(self, row: int, column: int) -> Path | None:
        """Download and unzip one tile, or return `None` where the product publishes none.

        Not every nominal tile exists: `R14_C19` falls outside the Mollweide world ellipse and is
        simply absent. That is the same statement as a nodata cell — "this product has no data
        here" — so it returns `None` and the caller carries on with whatever tiles it did get.
        """
        name = self.tile_name(row, column)
        target = self.directory / f"{name}.tif"
        if not target.exists():
            try:
                archive = _download(
                    self.config.url_template.format(name=name), self.directory / f"{name}.zip"
                )
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return None
                raise
            with zipfile.ZipFile(archive) as bundle:
                member = next(item for item in bundle.namelist() if item.endswith(f"{name}.tif"))
                partial = target.with_suffix(".tif.partial")
                with bundle.open(member) as source, partial.open("wb") as handle:
                    shutil.copyfileobj(source, handle, _DOWNLOAD_CHUNK)
                partial.replace(target)
        _verify_tile_position(target, row, column)
        return target

    def ensure(self, bbox: BBox) -> Path:
        tiles = self.tiles_for(bbox)
        paths = [path for path in (self._fetch_tile(*tile) for tile in tiles) if path is not None]
        if not paths:
            raise FileNotFoundError(
                f"GHS-BUILT-H publishes no tile covering {bbox}; the nominal grid wanted "
                f"{[f'R{row}_C{column}' for row, column in tiles]}."
            )
        if len(paths) == 1:
            return paths[0]
        clip = self.directory / "clips" / f"{self.config.tier_name}_{bbox_key(bbox)}.tif"
        return _merge_windows(paths, clip, bounds=self._mollweide_bounds(bbox))

    def _mollweide_bounds(self, bbox: BBox) -> tuple[float, float, float, float]:
        """`bbox` in the product's own CRS, padded a cell, for a bounded merge."""
        from pyproj import CRS, Transformer

        transformer = Transformer.from_crs(
            CRS.from_epsg(4326), CRS.from_user_input(self.config.crs), always_xy=True
        )
        minx, miny, maxx, maxy = bbox
        xs, ys = transformer.transform(
            [minx, maxx, minx, maxx, (minx + maxx) / 2, (minx + maxx) / 2],
            [miny, miny, maxy, maxy, miny, maxy],
        )
        pad = 200.0
        return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


def _verify_tile_position(path: Path, row: int, column: int) -> None:
    """Assert a downloaded tile lies inside the nominal square its name claims.

    Containment, not equality: tiles are cropped to their valid data extent, so `R14_C20` is
    400x300 km inside its nominal 1000 km square. What this still catches is the one failure
    mode that matters — an origin wrong by a whole tile, which would return heights from the
    wrong continent without anything looking amiss.
    """
    expected_x = MOLLWEIDE_ORIGIN_X + (column - 1) * MOLLWEIDE_TILE_M
    expected_y = MOLLWEIDE_ORIGIN_Y - (row - 1) * MOLLWEIDE_TILE_M
    with rasterio.open(path) as src:
        bounds = src.bounds
    inside = (
        bounds.left >= expected_x - 1.0
        and bounds.right <= expected_x + MOLLWEIDE_TILE_M + 1.0
        and bounds.top <= expected_y + 1.0
        and bounds.bottom >= expected_y - MOLLWEIDE_TILE_M - 1.0
    )
    if not inside:
        raise ValueError(
            f"{path.name} covers {tuple(bounds)}, which is not inside the nominal square the "
            f"R2023A grid gives R{row}_C{column}: "
            f"({expected_x}, {expected_y - MOLLWEIDE_TILE_M}, "
            f"{expected_x + MOLLWEIDE_TILE_M}, {expected_y}). The tiling constants in this "
            "module do not match the product on disk."
        )


def _merge_windows(
    paths: list[Path],
    destination: Path,
    bounds: tuple[float, float, float, float] | None = None,
) -> Path:
    """Merge several rasters into one, optionally cropped to `bounds` in their own CRS.

    `bounds` is what keeps this affordable: merging two whole 1000 km GHS-BUILT-H tiles would
    write 800 MB to answer a 30 km question. Passing `None` merges in full, which is what the
    Earth Engine sub-windows want — they are already the size of the answer.
    """
    if destination.exists():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    sources = [rasterio.open(path) for path in paths]
    try:
        array, transform = merge_rasters(sources, bounds=bounds)
        profile = sources[0].profile
    finally:
        for src in sources:
            src.close()
    profile.update(
        height=array.shape[1],
        width=array.shape[2],
        transform=transform,
        count=array.shape[0],
        compress="deflate",
        tiled=True,
    )
    partial = destination.with_suffix(".tif.partial")
    with rasterio.open(partial, "w", **profile) as out:
        out.write(array)
    partial.replace(destination)
    return destination


class OpenBuildings25dSource:
    """Tier 2: Google Open Buildings 2.5D Temporal, exported per window from Earth Engine.

    The only fine-resolution tier, and the only one distributed exclusively through Earth Engine
    — there is no public bucket. `building_height` is metres above terrain in `[0, 100]` at an
    effective 4 m (the rasters are served on a 0.5 m grid), annual 2016-2023, covering Africa,
    South and South-East Asia, Latin America and the Caribbean. Nothing outside those regions.

    Exported in a grid of sub-windows because a 900 km2 city at 4 m is 56 Mpx, over Earth
    Engine's per-request caps on both pixel count and payload size. The grid is sized from the
    configured caps rather than fixed, so the failure mode is a smaller request rather than an
    opaque server error.

    Absence is a real answer here: a window with no imagery returns no path, and the caller
    leaves the tier out of that city's cascade rather than failing the city.
    """

    def __init__(self, settings: Settings, config: OpenBuildings25dConfig | None = None) -> None:
        self.config = config or settings.height_products.gob25d
        self.directory = settings.source_dir(self.config.source_dir_name)
        self.project = settings.land_cover.gee_project

    @property
    def name(self) -> str:
        return self.config.tier_name

    def path_for(self, bbox: BBox) -> Path:
        return self.directory / f"{self.config.tier_name}_{self.config.year}_{bbox_key(bbox)}.tif"

    def sub_windows(self, bbox: BBox) -> list[BBox]:
        """`bbox` split into a grid small enough for one Earth Engine download each.

        Sized from the pixel cap, which binds before the byte cap for a float32 band: the grid
        is the smallest square one for which every cell is under both.
        """
        minx, miny, maxx, maxy = bbox
        metres = max(
            (maxx - minx) * 111_320.0 * math.cos(math.radians((miny + maxy) / 2)),
            (maxy - miny) * 110_540.0,
        )
        pixels = (metres / self.config.scale_m) ** 2
        by_pixels = math.sqrt(pixels / self.config.max_pixels_per_request)
        by_bytes = math.sqrt(pixels * 4 / self.config.max_bytes_per_request)
        side = max(1, math.ceil(max(by_pixels, by_bytes)))
        return [
            (
                minx + (maxx - minx) * i / side,
                miny + (maxy - miny) * j / side,
                minx + (maxx - minx) * (i + 1) / side,
                miny + (maxy - miny) * (j + 1) / side,
            )
            for i in range(side)
            for j in range(side)
        ]

    def ensure(self, bbox: BBox) -> Path | None:
        destination = self.path_for(bbox)
        if destination.exists():
            return destination

        import ee

        if self.project is None:
            raise ValueError(
                "No Earth Engine project is set. Put GEE_PROJECT_NAME in .env, or set "
                "`settings.land_cover.gee_project` explicitly."
            )
        ee.Initialize(project=self.project)

        region = ee.Geometry.Rectangle(list(bbox))
        collection = (
            ee.ImageCollection(self.config.collection)
            .filterBounds(region)
            .filter(ee.Filter.calendarRange(self.config.year, self.config.year, "year"))
        )
        if int(collection.size().getInfo()) == 0:
            return None

        band = self.config.band
        mosaic = collection.select(band).mosaic()
        crs = ee.Image(collection.first()).select(band).projection().crs().getInfo()

        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.parent / f".{destination.stem}_parts"
        staging.mkdir(parents=True, exist_ok=True)
        try:
            parts = [
                self._download_part(mosaic, window, crs, staging, index)
                for index, window in enumerate(self.sub_windows(bbox))
            ]
            return _merge_windows([part for part in parts if part is not None], destination)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _download_part(
        self, mosaic: Any, window: BBox, crs: str, staging: Path, index: int
    ) -> Path | None:
        """One sub-window as a GeoTIFF, or `None` where Earth Engine has nothing to give.

        An empty sub-window is normal at a city's edge and is not an error; it simply drops out
        of the merge.
        """
        import ee

        part = staging / f"part_{index:03d}.tif"
        if part.exists():
            return part
        url = mosaic.getDownloadURL(
            {
                "region": ee.Geometry.Rectangle(list(window)),
                "scale": self.config.scale_m,
                "crs": crs,
                "format": "GEO_TIFF",
            }
        )
        try:
            _download(url, part)
        except OSError:
            return None
        with rasterio.open(part) as src:
            if src.width == 0 or src.height == 0:
                return None
        return part


def resolve_areal_tiers(
    settings: Settings, bbox: BBox, config: HeightConfig | None = None
) -> tuple[HeightConfig, dict[str, str | None]]:
    """Place every enabled areal tier's product for `bbox` and return a ready `HeightConfig`.

    The missing half of `build_cascade`, which reads `filename` and never sets it. Without this
    the only route from a configured tier to a raster on disk was a private helper in one
    experiment script, so the package's own default cascade could not actually run — a shipped
    default nothing exercises is a claim, not a behaviour.

    Tiers run in `config.areal_tiers` order. A tier with `enabled=False` is left out, and so is
    one whose product has no coverage here — Open Buildings stops at Europe — but for different
    reasons that stay separable: the first shows as `enabled=False` in the serialised config, the
    second as a `None` in the returned record. A tier configured to read a file that is not there
    is neither, and still raises in `build_cascade`.

    `confidence` is deliberately not filled in. It is an ordinal ranking of measurement quality
    with no published value behind it, exactly like the two Overture confidences, and a default
    cascade that invented one would write a quality claim nobody chose into every manifest. Set
    it on the config and `build_cascade` accepts it; leave it unset and `build_cascade` says so.
    """
    resolved = (config or settings.heights).model_copy(deep=True)
    fetchers: dict[str, HeightProductSource] = {
        settings.height_products.gob25d.tier_name: OpenBuildings25dSource(settings),
        settings.height_products.wsf3d.tier_name: Wsf3dSource(settings),
        settings.height_products.ghsl.tier_name: GhslBuiltHSource(settings),
    }

    placed: dict[str, str | None] = {}
    tiers = []
    for tier in resolved.areal_tiers:
        if not tier.enabled:
            continue
        fetcher = fetchers.get(tier.name)
        if fetcher is None:
            raise KeyError(
                f"height tier {tier.name!r} is enabled but no fetcher owns it; place its raster "
                f"under input/{tier.source_dir_name}/ and set `filename` by hand instead."
            )
        path = fetcher.ensure(bbox)
        placed[tier.name] = str(path) if path is not None else None
        if path is None:
            continue
        tier.filename = str(path.relative_to(settings.source_dir(tier.source_dir_name)))
        tiers.append(tier)
    resolved.areal_tiers = tiers
    return resolved, placed
