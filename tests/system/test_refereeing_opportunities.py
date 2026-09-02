"""Real-PostgreSQL acceptance coverage for Referee opportunities."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from typing import cast

import psycopg

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
    boot_legacy_acceptance_spine,
)


def test_standing_referee_route_only_edit_renews_freshness() -> None:
    """A bounded Response Route edit renews a standing referee assertion."""
    ingestion = ControlledTelegramIngestionAdapter()
    classifier = ControlledModelAdapter()
    classifier.enable_open_match_primary_v4()
    resolver = ControlledLocationResolverAdapter()
    timezones = ControlledTimezoneDataAdapter()
    clock = FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    administrator_id = 49_580
    source_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_905_800,
    )
    ingestion.allow_public_username(
        address="@synthetic_refereeing_source",
        identity=source_identity,
        transport_boundary="channel-pts:49580",
    )
    timezones.add_source(version="controlled-tzdb-v1", timezones=("Europe/Moscow",))
    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="Saint Petersburg",
        resolution=_city_resolution(),
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=ingestion,
        model=classifier,
        location_resolver=resolver,
        timezone_data=timezones,
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        administrator_id=administrator_id,
    )

    body = (
        "Referee available for adult football matches in Saint Petersburg, "
        "7x7, head referee, paid."
    )
    result = _classifier_result(
        body=body,
        opportunity_type="referee_availability",
        evidence={
            "opportunity": "Referee available for adult football matches",
            "location": "in Saint Petersburg",
            "referee_availability": "Referee available",
            "event_types": "adult football matches",
            "team_formats": "7x7",
            "referee_roles": "head referee",
            "payment": "paid",
        },
        event_time=None,
        direction={"referee_availability": True},
        event_types=("match",),
    )
    candidates = result.output["candidates"]
    assert isinstance(candidates, list) and len(candidates) == 1
    candidate = candidates[0]
    assert isinstance(candidate, dict)
    # Force both accepted revisions to use only the bounded source route.
    candidate["response_routes"] = []
    classifier.return_for(body=body, result=result)

    old_route = "https://t.me/referee_route_old"
    new_route = "https://t.me/referee_route_new"
    create_time = datetime(2026, 8, 18, 9, 6, tzinfo=UTC)
    clock.advance_to(create_time)
    ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=49580),
        to_checkpoint=TelegramChannelCheckpoint(pts=49581),
        source_event_id="source-event:route-only-renewal:create",
        telegram_message_id=1590,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=body,
        event_time=create_time,
        source_publisher_id="publisher:route-only-renewal",
        source_author_dm_url=old_route,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()

    created = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id.endswith(":1590:revision:1")
    )
    created_cluster = next(
        cluster
        for cluster in system.exact_repost_clusters()
        if cluster.opportunity_type == "referee_availability"
    )
    assert created.response_route.kind == "direct_message"
    assert created.response_route.value == old_route
    assert created_cluster.freshness_renewed_at == create_time

    edit_time = datetime(2026, 8, 19, 9, 8, tzinfo=UTC)
    clock.advance_to(edit_time)
    ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=49581),
        to_checkpoint=TelegramChannelCheckpoint(pts=49582),
        source_event_id="source-event:route-only-renewal:edit",
        telegram_message_id=1590,
        revision=2,
        kind=SourceEventKind.EDIT,
        body=body,
        event_time=edit_time,
        source_publisher_id="publisher:route-only-renewal",
        source_author_dm_url=new_route,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()

    updated = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.opportunity_id == created.opportunity_id
    )
    updated_cluster = next(
        cluster
        for cluster in system.exact_repost_clusters()
        if cluster.opportunity_type == "referee_availability"
    )
    assert updated.source_message_revision_id.endswith(":1590:revision:2")
    assert updated.response_route.kind == "direct_message"
    assert updated.response_route.value == new_route
    assert updated_cluster.exact_repost_cluster_id == (
        created_cluster.exact_repost_cluster_id
    )
    assert updated_cluster.freshness_renewed_at == edit_time
    members = system.exact_repost_cluster_members(
        updated_cluster.exact_repost_cluster_id
    )
    assert len(members) == 1
    assert members[0].source_message_revision_id.endswith(":1590:revision:2")
    assert members[0].is_representative

    system.reset()


def test_dated_referee_route_only_edit_does_not_renew_freshness() -> None:
    """A dated referee edit remains governed by its event-bound cutoff."""
    ingestion = ControlledTelegramIngestionAdapter()
    classifier = ControlledModelAdapter()
    classifier.enable_open_match_primary_v4()
    resolver = ControlledLocationResolverAdapter()
    dates = ControlledDateInterpretationAdapter()
    timezones = ControlledTimezoneDataAdapter()
    clock = FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    administrator_id = 49_581
    source_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_905_810,
    )
    ingestion.allow_public_username(
        address="@synthetic_refereeing_source",
        identity=source_identity,
        transport_boundary="channel-pts:49581",
    )
    timezones.add_source(version="controlled-tzdb-v1", timezones=("Europe/Moscow",))
    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="Saint Petersburg",
        resolution=_city_resolution(),
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=ingestion,
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

    body = (
        "Referee available for an adult football match on 20 August 2026 "
        "at 19:00 in Saint Petersburg, 7x7, head referee, paid. "
        "Contact @referee_dated"
    )
    result = _classifier_result(
        body=body,
        opportunity_type="referee_availability",
        evidence={
            "opportunity": "Referee available for an adult football match",
            "event_time": "20 August 2026 at 19:00",
            "location": "in Saint Petersburg",
            "referee_availability": "Referee available",
            "event_types": "adult football match",
            "team_formats": "7x7",
            "referee_roles": "head referee",
            "payment": "paid",
        },
        event_time={
            "start_local_date": "2026-08-20",
            "end_local_date": "2026-08-20",
            "exact_local_time": "19:00",
            "iana_timezone": "Europe/Moscow",
        },
        direction={"referee_availability": True},
        event_types=("match",),
    )
    classifier.return_for(body=body, result=result)

    old_route = "https://t.me/referee_dated_route_old"
    new_route = "https://t.me/referee_dated_route_new"
    create_time = datetime(2026, 8, 18, 9, 6, tzinfo=UTC)
    clock.advance_to(create_time)
    ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=49581),
        to_checkpoint=TelegramChannelCheckpoint(pts=49582),
        source_event_id="source-event:dated-route-renewal:create",
        telegram_message_id=1591,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=body,
        event_time=create_time,
        source_publisher_id="publisher:dated-route-renewal",
        source_author_dm_url=old_route,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()

    created = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id.endswith(":1591:revision:1")
    )
    created_cluster = next(
        cluster
        for cluster in system.exact_repost_clusters()
        if cluster.opportunity_type == "referee_availability"
    )
    assert created.response_route.kind == "explicit_telegram_username"
    assert created.response_route.value == "@referee_dated"
    assert created_cluster.resolved_event_date == "2026-08-20/2026-08-20"
    assert created_cluster.freshness_renewed_at == create_time

    edit_time = datetime(2026, 8, 19, 9, 8, tzinfo=UTC)
    clock.advance_to(edit_time)
    ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=49582),
        to_checkpoint=TelegramChannelCheckpoint(pts=49583),
        source_event_id="source-event:dated-route-renewal:edit",
        telegram_message_id=1591,
        revision=2,
        kind=SourceEventKind.EDIT,
        body=body,
        event_time=edit_time,
        source_publisher_id="publisher:dated-route-renewal",
        source_author_dm_url=new_route,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()

    updated = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.opportunity_id == created.opportunity_id
    )
    updated_cluster = next(
        cluster
        for cluster in system.exact_repost_clusters()
        if cluster.opportunity_type == "referee_availability"
    )
    assert updated.source_message_revision_id.endswith(":1591:revision:2")
    assert updated.response_route.kind == "explicit_telegram_username"
    assert updated.response_route.value == "@referee_dated"
    assert updated_cluster.exact_repost_cluster_id == (
        created_cluster.exact_repost_cluster_id
    )
    assert updated_cluster.freshness_renewed_at == create_time
    members = system.exact_repost_cluster_members(
        updated_cluster.exact_repost_cluster_id
    )
    assert len(members) == 1
    assert members[0].source_message_revision_id.endswith(":1591:revision:2")
    assert members[0].is_representative

    system.reset()


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
    system = boot_legacy_acceptance_spine(
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
            "standing-availability-repost",
            "⚽ Referee available for adult football matches in Saint Petersburg, "
            "7x7, head referee, paid. Contact @referee_standing ⚽",
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
        if label.startswith("standing-availability"):
            source_publisher_id = "publisher:standing-availability"
        else:
            source_publisher_id = f"publisher:{label}"
        ingestion.add_channel_difference_event(
            identity=source_identity,
            from_checkpoint=TelegramChannelCheckpoint(pts=49570 + offset),
            to_checkpoint=TelegramChannelCheckpoint(pts=49571 + offset),
            source_event_id=f"source-event:refereeing:{label}",
            telegram_message_id=telegram_message_id,
            revision=1,
            kind=SourceEventKind.CREATE,
            body=body,
            event_time=datetime(2026, 8, 18, 9, 6 + offset, tzinfo=UTC),
            source_publisher_id=source_publisher_id,
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
    assert len(published) == 4
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
    standing_clusters = tuple(
        cluster
        for cluster in system.exact_repost_clusters()
        if cluster.opportunity_type == "referee_availability"
        and cluster.resolved_event_date == "standing"
    )
    assert len(standing_clusters) == 1
    standing_cluster = standing_clusters[0]
    assert standing_cluster.opportunity_type == "referee_availability"
    assert standing_cluster.resolved_event_date == "standing"
    assert isinstance(standing_cluster.representative_source_message_id, str)
    assert standing_cluster.representative_source_message_id.endswith(":1572")
    standing_members = system.exact_repost_cluster_members(
        standing_cluster.exact_repost_cluster_id
    )
    assert len(standing_members) == 2
    assert sum(member.is_representative for member in standing_members) == 1
    standing_representative = next(
        opportunity
        for opportunity in published
        if opportunity.source_message_revision_id.endswith(":1572:revision:1")
    )

    for offset, team_format in enumerate(("10x10", "11x11")):
        body = (
            "Referee available for adult football matches in Saint Petersburg, "
            f"{team_format}, head referee, paid. Contact @referee_standing"
        )
        classifier.return_for(
            body=body,
            result=_classifier_result(
                body=body,
                opportunity_type="referee_availability",
                evidence={
                    "opportunity": "Referee available for adult football matches",
                    "location": "in Saint Petersburg",
                    "referee_availability": "Referee available",
                    "event_types": "adult football matches",
                    "team_formats": team_format,
                    "referee_roles": "head referee",
                    "payment": "paid",
                },
                event_time=None,
                direction={"referee_availability": True},
                event_types=("match",),
                team_format=team_format,
            ),
        )
        telegram_message_id = 1580 + offset
        ingestion.add_channel_difference_event(
            identity=source_identity,
            from_checkpoint=TelegramChannelCheckpoint(pts=49574 + offset),
            to_checkpoint=TelegramChannelCheckpoint(pts=49575 + offset),
            source_event_id=f"source-event:refereeing:{team_format}",
            telegram_message_id=telegram_message_id,
            revision=1,
            kind=SourceEventKind.CREATE,
            body=body,
            event_time=datetime(2026, 8, 18, 10 + offset, tzinfo=UTC),
            source_publisher_id=f"publisher:{team_format}",
        )
        assert system.process_next_channel_telegram_difference(
            identity=source_identity,
            registry_generation=1,
        )
        system.process_opportunities_until_idle()
        large_format_opportunity = next(
            opportunity
            for opportunity in system.opportunities()
            if opportunity.source_message_revision_id.endswith(
                f":{telegram_message_id}:revision:1"
            )
        )
        publication = system.opportunity_publication_contracts(
            large_format_opportunity.source_message_revision_id
        )[-1]
        assert isinstance(publication.payload, dict)
        accepted_facts = publication.payload["accepted_facts"]
        assert isinstance(accepted_facts, dict)
        assert accepted_facts["team_formats"] == [team_format]

    _advance_to_complete_search(system, user_id=user_id)
    assert system.conversation_state(user_id).stage is ConversationStage.POST_CORE, (
        system.conversation_state(user_id),
        system.discovery_draft(user_id),
    )
    _configure_referee_details(system, user_id=user_id)
    system.submit_search(
        update_id="submit-referee-search",
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
    assert dict(results[-1].card_facts)["opportunity_id"] == (
        standing_representative.opportunity_id
    )
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
    _configure_referee_details(
        system,
        user_id=request_user_id,
        direction="refereeing_service_offer",
    )
    system.submit_search(
        update_id="submit-refereeing-service-offer",
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

    dated_availability = next(
        opportunity
        for opportunity in published
        if opportunity.source_message_revision_id.endswith(":1570:revision:1")
    )
    deletion_time = clock.now()
    ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=49576),
        to_checkpoint=TelegramChannelCheckpoint(pts=49577),
        source_event_id="source-event:refereeing:dated-availability-delete",
        telegram_message_id=1570,
        revision=2,
        kind=SourceEventKind.DELETE,
        body=None,
        event_time=deletion_time,
        source_publisher_id="publisher:dated-availability",
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()

    # The Bot Assistant's typed projection must honor the deletion barrier
    # before Recommendation consumes its suppression outbox.
    delete_first_results = system.results(completed[0].completed_search_id)
    deleted_result = next(
        result
        for result in delete_first_results
        if dict(result.card_facts)["opportunity_id"]
        == dated_availability.opportunity_id
    )
    assert dict(deleted_result.card_facts)["publication_state"] == "suppressed"
    assert "response_route_value" not in dict(deleted_result.card_facts)
    assert any(
        dict(result.card_facts)["publication_state"] == "active"
        for result in delete_first_results
        if dict(result.card_facts)["opportunity_id"]
        != dated_availability.opportunity_id
    )

    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        connection.execute(
            """
            UPDATE football_runtime.source_chat_registry
            SET enabled = FALSE, updated_at = %s
            WHERE peer_kind = %s
              AND telegram_chat_id = %s
              AND registry_generation = %s
            """,
            (clock.now(), source_identity.kind.value, source_identity.telegram_id, 1),
        )

    unavailable_results = system.results(completed[0].completed_search_id)
    assert unavailable_results
    assert all(
        dict(result.card_facts)["publication_state"] == "suppressed"
        for result in unavailable_results
    )
    assert all(
        "response_route_value" not in dict(result.card_facts)
        for result in unavailable_results
    )

    disabled_user_id = user_id + 2
    _advance_to_complete_search(system, user_id=disabled_user_id)
    _configure_referee_details(system, user_id=disabled_user_id)
    system.submit_search(
        update_id="submit-disabled-source-chat",
        telegram_user_id=disabled_user_id,
    )
    system.process_searches_until_idle()
    disabled_completed = system.completed_searches(disabled_user_id)
    assert len(disabled_completed) == 1
    assert system.results(disabled_completed[0].completed_search_id) == ()

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
    team_format: str = "7x7",
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
        "team_formats": [team_format],
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


def _configure_referee_details(
    system: AcceptanceSpine,
    *,
    user_id: int,
    direction: str = "referee_search",
) -> None:
    """Set one canonical referee-direction detail draft through public seams."""
    method_prefix = (
        "refereeing_service_offer"
        if direction == "refereeing_service_offer"
        else "referee_search"
    )
    details_attr = f"{method_prefix}_details"
    assert getattr(system.discovery_draft(user_id), details_attr) == ()
    getattr(system, f"open_{method_prefix}_details")(
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
        getattr(system, f"open_{method_prefix}_detail")(
            update_id=f"details-open:{detail_key}:{user_id}",
            telegram_user_id=user_id,
            detail_key=detail_key,
        )
        getattr(system, f"toggle_{method_prefix}_detail_value")(
            update_id=f"details-toggle:{detail_key}:{user_id}",
            telegram_user_id=user_id,
            value=value,
        )
        draft = system.discovery_draft(user_id)
        assert dict(getattr(draft, details_attr)).get(detail_key) is None
        assert getattr(draft, f"{method_prefix}_detail_draft") == (value,)
        getattr(system, f"commit_{method_prefix}_detail")(
            update_id=f"details-commit:{detail_key}:{user_id}",
            telegram_user_id=user_id,
        )
        committed_details[detail_key] = (value,)
        assert dict(getattr(system.discovery_draft(user_id), details_attr)) == (
            committed_details
        )

    getattr(system, f"open_{method_prefix}_detail")(
        update_id=f"details-open:times:{user_id}",
        telegram_user_id=user_id,
        detail_key="times",
    )
    getattr(system, f"open_{method_prefix}_exact_time")(
        update_id=f"details-exact-time-open:{user_id}",
        telegram_user_id=user_id,
    )
    getattr(system, f"submit_{method_prefix}_exact_time_text")(
        update_id=f"details-exact-time-submit:{user_id}",
        telegram_user_id=user_id,
        text="19:00",
    )
    committed_details["times"] = ("19:00",)
    assert dict(getattr(system.discovery_draft(user_id), details_attr)) == (
        committed_details
    )
    system.restart(RuntimeRole.BOT_ASSISTANT)
    assert dict(getattr(system.discovery_draft(user_id), details_attr)) == (
        committed_details
    )
