from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.types.json import Jsonb

from milai.api import create_app
from milai.application.formation_evolution_bridge import (
    EvolutionCurrentClaimV01,
    map_state_artifact_to_proposal,
)
from milai.application.state_change_formation import build_state_change_sidecar
from milai.config.settings import RuntimeSettings, prepare_runtime_directories
from milai.persistence import Database

pytestmark = pytest.mark.integration

TENANT_ID = "11111111-1111-4111-8111-111111111111"
ACTOR_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
API_TOKEN = "test-token-with-at-least-32-characters"
SUBMITTER_TOKEN = "submitter-token-with-at-least-32-characters"
REVIEWER_TOKEN = "reviewer-token-with-at-least-32-characters"


def _url(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture
def canonical_app(tmp_path: Path):  # type: ignore[no-untyped-def]
    command.upgrade(Config("alembic.ini"), "head")
    settings = RuntimeSettings(
        database_url=_url("MILAI_TEST_API_DATABASE_URL"),
        steward_database_url=_url("MILAI_TEST_STEWARD_DATABASE_URL"),
        blob_root=tmp_path / "blobs",
        tenant_id=TENANT_ID,
        local_actor_id=ACTOR_ID,
        api_token=API_TOKEN,
        causal_token_secret="test-causal-secret-with-at-least-32-characters",
        agent_submitter_token=SUBMITTER_TOKEN,
        agent_reviewer_token=REVIEWER_TOKEN,
    )
    prepare_runtime_directories(settings)
    database = Database(settings)
    steward_database = Database(settings, dsn=settings.steward_database_dsn)
    app = create_app(settings, database=database, steward_database=steward_database)
    app.config["TESTING"] = True
    yield app
    database.close()
    steward_database.close()


def _headers(key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _profile_headers(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


@pytest.mark.integration
def test_formation_evolution_bridge_replays_update_revoke_and_reground(
    canonical_app,
) -> None:  # type: ignore[no-untyped-def]
    client = canonical_app.test_client()

    def capture(content: str) -> tuple[UUID, str]:
        source_ref = f"formation-bridge://{uuid4()}"
        response = client.post(
            "/v1/evidence",
            headers=_profile_headers(SUBMITTER_TOKEN, f"bridge-evidence-{uuid4()}"),
            json={
                "source_type": "RUNTIME_OBSERVATION",
                "source_ref": source_ref,
                "subject_id": "subject:self",
                "observed_at": "2026-08-16T11:00:00+08:00",
                "content": content,
                "permission_snapshot": {"readable": True},
                "retention_state": "READABLE",
            },
        )
        assert response.status_code == 201
        return UUID(response.json["evidence_id"]), source_ref

    initial_evidence, _initial_ref = capture("I live in Shanghai.")
    initial = client.post(
        "/v1/proposals",
        headers=_profile_headers(SUBMITTER_TOKEN, f"bridge-initial-{uuid4()}"),
        json={
            "operation": "CREATE",
            "proposed_patch": {
                "subject_id": "subject:self",
                "predicate": "residence",
                "claim_type": "STATE",
                "payload": {"location": "Shanghai"},
                "authority": "INFORMATIONAL",
                "confidence": 0.9,
            },
            "supporting_evidence_refs": [str(initial_evidence)],
            "scope_predicate": {"project_ids": ["milai"]},
            "requested_authority": "INFORMATIONAL",
            "derivation_policy_id": "formation-bridge-integration-v0.1",
            "derivation_snapshot": {"fixture": "initial-state"},
        },
    )
    assert initial.status_code == 201
    initial_review = client.post(
        f"/v1/proposals/{initial.json['proposal_id']}/review",
        headers=_profile_headers(REVIEWER_TOKEN, f"bridge-initial-review-{uuid4()}"),
        json={
            "decision": "APPROVE",
            "policy_version": "formation-bridge-integration-v0.1",
            "reason_code": "SYNTHETIC_GROUNDED_STATE",
        },
    )
    assert initial_review.status_code == 200
    claim_id = UUID(initial_review.json["claim_id"])

    def current() -> EvolutionCurrentClaimV01:
        response = client.get(f"/v1/claims/{claim_id}", headers=_headers())
        assert response.status_code == 200
        return EvolutionCurrentClaimV01(
            claim_id=claim_id,
            claim_version_id=UUID(response.json["claim_version_id"]),
            subject_id=str(response.json["subject_id"]),
            predicate=str(response.json["predicate"]),
            payload=response.json["payload"],
            effective_status=str(response.json["effective_status"]),
        )

    def apply_formed(content: str) -> tuple[UUID, dict[str, object]]:
        evidence_id, source_ref = capture(content)
        sidecar = build_state_change_sidecar(
            [
                {
                    "evidence_id": str(evidence_id),
                    "source_ref": source_ref,
                    "content": content,
                    "observed_at": "2026-08-16T11:00:00+08:00",
                }
            ]
        )
        assert len(sidecar.assertions) == len(sidecar.transitions) == 1
        request = map_state_artifact_to_proposal(
            sidecar.assertions[0],
            transition=sidecar.transitions[0],
            current_claim=current(),
            governed_evidence_ref=evidence_id,
            scope_predicate={"project_ids": ["milai"]},
        )
        assert request is not None
        proposal = client.post(
            "/v1/proposals",
            headers=_profile_headers(SUBMITTER_TOKEN, f"bridge-proposal-{uuid4()}"),
            json=request.model_dump(mode="json", exclude_none=True),
        )
        assert proposal.status_code == 201
        assert proposal.json["commit_policy_decision"] == "USER_REVIEW"
        review = client.post(
            f"/v1/proposals/{proposal.json['proposal_id']}/review",
            headers=_profile_headers(REVIEWER_TOKEN, f"bridge-review-{uuid4()}"),
            json={
                "decision": "APPROVE",
                "policy_version": "formation-bridge-integration-v0.1",
                "reason_code": "FORMATION_ARTIFACT_REPLAY_VERIFIED",
            },
        )
        assert review.status_code == 200
        return evidence_id, review.json

    _move_evidence, move = apply_formed(
        "On August 12, 2026, I moved from Shanghai to Hangzhou for my new job."
    )
    assert move["claim_id"] == str(claim_id)
    assert current().payload == {"location": "Hangzhou"}

    correction_evidence, correction = apply_formed(
        "Correction: I did not move to Hangzhou; I still live in Shanghai."
    )
    assert correction["claim_version_id"] != move["claim_version_id"]
    assert current().payload == {"location": "Shanghai"}

    revoked = client.post(
        f"/v1/evidence/{correction_evidence}/revoke",
        headers=_headers(f"bridge-revoke-{uuid4()}"),
        json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
    )
    assert revoked.status_code == 202
    assert current().effective_status == "BLOCKED"

    _replacement_evidence, restored = apply_formed(
        "Correction: I did not move to Hangzhou; I still live in Shanghai. "
        "I reconfirmed this today."
    )
    assert restored["claim_version_id"] != correction["claim_version_id"]
    assert current().effective_status == "EFFECTIVE"
    versions = client.get(
        f"/v1/claims/{claim_id}/versions",
        headers=_headers(),
    )
    assert versions.status_code == 200
    assert [item["payload"] for item in versions.json["versions"]] == [
        {"location": "Shanghai"},
        {"location": "Hangzhou"},
        {"location": "Shanghai"},
        {"location": "Shanghai"},
    ]


@pytest.mark.integration
def test_named_submitter_and_reviewer_use_distinct_actors_and_capabilities(
    canonical_app,
) -> None:  # type: ignore[no-untyped-def]
    client = canonical_app.test_client()
    evidence = client.post(
        "/v1/evidence",
        headers=_profile_headers(SUBMITTER_TOKEN, f"profile-evidence-{uuid4()}"),
        json={
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": f"profile-test://{uuid4()}",
            "subject_id": "profile-separated-review",
            "observed_at": "2026-08-26T00:00:00+08:00",
            "content": "synthetic independently reviewed fact",
            "permission_snapshot": {"readable": True},
            "retention_state": "READABLE",
        },
    )
    assert evidence.status_code == 201
    proposal = client.post(
        "/v1/proposals",
        headers=_profile_headers(SUBMITTER_TOKEN, f"profile-proposal-{uuid4()}"),
        json={
            "operation": "CREATE",
            "proposed_patch": {
                "subject_id": f"profile-separated-{uuid4()}",
                "predicate": "has_review_state",
                "claim_type": "FACT",
                "payload": {"value": "independent"},
                "authority": "INFORMATIONAL",
                "confidence": 0.99,
            },
            "supporting_evidence_refs": [evidence.json["evidence_id"]],
            "scope_predicate": {"project_ids": ["milai"]},
            "requested_authority": "INFORMATIONAL",
            "derivation_policy_id": "profile-separation-v1",
            "derivation_snapshot": {"fixture": "profile-separation"},
        },
    )
    assert proposal.status_code == 201

    self_review = client.post(
        f"/v1/proposals/{proposal.json['proposal_id']}/review",
        headers=_profile_headers(SUBMITTER_TOKEN, f"profile-self-review-{uuid4()}"),
        json={
            "decision": "APPROVE",
            "policy_version": "profile-separation-v1",
            "reason_code": "MUST_NOT_RUN",
        },
    )
    reviewer_capture = client.post(
        "/v1/evidence",
        headers=_profile_headers(REVIEWER_TOKEN, f"profile-reviewer-capture-{uuid4()}"),
        json={},
    )
    assert self_review.status_code == 403
    assert reviewer_capture.status_code == 403

    review = client.post(
        f"/v1/proposals/{proposal.json['proposal_id']}/review",
        headers=_profile_headers(REVIEWER_TOKEN, f"profile-review-{uuid4()}"),
        json={
            "decision": "APPROVE",
            "policy_version": "profile-separation-v1",
            "reason_code": "SYNTHETIC_FIXTURE_VERIFIED",
        },
    )
    assert review.status_code == 200
    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        actors = owner.execute(
            """
            SELECT proposal.proposer_actor_id, decision.decision_actor_id
            FROM milai.operation_proposal proposal
            JOIN milai.steward_decision decision
              ON decision.tenant_id = proposal.tenant_id
             AND decision.proposal_id = proposal.proposal_id
            WHERE proposal.tenant_id = %s AND proposal.proposal_id = %s
            """,
            (TENANT_ID, proposal.json["proposal_id"]),
        ).fetchone()
    assert actors is not None
    assert actors[0] != actors[1]


@pytest.mark.integration
def test_canonical_procedure_rejects_legacy_same_actor_review(canonical_app) -> None:  # type: ignore[no-untyped-def]
    client = canonical_app.test_client()
    signature = "uuid,uuid,uuid,text,text,text,text,text,text"
    with psycopg.connect(_url("MILAI_TEST_STEWARD_DATABASE_URL")) as steward:
        privileges = steward.execute(
            """
            SELECT has_function_privilege(
                     current_user,
                     'milai.review_operation_proposal(' || %s || ')',
                     'EXECUTE'
                   ),
                   has_function_privilege(
                     current_user,
                     'milai.review_operation_proposal_without_actor_separation('
                       || %s || ')',
                     'EXECUTE'
                   )
            """,
            (signature, signature),
        ).fetchone()
    assert privileges == (True, False)

    evidence_id = _ingest(client, "grounding for canonical self-review rejection")
    proposal = client.post(
        "/v1/proposals",
        headers=_headers(f"self-review-proposal-{uuid4()}"),
        json={
            "operation": "CREATE",
            "proposed_patch": {
                "subject_id": f"self-review-{uuid4()}",
                "predicate": "has_review_state",
                "claim_type": "FACT",
                "payload": {"value": "must remain pending"},
                "authority": "INFORMATIONAL",
                "confidence": 0.99,
            },
            "supporting_evidence_refs": [evidence_id],
            "scope_predicate": {"project_ids": ["milai"]},
            "requested_authority": "INFORMATIONAL",
            "derivation_policy_id": "self-review-separation-v1",
            "derivation_snapshot": {"fixture": "self-review-separation"},
        },
    )
    assert proposal.status_code == 201

    forbidden = client.post(
        f"/v1/proposals/{proposal.json['proposal_id']}/review",
        headers=_headers(f"self-review-decision-{uuid4()}"),
        json={
            "decision": "APPROVE",
            "policy_version": "self-review-separation-v1",
            "reason_code": "MUST_NOT_RUN",
        },
    )
    assert forbidden.status_code == 403
    assert forbidden.json["error"]["code"] == "SELF_REVIEW_FORBIDDEN"

    with psycopg.connect(_url("MILAI_MIGRATION_DATABASE_URL")) as owner:
        state = owner.execute(
            """
            SELECT proposal.status,
                   (SELECT count(*) FROM milai.steward_decision decision
                    WHERE decision.tenant_id = proposal.tenant_id
                      AND decision.proposal_id = proposal.proposal_id)
            FROM milai.operation_proposal proposal
            WHERE proposal.tenant_id = %s AND proposal.proposal_id = %s
            """,
            (TENANT_ID, proposal.json["proposal_id"]),
        ).fetchone()
    assert state == ("PENDING_REVIEW", 0)

    independent = client.post(
        f"/v1/proposals/{proposal.json['proposal_id']}/review",
        headers=_profile_headers(REVIEWER_TOKEN, f"independent-review-{uuid4()}"),
        json={
            "decision": "APPROVE",
            "policy_version": "self-review-separation-v1",
            "reason_code": "SYNTHETIC_FIXTURE_VERIFIED",
        },
    )
    assert independent.status_code == 200


def _ingest(  # type: ignore[no-untyped-def]
    client, content: str, retention_state: str = "READABLE"
) -> str:
    response = client.post(
        "/v1/evidence",
        headers=_headers(f"evidence-{uuid4()}"),
        json={
            "source_type": "RUNTIME_OBSERVATION",
            "source_ref": f"integration://{uuid4()}",
            "subject_id": "milai-runtime-python",
            "observed_at": "2026-08-15T10:00:00+08:00",
            "content": content,
            "media_type": "text/plain",
            "permission_snapshot": {"readable": True, "scope": "local"},
            "retention_state": retention_state,
        },
    )
    assert response.status_code == 201
    return response.json["evidence_id"]


def _create_claim(client, evidence_id: str) -> dict[str, object]:  # type: ignore[no-untyped-def]
    key = f"proposal-create-{uuid4()}"
    payload = {
        "operation": "CREATE",
        "proposed_patch": {
            "subject_id": f"milai-runtime-python-{uuid4()}",
            "predicate": "uses_version",
            "claim_type": "RUNTIME_VERSION",
            "payload": {"python": "3.11"},
            "authority": "ACTION_SAFE",
            "confidence": 0.95,
        },
        "supporting_evidence_refs": [evidence_id],
        "scope_predicate": {"project_ids": ["milai"]},
        "requested_authority": "ACTION_SAFE",
        "derivation_policy_id": "integration-v1",
        "derivation_snapshot": {"source": "integration-test"},
    }
    created = client.post("/v1/proposals", json=payload, headers=_headers(key))
    assert created.status_code == 201
    replay = client.post("/v1/proposals", json=payload, headers=_headers(key))
    assert replay.status_code == 200
    assert replay.json["proposal_id"] == created.json["proposal_id"]
    assert replay.json["replayed"] is True

    reviewed = client.post(
        f"/v1/proposals/{created.json['proposal_id']}/review",
        headers=_profile_headers(REVIEWER_TOKEN, f"review-{uuid4()}"),
        json={
            "decision": "APPROVE",
            "policy_version": "human-review-v1",
            "reason_code": "SYNTHETIC_FIXTURE_VERIFIED",
        },
    )
    assert reviewed.status_code == 200
    assert reviewed.json["decision"] == "APPROVE"
    return reviewed.json


def _exact_query(client, claim_id: object):  # type: ignore[no-untyped-def]
    return client.post(
        "/v1/memory/query",
        headers=_headers(),
        json={
            "route": "L0",
            "claim_id": claim_id,
            "consistency": "CANONICAL_REQUIRED",
            "requested_scope": {"project_ids": ["milai"]},
            "required_authority": "ACTION_SAFE",
        },
    )


@pytest.mark.integration
def test_proposal_review_claim_conflict_and_lineage_api(canonical_app) -> None:  # type: ignore[no-untyped-def]
    client = canonical_app.test_client()
    support_evidence = _ingest(client, "deployment reports Python 3.11")
    created = _create_claim(client, support_evidence)
    claim_id = created["claim_id"]
    version_id = created["claim_version_id"]

    claim = client.get(f"/v1/claims/{claim_id}", headers=_headers())
    assert claim.status_code == 200
    assert claim.json["claim_version_id"] == version_id
    assert claim.json["effective_status"] == "EFFECTIVE"
    e1_query = _exact_query(client, claim_id)
    assert e1_query.json["results"][0]["claim_version_id"] == version_id
    e1_trace = client.get(
        f"/v1/retrieval-traces/{e1_query.json['retrieval_trace_id']}", headers=_headers()
    )
    assert e1_trace.json["accepted_candidates"][0]["claim_version_id"] == version_id
    versions = client.get(f"/v1/claims/{claim_id}/versions", headers=_headers())
    assert versions.status_code == 200
    assert [item["version_number"] for item in versions.json["versions"]] == [1]

    support_lineage = client.get(f"/v1/evidence/{support_evidence}/lineage", headers=_headers())
    assert support_lineage.status_code == 200
    assert support_lineage.json["claim_version_refs"] == [
        {"claim_version_id": version_id, "relation_type": "SUPPORTS"}
    ]

    contradiction = _ingest(client, "pyproject requires Python >=3.12")
    conflict_proposal = client.post(
        "/v1/proposals",
        headers=_headers(f"proposal-conflict-{uuid4()}"),
        json={
            "target_claim_id": claim_id,
            "operation": "CONTRADICT",
            "expected_version_id": version_id,
            "proposed_patch": {},
            "contradicting_evidence_refs": [contradiction],
            "scope_predicate": {"project_ids": ["milai"]},
            "requested_authority": "ACTION_SAFE",
            "derivation_policy_id": "integration-v1",
            "derivation_snapshot": {"source": "integration-test"},
        },
    )
    assert conflict_proposal.status_code == 201
    pending_proposals = client.get(
        "/v1/proposals?status=PENDING_REVIEW&limit=10", headers=_headers()
    )
    assert pending_proposals.status_code == 200
    assert conflict_proposal.json["proposal_id"] in {
        item["proposal_id"] for item in pending_proposals.json["proposals"]
    }
    assert conflict_proposal.json["commit_policy_decision"] == "USER_REVIEW"
    assert conflict_proposal.json["commit_policy_version"] == "lean-commit-policy-v1"
    stored_conflict_proposal = client.get(
        f"/v1/proposals/{conflict_proposal.json['proposal_id']}", headers=_headers()
    )
    diagnosis = stored_conflict_proposal.json["derivation_snapshot"]["milai_derive_and_diagnose"]
    assert diagnosis["relation"] == "CONFLICT"
    assert diagnosis["observed_claim_version_id"] == version_id
    conflict = client.post(
        f"/v1/proposals/{conflict_proposal.json['proposal_id']}/review",
        headers=_profile_headers(REVIEWER_TOKEN, f"review-conflict-{uuid4()}"),
        json={
            "decision": "APPROVE",
            "policy_version": "human-review-v1",
            "reason_code": "CONFLICT_CONFIRMED",
        },
    )
    assert conflict.status_code == 200
    issue_id = conflict.json["open_issue_id"]

    issue = client.get(f"/v1/open-issues/{issue_id}", headers=_headers())
    assert issue.status_code == 200
    assert issue.json["status"] == "OPEN"
    assert {branch["relation_type"] for branch in issue.json["branches"]} == {
        "SUPPORT_BRANCH",
        "CONTRADICT_BRANCH",
    }
    all_open_issues = client.get("/v1/open-issues", headers=_headers())
    assert all_open_issues.status_code == 200
    assert issue_id in {item["issue_id"] for item in all_open_issues.json["issues"]}
    filtered_open_issues = client.get("/v1/open-issues?status=OPEN", headers=_headers())
    assert filtered_open_issues.status_code == 200
    assert issue_id in {item["issue_id"] for item in filtered_open_issues.json["issues"]}
    current = client.get(f"/v1/claims/{claim_id}", headers=_headers())
    assert current.json["claim_version_id"] == version_id
    assert current.json["effective_status"] == "CONFLICTED"
    e2_query = _exact_query(client, claim_id)
    assert e2_query.json["abstained"] is True
    assert e2_query.json["open_issue_ids"] == [issue_id]
    e2_trace = client.get(
        f"/v1/retrieval-traces/{e2_query.json['retrieval_trace_id']}", headers=_headers()
    )
    assert e2_trace.json["rejected_candidates"][0]["reject_reason"] == "OPEN_ISSUE"

    contradiction_lineage = client.get(f"/v1/evidence/{contradiction}/lineage", headers=_headers())
    assert contradiction_lineage.status_code == 200
    assert contradiction_lineage.json["open_issue_refs"] == [
        {"open_issue_id": issue_id, "relation_type": "CONTRADICT_BRANCH"}
    ]

    ci_evidence = _ingest(client, "CI reports Python 3.12")
    runtime_evidence = _ingest(client, "production reports Python 3.12")
    resolution_proposal = client.post(
        "/v1/proposals",
        headers=_headers(f"proposal-resolution-{uuid4()}"),
        json={
            "target_claim_id": claim_id,
            "operation": "SUPERSEDE",
            "expected_version_id": version_id,
            "proposed_patch": {
                "payload": {"python": "3.12"},
                "authority": "ACTION_SAFE",
                "confidence": 0.99,
                "resolve_issue_id": issue_id,
                "expected_issue_revision": issue.json["revision"],
                "addressed_branches": ["SUPPORT_BRANCH", "CONTRADICT_BRANCH"],
            },
            "supporting_evidence_refs": [ci_evidence, runtime_evidence],
            "scope_predicate": {"project_ids": ["milai"]},
            "requested_authority": "ACTION_SAFE",
            "derivation_policy_id": "integration-v1",
            "derivation_snapshot": {"source": "integration-test", "phase": "E3"},
        },
    )
    assert resolution_proposal.status_code == 201
    pending_review = client.get(f"/v1/open-issues/{issue_id}", headers=_headers())
    assert pending_review.json["status"] == "OPEN"
    assert pending_review.json["revision"] == issue.json["revision"]
    assert [transition["event_type"] for transition in pending_review.json["transitions"]] == [
        "ISSUE_CREATED"
    ]
    assert not any(
        branch["relation_type"] == "RESOLUTION_CANDIDATE"
        for branch in pending_review.json["branches"]
    )

    resolved = client.post(
        f"/v1/proposals/{resolution_proposal.json['proposal_id']}/review",
        headers=_profile_headers(REVIEWER_TOKEN, f"review-resolution-{uuid4()}"),
        json={
            "decision": "APPROVE",
            "policy_version": "human-review-v1",
            "reason_code": "DISCHARGE_RULE_VERIFIED",
        },
    )
    assert resolved.status_code == 200
    assert resolved.json["open_issue_id"] == issue_id
    assert resolved.json["claim_version_id"] != version_id

    final_issue = client.get(f"/v1/open-issues/{issue_id}", headers=_headers())
    assert final_issue.json["status"] == "RESOLVED"
    assert final_issue.json["revision"] == issue.json["revision"] + 1
    assert [transition["event_type"] for transition in final_issue.json["transitions"]] == [
        "ISSUE_CREATED",
        "DISCHARGE_APPROVED",
    ]
    assert (
        sum(
            branch["relation_type"] == "RESOLUTION_CANDIDATE"
            for branch in final_issue.json["branches"]
        )
        == 2
    )

    superseded = client.get(f"/v1/claims/{claim_id}", headers=_headers())
    assert superseded.json["payload"] == {"python": "3.12"}
    assert superseded.json["version_number"] == 2
    assert superseded.json["effective_status"] == "EFFECTIVE"
    e3_query = _exact_query(client, claim_id)
    assert e3_query.json["results"][0]["claim_version_id"] == resolved.json["claim_version_id"]

    capsule_id = uuid4()
    pointer_id = uuid4()
    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    with psycopg.connect(owner_url) as owner:
        owner.execute(
            """
            INSERT INTO milai.context_capsule (
              tenant_id, capsule_id, protected_sections, content_hash,
              expires_at, created_by_actor_id
            ) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP + interval '1 hour', %s)
            """,
            (
                TENANT_ID,
                capsule_id,
                Jsonb({"RETRIEVED_EVIDENCE": [runtime_evidence]}),
                hashlib.sha256(b"capsule").hexdigest(),
                ACTOR_ID,
            ),
        )
        content_hash, permission_snapshot, retention_state = owner.execute(
            """
            SELECT blob.content_hash, evidence.permission_snapshot,
                   evidence.retention_state
            FROM milai.evidence_record evidence
            JOIN milai.content_blob blob
              ON blob.tenant_id = evidence.tenant_id
             AND blob.blob_id = evidence.blob_id
            WHERE evidence.tenant_id = %s AND evidence.evidence_id = %s
            """,
            (TENANT_ID, runtime_evidence),
        ).fetchone()
        owner.execute(
            """
            INSERT INTO milai.context_pointer (
              tenant_id, pointer_id, capsule_id, evidence_id,
              pointer_hash, content_hash_snapshot, permission_snapshot,
              retention_state_snapshot, created_by_actor_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                TENANT_ID,
                pointer_id,
                capsule_id,
                runtime_evidence,
                hashlib.sha256(runtime_evidence.encode()).hexdigest(),
                content_hash,
                Jsonb(permission_snapshot),
                retention_state,
                ACTOR_ID,
            ),
        )

    revoke_key = f"revoke-{uuid4()}"
    revoke_payload = {"reason_code": "USER_REQUEST", "confirmation": "REVOKE"}
    revoked = client.post(
        f"/v1/evidence/{runtime_evidence}/revoke",
        headers=_headers(revoke_key),
        json=revoke_payload,
    )
    assert revoked.status_code == 202
    assert revoked.json["logical_revocation_status"] == "APPLIED"
    assert revoked.json["canonical_block_status"] == "APPLIED"
    assert revoked.json["context_pointers_invalidated"] == 1
    replayed_revoke = client.post(
        f"/v1/evidence/{runtime_evidence}/revoke",
        headers=_headers(revoke_key),
        json=revoke_payload,
    )
    assert replayed_revoke.status_code == 200
    assert replayed_revoke.json["replayed"] is True
    assert replayed_revoke.json["deletion_request_id"] == revoked.json["deletion_request_id"]

    blocked = client.get(f"/v1/claims/{claim_id}", headers=_headers())
    assert blocked.json["claim_version_id"] == resolved.json["claim_version_id"]
    assert blocked.json["effective_status"] == "BLOCKED"
    revoked_query = _exact_query(client, claim_id)
    assert revoked_query.json["abstained"] is True
    revoked_trace = client.get(
        f"/v1/retrieval-traces/{revoked_query.json['retrieval_trace_id']}",
        headers=_headers(),
    )
    assert revoked_trace.json["rejected_candidates"][0]["reject_reason"] == ("GROUNDING_BLOCKED")
    reopened = client.get(f"/v1/open-issues/{issue_id}", headers=_headers())
    assert reopened.json["issue_id"] == issue_id
    assert reopened.json["status"] == "WAITING_EVIDENCE"
    assert reopened.json["revision"] == final_issue.json["revision"] + 1
    assert reopened.json["transitions"][-1]["event_type"] == ("RESOLUTION_EVIDENCE_REVOKED")

    revoked_evidence = client.get(f"/v1/evidence/{runtime_evidence}", headers=_headers())
    assert revoked_evidence.status_code == 200
    assert revoked_evidence.json["content"] is None
    deletion = client.get(
        f"/v1/deletions/{revoked.json['deletion_request_id']}",
        headers=_headers(),
    )
    assert deletion.status_code == 200
    assert deletion.json["derived_purge_status"] == "PENDING"
    with psycopg.connect(owner_url) as owner:
        pointer_state, capsule_status = owner.execute(
            """
            SELECT pointer.state, capsule.status
            FROM milai.context_pointer pointer
            JOIN milai.context_capsule capsule
              ON capsule.tenant_id = pointer.tenant_id
             AND capsule.capsule_id = pointer.capsule_id
            WHERE pointer.pointer_id = %s
            """,
            (pointer_id,),
        ).fetchone()
    assert (pointer_state, capsule_status) == ("INVALIDATED", "INVALIDATED")


@pytest.mark.integration
def test_canonical_api_fails_closed_for_split_and_tenant_switch(canonical_app) -> None:  # type: ignore[no-untyped-def]
    client = canonical_app.test_client()
    evidence_id = _ingest(client, "synthetic")
    created = _create_claim(client, evidence_id)

    split = client.post(
        "/v1/proposals",
        headers=_headers(f"split-{uuid4()}"),
        json={
            "target_claim_id": created["claim_id"],
            "operation": "SPLIT",
            "expected_version_id": created["claim_version_id"],
            "proposed_patch": {},
            "scope_predicate": {},
            "requested_authority": "ACTION_SAFE",
            "derivation_policy_id": "integration-v1",
            "derivation_snapshot": {},
        },
    )
    assert split.status_code == 422
    assert split.json["error"]["code"] == "OPERATION_NOT_ENABLED"

    switched = client.post(
        "/v1/proposals",
        headers=_headers(f"tenant-switch-{uuid4()}"),
        json={
            "tenant_id": "22222222-2222-4222-8222-222222222222",
            "operation": "CREATE",
            "proposed_patch": {
                "subject_id": "forbidden",
                "predicate": "uses_version",
                "claim_type": "RUNTIME_VERSION",
                "payload": {"python": "3.11"},
                "authority": "ACTION_SAFE",
                "confidence": 0.95,
            },
            "supporting_evidence_refs": [evidence_id],
            "scope_predicate": {},
            "requested_authority": "ACTION_SAFE",
            "derivation_policy_id": "integration-v1",
            "derivation_snapshot": {},
        },
    )
    assert switched.status_code == 403
    assert switched.json["error"]["code"] == "TENANT_MISMATCH"


@pytest.mark.integration
def test_revoke_preserves_shared_blob_and_retention_blocks_erasure(canonical_app) -> None:  # type: ignore[no-untyped-def]
    client = canonical_app.test_client()
    shared_content = f"shared-revocation-fixture-{uuid4()}"
    first = _ingest(client, shared_content)
    second = _ingest(client, shared_content)

    first_revoke = client.post(
        f"/v1/evidence/{first}/revoke",
        headers=_headers(f"revoke-first-{uuid4()}"),
        json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
    )
    assert first_revoke.status_code == 202
    assert first_revoke.json["primary_bytes_status"] == "BLOCKED_SHARED_REFERENCE"
    assert first_revoke.json["shared_live_reference_count"] == 1
    still_readable = client.get(f"/v1/evidence/{second}", headers=_headers())
    assert still_readable.status_code == 200
    assert still_readable.json["content"] == shared_content

    second_revoke = client.post(
        f"/v1/evidence/{second}/revoke",
        headers=_headers(f"revoke-second-{uuid4()}"),
        json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
    )
    assert second_revoke.status_code == 202
    assert second_revoke.json["primary_bytes_status"] == "PENDING"
    owner_url = _url("MILAI_MIGRATION_DATABASE_URL")
    with psycopg.connect(owner_url) as owner:
        blob_state = owner.execute(
            """
            SELECT physical_delete_state FROM milai.content_blob
            WHERE tenant_id = %s AND blob_id = %s
            """,
            (TENANT_ID, second_revoke.json.get("blob_id", still_readable.json["blob_id"])),
        ).fetchone()[0]
    assert blob_state == "PURGE_PENDING"

    held = _ingest(client, f"legal-hold-{uuid4()}", "LEGAL_HOLD")
    held_revoke = client.post(
        f"/v1/evidence/{held}/revoke",
        headers=_headers(f"revoke-held-{uuid4()}"),
        json={"reason_code": "USER_REQUEST", "confirmation": "REVOKE"},
    )
    assert held_revoke.status_code == 202
    assert held_revoke.json["retention_status"] == "LEGAL_HOLD"
    assert held_revoke.json["primary_bytes_status"] == "RETENTION_BLOCKED"
    assert held_revoke.json["backup_expiry_status"] == "RETENTION_BLOCKED"
