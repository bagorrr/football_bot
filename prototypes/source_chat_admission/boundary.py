"""PROTOTYPE — pure Source Chat admission and protection-boundary logic.

The module deliberately accepts no Telegram message body. It models only the
confirmed identity, admission-boundary, and protected-skip decisions needed by
the live probe.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime


@dataclass(frozen=True)
class SourceChat:
    stable_chat_id: int
    current_address_kind: str
    processing_started_at: datetime
    generation: int
    enabled: bool = True


@dataclass(frozen=True)
class ProtectedContentSkip:
    kind: str
    source_chat_id: int
    observed_at: datetime


@dataclass(frozen=True)
class AdmissionResult:
    source_chat: SourceChat
    created: bool


class SourceChatRegistry:
    def __init__(self) -> None:
        self._current: dict[int, SourceChat] = {}
        self._next_generation: dict[int, int] = {}

    def admit(
        self,
        *,
        stable_chat_id: int,
        address_kind: str,
        succeeded_at: datetime,
    ) -> AdmissionResult:
        existing = self._current.get(stable_chat_id)
        if existing and existing.enabled:
            updated = replace(existing, current_address_kind=address_kind)
            self._current[stable_chat_id] = updated
            return AdmissionResult(updated, created=False)

        generation = self._next_generation.get(stable_chat_id, 1)
        admitted = SourceChat(
            stable_chat_id=stable_chat_id,
            current_address_kind=address_kind,
            processing_started_at=succeeded_at,
            generation=generation,
        )
        self._current[stable_chat_id] = admitted
        self._next_generation[stable_chat_id] = generation + 1
        return AdmissionResult(admitted, created=True)

    def remove(self, *, stable_chat_id: int) -> None:
        existing = self._current[stable_chat_id]
        self._current[stable_chat_id] = replace(existing, enabled=False)


def route_event_without_body(
    *,
    source_chat_id: int,
    observed_at: datetime,
    peer_noforwards: bool,
    message_noforwards: bool,
) -> ProtectedContentSkip | None:
    """Return a body-free skip, or None when ordinary processing may begin."""

    if peer_noforwards or message_noforwards:
        return ProtectedContentSkip(
            kind="protected_content_skipped",
            source_chat_id=source_chat_id,
            observed_at=observed_at,
        )
    return None
