from __future__ import annotations

import re
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from milai.application.context_receipt import (
    ContextReceiptService,
    annotate_receipt_fallback,
)
from milai.application.errors import ContextOperationError
from milai.application.memory_access import MemoryAccessPlanner
from milai.application.memory_context import MemoryContextCompiler
from milai.application.memory_state import MemoryStateViewService
from milai.application.retrieval import (
    MatchedReplayPolicy,
    RetrievalExecution,
    RetrievalService,
)
from milai.domain.memory_resolve import (
    MemoryAvailability,
    MemoryIntentLevel,
    MemoryRequirement,
    MemoryResolveRequest,
    MemoryResolveStatus,
)
from milai.domain.memory_state import MemoryStateGetRequest
from milai.domain.reader_evidence_plan import DecisionSnapshot
from milai.domain.retrieval import EvidenceNeed, MemoryIntent, RetrievalRequest
from milai.persistence import DatabaseUnavailable, SessionContext

_REQUIRED = re.compile(
    r"\b(?:remember|recall|memory|previous(?:ly)?|earlier|history|historical|"
    r"current|currently|latest|last time|what did i|what have i|my preference|"
    r"open issue|conflict\w*|contradict\w*|why did .+ change)\b|"
    r"(?:\u8bb0\u5f97|\u8bb0\u5fc6|\u4e4b\u524d|\u6b64\u524d|\u5386\u53f2|\u5f53\u524d|\u73b0\u5728|\u6700\u65b0|\u4e0a\u6b21|\u6211\u7684\u504f\u597d|\u51b2\u7a81|\u4e3a\u4ec0\u4e48.*(?:\u6539\u53d8|\u53d8\u5316))",
    re.IGNORECASE,
)
_EXACT = re.compile(
    r"\b(?:current|currently|latest|configured|setting|status|state|target|owner|"
    r"deadline|database|preference)\b|(?:\u5f53\u524d|\u73b0\u5728|\u6700\u65b0|\u914d\u7f6e|\u8bbe\u7f6e|\u72b6\u6001|\u76ee\u6807|\u8d1f\u8d23\u4eba|\u622a\u6b62|\u6570\u636e\u5e93|\u504f\u597d)",
    re.IGNORECASE,
)
_CONFLICT = re.compile(
    r"\b(?:conflict\w*|open issue|contradict\w*|both branches)\b|"
    r"(?:\u51b2\u7a81|\u672a\u51b3\u95ee\u9898|\u77db\u76fe|\u4e24\u4e2a\u5206\u652f)",
    re.IGNORECASE,
)
_HISTORY = re.compile(
    r"\b(?:history|historical|previous(?:ly)?|earlier|before|last time)\b|"
    r"(?:\u5386\u53f2|\u4e4b\u524d|\u6b64\u524d|\u4ee5\u524d|\u4e0a\u6b21)",
    re.IGNORECASE,
)
_EXPLANATION = re.compile(
    r"\b(?:why|explain|provenance|evidence)\b|(?:\u4e3a\u4ec0\u4e48|\u89e3\u91ca|\u6eaf\u6e90|\u8bc1\u636e)",
    re.IGNORECASE,
)
_NOT_NEEDED = re.compile(
    r"^(?:hello|hi|good\s+(?:morning|afternoon|evening))\b|"
    r"\b(?:compute|calculate|what is)\s+\d+\s*(?:plus|minus|times|[+*\-/])\s*\d+",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class MemoryQueryInterpretation:
    intent: MemoryIntentLevel
    requirement: MemoryRequirement
    retrieval_intent: MemoryIntent | None
    evidence_need: EvidenceNeed
    reason_code: str
    interpreter_version: str = "runtime-query-interpreter-v1"


@dataclass(frozen=True, slots=True)
class MatchedMemoryResolveReplay:
    """Internal Q1R result; it is intentionally absent from MCP transport models."""

    schema_version: Literal["matched-memory-resolve-replay-v0.1"]
    evidence_snapshot: dict[str, Any]
    evidence_snapshot_digest: str
    policy_executions: dict[MatchedReplayPolicy, RetrievalExecution]
    policy_metadata: dict[MatchedReplayPolicy, dict[str, Any]]


class MemoryQueryInterpreter:
    """Deterministic M1 owner of task-free Memory reachability."""

    def interpret(
        self,
        query: str,
        *,
        invocation_mode: str = "EXPLICIT_READ",
        exact_target: bool = False,
    ) -> MemoryQueryInterpretation:
        text = unicodedata.normalize("NFKC", query).strip()
        if exact_target:
            return MemoryQueryInterpretation(
                intent="REQUIRED",
                requirement="EXACT",
                retrieval_intent="CURRENT_STATE",
                evidence_need="SUPPORT_POINTERS",
                reason_code="CANONICAL_STATE_ADDRESS_REQUESTED",
            )
        if invocation_mode == "PREFETCH_AUTO" and _NOT_NEEDED.search(text):
            return MemoryQueryInterpretation(
                intent="NOT_NEEDED",
                requirement="NONE",
                retrieval_intent=None,
                evidence_need="NONE",
                reason_code="QUERY_MEMORY_NOT_NEEDED",
            )
        required = _REQUIRED.search(text) is not None
        requirement: MemoryRequirement = "EXACT" if _EXACT.search(text) else "SEARCH"
        retrieval_intent: MemoryIntent | None = None
        evidence_need: EvidenceNeed = "SUPPORT_POINTERS"
        if _CONFLICT.search(text):
            retrieval_intent = "CONFLICT"
        elif _EXPLANATION.search(text):
            retrieval_intent = "EXPLANATION"
        elif _HISTORY.search(text):
            retrieval_intent = "HISTORY"
        elif requirement == "EXACT":
            retrieval_intent = "CURRENT_STATE"
        return MemoryQueryInterpretation(
            intent="REQUIRED" if required else "POSSIBLE",
            requirement=requirement,
            retrieval_intent=retrieval_intent,
            evidence_need=evidence_need,
            reason_code=(
                f"QUERY_MEMORY_{requirement}_SIGNAL"
                if required
                else "EXPLICIT_READ_REQUIREMENT_FLOOR"
            ),
        )


class MemoryResolveService:
    """Adapt one governed RetrievalService result into AccessOutcome v0.1."""

    def __init__(
        self,
        retrieval: RetrievalService,
        interpreter: MemoryQueryInterpreter | None = None,
        state_views: MemoryStateViewService | None = None,
        receipts: ContextReceiptService | None = None,
        access_planner: MemoryAccessPlanner | None = None,
        context_compiler: MemoryContextCompiler | None = None,
        progressive_context_evidence: bool = False,
    ) -> None:
        self._retrieval = retrieval
        self._interpreter = interpreter or MemoryQueryInterpreter()
        self._state_views = state_views
        self._receipts = receipts
        self._access_planner = access_planner or MemoryAccessPlanner()
        self._context_compiler = context_compiler or MemoryContextCompiler()
        self._progressive_context_evidence = progressive_context_evidence

    def resolve(
        self,
        context: SessionContext,
        request: MemoryResolveRequest,
        request_id: str,
        *,
        source_snapshot_as_of: datetime | None = None,
    ) -> RetrievalExecution:
        if source_snapshot_as_of is not None and (
            source_snapshot_as_of.tzinfo is None
            or source_snapshot_as_of.utcoffset() is None
        ):
            raise ValueError("source_snapshot_as_of must include a timezone offset")
        request, task_enhancement = _apply_task_context(request)
        interpretation = self._interpreter.interpret(
            request.query,
            invocation_mode=request.invocation_mode,
            exact_target=bool(request.state_keys or request.claim_ids),
        )
        if interpretation.requirement == "NONE":
            body = _not_needed_access_outcome(request, interpretation, request_id)
            if task_enhancement is not None:
                body["task_enhancement"] = task_enhancement
            return RetrievalExecution(body)
        receipt_fallback_reason: str | None = None
        receipt_validation_ms = 0.0
        if self._receipts is not None and request.previous_context_id is not None:
            try:
                reuse = self._receipts.reuse(context, request, request_id)
            except DatabaseUnavailable:
                receipt_fallback_reason = "RECEIPT_CANONICAL_UNAVAILABLE"
            else:
                receipt_fallback_reason = reuse.miss_reason
                receipt_validation_ms = reuse.validation_ms
                if reuse.body is not None:
                    if task_enhancement is not None:
                        reuse.body["task_enhancement"] = task_enhancement
                    return RetrievalExecution(reuse.body)
        if (
            self._state_views is not None
            and len(request.state_keys) + len(request.claim_ids) == 1
        ):
            state_execution = self._state_views.get(
                context,
                MemoryStateGetRequest(
                    claim_id=request.claim_ids[0] if request.claim_ids else None,
                    state_key=request.state_keys[0] if request.state_keys else None,
                    requested_scope=request.requested_scope,
                    required_authority=request.required_authority,
                    consistency_mode=request.consistency_mode,
                    causal_token=request.causal_token,
                    valid_at=request.valid_at,
                    known_at=request.known_at,
                ),
                request_id,
            )
            return self._finalize(
                context,
                request,
                RetrievalExecution(
                    _state_access_outcome(state_execution.body, interpretation),
                    status_code=state_execution.status_code,
                ),
                receipt_fallback_reason,
                receipt_validation_ms,
                task_enhancement,
            )
        retrieval_request = _retrieval_request(
            request,
            interpretation,
            source_snapshot_as_of=source_snapshot_as_of,
        )
        access_plan = self._access_planner.plan(request, interpretation)
        execution = self._retrieval.retrieve(
            context,
            retrieval_request,
            request_id,
            context_budget=access_plan.context_token_budget,
            access_plan=access_plan,
        )
        return self._finalize(
            context,
            request,
            RetrievalExecution(
                _access_outcome(
                    execution.body,
                    interpretation,
                    decision_snapshot=execution.decision_snapshot,
                    progressive_context_evidence=(self._progressive_context_evidence),
                ),
                status_code=execution.status_code,
                decision_snapshot=execution.decision_snapshot,
            ),
            receipt_fallback_reason,
            receipt_validation_ms,
            task_enhancement,
        )

    def resolve_matched_replay(
        self,
        context: SessionContext,
        request: MemoryResolveRequest,
        request_id: str,
    ) -> MatchedMemoryResolveReplay:
        """Compile both Q1R policies from one fail-closed retrieval execution."""

        request, task_enhancement = _apply_task_context(request)
        if request.previous_context_id is not None:
            raise ValueError("matched replay cannot reuse a previous Context receipt")
        if request.state_keys or request.claim_ids:
            raise ValueError("matched replay is only defined for L1 Evidence reads")
        interpretation = self._interpreter.interpret(
            request.query,
            invocation_mode=request.invocation_mode,
            exact_target=False,
        )
        if interpretation.requirement == "NONE":
            raise ValueError("matched replay requires a Memory read")
        access_plan = self._access_planner.plan(request, interpretation)
        execution = self._retrieval.retrieve(
            context,
            _retrieval_request(request, interpretation),
            request_id,
            context_budget=access_plan.context_token_budget,
            access_plan=access_plan,
            capture_matched_replay=True,
        )
        replay = execution.matched_replay
        if replay is None:
            raise RuntimeError("retrieval did not produce a matched replay capture")
        policy_executions: dict[MatchedReplayPolicy, RetrievalExecution] = {}
        for policy, raw_body in replay.policy_bodies.items():
            adapted = RetrievalExecution(
                _access_outcome(deepcopy(raw_body), interpretation),
                status_code=execution.status_code,
            )
            policy_executions[policy] = self._finalize(
                context,
                request,
                adapted,
                None,
                0.0,
                task_enhancement,
            )
        return MatchedMemoryResolveReplay(
            schema_version="matched-memory-resolve-replay-v0.1",
            evidence_snapshot=deepcopy(replay.evidence_snapshot),
            evidence_snapshot_digest=replay.evidence_snapshot_digest,
            policy_executions=policy_executions,
            policy_metadata=deepcopy(replay.policy_metadata),
        )

    def _finalize(
        self,
        context: SessionContext,
        request: MemoryResolveRequest,
        execution: RetrievalExecution,
        receipt_fallback_reason: str | None,
        receipt_validation_ms: float,
        task_enhancement: dict[str, Any] | None,
    ) -> RetrievalExecution:
        body = execution.body
        raw_items = body.get("items")
        has_evidence_observation = isinstance(raw_items, list) and any(
            isinstance(item, dict) and item.get("kind") == "EVIDENCE_OBSERVATION"
            for item in raw_items
        )
        body["context_candidate_kinds"] = sorted(
            {
                str(item.get("kind", "CANONICAL_STATE"))
                for item in raw_items
                if isinstance(raw_items, list) and isinstance(item, dict)
            }
        ) if isinstance(raw_items, list) else []
        compiled = self._context_compiler.compile(
            request,
            body,
            session_context=context,
            decision_snapshot=execution.decision_snapshot,
        )
        reader_evidence_boundary = body.pop("_reader_evidence_boundary", None)
        if isinstance(reader_evidence_boundary, str):
            body["reader_evidence_boundary"] = reader_evidence_boundary
        body["memory_context"] = compiled.memory_context.model_dump(mode="json")
        if compiled.evidence_receipt is not None:
            body["context_receipt"] = compiled.evidence_receipt.model_dump(mode="json")
        elif self._receipts is not None and not has_evidence_observation:
            try:
                body["context_receipt"] = self._receipts.issue(context, request, body)
            except ContextOperationError as exc:
                degraded = body.get("degraded_components")
                components = list(degraded) if isinstance(degraded, list) else []
                if "context_receipt" not in components:
                    components.append("context_receipt")
                body["degraded_components"] = sorted(components)
                body["context_receipt"] = None
                body["context_receipt_issue_reason"] = exc.code
            except DatabaseUnavailable:
                degraded = body.get("degraded_components")
                components = list(degraded) if isinstance(degraded, list) else []
                if "context_receipt" not in components:
                    components.append("context_receipt")
                body["degraded_components"] = sorted(components)
                body["context_receipt"] = None
                body["context_receipt_issue_reason"] = "CANONICAL_UNAVAILABLE"
        elif has_evidence_observation:
            # The compiler normally issues an ephemeral evidence receipt. Keep
            # this fail-closed branch explicit if a sub-minimum budget ever
            # prevents all Evidence provenance from entering the Context.
            body["context_receipt"] = None
            body["context_receipt_issue_reason"] = "EVIDENCE_CONTEXT_EMPTY"
            if _budget_infeasible_evidence_context(body["memory_context"]):
                body["status"] = "ABSTAINED"
                body["abstention_reason"] = "CONTEXT_BUDGET_INFEASIBLE"
        if task_enhancement is not None:
            body["task_enhancement"] = task_enhancement
        if receipt_fallback_reason is not None:
            annotate_receipt_fallback(
                body,
                receipt_fallback_reason,
                receipt_validation_ms,
            )
        return RetrievalExecution(
            body,
            status_code=execution.status_code,
            matched_replay=execution.matched_replay,
            decision_snapshot=execution.decision_snapshot,
            context_plan=compiled.context_plan,
        )


def _budget_infeasible_evidence_context(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    trace = value.get("compile_trace")
    return (
        value.get("authority_class") == "CANONICAL_STATE"
        and value.get("context_truncated") is True
        and value.get("selected_evidence_ids") == []
        and value.get("selected_source_turn_refs") == []
        and value.get("windows") == []
        and isinstance(trace, dict)
        and trace.get("reader_readiness") == "BUDGET_INFEASIBLE"
        and trace.get("selected_unit_ids") == []
        and trace.get("selected_conditional_unit_ids") == []
    )


def _apply_task_context(
    request: MemoryResolveRequest,
) -> tuple[MemoryResolveRequest, dict[str, Any] | None]:
    task = request.task_context
    if task is None:
        return request, None

    scope: dict[str, Any] = dict(request.requested_scope)
    raw_projects = scope.get("project_ids")
    projects = (
        [str(value) for value in raw_projects]
        if isinstance(raw_projects, list)
        else []
    )
    effective_projects = _narrow_values(projects, task.project_ids)
    effective_entities = _narrow_values(request.entities, task.entities)
    effective_memory_types = _narrow_values(
        request.memory_types, task.memory_types
    )
    effects: list[str] = []
    if task.project_ids:
        scope["project_ids"] = effective_projects
        effects.append("PROJECT_SCOPE_NARROWING")
    if task.entities:
        effects.append("ENTITY_HARD_PARTITION")
    if task.memory_types:
        effects.append("MEMORY_TYPE_HARD_PARTITION")
    if task.action_risk is not None:
        effects.append("ACTION_RISK_OBSERVED_NO_POLICY_EFFECT")

    effective = request.model_copy(
        update={
            "requested_scope": scope,
            "entities": effective_entities,
            "memory_types": effective_memory_types,
            # The effective request and receipt contain only governed narrowing
            # constraints, never a Host Task object or Task identity.
            "task_context": None,
        }
    )
    return effective, {
        "schema_version": "task-enhancement-v0.1",
        "present": True,
        "applied": bool(task.project_ids or task.entities or task.memory_types),
        "effects": effects,
        "effective_project_count": len(effective_projects),
        "effective_entity_count": len(effective_entities),
        "effective_memory_type_count": len(effective_memory_types),
        "action_risk_present": task.action_risk is not None,
        "action_risk_non_authoritative": True,
        "authority_unchanged": effective.required_authority
        == request.required_authority,
        "consistency_unchanged": effective.consistency_mode
        == request.consistency_mode,
    }


def _retrieval_request(
    request: MemoryResolveRequest,
    interpretation: MemoryQueryInterpretation,
    *,
    source_snapshot_as_of: datetime | None = None,
) -> RetrievalRequest:
    reference_time = request.reference_time or datetime.now(UTC)
    return RetrievalRequest(
        route="L1",
        query=request.query,
        entities=request.entities,
        memory_types=request.memory_types,
        memory_intent=interpretation.retrieval_intent,
        evidence_need=interpretation.evidence_need,
        requested_scope=request.requested_scope,
        required_authority=request.required_authority,
        required_freshness=request.required_freshness,
        consistency=request.consistency_mode,
        causal_token=request.causal_token,
        as_of=source_snapshot_as_of or reference_time,
        reference_time=reference_time,
        limit=request.budget.max_results,
    )


def _narrow_values(existing: list[str], task_values: list[str]) -> list[str]:
    if not task_values:
        return list(existing)
    if not existing:
        return list(task_values)
    allowed = {value.casefold() for value in task_values}
    return [value for value in existing if value.casefold() in allowed]


def _access_outcome(
    body: dict[str, Any],
    interpretation: MemoryQueryInterpretation,
    *,
    decision_snapshot: DecisionSnapshot | None = None,
    progressive_context_evidence: bool = False,
) -> dict[str, Any]:
    raw_items = body.get("results")
    items = [dict(item) for item in raw_items if isinstance(item, dict)] if isinstance(
        raw_items, list
    ) else []
    query_plan = body.get("query_plan")
    planner_version = (
        query_plan.get("planner_version") if isinstance(query_plan, dict) else None
    )
    formation_replay_applied = (
        isinstance(planner_version, str)
        and "formation-semantic-replay-v" in planner_version
    )
    accepted_binding_ids = (
        tuple(decision_snapshot.accepted_evidence_ids)
        if decision_snapshot is not None
        else ()
    )
    uniform_strict_boundary = (
        formation_replay_applied
        and decision_snapshot is not None
        and not progressive_context_evidence
    )
    if uniform_strict_boundary:
        accepted_ids = set(accepted_binding_ids)
        # The complete candidate snapshot remains sealed in the Retrieval audit.
        # Only the governed evidence adopted by the immutable semantic decision
        # crosses the public response and Reader presentation boundary.
        items = [
            item
            for item in items
            if accepted_ids.intersection(_access_item_evidence_ids(item))
        ]
    raw_issues = body.get("open_issue_ids")
    open_issue_ids = sorted(
        {str(value) for value in raw_issues if isinstance(value, str)}
        if isinstance(raw_issues, list)
        else set()
    )
    degraded = sorted(
        str(value)
        for value in body.get("degraded_components", [])
        if isinstance(value, str)
    )
    abstention_reason = body.get("abstention_reason")
    unavailable = abstention_reason == "CANONICAL_UNAVAILABLE"
    if unavailable:
        status: MemoryResolveStatus = "UNAVAILABLE"
        availability: MemoryAvailability = "UNAVAILABLE"
    elif abstention_reason == "ACCESS_DENIED":
        status = "DENIED"
        availability = "AVAILABLE"
    elif open_issue_ids:
        status = "CONTESTED"
        availability = "DEGRADED"
    elif body.get("abstained") is True:
        status = "ABSENT" if abstention_reason == "NO_CANDIDATE" else "ABSTAINED"
        availability = "AVAILABLE"
    elif degraded or body.get("fallback_used") is True:
        status = "PARTIAL"
        availability = "DEGRADED"
    else:
        status = "HIT"
        availability = "AVAILABLE"
    evidence_refs = (
        list(accepted_binding_ids)
        if uniform_strict_boundary
        else sorted(
            {
                str(evidence_id)
                for item in items
                for evidence_id in _access_item_evidence_ids(item)
            }
        )
    )
    memory_query_ir = (
        query_plan.get("memory_query_ir") if isinstance(query_plan, dict) else None
    )
    outcome: dict[str, Any] = {
        "schema_version": "access-outcome-v0.1",
        "status": status,
        "items": items,
        "open_issue_ids": open_issue_ids,
        "evidence_refs": evidence_refs,
        "accepted_binding_evidence_refs": list(accepted_binding_ids),
        "consistency": body.get("consistency"),
        "canonical_position": body.get("snapshot"),
        "trace_id": body.get("retrieval_trace_id"),
        "degraded_components": degraded,
        "abstention_reason": abstention_reason,
        "context_receipt": None,
        "memory_intent": interpretation.intent,
        "requirement": interpretation.requirement,
        "availability": availability,
        "interpretation": {
            "version": interpretation.interpreter_version,
            "reason_code": interpretation.reason_code,
            "retrieval_intent": interpretation.retrieval_intent,
        },
        "derived_result": body.get("derived_result"),
        "sufficiency_decision": (
            body.get("progressive_l1", {}).get("terminal_sufficiency_decision")
            if isinstance(body.get("progressive_l1"), dict)
            else None
        ),
        "access_trace": body.get("access_trace"),
        "request_id": body.get("request_id"),
        "fallback_used": body.get("fallback_used") is True,
        "fallback_reason": body.get("fallback_reason"),
        "access_plan": body.get("access_plan"),
        "search_trace": body.get("progressive_l1"),
        "memory_query_ir": memory_query_ir,
    }
    if uniform_strict_boundary:
        outcome["_reader_evidence_boundary"] = "DECISION_ACCEPTED_ONLY"
    elif progressive_context_evidence and decision_snapshot is not None:
        # Context admission is governance-backed and budgeted; it does not
        # alter the immutable Binding/Sufficiency/Operator proof boundary.
        outcome["_reader_evidence_boundary"] = "GOVERNANCE_ADMITTED_SOFT_RANKED"
    return outcome


def _access_item_evidence_ids(item: dict[str, Any]) -> tuple[str, ...]:
    raw_ids = item.get("evidence_ids")
    evidence_ids = (
        [str(value) for value in raw_ids if isinstance(value, str)]
        if isinstance(raw_ids, list)
        else []
    )
    singular = item.get("evidence_id")
    if isinstance(singular, str):
        evidence_ids.append(singular)
    return tuple(sorted(set(evidence_ids)))


def _state_access_outcome(
    body: dict[str, Any], interpretation: MemoryQueryInterpretation
) -> dict[str, Any]:
    raw_items = body.get("items")
    items = [dict(item) for item in raw_items if isinstance(item, dict)] if isinstance(
        raw_items, list
    ) else []
    raw_issues = body.get("open_issue_ids")
    open_issue_ids = sorted(
        {str(value) for value in raw_issues if isinstance(value, str)}
        if isinstance(raw_issues, list)
        else set()
    )
    raw_evidence = body.get("evidence_refs")
    evidence_refs = sorted(
        {str(value) for value in raw_evidence if isinstance(value, str)}
        if isinstance(raw_evidence, list)
        else set()
    )
    status = body.get("status")
    if body.get("abstention_reason") == "ACCESS_DENIED":
        status = "DENIED"
    return {
        "schema_version": "access-outcome-v0.1",
        "status": status,
        "items": items,
        "open_issue_ids": open_issue_ids,
        "evidence_refs": evidence_refs,
        "consistency": body.get("consistency"),
        "canonical_position": body.get("canonical_position"),
        "trace_id": body.get("trace_id"),
        "degraded_components": (
            ["open_issue"] if body.get("status") == "CONTESTED" else []
        ),
        "abstention_reason": body.get("abstention_reason"),
        "context_receipt": None,
        "memory_intent": interpretation.intent,
        "requirement": "EXACT",
        "availability": body.get("availability"),
        "interpretation": {
            "version": interpretation.interpreter_version,
            "reason_code": "CANONICAL_STATE_ADDRESS_RESOLVED",
            "retrieval_intent": interpretation.retrieval_intent,
        },
        "derived_result": None,
        "access_trace": body.get("access_trace"),
        "request_id": body.get("request_id"),
        "fallback_used": False,
        "fallback_reason": None,
        "state_view_schema_version": body.get("schema_version"),
        "resolution": body.get("resolution"),
    }


def _not_needed_access_outcome(
    request: MemoryResolveRequest,
    interpretation: MemoryQueryInterpretation,
    request_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": "access-outcome-v0.1",
        "status": "ABSENT",
        "items": [],
        "open_issue_ids": [],
        "evidence_refs": [],
        "consistency": request.consistency_mode,
        "canonical_position": None,
        "trace_id": None,
        "degraded_components": [],
        "abstention_reason": "MEMORY_NOT_NEEDED",
        "context_receipt": None,
        "memory_intent": interpretation.intent,
        "requirement": interpretation.requirement,
        "availability": "AVAILABLE",
        "interpretation": {
            "version": interpretation.interpreter_version,
            "reason_code": interpretation.reason_code,
            "retrieval_intent": None,
        },
        "derived_result": None,
        "access_trace": {
            "schema_version": "access-trace-v0.1",
            "retrieval_trace_id": None,
            "runtime_request_id": request_id,
            "requested_intent": None,
            "planned_stage": "NONE",
            "attempted_stages": [],
            "terminal_stage": "NONE",
            "stop_reason": "QUERY_MEMORY_NOT_NEEDED",
            "fallback_reason": None,
            "canonical_position": None,
            "spans": {
                "runtime_kernel_ms": 0.0,
                "repository_sql_ms": 0.0,
            },
            "structural_cost": {
                "auxiliary_llm_calls": 0,
                "embedding_calls": 0,
                "vector_search_calls": 0,
                "reranker_calls": 0,
                "broad_head_scan_calls": 0,
            },
            "resolution_dimensions": None,
            "route_trace_complete": True,
            "trace_gap_reason": None,
        },
        "request_id": request_id,
        "fallback_used": False,
        "fallback_reason": None,
    }
