"""In-person Coaching Services discovery through the controlled system seam."""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime

import pytest

from modules.domain import (
    ConversationStage,
    DateInterpretation,
    DateInterpretationResolution,
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
from tests.system.test_transfer_search import _transfer_location_resolution


@pytest.mark.parametrize(
    (
        "direction",
        "opportunity_type",
        "opportunity_phrase",
        "coaching_type",
        "source_start_date",
        "requested_start_date",
        "requested_start_text",
        "title",
    ),
    (
        (
            "coach_search",
            "coach_availability",
            "coach offers",
            "individual_training",
            "2026-08-20",
            date(2026, 8, 25),
            "from 25 August",
            "Coach Availability",
        ),
        (
            "coaching_service_offer",
            "coach_request",
            "looking for a coach",
            "team_training",
            "2026-09-05",
            date(2026, 9, 1),
            "from 1 September",
            "Coach Request",
        ),
    ),
)
def test_in_person_coaching_direction_persists_matches_and_renders(
    direction: str,
    opportunity_type: str,
    opportunity_phrase: str,
    coaching_type: str,
    source_start_date: str,
    requested_start_date: date,
    requested_start_text: str,
    title: str,
) -> None:
    """Both Coaching Services directions publish, persist, match, and localize."""
    telegram_ingestion = ControlledTelegramIngestionAdapter()
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    classifier = ControlledModelAdapter()
    resolver = ControlledLocationResolverAdapter()
    date_interpretation = ControlledDateInterpretationAdapter()
    timezone_data = ControlledTimezoneDataAdapter()
    timezone_data.add_source(
        version="controlled-tzdb-v1",
        timezones=("Europe/Moscow",),
    )
    date_interpretation.return_for(
        text=requested_start_text,
        resolution=DateInterpretationResolution(
            interpretations=(
                DateInterpretation(
                    start_local_date=requested_start_date,
                    end_local_date=requested_start_date,
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
    administrator_id = 56_001
    bot_user_id = 56_002 if direction == "coach_search" else 56_003
    source_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=5_600_100 if direction == "coach_search" else 5_600_101,
    )
    contact = "@coaching_contact"
    if opportunity_type == "coach_availability":
        body = (
            "In-person coach offers individual training on Petrogradskaya. "
            f"Wednesday 19:00-20:00, starts {source_start_date}. "
            "Average players, outdoor artificial turf. Payment: paid. "
            f"Message {contact}"
        )
    else:
        body = (
            "In-person team coaching: looking for a coach on Petrogradskaya for "
            f"11x11. Wednesday 19:00-20:00, starts {source_start_date}. "
            "Team training for Average players, outdoor artificial turf. "
            "Payment: paid. "
            f"Message {contact}"
        )
    telegram_ingestion.allow_public_username(
        address="@synthetic_open_match_source",
        identity=source_identity,
        transport_boundary=(
            "channel-pts:5600" if direction == "coach_search" else "channel-pts:5601"
        ),
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
        open_places_evidence="paid",
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
    candidate["in_person"] = True
    candidate["coaching_types"] = [coaching_type]
    candidate["playing_levels"] = ["average"]
    if opportunity_type == "coach_request":
        candidate["team_formats"] = ["11x11"]
    candidate["schedule"] = {
        "weekdays": ["wednesday"],
        "local_start_time": "19:00",
        "local_end_time": "20:00",
        "start_local_date": source_start_date,
    }
    candidate["venue_settings"] = ["outdoor"]
    candidate["playing_surfaces"] = ["artificial_turf"]
    candidate["payment"] = "paid"
    evidence.clear()
    evidence.update(
        {
            "opportunity": opportunity_phrase,
            "location": "on Petrogradskaya",
            opportunity_type: opportunity_phrase,
            "in_person": "In-person",
            "coaching_types": (
                "individual training"
                if coaching_type == "individual_training"
                else "Team training"
            ),
            "playing_levels": "Average players",
            "schedule": f"Wednesday 19:00-20:00, starts {source_start_date}",
            "venue_settings": "outdoor",
            "playing_surfaces": "artificial turf",
            "payment": "Payment: paid",
        }
    )
    if opportunity_type == "coach_request":
        evidence["team_formats"] = "11x11"
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
        timezone_data=timezone_data,
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    _register_source_chat(system, clock=clock, administrator_id=administrator_id)
    system.configure_source_chat_classifier_context(
        identity=source_identity,
        registry_generation=1,
        iana_timezone="Europe/Moscow",
        country_id="country:ru",
        city_id="city:ru:saint-petersburg",
    )
    source_event_id = f"source-event:{opportunity_type}:1"
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(
            pts=5600 if direction == "coach_search" else 5601
        ),
        to_checkpoint=TelegramChannelCheckpoint(
            pts=5601 if direction == "coach_search" else 5602
        ),
        source_event_id=source_event_id,
        telegram_message_id=5601 if direction == "coach_search" else 5602,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=body,
        event_time=datetime(2026, 8, 18, 9, 6, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    opportunities = system.opportunities()
    assert len(opportunities) == 1
    assert opportunities[0].opportunity_type == opportunity_type
    revision_id = (
        "source-chat:channel:5600100:generation:1:message:5601:revision:1"
        if direction == "coach_search"
        else "source-chat:channel:5600101:generation:1:message:5602:revision:1"
    )
    active_publications = [
        publication.payload
        for publication in system.opportunity_publication_contracts(revision_id)
        if isinstance(publication.payload, dict)
        and publication.payload.get("publication_state") == "active"
    ]
    assert len(active_publications) == 1
    accepted_facts = active_publications[0]["accepted_facts"]
    assert isinstance(accepted_facts, dict)
    assert accepted_facts[opportunity_type] is True
    assert accepted_facts["in_person"] is True
    assert accepted_facts["schedule"] == {
        "weekdays": ["wednesday"],
        "local_start_time": "19:00",
        "local_end_time": "20:00",
        "start_local_date": source_start_date,
    }

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
        direction="coaching_services",
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
    system.open_coaching_search_details(
        update_id=f"details:{direction}",
        telegram_user_id=bot_user_id,
    )
    system.open_coaching_search_detail(
        update_id=f"schedule:{direction}",
        telegram_user_id=bot_user_id,
        detail_key="schedule",
    )
    system.select_coaching_search_schedule_weekday(
        update_id=f"weekday:{direction}",
        telegram_user_id=bot_user_id,
        value="wednesday",
    )
    system.select_coaching_search_schedule_day_part(
        update_id=f"day-part:{direction}",
        telegram_user_id=bot_user_id,
        value="evening",
    )
    draft = system.discovery_draft(bot_user_id)
    assert draft is not None
    assert draft.coaching_search_detail_draft == (
        "wednesday",
        "day_part:evening",
    )
    system.back_from_coaching_search_detail(
        update_id=f"discard:{direction}",
        telegram_user_id=bot_user_id,
    )
    draft = system.discovery_draft(bot_user_id)
    assert draft is not None
    assert dict(draft.coaching_search_details) == {}
    assert draft.coaching_search_detail_draft == ()

    system.open_coaching_search_detail(
        update_id=f"schedule-again:{direction}",
        telegram_user_id=bot_user_id,
        detail_key="schedule",
    )
    system.select_coaching_search_schedule_weekday(
        update_id=f"weekday-again:{direction}",
        telegram_user_id=bot_user_id,
        value="wednesday",
    )
    system.submit_coaching_search_schedule_interval(
        update_id=f"interval:{direction}",
        telegram_user_id=bot_user_id,
        start_time="19:00",
        end_time="21:00",
    )
    system.open_coaching_search_schedule_start_date(
        update_id=f"start-date-prompt:{direction}",
        telegram_user_id=bot_user_id,
    )
    with pytest.raises(ValueError, match="start date is invalid"):
        system.submit_coaching_search_schedule_start_date_text(
            update_id=f"past-start-date:{direction}",
            telegram_user_id=bot_user_id,
            text="last month",
        )
    system.back_from_coaching_search_detail(
        update_id=f"close-start-date-prompt:{direction}",
        telegram_user_id=bot_user_id,
    )
    system.open_coaching_search_schedule_start_date(
        update_id=f"start-date-prompt-again:{direction}",
        telegram_user_id=bot_user_id,
    )
    system.submit_coaching_search_schedule_start_date_text(
        update_id=f"start-date-value:{direction}",
        telegram_user_id=bot_user_id,
        text=requested_start_text,
    )
    system.commit_coaching_search_detail(
        update_id=f"schedule-done:{direction}",
        telegram_user_id=bot_user_id,
    )
    system.open_coaching_search_detail(
        update_id=f"type:{direction}",
        telegram_user_id=bot_user_id,
        detail_key="coaching_types",
    )
    system.toggle_coaching_search_detail_value(
        update_id=f"type-value:{direction}",
        telegram_user_id=bot_user_id,
        value=coaching_type,
    )
    system.commit_coaching_search_detail(
        update_id=f"type-done:{direction}",
        telegram_user_id=bot_user_id,
    )
    draft = system.discovery_draft(bot_user_id)
    assert draft is not None
    details = dict(draft.coaching_search_details)
    assert details["coaching_types"] == (coaching_type,)
    assert details["schedule"] == {
        "weekdays": ["wednesday"],
        "local_start_time": "19:00",
        "local_end_time": "21:00",
        "start_local_date": requested_start_date.isoformat(),
    }

    system.submit_search(
        update_id=f"submit:{direction}",
        telegram_user_id=bot_user_id,
    )
    system.process_searches_until_idle()
    completed = system.completed_searches(bot_user_id)
    assert len(completed) == 1
    assert completed[0].required_date is None
    completed_details = dict(completed[0].coaching_search_details)
    assert completed_details["coaching_types"] == (coaching_type,)
    assert completed_details["schedule"] == {
        "weekdays": ["wednesday"],
        "local_start_time": "19:00",
        "local_end_time": "21:00",
        "start_local_date": requested_start_date.isoformat(),
    }
    results = system.results(completed[0].completed_search_id)
    assert len(results) == 1
    assert results[0].result_class == "confirmed_match"
    facts = dict(results[0].card_facts)
    assert facts["opportunity_type"] == opportunity_type
    assert json.loads(facts["match_states"])["schedule"] == "confirmed"
    assert json.loads(facts["match_states"])["schedule_time"] == "confirmed"
    assert json.loads(facts["match_states"])["schedule_start_date"] == "confirmed"
    assert title in telegram_delivery.messages[-1].text
    assert "In-person" not in telegram_delivery.messages[-1].text
    system.reset()


def test_online_only_coaching_proposition_is_not_published() -> None:
    """A classifier proposition cannot bypass the explicit in-person gate."""
    from modules.application import _body_establishes_coaching_opportunity

    assert not _body_establishes_coaching_opportunity(
        "Online-only coach offers individual training. Message @online_coach",
        "coach_availability",
    )
    assert not _body_establishes_coaching_opportunity(
        "Exclusively online coach requested for a team. Message @online_coach",
        "coach_request",
    )
    assert not _body_establishes_coaching_opportunity(
        "In-person is not available; online-only coach offers individual training. "
        "Message @online_coach",
        "coach_availability",
    )
    assert not _body_establishes_coaching_opportunity(
        "In-person sessions are unavailable; online-only team is looking for a coach. "
        "Message @online_coach",
        "coach_request",
    )
