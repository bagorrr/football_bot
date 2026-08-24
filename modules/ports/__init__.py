"""Inward-facing runtime ports."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
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
    JsonValue,
    OperatorAlert,
    RawContractEnvelope,
    RuntimeRole,
)
from modules.domain import (
    ActiveChatView,
    ActiveResultContext,
    ClassificationAttempt,
    ClassificationQueueHealth,
    ClassificationRoutingOutcome,
    ClassifierCircuitState,
    CompletedSearch,
    CompletedSearchView,
    ConversationState,
    DateInterpretationQuery,
    DateInterpretationResolution,
    DiscoveryDraft,
    GeographyConfirmation,
    GeographyConfirmationEvent,
    GeographySuggestion,
    IngestionFailure,
    LanguageSelection,
    LocationResolution,
    LocationResolutionQuery,
    OldChatViewCleanup,
    Opportunity,
    ProtectedContentSkip,
    RequiredDateConfirmation,
    RequiredDateConfirmationEvent,
    SearchResult,
    SourceChatAdmissionProvenance,
    SourceChatAdmissionResolution,
    SourceChatIngestionContext,
    SourceChatRegistrationContext,
    SourceChatRegistryEntry,
    SourceEventRecord,
    SourceMessage,
    SourceMessageRevision,
    TelegramAccountCheckpoint,
    TelegramCallbackDeliveryClaim,
    TelegramChannelCheckpoint,
    TelegramDeliveryClaim,
    TelegramDifferenceEvent,
    TelegramDifferenceResult,
    TelegramMessage,
    TelegramPeerIdentity,
    TelegramProtectedContentEvent,
    TelegramProtectionUnavailableEvent,
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

    def notify_live_update(self, identity: TelegramPeerIdentity) -> None:
        """Wake the difference pump without acknowledging Telegram state."""
        ...

    def resolve_source_chat(self, address: str) -> SourceChatAdmissionResolution:
        """Resolve one already-accessible chat without joining or reading history."""
        ...

    def capture_source_chat_registration_boundary(
        self, identity: TelegramPeerIdentity
    ) -> str:
        """Capture the current transport position after successful resolution."""
        ...

    def get_account_difference_event(
        self,
        checkpoint: TelegramAccountCheckpoint,
    ) -> TelegramDifferenceResult | None:
        """Return the next account-wide event from durable application state."""
        ...

    def get_channel_difference_event(
        self,
        identity: TelegramPeerIdentity,
        checkpoint: TelegramChannelCheckpoint,
    ) -> TelegramDifferenceResult | None:
        """Return the next channel event from its typed durable pts."""
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

    def classify(self, request: ClassifierRequest) -> ClassifierAdapterResult:
        """Return one strict, non-authoritative structured proposal."""
        ...

    def semantic_proof(self, request: ClassifierRequest) -> ClassifierAdapterResult:
        """Return one strict, source-bound semantic-proof proposal."""
        ...

    def proposal_id(self, revision_id: str) -> str:
        """Return one non-authoritative synthetic proposal identity."""
        ...

    @property
    def adapter_kind(self) -> str:
        """Return the low-cardinality adapter identity used by its circuit."""
        ...

    def schema_smoke_test(self) -> bool:
        """Run one synthetic structured-output recovery probe."""
        ...


class ClassifierAuthenticationError(RuntimeError):
    """The dedicated classifier identity requires protected recovery."""


class ClassifierQuotaError(RuntimeError):
    """The selected adapter cannot execute until provider capacity recovers."""

    def __init__(self, *, retry_after_seconds: int | None = None) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__("classifier quota unavailable")


class ClassifierExecutionTimeoutError(RuntimeError):
    """One adapter execution reached the classifier's hard deadline."""


class ClassifierTransientError(RuntimeError):
    """One retryable provider failure, optionally with a required delay."""

    def __init__(self, *, retry_after_seconds: int | None = None) -> None:
        if retry_after_seconds is not None and retry_after_seconds < 0:
            raise ValueError("classifier Retry-After cannot be negative")
        self.retry_after_seconds = retry_after_seconds
        super().__init__("classifier provider request failed transiently")


@dataclass(frozen=True, slots=True)
class ClassifierRequest:
    """Pinned classifier request with immutable policy provenance."""

    source_message_revision_id: str
    body: str
    source_event_time: str
    context_bundle_version: str
    source_chat_reference: str
    source_chat_timezone: str | None
    source_chat_geography: dict[str, JsonValue]
    bounded_metadata: dict[str, JsonValue]
    eligible_reply_context: dict[str, JsonValue] | None
    requested_model: str
    requested_reasoning_effort: str
    prompt_version: str
    schema_version: str
    glossary_version: str
    context_policy_version: str
    routing_policy_version: str
    pass_kind: str = "primary"
    adjacent_context: tuple[dict[str, JsonValue], ...] = ()
    proof_candidate_key: str | None = None


@dataclass(frozen=True, slots=True)
class ClassifierAdapterResult:
    """Provider-neutral classifier response plus effective provenance."""

    output: dict[str, JsonValue]
    effective_model: str
    effective_reasoning_effort: str
    codex_version: str
    adapter_kind: str
    adapter_version: str
    duration_ms: int
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class ClassificationProofWork:
    """Protected durable candidate state for a retryable semantic-proof pass."""

    source_message_revision_id: str
    ambiguity_output: dict[str, JsonValue]
    ambiguity_pass_execution: dict[str, JsonValue]
    ambiguity_adjacent_context: tuple[dict[str, JsonValue], ...]
    semantic_proofs: tuple[dict[str, JsonValue], ...] = ()
    semantic_proof_executions: tuple[dict[str, JsonValue], ...] = ()


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


@dataclass(frozen=True, slots=True)
class ClaimedContract:
    """One leased envelope plus transport-owned immutable provenance identity."""

    envelope: RawContractEnvelope
    source_chat_admission_provenance_id: UUID | None = None


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

    def next_source_chat_registration_generation(self) -> int:
        """Return the next durable one-administrator registration generation."""
        ...

    def accept_source_chat_registration(
        self,
        *,
        incoming: RawContractEnvelope,
        expected_revision: int,
        state: ConversationState,
        message: TelegramMessage,
        received_at: datetime,
        invalid_contract: bool = False,
    ) -> ConsumeResult:
        """Consume one admission result and queue its Bot presentation atomically."""
        ...

    def source_chat_registration_origin(
        self,
        correlation_id: UUID,
    ) -> SourceChatRegistrationContext | None:
        """Recover the Bot-owned durable origin for one pending registration."""
        ...

    def source_chat_registration_origin_for_terminal(
        self,
        incoming: RawContractEnvelope,
    ) -> SourceChatRegistrationContext | None:
        """Recover the unique durable origin proven by a terminal causation chain."""
        ...

    def reject_invalid_contract(
        self,
        *,
        incoming: RawContractEnvelope,
        received_at: datetime,
        outgoing: ContractEnvelope | None = None,
    ) -> ConsumeResult:
        """Durably reject one supported-version envelope with invalid semantics."""
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
        current_result: SearchResult | None,
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

    def replace_unauthorized_administration_delivery(
        self,
        *,
        delivery_id: str,
        claim_token: UUID,
        expected_revision: int,
        state: ConversationState,
        message: TelegramMessage,
        recorded_at: datetime,
    ) -> None:
        """Consume a claimed admin view and queue ordinary Settings atomically."""
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
        stale_outgoing: ContractEnvelope,
        received_at: datetime,
    ) -> ConsumeResult:
        """Atomically accept admission and publish the applicable terminal result."""
        ...

    def source_chats(self) -> tuple[SourceChatRegistryEntry, ...]:
        """Read application-owned Source Chats through a stable query."""
        ...

    def configure_source_chat_classifier_context(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        iana_timezone: str,
        country_id: str | None,
        city_id: str | None,
    ) -> None:
        """Set bounded Application-owned context for one active generation."""
        ...

    def eligible_source_chat_generation(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
    ) -> SourceChatRegistryEntry | None:
        """Return only the enabled current generation for an incoming event."""
        ...

    def source_chat_ingestion_context(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
    ) -> SourceChatIngestionContext | None:
        """Read the current eligible generation and durable difference cursor."""
        ...

    def initialize_account_ingestion_checkpoint(
        self,
        checkpoint: TelegramAccountCheckpoint,
        *,
        initialized_at: datetime,
    ) -> None:
        """Create the explicit Ingestion-owned account difference state."""
        ...

    def account_ingestion_checkpoint(self) -> TelegramAccountCheckpoint:
        """Read the durable Ingestion-owned account difference state."""
        ...

    def channel_ingestion_checkpoint(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
    ) -> TelegramChannelCheckpoint:
        """Read one Source Chat generation's durable channel pts."""
        ...

    def discard_account_difference_event(
        self,
        *,
        event: (
            TelegramDifferenceEvent
            | TelegramProtectedContentEvent
            | TelegramProtectionUnavailableEvent
        ),
        recorded_at: datetime,
    ) -> bool:
        """Advance one ineligible account event without retaining content."""
        ...

    def commit_source_event(
        self,
        *,
        event: TelegramDifferenceEvent | TelegramProtectedContentEvent,
        registry_generation: int,
        envelope: ContractEnvelope,
        recorded_at: datetime,
        inject_database_failure: bool = False,
    ) -> bool:
        """Atomically record one event, its outbox, and checkpoint advance."""
        ...

    def source_stream_is_stopped(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
    ) -> bool:
        """Return whether one Source Chat generation is durably stopped."""
        ...

    def account_stream_is_stopped(self) -> bool:
        """Return whether the account-wide difference stream is stopped."""
        ...

    def ingestion_role_is_stopped(self) -> bool:
        """Return whether session/auth loss stopped the whole ingestion role."""
        ...

    def stop_source_stream(
        self,
        *,
        failure: IngestionFailure,
        envelope: ContractEnvelope,
    ) -> bool:
        """Atomically record body-free stream failure state and its outbox."""
        ...

    def stop_account_stream(
        self,
        *,
        failure: IngestionFailure,
        envelope: ContractEnvelope,
    ) -> bool:
        """Atomically record an account-stream stop and its durable handoff."""
        ...

    def stop_ingestion_role(
        self,
        *,
        failure: IngestionFailure,
        envelope: ContractEnvelope,
    ) -> bool:
        """Atomically stop every ingestion pump after session/auth loss."""
        ...

    def accept_source_event(
        self,
        *,
        incoming: ContractEnvelope,
        received_at: datetime,
        outgoing: ContractEnvelope | None = None,
    ) -> ConsumeResult:
        """Apply one Source Event to Application-owned Source Message state."""
        ...

    def record_classification_attempt(
        self,
        *,
        incoming: ContractEnvelope,
        attempt: ClassificationAttempt,
        result: ClassifierAdapterResult,
        outgoing: ContractEnvelope | None,
        received_at: datetime,
        additional_attempts: tuple[
            tuple[ClassificationAttempt, ClassifierAdapterResult], ...
        ] = (),
        finalize: bool = True,
        proof_work: ClassificationProofWork | None = None,
        clear_proof_work: bool = False,
        retry_at: datetime | None = None,
        circuit_state: str | None = None,
        circuit_retry_at: datetime | None = None,
    ) -> ConsumeResult:
        """Retain one execution and optionally complete its queue handoff."""
        ...

    def begin_classification_attempt(
        self,
        *,
        incoming: ContractEnvelope,
        attempt: ClassificationAttempt,
        result: ClassifierAdapterResult,
        started_at: datetime,
    ) -> None:
        """Persist an execution identity before crossing the model boundary."""
        ...

    def classification_attempts_for_revision(
        self, source_message_revision_id: str
    ) -> tuple[ClassificationAttempt, ...]:
        """Read prior classifier attempts needed for bounded queue retry."""
        ...

    def close_classifier_authentication_circuit(
        self, *, adapter_kind: str, closed_at: datetime
    ) -> None:
        """Close one authentication circuit after its protected smoke test."""
        ...

    def classifier_circuit_state(
        self, adapter_kind: str
    ) -> ClassifierCircuitState | None:
        """Read the adapter's body-free circuit for bounded recovery timing."""
        ...

    def classification_proof_work_for_revision(
        self, source_message_revision_id: str
    ) -> ClassificationProofWork | None:
        """Read protected candidate state for a retryable semantic-proof pass."""
        ...

    def proposition_opportunity_ids(
        self, source_message_id: str
    ) -> tuple[tuple[int, str], ...]:
        """Read Application-owned proposition slots for one Source Message."""
        ...

    def proposition_opportunity_records(
        self, source_message_id: str
    ) -> tuple[dict[str, JsonValue], ...]:
        """Read durable proposition lineage facts for one Source Message."""
        ...

    def active_opportunity_records(
        self, source_message_id: str
    ) -> tuple[dict[str, JsonValue], ...]:
        """Read all currently active Application opportunities for one source."""
        ...

    def record_classification_routing_outcome(
        self,
        *,
        incoming: ContractEnvelope,
        outcome: ClassificationRoutingOutcome,
        received_at: datetime,
        suppressed_opportunities: tuple[dict[str, JsonValue], ...] = (),
        additional_outgoings: tuple[ContractEnvelope, ...] = (),
    ) -> ConsumeResult:
        """Atomically retain one body-free Application routing outcome."""
        ...

    def publish_opportunity(
        self,
        *,
        incoming: ContractEnvelope,
        opportunity: dict[str, JsonValue],
        outgoing: ContractEnvelope,
        received_at: datetime,
        routing_outcome: ClassificationRoutingOutcome | None = None,
        suppressed_opportunities: tuple[dict[str, JsonValue], ...] = (),
        additional_outgoings: tuple[ContractEnvelope, ...] = (),
    ) -> ConsumeResult:
        """Atomically accept Application facts and publish one state change."""
        ...

    def publish_opportunities(
        self,
        *,
        incoming: ContractEnvelope,
        opportunities: tuple[dict[str, JsonValue], ...],
        outgoing: ContractEnvelope,
        received_at: datetime,
        routing_outcome: ClassificationRoutingOutcome | None = None,
        suppressed_opportunities: tuple[dict[str, JsonValue], ...] = (),
        additional_outgoings: tuple[ContractEnvelope, ...] = (),
    ) -> ConsumeResult:
        """Atomically accept a compound candidate batch and publish one state change."""
        ...

    def project_opportunity(
        self,
        *,
        incoming: ContractEnvelope,
        received_at: datetime,
    ) -> ConsumeResult:
        """Apply one accepted publication to Recommendation's projection."""
        ...

    def owned_source_events(self) -> tuple[SourceEventRecord, ...]:
        """Read Ingestion-owned Source Events with the current role credential."""
        ...

    def owned_source_messages(self) -> tuple[SourceMessage, ...]:
        """Read Application-owned Source Messages with the current credential."""
        ...

    def source_message_revision(
        self, source_message_revision_id: str
    ) -> SourceMessageRevision | None:
        """Read one Application-owned immutable Source Message revision."""
        ...

    def eligible_reply_revision(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        telegram_message_id: int,
        current_event_time: datetime,
    ) -> SourceMessageRevision | None:
        """Return one retained current direct-reply target after the start boundary."""
        ...

    def adjacent_source_message_revisions(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        telegram_message_id: int,
        current_event_time: datetime,
    ) -> tuple[SourceMessageRevision, ...]:
        """Return the bounded same-generation adjacent context candidates."""
        ...

    def claim_next(
        self,
        *,
        supported_versions: Mapping[ContractName, Iterable[int]],
        claimed_at: datetime,
    ) -> ClaimedContract | None:
        """Claim the next recoverable handoff visible to this role."""
        ...

    def source_chat_admission_provenance(
        self,
        provenance_id: UUID,
    ) -> SourceChatAdmissionProvenance | None:
        """Read one Application proof through the Ingestion-only database seam."""
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
        """Evaluate one snapshot and atomically persist Search, Results and event."""
        ...

    def set_search_snapshot_hook(self, hook: Callable[[], None]) -> None:
        """Install one controlled test hook after candidate snapshot selection."""
        ...

    def find_search_results(
        self,
        completed_search: CompletedSearch,
        game_search_details: Mapping[str, tuple[str, ...]],
    ) -> tuple[SearchResult, ...]:
        """Deterministically match active Recommendation projections."""
        ...

    def source_chat_registration_context(
        self,
        correlation_id: UUID,
    ) -> SourceChatRegistrationContext | None:
        """Recover the authorized requester and generation for one admission."""
        ...

    def source_chat_registration_context_for_admission(
        self,
        incoming: RawContractEnvelope,
    ) -> SourceChatRegistrationContext | None:
        """Recover the unique durable request proven by admission causation."""
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

    def source_messages(self) -> tuple[SourceMessage, ...]:
        """Observe Application-owned Source Messages through the testkit."""
        ...

    def source_events(self) -> tuple[SourceEventRecord, ...]:
        """Observe Ingestion-owned Source Events through the testkit."""
        ...

    def source_message_revisions(self) -> tuple[SourceMessageRevision, ...]:
        """Observe immutable Source Message revisions through the testkit."""
        ...

    def protected_content_skips(self) -> tuple[ProtectedContentSkip, ...]:
        """Observe body-free protected-event outcomes through the testkit."""
        ...

    def ingestion_failures(self) -> tuple[IngestionFailure, ...]:
        """Observe operator-visible body-free ingestion failure state."""
        ...

    def source_stream_stop_contracts(self) -> tuple[RawContractEnvelope, ...]:
        """Observe body-free SourceStreamStopped handoffs."""
        ...

    def delete_account_ingestion_checkpoint(self) -> None:
        """Inject an unrecoverable missing account checkpoint."""
        ...

    def delete_channel_ingestion_checkpoint(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
    ) -> None:
        """Inject an unrecoverable missing channel checkpoint."""
        ...

    def source_event_contracts(self) -> tuple[RawContractEnvelope, ...]:
        """Observe SourceEventRecorded outbox signals through the testkit."""
        ...

    def classification_attempts(self) -> tuple[ClassificationAttempt, ...]:
        """Observe durable classifier execution provenance."""
        ...

    def classification_queue_health(
        self, observed_at: datetime
    ) -> ClassificationQueueHealth:
        """Observe body-free queue age, leases, failures, and circuit state."""
        ...

    def classification_routing_outcomes(
        self,
    ) -> tuple[ClassificationRoutingOutcome, ...]:
        """Observe body-free classifier routing state."""
        ...

    def opportunities(self) -> tuple[Opportunity, ...]:
        """Observe Application-authoritative accepted Opportunities."""
        ...

    def opportunity_publication_contracts(
        self, source_message_revision_id: str
    ) -> tuple[RawContractEnvelope, ...]:
        """Observe publication outbox effects for one Source Message revision."""
        ...

    def completed_search_opportunity_revision_inputs(
        self, completed_search_id: str
    ) -> tuple[dict[str, JsonValue], ...]:
        """Observe the immutable evaluated Opportunity revision input set."""
        ...

    def inject_concurrent_opportunity_revision(
        self,
        *,
        opportunity_id: str,
        opportunity_revision_id: str,
        open_places: int,
    ) -> None:
        """Inject a controlled projection revision for snapshot concurrency tests."""
        ...

    def replace_source_event_contract_version(
        self,
        message_id: UUID,
        version: int,
    ) -> RawContractEnvelope:
        """Inject one unsupported Source Event version at the contract seam."""
        ...

    def invalidate_contract_payload(
        self,
        message_id: UUID,
        payload_updates: dict[str, JsonValue],
    ) -> RawContractEnvelope:
        """Inject semantic incompatibility into one serialized contract."""
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

    def invalidate_source_chat_admission(
        self,
        correlation_id: UUID,
        payload_updates: dict[str, JsonValue],
    ) -> RawContractEnvelope:
        """Inject invalid Source Chat facts at the privileged test seam."""
        ...

    def invalidate_source_chat_contract(
        self,
        correlation_id: UUID,
        contract_name: ContractName,
        payload_updates: dict[str, JsonValue],
        *,
        new_message_id: UUID | None = None,
        new_subject_id: str | None = None,
        new_idempotency_key: str | None = None,
        new_recorded_at: datetime | None = None,
        new_contract_version: int | None = None,
        causation_id: UUID | None = None,
        new_correlation_id: UUID | None = None,
        new_subject_revision: int | None = None,
    ) -> RawContractEnvelope:
        """Inject one selected Source Chat wire fault at the test seam."""
        ...

    def replace_source_chat_contract_payload(
        self,
        correlation_id: UUID,
        contract_name: ContractName,
        payload: JsonValue,
    ) -> RawContractEnvelope:
        """Replace one Source Chat payload at the privileged test seam."""
        ...

    def invalidate_classifier_context(
        self,
        source_message_revision_id: str,
        contract_name: ContractName,
        payload_updates: dict[str, JsonValue],
        *,
        new_subject_id: str | None = None,
        new_idempotency_key: str | None = None,
    ) -> RawContractEnvelope:
        """Inject one classifier-context wire fault at the test seam."""
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

    def source_chat_contracts(
        self,
        correlation_id: UUID,
        contract_name: ContractName,
    ) -> tuple[RawContractEnvelope, ...]:
        """Observe Source Chat outcomes for one external registration origin."""
        ...

    def snapshot(
        self,
        probe_id: str,
        *,
        message_id: UUID | None = None,
    ) -> AcceptanceObservation:
        """Observe durable outcomes without exposing physical tables."""
        ...
