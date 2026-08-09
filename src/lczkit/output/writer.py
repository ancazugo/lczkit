"""Writing a run: `units.parquet`, `units_viz.parquet` and `manifest.json`.

Three files, into `output/lczkit/<run_id>/` and nowhere else. CLAUDE.md is emphatic on both
counts - a run must never write outside its own directory, and the viz table exists so that
Phase 7 is a pure transform of run outputs rather than a second analysis.

The split between the two tables is deliberate. `units.parquet` is the archival record: full
precision, geometry attached, every column any stage produced. `units_viz.parquet` is what a map
renders from: no geometry (the tiles carry it), floats rounded to three significant figures, and
the seventeen distances stored as scaled integers. The rounding is not cosmetic - at full float64
precision the distance vector alone triples the size of what a browser has to parse, and no
choropleth or sidebar reads past the third digit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype

from lczkit.classify.classifier import DISTANCE_COLUMNS, PrototypeClassifier
from lczkit.cleaning.report import CleaningReport
from lczkit.config import Settings
from lczkit.heights.cascade import HeightFillReport
from lczkit.heights.diagnostic import SourceAvailability
from lczkit.output.breaks import breaks_for
from lczkit.output.manifest import RunManifest, build_manifest
from lczkit.units import check_units
from lczkit.validation.agreement import AgreementReport

UNITS_FILE = "units.parquet"
VIZ_FILE = "units_viz.parquet"
MANIFEST_FILE = "manifest.json"
LAYERS_DIR = "layers"

#: Context layers `write_run` will persist, in the order the site draws them. Restricted to a known
#: set so a caller cannot quietly grow the run directory by an arbitrary GeoDataFrame, and so a
#: reader of a run knows what a file called `layers/streets.parquet` contains.
CONTEXT_LAYERS: tuple[str, ...] = ("land_use", "water", "streets", "buildings")

#: Columns excluded from the precomputed breaks. The distance vector is rendered as a per-unit bar
#: chart rather than a choropleth, and the two label columns are categorical codes whose quantiles
#: would be meaningless - the seventh decile of an LCZ code is not a class boundary.
_NOT_CONTINUOUS = frozenset({*DISTANCE_COLUMNS, "lcz_primary", "lcz_secondary", "reference_lcz"})


@dataclass(frozen=True)
class RunOutputs:
    """What a run wrote, and the manifest describing it."""

    run_dir: Path
    units: Path
    units_viz: Path
    manifest_path: Path
    manifest: RunManifest
    layers: dict[str, Path] = field(default_factory=dict)
    """Context layers persisted under `layers/`, by name. Empty unless the caller asked for them."""


def write_run(
    settings: Settings,
    units: gpd.GeoDataFrame,
    parameters: pd.DataFrame,
    classification: pd.DataFrame,
    classifier: PrototypeClassifier,
    *,
    extras: pd.DataFrame | None = None,
    cleaning: CleaningReport | None = None,
    height_fill: HeightFillReport | None = None,
    height_source_availability: SourceAvailability | None = None,
    validation: AgreementReport | None = None,
    layers: Mapping[str, gpd.GeoDataFrame] | None = None,
) -> RunOutputs:
    """Write one run's three files into `settings.run_dir`, returning their paths.

    `extras` is anything else keyed on `unit_id` that belongs in the output - the Phase 3 height
    provenance and the Phase 4 land-cover fractions, typically. It is joined verbatim, so a
    column appearing in two inputs is an error rather than a silent overwrite.

    `layers` persists the run's context geometry - the cleaned streets, water, land use and
    buildings - under `layers/<name>.parquet`. It exists so that **Phase 7's site build is a pure
    transform of run outputs**, which CLAUDE.md requires: without it the only way to draw a basemap
    or extrude buildings would be to re-read `input/` at site-build time, which would make the site
    depend on data the run does not carry and could not be rebuilt from an archived run directory.
    Names outside `CONTEXT_LAYERS` are rejected rather than written.

    Nothing outside `run_dir` is touched, and nothing under `input/` is read.
    """
    check_units(units)
    unknown = sorted(set(layers or {}) - set(CONTEXT_LAYERS))
    if unknown:
        raise ValueError(
            f"unknown context layers {', '.join(unknown)}; "
            f"write_run persists only {', '.join(CONTEXT_LAYERS)}"
        )
    for name, frame in (("parameters", parameters), ("classification", classification)):
        if not frame.index.equals(units.index):
            raise ValueError(f"{name} index does not match units; both must be the same unit_id")

    attributes = _join(parameters, classification, extras)
    table = gpd.GeoDataFrame(
        attributes.join(units[["geometry"]]), geometry="geometry", crs=units.crs
    )

    continuous = [
        column
        for column in attributes.columns
        if column not in _NOT_CONTINUOUS
        and is_numeric_dtype(attributes[column])
        and not is_bool_dtype(attributes[column])
    ]
    run_dir = settings.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    units_path = run_dir / UNITS_FILE
    viz_path = run_dir / VIZ_FILE
    manifest_path = run_dir / MANIFEST_FILE

    written = _write_layers(run_dir, layers)
    manifest = build_manifest(
        settings,
        classifier,
        breaks=breaks_for(attributes, continuous, settings.output.break_count),
        classification_summary=classification_summary(classification),
        cleaning=cleaning,
        height_fill=height_fill,
        height_source_availability=height_source_availability,
        validation=validation,
        outputs=[
            UNITS_FILE,
            VIZ_FILE,
            MANIFEST_FILE,
            *(str(path.relative_to(run_dir)) for path in written.values()),
        ],
    )

    table.to_parquet(units_path)
    viz_table(attributes, settings).to_parquet(viz_path)
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")

    return RunOutputs(
        run_dir=run_dir,
        units=units_path,
        units_viz=viz_path,
        manifest_path=manifest_path,
        manifest=manifest,
        layers=written,
    )


def _write_layers(run_dir: Path, layers: Mapping[str, gpd.GeoDataFrame] | None) -> dict[str, Path]:
    """Persist the context layers under `layers/`, in `CONTEXT_LAYERS` order.

    Written in a fixed order rather than the caller's so that two runs of the same city produce
    the same `outputs` list in the manifest, which is otherwise a gratuitous diff.
    """
    if not layers:
        return {}
    directory = run_dir / LAYERS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for name in CONTEXT_LAYERS:
        frame = layers.get(name)
        if frame is None:
            continue
        path = directory / f"{name}.parquet"
        frame.to_parquet(path)
        written[name] = path
    return written


def classification_summary(classification: pd.DataFrame) -> dict[str, Any]:
    """What the classifier did to this city, for the manifest.

    The LCZ 10 firing count is the reason this exists. A rule that never fires is
    indistinguishable, from the output alone, from one that was never configured, and CLAUDE.md's
    concern about LCZ 10 is precisely that it can go silently unemitted — so the count belongs in
    every run's manifest rather than in whatever investigation happens to look for it.
    """
    labels = classification["lcz_primary"]
    routes = classification["label_route"]
    uniqueness = classification["uniqueness"].dropna()
    counted = labels.dropna().astype("int64").value_counts().sort_index()
    return {
        "n_units": int(len(classification)),
        "n_unlabelled": int(labels.isna().sum()),
        "labels": {str(code): int(count) for code, count in counted.to_dict().items()},
        "label_route": {str(route): int(count) for route, count in routes.value_counts().items()},
        "lcz10_rule_applied": int(classification["lcz10_rule_applied"].sum()),
        "median_uniqueness": float(uniqueness.median()) if not uniqueness.empty else None,
        "median_n_params_used": float(classification["n_params_used"].median()),
    }


def viz_table(attributes: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    """The rounded, integer-scaled attribute table Phase 7 renders from.

    Exposed separately from `write_run` so the transformation is testable without a filesystem,
    and so a caller can inspect exactly what a viewer will see.
    """
    digits = settings.output.viz_significant_figures
    scale = settings.output.viz_distance_scale

    result = attributes.copy()
    for column in result.columns:
        if column in DISTANCE_COLUMNS:
            result[column] = _scaled_int(result[column], scale)
        elif is_numeric_dtype(result[column]) and not is_bool_dtype(result[column]):
            if pd.api.types.is_float_dtype(result[column]):
                result[column] = _round_significant(result[column], digits)
    result.index.name = "unit_id"
    return result


def _join(
    parameters: pd.DataFrame, classification: pd.DataFrame, extras: pd.DataFrame | None
) -> pd.DataFrame:
    frames = [parameters, classification] + ([] if extras is None else [extras])
    seen: dict[str, int] = {}
    for frame in frames:
        for column in frame.columns:
            seen[column] = seen.get(column, 0) + 1
    duplicates = sorted(name for name, count in seen.items() if count > 1)
    if duplicates:
        raise ValueError(
            f"columns appear in more than one input and would be ambiguous: {', '.join(duplicates)}"
        )
    return pd.concat(frames, axis=1)


def _round_significant(values: pd.Series, digits: int) -> pd.Series:
    """Round to `digits` significant figures, leaving zeros, nulls and infinities alone.

    Significant figures rather than decimal places because the columns span nine orders of
    magnitude - a mean footprint area in the thousands of square metres next to a fraction in the
    hundredths - and one decimal-place rule cannot serve both.
    """
    array = values.to_numpy(dtype="float64", na_value=np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        shift = digits - 1 - np.floor(np.log10(np.abs(array)))
    factor = np.where(
        np.isfinite(shift), np.power(10.0, np.where(np.isfinite(shift), shift, 0.0)), 1.0
    )
    rounded = np.where(np.isfinite(shift), np.round(array * factor) / factor, array)
    return pd.Series(rounded, index=values.index, dtype="float64")


def _scaled_int(values: pd.Series, scale: int) -> pd.Series:
    """A distance column as a nullable `Int16` scaled by `scale`.

    Nullable rather than a sentinel: a distance is null where the metric had nothing to work
    with, and an int16 sentinel would be read as a very large or very small distance by anything
    that did not know the convention. Values beyond the int16 range are clipped rather than
    wrapped, and a distance that far out is already off the end of any colour ramp.
    """
    array = values.to_numpy(dtype="float64", na_value=np.nan)
    scaled = np.clip(np.round(array * scale), np.iinfo(np.int16).min, np.iinfo(np.int16).max)
    return pd.Series(scaled, index=values.index).astype("Int16")
