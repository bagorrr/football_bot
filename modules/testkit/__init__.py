"""Stable testkit surface for the approved primary system seam."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from modules.contracts import (
    SUPPORTED_CONTRACTS,
    ContractDefinition,
    ContractEnvelope,
    ContractName,
    RuntimeRole,
)
from modules.contracts import (
    OperatorAlert as OperatorAlert,
)
from modules.ports import (
    AcceptanceObserver,
    AcceptanceRoleStore,
    Clock,
    ConsumeResult,
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

    def present(self, delivery_id: str) -> None:
        """Record one idempotent controlled presentation."""
        if delivery_id not in self.presentations:
            self.presentations.append(delivery_id)


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


@dataclass(slots=True)
class AcceptanceRole:
    """One independently reconnectable runtime responsibility."""

    role: RuntimeRole
    store: AcceptanceRoleStore
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


class AcceptanceSpine:
    """Drive independently restartable roles through public ports."""

    def __init__(
        self,
        *,
        roles: Mapping[RuntimeRole, AcceptanceRole],
        observer: AcceptanceObserver,
        clock: Clock,
        telegram_ingestion: TelegramIngestionAdapter,
        telegram_delivery: TelegramDeliveryAdapter,
        model: ModelAdapter,
        location_resolver: LocationResolverAdapter,
        restart_store: Callable[[RuntimeRole], AcceptanceRoleStore],
    ) -> None:
        self._roles = dict(roles)
        self._observer = observer
        self._clock = clock
        self._telegram_ingestion = telegram_ingestion
        self._telegram_delivery = telegram_delivery
        self._model = model
        self._location_resolver = location_resolver
        self._restart_store = restart_store

    def restart(self, role: RuntimeRole) -> AcceptanceSpine:
        """Reconnect exactly one runtime role without replacing the others."""
        previous = self._roles[role]
        self._roles[role] = AcceptanceRole(
            role=role,
            store=self._restart_store(role),
            supported_versions={
                name: set(versions)
                for name, versions in previous.supported_versions.items()
            },
        )
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
        fail_after_state: RuntimeRole | None = None,
    ) -> AcceptanceSnapshot:
        """Drive one versioned contract round trip through all five roles."""
        correlation_id = _identifier(probe_id, "correlation")
        source_event_id = self._telegram_ingestion.source_event_id(probe_id)
        incoming = self._envelope(
            definition=_CONTRACTS[
                (ContractName.SOURCE_EVENT_RECORDED, source_contract_version)
            ],
            probe_id=probe_id,
            version=source_contract_version,
            fact=source_event_id,
            causation_id=correlation_id,
            correlation_id=correlation_id,
        )
        self._roles[RuntimeRole.INGESTION].store.commit_initial(
            probe_id=probe_id,
            envelope=incoming,
        )

        revision_id = f"source-message-revision:{source_event_id}"
        proposal_id = self._model.proposal_id(revision_id)
        stages = (
            (
                RuntimeRole.APPLICATION,
                ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
                revision_id,
            ),
            (
                RuntimeRole.CLASSIFICATION,
                ContractName.CLASSIFICATION_PROPOSAL,
                proposal_id,
            ),
            (
                RuntimeRole.APPLICATION,
                ContractName.OPPORTUNITY_PUBLICATION_CHANGED,
                self._location_resolver.opportunity_revision_id(
                    proposal_id,
                ),
            ),
            (
                RuntimeRole.RECOMMENDATION,
                ContractName.SEARCH_COMPLETED,
                f"completed-search:{probe_id}",
            ),
            (
                RuntimeRole.BOT_ASSISTANT,
                ContractName.TELEGRAM_PRESENTATION_REQUESTED,
                f"delivery:{probe_id}",
            ),
        )
        for actor, outgoing_name, fact in stages:
            outgoing = self._envelope(
                definition=_CONTRACTS[(outgoing_name, 1)],
                probe_id=probe_id,
                version=1,
                fact=fact,
                causation_id=incoming.message_id,
                correlation_id=correlation_id,
            )
            if actor is fail_after_state:
                outgoing = _with_message_id(outgoing, incoming.message_id)
            try:
                result = self._roles[actor].store.consume(
                    incoming=incoming,
                    supported_versions=self._roles[actor].versions_for(
                        incoming.contract_name,
                    ),
                    received_at=self._clock.now(),
                    outgoing=outgoing,
                )
            except OutboxConflictError as error:
                raise InjectedFailureError from error
            if result is ConsumeResult.REJECTED:
                break
            if actor is RuntimeRole.BOT_ASSISTANT and result is ConsumeResult.APPLIED:
                self._telegram_delivery.present(fact)
            incoming = outgoing

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
    ) -> ContractEnvelope:
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
        attempt = ContractEnvelope(
            contract_name=ContractName.OWNER_STATE_WRITE,
            contract_version=1,
            message_id=message_id,
            producer=actor,
            consumer=owner,
            subject_id=probe_id,
            subject_revision=1,
            idempotency_key=f"{probe_id}:{actor.value}:{owner.value}:denied",
            causation_id=message_id,
            correlation_id=message_id,
            recorded_at=self._clock.now(),
            payload={},
        )
        allowed = self._roles[actor].store.attempt_owner_write(
            owner=owner,
            probe_id=probe_id,
            attempt=attempt,
        )
        if allowed:
            msg = "PostgreSQL accepted a cross-owner state write"
            raise AssertionError(msg)
        raise OwnershipViolationError(message_id)

    def operator_alert(self, message_id: UUID) -> OperatorAlert:
        """Observe one durable body-free operator alert."""
        return self._observer.operator_alert(message_id)

    def _envelope(
        self,
        *,
        definition: ContractDefinition,
        probe_id: str,
        version: int,
        fact: str,
        causation_id: UUID,
        correlation_id: UUID,
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
            recorded_at=self._clock.now(),
            payload={
                "probe_id": probe_id,
                definition.required_fact: fact,
                **{name: 1 for name in definition.required_integer_facts},
            },
        )


def _identifier(probe_id: str, purpose: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"football-bot:{probe_id}:{purpose}")


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
