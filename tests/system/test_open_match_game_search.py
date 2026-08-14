"""Open Match discovery through the approved PostgreSQL-backed system seam."""

# ruff: noqa: RUF001 -- reviewed multilingual product copy is intentional.

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime

import pytest

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
    assert [
        result.result_class
        for result in system.results(possible_search.completed_search_id)
    ] == ["confirmed_match", "possible_match"]

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
