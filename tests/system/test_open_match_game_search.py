"""Open Match discovery through the approved PostgreSQL-backed system seam."""

# ruff: noqa: RUF001 -- reviewed multilingual product copy is intentional.

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime

import pytest

from modules.contracts import (
    ContractName,
    FailureCode,
    JsonValue,
    OperatorAlert,
    RuntimeRole,
)
from modules.domain import (
    ConversationStage,
    DateInterpretation,
    DateInterpretationResolution,
    GeographicType,
    LocationCandidate,
    LocationInterpretation,
    LocationResolution,
    SourceEventKind,
    TelegramChannelCheckpoint,
    TelegramPeerIdentity,
    TelegramPeerKind,
)
from modules.ports import ClassifierAdapterResult
from modules.testkit import (
    AcceptanceSpine,
    ControlledDateInterpretationAdapter,
    ControlledLocationResolverAdapter,
    ControlledModelAdapter,
    ControlledTelegramDeliveryAdapter,
    ControlledTelegramIngestionAdapter,
    ControlledTimezoneDataAdapter,
    FrozenClock,
    boot_acceptance_spine,
)


def test_copy_permitted_source_message_becomes_one_open_match_result_card() -> None:
    telegram_ingestion = ControlledTelegramIngestionAdapter()
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    classifier = ControlledModelAdapter()
    resolver = ControlledLocationResolverAdapter()
    dates = ControlledDateInterpretationAdapter()
    timezones = ControlledTimezoneDataAdapter()
    clock = FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    administrator_id = 49_001
    bot_user_id = 49_002
    source_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_900_100,
    )
    body = (
        "20 августа 2026 в 19:00 играем 7x7 на Петроградской. "
        "Нужны вратарь и защитник, одно место, средний уровень, искусственный газон, "
        "на улице, участие 900 рублей. Пишите @open_match_contact"
    )
    telegram_ingestion.allow_public_username(
        address="@synthetic_open_match_source",
        identity=source_identity,
        transport_boundary="channel-pts:4900",
    )
    classifier.return_for(
        body=body,
        result=ClassifierAdapterResult(
            output={
                "schema_version": "source-message-classification-v1",
                "disposition": "accepted",
                "candidates": [
                    {
                        "candidate_key": "open-place",
                        "opportunity_type": "open_match",
                        "evidence": {
                            "opportunity": "Нужны вратарь и защитник, одно место",
                            "event_time": "20 августа 2026 в 19:00",
                            "location": "на Петроградской",
                            "open_places": "одно место",
                            "team_formats": "7x7",
                            "positions": "вратарь и защитник",
                            "playing_levels": "средний уровень",
                            "venue_settings": "на улице",
                            "playing_surfaces": "искусственный газон",
                            "payment": "900 рублей",
                        },
                        "location": {
                            "mention": "на Петроградской",
                            "place_id": "station:ru:spb:petrogradskaya",
                            "country_id": "country:ru",
                            "city_id": "city:ru:saint-petersburg",
                        },
                        "event_time": {
                            "start_local_date": "2026-08-20",
                            "end_local_date": "2026-08-20",
                            "exact_local_time": "19:00",
                            "iana_timezone": "Europe/Moscow",
                        },
                        "open_places": 1,
                        "team_formats": ["7x7"],
                        "positions": ["goalkeeper", "defender"],
                        "playing_levels": ["average"],
                        "venue_settings": ["outdoor"],
                        "playing_surfaces": ["artificial_turf"],
                        "payment": "paid",
                        "response_routes": [
                            {
                                "kind": "explicit_telegram_username",
                                "value": "@open_match_contact",
                                "evidence": "@open_match_contact",
                            }
                        ],
                    }
                ],
            },
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="controlled-offline",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=7,
            input_tokens=120,
            output_tokens=80,
        ),
    )
    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="на Петроградской",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    places=(
                        LocationCandidate(
                            place_id="station:ru:spb:petrogradskaya",
                            display_name="Петроградская",
                            geographic_type=GeographicType.STATION,
                            country_id="country:ru",
                            city_id="city:ru:saint-petersburg",
                            verified_parent_ids=(
                                "country:ru",
                                "city:ru:saint-petersburg",
                            ),
                            parent_display_names=("Россия", "Saint Petersburg"),
                            iana_timezone="Europe/Moscow",
                            resolver_version="controlled-resolver-v1",
                            glossary_version="location-glossary-v1",
                            localized_display_names=(
                                ("en", "Petrogradskaya"),
                                ("ru", "Петроградская"),
                            ),
                        ),
                    ),
                    glossary_version="location-glossary-v1",
                ),
            ),
        ),
    )
    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="в Санкт-Петербурге",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    places=(
                        LocationCandidate(
                            place_id="city:ru:saint-petersburg",
                            display_name="Санкт-Петербург",
                            geographic_type=GeographicType.CITY,
                            country_id="country:ru",
                            city_id="city:ru:saint-petersburg",
                            verified_parent_ids=("country:ru",),
                            parent_display_names=("Россия",),
                            iana_timezone="Europe/Moscow",
                            resolver_version="controlled-resolver-v1",
                            glossary_version="location-glossary-v1",
                            localized_display_names=(
                                ("en", "Saint Petersburg"),
                                ("ru", "Санкт-Петербург"),
                            ),
                        ),
                    ),
                    glossary_version="location-glossary-v1",
                ),
            ),
        ),
    )
    dates.return_for(
        text="20 August",
        resolution=DateInterpretationResolution(
            interpretations=(
                DateInterpretation(
                    start_local_date=date(2026, 8, 20),
                    end_local_date=date(2026, 8, 20),
                    iana_timezone="Europe/Moscow",
                ),
            )
        ),
    )
    timezones.add_source(
        version="controlled-tzdb-v1",
        timezones=("Europe/Moscow",),
    )
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telegram_ingestion,
        telegram_delivery=telegram_delivery,
        model=classifier,
        location_resolver=resolver,
        date_interpretation=dates,
        timezone_data=timezones,
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        administrator_id=administrator_id,
    )
    system.configure_source_chat_classifier_context(
        identity=source_identity,
        registry_generation=1,
        iana_timezone="Europe/Moscow",
        country_id="country:ru",
        city_id="city:ru:saint-petersburg",
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4900),
        to_checkpoint=TelegramChannelCheckpoint(pts=4901),
        source_event_id="source-event:open-match:1",
        telegram_message_id=101,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=body,
        event_time=datetime(2026, 8, 18, 9, 5, tzinfo=UTC),
    )

    assert system.channel_ingestion_checkpoint(
        identity=source_identity,
        registry_generation=1,
    ) == TelegramChannelCheckpoint(pts=4900)
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()

    request = classifier.requests[0]
    assert request.source_event_time == "2026-08-18T09:05:00+00:00"
    assert request.context_bundle_version == "primary-classifier-context-v1"
    assert request.source_chat_reference == "source-chat:channel:4900100"
    assert request.source_chat_timezone == "Europe/Moscow"
    assert request.source_chat_geography == {
        "country_id": "country:ru",
        "city_id": "city:ru:saint-petersburg",
    }
    assert request.bounded_metadata == {
        "message_language": None,
        "attachment_types": [],
        "source_author_dm_url": None,
        "reply_route_url": None,
        "source_message_url": None,
        "source_message_reply_capable": False,
    }

    assert {
        query.locale for query in resolver.queries if query.text == "на Петроградской"
    } == {"en", "es", "fr", "ru"}

    attempts = system.classification_attempts()
    assert len(attempts) == 1
    assert attempts[0].requested_model == "gpt-5.6-sol"
    assert attempts[0].effective_model == "gpt-5.6-sol"
    assert attempts[0].requested_reasoning_effort == "high"
    assert attempts[0].effective_reasoning_effort == "high"
    assert attempts[0].prompt_version == "open-match-primary-v1"
    assert attempts[0].schema_version == "source-message-classification-v1"
    assert attempts[0].glossary_version == "football-opportunity-glossary-v1"
    assert attempts[0].context_policy_version == "classifier-context-v1"
    assert attempts[0].routing_policy_version == "classifier-routing-v1"
    assert attempts[0].codex_version == "controlled-offline"
    assert attempts[0].adapter_kind == "controlled_recording"
    assert attempts[0].adapter_version == "classifier-recording-v1"
    assert attempts[0].pass_number == 1
    assert attempts[0].attempt_number == 1
    assert len(attempts[0].input_manifest_hash) == 64
    assert attempts[0].evidence_references
    assert all(
        reference.startswith("sha256:") for reference in attempts[0].evidence_references
    )
    assert attempts[0].disposition == "accepted"
    assert attempts[0].status == "succeeded"
    opportunities = system.opportunities()
    assert len(opportunities) == 1
    assert opportunities[0].opportunity_type == "open_match"
    assert opportunities[0].opportunity_revision_id.endswith(":revision:1")
    assert opportunities[0].publication_state == "active"
    assert opportunities[0].response_route.value == "@open_match_contact"

    _advance_to_complete_game_search(system, bot_user_id=bot_user_id)
    system.submit_search(
        update_id="submit-open-match-search",
        telegram_user_id=bot_user_id,
    )
    system.process_searches_until_idle()

    completed = system.completed_searches(bot_user_id)
    assert len(completed) == 1
    results = system.results(completed[0].completed_search_id)
    assert len(results) == 1
    revision_inputs = system.completed_search_opportunity_revision_inputs(
        completed[0].completed_search_id
    )
    assert len(revision_inputs) == 1
    assert revision_inputs[0]["opportunity_revision_id"] == (
        opportunities[0].opportunity_revision_id
    )
    persisted_facts = revision_inputs[0]["accepted_facts"]
    assert isinstance(persisted_facts, dict)
    assert persisted_facts["open_places"] == 1
    assert results[0].result_class == "confirmed_match"
    context = system.active_result_context(bot_user_id)
    assert context.current_result_id == results[0].result_id
    assert context.absolute_position == 1
    card = telegram_delivery.messages[-1]
    assert card.text == (
        "⚽ Open Match\n"
        "20 August 2026, 19:00\n"
        "Saint Petersburg, Petrogradskaya\n"
        "1 open place\n\n"
        "Matches: date and city.\n\n"
        "Additional: Team format: 7x7 · Positions: Goalkeeper, Defender · "
        "Playing levels: Average · Venue type: Outdoor · "
        "Playing surface: Artificial turf · Payment: Paid\n\n"
        "Posted: 18 August 2026 at 12:05\n"
        "Contact: @open_match_contact\n\n"
        "Questions? Message me. I can explain the card or help refine your search."
    )
    assert body not in card.text
    assert card.text.count("@open_match_contact") == 1
    assert card.reply_button == "Menu"

    russian_user_id = bot_user_id + 1
    _advance_to_complete_game_search(
        system,
        bot_user_id=russian_user_id,
        locale="ru",
    )
    system.open_game_search_details(
        update_id="open-confirmed-detail-search",
        telegram_user_id=russian_user_id,
    )
    details_hub = telegram_delivery.messages[-1]
    assert details_hub.text.startswith("Можно выбрать следующие настройки:")
    assert len(details_hub.button_rows) == 9
    system.open_game_search_detail(
        update_id="open-time-detail-search",
        telegram_user_id=russian_user_id,
        detail_key="times",
    )
    time_menu = telegram_delivery.messages[-1]
    assert time_menu.text == "🕒 В какое время?"
    assert [len(row) for row in time_menu.button_rows] == [1, 2, 2, 1, 1]
    assert time_menu.button_rows[-1][0][0] == "⬅️ Назад"
    time_submenu_draft = system.discovery_draft(russian_user_id)
    with pytest.raises(RuntimeError, match="exact-time prompt"):
        system.submit_game_search_exact_time_text(
            update_id="reject-exact-time-outside-prompt",
            telegram_user_id=russian_user_id,
            text="19:00",
        )
    assert system.discovery_draft(russian_user_id) == time_submenu_draft
    system.open_game_search_exact_time(
        update_id="open-exact-time-search",
        telegram_user_id=russian_user_id,
    )
    assert system.discovery_draft(russian_user_id).game_search_exact_time_prompt is True
    assert telegram_delivery.messages[-1].text == (
        "Введите точное местное время выбранного города."
    )
    assert telegram_delivery.messages[-1].button_rows[-1][0][0] == "⬅️ Назад"
    system.back_from_game_search_detail(
        update_id="back-exact-time-search",
        telegram_user_id=russian_user_id,
    )
    assert telegram_delivery.messages[-1].text == "🕒 В какое время?"
    system.open_game_search_exact_time(
        update_id="reopen-exact-time-search",
        telegram_user_id=russian_user_id,
    )
    system.submit_game_search_exact_time_text(
        update_id="submit-exact-time-search",
        telegram_user_id=russian_user_id,
        text="19:00",
    )
    assert dict(system.discovery_draft(russian_user_id).game_search_details) == {
        "times": ("19:00",)
    }
    system.open_game_search_detail(
        update_id="reopen-time-to-clear-search",
        telegram_user_id=russian_user_id,
        detail_key="times",
    )
    system.select_game_search_time(
        update_id="clear-time-detail-search",
        telegram_user_id=russian_user_id,
        value=None,
    )
    for detail_key, heading, row_sizes in (
        ("team_formats", "👥 Выберите форматы команд.", [3, 3, 2, 1]),
        (
            "playing_levels",
            "⚽ Выберите уровни игры.",
            [2, 2, 2, 2, 1, 1],
        ),
        ("venue_settings", "🏟 Выберите тип площадки.", [1, 1, 1, 1, 1]),
        (
            "playing_surfaces",
            "🌱 Выберите покрытие.",
            [1, 1, 1, 1, 1, 1],
        ),
        ("payment", "💳 Выберите тип оплаты.", [2, 1, 1]),
    ):
        system.open_game_search_detail(
            update_id=f"open-{detail_key}-layout-search",
            telegram_user_id=russian_user_id,
            detail_key=detail_key,
        )
        assert telegram_delivery.messages[-1].text == heading
        assert [
            len(row) for row in telegram_delivery.messages[-1].button_rows
        ] == row_sizes
        system.back_from_game_search_detail(
            update_id=f"back-{detail_key}-layout-search",
            telegram_user_id=russian_user_id,
        )
    system.open_game_search_detail(
        update_id="open-position-detail-search",
        telegram_user_id=russian_user_id,
        detail_key="positions",
    )
    assert telegram_delivery.messages[-1].text == "🥅 Какие позиции?"
    assert [len(row) for row in telegram_delivery.messages[-1].button_rows] == [
        2,
        2,
        1,
        1,
    ]
    system.toggle_game_search_detail_value(
        update_id="select-confirmed-detail-search",
        telegram_user_id=russian_user_id,
        value="defender",
    )
    draft_before_done = system.discovery_draft(russian_user_id)
    assert draft_before_done.game_search_details == ()
    assert draft_before_done.game_search_detail_draft == ("defender",)
    system.commit_game_search_detail(
        update_id="commit-confirmed-detail-search",
        telegram_user_id=russian_user_id,
    )
    assert dict(system.discovery_draft(russian_user_id).game_search_details) == {
        "positions": ("defender",)
    }
    system.open_game_search_detail(
        update_id="reopen-position-detail-search",
        telegram_user_id=russian_user_id,
        detail_key="positions",
    )
    system.toggle_game_search_detail_value(
        update_id="toggle-discarded-detail-search",
        telegram_user_id=russian_user_id,
        value="goalkeeper",
    )
    system.back_from_game_search_detail(
        update_id="discard-position-detail-search",
        telegram_user_id=russian_user_id,
    )
    assert dict(system.discovery_draft(russian_user_id).game_search_details) == {
        "positions": ("defender",)
    }
    system.submit_search(
        update_id="submit-confirmed-detail-search",
        telegram_user_id=russian_user_id,
    )
    system.process_searches_until_idle()
    russian_search = system.completed_searches(russian_user_id)[0]
    assert dict(russian_search.game_search_details) == {"positions": ("defender",)}
    assert system.results(russian_search.completed_search_id)[0].result_class == (
        "confirmed_match"
    )
    russian_card = telegram_delivery.messages[-1]
    assert russian_card.text.startswith("⚽ Открытая игра")
    assert "Подходит: дата и город, позиция." in russian_card.text
    assert "Контакт: @open_match_contact" in russian_card.text

    conflicting_user_id = bot_user_id + 2
    _advance_to_complete_game_search(system, bot_user_id=conflicting_user_id)
    system.submit_search(
        update_id="submit-conflicting-detail-search",
        telegram_user_id=conflicting_user_id,
        game_search_details={"positions": ["forward"]},
    )
    system.process_searches_until_idle()
    conflicting_search = system.completed_searches(conflicting_user_id)[0]
    assert system.results(conflicting_search.completed_search_id) == ()

    minimal_body = (
        "20–22 августа 2026 играем на Петроградской, есть одно место. "
        "Пишите @minimal_match_contact или @backup_contact"
    )
    classifier.return_for(
        body=minimal_body,
        result=ClassifierAdapterResult(
            output={
                "schema_version": "source-message-classification-v1",
                "disposition": "accepted",
                "candidates": [
                    {
                        "candidate_key": "open-place",
                        "opportunity_type": "open_match",
                        "evidence": {
                            "opportunity": "есть одно место",
                            "event_time": "20–22 августа 2026",
                            "location": "на Петроградской",
                            "open_places": "одно место",
                        },
                        "location": {
                            "mention": "на Петроградской",
                            "place_id": "station:ru:spb:petrogradskaya",
                            "country_id": "country:ru",
                            "city_id": "city:ru:saint-petersburg",
                        },
                        "event_time": {
                            "start_local_date": "2026-08-20",
                            "end_local_date": "2026-08-22",
                            "iana_timezone": "Europe/Moscow",
                        },
                        "open_places": 1,
                        "response_routes": [
                            {
                                "kind": "explicit_telegram_username",
                                "value": "@backup_contact",
                                "evidence": "@backup_contact",
                            },
                            {
                                "kind": "explicit_telegram_username",
                                "value": "@minimal_match_contact",
                                "evidence": "@minimal_match_contact",
                            },
                        ],
                    }
                ],
            },
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="controlled-offline",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=5,
            input_tokens=60,
            output_tokens=40,
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4901),
        to_checkpoint=TelegramChannelCheckpoint(pts=4902),
        source_event_id="source-event:open-match:2",
        telegram_message_id=1000,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=minimal_body,
        event_time=datetime(2026, 8, 18, 9, 6, tzinfo=UTC),
    )
    clock.advance_to(datetime(2026, 8, 18, 9, 6, tzinfo=UTC))
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    minimal_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id.endswith(":1000:revision:1")
    )
    assert minimal_opportunity.response_route.value == "@minimal_match_contact"

    possible_user_id = bot_user_id + 3
    _advance_to_complete_game_search(system, bot_user_id=possible_user_id)
    system.submit_search(
        update_id="submit-possible-detail-search",
        telegram_user_id=possible_user_id,
        game_search_details={"positions": ["defender"]},
    )
    system.process_searches_until_idle()
    possible_search = system.completed_searches(possible_user_id)[0]
    possible_results = system.results(possible_search.completed_search_id)
    assert [result.result_class for result in possible_results] == [
        "confirmed_match",
        "possible_match",
    ]
    minimal_result = next(
        result
        for result in possible_results
        if dict(result.card_facts)["opportunity_id"]
        == minimal_opportunity.opportunity_id
    )
    assert dict(minimal_result.card_facts)["response_route_value"] == (
        "@minimal_match_contact"
    )
    assert "@backup_contact" not in json.dumps(dict(minimal_result.card_facts))

    possible_only_user_id = bot_user_id + 4
    _advance_to_complete_game_search(system, bot_user_id=possible_only_user_id)
    system.submit_search(
        update_id="submit-possible-only-search",
        telegram_user_id=possible_only_user_id,
        game_search_details={"payment": ["free"]},
    )
    system.process_searches_until_idle()
    possible_only_search = system.completed_searches(possible_only_user_id)[0]
    possible_only_results = system.results(possible_only_search.completed_search_id)
    assert [result.result_class for result in possible_only_results] == [
        "possible_match"
    ]
    assert "No exact match was found." in telegram_delivery.messages[-1].text
    assert "Needs clarification: payment." in telegram_delivery.messages[-1].text
    assert "20–22 August 2026" in telegram_delivery.messages[-1].text

    invalid_provenance_body = (
        "20 августа 2026 играем на Петроградской, есть одно место. "
        "Пишите @invalid_provenance"
    )
    classifier.return_for(
        body=invalid_provenance_body,
        result=ClassifierAdapterResult(
            output={
                "schema_version": "source-message-classification-v1",
                "disposition": "accepted",
                "candidates": [
                    {
                        "candidate_key": "open-place",
                        "opportunity_type": "open_match",
                        "evidence": {
                            "opportunity": "есть одно место",
                            "event_time": "20 августа 2026",
                            "location": "на Петроградской",
                            "open_places": "одно место",
                        },
                        "location": {
                            "mention": "на Петроградской",
                            "place_id": "station:ru:spb:petrogradskaya",
                            "country_id": "country:ru",
                            "city_id": "city:ru:saint-petersburg",
                        },
                        "event_time": {
                            "start_local_date": "2026-08-20",
                            "end_local_date": "2026-08-20",
                            "iana_timezone": "Europe/Moscow",
                        },
                        "open_places": 1,
                        "response_routes": [
                            {
                                "kind": "explicit_telegram_username",
                                "value": "@invalid_provenance",
                                "evidence": "@invalid_provenance",
                            }
                        ],
                    }
                ],
            },
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=3,
            input_tokens=40,
            output_tokens=30,
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4902),
        to_checkpoint=TelegramChannelCheckpoint(pts=4903),
        source_event_id="source-event:open-match:invalid-provenance",
        telegram_message_id=1001,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=invalid_provenance_body,
        event_time=datetime(2026, 8, 18, 9, 7, tzinfo=UTC),
    )
    clock.advance_to(datetime(2026, 8, 18, 9, 7, tzinfo=UTC))
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    opportunity_count = len(system.opportunities())
    system.process_opportunities_until_idle()
    assert system.classification_attempts()[-1].status == "failed"
    assert len(system.opportunities()) == opportunity_count

    citywide_body = (
        "20 августа 2026 играем в Санкт-Петербурге, есть одно место. "
        "Пишите @citywide_match"
    )
    classifier.return_for(
        body=citywide_body,
        result=ClassifierAdapterResult(
            output={
                "schema_version": "source-message-classification-v1",
                "disposition": "accepted",
                "candidates": [
                    {
                        "candidate_key": "open-place",
                        "opportunity_type": "open_match",
                        "evidence": {
                            "opportunity": "есть одно место",
                            "event_time": "20 августа 2026",
                            "location": "в Санкт-Петербурге",
                            "open_places": "одно место",
                        },
                        "location": {
                            "mention": "в Санкт-Петербурге",
                            "place_id": "city:ru:saint-petersburg",
                            "country_id": "country:ru",
                            "city_id": "city:ru:saint-petersburg",
                        },
                        "event_time": {
                            "start_local_date": "2026-08-20",
                            "end_local_date": "2026-08-20",
                            "iana_timezone": "Europe/Moscow",
                        },
                        "open_places": 1,
                        "response_routes": [
                            {
                                "kind": "explicit_telegram_username",
                                "value": "@citywide_match",
                                "evidence": "@citywide_match",
                            }
                        ],
                    }
                ],
            },
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="controlled-offline",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=3,
            input_tokens=40,
            output_tokens=30,
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4903),
        to_checkpoint=TelegramChannelCheckpoint(pts=4904),
        source_event_id="source-event:open-match:citywide",
        telegram_message_id=1002,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=citywide_body,
        event_time=datetime(2026, 8, 18, 9, 8, tzinfo=UTC),
    )
    clock.advance_to(datetime(2026, 8, 18, 9, 8, tzinfo=UTC))
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    assert any(
        opportunity.source_message_revision_id.endswith(":1002:revision:1")
        for opportunity in system.opportunities()
    )

    broad_area_user_id = bot_user_id + 5
    _advance_to_complete_game_search(
        system,
        bot_user_id=broad_area_user_id,
        area_text="Near Komendantsky metro and in Primorsky District",
    )
    assert (
        system.discovery_draft(broad_area_user_id).stage is ConversationStage.POST_CORE
    )
    system.submit_search(
        update_id="submit-broad-area-search",
        telegram_user_id=broad_area_user_id,
        game_search_details={"payment": ["free"]},
    )
    system.process_searches_until_idle()
    broad_area_search = system.completed_searches(broad_area_user_id)[0]
    citywide_result = next(
        result
        for result in system.results(broad_area_search.completed_search_id)
        if ":1002:" in dict(result.card_facts)["opportunity_id"]
    )
    assert citywide_result.result_class == "possible_match"
    assert (
        json.loads(dict(citywide_result.card_facts)["match_states"])["search_area"]
        == "unknown"
    )
    concurrent_user_id = bot_user_id + 6
    _advance_to_complete_game_search(system, bot_user_id=concurrent_user_id)
    system.inject_projection_change_during_next_search(
        opportunity_id=opportunities[0].opportunity_id,
        opportunity_revision_id=(
            f"{opportunities[0].opportunity_id}:revision:concurrent"
        ),
        open_places=99,
    )
    system.submit_search(
        update_id="submit-concurrent-projection-search",
        telegram_user_id=concurrent_user_id,
    )
    system.process_searches_until_idle()
    concurrent_search = system.completed_searches(concurrent_user_id)[0]
    concurrent_inputs = system.completed_search_opportunity_revision_inputs(
        concurrent_search.completed_search_id
    )
    original_input = next(
        item
        for item in concurrent_inputs
        if item["opportunity_id"] == opportunities[0].opportunity_id
    )
    assert original_input["opportunity_revision_id"] == (
        opportunities[0].opportunity_revision_id
    )
    original_result = next(
        result
        for result in system.results(concurrent_search.completed_search_id)
        if dict(result.card_facts)["opportunity_id"] == opportunities[0].opportunity_id
    )
    assert dict(original_result.card_facts)["open_places"] == "1"
    system.restart(RuntimeRole.RECOMMENDATION)
    system.process_searches_until_idle()
    assert (
        system.completed_search_opportunity_revision_inputs(
            concurrent_search.completed_search_id
        )
        == concurrent_inputs
    )
    relative_body = (
        "Матч завтра на Петроградской, есть одно место. Пишите @relative_match_contact"
    )
    classifier.return_for(
        body=relative_body,
        result=ClassifierAdapterResult(
            output={
                "schema_version": "source-message-classification-v1",
                "disposition": "accepted",
                "candidates": [
                    {
                        "candidate_key": "relative-open-place",
                        "opportunity_type": "open_match",
                        "evidence": {
                            "opportunity": "есть одно место",
                            "event_time": "Матч завтра",
                            "location": "на Петроградской",
                            "open_places": "одно место",
                        },
                        "location": {
                            "mention": "на Петроградской",
                            "place_id": "station:ru:spb:petrogradskaya",
                            "country_id": "country:ru",
                            "city_id": "city:ru:saint-petersburg",
                        },
                        "event_time": {
                            "start_local_date": "2026-08-19",
                            "end_local_date": "2026-08-19",
                            "iana_timezone": "Europe/Moscow",
                        },
                        "open_places": 1,
                        "response_routes": [
                            {
                                "kind": "explicit_telegram_username",
                                "value": "@relative_match_contact",
                                "evidence": "@relative_match_contact",
                            }
                        ],
                    }
                ],
            },
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="controlled-offline",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=3,
            input_tokens=30,
            output_tokens=20,
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4904),
        to_checkpoint=TelegramChannelCheckpoint(pts=4905),
        source_event_id="source-event:open-match:relative",
        telegram_message_id=1003,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=relative_body,
        event_time=datetime(2026, 8, 18, 17, 30, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    relative_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id.endswith(":1003:revision:1")
    )
    assert relative_opportunity.publication_state == "active"
    wrong_date_body = (
        "20 августа 2026 на Петроградской нужны два игрока. Пишите @wrong_date_contact"
    )
    classifier.return_for(
        body=wrong_date_body,
        result=ClassifierAdapterResult(
            output={
                "schema_version": "source-message-classification-v1",
                "disposition": "accepted",
                "candidates": [
                    {
                        "candidate_key": "wrong-normalized-date",
                        "opportunity_type": "open_match",
                        "evidence": {
                            "opportunity": "нужны два игрока",
                            "event_time": "20 августа 2026",
                            "location": "на Петроградской",
                            "open_places": "два игрока",
                        },
                        "location": {
                            "mention": "на Петроградской",
                            "place_id": "station:ru:spb:petrogradskaya",
                            "country_id": "country:ru",
                            "city_id": "city:ru:saint-petersburg",
                        },
                        "event_time": {
                            "start_local_date": "2026-08-02",
                            "end_local_date": "2026-08-02",
                            "iana_timezone": "Europe/Moscow",
                        },
                        "open_places": 2,
                        "response_routes": [
                            {
                                "kind": "explicit_telegram_username",
                                "value": "@wrong_date_contact",
                                "evidence": "@wrong_date_contact",
                            }
                        ],
                    }
                ],
            },
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="controlled-offline",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=3,
            input_tokens=30,
            output_tokens=20,
        ),
    )
    before_wrong_date = len(system.opportunities())
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4905),
        to_checkpoint=TelegramChannelCheckpoint(pts=4906),
        source_event_id="source-event:open-match:wrong-date",
        telegram_message_id=1004,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=wrong_date_body,
        event_time=datetime(2026, 8, 18, 17, 31, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    assert len(system.opportunities()) == before_wrong_date
    wrong_date_user_id = bot_user_id + 7
    _advance_to_complete_game_search(system, bot_user_id=wrong_date_user_id)
    system.submit_search(
        update_id="submit-after-wrong-date",
        telegram_user_id=wrong_date_user_id,
    )
    system.process_searches_until_idle()
    wrong_date_search = system.completed_searches(wrong_date_user_id)[0]
    assert all(
        ":1004:" not in dict(result.card_facts)["opportunity_id"]
        for result in system.results(wrong_date_search.completed_search_id)
    )
    phone_body = (
        "20 августа 2026 на Петроградской нужен один игрок. Звоните +7 921 555-01-49"
    )
    classifier.return_for(
        body=phone_body,
        result=_minimal_classifier_result(
            candidate_key="phone-route",
            body=phone_body,
            response_routes=[
                {
                    "kind": "explicit_phone",
                    "value": "+7 921 555-01-49",
                    "evidence": "+7 921 555-01-49",
                }
            ],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4906),
        to_checkpoint=TelegramChannelCheckpoint(pts=4907),
        source_event_id="source-event:open-match:phone-route",
        telegram_message_id=1005,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=phone_body,
        event_time=datetime(2026, 8, 18, 17, 32, tzinfo=UTC),
        source_author_dm_url="https://t.me/unused_source_author_49",
        reply_route_url="https://t.me/unused_source_chat/1005?comment=5",
        source_message_url="https://t.me/unused_source_chat/1005",
        source_message_reply_capable=True,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    phone_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id.endswith(":1005:revision:1")
    )
    assert phone_opportunity.response_route.kind == "explicit_phone"
    assert phone_opportunity.response_route.value == "+7 921 555-01-49"
    assert "unused_source" not in phone_opportunity.response_route.value
    url_body = (
        "20 августа 2026 на Петроградской нужен один игрок. "
        "Форма https://example.test/open-match/49"
    )
    classifier.return_for(
        body=url_body,
        result=_minimal_classifier_result(
            candidate_key="url-route",
            body=url_body,
            response_routes=[
                {
                    "kind": "explicit_url",
                    "value": "https://example.test/open-match/49",
                    "evidence": "https://example.test/open-match/49",
                }
            ],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4907),
        to_checkpoint=TelegramChannelCheckpoint(pts=4908),
        source_event_id="source-event:open-match:url-route",
        telegram_message_id=1006,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=url_body,
        event_time=datetime(2026, 8, 18, 17, 33, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    url_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id.endswith(":1006:revision:1")
    )
    assert url_opportunity.response_route.kind == "explicit_url"
    assert url_opportunity.response_route.value == "https://example.test/open-match/49"
    fallback_body = "20 августа 2026 на Петроградской нужен один игрок."
    classifier.return_for(
        body=fallback_body,
        result=_minimal_classifier_result(
            candidate_key="author-dm-route",
            body=fallback_body,
            response_routes=[],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4908),
        to_checkpoint=TelegramChannelCheckpoint(pts=4909),
        source_event_id="source-event:open-match:author-dm-route",
        telegram_message_id=1007,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=fallback_body,
        event_time=datetime(2026, 8, 18, 17, 34, tzinfo=UTC),
        source_author_dm_url="https://t.me/source_author_49",
        reply_route_url="https://t.me/synthetic_open_match_source/1007?comment=7",
        source_message_url="https://t.me/synthetic_open_match_source/1007",
        source_message_reply_capable=True,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    dm_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id.endswith(":1007:revision:1")
    )
    assert dm_opportunity.response_route.kind == "direct_message"
    assert dm_opportunity.response_route.value == "https://t.me/source_author_49"
    assert "synthetic_open_match_source" not in dm_opportunity.response_route.value
    classifier.return_for(
        body=fallback_body,
        result=_minimal_classifier_result(
            candidate_key="reply-route",
            body=fallback_body,
            response_routes=[],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4909),
        to_checkpoint=TelegramChannelCheckpoint(pts=4910),
        source_event_id="source-event:open-match:reply-route",
        telegram_message_id=1008,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=fallback_body,
        event_time=datetime(2026, 8, 18, 17, 35, tzinfo=UTC),
        reply_route_url="https://t.me/synthetic_open_match_source/1008?comment=8",
        source_message_url="https://t.me/synthetic_open_match_source/1008",
        source_message_reply_capable=True,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    reply_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id.endswith(":1008:revision:1")
    )
    assert reply_opportunity.response_route.kind == "reply_thread"
    assert reply_opportunity.response_route.value.endswith("/1008?comment=8")
    classifier.return_for(
        body=fallback_body,
        result=_minimal_classifier_result(
            candidate_key="source-message-route",
            body=fallback_body,
            response_routes=[],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4910),
        to_checkpoint=TelegramChannelCheckpoint(pts=4911),
        source_event_id="source-event:open-match:source-message-route",
        telegram_message_id=1009,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=fallback_body,
        event_time=datetime(2026, 8, 18, 17, 36, tzinfo=UTC),
        source_message_url="https://t.me/synthetic_open_match_source/1009",
        source_message_reply_capable=True,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    source_message_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id.endswith(":1009:revision:1")
    )
    assert source_message_opportunity.response_route.kind == "source_message"
    assert source_message_opportunity.response_route.value.endswith("/1009")
    day_part_body = (
        "20 августа 2026 вечером на Петроградской нужен один игрок. "
        "Пишите @day_part_contact"
    )
    classifier.return_for(
        body=day_part_body,
        result=_minimal_classifier_result(
            candidate_key="day-part",
            body=day_part_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": "@day_part_contact",
                    "evidence": "@day_part_contact",
                }
            ],
            event_time_evidence="20 августа 2026 вечером",
            day_part="evening",
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4911),
        to_checkpoint=TelegramChannelCheckpoint(pts=4912),
        source_event_id="source-event:open-match:day-part",
        telegram_message_id=1010,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=day_part_body,
        event_time=datetime(2026, 8, 18, 17, 37, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    day_part_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id.endswith(":1010:revision:1")
    )
    day_part_user_id = bot_user_id + 8
    _advance_to_complete_game_search(system, bot_user_id=day_part_user_id)
    system.submit_search(
        update_id="submit-day-part-search",
        telegram_user_id=day_part_user_id,
        game_search_details={"times": ["evening"]},
    )
    system.process_searches_until_idle()
    day_part_search = system.completed_searches(day_part_user_id)[0]
    day_part_result = next(
        result
        for result in system.results(day_part_search.completed_search_id)
        if dict(result.card_facts)["opportunity_id"]
        == day_part_opportunity.opportunity_id
    )
    assert json.loads(dict(day_part_result.card_facts)["match_states"])["times"] == (
        "confirmed"
    )
    assert dict(day_part_result.card_facts)["day_part"] == "evening"
    exact_against_day_part_user_id = bot_user_id + 9
    _advance_to_complete_game_search(
        system,
        bot_user_id=exact_against_day_part_user_id,
    )
    system.submit_search(
        update_id="submit-exact-against-day-part-search",
        telegram_user_id=exact_against_day_part_user_id,
        game_search_details={"times": ["19:00"]},
    )
    system.process_searches_until_idle()
    exact_against_day_part_search = system.completed_searches(
        exact_against_day_part_user_id
    )[0]
    exact_against_day_part_result = next(
        result
        for result in system.results(exact_against_day_part_search.completed_search_id)
        if dict(result.card_facts)["opportunity_id"]
        == day_part_opportunity.opportunity_id
    )
    assert exact_against_day_part_result.result_class == "possible_match"
    assert (
        json.loads(dict(exact_against_day_part_result.card_facts)["match_states"])[
            "times"
        ]
        == "unknown"
    )
    disjoint_day_part_user_id = bot_user_id + 10
    _advance_to_complete_game_search(system, bot_user_id=disjoint_day_part_user_id)
    system.submit_search(
        update_id="submit-disjoint-day-part-search",
        telegram_user_id=disjoint_day_part_user_id,
        game_search_details={"times": ["daytime"]},
    )
    system.process_searches_until_idle()
    disjoint_day_part_search = system.completed_searches(disjoint_day_part_user_id)[0]
    assert all(
        dict(result.card_facts)["opportunity_id"] != day_part_opportunity.opportunity_id
        for result in system.results(disjoint_day_part_search.completed_search_id)
    )
    reply_parent_body = "Организатор уточнил детали в следующем сообщении."
    classifier.return_for(
        body=reply_parent_body,
        result=ClassifierAdapterResult(
            output={
                "schema_version": "source-message-classification-v1",
                "disposition": "irrelevant",
                "candidates": [],
            },
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="controlled-offline",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=1,
            input_tokens=10,
            output_tokens=5,
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4912),
        to_checkpoint=TelegramChannelCheckpoint(pts=4913),
        source_event_id="source-event:open-match:reply-parent",
        telegram_message_id=1011,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=reply_parent_body,
        event_time=datetime(2026, 8, 18, 17, 38, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    reply_child_body = (
        "20 августа 2026 на Петроградской нужен один игрок. "
        "Пишите @reply_context_contact"
    )
    classifier.return_for(
        body=reply_child_body,
        result=_minimal_classifier_result(
            candidate_key="eligible-reply-context",
            body=reply_child_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": "@reply_context_contact",
                    "evidence": "@reply_context_contact",
                }
            ],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4913),
        to_checkpoint=TelegramChannelCheckpoint(pts=4914),
        source_event_id="source-event:open-match:reply-child",
        telegram_message_id=1012,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=reply_child_body,
        event_time=datetime(2026, 8, 18, 18, 0, tzinfo=UTC),
        reply_to_telegram_message_id=1011,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    assert classifier.requests[-1].eligible_reply_context == {
        "relationship_kind": "direct_reply",
        "source_chat_reference": "source-chat:channel:4900100",
        "registry_generation": 1,
        "telegram_message_id": 1011,
        "source_message_revision_id": (
            "source-chat:channel:4900100:message:1011:revision:1"
        ),
        "body": reply_parent_body,
        "source_event_time": "2026-08-18T17:38:00+00:00",
    }

    cross_chat_child_body = (
        "20 августа 2026 на Петроградской нужен один игрок. Пишите @cross_chat_context"
    )
    classifier.return_for(
        body=cross_chat_child_body,
        result=_minimal_classifier_result(
            candidate_key="cross-chat-context",
            body=cross_chat_child_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": "@cross_chat_context",
                    "evidence": "@cross_chat_context",
                }
            ],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4914),
        to_checkpoint=TelegramChannelCheckpoint(pts=4915),
        source_event_id="source-event:open-match:cross-chat-reply-child",
        telegram_message_id=1013,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=cross_chat_child_body,
        event_time=datetime(2026, 8, 18, 18, 2, tzinfo=UTC),
        reply_to_telegram_message_id=1011,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    attempts_before_cross_chat = system.classification_attempts()
    cross_chat_revision_id = "source-chat:channel:4900100:message:1013:revision:1"
    invalid_command = system.invalidate_classifier_context(
        source_message_revision_id=cross_chat_revision_id,
        contract_name=ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
        payload_updates={
            "eligible_reply_context": {
                "relationship_kind": "direct_reply",
                "source_chat_reference": "source-chat:channel:4900200",
                "registry_generation": 1,
                "telegram_message_id": 1011,
                "source_message_revision_id": (
                    "source-chat:channel:4900200:message:1011:revision:1"
                ),
                "body": reply_parent_body,
                "source_event_time": "2026-08-18T17:38:00+00:00",
            }
        },
    )
    assert system.process_next_contract_handoff(RuntimeRole.CLASSIFICATION)
    assert not system.process_next_contract_handoff(RuntimeRole.CLASSIFICATION)
    assert system.classification_attempts() == attempts_before_cross_chat
    assert all(
        opportunity.source_message_revision_id != cross_chat_revision_id
        for opportunity in system.opportunities()
    )
    assert system.operator_alert(invalid_command.message_id) == OperatorAlert(
        producer=RuntimeRole.APPLICATION,
        consumer=RuntimeRole.CLASSIFICATION,
        contract_name=ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
        contract_version=2,
        failure_code=FailureCode.INVALID_CONTRACT,
    )

    updated_reply_parent_body = "Организатор уточнил актуальные детали игры."
    classifier.return_for(
        body=updated_reply_parent_body,
        result=ClassifierAdapterResult(
            output={
                "schema_version": "source-message-classification-v1",
                "disposition": "irrelevant",
                "candidates": [],
            },
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="controlled-offline",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=1,
            input_tokens=10,
            output_tokens=5,
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4915),
        to_checkpoint=TelegramChannelCheckpoint(pts=4916),
        source_event_id="source-event:open-match:reply-parent-edit",
        telegram_message_id=1011,
        revision=2,
        kind=SourceEventKind.EDIT,
        body=updated_reply_parent_body,
        event_time=datetime(2026, 8, 18, 18, 3, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()

    stale_context_child_body = (
        "20 августа 2026 на Петроградской нужен один игрок. Пишите @stale_context"
    )
    classifier.return_for(
        body=stale_context_child_body,
        result=_minimal_classifier_result(
            candidate_key="stale-reply-context",
            body=stale_context_child_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": "@stale_context",
                    "evidence": "@stale_context",
                }
            ],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4916),
        to_checkpoint=TelegramChannelCheckpoint(pts=4917),
        source_event_id="source-event:open-match:stale-reply-child",
        telegram_message_id=1014,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=stale_context_child_body,
        event_time=datetime(2026, 8, 18, 18, 5, tzinfo=UTC),
        reply_to_telegram_message_id=1011,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    assert system.process_next_contract_handoff(RuntimeRole.CLASSIFICATION)
    assert classifier.requests[-1].eligible_reply_context == {
        "relationship_kind": "direct_reply",
        "source_chat_reference": "source-chat:channel:4900100",
        "registry_generation": 1,
        "telegram_message_id": 1011,
        "source_message_revision_id": (
            "source-chat:channel:4900100:message:1011:revision:2"
        ),
        "body": updated_reply_parent_body,
        "source_event_time": "2026-08-18T18:03:00+00:00",
    }
    stale_child_revision_id = "source-chat:channel:4900100:message:1014:revision:1"
    system.invalidate_classifier_context(
        source_message_revision_id=stale_child_revision_id,
        contract_name=ContractName.CLASSIFICATION_PROPOSAL,
        payload_updates={
            "eligible_reply_context": {
                "relationship_kind": "direct_reply",
                "source_chat_reference": "source-chat:channel:4900100",
                "registry_generation": 1,
                "telegram_message_id": 1011,
                "source_message_revision_id": (
                    "source-chat:channel:4900100:message:1011:revision:1"
                ),
                "body": reply_parent_body,
                "source_event_time": "2026-08-18T17:38:00+00:00",
            }
        },
    )
    assert system.process_next_contract_handoff(RuntimeRole.APPLICATION)
    assert not system.process_next_contract_handoff(RuntimeRole.APPLICATION)
    assert all(
        opportunity.source_message_revision_id != stale_child_revision_id
        for opportunity in system.opportunities()
    )

    old_parent_body = "Контекст старше суток не является подходящим."
    classifier.return_for(
        body=old_parent_body,
        result=ClassifierAdapterResult(
            output={
                "schema_version": "source-message-classification-v1",
                "disposition": "irrelevant",
                "candidates": [],
            },
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="controlled-offline",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=1,
            input_tokens=10,
            output_tokens=5,
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4917),
        to_checkpoint=TelegramChannelCheckpoint(pts=4918),
        source_event_id="source-event:open-match:old-reply-parent",
        telegram_message_id=1020,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=old_parent_body,
        event_time=datetime(2026, 8, 17, 17, 59, 59, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    old_context_child_body = (
        "20 августа 2026 на Петроградской нужен один игрок. Пишите @old_context"
    )
    classifier.return_for(
        body=old_context_child_body,
        result=_minimal_classifier_result(
            candidate_key="old-reply-context",
            body=old_context_child_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": "@old_context",
                    "evidence": "@old_context",
                }
            ],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4918),
        to_checkpoint=TelegramChannelCheckpoint(pts=4919),
        source_event_id="source-event:open-match:old-reply-child",
        telegram_message_id=1021,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=old_context_child_body,
        event_time=datetime(2026, 8, 18, 18, 0, tzinfo=UTC),
        reply_to_telegram_message_id=1020,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    assert classifier.requests[-1].eligible_reply_context is None
    assert any(
        opportunity.source_message_revision_id
        == "source-chat:channel:4900100:message:1021:revision:1"
        for opportunity in system.opportunities()
    )

    non_direct_body = (
        "20 августа 2026 на Петроградской нужен один игрок. Пишите @non_direct_context"
    )
    classifier.return_for(
        body=non_direct_body,
        result=_minimal_classifier_result(
            candidate_key="non-direct-context",
            body=non_direct_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": "@non_direct_context",
                    "evidence": "@non_direct_context",
                }
            ],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4919),
        to_checkpoint=TelegramChannelCheckpoint(pts=4920),
        source_event_id="source-event:open-match:non-direct-context",
        telegram_message_id=1022,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=non_direct_body,
        event_time=datetime(2026, 8, 18, 18, 10, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    assert classifier.requests[-1].eligible_reply_context is None
    assert any(
        opportunity.source_message_revision_id
        == "source-chat:channel:4900100:message:1022:revision:1"
        for opportunity in system.opportunities()
    )

    weekday_body = "В среду на Петроградской нужен один игрок. Пишите @weekday_context"
    classifier.return_for(
        body=weekday_body,
        result=_minimal_classifier_result(
            candidate_key="weekday-relative",
            body=weekday_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": "@weekday_context",
                    "evidence": "@weekday_context",
                }
            ],
            event_time_evidence="В среду",
            start_local_date="2026-08-19",
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4920),
        to_checkpoint=TelegramChannelCheckpoint(pts=4921),
        source_event_id="source-event:open-match:weekday-relative",
        telegram_message_id=1023,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=weekday_body,
        event_time=datetime(2026, 8, 18, 21, 30, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    assert any(
        opportunity.source_message_revision_id
        == "source-chat:channel:4900100:message:1023:revision:1"
        and opportunity.publication_state == "active"
        for opportunity in system.opportunities()
    )

    mismatched_weekday_body = (
        "В среду на Петроградской нужен один игрок. Пишите @mismatched_weekday"
    )
    classifier.return_for(
        body=mismatched_weekday_body,
        result=_minimal_classifier_result(
            candidate_key="mismatched-weekday-relative",
            body=mismatched_weekday_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": "@mismatched_weekday",
                    "evidence": "@mismatched_weekday",
                }
            ],
            event_time_evidence="В среду",
            start_local_date="2026-08-20",
        ),
    )
    before_mismatched_weekday = len(system.opportunities())
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4921),
        to_checkpoint=TelegramChannelCheckpoint(pts=4922),
        source_event_id="source-event:open-match:mismatched-weekday-relative",
        telegram_message_id=1024,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=mismatched_weekday_body,
        event_time=datetime(2026, 8, 18, 21, 31, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    assert len(system.opportunities()) == before_mismatched_weekday

    selected_station_id = "station:ru:spb:komendantsky-prospekt"
    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="на Петроградской",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    places=(
                        LocationCandidate(
                            place_id="station:ru:spb:petrogradskaya",
                            display_name="Петроградская",
                            geographic_type=GeographicType.STATION,
                            country_id="country:ru",
                            city_id="city:ru:saint-petersburg",
                            verified_parent_ids=(
                                "country:ru",
                                "city:ru:saint-petersburg",
                            ),
                            parent_display_names=(
                                "Россия",
                                "Saint Petersburg",
                            ),
                            iana_timezone="Europe/Moscow",
                            resolver_version="controlled-resolver-v1",
                            glossary_version="location-glossary-v1",
                            localized_display_names=(
                                ("en", "Petrogradskaya"),
                                ("ru", "Петроградская"),
                            ),
                            verified_disjoint_place_ids=(selected_station_id,),
                        ),
                    ),
                    glossary_version="location-glossary-v1",
                ),
            ),
        ),
    )
    disjoint_proof_body = (
        "20 августа 2026 на Петроградской нужен один игрок. Пишите @disjoint_area_proof"
    )
    classifier.return_for(
        body=disjoint_proof_body,
        result=_minimal_classifier_result(
            candidate_key="resolver-disjoint-area-proof",
            body=disjoint_proof_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": "@disjoint_area_proof",
                    "evidence": "@disjoint_area_proof",
                }
            ],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4922),
        to_checkpoint=TelegramChannelCheckpoint(pts=4923),
        source_event_id="source-event:open-match:disjoint-area-proof",
        telegram_message_id=1025,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=disjoint_proof_body,
        event_time=datetime(2026, 8, 18, 21, 32, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    disjoint_proof_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id
        == "source-chat:channel:4900100:message:1025:revision:1"
    )

    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="at Komendantsky Prospekt",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    places=(
                        LocationCandidate(
                            place_id=selected_station_id,
                            display_name="Komendantsky Prospekt",
                            geographic_type=GeographicType.STATION,
                            country_id="country:ru",
                            city_id="city:ru:saint-petersburg",
                            verified_parent_ids=(
                                "district:ru:spb:primorsky",
                                "city:ru:saint-petersburg",
                                "country:ru",
                            ),
                            parent_display_names=(
                                "Primorsky District",
                                "Saint Petersburg",
                                "Russia",
                            ),
                            iana_timezone=None,
                            resolver_version="controlled-resolver-v1",
                            glossary_version="location-glossary-v1",
                            localized_display_names=(
                                ("en", "Komendantsky Prospekt"),
                                ("es", "Komendantsky Prospekt"),
                                ("fr", "Komendantsky Prospekt"),
                                ("ru", "Комендантский проспект"),
                            ),
                        ),
                    ),
                    glossary_version="location-glossary-v1",
                ),
            ),
        ),
    )
    area_proof_user_id = bot_user_id + 11
    _advance_to_complete_game_search(
        system,
        bot_user_id=area_proof_user_id,
        area_text="at Komendantsky Prospekt",
    )
    system.submit_search(
        update_id="submit-resolver-area-proof-search",
        telegram_user_id=area_proof_user_id,
    )
    system.process_searches_until_idle()
    area_proof_search = system.completed_searches(area_proof_user_id)[0]
    area_proof_results = system.results(area_proof_search.completed_search_id)
    unproven_station_result = next(
        result
        for result in area_proof_results
        if dict(result.card_facts)["opportunity_id"] == opportunities[0].opportunity_id
    )
    assert unproven_station_result.result_class == "possible_match"
    assert (
        json.loads(dict(unproven_station_result.card_facts)["match_states"])[
            "search_area"
        ]
        == "unknown"
    )
    assert all(
        dict(result.card_facts)["opportunity_id"]
        != disjoint_proof_opportunity.opportunity_id
        for result in area_proof_results
    )
    system.reset()


def _register_source_chat(
    system: AcceptanceSpine,
    *,
    clock: FrozenClock,
    administrator_id: int,
) -> None:
    system.start_bot_user(
        update_id="start:open-match-admin",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:open-match-admin",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 8, 18, 9, 5, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:open-match-admin",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:open-match-admin",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:open-match-admin",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:open-match-admin",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add-source-chat:open-match-admin",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id="address:open-match-admin",
        telegram_user_id=administrator_id,
        address="@synthetic_open_match_source",
    )
    system.process_source_chat_registrations_until_idle()


def _minimal_classifier_result(
    *,
    candidate_key: str,
    body: str,
    response_routes: list[JsonValue],
    event_time_evidence: str = "20 августа 2026",
    day_part: str | None = None,
    start_local_date: str = "2026-08-20",
) -> ClassifierAdapterResult:
    event_time: dict[str, JsonValue] = {
        "start_local_date": start_local_date,
        "end_local_date": start_local_date,
        "iana_timezone": "Europe/Moscow",
    }
    if day_part is not None:
        event_time["day_part"] = day_part
    output: dict[str, JsonValue] = {
        "schema_version": "source-message-classification-v1",
        "disposition": "accepted",
        "candidates": [
            {
                "candidate_key": candidate_key,
                "opportunity_type": "open_match",
                "evidence": {
                    "opportunity": "нужен один игрок",
                    "event_time": event_time_evidence,
                    "location": "на Петроградской",
                    "open_places": "один игрок",
                },
                "location": {
                    "mention": "на Петроградской",
                    "place_id": "station:ru:spb:petrogradskaya",
                    "country_id": "country:ru",
                    "city_id": "city:ru:saint-petersburg",
                },
                "event_time": event_time,
                "open_places": 1,
                "response_routes": response_routes,
            }
        ],
    }
    return ClassifierAdapterResult(
        output=output,
        effective_model="gpt-5.6-sol",
        effective_reasoning_effort="high",
        codex_version="controlled-offline",
        adapter_kind="controlled_recording",
        adapter_version="classifier-recording-v1",
        duration_ms=3,
        input_tokens=30,
        output_tokens=20,
    )


def _advance_to_complete_game_search(
    system: AcceptanceSpine,
    *,
    bot_user_id: int,
    locale: str = "en",
    area_text: str = "whole city",
) -> None:
    system.start_bot_user(
        update_id=f"start:open-match-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id=f"language:open-match-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        locale=locale,
    )
    system.select_direction(
        update_id=f"intent:open-match-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        direction="game_search",
    )
    system.submit_location_text(
        update_id=f"country:open-match-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id=f"city:open-match-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        text="Saint Petersburg",
    )
    system.submit_location_text(
        update_id=f"area:open-match-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        text=area_text,
    )
    system.submit_required_date_text(
        update_id=f"date:open-match-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        text="20 August",
    )
