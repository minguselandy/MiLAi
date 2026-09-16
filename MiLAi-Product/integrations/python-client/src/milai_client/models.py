from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol, Self, cast

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from milai_client.memory_need import MemoryNeedSignature, StateKeyRef

RecallStatus = Literal["OK", "DEGRADED", "ABSTAINED"]
MemoryResolveStatus = Literal[
    "HIT",
    "PARTIAL",
    "CONTESTED",
    "ABSENT",
    "ABSTAINED",
    "DENIED",
    "UNAVAILABLE",
]
Authority = Literal["INFORMATIONAL", "ACTION_SAFE", "USER_CONFIRMED"]
Consistency = Literal["EVENTUAL", "READ_YOUR_WRITES", "CANONICAL_REQUIRED"]
RecallExecutionRoute = Literal["NONE", "CACHE", "L0", "L1"]
RecallExecutionResult = Literal["HIT", "MISS", "BLOCKED", "ABSTAINED", "ERROR"]
PrepareContextEvent = Literal[
    "TASK_START",
    "GOAL_CHANGED",
    "EXPLICIT_MEMORY_REQUEST",
    "KNOWN_OBJECT",
    "TOOL_RESULT",
    "MEMORY_AFFECTING_TOOL_RESULT",
    "MODEL_RETRY",
    "CANONICAL_POSITION_CHANGED",
    "ACTION_PROPOSED",
]
AccessOutcomeStatus = Literal[
    "NO_MEMORY_NEEDED",
    "CONTEXT_READY_CURRENT",
    "MEMORY_REQUIRED_BUT_UNAVAILABLE",
    "MEMORY_INSUFFICIENT",
    "GOVERNANCE_BLOCKED",
]
ExecutionAction = Literal["CONTINUE", "RETRY", "ASK_USER", "ABSTAIN"]
ProviderExecution = Literal["ALLOWED", "PROHIBITED"]
AccessTerminalStage = Literal["NONE", "CACHE", "EXACT", "GATE", "SUFFICIENCY", "TRANSPORT"]
_CONSISTENCY_RANK = {"EVENTUAL": 0, "READ_YOUR_WRITES": 1, "CANONICAL_REQUIRED": 2}
_ACCESS_OUTCOME_MATRIX = {
    "NO_MEMORY_NEEDED": ("CONTINUE", "ALLOWED"),
    "CONTEXT_READY_CURRENT": ("CONTINUE", "ALLOWED"),
    "MEMORY_REQUIRED_BUT_UNAVAILABLE": ("RETRY", "PROHIBITED"),
    "MEMORY_INSUFFICIENT": ("ASK_USER", "PROHIBITED"),
    "GOVERNANCE_BLOCKED": ("ABSTAIN", "PROHIBITED"),
}


@dataclass(frozen=True, slots=True)
class AccessOutcome:
    """Single Host-facing truth for memory readiness and provider permission."""

    status: AccessOutcomeStatus
    execution_action: ExecutionAction
    provider_execution: ProviderExecution
    terminal_stage: AccessTerminalStage
    context_digest: str | None
    canonical_position: int | None
    reason_code: str | None
    trace_id: str

    def __post_init__(self) -> None:
        expected = _ACCESS_OUTCOME_MATRIX.get(self.status)
        if expected != (self.execution_action, self.provider_execution):
            raise ValueError("AccessOutcome violates the frozen status/action/provider matrix")
        if self.terminal_stage not in {
            "NONE",
            "CACHE",
            "EXACT",
            "GATE",
            "SUFFICIENCY",
            "TRANSPORT",
        }:
            raise ValueError("AccessOutcome terminal stage is invalid")
        if self.context_digest is not None and (
            not isinstance(self.context_digest, str)
            or len(self.context_digest) != 64
            or any(character not in "0123456789abcdef" for character in self.context_digest)
        ):
            raise ValueError("AccessOutcome context digest must be lowercase SHA-256")
        if self.canonical_position is not None and (
            isinstance(self.canonical_position, bool)
            or not isinstance(self.canonical_position, int)
            or self.canonical_position < 0
        ):
            raise ValueError("AccessOutcome canonical position must be non-negative")
        if self.reason_code is not None and (
            not isinstance(self.reason_code, str) or not self.reason_code.strip()
        ):
            raise ValueError("AccessOutcome reason code must be non-empty or null")
        if not isinstance(self.trace_id, str) or not self.trace_id.strip():
            raise ValueError("AccessOutcome trace ID is required")
        if self.status == "CONTEXT_READY_CURRENT" and self.context_digest is None:
            raise ValueError("current Context outcome requires rendered Context digest")
        if self.status != "CONTEXT_READY_CURRENT" and self.context_digest is not None:
            raise ValueError("only current Context outcome may carry a Context digest")

    def to_api(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "execution_action": self.execution_action,
            "provider_execution": self.provider_execution,
            "terminal_stage": self.terminal_stage,
            "context_digest": self.context_digest,
            "canonical_position": self.canonical_position,
            "reason_code": self.reason_code,
            "trace_id": self.trace_id,
        }


@dataclass(frozen=True, slots=True)
class RecallExecutionTrace(Mapping[str, Any]):
    need_signature_id: str | None
    requested_route: RecallExecutionRoute
    planned_route: RecallExecutionRoute
    attempted_routes: tuple[RecallExecutionRoute, ...]
    terminal_route: RecallExecutionRoute
    result: RecallExecutionResult
    policy_override_reason: str | None
    fallback_reason: str | None
    next_route_recommended: RecallExecutionRoute | None
    query_embedding_calls: int
    vector_calls: int
    reranker_calls: int
    exact_calls: int
    fts_calls: int
    l0_calls: int
    route_trace_complete: bool = True
    trace_gap_reason: str | None = None
    progressive_l1: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        routes = {"NONE", "CACHE", "L0", "L1"}
        if (
            self.requested_route not in routes
            or self.planned_route not in routes
            or self.terminal_route not in routes
            or any(route not in routes for route in self.attempted_routes)
        ):
            raise ValueError("recall execution trace route is invalid")
        if self.result not in {"HIT", "MISS", "BLOCKED", "ABSTAINED", "ERROR"}:
            raise ValueError("recall execution trace result is invalid")
        if self.requested_route != self.planned_route and self.policy_override_reason is None:
            raise ValueError("route override requires an explicit policy reason")
        if (
            self.attempted_routes
            and self.attempted_routes[0] != self.planned_route
            and self.policy_override_reason is None
        ):
            raise ValueError("first attempted route differs without an override")
        if (
            self.terminal_route
            != (self.attempted_routes[-1] if self.attempted_routes else self.planned_route)
            and self.fallback_reason is None
        ):
            raise ValueError("terminal route differs without a fallback reason")
        if any(value < 0 for value in self._counters()):
            raise ValueError("recall execution trace counters must be non-negative")
        if not self.route_trace_complete or self.trace_gap_reason is not None:
            raise ValueError("typed recall execution trace must be complete")

    @classmethod
    def from_api(cls, value: object) -> RecallExecutionTrace:
        if not isinstance(value, Mapping):
            raise ValueError("recall execution trace must be an object")
        attempted = value.get("attempted_routes")
        if not isinstance(attempted, list) or not all(
            isinstance(route, str) for route in attempted
        ):
            raise ValueError("recall execution attempted routes are invalid")
        planned_route = value.get("planned_route")
        validated_route = value.get("validated_route")
        if planned_route is None:
            planned_route = validated_route
        elif validated_route is not None and validated_route != planned_route:
            raise ValueError(
                "recall execution planned route conflicts with validated compatibility route"
            )
        return cls(
            need_signature_id=_optional_string(value.get("need_signature_id")),
            requested_route=cast(RecallExecutionRoute, value.get("requested_route")),
            planned_route=cast(RecallExecutionRoute, planned_route),
            attempted_routes=tuple(cast(RecallExecutionRoute, route) for route in attempted),
            terminal_route=cast(RecallExecutionRoute, value.get("terminal_route")),
            result=cast(RecallExecutionResult, value.get("result")),
            policy_override_reason=_optional_string(value.get("policy_override_reason")),
            fallback_reason=_optional_string(value.get("fallback_reason")),
            next_route_recommended=(
                cast(RecallExecutionRoute, value["next_route_recommended"])
                if value.get("next_route_recommended") is not None
                else None
            ),
            query_embedding_calls=_nonnegative_int(value.get("query_embedding_calls")),
            vector_calls=_nonnegative_int(value.get("vector_calls")),
            reranker_calls=_nonnegative_int(value.get("reranker_calls")),
            exact_calls=_nonnegative_int(value.get("exact_calls")),
            fts_calls=_nonnegative_int(value.get("fts_calls")),
            l0_calls=_nonnegative_int(value.get("l0_calls")),
            route_trace_complete=value.get("route_trace_complete") is True,
            trace_gap_reason=_optional_string(value.get("trace_gap_reason")),
            progressive_l1=(
                dict(value["progressive_l1"])
                if isinstance(value.get("progressive_l1"), Mapping)
                else None
            ),
        )

    def to_api(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "need_signature_id": self.need_signature_id,
            "requested_route": self.requested_route,
            "planned_route": self.planned_route,
            "validated_route": self.validated_route,
            "attempted_routes": list(self.attempted_routes),
            "terminal_route": self.terminal_route,
            "result": self.result,
            "policy_override_reason": self.policy_override_reason,
            "fallback_reason": self.fallback_reason,
            "next_route_recommended": self.next_route_recommended,
            "route_trace_complete": self.route_trace_complete,
            "trace_gap_reason": self.trace_gap_reason,
            "query_embedding_calls": self.query_embedding_calls,
            "vector_calls": self.vector_calls,
            "reranker_calls": self.reranker_calls,
            "exact_calls": self.exact_calls,
            "fts_calls": self.fts_calls,
            "l0_calls": self.l0_calls,
        }
        if self.progressive_l1 is not None:
            value["progressive_l1"] = self.progressive_l1
        return value

    @property
    def validated_route(self) -> RecallExecutionRoute:
        """Compatibility view of the authoritative planned route."""

        return self.planned_route

    def __getitem__(self, key: str) -> Any:
        return self.to_api()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_api())

    def __len__(self) -> int:
        return len(self.to_api())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, RecallExecutionTrace):
            return self.to_api() == other.to_api()
        if isinstance(other, Mapping):
            return self.to_api() == dict(other)
        return False

    def _counters(self) -> tuple[int, ...]:
        return (
            self.query_embedding_calls,
            self.vector_calls,
            self.reranker_calls,
            self.exact_calls,
            self.fts_calls,
            self.l0_calls,
        )


@dataclass(frozen=True, slots=True, init=False)
class AgentRecallPolicy:
    """Immutable host-owned recall boundary; model inputs cannot broaden it."""

    _scope_json: str = field(repr=False)
    authority: Authority
    consistency_floor: Consistency
    max_limit: int

    def __init__(
        self,
        *,
        scope: dict[str, Any],
        authority: Authority = "ACTION_SAFE",
        consistency_floor: Consistency = "CANONICAL_REQUIRED",
        max_limit: int = 5,
    ) -> None:
        if authority not in {"INFORMATIONAL", "ACTION_SAFE", "USER_CONFIRMED"}:
            raise ValueError("unknown host authority")
        if consistency_floor not in _CONSISTENCY_RANK:
            raise ValueError("unknown host consistency floor")
        if not 1 <= max_limit <= 50:
            raise ValueError("host maximum recall limit must be between 1 and 50")
        try:
            encoded = json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            normalized = json.loads(encoded)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("host recall scope must be JSON serializable") from exc
        if not isinstance(normalized, dict):
            raise ValueError("host recall scope must be an object")
        if authority == "ACTION_SAFE" and not normalized:
            raise ValueError("ACTION_SAFE recall requires a non-empty host scope")
        object.__setattr__(self, "_scope_json", encoded)
        object.__setattr__(self, "authority", authority)
        object.__setattr__(self, "consistency_floor", consistency_floor)
        object.__setattr__(self, "max_limit", max_limit)

    @property
    def scope(self) -> dict[str, Any]:
        value = json.loads(self._scope_json)
        if not isinstance(value, dict):  # pragma: no cover - constructor invariant
            raise RuntimeError("invalid frozen host scope")
        return value

    def effective_consistency(self, requested: str | None = None) -> Consistency:
        if requested is None:
            return self.consistency_floor
        if requested not in _CONSISTENCY_RANK:
            raise ValueError("unknown requested consistency")
        if _CONSISTENCY_RANK[requested] < _CONSISTENCY_RANK[self.consistency_floor]:
            return self.consistency_floor
        return cast(Consistency, requested)

    def effective_limit(self, requested: int | None = None) -> int:
        if requested is None:
            return self.max_limit
        return min(self.max_limit, max(1, requested))


@dataclass(frozen=True, slots=True)
class CapabilityDocument:
    api_version: str
    contract_version: str
    runtime_version: str
    profile: str
    capabilities: tuple[str, ...]
    routes: tuple[str, ...]
    consistency_modes: tuple[str, ...]
    agent_profiles: tuple[str, ...]
    features: dict[str, bool]
    limits: dict[str, int]
    data_mode: str
    schema_status: str
    implementation_status: str
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_api(cls, body: dict[str, Any]) -> CapabilityDocument:
        return cls(
            api_version=str(body.get("api_version", "")),
            contract_version=str(body.get("contract_version", "")),
            runtime_version=str(body.get("runtime_version", "")),
            profile=str(body.get("profile", "")),
            capabilities=_string_tuple(body.get("capabilities")),
            routes=_string_tuple(body.get("routes")),
            consistency_modes=_string_tuple(body.get("consistency_modes")),
            agent_profiles=_string_tuple(body.get("agent_profiles")),
            features=_bool_dict(body.get("features")),
            limits=_int_dict(body.get("limits")),
            data_mode=str(body.get("data_mode", "")),
            schema_status=str(body.get("schema_status", "")),
            implementation_status=str(body.get("implementation_status", "")),
            raw=body,
        )

    @property
    def compatible(self) -> bool:
        return (
            self.api_version == "1"
            and self.contract_version == "agent.v1"
            and {"L0", "L1"}.issubset(self.routes)
            and "CANONICAL_REQUIRED" in self.consistency_modes
        )


@dataclass(frozen=True, slots=True)
class HealthStatus:
    live: bool
    ready: bool
    dependencies: dict[str, str]
    schema_status: str
    implementation_status: str
    raw_live: dict[str, Any] = field(repr=False)
    raw_ready: dict[str, Any] = field(repr=False)


@dataclass(frozen=True, slots=True)
class SystemWatermarks:
    canonical_snapshot: int
    watermarks: tuple[dict[str, Any], ...]
    request_id: str | None
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_api(cls, body: dict[str, Any]) -> SystemWatermarks:
        snapshot = body.get("canonical_snapshot")
        if not isinstance(snapshot, int) or isinstance(snapshot, bool) or snapshot < 0:
            raise ValueError("canonical_snapshot must be a non-negative integer")
        return cls(
            canonical_snapshot=snapshot,
            watermarks=tuple(_dict_list(body.get("watermarks"))),
            request_id=_optional_string(body.get("request_id")),
            raw=body,
        )


@dataclass(frozen=True, slots=True)
class RecallRequest:
    query: str
    scope: dict[str, Any] = field(default_factory=dict)
    authority: Authority = "INFORMATIONAL"
    consistency: Consistency = "EVENTUAL"
    limit: int = 5
    causal_token: str | None = None

    def to_api(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "route": "L1",
            "query": self.query,
            "requested_scope": self.scope,
            "required_authority": self.authority,
            "consistency": self.consistency,
            "limit": self.limit,
        }
        if self.causal_token is not None:
            result["causal_token"] = self.causal_token
        return result


@dataclass(frozen=True, slots=True)
class ExactRecallRequest:
    claim_id: str | None = None
    subject_id: str | None = None
    predicate: str | None = None
    claim_type: str | None = None
    scope: dict[str, Any] = field(default_factory=dict)
    authority: Authority = "INFORMATIONAL"
    consistency: Consistency = "CANONICAL_REQUIRED"

    def to_api(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "route": "L0",
            "claim_id": self.claim_id,
            "subject_id": self.subject_id,
            "predicate": self.predicate,
            "claim_type": self.claim_type,
            "requested_scope": self.scope,
            "required_authority": self.authority,
            "consistency": self.consistency,
        }
        return {key: value for key, value in result.items() if value is not None}


@dataclass(frozen=True, slots=True)
class RecallEnvelope:
    status: RecallStatus
    items: list[dict[str, Any]]
    issues: list[str]
    trace_id: str | None
    consistency: str
    canonical_position: dict[str, Any] | None
    degraded_components: list[str]
    fallback_used: bool
    fallback_reason: str | None
    abstention_reason: str | None
    request_id: str | None
    context_capsule_id: str | None
    raw: dict[str, Any] = field(repr=False)
    derived_result: dict[str, Any] | None = None

    @classmethod
    def from_api(cls, body: dict[str, Any]) -> RecallEnvelope:
        items = _dict_list(body.get("results"))
        issue_ids = sorted(
            {
                *(str(issue_id) for issue_id in body.get("open_issue_ids", [])),
                *(str(issue_id) for item in items for issue_id in item.get("open_issue_ids", [])),
            }
        )
        degraded = [str(value) for value in body.get("degraded_components", [])]
        abstained = bool(body.get("abstained", False))
        status: RecallStatus = "OK"
        if degraded or body.get("fallback_used"):
            status = "DEGRADED"
        if abstained:
            status = "ABSTAINED"
            items = []
        snapshot = body.get("snapshot")
        return cls(
            status=status,
            items=items,
            issues=issue_ids,
            trace_id=_optional_string(body.get("retrieval_trace_id")),
            consistency=str(body.get("consistency", "UNKNOWN")),
            canonical_position=snapshot if isinstance(snapshot, dict) else None,
            degraded_components=degraded,
            fallback_used=bool(body.get("fallback_used", False)),
            fallback_reason=_optional_string(body.get("fallback_reason")),
            abstention_reason=_optional_string(body.get("abstention_reason")),
            request_id=_optional_string(body.get("request_id")),
            context_capsule_id=_optional_string(body.get("context_capsule_id")),
            derived_result=(
                dict(body["derived_result"])
                if isinstance(body.get("derived_result"), dict)
                else None
            ),
            raw=body,
        )


@dataclass(frozen=True, slots=True)
class ContextReceipt:
    context_capsule_id: str
    requirement_coverage: dict[str, Any]
    dependency_digest: str
    canonical_position: int
    issued_at: str
    expires_at: str
    invalidation_sequence: int
    freshness_at_issue: Literal["CURRENT", "STALE"]
    consistency_mode_at_issue: Consistency

    @classmethod
    def from_api(cls, body: Mapping[str, Any]) -> ContextReceipt:
        if body.get("schema_version") != "context-receipt-v0.1":
            raise ValueError("context receipt schema is invalid")
        coverage = body.get("requirement_coverage")
        dependency_digest = body.get("dependency_digest")
        canonical_position = body.get("canonical_position")
        invalidation_sequence = body.get("invalidation_sequence")
        freshness = body.get("freshness_at_issue")
        consistency = body.get("consistency_mode_at_issue")
        if not isinstance(coverage, Mapping):
            raise ValueError("context receipt coverage is invalid")
        if (
            not isinstance(dependency_digest, str)
            or len(dependency_digest) != 64
            or any(value not in "0123456789abcdef" for value in dependency_digest)
        ):
            raise ValueError("context receipt dependency digest is invalid")
        if (
            isinstance(canonical_position, bool)
            or not isinstance(canonical_position, int)
            or canonical_position < 0
            or isinstance(invalidation_sequence, bool)
            or not isinstance(invalidation_sequence, int)
            or invalidation_sequence < 0
        ):
            raise ValueError("context receipt sequence is invalid")
        if freshness not in {"CURRENT", "STALE"}:
            raise ValueError("context receipt freshness is invalid")
        if consistency not in {"EVENTUAL", "READ_YOUR_WRITES", "CANONICAL_REQUIRED"}:
            raise ValueError("context receipt consistency is invalid")
        capsule_id = body.get("context_capsule_id")
        issued_at = body.get("issued_at")
        expires_at = body.get("expires_at")
        if not all(
            isinstance(value, str) and value for value in (capsule_id, issued_at, expires_at)
        ):
            raise ValueError("context receipt identity or timestamps are invalid")
        try:
            issued_timestamp = datetime.fromisoformat(cast(str, issued_at))
            expiry_timestamp = datetime.fromisoformat(cast(str, expires_at))
        except ValueError as exc:
            raise ValueError("context receipt timestamps are invalid") from exc
        if (
            issued_timestamp.utcoffset() is None
            or expiry_timestamp.utcoffset() is None
            or expiry_timestamp <= issued_timestamp
        ):
            raise ValueError("context receipt timestamps are invalid")
        return cls(
            context_capsule_id=cast(str, capsule_id),
            requirement_coverage=dict(coverage),
            dependency_digest=dependency_digest,
            canonical_position=canonical_position,
            issued_at=cast(str, issued_at),
            expires_at=cast(str, expires_at),
            invalidation_sequence=invalidation_sequence,
            freshness_at_issue=cast(Literal["CURRENT", "STALE"], freshness),
            consistency_mode_at_issue=cast(Consistency, consistency),
        )


@dataclass(frozen=True, slots=True)
class EvidenceContextReceipt:
    """Ephemeral, noncanonical receipt for Evidence-only or mixed Context."""

    context_id: str
    authority_class: Literal["EVIDENCE_ONLY", "MIXED"]
    query_ir_digest: str
    requirement_digest: str
    semantic_context_digest: str
    reader_context_digest: str
    receipt_mapping: list[dict[str, Any]]
    source_evidence_ids: list[str]
    claim_versions: list[str]
    issue_revisions: list[dict[str, Any]]
    sufficiency_status: Literal["COMPLETE", "PARTIAL", "UNSATISFIED", "CONTESTED", "UNBOUNDED"]
    missing_slots: list[str]
    canonical_position: int | None
    projection_watermarks: dict[str, int]
    issued_at: str
    persisted: Literal[False]
    canonical_mutation: Literal[False]

    @classmethod
    def from_api(cls, body: Mapping[str, Any]) -> EvidenceContextReceipt:
        if body.get("schema_version") != "context-receipt-v0.2":
            raise ValueError("evidence context receipt schema is invalid")
        context_id = _required_string(body.get("context_id"))
        authority_class = body.get("authority_class")
        if authority_class not in {"EVIDENCE_ONLY", "MIXED"}:
            raise ValueError("evidence context receipt authority is invalid")
        digests = {
            name: _sha256_string(body.get(name))
            for name in (
                "query_ir_digest",
                "requirement_digest",
                "semantic_context_digest",
                "reader_context_digest",
            )
        }
        receipt_mapping = _strict_dict_list(body.get("receipt_mapping"))
        source_evidence_ids = _strict_string_list(body.get("source_evidence_ids"))
        claim_versions = _strict_string_list(body.get("claim_versions"))
        issue_revisions = _strict_dict_list(body.get("issue_revisions"))
        missing_slots = _strict_string_list(body.get("missing_slots"))
        sufficiency_status = body.get("sufficiency_status")
        if sufficiency_status not in {
            "COMPLETE",
            "PARTIAL",
            "UNSATISFIED",
            "CONTESTED",
            "UNBOUNDED",
        }:
            raise ValueError("evidence context receipt sufficiency is invalid")
        canonical_position = body.get("canonical_position")
        if canonical_position is not None and (
            isinstance(canonical_position, bool)
            or not isinstance(canonical_position, int)
            or canonical_position < 0
        ):
            raise ValueError("evidence context receipt position is invalid")
        projection_watermarks = body.get("projection_watermarks")
        if not isinstance(projection_watermarks, Mapping) or any(
            not isinstance(key, str)
            or not key
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            for key, value in projection_watermarks.items()
        ):
            raise ValueError("evidence context receipt watermarks are invalid")
        issued_at = _aware_timestamp(body.get("issued_at"))
        if body.get("persisted") is not False or body.get("canonical_mutation") is not False:
            raise ValueError("evidence context receipt must remain ephemeral and noncanonical")
        return cls(
            context_id=context_id,
            authority_class=cast(Literal["EVIDENCE_ONLY", "MIXED"], authority_class),
            query_ir_digest=digests["query_ir_digest"],
            requirement_digest=digests["requirement_digest"],
            semantic_context_digest=digests["semantic_context_digest"],
            reader_context_digest=digests["reader_context_digest"],
            receipt_mapping=receipt_mapping,
            source_evidence_ids=source_evidence_ids,
            claim_versions=claim_versions,
            issue_revisions=issue_revisions,
            sufficiency_status=cast(
                Literal[
                    "COMPLETE",
                    "PARTIAL",
                    "UNSATISFIED",
                    "CONTESTED",
                    "UNBOUNDED",
                ],
                sufficiency_status,
            ),
            missing_slots=missing_slots,
            canonical_position=canonical_position,
            projection_watermarks={
                str(key): cast(int, value) for key, value in projection_watermarks.items()
            },
            issued_at=issued_at,
            persisted=False,
            canonical_mutation=False,
        )


@dataclass(frozen=True, slots=True)
class MemoryResolveEnvelope:
    status: MemoryResolveStatus
    items: list[dict[str, Any]]
    open_issue_ids: list[str]
    evidence_refs: list[str]
    consistency: str | None
    canonical_position: dict[str, Any] | None
    trace_id: str | None
    degraded_components: list[str]
    abstention_reason: str | None
    memory_intent: Literal["NOT_NEEDED", "POSSIBLE", "REQUIRED"]
    requirement: Literal["NONE", "EXACT", "SEARCH", "RECONSTRUCT"]
    availability: Literal["AVAILABLE", "DEGRADED", "UNAVAILABLE"]
    context_receipt: ContextReceipt | EvidenceContextReceipt | None
    request_id: str | None
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_api(cls, body: dict[str, Any]) -> MemoryResolveEnvelope:
        status = body.get("status")
        memory_intent = body.get("memory_intent")
        requirement = body.get("requirement")
        availability = body.get("availability")
        if status not in {
            "HIT",
            "PARTIAL",
            "CONTESTED",
            "ABSENT",
            "ABSTAINED",
            "DENIED",
            "UNAVAILABLE",
        }:
            raise ValueError("memory resolve status is invalid")
        if memory_intent not in {"NOT_NEEDED", "POSSIBLE", "REQUIRED"}:
            raise ValueError("memory resolve intent is invalid")
        if requirement not in {"NONE", "EXACT", "SEARCH", "RECONSTRUCT"}:
            raise ValueError("memory resolve requirement is invalid")
        if availability not in {"AVAILABLE", "DEGRADED", "UNAVAILABLE"}:
            raise ValueError("memory resolve availability is invalid")
        canonical_position = body.get("canonical_position")
        return cls(
            status=cast(MemoryResolveStatus, status),
            items=_dict_list(body.get("items")),
            open_issue_ids=list(_string_tuple(body.get("open_issue_ids"))),
            evidence_refs=list(_string_tuple(body.get("evidence_refs"))),
            consistency=_optional_string(body.get("consistency")),
            canonical_position=(
                dict(canonical_position) if isinstance(canonical_position, dict) else None
            ),
            trace_id=_optional_string(body.get("trace_id")),
            degraded_components=list(_string_tuple(body.get("degraded_components"))),
            abstention_reason=_optional_string(body.get("abstention_reason")),
            memory_intent=cast(Literal["NOT_NEEDED", "POSSIBLE", "REQUIRED"], memory_intent),
            requirement=cast(Literal["NONE", "EXACT", "SEARCH", "RECONSTRUCT"], requirement),
            availability=cast(Literal["AVAILABLE", "DEGRADED", "UNAVAILABLE"], availability),
            context_receipt=(
                _context_receipt_from_api(body["context_receipt"])
                if isinstance(body.get("context_receipt"), Mapping)
                else None
            ),
            request_id=_optional_string(body.get("request_id")),
            raw=body,
        )


@dataclass(frozen=True, slots=True)
class MemoryStateViewEnvelope:
    status: Literal["HIT", "CONTESTED", "ABSENT", "ABSTAINED", "DENIED", "UNAVAILABLE"]
    items: list[dict[str, Any]]
    open_issue_ids: list[str]
    evidence_refs: list[str]
    consistency: str | None
    canonical_position: dict[str, Any] | None
    trace_id: str | None
    availability: Literal["AVAILABLE", "DEGRADED", "UNAVAILABLE"]
    abstention_reason: str | None
    resolution: dict[str, Any]
    access_trace: dict[str, Any] | None
    request_id: str | None
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_api(cls, body: dict[str, Any]) -> MemoryStateViewEnvelope:
        status = body.get("status")
        availability = body.get("availability")
        if status not in {
            "HIT",
            "CONTESTED",
            "ABSENT",
            "ABSTAINED",
            "DENIED",
            "UNAVAILABLE",
        }:
            raise ValueError("memory state status is invalid")
        if availability not in {"AVAILABLE", "DEGRADED", "UNAVAILABLE"}:
            raise ValueError("memory state availability is invalid")
        resolution = body.get("resolution")
        if not isinstance(resolution, Mapping):
            raise ValueError("memory state resolution is invalid")
        dimensions = ("addressable", "reachable", "correctly_resolved")
        if any(not isinstance(resolution.get(name), bool) for name in dimensions):
            raise ValueError("memory state resolution dimensions are invalid")
        canonical_position = body.get("canonical_position")
        access_trace = body.get("access_trace")
        return cls(
            status=cast(
                Literal["HIT", "CONTESTED", "ABSENT", "ABSTAINED", "DENIED", "UNAVAILABLE"],
                status,
            ),
            items=_dict_list(body.get("items")),
            open_issue_ids=list(_string_tuple(body.get("open_issue_ids"))),
            evidence_refs=list(_string_tuple(body.get("evidence_refs"))),
            consistency=_optional_string(body.get("consistency")),
            canonical_position=(
                dict(canonical_position) if isinstance(canonical_position, Mapping) else None
            ),
            trace_id=_optional_string(body.get("trace_id")),
            availability=cast(Literal["AVAILABLE", "DEGRADED", "UNAVAILABLE"], availability),
            abstention_reason=_optional_string(body.get("abstention_reason")),
            resolution=dict(resolution),
            access_trace=dict(access_trace) if isinstance(access_trace, Mapping) else None,
            request_id=_optional_string(body.get("request_id")),
            raw=body,
        )


@dataclass(frozen=True, slots=True)
class ContextRequest:
    retrieval_trace_id: str
    active_goal: str
    constraints: tuple[str, ...] = ()
    byte_budget: int = 16_384
    ttl_seconds: int = 900

    def to_api(self) -> dict[str, Any]:
        return {
            "retrieval_trace_id": self.retrieval_trace_id,
            "active_goal": self.active_goal,
            "constraints": list(self.constraints),
            "byte_budget": self.byte_budget,
            "ttl_seconds": self.ttl_seconds,
        }


@dataclass(frozen=True, slots=True)
class ContextEnvelope:
    capsule_id: str
    compression_level: str
    byte_size: int
    protected_sections: dict[str, Any]
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_api(cls, body: dict[str, Any]) -> ContextEnvelope:
        sections = body.get("protected_sections")
        return cls(
            capsule_id=str(body.get("capsule_id", "")),
            compression_level=str(body.get("compression_level", "")),
            byte_size=int(body.get("byte_size", 0)),
            protected_sections=sections if isinstance(sections, dict) else {},
            raw=body,
        )


@dataclass(frozen=True, slots=True)
class TaskMemoryBudget:
    max_prepare_context_calls: int = 4
    max_full_recall_calls: int = 2
    max_delta_refreshes: int = 2
    max_memory_tokens_injected: int = 1_600
    max_validation_calls: int = 16
    memory_deadline_ms: int = 250

    def to_api(self) -> dict[str, int]:
        return {
            "max_prepare_context_calls": self.max_prepare_context_calls,
            "max_full_recall_calls": self.max_full_recall_calls,
            "max_delta_refreshes": self.max_delta_refreshes,
            "max_memory_tokens_injected": self.max_memory_tokens_injected,
            "max_validation_calls": self.max_validation_calls,
            "memory_deadline_ms": self.memory_deadline_ms,
        }


@dataclass(frozen=True, slots=True)
class PrepareContextRequest:
    query: str
    active_goal: str
    session_id: str
    agent_id: str
    profile_id: str
    task_epoch: str
    event: PrepareContextEvent
    scope: dict[str, Any]
    authority: Authority
    consistency: Consistency
    compiler_digest: str
    router_digest: str
    tokenizer_digest: str
    policy_digest: str
    requested_route: RecallExecutionRoute = "L1"
    need_signature_id: str | None = None
    memory_need_signature: MemoryNeedSignature | None = None
    state_key_ref: StateKeyRef | None = None
    limit: int = 3
    constraints: tuple[str, ...] = ()
    byte_budget: int = 16_384
    memory_token_budget: int = 512
    slot_ttl_seconds: int = 300
    budget: TaskMemoryBudget = field(default_factory=TaskMemoryBudget)
    previous_validation_token: str | None = None
    known_claim_id: str | None = None
    action_digest: str | None = None

    def to_api(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "query": self.query,
            "active_goal": self.active_goal,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "profile_id": self.profile_id,
            "task_epoch": self.task_epoch,
            "event": self.event,
            "requested_scope": self.scope,
            "required_authority": self.authority,
            "consistency": self.consistency,
            "limit": self.limit,
            "constraints": list(self.constraints),
            "byte_budget": self.byte_budget,
            "memory_token_budget": self.memory_token_budget,
            "slot_ttl_seconds": self.slot_ttl_seconds,
            "compiler_digest": self.compiler_digest,
            "router_digest": self.router_digest,
            "tokenizer_digest": self.tokenizer_digest,
            "policy_digest": self.policy_digest,
            "requested_route": self.requested_route,
            "budget": self.budget.to_api(),
        }
        if self.need_signature_id is not None:
            value["need_signature_id"] = self.need_signature_id
        if self.memory_need_signature is not None:
            value["memory_need_signature"] = self.memory_need_signature.to_api()
        if self.state_key_ref is not None:
            value["state_key_ref"] = self.state_key_ref.to_api()
        for key, item in (
            ("previous_validation_token", self.previous_validation_token),
            ("known_claim_id", self.known_claim_id),
            ("action_digest", self.action_digest),
        ):
            if item is not None:
                value[key] = item
        return value


@dataclass(frozen=True, slots=True)
class CurrentStateEnvelope:
    status: Literal["HIT", "MISS", "BLOCKED", "AMBIGUOUS", "CANONICAL_UNAVAILABLE"]
    claims: tuple[dict[str, Any], ...]
    open_issues: tuple[dict[str, Any], ...]
    canonical_position: int | None
    slot_validation_handle: str | None
    trace_id: str | None

    @classmethod
    def from_api(cls, value: object) -> CurrentStateEnvelope:
        if not isinstance(value, Mapping):
            raise ValueError("current state envelope must be an object")
        status = value.get("status")
        if status not in {"HIT", "MISS", "BLOCKED", "AMBIGUOUS", "CANONICAL_UNAVAILABLE"}:
            raise ValueError("current state envelope status is invalid")
        position = value.get("canonical_position")
        if position is not None and (
            isinstance(position, bool) or not isinstance(position, int) or position < 0
        ):
            raise ValueError("current state canonical position is invalid")
        return cls(
            status=cast(
                Literal["HIT", "MISS", "BLOCKED", "AMBIGUOUS", "CANONICAL_UNAVAILABLE"],
                status,
            ),
            claims=tuple(_dict_list(value.get("claims"))),
            open_issues=tuple(_dict_list(value.get("open_issues"))),
            canonical_position=position,
            slot_validation_handle=_optional_string(value.get("slot_validation_handle")),
            trace_id=_optional_string(value.get("trace_id")),
        )


@dataclass(frozen=True, slots=True)
class MemorySlotCoverageEnvelope:
    version: str
    scope: dict[str, Any]
    authority_supported: Authority
    consistency_supported: Consistency
    claim_ids_and_head_versions: tuple[dict[str, Any], ...]
    state_keys_and_head_versions: tuple[dict[str, Any], ...]
    open_issue_ids_and_revisions: tuple[dict[str, Any], ...]
    temporal_coverage: Literal["CURRENT", "HISTORICAL", "AS_OF"]
    evidence_depth: Literal["NONE", "SUPPORT_POINTERS", "RAW_EVIDENCE"]
    policy_identity: str
    dependency_frontier: dict[str, Any]

    @classmethod
    def from_api(cls, value: object) -> MemorySlotCoverageEnvelope:
        if not isinstance(value, Mapping):
            raise ValueError("memory slot coverage must be an object")
        authority = value.get("authority_supported")
        consistency = value.get("consistency_supported")
        temporal = value.get("temporal_coverage")
        evidence = value.get("evidence_depth")
        scope = value.get("scope")
        version = value.get("version")
        policy_identity = value.get("policy_identity")
        frontier = value.get("dependency_frontier")
        if authority not in {"INFORMATIONAL", "ACTION_SAFE", "USER_CONFIRMED"}:
            raise ValueError("memory slot coverage authority is invalid")
        if version != "memory-slot-coverage-v1":
            raise ValueError("memory slot coverage version is invalid")
        if consistency not in {"EVENTUAL", "READ_YOUR_WRITES", "CANONICAL_REQUIRED"}:
            raise ValueError("memory slot coverage consistency is invalid")
        if temporal not in {"CURRENT", "HISTORICAL", "AS_OF"}:
            raise ValueError("memory slot temporal coverage is invalid")
        if evidence not in {"NONE", "SUPPORT_POINTERS", "RAW_EVIDENCE"}:
            raise ValueError("memory slot evidence depth is invalid")
        if not isinstance(scope, Mapping):
            raise ValueError("memory slot coverage scope is invalid")
        if (
            not isinstance(policy_identity, str)
            or len(policy_identity) != 64
            or any(character not in "0123456789abcdef" for character in policy_identity)
        ):
            raise ValueError("memory slot policy identity is invalid")
        if not isinstance(frontier, Mapping):
            raise ValueError("memory slot dependency frontier is invalid")
        position = frontier.get("canonical_position")
        if (
            frontier.get("kind") != "GLOBAL_CANONICAL_POSITION"
            or isinstance(position, bool)
            or not isinstance(position, int)
            or position < 0
        ):
            raise ValueError("memory slot dependency frontier is invalid")
        return cls(
            version=version,
            scope=dict(scope),
            authority_supported=cast(Authority, authority),
            consistency_supported=cast(Consistency, consistency),
            claim_ids_and_head_versions=tuple(_dict_list(value.get("claim_ids_and_head_versions"))),
            state_keys_and_head_versions=tuple(
                _dict_list(value.get("state_keys_and_head_versions"))
            ),
            open_issue_ids_and_revisions=tuple(
                _dict_list(value.get("open_issue_ids_and_revisions"))
            ),
            temporal_coverage=cast(Literal["CURRENT", "HISTORICAL", "AS_OF"], temporal),
            evidence_depth=cast(Literal["NONE", "SUPPORT_POINTERS", "RAW_EVIDENCE"], evidence),
            policy_identity=policy_identity,
            dependency_frontier=dict(frontier),
        )


@dataclass(frozen=True, slots=True)
class PrepareContextEnvelope:
    route: str
    status: str
    reason: str | None
    context_capsule: dict[str, Any] | None
    context_delta: dict[str, Any]
    relevant_open_issues: tuple[dict[str, Any], ...]
    canonical_position: int | None
    validation_token: str | None
    trace_pointer: str | None
    usage: dict[str, int] | None
    request_id: str | None
    recall_execution_trace: RecallExecutionTrace | None
    current_state_envelope: CurrentStateEnvelope | None
    memory_slot_coverage: MemorySlotCoverageEnvelope | None
    prepared_detail_level: Literal["ABSTRACT", "OVERVIEW", "EVIDENCE_DETAIL"] | None
    requested_detail_level: Literal["ABSTRACT", "OVERVIEW", "EVIDENCE_DETAIL"] | None
    raw: dict[str, Any] = field(repr=False)
    timing: dict[str, float] | None = None

    @classmethod
    def from_api(cls, body: dict[str, Any]) -> PrepareContextEnvelope:
        capsule = body.get("context_capsule")
        delta = body.get("context_delta")
        issues = body.get("relevant_open_issue_closure")
        usage = body.get("usage")
        timing = body.get("timing")
        recall_execution_trace = body.get("recall_execution_trace")
        current_state_envelope = body.get("current_state_envelope")
        memory_slot_coverage = body.get("memory_slot_coverage")
        canonical_position = body.get("canonical_position")
        prepared_detail_level = _detail_level(body.get("prepared_detail_level"))
        requested_detail_level = _detail_level(body.get("requested_detail_level"))
        if canonical_position is not None and (
            isinstance(canonical_position, bool) or not isinstance(canonical_position, int)
        ):
            raise ValueError("invalid prepare_context canonical position")
        return cls(
            route=str(body.get("route", "")),
            status=str(body.get("status", "")),
            reason=_optional_string(body.get("reason")),
            context_capsule=capsule if isinstance(capsule, dict) else None,
            context_delta=delta if isinstance(delta, dict) else {},
            relevant_open_issues=tuple(_dict_list(issues)),
            canonical_position=canonical_position,
            validation_token=_optional_string(body.get("validation_token")),
            trace_pointer=_optional_string(body.get("trace_pointer")),
            usage=(
                {str(key): int(value) for key, value in usage.items()}
                if isinstance(usage, dict)
                else None
            ),
            request_id=_optional_string(body.get("request_id")),
            recall_execution_trace=(
                RecallExecutionTrace.from_api(recall_execution_trace)
                if recall_execution_trace is not None
                else None
            ),
            current_state_envelope=(
                CurrentStateEnvelope.from_api(current_state_envelope)
                if current_state_envelope is not None
                else None
            ),
            memory_slot_coverage=(
                MemorySlotCoverageEnvelope.from_api(memory_slot_coverage)
                if memory_slot_coverage is not None
                else None
            ),
            prepared_detail_level=prepared_detail_level,
            requested_detail_level=requested_detail_level,
            raw=body,
            timing=(
                {
                    str(key): float(value)
                    for key, value in timing.items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                }
                if isinstance(timing, dict)
                else None
            ),
        )


def _detail_level(
    value: object,
) -> Literal["ABSTRACT", "OVERVIEW", "EVIDENCE_DETAIL"] | None:
    if value is None:
        return None
    if value not in {"ABSTRACT", "OVERVIEW", "EVIDENCE_DETAIL"}:
        raise ValueError("invalid prepare_context detail level")
    return cast(Literal["ABSTRACT", "OVERVIEW", "EVIDENCE_DETAIL"], value)


@dataclass(frozen=True, slots=True)
class ClaimEnvelope:
    claim_id: str
    claim_version_id: str
    effective_status: str
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_api(cls, body: dict[str, Any]) -> ClaimEnvelope:
        return cls(
            claim_id=str(body.get("claim_id", "")),
            claim_version_id=str(body.get("claim_version_id", "")),
            effective_status=str(body.get("effective_status", "")),
            raw=body,
        )


@dataclass(frozen=True, slots=True)
class OpenIssueEnvelope:
    issue_id: str
    status: str
    revision: int
    branches: tuple[dict[str, Any], ...]
    discharge_rule: dict[str, Any]
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_api(cls, body: dict[str, Any]) -> OpenIssueEnvelope:
        return cls(
            issue_id=str(body.get("issue_id", "")),
            status=str(body.get("status", "")),
            revision=int(body.get("revision", 0)),
            branches=tuple(_dict_list(body.get("branches"))),
            discharge_rule=(
                body["discharge_rule"] if isinstance(body.get("discharge_rule"), dict) else {}
            ),
            raw=body,
        )


@dataclass(frozen=True, slots=True)
class RetrievalTraceEnvelope:
    trace_id: str
    abstained: bool
    accepted_candidates: tuple[dict[str, Any], ...]
    rejected_candidates: tuple[dict[str, Any], ...]
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_api(cls, body: dict[str, Any]) -> RetrievalTraceEnvelope:
        return cls(
            trace_id=str(body.get("retrieval_trace_id", body.get("trace_id", ""))),
            abstained=bool(body.get("abstained", False)),
            accepted_candidates=tuple(_dict_list(body.get("accepted_candidates"))),
            rejected_candidates=tuple(_dict_list(body.get("rejected_candidates"))),
            raw=body,
        )


@dataclass(frozen=True, slots=True)
class EvidenceReceipt:
    evidence_id: str
    blob_id: str
    outbox_id: str
    replayed: bool
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_api(cls, body: dict[str, Any]) -> EvidenceReceipt:
        return cls(
            evidence_id=str(body.get("evidence_id", "")),
            blob_id=str(body.get("blob_id", "")),
            outbox_id=str(body.get("outbox_id", "")),
            replayed=bool(body.get("replayed", False)),
            raw=body,
        )


@dataclass(frozen=True, slots=True)
class ProposalReceipt:
    proposal_id: str
    status: str
    replayed: bool
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_api(cls, body: dict[str, Any]) -> ProposalReceipt:
        return cls(
            proposal_id=str(body.get("proposal_id", "")),
            status=str(body.get("status", body.get("commit_policy_decision", ""))),
            replayed=bool(body.get("replayed", False)),
            raw=body,
        )


@dataclass(frozen=True, slots=True)
class ProposalReviewReceipt:
    proposal_id: str
    decision_id: str
    decision: str
    claim_id: str | None
    claim_version_id: str | None
    open_issue_id: str | None
    canonical_commit_seq: int | None
    replayed: bool
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_api(cls, body: dict[str, Any]) -> ProposalReviewReceipt:
        return cls(
            proposal_id=str(body.get("proposal_id", "")),
            decision_id=str(body.get("decision_id", "")),
            decision=str(body.get("decision", "")),
            claim_id=(str(body["claim_id"]) if body.get("claim_id") is not None else None),
            claim_version_id=(
                str(body["claim_version_id"]) if body.get("claim_version_id") is not None else None
            ),
            open_issue_id=(
                str(body["open_issue_id"]) if body.get("open_issue_id") is not None else None
            ),
            canonical_commit_seq=(
                int(body["canonical_commit_seq"])
                if body.get("canonical_commit_seq") is not None
                else None
            ),
            replayed=bool(body.get("replayed", False)),
            raw=body,
        )


@dataclass(frozen=True, slots=True)
class DeletionReceipt:
    deletion_request_id: str
    logical_revocation_status: str
    canonical_block_status: str
    replayed: bool
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_api(cls, body: dict[str, Any]) -> DeletionReceipt:
        return cls(
            deletion_request_id=str(body.get("deletion_request_id", "")),
            logical_revocation_status=str(body.get("logical_revocation_status", "")),
            canonical_block_status=str(body.get("canonical_block_status", "")),
            replayed=bool(body.get("replayed", False)),
            raw=body,
        )


@dataclass(frozen=True, slots=True)
class CausalToken:
    token: str
    minimum_outbox_sequence: int
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_api(cls, body: dict[str, Any]) -> CausalToken:
        return cls(
            token=str(body.get("causal_token", body.get("token", ""))),
            minimum_outbox_sequence=int(body.get("minimum_outbox_sequence", 0)),
            raw=body,
        )


@dataclass(frozen=True, slots=True)
class PartialProposalOutcome:
    evidence: EvidenceReceipt
    proposal: ProposalReceipt | None
    proposal_error_code: str | None
    canonical_changed: bool = False


class EvidenceSourceContext(BaseModel):
    """Source-authored turn/round identity; omitted when the host cannot prove it."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    session_id: str = Field(min_length=1, max_length=512)
    turn_id: str = Field(min_length=1, max_length=512)
    turn_ordinal: int = Field(ge=0)
    round_id: str = Field(min_length=1, max_length=512)
    round_ordinal: int = Field(ge=0)
    previous_turn_id: str | None = Field(default=None, min_length=1, max_length=512)
    next_turn_id: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_adjacency(self) -> Self:
        if self.turn_id in {self.previous_turn_id, self.next_turn_id}:
            raise ValueError("a source turn cannot be adjacent to itself")
        if self.previous_turn_id is not None and self.previous_turn_id == self.next_turn_id:
            raise ValueError("previous and next source turns must be distinct")
        return self


class EvidenceCaptureRequest(BaseModel):
    """Locally validated Evidence input; capture never implies canonical truth."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    source_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    source_ref: str = Field(min_length=1, max_length=2_000)
    subject_id: str = Field(min_length=1, max_length=512)
    speaker: Literal["user", "assistant", "system", "tool"] | None = None
    source_context: EvidenceSourceContext | None = None
    observed_at: datetime
    content: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(min_length=1)
    data_classification: Literal["SYNTHETIC", "DEIDENTIFIED", "PERSONAL"] = "SYNTHETIC"
    permission_snapshot: dict[str, Any]
    media_type: str = Field(default="text/plain", min_length=1, max_length=255)
    retention_state: Literal["READABLE", "UNREADABLE", "EXPIRED", "LEGAL_HOLD"] = "READABLE"


class RevocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    reason_code: str = Field(min_length=1, max_length=255)
    confirmation: Literal["REVOKE"]


class ProposalDraft(BaseModel):
    """Model-boundary draft. Validation happens before any API request is sent."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    operation: str
    supporting_evidence_refs: tuple[str, ...] = ()
    requested_authority: Authority
    scope_predicate: dict[str, Any]
    model_id: str
    template_version: str
    input_snapshot_hash: str
    proposed_patch: dict[str, Any]
    target_claim_id: str | None = None
    expected_version_id: str | None = None
    contradicting_evidence_refs: tuple[str, ...] = ()
    derivation_policy_id: str = "agent-extractor-v1"

    @model_validator(mode="after")
    def validate_deterministic_shape(self) -> ProposalDraft:
        if self.operation not in {
            "CREATE",
            "SUPPORT",
            "WEAKEN",
            "REVALIDATE",
            "REGROUND",
            "SUPERSEDE",
            "CONTEXTUALIZE",
            "CONTRADICT",
            "NO_CHANGE",
        }:
            raise ValueError("proposal draft operation is not enabled")
        if len(self.input_snapshot_hash) != 64 or any(
            value not in "0123456789abcdef" for value in self.input_snapshot_hash
        ):
            raise ValueError("proposal draft snapshot hash must be lowercase SHA-256")
        if not self.model_id or not self.template_version:
            raise ValueError("proposal draft model and template identity are required")
        if len(set(self.supporting_evidence_refs)) != len(self.supporting_evidence_refs):
            raise ValueError("supporting Evidence refs must be unique")
        if len(set(self.contradicting_evidence_refs)) != len(self.contradicting_evidence_refs):
            raise ValueError("contradicting Evidence refs must be unique")
        if set(self.supporting_evidence_refs) & set(self.contradicting_evidence_refs):
            raise ValueError("Evidence cannot support and contradict the same draft")
        if self.operation == "CREATE":
            if self.target_claim_id is not None or self.expected_version_id is not None:
                raise ValueError("CREATE cannot target an existing ClaimVersion")
            required = {
                "subject_id",
                "predicate",
                "claim_type",
                "payload",
                "authority",
                "confidence",
            }
            if not required.issubset(self.proposed_patch):
                raise ValueError("CREATE proposed_patch is missing canonical fields")
        elif not self.target_claim_id or not self.expected_version_id:
            raise ValueError("non-CREATE proposal draft requires Claim and version heads")
        if (
            self.operation
            in {
                "CREATE",
                "SUPPORT",
                "WEAKEN",
                "REVALIDATE",
                "REGROUND",
                "SUPERSEDE",
                "CONTEXTUALIZE",
            }
            and not self.supporting_evidence_refs
        ):
            raise ValueError("version-changing draft requires supporting Evidence")
        if self.operation == "CONTRADICT" and not self.contradicting_evidence_refs:
            raise ValueError("CONTRADICT requires contradicting Evidence")
        if (
            self.proposed_patch.get("authority", self.requested_authority)
            != self.requested_authority
        ):
            raise ValueError("proposed authority must equal requested authority")
        return self

    def to_api(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "operation": self.operation,
            "proposed_patch": self.proposed_patch,
            "supporting_evidence_refs": list(self.supporting_evidence_refs),
            "contradicting_evidence_refs": list(self.contradicting_evidence_refs),
            "scope_predicate": self.scope_predicate,
            "requested_authority": self.requested_authority,
            "derivation_policy_id": self.derivation_policy_id,
            "model_id": self.model_id,
            "template_id": self.template_version,
            "derivation_snapshot": {
                "input_snapshot_hash": self.input_snapshot_hash,
                "model_id": self.model_id,
                "template_version": self.template_version,
            },
        }
        if self.target_claim_id is not None:
            body["target_claim_id"] = self.target_claim_id
        if self.expected_version_id is not None:
            body["expected_version_id"] = self.expected_version_id
        return body

    def validate_current_head(self, current_claim_version_id: str | None) -> ProposalDraft:
        """Reject a locally known stale head before submitting the Proposal mutation."""
        if self.operation == "CREATE":
            if current_claim_version_id is not None:
                raise ValueError("CREATE draft conflicts with an existing canonical Claim head")
            return self
        if self.expected_version_id != current_claim_version_id:
            raise ValueError("proposal draft expected Claim head is stale")
        return self


class MemoryCandidateExtractor(Protocol):
    """Optional untrusted extractor boundary; deliberately has no review method."""

    async def extract(
        self,
        observation: EvidenceReceipt,
        current: RecallEnvelope,
    ) -> list[ProposalDraft]: ...


@dataclass(frozen=True, slots=True)
class EpisodeReceipt:
    episode_id: str
    status: str
    revision: int
    replayed: bool
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_api(cls, body: dict[str, Any]) -> EpisodeReceipt:
        return cls(
            episode_id=str(body.get("episode_id", "")),
            status=str(body.get("status", "")),
            revision=int(body.get("revision", 0)),
            replayed=bool(body.get("replayed", False)),
            raw=body,
        )


@dataclass(frozen=True, slots=True)
class ObservationOutcome:
    evidence: dict[str, Any] | None
    proposal: dict[str, Any] | None
    proposal_error: str | None = None
    capture_denied_reason: str | None = None


def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _strict_dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("expected a list of objects")
    return [dict(item) for item in value]


def _strict_string_list(value: object) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError("expected a list of non-empty strings")
    return list(value)


def _required_string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("expected a non-empty string")
    return value


def _sha256_string(value: object) -> str:
    result = _required_string(value)
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise ValueError("expected a lowercase SHA-256 digest")
    return result


def _aware_timestamp(value: object) -> str:
    result = _required_string(value)
    try:
        parsed = datetime.fromisoformat(result)
    except ValueError as exc:
        raise ValueError("expected an ISO timestamp") from exc
    if parsed.utcoffset() is None:
        raise ValueError("expected a timezone-aware timestamp")
    return result


def _context_receipt_from_api(
    body: Mapping[str, Any],
) -> ContextReceipt | EvidenceContextReceipt:
    if body.get("schema_version") == "context-receipt-v0.1":
        return ContextReceipt.from_api(body)
    if body.get("schema_version") == "context-receipt-v0.2":
        return EvidenceContextReceipt.from_api(body)
    raise ValueError("context receipt schema is invalid")


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("expected a non-negative integer")
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    return tuple(str(item) for item in value) if isinstance(value, list) else ()


def _bool_dict(value: object) -> dict[str, bool]:
    return {str(key): bool(item) for key, item in value.items()} if isinstance(value, dict) else {}


def _int_dict(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        if isinstance(item, int) and not isinstance(item, bool):
            result[str(key)] = item
    return result
