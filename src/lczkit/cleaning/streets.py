"""Street-network simplification via `neatnet`, whole-extent and tiled.

`neatnet` owns its own tuning parameters (node-merge tolerance, continuity-stroke angle
threshold, and a dozen others) as documented package defaults — lczkit does not proxy them
into config; doing so would wrap an entire downstream library's parameter surface for no
current need.

Two entry points, same result shape:

- `simplify_streets` runs `neatify` over the whole extent. Correct at any size, and the only
  thing that was available before Phase 8, but superlinear — see `lczkit.cleaning.tiles`.
- `simplify_streets_tiled` splits the extent, simplifies each tile independently over a
  buffered window, and stitches the cores back together.

**The tiled path pins the face-artifact threshold globally.** `neatnet` derives that threshold
from the distribution of face-artifact-index values across whatever network it is handed — a
kernel-density valley — so a tile computes a *different* threshold from the whole extent. On a
2x2 tiling of 16 km2 of Berlin the whole extent found no valley and fell back to 7.0, while two
of the four tiles found 8.10 and 7.58: a face with an index of 7.5 would have been an artifact
in one tile and ordinary urban fabric in the run next to it. Computing the threshold once on the
full network and passing it into every tile removes that class of seam disagreement outright,
and it is cheap — artifact detection is 0.2 percent of `neatify`'s cost at 100 km2.
"""

from __future__ import annotations

import os
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import geopandas as gpd
import neatnet
import numpy as np
import pandas as pd
import shapely
from pyproj import CRS
from shapely.geometry.base import BaseGeometry

from lczkit.cleaning.report import CleaningStep
from lczkit.cleaning.tiles import Tile, build_tiles, layer_extent, shared_edges, subset
from lczkit.crs import assert_projected_crs

ARTIFACT_THRESHOLD_FALLBACK = 7.0
"""`neatnet.neatify`'s own default for when no face-artifact-index valley is found.

Restated here because the tiled path resolves the threshold itself and must fall back exactly
as `neatify` would, so that a one-tile run and a whole-extent run agree.
"""

SIMPLIFIED_COLUMN = "_simplified"
"""Per-edge flag: `False` marks linework that passed through a tile `neatnet` could not process.

Carried out of cleaning rather than reduced to a count, so a downstream oddity can be traced to
the tile that produced it instead of being attributed to the classifier.
"""


def simplify_streets(
    streets: gpd.GeoDataFrame, buildings: gpd.GeoDataFrame
) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Simplify `streets` with `neatnet.neatify`, using `buildings` as the exclusion mask.

    Required, not optional, per CLAUDE.md: unsimplified dual carriageways and roundabouts
    destroy enclosure generation downstream (Phase 2).
    """
    assert_projected_crs(streets, "streets")
    assert_projected_crs(buildings, "buildings")
    simplified = neatnet.neatify(streets, exclusion_mask=buildings.geometry)
    step = CleaningStep(
        stage="streets",
        operation="simplify_streets",
        n_in=len(streets),
        n_out=len(simplified),
        detail={"tiled": False},
    )
    return simplified, step


#: `neatify`'s own defaults for the two preprocessing steps that run before artifact detection.
#: Restated because the threshold must be measured on the network `neatify` will actually index,
#: and `neatify` indexes the *preprocessed* one.
NEATIFY_EPS = 1e-4
NEATIFY_MAX_SEGMENT_LENGTH = 1.0
NODE_CONSOLIDATION_FACTOR = 2.1


def _preprocess(streets: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """The topology fix and node consolidation `neatify` applies before it indexes any face.

    Isolated here because two callers need exactly what `neatify` does and would otherwise drift
    from it: the threshold resolver, which must measure the network `neatify` will actually
    index, and the per-tile fallback, which must return what `neatify` returns when it finds
    nothing to simplify — topologically fixed streets, not the raw input.
    """
    prepared = neatnet.fix_topology(streets, eps=NEATIFY_EPS)
    consolidated = neatnet.consolidate_nodes(
        prepared, tolerance=NEATIFY_MAX_SEGMENT_LENGTH * NODE_CONSOLIDATION_FACTOR
    )
    assert isinstance(consolidated, gpd.GeoDataFrame)  # noqa: S101 - neatnet is untyped here
    return consolidated


def resolve_artifact_threshold(
    streets: gpd.GeoDataFrame, *, fallback: float = ARTIFACT_THRESHOLD_FALLBACK
) -> float:
    """The face-artifact-index threshold `neatify` would derive from `streets` as a whole.

    Computed once per extent and pushed into every tile — see this module's docstring for why
    that matters.

    **Measured after the same preprocessing `neatify` applies**, not on the raw input.
    `neatify` runs `fix_topology` and then `consolidate_nodes` before it indexes any face, and
    those change which faces exist: an unnoded crossing forms no face at all, so a raw network
    can look artifact-free when the network actually simplified is not. Skipping this yields a
    threshold from a different network than the one it is pinned onto, which is the failure this
    function exists to prevent rather than one it may commit.

    Returns `fallback` when no kernel-density valley is found, which is what `neatify` does
    internally with its `artifact_threshold_fallback`. Degenerate networks are the fallback's
    other job: one too sparse to polygonize has no faces to index, and a perfectly uniform one
    gives every face the *same* index, which makes the kernel density estimate singular and
    raises out of scipy. Neither is worth failing a run over, and at metropolitan scale neither
    can be ruled out.
    """
    assert_projected_crs(streets, "streets")
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="No threshold found")
            warnings.filterwarnings("ignore", message="Input streets could not")
            threshold = neatnet.FaceArtifacts(_preprocess(streets)).threshold
    except (ValueError, np.linalg.LinAlgError):
        return fallback
    return fallback if threshold is None else float(threshold)


def _cache_path(cache_dir: Path, tile: Tile, fingerprint: str) -> Path:
    return cache_dir / fingerprint / f"{tile.key}.parquet"


def _simplify_window(
    tile: Tile,
    streets: gpd.GeoDataFrame,
    buildings: gpd.GeoDataFrame,
    threshold: float,
    cache_path: Path | None,
    owned_by_neighbour: BaseGeometry | None,
) -> gpd.GeoDataFrame:
    """Simplify one tile's window and return the part falling inside its core.

    Module-level and taking only picklable arguments, so `ProcessPoolExecutor` can run it.
    Clipping to the core happens here rather than in the parent: it is the step that makes the
    per-tile results disjoint, and it shrinks what crosses the process boundary on the way back.
    """
    if cache_path is not None and cache_path.exists():
        cached = gpd.read_parquet(cache_path)
        if isinstance(cached, gpd.GeoDataFrame):
            return cached

    if streets.empty:
        result = streets.iloc[:0].copy()
        result[SIMPLIFIED_COLUMN] = pd.Series(dtype="bool")
    else:
        try:
            simplified = neatnet.neatify(
                streets,
                exclusion_mask=buildings.geometry,
                artifact_threshold=threshold,
            )
            simplified[SIMPLIFIED_COLUMN] = True
        except Exception:  # noqa: BLE001 - see below; the tile is passed through, not lost
            # neatnet raises out of its own face detection on networks it cannot polygonize or
            # whose face indices are degenerate. One such tile must not end a run over a whole
            # city, so the streets pass through unsimplified and the tile is *counted* — a
            # silently unsimplified tile would show up downstream as a strangely shaped
            # enclosure and be impossible to trace back here.
            #
            # Preprocessed rather than raw: `neatify` returns topologically-fixed streets when
            # it finds no artifacts, so an unnoded pass-through would leave crossings unsplit
            # and put this tile's topology out of step with every tile around it.
            simplified = _preprocess(streets)
            simplified[SIMPLIFIED_COLUMN] = False
        clipped = simplified.copy()
        core_part = simplified.geometry.intersection(tile.core)
        if owned_by_neighbour is not None:
            # Drop only what lies *along* a shared edge. A street merely crossing that edge is
            # split at the crossing point rather than shortened, and `_stitch` heals the node.
            core_part = core_part.difference(owned_by_neighbour)
        clipped.geometry = core_part
        result = clipped[~clipped.geometry.is_empty & clipped.geometry.notna()]
        result = result.explode(index_parts=False).reset_index(drop=True)
        result = result[result.geometry.geom_type == "LineString"].copy()

    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        result.to_parquet(cache_path)
    return result


def _stitch(parts: list[gpd.GeoDataFrame], crs: CRS | None) -> gpd.GeoDataFrame:
    """Concatenate per-tile cores and dissolve the degree-2 nodes the seams introduced.

    Clipping each tile to its core cuts every street that crosses a seam, leaving an artificial
    node there. `remove_interstitial_nodes` is what neatnet itself uses to drop nodes of degree
    2, so running it over the union restores the topology the untiled path would have produced
    wherever the two tiles agreed about the geometry.
    """
    populated = [part for part in parts if len(part)]
    if not populated:
        return gpd.GeoDataFrame(geometry=[], crs=crs)
    stitched = pd.concat(populated, ignore_index=True)
    stitched = gpd.GeoDataFrame(stitched, geometry="geometry", crs=crs)
    if len(stitched) < 2:
        return stitched
    healed = neatnet.remove_interstitial_nodes(stitched)
    if not isinstance(healed, gpd.GeoDataFrame):
        healed = gpd.GeoDataFrame(geometry=healed, crs=crs)
    return healed.reset_index(drop=True)


def simplify_streets_tiled(
    streets: gpd.GeoDataFrame,
    buildings: gpd.GeoDataFrame,
    *,
    tile_size_m: float,
    buffer_m: float,
    workers: int | None = None,
    cache_dir: Path | None = None,
    cache_fingerprint: str = "default",
) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Tile the extent, simplify each tile over a buffered window, and stitch the cores.

    `workers` defaults to every core the process is allowed to use. `cache_dir`, when given,
    memoises each tile under `<cache_dir>/<cache_fingerprint>/<tile_key>.parquet`; the
    fingerprint must cover everything that changes a tile's result — the Overture release, the
    tile geometry, and the pinned threshold — because tile keys alone are CRS-origin-aligned and
    therefore shared across runs.

    Returns the same `(GeoDataFrame, CleaningStep)` shape as `simplify_streets`, so the caller
    does not branch on which path ran.
    """
    assert_projected_crs(streets, "streets")
    assert_projected_crs(buildings, "buildings")

    extent = layer_extent(streets)
    tiles = build_tiles(extent, tile_size_m=tile_size_m, buffer_m=buffer_m, crs_hint="streets")
    threshold = resolve_artifact_threshold(streets)

    # The threshold is pinned from the *whole* extent, so the same tile genuinely simplifies
    # differently under a different study area. It has to reach the cache key, or a second run
    # over a larger city would read back tiles decided by the smaller one's threshold.
    fingerprint = f"{cache_fingerprint}_thr{threshold:.6f}"
    jobs = [
        (
            tile,
            subset(streets, tile.window),
            subset(buildings, tile.window),
            threshold,
            None if cache_dir is None else _cache_path(cache_dir, tile, fingerprint),
            shared_edges(tile, tiles),
        )
        for tile in tiles
    ]

    n_workers = workers if workers is not None else len(os.sched_getaffinity(0))
    n_workers = max(1, min(n_workers, len(jobs)))

    if n_workers == 1:
        parts = [_simplify_window(*job) for job in jobs]
    else:
        with ProcessPoolExecutor(max_workers=n_workers) as pool:
            parts = list(pool.map(_simplify_window, *zip(*jobs, strict=True)))

    simplified = _stitch(parts, streets.crs)
    unsimplified = sum(
        1 for part in parts if len(part) and not bool(part[SIMPLIFIED_COLUMN].to_numpy().all())
    )
    step = CleaningStep(
        stage="streets",
        operation="simplify_streets_tiled",
        n_in=len(streets),
        n_out=len(simplified),
        detail={
            "tiled": True,
            "n_tiles": len(tiles),
            "tile_size_m": tile_size_m,
            "buffer_m": buffer_m,
            "workers": n_workers,
            "artifact_threshold": threshold,
            "cached": cache_dir is not None,
            "n_tiles_unsimplified": unsimplified,
        },
    )
    return simplified, step


def seam_disagreement(
    tiled: gpd.GeoDataFrame, untiled: gpd.GeoDataFrame, *, tolerance_m: float = 0.5
) -> dict[str, float]:
    """Length of linework present in one simplification and not the other, in kilometres.

    The correctness instrument for the tiled path, and the thing Phase 8's tests assert on.
    Both inputs are reduced to a single geometry and compared with a `tolerance_m` buffer, so a
    street counts as agreeing when it follows the same line, not when its vertices are equal —
    neatnet re-nodes and re-merges, so vertex equality is too strong a test.

    Compare only over ground both runs cover: a whole-extent run keeps streets that merely
    *intersect* its window and so reaches beyond it, while the tiled run is clipped to tile
    cores. Comparing the two unclipped exaggerates disagreement by the perimeter overhang.
    """
    left = tiled.geometry.union_all()
    right = untiled.geometry.union_all()
    overlap = shapely.box(*left.bounds).intersection(shapely.box(*right.bounds))
    common = shapely.box(*overlap.bounds)
    left = left.intersection(common)
    right = right.intersection(common)
    missing = right.difference(left.buffer(tolerance_m)).length
    extra = left.difference(right.buffer(tolerance_m)).length
    return {
        "tiled_km": left.length / 1000.0,
        "untiled_km": right.length / 1000.0,
        "missing_km": missing / 1000.0,
        "extra_km": extra / 1000.0,
        "agreement": 1.0 - missing / right.length if right.length else 1.0,
    }


def seam_lines(tiles: list[Tile]) -> BaseGeometry:
    """The union of tile core boundaries — where tiled and untiled may legitimately differ.

    Lets a test separate disagreement that the seam explains from disagreement that it does not.
    The second kind is the one that would mean the tiled path is wrong rather than merely cut.
    """
    return shapely.union_all([tile.core.exterior for tile in tiles])
