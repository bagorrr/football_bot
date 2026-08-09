"""Inward-facing runtime ports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, tzinfo
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from modules.contracts import (
    ContractEnvelope,
    ContractName,
    GetCompletedSearch,
    OperatorAlert,
    RawContractEnvelope,
    RuntimeRole,
)
from modules.domain import (
    ActiveChatView,
    ActiveResultContext,
    CompletedSearch,
    CompletedSearchView,
    ConversationState,
    DateInterpretationQuery,
    DateInterpretationResolution,
    DiscoveryDraft,
    GeographyConfirmation,
    GeographyConfirmationEvent,
    GeographySuggestion,
    LanguageSelection,
    LocationResolution,
    LocationResolutionQuery,
    OldChatViewCleanup,
    RequiredDateConfirmation,
    RequiredDateConfirmationEvent,
    SearchResult,
    SourceChatAdmissionResolution,
    SourceChatRegistryEntry,
    TelegramCallbackDeliveryClaim,
    TelegramDeliveryClaim,
    TelegramMessage,
    TelegramPeerIdentity,
    UserIntent,
)


class Clock(Protocol):
    """Application-owned source of authoritative UTC instants."""

    def now(self) -> datetime:
        """Return one timezone-aware current instant."""
        ...


@dataclass(frozen=True, slots=True)
class ResolvedTimezoneData:
    """One timezone and version resolved from the same installed source."""

    iana_timezone: str
    timezone: tzinfo
    version: str


class TimezoneDataAdapter(Protocol):
    """Application-owned boundary for installed IANA timezone data."""

    def resolve(self, iana_timezone: str) -> ResolvedTimezoneData:
        """Resolve one zone and its exact source-bound database version."""
        ...


class TimezoneDataError(RuntimeError):
    """Installed timezone data was missing, invalid, or unverifiable."""


class TelegramIngestionAdapter(Protocol):
    """Controlled Source Chat input boundary."""

    def source_event_id(self, probe_id: str) -> str:
        """Return a synthetic Source Event identity."""
        ...

    def resolve_source_chat(self, address: str) -> SourceChatAdmissionResolution:
        """Resolve one already-accessible chat without joining or reading history."""
        ...

    def capture_source_chat_registration_boundary(
        self, identity: TelegramPeerIdentity
    ) -> str:
        """Capture the current transport position after successful resolution."""
        ...


class SourceChatAdmissionError(RuntimeError):
    """Source Chat address was invalid, inaccessible, or technically unresolved."""


class TelegramDeliveryAdapter(Protocol):
    """Controlled Bot API presentation boundary."""

    def present(self, delivery_id: str) -> None:
        """Record one controlled Telegram presentation."""
        ...

    def send(self, message: TelegramMessage) -> str:
        """Make the sole initial send and return its presentation identity.

        Only a ``TelegramDeliveryPreEffectError`` proves that another initial
        send is safe. Every other failure is an unknown external outcome.
        """
        ...

    def reconcile(self, message: TelegramMessage) -> str | None:
        """Return a known accepted identity without sending, or ``None``."""
        ...

    def remove_inline_actions(
        self, *, telegram_user_id: int, telegram_message_id: str
    ) -> None:
        """Remove actions from one already rendered Telegram message."""
        ...

    def show_typing(self, *, telegram_user_id: int) -> None:
        """Show Telegram's native typing chat action."""
        ...

    def delete_message(
        self, *, telegram_user_id: int, telegram_message_id: str
    ) -> bool:
        """Best-effort delete one old Telegram message."""
        ...

    def answer_callback(self, *, callback_id: str, text: str) -> None:
        """Idempotently answer one callback-query identity without a chat message."""
        ...


class TelegramDeliveryPreEffectError(RuntimeError):
    """The adapter proves that no external Telegram effect occurred."""


class TelegramDeliveryOutcomeUnknownError(RuntimeError):
    """Telegram may have accepted a send whose identity was not returned."""


class ModelAdapter(Protocol):
    """Controlled model boundary for the acceptance spine."""

    def proposal_id(self, revision_id: str) -> str:
        """Return one non-authoritative synthetic proposal identity."""
        ...


class LocationResolverAdapter(Protocol):
    """Controlled location boundary for accepted publication facts."""

    def opportunity_revision_id(self, proposal_id: str) -> str:
        """Return one synthetic accepted Opportunity revision identity."""
        ...

    def resolve(self, query: LocationResolutionQuery) -> LocationResolution:
        """Return non-authoritative interpretations for application validation."""
        ...


class LocationResolverError(RuntimeError):
    """The controlled resolver could not complete one request."""


class DateInterpretationAdapter(Protocol):
    """Controlled natural-language date interpretation boundary."""

    def interpret(self, query: DateInterpretationQuery) -> DateInterpretationResolution:
        """Propose calendar boundaries from application-supplied local context."""
        ...


class DateInterpretationError(RuntimeError):
    """The controlled date interpreter could not complete one request."""


class ConversationLanguageAdapter(Protocol):
    """Bounded semantic adapter for free-text language names."""

    def interpret(self, text: str) -> LanguageSelection | None:
        """Propose one unambiguous language or request clarification."""
        ...

    def render(self, locale: str) -> LanguageSelection | None:
        """Render one previously validated non-static Conversation Language."""
        ...


class OutboxConflictError(RuntimeError):
    """A distinct message attempted to reuse an outbox identity."""


class ConversationAccessDeniedError(RuntimeError):
    """A non-owning runtime attempted to access Bot User state."""


class ConsumeResult(StrEnum):
    """Durable disposition of one inbox delivery."""

    APPLIED = "applied"
    REPLAYED = "replayed"
    REJECTED = "rejected"


class CompletedSearchQueryStatus(StrEnum):
    """Disposition of one public GetCompletedSearch request."""

    ACCEPTED = "accepted"
    MISSING = "missing"
    UNSUPPORTED_VERSION = "unsupported_version"
    INVALID_CONTRACT = "invalid_contract"


@dataclass(frozen=True, slots=True)
class CompletedSearchQueryResult:
    """Query disposition plus an optional immutable Recommendation snapshot."""

    status: CompletedSearchQueryStatus
    view: CompletedSearchView | None = None


class ConversationStore(Protocol):
    """Bot Assistant-owned persistence boundary for onboarding."""

    def serialize_conversation_update(
        self, *, update_id: str, telegram_user_id: int
    ) -> AbstractContextManager[bool]:
        """Serialize one user's update and expose its durable replay state."""
        ...

    def conversation_state(self, telegram_user_id: int) -> ConversationState | None:
        """Return account-level presentation state through a stable query."""
        ...

    def discovery_draft(self, telegram_user_id: int) -> DiscoveryDraft | None:
        """Return the Bot User's one durable unfinished Discovery Draft."""
        ...

    def geography_suggestion(
        self, *, telegram_user_id: int, user_intent: UserIntent
    ) -> GeographySuggestion | None:
        """Return the latest confirmed same-Intent country and optional city."""
        ...

    def expire_inactive_discovery_drafts(self, *, inactive_before: datetime) -> int:
        """Expire only unfinished drafts inactive through the cutoff."""
        ...

    def expire_inactive_discovery_draft(
        self, *, telegram_user_id: int, inactive_before: datetime
    ) -> bool:
        """Expire one Bot User's draft if its inactivity reached the cutoff."""
        ...

    def commit_conversation_update(
        self,
        *,
        update_id: str,
        expected_revision: int,
        state: ConversationState,
        message: TelegramMessage,
        recorded_at: datetime,
        draft: DiscoveryDraft | None = None,
        geography_confirmation: GeographyConfirmation | None = None,
        required_date_confirmation: RequiredDateConfirmation | None = None,
    ) -> bool:
        """Commit one idempotent Telegram update and its owned state."""
        ...

    def commit_conversation_presentation(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        expected_revision: int,
        message: TelegramMessage,
        recorded_at: datetime,
    ) -> bool:
        """Commit one idempotent presentation without changing account state."""
        ...

    def commit_conversation_callback(
        self,
        *,
        update_id: str,
        callback_id: str,
        telegram_user_id: int,
        expected_revision: int,
        text: str,
        recorded_at: datetime,
    ) -> bool:
        """Commit one callback update and its durable notification outbox."""
        ...

    def claim_conversation_callback(
        self,
        *,
        claim_token: UUID,
        claimed_at: datetime,
        stale_before: datetime,
    ) -> TelegramCallbackDeliveryClaim | None:
        """Claim one pending or abandoned callback notification."""
        ...

    def release_conversation_callback_claim(self, *, claim_token: UUID) -> None:
        """Release a callback claim for safe idempotent retry."""
        ...

    def mark_conversation_callback_delivered(
        self,
        *,
        delivery_id: str,
        claim_token: UUID,
        delivered_at: datetime,
    ) -> None:
        """Record one confirmed callback-query answer."""
        ...

    def commit_search_submission(
        self,
        *,
        update_id: str,
        expected_revision: int,
        state: ConversationState,
        draft: DiscoveryDraft,
        command: ContractEnvelope,
        recorded_at: datetime,
    ) -> bool:
        """Commit one Search action, submitting draft, and RunSearch command."""
        ...

    def commit_source_chat_registration_request(
        self,
        *,
        update_id: str,
        expected_revision: int,
        state: ConversationState,
        message: TelegramMessage,
        command: ContractEnvelope,
        recorded_at: datetime,
    ) -> bool:
        """Commit one authorized Bot update and registry command atomically."""
        ...

    def accept_source_chat_registration(
        self,
        *,
        incoming: RawContractEnvelope,
        expected_revision: int,
        state: ConversationState,
        message: TelegramMessage,
        received_at: datetime,
    ) -> ConsumeResult:
        """Consume one admission result and queue its Bot presentation atomically."""
        ...

    def defer_start_to_pending_search_result(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        recorded_at: datetime,
    ) -> bool:
        """Record /start without replacing a queued Search result presentation."""
        ...

    def accept_search_completion(
        self,
        *,
        incoming: RawContractEnvelope,
        expected_state_revision: int,
        expected_draft_revision: int,
        message: TelegramMessage,
        received_at: datetime,
    ) -> ConsumeResult:
        """Queue zero-result presentation without activating it prematurely."""
        ...

    def accept_search_failure(
        self,
        *,
        incoming: RawContractEnvelope,
        state: ConversationState,
        draft: DiscoveryDraft,
        message: TelegramMessage,
        received_at: datetime,
    ) -> ConsumeResult:
        """Restore a confirmed draft and queue Retry after technical failure."""
        ...

    def dispose_search_outcome(
        self,
        *,
        incoming: RawContractEnvelope,
        received_at: datetime,
    ) -> ConsumeResult:
        """Durably consume a stale Search outcome without changing Bot state."""
        ...

    def get_completed_search(
        self,
        query_request_id: UUID,
        *,
        supported_versions: Iterable[int],
        received_at: datetime,
    ) -> CompletedSearchQueryResult:
        """Consume and execute the canonical Completed Search query contract."""
        ...

    def current_conversation_message(
        self, telegram_user_id: int
    ) -> TelegramMessage | None:
        """Return the desired presentation for the current logical screen."""
        ...

    def active_conversation_view(self, telegram_user_id: int) -> ActiveChatView | None:
        """Return the latest successfully presented account view."""
        ...

    def active_result_context(
        self, telegram_user_id: int
    ) -> ActiveResultContext | None:
        """Return the latest successfully presented Completed Search."""
        ...

    def claim_conversation_message(
        self,
        *,
        claim_token: UUID,
        claimed_at: datetime,
        stale_before: datetime,
    ) -> TelegramDeliveryClaim | None:
        """Claim the oldest presentation with its safe send or reconcile mode."""
        ...

    def release_conversation_message_claim(self, *, claim_token: UUID) -> None:
        """Release one pre-effect failure for a later send retry."""
        ...

    def mark_conversation_message_outcome_unknown(
        self,
        *,
        delivery_id: str,
        claim_token: UUID,
        observed_at: datetime,
    ) -> None:
        """Record that Telegram may have accepted the presentation."""
        ...

    def mark_conversation_message_reconciliation_required(
        self,
        *,
        delivery_id: str,
        claim_token: UUID,
        observed_at: datetime,
    ) -> None:
        """Stop automatic delivery and raise a body-free operator condition."""
        ...

    def mark_conversation_message_delivered(
        self,
        *,
        delivery_id: str,
        claim_token: UUID,
        telegram_message_id: str,
        delivered_at: datetime,
    ) -> None:
        """Record one confirmed Bot API delivery."""
        ...

    def claim_old_chat_view_cleanup(
        self,
        *,
        claim_token: UUID,
        claimed_at: datetime,
        stale_before: datetime,
    ) -> OldChatViewCleanup | None:
        """Claim one replaced view for best-effort Telegram cleanup."""
        ...

    def mark_old_chat_view_cleanup_attempted(
        self,
        *,
        delivery_id: str,
        claim_token: UUID,
        deleted: bool,
        attempted_at: datetime,
    ) -> None:
        """Finish one old-view cleanup attempt regardless of platform outcome."""
        ...


class AcceptanceRoleStore(ConversationStore, Protocol):
    """Persistence operations available to exactly one runtime owner."""

    @property
    def role(self) -> RuntimeRole:
        """Return the sole owner represented by this store."""
        ...

    def commit_initial(
        self,
        *,
        probe_id: str,
        envelope: RawContractEnvelope,
    ) -> None:
        """Atomically commit initial owner state and its outbox."""
        ...

    def register_source_chat(
        self,
        *,
        incoming: RawContractEnvelope,
        entry: SourceChatRegistryEntry,
        outgoing: ContractEnvelope,
        received_at: datetime,
    ) -> ConsumeResult:
        """Atomically accept a command, mutate the registry, and publish its event."""
        ...

    def source_chats(self) -> tuple[SourceChatRegistryEntry, ...]:
        """Read application-owned Source Chats through a stable query."""
        ...

    def claim_next(
        self,
        *,
        supported_versions: Mapping[ContractName, Iterable[int]],
        claimed_at: datetime,
    ) -> RawContractEnvelope | None:
        """Claim the next recoverable handoff visible to this role."""
        ...

    def claim_presentation(
        self,
        *,
        claimed_at: datetime,
    ) -> RawContractEnvelope | None:
        """Claim one committed Telegram presentation owned by this role."""
        ...

    def record_presentation_attempt(
        self,
        *,
        envelope: RawContractEnvelope,
        delivery_id: str,
        attempted_at: datetime,
    ) -> None:
        """Durably record an external attempt before presenting."""
        ...

    def record_presentation_success(
        self,
        *,
        message_id: UUID,
        presented_at: datetime,
    ) -> None:
        """Durably record one confirmed idempotent presentation."""
        ...

    def consume(
        self,
        *,
        incoming: RawContractEnvelope,
        supported_versions: Iterable[int],
        received_at: datetime,
        outgoing: ContractEnvelope | None,
    ) -> ConsumeResult:
        """Deduplicate and atomically commit one accepted handoff."""
        ...

    def complete_search(
        self,
        *,
        incoming: RawContractEnvelope,
        completed_search: CompletedSearch,
        query: GetCompletedSearch,
        outgoing: ContractEnvelope,
        received_at: datetime,
    ) -> ConsumeResult:
        """Atomically persist a zero-result Completed Search and its event."""
        ...

    def reject_invalid_contract(
        self,
        *,
        incoming: RawContractEnvelope,
        received_at: datetime,
    ) -> ConsumeResult:
        """Durably reject one supported-version envelope with invalid semantics."""
        ...

    def attempt_owner_write(
        self,
        *,
        owner: RuntimeRole,
        probe_id: str,
        attempt: ContractEnvelope,
    ) -> bool:
        """Attempt a write used to verify the database owner boundary."""
        ...


@dataclass(frozen=True, slots=True)
class AcceptanceObservation:
    """Typed durable outcomes exposed by the observer port."""

    roles: frozenset[RuntimeRole]
    owner_state_records: int
    outbox_records: int
    accepted_inbox_records: int
    rejected_inbox_records: int
    operator_alerts: tuple[OperatorAlert, ...]
    completed: bool


class AcceptanceObserver(Protocol):
    """Administrative observation surface used only by the testkit."""

    def reset(self) -> None:
        """Clear synthetic acceptance records."""
        ...

    def envelope(self, message_id: UUID) -> RawContractEnvelope:
        """Recover one durable envelope."""
        ...

    def delete_completed_search_query(
        self, completed_search_id: str
    ) -> RawContractEnvelope:
        """Inject one missing canonical query at the privileged test seam."""
        ...

    def invalidate_completed_search_query(
        self, completed_search_id: str
    ) -> RawContractEnvelope:
        """Inject one invalid supported query at the privileged test seam."""
        ...

    def restore_completed_search_query(self, query: RawContractEnvelope) -> None:
        """Restore one corrected canonical query at the privileged test seam."""
        ...

    def contract_is_accepted(self, message_id: UUID) -> bool:
        """Report terminal acceptance for one durable contract identity."""
        ...

    def operator_alert(self, message_id: UUID) -> OperatorAlert:
        """Observe one body-free operator alert."""
        ...

    def unresolved_delivery_alerts(self) -> tuple[str, ...]:
        """Observe body-free delivery identities requiring reconciliation."""
        ...

    def geography_confirmations(
        self, telegram_user_id: int
    ) -> tuple[GeographyConfirmationEvent, ...]:
        """Observe append-only explicit geography confirmations."""
        ...

    def required_date_confirmations(
        self, telegram_user_id: int
    ) -> tuple[RequiredDateConfirmationEvent, ...]:
        """Observe append-only explicit Required Date confirmations."""
        ...

    def completed_searches(self, telegram_user_id: int) -> tuple[CompletedSearch, ...]:
        """Observe immutable Completed Searches through the public testkit."""
        ...

    def results(self, completed_search_id: str) -> tuple[SearchResult, ...]:
        """Observe ordered immutable Results through the public testkit."""
        ...

    def search_completions(
        self, search_update_id: str
    ) -> tuple[RawContractEnvelope, ...]:
        """Observe canonical completion events for one Search command identity."""
        ...

    def snapshot(self, probe_id: str) -> AcceptanceObservation:
        """Observe durable outcomes without exposing physical tables."""
        ...
