"""Public Bot API boundary tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.error import URLError

import pytest

from modules.bot_api import (
    T1_CONFIGURATION_KEYS,
    BotApiCallback,
    BotApiConfigurationError,
    BotApiConformance,
    BotApiConversationHandler,
    BotApiDeliveryAdapter,
    BotApiHttpTransport,
    BotApiIdentityMismatchError,
    BotApiIngress,
    BotApiMessage,
    BotApiOutcomeUnknownError,
    BotApiPollResult,
    BotApiRuntime,
    BotApiUpdate,
    BotApiWebhookActiveError,
    ControlledBotApiTransport,
    InMemoryBotApiContinuityStore,
    T1BotApiProjection,
    exact_administrator,
)
from modules.domain import TelegramMessage


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 7, tzinfo=UTC)


def test_t1_configuration_is_exact_and_validated_before_transport_creation() -> None:
    """An invalid T1 projection cannot construct a Bot API transport."""
    transport_calls: list[object] = []

    def transport_factory(configuration: object) -> object:
        transport_calls.append(configuration)
        return object()

    assert {
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ADMIN_USER_ID",
    } == T1_CONFIGURATION_KEYS
    projection = T1BotApiProjection.from_mapping(
        {
            "TELEGRAM_BOT_TOKEN": "123456:fake-token",
            "TELEGRAM_ADMIN_USER_ID": "456789",
        }
    )
    runtime = BotApiRuntime.from_projection(
        projection,
        transport_factory=transport_factory,
    )
    assert runtime.configuration.administrator_user_id == 456789
    assert len(transport_calls) == 1

    with pytest.raises(BotApiConfigurationError) as error:
        BotApiRuntime.from_mapping(
            {
                "TELEGRAM_BOT_TOKEN": "super-secret-token",
                "TELEGRAM_ADMIN_USER_ID": "456789",
                "TELETHON_SESSION": "protected",
            },
            transport_factory=transport_factory,
        )

    assert len(transport_calls) == 1
    assert "super-secret-token" not in str(error.value)
    assert "456789" not in str(error.value)
    assert error.value.status == "unknown_key"


def test_raw_bot_api_message_and_callback_are_strict_private_user_updates() -> None:
    message_update = BotApiUpdate.from_mapping(
        {
            "update_id": 17,
            "message": {
                "message_id": 4,
                "from": {"id": 456789, "language_code": "ru"},
                "chat": {"id": 456789, "type": "private"},
                "text": "/start",
            },
        }
    )
    callback_update = BotApiUpdate.from_mapping(
        {
            "update_id": 18,
            "callback_query": {
                "id": "callback-18",
                "from": {"id": 456789},
                "message": {
                    "message_id": 5,
                    "chat": {"id": 456789, "type": "private"},
                },
                "data": "menu:settings:2",
            },
        }
    )

    assert isinstance(message_update.message, BotApiMessage)
    assert message_update.is_private_user_update
    assert message_update.message.text == "/start"
    assert isinstance(callback_update.callback, BotApiCallback)
    assert callback_update.is_private_user_update
    assert callback_update.callback.data == "menu:settings:2"
    assert exact_administrator(456789, 456789)
    assert not exact_administrator(456788, 456789)

    group_update = BotApiUpdate.from_mapping(
        {
            "update_id": 19,
            "message": {
                "message_id": 6,
                "from": {"id": 456789},
                "chat": {"id": -100456789, "type": "supergroup"},
                "text": "/start",
            },
        }
    )
    assert not group_update.is_private_user_update


def test_conversation_handler_routes_ordinary_access_and_guards_admin_callbacks() -> (
    None
):
    application = _RecordingApplication()
    handler = BotApiConversationHandler(
        application,
        administrator_user_id=456789,
    )
    start = BotApiUpdate.from_mapping(
        {
            "update_id": 20,
            "message": {
                "message_id": 1,
                "from": {"id": 111222, "language_code": "en"},
                "chat": {"id": 111222, "type": "private"},
                "text": "/start",
            },
        }
    )
    unauthorized_callback = BotApiUpdate.from_mapping(
        {
            "update_id": 21,
            "callback_query": {
                "id": "callback-21",
                "from": {"id": 111222},
                "message": {
                    "message_id": 2,
                    "chat": {"id": 111222, "type": "private"},
                },
                "data": "settings:administration:1",
            },
        }
    )
    admin_callback = BotApiUpdate.from_mapping(
        {
            "update_id": 22,
            "callback_query": {
                "id": "callback-22",
                "from": {"id": 456789},
                "message": {
                    "message_id": 3,
                    "chat": {"id": 456789, "type": "private"},
                },
                "data": "settings:administration:1",
            },
        }
    )

    assert handler(start)
    assert not handler(unauthorized_callback)
    assert handler(admin_callback)
    assert application.calls == [
        ("start", 111222),
        ("settings", 456789),
    ]
    assert application.callback_ids == ["callback-22"]


def test_rejected_callback_is_not_consumed_or_acknowledged() -> None:
    application = _RecordingApplication(accept_callbacks=False)
    handler = BotApiConversationHandler(
        application,
        administrator_user_id=456789,
    )
    rejected = _private_callback(
        23,
        data="menu:unsupported:1",
        callback_id="callback-rejected",
    )

    assert not handler(rejected)
    assert application.calls == []
    assert application.callback_ids == []


class _RecordingApplication:
    def __init__(self, *, accept_callbacks: bool = True) -> None:
        self.calls: list[tuple[str, int]] = []
        self.callback_ids: list[str] = []
        self.callback_data: list[str] = []
        self.message_texts: list[str] = []
        self.accept_callbacks = accept_callbacks

    def start(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        telegram_language_hint: str | None,
    ) -> None:
        del update_id, telegram_language_hint
        self.calls.append(("start", telegram_user_id))

    def open_main_menu(self, *, update_id: str, telegram_user_id: int) -> None:
        del update_id
        self.calls.append(("menu", telegram_user_id))

    def handle_message(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        text: str,
        telegram_language_hint: str | None,
    ) -> bool:
        del update_id, telegram_language_hint
        self.message_texts.append(text)
        self.calls.append(("message", telegram_user_id))
        return True

    def handle_callback(
        self,
        *,
        update_id: str,
        callback_id: str,
        telegram_user_id: int,
        data: str,
        screen_revision: int,
        telegram_message_id: str,
    ) -> bool:
        del update_id, screen_revision, telegram_message_id
        if not self.accept_callbacks:
            return False
        self.callback_ids.append(callback_id)
        self.callback_data.append(data)
        self.calls.append(("callback", telegram_user_id))
        return True

    def select_main_menu_action(
        self,
        *,
        update_id: str,
        callback_id: str,
        telegram_user_id: int,
        action: str,
        screen_revision: int,
    ) -> bool:
        del update_id, action, screen_revision
        if not self.accept_callbacks:
            return False
        self.callback_ids.append(callback_id)
        self.calls.append(("main", telegram_user_id))
        return True

    def select_settings_action(
        self,
        *,
        update_id: str,
        callback_id: str,
        telegram_user_id: int,
        action: str,
        screen_revision: int,
    ) -> bool:
        del update_id, action, screen_revision
        if not self.accept_callbacks:
            return False
        self.callback_ids.append(callback_id)
        self.calls.append(("settings", telegram_user_id))
        return True

    def select_administration_action(
        self,
        *,
        update_id: str,
        callback_id: str,
        telegram_user_id: int,
        action: str,
        screen_revision: int,
    ) -> bool:
        del update_id, action, screen_revision
        if not self.accept_callbacks:
            return False
        self.callback_ids.append(callback_id)
        self.calls.append(("administration", telegram_user_id))
        return True

    def select_result_action(
        self,
        *,
        update_id: str,
        callback_id: str,
        telegram_user_id: int,
        action: str,
        screen_revision: int,
        context_token: str,
        target_position: int,
        telegram_message_id: str,
    ) -> None:
        del (
            update_id,
            callback_id,
            action,
            screen_revision,
            context_token,
            target_position,
            telegram_message_id,
        )
        self.calls.append(("results", telegram_user_id))

    def select_fixed_language(
        self,
        *,
        update_id: str,
        callback_id: str,
        telegram_user_id: int,
        locale: str,
        screen_revision: int,
    ) -> bool:
        del update_id, locale, screen_revision
        if not self.accept_callbacks:
            return False
        self.callback_ids.append(callback_id)
        self.calls.append(("language", telegram_user_id))
        return True

    def open_language_input(
        self,
        *,
        update_id: str,
        callback_id: str,
        telegram_user_id: int,
        screen_revision: int,
    ) -> bool:
        del update_id, screen_revision
        if not self.accept_callbacks:
            return False
        self.callback_ids.append(callback_id)
        self.calls.append(("language-input", telegram_user_id))
        return True

    def select_direction(
        self,
        *,
        update_id: str,
        callback_id: str,
        telegram_user_id: int,
        direction: str,
        screen_revision: int,
    ) -> bool:
        del update_id, direction, screen_revision
        if not self.accept_callbacks:
            return False
        self.callback_ids.append(callback_id)
        self.calls.append(("direction", telegram_user_id))
        return True


def test_long_polling_resumes_durable_offset_and_deduplicates_restart() -> None:
    transport = ControlledBotApiTransport()
    transport.enqueue_update(
        BotApiUpdate.from_mapping(
            {
                "update_id": 40,
                "message": {
                    "message_id": 1,
                    "from": {"id": 456789, "language_code": "en"},
                    "chat": {"id": 456789, "type": "private"},
                    "text": "/start",
                },
            }
        )
    )
    store = InMemoryBotApiContinuityStore()
    handled: list[int] = []
    first = BotApiIngress(
        configuration=BotApiRuntime.from_mapping(
            {
                "TELEGRAM_BOT_TOKEN": "123456:fake-token",
                "TELEGRAM_ADMIN_USER_ID": "456789",
            },
            transport_factory=lambda _configuration: transport,
        ).configuration,
        transport=transport,
        store=store,
        consumer=lambda update: handled.append(update.update_id),
        delivery=BotApiDeliveryAdapter(transport, retry_sleep=lambda _seconds: None),
        clock=_FixedClock(),
    )

    first.poll_once()
    restarted = BotApiIngress(
        configuration=first.configuration,
        transport=transport,
        store=store,
        consumer=lambda update: handled.append(update.update_id),
        delivery=BotApiDeliveryAdapter(transport, retry_sleep=lambda _seconds: None),
        clock=_FixedClock(),
    )
    restarted.poll_once()

    assert handled == [40]
    assert store.checkpoint().next_offset == 41
    assert transport.poll_offsets == [0, 41]


def test_positive_update_ids_without_retention_evidence_do_not_open_a_gap() -> None:
    transport = ControlledBotApiTransport()
    transport.enqueue_poll(BotApiPollResult(updates=(_private_update(900),)))
    transport.enqueue_poll(BotApiPollResult(updates=(_private_update(1_900),)))
    store = InMemoryBotApiContinuityStore()
    handled: list[int] = []
    runtime = BotApiRuntime.from_mapping(
        {
            "TELEGRAM_BOT_TOKEN": "123456:fake-token",
            "TELEGRAM_ADMIN_USER_ID": "456789",
        },
        transport_factory=lambda _configuration: transport,
    )
    ingress = BotApiIngress(
        configuration=runtime.configuration,
        transport=transport,
        store=store,
        consumer=lambda update: handled.append(update.update_id),
        delivery=BotApiDeliveryAdapter(transport, retry_sleep=lambda _seconds: None),
        clock=_FixedClock(),
    )

    first_result = ingress.poll_once()
    second_result = ingress.poll_once()

    assert first_result.accepted_update_ids == (900,)
    assert second_result.accepted_update_ids == (1_900,)
    assert not first_result.retention_gap_detected
    assert not second_result.retention_gap_detected
    assert not first_result.retention_alert_delivered
    assert not second_result.retention_alert_delivered
    assert handled == [900, 1_900]
    assert store.checkpoint().next_offset == 1_901
    assert store.retention_alerts == ()
    assert transport.sent_messages == []


def test_long_polling_refuses_an_active_webhook_before_get_updates() -> None:
    transport = ControlledBotApiTransport(webhook_url="https://example.invalid/hook")
    store = InMemoryBotApiContinuityStore()
    runtime = BotApiRuntime.from_mapping(
        {
            "TELEGRAM_BOT_TOKEN": "123456:fake-token",
            "TELEGRAM_ADMIN_USER_ID": "456789",
        },
        transport_factory=lambda _configuration: transport,
    )
    ingress = BotApiIngress(
        configuration=runtime.configuration,
        transport=transport,
        store=store,
        consumer=lambda _update: None,
        delivery=BotApiDeliveryAdapter(transport, retry_sleep=lambda _seconds: None),
        clock=_FixedClock(),
    )

    with pytest.raises(BotApiWebhookActiveError):
        ingress.poll_once()

    assert transport.poll_offsets == []


def test_retention_gap_skips_unavailable_updates_and_alerts_once_per_interval() -> None:
    transport = ControlledBotApiTransport()
    transport.enqueue_poll(
        BotApiPollResult(
            updates=(
                BotApiUpdate.from_mapping(
                    {
                        "update_id": 25,
                        "message": {
                            "message_id": 1,
                            "from": {"id": 456789},
                            "chat": {"id": 456789, "type": "private"},
                            "text": "/start",
                        },
                    }
                ),
            ),
            oldest_available_update_id=25,
        )
    )
    store = InMemoryBotApiContinuityStore()
    handled: list[int] = []
    runtime = BotApiRuntime.from_mapping(
        {
            "TELEGRAM_BOT_TOKEN": "123456:fake-token",
            "TELEGRAM_ADMIN_USER_ID": "456789",
        },
        transport_factory=lambda _configuration: transport,
    )
    ingress = BotApiIngress(
        configuration=runtime.configuration,
        transport=transport,
        store=store,
        consumer=lambda update: handled.append(update.update_id),
        delivery=BotApiDeliveryAdapter(transport, retry_sleep=lambda _seconds: None),
        clock=_FixedClock(),
    )

    result = ingress.poll_once()

    assert result.retention_gap_detected
    assert result.retention_alert_delivered
    assert handled == [25]
    assert store.checkpoint().next_offset == 26
    assert len(store.retention_alerts) == 1
    assert store.retention_alerts[0][1] == "confirmed"
    assert len(transport.sent_messages) == 1
    assert transport.sent_messages[0].telegram_user_id == 456789
    assert "25" not in transport.sent_messages[0].text

    transport.enqueue_poll(BotApiPollResult())
    second_result = ingress.poll_once()

    assert not second_result.retention_gap_detected
    assert len(store.retention_alerts) == 1
    assert len(transport.sent_messages) == 1


def test_retention_alert_reconciles_an_ambiguous_send_without_resending() -> None:
    transport = ControlledBotApiTransport(unknown_send_results_remaining=1)
    transport.enqueue_poll(
        BotApiPollResult(
            updates=(_private_update(25),),
            oldest_available_update_id=25,
        )
    )
    store = InMemoryBotApiContinuityStore()
    runtime = BotApiRuntime.from_mapping(
        {
            "TELEGRAM_BOT_TOKEN": "123456:fake-token",
            "TELEGRAM_ADMIN_USER_ID": "456789",
        },
        transport_factory=lambda _configuration: transport,
    )
    ingress = BotApiIngress(
        configuration=runtime.configuration,
        transport=transport,
        store=store,
        consumer=lambda _update: None,
        delivery=BotApiDeliveryAdapter(transport, retry_sleep=lambda _seconds: None),
        clock=_FixedClock(),
    )

    first_result = ingress.poll_once()
    assert not first_result.retention_alert_delivered
    assert store.retention_alerts[0][1] == "outcome_unknown"
    assert len(transport.sent_messages) == 1

    transport.enqueue_poll(BotApiPollResult())
    second_result = ingress.poll_once()

    assert second_result.retention_alert_delivered
    assert store.retention_alerts[0][1] == "confirmed"
    assert len(transport.sent_messages) == 1


def test_complete_bot_user_surface_is_forwarded_and_checkpointed() -> None:
    transport = ControlledBotApiTransport()
    valid_updates = (
        _private_update(600, text="Find a match for me"),
        _private_callback(
            601,
            data="location:other-city:1",
            callback_id="callback-location",
        ),
        _private_callback(
            602,
            data="location-suggestion:city:place-1:1",
            callback_id="callback-location-suggestion",
        ),
        _private_callback(
            603,
            data="details:open:team_formats:1",
            callback_id="callback-details",
        ),
        _private_callback(
            604,
            data="search:submit:1",
            callback_id="callback-search",
        ),
        _private_callback(
            605,
            data="source-chats:back:1",
            callback_id="callback-source-chats",
            sender_id=456789,
        ),
        _private_callback(
            606,
            data="sdd:back:1",
            callback_id="callback-source-data-deletion",
            sender_id=456789,
        ),
        _private_callback(
            607,
            data="direction:back:1",
            callback_id="callback-back",
        ),
    )
    unsupported = _private_callback(
        608,
        data="unsupported:control:1",
        callback_id="callback-unsupported",
    )
    transport.enqueue_poll(BotApiPollResult(updates=(*valid_updates, unsupported)))
    transport.enqueue_poll(BotApiPollResult(updates=(unsupported,)))
    store = InMemoryBotApiContinuityStore()
    application = _RecordingApplication()
    handler = BotApiConversationHandler(
        application,
        administrator_user_id=456789,
    )
    runtime = BotApiRuntime.from_mapping(
        {
            "TELEGRAM_BOT_TOKEN": "123456:fake-token",
            "TELEGRAM_ADMIN_USER_ID": "456789",
        },
        transport_factory=lambda _configuration: transport,
    )
    ingress = BotApiIngress(
        configuration=runtime.configuration,
        transport=transport,
        store=store,
        consumer=handler,
        delivery=BotApiDeliveryAdapter(transport, retry_sleep=lambda _seconds: None),
        clock=_FixedClock(),
    )

    result = ingress.poll_once()
    retry_result = ingress.poll_once()

    assert result.accepted_update_ids == tuple(
        update.update_id for update in valid_updates
    )
    assert result.duplicate_update_ids == ()
    assert retry_result.accepted_update_ids == ()
    assert retry_result.duplicate_update_ids == ()
    assert store.checkpoint().next_offset == unsupported.update_id
    assert store.retention_alerts == ()
    assert application.message_texts == ["Find a match for me"]
    assert application.callback_ids == [
        "callback-location",
        "callback-location-suggestion",
        "callback-details",
        "callback-search",
        "callback-source-chats",
        "callback-source-data-deletion",
        "callback-back",
    ]
    assert application.callback_data == [
        "location:other-city:1",
        "location-suggestion:city:place-1:1",
        "details:open:team_formats:1",
        "search:submit:1",
        "source-chats:back:1",
        "sdd:back:1",
        "direction:back:1",
    ]
    assert "callback-unsupported" not in application.callback_ids


def test_long_polling_requires_the_configured_private_administrator_destination() -> (
    None
):
    transport = ControlledBotApiTransport(administrator_chat_type="group")
    store = InMemoryBotApiContinuityStore()
    runtime = BotApiRuntime.from_mapping(
        {
            "TELEGRAM_BOT_TOKEN": "123456:fake-token",
            "TELEGRAM_ADMIN_USER_ID": "456789",
        },
        transport_factory=lambda _configuration: transport,
    )
    ingress = BotApiIngress(
        configuration=runtime.configuration,
        transport=transport,
        store=store,
        consumer=lambda _update: None,
        delivery=BotApiDeliveryAdapter(transport, retry_sleep=lambda _seconds: None),
        clock=_FixedClock(),
    )

    with pytest.raises(BotApiIdentityMismatchError):
        ingress.poll_once()

    assert transport.poll_offsets == []


def test_delivery_retries_rate_limit_and_proven_pre_effect_failure() -> None:
    transport = ControlledBotApiTransport(
        rate_limits_remaining=1,
        pre_effect_failures_remaining=1,
        retry_after_seconds=2,
    )
    waits: list[float] = []
    delivery = BotApiDeliveryAdapter(transport, retry_sleep=waits.append)
    message = _message("delivery-rate-limit")

    telegram_message_id = delivery.send(message)

    assert telegram_message_id == "controlled-message:1"
    assert waits == [2.0, 2.0]
    assert len(transport.sent_messages) == 1


def test_delivery_reconciles_ambiguous_send_without_a_second_user_message() -> None:
    transport = ControlledBotApiTransport(unknown_send_results_remaining=1)
    delivery = BotApiDeliveryAdapter(transport, retry_sleep=lambda _seconds: None)
    message = _message("delivery-ambiguous")

    with pytest.raises(BotApiOutcomeUnknownError):
        delivery.send(message)

    assert len(transport.sent_messages) == 1
    assert delivery.reconcile(message) == "controlled-message:1"
    assert len(transport.sent_messages) == 1


def test_http_transport_uses_get_updates_and_never_exposes_token_on_write_failure() -> (
    None
):
    requests: list[tuple[str, dict[str, object]]] = []

    class _Response:
        def __init__(self, payload: object) -> None:
            self._body = json.dumps(payload).encode("utf-8")

        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return self._body

    responses = [
        {
            "ok": True,
            "result": [
                {
                    "update_id": 41,
                    "message": {
                        "message_id": 1,
                        "from": {"id": 456789},
                        "chat": {"id": 456789, "type": "private"},
                        "text": "/start",
                    },
                }
            ],
        }
    ]

    def opener(request: object, **_kwargs: object) -> _Response:
        assert hasattr(request, "data")
        assert hasattr(request, "full_url")
        request_data = request.data
        request_url = request.full_url
        payload = json.loads(request_data.decode("utf-8"))
        requests.append((request_url.rsplit("/", 1)[-1], payload))
        return _Response(responses.pop(0))

    configuration = BotApiRuntime.from_mapping(
        {
            "TELEGRAM_BOT_TOKEN": "123456:secret-token",
            "TELEGRAM_ADMIN_USER_ID": "456789",
        },
        transport_factory=lambda configuration: BotApiHttpTransport(
            configuration,
            api_root="https://example.invalid/bot",
            opener=opener,
        ),
    ).configuration
    transport = BotApiHttpTransport(
        configuration,
        api_root="https://example.invalid/bot",
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            URLError("network unavailable")
        ),
    )

    poll = BotApiHttpTransport(
        configuration,
        api_root="https://example.invalid/bot",
        opener=opener,
    ).get_updates(offset=40, timeout_seconds=30)

    assert poll.updates[0].update_id == 41
    assert poll.oldest_available_update_id is None
    assert requests == [("getUpdates", {"offset": 40, "timeout": 30})]
    with pytest.raises(BotApiOutcomeUnknownError) as error:
        transport.send_message(_message("http-ambiguous"))
    assert "secret-token" not in str(error.value)


def test_http_transport_reports_only_a_decisive_retention_gap() -> None:
    responses = [
        {"ok": True, "result": [{"update_id": 900}]},
        {"ok": True, "result": [{"update_id": 1_900}]},
        {"ok": True, "result": [{"update_id": 3_000}]},
        {"ok": True, "result": [{"update_id": 4_000}]},
    ]

    class _Response:
        def __init__(self, payload: object) -> None:
            self._body = json.dumps(payload).encode("utf-8")

        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return self._body

    def opener(_request: object, **_kwargs: object) -> _Response:
        return _Response(responses.pop(0))

    configuration = BotApiRuntime.from_mapping(
        {
            "TELEGRAM_BOT_TOKEN": "123456:fake-token",
            "TELEGRAM_ADMIN_USER_ID": "456789",
        },
        transport_factory=lambda _configuration: BotApiHttpTransport(
            _configuration,
            api_root="https://example.invalid/bot",
            opener=opener,
        ),
    ).configuration
    transport = BotApiHttpTransport(
        configuration,
        api_root="https://example.invalid/bot",
        opener=opener,
    )
    origin = datetime(2026, 9, 1, tzinfo=UTC)

    initial = transport.get_updates(
        offset=0,
        timeout_seconds=30,
        observed_at=origin,
    )
    normal_positive = transport.get_updates(
        offset=901,
        timeout_seconds=30,
        last_poll_at=origin,
        observed_at=origin + timedelta(hours=1),
    )
    retention_gap = transport.get_updates(
        offset=1_901,
        timeout_seconds=30,
        last_poll_at=origin + timedelta(hours=1),
        observed_at=origin + timedelta(hours=26),
    )
    post_idle = transport.get_updates(
        offset=3_001,
        timeout_seconds=30,
        last_poll_at=origin + timedelta(hours=26),
        observed_at=origin + timedelta(days=9),
    )

    assert initial.oldest_available_update_id is None
    assert normal_positive.oldest_available_update_id is None
    assert retention_gap.oldest_available_update_id == 3_000
    assert post_idle.oldest_available_update_id is None


def test_http_transport_serializes_reply_keyboard_removal() -> None:
    requests: list[dict[str, object]] = []

    class _Response:
        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"message_id": 7}}).encode("utf-8")

    def opener(request: object, **_kwargs: object) -> _Response:
        assert hasattr(request, "data")
        requests.append(json.loads(request.data.decode("utf-8")))
        return _Response()

    configuration = BotApiRuntime.from_mapping(
        {
            "TELEGRAM_BOT_TOKEN": "123456:fake-token",
            "TELEGRAM_ADMIN_USER_ID": "456789",
        },
        transport_factory=lambda _configuration: BotApiHttpTransport(
            _configuration,
            api_root="https://example.invalid/bot",
            opener=opener,
        ),
    ).configuration
    BotApiHttpTransport(
        configuration,
        api_root="https://example.invalid/bot",
        opener=opener,
    ).send_message(_message("remove-keyboard"))

    assert requests == [
        {
            "chat_id": 456789,
            "text": "controlled message",
            "reply_markup": {"remove_keyboard": True},
        }
    ]


def test_protected_conformance_checks_identity_and_admin_destination() -> None:
    transport = ControlledBotApiTransport()
    configuration = BotApiRuntime.from_mapping(
        {
            "TELEGRAM_BOT_TOKEN": "123456:fake-token",
            "TELEGRAM_ADMIN_USER_ID": "456789",
        },
        transport_factory=lambda _configuration: transport,
    ).configuration
    conformance = BotApiConformance(
        configuration=configuration,
        transport=transport,
        delivery=BotApiDeliveryAdapter(transport, retry_sleep=lambda _seconds: None),
        expected_bot_user_id=900001,
    )

    status = conformance.run()

    assert status.bot_identity_verified
    assert status.webhook_inactive
    assert status.administrator_authorized
    assert status.administrator_destination_verified
    assert transport.sent_messages[-1].telegram_user_id == 456789
    assert transport.deleted_messages == [(456789, "controlled-message:1")]


def test_protected_conformance_fails_closed_on_identity_mismatch() -> None:
    transport = ControlledBotApiTransport()
    configuration = BotApiRuntime.from_mapping(
        {
            "TELEGRAM_BOT_TOKEN": "123456:fake-token",
            "TELEGRAM_ADMIN_USER_ID": "456789",
        },
        transport_factory=lambda _configuration: transport,
    ).configuration
    conformance = BotApiConformance(
        configuration=configuration,
        transport=transport,
        delivery=BotApiDeliveryAdapter(transport, retry_sleep=lambda _seconds: None),
        expected_bot_user_id=900002,
    )

    with pytest.raises(BotApiIdentityMismatchError):
        conformance.run()

    assert transport.sent_messages == []


def _message(delivery_id: str) -> TelegramMessage:
    return TelegramMessage(
        delivery_id=delivery_id,
        telegram_user_id=456789,
        display_locale="en",
        screen_revision=1,
        text="controlled message",
        button_rows=(),
    )


def _private_update(update_id: int, *, text: str = "/start") -> BotApiUpdate:
    return BotApiUpdate.from_mapping(
        {
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "from": {"id": 111222},
                "chat": {"id": 111222, "type": "private"},
                "text": text,
            },
        }
    )


def _private_callback(
    update_id: int,
    *,
    data: str,
    callback_id: str | None = None,
    sender_id: int = 111222,
) -> BotApiUpdate:
    return BotApiUpdate.from_mapping(
        {
            "update_id": update_id,
            "callback_query": {
                "id": callback_id or f"callback-{update_id}",
                "from": {"id": sender_id},
                "message": {
                    "message_id": update_id,
                    "chat": {"id": sender_id, "type": "private"},
                },
                "data": data,
            },
        }
    )
