"""Phase 6 validation - agreement against a reference LCZ map, reported lczexplore-style.

Per-class agreement and a confusion matrix, never a single accuracy number; plus the breakdowns
that turn the Phase 3 height caveat into a measured quantity - agreement by `height_completeness`
band, and the two confusion axes reported apart: the height axis (1<->2<->3, 4<->5<->6) and the
compactness axis (1<->4, 2<->5, 3<->6).

`ranges` adds the complementary instrument: agreement says whether a label was right, and
`parameter_ranges` says whether the parameter behind it could ever have reached the published
prototype it should have matched. `uncertainty` adds the third: how much of a difference between
two agreement figures is signal, given that the units are a correlated sheet rather than
independent draws.

Two references, not one. `reference_lcz` reads the Demuzere global map, which is a model output
carrying its own error; `labelled_lcz` reads hand-labelled So2Sat LCZ42 / DFC2017 polygons, which
are ground truth. Where both exist the labels are primary and the agreement *between* them is the
ceiling on any score against the map. Phase 6.7 exists because that distinction was not being made.
"""

from lczkit.validation.agreement import (
    AgreementReport,
    AxisConfusion,
    ClassAgreement,
    ConfusionCell,
    Stratum,
    agreement,
)
from lczkit.validation.labelled import LabelMatch, labelled_lcz
from lczkit.validation.ranges import ClassRange, RangeReport, parameter_ranges
from lczkit.validation.reference import reference_lcz
from lczkit.validation.uncertainty import (
    BootstrapReport,
    Interval,
    bootstrap_agreement,
    spatial_blocks,
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
    "RangeReport",
    "Stratum",
    "agreement",
    "bootstrap_agreement",
    "labelled_lcz",
    "parameter_ranges",
    "reference_lcz",
    "spatial_blocks",
]
