"""Named, complete run configurations — the settings a run needs that have no safe default.

`Settings.load()` cannot produce a runnable configuration on its own, and that is deliberate.
`CleaningConfig`'s eight numeric fields and `HeightConfig`'s two confidences all default to `None`
and raise at call time, because each is a threshold someone measured and an invented default would
travel into every run's manifest looking like a measurement. See those models for the argument.

The consequence, before Phase 15, was that the values lived in `scripts/` — spread across
`berlin_metropolitan.py` and `unit_scale_experiment.py`, reassembled by a `configure()` in a third
script, and reachable only through a `sys.path` insertion. A command line cannot import that, and
neither can anything else. This module is where they live now; `configure()` delegates here, so the
published sites and `lczkit run` cannot drift apart.

Modelled on `lczkit.classify.weights`, which already has this shape for the weight vectors.

**One preset, and that is the honest number.** `published` is what the three published sites were
built with. A second name would imply a second measured configuration exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lczkit.config import (
    CleaningConfig,
    HeightConfig,
    LandCoverConfig,
    Settings,
    UcpConfig,
)

OVERTURE_RELEASE = "2026-07-22.0"
"""The release the committed fixtures were built from, so only the extent differs between a run
here and the offline numbers. Never `"latest"` — CLAUDE.md pins this."""

AREAL_CONFIDENCE = {"gob25d": 0.5, "wsf3d": 0.35, "ghsl": 0.25}
"""`height_confidence` per areal tier, descending with coarseness below tier 1's 0.9 / 0.6.

Ordinal, with no published number behind it — the same standing as the two Overture confidences
beside them, and set here rather than defaulted in `lczkit.config` for exactly the reason
`HeightConfig` gives: an invented default would travel into every run's manifest as if it were
measured. The choice is recorded in the manifest where it is visible.
"""


def _published_cleaning() -> CleaningConfig:
    """Phase 8's fixture-derived working values, including the street tiling.

    **These are the metropolitan values, not the fixture ones.** `scripts/unit_scale_experiment.py`
    carries a second `CleaningConfig` with `building_max_area_m2=50_000` and
    `building_merge_limit_m2=200` and no tiling fields, used for the 9 km2 comparison arms. The
    published sites went through `configure()`, which takes *these*. Taking the other set would
    change what `lczkit run` produces relative to every published figure, silently.

    2000 m tiles keep the largest face-artifact component tractable; the 600 m buffer is where seam
    agreement stops improving — measured on 16 km2 of Berlin at 99.77% (300 m), 99.97% (600 m) and
    99.95% (900 m).
    """
    return CleaningConfig(
        building_max_area_m2=100_000.0,
        building_min_area_m2=20.0,
        building_merge_limit_m2=50.0,
        building_overlap_limit=0.1,
        building_road_buffer_m=4.0,
        building_road_overlap_limit=0.5,
        street_tile_size_m=2000.0,
        street_tile_buffer_m=600.0,
    )


def _published_heights() -> HeightConfig:
    """Tier 1 plus the `coarse` cascade, with a confidence set on every areal tier.

    Without the confidences `build_cascade` raises; without the tiers `fill_heights` runs tier 1
    alone, which is what every run before Phase 11 did. `gob25d` keeps its confidence and stays
    `enabled=False` — retired in Phase 11 as measured-harmful, not deleted.
    """
    config = HeightConfig(overture_height_confidence=0.9, overture_num_floors_confidence=0.6)
    for tier in config.areal_tiers:
        tier.confidence = AREAL_CONFIDENCE[tier.name]
    return config


@dataclass(frozen=True)
class RunPreset:
    """A complete set of the configuration a run cannot default its way into."""

    name: str

    description: str

    overture_release: str

    cleaning: CleaningConfig = field(default_factory=_published_cleaning)

    heights: HeightConfig = field(default_factory=_published_heights)

    land_cover: LandCoverConfig = field(default_factory=LandCoverConfig)

    ucp: UcpConfig = field(default_factory=UcpConfig)

    def apply(self, settings: Settings) -> Settings:
        """Write this preset over `settings`, in place, and return it.

        Each section is copied rather than shared, so two runs configured from one preset cannot
        mutate each other's settings through it.
        """
        settings.overture.release = self.overture_release
        settings.cleaning = self.cleaning.model_copy(deep=True)
        settings.heights = self.heights.model_copy(deep=True)
        settings.land_cover = self.land_cover.model_copy(deep=True)
        settings.ucp = self.ucp.model_copy(deep=True)
        return settings


PRESETS: dict[str, RunPreset] = {
    "published": RunPreset(
        name="published",
        description=(
            "The configuration the Berlin, Hong Kong and Cairo sites were published with: "
            "Phase 8's metropolitan cleaning thresholds and the coarse height cascade."
        ),
        overture_release=OVERTURE_RELEASE,
    ),
}

DEFAULT_PRESET = "published"


def preset(name: str) -> RunPreset:
    """The preset called `name`, or a `KeyError` naming the ones that exist."""
    try:
        return PRESETS[name]
    except KeyError:
        raise KeyError(f"unknown run preset {name!r}; choose from {sorted(PRESETS)}") from None


def apply_preset(settings: Settings, name: str = DEFAULT_PRESET) -> Settings:
    """Apply the named preset to `settings` in place, returning it for chaining."""
    return preset(name).apply(settings)
