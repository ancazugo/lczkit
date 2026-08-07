"""Phase 6 validation - agreement against a reference LCZ map, reported lczexplore-style.

Per-class agreement and a confusion matrix, never a single accuracy number; plus the two
breakdowns that turn the Phase 3 height caveat into a measured quantity - agreement by
`height_completeness` decile, and the 1<->4 / 2<->5 / 3<->6 confusion pairs.
"""

from lczkit.validation.agreement import (
    AgreementReport,
    ClassAgreement,
    ConfusionCell,
    HeightAxisConfusion,
    Stratum,
    agreement,
)
from lczkit.validation.reference import reference_lcz

__all__ = [
    "AgreementReport",
    "ClassAgreement",
    "ConfusionCell",
    "HeightAxisConfusion",
    "Stratum",
    "agreement",
    "reference_lcz",
]
