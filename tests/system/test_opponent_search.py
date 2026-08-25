"""Opponent Search through the approved PostgreSQL-backed system seam."""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime

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
from modules.testkit import (
    ControlledDateInterpretationAdapter,
    ControlledLocationResolverAdapter,
    ControlledModelAdapter,
    ControlledTelegramDeliveryAdapter,
    ControlledTelegramIngestionAdapter,
    ControlledTimezoneDataAdapter,
    FrozenClock,
    boot_acceptance_spine,
)
from tests.system.test_open_match_game_search import (
    _minimal_classifier_result,
    _register_source_chat,
)


def test_opponent_request_search_matches_published_request_end_to_end() -> None:
    telegram_ingestion = ControlledTelegramIngestionAdapter()
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    classifier = ControlledModelAdapter()
    resolver = ControlledLocationResolverAdapter()
    dates = ControlledDateInterpretationAdapter()
    timezones = ControlledTimezoneDataAdapter()
    clock = FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    administrator_id = 54_001
    bot_user_id = 54_002
    source_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=5_400_100,
    )
    body = (
        "20 августа 2026 в 19:00 наша команда ищет соперника на Петроградской. "
        "The team has a venue. Пишите @opponent_contact"
    )
    telegram_ingestion.allow_public_username(
        address="@synthetic_open_match_source",
        identity=source_identity,
        transport_boundary="channel-pts:5400",
    )
    result = _minimal_classifier_result(
        candidate_key="opponent-request",
        body=body,
        response_routes=[
            {
                "kind": "explicit_telegram_username",
                "value": "@opponent_contact",
                "evidence": "@opponent_contact",
            }
        ],
        event_time_evidence="20 августа 2026 в 19:00",
        exact_local_time="19:00",
        opportunity_evidence="наша команда ищет соперника",
    )
    candidates = result.output["candidates"]
    assert isinstance(candidates, list) and len(candidates) == 1
    candidate = candidates[0]
    assert isinstance(candidate, dict)
    evidence = candidate["evidence"]
    assert isinstance(evidence, dict)
    candidate["opportunity_type"] = "opponent_request"
    candidate.pop("open_places", None)
    candidate["opponent_request"] = True
    candidate["venue_provision"] = "team_has_venue"
    evidence.pop("open_places", None)
    evidence["opponent_request"] = "наша команда ищет соперника"
    evidence["venue_provision"] = "The team has a venue"
    classifier.return_for(body=body, result=result)
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
        from_checkpoint=TelegramChannelCheckpoint(pts=5400),
        to_checkpoint=TelegramChannelCheckpoint(pts=5401),
        source_event_id="source-event:opponent-request:1",
        telegram_message_id=541,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=body,
        event_time=datetime(2026, 8, 18, 9, 5, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    opportunities = system.opportunities()
    assert len(opportunities) == 1
    assert opportunities[0].opportunity_type == "opponent_request"
    assert opportunities[0].publication_state == "active"

    system.start_bot_user(
        update_id="start:opponent-user",
        telegram_user_id=bot_user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:opponent-user",
        telegram_user_id=bot_user_id,
        locale="en",
    )
    system.select_direction(
        update_id="branch:opponent-user",
        telegram_user_id=bot_user_id,
        direction="competition_search",
    )
    system.select_direction(
        update_id="intent:opponent-user",
        telegram_user_id=bot_user_id,
        direction="opponent_search",
    )
    system.submit_location_text(
        update_id="country:opponent-user",
        telegram_user_id=bot_user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id="city:opponent-user",
        telegram_user_id=bot_user_id,
        text="Saint Petersburg",
    )
    system.submit_location_text(
        update_id="area:opponent-user",
        telegram_user_id=bot_user_id,
        text="whole city",
    )
    system.submit_required_date_text(
        update_id="date:opponent-user",
        telegram_user_id=bot_user_id,
        text="20 August",
    )
    system.open_opponent_search_details(
        update_id="details:opponent-user",
        telegram_user_id=bot_user_id,
    )
    system.open_opponent_search_detail(
        update_id="time:opponent-user",
        telegram_user_id=bot_user_id,
        detail_key="times",
    )
    system.select_opponent_search_time(
        update_id="time-value:opponent-user",
        telegram_user_id=bot_user_id,
        value="evening",
    )
    system.open_opponent_search_detail(
        update_id="venue:opponent-user",
        telegram_user_id=bot_user_id,
        detail_key="venue_provision",
    )
    system.select_opponent_search_venue_provision(
        update_id="venue-value:opponent-user",
        telegram_user_id=bot_user_id,
        value="needs_opponent_venue",
    )
    draft = system.discovery_draft(bot_user_id)
    assert dict(draft.opponent_search_details) == {
        "times": ("evening",),
        "venue_provision": ("needs_opponent_venue",),
    }
    system.submit_search(
        update_id="submit:opponent-user",
        telegram_user_id=bot_user_id,
    )
    system.process_searches_until_idle()

    completed = system.completed_searches(bot_user_id)
    assert len(completed) == 1
    assert dict(completed[0].opponent_search_details) == {
        "times": ("evening",),
        "venue_provision": ("needs_opponent_venue",),
    }
    results = system.results(completed[0].completed_search_id)
    assert len(results) == 1
    assert results[0].result_class == "confirmed_match"
    facts = dict(results[0].card_facts)
    assert facts["opportunity_type"] == "opponent_request"
    assert facts["opponent_request"] == "true"
    assert facts["venue_provision"] == "team_has_venue"
    assert json.loads(facts["match_states"])["venue_provision"] == "confirmed"
    revision_inputs = system.completed_search_opportunity_revision_inputs(
        completed[0].completed_search_id
    )
    assert len(revision_inputs) == 1
    persisted_facts = revision_inputs[0]["accepted_facts"]
    assert isinstance(persisted_facts, dict)
    assert persisted_facts["opponent_request"] is True
    assert persisted_facts["venue_provision"] == "team_has_venue"
    card = telegram_delivery.messages[-1]
    assert card.text.startswith("⚽ Opponent Request\n")
    assert "Team has venue" in card.text
    assert "Our team has a venue" not in card.text
    assert "needs clarification" not in card.text
