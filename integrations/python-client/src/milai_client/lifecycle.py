from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal, cast

from milai_client.client import MilaiClient, MilaiClientError
from milai_client.formatting import ContextBudgetInfeasibleError, format_memory_for_prompt
from milai_client.models import (
    AgentRecallPolicy,
    ContextRequest,
    ExactRecallRequest,
    ObservationOutcome,
    ProposalDraft,
    RecallEnvelope,
)
from milai_client.optimization import (
    ContextCompileRequest,
    ContextIntegrityError,
    DeterministicRecallRouter,
    FrameworkEvent,
    GovernedContextCompiler,
    MemorySlot,
    PreparedAgentContext,
    RecallRoutingInput,
    SessionSlotRegistry,
    TokenBudget,
    TokenCounter,
    context_binding_digest,
    issue_revision_digest,
    memory_slot_cache_valid,
    turn_fingerprint,
)

CaptureMode = Literal["OFF", "ASK_EACH_TIME", "ALLOWLISTED"]
_CREDENTIAL_PATTERN = re.compile(
    r"(?i)(authorization\s*:\s*bearer|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"(?:password|passwd|api[_-]?key|access[_-]?token|secret)\s*[:=]\s*\S+)"
)


@dataclass(frozen=True, slots=True)
class CapturePolicy:
    """Host-owned capture decision; no mode grants review or canonical mutation."""

    mode: CaptureMode = "OFF"
    allowed_user_sources: frozenset[str] = frozenset()
    allowed_tool_sources: frozenset[str] = frozenset()
    sensitive_sources: frozenset[str] = frozenset(
        {"credential", "credentials", "env", "raw_log", "raw_prompt", "system_prompt"}
    )
    auto_create_proposal: bool = False
    capture_model_output: bool = False
    capture_raw_prompt: bool = False

    def __post_init__(self) -> None:
        if self.mode not in {"OFF", "ASK_EACH_TIME", "ALLOWLISTED"}:
            raise ValueError("capture mode must be OFF, ASK_EACH_TIME or ALLOWLISTED")
        if self.capture_model_output:
            raise ValueError("assistant/model output cannot be enabled as Evidence")
        if self.capture_raw_prompt:
            raise ValueError("complete prompts cannot be enabled as Evidence")
        if self.auto_create_proposal:
            raise ValueError(
                "automatic Proposal creation is disabled; use an explicit extractor boundary"
            )


@dataclass(slots=True)
class _SessionRefs:
    evidence: list[str] = field(default_factory=list)
    chat_turns: list[str] = field(default_factory=list)
    context_capsules: list[str] = field(default_factory=list)
    pending_proposals: list[str] = field(default_factory=list)


class AgentMemory:
    def __init__(
        self,
        client: MilaiClient,
        policy: CapturePolicy | None = None,
        *,
        recall_router: DeterministicRecallRouter | None = None,
        context_compiler: GovernedContextCompiler | None = None,
        slot_registry: SessionSlotRegistry | None = None,
    ) -> None:
        self.client = client
        self.policy = policy or CapturePolicy()
        self.recall_router = recall_router or DeterministicRecallRouter()
        self.context_compiler = context_compiler or GovernedContextCompiler()
        self.slot_registry = slot_registry or SessionSlotRegistry()
        self._sessions: dict[str, _SessionRefs] = {}
        self._operation_times: dict[str, str] = {}

    def on_session_start(self, session_id: str) -> dict[str, Any]:
        self._sessions.setdefault(session_id, _SessionRefs())
        health = self.client.health()
        capabilities = self.client.capabilities()
        issues = self.client.list_open_issues("OPEN")
        return {
            "session_id": session_id,
            "health": {
                "live": health.live,
                "ready": health.ready,
                "schema_status": health.schema_status,
                "implementation_status": health.implementation_status,
            },
            "capabilities": capabilities.raw,
            "live_issues": [
                {"issue_id": issue.issue_id, "status": issue.status, "revision": issue.revision}
                for issue in issues
            ],
        }

    def before_model(
        self,
        query: str,
        *,
        session_id: str | None = None,
        active_goal: str | None = None,
        context_constraints: tuple[str, ...] = (),
        context_byte_budget: int = 16_384,
        **recall_options: Any,
    ) -> tuple[RecallEnvelope, str]:
        envelope = self.client.recall(query, **recall_options)
        if active_goal is not None and envelope.trace_id is not None:
            context = self.client.build_context(
                ContextRequest(
                    retrieval_trace_id=envelope.trace_id,
                    active_goal=active_goal,
                    constraints=context_constraints,
                    byte_budget=context_byte_budget,
                )
            )
            envelope = replace(envelope, context_capsule_id=context.capsule_id)
            if session_id is not None:
                self._append_ref(session_id, "context_capsules", context.capsule_id)
        return envelope, format_memory_for_prompt(envelope, max_bytes=context_byte_budget)

    def prepare_context(
        self,
        query: str,
        *,
        session_id: str,
        recall_policy: AgentRecallPolicy,
        active_goal: str | None = None,
        previous_goal_fingerprint: str | None = None,
        context_constraints: tuple[str, ...] = (),
        known_claim_ids: tuple[str, ...] = (),
        framework_event: FrameworkEvent = "USER_TURN",
        token_counter: TokenCounter | None = None,
        token_budget: TokenBudget | None = None,
        context_byte_budget: int = 16_384,
        slot_ttl_seconds: int = 300,
    ) -> PreparedAgentContext:
        """Prepare a replace/remove/unchanged memory slot without implicit writes."""
        self._sessions.setdefault(session_id, _SessionRefs())
        previous_slot = self.slot_registry.get(session_id)
        base_input = RecallRoutingInput(
            current_turn=query,
            active_goal=active_goal,
            previous_goal_fingerprint=previous_goal_fingerprint,
            known_object_ids=known_claim_ids,
            requested_scope=recall_policy.scope,
            required_authority=recall_policy.authority,
            consistency_floor=recall_policy.consistency_floor,
            session_snapshot_id=previous_slot.snapshot_id if previous_slot is not None else None,
            canonical_position_seen=(
                previous_slot.canonical_position if previous_slot is not None else None
            ),
            issue_revision_digest_seen=(
                previous_slot.live_issue_revision_digest if previous_slot is not None else None
            ),
            framework_event=framework_event,
            max_limit=recall_policy.max_limit,
        )
        preliminary = self.recall_router.decide(base_input)
        effective_budget = token_budget or TokenBudget.for_class(
            preliminary.budget_class,
            counter=token_counter,
            max_bytes=context_byte_budget,
        )
        bound_input = replace(
            base_input,
            context_binding=context_binding_digest(
                constraints=context_constraints,
                token_budget=effective_budget,
                token_counter=token_counter,
                slot_ttl_seconds=slot_ttl_seconds,
                context_byte_budget=context_byte_budget,
            ),
        )
        cache_validated = False
        if (
            previous_slot is not None
            and previous_slot.query_fingerprint == turn_fingerprint(query)
            and previous_slot.cache_key == self.recall_router.cache_key(bound_input)
        ):
            cache_validated = self._validate_slot_cache(previous_slot)
        routing = self.recall_router.decide(
            replace(
                bound_input,
                cached_query_fingerprint=(
                    previous_slot.query_fingerprint if previous_slot is not None else None
                ),
                cache_validated=cache_validated,
            )
        )
        if routing.route in {"NONE", "CACHE"}:
            retain = routing.route == "CACHE" or routing.reason_code == (
                "MODEL_RETRY_REUSES_VALIDATED_SLOT"
            )
            compiled = self.context_compiler.without_recall(
                previous_slot=previous_slot,
                budget=effective_budget,
                counter=token_counter,
                reason_code=routing.reason_code,
                retain_previous=retain,
            )
            self.slot_registry.apply(session_id, compiled)
            return PreparedAgentContext(routing, None, compiled)

        if routing.route == "L0" and routing.exact_claim_id is not None:
            envelope = self.client.recall_exact(
                ExactRecallRequest(
                    claim_id=routing.exact_claim_id,
                    scope=recall_policy.scope,
                    authority=recall_policy.authority,
                    consistency=recall_policy.consistency_floor,
                )
            )
        else:
            envelope = self.client.recall(
                routing.query or query,
                requested_scope=recall_policy.scope,
                required_authority=recall_policy.authority,
                consistency=recall_policy.consistency_floor,
                limit=routing.limit,
            )

        protected_sections: dict[str, object] | None = None
        if active_goal is not None and envelope.trace_id is not None:
            context = self.client.build_context(
                ContextRequest(
                    retrieval_trace_id=envelope.trace_id,
                    active_goal=active_goal,
                    constraints=context_constraints,
                    byte_budget=context_byte_budget,
                )
            )
            envelope = replace(envelope, context_capsule_id=context.capsule_id)
            protected_sections = context.protected_sections
            self._append_ref(session_id, "context_capsules", context.capsule_id)

        issue_details: tuple[dict[str, object], ...] = ()
        if envelope.issues and protected_sections is None:
            issue_details = tuple(
                cast(dict[str, object], self.client.get_open_issue(issue_id).raw)
                for issue_id in envelope.issues
            )
        cache_issues: tuple[Mapping[str, object], ...]
        if protected_sections is not None:
            raw_cache_issues = protected_sections.get("OPEN ISSUES", [])
            cache_issues = (
                tuple(item for item in raw_cache_issues if isinstance(item, dict))
                if isinstance(raw_cache_issues, list)
                else ()
            )
        else:
            cache_issues = issue_details
        canonical_position = None
        if envelope.canonical_position is not None:
            raw_position = envelope.canonical_position.get("canonical_outbox_sequence")
            if isinstance(raw_position, int) and not isinstance(raw_position, bool):
                canonical_position = raw_position
        try:
            fresh_cache_key = self.recall_router.cache_key(
                replace(
                    bound_input,
                    canonical_position_seen=canonical_position,
                    issue_revision_digest_seen=issue_revision_digest(cache_issues),
                )
            )
        except ValueError as exc:
            self.slot_registry.invalidate(session_id)
            raise ContextIntegrityError("CONTEXT_ISSUE_DETAILS_INVALID") from exc
        try:
            compiled = self.context_compiler.compile(
                ContextCompileRequest(
                    recall_envelope=envelope,
                    session_id=session_id,
                    query_fingerprint=routing.query_fingerprint,
                    active_goal=active_goal,
                    constraints=context_constraints,
                    previous_slot=previous_slot,
                    token_budget=effective_budget,
                    token_counter=token_counter,
                    protected_sections=protected_sections,
                    open_issues=issue_details,
                    cache_key=fresh_cache_key,
                    slot_ttl_seconds=slot_ttl_seconds,
                    safety_required=(
                        recall_policy.authority != "INFORMATIONAL"
                        or recall_policy.consistency_floor == "CANONICAL_REQUIRED"
                    ),
                )
            )
        except (ContextBudgetInfeasibleError, ContextIntegrityError):
            self.slot_registry.invalidate(session_id)
            raise
        self.slot_registry.apply(session_id, compiled)
        return PreparedAgentContext(routing, envelope, compiled)

    def _validate_slot_cache(self, slot: MemorySlot) -> bool:
        try:
            status = self.client.system_watermarks()
            issues = [self.client.get_open_issue(issue_id) for issue_id in slot.live_issue_ids]
        except (AttributeError, MilaiClientError, ValueError):
            return False
        return memory_slot_cache_valid(
            slot,
            canonical_snapshot=status.canonical_snapshot,
            open_issues=tuple(issue.raw for issue in issues),
        )

    def invalidate_context(self, session_id: str) -> None:
        self.slot_registry.invalidate(session_id)

    def on_demand_recall(self, query: str, **recall_options: Any) -> RecallEnvelope:
        return self.client.recall(query, **recall_options)

    def after_user_observation(
        self,
        *,
        session_id: str,
        turn_id: str,
        subject_id: str,
        content: str,
        source_name: str = "user_statement",
        capture_confirmed: bool = False,
        contains_credentials: bool = False,
        is_full_prompt: bool = False,
        observed_at: str | None = None,
    ) -> ObservationOutcome:
        denial = self._capture_denial(
            source_kind="user",
            source_name=source_name,
            content=content,
            capture_confirmed=capture_confirmed,
            contains_credentials=contains_credentials,
            is_full_prompt=is_full_prompt,
            is_raw_log=False,
        )
        if denial is not None:
            return ObservationOutcome(None, None, capture_denied_reason=denial)
        return self._capture(
            session_id=session_id,
            operation_seed=f"user:{session_id}:{turn_id}",
            source_type="USER_OBSERVATION",
            source_ref=f"agent-session:{session_id}/turn:{turn_id}/source:{source_name}",
            subject_id=subject_id,
            content=content,
            observed_at=observed_at,
        )

    def after_tool_observation(
        self,
        *,
        session_id: str,
        call_id: str,
        tool_name: str,
        subject_id: str,
        content: str,
        capture_confirmed: bool = False,
        contains_credentials: bool = False,
        is_raw_log: bool = False,
        observed_at: str | None = None,
        source_type: Literal["TOOL_OBSERVATION", "RUNTIME_OBSERVATION"] = "TOOL_OBSERVATION",
    ) -> ObservationOutcome:
        denial = self._capture_denial(
            source_kind="tool",
            source_name=tool_name,
            content=content,
            capture_confirmed=capture_confirmed,
            contains_credentials=contains_credentials,
            is_full_prompt=False,
            is_raw_log=is_raw_log,
        )
        if denial is not None:
            return ObservationOutcome(None, None, capture_denied_reason=denial)
        return self._capture(
            session_id=session_id,
            operation_seed=f"tool:{session_id}:{call_id}",
            source_type=source_type,
            source_ref=f"agent-session:{session_id}/tool:{tool_name}/call:{call_id}",
            subject_id=subject_id,
            content=content,
            observed_at=observed_at,
        )

    def after_model(
        self,
        _content: str,
        *,
        session_id: str | None = None,
        chat_turn_id: str | None = None,
        context_capsule_id: str | None = None,
    ) -> dict[str, Any]:
        """Record only server-created references; model text is intentionally discarded."""
        if session_id is not None:
            if chat_turn_id is not None:
                self._append_ref(session_id, "chat_turns", chat_turn_id)
            if context_capsule_id is not None:
                self._append_ref(session_id, "context_capsules", context_capsule_id)
        return {
            "status": "MODEL_OUTPUT_NOT_EVIDENCE",
            "chat_turn_id": chat_turn_id,
            "context_capsule_id": context_capsule_id,
        }

    def before_compaction(
        self,
        query: str,
        *,
        session_id: str | None = None,
        active_goal: str = "preserve governed memory before compaction",
    ) -> str:
        _, block = self.before_model(
            query,
            session_id=session_id,
            active_goal=active_goal,
            consistency="CANONICAL_REQUIRED",
        )
        return block

    def on_session_end(self, session_id: str, *, subject_id: str) -> dict[str, Any]:
        refs = self._sessions.setdefault(session_id, _SessionRefs())
        self.slot_registry.invalidate(session_id)
        review_url = (
            f"{self.client.base_url}/#proposals=" + ",".join(refs.pending_proposals)
            if refs.pending_proposals
            else None
        )
        if not (refs.evidence or refs.chat_turns or refs.context_capsules):
            return {
                "session_id": session_id,
                "status": "CLOSED_NO_REPLAYABLE_REFS",
                "pending_proposal_ids": list(refs.pending_proposals),
                "review_url": review_url,
                "settlement_created": False,
            }
        episode = self.client.create_episode(
            subject_id=subject_id,
            evidence_refs=list(refs.evidence),
            chat_turn_refs=list(refs.chat_turns),
            context_capsule_refs=list(refs.context_capsules),
            operation_id=_operation_id(f"episode:{session_id}"),
        )
        return {
            "session_id": session_id,
            "status": "EPISODE_CAPTURED_NO_IMPLICIT_SETTLEMENT",
            "episode": episode.raw,
            "pending_proposal_ids": list(refs.pending_proposals),
            "review_url": review_url,
            "settlement_created": False,
        }

    def create_proposal(
        self,
        payload: ProposalDraft | dict[str, Any],
        *,
        session_id: str,
        candidate_id: str,
    ) -> dict[str, Any]:
        operation_id = _operation_id(f"proposal:{session_id}:{candidate_id}")
        draft = (
            payload if isinstance(payload, ProposalDraft) else ProposalDraft.model_validate(payload)
        )
        if draft.target_claim_id is not None:
            draft.validate_current_head(
                self.client.get_claim(draft.target_claim_id).claim_version_id
            )
        receipt = self.client.create_proposal(draft, operation_id=operation_id)
        self._append_ref(session_id, "pending_proposals", receipt.proposal_id)
        return receipt.raw

    def _capture(
        self,
        *,
        session_id: str,
        operation_seed: str,
        source_type: str,
        source_ref: str,
        subject_id: str,
        content: str,
        observed_at: str | None,
    ) -> ObservationOutcome:
        stable_observed_at = observed_at or self._operation_times.setdefault(
            operation_seed, datetime.now(UTC).isoformat()
        )
        evidence = self.client.capture_evidence(
            {
                "source_type": source_type,
                "source_ref": source_ref,
                "subject_id": subject_id,
                "observed_at": stable_observed_at,
                "content": content,
                "permission_snapshot": {
                    "readable": True,
                    "agent_capture": True,
                    "scope": "local",
                },
            },
            operation_id=_operation_id(operation_seed),
        )
        self._append_ref(session_id, "evidence", evidence.evidence_id)
        return ObservationOutcome(evidence.raw, None)

    def _capture_denial(
        self,
        *,
        source_kind: Literal["user", "tool"],
        source_name: str,
        content: str,
        capture_confirmed: bool,
        contains_credentials: bool,
        is_full_prompt: bool,
        is_raw_log: bool,
    ) -> str | None:
        normalized = source_name.strip().lower()
        if (
            normalized in {item.lower() for item in self.policy.sensitive_sources}
            or contains_credentials
            or is_full_prompt
            or is_raw_log
            or _CREDENTIAL_PATTERN.search(content) is not None
        ):
            return "SENSITIVE_SOURCE_REJECTED"
        if self.policy.mode == "OFF":
            return "CAPTURE_POLICY_OFF"
        if self.policy.mode == "ASK_EACH_TIME" and not capture_confirmed:
            return "CAPTURE_CONFIRMATION_REQUIRED"
        if self.policy.mode == "ALLOWLISTED":
            allowlist = (
                self.policy.allowed_user_sources
                if source_kind == "user"
                else self.policy.allowed_tool_sources
            )
            if source_name not in allowlist:
                return "SOURCE_NOT_ALLOWLISTED"
        return None

    def _append_ref(self, session_id: str, field_name: str, value: str) -> None:
        refs = self._sessions.setdefault(session_id, _SessionRefs())
        values = getattr(refs, field_name)
        if value not in values:
            values.append(value)


def _operation_id(seed: str) -> str:
    return "agent-v1-" + hashlib.sha256(seed.encode()).hexdigest()
