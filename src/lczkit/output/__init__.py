"""Phase 6 output - the three files a run writes into `output/lczkit/<run_id>/`.

`units.parquet` is the archival record, `units_viz.parquet` the rounded table a map renders from,
and `manifest.json` everything needed to read either of them and to reproduce the run.
"""

from lczkit.output.breaks import VariableBreaks, breaks_for, quantile_breaks
from lczkit.output.manifest import RunManifest, build_manifest, package_versions
from lczkit.output.writer import (
    MANIFEST_FILE,
    UNITS_FILE,
    VIZ_FILE,
    RunOutputs,
    viz_table,
    write_run,
)

__all__ = [
    "MANIFEST_FILE",
    "UNITS_FILE",
    "VIZ_FILE",
    "RunManifest",
    "RunOutputs",
    "VariableBreaks",
    "breaks_for",
    "build_manifest",
    "package_versions",
    "quantile_breaks",
    "viz_table",
    "write_run",
]
