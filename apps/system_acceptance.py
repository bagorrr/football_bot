"""Composition root for one system-acceptance runtime role."""

from __future__ import annotations

from modules.contracts import RuntimeRole
from modules.ports import (
    Clock,
    ConversationLanguageAdapter,
    DateInterpretationAdapter,
    LocationResolverAdapter,
    ModelAdapter,
    TelegramDeliveryAdapter,
    TelegramIngestionAdapter,
    TimezoneDataAdapter,
)
from modules.postgres_adapter import (
    PostgresRoleStore,
)
from modules.testkit import (
    AcceptanceRole,
)


def boot_acceptance_role(
    *,
    role: RuntimeRole,
    database_url: str,
    clock: Clock,
    telegram_ingestion: TelegramIngestionAdapter | None = None,
    telegram_delivery: TelegramDeliveryAdapter | None = None,
    model: ModelAdapter | None = None,
    location_resolver: LocationResolverAdapter | None = None,
    conversation_language: ConversationLanguageAdapter | None = None,
    date_interpretation: DateInterpretationAdapter | None = None,
    timezone_data: TimezoneDataAdapter | None = None,
) -> AcceptanceRole:
    """Boot exactly one role with its own least-privilege database credential."""
    return AcceptanceRole(
        role=role,
        store=PostgresRoleStore(role, database_url),
        clock=clock,
        telegram_ingestion=telegram_ingestion,
        telegram_delivery=telegram_delivery,
        model=model,
        location_resolver=location_resolver,
        conversation_language=conversation_language,
        date_interpretation=date_interpretation,
        timezone_data=timezone_data,
    )
