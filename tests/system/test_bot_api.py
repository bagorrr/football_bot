"""Bot API continuity through the real PostgreSQL role boundary."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from modules.bot_api import (
    BotApiConfiguration,
    BotApiDeliveryAdapter,
    BotApiIngress,
    BotApiMessage,
    BotApiPollResult,
    BotApiUpdate,
    ControlledBotApiTransport,
    PostgresBotApiContinuityStore,
    T1BotApiProjection,
)
from modules.contracts import RuntimeRole
from modules.postgres_adapter import (
    PostgresAcceptanceMigrator,
    runtime_database_url,
)


def test_postgres_continuity_survives_restart_and_suppresses_replayed_update(
    fresh_database_url: str,
) -> None:
    bot_database_url = _prepare_database(fresh_database_url)
    transport = ControlledBotApiTransport()
    update = _private_update(42)
    transport.enqueue_update(update)
    handled: list[int] = []

    first = _ingress(
        bot_database_url,
        transport,
        consumer=lambda item: handled.append(item.update_id),
    )
    first_result = first.poll_once()

    transport.enqueue_poll(BotApiPollResult(updates=(update,)))
    restarted = _ingress(
        bot_database_url,
        transport,
        consumer=lambda item: handled.append(item.update_id),
    )
    replay_result = restarted.poll_once()

    assert first_result.accepted_update_ids == (42,)
    assert replay_result.stale_update_ids == (42,)
    assert handled == [42]
    assert transport.poll_offsets == [0, 43]
    with psycopg.connect(fresh_database_url) as connection:
        assert connection.execute(
            """
            SELECT next_offset, retention_gap_open
            FROM football_runtime.bot_api_checkpoints
            WHERE checkpoint_key = 'telegram-bot-api'
            """
        ).fetchone() == (43, False)
        assert connection.execute(
            "SELECT count(*) FROM football_runtime.bot_api_updates"
        ).fetchone() == (1,)


def test_postgres_false_consumer_release_has_the_required_delete_privilege(
    fresh_database_url: str,
) -> None:
    bot_database_url = _prepare_database(fresh_database_url)
    transport = ControlledBotApiTransport()
    transport.enqueue_update(_private_update(43))
    ingress = _ingress(bot_database_url, transport, consumer=lambda _item: False)

    result = ingress.poll_once()

    assert result.accepted_update_ids == (43,)
    assert result.ignored_update_ids == (43,)
    assert result.next_offset == 44
    with psycopg.connect(fresh_database_url) as connection:
        assert connection.execute(
            """
            SELECT has_table_privilege(
                       'football_bot_assistant',
                       'football_runtime.bot_api_updates',
                       'DELETE'
                   ),
                   has_table_privilege(
                       'football_bot_assistant',
                       'football_runtime.bot_api_updates',
                       'TRUNCATE'
                   ),
                   count(*)
            FROM football_runtime.bot_api_updates
            """
        ).fetchone() == (True, False, 1)


def test_postgres_retention_loss_alerts_once_and_stays_private(
    fresh_database_url: str,
) -> None:
    bot_database_url = _prepare_database(fresh_database_url)
    transport = ControlledBotApiTransport()
    transport.enqueue_poll(
        BotApiPollResult(
            updates=(_private_update(25),),
            oldest_available_update_id=25,
        )
    )
    ingress = _ingress(bot_database_url, transport, consumer=lambda _item: None)

    result = ingress.poll_once()

    assert result.retention_gap_detected
    assert result.retention_alert_delivered
    assert len(transport.sent_messages) == 1
    assert transport.sent_messages[0].telegram_user_id == 456789
    assert "25" not in transport.sent_messages[0].text
    with psycopg.connect(fresh_database_url) as connection:
        assert connection.execute(
            """
            SELECT count(*), min(delivery_status), min(telegram_message_id)
            FROM football_runtime.bot_api_retention_alerts
            """
        ).fetchone() == (1, "confirmed", "controlled-message:1")
        assert connection.execute(
            """
            SELECT affected_update_id_start, affected_update_id_end,
                   recovery_boundary_update_id
            FROM football_runtime.bot_api_retention_alerts
            """
        ).fetchone() == (0, 24, 25)

    transport.enqueue_poll(BotApiPollResult())
    second_result = ingress.poll_once()
    assert not second_result.retention_alert_delivered
    assert len(transport.sent_messages) == 1


def test_postgres_poll_lease_allows_one_active_long_poll(
    fresh_database_url: str,
) -> None:
    bot_database_url = _prepare_database(fresh_database_url)
    first_store = PostgresBotApiContinuityStore(bot_database_url)
    second_store = PostgresBotApiContinuityStore(bot_database_url)
    now = datetime(2026, 9, 7, tzinfo=UTC)
    first_token = uuid4()
    second_token = uuid4()

    assert first_store.acquire_poll_lease(
        claim_token=first_token,
        claimed_at=now,
        expires_at=now + timedelta(seconds=40),
    )
    assert not second_store.acquire_poll_lease(
        claim_token=second_token,
        claimed_at=now,
        expires_at=now + timedelta(seconds=40),
    )
    first_store.release_poll_lease(claim_token=first_token)
    assert second_store.acquire_poll_lease(
        claim_token=second_token,
        claimed_at=now,
        expires_at=now + timedelta(seconds=40),
    )
    second_store.release_poll_lease(claim_token=second_token)

    passwords = _test_passwords()
    application_database_url = runtime_database_url(
        fresh_database_url,
        RuntimeRole.APPLICATION,
        passwords[RuntimeRole.APPLICATION],
    )
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        psycopg.connect(application_database_url) as connection,
    ):
        connection.execute("SELECT count(*) FROM football_runtime.bot_api_checkpoints")


def _prepare_database(database_url: str) -> str:
    migrator = PostgresAcceptanceMigrator(database_url)
    migrator.migrate()
    passwords = _test_passwords()
    migrator.provision_runtime_credentials(passwords)
    return runtime_database_url(
        database_url,
        RuntimeRole.BOT_ASSISTANT,
        passwords[RuntimeRole.BOT_ASSISTANT],
    )


def _test_passwords() -> dict[RuntimeRole, str]:
    return {role: f"ticket100-{role.value}-password" for role in RuntimeRole}


def _ingress(
    database_url: str,
    transport: ControlledBotApiTransport,
    *,
    consumer: Callable[[BotApiUpdate], object],
) -> BotApiIngress:
    configuration = BotApiConfiguration.from_projection(
        T1BotApiProjection.from_mapping(
            {
                "TELEGRAM_BOT_TOKEN": "123456:fake-token",
                "TELEGRAM_ADMIN_USER_ID": "456789",
            }
        )
    )
    return BotApiIngress(
        configuration=configuration,
        transport=transport,
        store=PostgresBotApiContinuityStore(database_url),
        consumer=consumer,
        delivery=BotApiDeliveryAdapter(transport, retry_sleep=lambda _seconds: None),
        clock=_FixedClock(),
    )


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 7, tzinfo=UTC)


def _private_update(update_id: int) -> BotApiUpdate:
    return BotApiUpdate(
        update_id=update_id,
        message=BotApiMessage(
            message_id=update_id,
            sender_id=111222,
            chat_id=111222,
            chat_type="private",
            text="/start",
            language_code="en",
        ),
    )
