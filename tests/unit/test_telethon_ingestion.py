"""Unit coverage for the provider-neutral Telethon ingestion boundary."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from telethon import types  # type: ignore[import-untyped]

from modules.domain import (
    InitialConsentAttestation,
    SourceChatAddressKind,
    SourceChatAdmissionResolution,
    SourceChatRegistryEntry,
    SourceEventKind,
    TelegramAccountCheckpoint,
    TelegramChannelCheckpoint,
    TelegramDifferenceCheckpointAdvance,
    TelegramDifferenceEvent,
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
        self.history_calls = 0
        self.raise_on_history = False

    def refresh_source_scope(
        self,
        approved_source_chats: object,
    ) -> None:
        del approved_source_chats

    def configure_message_identity_lookup(self, lookup: object) -> None:
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
        raise AssertionError(checkpoint)

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
    provider = TelethonProvider(client=client, approved_source_chats=(identity,))

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
                    SimpleNamespace(),
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
    )

    result = provider.get_account_difference_event(checkpoint)

    assert isinstance(result, TelegramDifferenceEvent)
    assert result.source_chat_identity == identity
    assert result.telegram_message_id == 8
    assert result.kind is SourceEventKind.DELETE
    assert result.body is None
    assert result.to_checkpoint == advanced


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
    provider = TelethonProvider(client=client, approved_source_chats=(identity,))

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
