"""Deterministic Opponent Search matching."""

# ruff: noqa: RUF001 -- reviewed multilingual interface copy is intentional.

from datetime import UTC, date, datetime
from typing import cast

from modules.application import (
    _opponent_request_result_message,
    _opponent_search_details_hub_message,
)
from modules.classifier_contract import (
    JsonValue as ClassifierJsonValue,
)
from modules.classifier_contract import (
    classifier_output_is_schema_valid,
)
from modules.domain import (
    CompletedSearch,
    MatchState,
    OpportunityRevisionProjection,
    RequiredDate,
    UserIntent,
    evaluate_opponent_search,
    match_venue_provision,
)


def _search(
    *,
    venue: str | None = None,
    details: tuple[tuple[str, tuple[str, ...]], ...] | None = None,
) -> CompletedSearch:
    return CompletedSearch(
        completed_search_id="completed-search:opponent",
        telegram_user_id=49_540,
        search_update_id="opponent-search",
        user_intent=UserIntent.OPPONENT_SEARCH,
        country_id="country:ru",
        city_id="city:ru:spb",
        sub_city_area_ids=(),
        whole_city=True,
        required_date=RequiredDate(
            start_local_date=date(2026, 8, 20),
            end_local_date=date(2026, 8, 20),
            iana_timezone="Europe/Moscow",
            timezone_data_version="controlled-tzdb-v1",
        ),
        completed_at=datetime(2026, 8, 18, 9, tzinfo=UTC),
        opponent_search_details=(
            details
            if details is not None
            else (("venue_provision", (venue,)),)
            if venue is not None
            else ()
        ),
    )


def _opportunity(
    *,
    opportunity_id: str,
    venue: str | None,
    opportunity_type: str = "opponent_request",
    explicit_request: bool = True,
    extra_facts: dict[str, object] | None = None,
) -> OpportunityRevisionProjection:
    facts: dict[str, object] = {
        "start_local_date": "2026-08-20",
        "end_local_date": "2026-08-20",
        "exact_local_time": None,
        "day_part": None,
        "iana_timezone": "Europe/Moscow",
        "country_id": "country:ru",
        "city_id": "city:ru:spb",
        "place_id": "city:ru:spb",
        "location_geographic_type": "city",
        "location_parent_ids": ["country:ru"],
        "location_verified_disjoint_place_ids": [],
        "source_posted_at": "2026-08-18T08:00:00+00:00",
        "opponent_request": explicit_request,
    }
    for locale, display_name in {
        "en": "Saint Petersburg",
        "ru": "Санкт-Петербург",
        "es": "San Petersburgo",
        "fr": "Saint-Pétersbourg",
    }.items():
        facts[f"city_display_{locale}"] = display_name
        facts[f"place_display_{locale}"] = display_name
    if venue is not None:
        facts["venue_provision"] = venue
    if extra_facts is not None:
        facts.update(extra_facts)
    return OpportunityRevisionProjection(
        opportunity_id=opportunity_id,
        opportunity_revision_id=f"{opportunity_id}:revision:1",
        opportunity_type=opportunity_type,
        publication_state="active",
        accepted_facts=facts,
        response_route={"kind": "source_message", "value": "https://t.me/source/1"},
    )


def test_venue_provision_complement_matrix_is_explicit() -> None:
    assert (
        match_venue_provision("team_has_venue", "team_has_venue")
        is MatchState.CONFIRMED
    )
    assert (
        match_venue_provision("team_has_venue", "needs_opponent_venue")
        is MatchState.CONFIRMED
    )
    assert (
        match_venue_provision("team_has_venue", "arrange_jointly")
        is MatchState.CONFIRMED
    )
    assert (
        match_venue_provision("needs_opponent_venue", "team_has_venue")
        is MatchState.CONFIRMED
    )
    assert (
        match_venue_provision("needs_opponent_venue", "arrange_jointly")
        is MatchState.CONFLICT
    )
    assert (
        match_venue_provision("arrange_jointly", "team_has_venue")
        is MatchState.CONFIRMED
    )
    assert (
        match_venue_provision("arrange_jointly", "arrange_jointly")
        is MatchState.CONFIRMED
    )
    assert (
        match_venue_provision("arrange_jointly", "needs_opponent_venue")
        is MatchState.CONFLICT
    )


def test_unknown_opportunity_venue_is_possible_but_conflict_is_excluded() -> None:
    details = dict(_search(venue="needs_opponent_venue").opponent_search_details)
    results = evaluate_opponent_search(
        _search(venue="needs_opponent_venue"),
        details,
        (
            _opportunity(opportunity_id="unknown", venue=None),
            _opportunity(opportunity_id="incompatible", venue="arrange_jointly"),
        ),
    )
    assert [result.result_id.rsplit(":", 1)[-1] for result in results] == ["unknown"]
    assert results[0].result_class == "possible_match"
    assert "venue_provision" not in dict(results[0].card_facts)
    message = _opponent_request_result_message(
        delivery_id="result",
        telegram_user_id=49_540,
        locale="en",
        screen_revision=1,
        result=results[0],
    )
    assert "Our team has a venue" not in message.text
    assert "Needs clarification" in message.text


def test_opponent_hub_and_card_follow_the_four_language_result_contract() -> None:
    details = (
        ("team_formats", ("7x7",)),
        ("playing_levels", ("average",)),
        ("venue_provision", ("team_has_venue",)),
        ("venue_settings", ("outdoor",)),
        ("playing_surfaces", ("artificial_turf",)),
        ("payment", ("free",)),
    )
    result = evaluate_opponent_search(
        _search(details=details),
        dict(details),
        (
            _opportunity(
                opportunity_id="localized-card",
                venue="team_has_venue",
                extra_facts={
                    "exact_local_time": "19:00",
                    "team_formats": ["7x7"],
                    "playing_levels": ["average"],
                    "venue_settings": ["outdoor"],
                    "playing_surfaces": ["artificial_turf"],
                    "payment": "free",
                },
            ),
        ),
    )[0]
    expected = {
        "en": {
            "hub": "You can choose the following settings:",
            "date": "20 August 2026, 19:00",
            "venue": "We have a venue",
            "criterion": "venue provision",
            "level": "Average",
            "label": "Matches",
            "posted": "Posted: 18 August 2026 at 11:00",
            "contact": "Contact:",
            "invitation": (
                "Questions? Message me. I can explain the card or help refine "
                "your search."
            ),
        },
        "ru": {
            "hub": "Можно выбрать следующие настройки:",
            "date": "20 августа 2026, 19:00",
            "venue": "Площадка у нас есть",
            "criterion": "предоставление площадки",
            "level": "Средний",
            "label": "Подходит",
            "posted": "Пост: 18 августа 2026 в 11:00",
            "contact": "Контакт:",
            "invitation": (
                "💬 Остались вопросы? Напишите, я объясню карточку "
                "или помогу уточнить поиск."
            ),
        },
        "es": {
            "hub": "Puedes elegir las siguientes opciones:",
            "date": "20 agosto 2026, 19:00",
            "venue": "Tenemos campo",
            "criterion": "provisión del campo",
            "level": "Medio",
            "label": "Coincide",
            "posted": "Publicado: 18 agosto 2026 a las 11:00",
            "contact": "Contacto:",
            "invitation": (
                "¿Tiene alguna pregunta? Escríbame. Le explicaré la ficha "
                "o le ayudaré a ajustar la búsqueda."
            ),
        },
        "fr": {
            "hub": "Vous pouvez choisir les paramètres suivants :",
            "date": "20 août 2026, 19:00",
            "venue": "Nous avons un terrain",
            "criterion": "mise à disposition du terrain",
            "level": "Moyen",
            "label": "Correspond",
            "posted": "Publié: 18 août 2026 à 11:00",
            "contact": "Contact:",
            "invitation": (
                "Une question ? Écrivez-moi. Je peux expliquer la fiche "
                "ou vous aider à affiner votre recherche."
            ),
        },
    }
    for locale, copy in expected.items():
        hub = _opponent_search_details_hub_message(
            update_id="hub",
            telegram_user_id=49_540,
            locale=locale,
            screen_revision=1,
            details={},
        )
        assert hub.text.startswith(copy["hub"])
        card = _opponent_request_result_message(
            delivery_id="result",
            telegram_user_id=49_540,
            locale=locale,
            screen_revision=1,
            result=result,
        )
        assert copy["date"] in card.text
        assert copy["venue"] in card.text
        assert copy["criterion"] in card.text
        assert copy["level"] in card.text
        assert copy["label"] in card.text
        assert copy["posted"] in card.text
        assert copy["contact"] in card.text
        assert copy["invitation"] in card.text
        assert "2026-08-20" not in card.text
        assert "venue_provision" not in card.text


def test_opponent_request_is_symmetric_and_requires_explicit_request_fact() -> None:
    results = evaluate_opponent_search(
        _search(),
        {},
        (
            _opportunity(opportunity_id="symmetric", venue="team_has_venue"),
            _opportunity(
                opportunity_id="not-a-request",
                venue="team_has_venue",
                explicit_request=False,
            ),
            _opportunity(
                opportunity_id="open-match",
                venue="team_has_venue",
                opportunity_type="open_match",
            ),
        ),
    )
    assert [result.result_id.rsplit(":", 1)[-1] for result in results] == ["symmetric"]
    assert dict(results[0].card_facts)["opponent_request"] == "true"


def test_classifier_publication_candidate_requires_event_time_and_request_fact() -> (
    None
):
    body = (
        "Our team seeks an opponent on 2026-08-20 at Saint Petersburg. "
        "Contact @opponent_contact"
    )
    candidate: dict[str, ClassifierJsonValue] = {
        "candidate_key": "opponent-1",
        "opportunity_type": "opponent_request",
        "evidence": {
            "opportunity": "seeks an opponent",
            "event_time": "2026-08-20",
            "location": "at Saint Petersburg",
            "opponent_request": "seeks an opponent",
        },
        "location": {
            "mention": "Saint Petersburg",
            "place_id": "city:ru:spb",
            "country_id": "country:ru",
            "city_id": "city:ru:spb",
        },
        "event_time": {
            "start_local_date": "2026-08-20",
            "end_local_date": "2026-08-20",
            "iana_timezone": "Europe/Moscow",
        },
        "opponent_request": True,
        "response_routes": [
            {
                "kind": "explicit_telegram_username",
                "value": "@opponent_contact",
                "evidence": "Contact @opponent_contact",
            }
        ],
    }
    accepted: dict[str, ClassifierJsonValue] = {
        "schema_version": "source-message-classification-v1",
        "disposition": "accepted",
        "candidates": [candidate],
    }
    assert classifier_output_is_schema_valid(accepted, body=body)

    missing_event_time = {
        **accepted,
        "candidates": [
            {key: value for key, value in candidate.items() if key != "event_time"}
        ],
    }
    assert not classifier_output_is_schema_valid(
        cast(dict[str, ClassifierJsonValue], missing_event_time), body=body
    )

    missing_request = {
        **accepted,
        "candidates": [{**candidate, "opponent_request": False}],
    }
    assert not classifier_output_is_schema_valid(
        cast(dict[str, ClassifierJsonValue], missing_request), body=body
    )
