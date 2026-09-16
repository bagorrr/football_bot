"""Production composition and supervision loops for the five durable owners."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from time import monotonic, sleep
from typing import Any, cast

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@dataclass(frozen=True, slots=True)
class SystemClock:
    """Return the process-independent authoritative UTC clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(slots=True)
class RuntimeService:
    """One production role and its optional Telegram service boundary."""

    role: Any
    application: Any
    store: Any
    bot_api_ingress: Any | None = None
    telethon_ingestion: Any | None = None
    wake_event: Event | None = None
    bot_api_conformance: Any | None = None


_PRIMARY_CLASSIFIER_SCHEMA = "source-message-classification-v5"
_CLASSIFIER_WORKSPACE = Path("/var/lib/football-bot/classification/workspace")
_WATCHDOG_INTERVAL_SECONDS = 15.0


def _required(projection: Mapping[str, str], key: str) -> str:
    value = projection.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("runtime configuration is incomplete")
    return value


def _classifier_artifacts(
    repository_root: Path,
) -> tuple[dict[str, Path], dict[str, Path]]:
    root = repository_root / "classifier"
    schemas: dict[str, Path] = {}
    prompts: dict[str, Path] = {}
    for path in sorted(root.glob("*/source-*.schema.json")):
        key = path.name.removesuffix(".schema.json")
        schemas.setdefault(key, path)
    for path in sorted(root.glob("*/prompt.md")):
        prompts[path.parent.name] = path
    return schemas, prompts


def _codex_cli_version(executable: Path, *, codex_home: Path) -> str:
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/var/empty"),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "PYTHONUTF8": "1",
        "CODEX_HOME": str(codex_home),
    }
    try:
        result = subprocess.run(
            (str(executable), "--version"),
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("T4 classifier dependency is unavailable") from None
    version = result.stdout.strip()
    if result.returncode != 0 or not version or len(version) > 128:
        raise RuntimeError("T4 classifier dependency is unavailable")
    return version


def build_runtime_service(
    role_name: str,
    projection: Mapping[str, str],
    *,
    repository_root: Path,
) -> RuntimeService:
    """Build only the adapters and credentials owned by one runtime role."""
    from modules.contracts import RuntimeRole
    from modules.postgres_adapter import PostgresRoleStore

    try:
        role = RuntimeRole(role_name)
    except ValueError:
        raise ValueError("runtime role is unsupported") from None
    database_url = _required(
        projection,
        {
            RuntimeRole.INGESTION: "DATABASE_URL_INGESTION",
            RuntimeRole.APPLICATION: "DATABASE_URL_APPLICATION",
            RuntimeRole.CLASSIFICATION: "DATABASE_URL_CLASSIFICATION",
            RuntimeRole.RECOMMENDATION: "DATABASE_URL_RECOMMENDATION",
            RuntimeRole.BOT_ASSISTANT: "DATABASE_URL_BOT_ASSISTANT",
        }[role],
    )
    store = PostgresRoleStore(
        role,
        database_url,
    )
    store.check_startup_readiness()
    clock = SystemClock()
    values = dict(projection)

    if role is RuntimeRole.INGESTION:
        from modules.application import RuntimeApplication
        from modules.source_chat_bootstrap import (
            bootstrap_source_chat_catalog,
            load_source_chat_seed_catalog,
        )
        from modules.telethon_ingestion import (
            T2TelethonProjection,
            TelethonIngestionAdapter,
            TelethonRuntime,
        )

        persisted_scope = store.active_source_chat_ingestion_scope()
        bootstrap_required = store.source_chat_ingestion_bootstrap_required()
        approved_source_chats = tuple(
            identity for identity, _generation in persisted_scope
        )
        wake_event = Event()
        telethon_values = {
            key: values[key]
            for key in (
                "TELEGRAM_API_ID",
                "TELEGRAM_API_HASH",
                "TELEGRAM_SESSION_STRING",
                "TELEGRAM_ADMIN_USER_ID",
            )
        }
        telethon_runtime = TelethonRuntime.from_projection(
            T2TelethonProjection.from_mapping(telethon_values)
        )
        source = telethon_runtime.create_production_provider(
            approved_source_chats=approved_source_chats,
            source_scope_generation_lookup=store.source_chat_ingestion_generation,
        )
        telethon_runtime.verify_conformance(
            transport=source,
            approved_source_chats=approved_source_chats,
        )
        source.refresh_source_scope(approved_source_chats)
        if bootstrap_required:
            seed_catalog = load_source_chat_seed_catalog(
                repository_root / "config" / "source-chats.yaml"
            )
            recorded_at = clock.now()
            resolutions = bootstrap_source_chat_catalog(
                seed_catalog,
                ingestion=source,
                publisher=store,
                telegram_user_id=int(telethon_values["TELEGRAM_ADMIN_USER_ID"]),
                recorded_at=recorded_at,
            )
            if not resolutions or len(resolutions) != len(seed_catalog.seeds):
                raise RuntimeError("T2 bootstrap scope is incomplete")
        current_scope = store.active_source_chat_ingestion_scope()
        if current_scope != persisted_scope:
            approved_source_chats = tuple(
                identity for identity, _generation in current_scope
            )
            telethon_runtime.verify_conformance(
                transport=source,
                approved_source_chats=approved_source_chats,
            )
            source.refresh_source_scope(approved_source_chats)
        adapter = TelethonIngestionAdapter(
            runtime=telethon_runtime,
            source=source,
            approved_source_chats=approved_source_chats,
            live_update_callback=lambda _identity: wake_event.set(),
        )
        adapter.start_live_ingestion()
        application = RuntimeApplication(
            role=role,
            store=store,
            clock=clock,
            telegram_ingestion=adapter,
        )
        return RuntimeService(
            role,
            application,
            store,
            telethon_ingestion=adapter,
            wake_event=wake_event,
        )

    if role is RuntimeRole.APPLICATION:
        from modules.application import RuntimeApplication
        from modules.geonames_location_resolver import GeoNamesLocationResolverAdapter

        resolver = GeoNamesLocationResolverAdapter(
            username=_required(values, "GEONAMES_USERNAME"),
            locationiq_access_token=_required(values, "LOCATIONIQ_ACCESS_TOKEN"),
        )
        application = RuntimeApplication(
            role=role,
            store=store,
            clock=clock,
            location_resolver=resolver,
            telegram_admin_user_id=None,
        )
        return RuntimeService(role, application, store)

    if role is RuntimeRole.CLASSIFICATION:
        from modules.application import RuntimeApplication
        from modules.classifier_configuration import (
            T4ClassifierProjection,
        )
        from modules.codex_classification_adapter import (
            CODEX_CLI_VERSION,
            CodexCliClassifierAdapter,
            SubprocessCodexRunner,
        )

        codex_home = Path(_required(values, "CLASSIFIER_CODEX_HOME"))
        executable_text = shutil.which("codex")
        if executable_text is None:
            raise RuntimeError("T4 classifier dependency is unavailable")
        executable = Path(executable_text)
        classifier_configuration = T4ClassifierProjection.from_t4_projection(
            {
                key: values[key]
                for key in ("CLASSIFIER_MODEL", "CLASSIFIER_REASONING_EFFORT")
                if key in values
            }
        )
        schema_paths, prompt_paths = _classifier_artifacts(repository_root)
        codex_version = _codex_cli_version(executable, codex_home=codex_home)
        if codex_version != CODEX_CLI_VERSION:
            raise RuntimeError("T4 classifier dependency is unavailable")
        model = CodexCliClassifierAdapter(
            codex_executable=executable,
            codex_home=codex_home,
            workspace=_CLASSIFIER_WORKSPACE,
            schema_paths=schema_paths,
            prompt_paths=prompt_paths,
            runner=SubprocessCodexRunner(),
            codex_version=codex_version,
            adapter_version="codex-cli-classifier-runtime-v1",
            classifier_configuration=classifier_configuration,
            primary_schema_version=_PRIMARY_CLASSIFIER_SCHEMA,
        )
        application = RuntimeApplication(
            role=role,
            store=store,
            clock=clock,
            model=model,
        )
        return RuntimeService(role, application, store)

    if role is RuntimeRole.RECOMMENDATION:
        from modules.application import RuntimeApplication

        application = RuntimeApplication(role=role, store=store, clock=clock)
        return RuntimeService(role, application, store)

    if role is RuntimeRole.BOT_ASSISTANT:
        from modules.application import RuntimeApplication
        from modules.bot_api import (
            BotApiConformance,
            BotApiConversationHandler,
            BotApiDeliveryAdapter,
            BotApiHttpTransport,
            BotApiIngress,
            BotApiRuntime,
            PostgresBotApiContinuityStore,
            PostgresBotApiDeliveryReconciliation,
            T1BotApiProjection,
        )
        from modules.codex_bot_assistant_adapter import (
            BOT_ASSISTANT_MODEL_KEY,
            BOT_ASSISTANT_REASONING_EFFORT_KEY,
            BOT_ASSISTANT_SDK_SLOTS_KEY,
            BotAssistantSdkSettings,
            CodexSdkBotAssistantAdapter,
        )
        from modules.codex_semantic_adapters import (
            CodexConversationLanguageAdapter,
            CodexDateInterpretationAdapter,
        )
        from modules.geonames_location_resolver import GeoNamesLocationResolverAdapter
        from modules.timezone_data_adapter import InstalledTimezoneDataAdapter

        admin_id = _required(values, "TELEGRAM_ADMIN_USER_ID")
        t1_projection = T1BotApiProjection.from_mapping(
            {
                "TELEGRAM_BOT_TOKEN": _required(values, "TELEGRAM_BOT_TOKEN"),
                "TELEGRAM_ADMIN_USER_ID": admin_id,
            }
        )
        reconciliation = PostgresBotApiDeliveryReconciliation(database_url)
        bot_api = BotApiRuntime.from_projection(
            t1_projection,
            transport_factory=lambda configuration: BotApiHttpTransport(
                configuration,
                reconciliation=reconciliation,
            ),
        )
        delivery = BotApiDeliveryAdapter(cast(Any, bot_api.transport))
        conformance = BotApiConformance(
            configuration=bot_api.configuration,
            transport=cast(Any, bot_api.transport),
            delivery=delivery,
        )
        t3_projection = {
            BOT_ASSISTANT_MODEL_KEY: _required(values, BOT_ASSISTANT_MODEL_KEY),
            BOT_ASSISTANT_REASONING_EFFORT_KEY: _required(
                values, BOT_ASSISTANT_REASONING_EFFORT_KEY
            ),
        }
        if BOT_ASSISTANT_SDK_SLOTS_KEY in values:
            t3_projection[BOT_ASSISTANT_SDK_SLOTS_KEY] = values[
                BOT_ASSISTANT_SDK_SLOTS_KEY
            ]
        settings = BotAssistantSdkSettings.from_t3_projection(t3_projection)
        assistant_model = CodexSdkBotAssistantAdapter(
            settings=settings,
            codex_home=Path(_required(values, "BOT_ASSISTANT_CODEX_HOME")),
        )
        location_resolver = GeoNamesLocationResolverAdapter(
            username=_required(values, "GEONAMES_USERNAME"),
            locationiq_access_token=_required(values, "LOCATIONIQ_ACCESS_TOKEN"),
        )
        conversation_language = CodexConversationLanguageAdapter(
            model=assistant_model,
            clock=clock,
            supported_locales=None,
        )
        application = RuntimeApplication(
            role=role,
            store=store,
            clock=clock,
            telegram_delivery=delivery,
            assistant_model=assistant_model,
            location_resolver=location_resolver,
            conversation_language=conversation_language,
            date_interpretation=CodexDateInterpretationAdapter(
                model=assistant_model,
                clock=clock,
            ),
            timezone_data=InstalledTimezoneDataAdapter(),
            telegram_admin_user_id=int(admin_id),
        )
        handler = BotApiConversationHandler(
            cast(Any, application),
            administrator_user_id=bot_api.configuration.administrator_user_id,
        )
        ingress = BotApiIngress(
            configuration=bot_api.configuration,
            transport=cast(Any, bot_api.transport),
            store=PostgresBotApiContinuityStore(database_url),
            consumer=handler,
            delivery=delivery,
            clock=clock,
        )
        return RuntimeService(
            role,
            application,
            store,
            bot_api_ingress=ingress,
            bot_api_conformance=conformance,
        )

    raise ValueError("runtime role is unsupported")


def _notify_systemd(message: str) -> None:
    notify_socket = os.environ.get("NOTIFY_SOCKET")
    if not notify_socket:
        return
    address = (
        f"\0{notify_socket[1:]}" if notify_socket.startswith("@") else notify_socket
    )
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as connection:
            connection.connect(address)
            connection.sendall(message.encode("utf-8"))
    except OSError:
        return


def _watchdog_tick(last_notification: float, *, now: float | None = None) -> float:
    current_time = monotonic() if now is None else now
    if current_time - last_notification < _WATCHDOG_INTERVAL_SECONDS:
        return last_notification
    _notify_systemd("WATCHDOG=1")
    return current_time


def _emit_readiness(
    role: str,
    *,
    configuration: str,
    dependencies: str,
    runtime: str,
    reason: str | None = None,
) -> None:
    status: dict[str, str] = {
        "event": "runtime_readiness",
        "role": role,
        "configuration": configuration,
        "dependencies": dependencies,
        "runtime": runtime,
    }
    if reason is not None:
        status["reason"] = reason
    print(json.dumps(status, sort_keys=True, separators=(",", ":")), flush=True)


def _run_durable_pump(service: RuntimeService) -> None:
    last_notification = 0.0
    while True:
        worked = service.application.process_next()
        last_notification = _watchdog_tick(last_notification)
        if not worked:
            sleep(0.5)


def _run_bot_assistant(service: RuntimeService) -> None:
    ingress = service.bot_api_ingress
    if ingress is None:
        raise RuntimeError("T1 ingress is unavailable")
    last_notification = 0.0
    while True:
        worked = False
        while service.application.process_next():
            worked = True
            last_notification = _watchdog_tick(last_notification)
        while service.application.present_next():
            worked = True
            last_notification = _watchdog_tick(last_notification)
        if not worked:
            ingress.poll_once()
        last_notification = _watchdog_tick(last_notification)


def _run_ingestion(service: RuntimeService) -> None:
    from modules.domain import (
        IngestionFailureReason,
        IngestionFailureScope,
        TelegramPeerKind,
    )
    from modules.telethon_ingestion import TelethonTransportError

    adapter = service.telethon_ingestion
    wake_event = service.wake_event
    if adapter is None or wake_event is None:
        raise RuntimeError("T2 ingestion boundary is unavailable")

    live_transport_failure: list[TelethonTransportError] = []

    def run_live_transport() -> None:
        try:
            adapter.run_live_ingestion()
        except TelethonTransportError as error:
            live_transport_failure.append(error)
        except Exception:
            live_transport_failure.append(
                TelethonTransportError(
                    "Telegram live ingestion failed",
                    reason=IngestionFailureReason.ACCESS_LOST,
                    scope=IngestionFailureScope.INGESTION_ROLE,
                )
            )
        else:
            live_transport_failure.append(
                TelethonTransportError(
                    "Telegram live ingestion disconnected",
                    reason=IngestionFailureReason.AUTHENTICATION_LOST,
                    scope=IngestionFailureScope.INGESTION_ROLE,
                )
            )
        finally:
            wake_event.set()

    live_thread = Thread(target=run_live_transport, daemon=True)
    live_thread.start()
    last_notification = 0.0
    while True:
        if live_transport_failure or not live_thread.is_alive():
            if live_transport_failure:
                service.application._stop_telethon_transport_failure(
                    live_transport_failure[0]
                )
            raise RuntimeError("T2 live transport stopped")
        worked = service.application.process_next()
        worked = service.application.process_account_telegram_difference() or worked
        last_notification = _watchdog_tick(last_notification)
        for identity, generation in service.store.active_source_chat_ingestion_scope():
            worked = (
                service.application.process_source_chat_history(
                    identity=identity,
                    registry_generation=generation,
                )
                or worked
            )
            last_notification = _watchdog_tick(last_notification)
            if identity.kind is TelegramPeerKind.CHANNEL:
                worked = (
                    service.application.process_channel_telegram_difference(
                        identity=identity,
                        registry_generation=generation,
                    )
                    or worked
                )
                last_notification = _watchdog_tick(last_notification)
        if not worked:
            wake_event.wait(5)
            wake_event.clear()
        last_notification = _watchdog_tick(last_notification)


def _run(service: RuntimeService) -> int:
    try:
        from modules.t5_runtime_configuration import (
            ROLE_CONFIGURATION_KEYS,
            preflight_role,
        )

        projection = {
            key: value
            for key, value in os.environ.items()
            if key in ROLE_CONFIGURATION_KEYS[service.role.value]
        }
        report = preflight_role(service.role.value, projection)
        if not report.configuration_ready:
            _emit_readiness(
                service.role.value,
                configuration="failed",
                dependencies="not_checked",
                runtime="not_started",
                reason="role_preflight_failed",
            )
            return 78
        if service.bot_api_ingress is not None:
            service.bot_api_ingress.verify_readiness()
            if service.bot_api_conformance is None:
                raise RuntimeError("T1 conformance boundary is unavailable")
            service.bot_api_conformance.run()
        _emit_readiness(
            service.role.value,
            configuration="ready",
            dependencies="ready",
            runtime="ready",
        )
        _notify_systemd("READY=1\nSTATUS=Runtime ready")
    except ImportError:
        _emit_readiness(
            service.role.value,
            configuration="ready",
            dependencies="failed",
            runtime="not_started",
            reason="dependency_unavailable",
        )
        _notify_systemd("STATUS=Runtime dependency unavailable")
        return 78
    except Exception:
        _emit_readiness(
            service.role.value,
            configuration="ready",
            dependencies="ready",
            runtime="failed",
            reason="startup_or_conformance_failed",
        )
        _notify_systemd("STATUS=Runtime startup failed")
        return 78

    try:
        if service.role.value == "ingestion":
            _run_ingestion(service)
        elif service.bot_api_ingress is not None:
            _run_bot_assistant(service)
        else:
            _run_durable_pump(service)
    except Exception:
        _emit_readiness(
            service.role.value,
            configuration="ready",
            dependencies="ready",
            runtime="failed",
            reason="runtime_stopped",
        )
        _notify_systemd("STATUS=Runtime stopped")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    from modules.postgres_adapter import PostgresRoleReadinessError
    from modules.source_chat_bootstrap import SourceChatBootstrapError
    from modules.t5_runtime_configuration import (
        ROLE_CONFIGURATION_KEYS,
        ROLE_DATABASE_KEYS,
        preflight_role,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--role",
        choices=sorted(ROLE_DATABASE_KEYS),
        required=True,
    )
    arguments = parser.parse_args(argv)
    role = arguments.role
    projection = {
        key: value
        for key, value in os.environ.items()
        if key in ROLE_CONFIGURATION_KEYS[role]
    }
    report = preflight_role(role, projection)
    if not report.configuration_ready:
        _emit_readiness(
            role,
            configuration="failed",
            dependencies="not_checked",
            runtime="not_started",
            reason="role_preflight_failed",
        )
        return 78
    try:
        service = build_runtime_service(
            role,
            projection,
            repository_root=Path(__file__).resolve().parents[1],
        )
    except ImportError:
        _emit_readiness(
            role,
            configuration="ready",
            dependencies="failed",
            runtime="not_started",
            reason="dependency_unavailable",
        )
        return 78
    except PostgresRoleReadinessError as error:
        _emit_readiness(
            role,
            configuration="ready",
            dependencies=(
                "failed" if error.status == "database_unavailable" else "not_ready"
            ),
            runtime="not_started",
            reason=error.status,
        )
        _notify_systemd("STATUS=Runtime database readiness failed")
        return 78
    except SourceChatBootstrapError as error:
        _emit_readiness(
            role,
            configuration=("failed" if error.phase == "configuration" else "ready"),
            dependencies=("not_checked" if error.phase == "configuration" else "ready"),
            runtime="not_started",
            reason="source_chat_bootstrap_failed",
        )
        _notify_systemd("STATUS=Source Chat seed bootstrap failed")
        return 78
    except Exception:
        _emit_readiness(
            role,
            configuration="ready",
            dependencies="ready",
            runtime="failed",
            reason="runtime_composition_failed",
        )
        return 78
    return _run(service)


if __name__ == "__main__":
    raise SystemExit(main())
