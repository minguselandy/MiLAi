from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from milai_client.client import AsyncMilaiClient, MilaiClientError
from milai_client.formatting import ContextBudgetInfeasibleError
from milai_client.models import AgentRecallPolicy, ContextRequest, ExactRecallRequest
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


class AsyncAgentContext:
    """Framework-neutral async recall/router/compiler coordinator."""

    def __init__(
        self,
        client: AsyncMilaiClient,
        *,
        recall_policy: AgentRecallPolicy,
        token_counter: TokenCounter | None = None,
        token_budget: TokenBudget | None = None,
        recall_router: DeterministicRecallRouter | None = None,
        context_compiler: GovernedContextCompiler | None = None,
        slot_registry: SessionSlotRegistry | None = None,
    ) -> None:
        self.client = client
        self.recall_policy = recall_policy
        self.token_counter = token_counter
        self.token_budget = token_budget
        self.recall_router = recall_router or DeterministicRecallRouter()
        self.context_compiler = context_compiler or GovernedContextCompiler()
        self.slot_registry = slot_registry or SessionSlotRegistry()

    async def prepare(
        self,
        query: str,
        *,
        session_id: str,
        active_goal: str | None = None,
        previous_goal_fingerprint: str | None = None,
        context_constraints: tuple[str, ...] = (),
        known_claim_ids: tuple[str, ...] = (),
        framework_event: FrameworkEvent = "USER_TURN",
        context_byte_budget: int = 16_384,
        slot_ttl_seconds: int = 300,
    ) -> PreparedAgentContext:
        if not session_id:
            raise ValueError("session_id is required")
        previous_slot = self.slot_registry.get(session_id)
        base_input = RecallRoutingInput(
            current_turn=query,
            active_goal=active_goal,
            previous_goal_fingerprint=previous_goal_fingerprint,
            known_object_ids=known_claim_ids,
            requested_scope=self.recall_policy.scope,
            required_authority=self.recall_policy.authority,
            consistency_floor=self.recall_policy.consistency_floor,
            session_snapshot_id=previous_slot.snapshot_id if previous_slot is not None else None,
            canonical_position_seen=(
                previous_slot.canonical_position if previous_slot is not None else None
            ),
            issue_revision_digest_seen=(
                previous_slot.live_issue_revision_digest if previous_slot is not None else None
            ),
            framework_event=framework_event,
            max_limit=self.recall_policy.max_limit,
        )
        preliminary = self.recall_router.decide(base_input)
        budget = self.token_budget or TokenBudget.for_class(
            preliminary.budget_class,
            counter=self.token_counter,
            max_bytes=context_byte_budget,
        )
        bound_input = replace(
            base_input,
            context_binding=context_binding_digest(
                constraints=context_constraints,
                token_budget=budget,
                token_counter=self.token_counter,
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
            cache_validated = await self._validate_slot_cache(previous_slot)
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
                budget=budget,
                counter=self.token_counter,
                reason_code=routing.reason_code,
                retain_previous=retain,
            )
            self.slot_registry.apply(session_id, compiled)
            return PreparedAgentContext(routing, None, compiled)

        if routing.route == "L0" and routing.exact_claim_id is not None:
            envelope = await self.client.recall_exact(
                ExactRecallRequest(
                    claim_id=routing.exact_claim_id,
                    scope=self.recall_policy.scope,
                    authority=self.recall_policy.authority,
                    consistency=self.recall_policy.consistency_floor,
                )
            )
        else:
            envelope = await self.client.recall(
                routing.query or query,
                requested_scope=self.recall_policy.scope,
                required_authority=self.recall_policy.authority,
                consistency=self.recall_policy.consistency_floor,
                limit=routing.limit,
            )

        protected_sections: dict[str, object] | None = None
        if active_goal is not None and envelope.trace_id is not None:
            context = await self.client.build_context(
                ContextRequest(
                    retrieval_trace_id=envelope.trace_id,
                    active_goal=active_goal,
                    constraints=context_constraints,
                    byte_budget=context_byte_budget,
                )
            )
            envelope = replace(envelope, context_capsule_id=context.capsule_id)
            protected_sections = context.protected_sections

        issue_details: tuple[dict[str, object], ...] = ()
        if envelope.issues and protected_sections is None:
            loaded_issue_details: list[dict[str, object]] = []
            for issue_id in envelope.issues:
                loaded_issue_details.append((await self.client.get_open_issue(issue_id)).raw)
            issue_details = tuple(loaded_issue_details)
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
                    token_budget=budget,
                    token_counter=self.token_counter,
                    protected_sections=protected_sections,
                    open_issues=issue_details,
                    cache_key=fresh_cache_key,
                    slot_ttl_seconds=slot_ttl_seconds,
                    safety_required=(
                        self.recall_policy.authority != "INFORMATIONAL"
                        or self.recall_policy.consistency_floor == "CANONICAL_REQUIRED"
                    ),
                )
            )
        except (ContextBudgetInfeasibleError, ContextIntegrityError):
            self.slot_registry.invalidate(session_id)
            raise
        self.slot_registry.apply(session_id, compiled)
        return PreparedAgentContext(routing, envelope, compiled)

    async def _validate_slot_cache(self, slot: MemorySlot) -> bool:
        try:
            status = await self.client.system_watermarks()
            issues = [
                await self.client.get_open_issue(issue_id) for issue_id in slot.live_issue_ids
            ]
        except (AttributeError, MilaiClientError, ValueError):
            return False
        return memory_slot_cache_valid(
            slot,
            canonical_snapshot=status.canonical_snapshot,
            open_issues=tuple(issue.raw for issue in issues),
        )

    def invalidate(self, session_id: str) -> None:
        self.slot_registry.invalidate(session_id)
