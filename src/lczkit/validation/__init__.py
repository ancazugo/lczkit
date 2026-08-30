"""Agreement against a reference LCZ map, in the style of the `lczexplore` package.

Per-class agreement and a confusion matrix, never a single accuracy number; plus the breakdowns
that turn the height caveat into a measured quantity - agreement by `height_completeness`
band, and the two confusion axes reported apart: the height axis (1<->2<->3, 4<->5<->6) and the
compactness axis (1<->4, 2<->5, 3<->6).

`ranges` adds the complementary instrument: agreement says whether a label was right, and
`parameter_ranges` says whether the parameter behind it could ever have reached the published
prototype it should have matched. `uncertainty` adds the third: how much of a difference between
two agreement figures is signal, given that the units are a correlated sheet rather than
independent draws.

Three references, not one, and they are three different kinds of object. `reference_lcz` reads the
Demuzere global map, which is a model output carrying its own error; `labelled_lcz` reads
hand-labelled So2Sat LCZ42 / DFC2017 patches, which are ground truth on a uniform grid;
`wudapt_lcz` reads WUDAPT LCZ Generator training areas, which are hand-drawn too but irregular,
overlapping, spread over four decades, and available for every city rather than fifty-one.

Where So2Sat exists it is primary and the agreement *between* it and `lcz_v3` is the ceiling on any
score against the map, and that distinction is easy to lose. WUDAPT does
**not** give a second such ceiling: the LCZ Generator's training areas are the training data behind
the Demuzere map, so the two are not independent and their agreement is inflated by construction.

All three return the same three columns, so `agreement()` consumes any of them without knowing
which — which is exactly why every report records `reference_file`. A table that does not name the
file it used is indistinguishable from one that used a different reference, and this project has
found that mistake twice.
"""

from lczkit.validation.agreement import (
    AgreementReport,
    AxisConfusion,
    ClassAgreement,
    ConfusionCell,
    Stratum,
    agreement,
    weighted_agreement,
)
from lczkit.validation.labelled import LabelMatch, labelled_lcz
from lczkit.validation.ranges import ClassRange, RangeReport, parameter_ranges
from lczkit.validation.reference import reference_lcz
from lczkit.validation.similarity import BECHTEL_2020, SIMILARITY
from lczkit.validation.uncertainty import (
    BootstrapReport,
    Interval,
    bootstrap_agreement,
    spatial_blocks,
)
from lczkit.validation.wudapt import (
    WUDAPT_CITATION,
    WUDAPT_SOURCE_DIR_NAME,
    OverlapReport,
    WudaptMatch,
    WudaptSelection,
    load_wudapt,
    prepare_wudapt,
    read_wudapt,
    resolve_overlaps,
    wudapt_lcz,
)

__all__ = [
    "AgreementReport",
    "AxisConfusion",
    "BootstrapReport",
    "ClassAgreement",
    "ClassRange",
    "ConfusionCell",
    "Interval",
    "LabelMatch",
    "OverlapReport",
    "RangeReport",
    "Stratum",
    "WudaptMatch",
    "WudaptSelection",
    "BECHTEL_2020",
    "SIMILARITY",
    "WUDAPT_CITATION",
    "WUDAPT_SOURCE_DIR_NAME",
    "agreement",
    "bootstrap_agreement",
    "labelled_lcz",
    "load_wudapt",
    "parameter_ranges",
    "prepare_wudapt",
    "read_wudapt",
    "reference_lcz",
    "resolve_overlaps",
    "spatial_blocks",
    "weighted_agreement",
    "wudapt_lcz",
]
