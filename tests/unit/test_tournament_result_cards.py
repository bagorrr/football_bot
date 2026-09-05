"""Tournament Result Card localization and publication-state regressions."""

from datetime import UTC, datetime

from modules.application import _tournament_result_message
from modules.domain import SearchResult
from modules.postgres_adapter import _result_card_facts_with_current_publication_state


def _result(*, publication_state: str = "active") -> SearchResult:
    facts = {
        "opportunity_id": "opportunity:tournament:card",
        "opportunity_revision_id": "opportunity:tournament:card:revision:1",
        "opportunity_type": "tournament",
        "publication_state": publication_state,
        "start_local_date": "2026-08-20",
        "end_local_date": "2026-08-20",
        "iana_timezone": "Europe/Moscow",
        "source_posted_at": "2026-07-18T09:06:00+00:00",
        "response_route_kind": "explicit_telegram_username",
        "response_route_value": "@tournament_contact",
        "location_specificity": "1",
        "city_display_en": "Saint Petersburg",
        "city_display_ru": "Санкт-Петербург",
        "city_display_es": "San Petersburgo",
        "city_display_fr": "Saint-Pétersbourg",
        "place_display_en": "Saint Petersburg",
        "place_display_ru": "Санкт-Петербург",
        "place_display_es": "San Petersburgo",
        "place_display_fr": "Saint-Pétersbourg",
        "match_states": "{}",
        "schedule": "Every Saturday",
        "structure": "group stage",
        "capacity": "16 teams",
        "prizes": '["cup", "Sponsor\'s choice"]',
    }
    return SearchResult(
        result_id="result:tournament:card",
        completed_search_id="completed-search:tournament:card",
        absolute_position=1,
        card_facts=tuple(sorted(facts.items())),
    )


def _current_projection(
    *,
    publication_state: str = "active",
    registration_deadline: str | None = "2026-08-25",
    response_route_value: str | None = "@current_tournament_contact",
) -> dict[str, object]:
    current_facts: dict[str, object] = {
        "start_local_date": "2026-08-20",
        "end_local_date": "2026-08-20",
        "iana_timezone": "Europe/Moscow",
        "open_participation": True,
    }
    if registration_deadline is not None:
        current_facts["registration_deadline"] = registration_deadline
    return {
        "opportunity_revision_id": "opportunity:tournament:card:revision:2",
        "publication_state": publication_state,
        "current_facts": current_facts,
        "response_route_kind": "explicit_telegram_username",
        "response_route_value": response_route_value,
    }


def test_tournament_result_card_localizes_free_text_field_by_field() -> None:
    message = _tournament_result_message(
        delivery_id="delivery:tournament:card",
        telegram_user_id=49_118,
        locale="ru",
        screen_revision=3,
        result=_result(),
    )

    assert "Каждую субботу" in message.text
    assert "Групповой этап" in message.text
    assert "16 команд" in message.text
    assert "Кубок" in message.text
    assert "Sponsor's choice (исходный язык)" in message.text
    assert "Every Saturday (исходный язык)" not in message.text
    assert "group stage (исходный язык)" not in message.text


def test_tournament_result_card_renders_nested_free_text_leaves_field_by_field() -> (
    None
):
    result = _result()
    facts = dict(result.card_facts)
    facts["schedule"] = (
        '{"weekday": "Saturday", "rounds": 3, "note": "Final venue announced later"}'
    )
    nested_result = SearchResult(
        result_id=result.result_id,
        completed_search_id=result.completed_search_id,
        absolute_position=result.absolute_position,
        card_facts=tuple(sorted(facts.items())),
    )

    message = _tournament_result_message(
        delivery_id="delivery:tournament:nested",
        telegram_user_id=49_118,
        locale="ru",
        screen_revision=3,
        result=nested_result,
    )

    assert "День недели: Суббота" in message.text
    assert "Раундов: 3" in message.text
    assert "Final venue announced later (исходный язык)" in message.text
    assert "{" not in message.text
    assert "}" not in message.text


def test_tournament_result_card_covers_all_conversation_languages() -> None:
    expected_titles = {
        "en": "⚽ Tournament",
        "ru": "⚽ Турнир",
        "es": "⚽ Torneo",
        "fr": "⚽ Tournoi",
    }
    expected_contacts = {
        "en": "Contact: @tournament_contact",
        "ru": "Контакт: @tournament_contact",
        "es": "Contacto: @tournament_contact",
        "fr": "Contact: @tournament_contact",
    }

    for locale, title in expected_titles.items():
        message = _tournament_result_message(
            delivery_id=f"delivery:tournament:{locale}",
            telegram_user_id=49_118,
            locale=locale,
            screen_revision=3,
            result=_result(),
        )
        assert title in message.text
        assert expected_contacts[locale] in message.text


def test_tournament_historical_card_is_unavailable_without_contact() -> None:
    unavailable_labels = {
        "en": "Unavailable",
        "ru": "Недоступно",
        "es": "No disponible",
        "fr": "Indisponible",
    }

    for locale, unavailable in unavailable_labels.items():
        message = _tournament_result_message(
            delivery_id=f"delivery:tournament:historical:{locale}",
            telegram_user_id=49_118,
            locale=locale,
            screen_revision=4,
            result=_result(publication_state="expired"),
        )
        assert unavailable in message.text
        assert "@tournament_contact" not in message.text
        assert {
            "en": "Contact",
            "ru": "Контакт",
            "es": "Contacto",
            "fr": "Contact",
        }[locale] + ":" not in message.text


def test_tournament_card_with_missing_current_projection_fails_closed() -> None:
    facts = dict(_result().card_facts)
    facts.pop("publication_state")
    result = SearchResult(
        result_id="result:tournament:missing-projection",
        completed_search_id="completed-search:tournament:missing-projection",
        absolute_position=1,
        card_facts=tuple(sorted(facts.items())),
    )

    message = _tournament_result_message(
        delivery_id="delivery:tournament:missing-projection",
        telegram_user_id=49_118,
        locale="en",
        screen_revision=4,
        result=result,
    )

    assert "Unavailable" in message.text
    assert "@tournament_contact" not in message.text
    assert "Contact:" not in message.text


def test_tournament_card_with_route_less_active_state_is_unavailable() -> None:
    facts = dict(_result().card_facts)
    facts.pop("response_route_kind")
    facts.pop("response_route_value")
    result = SearchResult(
        result_id="result:tournament:route-less-active",
        completed_search_id="completed-search:tournament:route-less-active",
        absolute_position=1,
        result_class="confirmed_match",
        card_facts=tuple(sorted(facts.items())),
    )

    message = _tournament_result_message(
        delivery_id="delivery:tournament:route-less-active",
        telegram_user_id=49_118,
        locale="en",
        screen_revision=4,
        result=result,
    )

    assert "Unavailable" in message.text
    assert "Contact:" not in message.text
    assert "@tournament_contact" not in message.text


def test_tournament_card_with_suppressed_current_projection_is_unavailable() -> None:
    message = _tournament_result_message(
        delivery_id="delivery:tournament:suppressed",
        telegram_user_id=49_118,
        locale="en",
        screen_revision=4,
        result=_result(publication_state="suppressed"),
    )

    assert "Unavailable" in message.text
    assert "@tournament_contact" not in message.text


def test_historical_card_uses_shortened_current_deadline_and_hides_contact() -> None:
    current_facts = _result().card_facts
    overlaid = _result_card_facts_with_current_publication_state(
        dict(current_facts),
        _current_projection(registration_deadline="2026-08-18"),
        as_of=datetime(2026, 8, 19, 0, 0, tzinfo=UTC),
    )

    assert overlaid["publication_state"] == "expired"
    assert "response_route_value" not in overlaid
    assert "@tournament_contact" not in str(overlaid)


def test_historical_card_uses_retracted_current_revision_and_hides_contact() -> None:
    overlaid = _result_card_facts_with_current_publication_state(
        dict(_result().card_facts),
        _current_projection(publication_state="suppressed"),
        as_of=datetime(2026, 8, 19, 0, 0, tzinfo=UTC),
    )

    assert overlaid["publication_state"] == "suppressed"
    assert "response_route_kind" not in overlaid
    assert "response_route_value" not in overlaid


def test_historical_card_fails_closed_on_malformed_current_deadline() -> None:
    overlaid = _result_card_facts_with_current_publication_state(
        dict(_result().card_facts),
        _current_projection(registration_deadline="not-a-date"),
        as_of=datetime(2026, 8, 19, 0, 0, tzinfo=UTC),
    )

    assert overlaid["publication_state"] == "suppressed"
    assert "response_route_value" not in overlaid


def test_historical_card_uses_current_route_when_current_revision_is_active() -> None:
    overlaid = _result_card_facts_with_current_publication_state(
        dict(_result().card_facts),
        _current_projection(),
        as_of=datetime(2026, 8, 19, 0, 0, tzinfo=UTC),
    )

    assert overlaid["publication_state"] == "active"
    assert overlaid["response_route_value"] == "@current_tournament_contact"
    assert "@tournament_contact" not in str(overlaid)


def test_tournament_projection_with_missing_route_fails_closed() -> None:
    overlaid = _result_card_facts_with_current_publication_state(
        dict(_result().card_facts),
        _current_projection(response_route_value=None),
        as_of=datetime(2026, 8, 19, 0, 0, tzinfo=UTC),
    )

    assert overlaid["publication_state"] == "suppressed"
    assert "response_route_kind" not in overlaid
    assert "response_route_value" not in overlaid
