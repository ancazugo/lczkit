"""2D urban morphometrics — Majer & Fleischmann (2026), Phase 29.

**A descriptive output, not classifier input.** `compute_morphometrics` returns 107 primary
attributes (dimensional/shape, spatial distribution/intensity, street descriptors/connectivity),
computed via momepy 1.0+ over enclosed tessellation cells (ETCs — see
`lczkit.units.tessellation`), plus an opt-in contextual expansion. None of it feeds
`lczkit.classify.PrototypeClassifier`: the paper's own finding is that 2D morphometrics alone
predict LCZ "selectively and inconsistently", and this package's classifier stays the existing
prototype-distance metric over Stewart & Oke's urban canopy parameters. Nor does it replicate the
paper's RandomForest/CNN prediction schemes (S1-S4) — those, and satellite imagery, are out of
scope for this feature.

Output ships as its own run artefact (`morphometrics.parquet`, and `morphometrics.tif` if a
raster resolution is requested) — never joined into `units.parquet` or the classification table,
since ETCs are a different, finer-grained unit set than the pipeline's classification units.

See `docs/references/tables/majer_2026_morphometrics_menu.md` for the full attribute list.

**Deliberately no eager re-exports here.** `raster.py` imports filename constants from
`lczkit.output.writer`, which imports `MorphometricsReport` from `report.py` — importing any
submodule always runs this file first, so re-exporting `raster`'s names here would make importing
`lczkit.morphometrics.report` alone drag in `raster.py`, and with it `output.writer`, while
`output.writer` is itself mid-import. Import submodules directly:
`lczkit.morphometrics.compute.compute_morphometrics`, `lczkit.morphometrics.raster.*`,
`lczkit.morphometrics.report.MorphometricsReport`.
"""

from __future__ import annotations
