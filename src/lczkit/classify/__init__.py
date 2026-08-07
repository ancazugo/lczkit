"""Phase 6 classification - the 17-way distance vector and the labels drawn from it.

`PrototypeClassifier` is the only thing most callers need. The distance vector is the primary
output and the label is a convenience over it, per CLAUDE.md: no core API here returns a bare LCZ
integer without the distances that produced it.
"""

from lczkit.classify.classifier import (
    CLASSIFICATION_COLUMNS,
    DISTANCE_COLUMNS,
    LABEL_COLUMNS,
    PrototypeClassifier,
    classify_units,
)
from lczkit.classify.labels import (
    BUILT_CODES,
    CODES,
    HEIGHT_AXIS_PAIRS,
    LCZ_CLASSES,
    NATURAL_CODES,
    LczClass,
    code_of,
    lcz,
    legend,
)
from lczkit.classify.prototypes import DIMENSIONS, PROTOTYPES, PrototypeRange
from lczkit.classify.weights import PRESETS, WeightPreset, preset

__all__ = [
    "BUILT_CODES",
    "CLASSIFICATION_COLUMNS",
    "CODES",
    "DIMENSIONS",
    "DISTANCE_COLUMNS",
    "HEIGHT_AXIS_PAIRS",
    "LABEL_COLUMNS",
    "LCZ_CLASSES",
    "NATURAL_CODES",
    "PRESETS",
    "PROTOTYPES",
    "LczClass",
    "PrototypeClassifier",
    "PrototypeRange",
    "WeightPreset",
    "classify_units",
    "code_of",
    "lcz",
    "legend",
    "preset",
]
