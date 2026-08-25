"""Tournament Result Card localization and publication-state regressions."""

from modules.application import _tournament_result_message
from modules.domain import SearchResult


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
