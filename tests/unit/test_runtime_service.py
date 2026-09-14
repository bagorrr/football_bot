from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from apps import runtime_service
from modules.contracts import RuntimeRole
from modules.domain import TelegramPeerIdentity
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
        },
        repository_root=Path("/srv/football-bot/current"),
    )

    assert service.store.require_classifier_promotion is True


def test_application_production_composition_uses_geonames_without_telegram(
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
            "TELEGRAM_BOT_TOKEN": "123456:controlled-token",
            "TELEGRAM_ADMIN_USER_ID": "123456",
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


def test_ingestion_production_composition_uses_generation_scoped_telethon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules import postgres_adapter
    from modules.telethon_ingestion import TelethonIngestionAdapter, TelethonRuntime

    captured: list[dict[str, object]] = []
    adapter = object()

    def create_adapter(**kwargs: object) -> object:
        captured.append(kwargs)
        return adapter

    monkeypatch.setattr(postgres_adapter, "PostgresRoleStore", _ReadyStore)
    monkeypatch.setattr(
        TelethonRuntime,
        "from_projection",
        staticmethod(lambda _projection: object()),
    )
    monkeypatch.setattr(
        TelethonIngestionAdapter,
        "from_runtime",
        staticmethod(create_adapter),
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
    assert service.telethon_ingestion is adapter
    assert service.application.telegram_ingestion is adapter
    assert captured[0]["approved_source_chats"] == ()
    assert captured[0]["source_scope_generation_lookup"] == (
        service.store.source_chat_ingestion_generation
    )


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
        lambda _executable, *, codex_home: "codex 1.0",
    )

    service = runtime_service.build_runtime_service(
        "classification",
        {
            "DATABASE_URL_CLASSIFICATION": (
                "postgresql://football_classification:controlled@db/football"
            ),
            "CLASSIFIER_CODEX_HOME": "/var/lib/football-bot/classification/codex",
        },
        repository_root=Path(__file__).resolve().parents[2],
    )

    assert service.role is RuntimeRole.CLASSIFICATION
    assert isinstance(service.application.model, CodexCliClassifierAdapter)
    assert service.application.telegram_ingestion is None
    assert service.application.telegram_delivery is None


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
