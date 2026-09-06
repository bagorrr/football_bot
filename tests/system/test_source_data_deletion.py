"""Source Author and Source Chat deletion through the public acceptance seam."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import psycopg
import pytest

from modules.contracts import RuntimeRole
from modules.domain import (
    ConversationStage,
    SourceEventKind,
    TelegramAccountCheckpoint,
    TelegramMessage,
    TelegramPeerIdentity,
    TelegramPeerKind,
)
from modules.postgres_adapter import PostgresRoleStore, _scrub_source_scope_outbox
from modules.testkit import (
    AcceptanceSpine,
    ControlledLocationResolverAdapter,
    ControlledModelAdapter,
    ControlledTelegramDeliveryAdapter,
    ControlledTelegramIngestionAdapter,
    FrozenClock,
    boot_legacy_acceptance_spine,
)


def test_source_data_deletion_ui_is_bounded_and_revision_bound() -> None:
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    administrator_id = 46_802
    delivery = ControlledTelegramDeliveryAdapter()
    system = _new_system(
        clock=clock,
        administrator_id=administrator_id,
        telegram_delivery=delivery,
    )
    system.reset()
    _open_deletion_requests(
        system,
        clock=clock,
        administrator_id=administrator_id,
        prefix="ui",
    )

    list_message = delivery.messages[-1]
    assert len(_callback(list_message, "sdd:intake:")) < 64
    system.select_source_data_deletion_action(
        update_id="ui:open-intake",
        telegram_user_id=administrator_id,
        action=_callback(list_message, "sdd:intake:"),
    )
    assert system.conversation_state(administrator_id).stage is (
        ConversationStage.SOURCE_DATA_DELETION_INPUT
    )
    input_revision = system.conversation_state(administrator_id).screen_revision
    assert "Do not include a body" in delivery.messages[-1].text

    system.submit_source_data_deletion_request(
        update_id="ui:submit-intake",
        telegram_user_id=administrator_id,
        request_id="deletion-request:ui",
        source_author_telegram_id=78_902,
        source_chat_key="source-chat:chat:4680102",
        support_case_pointer="support-case:ui",
        screen_revision=input_revision,
    )
    assert system.process_next_contract_handoff(RuntimeRole.APPLICATION)
    request = system.source_data_deletion_requests()[0]
    assert request.request_id == "deletion-request:ui"
    assert request.support_case_pointer == "support-case:ui"

    _refresh_deletion_requests(
        system,
        administrator_id=administrator_id,
        prefix="ui:refresh-after-intake",
    )
    approve_callback = _callback(delivery.messages[-1], "sdd:approve:")
    assert "deletion-request:ui" not in approve_callback
    system.select_source_data_deletion_action(
        update_id="ui:approve",
        telegram_user_id=administrator_id,
        action=approve_callback,
    )
    assert system.process_next_contract_handoff(RuntimeRole.APPLICATION)

    _refresh_deletion_requests(
        system,
        administrator_id=administrator_id,
        prefix="ui:refresh-after-approval",
    )
    review_callback = _callback(delivery.messages[-1], "sdd:review:")
    system.select_source_data_deletion_action(
        update_id="ui:review",
        telegram_user_id=administrator_id,
        action=review_callback,
    )
    assert system.conversation_state(administrator_id).stage is (
        ConversationStage.SOURCE_DATA_DELETION_REVIEW
    )
    review_message = delivery.messages[-1]
    assert "source_author=78902" in review_message.text
    assert "source-chat:chat:4680102" in review_message.text
    assert "support-case:ui" in review_message.text
    assert "source body" not in review_message.text

    system.select_source_data_deletion_action(
        update_id="ui:confirm-start",
        telegram_user_id=administrator_id,
        action=_callback(review_message, "sdd:start:"),
    )
    assert system.process_next_contract_handoff(RuntimeRole.APPLICATION)
    system.process_source_data_deletion_until_idle()
    assert system.source_data_deletion_requests()[0].status.value == (
        "awaiting_completion"
    )

    _refresh_deletion_requests(
        system,
        administrator_id=administrator_id,
        prefix="ui:refresh-before-notify",
    )
    notify_callback = _callback(delivery.messages[-1], "sdd:notify:")
    system.select_source_data_deletion_action(
        update_id="ui:notify",
        telegram_user_id=administrator_id,
        action=notify_callback,
    )
    assert system.process_next_contract_handoff(RuntimeRole.APPLICATION)

    _refresh_deletion_requests(
        system,
        administrator_id=administrator_id,
        prefix="ui:refresh-before-complete",
    )
    complete_callback = _callback(delivery.messages[-1], "sdd:complete:")
    system.select_source_data_deletion_action(
        update_id="ui:complete-input",
        telegram_user_id=administrator_id,
        action=complete_callback,
    )
    completion_revision = system.conversation_state(administrator_id).screen_revision
    system.submit_source_data_deletion_completion(
        update_id="ui:complete",
        telegram_user_id=administrator_id,
        request_id=request.request_id,
        completion_outcome="completed",
        completion_proof_pointer="support-proof:ui",
        screen_revision=completion_revision,
    )
    assert system.process_next_contract_handoff(RuntimeRole.APPLICATION)
    assert system.source_data_deletion_requests()[0].status.value == "completed"
    assert any(
        event.request_id == request.request_id
        and event.actor_telegram_id == administrator_id
        and event.reason_code == "completion_completed"
        for event in system.source_data_audit()
    )
    assert all("source body" not in message.text for message in delivery.messages)


def test_source_data_deletion_captures_pending_and_racing_ingestion() -> None:
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    administrator_id = 46_803
    author_id = 78_903
    chat_id = 4_680_103
    telethon = ControlledTelegramIngestionAdapter()
    identity = TelegramPeerIdentity(kind=TelegramPeerKind.CHAT, telegram_id=chat_id)
    telethon.allow_public_username(
        address="@source_deletion_fixture",
        identity=identity,
        transport_boundary="chat-sequence:4680",
    )
    system = _new_system(
        clock=clock,
        administrator_id=administrator_id,
        telegram_ingestion=telethon,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        administrator_id=administrator_id,
    )
    event_time = datetime(2026, 9, 1, 12, 1, tzinfo=UTC)
    telethon.add_account_difference_event(
        from_checkpoint=TelegramAccountCheckpoint(
            pts=4_690,
            qts=469,
            seq=4_690,
            date=datetime(2026, 9, 1, 11, 59, tzinfo=UTC),
        ),
        to_checkpoint=TelegramAccountCheckpoint(
            pts=4_691,
            qts=470,
            seq=4_691,
            date=event_time,
        ),
        identity=identity,
        registry_generation=1,
        source_event_id="source-event:pending-capture",
        telegram_message_id=103,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="pending source body must be scrubbed atomically",
        event_time=event_time,
        source_author_telegram_id=author_id,
    )
    system.initialize_account_ingestion_checkpoint(
        TelegramAccountCheckpoint(
            pts=4_690,
            qts=469,
            seq=4_690,
            date=datetime(2026, 9, 1, 11, 59, tzinfo=UTC),
        )
    )
    clock.advance_to(event_time)
    assert system.process_next_account_telegram_difference()
    assert system.source_messages() == ()
    assert system.source_events()[0].body == (
        "pending source body must be scrubbed atomically"
    )

    request = system.create_source_data_deletion_request(
        request_id="deletion-request:pending-capture",
        source_author_telegram_id=author_id,
        source_chat_key=f"source-chat:chat:{chat_id}",
        support_case_pointer="support-case:pending-capture",
        received_at=event_time,
    )
    assert system.decide_source_data_deletion_request(
        request_id=request.request_id,
        decision="approve",
        decision_reason=None,
        decided_by=administrator_id,
        decided_at=event_time,
    )
    effective_at = event_time + timedelta(minutes=1)
    clock.advance_to(effective_at)
    with ThreadPoolExecutor(max_workers=2) as executor:
        source_event_future = executor.submit(system.process_next_source_event)
        begin_future = executor.submit(
            system.begin_source_data_deletion_request,
            request_id=request.request_id,
            effective_at=effective_at,
        )
        assert source_event_future.result() is True
        assert begin_future.result() is True
    source_message_id = f"source-chat:chat:{chat_id}:generation:1:message:103"
    source_revision_id = f"{source_message_id}:revision:1"
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        target_row = connection.execute(
            """
            SELECT target_source_message_ids, target_source_message_revision_ids,
                   target_source_event_ids
            FROM football_runtime.application_source_data_deletion_requests
            WHERE request_id = %s
            """,
            (request.request_id,),
        ).fetchone()
    assert target_row == (
        [source_message_id],
        [source_revision_id],
        ["source-event:pending-capture"],
    )
    assert system.source_events()[0].body is None
    assert system.source_events()[0].bounded_metadata["source_message_url"] is None
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        payload = connection.execute(
            """
            SELECT payload
            FROM football_runtime.contract_outbox
            WHERE contract_name = 'SourceEventRecorded'
              AND payload ->> 'source_event_id' = 'source-event:pending-capture'
            """
        ).fetchone()
    assert payload is not None
    assert payload[0]["body"] is None
    assert payload[0]["bounded_metadata"]["source_message_url"] is None
    system.process_source_data_deletion_until_idle()
    assert system.source_messages() == ()
    assert system.source_events() == ()


def test_source_data_deletion_reminder_delivery_and_failure_rearm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    administrator_id = 46_804
    delivery = ControlledTelegramDeliveryAdapter()
    system = _new_system(
        clock=clock,
        administrator_id=administrator_id,
        telegram_delivery=delivery,
    )
    system.reset()
    system.start_bot_user(
        update_id="reminder:start",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    request = system.create_source_data_deletion_request(
        request_id="deletion-request:reminder",
        source_author_telegram_id=78_904,
        source_chat_key="source-chat:chat:4680104",
        support_case_pointer="support-case:reminder",
    )
    assert request.next_reminder_at is not None
    first_due = request.next_reminder_at
    clock.advance_to(first_due)
    assert system.remind_source_data_deletion_requests() == 1
    reminded = system.source_data_deletion_requests()[0]
    assert reminded.reminder_count == 1
    assert reminded.next_reminder_at == first_due + timedelta(days=1)
    assert system.process_next_contract_handoff(RuntimeRole.BOT_ASSISTANT)
    assert system.deliver_next_bot_message()
    reminder_message = delivery.messages[-1]
    assert reminder_message.delivery_id == (
        "source-data-deletion-reminder:deletion-request:reminder:1"
    )
    assert any(
        label == "Open deletion requests"
        for row in reminder_message.button_rows
        for label, _callback in row
    )
    assert system.remind_source_data_deletion_requests(as_of=first_due) == 0

    failure_request = system.create_source_data_deletion_request(
        request_id="deletion-request:rearm",
        source_author_telegram_id=78_905,
        source_chat_key="source-chat:chat:4680105",
        support_case_pointer="support-case:rearm",
    )
    assert system.decide_source_data_deletion_request(
        request_id=failure_request.request_id,
        decision="approve",
        decision_reason=None,
        decided_by=administrator_id,
        decided_at=clock.now(),
    )
    assert system.begin_source_data_deletion_request(
        request_id=failure_request.request_id,
        effective_at=clock.now(),
    )

    def fail_bot_cleanup(*_args: object, **_kwargs: object) -> int:
        raise RuntimeError("controlled Bot owner failure")

    monkeypatch.setattr(
        "modules.postgres_adapter._cleanup_bot_source_scope",
        fail_bot_cleanup,
    )
    assert system.process_next_contract_handoff(RuntimeRole.BOT_ASSISTANT)
    assert system.process_next_contract_handoff(RuntimeRole.APPLICATION)
    failed = system.source_data_deletion_requests()[1]
    assert failed.status.value == "execution_error"
    assert failed.next_reminder_at == clock.now()


def test_bot_source_data_cleanup_removes_result_context_and_retained_text() -> None:
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    administrator_id = 46_805
    author_id = 78_906
    chat_id = 4_680_106
    telethon = ControlledTelegramIngestionAdapter()
    identity = TelegramPeerIdentity(kind=TelegramPeerKind.CHAT, telegram_id=chat_id)
    telethon.allow_public_username(
        address="@source_deletion_fixture",
        identity=identity,
        transport_boundary="chat-sequence:4680",
    )
    system = _new_system(
        clock=clock,
        administrator_id=administrator_id,
        telegram_ingestion=telethon,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        administrator_id=administrator_id,
    )
    source_revision_id = _ingest_source_event(
        system,
        telethon=telethon,
        identity=identity,
        clock=clock,
        author_id=author_id,
        source_event_id="source-event:bot-cleanup",
        telegram_message_id=106,
        body="source body for Bot cleanup",
    )[1]
    completed_search_id = "completed-search:bot-cleanup"
    result_id = "result:bot-cleanup:1"
    presentation_delivery_id = "result-current:bot-cleanup"
    recorded_at = clock.now()
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        connection.execute("SET SESSION AUTHORIZATION football_recommendation")
        connection.execute(
            """
            INSERT INTO football_runtime.recommendation_completed_searches (
                completed_search_id, telegram_user_id, search_update_id,
                user_intent, country_id, city_id, sub_city_area_ids,
                whole_city, required_date, completed_at
            ) VALUES (%s, %s, %s, 'tournament_search', 'country:ru',
                      'city:moscow', '[]', true, NULL, %s)
            """,
            (
                completed_search_id,
                administrator_id,
                "search-update:bot-cleanup",
                recorded_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.recommendation_results (
                result_id, completed_search_id, absolute_position, result_class,
                card_facts
            ) VALUES (%s, %s, 1, 'confirmed_match', %s::jsonb)
            """,
            (
                result_id,
                completed_search_id,
                json.dumps(
                    {
                        "opportunity_id": "opportunity:bot-cleanup",
                        "source_message_revision_id": source_revision_id,
                    }
                ),
            ),
        )
        connection.execute("RESET SESSION AUTHORIZATION")
        connection.execute(
            """
            INSERT INTO football_runtime.bot_message_outbox (
                delivery_id, telegram_user_id, display_locale, screen_revision,
                message_text, button_rows, recorded_at
            ) VALUES (%s, %s, 'en', 3, %s, '[]'::jsonb, %s)
            """,
            (
                presentation_delivery_id,
                administrator_id,
                "retained result",
                recorded_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.bot_search_presentations (
                delivery_id, telegram_user_id, completed_search_id,
                current_result_id, absolute_position, accepted_at
            ) VALUES (%s, %s, %s, %s, 1, %s)
            """,
            (
                presentation_delivery_id,
                administrator_id,
                completed_search_id,
                result_id,
                recorded_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.bot_active_result_contexts (
                telegram_user_id, completed_search_id, current_result_id,
                absolute_position, screen_revision, activated_at
            ) VALUES (%s, %s, %s, 1, 3, %s)
            """,
            (administrator_id, completed_search_id, result_id, recorded_at),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.bot_result_conversation_messages (
                message_id, telegram_user_id, completed_search_id, turn_id,
                speaker, message_text, recorded_at
            ) VALUES
                ('bot-cleanup:user', %s, %s, 'turn:bot-cleanup', 'user',
                 'retained source body', %s),
                ('bot-cleanup:assistant', %s, %s, 'turn:bot-cleanup', 'assistant',
                 'retained assistant text', %s)
            """,
            (
                administrator_id,
                completed_search_id,
                recorded_at,
                administrator_id,
                completed_search_id,
                recorded_at,
            ),
        )

    request = system.create_source_data_deletion_request(
        request_id="deletion-request:bot-cleanup",
        source_author_telegram_id=author_id,
        source_chat_key=f"source-chat:chat:{chat_id}",
        support_case_pointer="support-case:bot-cleanup",
    )
    assert system.decide_source_data_deletion_request(
        request_id=request.request_id,
        decision="approve",
        decision_reason=None,
        decided_by=administrator_id,
        decided_at=clock.now(),
    )
    assert system.begin_source_data_deletion_request(
        request_id=request.request_id,
        effective_at=clock.now(),
    )
    system.process_source_data_deletion_until_idle()
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        counts = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM football_runtime.bot_active_result_contexts
                 WHERE completed_search_id = %s),
                (SELECT count(*) FROM football_runtime.bot_search_presentations
                 WHERE completed_search_id = %s),
                (SELECT count(*)
                 FROM football_runtime.bot_result_conversation_messages
                 WHERE completed_search_id = %s),
                (SELECT count(*) FROM football_runtime.bot_message_outbox
                 WHERE delivery_id = %s)
            """,
            (
                completed_search_id,
                completed_search_id,
                completed_search_id,
                presentation_delivery_id,
            ),
        ).fetchone()
    assert counts == (0, 0, 0, 0)


def test_source_data_deletion_scrubs_nested_opportunity_batches() -> None:
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    system = _new_system(clock=clock, administrator_id=46_807)
    system.reset()
    source_revision_id = "source-chat:chat:4680107:generation:1:message:107:revision:1"
    target_opportunity_id = "opportunity:nested-target"
    target_opportunity_revision_id = "opportunity:nested-target:revision:1"
    untouched_opportunity_id = "opportunity:nested-untouched"
    payloads = {
        3: {
            "publication_state": "active",
            "opportunities": [
                {
                    "opportunity_id": target_opportunity_id,
                    "opportunity_revision_id": target_opportunity_revision_id,
                    "source_message_revision_id": source_revision_id,
                    "accepted_facts": {"private": "nested fact"},
                    "evidence": {"private": "nested evidence"},
                    "response_route": {"kind": "url", "value": "https://private"},
                },
                {
                    "opportunity_id": untouched_opportunity_id,
                    "accepted_facts": {"keep": True},
                },
            ],
        },
        5: {
            "publication_state": "active",
            "opportunities": [
                {
                    "opportunity_id": target_opportunity_id,
                    "opportunity_revision_id": target_opportunity_revision_id,
                    "source_message_revision_id": source_revision_id,
                    "accepted_facts": {"private": "coaching fact"},
                    "evidence": {"private": "coaching evidence"},
                    "response_route": {"kind": "url", "value": "https://coaching"},
                },
            ],
        },
    }
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        for version, payload in payloads.items():
            message_id = uuid4()
            connection.execute(
                """
                INSERT INTO football_runtime.contract_outbox (
                    message_id, producer_role, consumer_role, contract_name,
                    contract_version, subject_id, subject_revision,
                    idempotency_key, causation_id, correlation_id, recorded_at,
                    payload
                ) VALUES (%s, 'application', 'recommendation',
                          'OpportunityPublicationChanged', %s, %s, 1, %s,
                          %s, %s, %s, %s::jsonb)
                """,
                (
                    message_id,
                    version,
                    f"batch:{version}",
                    f"batch-idempotency:{version}",
                    message_id,
                    message_id,
                    clock.now(),
                    json.dumps(payload),
                ),
            )
    application_store = cast(
        PostgresRoleStore,
        system._roles[RuntimeRole.APPLICATION].store,
    )
    application_url = application_store._database_url
    with psycopg.connect(application_url) as connection:
        assert (
            _scrub_source_scope_outbox(
                connection,
                producer_role=RuntimeRole.APPLICATION,
                source_message_ids=(),
                source_message_revision_ids=(source_revision_id,),
                opportunity_ids=(target_opportunity_id,),
                opportunity_revision_ids=(target_opportunity_revision_id,),
            )
            == 2
        )
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        rows = connection.execute(
            """
            SELECT contract_version, payload
            FROM football_runtime.contract_outbox
            WHERE idempotency_key LIKE 'batch-idempotency:%'
            ORDER BY contract_version
            """
        ).fetchall()
    assert len(rows) == 2
    for version, payload in rows:
        item = payload["opportunities"][0]
        assert "accepted_facts" not in item
        assert "evidence" not in item
        assert item["response_route"] == {"kind": "unavailable", "value": ""}
        if version == 3:
            assert payload["opportunities"][1] == {
                "opportunity_id": untouched_opportunity_id,
                "accepted_facts": {"keep": True},
            }


def test_source_data_deletion_audit_is_body_free_and_expires_after_90_days() -> None:
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    system = _new_system(clock=clock, administrator_id=46_808)
    system.reset()
    request = system.create_source_data_deletion_request(
        request_id="deletion-request:audit-retention",
        source_author_telegram_id=78_908,
        source_chat_key="source-chat:chat:4680108",
        support_case_pointer="support-case:audit-retention",
    )
    lifecycle = [
        event
        for event in system.source_data_audit()
        if event.request_id == request.request_id
    ]
    assert lifecycle
    assert all(
        event.action == "state_changed"
        and event.reason_code == "request_created"
        and event.notification_status == "pending"
        and event.expires_at == event.recorded_at + timedelta(days=90)
        for event in lifecycle
    )
    clock.advance_to(request.received_at + timedelta(days=90, seconds=1))
    system.cleanup_expired_source_data()
    assert not [
        event
        for event in system.source_data_audit()
        if event.request_id == request.request_id
    ]


def _new_system(
    *,
    clock: FrozenClock,
    administrator_id: int,
    telegram_ingestion: ControlledTelegramIngestionAdapter | None = None,
    telegram_delivery: ControlledTelegramDeliveryAdapter | None = None,
) -> AcceptanceSpine:
    return boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=(telegram_ingestion or ControlledTelegramIngestionAdapter()),
        telegram_delivery=telegram_delivery or ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=administrator_id,
    )


def _open_administration(
    system: AcceptanceSpine,
    *,
    clock: FrozenClock,
    administrator_id: int,
    prefix: str,
) -> None:
    system.start_bot_user(
        update_id=f"{prefix}:start",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id=f"{prefix}:language",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id=f"{prefix}:menu",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id=f"{prefix}:settings",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id=f"{prefix}:administration",
        telegram_user_id=administrator_id,
        action="administration",
    )


def _open_deletion_requests(
    system: AcceptanceSpine,
    *,
    clock: FrozenClock,
    administrator_id: int,
    prefix: str,
) -> None:
    _open_administration(
        system,
        clock=clock,
        administrator_id=administrator_id,
        prefix=prefix,
    )
    system.select_administration_action(
        update_id=f"{prefix}:deletion",
        telegram_user_id=administrator_id,
        action="source-data-deletion",
    )
    assert system.conversation_state(administrator_id).stage is (
        ConversationStage.SOURCE_DATA_DELETION_REQUESTS
    )


def _refresh_deletion_requests(
    system: AcceptanceSpine,
    *,
    administrator_id: int,
    prefix: str,
) -> None:
    current = system.conversation_state(administrator_id)
    assert current.stage is ConversationStage.SOURCE_DATA_DELETION_REQUESTS
    system.go_back(
        update_id=f"{prefix}:back",
        telegram_user_id=administrator_id,
        screen_revision=current.screen_revision,
    )
    system.select_administration_action(
        update_id=f"{prefix}:deletion",
        telegram_user_id=administrator_id,
        action="source-data-deletion",
    )


def _callback(message: TelegramMessage, prefix: str) -> str:
    for row in message.button_rows:
        for _label, callback in row:
            if callback.startswith(prefix):
                return callback
    raise AssertionError(f"missing callback {prefix!r}")


def _ingest_source_event(
    system: AcceptanceSpine,
    *,
    telethon: ControlledTelegramIngestionAdapter,
    identity: TelegramPeerIdentity,
    clock: FrozenClock,
    author_id: int,
    source_event_id: str,
    telegram_message_id: int,
    body: str,
) -> tuple[str, str]:
    initial_checkpoint = TelegramAccountCheckpoint(
        pts=4_700,
        qts=470,
        seq=4_700,
        date=datetime(2026, 9, 1, 11, 59, tzinfo=UTC),
    )
    event_time = datetime(2026, 9, 1, 12, 1, tzinfo=UTC)
    telethon.add_account_difference_event(
        from_checkpoint=initial_checkpoint,
        to_checkpoint=TelegramAccountCheckpoint(
            pts=4_701,
            qts=471,
            seq=4_701,
            date=event_time,
        ),
        identity=identity,
        registry_generation=1,
        source_event_id=source_event_id,
        telegram_message_id=telegram_message_id,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=body,
        event_time=event_time,
        source_author_telegram_id=author_id,
    )
    system.initialize_account_ingestion_checkpoint(initial_checkpoint)
    clock.advance_to(event_time)
    assert system.process_next_account_telegram_difference()
    assert system.process_next_source_event()
    source_message_id = (
        f"source-chat:chat:{identity.telegram_id}:generation:1:"
        f"message:{telegram_message_id}"
    )
    return source_message_id, f"{source_message_id}:revision:1"


def test_source_data_deletion_requires_approval_and_all_owner_acks() -> None:
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    administrator_id = 46_801
    author_id = 78_901
    chat_id = 4_680_100
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHAT,
        telegram_id=chat_id,
    )
    telethon = ControlledTelegramIngestionAdapter()
    telethon.allow_public_username(
        address="@source_deletion_fixture",
        identity=identity,
        transport_boundary="chat-sequence:4680",
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        administrator_id=administrator_id,
    )

    initial_checkpoint = TelegramAccountCheckpoint(
        pts=4_680,
        qts=468,
        seq=4_680,
        date=datetime(2026, 9, 1, 11, 59, tzinfo=UTC),
    )
    event_time = datetime(2026, 9, 1, 12, 1, tzinfo=UTC)
    advanced_checkpoint = TelegramAccountCheckpoint(
        pts=4_681,
        qts=469,
        seq=4_681,
        date=event_time,
    )
    telethon.add_account_difference_event(
        from_checkpoint=initial_checkpoint,
        to_checkpoint=advanced_checkpoint,
        identity=identity,
        registry_generation=1,
        source_event_id="source-event:deletion-fixture",
        telegram_message_id=101,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="source body must be removed",
        event_time=event_time,
        source_author_telegram_id=author_id,
    )
    system.initialize_account_ingestion_checkpoint(initial_checkpoint)
    clock.advance_to(event_time)
    assert system.process_next_account_telegram_difference()
    assert system.process_next_source_event()
    assert system.source_messages()[0].body == "source body must be removed"

    request = system.create_source_data_deletion_request(
        request_id="deletion-request:fixture",
        source_author_telegram_id=author_id,
        source_chat_key=f"source-chat:chat:{chat_id}",
        support_case_pointer="support-case:fixture",
        received_at=event_time,
    )
    assert request.status.value == "pending_decision"
    assert system.decide_source_data_deletion_request(
        request_id=request.request_id,
        decision="approve",
        decision_reason=None,
        decided_by=administrator_id,
        decided_at=event_time,
    )
    assert system.source_messages()[0].body == "source body must be removed"
    assert system.source_data_deletion_requests()[0].status.value == (
        "approved_awaiting_execution"
    )

    effective_at = event_time + timedelta(minutes=1)
    clock.advance_to(effective_at)
    assert system.begin_source_data_deletion_request(
        request_id=request.request_id,
        effective_at=effective_at,
    )
    assert system.source_messages()[0].body == "source body must be removed"
    assert system.source_data_deletion_requests()[0].status.value == "suppressing"

    system.process_source_data_deletion_until_idle()

    assert system.source_messages() == ()
    assert system.source_message_revisions() == ()
    assert system.source_events() == ()
    deletion_request = system.source_data_deletion_requests()[0]
    assert deletion_request.status.value == "awaiting_completion"
    owner_acks = system.source_data_deletion_owner_acks(request.request_id)
    assert len(owner_acks) == 5
    assert {ack.suppression_status.value for ack in owner_acks} == {"completed"}
    assert {ack.deletion_status.value for ack in owner_acks} == {"completed"}
    audit = system.source_data_audit()
    assert {event.action for event in audit} >= {
        "scheduled",
        "source_deleted",
        "state_changed",
    }
    lifecycle = [event for event in audit if event.action == "state_changed"]
    assert lifecycle
    assert all(event.request_id == request.request_id for event in lifecycle)
    assert any(
        event.reason_code == "decision_approved"
        and event.actor_telegram_id == administrator_id
        for event in lifecycle
    )

    assert system.record_source_data_deletion_notification(
        request_id=request.request_id,
        notified_at=clock.now(),
    )
    assert system.complete_source_data_deletion_request(
        request_id=request.request_id,
        completion_outcome="completed",
        completion_proof_pointer="support-proof:fixture",
        completed_at=clock.now(),
    )
    assert system.source_data_deletion_requests()[0].status.value == "completed"
    assert any(
        event.reason_code == "completion_completed"
        and event.notification_status == "recorded"
        and event.actor_telegram_id is None
        for event in system.source_data_audit()
    )
    barriers = system.source_data_deletion_replay_barriers()
    assert len(barriers) == 1
    assert barriers[0].source_author_telegram_id == author_id
    assert barriers[0].source_chat_key == f"source-chat:chat:{chat_id}"

    rejected = system.create_source_data_deletion_request(
        request_id="deletion-request:rejected-fixture",
        source_author_telegram_id=author_id,
        source_chat_key=f"source-chat:chat:{chat_id}",
        support_case_pointer="support-case:rejected-fixture",
        received_at=clock.now(),
    )
    assert system.decide_source_data_deletion_request(
        request_id=rejected.request_id,
        decision="reject",
        decision_reason="identity_unresolved",
        decided_by=administrator_id,
        decided_at=clock.now(),
    )
    assert system.record_source_data_deletion_notification(
        request_id=rejected.request_id,
        notified_at=clock.now(),
    )


def _register_source_chat(
    system: AcceptanceSpine,
    *,
    clock: FrozenClock,
    administrator_id: int,
) -> None:
    system.start_bot_user(
        update_id="start:source-deletion-fixture",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:source-deletion-fixture",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:source-deletion-fixture",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:source-deletion-fixture",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:source-deletion-fixture",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:source-deletion-fixture",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add-source-chat:source-deletion-fixture",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id="address:source-deletion-fixture",
        telegram_user_id=administrator_id,
        address="@source_deletion_fixture",
    )
    clock.advance_to(datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
    system.process_source_chat_registrations_until_idle()
