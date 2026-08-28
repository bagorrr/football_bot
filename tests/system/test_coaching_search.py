"""In-person Coaching Services discovery through the controlled system seam."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import UTC, date, datetime

import psycopg
import pytest

from modules.contracts import JsonValue
from modules.domain import (
    ConversationStage,
    DateInterpretation,
    DateInterpretationResolution,
    SourceEventKind,
    TelegramAccountCheckpoint,
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
    semantic_proof_result_for,
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
    classifier.enable_coaching_primary_v1()
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
    candidate["source_context"] = body
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
    result.output["schema_version"] = "source-message-classification-v5"
    result.output["routing"] = {
        "reason_code": "accepted",
        "required_context": "none",
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
    system.select_coaching_search_schedule_day_part(
        update_id=f"day-part-second:{direction}",
        telegram_user_id=bot_user_id,
        value="morning",
    )
    draft = system.discovery_draft(bot_user_id)
    assert draft is not None
    assert draft.coaching_search_detail_draft == (
        "wednesday",
        "day_part:evening",
        "day_part:morning",
    )
    system.open_coaching_search_schedule_start_date(
        update_id=f"start-date-any-prompt:{direction}",
        telegram_user_id=bot_user_id,
    )
    assert "any" in telegram_delivery.messages[-1].text.casefold()
    system.submit_coaching_search_schedule_start_date_text(
        update_id=f"start-date-any:{direction}",
        telegram_user_id=bot_user_id,
        text="any",
    )
    draft = system.discovery_draft(bot_user_id)
    assert draft is not None
    assert draft.coaching_search_detail_draft == (
        "wednesday",
        "day_part:evening",
        "day_part:morning",
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
    account_checkpoint = TelegramAccountCheckpoint(
        pts=5_600,
        qts=560,
        seq=56,
        date=clock.now(),
    )
    system.initialize_account_ingestion_checkpoint(account_checkpoint)
    telegram_ingestion.add_ingestion_role_account_difference_failure(
        checkpoint=account_checkpoint,
        reason="authentication_lost",
    )
    assert system.process_next_account_telegram_difference()
    assert system.process_next_source_event()
    role_failed_results = system.results(completed[0].completed_search_id)
    assert len(role_failed_results) == 1
    role_failed_facts = dict(role_failed_results[0].card_facts)
    assert role_failed_facts["publication_state"] == "suppressed"
    assert "response_route_value" not in role_failed_facts
    system.open_main_menu(
        update_id=f"role-failed-menu:{direction}",
        telegram_user_id=bot_user_id,
    )
    system.select_main_menu_action(
        update_id=f"role-failed-new-search:{direction}",
        telegram_user_id=bot_user_id,
        action="new-search",
    )
    system.select_direction(
        update_id=f"role-failed-branch:{direction}",
        telegram_user_id=bot_user_id,
        direction="coaching_services",
    )
    system.select_direction(
        update_id=f"role-failed-intent:{direction}",
        telegram_user_id=bot_user_id,
        direction=direction,
    )
    system.submit_location_text(
        update_id=f"role-failed-country:{direction}",
        telegram_user_id=bot_user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id=f"role-failed-city:{direction}",
        telegram_user_id=bot_user_id,
        text="Saint Petersburg",
    )
    system.submit_location_text(
        update_id=f"role-failed-area:{direction}",
        telegram_user_id=bot_user_id,
        text="whole city",
    )
    system.submit_search(
        update_id=f"role-failed-submit:{direction}",
        telegram_user_id=bot_user_id,
        coaching_search_details={
            "coaching_types": [coaching_type],
            "schedule": {
                "weekdays": ["wednesday"],
                "local_start_time": "19:00",
                "local_end_time": "21:00",
                "start_local_date": requested_start_date.isoformat(),
            },
        },
    )
    system.process_searches_until_idle()
    completed_after_role_stop = system.completed_searches(bot_user_id)
    assert len(completed_after_role_stop) == 2
    role_failed_search = next(
        search
        for search in completed_after_role_stop
        if search.search_update_id == f"role-failed-submit:{direction}"
    )
    assert system.results(role_failed_search.completed_search_id) == ()
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        connection.execute(
            """
            UPDATE football_runtime.ingestion_failures
            SET active = false
            WHERE scope = 'ingestion_role'
            """
        )
    restored_results = system.results(completed[0].completed_search_id)
    assert len(restored_results) == 1
    restored_facts = dict(restored_results[0].card_facts)
    assert restored_facts["publication_state"] == "active"
    assert restored_facts["response_route_value"] == contact
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        connection.execute(
            """
            UPDATE football_runtime.source_chat_registry
            SET enabled = false, updated_at = %s
            WHERE peer_kind = %s
              AND telegram_chat_id = %s
              AND registry_generation = 1
            """,
            (clock.now(), source_identity.kind.value, source_identity.telegram_id),
        )
    disabled_results = system.results(completed[0].completed_search_id)
    assert len(disabled_results) == 1
    disabled_facts = dict(disabled_results[0].card_facts)
    assert disabled_facts["publication_state"] == "suppressed"
    assert "response_route_value" not in disabled_facts
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


@pytest.mark.parametrize(
    (
        "body",
        "opportunity_type",
        "directional_evidence",
        "in_person_evidence",
        "route_value",
        "expected_active",
    ),
    (
        (
            "In-person coaching is not available at the field. "
            "Message @coach_contact on Petrogradskaya.",
            "coach_availability",
            "In-person coaching",
            "In-person",
            "@coach_contact",
            False,
        ),
        (
            "In-person coaching does not exist. "
            "Message @coach_contact on Petrogradskaya.",
            "coach_availability",
            "In-person coaching",
            "In-person",
            "@coach_contact",
            False,
        ),
        (
            "In-person coaching is offered by no one in Moscow. "
            "Message @coach_contact on Petrogradskaya.",
            "coach_availability",
            "In-person coaching",
            "In-person",
            "@coach_contact",
            False,
        ),
        (
            "In-person coaching is provided by nobody at the field. "
            "Message @coach_contact on Petrogradskaya.",
            "coach_availability",
            "In-person coaching",
            "In-person",
            "@coach_contact",
            False,
        ),
        (
            "In-person coaching is available to no one in Moscow. "
            "Message @coach_contact on Petrogradskaya.",
            "coach_availability",
            "In-person coaching",
            "In-person",
            "@coach_contact",
            False,
        ),
        (
            "In-person coaching is not for anyone at the field. "
            "Message @coach_contact on Petrogradskaya.",
            "coach_availability",
            "In-person coaching",
            "In-person",
            "@coach_contact",
            False,
        ),
        (
            "In-person coaching is for no one in Moscow. "
            "Message @coach_contact on Petrogradskaya.",
            "coach_availability",
            "In-person coaching",
            "In-person",
            "@coach_contact",
            False,
        ),
        (
            "In-person coaching is offered to nobody at the field. "
            "Message @coach_contact on Petrogradskaya.",
            "coach_availability",
            "In-person coaching",
            "In-person",
            "@coach_contact",
            False,
        ),
        (
            "Nobody offers in-person coaching. "
            "Message @coach_contact on Petrogradskaya.",
            "coach_availability",
            "Nobody offers in-person coaching",
            "in-person",
            "@coach_contact",
            False,
        ),
        (
            "In-person coaching is not happening. "
            "Message @coach_contact on Petrogradskaya.",
            "coach_availability",
            "In-person coaching",
            "In-person",
            "@coach_contact",
            False,
        ),
        (
            "In-person coaching is not necessary. "
            "Message @coach_contact on Petrogradskaya.",
            "coach_availability",
            "In-person coaching",
            "In-person",
            "@coach_contact",
            False,
        ),
        (
            "Nobody wants an in-person coach in Moscow. "
            "Message @team_contact on Petrogradskaya.",
            "coach_request",
            "Nobody wants an in-person coach",
            "in-person",
            "@team_contact",
            False,
        ),
        (
            "Not looking for a coach in person at the field. "
            "Message @team_contact on Petrogradskaya.",
            "coach_request",
            "looking for a coach",
            "in person",
            "@team_contact",
            False,
        ),
        (
            "In-person coaching — not available at the field. "
            "Message @coach_contact on Petrogradskaya.",
            "coach_availability",
            "In-person coaching",
            "In-person",
            "@coach_contact",
            False,
        ),
        (
            "In-person coaching. Not available at the field. "
            "Message @coach_contact on Petrogradskaya.",
            "coach_availability",
            "In-person coaching",
            "In-person",
            "@coach_contact",
            False,
        ),
        (
            "In-person coaching is available at the field; online-only sessions "
            "are also available. Message @coach_contact on Petrogradskaya.",
            "coach_availability",
            "In-person coaching is available",
            "In-person",
            "@coach_contact",
            True,
        ),
        (
            "Online-only coaching is available; in-person coaching is not offered "
            "at the field. Message @coach_contact on Petrogradskaya.",
            "coach_availability",
            "Online-only coaching is available",
            "in-person coaching is not offered",
            "@coach_contact",
            False,
        ),
        (
            "In-person coach offers individual training at the field. "
            "Message @coach_contact on Petrogradskaya.",
            "coach_availability",
            "coach offers",
            "In-person",
            "@coach_contact",
            True,
        ),
        (
            "The team wants an in-person coach at the field. "
            "Message @team_contact on Petrogradskaya.",
            "coach_request",
            "wants an in-person coach",
            "in-person",
            "@team_contact",
            True,
        ),
    ),
)
def test_coaching_polarity_is_enforced_by_authoritative_acceptance(
    body: str,
    opportunity_type: str,
    directional_evidence: str,
    in_person_evidence: str,
    route_value: str,
    expected_active: bool,
) -> None:
    """Schema-valid coaching artifacts cannot publish negated propositions."""
    telegram_ingestion = ControlledTelegramIngestionAdapter()
    classifier = ControlledModelAdapter()
    classifier.enable_coaching_primary_v1()
    resolver = ControlledLocationResolverAdapter()
    timezone_data = ControlledTimezoneDataAdapter()
    timezone_data.add_source(
        version="controlled-tzdb-v1",
        timezones=("Europe/Moscow",),
    )
    clock = FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    administrator_id = 56_004
    source_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=5_600_200,
    )
    telegram_ingestion.allow_public_username(
        address="@synthetic_open_match_source",
        identity=source_identity,
        transport_boundary="channel-pts:5620",
    )
    result = _minimal_classifier_result(
        candidate_key="coaching-polarity-candidate",
        body=body,
        response_routes=[
            {
                "kind": "explicit_telegram_username",
                "value": route_value,
                "evidence": route_value,
            }
        ],
        opportunity_evidence=directional_evidence,
    )
    candidates = result.output["candidates"]
    assert isinstance(candidates, list) and len(candidates) == 1
    candidate = candidates[0]
    assert isinstance(candidate, dict)
    evidence = candidate["evidence"]
    assert isinstance(evidence, dict)
    candidate["opportunity_type"] = opportunity_type
    candidate["source_context"] = body
    candidate.pop("event_time", None)
    candidate.pop("open_places", None)
    candidate[opportunity_type] = True
    candidate["in_person"] = True
    evidence.clear()
    evidence.update(
        {
            "opportunity": directional_evidence,
            "location": "on Petrogradskaya",
            opportunity_type: directional_evidence,
            "in_person": in_person_evidence,
        }
    )
    candidate["location"] = {
        "mention": "on Petrogradskaya",
        "place_id": "station:ru:spb:petrogradskaya",
        "country_id": "country:ru",
        "city_id": "city:ru:saint-petersburg",
    }
    result.output["schema_version"] = "source-message-classification-v5"
    result.output["routing"] = {
        "reason_code": "accepted",
        "required_context": "none",
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
        model=classifier,
        location_resolver=resolver,
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
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=5620),
        to_checkpoint=TelegramChannelCheckpoint(pts=5621),
        source_event_id="source-event:coaching-polarity:1",
        telegram_message_id=5621,
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
    revision_id = "source-chat:channel:5600200:generation:1:message:5621:revision:1"
    active_publications = [
        publication.payload
        for publication in system.opportunity_publication_contracts(revision_id)
        if isinstance(publication.payload, dict)
        and publication.payload.get("publication_state") == "active"
    ]
    if expected_active:
        opportunities = system.opportunities()
        assert len(opportunities) == 1
        assert opportunities[0].opportunity_type == opportunity_type
        assert len(active_publications) == 1
        assert active_publications[0]["response_route"] == {
            "kind": "explicit_telegram_username",
            "value": route_value,
        }
    else:
        assert system.opportunities() == ()
        assert active_publications == []
    system.reset()


def test_compound_coaching_source_keeps_typed_exact_reposts_separate() -> None:
    """Independent coaching directions retain separate typed repost clusters."""
    body = (
        "Coach offers in-person coaching on Petrogradskaya on Wednesday "
        "19:00-20:00 starting 20 August 2026 (2026-08-20). The team wants an "
        "in-person coach on Petrogradskaya on Wednesday 19:00-20:00 starting "
        "20 August 2026 (2026-08-20). "
        "Individual training for average players on outdoor artificial turf. "
        "Message @coach_contact or @team_contact."
    )
    telegram_ingestion = ControlledTelegramIngestionAdapter()
    classifier = ControlledModelAdapter()
    classifier.enable_coaching_primary_v1()
    resolver = ControlledLocationResolverAdapter()
    timezone_data = ControlledTimezoneDataAdapter()
    timezone_data.add_source(
        version="controlled-tzdb-v1",
        timezones=("Europe/Moscow",),
    )
    base_result = _minimal_classifier_result(
        candidate_key="compound-coaching-template",
        body=body,
        response_routes=[
            {
                "kind": "explicit_telegram_username",
                "value": "@coach_contact",
                "evidence": "@coach_contact",
            }
        ],
        opportunity_evidence="Coach offers in-person coaching",
    )
    candidates = base_result.output["candidates"]
    assert isinstance(candidates, list) and len(candidates) == 1
    template = candidates[0]
    assert isinstance(template, dict)
    compound_candidates: list[JsonValue] = []
    candidate_specs = (
        (
            "compound-coach-availability",
            "coach_availability",
            "Coach offers in-person coaching",
            "in-person",
            "@coach_contact",
        ),
        (
            "compound-coach-request",
            "coach_request",
            "The team wants an in-person coach",
            "in-person",
            "@team_contact",
        ),
    )
    for (
        candidate_key,
        opportunity_type,
        directional_evidence,
        in_person_evidence,
        route,
    ) in candidate_specs:
        candidate = deepcopy(template)
        candidate["candidate_key"] = candidate_key
        candidate["opportunity_type"] = opportunity_type
        candidate["source_context"] = body
        candidate.pop("event_time", None)
        candidate.pop("open_places", None)
        candidate[opportunity_type] = True
        candidate["in_person"] = True
        candidate["coaching_types"] = ["individual_training"]
        candidate["playing_levels"] = ["average"]
        candidate["schedule"] = {
            "weekdays": ["wednesday"],
            "local_start_time": "19:00",
            "local_end_time": "20:00",
            "start_local_date": "2026-08-20",
        }
        candidate["venue_settings"] = ["outdoor"]
        candidate["playing_surfaces"] = ["artificial_turf"]
        evidence = candidate["evidence"]
        assert isinstance(evidence, dict)
        evidence.clear()
        evidence.update(
            {
                "opportunity": directional_evidence,
                "location": "on Petrogradskaya",
                opportunity_type: directional_evidence,
                "in_person": in_person_evidence,
                "coaching_types": "Individual training",
                "playing_levels": "average players",
                "schedule": (
                    "Wednesday 19:00-20:00 starting 20 August 2026 (2026-08-20)"
                ),
                "venue_settings": "outdoor",
                "playing_surfaces": "artificial turf",
            }
        )
        candidate["location"] = {
            "mention": "on Petrogradskaya",
            "place_id": "station:ru:spb:petrogradskaya",
            "country_id": "country:ru",
            "city_id": "city:ru:saint-petersburg",
        }
        candidate["response_routes"] = [
            {
                "kind": "explicit_telegram_username",
                "value": route,
                "evidence": route,
            }
        ]
        compound_candidates.append(candidate)
    base_result.output["candidates"] = compound_candidates
    base_result.output["schema_version"] = "source-message-classification-v5"
    base_result.output["routing"] = {
        "reason_code": "accepted",
        "required_context": "none",
    }
    classifier.return_for(body=body, result=base_result)
    for proof_candidate in compound_candidates:
        assert isinstance(proof_candidate, dict)
        proof_candidate_key = proof_candidate.get("candidate_key")
        assert isinstance(proof_candidate_key, str)
        proof_output = deepcopy(base_result.output)
        proof_output["candidates"] = [deepcopy(proof_candidate)]
        classifier.return_proof_for(
            body=body,
            candidate_key=proof_candidate_key,
            result=semantic_proof_result_for(output=proof_output, body=body),
        )
    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="on Petrogradskaya",
        resolution=_transfer_location_resolution(),
    )
    clock = FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    administrator_id = 56_005
    source_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=5_600_500,
    )
    telegram_ingestion.allow_public_username(
        address="@synthetic_open_match_source",
        identity=source_identity,
        transport_boundary="channel-pts:5620",
    )
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telegram_ingestion,
        model=classifier,
        location_resolver=resolver,
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

    for checkpoint, message_id in ((5620, 5621), (5621, 5622)):
        telegram_ingestion.add_channel_difference_event(
            identity=source_identity,
            from_checkpoint=TelegramChannelCheckpoint(pts=checkpoint),
            to_checkpoint=TelegramChannelCheckpoint(pts=checkpoint + 1),
            source_event_id=f"source-event:compound-coaching:{message_id}",
            telegram_message_id=message_id,
            revision=1,
            kind=SourceEventKind.CREATE,
            body=body,
            event_time=datetime(2026, 8, 18, 9, message_id - 5615, tzinfo=UTC),
            source_publisher_id="publisher:compound",
        )
        assert system.process_next_channel_telegram_difference(
            identity=source_identity,
            registry_generation=1,
        )
        system.process_opportunities_until_idle()

    opportunities = system.opportunities()
    assert len(opportunities) == 4
    assert {opportunity.opportunity_type for opportunity in opportunities} == {
        "coach_availability",
        "coach_request",
    }
    clusters = system.exact_repost_clusters()
    assert len(clusters) == 2
    assert {cluster.opportunity_type for cluster in clusters} == {
        "coach_availability",
        "coach_request",
    }
    second_source_id = "source-chat:channel:5600500:generation:1:message:5622"
    for cluster in clusters:
        members = system.exact_repost_cluster_members(cluster.exact_repost_cluster_id)
        assert len(members) == 2
        assert {member.source_message_id for member in members} == {
            "source-chat:channel:5600500:generation:1:message:5621",
            second_source_id,
        }
        assert cluster.representative_source_message_id == second_source_id
        assert sum(member.is_representative for member in members) == 1
        assert sum(member.publication_state == "active" for member in members) == 1
    system.reset()
