"""Player offering semantics and source-bound quantity validation."""

import pytest

from modules.application import _player_availability_is_supported


@pytest.mark.parametrize(
    "text",
    (
        "We are 4 players available for the match.",
        "от 2 до 5 игроков доступны для матча.",
        "De 2 a 5 jugadores estamos disponibles para el partido.",
        "De 2 à 5 joueurs sont disponibles pour le match.",
    ),
)
def test_player_quantity_is_bound_to_an_offered_group_and_supported_locales(
    text: str,
) -> None:
    if text.startswith("We"):
        assert _player_availability_is_supported(
            4, None, None, text, authoritative_body=text
        )
    else:
        assert _player_availability_is_supported(
            None, 2, 5, text, authoritative_body=text
        )


@pytest.mark.parametrize(
    "text",
    (
        "Need 4 players for the match.",
        "Need some players for the match.",
        "Нужны 4 игрока на матч.",
        "De 2 a 5 jugadores son necesarios para el partido.",
        "De 2 à 5 joueurs sont recherchés pour le match.",
    ),
)
def test_organizer_request_or_opening_language_is_not_player_availability(
    text: str,
) -> None:
    assert not _player_availability_is_supported(
        4 if "4" in text else None,
        None if "4" in text else 2,
        None if "4" in text else 5,
        text,
        authoritative_body=text,
    )


def test_player_count_must_match_the_same_availability_clause() -> None:
    assert not _player_availability_is_supported(
        4,
        None,
        None,
        "We are 3 players available for the match.",
        authoritative_body="We are 3 players available for the match.",
    )
    unrelated = (
        "We are 4 players available for the match. The other team needs 2 to 5 players."
    )
    assert not _player_availability_is_supported(
        None,
        2,
        5,
        unrelated,
        authoritative_body=unrelated,
    )


def test_unknown_player_quantity_requires_an_offering_clause() -> None:
    assert _player_availability_is_supported(
        None,
        None,
        None,
        "We can play in Moscow; our group is available for the match.",
        authoritative_body=(
            "We can play in Moscow; our group is available for the match."
        ),
    )
    assert not _player_availability_is_supported(
        None,
        None,
        None,
        "Football match in Moscow.",
        authoritative_body="Football match in Moscow.",
    )
