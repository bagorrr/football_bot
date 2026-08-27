"""Localized Refereeing Result Card presentation and data-boundary tests."""

from __future__ import annotations

import json

from modules.application import _refereeing_result_message
from modules.domain import SearchResult


def _result(
    *, opportunity_type: str = "referee_availability", standing: bool = False
) -> SearchResult:
    facts: dict[str, str] = {
        "opportunity_id": "opportunity:referee-card",
        "opportunity_revision_id": "opportunity:referee-card:revision:1",
        "opportunity_type": opportunity_type,
        "iana_timezone": "Europe/Moscow",
        "source_posted_at": "2026-08-18T08:00:00+00:00",
        "source_edited_at": "2026-08-19T08:00:00+00:00",
        "response_route_kind": "explicit_telegram_username",
        "response_route_value": "@referee_contact",
        "location_specificity": "2",
        "event_types": json.dumps(["match", "tournament"]),
        "team_formats": json.dumps(["7x7"]),
        "referee_roles": json.dumps(["head_referee"]),
        "payment": "paid",
        "payment_amount": "50",
        "payment_currency": "EUR",
        "match_states": json.dumps(
            {
                "date": "unknown" if standing else "confirmed",
                "times": "confirmed",
                "event_types": "confirmed",
                "team_formats": "confirmed",
                "referee_roles": "confirmed",
                "payment": "confirmed",
                "search_area": "confirmed",
            },
            sort_keys=True,
        ),
    }
    if not standing:
        facts.update(
            {
                "start_local_date": "2026-08-20",
                "end_local_date": "2026-08-20",
                "exact_local_time": "19:00",
            }
        )
    for locale, city, place in (
        ("en", "Saint Petersburg", "Petrogradskaya"),
        ("ru", "Санкт-Петербург", "Петроградская"),
        ("es", "San Petersburgo", "Petrogradskaya"),
        ("fr", "Saint-Pétersbourg", "Petrogradskaya"),
    ):
        facts[f"city_display_{locale}"] = city
        facts[f"place_display_{locale}"] = place
    return SearchResult(
        result_id="result:referee-card",
        completed_search_id="completed-search:referee-card",
        absolute_position=1,
        result_class="possible_match" if standing else "confirmed_match",
        card_facts=tuple(sorted(facts.items())),
    )


def test_referee_result_card_uses_fixed_fields_and_excludes_non_selectable_facts() -> (
    None
):
    message = _refereeing_result_message(
        delivery_id="delivery:referee-card",
        telegram_user_id=49_100,
        locale="en",
        screen_revision=2,
        result=_result(),
    )

    assert "⚖️ Referee Availability" in message.text
    assert "20 August 2026, 19:00" in message.text
    assert "Saint Petersburg, Petrogradskaya" in message.text
    assert "Match, Tournament" in message.text
    assert "7x7" in message.text
    assert "Head referee" in message.text
    assert "Paid (50 EUR)" in message.text
    assert message.text.index("Match, Tournament") < message.text.index("7x7")
    assert message.text.index("7x7") < message.text.index("Head referee")
    assert message.text.index("Head referee") < message.text.index("Paid (50 EUR)")
    assert "Venue" not in message.text
    assert "surface" not in message.text.lower()
    assert "Contact: @referee_contact" in message.text


def test_standing_referee_availability_card_explains_unknown_date() -> None:
    message = _refereeing_result_message(
        delivery_id="delivery:referee-standing",
        telegram_user_id=49_100,
        locale="ru",
        screen_revision=2,
        result=_result(standing=True),
    )

    assert "⚖️ Доступность судьи" in message.text
    assert "Постоянная доступность" in message.text
    assert "Нужно уточнить: дата." in message.text
    assert "@referee_contact" in message.text


def test_referee_result_card_covers_all_conversation_languages() -> None:
    expected_titles = {
        "en": "⚖️ Referee Availability",
        "ru": "⚖️ Доступность судьи",
        "es": "⚖️ Disponibilidad de árbitro",
        "fr": "⚖️ Disponibilité de l\u2019arbitre",
    }
    for locale, title in expected_titles.items():
        message = _refereeing_result_message(
            delivery_id=f"delivery:referee:{locale}",
            telegram_user_id=49_100,
            locale=locale,
            screen_revision=2,
            result=_result(),
        )
        assert title in message.text
        assert "@referee_contact" in message.text
