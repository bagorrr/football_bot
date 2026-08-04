"""Stable testkit surface for the approved primary system seam."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from modules.application import ConversationOnboarding
from modules.contracts import (
    SUPPORTED_CONTRACTS,
    ContractDefinition,
    ContractEnvelope,
    ContractName,
    JsonValue,
    RawContractEnvelope,
    RuntimeRole,
)
from modules.contracts import (
    OperatorAlert as OperatorAlert,
)
from modules.domain import (
    ActiveChatView,
    ConversationState,
    LanguageSelection,
    TelegramMessage,
)
from modules.ports import (
    AcceptanceObserver,
    AcceptanceRoleStore,
    Clock,
    ConversationAccessDeniedError,
    ConversationLanguageAdapter,
    LocationResolverAdapter,
    ModelAdapter,
    OutboxConflictError,
    TelegramDeliveryAdapter,
    TelegramIngestionAdapter,
)

_CONTRACTS = {
    (definition.name, definition.version): definition
    for definition in SUPPORTED_CONTRACTS
}


@dataclass(frozen=True, slots=True)
class FrozenClock:
    """Controllable clock for deterministic system acceptance."""

    instant: datetime

    def now(self) -> datetime:
        """Return the configured acceptance instant."""
        return self.instant


@dataclass(slots=True)
class ControlledTelegramIngestionAdapter:
    """Synthetic Source Chat input with no live MTProto access."""

    def source_event_id(self, probe_id: str) -> str:
        """Return a stable synthetic Source Event identity."""
        return f"source-event:{probe_id}"


@dataclass(slots=True)
class ControlledTelegramDeliveryAdapter:
    """Synthetic Bot API output with no live Bot credential."""

    presentations: list[str] = field(default_factory=list)
    messages: list[TelegramMessage] = field(default_factory=list)
    failures_remaining: int = 0

    def fail_next(self) -> None:
        """Inject one controlled Bot API delivery failure."""
        self.failures_remaining += 1

    def present(self, delivery_id: str) -> None:
        """Record one idempotent controlled presentation."""
        if delivery_id not in self.presentations:
            self.presentations.append(delivery_id)

    def send(self, message: TelegramMessage) -> str:
        """Record one deterministic Bot Assistant message without Telegram."""
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise InjectedTelegramDeliveryError
        self.messages.append(message)
        return f"telegram-message:{len(self.messages)}"


class ControlledModelAdapter:
    """Deterministic model adapter with no provider access."""

    def proposal_id(self, revision_id: str) -> str:
        """Return a stable non-authoritative proposal identity."""
        return f"proposal:{revision_id}"


class ControlledLocationResolverAdapter:
    """Deterministic resolver adapter with no provider access."""

    def opportunity_revision_id(self, proposal_id: str) -> str:
        """Return a stable accepted Opportunity revision identity."""
        return f"opportunity-revision:{proposal_id}"


class ControlledConversationLanguageAdapter:
    """Deterministic free-text interpretation with no live model call."""

    def interpret(self, text: str) -> LanguageSelection | None:
        """Recognize one acceptance fixture and reject every ambiguous input."""
        if text.strip().casefold() != "deutsch":
            return None
        return self.render("de")

    def render(self, locale: str) -> LanguageSelection | None:
        """Render the one validated non-static acceptance locale."""
        if locale != "de":
            return None
        return LanguageSelection(
            locale="de",
            confirmation="✅ Wir sprechen ab jetzt Deutsch.",
            direction_question="Was möchten Sie tun?",
            direction_labels=(
                "Ein Spiel für mich finden",
                "Spieler für ein Spiel finden",
                "Turnier oder gegnerisches Team",
                "Trainer",
                "Schiedsrichter",
                "⬅️ Zurück",
                "Transfers",
            ),
        )


@dataclass(frozen=True, slots=True)
class AcceptanceSnapshot:
    """Durable outcomes exposed by the acceptance testkit."""

    owner_state_roles: frozenset[RuntimeRole]
    owner_state_records: int
    outbox_records: int
    accepted_inbox_records: int
    rejected_inbox_records: int
    operator_alerts: tuple[OperatorAlert, ...]
    completed: bool


class OwnershipViolationError(RuntimeError):
    """A cross-owner database write was rejected and reported."""

    def __init__(self, message_id: UUID) -> None:
        self.message_id = message_id
        super().__init__("runtime role cannot write another owner's state")


class InjectedFailureError(RuntimeError):
    """A controlled invalid outbox identity rolled back its transaction."""


class InjectedInterruptionError(RuntimeError):
    """A controlled process exit interrupted work after a durable commit."""


class InjectedTelegramDeliveryError(RuntimeError):
    """A controlled Bot API failure left durable presentation work pending."""


@dataclass(slots=True)
class AcceptanceRole:
    """One independently reconnectable runtime responsibility."""

    role: RuntimeRole
    store: AcceptanceRoleStore
    clock: Clock
    telegram_ingestion: TelegramIngestionAdapter | None = None
    telegram_delivery: TelegramDeliveryAdapter | None = None
    model: ModelAdapter | None = None
    location_resolver: LocationResolverAdapter | None = None
    conversation_language: ConversationLanguageAdapter | None = None
    supported_versions: dict[ContractName, set[int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.supported_versions:
            return
        for definition in SUPPORTED_CONTRACTS:
            if definition.consumer is self.role and definition.version == 1:
                self.supported_versions.setdefault(definition.name, set()).add(1)

    def supports(self, contract_name: ContractName, version: int) -> None:
        """Add one explicit consumer contract version."""
        self.supported_versions.setdefault(contract_name, {1}).add(version)

    def versions_for(self, contract_name: ContractName) -> set[int]:
        """Return explicit versions supported by this consumer."""
        return set(self.supported_versions.get(contract_name, set()))

    def record_source_event(
        self,
        probe_id: str,
        *,
        contract_version: int,
        payload: JsonValue | None = None,
    ) -> None:
        """Commit one synthetic Source Event through the ingestion role."""
        if self.role is not RuntimeRole.INGESTION or self.telegram_ingestion is None:
            msg = "only the ingestion runtime can record a Source Event"
            raise RuntimeError(msg)
        correlation_id = _identifier(probe_id, "correlation")
        source_event_id = self.telegram_ingestion.source_event_id(probe_id)
        definition = _CONTRACTS.get(
            (ContractName.SOURCE_EVENT_RECORDED, contract_version)
        )
        if definition is not None and payload is None:
            envelope: RawContractEnvelope = _envelope(
                definition=definition,
                probe_id=probe_id,
                version=contract_version,
                fact=source_event_id,
                causation_id=correlation_id,
                correlation_id=correlation_id,
                recorded_at=self.clock.now(),
            )
        else:
            envelope = RawContractEnvelope(
                contract_name=ContractName.SOURCE_EVENT_RECORDED,
                contract_version=contract_version,
                message_id=_identifier(
                    probe_id,
                    ContractName.SOURCE_EVENT_RECORDED.value,
                ),
                producer=RuntimeRole.INGESTION,
                consumer=RuntimeRole.APPLICATION,
                subject_id=probe_id,
                subject_revision=1,
                idempotency_key=(
                    f"{probe_id}:{ContractName.SOURCE_EVENT_RECORDED.value}"
                ),
                causation_id=correlation_id,
                correlation_id=correlation_id,
                recorded_at=self.clock.now(),
                payload=payload
                if payload is not None
                else {"probe_id": probe_id, "source_event_id": source_event_id},
            )
        self.store.commit_initial(probe_id=probe_id, envelope=envelope)

    def process_next(self, *, inject_outbox_conflict: bool = False) -> bool:
        """Discover and process one durable handoff addressed to this role."""
        incoming = self.store.claim_next(
            supported_versions=self.supported_versions,
            claimed_at=self.clock.now(),
        )
        if incoming is None:
            return False
        outgoing = None
        if incoming.contract_version in self.versions_for(incoming.contract_name):
            supported_incoming = ContractEnvelope.from_raw(incoming)
            definition, fact = self._next_handoff(supported_incoming)
            outgoing = _envelope(
                definition=definition,
                probe_id=incoming.subject_id,
                version=definition.version,
                fact=fact,
                causation_id=incoming.message_id,
                correlation_id=incoming.correlation_id,
                recorded_at=self.clock.now(),
            )
            if inject_outbox_conflict:
                outgoing = _with_message_id(outgoing, incoming.message_id)
        try:
            self.store.consume(
                incoming=incoming,
                supported_versions=self.versions_for(incoming.contract_name),
                received_at=self.clock.now(),
                outgoing=outgoing,
            )
        except OutboxConflictError as error:
            raise InjectedFailureError from error
        return True

    def present_next(self) -> bool:
        """Retry one committed presentation through the idempotent Bot API port."""
        if self.role is not RuntimeRole.BOT_ASSISTANT:
            return False
        if self.telegram_delivery is None:
            raise RuntimeError("Bot Assistant runtime has no delivery adapter")
        envelope = self.store.claim_presentation(claimed_at=self.clock.now())
        if envelope is None:
            return False
        delivery_id = _payload_text(envelope, "delivery_id")
        self.store.record_presentation_attempt(
            envelope=envelope,
            delivery_id=delivery_id,
            attempted_at=self.clock.now(),
        )
        self.telegram_delivery.present(delivery_id)
        self.store.record_presentation_success(
            message_id=envelope.message_id,
            presented_at=self.clock.now(),
        )
        return True

    def attempt_owner_write(self, *, owner: RuntimeRole, probe_id: str) -> bool:
        """Attempt one cross-owner write through this role's credential."""
        message_id = _identifier(probe_id, f"{self.role.value}:{owner.value}:denied")
        attempt = ContractEnvelope(
            contract_name=ContractName.OWNER_STATE_WRITE,
            contract_version=1,
            message_id=message_id,
            producer=self.role,
            consumer=owner,
            subject_id=probe_id,
            subject_revision=1,
            idempotency_key=f"{probe_id}:{self.role.value}:{owner.value}:denied",
            causation_id=message_id,
            correlation_id=message_id,
            recorded_at=self.clock.now(),
            payload={},
        )
        return self.store.attempt_owner_write(
            owner=owner,
            probe_id=probe_id,
            attempt=attempt,
        )

    def _next_handoff(
        self,
        incoming: ContractEnvelope,
    ) -> tuple[ContractDefinition, str]:
        if incoming.contract_name is ContractName.SOURCE_EVENT_RECORDED:
            source_event_id = _payload_text(incoming, "source_event_id")
            return (
                _CONTRACTS[(ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION, 1)],
                f"source-message-revision:{source_event_id}",
            )
        if incoming.contract_name is ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION:
            if self.model is None:
                raise RuntimeError("classification runtime has no model adapter")
            revision_id = _payload_text(incoming, "source_message_revision_id")
            return (
                _CONTRACTS[(ContractName.CLASSIFICATION_PROPOSAL, 1)],
                self.model.proposal_id(revision_id),
            )
        if incoming.contract_name is ContractName.CLASSIFICATION_PROPOSAL:
            if self.location_resolver is None:
                raise RuntimeError("application runtime has no resolver adapter")
            proposal_id = _payload_text(incoming, "proposal_id")
            return (
                _CONTRACTS[(ContractName.OPPORTUNITY_PUBLICATION_CHANGED, 1)],
                self.location_resolver.opportunity_revision_id(proposal_id),
            )
        if incoming.contract_name is ContractName.OPPORTUNITY_PUBLICATION_CHANGED:
            return (
                _CONTRACTS[(ContractName.SEARCH_COMPLETED, 1)],
                f"completed-search:{incoming.subject_id}",
            )
        if incoming.contract_name is ContractName.SEARCH_COMPLETED:
            return (
                _CONTRACTS[(ContractName.TELEGRAM_PRESENTATION_REQUESTED, 1)],
                f"delivery:{incoming.subject_id}",
            )
        msg = f"{self.role.value} has no handoff for {incoming.contract_name.value}"
        raise RuntimeError(msg)


class AcceptanceSpine:
    """Drive independently restartable roles through public ports."""

    def __init__(
        self,
        *,
        roles: Mapping[RuntimeRole, AcceptanceRole],
        observer: AcceptanceObserver,
        restart_role: Callable[[RuntimeRole], AcceptanceRole],
    ) -> None:
        self._roles = dict(roles)
        self._observer = observer
        self._restart_role = restart_role

    def restart(self, role: RuntimeRole) -> AcceptanceSpine:
        """Reconnect exactly one runtime role without replacing the others."""
        previous = self._roles[role]
        restarted = self._restart_role(role)
        restarted.supported_versions = {
            name: set(versions)
            for name, versions in previous.supported_versions.items()
        }
        self._roles[role] = restarted
        return self

    def support_version(
        self,
        *,
        consumer: RuntimeRole,
        contract_name: ContractName,
        version: int,
    ) -> None:
        """Enable a newly deployed consumer contract version."""
        definition = _CONTRACTS.get((contract_name, version))
        if definition is None:
            msg = "cannot support a contract version without a registered schema"
            raise ValueError(msg)
        if definition.consumer is not consumer:
            msg = "consumer does not own this contract version"
            raise ValueError(msg)
        self._roles[consumer].supports(contract_name, version)

    def reset(self) -> None:
        """Reset only synthetic spine observations."""
        self._observer.reset()

    def run(
        self,
        probe_id: str,
        *,
        source_contract_version: int = 1,
        source_payload: JsonValue | None = None,
        fail_after_state: RuntimeRole | None = None,
        interrupt_after_presentation_commit: bool = False,
    ) -> AcceptanceSnapshot:
        """Drive one versioned contract round trip through all five roles."""
        self.record_source_event(
            probe_id,
            source_contract_version=source_contract_version,
            source_payload=source_payload,
        )
        return self.run_until_idle(
            probe_id,
            fail_after_state=fail_after_state,
            interrupt_after_presentation_commit=(interrupt_after_presentation_commit),
        )

    def record_source_event(
        self,
        probe_id: str,
        *,
        source_contract_version: int = 1,
        source_payload: JsonValue | None = None,
    ) -> None:
        """Commit ingestion work without consuming its durable handoff."""
        self._roles[RuntimeRole.INGESTION].record_source_event(
            probe_id,
            contract_version=source_contract_version,
            payload=source_payload,
        )

    def run_until_idle(
        self,
        probe_id: str,
        *,
        fail_after_state: RuntimeRole | None = None,
        interrupt_after_presentation_commit: bool = False,
    ) -> AcceptanceSnapshot:
        """Let each role discover durable work until no handoff remains."""
        injected = False
        while True:
            progressed = False
            bot_handoff_committed = False
            for role in RuntimeRole:
                should_inject = role is fail_after_state and not injected
                processed = self._roles[role].process_next(
                    inject_outbox_conflict=should_inject,
                )
                progressed = processed or progressed
                bot_handoff_committed = (
                    role is RuntimeRole.BOT_ASSISTANT and processed
                ) or bot_handoff_committed
                injected = (should_inject and processed) or injected
            if interrupt_after_presentation_commit and bot_handoff_committed:
                raise InjectedInterruptionError
            presented = self._roles[RuntimeRole.BOT_ASSISTANT].present_next()
            progressed = presented or progressed
            if not progressed:
                return self.observe(probe_id)

    def observe(self, probe_id: str) -> AcceptanceSnapshot:
        """Observe business-neutral durable outcomes through the testkit."""
        values = self._observer.snapshot(probe_id)
        return AcceptanceSnapshot(
            owner_state_roles=values.roles,
            owner_state_records=values.owner_state_records,
            outbox_records=values.outbox_records,
            accepted_inbox_records=values.accepted_inbox_records,
            rejected_inbox_records=values.rejected_inbox_records,
            operator_alerts=values.operator_alerts,
            completed=values.completed,
        )

    def recoverable_contract(
        self,
        probe_id: str,
        *,
        contract_name: ContractName = ContractName.SOURCE_EVENT_RECORDED,
    ) -> RawContractEnvelope:
        """Recover a rejected or pending envelope without acknowledging it."""
        return self._observer.envelope(_identifier(probe_id, contract_name.value))

    def attempt_owner_write(
        self,
        *,
        actor: RuntimeRole,
        owner: RuntimeRole,
        probe_id: str,
    ) -> None:
        """Verify that a process credential cannot mutate another owner."""
        message_id = _identifier(probe_id, f"{actor.value}:{owner.value}:denied")
        allowed = self._roles[actor].attempt_owner_write(
            owner=owner,
            probe_id=probe_id,
        )
        if allowed:
            msg = "PostgreSQL accepted a cross-owner state write"
            raise AssertionError(msg)
        raise OwnershipViolationError(message_id)

    def operator_alert(self, message_id: UUID) -> OperatorAlert:
        """Observe one durable body-free operator alert."""
        return self._observer.operator_alert(message_id)

    def _conversation_onboarding(self) -> ConversationOnboarding:
        role = self._roles[RuntimeRole.BOT_ASSISTANT]
        if role.telegram_delivery is None:
            raise RuntimeError("Bot Assistant runtime has no delivery adapter")
        return ConversationOnboarding(
            store=role.store,
            telegram_delivery=role.telegram_delivery,
            conversation_language=_conversation_language(role),
            clock=role.clock,
        )

    def start_bot_user(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        telegram_language_hint: str | None,
    ) -> None:
        """Drive one synthetic private-chat /start through the Bot Assistant."""
        self._conversation_onboarding().start(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            telegram_language_hint=telegram_language_hint,
        )

    def select_fixed_language(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        locale: str,
        screen_revision: int | None = None,
    ) -> None:
        """Drive one fixed-language callback through the Bot Assistant."""
        self._conversation_onboarding().select_fixed_language(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            locale=locale,
            screen_revision=(
                screen_revision
                if screen_revision is not None
                else self.conversation_state(telegram_user_id).screen_revision
            ),
        )

    def open_language_input(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        screen_revision: int | None = None,
    ) -> None:
        """Drive the free-text language prompt through the Bot Assistant."""
        self._conversation_onboarding().open_language_input(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            screen_revision=(
                screen_revision
                if screen_revision is not None
                else self.conversation_state(telegram_user_id).screen_revision
            ),
        )

    def submit_language_text(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        text: str,
        screen_revision: int | None = None,
    ) -> None:
        """Drive one free-text language answer through the Bot Assistant."""
        self._conversation_onboarding().submit_language_text(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            text=text,
            screen_revision=(
                screen_revision
                if screen_revision is not None
                else self.conversation_state(telegram_user_id).screen_revision
            ),
        )

    def retry_bot_presentations(self) -> bool:
        """Retry one durable onboarding presentation after interruption."""
        return self._conversation_onboarding().deliver_pending()

    def conversation_state(self, telegram_user_id: int) -> ConversationState:
        """Observe durable account state through the Bot Assistant query port."""
        state = self._roles[RuntimeRole.BOT_ASSISTANT].store.conversation_state(
            telegram_user_id
        )
        if state is None:
            raise LookupError(telegram_user_id)
        return state

    def active_conversation_view(self, telegram_user_id: int) -> ActiveChatView:
        """Observe the latest successfully presented Bot User screen."""
        view = self._roles[RuntimeRole.BOT_ASSISTANT].store.active_conversation_view(
            telegram_user_id
        )
        if view is None:
            raise LookupError(telegram_user_id)
        return view

    def read_conversation_state_as(
        self,
        *,
        actor: RuntimeRole,
        telegram_user_id: int,
    ) -> ConversationState:
        """Exercise least-privilege read isolation through a runtime credential."""
        try:
            state = self._roles[actor].store.conversation_state(telegram_user_id)
        except ConversationAccessDeniedError as error:
            raise OwnershipViolationError(UUID(int=0)) from error
        if actor is not RuntimeRole.BOT_ASSISTANT and state is None:
            raise OwnershipViolationError(UUID(int=0))
        if state is None:
            raise LookupError(telegram_user_id)
        return state


def boot_acceptance_spine(
    *,
    admin_database_url: str,
    clock: Clock,
    telegram_ingestion: TelegramIngestionAdapter | None = None,
    telegram_delivery: TelegramDeliveryAdapter | None = None,
    model: ModelAdapter | None = None,
    location_resolver: LocationResolverAdapter | None = None,
    conversation_language: ConversationLanguageAdapter | None = None,
) -> AcceptanceSpine:
    """Provision the administrative test seam and boot each role separately."""
    from apps.system_acceptance import boot_acceptance_role
    from modules.postgres_adapter import (
        PostgresAcceptanceMigrator,
        PostgresAcceptanceObserver,
        runtime_database_url,
    )

    migrator = PostgresAcceptanceMigrator(admin_database_url)
    migrator.migrate()
    passwords = {role: secrets.token_urlsafe(24) for role in RuntimeRole}
    migrator.provision_runtime_credentials(passwords)
    role_urls = {
        role: runtime_database_url(admin_database_url, role, passwords[role])
        for role in RuntimeRole
    }
    controlled_ingestion = telegram_ingestion or ControlledTelegramIngestionAdapter()
    controlled_delivery = telegram_delivery or ControlledTelegramDeliveryAdapter()
    controlled_model = model or ControlledModelAdapter()
    controlled_resolver = location_resolver or ControlledLocationResolverAdapter()
    controlled_conversation_language = (
        conversation_language or ControlledConversationLanguageAdapter()
    )

    def restart_role(role: RuntimeRole) -> AcceptanceRole:
        return boot_acceptance_role(
            role=role,
            database_url=role_urls[role],
            clock=clock,
            telegram_ingestion=(
                controlled_ingestion if role is RuntimeRole.INGESTION else None
            ),
            telegram_delivery=(
                controlled_delivery if role is RuntimeRole.BOT_ASSISTANT else None
            ),
            model=controlled_model if role is RuntimeRole.CLASSIFICATION else None,
            location_resolver=(
                controlled_resolver if role is RuntimeRole.APPLICATION else None
            ),
            conversation_language=(
                controlled_conversation_language
                if role is RuntimeRole.BOT_ASSISTANT
                else None
            ),
        )

    return AcceptanceSpine(
        roles={role: restart_role(role) for role in RuntimeRole},
        observer=PostgresAcceptanceObserver(admin_database_url),
        restart_role=restart_role,
    )


def _identifier(probe_id: str, purpose: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"football-bot:{probe_id}:{purpose}")


def _conversation_language(role: AcceptanceRole) -> ConversationLanguageAdapter:
    if role.conversation_language is None:
        raise RuntimeError("Bot Assistant runtime has no language adapter")
    return role.conversation_language


def _envelope(
    *,
    definition: ContractDefinition,
    probe_id: str,
    version: int,
    fact: str,
    causation_id: UUID,
    correlation_id: UUID,
    recorded_at: datetime,
) -> ContractEnvelope:
    return ContractEnvelope(
        contract_name=definition.name,
        contract_version=version,
        message_id=_identifier(probe_id, definition.name.value),
        producer=definition.producer,
        consumer=definition.consumer,
        subject_id=probe_id,
        subject_revision=1,
        idempotency_key=f"{probe_id}:{definition.name.value}",
        causation_id=causation_id,
        correlation_id=correlation_id,
        recorded_at=recorded_at,
        payload={
            "probe_id": probe_id,
            definition.required_fact: fact,
            **{name: 1 for name in definition.required_integer_facts},
        },
    )


def _payload_text(envelope: RawContractEnvelope, name: str) -> str:
    if not isinstance(envelope.payload, dict):
        raise TypeError("supported contract payload must be a JSON object")
    value = envelope.payload.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"supported contract requires {name}")
    return value


def _with_message_id(envelope: ContractEnvelope, message_id: UUID) -> ContractEnvelope:
    return ContractEnvelope(
        contract_name=envelope.contract_name,
        contract_version=envelope.contract_version,
        message_id=message_id,
        producer=envelope.producer,
        consumer=envelope.consumer,
        subject_id=envelope.subject_id,
        subject_revision=envelope.subject_revision,
        idempotency_key=envelope.idempotency_key,
        causation_id=envelope.causation_id,
        correlation_id=envelope.correlation_id,
        recorded_at=envelope.recorded_at,
        payload=envelope.payload,
    )
