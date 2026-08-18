"""Turning a city name into an extent, and refusing to guess when the name is not enough.

The locator `--city` resolves against. Every test here runs offline against the committed
twelve-row GUPPD fixture, so none of them needs the 564 KB table under a real `DATA_DIR` — which
is also the point: the locator exists so that mapping a city stops depending on what happens to be
on this particular machine.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import PLACES_FIXTURES_DIR

from lczkit.config import Settings
from lczkit.places import (
    GUPPD_BOUNDS,
    GUPPD_SOURCE_DIR_NAME,
    bounds_path,
    find,
    in_country,
    load_places,
    normalise,
    place,
)


@pytest.fixture
def places(places_data_dir: Path) -> tuple:
    return load_places(Settings.load(create_run_dir=False))


# --------------------------------------------------------------------------- normalisation


def test_an_accented_name_is_found_by_its_unaccented_spelling(places: tuple) -> None:
    """`São Paulo` has to be reachable by typing `sao paulo`.

    The gazetteer spells names as the JRC does and a command line is typed by a person; requiring
    the two to match byte for byte would make a third of the world's cities unnameable on a UK
    keyboard.
    """
    found = place(places, "sao paulo")

    assert found.name == "São Paulo"
    assert found.iso == "BRA"


def test_normalisation_collapses_case_punctuation_and_spacing() -> None:
    assert normalise("São Paulo") == "saopaulo"
    assert normalise("Washington D.C.") == "washingtondc"
    assert normalise("  HONG-KONG  ") == "hongkong"
    assert normalise("") == ""


def test_a_stored_name_keeps_its_own_spelling(places: tuple) -> None:
    """Normalisation is applied to the comparison, never to the data.

    The name goes into the run manifest and into the map site's own description, so folding the
    accents away in storage would put a misspelling in front of a reader to save a lookup.
    """
    assert {entry.name for entry in places} >= {"São Paulo", "Hong Kong", "East London"}


# --------------------------------------------------------------------------- matching


def test_an_exact_name_outranks_one_that_merely_contains_it(places: tuple) -> None:
    """`london` means London, not East London."""
    matches = find(places, "london")

    assert [entry.iso for entry in matches[:2]] == ["GBR", "CAN"]
    assert matches[-1].name == "East London"


def test_a_name_shared_by_two_cities_is_refused_rather_than_guessed(places: tuple) -> None:
    """Silently taking the first would run the wrong continent and record a manifest that looks
    entirely correct. Nothing downstream of a bbox could tell."""
    with pytest.raises(LookupError) as error:
        place(places, "cambridge")

    message = str(error.value)
    assert "2 urban regions" in message
    assert "United Kingdom" in message and "Canada" in message
    assert "--country" in message


def test_the_ambiguity_message_lists_only_the_tied_names(places: tuple) -> None:
    """East London is not a candidate for `london` and naming it would suggest it was."""
    with pytest.raises(LookupError) as error:
        place(places, "london")

    assert "East London" not in str(error.value)
    assert "2 urban regions" in str(error.value)


@pytest.mark.parametrize("country", ["GBR", "gb", "united kingdom", "United Kingdom"])
def test_a_country_resolves_by_code_or_name_in_full_or_as_a_prefix(
    places: tuple, country: str
) -> None:
    assert place(places, "cambridge", country=country).iso == "GBR"


def test_an_unknown_name_says_how_to_search_for_the_right_one(places: tuple) -> None:
    with pytest.raises(LookupError) as error:
        place(places, "atlantis")

    assert "lczkit cities" in str(error.value)
    assert "--bbox" in str(error.value)


def test_an_empty_query_with_a_country_lists_that_country(places: tuple) -> None:
    """`lczkit cities --country KEN` is a listing, not a no-op."""
    assert {entry.name for entry in find(places, "", country="KEN")} == {"Nairobi", "Mombasa"}


def test_in_country_without_a_country_returns_everything(places: tuple) -> None:
    """So an optional flag can be passed straight through without the caller branching."""
    assert in_country(places, None) == places
    assert in_country(places, "") == places


# --------------------------------------------------------------------------- the extent itself


def test_a_place_carries_the_bbox_in_lon_lat_and_its_area(places: tuple) -> None:
    berlin = place(places, "berlin")

    west, south, east, north = berlin.bbox
    assert -180 <= west < east <= 180
    assert -90 <= south < north <= 90
    # Land Berlin is 891 km2 and the GUPPD urban region is a little larger.
    assert 1_000 < berlin.area_km2 < 1_300


def test_the_area_shrinks_with_latitude_rather_than_being_a_raw_degree_product() -> None:
    """A degree of longitude is 111 km at the equator and 56 km at 60 degrees.

    Without the cosine, a northern city's extent reads roughly twice its real size — and this
    number is what tells a caller whether they are starting a three-minute run or a three-hour one.
    """
    from lczkit.output.extent import bbox_area_km2

    equatorial = bbox_area_km2((0.0, 0.0, 1.0, 1.0))
    northern = bbox_area_km2((0.0, 60.0, 1.0, 61.0))

    assert northern < equatorial / 1.9


def test_every_row_of_the_committed_fixture_parses(places: tuple) -> None:
    assert len(places) == 12
    assert all(entry.smod_id and entry.iso and entry.country for entry in places)
    assert len({entry.smod_id for entry in places}) == 12


# --------------------------------------------------------------------------- when it is absent


def test_a_missing_bounds_table_names_the_path_and_the_way_round_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The table is one of the few things a run reads that a user may simply not have.

    The alternative to this message is a bare `csv` error several frames down that names neither
    the dataset nor `--bbox`, which needs nothing on disk at all.
    """
    (tmp_path / "input").mkdir()
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings = Settings.load(create_run_dir=False)

    with pytest.raises(FileNotFoundError) as error:
        load_places(settings)

    assert str(GUPPD_SOURCE_DIR_NAME) in str(error.value)
    assert "--bbox" in str(error.value)


def test_the_bounds_path_follows_the_documented_input_layout(places_data_dir: Path) -> None:
    """`input/NASA/GUPPD/` — the agency directory CLAUDE.md's layout diagram files GUPPD under."""
    settings = Settings.load(create_run_dir=False)

    assert bounds_path(settings) == places_data_dir / "input" / GUPPD_SOURCE_DIR_NAME / GUPPD_BOUNDS
    assert bounds_path(settings).exists()


def test_a_table_missing_a_column_says_which_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A truncated or differently-processed CSV should not surface as a `KeyError` on row one."""
    guppd = tmp_path / "input" / "NASA" / "GUPPD"
    guppd.mkdir(parents=True)
    text = (PLACES_FIXTURES_DIR / "guppd_bounds.csv").read_text(encoding="utf-8")
    lines = [",".join(line.split(",")[:4]) for line in text.splitlines()]
    (guppd / "guppd_bounds.csv").write_text("\n".join(lines), encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    with pytest.raises(ValueError) as error:
        load_places(Settings.load(create_run_dir=False))

    assert "minx" in str(error.value)
