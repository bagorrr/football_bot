"""Unit coverage for the provider-neutral Telethon ingestion boundary."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from modules.domain import (
    InitialConsentAttestation,
    SourceChatAddressKind,
    SourceChatAdmissionResolution,
    SourceChatRegistryEntry,
    SourceEventKind,
    TelegramAccountCheckpoint,
    TelegramChannelCheckpoint,
    TelegramDifferenceEvent,
    TelegramDifferenceResult,
    TelegramPeerIdentity,
    TelegramPeerKind,
)
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

    def get_channel_difference_event(
        self,
        identity: TelegramPeerIdentity,
        checkpoint: TelegramChannelCheckpoint,
        registry_generation: int | None = None,
    ) -> TelegramDifferenceResult | None:
        del identity, checkpoint, registry_generation
        return self.result

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
        return SimpleNamespace(id=42, broadcast=True, access_hash=9)

    def add_event_handler(self, callback: object, event: object) -> None:
        del callback
        self.handlers.append(event)

    def run_until_disconnected(self) -> None:
        self.calls.append("run_until_disconnected")


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
    assert client.calls[-1] == "run_until_disconnected"


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
