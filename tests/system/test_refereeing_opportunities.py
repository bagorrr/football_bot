"""Real-PostgreSQL acceptance coverage for Referee opportunities."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from typing import cast

from modules.contracts import JsonValue, RuntimeRole
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


def test_referee_availability_and_request_are_published_and_matched() -> None:
    """Match dated availability, standing availability, and a dated request."""
    ingestion = ControlledTelegramIngestionAdapter()
    classifier = ControlledModelAdapter()
    classifier.enable_open_match_primary_v4()
    delivery = ControlledTelegramDeliveryAdapter()
    resolver = ControlledLocationResolverAdapter()
    dates = ControlledDateInterpretationAdapter()
    timezones = ControlledTimezoneDataAdapter()
    clock = FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    administrator_id = 49_570
    user_id = 49_571
    source_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_905_700,
    )
    ingestion.allow_public_username(
        address="@synthetic_refereeing_source",
        identity=source_identity,
        transport_boundary="channel-pts:49570",
    )
    timezones.add_source(version="controlled-tzdb-v1", timezones=("Europe/Moscow",))
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
    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="Saint Petersburg",
        resolution=_city_resolution(),
    )
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=ingestion,
        telegram_delivery=delivery,
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
    assert ingestion.boundary_requests == [source_identity]
    assert system.source_chats()
    assert system.channel_ingestion_checkpoint(
        identity=source_identity,
        registry_generation=1,
    ) == TelegramChannelCheckpoint(pts=49570), (
        ingestion.boundary_requests,
        system.source_chats(),
    )

    source_cases = (
        (
            "dated-availability",
            "Referee available for an adult football match on 20 August 2026 "
            "at 19:00 in Saint Petersburg, 7x7, head referee, paid. "
            "Contact @referee_dated",
            "referee_availability",
            {
                "opportunity": "Referee available for an adult football match",
                "event_time": "20 August 2026 at 19:00",
                "location": "in Saint Petersburg",
                "referee_availability": "Referee available",
                "event_types": "adult football match",
                "team_formats": "7x7",
                "referee_roles": "head referee",
                "payment": "paid",
            },
            {
                "start_local_date": "2026-08-20",
                "end_local_date": "2026-08-20",
                "exact_local_time": "19:00",
                "iana_timezone": "Europe/Moscow",
            },
            {"referee_availability": True},
            ("match",),
        ),
        (
            "standing-availability",
            "Referee available for adult football matches in Saint Petersburg, "
            "7x7, head referee, paid. Contact @referee_standing",
            "referee_availability",
            {
                "opportunity": "Referee available for adult football matches",
                "location": "in Saint Petersburg",
                "referee_availability": "Referee available",
                "event_types": "adult football matches",
                "team_formats": "7x7",
                "referee_roles": "head referee",
                "payment": "paid",
            },
            None,
            {"referee_availability": True},
            ("match",),
        ),
        (
            "dated-request",
            "A team needs a referee for an adult football match on 20 August "
            "2026 at 19:00 in Saint Petersburg, 7x7, head referee, paid. "
            "Contact @referee_request",
            "referee_request",
            {
                "opportunity": "needs a referee for an adult football match",
                "event_time": "20 August 2026 at 19:00",
                "location": "in Saint Petersburg",
                "referee_request": "needs a referee",
                "event_types": "adult football match",
                "team_formats": "7x7",
                "referee_roles": "head referee",
                "payment": "paid",
            },
            {
                "start_local_date": "2026-08-20",
                "end_local_date": "2026-08-20",
                "exact_local_time": "19:00",
                "iana_timezone": "Europe/Moscow",
            },
            {"referee_request": True},
            ("match",),
        ),
    )
    for offset, (
        label,
        body,
        opportunity_type,
        evidence,
        event_time,
        direction,
        event_types,
    ) in enumerate(source_cases):
        classifier.return_for(
            body=body,
            result=_classifier_result(
                body=body,
                opportunity_type=opportunity_type,
                evidence=evidence,
                event_time=event_time,
                direction=direction,
                event_types=event_types,
            ),
        )
        telegram_message_id = 1570 + offset
        ingestion.add_channel_difference_event(
            identity=source_identity,
            from_checkpoint=TelegramChannelCheckpoint(pts=49570 + offset),
            to_checkpoint=TelegramChannelCheckpoint(pts=49571 + offset),
            source_event_id=f"source-event:refereeing:{label}",
            telegram_message_id=telegram_message_id,
            revision=1,
            kind=SourceEventKind.CREATE,
            body=body,
            event_time=datetime(2026, 8, 10, 9, 6 + offset, tzinfo=UTC),
        )
        assert system.process_next_channel_telegram_difference(
            identity=source_identity,
            registry_generation=1,
        )
        system.process_opportunities_until_idle()

    published = system.opportunities()
    assert {opportunity.opportunity_type for opportunity in published} == {
        "referee_availability",
        "referee_request",
    }
    assert len(published) == 3
    assert any(
        opportunity.opportunity_type == "referee_request" for opportunity in published
    )
    standing = next(
        opportunity
        for opportunity in published
        if opportunity.source_message_revision_id.endswith(":1571:revision:1")
    )
    standing_publication = system.opportunity_publication_contracts(
        standing.source_message_revision_id
    )[0]
    assert isinstance(standing_publication.payload, dict)
    standing_facts = standing_publication.payload["accepted_facts"]
    assert isinstance(standing_facts, dict)
    assert standing_facts["start_local_date"] is None
    assert standing_facts["end_local_date"] is None

    _advance_to_complete_search(system, user_id=user_id)
    assert system.conversation_state(user_id).stage is ConversationStage.POST_CORE, (
        system.conversation_state(user_id),
        system.discovery_draft(user_id),
    )
    _configure_refereeing_search_details(system, user_id=user_id)
    system.submit_search(
        update_id="submit-refereeing-search",
        telegram_user_id=user_id,
    )
    system.process_searches_until_idle()

    completed = system.completed_searches(user_id)
    assert len(completed) == 1
    results = system.results(completed[0].completed_search_id)
    result_classes = [result.result_class for result in results]
    assert result_classes == ["confirmed_match", "possible_match"]
    result_types = [dict(result.card_facts)["opportunity_type"] for result in results]
    assert result_types == ["referee_availability", "referee_availability"]
    assert dict(results[-1].card_facts)["opportunity_id"] == standing.opportunity_id
    availability_card = delivery.messages[-1].text
    assert "⚖️ Referee Availability" in availability_card
    assert "Event type: Match" in availability_card
    assert "Team format: 7x7" in availability_card
    assert "Referee role: Head referee" in availability_card
    assert "Payment: Paid" in availability_card
    assert "Venue" not in availability_card
    assert "Surface" not in availability_card
    assert "Contact: " in availability_card
    assert availability_card.count("Contact: ") == 1

    request_user_id = user_id + 1
    _advance_to_complete_search(
        system,
        user_id=request_user_id,
        direction="refereeing_service_offer",
    )
    _configure_refereeing_search_details(system, user_id=request_user_id)
    system.submit_search(
        update_id="submit-refereeing-service-offer-search",
        telegram_user_id=request_user_id,
    )
    system.process_searches_until_idle()
    request_completed = system.completed_searches(request_user_id)
    assert len(request_completed) == 1
    request_results = system.results(request_completed[0].completed_search_id)
    assert [result.result_class for result in request_results] == ["confirmed_match"]
    assert [
        dict(result.card_facts)["opportunity_type"] for result in request_results
    ] == ["referee_request"]
    request_card = delivery.messages[-1].text
    assert "⚖️ Referee Request" in request_card
    assert "Event type: Match" in request_card
    assert "Team format: 7x7" in request_card
    assert "Referee role: Head referee" in request_card
    assert "Payment: Paid" in request_card
    assert "Venue" not in request_card
    assert "Surface" not in request_card
    assert "Contact: " in request_card
    assert request_card.count("Contact: ") == 1
    system.reset()


def _city_resolution() -> LocationResolution:
    return LocationResolution(
        interpretations=(
            LocationInterpretation(
                glossary_version="location-glossary-v1",
                places=(
                    LocationCandidate(
                        place_id="city:ru:saint-petersburg",
                        display_name="Saint Petersburg",
                        geographic_type=GeographicType.CITY,
                        country_id="country:ru",
                        city_id="city:ru:saint-petersburg",
                        verified_parent_ids=("country:ru",),
                        parent_display_names=("Russia",),
                        iana_timezone="Europe/Moscow",
                        resolver_version="controlled-resolver-v1",
                        glossary_version="location-glossary-v1",
                        localized_display_names=(
                            ("en", "Saint Petersburg"),
                            ("es", "San Petersburgo"),
                            ("fr", "Saint-Pétersbourg"),
                            ("ru", "Санкт-Петербург"),
                        ),
                    ),
                ),
            ),
        )
    )


def _register_source_chat(
    system: AcceptanceSpine,
    *,
    clock: FrozenClock,
    administrator_id: int,
) -> None:
    system.start_bot_user(
        update_id="start:refereeing-admin",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:refereeing-admin",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 8, 18, 9, 5, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:refereeing-admin",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:refereeing-admin",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:refereeing-admin",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:refereeing-admin",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add-source-chat:refereeing-admin",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id="address:refereeing-admin",
        telegram_user_id=administrator_id,
        address="@synthetic_refereeing_source",
    )
    system.process_source_chat_registrations_until_idle()


def _classifier_result(
    *,
    body: str,
    opportunity_type: str,
    evidence: dict[str, str],
    event_time: dict[str, str] | None,
    direction: dict[str, bool],
    event_types: tuple[str, ...],
) -> ClassifierAdapterResult:
    candidate: dict[str, JsonValue] = {
        "candidate_key": opportunity_type,
        "opportunity_type": opportunity_type,
        "source_context": body,
        "evidence": cast(JsonValue, evidence),
        "location": {
            "mention": "Saint Petersburg",
            "place_id": "city:ru:saint-petersburg",
            "country_id": "country:ru",
            "city_id": "city:ru:saint-petersburg",
        },
        **direction,
        "event_types": list(event_types),
        "team_formats": ["7x7"],
        "referee_roles": ["head_referee"],
        "payment": "paid",
        "response_routes": [
            {
                "kind": "explicit_telegram_username",
                "value": (
                    "@referee_dated"
                    if "@referee_dated" in body
                    else "@referee_standing"
                    if "@referee_standing" in body
                    else "@referee_request"
                ),
                "evidence": (
                    "@referee_dated"
                    if "@referee_dated" in body
                    else "@referee_standing"
                    if "@referee_standing" in body
                    else "@referee_request"
                ),
            }
        ],
    }
    if event_time is not None:
        candidate["event_time"] = cast(JsonValue, event_time)
    return ClassifierAdapterResult(
        output={
            "schema_version": "source-message-classification-v4",
            "disposition": "accepted",
            "routing": {"reason_code": "accepted", "required_context": "none"},
            "candidates": [candidate],
        },
        effective_model="gpt-5.6-sol",
        effective_reasoning_effort="high",
        codex_version="controlled-offline",
        adapter_kind="controlled_recording",
        adapter_version="classifier-recording-v1",
        duration_ms=3,
        input_tokens=30,
        output_tokens=20,
    )


def _advance_to_complete_search(
    system: AcceptanceSpine,
    *,
    user_id: int,
    direction: str = "referee_search",
) -> None:
    system.start_bot_user(
        update_id=f"start:refereeing-user:{user_id}",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id=f"language:refereeing-user:{user_id}",
        telegram_user_id=user_id,
        locale="en",
    )
    system.select_direction(
        update_id=f"branch:refereeing-user:{user_id}",
        telegram_user_id=user_id,
        direction="refereeing_services",
    )
    system.select_direction(
        update_id=f"direction:refereeing-user:{user_id}",
        telegram_user_id=user_id,
        direction=direction,
    )
    system.submit_location_text(
        update_id=f"country:refereeing-user:{user_id}",
        telegram_user_id=user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id=f"city:refereeing-user:{user_id}",
        telegram_user_id=user_id,
        text="Saint Petersburg",
    )
    system.submit_location_text(
        update_id=f"area:refereeing-user:{user_id}",
        telegram_user_id=user_id,
        text="whole city",
    )
    system.submit_required_date_text(
        update_id=f"date:refereeing-user:{user_id}",
        telegram_user_id=user_id,
        text="20 August",
    )


def _configure_refereeing_search_details(
    system: AcceptanceSpine,
    *,
    user_id: int,
) -> None:
    """Set the shared referee detail draft through its public seams."""
    assert system.discovery_draft(user_id).refereeing_search_details == ()
    system.open_refereeing_search_details(
        update_id=f"details-hub:refereeing-user:{user_id}",
        telegram_user_id=user_id,
    )
    committed_details: dict[str, tuple[str, ...]] = {}
    for detail_key, value in (
        ("event_types", "match"),
        ("team_formats", "7x7"),
        ("referee_roles", "head_referee"),
        ("payment", "paid"),
    ):
        system.open_refereeing_search_detail(
            update_id=f"details-open:{detail_key}:{user_id}",
            telegram_user_id=user_id,
            detail_key=detail_key,
        )
        system.toggle_refereeing_search_detail_value(
            update_id=f"details-toggle:{detail_key}:{user_id}",
            telegram_user_id=user_id,
            value=value,
        )
        draft = system.discovery_draft(user_id)
        assert dict(draft.refereeing_search_details).get(detail_key) is None
        assert draft.refereeing_search_detail_draft == (value,)
        system.commit_refereeing_search_detail(
            update_id=f"details-commit:{detail_key}:{user_id}",
            telegram_user_id=user_id,
        )
        committed_details[detail_key] = (value,)
        assert dict(system.discovery_draft(user_id).refereeing_search_details) == (
            committed_details
        )

    system.open_refereeing_search_detail(
        update_id=f"details-open:times:{user_id}",
        telegram_user_id=user_id,
        detail_key="times",
    )
    system.open_refereeing_search_exact_time(
        update_id=f"details-exact-time-open:{user_id}",
        telegram_user_id=user_id,
    )
    system.submit_refereeing_search_exact_time_text(
        update_id=f"details-exact-time-submit:{user_id}",
        telegram_user_id=user_id,
        text="19:00",
    )
    committed_details["times"] = ("19:00",)
    assert dict(system.discovery_draft(user_id).refereeing_search_details) == (
        committed_details
    )
    system.restart(RuntimeRole.BOT_ASSISTANT)
    assert dict(system.discovery_draft(user_id).refereeing_search_details) == (
        committed_details
    )
