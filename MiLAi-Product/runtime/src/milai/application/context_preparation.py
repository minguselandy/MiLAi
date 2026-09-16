from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any, Literal
from uuid import UUID

from milai.application.context import ContextService
from milai.application.errors import ContextOperationError, TenantMismatch
from milai.application.recollection import RecollectionFacade
from milai.domain import (
    ClaimHeadCoverage,
    ContextBuildRequest,
    ContextValidationState,
    ContextValidationTokenCodec,
    ContextValidationTokenError,
    DependencyFrontier,
    MemorySlotCoverage,
    OpenIssueRevisionCoverage,
    PrepareContextRequest,
    RetrievalRequest,
    StateKeyHeadCoverage,
    need_covered,
)
from milai.persistence import DatabaseUnavailable, SessionContext
from milai.persistence.context_repository import ContextRepository

ExecutionRoute = Literal["NONE", "CACHE", "L0", "L1"]


@dataclass(frozen=True, slots=True)
class PrepareContextExecution:
    body: dict[str, Any]
    status_code: int = 200


class PrepareContextService:
    """One-wire governed context refresh and server-validated task-slot reuse."""

    def __init__(
        self,
        retrieval: RecollectionFacade,
        contexts: ContextService,
        repository: ContextRepository,
        tokens: ContextValidationTokenCodec,
    ) -> None:
        self._retrieval = retrieval
        self._contexts = contexts
        self._repository = repository
        self._tokens = tokens

    def prepare(
        self,
        context: SessionContext,
        principal_profile: str,
        request: PrepareContextRequest,
        request_id: str,
    ) -> PrepareContextExecution:
        if request.tenant_id is not None and request.tenant_id != context.tenant_id:
            raise TenantMismatch("body tenant does not match authenticated tenant")
        started = perf_counter()
        typed_policy_rejection = _typed_need_policy_rejection(request)
        if typed_policy_rejection is not None:
            return _with_timing(
                PrepareContextExecution(
                    _terminal_body(
                        request=request,
                        route=request.requested_route,
                        status="ABSTAIN",
                        reason=typed_policy_rejection,
                        validated_route=request.requested_route,
                        attempted_routes=[request.requested_route],
                        result="BLOCKED",
                        policy_override_reason=typed_policy_rejection,
                    )
                ),
                started,
            )
        binding_digest = _binding_digest(context, principal_profile, request)
        validated_route, policy_override_reason = _validated_route(request)
        cache_fallback_reason: str | None = None
        cache_validation_snapshot_ms = 0.0
        cache_validation_calls = 0
        try:
            previous = self._decode_previous(
                context,
                principal_profile,
                binding_digest,
                request.previous_validation_token,
            )
        except ContextOperationError:
            if validated_route == "CACHE":
                previous = None
                cache_fallback_reason = "BROKER_BOUND_VALIDATION_PROOF_INVALID"
            else:
                raise
        prepare_calls = (previous.prepare_calls if previous is not None else 0) + 1
        if prepare_calls > request.budget.max_prepare_context_calls:
            return _with_timing(
                self._budget_exhausted(
                    request,
                    "PREPARE_CONTEXT_CALL_BUDGET_EXHAUSTED",
                    route=validated_route,
                    validated_route=validated_route,
                    attempted_routes=[],
                ),
                started,
            )

        if validated_route == "NONE":
            return _with_timing(
                PrepareContextExecution(
                    _terminal_body(
                        request=request,
                        route="NONE",
                        status="UNCHANGED",
                        reason="NO_MEMORY_REQUESTED",
                        validated_route="NONE",
                        attempted_routes=[],
                        result="HIT",
                        policy_override_reason=policy_override_reason,
                    )
                ),
                started,
            )
        if validated_route == "CACHE":
            if cache_fallback_reason is None:
                (
                    cached,
                    cache_fallback_reason,
                    cache_validation_snapshot_ms,
                    cache_validation_calls,
                ) = self._validate_cached(
                    context,
                    principal_profile,
                    request,
                    previous,
                    prepare_calls,
                    started,
                    policy_override_reason,
                )
                if cached is not None:
                    return _with_timing(
                        cached,
                        started,
                        **(
                            {"validation_snapshot_ms": cache_validation_snapshot_ms}
                            if cache_validation_snapshot_ms
                            else {}
                        ),
                    )
            if self._deadline_exceeded(started, request):
                return _with_timing(
                    self._unavailable(
                        request,
                        "CACHE",
                        "MEMORY_DEADLINE_EXCEEDED",
                        validated_route="CACHE",
                        attempted_routes=["CACHE"],
                        fallback_reason=cache_fallback_reason,
                        policy_override_reason=policy_override_reason,
                    ),
                    started,
                    **(
                        {"validation_snapshot_ms": cache_validation_snapshot_ms}
                        if cache_validation_snapshot_ms
                        else {}
                    ),
                )

        full_recall_calls = (previous.full_recall_calls if previous is not None else 0) + 1
        delta_refreshes = previous.delta_refreshes if previous is not None else 0
        route: Literal["L0", "L1"]
        attempted_routes: list[str]
        if validated_route == "CACHE":
            route = "L0"
            attempted_routes = ["CACHE", "L0"]
        elif validated_route in {"L0", "L1"}:
            route = validated_route
            attempted_routes = [route]
        else:  # NONE returned above; keep the invariant explicit for type and runtime safety.
            raise AssertionError("memory retrieval requires an L0 or L1 execution route")
        trace_fallback_reason = cache_fallback_reason
        if request.event in {
            "MEMORY_AFFECTING_TOOL_RESULT",
            "CANONICAL_POSITION_CHANGED",
        }:
            delta_refreshes += 1
        if full_recall_calls > request.budget.max_full_recall_calls:
            return _with_timing(
                self._budget_exhausted(
                    request,
                    "FULL_RECALL_CALL_BUDGET_EXHAUSTED",
                    route="CACHE" if validated_route == "CACHE" else route,
                    validated_route=validated_route,
                    attempted_routes=(["CACHE"] if validated_route == "CACHE" else []),
                    fallback_reason=trace_fallback_reason,
                ),
                started,
            )
        if delta_refreshes > request.budget.max_delta_refreshes:
            return _with_timing(
                self._budget_exhausted(
                    request,
                    "DELTA_REFRESH_BUDGET_EXHAUSTED",
                    route="CACHE" if validated_route == "CACHE" else route,
                    validated_route=validated_route,
                    attempted_routes=(["CACHE"] if validated_route == "CACHE" else []),
                    fallback_reason=trace_fallback_reason,
                ),
                started,
            )

        retrieval_request = RetrievalRequest(
            route=route,
            query=None if route == "L0" else request.query,
            memory_intent=(
                request.memory_need_signature.intent_class
                if request.memory_need_signature is not None
                else None
            ),
            evidence_need=(
                request.memory_need_signature.evidence_need
                if request.memory_need_signature is not None
                else None
            ),
            claim_id=(
                request.state_key_ref.claim_id
                if route == "L0" and request.state_key_ref is not None
                else (request.known_claim_id if route == "L0" else None)
            ),
            subject_id=(
                request.state_key_ref.subject
                if route == "L0" and request.state_key_ref is not None
                else None
            ),
            predicate=(
                request.state_key_ref.predicate
                if route == "L0" and request.state_key_ref is not None
                else None
            ),
            claim_type=(
                request.state_key_ref.claim_type
                if route == "L0" and request.state_key_ref is not None
                else None
            ),
            consistency=request.consistency,
            requested_scope=request.requested_scope,
            required_authority=request.required_authority,
            limit=request.limit,
        )
        retrieval_started = perf_counter()
        try:
            retrieval = self._retrieval.retrieve(context, retrieval_request, request_id)
        except DatabaseUnavailable:
            return _with_timing(
                self._unavailable(
                    request,
                    route,
                    "CANONICAL_UNAVAILABLE",
                    validated_route=validated_route,
                    attempted_routes=attempted_routes,
                    fallback_reason=trace_fallback_reason,
                    policy_override_reason=policy_override_reason,
                ),
                started,
                retrieval_ms=_elapsed_ms(retrieval_started),
                **(
                    {"cache_validation_snapshot_ms": cache_validation_snapshot_ms}
                    if cache_validation_snapshot_ms
                    else {}
                ),
            )
        retrieval_ms = _elapsed_ms(retrieval_started)
        if retrieval.status_code == 503:
            return _with_timing(
                self._unavailable(
                    request,
                    route,
                    "CANONICAL_UNAVAILABLE",
                    stage_metrics=retrieval.body.get("stage_metrics"),
                    validated_route=validated_route,
                    attempted_routes=attempted_routes,
                    fallback_reason=(
                        trace_fallback_reason or retrieval.body.get("fallback_reason")
                    ),
                    policy_override_reason=policy_override_reason,
                ),
                started,
                retrieval_ms=retrieval_ms,
                **(
                    {"cache_validation_snapshot_ms": cache_validation_snapshot_ms}
                    if cache_validation_snapshot_ms
                    else {}
                ),
            )
        if retrieval.body.get("abstained") is True:
            return _with_timing(
                PrepareContextExecution(
                    _terminal_body(
                        request=request,
                        route=route,
                        status="ABSTAIN",
                        reason=str(retrieval.body.get("abstention_reason") or "NO_SAFE_MEMORY"),
                        canonical_position=_canonical_position(retrieval.body),
                        trace_pointer=retrieval.body.get("retrieval_trace_id"),
                        validated_route=validated_route,
                        attempted_routes=attempted_routes,
                        stage_metrics=retrieval.body.get("stage_metrics"),
                        fallback_reason=(
                            trace_fallback_reason or retrieval.body.get("fallback_reason")
                        ),
                        result="ABSTAINED",
                        policy_override_reason=policy_override_reason,
                    )
                ),
                started,
                retrieval_ms=retrieval_ms,
                **(
                    {"cache_validation_snapshot_ms": cache_validation_snapshot_ms}
                    if cache_validation_snapshot_ms
                    else {}
                ),
            )
        trace_value = retrieval.body.get("retrieval_trace_id")
        if not isinstance(trace_value, str):
            raise ContextOperationError("RETRIEVAL_TRACE_NOT_FOUND")
        context_build_started = perf_counter()
        built = self._contexts.build(
            context,
            ContextBuildRequest(
                retrieval_trace_id=UUID(trace_value),
                active_goal=request.active_goal,
                constraints=request.constraints,
                detail_level=_requested_detail_level(request),
                byte_budget=request.byte_budget,
                ttl_seconds=request.slot_ttl_seconds,
            ),
        )
        context_build_ms = _elapsed_ms(context_build_started)
        issue_values = built.sections.get("OPEN ISSUES", [])
        issues = (
            [value for value in issue_values if isinstance(value, dict)]
            if isinstance(issue_values, list)
            else []
        )
        issue_ids = sorted(
            str(issue["issue_id"]) for issue in issues if isinstance(issue.get("issue_id"), str)
        )
        validation_started = perf_counter()
        snapshot = self._repository.validation_snapshot(
            context, [UUID(issue_id) for issue_id in issue_ids]
        )
        validation_snapshot_ms = _elapsed_ms(validation_started)
        canonical_position = _canonical_position(retrieval.body)
        if snapshot.canonical_position != canonical_position:
            return _with_timing(
                self._unavailable(
                    request,
                    route,
                    "CANONICAL_POSITION_ADVANCED",
                    stage_metrics=retrieval.body.get("stage_metrics"),
                    validated_route=validated_route,
                    attempted_routes=attempted_routes,
                    fallback_reason=(
                        trace_fallback_reason or retrieval.body.get("fallback_reason")
                    ),
                    policy_override_reason=policy_override_reason,
                ),
                started,
                retrieval_ms=retrieval_ms,
                context_build_ms=context_build_ms,
                validation_snapshot_ms=validation_snapshot_ms,
                **(
                    {"cache_validation_snapshot_ms": cache_validation_snapshot_ms}
                    if cache_validation_snapshot_ms
                    else {}
                ),
            )
        if _issue_revision_digest(snapshot.open_issues) != _issue_revision_digest(issues):
            return _with_timing(
                self._unavailable(
                    request,
                    route,
                    "OPEN_ISSUE_REVISION_ADVANCED",
                    stage_metrics=retrieval.body.get("stage_metrics"),
                    validated_route=validated_route,
                    attempted_routes=attempted_routes,
                    fallback_reason=(
                        trace_fallback_reason or retrieval.body.get("fallback_reason")
                    ),
                    policy_override_reason=policy_override_reason,
                ),
                started,
                retrieval_ms=retrieval_ms,
                context_build_ms=context_build_ms,
                validation_snapshot_ms=validation_snapshot_ms,
                **(
                    {"cache_validation_snapshot_ms": cache_validation_snapshot_ms}
                    if cache_validation_snapshot_ms
                    else {}
                ),
            )
        if self._deadline_exceeded(started, request):
            return _with_timing(
                self._unavailable(
                    request,
                    route,
                    "MEMORY_DEADLINE_EXCEEDED",
                    stage_metrics=retrieval.body.get("stage_metrics"),
                    validated_route=validated_route,
                    attempted_routes=attempted_routes,
                    fallback_reason=(
                        trace_fallback_reason or retrieval.body.get("fallback_reason")
                    ),
                    policy_override_reason=policy_override_reason,
                ),
                started,
                retrieval_ms=retrieval_ms,
                context_build_ms=context_build_ms,
                validation_snapshot_ms=validation_snapshot_ms,
                **(
                    {"cache_validation_snapshot_ms": cache_validation_snapshot_ms}
                    if cache_validation_snapshot_ms
                    else {}
                ),
            )

        now = datetime.now(UTC)
        maximum_ttl = 30 if request.event == "ACTION_PROPOSED" else 86_400
        expires_at = now + timedelta(seconds=min(request.slot_ttl_seconds, maximum_ttl))
        capsule_id = str(built.capsule["capsule_id"])
        context_hash = str(built.capsule["content_hash"])
        slot_coverage = _slot_coverage(
            request=request,
            principal_profile=principal_profile,
            sections=built.sections,
            canonical_position=canonical_position,
        )
        state = ContextValidationState(
            tenant_id=context.tenant_id,
            principal_profile=principal_profile,
            binding_digest=binding_digest,
            canonical_position=canonical_position,
            issue_revision_digest=_issue_revision_digest(issues),
            issue_ids=tuple(issue_ids),
            slot_coverage=slot_coverage,
            capsule_id=capsule_id,
            context_hash=context_hash,
            prepare_calls=prepare_calls,
            full_recall_calls=full_recall_calls,
            delta_refreshes=delta_refreshes,
            validation_calls=(
                (previous.validation_calls if previous is not None else 0) + cache_validation_calls
            ),
            issued_at=now,
            expires_at=expires_at,
        )
        prior_ids = set(previous.issue_ids if previous is not None else ())
        current_ids = set(issue_ids)
        requested_evidence = (
            request.memory_need_signature.evidence_need
            if request.memory_need_signature is not None
            else None
        )
        if requested_evidence == "RAW_EVIDENCE" and slot_coverage.evidence_depth != "RAW_EVIDENCE":
            return _with_timing(
                PrepareContextExecution(
                    {
                        "route": route,
                        "status": "NEEDS_RECOVERY",
                        "reason": "RAW_EVIDENCE_RECOVERY_REQUIRED",
                        "context_capsule": {
                            "capsule_id": capsule_id,
                            "content_hash": context_hash,
                            "compression_level": built.compression_level,
                            "protected_sections": built.sections,
                        },
                        "context_delta": {
                            "status": "REPLACE",
                            "added_issue_ids": sorted(current_ids - prior_ids),
                            "removed_issue_ids": sorted(prior_ids - current_ids),
                        },
                        "relevant_open_issue_closure": issues,
                        "canonical_position": canonical_position,
                        "validation_token": None,
                        "memory_slot_coverage": slot_coverage.model_dump(mode="json"),
                        "prepared_detail_level": "OVERVIEW",
                        "requested_detail_level": "EVIDENCE_DETAIL",
                        "trace_pointer": trace_value,
                        "usage": _usage(state),
                        "current_state_envelope": _current_state_envelope(
                            route=route,
                            sections=built.sections,
                            canonical_position=canonical_position,
                            validation_handle=None,
                            trace_id=trace_value,
                        ),
                        "recall_execution_trace": _execution_trace(
                            request=request,
                            validated_route=validated_route,
                            attempted_routes=attempted_routes,
                            terminal_route=route,
                            result="MISS",
                            policy_override_reason=policy_override_reason,
                            stage_metrics=retrieval.body.get("stage_metrics"),
                            fallback_reason=(
                                trace_fallback_reason or "RAW_EVIDENCE_RECOVERY_REQUIRED"
                            ),
                            progressive_l1=retrieval.body.get("progressive_l1"),
                        ),
                    }
                ),
                started,
                retrieval_ms=retrieval_ms,
                context_build_ms=context_build_ms,
                validation_snapshot_ms=validation_snapshot_ms,
                **(
                    {"cache_validation_snapshot_ms": cache_validation_snapshot_ms}
                    if cache_validation_snapshot_ms
                    else {}
                ),
            )
        validation_handle = self._tokens.issue(state)
        return _with_timing(
            PrepareContextExecution(
                {
                    "route": (
                        "ACTION_VALIDATE"
                        if request.event == "ACTION_PROPOSED"
                        else (
                            "DELTA"
                            if request.event
                            in {"MEMORY_AFFECTING_TOOL_RESULT", "CANONICAL_POSITION_CHANGED"}
                            else route
                        )
                    ),
                    "status": "READY",
                    "reason": None,
                    "context_capsule": {
                        "capsule_id": capsule_id,
                        "content_hash": context_hash,
                        "compression_level": built.compression_level,
                        "protected_sections": built.sections,
                    },
                    "context_delta": {
                        "status": "REPLACE",
                        "added_issue_ids": sorted(current_ids - prior_ids),
                        "removed_issue_ids": sorted(prior_ids - current_ids),
                    },
                    "relevant_open_issue_closure": issues,
                    "canonical_position": canonical_position,
                    "validation_token": validation_handle,
                    "memory_slot_coverage": slot_coverage.model_dump(mode="json"),
                    "prepared_detail_level": _requested_detail_level(request),
                    "requested_detail_level": _requested_detail_level(request),
                    "trace_pointer": trace_value,
                    "usage": _usage(state),
                    "current_state_envelope": _current_state_envelope(
                        route=route,
                        sections=built.sections,
                        canonical_position=canonical_position,
                        validation_handle=validation_handle,
                        trace_id=trace_value,
                    ),
                    "recall_execution_trace": _execution_trace(
                        request=request,
                        validated_route=validated_route,
                        attempted_routes=attempted_routes,
                        terminal_route=route,
                        result="HIT",
                        policy_override_reason=policy_override_reason,
                        stage_metrics=retrieval.body.get("stage_metrics"),
                        fallback_reason=(
                            trace_fallback_reason or retrieval.body.get("fallback_reason")
                        ),
                        progressive_l1=retrieval.body.get("progressive_l1"),
                    ),
                }
            ),
            started,
            retrieval_ms=retrieval_ms,
            context_build_ms=context_build_ms,
            validation_snapshot_ms=validation_snapshot_ms,
            **(
                {"cache_validation_snapshot_ms": cache_validation_snapshot_ms}
                if cache_validation_snapshot_ms
                else {}
            ),
        )

    def _validate_cached(
        self,
        context: SessionContext,
        principal_profile: str,
        request: PrepareContextRequest,
        previous: ContextValidationState | None,
        prepare_calls: int,
        started: float,
        policy_override_reason: str | None,
    ) -> tuple[PrepareContextExecution | None, str | None, float, int]:
        if previous is None:
            return None, "NO_TASK_SLOT", 0.0, 0
        covered, coverage_miss_reason = need_covered(
            request.memory_need_signature,
            previous.slot_coverage,
            expected_policy_identity=_policy_identity(principal_profile, request),
        )
        if not covered:
            return (
                None,
                coverage_miss_reason or "CACHE_NEED_NOT_COVERED",
                0.0,
                0,
            )
        validation_calls = previous.validation_calls + 1
        if validation_calls > request.budget.max_validation_calls:
            return (
                self._budget_exhausted(
                    request,
                    "VALIDATION_CALL_BUDGET_EXHAUSTED",
                    route="CACHE",
                    validated_route="CACHE",
                    attempted_routes=["CACHE"],
                    fallback_reason="VALIDATION_CALL_BUDGET_EXHAUSTED",
                ),
                None,
                0.0,
                0,
            )
        validation_started = perf_counter()
        try:
            snapshot = self._repository.validation_snapshot(
                context, [UUID(issue_id) for issue_id in previous.issue_ids]
            )
        except DatabaseUnavailable:
            return (
                self._unavailable(
                    request,
                    "CACHE",
                    "CANONICAL_UNAVAILABLE",
                    validated_route="CACHE",
                    attempted_routes=["CACHE"],
                    policy_override_reason=policy_override_reason,
                ),
                None,
                _elapsed_ms(validation_started),
                1,
            )
        validation_snapshot_ms = _elapsed_ms(validation_started)
        current_digest = _issue_revision_digest(snapshot.open_issues)
        if snapshot.canonical_position != previous.canonical_position:
            return None, "CACHE_CANONICAL_POSITION_CHANGED", validation_snapshot_ms, 1
        if current_digest != previous.issue_revision_digest:
            return None, "CACHE_OPEN_ISSUE_REVISION_CHANGED", validation_snapshot_ms, 1
        if self._deadline_exceeded(started, request):
            return (
                self._unavailable(
                    request,
                    "CACHE",
                    "MEMORY_DEADLINE_EXCEEDED",
                    validated_route="CACHE",
                    attempted_routes=["CACHE"],
                    policy_override_reason=policy_override_reason,
                ),
                None,
                validation_snapshot_ms,
                1,
            )
        now = datetime.now(UTC)
        state = replace(
            previous,
            prepare_calls=prepare_calls,
            validation_calls=validation_calls,
            issued_at=now,
            expires_at=now + timedelta(seconds=request.slot_ttl_seconds),
        )
        return (
            PrepareContextExecution(
                {
                    "route": "CACHE",
                    "status": "UNCHANGED",
                    "reason": "VALIDATED_TASK_SLOT_REUSE",
                    "context_capsule": None,
                    "context_delta": {"status": "UNCHANGED"},
                    "relevant_open_issue_closure": [],
                    "canonical_position": state.canonical_position,
                    "validation_token": self._tokens.issue(state),
                    "memory_slot_coverage": state.slot_coverage.model_dump(mode="json"),
                    "prepared_detail_level": _requested_detail_level(request),
                    "requested_detail_level": _requested_detail_level(request),
                    "trace_pointer": None,
                    "usage": _usage(state),
                    "recall_execution_trace": _execution_trace(
                        request=request,
                        validated_route="CACHE",
                        attempted_routes=["CACHE"],
                        terminal_route="CACHE",
                        result="HIT",
                        policy_override_reason=policy_override_reason,
                    ),
                }
            ),
            None,
            validation_snapshot_ms,
            1,
        )

    def _decode_previous(
        self,
        context: SessionContext,
        profile: str,
        binding_digest: str,
        token: str | None,
    ) -> ContextValidationState | None:
        if token is None:
            return None
        try:
            return self._tokens.decode(
                token,
                expected_tenant_id=context.tenant_id,
                expected_profile=profile,
                expected_binding_digest=binding_digest,
            )
        except ContextValidationTokenError as exc:
            raise ContextOperationError("CONTEXT_VALIDATION_TOKEN_INVALID") from exc

    @staticmethod
    def _deadline_exceeded(started: float, request: PrepareContextRequest) -> bool:
        return (perf_counter() - started) * 1_000 > request.budget.memory_deadline_ms

    @staticmethod
    def _budget_exhausted(
        request: PrepareContextRequest,
        reason: str,
        *,
        route: str = "NONE",
        validated_route: str | None = None,
        attempted_routes: list[str] | None = None,
        fallback_reason: str | None = None,
    ) -> PrepareContextExecution:
        return PrepareContextExecution(
            _terminal_body(
                request=request,
                route=route,
                status="BUDGET_EXHAUSTED",
                reason=reason,
                validated_route=validated_route or route,
                attempted_routes=attempted_routes,
                fallback_reason=fallback_reason,
                result="BLOCKED",
            ),
            429,
        )

    @staticmethod
    def _unavailable(
        request: PrepareContextRequest,
        route: str,
        reason: str,
        *,
        stage_metrics: object = None,
        fallback_reason: object = None,
        validated_route: str | None = None,
        attempted_routes: list[str] | None = None,
        policy_override_reason: str | None = None,
    ) -> PrepareContextExecution:
        status = "ABSTAIN" if request.required_authority != "INFORMATIONAL" else "DEGRADED"
        return PrepareContextExecution(
            _terminal_body(
                request=request,
                route=route,
                status=status,
                reason=reason,
                validated_route=validated_route or route,
                attempted_routes=(
                    attempted_routes
                    if attempted_routes is not None
                    else ([] if route == "NONE" else [route])
                ),
                stage_metrics=stage_metrics,
                fallback_reason=fallback_reason,
                result=("ABSTAINED" if status == "ABSTAIN" else "ERROR"),
                policy_override_reason=(
                    policy_override_reason
                    if policy_override_reason is not None
                    else _validated_route(request)[1]
                ),
            ),
            503 if reason == "CANONICAL_UNAVAILABLE" else 200,
        )


def _binding_digest(
    context: SessionContext,
    principal_profile: str,
    request: PrepareContextRequest,
) -> str:
    return _sha256(
        {
            "tenant_id": str(context.tenant_id),
            "principal_profile": principal_profile,
            "session_id": request.session_id,
            "agent_id": request.agent_id,
            "profile_id": request.profile_id,
            "task_epoch": request.task_epoch,
            "active_goal": request.active_goal,
            "requested_scope": request.requested_scope,
            "required_authority": request.required_authority,
            "consistency": request.consistency,
            "limit": request.limit,
            "constraints": request.constraints,
            "byte_budget": request.byte_budget,
            "memory_token_budget": request.memory_token_budget,
            "slot_ttl_seconds": request.slot_ttl_seconds,
            "compiler_digest": request.compiler_digest,
            "router_digest": request.router_digest,
            "tokenizer_digest": request.tokenizer_digest,
            "policy_digest": request.policy_digest,
            "budget": request.budget.model_dump(mode="json"),
            "action_digest": request.action_digest,
        }
    )


def _issue_revision_digest(issues: list[dict[str, Any]]) -> str:
    values = [
        {
            "issue_id": issue.get("issue_id"),
            "target_claim_id": issue.get("target_claim_id"),
            "status": issue.get("status"),
            "issue_type": issue.get("issue_type"),
            "revision": issue.get("revision"),
            "required_authority": issue.get("required_authority"),
            "scope_predicate": issue.get("scope_predicate"),
            "discharge_rule": issue.get("discharge_rule"),
            "branches": issue.get("branches"),
        }
        for issue in issues
    ]
    values.sort(key=lambda value: str(value["issue_id"]))
    return _sha256(values)


def _canonical_position(body: dict[str, Any]) -> int:
    snapshot = body.get("snapshot")
    position = snapshot.get("canonical_outbox_sequence") if isinstance(snapshot, dict) else None
    if isinstance(position, bool) or not isinstance(position, int) or position < 0:
        raise ContextOperationError("CONTEXT_CANONICAL_POSITION_MISSING")
    return position


def _usage(state: ContextValidationState) -> dict[str, int]:
    return {
        "prepare_context_calls": state.prepare_calls,
        "full_recall_calls": state.full_recall_calls,
        "delta_refreshes": state.delta_refreshes,
        "validation_calls": state.validation_calls,
    }


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1_000, 3)


def _with_timing(
    execution: PrepareContextExecution,
    started: float,
    **segments: float,
) -> PrepareContextExecution:
    body = dict(execution.body)
    body["timing"] = {
        **{key: round(value, 3) for key, value in segments.items()},
        "runtime_total_ms": _elapsed_ms(started),
    }
    return PrepareContextExecution(body, execution.status_code)


def _terminal_body(
    *,
    request: PrepareContextRequest,
    route: str,
    status: str,
    reason: str,
    canonical_position: int | None = None,
    trace_pointer: object = None,
    validated_route: str | None = None,
    attempted_routes: list[str] | None = None,
    stage_metrics: object = None,
    fallback_reason: object = None,
    next_route_recommended: str | None = None,
    result: str,
    policy_override_reason: str | None = None,
) -> dict[str, Any]:
    runtime_validated_route = validated_route or route
    return {
        "route": route,
        "status": status,
        "reason": reason,
        "context_capsule": None,
        "context_delta": {"status": "UNCHANGED"},
        "relevant_open_issue_closure": [],
        "canonical_position": canonical_position,
        "validation_token": None,
        "memory_slot_coverage": None,
        "prepared_detail_level": None,
        "requested_detail_level": _requested_detail_level(request),
        "trace_pointer": trace_pointer,
        "usage": None,
        "recall_execution_trace": _execution_trace(
            request=request,
            validated_route=runtime_validated_route,
            attempted_routes=(
                attempted_routes
                if attempted_routes is not None
                else ([] if runtime_validated_route == "NONE" else [runtime_validated_route])
            ),
            terminal_route=route,
            result=result,
            policy_override_reason=policy_override_reason,
            stage_metrics=stage_metrics,
            fallback_reason=fallback_reason,
            next_route_recommended=next_route_recommended,
        ),
        "current_state_envelope": (
            {
                "status": (
                    "CANONICAL_UNAVAILABLE"
                    if result == "ERROR"
                    else ("BLOCKED" if result in {"BLOCKED", "ABSTAINED"} else "MISS")
                ),
                "claims": [],
                "open_issues": [],
                "canonical_position": canonical_position,
                "slot_validation_handle": None,
                "trace_id": trace_pointer if isinstance(trace_pointer, str) else None,
            }
            if route == "L0"
            else None
        ),
    }


def _execution_trace(
    *,
    request: PrepareContextRequest,
    validated_route: str,
    attempted_routes: list[str],
    terminal_route: str,
    result: str,
    policy_override_reason: str | None = None,
    stage_metrics: object = None,
    fallback_reason: object = None,
    next_route_recommended: object = None,
    progressive_l1: object = None,
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    if isinstance(stage_metrics, dict) and isinstance(stage_metrics.get("counts"), dict):
        counts = {
            str(key): int(value)
            for key, value in stage_metrics["counts"].items()
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        }
    trace: dict[str, Any] = {
        "need_signature_id": request.need_signature_id,
        "requested_route": request.requested_route,
        "planned_route": validated_route,
        "validated_route": validated_route,
        "attempted_routes": attempted_routes,
        "terminal_route": terminal_route,
        "result": result,
        "policy_override_reason": policy_override_reason,
        "fallback_reason": fallback_reason if isinstance(fallback_reason, str) else None,
        "next_route_recommended": (
            next_route_recommended
            if next_route_recommended in {"NONE", "CACHE", "L0", "L1"}
            else None
        ),
        "route_trace_complete": True,
        "trace_gap_reason": None,
        "query_embedding_calls": counts.get("query_embedding_ms", 0),
        "vector_calls": counts.get("vector_ms", 0),
        "reranker_calls": counts.get("reranker_ms", 0),
        "exact_calls": counts.get("exact_ms", 0),
        "fts_calls": counts.get("fts_ms", 0),
        "l0_calls": counts.get("l0_ms", 0),
    }
    if isinstance(progressive_l1, dict):
        trace["progressive_l1"] = progressive_l1
    return trace


def _validated_route(request: PrepareContextRequest) -> tuple[ExecutionRoute, str | None]:
    if (
        request.event in {"MEMORY_AFFECTING_TOOL_RESULT", "CANONICAL_POSITION_CHANGED"}
        and request.requested_route in {"NONE", "CACHE"}
        and not (
            request.requested_route == "CACHE"
            and request.memory_need_signature is not None
            and request.memory_need_signature.temporal_need == "CURRENT"
            and bool(
                request.memory_need_signature.claim_ids or request.memory_need_signature.state_keys
            )
        )
    ):
        return "L1", "CANONICAL_CHANGE_REQUIRES_REFRESH"
    if request.event == "ACTION_PROPOSED" and request.requested_route != "L1":
        return "L1", "ACTION_SAFE_REQUIRES_CANONICAL_RECALL"
    if (
        request.requested_route == "L0"
        and request.known_claim_id is None
        and request.state_key_ref is None
    ):
        return "L1", "L0_LOCATOR_UNAVAILABLE"
    return request.requested_route, None


def _typed_need_policy_rejection(request: PrepareContextRequest) -> str | None:
    signature = request.memory_need_signature
    if signature is not None:
        if signature.scope != request.requested_scope:
            return "NEED_SCOPE_MISMATCH"
        if any(key.scope != request.requested_scope for key in signature.state_keys):
            return "NEED_STATE_KEY_SCOPE_MISMATCH"
        if signature.required_authority != request.required_authority:
            return "NEED_AUTHORITY_MISMATCH"
        if signature.consistency_floor != request.consistency:
            return "NEED_CONSISTENCY_MISMATCH"
    if request.state_key_ref is not None and request.state_key_ref.scope != request.requested_scope:
        return "STATE_KEY_SCOPE_MISMATCH"
    return None


def _policy_identity(principal_profile: str, request: PrepareContextRequest) -> str:
    return _sha256(
        {
            "principal_profile": principal_profile,
            "profile_id": request.profile_id,
            "scope": request.requested_scope,
            "authority": request.required_authority,
            "consistency": request.consistency,
            "policy_digest": request.policy_digest,
        }
    )


def _slot_coverage(
    *,
    request: PrepareContextRequest,
    principal_profile: str,
    sections: dict[str, object],
    canonical_position: int,
) -> MemorySlotCoverage:
    raw_claims = sections.get("ACTIVE STATE", [])
    claims = (
        [value for value in raw_claims if isinstance(value, dict)]
        if isinstance(raw_claims, list)
        else []
    )
    claim_heads: dict[str, ClaimHeadCoverage] = {}
    claim_rows: dict[str, dict[str, object]] = {}
    for claim in claims:
        try:
            claim_uuid = UUID(str(claim["claim_id"]))
            version_id = UUID(str(claim["claim_version_id"]))
        except (KeyError, TypeError, ValueError):
            continue
        claim_heads[str(claim_uuid)] = ClaimHeadCoverage(
            claim_id=claim_uuid,
            claim_version_id=version_id,
        )
        claim_rows[str(claim_uuid)] = claim

    state_keys: dict[tuple[str, str, str, str], StateKeyHeadCoverage] = {}
    for claim_id_text, claim in claim_rows.items():
        subject = claim.get("subject_id")
        predicate = claim.get("predicate")
        claim_type = claim.get("claim_type")
        if not all(isinstance(value, str) and value for value in (subject, predicate, claim_type)):
            continue
        head = claim_heads[claim_id_text]
        identity = (
            _canonical_json(request.requested_scope),
            str(subject),
            str(predicate),
            str(claim_type),
        )
        state_keys[identity] = StateKeyHeadCoverage(
            scope=request.requested_scope,
            subject=str(subject),
            predicate=str(predicate),
            claim_type=str(claim_type),
            claim_id=head.claim_id,
            claim_version_id=head.claim_version_id,
        )

    requested_key = request.state_key_ref
    if requested_key is not None and claim_heads:
        matched_head = (
            claim_heads.get(str(requested_key.claim_id))
            if requested_key.claim_id is not None
            else (next(iter(claim_heads.values())) if len(claim_heads) == 1 else None)
        )
        if matched_head is not None:
            identity = (
                _canonical_json(requested_key.scope),
                requested_key.subject,
                requested_key.predicate,
                requested_key.claim_type,
            )
            state_keys[identity] = StateKeyHeadCoverage(
                scope=requested_key.scope,
                subject=requested_key.subject,
                predicate=requested_key.predicate,
                claim_type=requested_key.claim_type,
                claim_id=matched_head.claim_id,
                claim_version_id=matched_head.claim_version_id,
            )

    raw_issues = sections.get("OPEN ISSUES", [])
    issues = (
        [value for value in raw_issues if isinstance(value, dict)]
        if isinstance(raw_issues, list)
        else []
    )
    issue_revisions: dict[str, OpenIssueRevisionCoverage] = {}
    for issue in issues:
        try:
            issue_id = UUID(str(issue["issue_id"]))
            revision = int(issue["revision"])
        except (KeyError, TypeError, ValueError):
            continue
        if revision < 0:
            continue
        issue_revisions[str(issue_id)] = OpenIssueRevisionCoverage(
            issue_id=issue_id,
            revision=revision,
        )

    evidence_values = sections.get("RETRIEVED EVIDENCE", [])
    evidence = (
        [value for value in evidence_values if isinstance(value, dict)]
        if isinstance(evidence_values, list)
        else []
    )
    evidence_depth: Literal["NONE", "SUPPORT_POINTERS", "RAW_EVIDENCE"] = "NONE"
    if any("content" in item for item in evidence):
        evidence_depth = "RAW_EVIDENCE"
    elif evidence:
        evidence_depth = "SUPPORT_POINTERS"

    temporal = (
        request.memory_need_signature.temporal_need
        if request.memory_need_signature is not None
        else "CURRENT"
    )
    return MemorySlotCoverage(
        scope=request.requested_scope,
        authority_supported=request.required_authority,
        consistency_supported=request.consistency,
        claim_ids_and_head_versions=[claim_heads[key] for key in sorted(claim_heads)],
        state_keys_and_head_versions=[state_keys[key] for key in sorted(state_keys)],
        open_issue_ids_and_revisions=[issue_revisions[key] for key in sorted(issue_revisions)],
        temporal_coverage=temporal,
        evidence_depth=evidence_depth,
        policy_identity=_policy_identity(principal_profile, request),
        dependency_frontier=DependencyFrontier(canonical_position=canonical_position),
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _current_state_envelope(
    *,
    route: str,
    sections: dict[str, object],
    canonical_position: int,
    validation_handle: str | None,
    trace_id: str,
) -> dict[str, Any] | None:
    if route != "L0":
        return None
    claim_values = sections.get("ACTIVE STATE", [])
    issue_values = sections.get("OPEN ISSUES", [])
    claims = (
        [dict(value) for value in claim_values if isinstance(value, dict)]
        if isinstance(claim_values, list)
        else []
    )
    issues = (
        [dict(value) for value in issue_values if isinstance(value, dict)]
        if isinstance(issue_values, list)
        else []
    )
    return {
        "status": "HIT" if claims else "MISS",
        "claims": claims,
        "open_issues": issues,
        "canonical_position": canonical_position,
        "slot_validation_handle": validation_handle,
        "trace_id": trace_id,
    }


def _requested_detail_level(
    request: PrepareContextRequest,
) -> Literal["ABSTRACT", "OVERVIEW", "EVIDENCE_DETAIL"]:
    signature = request.memory_need_signature
    if signature is None or signature.evidence_need == "SUPPORT_POINTERS":
        return "OVERVIEW"
    if signature.evidence_need == "NONE":
        return "ABSTRACT"
    return "EVIDENCE_DETAIL"


def _sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
