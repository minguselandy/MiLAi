from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from milai_client import AgentMemory, AgentRecallPolicy, TokenBudget
from milai_client.models import RecallEnvelope


class _OptimizedClient:
    base_url = "http://127.0.0.1:18080"

    def __init__(self) -> None:
        self.recalls: list[tuple[str, dict[str, Any]]] = []
        self.exact_recalls: list[Any] = []
        self.issue_reads = 0
        self.canonical_snapshot = 7

    def system_watermarks(self) -> Any:
        return SimpleNamespace(canonical_snapshot=self.canonical_snapshot)

    def recall(self, query: str, **options: Any) -> RecallEnvelope:
        self.recalls.append((query, options))
        return RecallEnvelope.from_api(
            {
                "results": [
                    {
                        "claim_id": "claim-1",
                        "claim_version_id": "version-1",
                        "subject_id": "project",
                        "predicate": "project.status",
                        "payload": {"value": "synthetic"},
                        "authority": "INFORMATIONAL",
                        "canonical_commit_seq": 7,
                        "open_issue_ids": ["issue-1"],
                    }
                ],
                "open_issue_ids": ["issue-1"],
                "abstained": False,
                "degraded_components": [],
                "fallback_used": False,
                "retrieval_trace_id": "trace-1",
                "consistency": options["consistency"],
                "snapshot": {"canonical_outbox_sequence": 7},
            }
        )

    def recall_exact(self, request: Any) -> RecallEnvelope:
        self.exact_recalls.append(request)
        return RecallEnvelope.from_api(
            {
                "results": [
                    {
                        "claim_id": request.claim_id,
                        "claim_version_id": "version-exact",
                        "authority": request.authority,
                    }
                ],
                "abstained": False,
                "degraded_components": [],
                "fallback_used": False,
                "retrieval_trace_id": "trace-exact",
                "consistency": request.consistency,
                "snapshot": {"canonical_outbox_sequence": 7},
            }
        )

    def list_open_issues(self, status: str | None = None) -> list[Any]:
        self.issue_reads += 1
        return [
            SimpleNamespace(
                issue_id="issue-1",
                raw={
                    "issue_id": "issue-1",
                    "target_claim_id": "claim-1",
                    "issue_type": "CONFLICT",
                    "status": "OPEN",
                    "revision": 2,
                    "scope_predicate": {"project_ids": ["milai"]},
                    "branches": [
                        {"relation_type": "SUPPORT_BRANCH", "evidence_id": "evidence-1"},
                        {"relation_type": "CONTRADICT_BRANCH", "evidence_id": "evidence-2"},
                    ],
                    "discharge_rule": {"review_required": True},
                    "required_authority": "ACTION_SAFE",
                    "request_id": f"request-{self.issue_reads}",
                },
            )
        ]

    def get_open_issue(self, issue_id: str) -> Any:
        return next(issue for issue in self.list_open_issues() if issue.issue_id == issue_id)

    def build_context(self, request: Any) -> Any:
        return SimpleNamespace(
            capsule_id="capsule-1",
            protected_sections={
                "ACTIVE STATE": [
                    {
                        "claim_id": "claim-1",
                        "claim_version_id": "version-1",
                        "authority": "INFORMATIONAL",
                    }
                ],
                "OPEN ISSUES": [self.list_open_issues()[0].raw],
                "RETRIEVED EVIDENCE": [],
            },
        )


def _policy(
    *,
    project: str = "milai",
    authority: str = "INFORMATIONAL",
    consistency: str = "EVENTUAL",
    max_limit: int = 5,
) -> AgentRecallPolicy:
    return AgentRecallPolicy(
        scope={"project_ids": [project]},
        authority=authority,  # type: ignore[arg-type]
        consistency_floor=consistency,  # type: ignore[arg-type]
        max_limit=max_limit,
    )


def test_optimized_lifecycle_recall_cache_and_none_manage_one_slot() -> None:
    client = _OptimizedClient()
    memory = AgentMemory(client)  # type: ignore[arg-type]
    first = memory.prepare_context(
        "project status",
        session_id="session",
        recall_policy=_policy(),
    )
    assert first.routing.route == "L1"
    assert first.compiled.delta.status == "REPLACE"
    assert first.compiled.delta.rendered_context is not None
    assert "SUPPORT_BRANCH" in first.compiled.delta.rendered_context
    assert len(memory.slot_registry) == 1
    assert len(client.recalls) == 1
    assert client.recalls[0][1]["limit"] == 3

    cached = memory.prepare_context(
        "project status",
        session_id="session",
        recall_policy=_policy(),
    )
    assert cached.routing.route == "CACHE"
    assert cached.compiled.delta.status == "UNCHANGED"
    assert cached.compiled.delta.rendered_context is None
    assert len(client.recalls) == 1
    assert len(memory.slot_registry) == 1

    skipped = memory.prepare_context(
        "你好",
        session_id="session",
        recall_policy=_policy(),
    )
    assert skipped.routing.route == "NONE"
    assert skipped.compiled.delta.status == "REMOVE"
    assert len(client.recalls) == 1
    assert len(memory.slot_registry) == 0


def test_same_query_auto_validates_cache_and_canonical_advance_forces_recall() -> None:
    client = _OptimizedClient()
    memory = AgentMemory(client)  # type: ignore[arg-type]
    memory.prepare_context("project status", session_id="session", recall_policy=_policy())
    cached = memory.prepare_context("project status", session_id="session", recall_policy=_policy())
    assert cached.routing.route == "CACHE"
    assert len(client.recalls) == 1

    client.canonical_snapshot = 8
    refreshed = memory.prepare_context(
        "project status", session_id="session", recall_policy=_policy()
    )
    assert refreshed.routing.route == "L1"
    assert len(client.recalls) == 2


def test_cache_binds_host_scope_authority_consistency_budget_and_ttl() -> None:
    client = _OptimizedClient()
    memory = AgentMemory(client)  # type: ignore[arg-type]
    first = memory.prepare_context(
        "project status",
        session_id="session",
        recall_policy=_policy(),
        token_budget=TokenBudget(budget_class="STANDARD"),
    )
    assert first.compiled.slot is not None

    changed_policy = AgentRecallPolicy(
        scope={"project_ids": ["other"]},
        authority="ACTION_SAFE",
        consistency_floor="CANONICAL_REQUIRED",
        max_limit=2,
    )
    refreshed = memory.prepare_context(
        "project status",
        session_id="session",
        recall_policy=changed_policy,
        token_budget=TokenBudget(budget_class="LOW"),
    )
    assert refreshed.routing.route == "L1"
    assert len(client.recalls) == 2

    assert refreshed.compiled.slot is not None
    expired = replace(
        refreshed.compiled.slot,
        created_at=datetime.now(UTC) - timedelta(seconds=301),
        ttl_seconds=300,
    )
    memory.slot_registry.restore("session", expired)
    after_ttl = memory.prepare_context(
        "project status",
        session_id="session",
        recall_policy=changed_policy,
        token_budget=TokenBudget(budget_class="LOW"),
    )
    assert after_ttl.routing.route == "L1"
    assert len(client.recalls) == 3


@pytest.mark.parametrize(
    ("changed_policy", "changed_budget", "changed_constraints"),
    [
        (_policy(project="other"), None, ()),
        (_policy(authority="ACTION_SAFE"), None, ()),
        (
            _policy(consistency="CANONICAL_REQUIRED"),
            None,
            (),
        ),
        (_policy(max_limit=2), None, ()),
        (_policy(), TokenBudget(budget_class="LOW"), ()),
        (_policy(), None, ("new host constraint",)),
    ],
)
def test_each_cache_policy_or_budget_leg_independently_forces_recall(
    changed_policy: AgentRecallPolicy,
    changed_budget: TokenBudget | None,
    changed_constraints: tuple[str, ...],
) -> None:
    client = _OptimizedClient()
    memory = AgentMemory(client)  # type: ignore[arg-type]
    memory.prepare_context(
        "project status",
        session_id="session",
        recall_policy=_policy(),
        token_budget=TokenBudget(budget_class="STANDARD"),
    )
    refreshed = memory.prepare_context(
        "project status",
        session_id="session",
        recall_policy=changed_policy,
        token_budget=changed_budget or TokenBudget(budget_class="STANDARD"),
        context_constraints=changed_constraints,
    )
    assert refreshed.routing.route == "L1"
    assert len(client.recalls) == 2


def test_public_cache_validation_override_is_not_accepted() -> None:
    memory = AgentMemory(_OptimizedClient())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="cache_validated"):
        memory.prepare_context(  # type: ignore[call-arg]
            "project status",
            session_id="session",
            recall_policy=_policy(),
            cache_validated=True,
        )


def test_active_goal_uses_context_capsule_protected_sections_without_second_issue_read() -> None:
    client = _OptimizedClient()
    memory = AgentMemory(client)  # type: ignore[arg-type]
    prepared = memory.prepare_context(
        "project status",
        session_id="session",
        recall_policy=_policy(),
        active_goal="answer current project state",
        context_constraints=("preserve conflict",),
    )
    assert prepared.compiled.delta.status == "REPLACE"
    assert prepared.recall_envelope is not None
    assert prepared.recall_envelope.context_capsule_id == "capsule-1"
    assert client.issue_reads == 1  # the fake ContextCapsule builder performed this read


def test_known_claim_id_uses_l0_and_session_end_invalidates_only_temporary_slot() -> None:
    client = _OptimizedClient()
    memory = AgentMemory(client)  # type: ignore[arg-type]
    claim_id = "11111111-1111-4111-8111-111111111111"
    prepared = memory.prepare_context(
        "read exact claim",
        session_id="session",
        recall_policy=_policy(),
        known_claim_ids=(claim_id,),
    )
    assert prepared.routing.route == "L0"
    assert client.exact_recalls[0].claim_id == claim_id
    assert len(memory.slot_registry) == 1
    result = memory.on_session_end("session", subject_id="subject")
    assert result["status"] == "CLOSED_NO_REPLAYABLE_REFS"
    assert len(memory.slot_registry) == 0


def test_query_typed_claim_uuid_uses_exact_transport_without_known_ids() -> None:
    client = _OptimizedClient()
    memory = AgentMemory(client)  # type: ignore[arg-type]
    claim_id = "11111111-1111-4111-8111-111111111111"
    prepared = memory.prepare_context(
        f"read Claim {claim_id}",
        session_id="session",
        recall_policy=_policy(),
    )
    assert prepared.routing.route == "L0"
    assert client.exact_recalls[0].claim_id == claim_id
    assert client.recalls == []
