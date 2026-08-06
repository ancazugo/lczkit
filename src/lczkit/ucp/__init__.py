"""Phase 5 — urban canopy parameters, one row per `unit_id`.

The parameters Stewart & Oke (2012) actually define an LCZ by, in the units their table uses,
plus the functional `industrial_fraction` that makes LCZ 10 reachable at all. Everything here is
a pure transform over the Phase 1-4 outputs: no raster reads, no network, no file I/O.

Two of Stewart & Oke's seven morphological properties are **not** computed — sky view factor and
terrain roughness. See `lczkit.ucp.registry` for why, and the README for the same in prose.
"""

from lczkit.ucp.parameters import compute_parameters
from lczkit.ucp.registry import PARAMETER_COLUMNS, PARAMETERS, ParameterSpec, spec

__all__ = [
    "PARAMETERS",
    "PARAMETER_COLUMNS",
    "ParameterSpec",
    "compute_parameters",
    "spec",
]
