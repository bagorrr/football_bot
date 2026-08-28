"""Exact Repost Cluster behavior through the durable Player system seam."""

import os
import time
from datetime import UTC, datetime
from threading import Event, Thread

import psycopg
from psycopg import sql

from modules.contracts import (
    ContractName,
    JsonValue,
    RuntimeRole,
    derive_contract_message_id,
)
from modules.domain import ExactRepostCluster, SourceEventKind
from modules.player_promotion_runtime import (
    CONTROLLED_COSMETIC_EDIT_BODY,
    CONTROLLED_LIFECYCLE_BODY,
    CONTROLLED_MATERIAL_EDIT_BODY,
    CONTROLLED_REJECTED_MATERIAL_EDIT_BODY,
    DurableAcceptanceProbe,
)


def _probe(
    *operations: dict[str, JsonValue],
) -> DurableAcceptanceProbe:
    return DurableAcceptanceProbe(
        database_url=os.environ["TEST_DATABASE_URL"],
        execution_id="exact-repost-regression",
        case_id="exact-repost-regression",
        operations=tuple(operations) or ({"kind": "repost"},),
    )


def _source_id(revision_id: str) -> str:
    return revision_id.rsplit(":revision:", 1)[0]


def _create_pair(
    probe: DurableAcceptanceProbe,
    *,
    first_body: str = CONTROLLED_LIFECYCLE_BODY,
    second_body: str = CONTROLLED_LIFECYCLE_BODY,
    first_publisher: str = "publisher:one",
    second_publisher: str = "publisher:one",
    first_message_id: int = 701,
    second_message_id: int = 702,
) -> tuple[str, str, str, str]:
    first_revision, _ = probe.source_event(
        body=first_body,
        operation_number=1,
        telegram_message_id=first_message_id,
        source_publisher_id=first_publisher,
        event_time=datetime(2026, 8, 18, 9, 6, tzinfo=UTC),
    )
    probe.clock.advance_to(datetime(2026, 8, 18, 9, 7, tzinfo=UTC))
    second_revision, _ = probe.source_event(
        body=second_body,
        operation_number=2,
        telegram_message_id=second_message_id,
        source_publisher_id=second_publisher,
        event_time=datetime(2026, 8, 18, 9, 7, tzinfo=UTC),
    )
    assert first_revision is not None
    assert second_revision is not None
    return (
        first_revision,
        second_revision,
        _source_id(first_revision),
        _source_id(second_revision),
    )


def _cluster(probe: DurableAcceptanceProbe) -> ExactRepostCluster:
    clusters = probe.system.exact_repost_clusters()
    assert len(clusters) == 1
    return clusters[0]


def test_distinct_source_messages_form_one_durable_cluster_with_newest_rep() -> None:
    probe = _probe()
    first_revision, second_revision, first_source, second_source = _create_pair(probe)

    assert first_revision != second_revision
    assert first_source != second_source
    source_events = probe.system.source_events()
    assert {event.source_publisher_id for event in source_events} == {"publisher:one"}
    cluster = _cluster(probe)
    assert cluster.representative_source_message_id == second_source
    assert cluster.publication_state == "active"
    assert cluster.moderation_state == "none"
    assert cluster.source_publisher_id == "publisher:one"
    members = probe.system.exact_repost_cluster_members(cluster.exact_repost_cluster_id)
    assert {member.source_message_id for member in members} == {
        first_source,
        second_source,
    }
    first_member = next(
        member for member in members if member.source_message_id == first_source
    )
    second_member = next(
        member for member in members if member.source_message_id == second_source
    )
    assert first_member.publication_state == "suppressed"
    assert first_member.publication_reason == "exact_repost_superseded"
    assert first_member.source_message_revision_id == first_revision
    assert not first_member.is_representative
    assert second_member.publication_state == "active"
    assert second_member.publication_reason is None
    assert second_member.source_message_revision_id == second_revision
    assert second_member.is_representative
    assert cluster.freshness_renewed_at == probe.clock.now()


def test_decorative_normalization_matches_only_the_same_resolved_date() -> None:
    first_body = (
        "⚽ Open match in Saint Petersburg on 2026-12-01. "
        "Need one place! Contact @controlled_open_match."
    )
    equivalent_body = (
        "Open match in Saint Petersburg on 2026-12-01.   "
        "Need one place! Contact @controlled_open_match. ⚽"
    )
    probe = _probe(
        {"kind": "repost", "source": first_body},
        {"kind": "repost", "source": equivalent_body},
    )
    _create_pair(probe, first_body=first_body, second_body=equivalent_body)
    assert len(probe.system.exact_repost_clusters()) == 1

    date_changed_body = equivalent_body.replace("2026-12-01", "2026-12-02")
    probe = _probe(
        {"kind": "repost", "source": first_body},
        {"kind": "repost", "source": date_changed_body},
    )
    _create_pair(probe, first_body=first_body, second_body=date_changed_body)
    assert len(probe.system.exact_repost_clusters()) == 2
    assert len(probe.system.opportunities()) == 2

    near_duplicate_body = equivalent_body.replace("one place!", "one place?")
    probe = _probe(
        {"kind": "repost", "source": first_body},
        {"kind": "repost", "source": near_duplicate_body},
    )
    _create_pair(probe, first_body=first_body, second_body=near_duplicate_body)
    assert len(probe.system.exact_repost_clusters()) == 2
    assert len(probe.system.opportunities()) == 2


def test_different_visible_publishers_do_not_share_a_cluster() -> None:
    probe = _probe()
    _create_pair(probe, second_publisher="publisher:two")

    clusters = probe.system.exact_repost_clusters()
    assert len(clusters) == 2
    assert all(
        len(probe.system.exact_repost_cluster_members(cluster.exact_repost_cluster_id))
        == 1
        for cluster in clusters
    )


def test_material_body_edit_without_reclassification_removes_old_membership() -> None:
    probe = _probe({"kind": "edit", "source": CONTROLLED_REJECTED_MATERIAL_EDIT_BODY})
    first_revision, _ = probe.source_event(
        body=CONTROLLED_LIFECYCLE_BODY,
        operation_number=1,
        telegram_message_id=704,
        source_publisher_id="publisher:one",
        event_time=datetime(2026, 8, 18, 9, 6, tzinfo=UTC),
    )
    assert first_revision is not None
    cluster_before = _cluster(probe)
    cluster_id = cluster_before.exact_repost_cluster_id
    old_member = probe.system.exact_repost_cluster_members(cluster_id)
    assert len(old_member) == 1
    assert old_member[0].source_message_revision_id == first_revision

    probe.clock.advance_to(datetime(2026, 8, 18, 9, 8, tzinfo=UTC))
    edited_revision, snapshot = probe.source_event(
        body=CONTROLLED_REJECTED_MATERIAL_EDIT_BODY,
        operation_number=2,
        kind=SourceEventKind.EDIT,
        revision=2,
        telegram_message_id=704,
        source_publisher_id="publisher:one",
        event_time=datetime(2026, 8, 18, 9, 8, tzinfo=UTC),
    )
    assert edited_revision == f"{_source_id(first_revision)}:revision:2"
    assert snapshot["publication_state"] == "suppressed"
    exact = snapshot.get("exact_repost")
    assert isinstance(exact, dict)
    assert exact["cluster_count"] == 1
    assert exact["member_count"] == 0
    cluster = _cluster(probe)
    assert cluster.exact_repost_cluster_id == cluster_id
    assert cluster.representative_source_message_id is None
    assert cluster.representative_source_message_revision_id is None
    assert cluster.publication_state == "suppressed"
    assert probe.system.exact_repost_cluster_members(cluster_id) == ()

    revisions = {
        item.source_message_revision_id: item
        for item in probe.system.source_message_revisions()
    }
    assert revisions[first_revision].body == CONTROLLED_LIFECYCLE_BODY
    assert revisions[edited_revision].body == CONTROLLED_REJECTED_MATERIAL_EDIT_BODY
    opportunities = probe.system.opportunities()
    assert len(opportunities) == 1
    assert opportunities[0].source_message_revision_id == edited_revision
    assert opportunities[0].publication_state == "suppressed"
    assert opportunities[0].publication_reason == "source_revision_superseded"
    projected = probe.system.recommendation_opportunities()
    current_projection = max(
        projected,
        key=lambda item: int(item.opportunity_revision_id.rsplit(":", 1)[-1]),
    )
    assert current_projection.publication_state == "suppressed"
    assert current_projection.publication_reason == "source_revision_superseded"


def test_cosmetic_edit_retains_cluster_identity_and_renews_freshness() -> None:
    probe = _probe({"kind": "edit", "source": CONTROLLED_COSMETIC_EDIT_BODY})
    first_revision, _ = probe.source_event(
        body=CONTROLLED_LIFECYCLE_BODY,
        operation_number=1,
        telegram_message_id=705,
        source_publisher_id="publisher:one",
        event_time=datetime(2026, 8, 18, 9, 6, tzinfo=UTC),
    )
    assert first_revision is not None
    before = _cluster(probe)
    before_key = before.cluster_key
    probe.clock.advance_to(datetime(2026, 8, 18, 9, 8, tzinfo=UTC))
    edited_revision, snapshot = probe.source_event(
        body=CONTROLLED_COSMETIC_EDIT_BODY,
        operation_number=2,
        kind=SourceEventKind.EDIT,
        revision=2,
        telegram_message_id=705,
        source_publisher_id="publisher:one",
        event_time=datetime(2026, 8, 18, 9, 8, tzinfo=UTC),
    )
    assert edited_revision == f"{_source_id(first_revision)}:revision:2"
    cluster = _cluster(probe)
    assert cluster.cluster_key == before_key
    assert cluster.representative_source_message_revision_id == edited_revision
    assert cluster.representative_source_message_id == _source_id(edited_revision)
    assert cluster.freshness_renewed_at == probe.clock.now()
    members = probe.system.exact_repost_cluster_members(cluster.exact_repost_cluster_id)
    assert len(members) == 1
    assert members[0].source_message_revision_id == edited_revision
    assert members[0].publication_state == "active"
    assert members[0].publication_reason is None
    assert snapshot["publication_state"] == "active"
    exact = snapshot.get("exact_repost")
    assert isinstance(exact, dict)
    assert exact["projection_consistent"] is True
    revisions = {
        item.source_message_revision_id
        for item in probe.system.source_message_revisions()
    }
    assert first_revision in revisions
    assert edited_revision in revisions


def test_material_publisher_edit_reconciles_to_a_new_cluster() -> None:
    probe = _probe({"kind": "edit", "source": CONTROLLED_LIFECYCLE_BODY})
    first_revision, _ = probe.source_event(
        body=CONTROLLED_LIFECYCLE_BODY,
        operation_number=1,
        telegram_message_id=706,
        source_publisher_id="publisher:one",
        event_time=datetime(2026, 8, 18, 9, 6, tzinfo=UTC),
    )
    assert first_revision is not None
    old_cluster = _cluster(probe)
    old_cluster_id = old_cluster.exact_repost_cluster_id
    probe.clock.advance_to(datetime(2026, 8, 18, 9, 8, tzinfo=UTC))
    edited_revision, snapshot = probe.source_event(
        body=CONTROLLED_LIFECYCLE_BODY,
        operation_number=2,
        kind=SourceEventKind.EDIT,
        revision=2,
        telegram_message_id=706,
        source_publisher_id="publisher:two",
        event_time=datetime(2026, 8, 18, 9, 8, tzinfo=UTC),
    )
    assert edited_revision is not None
    assert edited_revision != first_revision
    clusters = probe.system.exact_repost_clusters()
    assert len(clusters) == 2
    old_cluster = next(
        cluster
        for cluster in clusters
        if cluster.exact_repost_cluster_id == old_cluster_id
    )
    new_cluster = next(
        cluster
        for cluster in clusters
        if cluster.exact_repost_cluster_id != old_cluster_id
    )
    assert probe.system.exact_repost_cluster_members(old_cluster_id) == ()
    new_members = probe.system.exact_repost_cluster_members(
        new_cluster.exact_repost_cluster_id
    )
    assert len(new_members) == 1
    assert new_members[0].source_message_revision_id == edited_revision
    assert new_cluster.source_publisher_id == "publisher:two"
    assert new_cluster.representative_source_message_revision_id == edited_revision
    assert new_cluster.publication_state == "active"
    assert old_cluster.representative_source_message_id is None
    assert snapshot["publication_state"] == "active"


def test_material_resolved_date_edit_reconciles_to_a_new_cluster() -> None:
    probe = _probe({"kind": "edit", "source": CONTROLLED_MATERIAL_EDIT_BODY})
    first_revision, _ = probe.source_event(
        body=CONTROLLED_LIFECYCLE_BODY,
        operation_number=1,
        telegram_message_id=707,
        source_publisher_id="publisher:one",
        event_time=datetime(2026, 8, 18, 9, 6, tzinfo=UTC),
    )
    assert first_revision is not None
    old_cluster = _cluster(probe)
    old_cluster_id = old_cluster.exact_repost_cluster_id
    probe.clock.advance_to(datetime(2026, 8, 18, 9, 8, tzinfo=UTC))
    edited_revision, snapshot = probe.source_event(
        body=CONTROLLED_MATERIAL_EDIT_BODY,
        operation_number=2,
        kind=SourceEventKind.EDIT,
        revision=2,
        telegram_message_id=707,
        source_publisher_id="publisher:one",
        event_time=datetime(2026, 8, 18, 9, 8, tzinfo=UTC),
    )
    assert edited_revision is not None
    clusters = probe.system.exact_repost_clusters()
    assert len(clusters) == 2
    old_cluster = next(
        cluster
        for cluster in clusters
        if cluster.exact_repost_cluster_id == old_cluster_id
    )
    new_cluster = next(
        cluster
        for cluster in clusters
        if cluster.exact_repost_cluster_id != old_cluster_id
    )
    assert probe.system.exact_repost_cluster_members(old_cluster_id) == ()
    new_members = probe.system.exact_repost_cluster_members(
        new_cluster.exact_repost_cluster_id
    )
    assert len(new_members) == 1
    assert new_members[0].source_message_revision_id == edited_revision
    assert new_cluster.resolved_event_date == "2026-12-02/2026-12-02"
    assert new_cluster.representative_source_message_revision_id == edited_revision
    assert new_cluster.publication_state == "active"
    assert old_cluster.representative_source_message_id is None
    assert snapshot["publication_state"] == "active"


def test_deleting_newest_representative_reactivates_old_survivor() -> None:
    probe = _probe()
    _, _, first_source, second_source = _create_pair(probe)
    deleted_revision, _ = probe.source_event(
        body=None,
        operation_number=3,
        kind=SourceEventKind.DELETE,
        revision=2,
        telegram_message_id=702,
        source_publisher_id="publisher:one",
        event_time=datetime(2026, 8, 18, 9, 8, tzinfo=UTC),
    )
    assert deleted_revision == f"{second_source}:revision:2"
    cluster = _cluster(probe)
    assert cluster.representative_source_message_id == first_source
    assert cluster.publication_state == "active"
    members = probe.system.exact_repost_cluster_members(cluster.exact_repost_cluster_id)
    deleted_member = next(
        member for member in members if member.source_message_id == second_source
    )
    survivor = next(
        member for member in members if member.source_message_id == first_source
    )
    assert deleted_member.publication_state == "suppressed"
    assert deleted_member.publication_reason == "source_deleted"
    assert survivor.publication_state == "active"
    assert survivor.is_representative
    projected = probe.system.recommendation_opportunities()
    deleted_projection_rows = tuple(
        item
        for item in projected
        if item.opportunity_id == deleted_member.opportunity_id
    )
    survivor_projection_rows = tuple(
        item for item in projected if item.opportunity_id == survivor.opportunity_id
    )
    assert deleted_projection_rows
    assert all(item.response_route.value == "" for item in deleted_projection_rows)
    assert survivor_projection_rows
    assert all(
        item.response_route.value == "@controlled_open_match"
        for item in survivor_projection_rows
    )
    projected_by_opportunity = {item.opportunity_id: item for item in projected}
    assert (
        projected_by_opportunity[survivor.opportunity_id].publication_state == "active"
    )
    assert (
        projected_by_opportunity[deleted_member.opportunity_id].publication_reason
        == "source_deleted"
    )


def test_claimed_recommendation_publication_cannot_reintroduce_deleted_route() -> None:
    probe = _probe()
    source_revision, _ = probe.source_event(
        body=CONTROLLED_LIFECYCLE_BODY,
        operation_number=1,
        telegram_message_id=703,
        source_publisher_id="publisher:one",
        event_time=datetime(2026, 8, 18, 9, 6, tzinfo=UTC),
        process=False,
    )
    assert source_revision is not None
    assert probe.system.process_next_contract_handoff(RuntimeRole.APPLICATION)
    publications = probe.system.opportunity_publication_contracts(source_revision)
    assert len(publications) == 1
    publication_payload = publications[0].payload
    assert isinstance(publication_payload, dict)
    opportunity_id = publication_payload["opportunity_id"]
    opportunity_revision_id = publication_payload["opportunity_revision_id"]
    assert isinstance(opportunity_id, str)
    assert isinstance(opportunity_revision_id, str)
    assert probe.system.process_next_contract_handoff(RuntimeRole.RECOMMENDATION)
    assert any(
        item.opportunity_id == opportunity_id
        and item.response_route.value == "@controlled_open_match"
        for item in probe.system.recommendation_opportunities()
    )
    probe.system.process_opportunities_until_idle()

    database_url = os.environ["TEST_DATABASE_URL"]
    trigger_name = "test_fix59_pause_recommendation_insert"
    function_name = "test_fix59_pause_recommendation_insert"
    advisory_key = 59059
    stale_message_id = derive_contract_message_id(
        publications[0].message_id,
        ContractName.OPPORTUNITY_PUBLICATION_CHANGED,
    )
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL(
                """
                CREATE OR REPLACE FUNCTION {}()
                RETURNS trigger
                LANGUAGE plpgsql
                AS $function$
                BEGIN
                    IF NEW.opportunity_revision_id = {}
                       AND NEW.publication_state = 'active' THEN
                        PERFORM pg_advisory_lock({});
                    END IF;
                    RETURN NEW;
                END
                $function$
                """
            ).format(
                sql.Identifier("football_runtime", function_name),
                sql.Literal(opportunity_revision_id),
                sql.Literal(advisory_key),
            )
        )
        connection.execute(
            sql.SQL(
                """
                CREATE TRIGGER {}
                BEFORE INSERT ON football_runtime.recommendation_opportunities
                FOR EACH ROW
                EXECUTE FUNCTION {}()
                """
            ).format(
                sql.Identifier(trigger_name),
                sql.Identifier("football_runtime", function_name),
            )
        )

    probe.system.record_search_event(
        probe_id="exact-repost-stale-publication",
        contract_name=ContractName.OPPORTUNITY_PUBLICATION_CHANGED,
        contract_version=2,
        telegram_user_id=49_520,
        producer=RuntimeRole.APPLICATION,
        include_telegram_user_id=False,
        subject_id=opportunity_id,
        subject_revision=1,
        idempotency_key=(
            f"opportunity-publication-exact-repost:{opportunity_revision_id}:active:2"
        ),
        message_id=stale_message_id,
        causation_id=publications[0].message_id,
        payload={
            "opportunity_id": opportunity_id,
            "opportunity_revision_id": opportunity_revision_id,
            "source_message_revision_id": source_revision,
            "publication_state": "active",
            "opportunity_type": publication_payload["opportunity_type"],
            "accepted_facts": publication_payload["accepted_facts"],
            "response_route": publication_payload["response_route"],
        },
    )
    stale_envelope = probe.system.recoverable_contract_message(stale_message_id)

    lock_connection = psycopg.connect(database_url)
    worker_errors: list[BaseException] = []
    delete_errors: list[BaseException] = []
    delete_started = Event()
    delete_finished = Event()
    worker_finished = Event()

    def process_claimed_publication() -> None:
        try:
            assert probe.system.process_next_contract_handoff(
                RuntimeRole.RECOMMENDATION
            )
        except BaseException as error:
            worker_errors.append(error)
        finally:
            worker_finished.set()

    def delete_source_message() -> None:
        delete_started.set()
        try:
            deleted_revision, _ = probe.source_event(
                body=None,
                operation_number=2,
                kind=SourceEventKind.DELETE,
                revision=2,
                telegram_message_id=703,
                source_publisher_id="publisher:one",
                event_time=datetime(2026, 8, 18, 9, 7, tzinfo=UTC),
                process=False,
            )
            assert deleted_revision == f"{_source_id(source_revision)}:revision:2"
        except BaseException as error:
            delete_errors.append(error)
        finally:
            delete_finished.set()

    worker = Thread(target=process_claimed_publication)
    deleter: Thread | None = None
    try:
        lock_connection.execute("SELECT pg_advisory_lock(%s)", (advisory_key,))
        worker.start()

        trigger_waiting = False
        activity_snapshot: tuple[object, ...] = ()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with psycopg.connect(database_url) as connection:
                activity_snapshot = tuple(
                    connection.execute(
                        """
                        SELECT usename, state, wait_event_type, wait_event,
                               left(query, 120)
                        FROM pg_stat_activity
                        WHERE datname = current_database()
                          AND pid <> pg_backend_pid()
                        ORDER BY pid
                        """
                    ).fetchall()
                )
                waiting = connection.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_stat_activity
                        WHERE datname = current_database()
                          AND pid <> pg_backend_pid()
                          AND wait_event_type = 'Lock'
                          AND wait_event ILIKE '%advisory%'
                    )
                    """
                ).fetchone()
            if waiting is not None and waiting[0]:
                trigger_waiting = True
                break
            time.sleep(0.01)
        with psycopg.connect(database_url) as connection:
            inbox_snapshot = connection.execute(
                """
                SELECT processing_status
                FROM football_runtime.contract_inbox
                WHERE consumer_role = 'recommendation'
                  AND message_id = %s
                """,
                (stale_envelope.message_id,),
            ).fetchone()
        assert trigger_waiting, (
            worker_errors,
            worker_finished.is_set(),
            activity_snapshot,
            inbox_snapshot,
        )

        deleter = Thread(target=delete_source_message)
        deleter.start()
        assert delete_started.wait(timeout=2)

        deletion_committed = False
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with psycopg.connect(database_url) as connection:
                tombstone = connection.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM football_runtime.application_source_message_tombstones
                        WHERE source_message_id = %s
                    )
                    """,
                    (_source_id(source_revision),),
                ).fetchone()
            if tombstone is not None and tombstone[0]:
                deletion_committed = True
                break
            time.sleep(0.01)
        if deletion_committed:
            probe.system.process_opportunities_until_idle()
            pre_release_rows = tuple(
                item
                for item in probe.system.recommendation_opportunities()
                if item.opportunity_id == opportunity_id
            )
            assert pre_release_rows
            assert all(item.response_route.value == "" for item in pre_release_rows)
    finally:
        lock_connection.execute("SELECT pg_advisory_unlock(%s)", (advisory_key,))
        lock_connection.commit()
        worker.join(timeout=5)
        if deleter is not None:
            deleter.join(timeout=5)
        lock_connection.close()
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL(
                    "DROP TRIGGER IF EXISTS {} ON "
                    "football_runtime.recommendation_opportunities"
                ).format(sql.Identifier(trigger_name))
            )
            connection.execute(
                sql.SQL("DROP FUNCTION IF EXISTS {}()").format(
                    sql.Identifier("football_runtime", function_name)
                )
            )

    assert worker_finished.is_set()
    assert delete_finished.is_set()
    assert not worker_errors, worker_errors
    assert not delete_errors, delete_errors

    probe.system.process_opportunities_until_idle()
    deleted_projection_rows = tuple(
        item
        for item in probe.system.recommendation_opportunities()
        if item.opportunity_id == opportunity_id
    )
    assert deleted_projection_rows
    assert all(
        item.response_route.kind == "unavailable" and item.response_route.value == ""
        for item in deleted_projection_rows
    )


def test_deleting_last_exact_repost_member_scrubs_cluster_and_is_idempotent() -> None:
    probe = _probe()
    _, _, first_source, second_source = _create_pair(probe)
    cluster_before = _cluster(probe)
    cluster_id = cluster_before.exact_repost_cluster_id

    deleted_revision, _ = probe.source_event(
        body=None,
        operation_number=3,
        kind=SourceEventKind.DELETE,
        revision=2,
        telegram_message_id=702,
        source_publisher_id="publisher:one",
        event_time=datetime(2026, 8, 18, 9, 8, tzinfo=UTC),
    )
    assert deleted_revision == f"{second_source}:revision:2"
    survivor_cluster = _cluster(probe)
    assert survivor_cluster.exact_repost_cluster_id == cluster_id
    assert survivor_cluster.source_publisher_id == "publisher:one"
    assert survivor_cluster.normalized_body == CONTROLLED_LIFECYCLE_BODY.casefold()
    assert survivor_cluster.representative_source_message_id == first_source

    deleted_revision, _ = probe.source_event(
        body=None,
        operation_number=4,
        kind=SourceEventKind.DELETE,
        revision=2,
        telegram_message_id=701,
        source_publisher_id="publisher:one",
        event_time=datetime(2026, 8, 18, 9, 9, tzinfo=UTC),
    )
    assert deleted_revision == f"{first_source}:revision:2"
    assert probe.system.exact_repost_clusters() == ()
    assert probe.system.exact_repost_cluster_members(cluster_id) == ()

    assert all(item.body is None for item in probe.system.source_events())
    assert all(
        item.source_publisher_id is None for item in probe.system.source_events()
    )
    assert all(item.body is None for item in probe.system.source_messages())
    assert all(
        item.source_publisher_id is None for item in probe.system.source_messages()
    )
    assert all(
        revision.body is None
        and revision.source_publisher_id is None
        and revision.reply_to_telegram_message_id is None
        for revision in probe.system.source_message_revisions()
    )
    assert all(
        opportunity.response_route.value == ""
        for opportunity in probe.system.opportunities()
    )
    recommendation_rows = probe.system.recommendation_opportunities()
    assert recommendation_rows
    assert all(
        opportunity.response_route.kind == "unavailable"
        and opportunity.response_route.value == ""
        for opportunity in recommendation_rows
    )
    assert {
        tombstone.source_message_id
        for tombstone in probe.system.source_message_deletion_tombstones()
    } == {first_source, second_source}

    deletion_events = tuple(
        event
        for event in probe.system.source_events()
        if event.event_kind is SourceEventKind.DELETE
    )
    assert len(deletion_events) == 2
    before_replay = (
        probe.system.source_messages(),
        probe.system.source_message_revisions(),
        probe.system.source_message_deletion_tombstones(),
        probe.system.opportunities(),
        probe.system.recommendation_opportunities(),
        probe.system.exact_repost_clusters(),
        tuple(
            probe.system.opportunity_publication_contracts(
                f"{event.source_message_id}:revision:{event.revision}"
            )
            for event in deletion_events
        ),
    )
    assert all(
        not probe.system.redeliver_source_event(event.source_event_id)
        for event in deletion_events
    )
    assert (
        probe.system.source_messages(),
        probe.system.source_message_revisions(),
        probe.system.source_message_deletion_tombstones(),
        probe.system.opportunities(),
        probe.system.recommendation_opportunities(),
        probe.system.exact_repost_clusters(),
        tuple(
            probe.system.opportunity_publication_contracts(
                f"{event.source_message_id}:revision:{event.revision}"
            )
            for event in deletion_events
        ),
    ) == before_replay


def test_moderation_applies_to_the_whole_cluster_and_approval_releases_it() -> None:
    probe = _probe()
    _create_pair(probe)
    cluster = _cluster(probe)
    cluster_id = cluster.exact_repost_cluster_id

    assert probe.system.moderate_exact_repost_cluster(
        exact_repost_cluster_id=cluster_id, decision="hold"
    )
    probe.system.process_opportunities_until_idle()
    held = _cluster(probe)
    assert held.moderation_state == "held_for_review"
    assert held.publication_state == "held_for_review"
    assert held.representative_source_message_id is None
    assert all(
        member.publication_state == "held_for_review"
        and member.publication_reason == "moderation_held"
        for member in probe.system.exact_repost_cluster_members(cluster_id)
    )
    assert not probe.system.moderate_exact_repost_cluster(
        exact_repost_cluster_id=cluster_id, decision="hold"
    )

    assert probe.system.moderate_exact_repost_cluster(
        exact_repost_cluster_id=cluster_id, decision="approve"
    )
    probe.system.process_opportunities_until_idle()
    approved = _cluster(probe)
    assert approved.moderation_state == "approved"
    assert approved.publication_state == "active"
    assert approved.representative_source_message_id is not None
    assert (
        sum(
            member.is_representative
            for member in probe.system.exact_repost_cluster_members(cluster_id)
        )
        == 1
    )

    assert probe.system.moderate_exact_repost_cluster(
        exact_repost_cluster_id=cluster_id, decision="suppress"
    )
    probe.system.process_opportunities_until_idle()
    suppressed = _cluster(probe)
    assert suppressed.moderation_state == "suppressed"
    assert suppressed.publication_state == "suppressed"
    assert suppressed.representative_source_message_id is None
    assert all(
        member.publication_state == "suppressed"
        and member.publication_reason == "moderation_suppressed"
        for member in probe.system.exact_repost_cluster_members(cluster_id)
    )


def test_new_exact_repost_cannot_bypass_suppressed_cluster() -> None:
    probe = _probe()
    _create_pair(probe)
    cluster = _cluster(probe)
    assert probe.system.moderate_exact_repost_cluster(
        exact_repost_cluster_id=cluster.exact_repost_cluster_id,
        decision="suppress",
    )
    probe.system.process_opportunities_until_idle()

    probe.clock.advance_to(datetime(2026, 8, 18, 9, 8, tzinfo=UTC))
    third_revision, _ = probe.source_event(
        body=CONTROLLED_LIFECYCLE_BODY,
        operation_number=3,
        telegram_message_id=703,
        source_publisher_id="publisher:one",
        event_time=datetime(2026, 8, 18, 9, 8, tzinfo=UTC),
    )
    assert third_revision is not None
    cluster = _cluster(probe)
    assert cluster.moderation_state == "suppressed"
    assert cluster.publication_state == "suppressed"
    assert cluster.representative_source_message_id is None
    members = probe.system.exact_repost_cluster_members(cluster.exact_repost_cluster_id)
    assert len(members) == 3
    assert all(
        member.publication_state == "suppressed"
        and member.publication_reason == "moderation_suppressed"
        for member in members
    )


def test_source_event_redelivery_is_idempotent_for_cluster_state() -> None:
    probe = _probe()
    _create_pair(probe)
    before = probe.system.exact_repost_clusters(), probe.system.opportunities()
    source_event = next(
        event
        for event in probe.system.source_events()
        if event.telegram_message_id == 702
    )
    assert not probe.system.redeliver_source_event(source_event.source_event_id)
    after = probe.system.exact_repost_clusters(), probe.system.opportunities()
    assert after == before
