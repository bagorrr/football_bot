"""Unit coverage for the provider-neutral Telethon ingestion boundary."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace

import pytest
from telethon import types  # type: ignore[import-untyped]

from modules.domain import (
    IngestionFailureReason,
    IngestionFailureScope,
    InitialConsentAttestation,
    SourceChatAddressKind,
    SourceChatAdmissionResolution,
    SourceChatRegistryEntry,
    SourceEventKind,
    TelegramAccountCheckpoint,
    TelegramChannelCheckpoint,
    TelegramDifferenceCheckpointAdvance,
    TelegramDifferenceEvent,
    TelegramDifferencePending,
    TelegramDifferenceResult,
    TelegramPeerIdentity,
    TelegramPeerKind,
    TelegramProtectedContentEvent,
)
from modules.ports import SourceChatAdmissionError
from modules.telethon_ingestion import (
    T2_CONFIGURATION_KEYS,
    ControlledTelethonTransport,
    SourceChatHistoryWindow,
    T2TelethonProjection,
    TelethonConfiguration,
    TelethonConfigurationError,
    TelethonConformance,
    TelethonConformanceError,
    TelethonIngestionAdapter,
    TelethonProvider,
    TelethonRuntime,
    TelethonTransportError,
)


class _RecordingTelethonSource:
    def __init__(self) -> None:
        self.result: TelegramDifferenceResult | None = None
        self.account_result: TelegramDifferenceResult | None = None
        self.history_calls = 0
        self.raise_on_history = False

    def refresh_source_scope(
        self,
        approved_source_chats: object,
    ) -> None:
        del approved_source_chats

    def configure_clock(self, clock: object) -> None:
        del clock

    def configure_message_identity_lookup(self, lookup: object) -> None:
        del lookup

    def configure_source_scope_generation_lookup(self, lookup: object) -> None:
        del lookup

    def configure_source_message_revision_lookup(self, lookup: object) -> None:
        del lookup

    def resolve_source_chat(self, address: str) -> SourceChatAdmissionResolution:
        raise AssertionError(address)

    def capture_source_chat_registration_boundary(
        self, identity: TelegramPeerIdentity
    ) -> str:
        raise AssertionError(identity)

    def get_account_difference_event(
        self, checkpoint: TelegramAccountCheckpoint
    ) -> TelegramDifferenceResult | None:
        del checkpoint
        return self.account_result

    def acknowledge_account_difference_event(
        self, checkpoint: TelegramAccountCheckpoint, result_id: str
    ) -> None:
        del checkpoint, result_id

    def get_channel_difference_event(
        self,
        identity: TelegramPeerIdentity,
        checkpoint: TelegramChannelCheckpoint,
        registry_generation: int | None = None,
    ) -> TelegramDifferenceResult | None:
        del identity, checkpoint, registry_generation
        return self.result

    def acknowledge_channel_difference_event(
        self,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        checkpoint: TelegramChannelCheckpoint,
        result_id: str,
    ) -> None:
        del identity, registry_generation, checkpoint, result_id

    def get_source_chat_history_event(
        self,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint,
        window_start: datetime,
        window_end: datetime,
        history_cursor: int | None = None,
    ) -> TelegramDifferenceResult | None:
        del (
            identity,
            registry_generation,
            checkpoint,
            window_start,
            window_end,
            history_cursor,
        )
        self.history_calls += 1
        if self.raise_on_history:
            raise RuntimeError("controlled-secret")
        return self.result

    def acknowledge_source_chat_history_event(
        self,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint,
        source_event_id: str,
    ) -> None:
        del identity, registry_generation, checkpoint, source_event_id


def test_t2_projection_accepts_only_its_four_keys_and_redacts_values() -> None:
    values = {
        "TELEGRAM_API_ID": "123456",
        "TELEGRAM_API_HASH": "controlled-api-hash",
        "TELEGRAM_SESSION_STRING": "controlled-session",
        "TELEGRAM_ADMIN_USER_ID": "789012",
    }

    projection = T2TelethonProjection.from_mapping(values)
    configuration = TelethonConfiguration.from_projection(projection)

    assert frozenset(values) == T2_CONFIGURATION_KEYS
    assert configuration.api_id == 123456
    assert configuration.administrator_user_id == 789012
    assert "controlled-api-hash" not in repr(projection)
    assert "controlled-session" not in repr(projection)
    assert "controlled-api-hash" not in repr(configuration)
    assert "controlled-session" not in repr(configuration)

    with pytest.raises(TelethonConfigurationError) as error:
        T2TelethonProjection.from_mapping(
            {**values, "TELEGRAM_BOT_TOKEN": "not-allowed"}
        )

    assert error.value.key == "TELEGRAM_BOT_TOKEN"
    assert error.value.status == "unknown_key"
    assert "not-allowed" not in str(error.value)


def test_t2_runtime_validates_before_constructing_client_and_requires_conformance() -> (
    None
):
    projection = T2TelethonProjection.from_mapping(
        {
            "TELEGRAM_API_ID": "123456",
            "TELEGRAM_API_HASH": "controlled-api-hash",
            "TELEGRAM_SESSION_STRING": "controlled-session",
            "TELEGRAM_ADMIN_USER_ID": "789012",
        }
    )
    constructed: list[TelethonConfiguration] = []

    runtime = TelethonRuntime.from_projection(
        projection,
        client_factory=lambda configuration: constructed.append(configuration),
    )

    assert len(constructed) == 1
    assert not runtime.ready
    with pytest.raises(TelethonConformanceError) as error:
        runtime.require_ready()
    assert error.value.key == "T2"
    assert error.value.status == "not_ready"

    transport = ControlledTelethonTransport()
    status = runtime.verify_conformance(transport=transport)

    assert status.authentication_verified
    assert status.account_identity_verified
    assert status.approved_scope_access_verified
    runtime.require_ready()


def test_invalid_t2_projection_does_not_construct_client() -> None:
    constructed = False

    def client_factory(_configuration: TelethonConfiguration) -> object:
        nonlocal constructed
        constructed = True
        return object()

    with pytest.raises(TelethonConfigurationError) as error:
        TelethonRuntime.from_mapping(
            {
                "TELEGRAM_API_ID": "",
                "TELEGRAM_API_HASH": "controlled-api-hash",
                "TELEGRAM_SESSION_STRING": "controlled-session",
                "TELEGRAM_ADMIN_USER_ID": "789012",
            },
            client_factory=client_factory,
        )

    assert error.value.key == "TELEGRAM_API_ID"
    assert error.value.status == "empty"
    assert not constructed


def test_conformance_checks_exact_identity_and_only_enabled_approved_scope() -> None:
    configuration = TelethonConfiguration.from_projection(
        T2TelethonProjection.from_mapping(
            {
                "TELEGRAM_API_ID": "123456",
                "TELEGRAM_API_HASH": "controlled-api-hash",
                "TELEGRAM_SESSION_STRING": "controlled-session",
                "TELEGRAM_ADMIN_USER_ID": "789012",
            }
        )
    )
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=42,
    )
    approved = SourceChatRegistryEntry(
        identity=identity,
        registry_generation=1,
        address_kind=SourceChatAddressKind.PUBLIC_USERNAME,
        current_address="@valid_source",
        processing_started_at=datetime.now(UTC),
        transport_boundary="channel-pts:1",
        enabled=True,
        initial_consent_attestation=InitialConsentAttestation.CONFIRMED,
        attested_at=datetime.now(UTC),
    )
    transport = ControlledTelethonTransport()

    status = TelethonConformance(
        configuration=configuration,
        transport=transport,
        approved_source_chats=(approved,),
    ).run()

    assert status.approved_scope_access_verified
    assert transport.access_requests == [identity]

    transport.account_user_id = 789013
    with pytest.raises(TelethonConformanceError) as error:
        TelethonConformance(
            configuration=configuration,
            transport=transport,
            approved_source_chats=(approved,),
        ).run()
    assert error.value.status == "identity_mismatch"
    assert "789013" not in str(error.value)


def test_conformance_rejects_disabled_source_before_access_probe() -> None:
    configuration = TelethonConfiguration(
        api_id=123456,
        api_hash="controlled-api-hash",
        session_string="controlled-session",
        administrator_user_id=789012,
    )
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 43)
    disabled = SourceChatRegistryEntry(
        identity=identity,
        registry_generation=1,
        address_kind=SourceChatAddressKind.PUBLIC_USERNAME,
        current_address="@disabled_source",
        processing_started_at=datetime.now(UTC),
        transport_boundary="channel-pts:1",
        enabled=False,
        initial_consent_attestation=InitialConsentAttestation.CONFIRMED,
        attested_at=datetime.now(UTC),
    )
    transport = ControlledTelethonTransport()

    with pytest.raises(TelethonConformanceError) as error:
        TelethonConformance(
            configuration=configuration,
            transport=transport,
            approved_source_chats=(disabled,),
        ).run()

    assert error.value.status == "scope_invalid"
    assert transport.authenticate_calls == 0
    assert transport.access_requests == []


def test_history_window_is_exactly_the_prior_seven_days() -> None:
    boundary = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    window = SourceChatHistoryWindow.before(boundary)

    assert window.start_at == datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    assert window.end_at == boundary
    assert window.contains(window.start_at)
    assert window.contains(window.end_at)
    assert not window.contains(window.start_at - timedelta(microseconds=1))


def test_difference_event_can_be_explicitly_marked_as_history() -> None:
    checkpoint = TelegramChannelCheckpoint(pts=10)
    event = TelegramDifferenceEvent(
        source_chat_identity=TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42),
        from_checkpoint=checkpoint,
        to_checkpoint=checkpoint,
        source_event_id="source-event:history:1",
        telegram_message_id=1,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Controlled historical body.",
        event_time=datetime(2026, 9, 1, tzinfo=UTC),
        from_history=True,
    )

    assert event.from_history


def test_telethon_adapter_enforces_exact_scope_and_bounded_history() -> None:
    values = {
        "TELEGRAM_API_ID": "123456",
        "TELEGRAM_API_HASH": "controlled-api-hash",
        "TELEGRAM_SESSION_STRING": "controlled-session",
        "TELEGRAM_ADMIN_USER_ID": "789012",
    }
    approved_identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    other_identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 43)
    checkpoint = TelegramChannelCheckpoint(pts=10)
    source = _RecordingTelethonSource()
    source.result = TelegramDifferenceEvent(
        source_chat_identity=other_identity,
        from_checkpoint=checkpoint,
        to_checkpoint=checkpoint,
        source_event_id="source-event:scope:1",
        telegram_message_id=1,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Controlled body.",
        event_time=datetime(2026, 9, 1, tzinfo=UTC),
    )
    runtime = TelethonRuntime.from_mapping(
        values,
        client_factory=lambda _: object(),
    )
    runtime.verify_conformance(
        transport=ControlledTelethonTransport(),
        approved_source_chats=(approved_identity,),
    )
    adapter = TelethonIngestionAdapter(
        runtime=runtime,
        source=source,
        approved_source_chats=(approved_identity,),
    )

    with pytest.raises(TelethonConformanceError) as scope_error:
        adapter.get_channel_difference_event(approved_identity, checkpoint)

    assert scope_error.value.status == "scope_mismatch"
    assert "43" not in str(scope_error.value)

    with pytest.raises(TelethonConformanceError) as window_error:
        adapter.get_source_chat_history_event(
            approved_identity,
            1,
            checkpoint,
            datetime(2026, 9, 1, tzinfo=UTC),
            datetime(2026, 9, 7, tzinfo=UTC),
        )
    assert window_error.value.status == "history_window_invalid"
    assert source.history_calls == 0

    source.raise_on_history = True
    with pytest.raises(TelethonTransportError) as transport_error:
        adapter.get_source_chat_history_event(
            approved_identity,
            1,
            checkpoint,
            datetime(2026, 8, 31, tzinfo=UTC),
            datetime(2026, 9, 7, tzinfo=UTC),
        )
    assert "controlled-secret" not in str(transport_error.value)


def test_telethon_adapter_canonicalizes_events_and_enforces_channel_origin() -> None:
    values = {
        "TELEGRAM_API_ID": "123456",
        "TELEGRAM_API_HASH": "controlled-api-hash",
        "TELEGRAM_SESSION_STRING": "controlled-session",
        "TELEGRAM_ADMIN_USER_ID": "789012",
    }
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    checkpoint = TelegramChannelCheckpoint(pts=10)
    source = _RecordingTelethonSource()
    source.result = TelegramDifferenceEvent(
        source_chat_identity=identity,
        from_checkpoint=checkpoint,
        to_checkpoint=TelegramChannelCheckpoint(pts=11),
        source_event_id="provider-id-that-is-not-canonical",
        telegram_message_id=7,
        revision=2,
        kind=SourceEventKind.EDIT,
        body="Controlled body.",
        event_time=datetime(2026, 9, 1, tzinfo=UTC),
        registry_generation=1,
    )
    runtime = TelethonRuntime.from_mapping(
        values,
        client_factory=lambda _: object(),
    )
    runtime.verify_conformance(
        transport=ControlledTelethonTransport(),
        approved_source_chats=(identity,),
    )
    adapter = TelethonIngestionAdapter(
        runtime=runtime,
        source=source,
        approved_source_chats=(identity,),
    )

    result = adapter.get_channel_difference_event(
        identity,
        checkpoint,
        registry_generation=1,
    )

    assert isinstance(result, TelegramDifferenceEvent)
    assert result.source_event_id == (
        "telegram-event:channel:42:message:7:revision:2:kind:edit"
    )

    source.result = replace(
        result,
        from_checkpoint=checkpoint,
        to_checkpoint=checkpoint,
        from_history=True,
    )
    with pytest.raises(TelethonTransportError) as error:
        adapter.get_channel_difference_event(
            identity,
            checkpoint,
            registry_generation=1,
        )
    assert error.value.reason.value == "checkpoint_invalid"


def test_telethon_adapter_allows_durably_admitted_account_identity() -> None:
    values = {
        "TELEGRAM_API_ID": "123456",
        "TELEGRAM_API_HASH": "controlled-api-hash",
        "TELEGRAM_SESSION_STRING": "controlled-session",
        "TELEGRAM_ADMIN_USER_ID": "789012",
    }
    approved_identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    admitted_identity = TelegramPeerIdentity(TelegramPeerKind.CHAT, 43)
    checkpoint = TelegramAccountCheckpoint(
        pts=10,
        qts=20,
        seq=30,
        date=datetime(2026, 9, 1, tzinfo=UTC),
    )
    advanced = replace(checkpoint, pts=11, seq=31)
    source = _RecordingTelethonSource()
    source.account_result = TelegramDifferenceEvent(
        source_chat_identity=admitted_identity,
        from_checkpoint=checkpoint,
        to_checkpoint=advanced,
        source_event_id="provider-id-that-is-not-canonical",
        telegram_message_id=7,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Durably admitted account event.",
        event_time=advanced.date,
        registry_generation=3,
    )
    runtime = TelethonRuntime.from_mapping(
        values,
        client_factory=lambda _: object(),
    )
    runtime.verify_conformance(
        transport=ControlledTelethonTransport(),
        approved_source_chats=(approved_identity,),
    )
    adapter = TelethonIngestionAdapter(
        runtime=runtime,
        source=source,
        approved_source_chats=(approved_identity,),
    )
    adapter.configure_source_scope_generation_lookup(
        lambda identity: 3 if identity == admitted_identity else None
    )

    result = adapter.get_account_difference_event(checkpoint)

    assert isinstance(result, TelegramDifferenceEvent)
    assert result.source_chat_identity == admitted_identity
    assert result.source_event_id == (
        "telegram-event:chat:43:message:7:revision:1:kind:create:generation:3"
    )


class _ProductionClientProbe:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.handlers: list[object] = []

    def connect(self) -> None:
        self.calls.append("connect")

    def is_user_authorized(self) -> bool:
        self.calls.append("is_user_authorized")
        return True

    def get_me(self) -> object:
        self.calls.append("get_me")
        return SimpleNamespace(id=789012)

    def get_entity(self, entity: object) -> object:
        self.calls.append(f"get_entity:{entity}")
        return _channel_entity()

    def add_event_handler(self, callback: object, event: object) -> None:
        del callback
        self.handlers.append(event)

    def run_until_disconnected(self) -> None:
        self.calls.append("run_until_disconnected")

    def catch_up(self) -> None:
        self.calls.append("catch_up")


def test_production_telethon_provider_is_lazy_and_wires_live_client_boundary() -> None:
    client = _ProductionClientProbe()
    provider = TelethonProvider(client=client)

    assert client.calls == []
    assert provider.authenticate() == 789012
    assert provider.check_source_chat_access(
        TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    )
    callback_identities: list[TelegramPeerIdentity] = []
    provider.start_live_ingestion(callback_identities.append)
    provider.run_live_ingestion()

    assert client.calls[:3] == ["connect", "is_user_authorized", "get_me"]
    assert len(client.handlers) == 3
    assert client.calls[-2:] == ["catch_up", "run_until_disconnected"]


class _DifferenceClientProbe:
    def __init__(
        self,
        responses: list[object],
        *,
        entities: list[object] | None = None,
        history_messages: list[object] | None = None,
    ) -> None:
        self.responses = responses
        self.entities = entities or []
        self.default_entity = _channel_entity()
        self.history_messages = history_messages or []
        self.requests: list[object] = []
        self.entity_requests: list[object] = []
        self.history_kwargs: dict[str, object] | None = None

    def __call__(self, request: object) -> object:
        self.requests.append(request)
        return self.responses.pop(0)

    def get_entity(self, entity: object) -> object:
        self.entity_requests.append(entity)
        if self.entities:
            return self.entities.pop(0)
        if isinstance(entity, types.PeerChat):
            return _chat_entity()
        return self.default_entity

    def iter_messages(self, _entity: object, **kwargs: object) -> object:
        self.history_kwargs = kwargs
        return iter(self.history_messages)


def _account_message(
    *,
    message_id: int,
    identity: TelegramPeerIdentity,
    event_time: datetime,
    body: str,
) -> SimpleNamespace:
    peer = (
        types.PeerChannel(identity.telegram_id)
        if identity.kind is TelegramPeerKind.CHANNEL
        else types.PeerChat(identity.telegram_id)
    )
    return SimpleNamespace(
        id=message_id,
        peer_id=peer,
        date=event_time,
        message=body,
        noforwards=False,
    )


def _channel_entity(
    *,
    telegram_id: int = 42,
    noforwards: bool | None = False,
) -> types.Channel:
    return types.Channel(
        id=telegram_id,
        title="controlled channel",
        photo=types.ChatPhotoEmpty(),
        date=None,
        broadcast=True,
        noforwards=noforwards,
        access_hash=9,
    )


def _chat_entity(
    *,
    telegram_id: int = 42,
    noforwards: bool | None = False,
) -> types.Chat:
    return types.Chat(
        id=telegram_id,
        title="controlled chat",
        photo=types.ChatPhotoEmpty(),
        participants_count=0,
        date=None,
        version=1,
        noforwards=noforwards,
    )


def test_provider_reads_account_checkpoint_from_difference_state() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHAT, 42)
    checkpoint = TelegramAccountCheckpoint(
        pts=10,
        qts=20,
        seq=30,
        date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )
    advanced = TelegramAccountCheckpoint(
        pts=11,
        qts=21,
        seq=31,
        date=datetime(2026, 9, 1, 10, 1, tzinfo=UTC),
    )
    client = _DifferenceClientProbe(
        [
            SimpleNamespace(
                new_messages=[
                    _account_message(
                        message_id=1,
                        identity=identity,
                        event_time=advanced.date,
                        body="account body",
                    )
                ],
                other_updates=[],
                state=SimpleNamespace(
                    pts=advanced.pts,
                    qts=advanced.qts,
                    seq=advanced.seq,
                    date=advanced.date,
                ),
            )
        ]
    )
    provider = TelethonProvider(client=client, approved_source_chats=(identity,))

    result = provider.get_account_difference_event(checkpoint)

    assert isinstance(result, TelegramDifferenceEvent)
    assert result.from_checkpoint == checkpoint
    assert result.to_checkpoint == advanced


def test_provider_normalizes_every_channel_page_update_and_acknowledges_in_order() -> (
    None
):
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    checkpoint = TelegramChannelCheckpoint(pts=10)
    advanced = TelegramChannelCheckpoint(pts=14)
    event_time = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    edit_message = _account_message(
        message_id=3,
        identity=identity,
        event_time=event_time,
        body="edited body",
    )
    edit_message.edit_date = event_time + timedelta(minutes=1)
    response = SimpleNamespace(
        new_messages=[
            _account_message(
                message_id=1,
                identity=identity,
                event_time=event_time,
                body="first",
            ),
            _account_message(
                message_id=2,
                identity=identity,
                event_time=event_time,
                body="second",
            ),
        ],
        other_updates=[
            types.UpdateEditChannelMessage(edit_message, pts=13, pts_count=1),
            types.UpdateDeleteChannelMessages(
                channel_id=identity.telegram_id,
                messages=[4],
                pts=14,
                pts_count=1,
            ),
        ],
        pts=advanced.pts,
    )
    client = _DifferenceClientProbe([response])
    provider = TelethonProvider(
        client=client,
        approved_source_chats=(identity,),
        clock=SimpleNamespace(now=lambda: event_time + timedelta(minutes=2)),
    )

    first = provider.get_channel_difference_event(identity, checkpoint, 1)
    assert isinstance(first, TelegramDifferenceEvent)
    retry = provider.get_channel_difference_event(identity, checkpoint, 1)
    assert isinstance(retry, TelegramDifferenceEvent)
    assert retry.source_event_id == first.source_event_id
    results: list[TelegramDifferenceEvent] = [first]
    provider.acknowledge_channel_difference_event(
        identity,
        1,
        checkpoint,
        first.source_event_id,
    )
    for _ in range(3):
        result = provider.get_channel_difference_event(identity, checkpoint, 1)
        assert isinstance(result, TelegramDifferenceEvent)
        results.append(result)
        provider.acknowledge_channel_difference_event(
            identity,
            1,
            checkpoint,
            _difference_result_id(result),
        )

    assert [result.telegram_message_id for result in results] == [1, 2, 3, 4]
    assert [result.kind for result in results] == [
        SourceEventKind.CREATE,
        SourceEventKind.CREATE,
        SourceEventKind.EDIT,
        SourceEventKind.DELETE,
    ]
    assert all(result.from_checkpoint == checkpoint for result in results)
    assert all(result.to_checkpoint == checkpoint for result in results[:-1])
    assert results[-1].to_checkpoint == advanced
    assert results[-1].event_time == event_time + timedelta(minutes=2)


def test_provider_rejects_basic_chat_delete_constructor_on_channel_route() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    response = SimpleNamespace(
        new_messages=[],
        other_updates=[types.UpdateDeleteMessages([4], 11, 1)],
        pts=11,
    )
    provider = TelethonProvider(
        client=_DifferenceClientProbe([response]),
        approved_source_chats=(identity,),
    )

    with pytest.raises(TelethonTransportError) as error:
        provider.get_channel_difference_event(
            identity,
            TelegramChannelCheckpoint(pts=10),
            1,
        )

    assert error.value.reason.value == "checkpoint_invalid"
    assert error.value.scope is not None
    assert error.value.scope.value == "source_stream"


@pytest.mark.parametrize(
    "update",
    (
        pytest.param(
            types.UpdateDeleteChannelMessages(99, [4], 11, 1),
            id="wrong-channel-delete",
        ),
        pytest.param(
            types.UpdateNewChannelMessage(
                _account_message(
                    message_id=4,
                    identity=TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 99),
                    event_time=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
                    body="wrong channel body",
                ),
                11,
                1,
            ),
            id="wrong-channel-message",
        ),
        pytest.param(
            types.UpdateNewMessage(
                _account_message(
                    message_id=4,
                    identity=TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42),
                    event_time=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
                    body="generic channel body",
                ),
                11,
                1,
            ),
            id="generic-channel-message",
        ),
    ),
)
def test_provider_fails_closed_for_channel_identity_and_constructor_mismatches(
    update: object,
) -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    provider = TelethonProvider(
        client=_DifferenceClientProbe(
            [SimpleNamespace(new_messages=[], other_updates=[update], pts=11)]
        ),
        approved_source_chats=(identity,),
    )

    with pytest.raises(TelethonTransportError) as error:
        provider.get_channel_difference_event(
            identity,
            TelegramChannelCheckpoint(pts=10),
            1,
        )

    assert error.value.reason is IngestionFailureReason.CHECKPOINT_INVALID
    assert error.value.scope is IngestionFailureScope.SOURCE_STREAM


def test_provider_fails_closed_for_malformed_in_scope_channel_message() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    checkpoint = TelegramChannelCheckpoint(pts=10)
    malformed_message = SimpleNamespace(
        id=1,
        peer_id=SimpleNamespace(channel_id=42),
        date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        message="controlled in-scope body",
        noforwards=False,
    )
    client = _DifferenceClientProbe(
        [SimpleNamespace(new_messages=[malformed_message], other_updates=[], pts=11)]
    )
    provider = TelethonProvider(client=client, approved_source_chats=(identity,))

    with pytest.raises(TelethonTransportError) as error:
        provider.get_channel_difference_event(identity, checkpoint, 1)

    assert error.value.reason.value == "checkpoint_invalid"
    assert error.value.scope is not None
    assert error.value.scope.value == "source_stream"


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("new_messages", 17),
        ("messages", 17),
        ("other_updates", 17),
        ("new_messages", {}),
        ("messages", {}),
        ("other_updates", {}),
        ("new_messages", "malformed"),
        ("messages", "malformed"),
        ("other_updates", "malformed"),
        ("new_messages", None),
        ("messages", None),
        ("other_updates", None),
        ("new_messages", b"malformed"),
        ("messages", b"malformed"),
        ("other_updates", b"malformed"),
    ),
)
def test_provider_fails_closed_for_non_iterable_difference_container(
    field_name: str,
    value: object,
) -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    response = SimpleNamespace(pts=11)
    setattr(response, field_name, value)
    provider = TelethonProvider(
        client=_DifferenceClientProbe([response]),
        approved_source_chats=(identity,),
    )

    with pytest.raises(TelethonTransportError) as error:
        provider.get_channel_difference_event(
            identity,
            TelegramChannelCheckpoint(pts=10),
            1,
        )

    assert error.value.reason.value == "checkpoint_invalid"


def test_provider_fails_closed_for_unknown_difference_update() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    response = SimpleNamespace(
        new_messages=[],
        other_updates=[object()],
        pts=11,
    )
    provider = TelethonProvider(
        client=_DifferenceClientProbe([response]),
        approved_source_chats=(identity,),
    )

    with pytest.raises(TelethonTransportError) as error:
        provider.get_channel_difference_event(
            identity,
            TelegramChannelCheckpoint(pts=10),
            1,
        )

    assert error.value.reason.value == "checkpoint_invalid"


@pytest.mark.parametrize("field_name", ("new_messages", "messages", "other_updates"))
def test_provider_fails_closed_for_malformed_difference_items(field_name: str) -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    response = SimpleNamespace(new_messages=[], other_updates=[], pts=11)
    setattr(response, field_name, [{}])
    provider = TelethonProvider(
        client=_DifferenceClientProbe([response]),
        approved_source_chats=(identity,),
    )

    with pytest.raises(TelethonTransportError) as error:
        provider.get_channel_difference_event(
            identity,
            TelegramChannelCheckpoint(pts=10),
            1,
        )

    assert error.value.reason.value == "checkpoint_invalid"


@pytest.mark.parametrize("vector", ([], ()))
def test_provider_accepts_valid_empty_difference_vectors(
    vector: list[object] | tuple[object, ...],
) -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    response = SimpleNamespace(
        new_messages=vector,
        messages=vector,
        other_updates=vector,
        pts=11,
    )
    result = TelethonProvider(
        client=_DifferenceClientProbe([response]),
        approved_source_chats=(identity,),
    ).get_channel_difference_event(
        identity,
        TelegramChannelCheckpoint(pts=10),
        1,
    )

    assert isinstance(result, TelegramDifferenceCheckpointAdvance)
    assert result.to_checkpoint == TelegramChannelCheckpoint(pts=11)


@pytest.mark.parametrize(
    "response",
    (
        SimpleNamespace(pts=11),
        SimpleNamespace(new_messages=[], pts=11),
        SimpleNamespace(other_updates=[], pts=11),
    ),
)
def test_provider_rejects_missing_difference_collections(response: object) -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    provider = TelethonProvider(
        client=_DifferenceClientProbe([response]),
        approved_source_chats=(identity,),
    )

    with pytest.raises(TelethonTransportError) as error:
        provider.get_channel_difference_event(
            identity,
            TelegramChannelCheckpoint(pts=10),
            1,
        )

    assert error.value.reason is IngestionFailureReason.CHECKPOINT_INVALID
    assert error.value.scope is IngestionFailureScope.SOURCE_STREAM


def test_provider_accepts_typed_empty_channel_difference() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    result = TelethonProvider(
        client=_DifferenceClientProbe(
            [types.updates.ChannelDifferenceEmpty(pts=11, final=True)]
        ),
        approved_source_chats=(identity,),
    ).get_channel_difference_event(
        identity,
        TelegramChannelCheckpoint(pts=10),
        1,
    )

    assert isinstance(result, TelegramDifferenceCheckpointAdvance)
    assert result.to_checkpoint == TelegramChannelCheckpoint(pts=11)


@pytest.mark.parametrize(
    "update",
    (
        pytest.param(
            types.UpdateUserStatus(42, types.UserStatusRecently()),
            id="UpdateUserStatus",
        ),
        pytest.param(types.UpdateChannel(42), id="UpdateChannel"),
        pytest.param(types.UpdateChat(42), id="UpdateChat"),
        pytest.param(types.UpdateUser(42), id="UpdateUser"),
        pytest.param(
            types.UpdateChannelParticipant(
                42,
                datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
                7,
                8,
                9,
            ),
            id="UpdateChannelParticipant",
        ),
        pytest.param(
            types.UpdateWebPage(types.WebPageEmpty(1), 11, 1),
            id="UpdateWebPage",
        ),
        pytest.param(
            types.UpdateChannelAvailableMessages(42, 1),
            id="UpdateChannelAvailableMessages",
        ),
        pytest.param(
            types.UpdateUserName(42, "Controlled", "", []),
            id="UpdateUserName",
        ),
        pytest.param(types.UpdatePtsChanged(), id="UpdatePtsChanged"),
        pytest.param(
            types.UpdateChannelTooLong(42, pts=11),
            id="UpdateChannelTooLong",
        ),
        pytest.param(
            types.UpdateChatParticipantAdd(
                42,
                43,
                44,
                datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
                1,
            ),
            id="UpdateChatParticipantAdd",
        ),
        pytest.param(
            types.UpdateUserPhone(42, "controlled-phone"),
            id="UpdateUserPhone",
        ),
        pytest.param(
            types.UpdateChannelUserTyping(
                42,
                types.PeerUser(7),
                types.SendMessageTypingAction(),
            ),
            id="UpdateChannelUserTyping",
        ),
        pytest.param(
            types.UpdateChannelWebPage(42, types.WebPageEmpty(1), 11, 1),
            id="UpdateChannelWebPage",
        ),
        pytest.param(
            types.UpdateFolderPeers([], 11, 1),
            id="UpdateFolderPeers",
        ),
        pytest.param(
            types.UpdateMessageExtendedMedia(types.PeerChannel(42), 1, []),
            id="UpdateMessageExtendedMedia",
        ),
    ),
)
@pytest.mark.parametrize("route", ("account", "channel"))
def test_provider_ignores_typed_unrelated_updates_on_both_routes(
    update: object,
    route: str,
) -> None:
    if route == "account":
        account_checkpoint = TelegramAccountCheckpoint(
            pts=10,
            qts=20,
            seq=30,
            date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        )
        account_advanced = replace(account_checkpoint, pts=11, seq=31)
        response = SimpleNamespace(
            new_messages=[],
            other_updates=[update],
            state=SimpleNamespace(
                pts=account_advanced.pts,
                qts=account_advanced.qts,
                seq=account_advanced.seq,
                date=account_advanced.date,
            ),
        )
        result = TelethonProvider(
            client=_DifferenceClientProbe([response]),
        ).get_account_difference_event(account_checkpoint)
        assert isinstance(result, TelegramDifferenceCheckpointAdvance)
        assert result.from_checkpoint == account_checkpoint
        assert result.to_checkpoint == account_advanced
    else:
        identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
        channel_checkpoint = TelegramChannelCheckpoint(pts=10)
        channel_advanced = TelegramChannelCheckpoint(pts=11)
        response = SimpleNamespace(
            new_messages=[],
            other_updates=[update],
            pts=channel_advanced.pts,
        )
        result = TelethonProvider(
            client=_DifferenceClientProbe([response]),
            approved_source_chats=(identity,),
        ).get_channel_difference_event(identity, channel_checkpoint, 1)
        assert isinstance(result, TelegramDifferenceCheckpointAdvance)
        assert result.from_checkpoint == channel_checkpoint
        assert result.to_checkpoint == channel_advanced


def test_provider_accepts_typed_empty_account_difference_boundary() -> None:
    checkpoint = TelegramAccountCheckpoint(
        pts=10,
        qts=20,
        seq=30,
        date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )
    advanced_date = datetime(2026, 9, 1, 10, 1, tzinfo=UTC)
    result = TelethonProvider(
        client=_DifferenceClientProbe(
            [types.updates.DifferenceEmpty(date=advanced_date, seq=31)]
        )
    ).get_account_difference_event(checkpoint)

    assert isinstance(result, TelegramDifferenceCheckpointAdvance)
    assert result.to_checkpoint == TelegramAccountCheckpoint(
        pts=checkpoint.pts,
        qts=checkpoint.qts,
        seq=31,
        date=advanced_date,
    )


_MISSING_CHECKPOINT_FIELD = object()


@pytest.mark.parametrize(
    "state",
    (
        _MISSING_CHECKPOINT_FIELD,
        None,
        SimpleNamespace(qts=21, seq=31, date=datetime(2026, 9, 1, 10, 1, tzinfo=UTC)),
        SimpleNamespace(
            pts=None,
            qts=21,
            seq=31,
            date=datetime(2026, 9, 1, 10, 1, tzinfo=UTC),
        ),
        SimpleNamespace(
            pts=11,
            qts=-1,
            seq=31,
            date=datetime(2026, 9, 1, 10, 1, tzinfo=UTC),
        ),
        SimpleNamespace(
            pts=11,
            qts=21,
            seq="malformed",
            date=datetime(2026, 9, 1, 10, 1, tzinfo=UTC),
        ),
        SimpleNamespace(pts=11, qts=21, seq=31, date=None),
        SimpleNamespace(pts=11, qts=21, seq=31, date=datetime(2026, 9, 1, 10, 1)),
    ),
)
def test_provider_fails_closed_for_missing_or_invalid_account_checkpoint_state(
    state: object,
) -> None:
    checkpoint = TelegramAccountCheckpoint(
        pts=10,
        qts=20,
        seq=30,
        date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )
    response = SimpleNamespace(new_messages=[], other_updates=[])
    if state is not _MISSING_CHECKPOINT_FIELD:
        response.state = state
    provider = TelethonProvider(client=_DifferenceClientProbe([response]))

    with pytest.raises(TelethonTransportError) as error:
        provider.get_account_difference_event(checkpoint)

    assert error.value.reason.value == "checkpoint_invalid"
    assert error.value.scope is not None
    assert error.value.scope.value == "account_stream"


@pytest.mark.parametrize("pts", (_MISSING_CHECKPOINT_FIELD, None, -1, "malformed"))
def test_provider_fails_closed_for_missing_or_invalid_channel_checkpoint(
    pts: object,
) -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    checkpoint = TelegramChannelCheckpoint(pts=10)
    response = SimpleNamespace(new_messages=[], other_updates=[])
    if pts is not _MISSING_CHECKPOINT_FIELD:
        response.pts = pts
    provider = TelethonProvider(
        client=_DifferenceClientProbe([response]),
        approved_source_chats=(identity,),
    )

    with pytest.raises(TelethonTransportError) as error:
        provider.get_channel_difference_event(identity, checkpoint, 1)

    assert error.value.reason.value == "checkpoint_invalid"
    assert error.value.scope is not None
    assert error.value.scope.value == "source_stream"


@pytest.mark.parametrize("route", ("account", "channel"))
@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("pts", _MISSING_CHECKPOINT_FIELD),
        ("pts", None),
        ("pts_count", _MISSING_CHECKPOINT_FIELD),
        ("pts_count", None),
        ("pts_count", 0),
    ),
)
def test_provider_fails_closed_for_invalid_typed_update_progress(
    route: str,
    field_name: str,
    value: object,
) -> None:
    event_time = datetime(2026, 9, 1, 10, 1, tzinfo=UTC)
    if route == "account":
        identity = TelegramPeerIdentity(TelegramPeerKind.CHAT, 42)
        account_checkpoint = TelegramAccountCheckpoint(
            pts=10,
            qts=20,
            seq=30,
            date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        )
        update = types.UpdateNewMessage(
            _account_message(
                message_id=1,
                identity=identity,
                event_time=event_time,
                body="account body",
            ),
            pts=11,
            pts_count=1,
        )
        response = SimpleNamespace(
            new_messages=[],
            other_updates=[update],
            state=SimpleNamespace(pts=11, qts=20, seq=31, date=event_time),
        )
    else:
        identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
        channel_checkpoint = TelegramChannelCheckpoint(pts=10)
        update = types.UpdateNewChannelMessage(
            _account_message(
                message_id=1,
                identity=identity,
                event_time=event_time,
                body="channel body",
            ),
            pts=11,
            pts_count=1,
        )
        response = SimpleNamespace(
            new_messages=[],
            other_updates=[update],
            pts=11,
        )
    if value is _MISSING_CHECKPOINT_FIELD:
        delattr(update, field_name)
    else:
        setattr(update, field_name, value)
    provider = TelethonProvider(
        client=_DifferenceClientProbe([response]),
        approved_source_chats=(identity,) if route == "channel" else (),
    )

    with pytest.raises(TelethonTransportError) as error:
        if route == "account":
            provider.get_account_difference_event(account_checkpoint)
        else:
            provider.get_channel_difference_event(identity, channel_checkpoint, 1)

    assert error.value.reason.value == "checkpoint_invalid"


@pytest.mark.parametrize("message_ids", ({}, "malformed", b"malformed", 17))
def test_provider_fails_closed_for_malformed_deletion_id_collections(
    message_ids: object,
) -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    response = SimpleNamespace(
        new_messages=[],
        other_updates=[types.UpdateDeleteChannelMessages(42, message_ids, 11, 1)],
        pts=11,
    )
    provider = TelethonProvider(
        client=_DifferenceClientProbe([response]),
        approved_source_chats=(identity,),
    )

    with pytest.raises(TelethonTransportError) as error:
        provider.get_channel_difference_event(
            identity,
            TelegramChannelCheckpoint(pts=10),
            1,
        )

    assert error.value.reason.value == "checkpoint_invalid"


def test_provider_ignores_scheduled_updates() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    checkpoint = TelegramChannelCheckpoint(pts=10)
    scheduled_message = _account_message(
        message_id=1,
        identity=identity,
        event_time=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        body="scheduled body",
    )
    for update in (
        types.UpdateNewScheduledMessage(scheduled_message),
        types.UpdateDeleteScheduledMessages(types.PeerChannel(42), [1]),
    ):
        result = TelethonProvider(
            client=_DifferenceClientProbe(
                [SimpleNamespace(new_messages=[], other_updates=[update], pts=11)]
            ),
            approved_source_chats=(identity,),
        ).get_channel_difference_event(identity, checkpoint, 1)

        assert isinstance(result, TelegramDifferenceCheckpointAdvance)
        assert result.to_checkpoint == TelegramChannelCheckpoint(pts=11)


def test_provider_rejects_non_final_channel_registration_boundary() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    client = _DifferenceClientProbe([SimpleNamespace(pts=11, final=False)])
    provider = TelethonProvider(
        client=client,
        approved_source_chats=(identity,),
    )

    with pytest.raises(TelethonTransportError) as error:
        provider.capture_source_chat_registration_boundary(identity)

    assert error.value.reason is IngestionFailureReason.CHECKPOINT_UNAVAILABLE
    assert client.responses == []


def test_unrelated_account_updates_are_body_free_checkpoint_progress() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHAT, 42)
    checkpoint = TelegramAccountCheckpoint(
        pts=10,
        qts=20,
        seq=30,
        date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )
    advanced = TelegramAccountCheckpoint(
        pts=11,
        qts=20,
        seq=31,
        date=datetime(2026, 9, 1, 10, 1, tzinfo=UTC),
    )
    private_message = _account_message(
        message_id=7,
        identity=TelegramPeerIdentity(TelegramPeerKind.CHAT, 99),
        event_time=advanced.date,
        body="private body",
    )
    private_message.peer_id = types.PeerUser(99)
    client = _DifferenceClientProbe(
        [
            SimpleNamespace(
                new_messages=[private_message],
                other_updates=[
                    types.UpdateRecentReactions(),
                    types.UpdateDeleteMessages([8], 11, 1),
                ],
                state=SimpleNamespace(
                    pts=advanced.pts,
                    qts=advanced.qts,
                    seq=advanced.seq,
                    date=advanced.date,
                ),
            )
        ]
    )
    provider = TelethonProvider(client=client, approved_source_chats=(identity,))

    result = provider.get_account_difference_event(checkpoint)

    assert isinstance(result, TelegramDifferenceCheckpointAdvance)
    assert result.source_chat_identity is None
    assert result.from_checkpoint == checkpoint
    assert result.to_checkpoint == advanced
    provider.acknowledge_account_difference_event(
        checkpoint,
        result.outcome_id,
    )


def test_provider_resolves_basic_delete_through_durable_message_lookup() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHAT, 42)
    checkpoint = TelegramAccountCheckpoint(
        pts=10,
        qts=20,
        seq=30,
        date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )
    advanced = replace(
        checkpoint, pts=11, seq=31, date=datetime(2026, 9, 1, 10, 1, tzinfo=UTC)
    )
    client = _DifferenceClientProbe(
        [
            SimpleNamespace(
                new_messages=[],
                other_updates=[types.UpdateDeleteMessages([8], 11, 1)],
                state=SimpleNamespace(
                    pts=advanced.pts,
                    qts=advanced.qts,
                    seq=advanced.seq,
                    date=advanced.date,
                ),
            )
        ]
    )
    provider = TelethonProvider(
        client=client,
        approved_source_chats=(identity,),
        message_identity_lookup=lambda message_id: (
            identity if message_id == 8 else None
        ),
        clock=SimpleNamespace(now=lambda: advanced.date),
    )

    result = provider.get_account_difference_event(checkpoint)

    assert isinstance(result, TelegramDifferenceEvent)
    assert result.source_chat_identity == identity
    assert result.telegram_message_id == 8
    assert result.kind is SourceEventKind.DELETE
    assert result.body is None
    assert result.event_time == advanced.date
    assert result.to_checkpoint == advanced


@pytest.mark.parametrize(
    ("durable_identity", "should_resolve"),
    (
        (TelegramPeerIdentity(TelegramPeerKind.CHAT, 42), True),
        (TelegramPeerIdentity(TelegramPeerKind.CHAT, 99), False),
        (None, False),
    ),
)
def test_provider_reconciles_warm_peerless_delete_with_durable_identity(
    durable_identity: TelegramPeerIdentity | None,
    should_resolve: bool,
) -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHAT, 42)
    checkpoint = TelegramAccountCheckpoint(
        pts=10,
        qts=20,
        seq=30,
        date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )
    warm_checkpoint = replace(
        checkpoint,
        pts=11,
        seq=31,
        date=datetime(2026, 9, 1, 10, 1, tzinfo=UTC),
    )
    delete_checkpoint = replace(
        warm_checkpoint,
        pts=12,
        seq=32,
        date=datetime(2026, 9, 1, 10, 2, tzinfo=UTC),
    )
    response = SimpleNamespace(
        new_messages=[
            _account_message(
                message_id=8,
                identity=identity,
                event_time=warm_checkpoint.date,
                body="warm cache source",
            )
        ],
        other_updates=[],
        state=SimpleNamespace(
            pts=warm_checkpoint.pts,
            qts=warm_checkpoint.qts,
            seq=warm_checkpoint.seq,
            date=warm_checkpoint.date,
        ),
    )
    delete_response = SimpleNamespace(
        new_messages=[],
        other_updates=[types.UpdateDeleteMessages([8], 12, 1)],
        state=SimpleNamespace(
            pts=delete_checkpoint.pts,
            qts=delete_checkpoint.qts,
            seq=delete_checkpoint.seq,
            date=delete_checkpoint.date,
        ),
    )
    lookup_calls: list[int] = []

    def lookup(message_id: int) -> TelegramPeerIdentity | None:
        lookup_calls.append(message_id)
        return durable_identity

    provider = TelethonProvider(
        client=_DifferenceClientProbe([response, delete_response]),
        approved_source_chats=(identity,),
        message_identity_lookup=lookup,
        clock=SimpleNamespace(now=lambda: delete_checkpoint.date),
    )

    warm_result = provider.get_account_difference_event(checkpoint)
    assert isinstance(warm_result, TelegramDifferenceEvent)
    provider.acknowledge_account_difference_event(
        checkpoint,
        warm_result.source_event_id,
    )

    if should_resolve:
        result = provider.get_account_difference_event(warm_checkpoint)
        assert isinstance(result, TelegramDifferenceEvent)
        assert result.source_chat_identity == identity
        assert result.kind is SourceEventKind.DELETE
        assert result.to_checkpoint == delete_checkpoint
    else:
        with pytest.raises(TelethonTransportError) as error:
            provider.get_account_difference_event(warm_checkpoint)
        assert error.value.reason.value == "checkpoint_invalid"

    assert lookup_calls == [8]


def test_account_delete_rejects_without_a_current_live_boundary() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHAT, 42)
    checkpoint = TelegramAccountCheckpoint(
        pts=10,
        qts=20,
        seq=30,
        date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )
    response = SimpleNamespace(
        new_messages=[],
        other_updates=[types.UpdateDeleteMessages([8], 11, 1)],
        state=SimpleNamespace(pts=11, qts=20, seq=31),
    )
    provider = TelethonProvider(
        client=_DifferenceClientProbe([response]),
        approved_source_chats=(identity,),
        message_identity_lookup=lambda _message_id: identity,
    )

    with pytest.raises(TelethonTransportError) as error:
        provider.get_account_difference_event(checkpoint)

    assert error.value.reason.value == "checkpoint_invalid"


def test_provider_uses_a_distinct_application_clock_time_for_each_account_delete() -> (
    None
):
    identity = TelegramPeerIdentity(TelegramPeerKind.CHAT, 42)
    checkpoint = TelegramAccountCheckpoint(
        pts=10,
        qts=20,
        seq=30,
        date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )
    advanced = replace(
        checkpoint,
        pts=12,
        seq=32,
        date=datetime(2026, 9, 1, 10, 10, tzinfo=UTC),
    )
    first_observation = checkpoint.date + timedelta(minutes=1)
    observations = [first_observation]

    def now() -> datetime:
        value = observations[0]
        observations[0] += timedelta(seconds=1)
        return value

    provider = TelethonProvider(
        client=_DifferenceClientProbe(
            [
                SimpleNamespace(
                    new_messages=[],
                    other_updates=[
                        types.UpdateDeleteMessages([8, 9], 11, 1),
                    ],
                    state=SimpleNamespace(
                        pts=advanced.pts,
                        qts=advanced.qts,
                        seq=advanced.seq,
                        date=advanced.date,
                    ),
                )
            ]
        ),
        approved_source_chats=(identity,),
        message_identity_lookup=lambda _message_id: identity,
        clock=SimpleNamespace(now=now),
    )

    first = provider.get_account_difference_event(checkpoint)
    assert isinstance(first, TelegramDifferenceEvent)
    provider.acknowledge_account_difference_event(checkpoint, first.source_event_id)
    second = provider.get_account_difference_event(checkpoint)

    assert isinstance(second, TelegramDifferenceEvent)
    assert first.event_time == first_observation
    assert second.event_time == first_observation + timedelta(seconds=1)
    assert first.event_time != advanced.date
    assert second.event_time != advanced.date


def test_channel_delete_fails_closed_without_an_application_clock() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    response = SimpleNamespace(
        new_messages=[],
        other_updates=[types.UpdateDeleteChannelMessages(42, [9], 11, 1)],
        pts=11,
    )
    provider = TelethonProvider(
        client=_DifferenceClientProbe([response]),
        approved_source_chats=(identity,),
    )

    with pytest.raises(TelethonTransportError) as error:
        provider.get_channel_difference_event(
            identity,
            TelegramChannelCheckpoint(pts=10),
            1,
        )

    assert error.value.reason.value == "checkpoint_invalid"


def test_basic_chat_participant_is_the_visible_source_publisher() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHAT, 42)
    checkpoint = TelegramAccountCheckpoint(
        pts=10,
        qts=20,
        seq=30,
        date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )
    advanced = replace(checkpoint, pts=11, seq=31)
    message = _account_message(
        message_id=9,
        identity=identity,
        event_time=advanced.date,
        body="participant body",
    )
    message.from_id = types.PeerUser(777)
    client = _DifferenceClientProbe(
        [
            SimpleNamespace(
                new_messages=[message],
                other_updates=[],
                state=SimpleNamespace(
                    pts=advanced.pts,
                    qts=advanced.qts,
                    seq=advanced.seq,
                    date=advanced.date,
                ),
            )
        ]
    )

    result = TelethonProvider(
        client=client,
        approved_source_chats=(identity,),
    ).get_account_difference_event(checkpoint)

    assert isinstance(result, TelegramDifferenceEvent)
    assert result.bounded_metadata["source_author_telegram_id"] == 777
    assert result.bounded_metadata["source_publisher_id"] is not None
    assert result.bounded_metadata["source_publisher_id"] != (
        "publisher:telegram-" + sha256(b"telegram:chat:42").hexdigest()[:32]
    )


def test_provider_fails_closed_for_ambiguous_peerless_delete() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHAT, 42)
    checkpoint = TelegramAccountCheckpoint(
        pts=10,
        qts=20,
        seq=30,
        date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )
    advanced = replace(checkpoint, pts=11, seq=31)
    response = SimpleNamespace(
        new_messages=[],
        other_updates=[types.UpdateDeleteMessages([9], 11, 1)],
        state=SimpleNamespace(
            pts=advanced.pts,
            qts=advanced.qts,
            seq=advanced.seq,
            date=advanced.date,
        ),
    )

    def ambiguous_lookup(_message_id: int) -> TelegramPeerIdentity:
        raise ValueError("ambiguous")

    provider = TelethonProvider(
        client=_DifferenceClientProbe([response]),
        approved_source_chats=(identity,),
        message_identity_lookup=ambiguous_lookup,
    )

    with pytest.raises(TelethonTransportError) as error:
        provider.get_account_difference_event(checkpoint)

    assert error.value.reason.value == "checkpoint_invalid"


def test_provider_ignores_unmapped_peerless_delete_without_starving_account() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHAT, 42)
    checkpoint = TelegramAccountCheckpoint(
        pts=10,
        qts=20,
        seq=30,
        date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )
    advanced = replace(checkpoint, pts=11, seq=31)
    response = SimpleNamespace(
        new_messages=[],
        other_updates=[types.UpdateDeleteMessages([9], 11, 1)],
        state=SimpleNamespace(
            pts=advanced.pts,
            qts=advanced.qts,
            seq=advanced.seq,
            date=advanced.date,
        ),
    )
    provider = TelethonProvider(
        client=_DifferenceClientProbe([response]),
        approved_source_chats=(identity,),
        message_identity_lookup=lambda _message_id: None,
    )

    result = provider.get_account_difference_event(checkpoint)

    assert isinstance(result, TelegramDifferenceCheckpointAdvance)
    assert result.to_checkpoint == advanced


def test_channel_message_cache_cannot_resolve_account_peerless_delete() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    account_checkpoint = TelegramAccountCheckpoint(
        pts=20,
        qts=30,
        seq=40,
        date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )
    channel_message = _account_message(
        message_id=9,
        identity=identity,
        event_time=account_checkpoint.date,
        body="channel message",
    )
    account_response = SimpleNamespace(
        new_messages=[],
        other_updates=[types.UpdateDeleteMessages([9], 21, 1)],
        state=SimpleNamespace(
            pts=21,
            qts=30,
            seq=41,
            date=account_checkpoint.date + timedelta(minutes=1),
        ),
    )
    provider = TelethonProvider(
        client=_DifferenceClientProbe(
            [
                SimpleNamespace(
                    new_messages=[channel_message],
                    other_updates=[],
                    pts=11,
                ),
                account_response,
            ]
        ),
        approved_source_chats=(identity,),
    )

    channel_result = provider.get_channel_difference_event(
        identity,
        TelegramChannelCheckpoint(pts=10),
        1,
    )
    assert isinstance(channel_result, TelegramDifferenceEvent)
    provider.acknowledge_channel_difference_event(
        identity,
        1,
        TelegramChannelCheckpoint(pts=10),
        channel_result.source_event_id,
    )

    account_result = provider.get_account_difference_event(account_checkpoint)

    assert isinstance(account_result, TelegramDifferenceCheckpointAdvance)
    assert account_result.to_checkpoint.pts == 21


def test_provider_treats_absent_optional_copy_protection_as_unprotected() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    checkpoint = TelegramChannelCheckpoint(pts=10)
    message = _account_message(
        message_id=1,
        identity=identity,
        event_time=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        body="must not be exposed",
    )
    client = _DifferenceClientProbe(
        [SimpleNamespace(new_messages=[message], other_updates=[], pts=11)],
        entities=[_channel_entity(noforwards=None), _channel_entity(noforwards=None)],
    )
    provider = TelethonProvider(client=client, approved_source_chats=(identity,))

    result = provider.get_channel_difference_event(identity, checkpoint, 1)

    assert isinstance(result, TelegramDifferenceEvent)
    assert result.body == "must not be exposed"


def test_provider_fails_closed_when_copy_protection_attribute_is_missing() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    checkpoint = TelegramChannelCheckpoint(pts=10)
    message = SimpleNamespace(
        id=1,
        peer_id=types.PeerChannel(42),
        date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        message="must not be exposed",
    )
    client = _DifferenceClientProbe(
        [SimpleNamespace(new_messages=[message], other_updates=[], pts=11)],
        entities=[_channel_entity(noforwards=False), _channel_entity(noforwards=False)],
    )
    provider = TelethonProvider(client=client, approved_source_chats=(identity,))

    with pytest.raises(TelethonTransportError) as error:
        provider.get_channel_difference_event(identity, checkpoint, 1)

    assert error.value.reason.value == "protection_unavailable"


def test_live_and_history_edits_share_a_route_independent_identity() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    checkpoint = TelegramChannelCheckpoint(pts=10)
    event_time = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    edit_date = event_time + timedelta(minutes=1)

    live_message = _account_message(
        message_id=9,
        identity=identity,
        event_time=event_time,
        body="same edit",
    )
    live_message.edit_date = edit_date
    live_provider = TelethonProvider(
        client=_DifferenceClientProbe(
            [
                SimpleNamespace(
                    new_messages=[],
                    other_updates=[types.UpdateEditChannelMessage(live_message, 99, 1)],
                    pts=100,
                )
            ]
        ),
        approved_source_chats=(identity,),
    )
    live = live_provider.get_channel_difference_event(identity, checkpoint, 1)

    history_message = _account_message(
        message_id=9,
        identity=identity,
        event_time=event_time,
        body="same edit",
    )
    history_message.edit_date = edit_date
    history_provider = TelethonProvider(
        client=_DifferenceClientProbe([], history_messages=[history_message]),
        approved_source_chats=(identity,),
    )
    history = history_provider.get_source_chat_history_event(
        identity,
        1,
        checkpoint,
        event_time - timedelta(days=1),
        event_time + timedelta(days=1),
    )

    assert isinstance(live, TelegramDifferenceEvent)
    assert isinstance(history, TelegramDifferenceEvent)
    assert live.source_event_id == history.source_event_id


def test_restarted_provider_distinguishes_same_time_edit_pts_occurrences() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    checkpoint = TelegramChannelCheckpoint(pts=10)
    event_time = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    edit_date = event_time + timedelta(minutes=1)
    durable_history: list[
        tuple[int, SourceEventKind, str | None, datetime, str | None, int | None]
    ] = []

    def revision_history(
        requested_identity: TelegramPeerIdentity,
        requested_generation: int,
        requested_message_id: int,
    ) -> tuple[
        tuple[int, SourceEventKind, str | None, datetime, str | None, int | None], ...
    ]:
        assert requested_identity == identity
        assert requested_generation == 1
        assert requested_message_id == 9
        return tuple(durable_history)

    def edit_message(body: str) -> types.Message:
        return types.Message(
            id=9,
            peer_id=types.PeerChannel(identity.telegram_id),
            date=event_time,
            message=body,
            noforwards=False,
            edit_date=edit_date,
        )

    def edit_response(body: str, pts: int) -> SimpleNamespace:
        return SimpleNamespace(
            new_messages=[],
            other_updates=[types.UpdateEditChannelMessage(edit_message(body), pts, 1)],
            pts=pts,
        )

    first = TelethonProvider(
        client=_DifferenceClientProbe([edit_response("A", 11)]),
        approved_source_chats=(identity,),
        revision_history_lookup=revision_history,
    ).get_channel_difference_event(identity, checkpoint, 1)
    assert isinstance(first, TelegramDifferenceEvent)
    durable_history.append(
        (
            first.revision,
            first.kind,
            first.body,
            first.event_time,
            first.transport_event_id,
            first.transport_order,
        )
    )

    second = TelethonProvider(
        client=_DifferenceClientProbe([edit_response("B", 12)]),
        approved_source_chats=(identity,),
        revision_history_lookup=revision_history,
    ).get_channel_difference_event(identity, checkpoint, 1)

    assert isinstance(second, TelegramDifferenceEvent)
    assert second.body == "B"
    assert second.revision > first.revision
    assert second.source_event_id != first.source_event_id
    assert second.transport_event_id != first.transport_event_id

    replayed = TelethonProvider(
        client=_DifferenceClientProbe([edit_response("A", 11)]),
        approved_source_chats=(identity,),
        revision_history_lookup=revision_history,
    ).get_channel_difference_event(identity, checkpoint, 1)

    assert isinstance(replayed, TelegramDifferenceEvent)
    assert replayed.body == "A"
    assert replayed.revision == first.revision
    assert replayed.source_event_id == first.source_event_id


def test_durable_transport_history_reconciles_overlap_and_stale_snapshots() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    checkpoint = TelegramChannelCheckpoint(pts=10)
    publication_time = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    first_edit_time = publication_time + timedelta(minutes=1)
    second_edit_time = publication_time + timedelta(minutes=2)
    durable_history: list[
        tuple[int, SourceEventKind, str | None, datetime, str | None, int | None]
    ] = []

    def revision_history(
        requested_identity: TelegramPeerIdentity,
        requested_generation: int,
        requested_message_id: int,
    ) -> tuple[
        tuple[int, SourceEventKind, str | None, datetime, str | None, int | None], ...
    ]:
        assert requested_identity == identity
        assert requested_generation == 1
        assert requested_message_id == 9
        return tuple(durable_history)

    def edit_message(edit_time: datetime, body: str) -> SimpleNamespace:
        message = _account_message(
            message_id=9,
            identity=identity,
            event_time=publication_time,
            body=body,
        )
        message.edit_date = edit_time
        return message

    first = TelethonProvider(
        client=_DifferenceClientProbe(
            [
                SimpleNamespace(
                    new_messages=[],
                    other_updates=[
                        types.UpdateEditChannelMessage(
                            edit_message(first_edit_time, "A"), 11, 1
                        )
                    ],
                    pts=11,
                )
            ]
        ),
        approved_source_chats=(identity,),
        revision_history_lookup=revision_history,
    ).get_channel_difference_event(identity, checkpoint, 1)
    assert isinstance(first, TelegramDifferenceEvent)
    durable_history.append(
        (
            first.revision,
            first.kind,
            first.body,
            first.event_time,
            first.transport_event_id,
            first.transport_order,
        )
    )

    replayed = TelethonProvider(
        client=_DifferenceClientProbe(
            [],
            history_messages=[edit_message(first_edit_time, "A")],
        ),
        approved_source_chats=(identity,),
        revision_history_lookup=revision_history,
    ).get_source_chat_history_event(
        identity,
        1,
        checkpoint,
        publication_time - timedelta(days=1),
        publication_time + timedelta(days=1),
    )
    assert isinstance(replayed, TelegramDifferenceEvent)
    assert replayed.source_event_id == first.source_event_id
    assert replayed.revision == first.revision
    assert replayed.transport_event_id == first.transport_event_id
    assert replayed.transport_order == first.transport_order

    second = TelethonProvider(
        client=_DifferenceClientProbe(
            [
                SimpleNamespace(
                    new_messages=[],
                    other_updates=[
                        types.UpdateEditChannelMessage(
                            edit_message(second_edit_time, "B"), 12, 1
                        )
                    ],
                    pts=12,
                )
            ]
        ),
        approved_source_chats=(identity,),
        revision_history_lookup=revision_history,
    ).get_channel_difference_event(
        identity,
        TelegramChannelCheckpoint(pts=11),
        1,
    )
    assert isinstance(second, TelegramDifferenceEvent)
    durable_history.append(
        (
            second.revision,
            second.kind,
            second.body,
            second.event_time,
            second.transport_event_id,
            second.transport_order,
        )
    )

    late_replay = TelethonProvider(
        client=_DifferenceClientProbe(
            [],
            history_messages=[edit_message(first_edit_time, "A")],
        ),
        approved_source_chats=(identity,),
        revision_history_lookup=revision_history,
    ).get_source_chat_history_event(
        identity,
        1,
        checkpoint,
        publication_time - timedelta(days=1),
        publication_time + timedelta(days=1),
    )
    assert isinstance(late_replay, TelegramDifferenceEvent)
    assert late_replay.source_event_id == first.source_event_id
    assert late_replay.revision == first.revision
    assert late_replay.transport_event_id == first.transport_event_id
    assert late_replay.transport_order == first.transport_order

    third_edit_time = publication_time + timedelta(minutes=3)
    history_first = TelethonProvider(
        client=_DifferenceClientProbe(
            [],
            history_messages=[edit_message(third_edit_time, "C")],
        ),
        approved_source_chats=(identity,),
        revision_history_lookup=revision_history,
    ).get_source_chat_history_event(
        identity,
        1,
        checkpoint,
        publication_time - timedelta(days=1),
        publication_time + timedelta(days=1),
    )
    assert isinstance(history_first, TelegramDifferenceEvent)
    durable_history.append(
        (
            history_first.revision,
            history_first.kind,
            history_first.body,
            history_first.event_time,
            history_first.transport_event_id,
            history_first.transport_order,
        )
    )

    live_after_history = TelethonProvider(
        client=_DifferenceClientProbe(
            [
                SimpleNamespace(
                    new_messages=[],
                    other_updates=[
                        types.UpdateEditChannelMessage(
                            edit_message(third_edit_time, "C"), 13, 1
                        )
                    ],
                    pts=13,
                )
            ]
        ),
        approved_source_chats=(identity,),
        revision_history_lookup=revision_history,
    ).get_channel_difference_event(
        identity,
        TelegramChannelCheckpoint(pts=12),
        1,
    )

    assert isinstance(live_after_history, TelegramDifferenceEvent)
    assert live_after_history.source_event_id == history_first.source_event_id
    assert live_after_history.revision == history_first.revision
    assert live_after_history.transport_event_id == history_first.transport_event_id
    assert live_after_history.transport_order == history_first.transport_order


def test_public_source_url_is_provenance_only_without_positive_reply_evidence() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    entity = _channel_entity()
    entity.username = "valid_source"
    message = _account_message(
        message_id=9,
        identity=identity,
        event_time=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        body="public post",
    )
    result = TelethonProvider(
        client=_DifferenceClientProbe(
            [
                SimpleNamespace(
                    new_messages=[message],
                    other_updates=[],
                    pts=11,
                )
            ],
            entities=[entity, entity],
        ),
        approved_source_chats=(identity,),
    ).get_channel_difference_event(identity, TelegramChannelCheckpoint(pts=10), 1)

    assert isinstance(result, TelegramDifferenceEvent)
    assert result.bounded_metadata["source_message_url"] == (
        "https://t.me/valid_source/9"
    )
    assert result.bounded_metadata["reply_route_url"] is None
    assert result.bounded_metadata["source_message_reply_capable"] is False

    message.replies = SimpleNamespace(comments=True)
    positive = TelethonProvider(
        client=_DifferenceClientProbe(
            [
                SimpleNamespace(
                    new_messages=[message],
                    other_updates=[],
                    pts=11,
                )
            ],
            entities=[entity, entity],
        ),
        approved_source_chats=(identity,),
    ).get_channel_difference_event(identity, TelegramChannelCheckpoint(pts=10), 1)

    assert isinstance(positive, TelegramDifferenceEvent)
    assert positive.bounded_metadata["reply_route_url"] == (
        "https://t.me/valid_source/9"
    )
    assert positive.bounded_metadata["source_message_reply_capable"] is True


def test_admitted_source_chat_refreshes_active_scope_and_runtime_conformance() -> None:
    values = {
        "TELEGRAM_API_ID": "123456",
        "TELEGRAM_API_HASH": "controlled-api-hash",
        "TELEGRAM_SESSION_STRING": "controlled-session",
        "TELEGRAM_ADMIN_USER_ID": "789012",
    }
    initial_identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    new_identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 43)
    runtime = TelethonRuntime.from_mapping(values, client_factory=lambda _: object())
    runtime.verify_conformance(
        transport=ControlledTelethonTransport(),
        approved_source_chats=(initial_identity,),
    )
    source = TelethonProvider(
        client=_ProductionClientProbe(), approved_source_chats=(initial_identity,)
    )
    callback_identities: list[TelegramPeerIdentity] = []
    adapter = TelethonIngestionAdapter(
        runtime=runtime,
        source=source,
        approved_source_chats=(initial_identity,),
        live_update_callback=callback_identities.append,
    )
    resolution = SourceChatAdmissionResolution(
        identity=new_identity,
        address_kind=SourceChatAddressKind.PUBLIC_USERNAME,
        current_address="@new_source",
    )

    adapter.admit_source_chat(
        resolution,
        registry_generation=2,
        processing_started_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        transport_boundary="channel-pts:10",
    )

    assert new_identity in runtime.conformance_scope
    adapter.notify_live_update(new_identity)
    assert callback_identities == [new_identity]


def test_history_uses_ascending_lower_boundary_and_stops_at_upper_boundary() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    checkpoint = TelegramChannelCheckpoint(pts=10)
    window = SourceChatHistoryWindow(
        start_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        end_at=datetime(2026, 9, 8, 10, 0, tzinfo=UTC),
    )
    client = _DifferenceClientProbe(
        [],
        history_messages=[
            _account_message(
                message_id=1,
                identity=identity,
                event_time=window.start_at,
                body="at lower bound",
            ),
            _account_message(
                message_id=2,
                identity=identity,
                event_time=window.end_at + timedelta(seconds=1),
                body="after upper bound",
            ),
        ],
    )
    provider = TelethonProvider(client=client, approved_source_chats=(identity,))

    result = provider.get_source_chat_history_event(
        identity,
        1,
        checkpoint,
        window.start_at,
        window.end_at,
    )

    assert isinstance(result, TelegramDifferenceEvent)
    assert result.telegram_message_id == 1
    assert client.history_kwargs is not None
    assert client.history_kwargs["reverse"] is True
    offset_date = client.history_kwargs["offset_date"]
    assert isinstance(offset_date, datetime)
    assert offset_date < window.start_at


@pytest.mark.parametrize(
    "message",
    (
        SimpleNamespace(
            id=0,
            peer_id=types.PeerChannel(42),
            date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
            message="invalid id",
        ),
        SimpleNamespace(
            id=1,
            date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
            message="missing peer",
        ),
        SimpleNamespace(
            id=1,
            peer_id=types.PeerChannel(99),
            date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
            message="wrong peer",
        ),
    ),
)
def test_provider_fails_closed_for_malformed_history_messages(
    message: object,
) -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    client = _DifferenceClientProbe([], history_messages=[message])
    provider = TelethonProvider(client=client, approved_source_chats=(identity,))

    with pytest.raises(TelethonTransportError) as error:
        provider.get_source_chat_history_event(
            identity,
            1,
            TelegramChannelCheckpoint(pts=10),
            datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
            datetime(2026, 9, 8, 10, 0, tzinfo=UTC),
        )

    assert error.value.reason is IngestionFailureReason.CHECKPOINT_INVALID
    assert error.value.scope is IngestionFailureScope.SOURCE_STREAM


def test_protection_is_refreshed_before_body_access() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    checkpoint = TelegramChannelCheckpoint(pts=10)
    message_accessed = False

    class _LazyMessage:
        id = 1
        peer_id = types.PeerChannel(42)
        date = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
        noforwards = False

        @property
        def message(self) -> str:
            nonlocal message_accessed
            message_accessed = True
            return "protected body"

    initial_entity = _channel_entity(noforwards=False)
    refreshed_entity = _channel_entity(noforwards=True)
    client = _DifferenceClientProbe(
        [SimpleNamespace(new_messages=[_LazyMessage()], other_updates=[], pts=11)],
        entities=[initial_entity, refreshed_entity],
    )
    provider = TelethonProvider(client=client, approved_source_chats=(identity,))
    provider.resolve_source_chat("@protected_source")

    result = provider.get_channel_difference_event(identity, checkpoint, 1)

    assert isinstance(result, TelegramProtectedContentEvent)
    assert not message_accessed


def test_repeated_edits_have_monotonic_restart_stable_revisions() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    first_checkpoint = TelegramChannelCheckpoint(pts=10)
    second_checkpoint = TelegramChannelCheckpoint(pts=11)
    event_time = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)

    def edit_response(*, update_pts: int, response_pts: int, body: str) -> object:
        message = _account_message(
            message_id=9,
            identity=identity,
            event_time=event_time,
            body=body,
        )
        message.edit_date = event_time + timedelta(minutes=update_pts)
        return SimpleNamespace(
            new_messages=[],
            other_updates=[types.UpdateEditChannelMessage(message, update_pts, 1)],
            pts=response_pts,
        )

    client = _DifferenceClientProbe(
        [
            edit_response(update_pts=1, response_pts=11, body="edit one"),
            edit_response(update_pts=2, response_pts=12, body="edit two"),
        ]
    )
    provider = TelethonProvider(client=client, approved_source_chats=(identity,))
    first = provider.get_channel_difference_event(identity, first_checkpoint, 1)
    assert isinstance(first, TelegramDifferenceEvent)
    provider.acknowledge_channel_difference_event(
        identity,
        1,
        first_checkpoint,
        first.source_event_id,
    )
    second = provider.get_channel_difference_event(identity, second_checkpoint, 1)
    assert isinstance(second, TelegramDifferenceEvent)

    restarted_client = _DifferenceClientProbe(
        [edit_response(update_pts=1, response_pts=11, body="edit one")]
    )
    restarted = TelethonProvider(
        client=restarted_client,
        approved_source_chats=(identity,),
    ).get_channel_difference_event(identity, first_checkpoint, 1)

    assert first.revision >= 2
    assert second.revision > first.revision
    assert isinstance(restarted, TelegramDifferenceEvent)
    assert restarted.revision == first.revision
    assert restarted.source_event_id == first.source_event_id


def test_a_body_b_body_a_body_edits_are_three_transport_occurrences() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    event_time = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)

    def edit_response(*, body: str, minutes: int, pts: int) -> object:
        message = _account_message(
            message_id=9,
            identity=identity,
            event_time=event_time,
            body=body,
        )
        message.edit_date = event_time + timedelta(minutes=minutes)
        return SimpleNamespace(
            new_messages=[],
            other_updates=[types.UpdateEditChannelMessage(message, pts, 1)],
            pts=pts,
        )

    client = _DifferenceClientProbe(
        [
            edit_response(body="A", minutes=1, pts=11),
            edit_response(body="B", minutes=2, pts=12),
            edit_response(body="A", minutes=3, pts=13),
        ]
    )
    provider = TelethonProvider(client=client, approved_source_chats=(identity,))
    results: list[TelegramDifferenceEvent] = []

    for index in range(3):
        checkpoint = TelegramChannelCheckpoint(pts=10 + index)
        result = provider.get_channel_difference_event(identity, checkpoint, 1)
        assert isinstance(result, TelegramDifferenceEvent)
        results.append(result)
        provider.acknowledge_channel_difference_event(
            identity,
            1,
            checkpoint,
            result.source_event_id,
        )

    assert [result.body for result in results] == ["A", "B", "A"]
    assert [result.revision for result in results] == sorted(
        result.revision for result in results
    )
    assert len({result.source_event_id for result in results}) == 3


def test_readded_generation_does_not_reuse_generation_one_event_identity() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    event_time = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    message = _account_message(
        message_id=9,
        identity=identity,
        event_time=event_time,
        body="re-added source",
    )

    def response(pts: int) -> SimpleNamespace:
        return SimpleNamespace(
            new_messages=[message],
            other_updates=[],
            pts=pts,
        )

    provider = TelethonProvider(
        client=_DifferenceClientProbe([response(11), response(12)]),
        approved_source_chats=(identity,),
    )
    first_checkpoint = TelegramChannelCheckpoint(pts=10)
    first = provider.get_channel_difference_event(identity, first_checkpoint, 1)
    assert isinstance(first, TelegramDifferenceEvent)
    provider.acknowledge_channel_difference_event(
        identity,
        1,
        first_checkpoint,
        first.source_event_id,
    )

    provider.refresh_source_scope(
        (
            SourceChatRegistryEntry(
                identity=identity,
                registry_generation=2,
                address_kind=SourceChatAddressKind.PUBLIC_USERNAME,
                current_address="@valid_source",
                processing_started_at=event_time,
                transport_boundary="channel-pts:11",
                enabled=True,
                initial_consent_attestation=InitialConsentAttestation.CONFIRMED,
                attested_at=event_time,
            ),
        )
    )
    second = provider.get_channel_difference_event(
        identity,
        TelegramChannelCheckpoint(pts=11),
        2,
    )

    assert isinstance(second, TelegramDifferenceEvent)
    assert first.revision == second.revision == 1
    assert first.source_event_id != second.source_event_id
    assert second.source_event_id.endswith(":generation:2")


def test_same_timestamp_edits_and_a_later_delete_have_strict_revisions() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    first_checkpoint = TelegramChannelCheckpoint(pts=10)
    second_checkpoint = TelegramChannelCheckpoint(pts=11)
    third_checkpoint = TelegramChannelCheckpoint(pts=12)
    event_time = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)

    def edit_response(*, body: str, response_pts: int) -> object:
        message = _account_message(
            message_id=9,
            identity=identity,
            event_time=event_time,
            body=body,
        )
        message.edit_date = event_time + timedelta(minutes=1)
        return SimpleNamespace(
            new_messages=[],
            other_updates=[types.UpdateEditChannelMessage(message, response_pts, 1)],
            pts=response_pts,
        )

    client = _DifferenceClientProbe(
        [
            edit_response(body="first", response_pts=11),
            edit_response(body="second", response_pts=12),
            SimpleNamespace(
                new_messages=[],
                other_updates=[types.UpdateDeleteChannelMessages(42, [9], 13, 1)],
                pts=13,
            ),
        ]
    )
    provider = TelethonProvider(
        client=client,
        approved_source_chats=(identity,),
        clock=SimpleNamespace(now=lambda: event_time + timedelta(minutes=2)),
    )

    first = provider.get_channel_difference_event(identity, first_checkpoint, 1)
    second = provider.get_channel_difference_event(identity, second_checkpoint, 1)
    deleted = provider.get_channel_difference_event(identity, third_checkpoint, 1)

    assert isinstance(first, TelegramDifferenceEvent)
    assert isinstance(second, TelegramDifferenceEvent)
    assert isinstance(deleted, TelegramDifferenceEvent)
    assert second.revision > first.revision
    assert deleted.revision > second.revision
    assert deleted.kind is SourceEventKind.DELETE
    assert deleted.body is None


def test_restarted_provider_durable_revision_history_for_same_timestamp_edits() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    first_checkpoint = TelegramChannelCheckpoint(pts=10)
    second_checkpoint = TelegramChannelCheckpoint(pts=11)
    event_time = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    edit_date = event_time + timedelta(minutes=1)

    def edit_response(*, body: str, update_pts: int, response_pts: int) -> object:
        message = _account_message(
            message_id=9,
            identity=identity,
            event_time=event_time,
            body=body,
        )
        message.edit_date = edit_date
        return SimpleNamespace(
            new_messages=[],
            other_updates=[types.UpdateEditChannelMessage(message, update_pts, 1)],
            pts=response_pts,
        )

    durable_history: list[tuple[int, SourceEventKind, str | None, datetime]] = []

    def revision_history(
        requested_identity: TelegramPeerIdentity,
        requested_generation: int,
        requested_message_id: int,
    ) -> tuple[tuple[int, SourceEventKind, str | None, datetime], ...]:
        assert requested_identity == identity
        assert requested_generation == 1
        assert requested_message_id == 9
        return tuple(durable_history)

    first_provider = TelethonProvider(
        client=_DifferenceClientProbe(
            [edit_response(body="first", update_pts=11, response_pts=11)]
        ),
        approved_source_chats=(identity,),
        revision_history_lookup=revision_history,
    )
    first = first_provider.get_channel_difference_event(identity, first_checkpoint, 1)
    assert isinstance(first, TelegramDifferenceEvent)
    durable_history.append((first.revision, first.kind, first.body, first.event_time))

    restarted_provider = TelethonProvider(
        client=_DifferenceClientProbe(
            [edit_response(body="second", update_pts=12, response_pts=12)]
        ),
        approved_source_chats=(identity,),
        revision_history_lookup=revision_history,
    )
    second = restarted_provider.get_channel_difference_event(
        identity, second_checkpoint, 1
    )

    assert isinstance(second, TelegramDifferenceEvent)
    assert second.revision > first.revision
    assert second.source_event_id != first.source_event_id


def test_restarted_provider_replays_delete_time_and_allows_later_edit() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    delete_checkpoint = TelegramChannelCheckpoint(pts=10)
    edit_checkpoint = TelegramChannelCheckpoint(pts=11)
    message_time = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    delete_observed_at = message_time + timedelta(minutes=1)
    delete_response = SimpleNamespace(
        new_messages=[],
        other_updates=[types.UpdateDeleteChannelMessages(42, [9], 11, 1)],
        pts=11,
    )
    durable_history: list[
        tuple[int, SourceEventKind, str | None, datetime, str | None, int | None]
    ] = [(1, SourceEventKind.CREATE, "original", message_time, None, None)]

    def revision_history(
        requested_identity: TelegramPeerIdentity,
        requested_generation: int,
        requested_message_id: int,
    ) -> tuple[
        tuple[int, SourceEventKind, str | None, datetime, str | None, int | None], ...
    ]:
        assert requested_identity == identity
        assert requested_generation == 1
        assert requested_message_id == 9
        return tuple(durable_history)

    first_provider = TelethonProvider(
        client=_DifferenceClientProbe([delete_response]),
        approved_source_chats=(identity,),
        revision_history_lookup=revision_history,
        clock=SimpleNamespace(now=lambda: delete_observed_at),
    )
    first_delete = first_provider.get_channel_difference_event(
        identity, delete_checkpoint, 1
    )
    assert isinstance(first_delete, TelegramDifferenceEvent)
    assert first_delete.kind is SourceEventKind.DELETE
    assert first_delete.event_time == delete_observed_at
    durable_history.append(
        (
            first_delete.revision,
            first_delete.kind,
            first_delete.body,
            first_delete.event_time,
            first_delete.transport_event_id,
            first_delete.transport_order,
        )
    )

    edit_message = _account_message(
        message_id=9,
        identity=identity,
        event_time=message_time,
        body="later edit",
    )
    edit_message.edit_date = message_time + timedelta(minutes=2)
    restarted_provider = TelethonProvider(
        client=_DifferenceClientProbe(
            [
                delete_response,
                SimpleNamespace(
                    new_messages=[],
                    other_updates=[types.UpdateEditChannelMessage(edit_message, 12, 1)],
                    pts=12,
                ),
            ]
        ),
        approved_source_chats=(identity,),
        revision_history_lookup=revision_history,
        clock=SimpleNamespace(now=lambda: delete_observed_at),
    )
    replayed_delete = restarted_provider.get_channel_difference_event(
        identity, delete_checkpoint, 1
    )
    assert isinstance(replayed_delete, TelegramDifferenceEvent)
    assert replayed_delete.revision == first_delete.revision
    assert replayed_delete.event_time == first_delete.event_time

    restarted_provider.acknowledge_channel_difference_event(
        identity,
        1,
        delete_checkpoint,
        replayed_delete.source_event_id,
    )
    later_edit = restarted_provider.get_channel_difference_event(
        identity, edit_checkpoint, 1
    )
    assert isinstance(later_edit, TelegramDifferenceEvent)
    assert later_edit.kind is SourceEventKind.EDIT
    assert later_edit.revision > replayed_delete.revision


def test_account_difference_discards_unknown_identity_without_starving_the_stream() -> (
    None
):
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 43)
    checkpoint = TelegramAccountCheckpoint(
        pts=10,
        qts=20,
        seq=30,
        date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )
    advanced = replace(
        checkpoint,
        pts=11,
        seq=31,
        date=datetime(2026, 9, 1, 10, 1, tzinfo=UTC),
    )
    message = _account_message(
        message_id=9,
        identity=identity,
        event_time=advanced.date,
        body="must wait for scope activation",
    )
    response = SimpleNamespace(
        new_messages=[message],
        other_updates=[],
        state=SimpleNamespace(
            pts=advanced.pts,
            qts=advanced.qts,
            seq=advanced.seq,
            date=advanced.date,
        ),
    )
    client = _DifferenceClientProbe(
        [response, response],
        entities=[_channel_entity(telegram_id=43)],
    )
    durable_scope: dict[TelegramPeerIdentity, int] = {}
    provider = TelethonProvider(
        client=client,
        source_scope_generation_lookup=lambda requested_identity: durable_scope.get(
            requested_identity
        ),
    )

    discarded = provider.get_account_difference_event(checkpoint)
    assert isinstance(discarded, TelegramDifferenceCheckpointAdvance)
    assert discarded.to_checkpoint == advanced
    provider.acknowledge_account_difference_event(
        checkpoint,
        discarded.outcome_id,
    )

    durable_scope[identity] = 1
    event = provider.get_account_difference_event(checkpoint)

    assert isinstance(event, TelegramDifferenceEvent)
    assert event.source_chat_identity == identity
    assert event.registry_generation == 1
    assert event.body == "must wait for scope activation"
    assert event.to_checkpoint == advanced


def test_account_difference_keeps_body_free_pending_only_during_admission() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    checkpoint = TelegramAccountCheckpoint(
        pts=10,
        qts=20,
        seq=30,
        date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )
    advanced = replace(checkpoint, pts=11, seq=31)
    message = _account_message(
        message_id=9,
        identity=identity,
        event_time=advanced.date,
        body="must remain retryable",
    )
    client = _DifferenceClientProbe(
        [
            SimpleNamespace(
                new_messages=[message],
                other_updates=[],
                state=SimpleNamespace(
                    pts=advanced.pts,
                    qts=advanced.qts,
                    seq=advanced.seq,
                    date=advanced.date,
                ),
            )
        ],
        entities=[_channel_entity(telegram_id=42)],
    )
    provider = TelethonProvider(
        client=client,
        source_scope_generation_lookup=lambda _identity: None,
    )
    provider.resolve_source_chat("@admission_in_progress")

    result = provider.get_account_difference_event(checkpoint)

    assert isinstance(result, TelegramDifferencePending)
    assert result.telegram_message_id == 9
    assert result.to_checkpoint == advanced


def test_scope_refresh_clears_stale_admission_pending_state() -> None:
    identity = TelegramPeerIdentity(TelegramPeerKind.CHAT, 42)
    checkpoint = TelegramAccountCheckpoint(
        pts=10,
        qts=20,
        seq=30,
        date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    )
    advanced = replace(checkpoint, pts=11, seq=31)
    response = SimpleNamespace(
        new_messages=[],
        other_updates=[types.UpdateDeleteMessages([9], 11, 1)],
        state=SimpleNamespace(
            pts=advanced.pts,
            qts=advanced.qts,
            seq=advanced.seq,
            date=advanced.date,
        ),
    )
    provider = TelethonProvider(
        client=_DifferenceClientProbe(
            [response, response],
            entities=[_chat_entity(telegram_id=42)],
        ),
        source_scope_generation_lookup=lambda _identity: None,
        message_identity_lookup=lambda _message_id: identity,
    )
    provider.resolve_source_chat("@stale_admission")
    pending = provider.get_account_difference_event(checkpoint)
    assert isinstance(pending, TelegramDifferencePending)

    provider.refresh_source_scope(())

    advanced_result = provider.get_account_difference_event(checkpoint)
    assert isinstance(advanced_result, TelegramDifferenceCheckpointAdvance)
    assert advanced_result.to_checkpoint == advanced


def test_source_chat_admission_rejects_users_and_unknown_entities() -> None:
    class _UserEntityClient:
        def __init__(self, entity: object) -> None:
            self.entity = entity

        def get_entity(self, _address: object) -> object:
            return self.entity

    for entity in (
        types.User(42),
        SimpleNamespace(id=42),
        SimpleNamespace(id=42, title="unknown", noforwards=False),
    ):
        with pytest.raises(SourceChatAdmissionError):
            TelethonProvider(client=_UserEntityClient(entity)).resolve_source_chat(
                "@not_a_source"
            )


def _difference_result_id(result: TelegramDifferenceResult) -> str:
    if isinstance(result, TelegramDifferenceCheckpointAdvance):
        return result.outcome_id
    if isinstance(result, TelegramDifferenceEvent):
        return result.source_event_id
    raise AssertionError(f"unexpected test result: {result!r}")


def test_runtime_composes_and_verifies_the_production_provider() -> None:
    values = {
        "TELEGRAM_API_ID": "123456",
        "TELEGRAM_API_HASH": "controlled-api-hash",
        "TELEGRAM_SESSION_STRING": "controlled-session",
        "TELEGRAM_ADMIN_USER_ID": "789012",
    }
    identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 42)
    client = _ProductionClientProbe()
    runtime = TelethonRuntime.from_mapping(
        values,
        client_factory=lambda _: client,
    )

    adapter = TelethonIngestionAdapter.from_runtime(
        runtime=runtime,
        approved_source_chats=(identity,),
    )

    assert runtime.ready
    assert adapter.source_event_id("production-provider") == (
        "source-event:production-provider"
    )
    assert client.calls[:3] == ["connect", "is_user_authorized", "get_me"]
