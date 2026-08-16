"""WUDAPT LCZ training areas, reduced to one label per spatial unit.

The third reference, and the only one that reaches every city this package has been run on.
CLAUDE.md names it "the secondary validation reference and the first if So2Sat doesn't have
sufficient labels for a ROI"; measured over the sixteen study windows it carries 119-2374 polygons
each, 11-18 classes, and **63-996 km2 of labelled ground against So2Sat's 7.1 km2 union on
Berlin** - one to two orders of magnitude more labelled area, at neighbourhood scale.

**Why the reduction is areal here and not centroid-anchored.** `labelled_lcz` anchors each So2Sat
label on its patch centre, and that rule is justified by a property WUDAPT does not have: So2Sat
patches are uniform 320 m squares on a 100 m stride, so a centroid is an exact, non-double-counting
stand-in for the patch. WUDAPT polygons are hand-drawn and span 0 m2 to 18 680 km2, with a median
of 4.8 ha across the whole file. A centroid rule would let a 4.8 ha polygon and a 1000 km2 polygon
each label exactly one unit, which is not a sampling scheme but a discarding of almost all of the
reference. So the reduction is an areal overlay, and `reference_coverage` is genuinely fractional
here - unlike `labelled_lcz`, where it is deliberately binary.

**The overlaps are real and are resolved before the overlay, not during it.** Contributions come
from different submissions in different years - `representative_date` spans 1983 to 2025 - and they
overlap each other: in a 15 x 12 km Kowloon window, 803 polygons form 3330 overlapping pairs of
which 560 carry *different* classes. Overlaying that directly would count the same ground several
times under labels that contradict each other, and the "majority" would measure contributor
enthusiasm rather than the city. `resolve_overlaps` gives each piece of ground to exactly one
polygon by an explicit priority, and reports how much ground was contested and how much was merely
duplicated - the contributors' own disagreement rate is a number worth having rather than hiding.

**Two things about this file that will mislead a reader who trusts it.**

- The stored `area` column is **not** area in any usable unit: it is km2 computed in Web Mercator,
  so it is inflated by 1/cos^2(latitude) - the median ratio to true area is 1 004 995 against
  Mollweide's 744 899. Nothing here reads it; `test_validation_wudapt.py` asserts that.
- `class` runs 1 to **19**, not 1 to 17. 633 polygons globally carry codes 18 and 19, which are
  outside the Demuzere/So2Sat coding this package uses everywhere else. They are dropped and
  counted, never mapped onto a neighbouring class.

**WUDAPT is not independent of `lcz_v3`.** The LCZ Generator's training areas are the training
data behind the Demuzere global map, so an agreement figure between the two is inflated by
construction and is *not* a ceiling in the sense Phase 6.7 established for So2Sat. Report it only
with that stated beside it.

Returns the same three columns as `reference_lcz` and `labelled_lcz`, so `agreement()` consumes
any of the three without knowing which it was given.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely
from pyproj import CRS

from lczkit.classify.labels import CODES
from lczkit.config import WudaptConfig
from lczkit.protocols import BBox
from lczkit.units import check_units

WUDAPT_SOURCE_DIR_NAME = "WUDAPT"
"""`input/<name>/` holding the LCZ Generator training-area export."""

WUDAPT_CITATION = "10.3390/ijgi4010199"
"""Bechtel et al. (2015), *IJGI* 4(1), 199-219 - the WUDAPT Level 0 protocol these areas follow.
The LCZ Generator itself is Demuzere, Kittner & Bechtel (2021), `10.3389/fenvs.2021.637455`."""

CLASS_COLUMN = "class"
"""WUDAPT's own class column. Integer, and 1-17 agrees with Demuzere's coding - but see
`UNSUPPORTED_CLASSES`, because it does not stop at 17."""

UNSUPPORTED_CLASSES: tuple[int, ...] = (18, 19)
"""Codes present in the file and absent from `lczkit.classify.labels.CODES`.

633 polygons of 630 311 globally. They are dropped rather than folded into a neighbouring class:
this package has no definition for them, and inventing one would put a label into the reference
that no contributor ever drew.
"""

QC_COLUMNS: tuple[str, ...] = ("qc_step1", "qc_step2", "qc_step3")
"""The LCZ Generator's three submission quality-control flags, stored as strings."""

_TRUE = frozenset({"True", "true", "T", "t", "TRUE", "1"})
_FALSE = frozenset({"False", "false", "F", "f", "FALSE", "0"})
"""The flags are not consistently encoded - both `'True'`/`'False'` and `'T'`/`'F'` occur across
the file. Parsing only one spelling would read the other as null and silently gate on it."""

PRIORITY_COLUMNS: tuple[str, ...] = ("representative_date", "oa", "submission_date")
"""Columns `resolve_overlaps` reads to rank contested ground. Absent columns are skipped."""

READ_COLUMNS: tuple[str, ...] = (
    CLASS_COLUMN,
    *QC_COLUMNS,
    "submission_id",
    "submission_date",
    "representative_date",
    "city",
    "oa",
    "license",
)
"""Everything the loader needs. Reading 40 columns over 630 311 features to use nine of them is
the difference between a fixture build that takes seconds and one that takes minutes."""

COLUMNS = ("reference_lcz", "reference_coverage", "reference_majority_fraction")


@dataclass(frozen=True)
class WudaptSelection:
    """What `prepare_wudapt` kept, what it dropped, and what the contributors disagreed about.

    Every drop is counted rather than being visible only as a smaller frame. The point is the same
    one Phase 1's cleaning report makes: a reference that quietly loses half its polygons to a
    quality gate looks exactly like one that never had them.
    """

    n_read: int
    n_kept: int

    n_dropped_invalid: int
    """Non-polygonal or unrepairable geometry. About 1.0% of the file self-intersects."""

    n_dropped_unsupported_class: int
    """Codes in `UNSUPPORTED_CLASSES`, or null."""

    n_dropped_qc: int
    """Failed the quality gate. Zero when `WudaptConfig.require_qc` is off, which is the default -
    the gate costs 51.8% of the file, so it is offered rather than imposed."""

    n_dropped_accuracy: int
    """Below `WudaptConfig.min_oa`. `oa` is a property of the *submission*, not the polygon."""

    n_dropped_area: int
    """Outside `WudaptConfig.min_area_m2` / `max_area_m2`."""

    qc_pass_fraction: float
    """Share of the read polygons passing all three QC flags, reported whether or not the gate is
    on, so the cost of turning it on is visible without a second run."""

    n_overlapping_pairs: int
    """Pairs of kept polygons whose interiors overlap, in one direction each."""

    n_conflicting_pairs: int
    """Of those, the pairs carrying *different* classes - contributors disagreeing about ground,
    as opposed to re-drawing it."""

    duplicate_area_m2: float
    """Ground a polygon yielded to a higher-priority polygon of the **same** class. Redundancy."""

    conflict_area_m2: float
    """Ground a polygon yielded to a higher-priority polygon of a **different** class. This is the
    reference disagreeing with itself, and it belongs in the write-up beside any figure measured
    against it."""

    labelled_area_m2: float
    """Area of the resolved, non-overlapping polygons. The reference's actual support."""

    date_min: str | None
    date_max: str | None
    """Range of `representative_date` among the kept polygons. A reference spanning four decades is
    not a snapshot, and a city that redeveloped inside that span will disagree with any single map
    for reasons that are not the map's error."""

    licences: tuple[str, ...] = ()
    """Distinct `license` values among the kept polygons, read from the data rather than assumed.
    Most of the file is `CC BY-NC-SA 4.0` or `CC BY-SA` - **non-commercial in the first case**.
    That constrains the data, not this MIT package, and nothing here redistributes it; it is
    recorded so a run's manifest states the terms of what it was scored against."""

    cities: tuple[str, ...] = ()
    """Distinct `city` strings among the kept polygons. Free text and not normalised upstream -
    `Wuhan` and `wuhan` are different submissions - so this is provenance, never a join key."""


@dataclass(frozen=True)
class WudaptMatch:
    """How the resolved polygons landed on the units.

    The analogue of `LabelMatch`, and it exists for the same reason: a reference that reaches a
    tenth of the study area produces exactly the same column set as one that reaches all of it.
    """

    n_polygons: int
    n_units: int
    n_units_labelled: int
    """Units receiving any labelled ground at all, before `min_reference_coverage` filters them."""

    n_units_multi_label: int
    """Units whose labelled ground carries more than one class, and so are decided by an areal
    majority. Expected to be common on patch-scale units and rare on a 100 m grid."""

    unit_area_m2: float
    labelled_area_m2: float
    """Labelled ground falling inside the units. Below `WudaptSelection.labelled_area_m2` whenever
    the reference extends past the study window, which it usually does."""

    mean_coverage: float
    """Area-weighted mean `reference_coverage` over the labelled units."""

    class_counts: dict[int, int] = field(default_factory=dict)
    """Units per assigned reference class, so a window carrying two classes is visible as such."""


def _boolean(values: pd.Series) -> pd.Series:
    """The QC flags as nullable booleans, accepting every spelling the file uses."""
    text = values.astype("string").str.strip()
    unknown = pd.Series(pd.NA, index=values.index, dtype="boolean")
    return unknown.mask(text.isin(_TRUE), True).mask(text.isin(_FALSE), False)


def _dates(values: pd.Series) -> pd.Series:
    """`representative_date` as timestamps, unparseable entries as NaT.

    9.7% of the file does not parse as `%Y-%m-%d`. Those rows are not dropped - a missing date
    costs a polygon its place in the priority order, not its label.
    """
    return pd.to_datetime(values, errors="coerce", format="mixed")


def read_wudapt(
    path: Path,
    bbox: BBox,
    *,
    layer: str | None = None,
    columns: tuple[str, ...] = READ_COLUMNS,
) -> gpd.GeoDataFrame:
    """The raw polygons intersecting `bbox`, in the file's own CRS (EPSG:4326).

    Reads only `columns` and only the bbox: the file is 720 MB and 630 311 features, and every
    caller wants a city-sized window of it.

    `layer=None` resolves to the first *geometry-bearing* layer rather than being passed through.
    The published export carries a second layer, `layer_styles`, which is a QGIS style table with
    no geometry; letting the driver pick would work today and read the style table the day the
    layer order changes.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"WUDAPT training areas not found at {path}. Place the LCZ Generator export under "
            f"input/{WUDAPT_SOURCE_DIR_NAME}/ and set ValidationConfig.wudapt.filename."
        )
    frame = gpd.read_file(
        path,
        layer=layer if layer is not None else _first_geometry_layer(path),
        bbox=bbox,
        columns=list(columns),
    )
    return gpd.GeoDataFrame(frame)


def _first_geometry_layer(path: Path) -> str:
    """The first layer in `path` that carries geometry."""
    layers = pyogrio.list_layers(path)
    for name, geometry_type in layers:
        if geometry_type:
            return str(name)
    raise ValueError(f"{path} has no geometry-bearing layer; found {[row[0] for row in layers]}")


def prepare_wudapt(
    polygons: gpd.GeoDataFrame,
    *,
    crs: CRS,
    config: WudaptConfig | None = None,
) -> tuple[gpd.GeoDataFrame, WudaptSelection]:
    """Clean, filter and de-overlap `polygons`, returning them in `crs` with a record of the cost.

    The returned frame carries `class` and a non-overlapping geometry: every piece of ground
    belongs to exactly one polygon, so an areal overlay onto units cannot double-count it.

    `polygons` is not mutated.
    """
    settings = config or WudaptConfig()
    class_column = settings.class_column
    n_read = int(len(polygons))
    if class_column not in polygons.columns:
        raise ValueError(
            f"polygons must carry a {class_column!r} column; got {list(polygons.columns)}"
        )
    if polygons.crs is None:
        raise ValueError("polygons must declare a CRS")

    frame = polygons.to_crs(crs)
    qc_pass = _qc_pass(frame)
    qc_pass_fraction = float(qc_pass.fillna(False).mean()) if n_read else 0.0

    # Force 2D before anything geometric: every feature in the file is `Polygon Z` carrying a
    # dummy Z, and a Z coordinate survives `make_valid` into overlay operations that do not want it.
    geometry = shapely.force_2d(shapely.make_valid(frame.geometry.to_numpy()))
    frame = frame.set_geometry(gpd.GeoSeries(geometry, index=frame.index, crs=crs))
    valid = frame.geom_type.isin(("Polygon", "MultiPolygon")) & ~frame.geometry.is_empty
    n_dropped_invalid = int((~valid).sum())
    frame = frame.loc[valid]

    codes = pd.to_numeric(frame[class_column], errors="coerce")
    supported = codes.isin(CODES)
    n_dropped_unsupported = int((~supported).sum())
    frame = frame.loc[supported].assign(**{class_column: codes[supported].astype("int64")})

    kept_qc = qc_pass.reindex(frame.index)
    if settings.require_qc:
        gate = kept_qc.fillna(False).astype(bool)
        n_dropped_qc = int((~gate).sum())
        frame = frame.loc[gate]
    else:
        n_dropped_qc = 0

    if settings.min_oa is not None and "oa" in frame.columns:
        accurate = pd.to_numeric(frame["oa"], errors="coerce").ge(settings.min_oa).fillna(False)
        n_dropped_accuracy = int((~accurate).sum())
        frame = frame.loc[accurate.astype(bool)]
    else:
        n_dropped_accuracy = 0

    # Recomputed in the projected CRS, never read from the stored `area` column - see the module
    # docstring. `test_validation_wudapt.py` asserts the stored column is not consulted.
    areas = frame.geometry.area
    big_enough = areas.ge(settings.min_area_m2)
    if settings.max_area_m2 is not None:
        big_enough &= areas.le(settings.max_area_m2)
    n_dropped_area = int((~big_enough).sum())
    frame = frame.loc[big_enough]

    resolved, overlaps = resolve_overlaps(frame, class_column=class_column)

    dates = _dates(frame["representative_date"]) if "representative_date" in frame else None
    return resolved, WudaptSelection(
        n_read=n_read,
        n_kept=int(len(resolved)),
        n_dropped_invalid=n_dropped_invalid,
        n_dropped_unsupported_class=n_dropped_unsupported,
        n_dropped_qc=n_dropped_qc,
        n_dropped_accuracy=n_dropped_accuracy,
        n_dropped_area=n_dropped_area,
        qc_pass_fraction=qc_pass_fraction,
        n_overlapping_pairs=overlaps.n_overlapping_pairs,
        n_conflicting_pairs=overlaps.n_conflicting_pairs,
        duplicate_area_m2=overlaps.duplicate_area_m2,
        conflict_area_m2=overlaps.conflict_area_m2,
        labelled_area_m2=float(resolved.geometry.area.sum()),
        date_min=_stamp(dates.min()) if dates is not None and dates.notna().any() else None,
        date_max=_stamp(dates.max()) if dates is not None and dates.notna().any() else None,
        licences=_distinct(frame, "license"),
        cities=_distinct(frame, "city"),
    )


def _stamp(value: pd.Timestamp) -> str:
    return str(pd.Timestamp(value).date())


def _distinct(frame: gpd.GeoDataFrame, column: str) -> tuple[str, ...]:
    if column not in frame.columns or frame.empty:
        return ()
    return tuple(sorted({str(value) for value in frame[column].dropna().unique()}))


def _qc_pass(frame: gpd.GeoDataFrame) -> pd.Series:
    """True where all three QC flags pass; null where any is missing or unparseable."""
    present = [column for column in QC_COLUMNS if column in frame.columns]
    if not present:
        return pd.Series(pd.NA, index=frame.index, dtype="boolean")
    flags = [_boolean(frame[column]) for column in present]
    combined = flags[0]
    for flag in flags[1:]:
        combined &= flag
    return combined


OVERLAP_EPS_M2 = 1e-6
"""Intersection area below which two resolved polygons are treated as not overlapping.

`shapely.difference` leaves coordinate-noise slivers along the cut, so the topological `overlaps`
predicate still fires on pairs whose shared area is around 1e-8 m² — a hundredth of a square
micrometre, measured on the Berlin fixture. The resolution is exact in area (`labelled +
duplicate + conflict` reproduces the raw sum to the full 13 595 047.0 m² on that fixture); it is
the *predicate* that is not a statement about area. Tests assert on area against this tolerance.

A module constant and not config, following CLAUDE.md's Phase 1 ruling on `eps_m`: a
floating-point tolerance is not a domain threshold.
"""


@dataclass(frozen=True)
class OverlapReport:
    """What `resolve_overlaps` had to arbitrate.

    The three areas satisfy `raw = labelled + duplicate + conflict` exactly, which is the
    invariant worth checking: every square metre a contributor drew is either kept, redundant, or
    contested, and nothing is silently lost.
    """

    n_overlapping_pairs: int
    """Ordered pairs, counted once per lower-priority polygon per higher-priority polygon it
    genuinely shares area with. Polygons that merely touch are excluded."""

    n_conflicting_pairs: int
    """Of those, the pairs whose classes differ."""

    duplicate_area_m2: float
    """Ground yielded to a higher-priority polygon of the same class, **summed over polygons** —
    so ground claimed by k agreeing polygons contributes k-1 times. It measures redundant drawing
    effort, not an area of the city."""

    conflict_area_m2: float
    """Ground yielded to a higher-priority polygon of a different class, summed the same way.
    Attributed to `duplicate_area_m2` first where a polygon lost the same ground to both an
    agreeing and a disagreeing claimant, so this is the conservative reading of the disagreement."""


def priority_order(polygons: gpd.GeoDataFrame) -> pd.Index:
    """Index of `polygons`, best claim to contested ground first.

    Most recent `representative_date`, then the higher submission accuracy, then the *smaller*
    polygon, then the index. The last two are what make it deterministic; the first two are the
    judgement:

    - **Recency wins** because a WUDAPT polygon describes the city at `representative_date`, the
      dates span 1983-2025, and lczkit is classifying a current Overture release. Where two
      contributors disagree about the same ground, the newer one is describing the city the
      package is looking at.
    - **Accuracy breaks the tie** because `oa` is the LCZ Generator's own cross-validated score
      for the submission the polygon came from. It is a property of the submission, not the
      polygon, so it is a weak signal - which is exactly why it ranks below recency rather than
      above it.
    - **Smaller wins** last, on the reasoning that a contributor who drew a 2 ha polygon inside
      someone else's 200 ha one was being more specific about that ground.

    A missing date or accuracy sorts last rather than dropping the polygon: it costs the polygon
    its claim on contested ground, not its label on ground nobody else drew.
    """
    frame = pd.DataFrame(index=polygons.index)
    if "representative_date" in polygons.columns:
        frame["date"] = _dates(polygons["representative_date"])
    elif "submission_date" in polygons.columns:
        frame["date"] = pd.to_datetime(polygons["submission_date"], errors="coerce", utc=True)
    if "oa" in polygons.columns:
        frame["oa"] = pd.to_numeric(polygons["oa"], errors="coerce")
    frame["small"] = -polygons.geometry.area

    by = [*(column for column in ("date", "oa") if column in frame.columns), "small"]
    ordered = frame.sort_values(by=by, ascending=False, na_position="last", kind="stable")
    return ordered.index


def resolve_overlaps(
    polygons: gpd.GeoDataFrame, *, class_column: str = CLASS_COLUMN
) -> tuple[gpd.GeoDataFrame, OverlapReport]:
    """Give every piece of ground to exactly one polygon, and report what that cost.

    Each polygon keeps itself minus every higher-priority polygon. Subtracting the higher-priority
    polygons' *original* geometries rather than their remainders is equivalent and cheaper: ground
    a higher-priority polygon itself lost went to something higher still, so it is claimed either
    way and never returns to a lower-priority claimant.

    Polygons reduced to nothing are dropped. Their label is not lost - it agreed with, or was
    overruled by, a polygon that kept the same ground.

    The result is exact in area but not in topology: the cuts leave coordinate-noise slivers, so
    `overlaps` still fires on some pairs at around 1e-8 m2. See `OVERLAP_EPS_M2`.
    """
    if polygons.empty:
        return polygons, OverlapReport(0, 0, 0.0, 0.0)

    order = priority_order(polygons)
    ordered = polygons.loc[order]
    geometry = ordered.geometry.to_numpy()
    codes = ordered[class_column].to_numpy()
    tree = shapely.STRtree(geometry)

    remainders: list[shapely.Geometry] = []
    duplicate_area = 0.0
    conflict_area = 0.0
    overlapping = 0
    conflicting = 0

    for position, geom in enumerate(geometry):
        hits = tree.query(geom, predicate="intersects")
        higher = hits[hits < position]
        if higher.size == 0:
            remainders.append(geom)
            continue

        # `intersects` includes polygons that merely touch, which take no area and are not
        # overlaps. Counting them would inflate the disagreement rate with shared edges.
        claimed = shapely.intersection(geom, shapely.union_all(geometry[higher]))
        lost = float(shapely.area(claimed))
        if lost > 0.0:
            same = higher[codes[higher] == codes[position]]
            different = higher.size - same.size
            overlapping += int(higher.size)
            conflicting += int(different)
            duplicate = (
                float(shapely.area(shapely.intersection(geom, shapely.union_all(geometry[same]))))
                if same.size
                else 0.0
            )
            duplicate_area += duplicate
            conflict_area += max(lost - duplicate, 0.0)
        remainders.append(shapely.difference(geom, shapely.union_all(geometry[higher])))

    cut = np.asarray(remainders, dtype=object)
    resolved = ordered.set_geometry(gpd.GeoSeries(cut, index=ordered.index, crs=polygons.crs))
    # Tested on the shapely array rather than through `GeoSeries.notna`, whose treatment of empty
    # geometries changed in geopandas 1.x and now warns whenever any are present — which is exactly
    # the case here, since a fully absorbed polygon is how this function reports "kept nothing".
    kept = ~(shapely.is_empty(cut) | shapely.is_missing(cut))
    return gpd.GeoDataFrame(resolved.loc[kept]), OverlapReport(
        n_overlapping_pairs=overlapping,
        n_conflicting_pairs=conflicting,
        duplicate_area_m2=duplicate_area,
        conflict_area_m2=conflict_area,
    )


def wudapt_lcz(
    units: gpd.GeoDataFrame,
    polygons: gpd.GeoDataFrame,
    *,
    class_column: str = CLASS_COLUMN,
) -> tuple[pd.DataFrame, WudaptMatch]:
    """The reference class per `unit_id` by areal majority, and how the labels landed.

    Returns the three columns `reference_lcz` and `labelled_lcz` return, with the same meanings:

    - `reference_lcz` - the class holding most of the unit's *labelled* area, or null where no
      polygon reaches it. Nullable `Int8`, never a sentinel.
    - `reference_coverage` - fraction of the unit any polygon covers. Genuinely fractional, unlike
      `labelled_lcz`'s binary flag, because WUDAPT polygons tile ground rather than sampling it.
    - `reference_majority_fraction` - the winner's share of the labelled part.

    `polygons` must already be non-overlapping - pass what `prepare_wudapt` returns. Overlapping
    input is not detected here (the check costs as much as the fix); it would inflate every
    coverage above 1.0 and let one contributor outvote a city.

    Neither input is mutated.
    """
    check_units(units)
    if class_column not in polygons.columns:
        raise ValueError(
            f"polygons must carry a {class_column!r} column; got {list(polygons.columns)}"
        )
    if polygons.crs is None:
        raise ValueError("polygons must declare a CRS")

    unit_area = units.geometry.area
    result = pd.DataFrame(
        {
            "reference_lcz": pd.Series(pd.NA, index=units.index, dtype="Int8"),
            "reference_coverage": 0.0,
            "reference_majority_fraction": pd.Series(np.nan, index=units.index, dtype="float64"),
        },
        index=units.index,
    )
    empty = WudaptMatch(
        n_polygons=int(len(polygons)),
        n_units=int(len(units)),
        n_units_labelled=0,
        n_units_multi_label=0,
        unit_area_m2=float(unit_area.sum()),
        labelled_area_m2=0.0,
        mean_coverage=0.0,
    )
    if polygons.empty or units.empty:
        return result, empty

    target = units.crs
    assert target is not None  # noqa: S101 - check_units already raised if it were
    labels = polygons.to_crs(target)[[class_column, "geometry"]]
    pieces = gpd.overlay(
        units.reset_index()[["unit_id", "geometry"]],
        labels,
        how="intersection",
        keep_geom_type=True,
    )
    if pieces.empty:
        return result, empty

    pieces = pieces.assign(area=pieces.geometry.area)
    pieces = pieces.loc[pieces["area"] > 0.0]
    if pieces.empty:
        return result, empty

    by_class = pieces.groupby(["unit_id", class_column], observed=True)["area"].sum()
    totals = by_class.groupby("unit_id").sum()
    # `idxmax` over the (unit, class) index rather than a pivot: the pivot would be 17 columns wide
    # over every unit, and the winner is a single positional lookup either way.
    winners = by_class.loc[by_class.groupby("unit_id").idxmax()]
    winner_class = winners.index.get_level_values(class_column)
    winner_area = pd.Series(winners.to_numpy(), index=winners.index.get_level_values("unit_id"))
    winner_code = pd.Series(winner_class, index=winner_area.index)

    labelled = totals.reindex(units.index)
    result["reference_lcz"] = winner_code.reindex(units.index).astype("Int8")
    result["reference_coverage"] = (
        labelled.div(unit_area.where(unit_area > 0)).fillna(0.0).clip(upper=1.0)
    )
    result["reference_majority_fraction"] = winner_area.reindex(units.index).div(
        labelled.where(labelled > 0)
    )

    assigned = result["reference_lcz"].dropna()
    return result, WudaptMatch(
        n_polygons=int(len(polygons)),
        n_units=int(len(units)),
        n_units_labelled=int(len(assigned)),
        n_units_multi_label=int((by_class.groupby("unit_id").size() > 1).sum()),
        unit_area_m2=float(unit_area.sum()),
        labelled_area_m2=float(pieces["area"].sum()),
        mean_coverage=float(result.loc[assigned.index, "reference_coverage"].mean())
        if len(assigned)
        else 0.0,
        class_counts={
            int(str(code)): int(count) for code, count in assigned.value_counts().items()
        },
    )


def load_wudapt(
    path: Path,
    bbox: BBox,
    *,
    crs: CRS,
    config: WudaptConfig | None = None,
) -> tuple[gpd.GeoDataFrame, WudaptSelection]:
    """`read_wudapt` then `prepare_wudapt`: the whole file route in one call.

    Split into two functions underneath so tests can exercise the cleaning against a committed
    fixture frame without `DATA_DIR` being set.
    """
    settings = config or WudaptConfig()
    raw = read_wudapt(path, bbox, layer=settings.layer)
    return prepare_wudapt(raw, crs=crs, config=settings)
