"""Focused Opponent Search presentation seams."""

# ruff: noqa: RUF001 -- reviewed multilingual interface copy is intentional.

from __future__ import annotations

import json

import pytest

from modules.application import (
    _opponent_request_result_message,
    _opponent_search_detail_submenu_message,
)
from modules.domain import SearchResult


def _opponent_result(*, include_publication_state: bool = True) -> SearchResult:
    facts = {
        "opportunity_id": "opportunity:opponent-card",
        "opportunity_type": "opponent_request",
        "start_local_date": "2026-08-20",
        "end_local_date": "2026-08-20",
        "iana_timezone": "Europe/Moscow",
        "city_display_en": "Saint Petersburg",
        "place_display_en": "Petrogradskaya",
        "location_specificity": "2",
        "venue_provision": "team_has_venue",
        "match_states": json.dumps({"venue_provision": "confirmed"}),
        "source_posted_at": "2026-08-18T08:00:00+00:00",
        "response_route_kind": "explicit_telegram_username",
        "response_route_value": "@opponent_contact",
    }
    if include_publication_state:
        facts["publication_state"] = "active"
    return SearchResult(
        result_id="result:opponent-card",
        completed_search_id="completed-search:opponent-card",
        absolute_position=1,
        result_class="confirmed_match",
        card_facts=tuple(sorted(facts.items())),
    )


@pytest.mark.parametrize(
    ("locale", "expected_labels"),
    (
        (
            "en",
            (
                "Our team has a venue",
                "We need the opponent’s venue",
                "Arrange jointly",
                "Any",
            ),
        ),
        (
            "ru",
            (
                "У нашей команды есть площадка",
                "Нужна площадка соперника",
                "Организуем вместе",
                "Неважно",
            ),
        ),
        (
            "es",
            (
                "Nuestro equipo tiene campo",
                "Necesitamos el campo del rival",
                "Organizar juntos",
                "Cualquiera",
            ),
        ),
        (
            "fr",
            (
                "Notre équipe a un terrain",
                "Nous avons besoin du terrain adverse",
                "Organiser ensemble",
                "Peu importe",
            ),
        ),
    ),
)
def test_venue_provision_renderer_is_one_answer_with_any(
    locale: str,
    expected_labels: tuple[str, ...],
) -> None:
    message = _opponent_search_detail_submenu_message(
        update_id=f"venue-menu:{locale}",
        telegram_user_id=1,
        locale=locale,
        screen_revision=7,
        detail_key="venue_provision",
        temporary=(),
    )

    labels = tuple(row[0][0].removeprefix("✓ ") for row in message.button_rows[:-1])
    callbacks = tuple(row[0][1] for row in message.button_rows[:-1])
    assert labels == expected_labels
    assert all("toggle" not in callback for callback in callbacks)
    assert callbacks[-1] == "opponent-details:venue:any:7"


def test_opponent_result_with_missing_publication_state_is_unavailable() -> None:
    message = _opponent_request_result_message(
        delivery_id="result:opponent-missing-publication-state",
        telegram_user_id=55_200,
        locale="en",
        screen_revision=2,
        result=_opponent_result(include_publication_state=False),
    )

    assert "Unavailable" in message.text
    assert "Contact" not in message.text
    assert "@opponent_contact" not in message.text
