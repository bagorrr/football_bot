"""Composition root for the five-role system acceptance seam."""

from __future__ import annotations

import secrets

from modules.contracts import RuntimeRole
from modules.ports import (
    Clock,
    LocationResolverAdapter,
    ModelAdapter,
    TelegramDeliveryAdapter,
    TelegramIngestionAdapter,
)
from modules.postgres_adapter import (
    PostgresAcceptanceMigrator,
    PostgresAcceptanceObserver,
    PostgresRoleStore,
    runtime_database_url,
)
from modules.testkit import (
    AcceptanceRole,
    AcceptanceSpine,
    ControlledLocationResolverAdapter,
    ControlledModelAdapter,
    ControlledTelegramDeliveryAdapter,
    ControlledTelegramIngestionAdapter,
)


def boot_acceptance_spine(
    *,
    admin_database_url: str,
    clock: Clock,
    telegram_ingestion: TelegramIngestionAdapter | None = None,
    telegram_delivery: TelegramDeliveryAdapter | None = None,
    model: ModelAdapter | None = None,
    location_resolver: LocationResolverAdapter | None = None,
) -> AcceptanceSpine:
    """Provision and boot five separately credentialed runtime roles."""
    migrator = PostgresAcceptanceMigrator(admin_database_url)
    migrator.migrate()
    passwords = {role: secrets.token_urlsafe(24) for role in RuntimeRole}
    migrator.provision_runtime_credentials(passwords)
    role_urls = {
        role: runtime_database_url(admin_database_url, role, passwords[role])
        for role in RuntimeRole
    }

    def role_store(role: RuntimeRole) -> PostgresRoleStore:
        return PostgresRoleStore(role, role_urls[role])

    roles = {
        role: AcceptanceRole(role=role, store=role_store(role)) for role in RuntimeRole
    }
    return AcceptanceSpine(
        roles=roles,
        observer=PostgresAcceptanceObserver(admin_database_url),
        clock=clock,
        telegram_ingestion=telegram_ingestion or ControlledTelegramIngestionAdapter(),
        telegram_delivery=telegram_delivery or ControlledTelegramDeliveryAdapter(),
        model=model or ControlledModelAdapter(),
        location_resolver=location_resolver or ControlledLocationResolverAdapter(),
        restart_store=role_store,
    )
