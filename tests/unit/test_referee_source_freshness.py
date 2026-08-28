"""Standing Referee Availability freshness lifecycle regressions."""

from datetime import UTC, datetime

from modules.application import (
    _source_refereeing_edit_qualifies_freshness,
    _source_refereeing_qualifying_assertion_at,
)
from modules.domain import SourceEventKind, SourceMessageRevision


def _revision(
    *,
    revision: int,
    body: str,
    bounded_metadata: dict[str, object] | None = None,
) -> SourceMessageRevision:
    event_time = datetime(2026, 8, 18 + revision, 9, tzinfo=UTC)
    return SourceMessageRevision(
        source_message_revision_id=f"source:revision:{revision}",
        source_message_id="source",
        source_event_id=f"event:{revision}",
        revision=revision,
        event_kind=SourceEventKind.CREATE if revision == 1 else SourceEventKind.EDIT,
        body=body,
        event_time=event_time,
        recorded_at=event_time,
        bounded_metadata=bounded_metadata or {},
    )


BASE_BODY = (
    "Referee available for an adult football match in Saint Petersburg, "
    "7x7, head referee, paid. Contact @referee_contact"
)


def test_referee_non_actionable_text_edit_does_not_renew_freshness() -> None:
    previous = _revision(revision=1, body=BASE_BODY)
    current = _revision(
        revision=2,
        body=f"{BASE_BODY} Thanks for sharing this opportunity.",
    )

    assert not _source_refereeing_edit_qualifies_freshness(
        current, previous, "referee_availability"
    )


def test_referee_actionable_term_edit_renews_freshness() -> None:
    previous = _revision(revision=1, body=BASE_BODY)
    current = _revision(
        revision=2,
        body=BASE_BODY.replace("7x7", "11x11"),
    )

    assert _source_refereeing_edit_qualifies_freshness(
        current, previous, "referee_availability"
    )


def test_referee_response_route_metadata_edit_renews_freshness() -> None:
    previous = _revision(
        revision=1,
        body=BASE_BODY,
        bounded_metadata={
            "source_message_url": "https://t.me/source/1",
            "source_message_reply_capable": True,
        },
    )
    current = _revision(
        revision=2,
        body=BASE_BODY,
        bounded_metadata={
            "source_message_url": "https://t.me/source/2",
            "source_message_reply_capable": True,
        },
    )

    assert _source_refereeing_edit_qualifies_freshness(
        current, previous, "referee_availability"
    )


def test_referee_explicit_renewal_edit_renews_freshness() -> None:
    previous = _revision(revision=1, body=BASE_BODY)
    current = _revision(revision=2, body=f"Renewed: {BASE_BODY}")

    assert _source_refereeing_edit_qualifies_freshness(
        current, previous, "referee_availability"
    )


def test_referee_qualifying_assertion_keeps_last_actionable_revision() -> None:
    created = _revision(revision=1, body=BASE_BODY)
    cosmetic = _revision(
        revision=2,
        body=f"{BASE_BODY} Thanks for sharing this opportunity.",
    )

    assert (
        _source_refereeing_qualifying_assertion_at(
            cosmetic,
            (created, cosmetic),
            "referee_availability",
        )
        == created.event_time
    )
