"""Phase 13's pooling and its pre-registered verdict rule.

The sweep itself is not a test — sixteen metropolitan windows take hours. What is tested is the
arithmetic that turns sixteen per-city tables into one answer, because every failure mode here
produces a plausible number rather than an error:

- **pooling**, which must be area-weighted across cities. Vancouver carries 16 517 labelled cells
  against Mumbai's 1 706, so a mean of per-city shares would let the small cities outvote the large
  ones and quietly change the outcome.
- **the verdict rule**, which is pre-registered precisely so the outcome is not chosen after seeing
  the numbers. A rule that cannot be shown to fire correctly on constructed inputs is not a
  pre-registration, it is a hope.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


def load_script() -> ModuleType:
    """Import `scripts/bsf_published_ranges.py` by path, for the reason its sibling test gives:
    `scripts/` holds one-off analyses and is deliberately not importable as a package."""
    path = Path(__file__).resolve().parent.parent / "scripts" / "bsf_published_ranges.py"
    spec = importlib.util.spec_from_file_location("bsf_published_ranges", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script() -> ModuleType:
    return load_script()


def row(
    script: ModuleType,
    *,
    city: str,
    code: int,
    share: float,
    area: float,
    median: float | None = 0.3,
    europe: bool = False,
    grouping: str = "so2sat_labels",
    n: int | None = None,
):
    return script.ClassRow(
        city=city,
        region="test",
        europe_or_na=europe,
        arm="A",
        cascade="coarse",
        grouping=grouping,
        reference_file="so2sat.parquet",
        code=code,
        name="Compact midrise",
        n=n if n is not None else int(area / 10_000),
        area_m2=area,
        median=median,
        p10=None,
        p90=None,
        share_in_range=share,
        published_min=0.40,
        published_max=0.70,
    )


def test_pooling_is_area_weighted_across_cities_not_a_mean_of_city_shares(
    script: ModuleType,
) -> None:
    """A large city fully inside its range and a small one fully outside. The pooled share is the
    large city's, not the average of 1.0 and 0.0 — which is the difference between "reaches" and
    "does not" under the verdict rule."""
    rows = [
        row(script, city="big", code=2, share=1.0, area=900_000.0),
        row(script, city="small", code=2, share=0.0, area=100_000.0),
    ]

    pooled = script.pool(rows)

    assert pooled is not None
    assert pooled["share_in_range"] == pytest.approx(0.9)
    assert pooled["n_cities"] == 2
    assert pooled["reaches_range"] is True


def test_zero_area_classes_do_not_divide_the_pool_by_zero(script: ModuleType) -> None:
    assert script.pool([row(script, city="a", code=2, share=0.0, area=0.0)]) is None


def test_normalised_gap_is_measured_in_interval_widths(script: ModuleType) -> None:
    """So a 0.40-0.70 class and a 0.40-0.60 class can be averaged without the wider band
    dominating. Zero inside, negative below, positive above, None where an end is open."""
    assert script.normalised_gap(0.55, 0.40, 0.70) == pytest.approx(0.0)
    assert script.normalised_gap(0.10, 0.40, 0.70) == pytest.approx(-1.0)
    assert script.normalised_gap(0.90, 0.40, 0.70) == pytest.approx(2.0 / 3.0)
    assert script.normalised_gap(0.10, None, 0.10) is None
    assert script.normalised_gap(None, 0.40, 0.70) is None


def test_verdict_reads_inside_when_most_built_cells_reach_their_range(script: ModuleType) -> None:
    rows = [
        row(script, city="a", code=2, share=0.9, area=900_000.0),
        row(script, city="a", code=6, share=0.1, area=100_000.0),
    ]

    verdict = script.verdict(rows, grouping="so2sat_labels", arm="A", cascade="coarse")

    assert verdict["outcome"] == "inside"
    assert verdict["classes_reaching"] == [2]


def test_verdict_reads_worse_in_europe_only_when_europe_actually_trails(
    script: ModuleType,
) -> None:
    """Depressed everywhere, and materially more so in Europe on both classes — the outcome that
    would make unit definition the cause."""
    rows = [
        row(script, city="berlin", code=2, share=0.10, area=500_000.0, europe=True),
        row(script, city="berlin", code=6, share=0.10, area=500_000.0, europe=True),
        row(script, city="cairo", code=2, share=0.40, area=500_000.0),
        row(script, city="cairo", code=6, share=0.40, area=500_000.0),
    ]

    verdict = script.verdict(rows, grouping="so2sat_labels", arm="A", cascade="coarse")

    assert verdict["outcome"] == "worse_in_europe"
    assert sorted(verdict["classes_where_europe_trails"]) == [2, 6]


def test_a_regional_gap_below_the_threshold_is_not_called_regional(script: ModuleType) -> None:
    """Europe trails by 0.02, under the 0.05 pre-registered bar, so the outcome falls through to
    uniform depression rather than blaming unit definition for noise."""
    rows = [
        row(script, city="berlin", code=2, share=0.20, area=500_000.0, europe=True),
        row(script, city="cairo", code=2, share=0.22, area=500_000.0),
    ]

    verdict = script.verdict(rows, grouping="so2sat_labels", arm="A", cascade="coarse")

    assert verdict["outcome"] == "depressed_uniformly"
    assert verdict["classes_where_europe_trails"] == []


def test_europe_leading_is_not_mistaken_for_europe_trailing(script: ModuleType) -> None:
    """The direction the stored `lcz_v3` table actually shows. A sign error here would invert the
    phase's conclusion, so it is asserted rather than assumed."""
    rows = [
        row(script, city="berlin", code=2, share=0.46, area=500_000.0, europe=True),
        row(script, city="cairo", code=2, share=0.38, area=500_000.0),
    ]

    verdict = script.verdict(rows, grouping="so2sat_labels", arm="A", cascade="coarse")

    assert verdict["outcome"] == "depressed_uniformly"
    assert verdict["regional_gap_share"][2] == pytest.approx(0.08)


def test_the_two_groupings_are_compared_rather_than_conflated(script: ModuleType) -> None:
    """P3's instrument. Same class, same arm, two references, opposite verdicts on whether the
    published range is reached — which is the failure this phase exists to have caught."""
    rows = [
        row(script, city="a", code=2, share=0.8, area=100_000.0, grouping="so2sat_labels"),
        row(script, city="a", code=2, share=0.2, area=100_000.0, grouping="lcz_v3"),
    ]

    comparison = script.compare_groupings(rows, arm="A", cascade="coarse")

    assert comparison["per_class"][2]["share_delta"] == pytest.approx(0.6)
    assert comparison["per_class"][2]["verdict_differs"] is True
    assert comparison["n_classes_where_verdict_differs"] == 1


def test_a_missing_grouping_reports_absence_rather_than_a_number(script: ModuleType) -> None:
    """Rotterdam has no So2Sat coverage, and a city without labels must not silently fall back to
    the comparator — that substitution is the whole subject of this phase."""
    rows = [row(script, city="a", code=2, share=0.5, area=100_000.0, grouping="lcz_v3")]

    verdict = script.verdict(rows, grouping="so2sat_labels", arm="A", cascade="coarse")
    comparison = script.compare_groupings(rows, arm="A", cascade="coarse")

    assert verdict["outcome"] is None
    assert "meaning" in verdict
    assert comparison["mean_abs_share_delta"] is None


def test_flag_values_are_not_mistaken_for_city_keys(script: ModuleType) -> None:
    """`--stored <path>` consumed its path as a city key on the first launch of the sweep."""
    positional, values = script.parse_args(["berlin", "--stored", "/tmp/record.json"])

    assert positional == ["berlin"]
    assert values["--stored"] == Path("/tmp/record.json")


def test_stability_compares_only_the_cities_both_records_hold(script: ModuleType, tmp_path) -> None:
    """A partially-complete sweep must not report the difference between two city lists as a
    pipeline deviation. It did, at 6.6%, before this was fixed."""
    stored = tmp_path / "stored.json"
    stored.write_text(
        json.dumps(
            {
                "cities": [
                    _city_record("berlin", share=0.40),
                    # A city the in-progress run has not reached yet, with a very different share.
                    _city_record("vancouver", share=0.90),
                ]
            }
        ),
        encoding="utf-8",
    )
    # The run so far holds Berlin only, and reproduces it exactly.
    rows = [row(script, city="berlin", code=2, share=0.40, area=100_000.0, grouping="lcz_v3")]

    stability = script.harness_stability(rows, stored)

    assert stability is not None
    assert stability["max_abs_delta"] == pytest.approx(0.0)


def _city_record(name: str, *, share: float) -> dict:
    return {
        "fixture": name,
        "window": {"region": "test"},
        "cascades": {
            "coarse": {
                "arms": {
                    "A": {
                        "bsf_by_reference_class": {
                            "reference_file": "lcz_v3.tif",
                            "per_class": [
                                {
                                    "code": 2,
                                    "name": "Compact midrise",
                                    "n": 10,
                                    "area_m2": 100_000.0,
                                    "median": 0.3,
                                    "p10": None,
                                    "p90": None,
                                    "share_in_range": share,
                                    "published_min": 0.40,
                                    "published_max": 0.70,
                                }
                            ],
                        }
                    }
                }
            }
        },
    }
