"""Named, complete run configurations — the settings a run needs that have no safe default.

`Settings.load()` cannot produce a runnable configuration on its own, and that is deliberate.
`CleaningConfig`'s eight numeric fields and `HeightConfig`'s two confidences all default to `None`
and raise at call time, because each is a threshold someone measured and an invented default would
travel into every run's manifest looking like a measurement. See those models for the argument.

A preset is where those values live, so that `lczkit run` and the published sites cannot drift
apart. Modelled on `lczkit.classify.weights`, which has the same shape for the weight vectors.

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
here and the offline numbers. Never `"latest"`: a floating release is not reproducible."""

AREAL_CONFIDENCE = {"gob25d": 0.5, "wsf3d": 0.35, "ghsl": 0.25}
"""`height_confidence` per areal tier, descending with coarseness below tier 1's 0.9 / 0.6.

Ordinal, with no published number behind it — the same standing as the two Overture confidences
beside them, and set here rather than defaulted in `lczkit.config` for exactly the reason
`HeightConfig` gives: an invented default would travel into every run's manifest as if it were
measured. The choice is recorded in the manifest where it is visible.
"""


def _published_cleaning() -> CleaningConfig:
    """The fixture-derived working values for a metropolitan extent, including the street tiling.

    These are the thresholds the published sites were built with. A smaller extent can afford a
    smaller `building_max_area_m2` and no tiling, but changing them here changes what `lczkit run`
    produces relative to every published figure.

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
    alone. `gob25d` keeps its confidence and stays `enabled=False` — measured harmful, so it is
    switched off rather than deleted.
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

        **`gee_project` survives the copy.** It is resolved from `GEE_PROJECT_NAME` by
        `Settings.load`, so it is a credential and not a measured configuration, and replacing the
        whole `land_cover` section discarded it — every `lczkit run` cleared the variable moments
        after reading it. That was invisible while nothing downstream read the field, and it is
        exactly the silent-discard failure `Settings.load` documents in the other direction: an
        absent value must leave what is already there alone. A preset that names a project itself
        still wins, so the precedence is preset, then environment.

        A consequence worth naming, because the field now reaches places it never did: every
        manifest on disk before this fix recorded `gee_project: null`, and every one after it
        records the project the environment supplied, whichever backend answered. The manifest is
        `settings.model_dump()` verbatim and `build_site` copies it into the site, so the project
        ID is published with any site built from such a run. That is the designed behaviour rather
        than a leak — a Google Cloud project ID names a tenancy and is not a credential, unlike
        `VizConfig.maptiler_key`, which is `exclude=True` precisely because it is one — but it is
        the same three-files-deep path, so it is stated rather than left to be discovered.
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
