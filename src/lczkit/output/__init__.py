"""What a run writes into `output/lczkit/<run_id>/`.

`units.parquet` is the archival record, `units_viz.parquet` the rounded table a map renders from,
and `manifest.json` everything needed to read either of them and to reproduce the run - including
the CRS, which is derived from the extent rather than configured and so is not in `config`.

`units.gpkg` is the same unit table in a format whose reader is unconditional. It is written by
default and is not the archival record; see `OutputConfig.gis_format`.
"""

from lczkit.output.breaks import VariableBreaks, breaks_for, quantile_breaks
from lczkit.output.gis import GisExport, export_gis
from lczkit.output.manifest import RunManifest, build_manifest, package_versions
from lczkit.output.writer import (
    GPKG_FILE,
    GPKG_LAYER,
    MANIFEST_FILE,
    UNITS_FILE,
    VIZ_FILE,
    RunOutputs,
    viz_table,
    write_gpkg,
    write_run,
)

__all__ = [
    "GPKG_FILE",
    "GPKG_LAYER",
    "MANIFEST_FILE",
    "UNITS_FILE",
    "VIZ_FILE",
    "GisExport",
    "RunManifest",
    "RunOutputs",
    "VariableBreaks",
    "breaks_for",
    "build_manifest",
    "export_gis",
    "package_versions",
    "quantile_breaks",
    "viz_table",
    "write_gpkg",
    "write_run",
]
