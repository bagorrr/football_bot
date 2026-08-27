"""Player Match Availability through the controlled PostgreSQL system seam."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import psycopg
import pytest

from modules.classifier_promotion import (
    describe_player_classifier_release,
    player_classifier_promotion_is_approved,
    promotion_gate_database_binding,
)
from modules.contracts import ContractEnvelope, ContractName, JsonValue, RuntimeRole
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


def test_forged_structural_promotion_claim_without_gate_stays_fail_closed() -> None:
    """A fully shaped forged claim cannot replace the privileged gate."""
    clock = FrozenClock(datetime(2026, 8, 27, 12, 0, tzinfo=UTC))
    admin_database_url = os.environ["TEST_DATABASE_URL"]
    system = boot_acceptance_spine(admin_database_url=admin_database_url, clock=clock)
    system.reset()

    release = describe_player_classifier_release()
    application_store = system._roles[RuntimeRole.APPLICATION].store

    system.record_player_classifier_promotion()
    legitimate_approval = system.player_classifier_promotion()
    assert legitimate_approval is not None
    assert player_classifier_promotion_is_approved(legitimate_approval)
    legitimate_evidence = legitimate_approval.get("evidence")
    assert isinstance(legitimate_evidence, dict)

    forged_evidence: dict[str, JsonValue] = deepcopy(legitimate_evidence)
    forged_gate_run_id = str(uuid4())
    forged_evidence["gate_run_id"] = forged_gate_run_id
    base_database_binding = cast(str, forged_evidence["base_database_binding"])
    release_binding = cast(str, forged_evidence["release_binding"])
    replay_execution_ids = cast(list[str], forged_evidence["replay_execution_ids"])
    replay_database_bindings = cast(
        list[str], forged_evidence["replay_database_bindings"]
    )
    forged_evidence["database_binding"] = promotion_gate_database_binding(
        gate_run_id=forged_gate_run_id,
        base_database_binding=base_database_binding,
        replay_database_bindings=replay_database_bindings,
        replay_execution_ids=replay_execution_ids,
        release_binding=release_binding,
    )
    forged_attestation_id = uuid4()
    forged_message_id = uuid4()
    forged_approval: dict[str, JsonValue] = deepcopy(legitimate_approval)
    forged_approval["attestation_id"] = str(forged_attestation_id)
    forged_approval["evidence"] = forged_evidence
    assert release.required_replays == 3
    assert player_classifier_promotion_is_approved(forged_approval)

    # Leave only the forged attestation and its matching Application outbox
    # payload in this database. The legitimate gate above supplies the exact
    # approval-shaped evidence, while the fresh gate identity has no protected
    # gate-run or replay rows of its own.
    system.reset()

    with psycopg.connect(admin_database_url) as connection:
        connection.execute(
            """
            INSERT INTO
                football_runtime.application_classifier_promotion_attestations (
                attestation_id, approval_message_id, release_name,
                contract_version, release_fingerprint, gate_run_id,
                execution_version, base_database_binding, database_binding,
                replay_execution_ids, release_binding, replay_database_bindings,
                canonical_replay_digests, replay_digests,
                failure_mode_observations, lifecycle_observations, evidence,
                recorded_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s,
                %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
                %s::jsonb, %s
            )
            """,
            (
                forged_attestation_id,
                forged_message_id,
                release.release_name,
                release.contract_version,
                release.release_fingerprint,
                forged_gate_run_id,
                forged_evidence["execution_version"],
                forged_evidence["base_database_binding"],
                forged_evidence["database_binding"],
                json.dumps(forged_evidence["replay_execution_ids"]),
                forged_evidence["release_binding"],
                json.dumps(forged_evidence["replay_database_bindings"]),
                json.dumps(forged_evidence["canonical_replay_digests"]),
                json.dumps(forged_evidence["replay_digests"]),
                json.dumps(forged_evidence["failure_mode_observations"]),
                json.dumps(forged_evidence["lifecycle_observations"]),
                json.dumps(forged_evidence),
                clock.now(),
            ),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.contract_outbox (
                message_id, producer_role, consumer_role, contract_name,
                contract_version, subject_id, subject_revision,
                idempotency_key, causation_id, correlation_id, recorded_at,
                payload, source_chat_admission_provenance_id
            ) VALUES (%s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)
            """,
            (
                forged_message_id,
                RuntimeRole.APPLICATION.value,
                ContractName.CLASSIFIER_RELEASE_PROMOTION_APPROVED.value,
                1,
                release.release_name,
                1,
                f"forged-classifier-promotion:{forged_attestation_id}",
                uuid4(),
                uuid4(),
                clock.now(),
                json.dumps(forged_approval),
            ),
        )

        protected_rows = connection.execute(
            """
            SELECT
                EXISTS(
                    SELECT 1
                    FROM football_runtime.application_classifier_promotion_gate_runs
                    WHERE gate_run_id = %s
                ),
                EXISTS(
                    SELECT 1
                    FROM football_runtime.application_classifier_promotion_replays
                    WHERE gate_run_id = %s
                )
            """,
            (forged_gate_run_id, forged_gate_run_id),
        ).fetchone()
    assert protected_rows == (False, False)

    assert system.player_classifier_promotion() is None
    with pytest.raises(ValueError, match="cannot publish"):
        application_store.publish_opportunity(
            incoming=cast(
                ContractEnvelope,
                SimpleNamespace(
                    payload={
                        "requested_model": "gpt-5.6-sol",
                        "effective_model": "gpt-5.6-sol",
                        "requested_reasoning_effort": "high",
                        "effective_reasoning_effort": "high",
                        "prompt_version": "player-match-primary-v1",
                        "schema_version": "source-message-classification-v3",
                        "glossary_version": "football-opportunity-glossary-v1",
                        "context_policy_version": "classifier-context-v1",
                        "routing_policy_version": "classifier-routing-player-v1",
                        "classification_status": "succeeded",
                    }
                ),
            ),
            opportunity={"opportunity_type": "player_match_availability"},
            outgoing=cast(ContractEnvelope, SimpleNamespace()),
            received_at=clock.now(),
        )


def test_player_search_publishes_confirmed_partial_and_possible_without_combining() -> (
    None
):
    telegram_ingestion = ControlledTelegramIngestionAdapter()
    classifier = ControlledModelAdapter()
    classifier.enable_primary_v3()
    resolver = ControlledLocationResolverAdapter()
    dates = ControlledDateInterpretationAdapter()
    timezones = ControlledTimezoneDataAdapter()
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    # Leave the initial draft inactive long enough for the shared source-chat
    # registration helper to reach the administration surface through the
    # public Menu seam.
    clock = FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    administrator_id = 49_520
    source_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_952_000,
    )
    telegram_ingestion.allow_public_username(
        address="@synthetic_player_source",
        identity=source_identity,
        transport_boundary="channel-pts:4952",
    )
    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="in whole city",
        resolution=LocationResolution(
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
                    whole_city=True,
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

    unapproved_body = (
        "Football match 20 August 2026 in whole city. We are 4 players "
        "available to play. Contact @player_unapproved."
    )
    classifier.return_for(
        body=unapproved_body,
        result=_player_classifier_result(
            candidate_key="unapproved",
            body=unapproved_body,
            count_evidence="We are 4 players available to play",
            exact_count=4,
            minimum_count=None,
            maximum_count=None,
            contact="@player_unapproved",
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4952),
        to_checkpoint=TelegramChannelCheckpoint(pts=4953),
        source_event_id="source-event:player-match:unapproved",
        telegram_message_id=5199,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=unapproved_body,
        event_time=datetime(2026, 8, 18, 9, 6, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    denied_revision = next(
        revision
        for revision in system.source_message_revisions()
        if revision.body == unapproved_body
    )
    assert not system.opportunities()
    assert (
        system.opportunity_publication_contracts(
            denied_revision.source_message_revision_id
        )
        == ()
    )
    assert system.player_classifier_promotion() is None

    release = describe_player_classifier_release()
    application_store = system._roles[RuntimeRole.APPLICATION].store
    with pytest.raises(ValueError, match="cannot publish"):
        application_store.publish_opportunity(
            incoming=cast(
                ContractEnvelope,
                SimpleNamespace(
                    payload={
                        "requested_model": "gpt-5.6-sol",
                        "effective_model": "gpt-5.6-sol",
                        "requested_reasoning_effort": "high",
                        "effective_reasoning_effort": "high",
                        "prompt_version": "player-match-primary-v1",
                        "schema_version": "source-message-classification-v3",
                        "glossary_version": "football-opportunity-glossary-v1",
                        "context_policy_version": "classifier-context-v1",
                        "routing_policy_version": "classifier-routing-player-v1",
                        "classification_status": "succeeded",
                    }
                ),
            ),
            opportunity={"opportunity_type": "player_match_availability"},
            outgoing=cast(ContractEnvelope, SimpleNamespace()),
            received_at=clock.now(),
        )

    system.record_player_classifier_promotion()
    first_approval = system.player_classifier_promotion()
    assert first_approval is not None
    assert player_classifier_promotion_is_approved(first_approval)

    valid_evidence = cast(dict[str, JsonValue], first_approval["evidence"])
    gate_run_id = valid_evidence["gate_run_id"]
    assert isinstance(gate_run_id, str)
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        replay_row = connection.execute(
            """
            SELECT execution_id, replay_database_binding, replay_digest, observations
            FROM football_runtime.application_classifier_promotion_replays
            WHERE gate_run_id = %s AND replay_number = 1
            """,
            (gate_run_id,),
        ).fetchone()
    assert replay_row is not None
    (
        original_execution_id,
        original_database_binding,
        original_digest,
        original_observation,
    ) = replay_row

    tampered_observation = cast(dict[str, JsonValue], original_observation).copy()
    tampered_observation["execution_id"] = str(uuid4())
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        connection.execute(
            """
            UPDATE football_runtime.application_classifier_promotion_replays
            SET execution_id = %s,
                replay_database_binding = %s,
                replay_digest = %s,
                observations = %s::jsonb
            WHERE gate_run_id = %s AND replay_number = 1
            """,
            (
                uuid4(),
                "0" * 64,
                "0" * 64,
                json.dumps(tampered_observation),
                gate_run_id,
            ),
        )
    assert system.player_classifier_promotion() is None
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        connection.execute(
            """
            UPDATE football_runtime.application_classifier_promotion_replays
            SET execution_id = %s,
                replay_database_binding = %s,
                replay_digest = %s,
                observations = %s::jsonb
            WHERE gate_run_id = %s AND replay_number = 1
            """,
            (
                original_execution_id,
                original_database_binding,
                original_digest,
                json.dumps(original_observation),
                gate_run_id,
            ),
        )

    assert system.player_classifier_promotion() == first_approval

    forged_replay_ids = [str(uuid4()) for _ in range(release.required_replays)]
    forged_evidence = deepcopy(valid_evidence)
    forged_evidence["replay_ids"] = cast(list[JsonValue], forged_replay_ids)
    forged_evidence["replay_execution_ids"] = cast(list[JsonValue], forged_replay_ids)
    forged_approval: dict[str, JsonValue] = {
        "release_name": release.release_name,
        "contract_version": release.contract_version,
        "release_fingerprint": release.release_fingerprint,
        "state": "approved",
        "evidence": forged_evidence,
    }
    assert player_classifier_promotion_is_approved(forged_approval)
    with pytest.raises(ValueError, match="Application-owned fresh gate"):
        application_store.record_classifier_release_promotion(
            release=forged_approval,
            recorded_at=clock.now(),
        )
    system.record_player_classifier_promotion()
    assert system.player_classifier_promotion() == first_approval

    cases = (
        (
            "exact-four",
            "Football match 20 August 2026 in whole city. We are 4 players "
            "available to play. Contact @player_four.",
            "We are 4 players available to play",
            4,
            None,
            None,
            "@player_four",
        ),
        (
            "exact-two",
            "Football match 20 August 2026 in whole city. We are 2 players "
            "available to play. Contact @player_two.",
            "We are 2 players available to play",
            2,
            None,
            None,
            "@player_two",
        ),
        (
            "range-two-five",
            "Football match 20 August 2026 in whole city. From 2 to 5 players "
            "are available to play. Contact @player_range.",
            "From 2 to 5 players are available to play",
            None,
            2,
            5,
            "@player_range",
        ),
        (
            "unknown-count",
            "Football match 20 August 2026 in whole city. We are available to "
            "play as a group. Contact @player_unknown.",
            "We are available to play as a group",
            None,
            None,
            None,
            "@player_unknown",
        ),
    )
    opportunity_ids: dict[str, str] = {}
    for offset, (
        label,
        body,
        count_evidence,
        exact_count,
        minimum_count,
        maximum_count,
        contact,
    ) in enumerate(cases, start=2):
        classifier.return_for(
            body=body,
            result=_player_classifier_result(
                candidate_key=label,
                body=body,
                count_evidence=count_evidence,
                exact_count=exact_count,
                minimum_count=minimum_count,
                maximum_count=maximum_count,
                contact=contact,
            ),
        )
        telegram_ingestion.add_channel_difference_event(
            identity=source_identity,
            from_checkpoint=TelegramChannelCheckpoint(pts=4952 + offset - 1),
            to_checkpoint=TelegramChannelCheckpoint(pts=4952 + offset),
            source_event_id=f"source-event:player-match:{label}",
            telegram_message_id=5200 + offset,
            revision=1,
            kind=SourceEventKind.CREATE,
            body=body,
            event_time=datetime(2026, 8, 18, 9, 6 + offset, tzinfo=UTC),
        )
        assert system.process_next_channel_telegram_difference(
            identity=source_identity,
            registry_generation=1,
        )
        system.process_opportunities_until_idle()
        opportunity = next(
            opportunity
            for opportunity in system.opportunities()
            if opportunity.response_route.value == contact
        )
        assert opportunity.opportunity_type == "player_match_availability"
        assert opportunity.publication_state == "active"
        opportunity_ids[label] = opportunity.opportunity_id

    _advance_to_player_search_details(
        system,
        bot_user_id=49_533,
    )
    system.open_player_search_detail(
        update_id="number:back-player-user:49533",
        telegram_user_id=49_533,
        detail_key="number_of_players",
    )
    system.back_from_game_search_detail(
        update_id="back:number-prompt:49533",
        telegram_user_id=49_533,
    )
    number_prompt_draft = system.discovery_draft(49_533)
    assert number_prompt_draft.user_intent is not None
    assert number_prompt_draft.user_intent.value == "player_search"
    assert not number_prompt_draft.player_search_number_prompt
    assert number_prompt_draft.editing_game_search_detail is None
    assert any(
        callback.startswith("details:open:number_of_players:")
        for row in telegram_delivery.messages[-1].button_rows
        for _, callback in row
    )

    _advance_to_player_search_details(
        system,
        bot_user_id=49_534,
    )
    system.open_player_search_detail(
        update_id="team-format:back-player-user:49534",
        telegram_user_id=49_534,
        detail_key="team_formats",
    )
    system.back_from_game_search_detail(
        update_id="back:submenu:49534",
        telegram_user_id=49_534,
    )
    submenu_draft = system.discovery_draft(49_534)
    assert submenu_draft.user_intent is not None
    assert submenu_draft.user_intent.value == "player_search"
    assert submenu_draft.editing_game_search_detail is None
    assert any(
        callback.startswith("details:open:team_formats:")
        for row in telegram_delivery.messages[-1].button_rows
        for _, callback in row
    )

    _advance_to_player_search_details(
        system,
        bot_user_id=49_535,
    )
    system.back_from_game_search_detail(
        update_id="back:player-hub:49535",
        telegram_user_id=49_535,
    )
    hub_draft = system.discovery_draft(49_535)
    assert hub_draft.user_intent is not None
    assert hub_draft.user_intent.value == "player_search"
    assert any(
        callback.startswith("details:open:")
        for row in telegram_delivery.messages[-1].button_rows
        for _, callback in row
    )

    _advance_to_player_search(
        system,
        bot_user_id=49_530,
        number_of_players=3,
    )
    first_search = system.completed_searches(49_530)[0]
    assert first_search.number_of_players == 3
    first_results = system.results(first_search.completed_search_id)
    assert [result.result_class for result in first_results] == [
        "confirmed_match",
        "partial_result",
        "possible_match",
        "possible_match",
    ]
    assert (
        dict(first_results[0].card_facts)["opportunity_id"]
        == opportunity_ids["exact-four"]
    )
    assert dict(first_results[1].card_facts)["available_player_contribution"] == "2/3"
    assert dict(first_results[2].card_facts)["available_player_count_min"] == "2"
    assert dict(first_results[2].card_facts)["available_player_count_max"] == "5"
    assert "available_player_count" not in dict(first_results[3].card_facts)
    english_cards = [
        message
        for message in telegram_delivery.messages
        if message.telegram_user_id == 49_530
    ]
    english_exact_card = next(
        message for message in english_cards if "@player_four" in message.text
    )
    assert english_exact_card.display_locale == "en"
    assert "⚽ Player Match Availability" in english_exact_card.text
    assert "4 players available" in english_exact_card.text

    _advance_to_player_search(
        system,
        bot_user_id=49_531,
        number_of_players=5,
    )
    second_search = system.completed_searches(49_531)[0]
    second_results = system.results(second_search.completed_search_id)
    assert [result.result_class for result in second_results] == [
        "partial_result",
        "partial_result",
        "possible_match",
        "possible_match",
    ]
    contributions = {
        dict(result.card_facts)["opportunity_id"]: dict(result.card_facts).get(
            "available_player_contribution"
        )
        for result in second_results
        if result.result_class == "partial_result"
    }
    assert contributions == {
        opportunity_ids["exact-four"]: "4/5",
        opportunity_ids["exact-two"]: "2/5",
    }
    second_cards = [
        message
        for message in telegram_delivery.messages
        if message.telegram_user_id == 49_531
    ]
    second_partial_card = next(
        message for message in second_cards if "@player_four" in message.text
    )
    assert "Partially matches: 4 of 5 players." in second_partial_card.text

    _advance_to_player_search(
        system,
        bot_user_id=49_532,
        locale="es",
        number_of_players=3,
    )
    spanish_search = system.completed_searches(49_532)[0]
    assert spanish_search.number_of_players == 3
    spanish_cards = [
        message
        for message in telegram_delivery.messages
        if message.telegram_user_id == 49_532
    ]
    spanish_exact_card = next(
        message for message in spanish_cards if "@player_four" in message.text
    )
    assert spanish_exact_card.display_locale == "es"
    assert "⚽ Disponibilidad de jugadores" in spanish_exact_card.text
    assert "4 jugadores disponibles" in spanish_exact_card.text

    _advance_to_player_search_details(
        system,
        bot_user_id=49_536,
    )
    system.open_player_search_detail(
        update_id="number:clear-player-user:49536",
        telegram_user_id=49_536,
        detail_key="number_of_players",
    )
    prompt_draft = system.discovery_draft(49_536)
    assert prompt_draft is not None
    prompt_message = telegram_delivery.messages[-1]
    assert prompt_message.button_rows[0] == (
        ("Any", f"details:number:any:{prompt_draft.screen_revision}"),
    )

    system.clear_player_search_number(
        update_id="number:clear:49536",
        telegram_user_id=49_536,
    )
    cleared_draft = system.discovery_draft(49_536)
    assert cleared_draft is not None
    assert cleared_draft.number_of_players is None
    assert not cleared_draft.player_search_number_prompt

    system.open_player_search_detail(
        update_id="number:reopen:49536",
        telegram_user_id=49_536,
        detail_key="number_of_players",
    )
    reopened_draft = system.discovery_draft(49_536)
    assert reopened_draft is not None
    assert reopened_draft.player_search_number_prompt
    assert telegram_delivery.messages[-1].button_rows[0][0][0] == "Any"
    system.clear_player_search_number(
        update_id="number:clear-after-reopen:49536",
        telegram_user_id=49_536,
    )
    system.submit_search(
        update_id="submit:unconstrained-player-user:49536",
        telegram_user_id=49_536,
    )
    system.process_searches_until_idle()
    unconstrained_search = system.completed_searches(49_536)[0]
    assert unconstrained_search.number_of_players is None
    assert all(
        result.result_class == "confirmed_match"
        for result in system.results(unconstrained_search.completed_search_id)
    )


def _register_source_chat(
    system: AcceptanceSpine,
    *,
    clock: FrozenClock,
    administrator_id: int,
) -> None:
    system.start_bot_user(
        update_id="start:player-admin",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:player-admin",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 8, 18, 9, 5, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:player-admin",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:player-admin",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:player-admin",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:player-admin",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add-source-chat:player-admin",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id="address:player-admin",
        telegram_user_id=administrator_id,
        address="@synthetic_player_source",
    )
    system.process_source_chat_registrations_until_idle()


def _advance_to_player_search(
    system: AcceptanceSpine,
    *,
    bot_user_id: int,
    number_of_players: int,
    locale: str = "en",
) -> None:
    _advance_to_player_search_details(
        system,
        bot_user_id=bot_user_id,
        locale=locale,
    )
    system.open_player_search_detail(
        update_id=f"number:player-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        detail_key="number_of_players",
    )
    system.submit_player_search_number_text(
        update_id=f"number-submit:player-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        text=str(number_of_players),
    )
    assert system.discovery_draft(bot_user_id).number_of_players == number_of_players
    system.submit_search(
        update_id=f"submit:player-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
    )
    system.process_searches_until_idle()


def _advance_to_player_search_details(
    system: AcceptanceSpine,
    *,
    bot_user_id: int,
    locale: str = "en",
) -> None:
    system.start_bot_user(
        update_id=f"start:player-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id=f"language:player-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        locale=locale,
    )
    system.select_direction(
        update_id=f"intent:player-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        direction="player_search",
    )
    system.submit_location_text(
        update_id=f"country:player-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id=f"city:player-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        text="Saint Petersburg",
    )
    system.submit_location_text(
        update_id=f"area:player-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        text="whole city",
    )
    system.submit_required_date_text(
        update_id=f"date:player-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        text="20 August",
    )
    system.open_player_search_details(
        update_id=f"details:player-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
    )


def _player_classifier_result(
    *,
    candidate_key: str,
    body: str,
    count_evidence: str,
    exact_count: int | None,
    minimum_count: int | None,
    maximum_count: int | None,
    contact: str,
) -> ClassifierAdapterResult:
    evidence: dict[str, JsonValue] = {
        "opportunity": count_evidence,
        "event_time": "20 August 2026",
        "location": "in whole city",
    }
    candidate: dict[str, JsonValue] = {
        "candidate_key": candidate_key,
        "opportunity_type": "player_match_availability",
        "evidence": evidence,
        "location": {
            "mention": "in whole city",
            "place_id": "city:ru:saint-petersburg",
            "country_id": "country:ru",
            "city_id": "city:ru:saint-petersburg",
        },
        "event_time": {
            "start_local_date": "2026-08-20",
            "end_local_date": "2026-08-20",
            "iana_timezone": "Europe/Moscow",
        },
        "response_routes": [
            {
                "kind": "explicit_telegram_username",
                "value": contact,
                "evidence": contact,
            }
        ],
    }
    if exact_count is not None:
        evidence["available_player_count"] = count_evidence
        candidate["available_player_count"] = exact_count
    elif minimum_count is not None and maximum_count is not None:
        evidence["available_player_count_min"] = count_evidence
        evidence["available_player_count_max"] = count_evidence
        candidate["available_player_count_min"] = minimum_count
        candidate["available_player_count_max"] = maximum_count
    return ClassifierAdapterResult(
        output={
            "schema_version": "source-message-classification-v3",
            "disposition": "accepted",
            "candidates": [{"source_context": body, **candidate}],
            "routing": {"reason_code": "accepted", "required_context": "none"},
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
