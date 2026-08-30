"""The 17 Local Climate Zones: integer code, Stewart & Oke label, name, colour.

Integer coding and colours follow Demuzere et al. (2022), so a run's output drops straight into
the LCZ Generator's tooling and can be compared against the global map without a translation
step. Transcribed from `docs/references/tables/demuzere_2022_lcz_codes.md`, which a test parses
and asserts equal to `LCZ_CLASSES` — the committed table is the authority, this module is a copy
of it that ships in the wheel.

Nothing here is configurable. The codes are an interchange convention and the colours are how
every published LCZ map is read; a run that renumbered them would be unreadable by the tools this
package exists to feed.
"""

from __future__ import annotations

from dataclasses import dataclass

DEMUZERE_2022 = "10.5194/essd-14-3835-2022"
"""Demuzere et al. (2022), *ESSD* 14, 3835-3873. The coding convention and colour table."""


@dataclass(frozen=True)
class LczClass:
    """One Local Climate Zone."""

    code: int
    """Integer code 1-17, as written to the output raster/table."""

    label: str
    """Stewart & Oke's own label: `"1"`-`"10"` for the built types, `"A"`-`"G"` for the natural."""

    name: str
    """Class name, e.g. `"Compact high-rise"`."""

    colour: str
    """Lower-case `#rrggbb`, from the published map's colormap."""


LCZ_CLASSES: tuple[LczClass, ...] = (
    LczClass(1, "1", "Compact high-rise", "#8c0000"),
    LczClass(2, "2", "Compact midrise", "#d10000"),
    LczClass(3, "3", "Compact low-rise", "#ff0000"),
    LczClass(4, "4", "Open high-rise", "#bf4d00"),
    LczClass(5, "5", "Open midrise", "#ff6600"),
    LczClass(6, "6", "Open low-rise", "#ff9955"),
    LczClass(7, "7", "Lightweight low-rise", "#faee05"),
    LczClass(8, "8", "Large low-rise", "#bcbcbc"),
    LczClass(9, "9", "Sparsely built", "#ffccaa"),
    LczClass(10, "10", "Heavy industry", "#555555"),
    LczClass(11, "A", "Dense trees", "#006a00"),
    LczClass(12, "B", "Scattered trees", "#00aa00"),
    LczClass(13, "C", "Bush, scrub", "#648525"),
    LczClass(14, "D", "Low plants", "#b9db79"),
    LczClass(15, "E", "Bare rock or paved", "#000000"),
    LczClass(16, "F", "Bare soil or sand", "#fbf7ae"),
    LczClass(17, "G", "Water", "#6a6aff"),
)

CODES: tuple[int, ...] = tuple(lcz.code for lcz in LCZ_CLASSES)
"""Every code, ascending. The column order of the 17-way distance vector."""

BUILT_CODES: tuple[int, ...] = tuple(lcz.code for lcz in LCZ_CLASSES if lcz.label.isdigit())
"""LCZ 1-10. The types Bernard et al. (2024) apply the closest-distance approach to."""

NATURAL_CODES: tuple[int, ...] = tuple(lcz.code for lcz in LCZ_CLASSES if not lcz.label.isdigit())
"""LCZ A-G, codes 11-17."""

NODATA_CODE = 0
"""The published map's nodata value. Never a class, and never written as a label."""

COMPACTNESS_AXIS_PAIRS: tuple[tuple[int, int], ...] = ((1, 4), (2, 5), (3, 6))
"""Pairs holding the height band fixed and varying compactness.

1 and 4 are both high-rise, 2 and 5 both midrise, 3 and 6 both low-rise; within each pair the
compact member differs from the open one in building surface fraction alone (LCZ 2 is 40-70%,
LCZ 5 is 20-40%). A disagreement here is evidence about **footprint coverage and unit definition**
- whether the buildings are all present and whether the unit is the right size to hold an LCZ
patch - not about height.
"""

HEIGHT_AXIS_PAIRS: tuple[tuple[int, int], ...] = (
    (1, 2),
    (2, 3),
    (1, 3),
    (4, 5),
    (5, 6),
    (4, 6),
)
"""Pairs holding compactness fixed and varying the height band.

1<->2<->3 among the compact types and 4<->5<->6 among the open ones, which is the axis Stewart &
Oke separate on height: >25 m, 10-25 m and <10 m. A disagreement here is evidence about the
**height estimate**, which is why this is the axis that pairs with `height_completeness`: where
heights come from an areal product, error concentrates along it, because such a product cannot
resolve those three bands within a heterogeneous unit.

Every pair within each compactness group, not only the adjacent ones. 1<->3 is a high-rise read as
low-rise: a height confusion of two full bands rather than one, and the most severe kind. Counting
only 1<->2 and 2<->3 would report the axis as quieter than it is.

The two axes are reported separately and under the names that describe them. They are easy to
confuse: the compactness pairs hold height fixed and vary building surface fraction.
"""

_BY_CODE = {lcz.code: lcz for lcz in LCZ_CLASSES}
_BY_LABEL = {lcz.label: lcz for lcz in LCZ_CLASSES}


def lcz(code: int) -> LczClass:
    """The class with integer `code`, or a `KeyError` saying what exists."""
    try:
        return _BY_CODE[code]
    except KeyError:
        raise KeyError(f"no LCZ with code {code}; codes are {CODES[0]}-{CODES[-1]}") from None


def code_of(label: str) -> int:
    """The integer code for a Stewart & Oke label such as `"3"` or `"A"`."""
    try:
        return _BY_LABEL[label].code
    except KeyError:
        raise KeyError(f"no LCZ labelled {label!r}; labels are {', '.join(_BY_LABEL)}") from None


def legend() -> dict[str, dict[str, str | int]]:
    """The full legend, keyed by code as a string, for the run manifest and the map site."""
    return {
        str(entry.code): {
            "code": entry.code,
            "label": entry.label,
            "name": entry.name,
            "colour": entry.colour,
        }
        for entry in LCZ_CLASSES
    }
