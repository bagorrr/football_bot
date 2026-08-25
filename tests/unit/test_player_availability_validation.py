"""Player offering semantics and source-bound quantity validation."""

# ruff: noqa: RUF001 -- reviewed multilingual evidence is intentional.

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


@pytest.mark.parametrize(
    "text",
    (
        "We are 4 players not available for the match.",
        "No players are available for the match.",
        "4 игрока недоступны для матча.",
        "Нет игроков, доступных для матча.",
        "4 jugadores no están disponibles para el partido.",
        "Ningún jugador está disponible para el partido.",
        "4 joueurs ne sont pas disponibles pour le match.",
        "Aucun joueur n’est disponible pour le match.",
    ),
)
def test_negative_availability_polarity_is_rejected_in_four_locales(
    text: str,
) -> None:
    assert not _player_availability_is_supported(
        4 if "4" in text else None,
        None,
        None,
        text,
        authoritative_body=text,
    )


@pytest.mark.parametrize(
    "text",
    (
        "We are 4 players available for the match.",
        "4 игрока доступны для матча.",
        "4 jugadores están disponibles para el partido.",
        "4 joueurs sont disponibles pour le match.",
    ),
)
def test_positive_availability_counterparts_remain_accepted(text: str) -> None:
    assert _player_availability_is_supported(
        4,
        None,
        None,
        text,
        authoritative_body=text,
    )


@pytest.mark.parametrize(
    ("text", "minimum", "maximum"),
    (
        ("We are 12-105 players available for the match.", 12, 105),
        ("Entre 2 y 5 jugadores están disponibles para el partido.", 2, 5),
        ("Entre 2 et 5 joueurs sont disponibles pour le match.", 2, 5),
    ),
)
def test_player_ranges_support_long_endpoints_and_localized_connectors(
    text: str,
    minimum: int,
    maximum: int,
) -> None:
    assert _player_availability_is_supported(
        None,
        minimum,
        maximum,
        text,
        authoritative_body=text,
    )


def test_player_quantity_values_must_share_one_compatible_offering_clause() -> None:
    contradictory = (
        "We are 6 players available for the match; between 2 and 5 players "
        "are available for the match."
    )
    assert not _player_availability_is_supported(
        None,
        2,
        5,
        contradictory,
        authoritative_body=contradictory,
    )
    assert not _player_availability_is_supported(
        6,
        None,
        None,
        contradictory,
        authoritative_body=contradictory,
    )
