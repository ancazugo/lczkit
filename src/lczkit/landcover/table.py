"""The fractions table both land-cover backends return, and the entry checks both make.

CLAUDE.md's acceptance criterion for this phase is that `LocalRasterSource` and
`EarthEngineSource` return schema-identical tables. Routing both through `fractions_table` makes
that true by construction rather than by inspection: the backends differ only in how they produce
per-unit *cell counts*, and everything after that — column order, absent classes, normalisation,
the empty-unit convention — happens once, here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from lczkit.config import LandCoverDatasetConfig


def fractions_table(
    counts: pd.DataFrame,
    config: LandCoverDatasetConfig,
    index: pd.Index,
) -> pd.DataFrame:
    """Normalise per-unit class `counts` into the fractions table, indexed to match `index`.

    `counts` is indexed by `unit_id` with one column per *class index* (position in
    `config.classes`), holding whatever the backend counts in — exact cell-coverage area locally,
    pixel counts server-side. Only ratios survive, so the two units of measurement agree.

    Every class in `config.classes` gets a column whether or not it occurs in the data, so the
    output schema is fixed by config rather than by which classes a given city happens to contain.
    Units with no counted cells come out all-`NaN`, not all-zero: "the raster does not cover this
    unit" and "0% of this unit is tree" are different statements, and the same call
    `height_metrics()` makes for a unit holding no buildings.
    """
    columns = [f"{config.column_prefix}{name}" for name in config.classes]
    positions = pd.Index(range(len(config.classes)))

    if counts.empty:
        return _all_null(index, columns)

    aligned = (
        counts.reindex(columns=positions, fill_value=0.0)
        .reindex(index=index, fill_value=0.0)
        .astype("float64")
    )
    totals = aligned.sum(axis=1)
    fractions = aligned.div(totals.where(totals > 0), axis=0)
    fractions.columns = pd.Index(columns)
    fractions.index.name = "unit_id"
    return fractions


def _all_null(index: pd.Index, columns: list[str]) -> pd.DataFrame:
    frame = pd.DataFrame(np.nan, index=index, columns=pd.Index(columns), dtype="float64")
    frame.index.name = "unit_id"
    return frame
