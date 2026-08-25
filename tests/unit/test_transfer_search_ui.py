"""Localized long-term transfer Details and Result Card seams."""

# ruff: noqa: RUF001 -- reviewed multilingual interface copy is intentional.

from __future__ import annotations

import json

import pytest

from modules.application import (
    _normalize_transfer_timing_text,
    _transfer_search_detail_submenu_message,
    _transfer_search_result_message,
)
from modules.domain import SearchResult


@pytest.mark.parametrize(
    ("text", "kind", "expected"),
    (
        ("2026/27", "stated_season", "stated_season:2026-2027"),
        ("01.09.2026", "start_local_date", "start_local_date:2026-09-01"),
        ("ready_now", "ready_now", "ready_now"),
    ),
)
def test_transfer_timing_answers_are_normalized_without_tolerance(
    text: str, kind: str, expected: str
) -> None:
    assert _normalize_transfer_timing_text(text, kind=kind) == expected


@pytest.mark.parametrize("locale", ("en", "ru", "es", "fr"))
def test_transfer_seasonal_timing_menu_has_mutually_exclusive_answers(
    locale: str,
) -> None:
    message = _transfer_search_detail_submenu_message(
        update_id=f"timing:{locale}",
        telegram_user_id=55_100,
        locale=locale,
        screen_revision=9,
        detail_key="seasonal_timing",
        temporary=("ready_now",),
    )
    callbacks = tuple(row[0][1] for row in message.button_rows)
    assert sum("timing:" in callback for callback in callbacks) == 4
    assert callbacks[-2].startswith("transfer-details:done:")
    assert callbacks[-1].startswith("transfer-details:back:")


@pytest.mark.parametrize(
    ("locale", "expected_title", "expected_timing"),
    (
        ("en", "Roster Vacancy", "Named season: 2026-2027"),
        ("ru", "Вакансия в составе", "Указанный сезон: 2026-2027"),
        ("es", "Vacante en la plantilla", "Temporada indicada: 2026-2027"),
        ("fr", "Poste vacant dans l’effectif", "Saison indiquée: 2026-2027"),
    ),
)
def test_transfer_result_card_localizes_timing_and_provenance(
    locale: str,
    expected_title: str,
    expected_timing: str,
) -> None:
    result = SearchResult(
        result_id="result:transfer-card",
        completed_search_id="completed-search:transfer-card",
        absolute_position=1,
        result_class="confirmed_match",
        card_facts=tuple(
            sorted(
                {
                    "opportunity_id": "opportunity:transfer-card",
                    "opportunity_type": "roster_vacancy",
                    "roster_vacancy": "true",
                    "city_display_en": "Saint Petersburg",
                    "city_display_ru": "Санкт-Петербург",
                    "city_display_es": "San Petersburgo",
                    "city_display_fr": "Saint-Pétersbourg",
                    "place_display_en": "Petrogradskaya",
                    "place_display_ru": "Петроградская",
                    "place_display_es": "Petrogradskaya",
                    "place_display_fr": "Petrogradskaya",
                    "location_specificity": "2",
                    "positions": json.dumps(["goalkeeper"]),
                    "seasonal_timing": json.dumps(
                        {"kind": "stated_season", "value": "2026-2027"}
                    ),
                    "match_states": json.dumps(
                        {"positions": "confirmed", "seasonal_timing": "confirmed"}
                    ),
                    "source_posted_at": "2026-08-18T08:00:00+00:00",
                    "response_route_kind": "explicit_telegram_username",
                    "response_route_value": "@transfer_contact",
                }.items()
            )
        ),
    )
    message = _transfer_search_result_message(
        delivery_id=f"result:{locale}",
        telegram_user_id=55_100,
        locale=locale,
        screen_revision=2,
        result=result,
    )
    assert expected_title in message.text
    assert expected_timing in message.text
    assert "@transfer_contact" in message.text
