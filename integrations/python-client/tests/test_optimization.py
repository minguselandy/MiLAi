from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any

import pytest

from milai_client.formatting import ContextBudgetInfeasibleError
from milai_client.models import RecallEnvelope
from milai_client.optimization import (
    CallableTokenCounter,
    ContextCompileRequest,
    ContextIntegrityError,
    DeterministicRecallRouter,
    GovernedContextCompiler,
    MemorySlot,
    ProviderTokenUsage,
    RecallRoutingInput,
    SessionSlotRegistry,
    TokenBudget,
    goal_fingerprint,
    issue_revision_digest,
    measure_tool_schemas,
    memory_slot_cache_valid,
    turn_fingerprint,
)

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[^\w\s]", re.UNICODE)


def _counter() -> CallableTokenCounter:
    return CallableTokenCounter(
        "test.regex.v1",
        lambda value: len(_TOKEN_PATTERN.findall(value)),
    )


def _envelope(
    *,
    items: list[dict[str, Any]] | None = None,
    issue_ids: list[str] | None = None,
    status: str = "OK",
    abstention_reason: str | None = None,
    degraded: list[str] | None = None,
) -> RecallEnvelope:
    return RecallEnvelope.from_api(
        {
            "results": items or [],
            "open_issue_ids": issue_ids or [],
            "abstained": status == "ABSTAINED",
            "abstention_reason": abstention_reason,
            "degraded_components": degraded or [],
            "fallback_used": False,
            "retrieval_trace_id": "trace-1",
            "consistency": "CANONICAL_REQUIRED",
            "snapshot": {
                "canonical_outbox_sequence": 7,
                "fts_watermark": 7,
                "vector_watermark": 7,
            },
        }
    )


def _claim(index: int, *, size: int = 0) -> dict[str, Any]:
    return {
        "claim_version_id": f"version-{index}",
        "claim_id": f"claim-{index}",
        "subject_id": "project",
        "predicate": f"state.{index}",
        "claim_type": "FACT",
        "payload": {"value": "x" * size if size else f"value-{index}"},
        "scope_predicate": {"project_ids": ["milai"]},
        "authority": "ACTION_SAFE",
        "effective_status": "EFFECTIVE",
        "canonical_commit_seq": index,
        "open_issue_ids": [],
    }


def _issue(issue_id: str = "issue-1", *, revision: int = 1) -> dict[str, Any]:
    return {
        "issue_id": issue_id,
        "target_claim_id": "claim-1",
        "issue_type": "CONFLICT",
        "status": "OPEN",
        "revision": revision,
        "scope_predicate": {"project_ids": ["milai"]},
        "branches": [
            {"relation_type": "SUPPORT_BRANCH", "evidence_id": "evidence-support"},
            {"relation_type": "CONTRADICT_BRANCH", "evidence_id": "evidence-conflict"},
        ],
        "discharge_rule": {
            "must_address_branches": ["SUPPORT_BRANCH", "CONTRADICT_BRANCH"],
            "review_required": True,
        },
        "required_authority": "ACTION_SAFE",
    }


def test_callable_token_counter_and_tool_measurement_are_exact() -> None:
    counter = _counter()
    tools = (
        {"name": "milai_recall", "description": "Recall governed memory"},
        {"name": "milai_claim_get", "description": "Read one Claim"},
    )
    usage = measure_tool_schemas(tools, counter)
    encoded = json.dumps(list(tools), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert usage.tokenizer_id == "test.regex.v1"
    assert usage.verified is True
    assert usage.actual_tokens == counter.count_text(encoded)
    assert usage.actual_bytes == len(encoded.encode())
    assert measure_tool_schemas(tools).actual_tokens is None


def test_token_budget_does_not_invent_tokens_without_a_counter() -> None:
    fallback = TokenBudget.for_class("STANDARD")
    assert fallback.verified is False
    assert fallback.tokenizer_id is None
    assert fallback.max_memory_tokens is None
    verified = TokenBudget.for_class("STANDARD", counter=_counter())
    assert verified.verified is True
    assert verified.max_memory_tokens == 512
    with pytest.raises(ValueError, match="requires tokenizer"):
        TokenBudget(max_memory_tokens=512, verified=True)
    with pytest.raises(ValueError, match="cannot exceed 1600"):
        TokenBudget(max_memory_tokens=1_601)
    with pytest.raises(ValueError, match="cannot exceed 250"):
        TokenBudget(max_tool_schema_tokens=251)
    assert verified.max_tool_schema_tokens == 250
    assert verified.max_total_milai_tokens == 1_600


def test_provider_usage_rejects_inferred_or_inconsistent_counters() -> None:
    with pytest.raises(ValueError, match="verified provider counters"):
        ProviderTokenUsage("provider", "model", 1, 0, 1, verified=False)
    with pytest.raises(ValueError, match="cannot exceed"):
        ProviderTokenUsage("provider", "model", 1, 2, 1)


@pytest.mark.parametrize(
    ("value", "route", "reason"),
    [
        (
            RecallRoutingInput(current_turn="你好"),
            "NONE",
            "HIGH_CONFIDENCE_NO_MEMORY_TASK",
        ),
        (
            RecallRoutingInput(current_turn="请回忆之前的项目决定"),
            "L1",
            "EXPLICIT_MEMORY_INTENT",
        ),
        (
            RecallRoutingInput(current_turn="这个 Evidence 是否已经撤销?"),
            "L1",
            "SAFETY_CRITICAL_GOVERNED_SEARCH",
        ),
        (
            RecallRoutingInput(
                current_turn="read it",
                known_object_ids=("11111111-1111-4111-8111-111111111111",),
            ),
            "L0",
            "KNOWN_CLAIM_ID_EXACT",
        ),
    ],
)
def test_router_rule_precedence(value: RecallRoutingInput, route: str, reason: str) -> None:
    decision = DeterministicRecallRouter().decide(value)
    assert decision.route == route
    assert decision.reason_code == reason
    assert decision.limit <= 3


def test_router_cache_requires_validation_same_query_and_goal_changes_force_recall() -> None:
    router = DeterministicRecallRouter()
    query = "project status"
    cached = RecallRoutingInput(
        current_turn=query,
        session_snapshot_id="snapshot",
        cached_query_fingerprint=turn_fingerprint(query),
        cache_validated=True,
        consistency_floor="CANONICAL_REQUIRED",
    )
    decision = router.decide(cached)
    assert decision.route == "CACHE"
    assert decision.cache_validation_required is True

    changed = replace(
        cached,
        active_goal="new goal",
        previous_goal_fingerprint=goal_fingerprint("old goal"),
    )
    assert router.decide(changed).route == "L1"
    unvalidated = replace(cached, cache_validated=False)
    assert router.decide(unvalidated).route == "L1"


def test_router_cache_key_binds_scope_authority_consistency_and_watermarks() -> None:
    router = DeterministicRecallRouter()
    base = RecallRoutingInput(
        current_turn="status",
        requested_scope={"project_ids": ["milai"]},
        canonical_position_seen=7,
        issue_revision_digest_seen="digest-1",
    )
    baseline = router.cache_key(base)
    variants = (
        replace(base, requested_scope={"project_ids": ["other"]}),
        replace(base, required_authority="ACTION_SAFE"),
        replace(base, consistency_floor="CANONICAL_REQUIRED"),
        replace(base, canonical_position_seen=8),
        replace(base, issue_revision_digest_seen="digest-2"),
        replace(base, context_binding="budget-or-compiler-change"),
        replace(base, max_limit=4),
    )
    assert all(router.cache_key(value) != baseline for value in variants)


def test_router_only_claim_typed_single_uuid_uses_exact_l0() -> None:
    router = DeterministicRecallRouter()
    claim_id = "11111111-1111-4111-8111-111111111111"
    exact = router.decide(RecallRoutingInput(current_turn=f"read Claim {claim_id}"))
    assert exact.route == "L0"
    assert exact.exact_claim_id == claim_id
    issue = router.decide(
        RecallRoutingInput(current_turn=f"read OpenIssue target Claim {claim_id}")
    )
    assert issue.route == "L1"
    assert issue.reason_code == "OPEN_ISSUE_ID_GOVERNED_SEARCH"
    ambiguous = router.decide(
        RecallRoutingInput(
            current_turn=f"compare {claim_id} and 22222222-2222-4222-8222-222222222222"
        )
    )
    assert ambiguous.route == "L1"
    assert ambiguous.exact_claim_id is None


def test_compiler_preserves_complete_open_issue_and_downgrades_large_items() -> None:
    counter = _counter()
    issue = _issue()
    envelope = _envelope(
        items=[_claim(1, size=1_500), _claim(2, size=1_500), _claim(3, size=1_500)],
        issue_ids=[issue["issue_id"]],
    )
    result = GovernedContextCompiler().compile(
        ContextCompileRequest(
            recall_envelope=envelope,
            session_id="session",
            query_fingerprint=turn_fingerprint("status"),
            active_goal="answer safely",
            constraints=("preserve conflict",),
            token_budget=TokenBudget(
                tokenizer_id=counter.tokenizer_id,
                max_memory_tokens=1_024,
                max_bytes=4_096,
                budget_class="HIGH",
                verified=True,
            ),
            token_counter=counter,
            open_issues=(issue,),
        )
    )
    assert result.delta.status == "REPLACE"
    assert result.delta.rendered_context is not None
    rendered = result.delta.rendered_context
    assert rendered.count("GROUP authority=ACTION_SAFE epistemic=EFFECTIVE") == 1
    assert "BRANCH=SUPPORT_BRANCH" in rendered
    assert "BRANCH=CONTRADICT_BRANCH" in rendered
    assert 'DISCHARGE={"must_address_branches"' in rendered
    assert "evidence-support" not in rendered
    assert "evidence-conflict" not in rendered
    assert "trace-1" not in rendered
    assert "claim-1" not in rendered
    assert "MILAI_CONTEXT_BEGIN" in rendered
    assert "MILAI_CONTEXT_END" in rendered
    assert result.metrics.actual_tokens is not None
    assert result.metrics.actual_tokens <= 1_024
    assert result.metrics.token_budget_verified is True
    assert result.slot is not None
    assert result.slot.canonical_position == 7
    assert any(tier != "FULL" for _, tier in result.metrics.representation_tiers)


def test_abstract_representation_keeps_bounded_semantic_payload() -> None:
    counter = _counter()
    claim = _claim(1, size=2_000)
    claim["payload"] = {
        "python": "3.11",
        "marker": "synthetic-project",
        "memory_text": "x" * 2_000,
    }
    result = GovernedContextCompiler().compile(
        ContextCompileRequest(
            recall_envelope=_envelope(items=[claim]),
            session_id="session",
            query_fingerprint=turn_fingerprint("python version"),
            active_goal="answer the current runtime version",
            token_budget=TokenBudget(
                tokenizer_id=counter.tokenizer_id,
                max_memory_tokens=256,
                max_bytes=2_048,
                budget_class="LOW",
                verified=True,
            ),
            token_counter=counter,
        )
    )
    assert result.delta.rendered_context is not None
    assert '"marker":"synthetic-project"' in result.delta.rendered_context
    assert '"python":"3.11"' in result.delta.rendered_context
    assert result.metrics.actual_tokens is not None
    assert result.metrics.actual_tokens <= 256


def test_memory_slot_checkpoint_and_canonical_issue_validation_are_strict() -> None:
    issue = _issue()
    result = GovernedContextCompiler().compile(
        ContextCompileRequest(
            recall_envelope=_envelope(items=[_claim(1)], issue_ids=[issue["issue_id"]]),
            session_id="session",
            query_fingerprint=turn_fingerprint("status"),
            open_issues=(issue,),
        )
    )
    assert result.slot is not None
    restored = MemorySlot.from_state(result.slot.to_state())
    assert restored == result.slot
    assert restored.query_fingerprint == turn_fingerprint("status")
    assert restored.live_issue_ids == ("issue-1",)
    assert restored.live_issue_revision_digest == issue_revision_digest((issue,))
    assert memory_slot_cache_valid(restored, canonical_snapshot=7, open_issues=(issue,))
    assert not memory_slot_cache_valid(restored, canonical_snapshot=8, open_issues=(issue,))
    assert not memory_slot_cache_valid(
        restored, canonical_snapshot=7, open_issues=(_issue(revision=2),)
    )
    invalid = restored.to_state()
    invalid["content_hash"] = "not-a-digest"
    with pytest.raises(ValueError, match="invalid MiLAi memory slot"):
        MemorySlot.from_state(invalid)
    legacy = restored.to_state()
    legacy.pop("cache_key")
    with pytest.raises(ValueError, match="invalid MiLAi memory slot"):
        MemorySlot.from_state(legacy)


def test_legacy_representation_identity_reads_old_and_writes_semantic() -> None:
    issue = _issue()
    result = GovernedContextCompiler().compile(
        ContextCompileRequest(
            recall_envelope=_envelope(items=[_claim(1)], issue_ids=[issue["issue_id"]]),
            session_id="session",
            query_fingerprint=turn_fingerprint("status"),
            open_issues=(issue,),
        )
    )
    assert result.slot is not None
    legacy = result.slot.to_state()
    legacy["representation_policy_version"] = "dg11-grouped-compact-v1"

    restored = MemorySlot.from_state(legacy)

    assert restored.representation_policy_version == "grouped-compact/v3"
    assert restored.to_state()["representation_policy_version"] == "grouped-compact/v3"


def test_mixed_representation_identity_invalidates_previous_slot() -> None:
    compiler = GovernedContextCompiler()
    initial = compiler.compile(
        ContextCompileRequest(
            recall_envelope=_envelope(items=[_claim(1)]),
            session_id="session",
            query_fingerprint=turn_fingerprint("status"),
        )
    )
    assert initial.slot is not None

    mixed = compiler.compile(
        ContextCompileRequest(
            recall_envelope=_envelope(items=[_claim(1)]),
            session_id="session",
            query_fingerprint=turn_fingerprint("status"),
            previous_slot=initial.slot,
            representation_policy_version="grouped-compact/v4",
        )
    )

    assert mixed.delta.status == "REPLACE"
    assert mixed.slot is not None
    assert mixed.slot.representation_policy_version == "grouped-compact/v4"


def test_open_issue_digest_ignores_transport_metadata_but_binds_semantics() -> None:
    issue = _issue()
    first = {**issue, "request_id": "request-a", "transitions": [{"revision": 1}]}
    second = {**issue, "request_id": "request-b", "transitions": [{"revision": 99}]}
    assert issue_revision_digest((first,)) == issue_revision_digest((second,))
    assert issue_revision_digest((first,)) != issue_revision_digest((_issue(revision=2),))


@pytest.mark.parametrize(
    "mutation",
    [
        {"status": "RESOLVED"},
        {"revision": -9},
        {"target_claim_id": "wrong-claim"},
        {"branches": []},
        {"discharge_rule": {}},
        {"branches": [{"relation_type": "UNKNOWN", "evidence_id": "e1"}]},
    ],
)
def test_compiler_fails_closed_on_semantically_invalid_open_issue(
    mutation: dict[str, object],
) -> None:
    invalid = {**_issue(), **mutation}
    expected = (
        "CONTEXT_ISSUE_TARGET_MISMATCH"
        if mutation.get("target_claim_id") == "wrong-claim"
        else "CONTEXT_ISSUE_DETAILS_INVALID"
    )
    with pytest.raises(ContextIntegrityError, match=expected):
        GovernedContextCompiler().compile(
            ContextCompileRequest(
                recall_envelope=_envelope(items=[_claim(1)], issue_ids=["issue-1"]),
                session_id="session",
                query_fingerprint=turn_fingerprint("conflict"),
                open_issues=(invalid,),
            )
        )


def test_compiler_refuses_issue_id_without_branches_and_discharge_rule() -> None:
    with pytest.raises(ContextIntegrityError, match="CONTEXT_ISSUE_DETAILS_REQUIRED"):
        GovernedContextCompiler().compile(
            ContextCompileRequest(
                recall_envelope=_envelope(issue_ids=["issue-1"]),
                session_id="session",
                query_fingerprint=turn_fingerprint("conflict"),
            )
        )


def test_protected_minimum_is_infeasible_instead_of_dropping_issue() -> None:
    counter = CallableTokenCounter("chars.v1", len)
    issue = _issue()
    with pytest.raises(ContextBudgetInfeasibleError, match="CONTEXT_BUDGET_INFEASIBLE"):
        GovernedContextCompiler().compile(
            ContextCompileRequest(
                recall_envelope=_envelope(items=[_claim(1)], issue_ids=[issue["issue_id"]]),
                session_id="session",
                query_fingerprint=turn_fingerprint("conflict"),
                token_budget=TokenBudget(
                    tokenizer_id=counter.tokenizer_id,
                    max_memory_tokens=256,
                    max_bytes=8_192,
                    budget_class="LOW",
                    verified=True,
                ),
                token_counter=counter,
                open_issues=(issue,),
            )
        )


def test_no_candidate_zero_injection_removes_previous_slot_when_not_safety_required() -> None:
    compiler = GovernedContextCompiler()
    initial = compiler.compile(
        ContextCompileRequest(
            recall_envelope=_envelope(items=[_claim(1)]),
            session_id="session",
            query_fingerprint=turn_fingerprint("status"),
        )
    )
    assert initial.slot is not None
    empty = compiler.compile(
        ContextCompileRequest(
            recall_envelope=_envelope(status="ABSTAINED", abstention_reason="NO_CANDIDATE"),
            session_id="session",
            query_fingerprint=turn_fingerprint("hello"),
            previous_slot=initial.slot,
            safety_required=False,
        )
    )
    assert empty.delta.status == "REMOVE"
    assert empty.delta.rendered_context is None
    assert empty.metrics.actual_bytes == 0


def test_canonical_unavailable_still_injects_minimal_safety_state() -> None:
    result = GovernedContextCompiler().compile(
        ContextCompileRequest(
            recall_envelope=_envelope(
                status="ABSTAINED",
                abstention_reason="CANONICAL_UNAVAILABLE",
                degraded=["canonical_database"],
            ),
            session_id="session",
            query_fingerprint=turn_fingerprint("current state"),
            safety_required=True,
        )
    )
    assert result.delta.status == "REPLACE"
    assert result.delta.rendered_context is not None
    assert "CANONICAL_UNAVAILABLE" in result.delta.rendered_context
    assert "canonical_database" in result.delta.rendered_context


def test_unchanged_snapshot_emits_zero_context_and_registry_stays_constant_for_500_turns() -> None:
    compiler = GovernedContextCompiler()
    registry = SessionSlotRegistry()
    request = ContextCompileRequest(
        recall_envelope=_envelope(items=[_claim(1)]),
        session_id="session",
        query_fingerprint=turn_fingerprint("same query"),
    )
    result = compiler.compile(request)
    registry.apply("session", result)
    assert result.slot is not None
    for _ in range(499):
        repeated = compiler.compile(replace(request, previous_slot=registry.get("session")))
        assert repeated.delta.status == "UNCHANGED"
        assert repeated.delta.rendered_context is None
        assert repeated.metrics.actual_bytes == 0
        registry.apply("session", repeated)
    assert len(registry) == 1
    assert registry.get("session") == result.slot


def test_issue_revision_changes_snapshot_and_replaces_slot() -> None:
    compiler = GovernedContextCompiler()
    first_issue = _issue(revision=1)
    envelope = _envelope(items=[_claim(1)], issue_ids=["issue-1"])
    first = compiler.compile(
        ContextCompileRequest(
            recall_envelope=envelope,
            session_id="session",
            query_fingerprint=turn_fingerprint("conflict"),
            open_issues=(first_issue,),
        )
    )
    assert first.slot is not None
    second = compiler.compile(
        ContextCompileRequest(
            recall_envelope=envelope,
            session_id="session",
            query_fingerprint=turn_fingerprint("conflict"),
            open_issues=(_issue(revision=2),),
            previous_slot=first.slot,
        )
    )
    assert second.delta.status == "REPLACE"
    assert second.slot is not None
    assert second.slot.snapshot_id != first.slot.snapshot_id


def test_byte_fallback_reports_no_token_value_and_tokenizer_mismatch_fails() -> None:
    compiler = GovernedContextCompiler()
    request = ContextCompileRequest(
        recall_envelope=_envelope(items=[_claim(1)]),
        session_id="session",
        query_fingerprint=turn_fingerprint("status"),
        token_budget=TokenBudget(max_bytes=2_048),
    )
    result = compiler.compile(request)
    assert result.metrics.token_budget_verified is False
    assert result.metrics.actual_tokens is None
    with pytest.raises(ValueError, match="tokenizer_id"):
        compiler.compile(
            replace(
                request,
                token_budget=TokenBudget(
                    tokenizer_id="other",
                    max_memory_tokens=512,
                    verified=True,
                ),
                token_counter=_counter(),
            )
        )
