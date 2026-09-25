"""Named, complete run configurations: the measured values that have no safe default.

`CleaningConfig`'s thresholds and the height confidences default to `None` in `lczkit.config` and
raise when used, because an invented default would enter every manifest looking like a
measurement. A preset supplies them, so `lczkit run` and the published sites cannot drift apart.
There is one preset, `published`, because only one configuration has been measured.
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
here and the offline numbers. Never `"latest"`: a floating release is not reproducible."""

AREAL_CONFIDENCE = {"gob25d": 0.5, "wsf3d": 0.35, "ghsl": 0.25}
"""`height_confidence` per areal tier, descending with coarseness below tier 1's 0.9 / 0.6.
Ordinal, with no published number behind it; recorded in the manifest."""


def _published_cleaning() -> CleaningConfig:
    """The fixture-derived values the published sites were built with, street tiling included.

    The 600 m tile buffer is where seam agreement stops improving: 99.77% (300 m), 99.97% (600 m)
    and 99.95% (900 m) on 16 km² of Berlin.
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
    """Tier 1 plus the `coarse` cascade, with a confidence on every areal tier.

    Open Buildings 2.5D keeps its confidence and stays disabled.
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

        Sections are copied, not shared, so two runs from one preset cannot mutate each other. An
        environment-supplied `gee_project` survives unless the preset names one itself: replacing
        the whole `land_cover` section used to discard it.
        """
        settings.overture.release = self.overture_release
        settings.cleaning = self.cleaning.model_copy(deep=True)
        settings.heights = self.heights.model_copy(deep=True)
        land_cover = self.land_cover.model_copy(deep=True)
        if land_cover.gee_project is None:
            land_cover.gee_project = settings.land_cover.gee_project
        settings.land_cover = land_cover
        settings.ucp = self.ucp.model_copy(deep=True)
        return settings


PRESETS: dict[str, RunPreset] = {
    "published": RunPreset(
        name="published",
        description=(
            "The configuration the Berlin, Hong Kong and Cairo sites were published with: "
            "metropolitan cleaning thresholds and the coarse height cascade."
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
