"""Street-network simplification via `neatnet`, whole-extent and tiled.

`neatnet` owns its own tuning parameters (node-merge tolerance, continuity-stroke angle
threshold, and a dozen others) as documented package defaults — lczkit does not proxy them
into config; doing so would wrap an entire downstream library's parameter surface for no
current need.

Two entry points, same result shape:

- `simplify_streets` runs `neatify` over the whole extent. Correct at any size, but superlinear —
  see `lczkit.cleaning.tiles`.
- `simplify_streets_tiled` splits the extent, simplifies each tile independently over a
  buffered window, and stitches the cores back together.

**The tiled path pins one face-artifact threshold across every tile.** `neatnet` derives that
threshold from the distribution of face-artifact-index values across whatever network it is
handed — a kernel-density valley — so a tile left to itself computes a *different* threshold from
its neighbour. On a 2x2 tiling of 16 km2 of Berlin the whole extent found no valley and fell back
to 7.0, while two of the four tiles found 8.10 and 7.58: a face with an index of 7.5 would have
been an artifact in one tile and ordinary urban fabric in the run next to it. Pinning one value
across all tiles removes that class of seam disagreement outright.

**Simplification is sensitive to input row order.** `neatnet` re-nodes and re-merges a network in
the order it receives it: a shuffled input yields the same feature count and the same total length
with the edges split at different points, which reaches `momepy.street_profile` and so
`aspect_ratio`. Nothing here can fix that, and nothing here should paper over it — what it means
is that the row order arriving from a `VectorSource` has to be canonical *already*, or two runs
over the same city disagree. `lczkit.sources.overture._canonical_order` is where that is
established; this module only depends on it.

**Where that value comes from is the second scaling problem this module had.** Deriving it from
the whole network, as `resolve_artifact_threshold` does, means running `neatnet.fix_topology`
over the whole network — quadratic in feature count, measured at exponent 2.0 and projecting to
~8.6 hours at metropolitan scale, against 7.5 minutes for the tiles themselves. Detection is not
the expensive part; the preprocessing it needs is, at 8.3 s against 12 392 s at 484 km2. The
index is a *per-face* quantity, so `pooled_artifact_threshold` assembles the same distribution
from the per-tile windows at k * (n/k)**2, in parallel, and `resolve_artifact_threshold` remains
as the reference the pooled one is measured against.
"""

from __future__ import annotations

import multiprocessing
import os
import sys
import warnings
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import geopandas as gpd
import neatnet
import numpy as np
import numpy.typing as npt
import pandas as pd
import shapely
from pyproj import CRS
from scipy.signal import find_peaks
from scipy.stats import gaussian_kde
from shapely.geometry.base import BaseGeometry

from lczkit.cleaning.report import CleaningStep
from lczkit.cleaning.tiles import Tile, build_tiles, layer_extent, shared_edges, subset
from lczkit.crs import assert_projected_crs

ARTIFACT_THRESHOLD_FALLBACK = 7.0
"""`neatnet.neatify`'s own default for when no face-artifact-index valley is found.

Restated here because the tiled path resolves the threshold itself and must fall back exactly
as `neatify` would, so that a one-tile run and a whole-extent run agree.
"""

TILE_RESULT_VERSION = 3
"""Bumped whenever `_simplify_window` changes what it writes for a given input.

Part of the per-tile cache key. Config and the `neatnet` version cover everything *outside* this
module that changes a tile's contents; this covers what is inside it, which nothing else in the
key would detect.

Version 2 adds `_tile_key` and `_failure`, so a cached tile replays the *report* as well as the
geometry.

Version 3: `subset` now preserves the layer's row order rather than returning spatial-index order,
which changes the linework `neatnet` produces for an unchanged input. **The rest of the key does not
notice.** Measured at 64 and 144 km2 of Berlin, the pooled threshold is *identical* under both
orderings, so `_threshold_tag` moves not at all while tile contents differ by ~1.2% of linework —
exactly the case this field exists for, and one that would otherwise have served pre-fix tiles to a
post-fix run with nothing reporting it.
"""

SIMPLIFIED_COLUMN = "_simplified"
"""Per-edge flag: `False` marks linework that passed through a tile `neatnet` could not process.

Carried out of cleaning rather than reduced to a count, so a downstream oddity can be traced to
the tile that produced it instead of being attributed to the classifier.
"""

TILE_KEY_COLUMN = "_tile_key"
"""Per-edge tile provenance: which tile emitted this line.

`SIMPLIFIED_COLUMN` alone says an edge came from a tile that failed, not *which* tile, so it
could not actually be traced back — the claim that it could was made and never exercised. With
the key present, a suspect enclosure downstream resolves to one tile and one window.
"""

FAILURE_COLUMN = "_failure"
"""Internal, dropped before the stitch: the exception class that made a tile pass through.

Written into the per-tile cache so a cached run reconstructs the same cleaning report a cold run
would have produced. A cache that reproduces the geometry but not the record of how it was
obtained is still not transparent.
"""


def _threshold_tag(threshold: float) -> str:
    """The threshold's contribution to the cache key, at full precision.

    `repr` of a float round-trips exactly; the `:.6f` this used to be did not. Two runs whose
    pooled thresholds differed beyond the sixth decimal — which is the ordinary case, since the
    value comes out of a kernel-density valley search — hashed to the same directory, so the
    second silently read tiles simplified against a threshold it never used. That is precisely
    the "same tile, different answer" the key exists to prevent, and it was invisible because
    the printed threshold matched to the precision anyone looked at.
    """
    return repr(float(threshold)).replace("-", "m")


THREAD_LIMIT_VARS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)
"""The native thread-pool controls every worker must see set to 1.

Each worker runs GEOS and BLAS through geopandas, and each would otherwise start a thread pool
sized to the whole machine. Thirty-two workers times thirty-two threads is not parallelism, it
is the same oversubscription that makes the pool appear hung.
"""


@contextmanager
def _single_threaded_children() -> Iterator[None]:
    """Pin native thread pools to one thread for the duration of the block, then restore.

    **Set in the parent, deliberately, and not in a pool `initializer`.** The `forkserver`
    daemon inherits `environ` at the moment it starts, and libgomp and OpenBLAS read their
    thread counts when the library initialises — which is before any initializer callable of
    ours could run. Setting these anywhere later sets them too late to have an effect.

    This is the one place in the package that writes `os.environ`. No module *reads* the
    environment outside the config model, because `DATA_DIR` must resolve once; this reads nothing
    and configures a child process, and restoring on exit keeps it from leaking into the rest of
    the run.
    """
    previous = {name: os.environ.get(name) for name in THREAD_LIMIT_VARS}
    os.environ.update(dict.fromkeys(THREAD_LIMIT_VARS, "1"))
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@contextmanager
def _worker_pool(n_workers: int) -> Iterator[ProcessPoolExecutor]:
    """A worker pool that starts its children from a fresh interpreter rather than forking.

    **`forkserver`, not the default `fork`.** By the time simplification runs, the parent has
    already been through DuckDB, GEOS and NumPy, all of which hold locks across threads that do
    not exist in a forked child. Observed directly at metropolitan scale: parent and all 32
    workers sat at zero CPU for 14h50m, having deadlocked before doing any work. `forkserver`
    launches a clean interpreter to fork from, so no such lock is ever inherited.

    Preloading this module makes the forkserver daemon import geopandas and neatnet once,
    instead of every child paying for it.

    **`__main__` is hidden from the children on purpose.** A `forkserver` child goes through the
    same startup as a `spawn` child, which re-executes the parent's entry point so that a
    callable defined there can be unpickled. Nothing here needs that — the only function sent to
    a worker is this module's `_simplify_window`, referenced by qualified name — and paying for
    it is worse than useless: every worker would re-import the whole entry script, and an entry
    point without a real file (`python -c`, a heredoc, a notebook) fails outright with a
    `BrokenProcessPool` whose traceback names neither the cause nor the fix.

    The two attributes `multiprocessing` consults are handled differently because it reads them
    differently: `__spec__` is dereferenced outright and so must exist and be `None`, while
    `__file__` is read with `getattr(..., None)` and so must be absent. With both in that state
    the children come up on a bare `__mp_main__`, importing only what unpickling asks for.
    """
    context = multiprocessing.get_context("forkserver")
    context.set_forkserver_preload(["lczkit.cleaning.streets"])
    main = sys.modules["__main__"]
    had_file, file_value = hasattr(main, "__file__"), getattr(main, "__file__", None)
    spec_value = getattr(main, "__spec__", None)
    if had_file:
        del main.__file__
    main.__spec__ = None
    try:
        with ProcessPoolExecutor(max_workers=n_workers, mp_context=context) as pool:
            yield pool
    finally:
        if had_file:
            main.__file__ = file_value
        main.__spec__ = spec_value


def simplify_streets(
    streets: gpd.GeoDataFrame, buildings: gpd.GeoDataFrame
) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Simplify `streets` with `neatnet.neatify`, using `buildings` as the exclusion mask.

    Required, not optional: unsimplified dual carriageways and roundabouts destroy enclosure
    generation downstream.
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


#: `neatnet.FaceArtifacts`'s own peak/valley parameters, restated so the pooled threshold is
#: selected by the same rule as the whole-network one. Drift is caught by
#: `test_threshold_from_index_reproduces_face_artifacts`, which asserts exact equality against
#: `neatnet.FaceArtifacts(...).threshold` rather than trusting these to stay in step.
FACE_INDEX_SAMPLES = 1000
FACE_PEAK_HEIGHT_MAX = 0.008
FACE_PEAK_PROMINENCE = 0.00075


def _threshold_from_index(values: npt.NDArray[np.float64]) -> float | None:
    """The face-artifact threshold implied by a distribution of face-artifact-index values.

    `neatnet.FaceArtifacts` computes this from a network it polygonizes itself, which is exactly
    what makes it whole-extent and therefore quadratic here. The index is a **per-face** quantity
    — `log(minimum_bounding_circle_ratio * area)` — so the distribution it is read from can be
    assembled tile by tile and the selection rule applied to the pool. This function is that
    selection rule, separated from where the values came from.

    Returns `None` when the distribution has no valley between peaks, which is what
    `FaceArtifacts` reports in the same situation; the caller decides what to fall back to.

    Reimplemented from `neatnet` 0.1.6 (BSD-3-Clause), not copied from a copyleft source.
    """
    linspace = np.linspace(values.min(), values.max(), FACE_INDEX_SAMPLES)
    pdf = gaussian_kde(values, bw_method="silverman").pdf(linspace)

    peaks, peak_data = find_peaks(
        x=pdf,
        height=FACE_PEAK_HEIGHT_MAX,
        threshold=None,
        distance=None,
        prominence=FACE_PEAK_PROMINENCE,
        width=1,
        plateau_size=None,
    )
    valleys, _ = find_peaks(
        x=-pdf + 1,
        height=-np.inf,
        threshold=None,
        distance=None,
        prominence=FACE_PEAK_PROMINENCE,
        width=1,
        plateau_size=None,
    )
    if len(peaks) < 2 or len(valleys) == 0:
        return None

    highest_peak = peaks[np.argmax(peak_data["peak_heights"])]
    bounds = [b for b in zip(peaks[:-1], peaks[1:], strict=True) if highest_peak in b]
    accepted = [v for v in valleys if any(v in range(low, high) for low, high in bounds)]
    if not accepted:
        # `FaceArtifacts` indexes straight into this list and raises `IndexError` when it is
        # empty. Reported as "no threshold" instead: at metropolitan scale a distribution with
        # peaks but no valley between the accepted pair is not rare enough to end a run over.
        return None
    return float(linspace[accepted[0]])


class TileFaceIndex(NamedTuple):
    """One tile's contribution to the pooled face-artifact-index distribution."""

    values: npt.NDArray[np.float64]
    n_dropped: int
    dropped_area_m2: float
    kept_area_m2: float


def _tile_face_index(tile: Tile, streets: gpd.GeoDataFrame) -> TileFaceIndex:
    """Index the faces of one tile's window, keeping only those the pool can trust.

    Module-level and picklable, so it runs on the same worker pool as simplification.

    Two filters, and both are load-bearing:

    - **Attribute each face to the tile whose core contains its representative point.** Windows
      overlap by the buffer, so a face near a seam is seen by several tiles; cores partition, so
      exactly one of them claims it. Without this the pooled distribution would weight seam
      neighbourhoods several times over and shift the valley.
    - **Reject any face meeting the window boundary.** A face larger than the buffer is *cut* by
      the window, and the fragment left behind indexes as a small compact face — a fictitious
      artifact. Dropping it loses a real face rather than inventing a false one, which is the
      right way round; the count and area of what was dropped are returned so the size of the
      approximation is reported rather than assumed small.
    """
    if streets.empty:
        return TileFaceIndex(np.empty(0, dtype=float), 0, 0.0, 0.0)
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Input streets could not")
            faces = neatnet.FaceArtifacts(_preprocess(streets)).polygons
    except (ValueError, np.linalg.LinAlgError, KeyError):
        return TileFaceIndex(np.empty(0, dtype=float), 0, 0.0, 0.0)
    if faces is None or faces.empty or "face_artifact_index" not in faces:
        return TileFaceIndex(np.empty(0, dtype=float), 0, 0.0, 0.0)

    geometry = gpd.GeoSeries(faces.geometry, crs=streets.crs)
    owned = geometry.representative_point().within(tile.core).to_numpy(dtype=bool)
    whole = ~geometry.intersects(tile.window.exterior).to_numpy(dtype=bool)
    keep, dropped = owned & whole, owned & ~whole
    area = geometry.area.to_numpy(dtype=float)
    return TileFaceIndex(
        values=faces["face_artifact_index"].to_numpy(dtype=float)[keep],
        n_dropped=int(dropped.sum()),
        dropped_area_m2=float(area[dropped].sum()),
        kept_area_m2=float(area[keep].sum()),
    )


@dataclass(frozen=True)
class PooledThreshold:
    """A face-artifact threshold pooled from per-tile distributions, with its error term."""

    value: float
    n_faces: int
    n_faces_dropped: int
    dropped_area_fraction: float
    n_tiles_indexed: int
    fallback_used: bool

    def as_detail(self) -> dict[str, object]:
        """The cleaning-report form. Every field travels; the error term is not a debug aid."""
        return {
            "artifact_threshold": self.value,
            "threshold_source": "pooled",
            "threshold_fallback_used": self.fallback_used,
            "threshold_n_faces": self.n_faces,
            "threshold_n_faces_dropped": self.n_faces_dropped,
            "threshold_dropped_area_fraction": self.dropped_area_fraction,
            "threshold_n_tiles_indexed": self.n_tiles_indexed,
        }


def pooled_artifact_threshold(
    streets: gpd.GeoDataFrame,
    tiles: list[Tile],
    *,
    workers: int = 1,
    fallback: float = ARTIFACT_THRESHOLD_FALLBACK,
) -> PooledThreshold:
    """Pin the artifact threshold from the tiles, instead of from the whole network.

    `resolve_artifact_threshold` gets the same number by running `neatnet.fix_topology` over the
    entire extent, which is **quadratic in feature count** — measured at 481.7 s, 1916.9 s,
    5004.6 s and 12392.6 s for 33.8k, 67.2k, 106.7k and 168.5k Berlin streets, an exponent of
    2.0, and extrapolating to roughly 8.6 hours at the 267k streets of the metropolitan extent.
    That is the whole of the gap between the 7.5 minutes the tiles actually take and the 15 hours
    the first metropolitan run spent before it was killed.

    Each tile already runs `fix_topology` over its own window inside `neatify`, so the same
    distribution can be assembled from k windows at k * (n/k)**2 — and, unlike the whole-network
    step, it parallelises.

    **This is an approximation with a measured error, not an identity.** Faces spanning a window
    boundary are absent from the pool (see `_tile_face_index`), so the pooled distribution is
    missing its largest faces. `dropped_area_fraction` is that error. Measured against the
    whole-network threshold over six extents, the two estimators converge — the pooled value
    settles at 8.1876 against 8.1918, and the deviation shrinks as the extent grows.
    """
    assert_projected_crs(streets, "streets")
    jobs = [(tile, subset(streets, tile.window)) for tile in tiles]
    n_workers = max(1, min(workers, len(jobs)))
    # The thread pinning wraps *both* branches. `n_workers` follows `os.sched_getaffinity`, so
    # whether this runs serially is a property of the machine, and the threshold it produces is
    # the tile cache key at full float precision. Pinning only the parallel branch would let the
    # same extent on a differently-sized node land on a different key and silently rebuild every
    # tile - a cache that misses for reasons the report cannot show.
    with _single_threaded_children():
        if n_workers == 1:
            indexed = [_tile_face_index(*job) for job in jobs]
        else:
            with _worker_pool(n_workers) as pool:
                indexed = list(pool.map(_tile_face_index, *zip(*jobs, strict=True)))

    populated = [tile_index for tile_index in indexed if tile_index.values.size]
    values = (
        np.concatenate([tile_index.values for tile_index in populated])
        if populated
        else np.empty(0, dtype=float)
    )
    n_dropped = sum(tile_index.n_dropped for tile_index in indexed)
    dropped_area = sum(tile_index.dropped_area_m2 for tile_index in indexed)
    kept_area = sum(tile_index.kept_area_m2 for tile_index in indexed)
    total_area = dropped_area + kept_area

    threshold = None
    if values.size > 1:
        try:
            threshold = _threshold_from_index(values)
        except (ValueError, np.linalg.LinAlgError):
            threshold = None
    return PooledThreshold(
        value=fallback if threshold is None else threshold,
        n_faces=int(values.size),
        n_faces_dropped=n_dropped,
        dropped_area_fraction=dropped_area / total_area if total_area else 0.0,
        n_tiles_indexed=len(populated),
        fallback_used=threshold is None,
    )


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

    failure: str | None = None
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
        except MemoryError:
            # Deliberately not caught with the rest. Every other exception here is a statement
            # about this tile's geometry and means the same thing on every run; running out of
            # memory is a statement about the machine, so swallowing it makes the map depend on
            # what else the node happened to be doing. That is a reproducibility hole, and a
            # silent one — the run still produces a plausible map, just not the same map twice.
            raise
        except Exception as error:  # noqa: BLE001 - see below; the tile is passed through
            # neatnet raises out of its own face detection on networks it cannot polygonize or
            # whose face indices are degenerate. One such tile must not end a run over a whole
            # city, so the streets pass through unsimplified and the tile is *recorded* — with
            # its key and the exception class, because a count alone cannot tell two runs that
            # degraded on different tiles apart, and 34 of Berlin's 594 tiles take this path.
            #
            # Preprocessed rather than raw: `neatify` returns topologically-fixed streets when
            # it finds no artifacts, so an unnoded pass-through would leave crossings unsplit
            # and put this tile's topology out of step with every tile around it.
            failure = type(error).__name__
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

    result[TILE_KEY_COLUMN] = tile.key
    result[FAILURE_COLUMN] = failure

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

    **This runs over the whole stitched network, and that was checked rather than assumed.**
    Measured directly on Berlin's 209 553 stitched features it takes **17.4 s**. A per-seam
    restriction was built, measured, and thrown away: it was *slower* (21.6 s), it left
    `momepy.street_profile`'s aspect ratio about twice as far from the whole-extent answer, and at
    metropolitan scale it did not reproduce the same linework.
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
    artifact_threshold: float | None = None,
) -> tuple[gpd.GeoDataFrame, CleaningStep]:
    """Tile the extent, simplify each tile over a buffered window, and stitch the cores.

    `workers` defaults to every core the process is allowed to use. `cache_dir`, when given,
    memoises each tile under `<cache_dir>/<cache_fingerprint>/<tile_key>.parquet`; the
    fingerprint must cover everything that changes a tile's result — the Overture release, the
    tile geometry, and the pinned threshold — because tile keys alone are CRS-origin-aligned and
    therefore shared across runs.

    `artifact_threshold` pins the face-artifact threshold explicitly; `None` pools it from the
    tiles via `pooled_artifact_threshold`.

    Returns the same `(GeoDataFrame, CleaningStep)` shape as `simplify_streets`, so the caller
    does not branch on which path ran.
    """
    assert_projected_crs(streets, "streets")
    assert_projected_crs(buildings, "buildings")

    extent = layer_extent(streets)
    tiles = build_tiles(extent, tile_size_m=tile_size_m, buffer_m=buffer_m, crs_hint="streets")
    n_workers = workers if workers is not None else len(os.sched_getaffinity(0))
    n_workers = max(1, min(n_workers, len(tiles)))

    if artifact_threshold is None:
        pooled = pooled_artifact_threshold(streets, tiles, workers=n_workers)
        threshold, threshold_detail = pooled.value, pooled.as_detail()
    else:
        threshold = artifact_threshold
        threshold_detail = {"artifact_threshold": threshold, "threshold_source": "configured"}

    # The threshold reaches the cache key because it is pinned from the whole extent: the same
    # tile genuinely simplifies differently under a different study area, and without this a run
    # over a larger city would read back tiles decided by the smaller one's threshold.
    # `TILE_RESULT_VERSION` covers the other half — a change to what `_simplify_window` writes,
    # which no amount of config hashing would notice.
    fingerprint = f"{cache_fingerprint}_v{TILE_RESULT_VERSION}_thr{_threshold_tag(threshold)}"
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

    # Counted before anything runs, because `_simplify_window` writes the file it would have
    # read. Asking afterwards reports every tile as a hit and tells you nothing.
    n_cached = sum(1 for job in jobs if job[4] is not None and job[4].exists())

    if n_workers == 1:
        parts = [_simplify_window(*job) for job in jobs]
    else:
        with _single_threaded_children(), _worker_pool(n_workers) as pool:
            parts = list(pool.map(_simplify_window, *zip(*jobs, strict=True)))

    # Aggregated before the stitch and sorted by tile key, so two runs that degraded on
    # different tiles are distinguishable from the report alone rather than by re-running.
    # `pd.notna`, not `is not None`: an all-null object column round-trips out of parquet as a
    # float NaN column, so a cached healthy tile would otherwise be reported as having failed
    # with the reason "nan" — a bug visible only on the cache path, which is the worst kind.
    passed_through = {
        str(part[TILE_KEY_COLUMN].iloc[0]): str(part[FAILURE_COLUMN].iloc[0])
        for part in parts
        if len(part) and pd.notna(part[FAILURE_COLUMN].iloc[0])
    }
    parts = [part.drop(columns=[FAILURE_COLUMN]) for part in parts]

    simplified = _stitch(parts, streets.crs)
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
            # Two separate facts. The old single `cached` flag recorded only that a directory
            # was configured, and was read as "this run reused tiles" — which is how a run that
            # had computed all 594 of its own tiles came to be reported as a cached run, and a
            # cold/cold difference came to be written up as a cache defect.
            "cache_dir_configured": cache_dir is not None,
            "n_tiles_reused": n_cached,
            "n_tiles_unsimplified": len(passed_through),
            "tiles_unsimplified": dict(sorted(passed_through.items())),
            **threshold_detail,
        },
    )
    return simplified, step


def seam_disagreement(
    tiled: gpd.GeoDataFrame, untiled: gpd.GeoDataFrame, *, tolerance_m: float = 0.5
) -> dict[str, float]:
    """Length of linework present in one simplification and not the other, in kilometres.

    The correctness instrument for the tiled path, and what its tests assert on.
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
