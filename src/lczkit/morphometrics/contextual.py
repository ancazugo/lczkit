"""The opt-in contextual expansion — Majer & Fleischmann (2026) §3.1.

Per primary attribute, the 25th/50th/75th percentile across neighbouring ETCs within
`config.contextual_steps` topological steps, via `momepy.percentile` (linearly weighted, "hazen"
interpolation — momepy's own default and the paper's own choice). Unlike the paper, which drops
the primary attributes once the expansion is computed, lczkit keeps both: `MorphometricsConfig`
docstring records this as a deliberate divergence, not an oversight.
"""

from __future__ import annotations

from collections.abc import Iterable

import momepy
import pandas as pd
from libpysal.graph import Graph


def contextual_expand(
    primary: pd.DataFrame, graph: Graph, *, quantiles: Iterable[int] = (25, 50, 75)
) -> pd.DataFrame:
    """`{column}_p{q}` for every column of `primary` and every `q` in `quantiles`.

    `graph` should be the ETC contiguity graph expanded to the configured number of topological
    steps (`lczkit.morphometrics.graphs.etc_higher_order`) — *not* self-weighted: the paper's own
    wording is percentiles across *neighbouring* cells, so the focal cell's own value must not be
    counted as one of its own neighbours.
    """
    quantiles = list(quantiles)
    columns: dict[str, pd.Series] = {}
    for column in primary.columns:
        percentiles = momepy.percentile(primary[column], graph, q=quantiles)
        for q in quantiles:
            columns[f"{column}_p{q}"] = percentiles[q]
    return pd.DataFrame(columns, index=primary.index)
