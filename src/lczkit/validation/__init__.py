"""Phase 6 validation - agreement against a reference LCZ map, reported lczexplore-style.

Per-class agreement and a confusion matrix, never a single accuracy number; plus the breakdowns
that turn the Phase 3 height caveat into a measured quantity - agreement by `height_completeness`
band, and the two confusion axes reported apart: the height axis (1<->2<->3, 4<->5<->6) and the
compactness axis (1<->4, 2<->5, 3<->6).
"""

from lczkit.validation.agreement import (
    AgreementReport,
    AxisConfusion,
    ClassAgreement,
    ConfusionCell,
    Stratum,
    agreement,
)
from lczkit.validation.reference import reference_lcz

__all__ = [
    "AgreementReport",
    "AxisConfusion",
    "ClassAgreement",
    "ConfusionCell",
    "Stratum",
    "agreement",
    "reference_lcz",
]
