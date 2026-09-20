from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar
from uuid import UUID, uuid4

import pytest

from milai.application import context_preparation as context_preparation_module
from milai.application.context import ContextCapsuleBuilt, _context_variants
from milai.application.context_preparation import PrepareContextService
from milai.application.context_prepare.binding import binding_digest
from milai.application.errors import ContextOperationError
from milai.application.retrieval import RetrievalExecution
from milai.domain import (
    ContextValidationTokenCodec,
    MemoryNeedSignature,
    PrepareContextRequest,
    StateKeyRef,
)
from milai.domain import context_validation as context_validation_module
from milai.persistence import DatabaseUnavailable, SessionContext
from milai.persistence.context_repository import ContextMaterial, ContextValidationSnapshot

DIGEST = "a" * 64
SECRET = "context-preparation-test-secret-that-is-long-enough"


class _ControlledDatetime(datetime):
    current = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):  # type: ignore[no-untyped-def]
        value = cls.current
        return value if tz is None else value.astimezone(tz)


class _Retrieval:
    def __init__(self) -> None:
        self.calls = 0
        self.canonical_position = 9
        self.requests: list[object] = []
        self.unavailable = False

    def retrieve(self, _context, request, _request_id) -> RetrievalExecution:  # type: ignore[no-untyped-def]
        self.calls += 1
        self.requests.append(request)
        if self.unavailable:
            raise DatabaseUnavailable("synthetic exact canonical outage")
        return RetrievalExecution(
            {
                "abstained": False,
                "retrieval_trace_id": str(UUID(int=7)),
                "snapshot": {"canonical_outbox_sequence": self.canonical_position},
                "results": [{"claim_id": str(UUID(int=8))}],
            }
        )


class _Contexts:
    last_request: ClassVar[object | None] = None
    issue: ClassVar[dict[str, object]] = {
        "issue_id": str(UUID(int=10)),
        "target_claim_id": str(UUID(int=8)),
        "status": "OPEN",
        "issue_type": "CONFLICT",
        "revision": 1,
        "required_authority": "ACTION_SAFE",
        "scope_predicate": {"project_ids": ["milai"]},
        "discharge_rule": {"kind": "STEWARD_REVIEW"},
        "branches": [],
    }

    def __init__(self, repository: _Repository) -> None:
        self._repository = repository
        self._builds = 0

    def build(self, _context, _request) -> ContextCapsuleBuilt:  # type: ignore[no-untyped-def]
        self.last_request = _request
        capsule_id = UUID(int=11 + self._builds)
        self._builds += 1
        expires_at = context_preparation_module.datetime.now(UTC) + timedelta(
            seconds=_request.ttl_seconds
        )
        self._repository.capsules[capsule_id] = {
            "status": "ACTIVE",
            "expires_at": expires_at,
            "content_hash": "b" * 64,
        }
        return ContextCapsuleBuilt(
            {
                "capsule_id": str(capsule_id),
                "content_hash": "b" * 64,
                "expires_at": expires_at.isoformat(),
            },
            {
                "ACTIVE GOAL": {"text": "finish"},
                "ACTIVE STATE": [
                    {
                        "claim_id": str(UUID(int=8)),
                        "claim_version_id": str(UUID(int=9)),
                        "subject_id": "project",
                        "predicate": "project.status",
                        "claim_type": "PROJECT_STATE",
                        "payload": {"value": "ready"},
                        "authority": "INFORMATIONAL",
                        "canonical_commit_seq": 9,
                    }
                ],
                "OPEN ISSUES": [self.issue],
                "RETRIEVED EVIDENCE": [
                    {
                        "pointer_id": str(UUID(int=12)),
                        "evidence_id": str(UUID(int=13)),
                        "content_hash": "c" * 64,
                    }
                ],
            },
            "MINIMAL",
        )


class _Repository:
    def __init__(self) -> None:
        self.canonical_position = 9
        self.calls = 0
        self.open_issues = [_Contexts.issue]
        self.unavailable = False
        self.capsules: dict[UUID, dict[str, object]] = {}

    def validation_snapshot(  # type: ignore[no-untyped-def]
        self, _context, _issue_ids, capsule_id
    ) -> ContextValidationSnapshot:
        self.calls += 1
        if self.unavailable:
            raise DatabaseUnavailable("synthetic canonical outage")
        capsule = self.capsules.get(capsule_id)
        return ContextValidationSnapshot(
            self.canonical_position,
            self.open_issues,
            str(capsule["status"]) if capsule is not None else None,
            (
                capsule["expires_at"]
                if capsule is not None and isinstance(capsule["expires_at"], datetime)
                else None
            ),
            str(capsule["content_hash"]) if capsule is not None else None,
        )


def _request(**updates: object) -> PrepareContextRequest:
    value: dict[str, object] = {
        "query": "current project state",
        "active_goal": "finish",
        "session_id": "session-1",
        "agent_id": "agent-1",
        "profile_id": "reader-lite",
        "task_epoch": "task-1",
        "event": "TASK_START",
        "requested_scope": {"project_ids": ["milai"]},
        "compiler_digest": DIGEST,
        "router_digest": DIGEST,
        "tokenizer_digest": DIGEST,
        "policy_digest": DIGEST,
        "budget": {"memory_deadline_ms": 5_000},
    }
    value.update(updates)
    return PrepareContextRequest.model_validate(value)


def _service() -> tuple[PrepareContextService, _Retrieval, _Repository]:
    retrieval = _Retrieval()
    repository = _Repository()
    service = PrepareContextService(  # type: ignore[arg-type]
        retrieval,
        _Contexts(repository),
        repository,
        ContextValidationTokenCodec(SECRET),
    )
    return service, retrieval, repository


def _typed_need(
    *,
    subject: str = "project",
    evidence_need: str = "SUPPORT_POINTERS",
) -> tuple[MemoryNeedSignature, StateKeyRef]:
    key = StateKeyRef(
        scope={"project_ids": ["milai"]},
        subject=subject,
        predicate="project.status",
        claim_type="PROJECT_STATE",
        claim_id=UUID(int=8) if subject == "project" else None,
    )
    signature = MemoryNeedSignature(
        scope={"project_ids": ["milai"]},
        required_authority="INFORMATIONAL",
        consistency_floor="CANONICAL_REQUIRED",
        state_keys=[key],
        temporal_need="CURRENT",
        evidence_need=evidence_need,  # type: ignore[arg-type]
        intent_class="CURRENT_STATE",
    )
    return signature, key


def test_one_refresh_then_tool_result_uses_validated_cache_without_recall() -> None:
    service, retrieval, repository = _service()
    context = SessionContext(uuid4(), uuid4())
    signature, key = _typed_need()
    first = service.prepare(
        context,
        "reader",
        _request(
            need_signature_id=signature.signature_id,
            memory_need_signature=signature,
            state_key_ref=key,
        ),
        "request-1",
    )
    assert first.body["status"] == "READY"
    assert first.body["route"] == "L1"
    assert first.body["recall_execution_trace"] == {
        "need_signature_id": signature.signature_id,
        "requested_route": "L1",
        "planned_route": "L1",
        "validated_route": "L1",
        "attempted_routes": ["L1"],
        "terminal_route": "L1",
        "result": "HIT",
        "policy_override_reason": None,
        "fallback_reason": None,
        "next_route_recommended": None,
        "route_trace_complete": True,
        "trace_gap_reason": None,
        "query_embedding_calls": 0,
        "vector_calls": 0,
        "reranker_calls": 0,
        "exact_calls": 0,
        "fts_calls": 0,
        "l0_calls": 0,
    }
    assert first.body["relevant_open_issue_closure"] == [_Contexts.issue]
    assert set(first.body["timing"]) == {
        "retrieval_ms",
        "context_build_ms",
        "validation_snapshot_ms",
        "runtime_total_ms",
    }
    token = first.body["validation_token"]
    assert isinstance(token, str)

    cached = service.prepare(
        context,
        "reader",
        _request(
            event="TOOL_RESULT",
            query="tool output",
            requested_route="CACHE",
            previous_validation_token=token,
            need_signature_id=signature.signature_id,
            memory_need_signature=signature,
            state_key_ref=key,
        ),
        "request-2",
    )
    assert cached.body["route"] == "CACHE"
    assert cached.body["status"] == "UNCHANGED"
    assert cached.body["recall_execution_trace"]["validated_route"] == "CACHE"
    assert cached.body["recall_execution_trace"]["terminal_route"] == "CACHE"
    assert cached.body["context_capsule"] is None
    assert cached.body["memory_slot_coverage"]["state_keys_and_head_versions"]
    assert set(cached.body["timing"]) == {
        "validation_snapshot_ms",
        "runtime_total_ms",
    }
    assert cached.body["usage"] == {
        "prepare_context_calls": 2,
        "full_recall_calls": 1,
        "delta_refreshes": 0,
        "validation_calls": 1,
    }
    assert retrieval.calls == 1
    assert repository.calls == 2


def test_cache_validation_renews_past_original_capsule_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the diagnosis case as a regression for capsule-bounded renewal."""

    monkeypatch.setattr(context_preparation_module, "datetime", _ControlledDatetime)
    monkeypatch.setattr(context_validation_module, "datetime", _ControlledDatetime)
    service, retrieval, repository = _service()
    context = SessionContext(uuid4(), uuid4())
    signature, key = _typed_need()
    initial_time = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)
    _ControlledDatetime.current = initial_time
    initial = service.prepare(
        context,
        "reader",
        _request(
            slot_ttl_seconds=10,
            need_signature_id=signature.signature_id,
            memory_need_signature=signature,
            state_key_ref=key,
        ),
        "request-original-capsule",
    )

    _ControlledDatetime.current = initial_time + timedelta(seconds=9)
    renewed = service.prepare(
        context,
        "reader",
        _request(
            event="TOOL_RESULT",
            requested_route="CACHE",
            slot_ttl_seconds=10,
            previous_validation_token=initial.body["validation_token"],
            need_signature_id=signature.signature_id,
            memory_need_signature=signature,
            state_key_ref=key,
        ),
        "request-renew-lease",
    )
    assert renewed.body["route"] == "CACHE"
    assert renewed.body["reason"] == "VALIDATED_TASK_SLOT_REUSE"
    renewed_request = _request(
        event="TOOL_RESULT",
        requested_route="CACHE",
        slot_ttl_seconds=10,
        previous_validation_token=initial.body["validation_token"],
        need_signature_id=signature.signature_id,
        memory_need_signature=signature,
        state_key_ref=key,
    )
    renewed_state = ContextValidationTokenCodec(SECRET).decode(
        renewed.body["validation_token"],
        expected_tenant_id=context.tenant_id,
        expected_profile="reader",
        expected_binding_digest=binding_digest(context, "reader", renewed_request),
        now=_ControlledDatetime.current,
    )
    assert renewed_state.expires_at == initial_time + timedelta(seconds=10)

    # The renewed proof expires with the original immutable ContextCapsule.
    # At t0+11 it cannot be reused and the same call performs an exact refresh.
    _ControlledDatetime.current = initial_time + timedelta(seconds=11)
    after_original_capsule_expiry = service.prepare(
        context,
        "reader",
        _request(
            event="TOOL_RESULT",
            requested_route="CACHE",
            slot_ttl_seconds=10,
            previous_validation_token=renewed.body["validation_token"],
            need_signature_id=signature.signature_id,
            memory_need_signature=signature,
            state_key_ref=key,
        ),
        "request-after-original-capsule-expiry",
    )
    assert after_original_capsule_expiry.body["route"] == "L0"
    assert after_original_capsule_expiry.body["status"] == "READY"
    assert (
        after_original_capsule_expiry.body["context_capsule"]["capsule_id"]
        != (initial.body["context_capsule"]["capsule_id"])
    )
    assert (
        after_original_capsule_expiry.body["recall_execution_trace"]["fallback_reason"]
        == "BROKER_BOUND_VALIDATION_PROOF_INVALID"
    )
    assert retrieval.calls == 2
    assert repository.calls == 3


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        ("MISSING", "CACHE_CAPSULE_NOT_FOUND"),
        ("INVALIDATED", "CACHE_CAPSULE_INVALIDATED"),
        ("EXPIRED", "CACHE_CAPSULE_EXPIRED"),
        ("HASH_MISMATCH", "CACHE_CAPSULE_CONTENT_HASH_CHANGED"),
    ],
)
def test_authoritative_capsule_lifecycle_miss_refreshes_exactly(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    expected_reason: str,
) -> None:
    monkeypatch.setattr(context_preparation_module, "datetime", _ControlledDatetime)
    monkeypatch.setattr(context_validation_module, "datetime", _ControlledDatetime)
    service, retrieval, repository = _service()
    context = SessionContext(uuid4(), uuid4())
    signature, key = _typed_need()
    initial_time = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)
    _ControlledDatetime.current = initial_time
    initial = service.prepare(
        context,
        "reader",
        _request(
            slot_ttl_seconds=300,
            need_signature_id=signature.signature_id,
            memory_need_signature=signature,
            state_key_ref=key,
        ),
        f"request-capsule-{mutation.lower()}",
    )
    capsule_id = UUID(initial.body["context_capsule"]["capsule_id"])
    if mutation == "MISSING":
        del repository.capsules[capsule_id]
    elif mutation == "INVALIDATED":
        repository.capsules[capsule_id]["status"] = "INVALIDATED"
    elif mutation == "EXPIRED":
        repository.capsules[capsule_id]["expires_at"] = initial_time
    else:
        repository.capsules[capsule_id]["content_hash"] = "c" * 64

    _ControlledDatetime.current = initial_time + timedelta(seconds=1)
    refreshed = service.prepare(
        context,
        "reader",
        _request(
            event="TOOL_RESULT",
            requested_route="CACHE",
            slot_ttl_seconds=300,
            previous_validation_token=initial.body["validation_token"],
            need_signature_id=signature.signature_id,
            memory_need_signature=signature,
            state_key_ref=key,
        ),
        f"request-refresh-{mutation.lower()}",
    )

    assert refreshed.body["route"] == "L0"
    assert refreshed.body["status"] == "READY"
    assert refreshed.body["context_capsule"]["capsule_id"] != str(capsule_id)
    assert refreshed.body["recall_execution_trace"]["fallback_reason"] == expected_reason
    assert retrieval.calls == 2
    assert repository.calls == 3


def test_cache_position_change_falls_through_to_exact_l0_in_same_call() -> None:
    service, retrieval, repository = _service()
    context = SessionContext(uuid4(), uuid4())
    signature, key = _typed_need()
    first = service.prepare(
        context,
        "reader",
        _request(
            need_signature_id=signature.signature_id,
            memory_need_signature=signature,
            state_key_ref=key,
        ),
        "request-1",
    )
    repository.canonical_position = 10
    retrieval.canonical_position = 10
    cached = service.prepare(
        context,
        "reader",
        _request(
            event="MODEL_RETRY",
            query="retry",
            requested_route="CACHE",
            previous_validation_token=first.body["validation_token"],
            need_signature_id=signature.signature_id,
            memory_need_signature=signature,
            state_key_ref=key,
        ),
        "request-2",
    )
    trace = cached.body["recall_execution_trace"]
    assert cached.body["status"] == "READY"
    assert cached.body["route"] == "L0"
    assert trace["requested_route"] == "CACHE"
    assert trace["planned_route"] == "CACHE"
    assert trace["attempted_routes"] == ["CACHE", "L0"]
    assert trace["terminal_route"] == "L0"
    assert trace["fallback_reason"] == "CACHE_CANONICAL_POSITION_CHANGED"
    assert trace["next_route_recommended"] is None
    assert cached.body["usage"]["validation_calls"] == 1
    assert retrieval.calls == 2
    assert repository.calls == 3


def test_cache_issue_revision_change_falls_through_to_one_exact_l0() -> None:
    service, retrieval, repository = _service()
    context = SessionContext(uuid4(), uuid4())
    signature, key = _typed_need()
    original_issue = _Contexts.issue
    first = service.prepare(
        context,
        "reader",
        _request(
            need_signature_id=signature.signature_id,
            memory_need_signature=signature,
            state_key_ref=key,
        ),
        "request-1",
    )
    revised_issue = {**original_issue, "revision": 2}
    try:
        _Contexts.issue = revised_issue
        repository.open_issues = [revised_issue]
        cached = service.prepare(
            context,
            "reader",
            _request(
                event="MODEL_RETRY",
                requested_route="CACHE",
                previous_validation_token=first.body["validation_token"],
                need_signature_id=signature.signature_id,
                memory_need_signature=signature,
                state_key_ref=key,
            ),
            "request-2",
        )
    finally:
        _Contexts.issue = original_issue

    trace = cached.body["recall_execution_trace"]
    assert cached.body["status"] == "READY"
    assert trace["attempted_routes"] == ["CACHE", "L0"]
    assert trace["terminal_route"] == "L0"
    assert trace["fallback_reason"] == "CACHE_OPEN_ISSUE_REVISION_CHANGED"
    assert trace["next_route_recommended"] is None
    assert retrieval.calls == 2
    assert repository.calls == 3


def test_cache_canonical_unavailable_is_typed_and_does_not_attempt_exact() -> None:
    service, retrieval, repository = _service()
    context = SessionContext(uuid4(), uuid4())
    signature, key = _typed_need()
    first = service.prepare(
        context,
        "reader",
        _request(
            need_signature_id=signature.signature_id,
            memory_need_signature=signature,
            state_key_ref=key,
        ),
        "request-1",
    )
    repository.unavailable = True

    cached = service.prepare(
        context,
        "reader",
        _request(
            event="MODEL_RETRY",
            requested_route="CACHE",
            previous_validation_token=first.body["validation_token"],
            need_signature_id=signature.signature_id,
            memory_need_signature=signature,
            state_key_ref=key,
        ),
        "request-cache-canonical-down",
    )

    trace = cached.body["recall_execution_trace"]
    assert cached.status_code == 503
    assert cached.body["status"] == "DEGRADED"
    assert cached.body["reason"] == "CANONICAL_UNAVAILABLE"
    assert cached.body["route"] == "CACHE"
    assert trace["requested_route"] == "CACHE"
    assert trace["planned_route"] == "CACHE"
    assert trace["attempted_routes"] == ["CACHE"]
    assert trace["terminal_route"] == "CACHE"
    assert trace["result"] == "ERROR"
    assert trace["next_route_recommended"] is None
    assert retrieval.calls == 1
    assert repository.calls == 2


def test_cache_miss_exact_canonical_unavailable_is_not_rewritten_as_none() -> None:
    service, retrieval, repository = _service()
    context = SessionContext(uuid4(), uuid4())
    signature, key = _typed_need()
    retrieval.unavailable = True

    result = service.prepare(
        context,
        "reader",
        _request(
            event="TOOL_RESULT",
            requested_route="CACHE",
            need_signature_id=signature.signature_id,
            memory_need_signature=signature,
            state_key_ref=key,
        ),
        "request-cache-exact-canonical-down",
    )

    trace = result.body["recall_execution_trace"]
    assert result.status_code == 503
    assert result.body["status"] == "DEGRADED"
    assert result.body["reason"] == "CANONICAL_UNAVAILABLE"
    assert result.body["route"] == "L0"
    assert result.body["current_state_envelope"]["status"] == "CANONICAL_UNAVAILABLE"
    assert trace["requested_route"] == "CACHE"
    assert trace["planned_route"] == "CACHE"
    assert trace["attempted_routes"] == ["CACHE", "L0"]
    assert trace["terminal_route"] == "L0"
    assert trace["fallback_reason"] == "NO_TASK_SLOT"
    assert trace["next_route_recommended"] is None
    assert retrieval.calls == 1
    assert repository.calls == 0


def test_cache_miss_does_not_reset_deadline_before_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, retrieval, repository = _service()
    context = SessionContext(uuid4(), uuid4())
    signature, key = _typed_need()
    times = iter((0.0, 0.026, 0.027))
    monkeypatch.setattr(context_preparation_module, "perf_counter", lambda: next(times))

    result = service.prepare(
        context,
        "reader",
        _request(
            event="TOOL_RESULT",
            requested_route="CACHE",
            budget={"memory_deadline_ms": 25},
            need_signature_id=signature.signature_id,
            memory_need_signature=signature,
            state_key_ref=key,
        ),
        "request-cache-deadline",
    )

    trace = result.body["recall_execution_trace"]
    assert result.body["status"] == "DEGRADED"
    assert result.body["reason"] == "MEMORY_DEADLINE_EXCEEDED"
    assert trace["planned_route"] == "CACHE"
    assert trace["attempted_routes"] == ["CACHE"]
    assert trace["terminal_route"] == "CACHE"
    assert trace["fallback_reason"] == "NO_TASK_SLOT"
    assert trace["next_route_recommended"] is None
    assert retrieval.calls == 0
    assert repository.calls == 0


def test_cache_need_must_be_covered_before_dependency_validation() -> None:
    service, retrieval, repository = _service()
    context = SessionContext(uuid4(), uuid4())
    signature, key = _typed_need()
    first = service.prepare(
        context,
        "reader",
        _request(
            need_signature_id=signature.signature_id,
            memory_need_signature=signature,
            state_key_ref=key,
        ),
        "request-1",
    )
    other_signature, other_key = _typed_need(subject="other-project")

    cached = service.prepare(
        context,
        "reader",
        _request(
            event="MODEL_RETRY",
            query="other project status",
            requested_route="CACHE",
            previous_validation_token=first.body["validation_token"],
            need_signature_id=other_signature.signature_id,
            memory_need_signature=other_signature,
            state_key_ref=other_key,
        ),
        "request-2",
    )

    trace = cached.body["recall_execution_trace"]
    assert cached.body["status"] == "READY"
    assert cached.body["route"] == "L0"
    assert trace["planned_route"] == "CACHE"
    assert trace["attempted_routes"] == ["CACHE", "L0"]
    assert trace["terminal_route"] == "L0"
    assert trace["fallback_reason"] == "CACHE_STATE_KEY_UNCOVERED"
    assert trace["next_route_recommended"] is None
    assert retrieval.calls == 2
    assert repository.calls == 2


def test_cache_raw_evidence_need_is_not_covered_by_support_pointers() -> None:
    service, _retrieval, repository = _service()
    context = SessionContext(uuid4(), uuid4())
    signature, key = _typed_need()
    first = service.prepare(
        context,
        "reader",
        _request(
            need_signature_id=signature.signature_id,
            memory_need_signature=signature,
            state_key_ref=key,
        ),
        "request-1",
    )
    raw_signature, raw_key = _typed_need(evidence_need="RAW_EVIDENCE")

    cached = service.prepare(
        context,
        "reader",
        _request(
            event="MODEL_RETRY",
            query="show raw evidence",
            requested_route="CACHE",
            previous_validation_token=first.body["validation_token"],
            need_signature_id=raw_signature.signature_id,
            memory_need_signature=raw_signature,
            state_key_ref=raw_key,
        ),
        "request-2",
    )

    trace = cached.body["recall_execution_trace"]
    assert cached.body["status"] == "NEEDS_RECOVERY"
    assert cached.body["reason"] == "RAW_EVIDENCE_RECOVERY_REQUIRED"
    assert trace["attempted_routes"] == ["CACHE", "L0"]
    assert trace["terminal_route"] == "L0"
    assert trace["fallback_reason"] == "CACHE_EVIDENCE_DEPTH_UNCOVERED"
    assert trace["next_route_recommended"] is None
    assert repository.calls == 2


def test_raw_evidence_need_returns_explicit_recovery_without_slot_proof() -> None:
    service, retrieval, _repository = _service()
    context = SessionContext(uuid4(), uuid4())
    signature, key = _typed_need(evidence_need="RAW_EVIDENCE")

    result = service.prepare(
        context,
        "reader",
        _request(
            need_signature_id=signature.signature_id,
            memory_need_signature=signature,
            state_key_ref=key,
        ),
        "request-raw-recovery",
    )

    assert result.body["status"] == "NEEDS_RECOVERY"
    assert result.body["reason"] == "RAW_EVIDENCE_RECOVERY_REQUIRED"
    assert result.body["validation_token"] is None
    assert result.body["requested_detail_level"] == "EVIDENCE_DETAIL"
    assert result.body["prepared_detail_level"] == "OVERVIEW"
    assert result.body["memory_slot_coverage"]["evidence_depth"] == "SUPPORT_POINTERS"
    assert result.body["recall_execution_trace"]["result"] == "MISS"
    assert result.body["recall_execution_trace"]["route_trace_complete"] is True
    assert retrieval.calls == 1


def test_abstract_context_variant_omits_evidence_while_overview_keeps_pointers() -> None:
    material = ContextMaterial(
        retrieval_trace_id=UUID(int=1),
        claims=[],
        open_issues=[],
        evidence=[
            {
                "evidence_id": str(UUID(int=2)),
                "content_hash": "d" * 64,
                "permission_snapshot": {"readable": True},
                "retention_state": "READABLE",
            }
        ],
    )

    abstract = _context_variants(material, "goal", [], "ABSTRACT")
    overview = _context_variants(material, "goal", [], "OVERVIEW")

    assert all(not sections["RETRIEVED EVIDENCE"] for _level, sections in abstract)
    assert all(sections["RETRIEVED EVIDENCE"] for _level, sections in overview)


def test_invalid_cache_proof_falls_through_to_exact_without_reusing_slot() -> None:
    service, retrieval, repository = _service()
    context = SessionContext(uuid4(), uuid4())
    signature, key = _typed_need()

    cached = service.prepare(
        context,
        "reader",
        _request(
            event="MODEL_RETRY",
            requested_route="CACHE",
            previous_validation_token="x" * 64,
            need_signature_id=signature.signature_id,
            memory_need_signature=signature,
            state_key_ref=key,
        ),
        "request-invalid-proof",
    )

    trace = cached.body["recall_execution_trace"]
    assert cached.body["status"] == "READY"
    assert cached.body["route"] == "L0"
    assert trace["planned_route"] == "CACHE"
    assert trace["attempted_routes"] == ["CACHE", "L0"]
    assert trace["terminal_route"] == "L0"
    assert trace["fallback_reason"] == "BROKER_BOUND_VALIDATION_PROOF_INVALID"
    assert trace["next_route_recommended"] is None
    assert retrieval.calls == 1
    assert repository.calls == 1


def test_token_cannot_cross_profile_or_task_binding() -> None:
    service, _retrieval, _repository = _service()
    context = SessionContext(uuid4(), uuid4())
    first = service.prepare(context, "reader", _request(), "request-1")
    token = first.body["validation_token"]
    with pytest.raises(ContextOperationError, match="CONTEXT_VALIDATION_TOKEN_INVALID"):
        service.prepare(
            context,
            "submitter",
            _request(event="TOOL_RESULT", previous_validation_token=token),
            "request-2",
        )
    with pytest.raises(ContextOperationError, match="CONTEXT_VALIDATION_TOKEN_INVALID"):
        service.prepare(
            context,
            "reader",
            _request(
                event="TOOL_RESULT",
                task_epoch="task-2",
                previous_validation_token=token,
            ),
            "request-3",
        )


def test_budget_exhaustion_is_explicit_before_second_full_recall() -> None:
    service, retrieval, _repository = _service()
    context = SessionContext(uuid4(), uuid4())
    request = _request(budget={"max_full_recall_calls": 1, "memory_deadline_ms": 5_000})
    first = service.prepare(context, "reader", request, "request-1")
    exhausted = service.prepare(
        context,
        "reader",
        _request(
            event="EXPLICIT_MEMORY_REQUEST",
            previous_validation_token=first.body["validation_token"],
            budget={"max_full_recall_calls": 1, "memory_deadline_ms": 5_000},
        ),
        "request-2",
    )
    assert exhausted.status_code == 429
    assert exhausted.body["status"] == "BUDGET_EXHAUSTED"
    assert retrieval.calls == 1


def test_cache_fallback_budget_terminal_preserves_cache_trace_without_retrieval() -> None:
    service, retrieval, repository = _service()
    context = SessionContext(uuid4(), uuid4())
    signature, key = _typed_need()
    budget = {"max_full_recall_calls": 1, "memory_deadline_ms": 5_000}
    first = service.prepare(
        context,
        "reader",
        _request(
            budget=budget,
            need_signature_id=signature.signature_id,
            memory_need_signature=signature,
            state_key_ref=key,
        ),
        "request-1",
    )
    other_signature, other_key = _typed_need(subject="other-project")

    exhausted = service.prepare(
        context,
        "reader",
        _request(
            event="MODEL_RETRY",
            requested_route="CACHE",
            previous_validation_token=first.body["validation_token"],
            budget=budget,
            need_signature_id=other_signature.signature_id,
            memory_need_signature=other_signature,
            state_key_ref=other_key,
        ),
        "request-cache-budget",
    )

    trace = exhausted.body["recall_execution_trace"]
    assert exhausted.status_code == 429
    assert exhausted.body["status"] == "BUDGET_EXHAUSTED"
    assert exhausted.body["reason"] == "FULL_RECALL_CALL_BUDGET_EXHAUSTED"
    assert trace["requested_route"] == "CACHE"
    assert trace["planned_route"] == "CACHE"
    assert trace["attempted_routes"] == ["CACHE"]
    assert trace["terminal_route"] == "CACHE"
    assert trace["fallback_reason"] == "CACHE_STATE_KEY_UNCOVERED"
    assert trace["next_route_recommended"] is None
    assert retrieval.calls == 1
    assert repository.calls == 1


def test_l0_without_locator_is_explicitly_overridden_before_l1_execution() -> None:
    service, retrieval, _repository = _service()
    context = SessionContext(uuid4(), uuid4())

    result = service.prepare(
        context,
        "reader",
        _request(requested_route="L0"),
        "request-l0-override",
    )

    trace = result.body["recall_execution_trace"]
    assert result.body["route"] == "L1"
    assert trace["requested_route"] == "L0"
    assert trace["planned_route"] == "L1"
    assert trace["validated_route"] == "L1"
    assert trace["attempted_routes"] == ["L1"]
    assert trace["terminal_route"] == "L1"
    assert trace["policy_override_reason"] == "L0_LOCATOR_UNAVAILABLE"
    assert retrieval.calls == 1


def test_typed_need_scope_mismatch_is_a_traced_block_without_retrieval() -> None:
    service, retrieval, _repository = _service()
    context = SessionContext(uuid4(), uuid4())
    key = StateKeyRef(
        scope={"project_ids": ["other"]},
        subject="release",
        predicate="release.target",
        claim_type="PROJECT_STATE",
    )
    signature = MemoryNeedSignature(
        scope={"project_ids": ["other"]},
        required_authority="INFORMATIONAL",
        consistency_floor="CANONICAL_REQUIRED",
        state_keys=[key],
        temporal_need="CURRENT",
        evidence_need="SUPPORT_POINTERS",
        intent_class="CURRENT_STATE",
    )

    result = service.prepare(
        context,
        "reader-lite",
        _request(
            requested_route="L0",
            need_signature_id=signature.signature_id,
            memory_need_signature=signature,
            state_key_ref=key,
        ),
        "request-wrong-scope",
    )

    trace = result.body["recall_execution_trace"]
    assert result.body["status"] == "ABSTAIN"
    assert result.body["reason"] == "NEED_SCOPE_MISMATCH"
    assert result.body["current_state_envelope"]["status"] == "BLOCKED"
    assert trace["requested_route"] == "L0"
    assert trace["planned_route"] == "L0"
    assert trace["validated_route"] == "L0"
    assert trace["attempted_routes"] == ["L0"]
    assert trace["terminal_route"] == "L0"
    assert trace["result"] == "BLOCKED"
    assert trace["policy_override_reason"] == "NEED_SCOPE_MISMATCH"
    assert trace["route_trace_complete"] is True
    assert trace["l0_calls"] == 0
    assert retrieval.calls == 0


def test_cache_miss_falls_through_to_exact_l0_while_none_skips_retrieval() -> None:
    service, retrieval, _repository = _service()
    context = SessionContext(uuid4(), uuid4())
    signature, key = _typed_need()

    cache = service.prepare(
        context,
        "reader",
        _request(
            requested_route="CACHE",
            event="TOOL_RESULT",
            need_signature_id=signature.signature_id,
            memory_need_signature=signature,
            state_key_ref=key,
        ),
        "request-cache-miss",
    )
    none = service.prepare(
        context,
        "reader",
        _request(requested_route="NONE"),
        "request-none",
    )

    assert cache.body["route"] == "L0"
    assert cache.body["status"] == "READY"
    assert cache.body["recall_execution_trace"] == {
        "need_signature_id": signature.signature_id,
        "requested_route": "CACHE",
        "planned_route": "CACHE",
        "validated_route": "CACHE",
        "attempted_routes": ["CACHE", "L0"],
        "terminal_route": "L0",
        "result": "HIT",
        "policy_override_reason": None,
        "fallback_reason": "NO_TASK_SLOT",
        "next_route_recommended": None,
        "route_trace_complete": True,
        "trace_gap_reason": None,
        "query_embedding_calls": 0,
        "vector_calls": 0,
        "reranker_calls": 0,
        "exact_calls": 0,
        "fts_calls": 0,
        "l0_calls": 0,
    }
    assert none.body["recall_execution_trace"]["result"] == "HIT"
    assert none.body["recall_execution_trace"]["attempted_routes"] == []
    assert retrieval.calls == 1
    assert retrieval.requests[0].route == "L0"  # type: ignore[attr-defined]
