"""Morphometric attributes over the So2Sat LCZ42 city grids, for CNN training input.

    uv run --active python scripts/so2sat_morphometrics_extract.py [--cities A,B] [--workers 32]

**Overture is fetched for each city's full extent; morphometrics are computed only where the
grid is labelled.** Those are deliberately different areas. The full extent is cached under
`input/Overture_Maps/` so a later whole-grid inference pass needs no re-fetch, while the
expensive half — tessellation and the momepy metric blocks — runs only over the ~6% of cells
carrying a So2Sat label, plus a buffer.

**The buffer is not optional and its size is measured, not chosen.** Of the 50 attributes written
here, 38 are neighbourhood quantities: 100 m/200 m distance bands, 1-3 ETC topological steps, and
a 400 m network radius. Near the edge of whatever extent was tessellated they read a truncated
neighbourhood and are quietly wrong. Measured 3-topological-step reach on real Nairobi fabric:

    dense core   (890 ETC/km2)   p50  184 m   p95   434 m   max   830 m
    rural fringe  (72 ETC/km2)   p50  724 m   p95 1 271 m   max 1 420 m

Reach scales inversely with density, so the buffer has to cover the sparse case: `BUFFER_M` is
1 500 m. A labelled cell is only 1 280 m across, so computing per-cell with no buffer would
contaminate every neighbourhood attribute across the cell's whole width.

**Core size is a compromise the buffer largely dictates.** `compute_morphometrics` has a known,
unexplained superlinearity (Berlin: 5 406 ETCs in 50.9 s, 12 322 in 1 029 s), so a core wants to
be small — but processed area is `core + 2*buffer`, and with a 1 500 m buffer even a zero-size
core still processes 3x3 km. In central Caracas (1 289 ETC/km2, measured) that floor alone is
~11 600 ETCs, so dense fabric cannot be brought below the cliff by shrinking cores at all.
So `CORE_KM` stays at 4 km and the *ceiling* is raised instead. Total processed area is
`((core + 2*buffer)/core)^2` times the labelled envelope — x3.06 at 4 km against x6.25 at 2 km —
so shrinking the core doubles total work while only halving per-call cells, which is the wrong
trade. Raising the ceiling is safe on measurement rather than on hope: Caracas failed *after* a
successful tessellation (63 155 cells built in 453 s, then rejected by the guard), so the
expensive step was already shown tractable at that size.

Note what subdivision does and does not buy: quartering a 4 km core gives four 2 km cores at
25 km2 each, so the per-call extent falls 49 -> 25 km2 while total work rises 49 -> 100 km2. It
rescues a core that would otherwise fail outright; it is not an efficiency measure.

The square core is only a *grouping*: the extent actually processed is the tight envelope of the
labelled cells inside it, buffered — see `cores_for`. That is what takes the 48 cities from
327 918 km2 of processed ground to 211 090 km2, and rather more than that in time, since per-core
cost is roughly quadratic in cell count.

**Street tiling is switched off for the per-core cleaning**, unlike the published preset. Two
reasons, both load-bearing: `clean_vectors` would otherwise start its own process pool inside
each of this script's workers, and at these extents the whole-network simplification Phase 8
tiled *away from* is both tractable and the more accurate of the two.

Resumable: a city whose two outputs already exist is skipped, so the run can be stopped and
restarted. Guarded: it refuses to start another city once free disk falls below `MIN_FREE_GB`,
because `DATA_DIR` is a shared volume that is already near capacity.

Output mirrors the So2Sat layout — `<run_dir>/cities/<City>/<City>_morphometrics.{parquet,tif}`
— under `output/lczkit/`, never inside `input/`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing
import os
import shutil
import sys
import time
import traceback
import warnings
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

warnings.filterwarnings("ignore")

import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402
from shapely.geometry import box  # noqa: E402

from lczkit.cleaning.pipeline import clean_vectors  # noqa: E402
from lczkit.config import CleaningConfig, MorphometricsConfig, Settings  # noqa: E402
from lczkit.morphometrics.compute import compute_morphometrics  # noqa: E402
from lczkit.morphometrics.raster import rasterize_attributes  # noqa: E402
from lczkit.presets import apply_preset  # noqa: E402
from lczkit.protocols import BBox  # noqa: E402
from lczkit.sources.overture import OvertureSource  # noqa: E402

SO2SAT = Path("/maps/acz25/phd-thesis-data/input/So2Sat-LCZ42/v4")
BOUNDS_CSV = SO2SAT / "so2sat_guppd_bounds.csv"
CITIES_DIR = SO2SAT / "cities"

RESOLUTION_M = 10.0
BUFFER_M = 1500.0
CORE_KM = 4.0
#: Grouping squares `core_size_for` chooses between, largest first. The top of the range is the
#: 4 km square every measurement in this file's header was taken at; the bottom is one labelled
#: So2Sat grid cell (1 280 m), below which a cell would be split across cores that each pay the
#: full 1 500 m buffer.
CORE_SIZES_M = (4000.0, 2560.0, 1280.0)
#: Jobs wanted per worker before a larger square is accepted. Four rather than one so the tail of
#: a city is short: with one job each, the run waits on whichever single core happens to be
#: densest, which is the failure this sizing exists to remove.
JOBS_PER_WORKER = 4
MIN_JOBS = 16
#: DuckDB threads each worker's `OvertureSource` may use. Without it `--workers N` is not a CPU
#: budget: DuckDB sizes its own pool from the host's core count and ignores the `OMP_NUM_THREADS=1`
#: the pool pins, so N workers meant N x (host cores) threads during ingestion. Measured here: a
#: single un-pinned prefetch process held 672% CPU — about seven cores — for its whole run. Two
#: rather than one because the S3 scans are latency-bound and one thread leaves them serialised;
#: the pair puts the ceiling at `workers x 2` cores, which is what a shared machine can be told.
DUCKDB_THREADS_PER_WORKER = 2
FETCH_TILE_KM = 20.0
MAX_ETCS_PER_CORE = 80_000
MAX_SPLIT_DEPTH = 3
MIN_FREE_GB = 150.0

RESULT_VERSION = 1
"""Bump when a change to this script or to `lczkit.morphometrics` alters the numbers a finished
city holds, in a way the constants below do not already express — a corrected metric, a different
graph, a new column definition.

It exists because the two reuse paths here are keyed on *paths*, and a path cannot see a code
change: `already_done` skips a city whose parquet and raster are on disk, and `enqueue` reuses a
scratch leaf whose parquet is on disk. Both are worth having — they saved five hours of Bogota
after an interrupted run — and both would happily serve a cell computed under a superseded
definition into a dataset built under the current one, which is the failure this whole extraction
exists to avoid: 48 cities must share one definition of all 50 columns.

The same shape as this package's `TILE_RESULT_VERSION`, and for the same reason recorded there:
when a fix changes what a cached artefact contains, bump the version — do not assume the key
notices."""


def result_parameters() -> dict:
    """Everything that decides what a cell's 50 numbers are, as far as this script controls it.

    `BUFFER_M` is the one most likely to move and the most consequential: it sets how much ground
    around a core is tessellated before the metrics are read off, so two runs at different buffers
    describe the same cell differently at its edges. `CORE_SIZES_M` and `MAX_ETCS_PER_CORE` change
    how ground is cut into cores, which changes which cells a given tessellation sees.
    """
    return {
        "result_version": RESULT_VERSION,
        "buffer_m": BUFFER_M,
        "resolution_m": RESOLUTION_M,
        "core_sizes_m": [float(c) for c in CORE_SIZES_M],
        "max_etcs_per_core": MAX_ETCS_PER_CORE,
        "max_split_depth": MAX_SPLIT_DEPTH,
        "columns": list(COLUMNS),
    }


def result_stamp() -> str:
    """A short token for `result_parameters()`, used in paths so reuse cannot cross definitions."""
    payload = json.dumps(result_parameters(), sort_keys=True).encode()
    return hashlib.blake2b(payload, digest_size=4).hexdigest()


THREAD_LIMIT_VARS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)

#: The 50 attributes Majer & Fleischmann's own RF feature importance selects, resolved from the
#: aliases in their `figures.ipynb` (the union of the top-20 across their 8 city runs) to this
#: package's column names, and asserted against the registry at start-up.
COLUMNS = [
    "area_building",
    "building_adjacency_200m",
    "circular_compactness_building_w100m",
    "circular_compactness_building_w200m",
    "compactness_weighted_axis_building",
    "compactness_weighted_axis_building_w100m",
    "compactness_weighted_axis_building_w200m",
    "convexity_building_w200m",
    "convexity_etc_w3steps",
    "coverage_area_ratio_etc",
    "coverage_area_ratio_etc_w3steps",
    "cyclomatic_r400m",
    "cyclomatic_r5m",
    "edge_node_ratio_r400m",
    "elongation_building",
    "elongation_building_w200m",
    "equivalent_rectangular_index_building_w200m",
    "etc_granularity_1step",
    "facade_ratio_building_w100m",
    "facade_ratio_building_w200m",
    "fractal_dimension_building_w100m",
    "fractal_dimension_building_w200m",
    "fractal_dimension_etc",
    "longest_axis_length_building",
    "longest_axis_length_building_w100m",
    "longest_axis_length_building_w200m",
    "longest_axis_length_etc",
    "longest_axis_length_etc_w3steps",
    "mean_dist_neighbors_building_100m",
    "mean_dist_neighbors_etc_2steps",
    "mean_dist_neighbors_etc_3steps",
    "mean_interbuilding_distance_200m",
    "mean_node_degree_r5m",
    "meshedness_r400m",
    "neighbors_building_200m",
    "node_density_r400m",
    "node_density_r5m",
    "perimeter_wall_building",
    "perimeter_wall_building_w100m",
    "perimeter_wall_building_w200m",
    "rectangularity_building_w200m",
    "rectangularity_etc_w3steps",
    "shape_index_building",
    "shape_index_building_w100m",
    "shape_index_building_w200m",
    "square_compactness_building_w200m",
    "street_alignment_building_w200m",
    "street_linearity",
    "street_openness",
    "street_width",
]

_STATE: dict[str, object] = {}


def _worker_state(run_id: str) -> tuple[Settings, CleaningConfig, OvertureSource]:
    """Settings, cleaning config and Overture source, built once per worker process.

    Rebuilt in the child rather than pickled from the parent: `Settings.load` is the only
    supported way to resolve `DATA_DIR`, and an `OvertureSource` holds a DuckDB connection that
    must not cross a process boundary.
    """
    if "source" not in _STATE:
        settings = apply_preset(Settings.load(run_id=run_id, create_run_dir=False))
        settings.overture.duckdb_threads = DUCKDB_THREADS_PER_WORKER
        cleaning = settings.cleaning.model_copy(
            update={"street_tile_size_m": None, "street_tile_buffer_m": None}
        )
        _STATE["settings"] = settings
        _STATE["cleaning"] = cleaning
        _STATE["source"] = OvertureSource(settings)
    return _STATE["settings"], _STATE["cleaning"], _STATE["source"]  # type: ignore[return-value]


def quarters(core: tuple[float, float, float, float]) -> list[tuple[float, float, float, float]]:
    minx, miny, maxx, maxy = core
    midx, midy = (minx + maxx) / 2, (miny + maxy) / 2
    return [
        (minx, miny, midx, midy),
        (midx, miny, maxx, midy),
        (minx, midy, midx, maxy),
        (midx, midy, maxx, maxy),
    ]


def _one_core(
    core: tuple[float, float, float, float], crs: str, out_stem: Path, depth: int
) -> list[dict]:
    """Tessellate `core` + buffer, keep the ETCs inside `core`; subdivide if it is too dense.

    **Density is discovered, not predicted.** A fixed core size cannot work across this sample:
    Nairobi's rural fringe holds 72 ETC/km2 and central Caracas 1 289, an eighteen-fold spread, so
    any single choice is either wasteful in sparse fabric or over the tessellation ceiling in
    dense. Measured directly on the first attempt — a 4 km core over Caracas produced 63 155 ETCs
    against a 50 000 ceiling and failed after 453 s.

    Rather than guess a per-city size, a core that trips the ceiling is reported back as `split`
    and the driver re-queues its four quarters as jobs of their own, so they run in parallel
    across the pool rather than serially inside the worker that found the split. That costs a
    wasted tessellation on the way down, which is why `CORE_KM` is set small enough that most
    cores pass first time and only genuinely dense fabric splits. The re-fetch a quarter needs is
    not free either — `OvertureSource` keys its cache on the exact bbox — but it is bounded by
    depth and confined to the dense minority.
    """
    settings, cleaning, source = _worker_state(_STATE["run_id"])  # type: ignore[arg-type]
    buffered = box(core[0] - BUFFER_M, core[1] - BUFFER_M, core[2] + BUFFER_M, core[3] + BUFFER_M)
    wgs = gpd.GeoSeries([buffered], crs=crs).to_crs("EPSG:4326").total_bounds
    bbox: BBox = (float(wgs[0]), float(wgs[1]), float(wgs[2]), float(wgs[3]))

    cleaned = clean_vectors(source, bbox, cleaning, cache_dir=settings.tile_cache_dir)
    if len(cleaned.buildings_area) == 0:
        return [{"core": core, "status": "no_buildings", "n": 0}]

    # Pin the computation to the city grid's CRS. `clean_vectors` derives its own from this
    # core's buffered bbox via `estimate_utm_crs()`, which is correct in isolation and wrong
    # here: `core` is expressed in the grid's CRS, so wherever the two disagree the `within`
    # test below compares coordinates in different zones and keeps nothing. It fails silently,
    # because an empty result is indistinguishable from a core with no buildings in it.
    #
    # Measured on Hong Kong, which straddles the zone 49/50 boundary at 114 degrees E: the
    # Tung Chung core box came out at x = 183 659-184 939 (zone 50, the grid's CRS) against ETC
    # bounds of x = 800 374-804 785 (zone 49, estimated from the core's own extent) -- the same
    # ground, 620 km apart, 0 of 1 364 ETCs kept. Anything with a north/south hemisphere split
    # would be worse still, since those differ by a 10 000 km false northing.
    #
    # The city CRS is the right one to pin to rather than the local estimate: the So2Sat grid
    # this run exists to describe is in it, the per-city parquet is assembled by concatenating
    # cores under one CRS, and the raster is cut on the grid's own origin. The cost is scale
    # distortion for cores near the far edge of the city's zone -- Hong Kong's worst case is
    # 3.1 degrees off the central meridian, k = 1.00086, so 0.09% in length and 0.17% in area.
    buildings = cleaned.buildings_area.to_crs(crs)
    streets = cleaned.streets.to_crs(crs)
    waterbodies = cleaned.waterbodies.to_crs(crs)

    try:
        etc, report = compute_morphometrics(
            bbox,
            buildings,
            streets,
            waterbodies,
            config=MorphometricsConfig(
                enabled=True,
                max_tessellation_cells=MAX_ETCS_PER_CORE,
                # This function already runs inside this script's own worker pool, and
                # `momepy.enclosed_tessellation` defaults to a `joblib` pool over every core on
                # the host — so the default nests one pool inside another. Measured here: 8
                # workers produced **2 923 processes and ~70 cores** against a stated 16-core
                # budget, on a 256-core shared node whose load average reached 428. The
                # `OMP_NUM_THREADS=1` pinning below does not touch it; that caps threads inside
                # a process and this spawns processes.
                tessellation_n_jobs=1,
            ),
        )
    except ValueError as error:
        if "max_tessellation_cells" not in str(error) or depth >= MAX_SPLIT_DEPTH:
            raise
        # **Hand the quarters back to the driver; do not recurse here.** Recursing keeps all four
        # inside the one worker that discovered the split, so a dense core is computed serially
        # while the rest of the pool idles. Measured on Bogota, 2 labelled cells over 2 cores:
        # one tripped the ceiling and its quarters completed 69, 95 and 134+ minutes apart, one
        # after another -- 7h22m for the city with six of eight workers idle throughout, against
        # 7.4h for the same city before any of this run's fixes, i.e. no gain at all.
        # `core_size_for` fixed the other half of this, how cores are grouped, and its own
        # docstring names the serial-subdivision failure that it does not fix. This is that half.
        return [{"core": core, "status": "split", "depth": depth, "stem": str(out_stem)}]

    keep = etc[etc.geometry.representative_point().within(box(*core))]
    if len(keep) == 0:
        return [{"core": core, "status": "no_core_etcs", "n": 0}]

    # **Namespace the ETC id by its core.** `TessellationUnits` numbers cells with a positional
    # counter over the buildings it was handed, so every core independently produces
    # `etc_bld_0, etc_bld_1, ...` — ids that are unique within one call and collide wholesale
    # across calls. Assembly drops duplicate ids, so without this the city keeps roughly one
    # core's worth of cells however many it computed: measured on Hong Kong at **138 022 ETCs
    # computed and 20 870 kept, 84.9% discarded in silence**, with the two largest cores alone
    # sharing 362 ids. The stem is unique per core and per subdivision quarter, so it is the
    # natural namespace, and it keeps a cell traceable to the core that produced it.
    keep = keep.set_index(out_stem.name + "_" + keep.index.astype(str))
    keep.index.name = "unit_id"
    out = out_stem.with_suffix(".parquet")
    keep[COLUMNS + ["geometry"]].to_parquet(out)
    return [
        {
            "core": core,
            "status": "ok",
            "n": len(keep),
            "path": str(out),
            "processed_etcs": report.tessellation.n_etc,
            "depth": depth,
        }
    ]


def compute_core(job: dict) -> dict:
    """One core job, collapsed to a single result for the parent.

    **A core too dense to tessellate returns `split`, it does not subdivide itself.** The driver
    re-queues the four quarters as ordinary jobs, so they occupy four workers instead of one.

    Module-level and taking only picklable arguments, so `ProcessPoolExecutor` can run it. Writes
    results to parquet and returns paths rather than frames — a core can hold tens of thousands of
    ETCs across 50 columns, and sending that back through the pool's pipe is slower than the
    filesystem and far more memory.

    **Every no-output reason is reported separately.** An earlier version collapsed all of them to
    a single `"empty"`, which is how a CRS defect that discarded 1 364 real ETCs per core read as
    "there are no buildings here" in the run log — a city reported `core_failures: 0` and was
    missing a quarter of its built cells. `no_buildings` and `no_core_etcs` are different claims
    and only one of them is ever expected.
    """
    _STATE["run_id"] = job["run_id"]
    core = job["core"]
    try:
        stem = Path(job["stem"])
        depth = int(job["depth"])
        parts = _one_core(tuple(core), job["crs"], stem, depth)  # type: ignore[arg-type]
        if parts and parts[0]["status"] == "split":
            return {"core": core, "status": "split", "n": 0, "depth": depth, "stem": str(stem)}
        paths = [p["path"] for p in parts if p["status"] == "ok"]
        total = sum(p["n"] for p in parts)
        if not paths:
            reasons = sorted({p["status"] for p in parts})
            return {
                "core": core,
                "n": 0,
                "reasons": reasons,
                "parts": len(parts),
                "status": reasons[0] if len(reasons) == 1 else "mixed_empty",
            }
        return {
            "core": core,
            "status": "ok",
            "n": total,
            "paths": paths,
            "splits": max(p.get("depth", 0) for p in parts if p["status"] == "ok"),
        }
    except Exception as error:
        return {
            "core": core,
            "status": "error",
            "n": 0,
            "error": f"{type(error).__name__}: {error}",
        }


def free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / 1e9


#: Bounds-CSV names whose `cities/` folder is spelled differently. Both were found by a start-up
#: check rather than by reading: `JRC_NAME_MAIN` carries the endonym or the accented form, the
#: folder carries an ASCII transliteration, and a plain name match drops the city **silently** —
#: Sao Paulo, one of the paper's own five study sites, would simply not have been extracted.
FOLDER_ALIASES = {
    "São_Paulo": "Sao_Paulo",
    "东营区": "Dongying",
}

#: Cities whose folder exists but holds no `*_grid.gpkg`. Listed so that "no grid" stays a known,
#: asserted state rather than something the run discovers and shrugs at.
KNOWN_WITHOUT_GRID = {"Osaka_[Kyoto]", "Quezon_City_[Manila]", "Rawalpindi_[Islamabad]"}


def folder_for(city: str) -> str:
    """The `cities/` folder name for a bounds-CSV city name.

    The space-to-underscore step belongs here rather than in the caller. It lived in `main`, so
    `city_grid("Hong Kong")` returned `None` for every other caller — which is how a diagnostic
    written against this module silently skipped all seventeen multi-word cities and reported a
    clean result for them. Same shape as the alias defect below, one layer out: a name
    normalisation that lives in one caller is one the next caller will forget.
    """
    folder = city.replace(" ", "_")
    return FOLDER_ALIASES.get(folder, folder)


def city_grid(city: str) -> Path | None:
    hits = sorted(CITIES_DIR.glob(f"{folder_for(city)}/*_grid.gpkg"))
    return hits[0] if hits else None


def fetch_tiles(bbox: BBox, tile_km: float) -> list[BBox]:
    """`bbox` cut into roughly `tile_km`-square lon/lat windows.

    One DuckDB scan over a whole metropolitan bbox is a single unbounded query; the Overture cache
    is keyed per bbox anyway, so fetching in tiles both bounds any one call and leaves the cache
    reusable at a finer granularity.
    """
    minx, miny, maxx, maxy = bbox
    lat_step = tile_km / 111.0
    lon_step = lat_step / max(math.cos(math.radians((miny + maxy) / 2)), 0.01)
    tiles: list[BBox] = []
    y = miny
    while y < maxy:
        x = minx
        while x < maxx:
            tiles.append((x, y, min(x + lon_step, maxx), min(y + lat_step, maxy)))
            x += lon_step
        y += lat_step
    return tiles


def cores_for(labelled: gpd.GeoDataFrame, core_m: float) -> list[tuple[float, float, float, float]]:
    """Compute extents covering the labelled cells: one per `core_m` square that holds any.

    **The returned box is the tight envelope of the labelled cells inside each square, not the
    square itself.** The square is only a grouping device. Labelled cells are sparse -- 5.8% of a
    city grid -- and clustered, so a square core routinely holds a handful of cells in one corner
    and 40-odd km2 of ground nobody asked for. Caracas is the extreme: 4 labelled cells (6.6 km2
    of output) inside one 4 km square whose buffered extent is 49 km2, seven eighths of which the
    tessellation then discards.

    Measured across the 48 city grids: square cores process 327 918 km2, tight envelopes 211 090
    km2 -- a 36% reduction. That compounds, because per-core cost is roughly quadratic in cell
    count (Nairobi 8 014 cells in 64 s against Caracas 63 155 in 40+ min), so 36% fewer cells per
    call is nearer 2.4x less time -- and it costs nothing, since every cell dropped was ground
    outside the labelled cells this run exists to describe.
    """
    minx, miny, maxx, maxy = labelled.total_bounds
    sindex = labelled.sindex
    out = []
    y = miny
    while y < maxy:
        x = minx
        while x < maxx:
            square = (x, y, min(x + core_m, maxx), min(y + core_m, maxy))
            # `intersects` is true for a cell that merely *touches* the square along an edge, so
            # the candidates are filtered to those that actually overlap it. Without this, two
            # cells touching opposite edges of an empty square produce a joint envelope covering
            # the whole square — a core holding no labelled ground that is still fetched, cleaned
            # and tessellated over its full `core + 2 * BUFFER_M` extent, about 9 km2 of work to
            # keep nothing. Latent at 4 km, where a square edge rarely coincides with a cell edge;
            # systematic at 1 280 m, where every square edge is one. Measured on Caracas: 9 cores
            # for 4 labelled cells before this, 4 after, with cell coverage unchanged at 1.0000.
            sq = box(*square)
            idx = sindex.query(sq, predicate="intersects")
            if len(idx):
                candidates = labelled.iloc[idx]
                overlapping = candidates[candidates.geometry.intersection(sq).area > 0.0]
                if len(overlapping):
                    cells = overlapping.total_bounds
                    out.append(
                        (
                            max(float(cells[0]), square[0]),
                            max(float(cells[1]), square[1]),
                            min(float(cells[2]), square[2]),
                            min(float(cells[3]), square[3]),
                        )
                    )
            x += core_m
        y += core_m
    return out


def core_size_for(
    labelled: gpd.GeoDataFrame, workers: int
) -> tuple[float, list[tuple[float, float, float, float]]]:
    """The largest grouping square that still gives the pool enough jobs to stay busy.

    **Wall time is set by the slowest single core, not by total work.** That is the lesson of
    Karachi: 18 labelled cells grouped into 3 cores of 4 km, run against 24 workers, so 21 of
    them sat idle for 25 hours while three did everything — and each of those three then tripped
    the ETC ceiling and subdivided into six sub-cores *serially inside one worker*. The city
    produced eighteen tessellations either way. The only difference the grouping made was whether
    they could run at the same time.

    So the square is chosen by measuring, not by modelling: `cores_for` is called at each
    candidate size and the largest one meeting the target is taken. Measuring rather than
    dividing labelled area by `size**2` matters because labelled cells are sparse and clustered —
    a size that should yield 30 cores on area alone yields 18 when they are scattered one to a
    square, and the error runs in the direction that starves the pool.

    Descending, because a larger square is better where it is affordable: processed area per core
    is `(size + 2 * BUFFER_M)**2`, so the buffer overhead is x3.06 at 4 km against x11.2 at
    1.28 km. `CORE_MIN_M` is one labelled cell — below that a single cell spans several cores,
    each paying the full 3 km buffer to describe a sliver of it, which is waste with no
    parallelism left to buy.
    """
    target = max(JOBS_PER_WORKER * workers, MIN_JOBS)
    cores: list[tuple[float, float, float, float]] = []
    for size in CORE_SIZES_M:
        cores = cores_for(labelled, size)
        if len(cores) >= target:
            return size, cores
    return CORE_SIZES_M[-1], cores


def worker_pool(n_workers: int) -> ProcessPoolExecutor:
    """A `forkserver` pool, per this package's own hard-won precedent.

    `fork` deadlocks once the parent has been through DuckDB, GEOS and NumPy — measured in Phase 8
    as a parent and 32 workers sitting at zero CPU for 14h50m. See
    `lczkit.cleaning.streets._worker_pool` for the full reasoning.

    **Unlike that one, `__main__` is deliberately *not* hidden here.** It hides `__main__` because
    the only callable it sends to a worker lives in an importable module and is referenced by
    qualified name, so re-executing the entry point would be pure cost. `compute_core` is defined
    in *this script*, so a child that cannot import `__main__` cannot unpickle it — tried, and it
    fails as `Can't get attribute 'compute_core' on <module '__main__'>` surfacing as a
    `BrokenProcessPool`. Re-executing is cheap here anyway: everything this module imports at
    module scope is already in the forkserver preload, and `main()` is guarded.
    """
    context = multiprocessing.get_context("forkserver")
    context.set_forkserver_preload(["lczkit.cleaning.pipeline", "lczkit.morphometrics.compute"])
    return ProcessPoolExecutor(max_workers=n_workers, mp_context=context)


def prefetch_city(city: str, bounds: BBox, settings: Settings) -> dict:
    """Cache Overture over a city's whole extent, for a later whole-grid pass.

    **This does not speed up the per-core compute, and is not meant to.** `OvertureSource`'s cache
    is keyed on the exact bbox string (`lczkit.sources.overture.bbox_key`) with no containment
    lookup, so a 20 km prefetch tile is never served to a core asking for its own 7 km window.
    The two are additive: this exists so that inference over the *full* grid later needs no
    re-download, which is what was asked for. Run it alongside the compute rather than in front of
    it — it is network-bound and they barely contend.
    """
    started = time.perf_counter()
    tiles = fetch_tiles(bounds, FETCH_TILE_KM)
    source = OvertureSource(settings)
    cleaning = settings.cleaning.model_copy(
        update={"street_tile_size_m": None, "street_tile_buffer_m": None}
    )
    failed = 0
    for i, tile in enumerate(tiles, 1):
        try:
            clean_vectors(source, tile, cleaning, cache_dir=settings.tile_cache_dir)
        except Exception as error:
            failed += 1
            if failed <= 3:
                print(f"    fetch {i}/{len(tiles)} skipped: {type(error).__name__}", flush=True)
        if i % 10 == 0 or i == len(tiles):
            print(f"    fetched {i}/{len(tiles)} tiles ({failed} skipped)", flush=True)
    return {
        "city": city,
        "status": "prefetched",
        "tiles": len(tiles),
        "failed": failed,
        "seconds": round(time.perf_counter() - started, 1),
    }


def run_city(city: str, bounds: BBox, settings: Settings, workers: int, fetch: bool) -> dict:
    grid_path = city_grid(city)
    if grid_path is None:
        return {"city": city, "status": "no_grid"}

    grid = gpd.read_file(grid_path)
    labelled = grid[grid["is_valid"]] if "is_valid" in grid.columns else grid
    if len(labelled) == 0:
        return {"city": city, "status": "no_labelled_cells"}

    folder = folder_for(city)
    out_dir = settings.run_dir / "cities" / folder
    parquet_path = out_dir / f"{folder}_morphometrics.parquet"
    raster_path = out_dir / f"{folder}_morphometrics.tif"
    params_path = out_dir / f"{folder}_morphometrics.params.json"
    # **A finished city is skipped only if it was finished under *this* definition.** Presence of
    # the two files was the whole test before, so changing `BUFFER_M` and restarting would have
    # left the cities already on disk untouched and computed the rest differently -- a 48-city
    # dataset carrying two definitions of the same 50 columns, silently, which is the one outcome
    # this extraction exists to prevent. The sidecar says what a city was built with; a city with
    # no sidecar predates the stamp and is rebuilt rather than trusted.
    if parquet_path.exists() and raster_path.exists():
        recorded = None
        if params_path.exists():
            try:
                recorded = json.loads(params_path.read_text())
            except json.JSONDecodeError:
                recorded = None
        if recorded == result_parameters():
            return {"city": city, "status": "already_done"}
        why = "no parameter record" if recorded is None else "built under a different definition"
        print(f"    rebuilding: {why}", flush=True)

    origin = (float(grid.total_bounds[0]), float(grid.total_bounds[3]))
    core_m, cores = core_size_for(labelled, workers)
    info: dict = {
        "city": city,
        "crs": str(grid.crs),
        "cells": len(grid),
        "labelled": len(labelled),
        "labelled_km2": round(len(labelled) * 1.6384, 1),
        "cores": len(cores),
        "core_m": core_m,
    }
    started = time.perf_counter()

    if fetch:
        tiles = fetch_tiles(bounds, FETCH_TILE_KM)
        info["fetch_tiles"] = len(tiles)
        source = OvertureSource(settings)
        cleaning = settings.cleaning.model_copy(
            update={"street_tile_size_m": None, "street_tile_buffer_m": None}
        )
        for i, tile in enumerate(tiles, 1):
            try:
                clean_vectors(source, tile, cleaning, cache_dir=settings.tile_cache_dir)
            except Exception as error:
                print(f"    fetch {i}/{len(tiles)} skipped: {type(error).__name__}", flush=True)
            if i % 10 == 0 or i == len(tiles):
                print(f"    fetched {i}/{len(tiles)} tiles", flush=True)
        info["fetch_seconds"] = round(time.perf_counter() - started, 1)

    # Stamped, because `enqueue` reuses any leaf parquet it finds here by path alone and cannot
    # tell one computed at a different buffer from one computed at this buffer.
    scratch = settings.run_dir / "_scratch" / f"{folder}__{result_stamp()}"
    scratch.mkdir(parents=True, exist_ok=True)

    def job_for(core: tuple[float, float, float, float], stem: str, depth: int) -> dict:
        return {
            "core": core,
            "crs": str(grid.crs),
            "stem": stem,
            "depth": depth,
            "run_id": settings.run_id,
        }

    jobs = [job_for(c, str(scratch / f"core_{i:05d}"), 0) for i, c in enumerate(cores)]

    t0 = time.perf_counter()
    paths: list[str] = []
    failures = 0
    done = 0
    splits = 0
    reused = 0
    submitted = 0
    # Every status, not just failures. `no_core_etcs` is the one that matters: it means the core
    # was tessellated and then nothing was kept, which is expected only where a core holds no
    # labelled ground at all. A run where it is common is a run with a geometry defect in it.
    outcomes: Counter[str] = Counter()
    # **The job list grows while it is being worked**, so the pool is driven directly rather than
    # through `pool.map`, which takes a fixed iterable. A core too dense to tessellate comes back
    # as `split` and its four quarters are queued as jobs of their own. The pool is sized for
    # `workers` and not for the cores known up front, because on a city like Bogota -- 2 labelled
    # cells, 2 cores -- the quarters are the only thing that can fill it.
    with worker_pool(workers) as pool:
        futures: dict = {}

        def enqueue(job: dict) -> None:
            """Submit `job`, or settle it from scratch where an earlier run already did the work.

            A leaf whose parquet is on disk is taken as-is. A core whose quarter files exist is
            known to have split, so its quarters are queued *without* re-running the tessellation
            that discovers a split -- which is the expensive half: on Bogota's dense core it ran
            two hours before raising, and it would be paid again on every restart otherwise.
            """
            nonlocal reused, splits, submitted
            stem = Path(job["stem"])
            leaf = stem.with_suffix(".parquet")
            if leaf.exists():
                paths.append(str(leaf))
                outcomes["reused"] += 1
                reused += 1
                return
            if job["depth"] < MAX_SPLIT_DEPTH and any(stem.parent.glob(f"{stem.name}_q*.parquet")):
                splits += 1
                for q, sub_core in enumerate(quarters(tuple(job["core"]))):
                    enqueue(job_for(sub_core, f"{stem}_q{q}", job["depth"] + 1))
                return
            futures[pool.submit(compute_core, job)] = job
            submitted += 1

        for job in jobs:
            enqueue(job)

        while futures:
            finished, _ = wait(list(futures), return_when=FIRST_COMPLETED)
            for future in finished:
                futures.pop(future, None)
                result = future.result()
                done += 1
                outcomes[result["status"]] += 1
                if result["status"] == "ok":
                    paths.extend(result["paths"])
                elif result["status"] == "split":
                    splits += 1
                    for q, sub_core in enumerate(quarters(tuple(result["core"]))):
                        enqueue(job_for(sub_core, f"{result['stem']}_q{q}", result["depth"] + 1))
                elif result["status"] == "error":
                    failures += 1
                    if failures <= 5:
                        print(f"    core failed: {result['error']}", flush=True)
                if done % 25 == 0 or not futures:
                    print(
                        f"    cores {done}/{submitted} computed, {reused} reused, "
                        f"{splits} split, {len(paths)} with data, {failures} failed",
                        flush=True,
                    )
    info["core_failures"] = failures
    info["core_outcomes"] = dict(outcomes)
    info["core_splits"] = splits
    info["cores_submitted"] = submitted
    if reused:
        info["cores_reused_from_scratch"] = reused
    info["compute_seconds"] = round(time.perf_counter() - t0, 1)
    empty = outcomes.get("no_core_etcs", 0) + outcomes.get("mixed_empty", 0)
    if empty:
        print(
            f"    {empty}/{submitted} cores tessellated but kept nothing ({dict(outcomes)})",
            flush=True,
        )

    if not paths:
        return {**info, "status": "no_etcs"}

    frames = [gpd.read_parquet(p) for p in paths]
    # `pd.concat` drops the CRS and the stamp below would assert whatever the first frame happens
    # to carry, so a part written in another CRS would be silently relabelled rather than raise.
    # Cores are pinned to the grid CRS in `_one_core`; this is what says so.
    # Compared as CRS objects, never as strings. `str()` of a CRS round-tripped through GeoParquet
    # is the full PROJJSON; `str()` of one read from a GeoPackage is "EPSG:32650". They are the
    # same CRS and the strings differ by two thousand characters, so a string comparison here
    # rejected every city on its first run — the guard failing rather than the thing it guards.
    # `pyproj`'s own equality is what knows two representations describe one projection.
    mismatched = sorted({f.crs.to_string() for f in frames if f.crs != grid.crs})
    if mismatched:
        # Also what the raster depends on: `origin` below is read off the grid's bounds, so an
        # ETC layer in any other CRS would anchor the pixel lattice to a meaningless point.
        raise RuntimeError(
            f"{city}: cores came back in {mismatched}, expected the grid's {grid.crs.to_string()}"
        )
    etcs = gpd.GeoDataFrame(pd.concat(frames), crs=frames[0].crs)
    # Cores tile without overlap and their ids are namespaced by core, so a duplicate here is a
    # defect rather than an expected collision. It is counted and reported rather than dropped
    # quietly: this line silently discarded 84.9% of Hong Kong before the ids were namespaced,
    # and a `drop_duplicates` that never says how much it dropped cannot be told from one that
    # had nothing to do.
    duplicated = int(etcs.index.duplicated(keep="first").sum())
    if duplicated:
        info["duplicate_unit_ids"] = duplicated
        print(
            f"    WARNING: {duplicated:,} duplicate unit_ids across cores "
            f"({duplicated / len(etcs):.1%}) — ids should be namespaced per core",
            flush=True,
        )
        etcs = etcs[~etcs.index.duplicated(keep="first")]
    info["etcs"] = len(etcs)

    out_dir.mkdir(parents=True, exist_ok=True)
    etcs.to_parquet(parquet_path)

    t0 = time.perf_counter()
    # **COG, not plain GeoTIFF, and the reason is the nodata.** Labelled cells are ~6% of a city
    # grid and clustered, but the raster covers their whole bounding rectangle — measured at
    # **91.1% nodata** on Hong Kong. Uncompressed that is 442 GB across the 48 cities, against
    # 429 GB free on a *shared* volume already at 100%. The COG driver compresses (LZW) and tiles
    # by default, and on the same input writes **1.720 GB -> 0.074 GB, 23x smaller, and 29%
    # faster** (2 699 s -> 1 929 s) because there is that much less to write. Same filename and
    # same path, so the So2Sat-mirroring layout is unchanged, and a COG is the better artefact to
    # read a patch out of besides. DEFLATE/ZSTD reach 34x/57x and would need creation options the
    # package does not expose; LZW needs no change here and is the most portable of the three.
    report = rasterize_attributes(
        etcs,
        RESOLUTION_M,
        raster_path,
        columns=COLUMNS,
        origin=origin,
        format="cog",
        max_cells=400_000_000,
        max_bytes=24_000_000_000,
    )
    params_path.write_text(json.dumps(result_parameters(), indent=2, sort_keys=True))
    info["raster_seconds"] = round(time.perf_counter() - t0, 1)
    info["raster_shape"] = [report.n_rows, report.n_cols]
    info["bands"] = len(report.band_names)
    shutil.rmtree(scratch, ignore_errors=True)
    info["status"] = "ok"
    info["total_seconds"] = round(time.perf_counter() - started, 1)
    return info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", default=None, help="comma-separated subset")
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--run-id", default="so2sat-morphometrics")
    ap.add_argument(
        "--no-fetch",
        action="store_true",
        help="skip the full-extent Overture prefetch (per-core cleaning still fetches)",
    )
    ap.add_argument(
        "--fetch-only",
        action="store_true",
        help="only cache Overture over the full extents; compute nothing",
    )
    args = ap.parse_args()

    # Set in the parent, before any pool exists: libgomp and OpenBLAS read these when the library
    # initialises, which is before a pool initializer of ours could run.
    os.environ.update(dict.fromkeys(THREAD_LIMIT_VARS, "1"))

    settings = apply_preset(Settings.load(run_id=args.run_id))
    settings.overture.duckdb_threads = DUCKDB_THREADS_PER_WORKER
    from lczkit.morphometrics.registry import PARAMETERS

    unknown = sorted(set(COLUMNS) - {p.name for p in PARAMETERS})
    if unknown:
        sys.exit(f"columns not in the registry: {unknown}")

    bounds_df = pd.read_csv(BOUNDS_CSV)
    wanted = set(args.cities.split(",")) if args.cities else None
    ledger = settings.run_dir / (
        "prefetch_log.jsonl" if args.fetch_only else "extraction_log.jsonl"
    )

    print(f"output root : {settings.run_dir}")
    print(f"columns     : {len(COLUMNS)}   resolution {RESOLUTION_M:g} m   buffer {BUFFER_M:g} m")
    print(f"definition  : v{RESULT_VERSION} stamp {result_stamp()} (reuse is confined to this)")
    print(
        f"cores       : {'/'.join(f'{c / 1000:g}' for c in CORE_SIZES_M)} km candidates, "
        f"{args.workers} workers x {DUCKDB_THREADS_PER_WORKER} DuckDB threads "
        f"= {args.workers * DUCKDB_THREADS_PER_WORKER} core ceiling"
    )
    print(
        f"free disk   : {free_gb(settings.run_dir):.0f} GB (floor {MIN_FREE_GB:.0f} GB)\n",
        flush=True,
    )

    # Smallest first, so a run that has to be stopped early still delivers whole cities.
    order = []
    unresolved = []
    for _, r in bounds_df.iterrows():
        city = str(r["JRC_NAME_MAIN"])
        gp = city_grid(city)
        if gp is None and folder_for(city) not in KNOWN_WITHOUT_GRID:
            unresolved.append(city)
        n = len(gpd.read_file(gp)) if gp else 10**9
        order.append((n, city, (r["minx"], r["miny"], r["maxx"], r["maxy"])))
    order.sort()

    # A city the bounds CSV names but whose grid cannot be found is dropped *silently* otherwise,
    # which is how Sao Paulo — one of the source paper's five study sites — went missing on the
    # first run: `JRC_NAME_MAIN` spells it with a diacritic and the folder does not. Refuse rather
    # than quietly extract 44 cities when 46 were asked for.
    if unresolved:
        sys.exit(
            f"no grid found for {len(unresolved)} city/cities the bounds file names: "
            f"{unresolved}. Add a FOLDER_ALIASES entry, or list them in KNOWN_WITHOUT_GRID if "
            "they genuinely have no grid."
        )
    resolved = sum(1 for n, _, _ in order if n < 10**9)
    print(
        f"cities      : {resolved} with a grid, "
        f"{len(order) - resolved} without ({sorted(KNOWN_WITHOUT_GRID)})\n",
        flush=True,
    )

    for n, city, bounds in order:
        if wanted and city not in wanted:
            continue
        if free_gb(settings.run_dir) < MIN_FREE_GB:
            print(
                f"STOPPING: free disk {free_gb(settings.run_dir):.0f} GB below "
                f"{MIN_FREE_GB:.0f} GB floor",
                flush=True,
            )
            break
        print(f"=== {city} ({n:,} grid cells) ===", flush=True)
        try:
            if args.fetch_only:
                info = prefetch_city(city, bounds, settings)
            else:
                info = run_city(city, bounds, settings, args.workers, not args.no_fetch)
        except Exception:
            info = {"city": city, "status": "error", "traceback": traceback.format_exc()}
            print(info["traceback"], flush=True)
        info["free_gb_after"] = round(free_gb(settings.run_dir), 1)
        print(
            f"    -> {json.dumps({k: v for k, v in info.items() if k != 'traceback'})}\n",
            flush=True,
        )
        with ledger.open("a", encoding="utf-8") as f:
            f.write(json.dumps(info) + "\n")

    print("DONE", flush=True)


if __name__ == "__main__":
    main()
