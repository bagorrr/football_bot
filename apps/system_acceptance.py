"""Composition root for one system-acceptance runtime role."""

from __future__ import annotations

from modules.application import RuntimeApplication
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


def boot_acceptance_role(
    *,
    role: RuntimeRole,
    database_url: str,
    promotion_gate_database_url: str | None = None,
    require_classifier_promotion: bool = True,
    clock: Clock,
    telegram_ingestion: TelegramIngestionAdapter | None = None,
    telegram_delivery: TelegramDeliveryAdapter | None = None,
    model: ModelAdapter | None = None,
    location_resolver: LocationResolverAdapter | None = None,
    conversation_language: ConversationLanguageAdapter | None = None,
    date_interpretation: DateInterpretationAdapter | None = None,
    timezone_data: TimezoneDataAdapter | None = None,
    telegram_admin_user_id: int | None = None,
) -> RuntimeApplication:
    """Boot exactly one role with its own least-privilege database credential."""
    return RuntimeApplication(
        role=role,
        store=PostgresRoleStore(
            role,
            database_url,
            promotion_gate_database_url=promotion_gate_database_url,
            require_classifier_promotion=require_classifier_promotion,
        ),
        clock=clock,
        telegram_ingestion=telegram_ingestion,
        telegram_delivery=telegram_delivery,
        model=model,
        location_resolver=location_resolver,
        conversation_language=conversation_language,
        date_interpretation=date_interpretation,
        timezone_data=timezone_data,
        telegram_admin_user_id=telegram_admin_user_id,
    )
