"""Long-term transfer Search through the approved PostgreSQL-backed seam."""

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
from modules.testkit import (
    ControlledDateInterpretationAdapter,
    ControlledLocationResolverAdapter,
    ControlledModelAdapter,
    ControlledTelegramDeliveryAdapter,
    ControlledTelegramIngestionAdapter,
    FrozenClock,
    boot_acceptance_spine,
)
from tests.system.test_open_match_game_search import (
    _minimal_classifier_result,
    _register_source_chat,
)


def _transfer_location_resolution() -> LocationResolution:
    return LocationResolution(
        interpretations=(
            LocationInterpretation(
                places=(
                    LocationCandidate(
                        place_id="station:ru:spb:petrogradskaya",
                        display_name="Petrogradskaya",
                        geographic_type=GeographicType.STATION,
                        country_id="country:ru",
                        city_id="city:ru:saint-petersburg",
                        verified_parent_ids=(
                            "country:ru",
                            "city:ru:saint-petersburg",
                        ),
                        parent_display_names=("Russia", "Saint Petersburg"),
                        iana_timezone="Europe/Moscow",
                        resolver_version="controlled-resolver-v1",
                        glossary_version="location-glossary-v1",
                        localized_display_names=(
                            ("en", "Petrogradskaya"),
                            ("ru", "Петроградская"),
                            ("es", "Petrogradskaya"),
                            ("fr", "Petrogradskaya"),
                        ),
                    ),
                ),
                glossary_version="location-glossary-v1",
            ),
        ),
    )


@pytest.mark.parametrize(
    ("direction", "opportunity_type", "opportunity_phrase", "title"),
    (
        (
            "new_team_search",
            "roster_vacancy",
            "roster vacancy",
            "Roster Vacancy",
        ),
        (
            "transfer_player_search",
            "player_transfer_availability",
            "player transfer availability",
            "Player Transfer Availability",
        ),
    ),
)
def test_long_term_transfer_direction_persists_and_matches_only_its_target(
    direction: str,
    opportunity_type: str,
    opportunity_phrase: str,
    title: str,
) -> None:
    telegram_ingestion = ControlledTelegramIngestionAdapter()
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    classifier = ControlledModelAdapter()
    resolver = ControlledLocationResolverAdapter()
    date_interpretation = ControlledDateInterpretationAdapter()
    date_interpretation.return_for(
        text="from 1 September",
        resolution=DateInterpretationResolution(
            interpretations=(
                DateInterpretation(
                    start_local_date=date(2026, 9, 1),
                    end_local_date=date(2026, 9, 1),
                    iana_timezone="Europe/Moscow",
                ),
            )
        ),
    )
    date_interpretation.return_for(
        text="last month",
        resolution=DateInterpretationResolution(
            interpretations=(
                DateInterpretation(
                    start_local_date=date(2026, 7, 17),
                    end_local_date=date(2026, 7, 17),
                    iana_timezone="Europe/Moscow",
                ),
            )
        ),
    )
    clock = FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    administrator_id = 55_001
    bot_user_id = 55_002 if direction == "new_team_search" else 55_003
    source_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=5_500_100,
    )
    contact = "@transfer_contact"
    body = (
        f"Long-term {opportunity_phrase}: need a goalkeeper for the 2026-2027 "
        f"season on Petrogradskaya. Message {contact}"
    )
    telegram_ingestion.allow_public_username(
        address="@synthetic_open_match_source",
        identity=source_identity,
        transport_boundary="channel-pts:5500",
    )
    result = _minimal_classifier_result(
        candidate_key=f"{opportunity_type}-candidate",
        body=body,
        response_routes=[
            {
                "kind": "explicit_telegram_username",
                "value": contact,
                "evidence": contact,
            }
        ],
        opportunity_evidence=opportunity_phrase,
        open_places_evidence="goalkeeper",
    )
    candidates = result.output["candidates"]
    assert isinstance(candidates, list) and len(candidates) == 1
    candidate = candidates[0]
    assert isinstance(candidate, dict)
    evidence = candidate["evidence"]
    assert isinstance(evidence, dict)
    candidate["opportunity_type"] = opportunity_type
    candidate.pop("event_time", None)
    candidate.pop("open_places", None)
    candidate[opportunity_type] = True
    candidate["positions"] = ["goalkeeper"]
    candidate["seasonal_timing"] = {
        "kind": "stated_season",
        "value": "2026-2027",
    }
    evidence.pop("event_time", None)
    evidence.pop("open_places", None)
    evidence["location"] = "on Petrogradskaya"
    evidence[opportunity_type] = opportunity_phrase
    evidence["positions"] = "goalkeeper"
    evidence["seasonal_timing"] = "2026-2027"
    candidate["location"] = {
        "mention": "on Petrogradskaya",
        "place_id": "station:ru:spb:petrogradskaya",
        "country_id": "country:ru",
        "city_id": "city:ru:saint-petersburg",
    }
    classifier.return_for(body=body, result=result)
    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="on Petrogradskaya",
        resolution=_transfer_location_resolution(),
    )
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telegram_ingestion,
        telegram_delivery=telegram_delivery,
        model=classifier,
        location_resolver=resolver,
        date_interpretation=date_interpretation,
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
    created_at = datetime(2026, 8, 18, 9, 5, tzinfo=UTC)
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=5500),
        to_checkpoint=TelegramChannelCheckpoint(pts=5501),
        source_event_id=f"source-event:{opportunity_type}:1",
        telegram_message_id=5501,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=body,
        event_time=created_at,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    opportunities = system.opportunities()
    assert len(opportunities) == 1
    assert opportunities[0].opportunity_type == opportunity_type
    revision_id = "source-chat:channel:5500100:generation:1:message:5501:revision:1"
    publication_payloads = [
        publication.payload
        for publication in system.opportunity_publication_contracts(revision_id)
        if isinstance(publication.payload, dict)
        and publication.payload.get("publication_state") == "active"
    ]
    assert len(publication_payloads) == 1
    accepted_facts = publication_payloads[0]["accepted_facts"]
    assert isinstance(accepted_facts, dict)
    assert accepted_facts[opportunity_type] is True
    assert accepted_facts["seasonal_timing"] == {
        "kind": "stated_season",
        "value": "2026-2027",
    }
    assert accepted_facts["source_qualifying_assertion_at"] == created_at.isoformat()

    system.start_bot_user(
        update_id=f"start:{direction}",
        telegram_user_id=bot_user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id=f"language:{direction}",
        telegram_user_id=bot_user_id,
        locale="en",
    )
    system.select_direction(
        update_id=f"branch:{direction}",
        telegram_user_id=bot_user_id,
        direction="transfer_search",
    )
    system.select_direction(
        update_id=f"intent:{direction}",
        telegram_user_id=bot_user_id,
        direction=direction,
    )
    system.submit_location_text(
        update_id=f"country:{direction}",
        telegram_user_id=bot_user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id=f"city:{direction}",
        telegram_user_id=bot_user_id,
        text="Saint Petersburg",
    )
    system.submit_location_text(
        update_id=f"area:{direction}",
        telegram_user_id=bot_user_id,
        text="whole city",
    )
    system.open_transfer_search_details(
        update_id=f"details:{direction}",
        telegram_user_id=bot_user_id,
    )
    system.open_transfer_search_detail(
        update_id=f"timing:{direction}",
        telegram_user_id=bot_user_id,
        detail_key="seasonal_timing",
    )
    system.open_transfer_search_seasonal_timing_start_date(
        update_id=f"start-date-prompt:{direction}",
        telegram_user_id=bot_user_id,
    )
    with pytest.raises(ValueError, match="start date is invalid"):
        system.submit_transfer_search_seasonal_timing_start_date_text(
            update_id=f"past-start-date:{direction}",
            telegram_user_id=bot_user_id,
            text="last month",
        )
    draft = system.discovery_draft(bot_user_id)
    assert draft is not None
    assert draft.transfer_search_detail_draft == ()
    system.submit_transfer_search_seasonal_timing_start_date_text(
        update_id=f"start-date-value:{direction}",
        telegram_user_id=bot_user_id,
        text="from 1 September",
    )
    draft = system.discovery_draft(bot_user_id)
    assert draft is not None
    assert draft.transfer_search_detail_draft == ("start_local_date:2026-09-01",)
    system.select_transfer_search_seasonal_timing(
        update_id=f"ready-now:{direction}",
        telegram_user_id=bot_user_id,
        value="ready_now",
    )
    system.open_transfer_search_seasonal_timing_season(
        update_id=f"season-prompt:{direction}",
        telegram_user_id=bot_user_id,
    )
    system.submit_transfer_search_seasonal_timing_season_text(
        update_id=f"season-value:{direction}",
        telegram_user_id=bot_user_id,
        text="2026/27",
    )
    draft = system.discovery_draft(bot_user_id)
    assert draft is not None
    assert dict(draft.transfer_search_details) == {}
    assert draft.transfer_search_detail_draft == ("stated_season:2026-2027",)
    system.back_from_transfer_search_detail(
        update_id=f"discard:{direction}",
        telegram_user_id=bot_user_id,
    )
    draft = system.discovery_draft(bot_user_id)
    assert draft is not None
    assert dict(draft.transfer_search_details) == {}
    assert draft.transfer_search_detail_draft == ()

    system.open_transfer_search_detail(
        update_id=f"timing-again:{direction}",
        telegram_user_id=bot_user_id,
        detail_key="seasonal_timing",
    )
    system.open_transfer_search_seasonal_timing_season(
        update_id=f"season-prompt-again:{direction}",
        telegram_user_id=bot_user_id,
    )
    system.submit_transfer_search_seasonal_timing_season_text(
        update_id=f"season-value-again:{direction}",
        telegram_user_id=bot_user_id,
        text="2026/27",
    )
    system.commit_transfer_search_detail(
        update_id=f"done:{direction}",
        telegram_user_id=bot_user_id,
    )
    draft = system.discovery_draft(bot_user_id)
    assert draft is not None
    assert dict(draft.transfer_search_details) == {
        "seasonal_timing": ("stated_season:2026-2027",)
    }

    system.submit_search(
        update_id=f"submit:{direction}",
        telegram_user_id=bot_user_id,
    )
    system.process_searches_until_idle()
    system.process_searches_until_idle()
    completed = system.completed_searches(bot_user_id)
    assert len(completed) == 1
    assert dict(completed[0].transfer_search_details) == {
        "seasonal_timing": ("stated_season:2026-2027",)
    }
    results = system.results(completed[0].completed_search_id)
    assert len(results) == 1
    assert results[0].result_class == "confirmed_match"
    facts = dict(results[0].card_facts)
    assert facts["opportunity_type"] == opportunity_type
    assert facts[opportunity_type] == "true"
    assert json.loads(facts["match_states"])["seasonal_timing"] == "confirmed"
    assert title in telegram_delivery.messages[-1].text
    revision_inputs = system.completed_search_opportunity_revision_inputs(
        completed[0].completed_search_id
    )
    assert len(revision_inputs) == 1

    deletion_time = datetime(2026, 8, 18, 10, 0, tzinfo=UTC)
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=5501),
        to_checkpoint=TelegramChannelCheckpoint(pts=5502),
        source_event_id=f"source-event:{opportunity_type}:delete",
        telegram_message_id=5501,
        revision=2,
        kind=SourceEventKind.DELETE,
        body=None,
        event_time=deletion_time,
    )
    clock.advance_to(deletion_time)
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    system.process_opportunities_until_idle()

    deleted_result = system.results(completed[0].completed_search_id)[0]
    deleted_facts = dict(deleted_result.card_facts)
    assert deleted_facts["publication_state"] == "suppressed"
    assert "response_route_kind" not in deleted_facts
    assert "response_route_value" not in deleted_facts
    assert contact not in json.dumps(deleted_facts)
