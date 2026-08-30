"""Opponent Search through the approved PostgreSQL-backed system seam."""

# ruff: noqa: RUF001 -- reviewed multilingual evidence is intentional.

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
    system = boot_legacy_acceptance_spine(
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
    assert "We have a venue" in card.text
    assert "Our team has a venue" not in card.text
    assert "needs clarification" not in card.text
    assert "Edited:" not in card.text


def test_edited_current_representative_reaches_persisted_facts_and_result_card() -> (
    None
):
    """An edited Source Message keeps Posted and adds Edited through public state."""
    telegram_ingestion = ControlledTelegramIngestionAdapter()
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    classifier = ControlledModelAdapter()
    resolver = ControlledLocationResolverAdapter()
    dates = ControlledDateInterpretationAdapter()
    timezones = ControlledTimezoneDataAdapter()
    clock = FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    administrator_id = 54_007
    source_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=5_400_700,
    )
    body = (
        "20 августа 2026 в 19:00 наша команда ищет соперника на Петроградской. "
        "The team has a venue. Пишите @edited_opponent_contact"
    )
    telegram_ingestion.allow_public_username(
        address="@synthetic_open_match_source",
        identity=source_identity,
        transport_boundary="channel-pts:5470",
    )
    result = _minimal_classifier_result(
        candidate_key="edited-opponent-request",
        body=body,
        response_routes=[
            {
                "kind": "explicit_telegram_username",
                "value": "@edited_opponent_contact",
                "evidence": "@edited_opponent_contact",
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
                                ("es", "Petrogradskaya"),
                                ("fr", "Petrogradskaya"),
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
    system = boot_legacy_acceptance_spine(
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
    posted_at = datetime(2026, 8, 18, 9, 5, tzinfo=UTC)
    edited_at = datetime(2026, 8, 18, 10, 5, tzinfo=UTC)
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=5470),
        to_checkpoint=TelegramChannelCheckpoint(pts=5471),
        source_event_id="source-event:edited-opponent:create",
        telegram_message_id=54701,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=body,
        event_time=posted_at,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    system.process_opportunities_until_idle()

    clock.advance_to(edited_at)
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=5471),
        to_checkpoint=TelegramChannelCheckpoint(pts=5472),
        source_event_id="source-event:edited-opponent:edit",
        telegram_message_id=54701,
        revision=2,
        kind=SourceEventKind.EDIT,
        body=body,
        event_time=edited_at,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    system.process_opportunities_until_idle()

    revision_id = "source-chat:channel:5400700:generation:1:message:54701:revision:2"
    publications = system.opportunity_publication_contracts(revision_id)
    publication_payloads = [
        publication.payload
        for publication in publications
        if isinstance(publication.payload, dict)
    ]
    active_payloads = [
        payload
        for payload in publication_payloads
        if payload["publication_state"] == "active"
    ]
    assert len(active_payloads) == 1
    persisted_facts = active_payloads[0]["accepted_facts"]
    assert isinstance(persisted_facts, dict)
    assert persisted_facts["source_posted_at"] == posted_at.isoformat()
    assert persisted_facts["source_edited_at"] == edited_at.isoformat()

    user_id = 54_008
    _advance_to_complete_opponent_search(system, bot_user_id=user_id)
    system.submit_search(update_id="submit:edited-opponent", telegram_user_id=user_id)
    system.process_searches_until_idle()
    card = telegram_delivery.messages[-1]
    assert "Posted: 18 August 2026 at 12:05" in card.text
    assert "Edited: 18 August 2026 at 13:05" in card.text


@pytest.mark.parametrize(
    ("locale", "expected_labels"),
    (
        (
            "en",
            (
                "Our team has a venue",
                "We need the opponent’s venue",
                "Arrange jointly",
                "Any",
            ),
        ),
        (
            "ru",
            (
                "У нашей команды есть площадка",
                "Нужна площадка соперника",
                "Организуем вместе",
                "Неважно",
            ),
        ),
        (
            "es",
            (
                "Nuestro equipo tiene campo",
                "Necesitamos el campo del rival",
                "Organizar juntos",
                "Cualquiera",
            ),
        ),
        (
            "fr",
            (
                "Notre équipe a un terrain",
                "Nous avons besoin du terrain adverse",
                "Organiser ensemble",
                "Peu importe",
            ),
        ),
    ),
)
def test_venue_provision_menu_is_one_answer_and_has_any_in_every_locale(
    locale: str,
    expected_labels: tuple[str, ...],
) -> None:
    """The public Bot Assistant menu exposes one-answer Venue Provision choices."""
    dates = ControlledDateInterpretationAdapter()
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
    timezones = ControlledTimezoneDataAdapter()
    timezones.add_source(
        version="controlled-tzdb-v1",
        timezones=("Europe/Moscow",),
    )
    delivery = ControlledTelegramDeliveryAdapter()
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC)),
        telegram_ingestion=ControlledTelegramIngestionAdapter(),
        telegram_delivery=delivery,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        date_interpretation=dates,
        timezone_data=timezones,
        telegram_admin_user_id=54_003,
    )
    system.reset()
    _advance_to_complete_opponent_search(
        system,
        bot_user_id=54_004,
        locale=locale,
    )
    system.open_opponent_search_details(
        update_id=f"details:venue-menu:{locale}",
        telegram_user_id=54_004,
    )
    system.open_opponent_search_detail(
        update_id=f"venue:menu:{locale}",
        telegram_user_id=54_004,
        detail_key="venue_provision",
    )

    menu = delivery.messages[-1]
    labels = tuple(row[0][0].removeprefix("✓ ") for row in menu.button_rows[:-1])
    callbacks = tuple(row[0][1] for row in menu.button_rows[:-1])
    assert labels == expected_labels
    assert all("Done" not in label for label in labels)
    assert all("toggle" not in callback for callback in callbacks)
    assert callbacks[-1].startswith("opponent-details:venue:any:")


def test_venue_provision_replaces_prior_choice_and_any_is_no_constraint() -> None:
    """Venue Provision replacement and clearing stay valid through submission."""
    dates = ControlledDateInterpretationAdapter()
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
    timezones = ControlledTimezoneDataAdapter()
    timezones.add_source(
        version="controlled-tzdb-v1",
        timezones=("Europe/Moscow",),
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC)),
        telegram_ingestion=ControlledTelegramIngestionAdapter(),
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        date_interpretation=dates,
        timezone_data=timezones,
        telegram_admin_user_id=54_005,
    )
    system.reset()
    user_id = 54_006
    _advance_to_complete_opponent_search(system, bot_user_id=user_id)

    system.open_opponent_search_details(
        update_id="details:venue-replacement",
        telegram_user_id=user_id,
    )
    system.open_opponent_search_detail(
        update_id="venue:first",
        telegram_user_id=user_id,
        detail_key="venue_provision",
    )
    system.select_opponent_search_venue_provision(
        update_id="venue:first-value",
        telegram_user_id=user_id,
        value="team_has_venue",
    )
    assert dict(system.discovery_draft(user_id).opponent_search_details) == {
        "venue_provision": ("team_has_venue",)
    }

    system.open_opponent_search_detail(
        update_id="venue:second",
        telegram_user_id=user_id,
        detail_key="venue_provision",
    )
    system.select_opponent_search_venue_provision(
        update_id="venue:second-value",
        telegram_user_id=user_id,
        value="needs_opponent_venue",
    )
    assert dict(system.discovery_draft(user_id).opponent_search_details) == {
        "venue_provision": ("needs_opponent_venue",)
    }

    system.open_opponent_search_detail(
        update_id="venue:any",
        telegram_user_id=user_id,
        detail_key="venue_provision",
    )
    system.select_opponent_search_venue_provision(
        update_id="venue:any-value",
        telegram_user_id=user_id,
        value=None,
    )
    draft = system.discovery_draft(user_id)
    assert "venue_provision" not in dict(draft.opponent_search_details)
    assert all(
        len(values) <= 1 for values in dict(draft.opponent_search_details).values()
    )

    system.submit_search(update_id="submit:venue-any", telegram_user_id=user_id)
    system.process_searches_until_idle()
    completed = system.completed_searches(user_id)
    assert len(completed) == 1
    assert "venue_provision" not in dict(completed[0].opponent_search_details)


def test_multilingual_venue_provision_evidence_reaches_publication() -> None:
    """Accept explicit supported-language venue facts and reject ambiguity."""
    telegram_ingestion = ControlledTelegramIngestionAdapter()
    classifier = ControlledModelAdapter()
    resolver = ControlledLocationResolverAdapter()
    timezones = ControlledTimezoneDataAdapter()
    clock = FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    administrator_id = 54_101
    source_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=5_410_100,
    )
    telegram_ingestion.allow_public_username(
        address="@synthetic_open_match_source",
        identity=source_identity,
        transport_boundary="channel-pts:5410",
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
                                ("es", "Petrogradskaya"),
                                ("fr", "Petrogradskaya"),
                            ),
                        ),
                    ),
                    glossary_version="location-glossary-v1",
                ),
            ),
        ),
    )
    timezones.add_source(
        version="controlled-tzdb-v1",
        timezones=("Europe/Moscow",),
    )
    localized_facts = (
        ("ru", "У команды есть площадка", "team_has_venue"),
        ("es", "Necesitamos el campo del rival", "needs_opponent_venue"),
        ("fr", "Nous trouverons un terrain ensemble", "arrange_jointly"),
    )
    rejected_facts = (
        ("missing", None, None),
        ("absent", None, "team_has_venue"),
        (
            "ambiguous",
            "У команды есть площадка или нужна площадка соперника",
            "team_has_venue",
        ),
    )

    def configure_result(
        *, body: str, candidate_key: str, venue_evidence: str | None, venue: str | None
    ) -> None:
        result = _minimal_classifier_result(
            candidate_key=candidate_key,
            body=body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": f"@opponent_{candidate_key.replace('-', '')}",
                    "evidence": f"Пишите @opponent_{candidate_key.replace('-', '')}",
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
        evidence.pop("open_places", None)
        evidence["opponent_request"] = "наша команда ищет соперника"
        if venue is not None:
            candidate["venue_provision"] = venue
            if venue_evidence is not None:
                evidence["venue_provision"] = venue_evidence
        classifier.return_for(body=body, result=result)

    records = tuple(localized_facts) + rejected_facts
    for index, (language, venue_evidence, venue) in enumerate(records, start=1):
        candidate_key = f"opponent-{language}"
        contact = f"@opponent_{candidate_key.replace('-', '')}"
        body = (
            "20 августа 2026 в 19:00 наша команда ищет соперника на Петроградской. "
            f"{venue_evidence + '. ' if venue_evidence else ''}"
            f"Пишите {contact}"
        )
        configure_result(
            body=body,
            candidate_key=candidate_key,
            venue_evidence=venue_evidence,
            venue=venue,
        )
        telegram_ingestion.add_channel_difference_event(
            identity=source_identity,
            from_checkpoint=TelegramChannelCheckpoint(pts=5410 + index - 1),
            to_checkpoint=TelegramChannelCheckpoint(pts=5410 + index),
            source_event_id=f"source-event:multilingual-opponent:{language}",
            telegram_message_id=5410 + index,
            revision=1,
            kind=SourceEventKind.CREATE,
            body=body,
            event_time=datetime(2026, 8, 18, 9, index, tzinfo=UTC),
        )

    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telegram_ingestion,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
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
    system.configure_source_chat_classifier_context(
        identity=source_identity,
        registry_generation=1,
        iana_timezone="Europe/Moscow",
        country_id="country:ru",
        city_id="city:ru:saint-petersburg",
    )
    for _ in records:
        assert system.process_next_channel_telegram_difference(
            identity=source_identity,
            registry_generation=1,
        )
    system.process_opportunities_until_idle()

    opportunities = system.opportunities()
    assert len(opportunities) == 4
    assert {opportunity.opportunity_type for opportunity in opportunities} == {
        "opponent_request"
    }
    accepted_venues: set[object] = set()
    for opportunity in opportunities:
        publications = system.opportunity_publication_contracts(
            opportunity.source_message_revision_id
        )
        assert len(publications) == 1
        payload = publications[0].payload
        assert isinstance(payload, dict)
        accepted_facts = payload["accepted_facts"]
        assert isinstance(accepted_facts, dict)
        accepted_venues.add(accepted_facts.get("venue_provision"))
    assert accepted_venues == {
        "team_has_venue",
        "needs_opponent_venue",
        "arrange_jointly",
        None,
    }


def _advance_to_complete_opponent_search(
    system: AcceptanceSpine,
    *,
    bot_user_id: int,
    locale: str = "en",
    date_text: str = "20 August",
) -> None:
    """Drive the public onboarding seam to an Opponent Search Details draft."""
    system.start_bot_user(
        update_id=f"start:opponent-ui:{bot_user_id}",
        telegram_user_id=bot_user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id=f"language:opponent-ui:{bot_user_id}",
        telegram_user_id=bot_user_id,
        locale=locale,
    )
    system.select_direction(
        update_id=f"branch:opponent-ui:{bot_user_id}",
        telegram_user_id=bot_user_id,
        direction="competition_search",
    )
    system.select_direction(
        update_id=f"intent:opponent-ui:{bot_user_id}",
        telegram_user_id=bot_user_id,
        direction="opponent_search",
    )
    system.submit_location_text(
        update_id=f"country:opponent-ui:{bot_user_id}",
        telegram_user_id=bot_user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id=f"city:opponent-ui:{bot_user_id}",
        telegram_user_id=bot_user_id,
        text="Saint Petersburg",
    )
    system.submit_location_text(
        update_id=f"area:opponent-ui:{bot_user_id}",
        telegram_user_id=bot_user_id,
        text="whole city",
    )
    system.submit_required_date_text(
        update_id=f"date:opponent-ui:{bot_user_id}",
        telegram_user_id=bot_user_id,
        text=date_text,
    )
