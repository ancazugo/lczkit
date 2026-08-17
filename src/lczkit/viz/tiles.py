"""Vector tiles: GeoParquet in a `GeoDataFrame`, PMTiles out, `tippecanoe` in between.

CLAUDE.md fixes the chain — GeoParquet -> **FlatGeobuf** via `pyogrio` -> tippecanoe -> PMTiles —
and explicitly rules out routing through GeoJSON, which at buildings scale is dramatically slower.
tippecanoe is a subprocess, never linked or vendored, and it is an optional extra (`lczkit[viz]`)
so that the classification pipeline does not acquire a 36 MB binary it never calls.

**The binary is located through the installed package, not `PATH`.** The `tippecanoe` PyPI wheel
ships the real upstream binaries under `tippecanoe.BIN_DIR`, and resolving them that way means the
version tippecanoe reports is the version the lockfile pinned. A `PATH` lookup would silently prefer
whatever a system package manager had put there, which is exactly the reproducibility hole the
manifest exists to close.

Every invocation is recorded verbatim, argv and all, in the site manifest. CLAUDE.md requires the
exact tippecanoe command line to be recorded, and a recorded command is the only way a reader can
tell a tile that is empty because the data was empty from one that is empty because
`--drop-densest-as-needed` threw it away.

**tippecanoe's thread count is capped, and that is a bug workaround with a measurement behind it.**
On this project's 256-core node every tileset failed with `Internal error: 745 shards not a power
of 2`, raised from tippecanoe's radix sort while reordering geometry. Sweeping the thread count
showed 8, 16, 32, 48, 64, 96, 128 and 192 all succeed and only 256 fails, so the shard arithmetic
breaks at the top of the range rather than at a particular value. Decoding two tilesets built at 8
and 128 threads showed **identical tile content** — the only bytes that differ are the output
filename tippecanoe records in its own metadata — so capping costs nothing but wall time, and tile
generation is minutes rather than hours. This is the same shape of defect as Phase 8's `fork`
deadlock: invisible on a laptop, fatal on the machine the package actually runs on.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import pyogrio

TIPPECANOE_EXTRA = "lczkit[viz]"
"""Install target named in the error when the binary is missing. One string, so the message and
the packaging cannot drift apart."""

THREAD_LIMIT_VAR = "TIPPECANOE_MAX_THREADS"
MAX_THREADS = 32
"""Ceiling on tippecanoe's worker threads. See the module docstring: above roughly this, the gain
is nil and at 256 the shard arithmetic fails outright. An operator who has already set
`TIPPECANOE_MAX_THREADS` keeps their value — this is a floor under a broken default, not a policy
about how many cores anyone may use."""


class TippecanoeMissingError(RuntimeError):
    """Raised when a tileset is requested but tippecanoe is not installed."""


@dataclass(frozen=True)
class TilesetReport:
    """One tileset, and exactly how it was produced."""

    name: str
    path: Path
    layers: tuple[str, ...]
    n_features: int
    size_bytes: int
    min_zoom: int
    max_zoom: int
    argv: tuple[str, ...]
    """The full command line, including the binary's resolved path."""

    version: str
    max_threads: str
    """The `TIPPECANOE_MAX_THREADS` the run used. Recorded because it is a workaround for a
    machine-dependent failure, and a reader comparing two runs should be able to see it."""

    seconds: float

    def as_detail(self) -> dict[str, object]:
        """One tileset's row for the manifest: what was built, how big, and at which zooms."""
        return {
            "name": self.name,
            "file": self.path.name,
            "layers": list(self.layers),
            "n_features": self.n_features,
            "size_bytes": self.size_bytes,
            "min_zoom": self.min_zoom,
            "max_zoom": self.max_zoom,
            "seconds": round(self.seconds, 2),
            "tippecanoe_version": self.version,
            "tippecanoe_max_threads": self.max_threads,
            "tippecanoe_argv": list(self.argv),
        }


def tippecanoe_binary() -> Path:
    """Path to the pinned `tippecanoe` executable, or a message saying how to get one."""
    try:
        import tippecanoe
    except ModuleNotFoundError as error:
        raise TippecanoeMissingError(
            "tippecanoe is required to build a map site and is not installed. "
            f"Install the viz extra: pip install '{TIPPECANOE_EXTRA}'"
        ) from error
    binary = Path(tippecanoe.BIN_DIR) / "tippecanoe"
    if not binary.is_file():
        raise TippecanoeMissingError(
            f"the tippecanoe package is installed but {binary} is missing; "
            f"reinstall it: pip install --force-reinstall '{TIPPECANOE_EXTRA}'"
        )
    return binary


def tippecanoe_available() -> bool:
    """Whether a tileset can be built here. For skipping tests, not for silently degrading."""
    try:
        tippecanoe_binary()
    except TippecanoeMissingError:
        return False
    return True


def tippecanoe_version() -> str:
    """The version string the pinned binary reports, for the manifest."""
    result = subprocess.run(
        [str(tippecanoe_binary()), "--version"], capture_output=True, text=True, check=False
    )
    # tippecanoe prints its version banner on stderr and exits non-zero for `--version`.
    return (
        (result.stderr or result.stdout).strip().splitlines()[0]
        if result.stderr or result.stdout
        else "unknown"
    )


def tippecanoe_environment() -> dict[str, str]:
    """The subprocess environment, with the thread ceiling applied unless already set."""
    environment = dict(os.environ)
    if THREAD_LIMIT_VAR not in environment:
        # `sched_getaffinity` rather than `cpu_count`, matching `cleaning.streets`: on a scheduled
        # HPC node the affinity mask is the allocation, and the machine's core count is not.
        environment[THREAD_LIMIT_VAR] = str(min(len(os.sched_getaffinity(0)), MAX_THREADS))
    return environment


def write_flatgeobuf(frame: gpd.GeoDataFrame, path: Path) -> int:
    """Write `frame` to FlatGeobuf in EPSG:4326, returning the feature count.

    Reprojected here rather than by the caller because tippecanoe reads coordinates as lon/lat and
    has no CRS machinery of its own: handing it the projected CRS every other stage of this package
    computes in would produce a tileset covering a few square metres off the coast of Africa, and it
    would do so without complaining.
    """
    if frame.crs is None:
        raise ValueError(f"{path.name}: cannot tile a layer with no CRS")
    exported = frame.to_crs(4326) if frame.crs.to_epsg() != 4326 else frame
    exported = exported[~exported.geometry.is_empty & exported.geometry.notna()]
    pyogrio.write_dataframe(exported, path, driver="FlatGeobuf")
    return len(exported)


def build_tileset(
    layers: dict[str, gpd.GeoDataFrame],
    destination: Path,
    *,
    name: str,
    min_zoom: int,
    max_zoom: int,
    drop_densest: bool = True,
    simplification: int | None = None,
) -> TilesetReport:
    """Tile one or more named layers into a single `.pmtiles` at `destination`.

    Several layers in one tileset rather than one file each: a basemap's water, land use and streets
    are always drawn together, and MapLibre re-requests tiles per *source*, so splitting them would
    triple the request count for tiles that always arrive together anyway.

    `drop_densest` is `--drop-densest-as-needed`, which drops features from tiles that would blow
    the size limit rather than emitting a tile a browser cannot parse. It is on for everything
    except the click-detail tileset, where a dropped feature is a unit whose sidebar would silently
    come up empty — there the right failure is a large tile, not a missing one.

    `simplification` is passed only for the basemap. Context geometry carries no measurement, so it
    is the one thing in the site that may be coarsened for display; the unit and building tilesets
    keep tippecanoe's faithful default, because their vertices are the run's own output.
    """
    binary = tippecanoe_binary()
    environment = tippecanoe_environment()
    destination.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="lczkit-tiles-") as scratch:
        inputs: list[str] = []
        n_features = 0
        for layer_name, frame in layers.items():
            source = Path(scratch) / f"{layer_name}.fgb"
            n_features += write_flatgeobuf(frame, source)
            inputs += ["--named-layer", f"{layer_name}:{source}"]

        argv = [
            str(binary),
            "--output",
            str(destination),
            "--minimum-zoom",
            str(min_zoom),
            "--maximum-zoom",
            str(max_zoom),
            "--force",
            "--quiet",
            # The per-layer statistics tippecanoe embeds are a second, coarser copy of the run's
            # own breaks. The site reads the manifest's, so shipping these would be a second
            # answer to a question the run already answered.
            "--no-tile-stats",
            *(
                ["--drop-densest-as-needed"]
                if drop_densest
                else ["--no-feature-limit", "--no-tile-size-limit"]
            ),
            *([f"--simplification={simplification}"] if simplification else []),
            *inputs,
        ]
        completed = subprocess.run(
            argv, capture_output=True, text=True, check=False, env=environment
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"tippecanoe failed for tileset {name!r} (exit {completed.returncode}, "
                f"{THREAD_LIMIT_VAR}={environment[THREAD_LIMIT_VAR]}):\n"
                f"{completed.stderr.strip()}"
            )

    return TilesetReport(
        name=name,
        path=destination,
        layers=tuple(layers),
        n_features=n_features,
        size_bytes=destination.stat().st_size,
        min_zoom=min_zoom,
        max_zoom=max_zoom,
        argv=tuple(argv),
        version=tippecanoe_version(),
        max_threads=environment[THREAD_LIMIT_VAR],
        seconds=time.perf_counter() - started,
    )


def copy_tree(source: Path, destination: Path) -> None:
    """Copy a vendored asset directory into a site, replacing whatever was there."""
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
