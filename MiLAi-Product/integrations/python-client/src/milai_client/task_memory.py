from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from threading import RLock
from time import perf_counter
from typing import Literal

from milai_client.client import MilaiClient, UnavailableError
from milai_client.memory_need import MemoryNeedSignature, StateKeyRef
from milai_client.models import (
    AccessOutcome,
    AgentRecallPolicy,
    CurrentStateEnvelope,
    MemorySlotCoverageEnvelope,
    PrepareContextEnvelope,
    PrepareContextEvent,
    PrepareContextRequest,
    RecallEnvelope,
    RecallExecutionRoute,
    RecallExecutionTrace,
    TaskMemoryBudget,
)
from milai_client.optimization import (
    ContextCompileRequest,
    ContextCompileResult,
    ContextIntegrityError,
    GovernedContextCompiler,
    MemorySlot,
    TokenBudget,
    TokenCounter,
    turn_fingerprint,
)

TaskMemoryStatus = Literal[
    "READY",
    "UNCHANGED",
    "NEEDS_RECOVERY",
    "DEGRADED",
    "ABSTAIN",
    "BUDGET_EXHAUSTED",
]


@dataclass(frozen=True, slots=True)
class TaskMemoryIdentity:
    tenant_id: str
    session_id: str
    agent_id: str
    profile_id: str
    task_epoch: str

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.tenant_id,
                self.session_id,
                self.agent_id,
                self.profile_id,
                self.task_epoch,
            )
        ):
            raise ValueError("all task memory identity fields are required")


@dataclass(frozen=True, slots=True)
class TaskMemorySlot:
    binding_key: str
    validation_token: str
    compiled_slot: MemorySlot
    rendered_context: str
    memory_tokens_injected: int
    memory_slot_coverage: MemorySlotCoverageEnvelope


@dataclass(frozen=True, slots=True)
class TaskPreparedContext:
    route: str
    outcome: AccessOutcome
    delta: ContextCompileResult | None
    validation_token: str | None
    trace_pointer: str | None
    usage: dict[str, int] | None
    timing: dict[str, float] | None = None
    recall_execution_trace: RecallExecutionTrace | None = None
    current_state_envelope: CurrentStateEnvelope | None = None
    memory_slot_coverage: MemorySlotCoverageEnvelope | None = None

    @property
    def status(self) -> TaskMemoryStatus:
        """Legacy status derived from the authoritative AccessOutcome."""
        if self.outcome.status == "CONTEXT_READY_CURRENT":
            return "READY" if self.delta is not None else "UNCHANGED"
        if self.outcome.status == "MEMORY_REQUIRED_BUT_UNAVAILABLE":
            return "NEEDS_RECOVERY"
        if self.outcome.status == "MEMORY_INSUFFICIENT":
            if self.outcome.reason_code == "MEMORY_TOKEN_BUDGET_EXHAUSTED":
                return "BUDGET_EXHAUSTED"
            return "ABSTAIN"
        if self.outcome.status == "GOVERNANCE_BLOCKED":
            return "ABSTAIN"
        return "READY"

    @property
    def reason(self) -> str | None:
        """Legacy reason derived from the authoritative AccessOutcome."""
        return self.outcome.reason_code


class MemoryTransportUnavailableError(RuntimeError):
    """Stable boundary error for a required memory transport."""

    def __init__(self, code: str) -> None:
        if not code or any(character.isspace() for character in code):
            raise ValueError("memory transport error code must be a non-empty token")
        super().__init__(code)
        self.code = code


class ActionAuthorization:
    """Host-only, action-bound authorization handle that can be consumed once."""

    def __init__(
        self,
        *,
        action_digest: str,
        validation_token: str,
        trace_pointer: str | None,
    ) -> None:
        if not _is_digest(action_digest) or not validation_token:
            raise ValueError("action authorization requires a digest and validation token")
        self._action_digest = action_digest
        self._validation_token = validation_token
        self._trace_pointer = trace_pointer
        self._consumed = False
        self._lock = RLock()

    @property
    def action_digest(self) -> str:
        return self._action_digest

    @property
    def trace_pointer(self) -> str | None:
        return self._trace_pointer

    @property
    def consumed(self) -> bool:
        with self._lock:
            return self._consumed

    def consume(self, action: object) -> str:
        """Return the opaque Runtime token exactly once for the bound action bytes."""
        if not _constant_digest_equal(_sha256(action), self._action_digest):
            raise ValueError("action authorization does not match the proposed action")
        with self._lock:
            if self._consumed:
                raise RuntimeError("action authorization was already consumed")
            self._consumed = True
            return self._validation_token


@dataclass(frozen=True, slots=True)
class ActionValidationResult:
    status: TaskMemoryStatus
    reason: str | None
    authorization: ActionAuthorization | None
    trace_pointer: str | None
    usage: dict[str, int] | None


class TaskMemoryController:
    """Host-owned task lifecycle over the Runtime composite prepare_context boundary."""

    def __init__(
        self,
        client: MilaiClient,
        *,
        compiler: GovernedContextCompiler | None = None,
        compiler_digest: str,
        router_digest: str,
        policy_digest: str,
    ) -> None:
        for digest in (compiler_digest, router_digest, policy_digest):
            if not _is_digest(digest):
                raise ValueError("controller digests must be lowercase SHA-256")
        self._client = client
        self._compiler = compiler or GovernedContextCompiler()
        self._compiler_digest = compiler_digest
        self._router_digest = router_digest
        self._policy_digest = policy_digest
        self._slots: dict[str, TaskMemorySlot] = {}
        self._lock = RLock()

    def prepare_context(
        self,
        query: str,
        *,
        identity: TaskMemoryIdentity,
        event: PrepareContextEvent,
        active_goal: str,
        recall_policy: AgentRecallPolicy,
        token_counter: TokenCounter,
        token_budget: TokenBudget,
        task_budget: TaskMemoryBudget | None = None,
        constraints: tuple[str, ...] = (),
        byte_budget: int = 16_384,
        slot_ttl_seconds: int = 300,
        requested_route: RecallExecutionRoute = "L1",
        need_signature_id: str | None = None,
        memory_need_signature: MemoryNeedSignature | None = None,
        state_key_ref: StateKeyRef | None = None,
        known_claim_id: str | None = None,
        action_digest: str | None = None,
    ) -> TaskPreparedContext:
        if token_budget.max_memory_tokens is None:
            raise ValueError("TaskMemoryController requires a verified memory token ceiling")
        if task_budget is None:
            task_budget = TaskMemoryBudget()
        binding_key = _binding_key(
            identity,
            active_goal,
            recall_policy,
            constraints,
            token_counter.tokenizer_id,
            token_budget,
            task_budget,
            byte_budget,
            slot_ttl_seconds,
            self._compiler_digest,
            self._router_digest,
            self._policy_digest,
            action_digest,
        )
        identity_prefix = _identity_prefix(identity)
        with self._lock:
            for stale_key in tuple(self._slots):
                if stale_key.startswith(identity_prefix) and stale_key != binding_key:
                    del self._slots[stale_key]
            previous = self._slots.get(binding_key)
        request = PrepareContextRequest(
            query=query,
            active_goal=active_goal,
            session_id=identity.session_id,
            agent_id=identity.agent_id,
            profile_id=identity.profile_id,
            task_epoch=identity.task_epoch,
            event=event,
            scope=recall_policy.scope,
            authority=recall_policy.authority,
            consistency=recall_policy.consistency_floor,
            compiler_digest=self._compiler_digest,
            router_digest=self._router_digest,
            tokenizer_digest=hashlib.sha256(token_counter.tokenizer_id.encode()).hexdigest(),
            policy_digest=self._policy_digest,
            requested_route=requested_route,
            need_signature_id=need_signature_id,
            memory_need_signature=memory_need_signature,
            state_key_ref=state_key_ref,
            limit=min(3, recall_policy.max_limit),
            constraints=constraints,
            byte_budget=byte_budget,
            memory_token_budget=token_budget.max_memory_tokens,
            slot_ttl_seconds=slot_ttl_seconds,
            budget=task_budget,
            previous_validation_token=(previous.validation_token if previous is not None else None),
            known_claim_id=known_claim_id,
            action_digest=action_digest,
        )
        try:
            envelope = self._client.prepare_context(request)
        except (MemoryTransportUnavailableError, UnavailableError) as exc:
            reason_code = str(exc) if isinstance(exc, MemoryTransportUnavailableError) else exc.code
            return TaskPreparedContext(
                route=requested_route,
                outcome=AccessOutcome(
                    status="MEMORY_REQUIRED_BUT_UNAVAILABLE",
                    execution_action="RETRY",
                    provider_execution="PROHIBITED",
                    terminal_stage="TRANSPORT",
                    context_digest=None,
                    canonical_position=None,
                    reason_code=reason_code,
                    trace_id="transport:" + _sha256(request.to_api()),
                ),
                delta=None,
                validation_token=None,
                trace_pointer=None,
                usage=None,
            )
        if envelope.status == "UNCHANGED":
            if (
                previous is None
                or envelope.validation_token is None
                or envelope.memory_slot_coverage is None
            ):
                with self._lock:
                    self._slots.pop(binding_key, None)
                return TaskPreparedContext(
                    route=envelope.route,
                    outcome=_unavailable_outcome(
                        envelope,
                        reason_code=envelope.reason or "CACHE_VALIDATION_PROOF_MISSING",
                        terminal_stage="CACHE",
                    ),
                    delta=None,
                    validation_token=None,
                    trace_pointer=envelope.trace_pointer,
                    usage=envelope.usage,
                    timing=envelope.timing,
                    recall_execution_trace=envelope.recall_execution_trace,
                    current_state_envelope=envelope.current_state_envelope,
                    memory_slot_coverage=envelope.memory_slot_coverage,
                )
            refreshed = TaskMemorySlot(
                binding_key,
                envelope.validation_token,
                previous.compiled_slot,
                previous.rendered_context,
                previous.memory_tokens_injected,
                envelope.memory_slot_coverage,
            )
            with self._lock:
                self._slots[binding_key] = refreshed
            return TaskPreparedContext(
                route=envelope.route,
                outcome=AccessOutcome(
                    status="CONTEXT_READY_CURRENT",
                    execution_action="CONTINUE",
                    provider_execution="ALLOWED",
                    terminal_stage="CACHE",
                    context_digest=hashlib.sha256(previous.rendered_context.encode()).hexdigest(),
                    canonical_position=_canonical_position(envelope),
                    reason_code=envelope.reason,
                    trace_id=_trace_id(envelope),
                ),
                delta=None,
                validation_token=envelope.validation_token,
                trace_pointer=envelope.trace_pointer,
                usage=envelope.usage,
                timing=envelope.timing,
                recall_execution_trace=envelope.recall_execution_trace,
                current_state_envelope=envelope.current_state_envelope,
                memory_slot_coverage=envelope.memory_slot_coverage,
            )
        if envelope.status != "READY":
            with self._lock:
                self._slots.pop(binding_key, None)
            return TaskPreparedContext(
                route=envelope.route,
                outcome=_terminal_outcome(envelope),
                delta=None,
                validation_token=None,
                trace_pointer=envelope.trace_pointer,
                usage=envelope.usage,
                timing=envelope.timing,
                recall_execution_trace=envelope.recall_execution_trace,
                current_state_envelope=envelope.current_state_envelope,
                memory_slot_coverage=envelope.memory_slot_coverage,
            )
        compile_started = perf_counter()
        try:
            compiled = self._compile(
                envelope,
                query=query,
                identity=identity,
                active_goal=active_goal,
                constraints=constraints,
                recall_policy=recall_policy,
                token_counter=token_counter,
                token_budget=token_budget,
                previous=previous,
                slot_ttl_seconds=slot_ttl_seconds,
            )
        except ContextIntegrityError as exc:
            with self._lock:
                self._slots.pop(binding_key, None)
            timing = {
                **(envelope.timing or {}),
                "context_compile_ms": round((perf_counter() - compile_started) * 1_000, 3),
            }
            return TaskPreparedContext(
                route=envelope.route,
                outcome=AccessOutcome(
                    status="GOVERNANCE_BLOCKED",
                    execution_action="ABSTAIN",
                    provider_execution="PROHIBITED",
                    terminal_stage="GATE",
                    context_digest=None,
                    canonical_position=_canonical_position(envelope),
                    reason_code=str(exc),
                    trace_id=_trace_id(envelope),
                ),
                delta=None,
                validation_token=None,
                trace_pointer=envelope.trace_pointer,
                usage=envelope.usage,
                timing=timing,
                recall_execution_trace=envelope.recall_execution_trace,
                current_state_envelope=envelope.current_state_envelope,
                memory_slot_coverage=envelope.memory_slot_coverage,
            )
        timing = {
            **(envelope.timing or {}),
            "context_compile_ms": round((perf_counter() - compile_started) * 1_000, 3),
        }
        if compiled.slot is None or compiled.delta.rendered_context is None:
            raise RuntimeError("READY prepare_context did not compile a replacement slot")
        injected = compiled.metrics.actual_tokens
        if injected is None:
            raise RuntimeError("verified token counter did not return memory tokens")
        total_injected = (previous.memory_tokens_injected if previous is not None else 0) + injected
        if total_injected > task_budget.max_memory_tokens_injected:
            with self._lock:
                self._slots.pop(binding_key, None)
            return TaskPreparedContext(
                route=envelope.route,
                outcome=AccessOutcome(
                    status="MEMORY_INSUFFICIENT",
                    execution_action="ASK_USER",
                    provider_execution="PROHIBITED",
                    terminal_stage="SUFFICIENCY",
                    context_digest=None,
                    canonical_position=_canonical_position(envelope),
                    reason_code="MEMORY_TOKEN_BUDGET_EXHAUSTED",
                    trace_id=_trace_id(envelope),
                ),
                delta=None,
                validation_token=None,
                trace_pointer=envelope.trace_pointer,
                usage=envelope.usage,
                timing=timing,
                recall_execution_trace=envelope.recall_execution_trace,
                current_state_envelope=envelope.current_state_envelope,
                memory_slot_coverage=envelope.memory_slot_coverage,
            )
        if envelope.validation_token is None:
            raise RuntimeError("READY prepare_context omitted validation token")
        if envelope.memory_slot_coverage is None:
            raise RuntimeError("READY prepare_context omitted memory slot coverage")
        slot = TaskMemorySlot(
            binding_key,
            envelope.validation_token,
            compiled.slot,
            compiled.delta.rendered_context,
            total_injected,
            envelope.memory_slot_coverage,
        )
        with self._lock:
            self._slots[binding_key] = slot
        return TaskPreparedContext(
            route=envelope.route,
            outcome=AccessOutcome(
                status="CONTEXT_READY_CURRENT",
                execution_action="CONTINUE",
                provider_execution="ALLOWED",
                terminal_stage="CACHE" if envelope.route == "CACHE" else "EXACT",
                context_digest=hashlib.sha256(compiled.delta.rendered_context.encode()).hexdigest(),
                canonical_position=_canonical_position(envelope),
                reason_code=None,
                trace_id=_trace_id(envelope),
            ),
            delta=compiled,
            validation_token=envelope.validation_token,
            trace_pointer=envelope.trace_pointer,
            usage=envelope.usage,
            timing=timing,
            recall_execution_trace=envelope.recall_execution_trace,
            current_state_envelope=envelope.current_state_envelope,
            memory_slot_coverage=envelope.memory_slot_coverage,
        )

    def invalidate(self, identity: TaskMemoryIdentity) -> int:
        prefix = _identity_prefix(identity)
        with self._lock:
            keys = [key for key in self._slots if key.startswith(prefix)]
            for key in keys:
                del self._slots[key]
        return len(keys)

    def authorize_action(
        self,
        action: object,
        query: str,
        *,
        identity: TaskMemoryIdentity,
        active_goal: str,
        recall_policy: AgentRecallPolicy,
        token_counter: TokenCounter,
        token_budget: TokenBudget,
        task_budget: TaskMemoryBudget | None = None,
        constraints: tuple[str, ...] = (),
        byte_budget: int = 16_384,
        slot_ttl_seconds: int = 30,
    ) -> ActionValidationResult:
        """Revalidate current canonical state before a host executes a side effect."""
        if recall_policy.authority != "ACTION_SAFE":
            raise ValueError("action authorization requires ACTION_SAFE authority")
        if recall_policy.consistency_floor != "CANONICAL_REQUIRED":
            raise ValueError("action authorization requires CANONICAL_REQUIRED consistency")
        if not recall_policy.scope:
            raise ValueError("action authorization requires a non-empty scope")
        action_digest = _sha256(action)
        prepared = self.prepare_context(
            query,
            identity=identity,
            event="ACTION_PROPOSED",
            active_goal=active_goal,
            recall_policy=recall_policy,
            token_counter=token_counter,
            token_budget=token_budget,
            task_budget=task_budget,
            constraints=constraints,
            byte_budget=byte_budget,
            slot_ttl_seconds=min(slot_ttl_seconds, 30),
            action_digest=action_digest,
        )
        authorization: ActionAuthorization | None = None
        if prepared.status == "READY":
            if prepared.route != "ACTION_VALIDATE" or prepared.validation_token is None:
                raise RuntimeError("Runtime did not return an action validation token")
            authorization = ActionAuthorization(
                action_digest=action_digest,
                validation_token=prepared.validation_token,
                trace_pointer=prepared.trace_pointer,
            )
        return ActionValidationResult(
            status=prepared.status,
            reason=prepared.reason,
            authorization=authorization,
            trace_pointer=prepared.trace_pointer,
            usage=prepared.usage,
        )

    def _compile(
        self,
        envelope: PrepareContextEnvelope,
        *,
        query: str,
        identity: TaskMemoryIdentity,
        active_goal: str,
        constraints: tuple[str, ...],
        recall_policy: AgentRecallPolicy,
        token_counter: TokenCounter,
        token_budget: TokenBudget,
        previous: TaskMemorySlot | None,
        slot_ttl_seconds: int,
    ) -> ContextCompileResult:
        capsule = envelope.context_capsule or {}
        sections = capsule.get("protected_sections")
        protected_sections = sections if isinstance(sections, dict) else {}
        recall = RecallEnvelope(
            status="OK",
            items=[],
            issues=[str(issue.get("issue_id")) for issue in envelope.relevant_open_issues],
            trace_id=envelope.trace_pointer,
            consistency=recall_policy.consistency_floor,
            canonical_position={"canonical_outbox_sequence": envelope.canonical_position},
            degraded_components=[],
            fallback_used=False,
            fallback_reason=None,
            abstention_reason=None,
            request_id=envelope.request_id,
            context_capsule_id=str(capsule.get("capsule_id", "")),
            raw=envelope.raw,
        )
        return self._compiler.compile(
            ContextCompileRequest(
                recall_envelope=recall,
                session_id=identity.session_id,
                query_fingerprint=turn_fingerprint(query),
                active_goal=active_goal,
                constraints=constraints,
                previous_slot=previous.compiled_slot if previous is not None else None,
                token_budget=token_budget,
                token_counter=token_counter,
                protected_sections=protected_sections,
                open_issues=envelope.relevant_open_issues,
                slot_ttl_seconds=slot_ttl_seconds,
                safety_required=(
                    recall_policy.authority != "INFORMATIONAL"
                    or recall_policy.consistency_floor == "CANONICAL_REQUIRED"
                ),
            )
        )


def _trace_id(envelope: PrepareContextEnvelope) -> str:
    if envelope.trace_pointer:
        return envelope.trace_pointer
    if envelope.current_state_envelope is not None and envelope.current_state_envelope.trace_id:
        return envelope.current_state_envelope.trace_id
    if envelope.request_id:
        return envelope.request_id
    return "prepare-context:" + _sha256(
        {
            "route": envelope.route,
            "status": envelope.status,
            "reason": envelope.reason,
            "canonical_position": envelope.canonical_position,
            "current_state_status": (
                envelope.current_state_envelope.status
                if envelope.current_state_envelope is not None
                else None
            ),
        }
    )


def _canonical_position(envelope: PrepareContextEnvelope) -> int | None:
    if envelope.current_state_envelope is not None:
        return envelope.current_state_envelope.canonical_position
    return envelope.canonical_position


def _unavailable_outcome(
    envelope: PrepareContextEnvelope,
    *,
    reason_code: str,
    terminal_stage: Literal["CACHE", "TRANSPORT"],
) -> AccessOutcome:
    return AccessOutcome(
        status="MEMORY_REQUIRED_BUT_UNAVAILABLE",
        execution_action="RETRY",
        provider_execution="PROHIBITED",
        terminal_stage=terminal_stage,
        context_digest=None,
        canonical_position=_canonical_position(envelope),
        reason_code=reason_code,
        trace_id=_trace_id(envelope),
    )


def _terminal_outcome(envelope: PrepareContextEnvelope) -> AccessOutcome:
    current_status = (
        envelope.current_state_envelope.status
        if envelope.current_state_envelope is not None
        else None
    )
    reason = envelope.reason or current_status or envelope.status
    canonical_position = _canonical_position(envelope)
    trace_id = _trace_id(envelope)
    if current_status in {"MISS", "AMBIGUOUS"} or envelope.status == "BUDGET_EXHAUSTED":
        return AccessOutcome(
            status="MEMORY_INSUFFICIENT",
            execution_action="ASK_USER",
            provider_execution="PROHIBITED",
            terminal_stage="SUFFICIENCY",
            context_digest=None,
            canonical_position=canonical_position,
            reason_code=reason,
            trace_id=trace_id,
        )
    if current_status == "BLOCKED" or envelope.status == "ABSTAIN":
        return AccessOutcome(
            status="GOVERNANCE_BLOCKED",
            execution_action="ABSTAIN",
            provider_execution="PROHIBITED",
            terminal_stage="GATE",
            context_digest=None,
            canonical_position=canonical_position,
            reason_code=reason,
            trace_id=trace_id,
        )
    return AccessOutcome(
        status="MEMORY_REQUIRED_BUT_UNAVAILABLE",
        execution_action="RETRY",
        provider_execution="PROHIBITED",
        terminal_stage="TRANSPORT",
        context_digest=None,
        canonical_position=canonical_position,
        reason_code=reason,
        trace_id=trace_id,
    )


def _binding_key(
    identity: TaskMemoryIdentity,
    active_goal: str,
    recall_policy: AgentRecallPolicy,
    constraints: tuple[str, ...],
    tokenizer_id: str,
    token_budget: TokenBudget,
    task_budget: TaskMemoryBudget,
    byte_budget: int,
    slot_ttl_seconds: int,
    compiler_digest: str,
    router_digest: str,
    policy_digest: str,
    action_digest: str | None,
) -> str:
    digest = _sha256(
        {
            "identity": {
                "tenant_id": identity.tenant_id,
                "session_id": identity.session_id,
                "agent_id": identity.agent_id,
                "profile_id": identity.profile_id,
                "task_epoch": identity.task_epoch,
            },
            "active_goal": active_goal,
            "scope": recall_policy.scope,
            "authority": recall_policy.authority,
            "consistency": recall_policy.consistency_floor,
            "limit": recall_policy.max_limit,
            "constraints": constraints,
            "tokenizer_id": tokenizer_id,
            "token_budget": {
                "max_memory_tokens": token_budget.max_memory_tokens,
                "max_bytes": token_budget.max_bytes,
                "budget_class": token_budget.budget_class,
                "verified": token_budget.verified,
            },
            "task_budget": task_budget.to_api(),
            "byte_budget": byte_budget,
            "slot_ttl_seconds": slot_ttl_seconds,
            "compiler_digest": compiler_digest,
            "router_digest": router_digest,
            "policy_digest": policy_digest,
            "action_digest": action_digest,
        }
    )
    return _identity_prefix(identity) + digest


def _identity_prefix(identity: TaskMemoryIdentity) -> str:
    return (
        _sha256(
            {
                "tenant_id": identity.tenant_id,
                "session_id": identity.session_id,
                "agent_id": identity.agent_id,
                "profile_id": identity.profile_id,
                "task_epoch": identity.task_epoch,
            }
        )
        + ":"
    )


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _constant_digest_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


def _is_digest(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
