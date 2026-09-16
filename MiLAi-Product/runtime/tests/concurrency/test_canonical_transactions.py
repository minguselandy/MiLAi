from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.types.json import Jsonb

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
ACTOR_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
REVIEWER_ACTOR_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _url(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not configured")
    return value


def _context(
    connection: psycopg.Connection[tuple[object, ...]], actor_id: UUID = ACTOR_ID
) -> None:
    connection.execute("SELECT set_config('milai.tenant_id', %s, false)", (str(TENANT_ID),))
    connection.execute("SELECT set_config('milai.actor_id', %s, false)", (str(actor_id),))


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _ingest(label: str) -> UUID:
    api_url = _url("MILAI_TEST_API_DATABASE_URL")
    key = f"canonical-evidence-{label}-{uuid4()}"
    content = label.encode()
    content_hash = hashlib.sha256(content).hexdigest()
    with psycopg.connect(api_url) as connection:
        _context(connection)
        row = connection.execute(
            """
            SELECT milai.tx01_ingest_evidence(
              %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                TENANT_ID,
                ACTOR_ID,
                key,
                _fingerprint(key),
                "RUNTIME_OBSERVATION",
                f"canonical-test://{key}",
                "milai-runtime-python",
                datetime.now(UTC),
                content_hash,
                f"cas://sha256/{TENANT_ID}/{content_hash}",
                len(content),
                "text/plain",
                Jsonb({"readable": True}),
                "READABLE",
            ),
        ).fetchone()
    assert row is not None
    return UUID(str(row[0]["evidence_id"]))


def _scope() -> dict[str, object]:
    return {
        "scope_kind": "CONTEXTUAL",
        "project_ids": ["milai"],
        "task_domains": ["development"],
        "interaction_modes": [],
        "exclusions": [],
    }


def _create_patch(identity: str, value: str = "3.11") -> dict[str, object]:
    return {
        "subject_id": identity,
        "predicate": "runtime.python.version",
        "claim_type": "FACT",
        "payload": {"value": value},
        "authority": "ACTION_SAFE",
        "confidence": 0.95,
        "lifecycle": "ACTIVE",
        "epistemic_status": "VERIFIED",
        "freshness": "CURRENT",
    }


def _create_proposal(
    operation: str,
    patch: dict[str, object],
    supporting: list[UUID],
    *,
    target_claim_id: UUID | None = None,
    expected_version_id: UUID | None = None,
    contradicting: list[UUID] | None = None,
    key: str | None = None,
) -> dict[str, object]:
    api_url = _url("MILAI_TEST_API_DATABASE_URL")
    proposal_key = key or f"proposal-{operation.lower()}-{uuid4()}"
    with psycopg.connect(api_url) as connection:
        _context(connection)
        row = connection.execute(
            """
            SELECT milai.create_operation_proposal(
              %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                TENANT_ID,
                ACTOR_ID,
                proposal_key,
                _fingerprint(proposal_key),
                target_claim_id,
                operation,
                expected_version_id,
                Jsonb(patch),
                supporting,
                contradicting or [],
                Jsonb(_scope()),
                "ACTION_SAFE",
                "canonical-test-policy-v1",
                None,
                "canonical-test-template-v1",
                Jsonb({"fixture": "canonical-transactions"}),
            ),
        ).fetchone()
    assert row is not None
    return row[0]


def _review(
    proposal_id: UUID,
    *,
    decision: str = "APPROVE",
    actor_type: str = "USER",
    key: str | None = None,
) -> dict[str, object]:
    steward_url = _url("MILAI_TEST_STEWARD_DATABASE_URL")
    review_key = key or f"review-{proposal_id}-{uuid4()}"
    with psycopg.connect(steward_url) as connection:
        _context(connection, REVIEWER_ACTOR_ID)
        row = connection.execute(
            """
            SELECT milai.review_operation_proposal(
              %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                TENANT_ID,
                REVIEWER_ACTOR_ID,
                proposal_id,
                decision,
                actor_type,
                "canonical-test-policy-v1",
                "TEST_REVIEW",
                review_key,
                _fingerprint(review_key),
            ),
        ).fetchone()
    assert row is not None
    return row[0]


def _create_claim(identity: str) -> tuple[dict[str, object], UUID]:
    evidence_id = _ingest(f"{identity}-e1")
    proposal = _create_proposal("CREATE", _create_patch(identity), [evidence_id])
    result = _review(UUID(str(proposal["proposal_id"])))
    return result, evidence_id


def _create_conflict() -> tuple[dict[str, object], UUID, UUID]:
    created, _ = _create_claim(f"issue-race-{uuid4()}")
    claim_id = UUID(str(created["claim_id"]))
    head_id = UUID(str(created["claim_version_id"]))
    contradiction = _ingest(f"{claim_id}-contradiction")
    proposal = _create_proposal(
        "CONTRADICT",
        {},
        [],
        target_claim_id=claim_id,
        expected_version_id=head_id,
        contradicting=[contradiction],
    )
    conflict = _review(UUID(str(proposal["proposal_id"])))
    return conflict, claim_id, head_id


@pytest.fixture(scope="module", autouse=True)
def migrate_canonical_schema() -> None:
    command.upgrade(Config("alembic.ini"), "head")


@pytest.mark.integration
def test_tx02_create_is_versioned_grounded_and_idempotent() -> None:
    identity = f"tx02-{uuid4()}"
    evidence_id = _ingest(f"{identity}-e1")
    proposal = _create_proposal("CREATE", _create_patch(identity), [evidence_id])
    review_key = f"review-create-{uuid4()}"
    first = _review(UUID(str(proposal["proposal_id"])), key=review_key)
    replay = _review(UUID(str(proposal["proposal_id"])), key=review_key)
    assert replay["replayed"] is True
    assert replay["claim_version_id"] == first["claim_version_id"]

    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    with psycopg.connect(owner_url) as owner:
        row = owner.execute(
            """
            SELECT cv.version_number, cv.authority, cv.confidence,
                   ch.current_claim_version_id, ecs.effective_status,
                   (SELECT count(*) FROM milai.version_transition vt
                    WHERE vt.claim_id = c.claim_id)
            FROM milai.claim c
            JOIN milai.claim_version cv
              ON cv.tenant_id = c.tenant_id AND cv.claim_id = c.claim_id
            JOIN milai.claim_head ch
              ON ch.tenant_id = c.tenant_id AND ch.claim_id = c.claim_id
            JOIN milai.effective_claim_state ecs
              ON ecs.tenant_id = c.tenant_id AND ecs.claim_id = c.claim_id
            WHERE c.tenant_id = %s AND c.claim_id = %s
            """,
            (TENANT_ID, UUID(str(first["claim_id"]))),
        ).fetchone()
    assert row == (
        1,
        "ACTION_SAFE",
        Decimal("0.9500"),
        UUID(str(first["claim_version_id"])),
        "EFFECTIVE",
        1,
    )


@pytest.mark.integration
def test_tx02_proposal_replay_precedes_dynamic_head_validation() -> None:
    created, _ = _create_claim(f"proposal-replay-{uuid4()}")
    claim_id = UUID(str(created["claim_id"]))
    head_id = UUID(str(created["claim_version_id"]))
    evidence_id = _ingest(f"{claim_id}-proposal-replay")
    key = f"proposal-support-replay-{uuid4()}"
    patch = {"authority": "ACTION_SAFE", "confidence": 0.96}
    proposal = _create_proposal(
        "SUPPORT",
        patch,
        [evidence_id],
        target_claim_id=claim_id,
        expected_version_id=head_id,
        key=key,
    )
    _review(UUID(str(proposal["proposal_id"])))

    replay = _create_proposal(
        "SUPPORT",
        patch,
        [evidence_id],
        target_claim_id=claim_id,
        expected_version_id=head_id,
        key=key,
    )

    assert replay["replayed"] is True
    assert replay["proposal_id"] == proposal["proposal_id"]


def _review_outcome(proposal_id: UUID) -> tuple[str, str]:
    try:
        result = _review(proposal_id)
        return "ok", str(result["claim_version_id"])
    except psycopg.Error as exc:
        return "error", str(exc.diag.message_primary)


@pytest.mark.integration
def test_tx02_absence_cas_allows_only_one_identity() -> None:
    identity = f"absence-{uuid4()}"
    evidence_id = _ingest(f"{identity}-e1")
    first = _create_proposal("CREATE", _create_patch(identity), [evidence_id])
    second = _create_proposal("CREATE", _create_patch(identity), [evidence_id])
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                _review_outcome,
                [UUID(str(first["proposal_id"])), UUID(str(second["proposal_id"]))],
            )
        )
    assert sorted(outcome[0] for outcome in outcomes) == ["error", "ok"]
    assert any(value == "VERSION_CONFLICT" for status, value in outcomes if status == "error")


@pytest.mark.integration
def test_tx03_exact_head_cas_allows_only_one_revision() -> None:
    created, _ = _create_claim(f"revision-{uuid4()}")
    claim_id = UUID(str(created["claim_id"]))
    head_id = UUID(str(created["claim_version_id"]))
    first_evidence = _ingest(f"{claim_id}-revision-a")
    second_evidence = _ingest(f"{claim_id}-revision-b")
    patch = {"payload": {"value": "3.12"}, "authority": "ACTION_SAFE", "confidence": 0.97}
    first = _create_proposal(
        "SUPERSEDE", patch, [first_evidence], target_claim_id=claim_id, expected_version_id=head_id
    )
    second = _create_proposal(
        "SUPERSEDE", patch, [second_evidence], target_claim_id=claim_id, expected_version_id=head_id
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                _review_outcome,
                [UUID(str(first["proposal_id"])), UUID(str(second["proposal_id"]))],
            )
        )
    assert sorted(outcome[0] for outcome in outcomes) == ["error", "ok"]
    assert any(value == "VERSION_CONFLICT" for status, value in outcomes if status == "error")

    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    with psycopg.connect(owner_url) as owner:
        version_count, transition_count = owner.execute(
            """
            SELECT
              (SELECT count(*) FROM milai.claim_version WHERE claim_id = %s),
              (SELECT count(*) FROM milai.version_transition WHERE claim_id = %s)
            """,
            (claim_id, claim_id),
        ).fetchone()
    assert (version_count, transition_count) == (2, 2)


@pytest.mark.integration
def test_tx04_no_change_creates_no_version_or_transition() -> None:
    created, _ = _create_claim(f"no-change-{uuid4()}")
    claim_id = UUID(str(created["claim_id"]))
    head_id = UUID(str(created["claim_version_id"]))
    proposal = _create_proposal(
        "NO_CHANGE", {}, [], target_claim_id=claim_id, expected_version_id=head_id
    )
    result = _review(UUID(str(proposal["proposal_id"])))
    assert result["claim_version_id"] is None
    assert result["open_issue_id"] is None

    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    with psycopg.connect(owner_url) as owner:
        version_count, transition_count, current_head = owner.execute(
            """
            SELECT
              (SELECT count(*) FROM milai.claim_version WHERE claim_id = %s),
              (SELECT count(*) FROM milai.version_transition WHERE claim_id = %s),
              (SELECT current_claim_version_id FROM milai.claim_head WHERE claim_id = %s)
            """,
            (claim_id, claim_id, claim_id),
        ).fetchone()
    assert (version_count, transition_count, current_head) == (1, 1, head_id)


@pytest.mark.integration
def test_tx04_conflict_preserves_head_and_structured_branches() -> None:
    created, supporting_evidence = _create_claim(f"conflict-{uuid4()}")
    claim_id = UUID(str(created["claim_id"]))
    head_id = UUID(str(created["claim_version_id"]))
    contradicting_evidence = _ingest(f"{claim_id}-contradiction")
    proposal = _create_proposal(
        "CONTRADICT",
        {},
        [],
        target_claim_id=claim_id,
        expected_version_id=head_id,
        contradicting=[contradicting_evidence],
    )
    result = _review(UUID(str(proposal["proposal_id"])))
    issue_id = UUID(str(result["open_issue_id"]))

    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    with psycopg.connect(owner_url) as owner:
        head, version_count, issue_status = owner.execute(
            """
            SELECT ch.current_claim_version_id,
                   (SELECT count(*) FROM milai.claim_version WHERE claim_id = %s),
                   oi.status
            FROM milai.claim_head ch
            JOIN milai.open_issue oi
              ON oi.tenant_id = ch.tenant_id AND oi.target_claim_id = ch.claim_id
            WHERE ch.claim_id = %s AND oi.issue_id = %s
            """,
            (claim_id, claim_id, issue_id),
        ).fetchone()
        branches = dict(
            owner.execute(
                """
                SELECT relation_type, count(*)
                FROM milai.grounding_relation
                WHERE open_issue_id = %s
                GROUP BY relation_type
                """,
                (issue_id,),
            ).fetchall()
        )
        ecs_status = owner.execute(
            "SELECT effective_status FROM milai.effective_claim_state WHERE claim_id = %s",
            (claim_id,),
        ).fetchone()[0]
    assert (head, version_count, issue_status) == (head_id, 1, "OPEN")
    assert branches == {"CONTRADICT_BRANCH": 1, "SUPPORT_BRANCH": 1}
    assert supporting_evidence != contradicting_evidence
    assert ecs_status == "CONFLICTED"


def _resolution_candidate_outcome(
    claim_id: UUID, head_id: UUID, issue_id: UUID, evidence_id: UUID
) -> tuple[str, str]:
    patch = {
        "payload": {"value": "3.12"},
        "authority": "ACTION_SAFE",
        "confidence": 0.99,
        "resolve_issue_id": str(issue_id),
        "expected_issue_revision": 1,
        "addressed_branches": ["SUPPORT_BRANCH", "CONTRADICT_BRANCH"],
    }
    try:
        result = _create_proposal(
            "SUPERSEDE",
            patch,
            [evidence_id],
            target_claim_id=claim_id,
            expected_version_id=head_id,
        )
        return "ok", str(result["proposal_id"])
    except psycopg.Error as exc:
        return "error", str(exc.diag.message_primary)


@pytest.mark.integration
def test_resolution_submission_is_noncanonical_and_rejection_preserves_issue() -> None:
    conflict, claim_id, head_id = _create_conflict()
    issue_id = UUID(str(conflict["open_issue_id"]))
    evidence = [_ingest(f"{issue_id}-resolution-{suffix}") for suffix in ("a", "b")]

    outcomes = [
        _resolution_candidate_outcome(claim_id, head_id, issue_id, item) for item in evidence
    ]
    assert [status for status, _ in outcomes] == ["ok", "ok"]
    proposal_id = UUID(outcomes[0][1])

    rejected = _review(proposal_id, decision="REJECT")
    assert rejected["open_issue_id"] == str(issue_id)
    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    with psycopg.connect(owner_url) as owner:
        status, revision = owner.execute(
            "SELECT status, revision FROM milai.open_issue WHERE issue_id = %s",
            (issue_id,),
        ).fetchone()
        transitions = owner.execute(
            """
            SELECT event_type, from_revision, to_revision
            FROM milai.open_issue_transition
            WHERE issue_id = %s ORDER BY to_revision
            """,
            (issue_id,),
        ).fetchall()
    assert (status, revision) == ("OPEN", 1)
    assert transitions == [("ISSUE_CREATED", 0, 1)]


@pytest.mark.integration
def test_resolution_review_revision_cas_allows_one_atomic_winner() -> None:
    conflict, claim_id, head_id = _create_conflict()
    issue_id = UUID(str(conflict["open_issue_id"]))
    proposals = []
    for suffix in ("a", "b"):
        evidence_id = _ingest(f"{issue_id}-review-race-{suffix}")
        status, value = _resolution_candidate_outcome(claim_id, head_id, issue_id, evidence_id)
        assert status == "ok"
        proposals.append(UUID(value))

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(_review_outcome, proposals))
    assert sorted(status for status, _ in outcomes) == ["error", "ok"]
    assert any(
        value in {"ISSUE_REVISION_CONFLICT", "VERSION_CONFLICT"}
        for status, value in outcomes
        if status == "error"
    )

    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    with psycopg.connect(owner_url) as owner:
        status, revision, transition_types, decision_count, outbox_count = owner.execute(
            """
            SELECT issue.status, issue.revision,
                   ARRAY(
                     SELECT transition.event_type
                     FROM milai.open_issue_transition transition
                     WHERE transition.issue_id = issue.issue_id
                     ORDER BY transition.to_revision
                   ),
                   (SELECT count(*) FROM milai.steward_decision decision
                    JOIN milai.operation_proposal proposal
                      ON proposal.tenant_id = decision.tenant_id
                     AND proposal.proposal_id = decision.proposal_id
                    WHERE decision.resulting_open_issue_id = issue.issue_id
                      AND decision.decision = 'APPROVE'
                      AND proposal.operation = 'SUPERSEDE'),
                   (SELECT count(*) FROM milai.outbox_event event
                    WHERE event.aggregate_id = issue.issue_id
                      AND event.event_type = 'OPEN_ISSUE_CHANGED'
                      AND event.payload ->> 'operation' = 'SUPERSEDE')
            FROM milai.open_issue issue WHERE issue.issue_id = %s
            """,
            (issue_id,),
        ).fetchone()
    assert (status, revision) == ("RESOLVED", 2)
    assert transition_types == ["ISSUE_CREATED", "DISCHARGE_APPROVED"]
    assert (decision_count, outbox_count) == (1, 1)


@pytest.mark.integration
def test_claim_version_axes_accept_normative_values_and_map_legacy_values() -> None:
    valid_axes = (
        ("lifecycle", ["ACTIVE", "SUPERSEDED", "ARCHIVED", "DELETED"]),
        (
            "epistemic_status",
            ["PROVISIONAL", "VERIFIED", "CHALLENGED", "UNPROVABLE"],
        ),
        ("freshness", ["CURRENT", "STALE"]),
    )
    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    for axis, values in valid_axes:
        for value in values:
            identity = f"axis-{axis}-{value}-{uuid4()}"
            evidence_id = _ingest(identity)
            patch = _create_patch(identity)
            patch[axis] = value
            proposal = _create_proposal("CREATE", patch, [evidence_id])
            result = _review(UUID(str(proposal["proposal_id"])))
            with psycopg.connect(owner_url) as owner:
                stored = owner.execute(
                    f"SELECT {axis} FROM milai.claim_version "  # noqa: S608 - fixed axis list
                    "WHERE claim_version_id = %s",
                    (UUID(str(result["claim_version_id"])),),
                ).fetchone()[0]
            assert stored == value

    legacy_mapping = {
        "SUPPORTED": "VERIFIED",
        "WEAKENED": "CHALLENGED",
        "UNCERTAIN": "PROVISIONAL",
    }
    for legacy, normative in legacy_mapping.items():
        identity = f"legacy-axis-{legacy}-{uuid4()}"
        evidence_id = _ingest(identity)
        patch = _create_patch(identity)
        patch["epistemic_status"] = legacy
        proposal = _create_proposal("CREATE", patch, [evidence_id])
        result = _review(UUID(str(proposal["proposal_id"])))
        with psycopg.connect(owner_url) as owner:
            stored = owner.execute(
                "SELECT epistemic_status FROM milai.claim_version WHERE claim_version_id = %s",
                (UUID(str(result["claim_version_id"])),),
            ).fetchone()[0]
        assert stored == normative


@pytest.mark.integration
def test_claim_version_axes_reject_unknown_values_atomically() -> None:
    for axis in ("lifecycle", "epistemic_status", "freshness"):
        identity = f"invalid-axis-{axis}-{uuid4()}"
        evidence_id = _ingest(identity)
        patch = _create_patch(identity)
        patch[axis] = "NOT_A_STATE"
        proposal = _create_proposal("CREATE", patch, [evidence_id])
        with pytest.raises(psycopg.errors.CheckViolation):
            _review(UUID(str(proposal["proposal_id"])))

        owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
        with psycopg.connect(owner_url) as owner:
            claim_count, decision_count = owner.execute(
                """
                SELECT
                  (SELECT count(*) FROM milai.claim WHERE subject_id = %s),
                  (SELECT count(*) FROM milai.steward_decision
                   WHERE proposal_id = %s)
                """,
                (identity, UUID(str(proposal["proposal_id"]))),
            ).fetchone()
        assert (claim_count, decision_count) == (0, 0)


@pytest.mark.integration
def test_split_and_policy_approval_fail_closed() -> None:
    evidence_id = _ingest(f"split-{uuid4()}")
    api_url = _url("MILAI_TEST_API_DATABASE_URL")
    with psycopg.connect(api_url) as connection:
        _context(connection)
        with pytest.raises(psycopg.errors.RaiseException, match="OPERATION_NOT_ENABLED"):
            connection.execute(
                """
                SELECT milai.create_operation_proposal(
                  %s, %s, %s, %s, NULL, 'SPLIT', NULL, %s,
                  %s, %s, %s, 'ACTION_SAFE', %s, NULL, NULL, %s
                )
                """,
                (
                    TENANT_ID,
                    ACTOR_ID,
                    f"split-{uuid4()}",
                    _fingerprint("split"),
                    Jsonb({}),
                    [evidence_id],
                    [],
                    Jsonb(_scope()),
                    "test-policy",
                    Jsonb({}),
                ),
            )

    created, _ = _create_claim(f"policy-denied-{uuid4()}")
    proposal = _create_proposal(
        "NO_CHANGE",
        {},
        [],
        target_claim_id=UUID(str(created["claim_id"])),
        expected_version_id=UUID(str(created["claim_version_id"])),
    )
    with pytest.raises(psycopg.errors.RaiseException, match="AUTHORITY_INSUFFICIENT"):
        _review(UUID(str(proposal["proposal_id"])), actor_type="POLICY")


@pytest.mark.integration
def test_reject_changes_no_claim_state() -> None:
    identity = f"reject-{uuid4()}"
    evidence_id = _ingest(f"{identity}-e1")
    proposal = _create_proposal("CREATE", _create_patch(identity), [evidence_id])
    result = _review(UUID(str(proposal["proposal_id"])), decision="REJECT")
    assert result["decision"] == "REJECT"

    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    with psycopg.connect(owner_url) as owner:
        claim_count, proposal_status = owner.execute(
            """
            SELECT
              (SELECT count(*) FROM milai.claim WHERE subject_id = %s),
              (SELECT status FROM milai.operation_proposal WHERE proposal_id = %s)
            """,
            (identity, UUID(str(proposal["proposal_id"]))),
        ).fetchone()
    assert (claim_count, proposal_status) == (0, "REJECTED")


@pytest.mark.integration
def test_tx06_reground_requires_block_and_creates_new_version() -> None:
    created, original_evidence = _create_claim(f"reground-{uuid4()}")
    claim_id = UUID(str(created["claim_id"]))
    head_id = UUID(str(created["claim_version_id"]))
    replacement_evidence = _ingest(f"{claim_id}-replacement")
    patch = {"authority": "ACTION_SAFE", "confidence": 0.99}

    no_block = _create_proposal(
        "REGROUND",
        patch,
        [replacement_evidence],
        target_claim_id=claim_id,
        expected_version_id=head_id,
    )
    with pytest.raises(psycopg.errors.RaiseException, match="GROUNDING_BLOCKED"):
        _review(UUID(str(no_block["proposal_id"])))

    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    with psycopg.connect(owner_url) as owner:
        block_id = uuid4()
        owner.execute(
            """
            INSERT INTO milai.grounding_block (
              tenant_id, block_id, claim_version_id, caused_by_evidence_id,
              block_type, active, created_by_actor_id
            ) VALUES (%s, %s, %s, %s, 'EVIDENCE_REVOKED', true, %s)
            """,
            (TENANT_ID, block_id, head_id, original_evidence, ACTOR_ID),
        )

    proposal = _create_proposal(
        "REGROUND",
        patch,
        [replacement_evidence],
        target_claim_id=claim_id,
        expected_version_id=head_id,
    )
    result = _review(UUID(str(proposal["proposal_id"])))
    new_version_id = UUID(str(result["claim_version_id"]))
    assert new_version_id != head_id

    with psycopg.connect(owner_url) as owner:
        active, restored_version, restored_decision = owner.execute(
            """
            SELECT active, restored_by_claim_version_id, restored_by_decision_id
            FROM milai.grounding_block WHERE block_id = %s
            """,
            (block_id,),
        ).fetchone()
    assert active is False
    assert restored_version == new_version_id
    assert restored_decision == UUID(str(result["decision_id"]))


@pytest.mark.integration
@pytest.mark.security
def test_canonical_tables_deny_direct_dml_and_history_is_immutable() -> None:
    created, _ = _create_claim(f"permissions-{uuid4()}")
    claim_id = UUID(str(created["claim_id"]))
    version_id = UUID(str(created["claim_version_id"]))
    for role_variable in (
        "MILAI_TEST_API_DATABASE_URL",
        "MILAI_TEST_STEWARD_DATABASE_URL",
        "MILAI_TEST_WORKER_DATABASE_URL",
        "MILAI_TEST_AUDIT_DATABASE_URL",
    ):
        with psycopg.connect(_url(role_variable)) as connection:
            _context(connection)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    "UPDATE milai.claim_head SET current_claim_version_id = %s WHERE claim_id = %s",
                    (version_id, claim_id),
                )

    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    with psycopg.connect(owner_url) as owner:
        with pytest.raises(psycopg.errors.RaiseException, match="APPEND_ONLY_VIOLATION"):
            owner.execute(
                "UPDATE milai.claim_version SET confidence = 0 WHERE claim_version_id = %s",
                (version_id,),
            )

    conflict, _, _ = _create_conflict()
    issue_id = UUID(str(conflict["open_issue_id"]))
    immutable_updates = (
        (
            "UPDATE milai.version_transition SET transition_type = transition_type "
            "WHERE claim_id = %s",
            claim_id,
        ),
        (
            "UPDATE milai.steward_decision SET reason_code = reason_code "
            "WHERE resulting_claim_version_id = %s",
            version_id,
        ),
        (
            "UPDATE milai.open_issue_transition SET event_type = event_type WHERE issue_id = %s",
            issue_id,
        ),
    )
    for statement, identifier in immutable_updates:
        with psycopg.connect(owner_url) as owner:
            with pytest.raises(psycopg.errors.RaiseException, match="APPEND_ONLY_VIOLATION"):
                owner.execute(statement, (identifier,))


@pytest.mark.integration
@pytest.mark.security
def test_i01_evidence_cannot_be_collapsed_directly_into_claim_version() -> None:
    evidence_id = _ingest(f"evidence-claim-collapse-{uuid4()}")
    with psycopg.connect(_url("MILAI_TEST_API_DATABASE_URL")) as connection:
        _context(connection)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """
                INSERT INTO milai.claim_version (
                  tenant_id, claim_version_id, claim_id, version_number,
                  payload, scope_predicate, lifecycle, epistemic_status,
                  freshness, authority, confidence, derivation_policy_id,
                  steward_decision_id, canonical_commit_seq, created_by_actor_id
                )
                SELECT evidence.tenant_id, gen_random_uuid(), gen_random_uuid(), 1,
                       jsonb_build_object('evidence_id', evidence.evidence_id),
                       '{}'::jsonb, 'ACTIVE', 'VERIFIED', 'CURRENT',
                       'INFORMATIONAL', 1, 'forbidden-collapse', gen_random_uuid(),
                       1, %s
                FROM milai.evidence_record evidence
                WHERE evidence.tenant_id = %s AND evidence.evidence_id = %s
                """,
                (ACTOR_ID, TENANT_ID, evidence_id),
            )


@pytest.mark.integration
@pytest.mark.security
def test_tx05_is_steward_only_and_runtime_roles_cannot_bypass_revocation() -> None:
    evidence_id = _ingest(f"tx05-permissions-{uuid4()}")
    for role_variable in (
        "MILAI_TEST_API_DATABASE_URL",
        "MILAI_TEST_WORKER_DATABASE_URL",
        "MILAI_TEST_AUDIT_DATABASE_URL",
    ):
        with psycopg.connect(_url(role_variable)) as connection:
            _context(connection)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    """
                    SELECT milai.tx05_revoke_evidence(
                      %s, %s, %s, 'USER_REQUEST', 'REVOKE', %s, %s
                    )
                    """,
                    (
                        TENANT_ID,
                        ACTOR_ID,
                        evidence_id,
                        f"forbidden-{uuid4()}",
                        _fingerprint("forbidden-tx05"),
                    ),
                )

    for role_variable in (
        "MILAI_TEST_API_DATABASE_URL",
        "MILAI_TEST_STEWARD_DATABASE_URL",
        "MILAI_TEST_WORKER_DATABASE_URL",
        "MILAI_TEST_AUDIT_DATABASE_URL",
    ):
        with psycopg.connect(_url(role_variable)) as connection:
            _context(connection)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    """
                    UPDATE milai.evidence_record
                    SET revoked_at = CURRENT_TIMESTAMP,
                        revocation_reason = 'BYPASS_ATTEMPT'
                    WHERE evidence_id = %s
                    """,
                    (evidence_id,),
                )

    key = f"governed-revoke-{uuid4()}"
    with psycopg.connect(_url("MILAI_TEST_STEWARD_DATABASE_URL")) as steward:
        _context(steward)
        result = steward.execute(
            """
            SELECT milai.tx05_revoke_evidence(
              %s, %s, %s, 'USER_REQUEST', 'REVOKE', %s, %s
            )
            """,
            (TENANT_ID, ACTOR_ID, evidence_id, key, _fingerprint(key)),
        ).fetchone()[0]
    proposal_id = UUID(str(result["proposal_id"]))
    decision_id = UUID(str(result["decision_id"]))
    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        operation, proposal_status, decision, resulting_evidence, decision_seq = owner.execute(
            """
            SELECT proposal.operation, proposal.status, decision.decision,
                   decision.resulting_evidence_id, decision.canonical_commit_seq
            FROM milai.operation_proposal proposal
            JOIN milai.steward_decision decision
              ON decision.tenant_id = proposal.tenant_id
             AND decision.proposal_id = proposal.proposal_id
            WHERE proposal.proposal_id = %s AND decision.decision_id = %s
            """,
            (proposal_id, decision_id),
        ).fetchone()
        linked_outboxes = owner.execute(
            """
            SELECT count(*) FROM milai.outbox_event
            WHERE canonical_commit_seq = %s
              AND payload ->> 'proposal_id' = %s
              AND payload ->> 'decision_id' = %s
              AND event_type IN ('EVIDENCE_REVOKED', 'PURGE_EVIDENCE_DERIVATIVES')
            """,
            (decision_seq, str(proposal_id), str(decision_id)),
        ).fetchone()[0]
        linked_operational = owner.execute(
            """
            SELECT count(*) FROM milai.operational_event
            WHERE event_type = 'EVIDENCE_REVOKED'
              AND safe_metadata ->> 'proposal_id' = %s
              AND safe_metadata ->> 'decision_id' = %s
            """,
            (str(proposal_id), str(decision_id)),
        ).fetchone()[0]
    assert (operation, proposal_status, decision, resulting_evidence) == (
        "REVOKE_EVIDENCE",
        "APPLIED",
        "APPROVE",
        evidence_id,
    )
    assert (linked_outboxes, linked_operational) == (2, 1)


@pytest.mark.integration
def test_tx05_failure_rolls_back_mutation_decision_event_and_outbox() -> None:
    evidence_id = _ingest(f"tx05-rollback-{uuid4()}")
    key = f"tx05-rollback-{uuid4()}"
    with pytest.raises(RuntimeError, match="force rollback"):
        with psycopg.connect(_url("MILAI_TEST_STEWARD_DATABASE_URL")) as steward:
            _context(steward)
            result = steward.execute(
                """
                SELECT milai.tx05_revoke_evidence(
                  %s, %s, %s, 'USER_REQUEST', 'REVOKE', %s, %s
                )
                """,
                (TENANT_ID, ACTOR_ID, evidence_id, key, _fingerprint(key)),
            ).fetchone()[0]
            assert result["decision_id"] is not None
            raise RuntimeError("force rollback")

    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        values = owner.execute(
            """
            SELECT evidence.revoked_at,
                   (SELECT count(*) FROM milai.deletion_request deletion
                    WHERE deletion.evidence_id = evidence.evidence_id),
                   (SELECT count(*) FROM milai.operation_proposal proposal
                    WHERE proposal.operation = 'REVOKE_EVIDENCE'
                      AND proposal.proposed_patch ->> 'evidence_id' = evidence.evidence_id::text),
                   (SELECT count(*) FROM milai.steward_decision decision
                    WHERE decision.resulting_evidence_id = evidence.evidence_id),
                   (SELECT count(*) FROM milai.outbox_event event
                    WHERE event.aggregate_id = evidence.evidence_id
                      AND event.event_type = 'EVIDENCE_REVOKED'),
                   (SELECT count(*) FROM milai.operational_event event
                    WHERE event.event_type = 'EVIDENCE_REVOKED'
                      AND event.safe_metadata ->> 'evidence_id' = evidence.evidence_id::text)
            FROM milai.evidence_record evidence
            WHERE evidence.evidence_id = %s
            """,
            (evidence_id,),
        ).fetchone()
    assert values == (None, 0, 0, 0, 0, 0)
