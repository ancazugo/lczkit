"""Seam correctness for Phase 8's tiled street simplification.

**What can and cannot be guaranteed.** `neatnet` groups face artifacts into rook-contiguous
components and simplifies each component as one unit. Those components percolate: on Berlin, 93
percent of artifacts fall into a single component that spans the whole extent (32,966 of 35,293
at 100 km2). No tiling of any size contains that component, so tiled and whole-extent results
cannot be identical everywhere, and a test asserting they are would be asserting something
false.

What *is* guaranteed, and is tested here:

1. A network with no face artifacts is passed through untouched, so a street crossing a seam in
   ordinary fabric is bit-for-bit what the whole-extent path produces.
2. The tiled path invents nothing. Linework the tiled run has and the whole-extent run does not
   is the failure mode that would corrupt downstream enclosures, and it is what pinning the
   artifact threshold removes.
3. One tile covering everything reproduces the whole-extent path exactly — the tiling machinery
   itself introduces no drift.
4. Cores partition, so nothing is dropped or double-counted at a seam.
"""

from __future__ import annotations

import geopandas as gpd
import neatnet
import numpy as np
import pytest
import shapely
from conftest import FIXTURE_BBOX, SMALL_BBOX, FixtureVectorSource
from shapely.geometry import LineString

from lczkit.cleaning.pipeline import reproject_to_local_utm
from lczkit.cleaning.streets import (
    _preprocess,
    _threshold_from_index,
    pooled_artifact_threshold,
    resolve_artifact_threshold,
    seam_disagreement,
    simplify_streets,
    simplify_streets_tiled,
)
from lczkit.cleaning.tiles import build_tiles, layer_extent
from lczkit.crs import assert_projected_crs

CRS = "EPSG:32633"


#: Blocks around a kilometre across: large enough that every face indexes well above the
#: artifact threshold, so `neatnet` finds nothing to simplify and both paths reduce to a
#: topology fix. Roads at 0, 900, 2000, 3100 and 4000 m; with 1000 m tiles the one at x=2000
#: lies exactly along a seam, which is the case that double-counted before edge ownership.
COARSE_OFFSETS = (0.0, 900.0, 2000.0, 3100.0, 4000.0)
COARSE_EXTENT = 4000.0


def _coarse_network() -> gpd.GeoDataFrame:
    """A grid of large blocks: faces exist, but none of them is an artifact.

    This is the network on which the two paths must agree *exactly*, and the reason it is not a
    finer grid is that a finer one is genuinely simplified — the whole-extent path takes a 400 m
    grid from 24 km down to 14.5 km — which would confound tiling with ordinary simplification.

    Two neighbouring shapes are ruled out. A perfectly uniform grid gives every face an identical
    index, making neatnet's kernel density estimate singular so it raises out of scipy; an
    acyclic network encloses nothing at all and raises a `KeyError` on the missing index column.
    Both fail for the whole-extent path exactly as they do for the tiled one, so they are outside
    neatnet's domain rather than tiling bugs.
    """
    lines: list[LineString] = []
    for offset in COARSE_OFFSETS:
        lines.append(LineString([(0.0, offset), (COARSE_EXTENT, offset)]))
        lines.append(LineString([(offset, 0.0), (offset, COARSE_EXTENT)]))
    return gpd.GeoDataFrame(geometry=lines, crs=CRS)


def _grid_network(spacing: float = 400.0, extent: float = 2000.0) -> gpd.GeoDataFrame:
    """A closed, unevenly spaced grid — a network `neatnet` genuinely does simplify.

    Used where the point is that tiling neither loses nor duplicates length, rather than that
    the two paths agree edge for edge.
    """
    lines: list[LineString] = []
    offsets = [i * spacing + (i % 3) * 25.0 for i in range(int(extent // spacing))]
    offsets = [0.0, *offsets[1:], extent]
    for offset in offsets:
        lines.append(LineString([(0.0, offset), (extent, offset)]))
        lines.append(LineString([(offset, 0.0), (offset, extent)]))
    return gpd.GeoDataFrame(geometry=lines, crs=CRS)


def _no_buildings() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=[], crs=CRS)


def test_a_road_crossing_a_seam_is_unchanged_where_there_is_nothing_to_simplify() -> None:
    """The property the tiled path exists to preserve, stated at its strongest.

    Every east-west road here crosses the vertical seam at x=1000. With no artifacts anywhere,
    the tiled result must reproduce the whole-extent result exactly, not approximately.
    """
    streets = _coarse_network()
    tiled, _ = simplify_streets_tiled(
        streets, _no_buildings(), tile_size_m=1000.0, buffer_m=300.0, workers=1
    )
    untiled, _ = simplify_streets(streets, _no_buildings())

    report = seam_disagreement(tiled, untiled)
    assert report["missing_km"] == pytest.approx(0.0, abs=1e-6)
    assert report["extra_km"] == pytest.approx(0.0, abs=1e-6)
    assert report["agreement"] == pytest.approx(1.0)


def test_tiling_leaves_no_break_in_the_middle_of_a_block() -> None:
    """Clipping to cores cuts every seam-crossing street; stitching must heal the cut.

    A leftover break mid-block is the failure that would corrupt Phase 2: enclosure generation
    treats a line end as a boundary, so a spurious node in the middle of a street would partition
    a block that is not divided on the ground.

    Feature *decomposition* is allowed to differ. The tiled path can split a road at a junction
    the whole-extent path happened to carry straight through — both are valid readings of the
    same graph, the geometry is identical either way (see the exactness test above), and only the
    position of the breaks is asserted here.
    """
    streets = _coarse_network()
    tiled, _ = simplify_streets_tiled(
        streets, _no_buildings(), tile_size_m=1000.0, buffer_m=300.0, workers=1
    )
    untiled, _ = simplify_streets(streets, _no_buildings())

    lines = list(untiled.geometry)
    junctions = [
        shapely.Point(coord) for line in lines for coord in (line.coords[0], line.coords[-1])
    ]
    for i, first in enumerate(lines):
        for second in lines[i + 1 :]:
            meeting = first.intersection(second)
            if not meeting.is_empty:
                junctions.extend(shapely.points(shapely.get_coordinates(meeting)))
    nodes = shapely.union_all(junctions)

    for geometry in tiled.geometry:
        for end in (shapely.Point(geometry.coords[0]), shapely.Point(geometry.coords[-1])):
            assert nodes.distance(end) < 1e-6, f"tiled line ends mid-block at {end}"


def test_a_single_tile_reproduces_the_whole_extent_path(
    fixture_vector_source: FixtureVectorSource,
) -> None:
    """Real Berlin topology, one tile big enough to hold it: the machinery must add no drift."""
    _, layers = reproject_to_local_utm(
        SMALL_BBOX,
        buildings=fixture_vector_source.buildings(SMALL_BBOX),
        streets=fixture_vector_source.streets(SMALL_BBOX),
    )
    buildings, streets = layers["buildings"], layers["streets"]

    tiled, step = simplify_streets_tiled(
        streets, buildings, tile_size_m=100_000.0, buffer_m=500.0, workers=1
    )
    untiled, _ = simplify_streets(streets, buildings)

    assert step.detail["n_tiles"] == 1
    report = seam_disagreement(tiled, untiled)
    assert report["missing_km"] == pytest.approx(0.0, abs=1e-6)
    assert report["extra_km"] == pytest.approx(0.0, abs=1e-6)


def test_the_tiled_path_reports_what_it_did(
    fixture_vector_source: FixtureVectorSource,
) -> None:
    """The pinned threshold and tile count belong in the cleaning report, not only in behaviour.

    A run that silently tiled differently from another run is a run whose numbers cannot be
    compared, and Phase 1's report is where that has to be visible.
    """
    _, layers = reproject_to_local_utm(
        SMALL_BBOX,
        buildings=fixture_vector_source.buildings(SMALL_BBOX),
        streets=fixture_vector_source.streets(SMALL_BBOX),
    )
    _, step = simplify_streets_tiled(
        layers["streets"], layers["buildings"], tile_size_m=400.0, buffer_m=200.0, workers=1
    )
    assert step.stage == "streets"
    assert step.operation == "simplify_streets_tiled"
    assert step.detail["tiled"] is True
    assert step.detail["n_tiles"] > 1
    assert step.detail["tile_size_m"] == 400.0
    assert step.detail["buffer_m"] == 200.0
    assert isinstance(step.detail["artifact_threshold"], float)


def test_the_whole_extent_path_says_it_did_not_tile() -> None:
    streets = _grid_network()
    _, step = simplify_streets(streets, _no_buildings())
    assert step.operation == "simplify_streets"
    assert step.detail["tiled"] is False


def test_the_artifact_threshold_falls_back_when_there_are_no_faces_to_index() -> None:
    """Pinning is the seam-correctness lever, so the resolver must be deterministic and total.

    A grid of large blocks yields no kernel-density valley: neatnet returns `None`, and the
    tiled path must land on the value `neatify` itself would use.
    """
    streets = _coarse_network()
    assert resolve_artifact_threshold(streets, fallback=7.0) == 7.0
    assert resolve_artifact_threshold(streets, fallback=9.5) == 9.5


def test_the_artifact_threshold_survives_a_degenerate_network() -> None:
    """A perfectly uniform grid makes neatnet's kernel density estimate singular.

    It raises out of scipy rather than returning `None`. One such tile must not end a run over a
    whole city, so the resolver falls back instead of propagating.
    """
    lines = [LineString([(0.0, i * 100.0), (400.0, i * 100.0)]) for i in range(5)]
    lines += [LineString([(i * 100.0, 0.0), (i * 100.0, 400.0)]) for i in range(5)]
    uniform = gpd.GeoDataFrame(geometry=lines, crs=CRS)
    assert resolve_artifact_threshold(uniform, fallback=7.0) == 7.0


def test_the_threshold_is_measured_after_the_preprocessing_neatify_applies() -> None:
    """`neatify` runs `fix_topology` and `consolidate_nodes` before it indexes any face.

    Unnoded crossings enclose nothing until they are noded, so a raw network can look
    artifact-free when the network actually simplified is dense with artifacts. Measuring before
    that step would pin a threshold taken from a different network than the one it is applied
    to — the exact failure pinning exists to prevent.
    """
    streets = _grid_network()
    assert resolve_artifact_threshold(streets, fallback=7.0) != 7.0


def test_tiled_simplification_requires_a_projected_crs() -> None:
    streets = gpd.GeoDataFrame(geometry=[LineString([(0.0, 0.0), (1.0, 1.0)])], crs="EPSG:4326")
    with pytest.raises(ValueError, match="projected CRS"):
        simplify_streets_tiled(
            streets, _no_buildings(), tile_size_m=1000.0, buffer_m=100.0, workers=1
        )


def test_tiled_output_keeps_a_projected_crs_and_line_geometry() -> None:
    streets = _grid_network()
    tiled, _ = simplify_streets_tiled(
        streets, _no_buildings(), tile_size_m=1000.0, buffer_m=300.0, workers=1
    )
    assert_projected_crs(tiled, "tiled")
    assert tiled.crs == streets.crs
    assert tiled.geometry.is_valid.all()
    assert tiled.geometry.geom_type.isin(["LineString", "MultiLineString"]).all()


def test_per_tile_results_are_cached_and_reused(tmp_path: object) -> None:
    """A cache hit must be indistinguishable from a recomputation, and must actually be a hit."""
    from pathlib import Path

    cache_dir = Path(str(tmp_path)) / "tiles"
    streets = _grid_network()
    first, _ = simplify_streets_tiled(
        streets,
        _no_buildings(),
        tile_size_m=1000.0,
        buffer_m=300.0,
        workers=1,
        cache_dir=cache_dir,
        cache_fingerprint="testfp",
    )
    written = sorted(cache_dir.rglob("*.parquet"))
    assert written, "expected per-tile parquet files to be written"

    second, step = simplify_streets_tiled(
        streets,
        _no_buildings(),
        tile_size_m=1000.0,
        buffer_m=300.0,
        workers=1,
        cache_dir=cache_dir,
        cache_fingerprint="testfp",
    )
    assert step.detail["cached"] is True
    assert seam_disagreement(second, first)["agreement"] == pytest.approx(1.0)


def test_the_cache_key_separates_different_tilings(tmp_path: object) -> None:
    """Different buffers are different answers; they must not collide in the cache.

    The tile key alone is aligned to the CRS origin and shared across runs, which is what makes
    the cache useful and also what makes an under-specified key dangerous.
    """
    from pathlib import Path

    cache_dir = Path(str(tmp_path)) / "tiles"
    streets = _grid_network()
    for buffer_m, fingerprint in ((200.0, "fp-a"), (400.0, "fp-b")):
        simplify_streets_tiled(
            streets,
            _no_buildings(),
            tile_size_m=1000.0,
            buffer_m=buffer_m,
            workers=1,
            cache_dir=cache_dir,
            cache_fingerprint=fingerprint,
        )
    assert len({path.parent.name for path in cache_dir.rglob("*.parquet")}) == 2


def test_seam_disagreement_compares_only_common_ground() -> None:
    """The metric's own trap, guarded.

    A whole-extent run keeps streets that merely *intersect* its window, so its result reaches
    past the edge; the tiled run is clipped to cores. Comparing them unclipped charges the tiled
    path for the perimeter overhang. Measured on 16 km2 of Berlin that was 48 km of 425 km — it
    read as 88.6 percent agreement when the two actually agreed.
    """
    inner = gpd.GeoDataFrame(geometry=[LineString([(0.0, 0.0), (100.0, 0.0)])], crs=CRS)
    reaching = gpd.GeoDataFrame(geometry=[LineString([(0.0, 0.0), (500.0, 0.0)])], crs=CRS)
    report = seam_disagreement(inner, reaching)
    assert report["agreement"] == pytest.approx(1.0)
    assert report["missing_km"] == pytest.approx(0.0, abs=1e-9)


def test_a_road_running_along_a_seam_is_emitted_once() -> None:
    """Cores partition by area but *share their boundary lines*, so a road lying along a seam is
    inside both neighbours' closed cores.

    Clipping each tile to its core therefore emitted that road twice: measured at 30.9 km of
    output from 24.0 km of input on a grid aligned to the tiling. That is not a contrived case —
    tiles are axis-aligned to the CRS origin and so are a great many streets. The road at
    x=2000 here lies exactly along a seam of the 1000 m tiling.
    """
    streets = _coarse_network()
    tiled, _ = simplify_streets_tiled(
        streets, _no_buildings(), tile_size_m=1000.0, buffer_m=300.0, workers=1
    )
    total = sum(geometry.length for geometry in tiled.geometry)
    assert total == pytest.approx(streets.geometry.union_all().length, rel=1e-9)


def test_tiles_partition_so_nothing_is_counted_twice() -> None:
    """Total simplified length must not inflate on a network neatnet genuinely does simplify."""
    streets = _grid_network()
    tiled, _ = simplify_streets_tiled(
        streets, _no_buildings(), tile_size_m=500.0, buffer_m=200.0, workers=1
    )
    union_length = tiled.geometry.union_all().length
    summed_length = sum(geometry.length for geometry in tiled.geometry)
    # Summing features and unioning them agree only when no two features overlap.
    assert summed_length == pytest.approx(union_length, rel=1e-6)


def test_an_empty_tile_contributes_nothing_rather_than_failing() -> None:
    """A city with water or parkland has empty tiles; they must not abort the run."""
    corner = gpd.GeoDataFrame(
        geometry=[LineString([(10.0, 10.0), (200.0, 200.0)])],
        crs=CRS,
    )
    tiled, step = simplify_streets_tiled(
        corner, _no_buildings(), tile_size_m=100.0, buffer_m=10.0, workers=1
    )
    assert len(tiled) > 0
    assert step.detail["n_tiles"] >= 1
    assert shapely.union_all(tiled.geometry.to_numpy()).length == pytest.approx(
        corner.geometry.iloc[0].length, rel=1e-6
    )


# --------------------------------------------------------------------------------------------
# Phase 8's three scaling fixes. Each replaces a whole-network step with a local one, so each
# test below is an equivalence test in miniature; the extent-scale versions are in
# `docs/experiments/phase-8-scaling.md`.
# --------------------------------------------------------------------------------------------


def test_threshold_from_index_reproduces_face_artifacts(
    fixture_vector_source: FixtureVectorSource,
) -> None:
    """The pooled selection rule must be neatnet's rule, not merely one that resembles it.

    `_threshold_from_index` restates `neatnet.FaceArtifacts`'s kernel-density valley search so
    the distribution can be assembled tile by tile. Restating it invites drift, and this is the
    guard: exact equality, not approximate, on the same distribution.
    """
    _, layers = reproject_to_local_utm(
        FIXTURE_BBOX, streets=fixture_vector_source.streets(FIXTURE_BBOX)
    )
    faces = neatnet.FaceArtifacts(_preprocess(layers["streets"]))
    values = faces.polygons["face_artifact_index"].to_numpy(dtype=float)
    assert _threshold_from_index(values) == faces.threshold


def test_threshold_from_index_reports_no_valley_rather_than_guessing() -> None:
    """A distribution with no valley between peaks yields `None`, as `FaceArtifacts` does."""
    assert _threshold_from_index(np.linspace(0.0, 1.0, 500)) is None


def test_pooled_threshold_matches_the_whole_network_on_the_fixture(
    fixture_vector_source: FixtureVectorSource,
) -> None:
    """The quadratic whole-network resolver and the pooled one must agree where both are cheap.

    Pooling exists because `resolve_artifact_threshold` runs `neatnet.fix_topology` over the
    whole extent, which is quadratic in feature count — ~8.6 hours at metropolitan scale. It is
    only worth having if it gets the same answer, so at fixture scale, with tiles large enough
    that no face is cut by a window boundary, "the same answer" means exactly equal.
    """
    _, layers = reproject_to_local_utm(
        FIXTURE_BBOX,
        streets=fixture_vector_source.streets(FIXTURE_BBOX),
    )
    streets = layers["streets"]
    tiles = build_tiles(
        layer_extent(streets), tile_size_m=1500.0, buffer_m=600.0, crs_hint="streets"
    )
    pooled = pooled_artifact_threshold(streets, tiles, workers=1)

    assert len(tiles) > 1
    # Both sides must find a real kernel-density valley. Agreeing on the fallback would be
    # agreement about nothing -- `SMALL_BBOX` does exactly that, at 137 faces.
    assert pooled.fallback_used is False
    assert pooled.n_faces_dropped == 0
    assert pooled.value == resolve_artifact_threshold(streets)


def test_pooled_threshold_reports_the_faces_it_had_to_drop(
    fixture_vector_source: FixtureVectorSource,
) -> None:
    """The approximation's error term must be a reported number, not an assumption.

    A face larger than the buffer is cut by its tile's window and cannot be indexed honestly, so
    it is dropped. CLAUDE.md calls that error unbounded until measured; these are the fields that
    measure it, and they have to travel into the cleaning report rather than stay internal.
    """
    _, layers = reproject_to_local_utm(
        SMALL_BBOX,
        streets=fixture_vector_source.streets(SMALL_BBOX),
    )
    streets = layers["streets"]
    tiles = build_tiles(
        layer_extent(streets), tile_size_m=400.0, buffer_m=100.0, crs_hint="streets"
    )
    pooled = pooled_artifact_threshold(streets, tiles, workers=1)

    assert pooled.n_faces > 0
    assert pooled.n_faces_dropped > 0, "a 100 m buffer must cut some face"
    assert 0.0 < pooled.dropped_area_fraction < 1.0
    detail = pooled.as_detail()
    assert detail["threshold_source"] == "pooled"
    assert detail["threshold_n_faces_dropped"] == pooled.n_faces_dropped


def test_tiled_simplification_runs_across_processes() -> None:
    """The worker pool must survive a parent that has already used threaded native libraries.

    `ProcessPoolExecutor`'s default `fork` context inherits locks held by threads that do not
    exist in the child. At metropolitan scale that showed up as the parent and all 32 workers
    sitting at zero CPU for 14h50m. Every other test here runs `workers=1` and so cannot see it.
    """
    streets = _coarse_network()
    warmed = np.random.default_rng(0).random((256, 256))
    warmed @ warmed  # touch BLAS in the parent, which is the condition that deadlocked fork

    parallel, step = simplify_streets_tiled(
        streets, _no_buildings(), tile_size_m=1000.0, buffer_m=300.0, workers=2
    )
    serial, _ = simplify_streets_tiled(
        streets, _no_buildings(), tile_size_m=1000.0, buffer_m=300.0, workers=1
    )

    assert step.detail["workers"] == 2
    report = seam_disagreement(parallel, serial)
    assert report["missing_km"] == pytest.approx(0.0, abs=1e-9)
    assert report["extra_km"] == pytest.approx(0.0, abs=1e-9)


def test_a_configured_threshold_overrides_the_pooled_one() -> None:
    """Pinning the threshold explicitly is what an A/B between two thresholds needs."""
    streets = _grid_network()
    _, step = simplify_streets_tiled(
        streets,
        _no_buildings(),
        tile_size_m=500.0,
        buffer_m=200.0,
        workers=1,
        artifact_threshold=9.25,
    )
    assert step.detail["artifact_threshold"] == 9.25
    assert step.detail["threshold_source"] == "configured"
