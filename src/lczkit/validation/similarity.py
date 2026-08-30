"""Bechtel et al. (2020) class-similarity weights, and the weighted accuracy they define.

**Why this is not just another accuracy number.** Overall accuracy treats every mistake as equally
wrong: calling a compact midrise cell "open midrise" costs exactly what calling it "water" costs.
For LCZ that is plainly false — the scheme's classes lie on a near-continuum of built form, and the
whole point of reporting the two confusion axes separately is that adjacent-class error means
something different from cross-family error. `OA_w` is the LCZ community's answer, and reporting it
is what makes this package's per-class figures comparable to published LCZ maps.

Bechtel et al. frame it as a *generalisation* of overall accuracy rather than a different measure.
Plain OA is already the Hadamard product of the confusion matrix with a weight matrix carrying ones
on the diagonal and zeros off it — itself a similarity metric, in which every class is fully similar
to itself and fully dissimilar to everything else. Relaxing those off-diagonal zeros to real
similarities buys partial credit for a near-miss. So `OA_w` reduces to `OA` exactly when the matrix
is the identity, which is the first thing `test_validation_similarity.py` asserts.

**The weights live in `docs/references/tables/lcz_class_similarity.md`, not here.** A published
number is read from a committed transcription rather than reproduced from memory, and this matrix
has 289 cells, of which a wrong one would be invisible. The table is parsed
at import and the parsed values are the constants; there is no second copy to drift.

That file holds **two** matrices with identical headers — the similarity one and its complement.
`OA_w` uses the similarity matrix. Substituting the other inverts the measure without raising:
a perfect map scores 0.00, a map confusing LCZ 1 with LCZ G scores 1.00, and every cross-city
comparison in a paper ranks backwards. Hence the parsing is by section heading and the direction is
asserted by a test rather than trusted to a comment.
"""

from __future__ import annotations

import re
from pathlib import Path

from lczkit.classify.labels import CODES, code_of, lcz

BECHTEL_2020 = "10.3390/rs12111769"
"""Bechtel, Demuzere & Stewart (2020), *Remote Sensing* 12(11), 1769. Defines `OA_w` and the class
similarity matrix it weights the confusion matrix with."""

SIMILARITY_TABLE = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "references"
    / "tables"
    / "lcz_class_similarity.md"
)
"""The committed transcription. Repo content rather than data, so it needs no `DATA_DIR` — the same
exception `tests/fixtures/` relies on, and for the same reason: a clean checkout must be able to
reproduce a classification."""

SIMILARITY_HEADING = "## Similarity matrix of LCZ classes"


def _heading_matches(line: str, heading: str) -> bool:
    """Whether `line` is `heading`, ignoring a trailing parenthetical.

    The table records where in the paper each matrix came from — "(Figure 3a)", "(Figure 3b)",
    "(equation 1)" — and that provenance is exactly what a reference table is for. Matching the
    heading verbatim made adding it break the parse, which is the wrong way round: a citation
    should be addable without touching code.

    Deliberately *not* a `startswith`. "Dissimilarity matrix of LCZ classes" does not begin with
    "Similarity matrix…", so a prefix test happens to work here, but it would also match a future
    "Similarity matrix of LCZ classes, complement" — and picking up the complement is the one
    failure this whole module is arranged to prevent.
    """
    return re.sub(r"\s*\([^)]*\)\s*$", "", line.strip()) == heading


def _parse(path: Path, heading: str) -> dict[tuple[int, int], float]:
    """Read one matrix out of the table file, keyed by integer LCZ code pairs.

    Selected by heading, because the file holds two matrices whose header rows are identical and
    the *first* one is the matrix that must not be used.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if _heading_matches(line, heading))
    except StopIteration:  # pragma: no cover - a broken checkout, not a code path
        raise RuntimeError(f"{path} has no section {heading!r}") from None

    # The *contiguous* run of table lines, not every pipe-prefixed line in the section: the section
    # also carries a worked-values table below the prose, and filtering rather than slicing would
    # walk straight into it.
    body = lines[start:]
    first = next(index for index, line in enumerate(body) if line.startswith("|"))
    table: list[str] = []
    for line in body[first:]:
        if not line.startswith("|"):
            break
        table.append(line)

    columns = [cell.strip() for cell in table[0].strip().strip("|").split("|")][1:]
    weights: dict[tuple[int, int], float] = {}
    for line in table[2:]:  # +2 skips the alignment row
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        for column, value in zip(columns, cells[1:], strict=True):
            weights[(code_of(cells[0]), code_of(column))] = float(value)
    return weights


SIMILARITY: dict[tuple[int, int], float] = _parse(SIMILARITY_TABLE, SIMILARITY_HEADING)
"""`(reference code, predicted code) -> similarity in [0, 1]`. One on the diagonal."""


def _check() -> None:
    """Refuse to import against a table that cannot support the metric.

    Cheap, and it runs on a clean checkout. Each of these failing would produce a plausible number
    rather than an error: a missing pair silently drops units from the numerator, an off-diagonal
    one would mean a wrong answer scores as well as a right one, and a diagonal below one would
    penalise a correct classification.
    """
    missing = [(i, j) for i in CODES for j in CODES if (i, j) not in SIMILARITY]
    if missing:
        raise RuntimeError(
            f"{SIMILARITY_TABLE} is missing {len(missing)} pairs, e.g. {missing[:3]}"
        )
    for code in CODES:
        if SIMILARITY[(code, code)] != 1.0:
            raise RuntimeError(
                f"LCZ {lcz(code).label} has self-similarity {SIMILARITY[(code, code)]}, not 1.0 — "
                "this is the dissimilarity matrix, which inverts the measure"
            )
    out_of_range = [pair for pair, value in SIMILARITY.items() if not 0.0 <= value <= 1.0]
    if out_of_range:
        raise RuntimeError(f"{SIMILARITY_TABLE} has weights outside [0, 1]: {out_of_range[:3]}")


_check()
