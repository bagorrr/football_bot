from __future__ import annotations

import shutil
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any, cast

import pytest

from apps import runtime_service
from modules.contracts import ContractEnvelope, ContractName, RuntimeRole
from modules.domain import (
    IngestionFailureReason,
    IngestionFailureScope,
    TelegramPeerIdentity,
    TelegramPeerKind,
)
from modules.geonames_location_resolver import GeoNamesLocationResolverAdapter


class _ReadyStore:
    def __init__(self, role: RuntimeRole, database_url: str, **_kwargs: object) -> None:
        self.role = role
        self.database_url = database_url

    def check_startup_readiness(self) -> None:
        return None

    def active_source_chat_ingestion_scope(
        self,
    ) -> tuple[tuple[TelegramPeerIdentity, int], ...]:
        return ()

    def source_chat_ingestion_generation(self, _identity: object) -> int | None:
        return None

    def source_chat_ingestion_bootstrap_required(self) -> bool:
        return True

    def source_chat_ingestion_activation_boundary(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
    ) -> tuple[datetime, str] | None:
        del identity, registry_generation
        return None


def test_application_runtime_preserves_classifier_promotion_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.postgres_adapter import PostgresRoleStore

    monkeypatch.setattr(
        PostgresRoleStore, "check_startup_readiness", lambda _self: None
    )

    service = runtime_service.build_runtime_service(
        "application",
        {
            "DATABASE_URL_APPLICATION": (
                "postgresql://football_application:controlled@db/football"
            ),
            "GEONAMES_USERNAME": "controlled-geonames-user",
            "LOCATIONIQ_ACCESS_TOKEN": "controlled-locationiq-token",
        },
        repository_root=Path("/srv/football-bot/current"),
    )

    assert service.store.require_classifier_promotion is True


def test_application_production_composition_uses_location_resolvers_without_telegram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules import postgres_adapter

    monkeypatch.setattr(postgres_adapter, "PostgresRoleStore", _ReadyStore)

    service = runtime_service.build_runtime_service(
        "application",
        {
            "DATABASE_URL_APPLICATION": (
                "postgresql://football_application:controlled@db/football"
            ),
            "GEONAMES_USERNAME": "controlled-geonames-user",
            "LOCATIONIQ_ACCESS_TOKEN": "controlled-locationiq-token",
        },
        repository_root=Path("/srv/football-bot/current"),
    )

    assert service.role is RuntimeRole.APPLICATION
    assert isinstance(
        service.application.location_resolver,
        GeoNamesLocationResolverAdapter,
    )
    assert service.application.telegram_admin_user_id is None
    assert service.application.telegram_delivery is None
    assert service.application.telegram_ingestion is None


def test_bot_assistant_production_composition_uses_real_adapters_and_t1_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules import postgres_adapter
    from modules.codex_bot_assistant_adapter import CodexSdkBotAssistantAdapter
    from modules.codex_semantic_adapters import (
        CodexConversationLanguageAdapter,
        CodexDateInterpretationAdapter,
    )

    monkeypatch.setattr(postgres_adapter, "PostgresRoleStore", _ReadyStore)

    service = runtime_service.build_runtime_service(
        "bot_assistant",
        {
            "DATABASE_URL_BOT_ASSISTANT": (
                "postgresql://football_bot_assistant:controlled@db/football"
            ),
            "GEONAMES_USERNAME": "controlled-geonames-user",
            "LOCATIONIQ_ACCESS_TOKEN": "controlled-locationiq-token",
            "TELEGRAM_BOT_TOKEN": "123456:controlled-token",
            "TELEGRAM_ADMIN_USER_ID": "123456",
            "BOT_ASSISTANT_MODEL": "gpt-5.6-luna",
            "BOT_ASSISTANT_REASONING_EFFORT": "high",
            "BOT_ASSISTANT_CODEX_HOME": "/var/lib/football-bot/bot_assistant/codex",
        },
        repository_root=Path("/srv/football-bot/current"),
    )

    assert service.role is RuntimeRole.BOT_ASSISTANT
    assert service.bot_api_ingress is not None
    assert isinstance(service.application.assistant_model, CodexSdkBotAssistantAdapter)
    assert isinstance(
        service.application.location_resolver,
        GeoNamesLocationResolverAdapter,
    )
    assert isinstance(
        service.application.conversation_language,
        CodexConversationLanguageAdapter,
    )
    assert isinstance(
        service.application.date_interpretation,
        CodexDateInterpretationAdapter,
    )
    assert service.application.telegram_admin_user_id == 123456
    assert service.application.telegram_ingestion is None
    assert service.bot_api_conformance is not None


def test_runtime_readiness_uses_only_read_only_bot_api_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules import t5_runtime_configuration

    class _Ingress:
        def __init__(self) -> None:
            self.readiness_checks = 0

        def verify_readiness(self) -> None:
            self.readiness_checks += 1

    class _Conformance:
        def __init__(self) -> None:
            self.probes = 0

        def run(self) -> None:
            self.probes += 1

    class _ReadyReport:
        configuration_ready = True

    ingress = _Ingress()
    conformance = _Conformance()
    monkeypatch.setattr(
        t5_runtime_configuration,
        "preflight_role",
        lambda _role, _projection: _ReadyReport(),
    )
    monkeypatch.setattr(
        runtime_service, "_emit_readiness", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(runtime_service, "_notify_systemd", lambda _message: None)

    def stop_runtime(_service: runtime_service.RuntimeService) -> None:
        raise RuntimeError("controlled stop")

    monkeypatch.setattr(runtime_service, "_run_bot_assistant", stop_runtime)
    service = runtime_service.RuntimeService(
        role=RuntimeRole.BOT_ASSISTANT,
        application=object(),
        store=object(),
        bot_api_ingress=ingress,
        bot_api_conformance=conformance,
    )

    assert runtime_service._run(service) == 1
    assert ingress.readiness_checks == 1
    assert conformance.probes == 0


def test_ingestion_production_composition_uses_generation_scoped_telethon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules import postgres_adapter, source_chat_bootstrap, telethon_ingestion
    from modules.telethon_ingestion import TelethonRuntime

    captured: list[dict[str, object]] = []
    recorded_at = datetime(2026, 1, 1, tzinfo=UTC)
    active_identity = TelegramPeerIdentity(TelegramPeerKind.CHANNEL, 1000)
    persisted_scope = ((active_identity, 7),)

    envelopes = tuple(
        SimpleNamespace(
            recorded_at=recorded_at,
            payload={
                "source_chat_key": f"source-chat:channel:{1000 + index}",
                "telegram_user_id": 123456,
                "telegram_peer_kind": "channel",
                "telegram_chat_id": 1000 + index,
                "address_kind": "public_username",
                "current_address": f"@{username}",
                "transport_boundary": f"channel-pts:{index}",
                "registry_generation": 1,
                "registration_request_id": f"request-{index}",
            },
        )
        for index, username in enumerate(
            ("piterfut", "lovefootballspb", "fballer_spb", "spbfutbol")
        )
    )

    class _RecordingSource:
        def __init__(self) -> None:
            self.refreshes: list[tuple[object, ...]] = []

        def refresh_source_scope(self, entries: Iterable[object]) -> None:
            self.refreshes.append(tuple(entries))

    class _PersistedScopeStore(_ReadyStore):
        def active_source_chat_ingestion_scope(
            self,
        ) -> tuple[tuple[TelegramPeerIdentity, int], ...]:
            return persisted_scope

        def source_chat_ingestion_generation(self, identity: object) -> int | None:
            return next(
                (
                    generation
                    for persisted_identity, generation in persisted_scope
                    if persisted_identity == identity
                ),
                None,
            )

        def source_chat_ingestion_bootstrap_required(self) -> bool:
            return False

    class _RecordingRuntime:
        def __init__(self) -> None:
            self.source = _RecordingSource()
            self.provider_kwargs: dict[str, object] = {}
            self.conformance_scopes: list[tuple[object, ...]] = []

        def create_production_provider(self, **kwargs: object) -> _RecordingSource:
            self.provider_kwargs = kwargs
            return self.source

        def verify_conformance(
            self,
            *,
            transport: _RecordingSource,
            approved_source_chats: Iterable[object],
        ) -> None:
            assert transport is self.source
            scope: tuple[object, ...] = tuple(approved_source_chats)
            self.conformance_scopes.append(scope)

    class _RecordingAdapter:
        def __init__(self, **kwargs: object) -> None:
            captured.append(kwargs)
            self.started = False

        def start_live_ingestion(self) -> None:
            self.started = True

    adapter_runtime = _RecordingRuntime()

    monkeypatch.setattr(postgres_adapter, "PostgresRoleStore", _PersistedScopeStore)
    monkeypatch.setattr(
        source_chat_bootstrap,
        "load_source_chat_seed_catalog",
        lambda _path: SimpleNamespace(seeds=(1, 2, 3, 4)),
    )
    monkeypatch.setattr(
        source_chat_bootstrap,
        "bootstrap_source_chat_catalog",
        lambda *args, **kwargs: envelopes,
    )
    monkeypatch.setattr(
        TelethonRuntime,
        "from_projection",
        staticmethod(lambda _projection: adapter_runtime),
    )
    monkeypatch.setattr(
        telethon_ingestion,
        "TelethonIngestionAdapter",
        _RecordingAdapter,
    )

    service = runtime_service.build_runtime_service(
        "ingestion",
        {
            "DATABASE_URL_INGESTION": (
                "postgresql://football_ingestion:controlled@db/football"
            ),
            "TELEGRAM_API_ID": "123456",
            "TELEGRAM_API_HASH": "controlled-api-hash",
            "TELEGRAM_SESSION_STRING": "controlled-session",
            "TELEGRAM_ADMIN_USER_ID": "123456",
        },
        repository_root=Path("/srv/football-bot/current"),
    )

    assert service.role is RuntimeRole.INGESTION
    assert service.telethon_ingestion is service.application.telegram_ingestion
    scope = captured[0]["approved_source_chats"]
    assert scope == (active_identity,)
    assert adapter_runtime.conformance_scopes == [scope]
    assert adapter_runtime.source.refreshes == [scope]
    assert captured[0]["source"] is adapter_runtime.source
    assert adapter_runtime.provider_kwargs["source_scope_generation_lookup"] == (
        service.store.source_chat_ingestion_generation
    )
    assert service.telethon_ingestion.started is True


def test_ingestion_restart_does_not_rebootstrap_paused_or_removed_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules import postgres_adapter, source_chat_bootstrap, telethon_ingestion
    from modules.telethon_ingestion import TelethonRuntime

    class _ExistingRegistryStore(_ReadyStore):
        def source_chat_ingestion_bootstrap_required(self) -> bool:
            return False

    class _Source:
        def __init__(self) -> None:
            self.refreshes: list[tuple[object, ...]] = []

        def refresh_source_scope(self, scope: Iterable[object]) -> None:
            self.refreshes.append(tuple(scope))

    class _Runtime:
        def __init__(self) -> None:
            self.source = _Source()

        def create_production_provider(self, **_kwargs: object) -> _Source:
            return self.source

        def verify_conformance(
            self,
            *,
            transport: _Source,
            approved_source_chats: Iterable[object],
        ) -> None:
            assert transport is self.source
            assert tuple(approved_source_chats) == ()

    class _Adapter:
        def __init__(self, **_kwargs: object) -> None:
            self.started = False

        def start_live_ingestion(self) -> None:
            self.started = True

    adapter_runtime = _Runtime()

    def unexpected_seed_load(_path: Path) -> object:
        raise AssertionError("YAML seeds must not be loaded for an existing registry")

    monkeypatch.setattr(postgres_adapter, "PostgresRoleStore", _ExistingRegistryStore)
    monkeypatch.setattr(
        source_chat_bootstrap,
        "load_source_chat_seed_catalog",
        unexpected_seed_load,
    )
    monkeypatch.setattr(
        source_chat_bootstrap,
        "bootstrap_source_chat_catalog",
        lambda *_args, **_kwargs: pytest.fail("existing registry must not bootstrap"),
    )
    monkeypatch.setattr(
        TelethonRuntime,
        "from_projection",
        staticmethod(lambda _projection: adapter_runtime),
    )
    monkeypatch.setattr(telethon_ingestion, "TelethonIngestionAdapter", _Adapter)

    service = runtime_service.build_runtime_service(
        "ingestion",
        {
            "DATABASE_URL_INGESTION": (
                "postgresql://football_ingestion:controlled@db/football"
            ),
            "TELEGRAM_API_ID": "123456",
            "TELEGRAM_API_HASH": "controlled-api-hash",
            "TELEGRAM_SESSION_STRING": "controlled-session",
            "TELEGRAM_ADMIN_USER_ID": "123456",
        },
        repository_root=Path("/srv/football-bot/current"),
    )

    assert adapter_runtime.source.refreshes == [()]
    assert service.telethon_ingestion is service.application.telegram_ingestion


def test_ingestion_bootstraps_only_after_telethon_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules import postgres_adapter, source_chat_bootstrap, telethon_ingestion
    from modules.telethon_ingestion import TelethonRuntime

    events: list[str] = []

    class _RecordingSource:
        def __init__(self) -> None:
            self.authenticated = False

        def refresh_source_scope(self, _entries: object) -> None:
            return None

        def resolve_source_chat(self, _address: str) -> object:
            assert self.authenticated
            events.append("resolve_source_chat")
            return object()

    class _RecordingRuntime:
        def __init__(self) -> None:
            self.source = _RecordingSource()

        def create_production_provider(self, **_kwargs: object) -> _RecordingSource:
            return self.source

        def verify_conformance(
            self,
            *,
            transport: _RecordingSource,
            approved_source_chats: Iterable[object],
        ) -> None:
            assert transport is self.source
            assert tuple(approved_source_chats) == ()
            events.append("authenticate")
            self.source.authenticated = True

    class _RecordingAdapter:
        def __init__(self, **_kwargs: object) -> None:
            self.started = False

        def start_live_ingestion(self) -> None:
            self.started = True

    def bootstrap(
        _catalog: object,
        *,
        ingestion: _RecordingSource,
        **_kwargs: object,
    ) -> tuple[object, ...]:
        ingestion.resolve_source_chat("@piterfut")
        return (object(), object(), object(), object())

    adapter_runtime = _RecordingRuntime()
    monkeypatch.setattr(postgres_adapter, "PostgresRoleStore", _ReadyStore)
    monkeypatch.setattr(
        source_chat_bootstrap,
        "load_source_chat_seed_catalog",
        lambda _path: SimpleNamespace(seeds=(1, 2, 3, 4)),
    )
    monkeypatch.setattr(
        source_chat_bootstrap,
        "bootstrap_source_chat_catalog",
        bootstrap,
    )
    monkeypatch.setattr(
        TelethonRuntime,
        "from_projection",
        staticmethod(lambda _projection: adapter_runtime),
    )
    monkeypatch.setattr(
        telethon_ingestion,
        "TelethonIngestionAdapter",
        _RecordingAdapter,
    )

    runtime_service.build_runtime_service(
        "ingestion",
        {
            "DATABASE_URL_INGESTION": (
                "postgresql://football_ingestion:controlled@db/football"
            ),
            "TELEGRAM_API_ID": "123456",
            "TELEGRAM_API_HASH": "controlled-api-hash",
            "TELEGRAM_SESSION_STRING": "controlled-session",
            "TELEGRAM_ADMIN_USER_ID": "123456",
        },
        repository_root=Path("/srv/football-bot/current"),
    )

    assert events[:2] == ["authenticate", "resolve_source_chat"]


def test_ingestion_role_transport_failure_uses_role_stop_boundary() -> None:
    from modules.application import RuntimeApplication
    from modules.telethon_ingestion import TelethonTransportError

    class _FailureBoundary:
        def __init__(self) -> None:
            self.reason: IngestionFailureReason | None = None

        def _stop_ingestion_role(self, reason: IngestionFailureReason) -> bool:
            self.reason = reason
            return True

        def _stop_account_stream_for_transport_failure(
            self, *, reason: IngestionFailureReason
        ) -> bool:
            raise AssertionError(f"unexpected account stop: {reason}")

    boundary = _FailureBoundary()
    error = TelethonTransportError(
        "controlled live failure",
        reason=IngestionFailureReason.ACCESS_LOST,
        scope=IngestionFailureScope.INGESTION_ROLE,
    )

    assert RuntimeApplication._stop_telethon_transport_failure(
        cast(RuntimeApplication, boundary), error
    )
    assert boundary.reason is IngestionFailureReason.ACCESS_LOST


def test_run_ingestion_routes_typed_live_failure_to_durable_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.telethon_ingestion import TelethonTransportError

    class _Adapter:
        def run_live_ingestion(self) -> None:
            raise TelethonTransportError(
                "controlled live failure",
                reason=IngestionFailureReason.ACCESS_LOST,
                scope=IngestionFailureScope.INGESTION_ROLE,
            )

    class _ImmediateThread:
        def __init__(self, target: Callable[[], None], *, daemon: bool) -> None:
            assert daemon is True
            self._target = target
            self._alive = True

        def start(self) -> None:
            self._target()
            self._alive = False

        def is_alive(self) -> bool:
            return self._alive

    class _Application:
        def __init__(self) -> None:
            self.stopped: list[Exception] = []
            self.process_calls = 0

        def _stop_telethon_transport_failure(self, error: Exception) -> bool:
            self.stopped.append(error)
            return True

        def process_next(self) -> bool:
            self.process_calls += 1
            return False

    service = runtime_service.RuntimeService(
        role=RuntimeRole.INGESTION,
        application=_Application(),
        store=object(),
        telethon_ingestion=_Adapter(),
        wake_event=Event(),
    )
    monkeypatch.setattr(runtime_service, "Thread", _ImmediateThread)

    with pytest.raises(RuntimeError, match="T2 live transport stopped"):
        runtime_service._run_ingestion(service)

    assert len(service.application.stopped) == 1
    assert isinstance(service.application.stopped[0], TelethonTransportError)
    assert service.application.process_calls == 0


def test_run_ingestion_routes_normal_disconnect_to_durable_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.telethon_ingestion import TelethonTransportError

    class _Adapter:
        def run_live_ingestion(self) -> None:
            return None

    class _ImmediateThread:
        def __init__(self, target: Callable[[], None], *, daemon: bool) -> None:
            assert daemon is True
            self._target = target
            self._alive = True

        def start(self) -> None:
            self._target()
            self._alive = False

        def is_alive(self) -> bool:
            return self._alive

    class _Application:
        def __init__(self) -> None:
            self.stopped: list[Exception] = []

        def _stop_telethon_transport_failure(self, error: Exception) -> bool:
            self.stopped.append(error)
            return True

    application = _Application()
    service = runtime_service.RuntimeService(
        role=RuntimeRole.INGESTION,
        application=application,
        store=object(),
        telethon_ingestion=_Adapter(),
        wake_event=Event(),
    )
    monkeypatch.setattr(runtime_service, "Thread", _ImmediateThread)

    with pytest.raises(RuntimeError, match="T2 live transport stopped"):
        runtime_service._run_ingestion(service)

    assert len(application.stopped) == 1
    error = application.stopped[0]
    assert isinstance(error, TelethonTransportError)
    assert error.reason is IngestionFailureReason.AUTHENTICATION_LOST
    assert error.scope is IngestionFailureScope.INGESTION_ROLE


def test_run_emits_typed_redacted_ingestion_stop_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.telethon_ingestion import TelethonTransportError

    readiness: list[dict[str, object]] = []
    monkeypatch.setattr(
        runtime_service,
        "_emit_readiness",
        lambda _role, **values: readiness.append(values),
    )
    monkeypatch.setattr(runtime_service, "_notify_systemd", lambda _message: None)
    monkeypatch.setattr(
        "modules.t5_runtime_configuration.preflight_role",
        lambda _role, _projection: SimpleNamespace(configuration_ready=True),
    )

    def stop_with_typed_reason(_service: object) -> None:
        raise TelethonTransportError(
            "secret provider detail",
            reason=IngestionFailureReason.CHECKPOINT_UNAVAILABLE,
            scope=IngestionFailureScope.INGESTION_ROLE,
        )

    monkeypatch.setattr(runtime_service, "_run_ingestion", stop_with_typed_reason)
    service = runtime_service.RuntimeService(
        role=RuntimeRole.INGESTION,
        application=object(),
        store=object(),
    )

    assert runtime_service._run(service) == 1
    assert readiness[-1]["reason"] == "checkpoint_unavailable"
    assert "secret provider detail" not in str(readiness)


def test_ingestion_discards_scope_activation_after_registry_change() -> None:
    from modules.application import RuntimeApplication

    processing_started_at = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)

    class _Store:
        def __init__(self) -> None:
            self.consumed: list[object] = []

        def source_chat_ingestion_activation_boundary(
            self,
            *,
            identity: TelegramPeerIdentity,
            registry_generation: int,
        ) -> tuple[datetime, str] | None:
            del identity, registry_generation
            return None

        def consume(self, **kwargs: object) -> None:
            self.consumed.append(kwargs["incoming"])

    class _Adapter:
        def __init__(self) -> None:
            self.admitted = False

        def admit_source_chat(self, **_kwargs: object) -> None:
            self.admitted = True

    store = _Store()
    adapter = _Adapter()
    application = RuntimeApplication(
        role=RuntimeRole.INGESTION,
        store=cast(Any, store),
        clock=cast(Any, SimpleNamespace(now=lambda: processing_started_at)),
        telegram_ingestion=cast(Any, adapter),
    )
    incoming = cast(
        ContractEnvelope,
        SimpleNamespace(
            contract_name=ContractName.SOURCE_CHAT_SCOPE_ACTIVATED,
            payload={
                "telegram_peer_kind": "channel",
                "telegram_chat_id": 42,
                "registry_generation": 3,
                "address_kind": "public_username",
                "current_address": "@stale_source",
                "processing_started_at": processing_started_at.isoformat(),
                "transport_boundary": "channel-pts:10",
                "source_chat_key": "source-chat:channel:42",
            },
        ),
    )

    RuntimeApplication._activate_source_chat_scope(
        application,
        incoming,
    )

    assert adapter.admitted is False
    assert store.consumed == [incoming]


def test_classification_production_composition_uses_primary_codex_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules import postgres_adapter
    from modules.codex_classification_adapter import CodexCliClassifierAdapter

    monkeypatch.setattr(postgres_adapter, "PostgresRoleStore", _ReadyStore)
    monkeypatch.setattr(shutil, "which", lambda _command: "/usr/bin/codex")
    monkeypatch.setattr(
        runtime_service,
        "_codex_cli_version",
        lambda _executable, *, codex_home: "codex-cli 0.144.4",
    )

    service = runtime_service.build_runtime_service(
        "classification",
        {
            "DATABASE_URL_CLASSIFICATION": (
                "postgresql://football_classification:controlled@db/football"
            ),
            "CLASSIFIER_CODEX_HOME": "/var/lib/football-bot/classification/codex",
            "CLASSIFIER_MODEL": "gpt-5.6-sol",
            "CLASSIFIER_REASONING_EFFORT": "high",
        },
        repository_root=Path(__file__).resolve().parents[2],
    )

    assert service.role is RuntimeRole.CLASSIFICATION
    assert isinstance(service.application.model, CodexCliClassifierAdapter)
    assert service.application.telegram_ingestion is None
    assert service.application.telegram_delivery is None


def test_classification_production_composition_rejects_an_unpinned_codex_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules import postgres_adapter

    monkeypatch.setattr(postgres_adapter, "PostgresRoleStore", _ReadyStore)
    monkeypatch.setattr(shutil, "which", lambda _command: "/usr/bin/codex")
    monkeypatch.setattr(
        runtime_service,
        "_codex_cli_version",
        lambda _executable, *, codex_home: "codex-cli 0.143.4",
    )

    with pytest.raises(RuntimeError, match="T4 classifier dependency is unavailable"):
        runtime_service.build_runtime_service(
            "classification",
            {
                "DATABASE_URL_CLASSIFICATION": (
                    "postgresql://football_classification:controlled@db/football"
                ),
                "CLASSIFIER_CODEX_HOME": "/var/lib/football-bot/classification/codex",
                "CLASSIFIER_MODEL": "gpt-5.6-sol",
                "CLASSIFIER_REASONING_EFFORT": "high",
            },
            repository_root=Path(__file__).resolve().parents[2],
        )


def test_classification_runtime_rejects_missing_model_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules import postgres_adapter
    from modules.classifier_configuration import ClassifierConfigurationError

    monkeypatch.setattr(postgres_adapter, "PostgresRoleStore", _ReadyStore)
    monkeypatch.setattr(shutil, "which", lambda _command: "/usr/bin/codex")

    with pytest.raises(ClassifierConfigurationError) as error:
        runtime_service.build_runtime_service(
            "classification",
            {
                "DATABASE_URL_CLASSIFICATION": (
                    "postgresql://football_classification:controlled@db/football"
                ),
                "CLASSIFIER_CODEX_HOME": "/var/lib/football-bot/classification/codex",
            },
            repository_root=Path(__file__).resolve().parents[2],
        )

    assert error.value.key == "CLASSIFIER_MODEL"
    assert error.value.status == "missing"


def test_recommendation_production_composition_uses_its_own_database_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules import postgres_adapter

    monkeypatch.setattr(postgres_adapter, "PostgresRoleStore", _ReadyStore)

    service = runtime_service.build_runtime_service(
        "recommendation",
        {
            "DATABASE_URL_RECOMMENDATION": (
                "postgresql://football_recommendation:controlled@db/football"
            ),
        },
        repository_root=Path("/srv/football-bot/current"),
    )

    assert service.role is RuntimeRole.RECOMMENDATION
    assert service.application.telegram_ingestion is None
    assert service.application.telegram_delivery is None
    assert service.application.model is None
