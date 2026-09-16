from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from typing import Any

from autogen_core import CancellationToken
from autogen_core.memory import (
    Memory,
    MemoryContent,
    MemoryQueryResult,
    UpdateContextResult,
)
from autogen_core.model_context import ChatCompletionContext
from autogen_core.models import UserMessage
from milai_client import (
    AgentRecallPolicy,
    AsyncMilaiClient,
    ContextCompileRequest,
    DeterministicRecallRouter,
    EvidenceCaptureRequest,
    ExactRecallRequest,
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
from milai_client.client import MilaiClientError

_SECRET_PATTERN = re.compile(
    r"(?i)(authorization\s*:\s*bearer|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"(?:password|api[_-]?key|access[_-]?token|secret)\s*[:=]\s*\S+)"
)


class MilaiMemory(Memory):
    """Official AutoGen Memory adapter without owning AutoGen checkpoint state."""

    component_type = "memory"

    def __init__(
        self,
        client: AsyncMilaiClient,
        *,
        recall_policy: AgentRecallPolicy,
        session_id: str = "autogen-default",
        token_counter: TokenCounter | None = None,
        token_budget: TokenBudget | None = None,
        recall_router: DeterministicRecallRouter | None = None,
        context_compiler: GovernedContextCompiler | None = None,
        slot_registry: SessionSlotRegistry | None = None,
    ) -> None:
        if not session_id:
            raise ValueError("AutoGen MiLAi session_id is required")
        self.client = client
        self.recall_policy = recall_policy
        self.session_id = session_id
        self.token_counter = token_counter
        self.token_budget = token_budget
        self.recall_router = recall_router or DeterministicRecallRouter()
        self.context_compiler = context_compiler or GovernedContextCompiler()
        self.slot_registry = slot_registry or SessionSlotRegistry()
        self.last_write_receipt: dict[str, Any] | None = None

    async def query(
        self,
        query: str | MemoryContent = "",
        cancellation_token: CancellationToken | None = None,
        **kwargs: Any,
    ) -> MemoryQueryResult:
        _raise_if_cancelled(cancellation_token)
        policy_overrides = sorted(
            {"scope", "authority", "consistency", "limit"}.intersection(kwargs)
        )
        if policy_overrides:
            raise PermissionError(
                "AutoGen query cannot override host recall policy: " + ", ".join(policy_overrides)
            )
        text = query.content if isinstance(query, MemoryContent) else query
        if not isinstance(text, str):
            raise TypeError("MiLAi Memory query content must be text")
        prepared = await self._prepare(text, previous_slot=None)
        _raise_if_cancelled(cancellation_token)
        envelope = prepared.recall_envelope
        rendered = prepared.compiled.delta.rendered_context
        if envelope is None or rendered is None:
            return MemoryQueryResult(results=[])
        result = MemoryContent(
            mime_type="text/plain",
            content=rendered,
            metadata={
                "status": envelope.status,
                "trace_id": envelope.trace_id,
                "open_issue_ids": envelope.issues,
                "context_capsule_id": envelope.context_capsule_id,
                "trust": "data-only",
                "slot_id": "milai-memory",
                "snapshot_id": prepared.compiled.delta.snapshot_id,
                "delta_status": prepared.compiled.delta.status,
                "tokenizer_id": prepared.compiled.metrics.tokenizer_id,
                "actual_tokens": prepared.compiled.metrics.actual_tokens,
                "token_budget_verified": prepared.compiled.metrics.token_budget_verified,
            },
        )
        return MemoryQueryResult(results=[result])

    async def update_context(
        self,
        model_context: ChatCompletionContext,
    ) -> UpdateContextResult:
        query = await _last_business_message(model_context)
        previous_slot = self.slot_registry.get(self.session_id)
        prepared = await self._prepare(query, previous_slot=previous_slot)
        compiled = prepared.compiled
        memories = _memory_query_result(prepared)
        if compiled.delta.status in {"REPLACE", "REMOVE"}:
            await _remove_old_memory_slot(model_context)
        if compiled.delta.status == "REPLACE":
            rendered = compiled.delta.rendered_context
            if rendered is None:  # pragma: no cover - compiler invariant
                raise RuntimeError("REPLACE delta returned no rendered context")
            await model_context.add_message(
                UserMessage(content=rendered, source="milai-memory-data")
            )
        self.slot_registry.apply(self.session_id, compiled)
        return UpdateContextResult(memories=memories)

    async def _prepare(
        self,
        query: str,
        *,
        previous_slot: MemorySlot | None,
    ) -> PreparedAgentContext:
        base_input = RecallRoutingInput(
            current_turn=query,
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
            max_limit=self.recall_policy.max_limit,
        )
        preliminary = self.recall_router.decide(base_input)
        budget = self.token_budget or TokenBudget.for_class(
            preliminary.budget_class,
            counter=self.token_counter,
            max_bytes=16_384,
        )
        bound_input = replace(
            base_input,
            context_binding=context_binding_digest(
                constraints=(),
                token_budget=budget,
                token_counter=self.token_counter,
                context_byte_budget=16_384,
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
            compiled = self.context_compiler.without_recall(
                previous_slot=previous_slot,
                budget=budget,
                counter=self.token_counter,
                reason_code=routing.reason_code,
                retain_previous=routing.route == "CACHE",
            )
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
        issue_details: tuple[dict[str, Any], ...] = ()
        if envelope.issues:
            loaded_issue_details: list[dict[str, Any]] = []
            for issue_id in envelope.issues:
                loaded_issue_details.append((await self.client.get_open_issue(issue_id)).raw)
            issue_details = tuple(loaded_issue_details)
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
                    issue_revision_digest_seen=issue_revision_digest(issue_details),
                )
            )
        except ValueError as exc:
            raise ValueError("MiLAi returned invalid OpenIssue details") from exc
        compiled = self.context_compiler.compile(
            ContextCompileRequest(
                recall_envelope=envelope,
                session_id=self.session_id,
                query_fingerprint=routing.query_fingerprint,
                previous_slot=previous_slot,
                token_budget=budget,
                token_counter=self.token_counter,
                open_issues=issue_details,
                cache_key=fresh_cache_key,
                safety_required=(
                    self.recall_policy.authority != "INFORMATIONAL"
                    or self.recall_policy.consistency_floor == "CANONICAL_REQUIRED"
                ),
            )
        )
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

    async def add(
        self,
        content: MemoryContent,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        _raise_if_cancelled(cancellation_token)
        metadata = content.metadata or {}
        source = metadata.get("source")
        if source not in {"user", "tool"}:
            raise PermissionError("model/assistant output is not Evidence")
        if metadata.get("capture_confirmed") is not True:
            raise PermissionError("explicit capture confirmation is required")
        if source == "tool" and metadata.get("tool_allowlisted") is not True:
            raise PermissionError("tool source is not allowlisted")
        text = content.content
        if not isinstance(text, str):
            raise TypeError("MiLAi Evidence capture accepts text after host redaction")
        if metadata.get("redaction_status") != "SAFE" or _SECRET_PATTERN.search(text):
            raise PermissionError("sensitive or unredacted content is not capturable")
        request = EvidenceCaptureRequest.model_validate(
            {
                "source_type": ("USER_OBSERVATION" if source == "user" else "TOOL_OBSERVATION"),
                "source_ref": metadata.get("source_ref"),
                "subject_id": metadata.get("subject_id"),
                "speaker": source,
                "source_context": metadata.get("source_context"),
                "observed_at": metadata.get("observed_at"),
                "content": text,
                "permission_snapshot": metadata.get("permission_snapshot", {}),
            }
        )
        receipt = await self.client.capture_evidence(
            request, operation_id=str(metadata.get("operation_id", ""))
        )
        _raise_if_cancelled(cancellation_token)
        self.last_write_receipt = receipt.raw

    async def clear(self) -> None:
        raise PermissionError("MiLAi tenant clear is intentionally unavailable")

    async def close(self) -> None:
        self.slot_registry.clear()
        await self.client.close()


def _raise_if_cancelled(token: CancellationToken | None) -> None:
    if token is not None and token.is_cancelled():
        raise asyncio.CancelledError


def _memory_query_result(prepared: PreparedAgentContext) -> MemoryQueryResult:
    envelope = prepared.recall_envelope
    rendered = prepared.compiled.delta.rendered_context
    if envelope is None or rendered is None:
        return MemoryQueryResult(results=[])
    return MemoryQueryResult(
        results=[
            MemoryContent(
                mime_type="text/plain",
                content=rendered,
                metadata={
                    "status": envelope.status,
                    "trace_id": envelope.trace_id,
                    "open_issue_ids": envelope.issues,
                    "context_capsule_id": envelope.context_capsule_id,
                    "trust": "data-only",
                    "slot_id": "milai-memory",
                    "snapshot_id": prepared.compiled.delta.snapshot_id,
                    "delta_status": prepared.compiled.delta.status,
                    "tokenizer_id": prepared.compiled.metrics.tokenizer_id,
                    "actual_tokens": prepared.compiled.metrics.actual_tokens,
                    "token_budget_verified": (prepared.compiled.metrics.token_budget_verified),
                },
            )
        ]
    )


async def _last_business_message(model_context: ChatCompletionContext) -> str:
    for message in reversed(await model_context.get_messages()):
        content = message.content
        if getattr(message, "source", None) == "milai-memory-data":
            continue
        return content if isinstance(content, str) else str(content)
    return ""


async def _remove_old_memory_slot(model_context: ChatCompletionContext) -> None:
    state = dict(await model_context.save_state())
    raw_messages = state.get("messages")
    if not isinstance(raw_messages, list):
        raise RuntimeError("AutoGen context state does not contain a messages list")
    filtered: list[object] = []
    for raw in raw_messages:
        if not isinstance(raw, dict):
            filtered.append(raw)
            continue
        is_milai_slot = raw.get("source") == "milai-memory-data"
        if not is_milai_slot:
            filtered.append(raw)
    if len(filtered) != len(raw_messages):
        state["messages"] = filtered
        await model_context.load_state(state)
