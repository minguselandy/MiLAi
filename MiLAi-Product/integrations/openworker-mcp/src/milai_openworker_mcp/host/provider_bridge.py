"""OpenWorker provider, memory and settlement orchestration bridge."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import defaultdict, deque
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass as dataclass
from pathlib import Path
from typing import Any, cast

from milai_client import (
    AgentRecallPolicy,
    ContextBudgetInfeasibleError,
    ContextIntegrityError,
    DeterministicMemoryNeedResolver,
    DeterministicQueryOnlyIntentShadow,
    MemoryNeedResolution,
    TaskMemoryBudget,
    TaskPreparedContext,
    TokenBudget,
)
from milai_client import (
    TaskBindingContext as TaskBindingContext,
)
from milai_client import (
    TaskMemoryIdentity as TaskMemoryIdentity,
)
from milai_client import (
    TaskMemoryState as TaskMemoryState,
)
from milai_client.context_policy import PrefetchContext, prepare_prefetch
from milai_client.models import PrepareContextEvent as PrepareContextEvent

from milai_openworker_mcp import TargetTokenizerCounter, build_task_memory_controller
from milai_openworker_mcp.completion_capture import (
    CompletionCaptureError,
    buffer_openai_stream,
    final_assistant_content,
    replace_assistant_content,
)
from milai_openworker_mcp.evidence_use import (
    EvidenceLedgerV01,
    EvidenceUseMode,
    EvidenceUseValidationError,
    GroundedEvidenceUseV01,
    apply_evidence_use_protocol,
    apply_ledger_final_protocol,
    parse_evidence_ledger,
    parse_grounded_evidence_use,
)
from milai_openworker_mcp.host.ingress import StartupTaskPolicy as StartupTaskPolicy
from milai_openworker_mcp.host.ingress import (
    _load_startup_task_policy,
)
from milai_openworker_mcp.host.memory_flow import (
    _HOST_PREFETCH_MODES as _HOST_PREFETCH_MODES,
)
from milai_openworker_mcp.host.memory_flow import (
    _completion as _completion,
)
from milai_openworker_mcp.host.memory_flow import (
    _last_user_content as _last_user_content,
)
from milai_openworker_mcp.host.memory_flow import (
    _memory_answer_eligible as _memory_answer_eligible,
)
from milai_openworker_mcp.host.memory_flow import (
    _memory_insufficient_outcome as _memory_insufficient_outcome,
)
from milai_openworker_mcp.host.memory_flow import (
    _memory_terminal_completion as _memory_terminal_completion,
)
from milai_openworker_mcp.host.memory_flow import (
    _messages as _messages,
)
from milai_openworker_mcp.host.memory_flow import (
    _native_user_content as _native_user_content,
)
from milai_openworker_mcp.host.memory_flow import (
    _prepared_prefetch as _prepared_prefetch,
)
from milai_openworker_mcp.host.memory_flow import (
    _question as _question,
)
from milai_openworker_mcp.host.memory_flow import (
    _recall_from_messages as _recall_from_messages,
)
from milai_openworker_mcp.host.memory_flow import (
    _recall_object as _recall_object,
)
from milai_openworker_mcp.host.memory_flow import (
    _recall_query as _recall_query,
)
from milai_openworker_mcp.host.memory_flow import (
    _resolve_prepared_context as _resolve_prepared_context,
)
from milai_openworker_mcp.host.memory_flow import (
    _should_recall as _should_recall,
)
from milai_openworker_mcp.host.memory_flow import (
    _text as _text,
)
from milai_openworker_mcp.host.memory_flow import (
    _transport_unavailable_outcome as _transport_unavailable_outcome,
)
from milai_openworker_mcp.host.request_contract import (
    _MEMORY_READING_POLICY as _MEMORY_READING_POLICY,
)
from milai_openworker_mcp.host.request_contract import (
    EXACT_MODEL_ID,
    OpenAIChatRequest,
    OpenWorkerAdapterError,
    StreamingCompletion,
    _is_memory_tool,
)
from milai_openworker_mcp.host.request_contract import _tool_choice_name as _tool_choice_name
from milai_openworker_mcp.host.request_contract import (
    _tool_definition_name as _tool_definition_name,
)
from milai_openworker_mcp.host.task_state import (
    _TASK_EVENTS as _TASK_EVENTS,
)
from milai_openworker_mcp.host.task_state import HostTaskState
from milai_openworker_mcp.host.task_state import (
    _BoundTaskState as _BoundTaskState,
)
from milai_openworker_mcp.host.tool_compat import (
    _ORDINARY_READ_PATH as _ORDINARY_READ_PATH,
)
from milai_openworker_mcp.host.tool_compat import (
    _VLLM_JSON_SCHEMA_NAMED_TOOL as _VLLM_JSON_SCHEMA_NAMED_TOOL,
)
from milai_openworker_mcp.host.tool_compat import (
    _apply_single_ordinary_tool_required_once,
    _apply_vllm_json_schema_named_tool_compatibility,
    _canonical,
    _sse,
    _vllm_json_schema_named_tool_chunks,
)
from milai_openworker_mcp.host.tool_compat import (
    _ordinary_read_completion as _ordinary_read_completion,
)
from milai_openworker_mcp.host.trace import (
    _evidence_use_trace_result as _evidence_use_trace_result,
)
from milai_openworker_mcp.host.trace import (
    _host_access_trace_link as _host_access_trace_link,
)
from milai_openworker_mcp.host.trace import (
    _native_request_observation as _native_request_observation,
)
from milai_openworker_mcp.host.trace import (
    _nonnegative_difference as _nonnegative_difference,
)
from milai_openworker_mcp.host.trace import (
    _progressive_l1_trace as _progressive_l1_trace,
)
from milai_openworker_mcp.host.trace import (
    _query_only_intent_shadow_trace as _query_only_intent_shadow_trace,
)
from milai_openworker_mcp.host.trace import (
    _requested_memory_route as _requested_memory_route,
)
from milai_openworker_mcp.host.trace import (
    _shadow_route_trace as _shadow_route_trace,
)
from milai_openworker_mcp.memory_facade import (
    OpenWorkerMemoryFacade,
    OpenWorkerMemoryRecall,
)
from milai_openworker_mcp.provider_execution import (
    BudgetError,
    CapabilityError,
    DevRunCapability,
    JsonCompletionTransport,
    ProviderCallError,
    ProviderExecutionGateway,
    ProviderRequest,
    ProviderTransport,
    StreamCompletionTransport,
)
from milai_openworker_mcp.provider_execution import (
    ProviderTransportError as ProviderTransportError,
)
from milai_openworker_mcp.provider_execution import (
    _SseObserver as _SseObserver,
)
from milai_openworker_mcp.reader_session import (
    ReaderModelProfile,
    ReaderProviderRound,
    ReaderSessionError,
    ReaderSessionInput,
    ReaderSessionResult,
    VllmEvidenceReaderSession,
)
from milai_openworker_mcp.settlement import MemoryDataClassification
from milai_openworker_mcp.task_binding import (
    DeterministicTaskRelationResolver,
    DeterministicTaskTransitionValidator,
    HostTaskRegistry,
    NativeTaskMetadata,
    SameProcessTaskRegistry,
)
from milai_openworker_mcp.task_binding import (
    HostTaskRelationEvent as HostTaskRelationEvent,
)
from milai_openworker_mcp.task_binding import (
    TaskBindingConflict as TaskBindingConflict,
)
from milai_openworker_mcp.task_binding import (
    TaskResolution as TaskResolution,
)
from milai_openworker_mcp.task_binding import (
    bind_host_task as bind_host_task,
)
from milai_openworker_mcp.transport import McpUnixClient, McpUnixClientError

_EVIDENCE_USE_MODES = frozenset(
    {"direct", "inventory", "grounded", "ledger", "model-native"}
)
_QUERY_FIRST_MAX_CONTEXT_CHARS = 262_144
_READER_FALLBACK_ANSWER = (
    "I couldn't reliably complete this memory answer from the available evidence."
)
def _per_request_token_budget(total_tokens: int, max_native_requests: int) -> int:
    """Partition a run-level capability budget without over-reserving its first call."""

    per_request = total_tokens // max_native_requests
    if per_request < 1:
        raise OpenWorkerAdapterError("provider token budget is smaller than native request budget")
    return per_request


def _bounded_provider_timeout(value: object) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not 0 < float(value) <= 600
    ):
        raise ValueError("provider timeout must be between 0 and 600 seconds")
    return float(value)


def _task_seed(question: str) -> int:
    return int(hashlib.sha256(question.encode()).hexdigest()[:16], 16) & ((1 << 63) - 1)


def _tool_name(tools: object) -> str | None:
    if not isinstance(tools, Sequence) or isinstance(tools, (str, bytes)):
        return None
    for item in tools:
        if not isinstance(item, Mapping):
            continue
        function = item.get("function")
        name = function.get("name") if isinstance(function, Mapping) else None
        if isinstance(name, str) and _is_memory_tool(name):
            return name
    return None


class OpenWorkerProviderAdapter(HostTaskState):
    settlement_enabled = False

    def __init__(
        self,
        manifest: Path,
        ledger: Path,
        trace: Path,
        *,
        memory_mode: str = "auto",
        prefetch_socket: Path | None = None,
        tokenizer_json: Path | None = None,
        broker_policy: Path | None = None,
        task_fixture: Path | None = None,
        task_session_id: str | None = None,
        provider_timeout_seconds: float = 60,
        single_ordinary_tool_required_once: str | None = None,
        ordinary_tool_provider_compatibility: str | None = None,
        submitter_socket: Path | None = None,
        memory_subject_id: str | None = None,
        memory_data_classification: str = "SYNTHETIC",
        evidence_use_mode: str = "direct",
    ) -> None:
        if memory_mode not in {"auto", "none", *_HOST_PREFETCH_MODES}:
            raise ValueError("unknown memory mode")
        host_prefetch = memory_mode in _HOST_PREFETCH_MODES
        if host_prefetch and prefetch_socket is None:
            raise ValueError("prefetch mode requires a host MCP socket")
        if not host_prefetch and prefetch_socket is not None:
            raise ValueError("host MCP socket is only valid in prefetch mode")
        if host_prefetch and tokenizer_json is None:
            raise ValueError("prefetch mode requires the target tokenizer.json")
        if not host_prefetch and tokenizer_json is not None:
            raise ValueError("target tokenizer is only valid in prefetch mode")
        if host_prefetch and (broker_policy is None or task_fixture is None):
            raise ValueError("prefetch mode requires broker policy and task fixture")
        if not host_prefetch and (broker_policy is not None or task_fixture is not None):
            raise ValueError("startup task policy is only valid in prefetch mode")
        if host_prefetch and task_session_id is not None:
            raise ValueError("prefetch task identity must come from native headers")
        if task_session_id is not None and (
            not task_session_id.strip() or len(task_session_id) > 256
        ):
            raise ValueError("task_session_id must contain 1-256 characters")
        if single_ordinary_tool_required_once not in {None, "read"}:
            raise ValueError("single ordinary tool compatibility only supports read")
        if ordinary_tool_provider_compatibility not in {
            None,
            _VLLM_JSON_SCHEMA_NAMED_TOOL,
        }:
            raise ValueError("unknown ordinary tool provider compatibility")
        if (
            ordinary_tool_provider_compatibility is not None
            and single_ordinary_tool_required_once != "read"
        ):
            raise ValueError("ordinary provider compatibility requires the read policy")
        if evidence_use_mode not in _EVIDENCE_USE_MODES:
            raise ValueError("unknown evidence-use mode")
        if evidence_use_mode != "direct" and memory_mode != "query-first":
            raise ValueError("evidence-use treatment requires query-first memory")
        if submitter_socket is not None and memory_mode != "query-first":
            raise ValueError("exchange settlement requires query-first memory")
        if (submitter_socket is None) != (memory_subject_id is None):
            raise ValueError("submitter socket and memory subject must be configured together")
        if submitter_socket is not None and submitter_socket == prefetch_socket:
            raise ValueError("reader and submitter sockets must be independent")
        if memory_data_classification not in {"SYNTHETIC", "DEIDENTIFIED", "PERSONAL"}:
            raise ValueError("unknown memory data classification")
        self.gateway = ProviderExecutionGateway(manifest, ledger)
        self.transport: ProviderTransport = JsonCompletionTransport()
        self.stream_transport = StreamCompletionTransport()
        capability = DevRunCapability.load(manifest)
        next_logical_request_sequence = self.gateway.next_logical_request_sequence()
        if capability.model_id != EXACT_MODEL_ID:
            raise ValueError("provider capability model is not the frozen U1 model")
        self.provider_capability = capability
        self.provider_timeout_seconds = _bounded_provider_timeout(provider_timeout_seconds)
        self.single_ordinary_tool_required_once = single_ordinary_tool_required_once
        self.ordinary_tool_provider_compatibility = ordinary_tool_provider_compatibility
        self.evidence_use_mode = cast(EvidenceUseMode, evidence_use_mode)
        self.run_id = capability.run_id
        self.trace = trace
        self.memory_mode = memory_mode
        self.task_session_id = task_session_id.strip() if task_session_id is not None else None
        self.task_free_context_locators: dict[str, str] = {}
        self.host_mcp = McpUnixClient(prefetch_socket) if prefetch_socket is not None else None
        self.submitter_mcp = (
            McpUnixClient(submitter_socket) if submitter_socket is not None else None
        )
        self.target_counter = (
            TargetTokenizerCounter(tokenizer_json) if tokenizer_json is not None else None
        )
        digest_input = {
            "integration": "milai-openworker-mcp-v1",
            "profile": "reader-lite",
            "model_id": capability.model_id,
            "representation": "grouped-compact/v3",
        }
        integration_digest = hashlib.sha256(_canonical(digest_input)).hexdigest()
        self.task_memory = (
            build_task_memory_controller(
                self.host_mcp,
                compiler_digest=integration_digest,
                router_digest=integration_digest,
                policy_digest=integration_digest,
            )
            if self.host_mcp is not None
            else None
        )
        self.startup_task_policy = (
            _load_startup_task_policy(broker_policy, task_fixture)
            if broker_policy is not None and task_fixture is not None
            else None
        )
        self.task_policy = AgentRecallPolicy(
            scope=(
                self.startup_task_policy.scope
                if self.startup_task_policy is not None
                else {"host_policy": "reader-lite"}
            ),
            authority=(
                self.startup_task_policy.required_authority
                if self.startup_task_policy is not None
                else "INFORMATIONAL"
            ),
            consistency_floor=(
                self.startup_task_policy.consistency_floor
                if self.startup_task_policy is not None
                else "CANONICAL_REQUIRED"
            ),
            max_limit=(
                self.startup_task_policy.max_limit if self.startup_task_policy is not None else 3
            ),
        )
        permission_snapshot = dict(self.task_policy.scope)
        permission_snapshot["readable"] = True
        self.memory_facade = (
            OpenWorkerMemoryFacade(
                self.host_mcp,
                submitter=self.submitter_mcp,
                subject_id=memory_subject_id,
                permission_snapshot=permission_snapshot,
                data_classification=cast(
                    MemoryDataClassification,
                    memory_data_classification,
                ),
            )
            if self.memory_mode == "query-first" and self.host_mcp is not None
            else None
        )
        self.settlement_enabled = self.submitter_mcp is not None
        self.need_resolver = DeterministicMemoryNeedResolver()
        self.task_budget = TaskMemoryBudget(
            max_prepare_context_calls=64,
            max_full_recall_calls=20,
            max_delta_refreshes=8,
            max_memory_tokens_injected=10_240,
            max_validation_calls=63,
            memory_deadline_ms=5_000,
        )
        self.token_budget = (
            TokenBudget.for_class("STANDARD", counter=self.target_counter)
            if self.target_counter is not None
            else None
        )
        self._task_contexts: dict[str, PrefetchContext] = {}
        self._task_lock = threading.Lock()
        self._native_bind_lock = threading.Lock()
        self._task_sequence = 0
        self.task_registry = HostTaskRegistry()
        self.native_task_registry = SameProcessTaskRegistry()
        self.task_relation_resolver = DeterministicTaskRelationResolver()
        self.task_transition_validator = DeterministicTaskTransitionValidator()
        self._active_task_key_by_task: dict[str, str] = {}
        self._last_need_by_task_key: dict[str, MemoryNeedResolution] = {}
        self._lock = threading.Lock()
        self._sequence = next_logical_request_sequence - 1
        self._pending_recall: defaultdict[str, deque[float]] = defaultdict(deque)
        self._pending_lock = threading.Lock()

    def close(self) -> None:
        if self.host_mcp is not None:
            self.host_mcp.close()
        if self.submitter_mcp is not None:
            self.submitter_mcp.close()

    def _record(self, event: Mapping[str, Any]) -> None:
        self.trace.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.trace.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(event), ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _record_ingress_terminal(self, http_status: int, exc: Exception) -> None:
        if isinstance(
            exc,
            (OpenWorkerAdapterError, ProviderCallError, BudgetError, CapabilityError),
        ):
            reason_code = str(exc)
        elif isinstance(exc, json.JSONDecodeError):
            reason_code = "JSON_DECODE_ERROR"
        else:
            reason_code = "VALUE_ERROR"
        self._record(
            {
                "event": "HOST_INGRESS_TERMINAL",
                "exception_type": type(exc).__name__,
                "http_status": http_status,
                "reason_code": reason_code,
            }
        )

    def _record_stream_terminal(self, exc: Exception) -> None:
        reason_code = (
            str(exc)
            if isinstance(exc, (ProviderCallError, BudgetError))
            else "STREAM_CONNECTION_CLOSED"
        )
        self._record(
            {
                "event": "HOST_STREAM_TERMINAL",
                "exception_type": type(exc).__name__,
                "http_status": 200,
                "reason_code": reason_code,
                "response_headers_committed": True,
                "status": "FAILED",
            }
        )

    def _logical_request_id(self) -> str:
        with self._lock:
            self._sequence += 1
            return f"{self.run_id}-ow-{self._sequence:02d}"

    def _settle_answer(
        self,
        *,
        metadata: NativeTaskMetadata,
        bound: _BoundTaskState,
        messages: Sequence[Mapping[str, Any]],
        assistant_content: str,
        context_sha256: str,
        support_aliases: Sequence[str],
        recall: OpenWorkerMemoryRecall,
    ) -> None:
        if not self.settlement_enabled:
            return
        if (
            self.memory_facade is None
            or metadata.assistant_message is None
            or metadata.user_observed_at is None
            or metadata.assistant_observed_at is None
        ):
            raise ProviderCallError("HOST_SETTLEMENT_IDENTITY_ABSENT")
        user_content = _last_user_content(messages)
        round_ordinal = sum(message.get("role") == "user" for message in messages) - 1
        try:
            receipt = self.memory_facade.settle_exchange(
                task_epoch=bound.identity.task_epoch,
                session_id=metadata.task_session,
                user_message_id=metadata.task_operation,
                assistant_message_id=metadata.assistant_message,
                user_content=user_content,
                assistant_content=assistant_content,
                user_observed_at=metadata.user_observed_at,
                assistant_observed_at=metadata.assistant_observed_at,
                round_ordinal=round_ordinal,
                context_sha256=context_sha256,
                support_aliases=support_aliases,
                recall=recall,
            )
        except (McpUnixClientError, RuntimeError, ValueError) as exc:
            reason_code = exc.code if isinstance(exc, McpUnixClientError) else type(exc).__name__
            self._record(
                {
                    "event": "HOST_MEMORY_SETTLEMENT_FAILED",
                    "provider_call": False,
                    "reason_code": reason_code,
                    "task_session_sha256": hashlib.sha256(
                        metadata.task_session.encode()
                    ).hexdigest(),
                    "task_operation_sha256": hashlib.sha256(
                        metadata.task_operation.encode()
                    ).hexdigest(),
                }
            )
            raise ProviderCallError("HOST_SETTLEMENT_FAILED") from exc
        lineage = receipt.memory_support
        self._record(
            {
                "event": "HOST_MEMORY_SETTLED",
                "provider_call": False,
                "task_session_sha256": hashlib.sha256(
                    metadata.task_session.encode()
                ).hexdigest(),
                "user_message_sha256": hashlib.sha256(
                    metadata.task_operation.encode()
                ).hexdigest(),
                "assistant_message_sha256": hashlib.sha256(
                    metadata.assistant_message.encode()
                ).hexdigest(),
                "user_content_sha256": hashlib.sha256(user_content.encode()).hexdigest(),
                "assistant_content_sha256": hashlib.sha256(
                    assistant_content.encode()
                ).hexdigest(),
                "round_ordinal": round_ordinal,
                "evidence_ids": [receipt.user.evidence_id, receipt.assistant.evidence_id],
                "outbox_ids": list(receipt.outbox_ids),
                "deduplicated": [
                    receipt.user.deduplicated,
                    receipt.assistant.deduplicated,
                ],
                "memory_support_refs": (
                    list(lineage.evidence_ids) if lineage is not None else []
                ),
                "memory_support_aliases": (
                    list(lineage.evidence_aliases) if lineage is not None else []
                ),
                "canonical_changed": False,
            }
        )

    def complete(
        self,
        incoming: OpenAIChatRequest,
        metadata: NativeTaskMetadata,
        *,
        request_parse_ms: float | None = None,
    ) -> tuple[dict[str, Any] | StreamingCompletion, str]:
        adapter_started = time.perf_counter()
        payload_input = incoming.payload
        messages = list(incoming.messages)
        incoming.provider_payload(None)  # validates direct memory-tool selection pre-MCP
        recall_name = _tool_name(payload_input.get("tools"))
        recall = (
            None
            if self.memory_mode in _HOST_PREFETCH_MODES
            else _recall_from_messages(messages)
        )
        question = _question(messages)
        question_sha256 = hashlib.sha256(question.encode()).hexdigest()
        query_intent = DeterministicQueryOnlyIntentShadow().interpret(
            question,
            invocation_mode="PREFETCH_AUTO",
        )
        has_tool_result = any(message.get("role") == "tool" for message in messages)
        self._record(_native_request_observation(incoming, metadata))
        memory_control_ms: float | None = None
        memory_source = "NO_MEMORY"
        mcp_calls = 0
        context: PrefetchContext | None = None
        prepared: TaskPreparedContext | None = None
        memory_recall: OpenWorkerMemoryRecall | None = None
        bound = (
            self._bind_native_task_state(
                metadata,
                allow_operation_continuation=has_tool_result,
            )
            if self.memory_mode in _HOST_PREFETCH_MODES and recall is None
            else None
        )
        turn_authority = self.task_policy.authority
        turn_policy = (
            AgentRecallPolicy(
                scope=bound.state.project_scope,
                authority=turn_authority,
                consistency_floor=self.task_policy.consistency_floor,
                max_limit=self.task_policy.max_limit,
            )
            if bound is not None
            else self.task_policy
        )
        previous_need_resolution = (
            self._last_need_by_task_key.get(bound.task_key) if bound is not None else None
        )
        need_resolution = (
            self.need_resolver.resolve(
                question,
                scope=bound.state.project_scope,
                required_authority=turn_policy.authority,
                consistency_floor=turn_policy.consistency_floor,
                known_state_keys=bound.state.known_state_keys,
                known_claim_ids=bound.state.known_claim_ids,
                open_issue_ids=bound.state.relevant_open_issue_ids,
                canonical_position_seen=bound.state.canonical_position_seen,
                previous=previous_need_resolution,
            )
            if self.memory_mode == "prefetch" and recall is None and bound is not None
            else None
        )
        requested_memory_route = _requested_memory_route(
            bound,
            need_resolution,
            previous_need_resolution,
        )
        if self.memory_mode in _HOST_PREFETCH_MODES and recall is None:
            current_effective_route = (
                "NONE"
                if bound is None or bound.binding_context.tentative
                else requested_memory_route
            )
            self._record(
                {
                    "event": "HOST_QUERY_ONLY_INTENT_SHADOW",
                    "provider_call": False,
                    "question_sha256": question_sha256,
                    **_query_only_intent_shadow_trace(
                        question,
                        current_resolution=need_resolution,
                        current_effective_route=current_effective_route,
                    ),
                }
            )
        if need_resolution is not None:
            if bound is None:  # resolution is produced only for a bound prefetch task
                raise OpenWorkerAdapterError("Host task-memory state is absent")
            if need_resolution.signature.intent_class != "NONE":
                self._last_need_by_task_key[bound.task_key] = need_resolution
            self._record(
                {
                    "event": "HOST_MEMORY_NEED_RESOLVED",
                    "provider_call": False,
                    "question_sha256": question_sha256,
                    "need_signature_id": need_resolution.signature.need_signature_id,
                    "intent_class": need_resolution.signature.intent_class,
                    "temporal_need": need_resolution.signature.temporal_need,
                    "evidence_need": need_resolution.signature.evidence_need,
                    "resolver_route": need_resolution.requested_route,
                    "requested_route": requested_memory_route,
                    "state_key_ref_present": need_resolution.state_key_ref is not None,
                    "state_key_ref_sha256": (
                        hashlib.sha256(
                            _canonical(need_resolution.state_key_ref.to_api())
                        ).hexdigest()
                        if need_resolution.state_key_ref is not None
                        else None
                    ),
                    "state_key_subject_sha256": (
                        hashlib.sha256(need_resolution.state_key_ref.subject.encode()).hexdigest()
                        if need_resolution.state_key_ref is not None
                        else None
                    ),
                    "state_key_predicate_sha256": (
                        hashlib.sha256(need_resolution.state_key_ref.predicate.encode()).hexdigest()
                        if need_resolution.state_key_ref is not None
                        else None
                    ),
                    "state_key_claim_type_sha256": (
                        hashlib.sha256(
                            need_resolution.state_key_ref.claim_type.encode()
                        ).hexdigest()
                        if need_resolution.state_key_ref is not None
                        else None
                    ),
                    "resolver_model_calls": need_resolution.resolver_model_calls,
                    "resolver_embedding_calls": need_resolution.resolver_embedding_calls,
                    "resolver_retrieval_calls": need_resolution.resolver_retrieval_calls,
                }
            )
        if bound is not None:
            self._record(
                {
                    "event": "HOST_TASK_STATE_SHADOW",
                    "provider_call": False,
                    "question_sha256": question_sha256,
                    "task_id_sha256": hashlib.sha256(bound.state.task_id.encode()).hexdigest(),
                    "task_epoch": bound.identity.task_epoch,
                    "active_goal_id_sha256": hashlib.sha256(
                        bound.state.active_goal_id.encode()
                    ).hexdigest(),
                    "active_goal_version": bound.state.active_goal_version,
                    "active_goal_sha256": hashlib.sha256(bound.active_goal.encode()).hexdigest(),
                    "active_goal_equals_current_question": bound.active_goal == question,
                    "project_scope_sha256": hashlib.sha256(
                        _canonical(bound.state.project_scope)
                    ).hexdigest(),
                    "profile_id": bound.state.profile_id,
                    "task_key": bound.task_key,
                    "declared_host_event": bound.declared_event,
                    "host_event": bound.event,
                    "event_adjustment": bound.event_adjustment,
                    "binding_transition": bound.transition,
                    "task_relation": bound.binding_context.relation_decision.relation,
                    "confidence_tier": (bound.binding_context.relation_decision.confidence_tier),
                    "reason_codes": list(bound.binding_context.relation_decision.reason_codes),
                    "transition_operation": bound.binding_context.transition.operation,
                    "source_task_id_sha256": (
                        hashlib.sha256(
                            bound.binding_context.transition.source_task_id.encode()
                        ).hexdigest()
                        if bound.binding_context.transition.source_task_id is not None
                        else None
                    ),
                    "target_task_id_sha256": (
                        hashlib.sha256(
                            bound.binding_context.transition.target_task_id.encode()
                        ).hexdigest()
                        if bound.binding_context.transition.target_task_id is not None
                        else None
                    ),
                    "registry_revision_before": (bound.binding_context.registry_revision_before),
                    "registry_revision_after": bound.binding_context.registry_revision_after,
                    "expected_registry_revision": (
                        bound.binding_context.transition.expected_registry_revision
                    ),
                    "task_generation": bound.state.identity.task_generation,
                    "binding_generation": bound.state.identity.binding_generation,
                    "expected_task_generation": (
                        bound.binding_context.transition.expected_task_generation
                    ),
                    "execution_lane_id_sha256": hashlib.sha256(
                        bound.state.identity.execution_lane_id.encode()
                    ).hexdigest(),
                    "cache_reuse_constraint": (bound.binding_context.cache_reuse_constraint),
                    "tentative_binding": bound.binding_context.tentative,
                    "scope_compatible": (bound.binding_context.relation_decision.scope_compatible),
                    "profile_compatible": (
                        bound.binding_context.relation_decision.profile_compatible
                    ),
                    "resolver_ms": bound.resolution.resolver_ms,
                    "task_relation_ms": bound.resolution.resolver_ms,
                    "task_transition_ms": bound.resolution.task_transition_ms,
                    "task_state_rebind_ms": bound.resolution.task_state_rebind_ms,
                    "task_resolver_llm_calls": bound.resolution.llm_calls,
                    "task_resolver_embedding_calls": bound.resolution.embedding_calls,
                    "task_resolver_retrieval_calls": bound.resolution.retrieval_calls,
                    "task_resolver_training_calls": bound.resolution.training_calls,
                    "task_resolver_hidden_provider_calls": (bound.resolution.hidden_provider_calls),
                    "relation_transition_trace_complete": True,
                    "retained_slot_present": bound.retained is not None,
                }
            )
        if self.memory_mode == "query-first" and recall is None:
            if self.host_mcp is None or self.target_counter is None:
                raise OpenWorkerAdapterError("query-first MCP client is absent")
            recalled_at = time.perf_counter()
            attempt_trace_id = (
                "host-mcp-attempt:" + hashlib.sha256(_canonical(payload_input)).hexdigest()
            )
            native_trace_identity = {
                "task_session_sha256": hashlib.sha256(
                    metadata.task_session.encode()
                ).hexdigest(),
                "task_operation_sha256": hashlib.sha256(
                    metadata.task_operation.encode()
                ).hexdigest(),
            }
            previous_context_id = self.task_free_context_locators.get(
                metadata.task_session
            )
            self._record(
                {
                    "event": "HOST_MCP_PREPARE_ATTEMPT",
                    "provider_call": False,
                    "question_sha256": question_sha256,
                    **native_trace_identity,
                    "memory_mode": self.memory_mode,
                    "mcp_tool": "milai_memory_resolve",
                    "requested_route": "L1",
                    "fresh_resolve": previous_context_id is None,
                    "receipt_locator_present": previous_context_id is not None,
                    "logical_mcp_calls": 1,
                    "attempt_trace_id": attempt_trace_id,
                }
            )
            try:
                query = _recall_query(question)
                memory_recall = OpenWorkerMemoryFacade(
                    self.host_mcp
                ).recall_for_operation(
                    query,
                    previous_context_id=previous_context_id,
                )
                resolved = memory_recall.payload
            except McpUnixClientError as exc:
                memory_control_ms = (time.perf_counter() - recalled_at) * 1_000
                outcome = _transport_unavailable_outcome(payload_input, exc.code)
                completion = _memory_terminal_completion(payload_input, outcome)
                self._record(
                    {
                        "event": "HOST_MCP_PREFETCH_FAILED",
                        "provider_call": False,
                        "request_id": completion["id"],
                        "question_sha256": question_sha256,
                        **native_trace_identity,
                        "memory_mode": self.memory_mode,
                        "mcp_tool": "milai_memory_resolve",
                        "memory_control_ms": round(memory_control_ms, 3),
                        "failure_code": exc.code,
                        "attempt_trace_id": attempt_trace_id,
                        "access_outcome": outcome.to_api(),
                    }
                )
                return completion, "HOST_" + outcome.status

            compile_started = time.perf_counter()
            # Runtime-owned MemoryContext is already governed and token
            # budgeted.  WIDE OpenWorker reads may legitimately exceed the
            # legacy 4 KiB item-reconstruction ceiling.
            context = prepare_prefetch(
                resolved,
                max_context_chars=_QUERY_FIRST_MAX_CONTEXT_CHARS,
            )
            next_context_id = memory_recall.context_id
            if isinstance(next_context_id, str) and next_context_id:
                self.task_free_context_locators[metadata.task_session] = next_context_id
                if len(self.task_free_context_locators) > 256:
                    oldest = next(iter(self.task_free_context_locators))
                    if oldest != metadata.task_session:
                        self.task_free_context_locators.pop(oldest, None)
            context_compile_ms = (time.perf_counter() - compile_started) * 1_000
            memory_control_ms = (time.perf_counter() - recalled_at) * 1_000
            memory_source = "HOST_MCP_QUERY_FIRST"
            mcp_calls = 1
            raw_trace = resolved.get("access_trace")
            access_trace = dict(raw_trace) if isinstance(raw_trace, Mapping) else {}
            raw_spans = access_trace.get("spans")
            spans = dict(raw_spans) if isinstance(raw_spans, Mapping) else {}
            raw_transport = resolved.get("host_transport")
            host_transport = (
                dict(raw_transport) if isinstance(raw_transport, Mapping) else {}
            )

            def measured(value: object) -> float | None:
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return float(value)
                return None

            query_timing = {
                "uds_roundtrip_ms": measured(host_transport.get("uds_roundtrip_ms")),
                "mcp_handler_ms": measured(spans.get("mcp_handler_ms")),
                "runtime_total_ms": measured(spans.get("runtime_client_ms")),
                "context_compile_ms": round(context_compile_ms, 3),
            }
            items = resolved.get("items")
            issue_ids = resolved.get("open_issue_ids")
            target_status = str(resolved.get("status"))
            terminal_stage = access_trace.get("terminal_stage")
            trace_id = resolved.get("trace_id")
            compiled = context.status in {"AVAILABLE", "UNCERTAIN"}
            prepare_status = (
                "READY"
                if compiled
                else "ABSTAIN"
                if context.status == "NO_MEMORY"
                else "DEGRADED"
            )
            self._record(
                {
                    "event": "HOST_MCP_PREPARE_CONTEXT",
                    "provider_call": False,
                    "question_sha256": question_sha256,
                    **native_trace_identity,
                    "attempt_trace_id": attempt_trace_id,
                    "memory_mode": self.memory_mode,
                    "mcp_tool": "milai_memory_resolve",
                    "fresh_resolve": previous_context_id is None,
                    "memory_control_ms": round(memory_control_ms, 3),
                    "memory_status": context.status,
                    "route": access_trace.get("planned_stage") or "SEARCH",
                    "prepare_status": prepare_status,
                    "prepare_reason": context.abstention_reason,
                    "access_outcome": {
                        "schema_version": resolved.get("schema_version"),
                        "status": target_status,
                        "availability": resolved.get("availability"),
                        "terminal_stage": terminal_stage,
                        "trace_id": trace_id,
                    },
                    "trace_id": trace_id,
                    "current_state_status": target_status,
                    "current_state_claim_count": (
                        len(items) if isinstance(items, list) else 0
                    ),
                    "current_state_open_issue_count": (
                        len(issue_ids) if isinstance(issue_ids, list) else 0
                    ),
                    "cache_validation_outcome": (
                        "REUSED"
                        if resolved.get("receipt_reused") is True
                        else resolved.get("receipt_fallback_reason")
                    ),
                    "timing": query_timing,
                    "access_trace_link": _host_access_trace_link(
                        attempt_trace_id=attempt_trace_id,
                        retrieval_trace_id=(trace_id if isinstance(trace_id, str) else None),
                        timing={
                            key: value
                            for key, value in query_timing.items()
                            if isinstance(value, float)
                        },
                        host_total_ms=memory_control_ms,
                    ),
                    "compiled_memory_tokens": (
                        self.target_counter.count_text(context.rendered) if compiled else None
                    ),
                    "compiled_memory_bytes": (
                        len(context.rendered.encode("utf-8")) if compiled else None
                    ),
                    "recall_execution_trace": access_trace,
                }
            )
            if context.status == "UNAVAILABLE":
                outcome = _transport_unavailable_outcome(
                    payload_input,
                    context.abstention_reason or target_status,
                )
                return _memory_terminal_completion(payload_input, outcome), "HOST_" + outcome.status
            if context.status == "UNCERTAIN" or (
                context.status == "NO_MEMORY" and query_intent.intent == "REQUIRED"
            ):
                outcome = _memory_insufficient_outcome(payload_input, resolved, context)
                completion = _memory_terminal_completion(payload_input, outcome)
                self._record(
                    {
                        "event": "HOST_MCP_MEMORY_INSUFFICIENT",
                        "provider_call": False,
                        "question_sha256": question_sha256,
                        **native_trace_identity,
                        "memory_mode": self.memory_mode,
                        "mcp_tool": "milai_memory_resolve",
                        "memory_status": context.status,
                        "attempt_trace_id": attempt_trace_id,
                        "access_outcome": outcome.to_api(),
                    }
                )
                if self.settlement_enabled:
                    if bound is None or memory_recall is None:
                        raise ProviderCallError("HOST_SETTLEMENT_CONTEXT_ABSENT")
                    assistant_content, _ = final_assistant_content(completion)
                    self._settle_answer(
                        metadata=metadata,
                        bound=bound,
                        messages=messages,
                        assistant_content=assistant_content,
                        context_sha256=context.context_sha256,
                        support_aliases=(),
                        recall=memory_recall,
                    )
                return completion, "HOST_" + outcome.status
        elif bound is not None and bound.binding_context.tentative:
            context = PrefetchContext.no_memory()
            memory_source = "HOST_TASK_BINDING_AMBIGUOUS"
            self._record(
                {
                    "event": "HOST_MEMORY_ROUTE_NONE",
                    "provider_call": False,
                    "question_sha256": question_sha256,
                    "memory_mode": self.memory_mode,
                    "route": "NONE",
                    "reason": "TASK_BINDING_AMBIGUOUS",
                    "mcp_calls": 0,
                    "compiled_memory_tokens": 0,
                    "recall_execution_trace": _shadow_route_trace(
                        requested_route="NONE",
                        actual_route="NONE",
                        host_terminal=True,
                    ),
                }
            )
        elif need_resolution is not None and need_resolution.requested_route == "NONE":
            context = PrefetchContext.no_memory()
            memory_source = "HOST_ROUTER_NONE"
            self._record(
                {
                    "event": "HOST_MEMORY_ROUTE_NONE",
                    "provider_call": False,
                    "question_sha256": question_sha256,
                    "memory_mode": self.memory_mode,
                    "route": "NONE",
                    "reason": need_resolution.reason_code,
                    "mcp_calls": 0,
                    "compiled_memory_tokens": 0,
                    "recall_execution_trace": _shadow_route_trace(
                        requested_route="NONE",
                        actual_route="NONE",
                        host_terminal=True,
                    ),
                }
            )
        elif self.memory_mode == "prefetch" and recall is None:
            if (
                self.task_memory is None or self.target_counter is None or self.token_budget is None
            ):  # pragma: no cover - constructor invariant
                raise OpenWorkerAdapterError("host task-memory controller is absent")
            if bound is None:  # pragma: no cover - constructor and branch invariant
                raise OpenWorkerAdapterError("Host task-memory state is absent")
            identity = bound.identity
            active_goal = bound.active_goal
            task_key = bound.task_key
            event = bound.event
            retained = bound.retained
            recalled_at = time.perf_counter()
            attempt_trace_id = (
                "host-mcp-attempt:" + hashlib.sha256(_canonical(payload_input)).hexdigest()
            )
            self._record(
                {
                    "event": "HOST_MCP_PREPARE_ATTEMPT",
                    "provider_call": False,
                    "question_sha256": question_sha256,
                    "task_session_sha256": hashlib.sha256(
                        metadata.task_session.encode()
                    ).hexdigest(),
                    "task_operation_sha256": hashlib.sha256(
                        metadata.task_operation.encode()
                    ).hexdigest(),
                    "memory_mode": self.memory_mode,
                    "requested_route": requested_memory_route,
                    "logical_mcp_calls": 1,
                    "attempt_trace_id": attempt_trace_id,
                }
            )
            try:
                prepared = self.task_memory.prepare_context(
                    _recall_query(question),
                    identity=identity,
                    event=event,
                    active_goal=active_goal,
                    recall_policy=turn_policy,
                    token_counter=self.target_counter,
                    token_budget=self.token_budget,
                    task_budget=self.task_budget,
                    requested_route=(requested_memory_route),
                    need_signature_id=(
                        need_resolution.signature.need_signature_id
                        if need_resolution is not None
                        else None
                    ),
                    memory_need_signature=(
                        need_resolution.signature if need_resolution is not None else None
                    ),
                    state_key_ref=(
                        need_resolution.state_key_ref if need_resolution is not None else None
                    ),
                    known_claim_id=(
                        bound.state.known_claim_ids[0]
                        if event == "KNOWN_OBJECT" and bound.state.known_claim_ids
                        else None
                    ),
                )
            except McpUnixClientError as exc:
                memory_control_ms = (time.perf_counter() - recalled_at) * 1000
                outcome = _transport_unavailable_outcome(payload_input, exc.code)
                completion = _memory_terminal_completion(payload_input, outcome)
                self._record(
                    {
                        "event": "HOST_MCP_PREFETCH_FAILED",
                        "provider_call": False,
                        "request_id": completion["id"],
                        "question_sha256": question_sha256,
                        "memory_mode": self.memory_mode,
                        "memory_control_ms": round(memory_control_ms, 3),
                        "failure_code": exc.code,
                        "attempt_trace_id": attempt_trace_id,
                        "access_outcome": outcome.to_api(),
                    }
                )
                return (
                    completion,
                    "HOST_" + outcome.status,
                )
            except (ContextBudgetInfeasibleError, ContextIntegrityError, RuntimeError) as exc:
                memory_control_ms = (time.perf_counter() - recalled_at) * 1000
                self._record(
                    {
                        "event": "HOST_TASK_CONTEXT_REJECTED",
                        "provider_call": False,
                        "question_sha256": question_sha256,
                        "memory_control_ms": round(memory_control_ms, 3),
                        "failure_type": type(exc).__name__,
                        "failure_code": str(exc),
                    }
                )
                raise OpenWorkerAdapterError("host task context was rejected") from exc
            context = _resolve_prepared_context(prepared, retained)
            if prepared.status != "UNCHANGED":
                with self._task_lock:
                    if prepared.status == "READY":
                        self._task_contexts[task_key] = context
                    else:
                        self._task_contexts.pop(task_key, None)
            memory_control_ms = (time.perf_counter() - recalled_at) * 1000
            memory_source = "HOST_MCP_COMPOSITE"
            mcp_calls = 1
            prepare_timing = prepared.timing or {}
            uds_roundtrip_ms = prepare_timing.get("uds_roundtrip_ms")
            mcp_handler_ms = prepare_timing.get("mcp_handler_ms")
            runtime_total_ms = prepare_timing.get("runtime_total_ms")
            self._record(
                {
                    "event": "HOST_MCP_PREPARE_CONTEXT",
                    "provider_call": False,
                    "question_sha256": question_sha256,
                    "task_session_sha256": hashlib.sha256(
                        metadata.task_session.encode()
                    ).hexdigest(),
                    "task_operation_sha256": hashlib.sha256(
                        metadata.task_operation.encode()
                    ).hexdigest(),
                    "attempt_trace_id": attempt_trace_id,
                    "memory_mode": self.memory_mode,
                    "memory_control_ms": round(memory_control_ms, 3),
                    "memory_status": context.status,
                    "route": prepared.route,
                    "prepare_status": prepared.status,
                    "prepare_reason": prepared.reason,
                    "access_outcome": prepared.outcome.to_api(),
                    "usage": prepared.usage,
                    "trace_id": prepared.trace_pointer,
                    "current_state_status": (
                        prepared.current_state_envelope.status
                        if prepared.current_state_envelope is not None
                        else None
                    ),
                    "current_state_claim_count": (
                        len(prepared.current_state_envelope.claims)
                        if prepared.current_state_envelope is not None
                        else 0
                    ),
                    "current_state_open_issue_count": (
                        len(prepared.current_state_envelope.open_issues)
                        if prepared.current_state_envelope is not None
                        else 0
                    ),
                    "current_state_validation_handle_present": (
                        prepared.current_state_envelope.slot_validation_handle is not None
                        if prepared.current_state_envelope is not None
                        else False
                    ),
                    "memory_slot_coverage_present": (prepared.memory_slot_coverage is not None),
                    "memory_slot_coverage_counts": (
                        {
                            "claims": len(
                                prepared.memory_slot_coverage.claim_ids_and_head_versions
                            ),
                            "state_keys": len(
                                prepared.memory_slot_coverage.state_keys_and_head_versions
                            ),
                            "open_issues": len(
                                prepared.memory_slot_coverage.open_issue_ids_and_revisions
                            ),
                        }
                        if prepared.memory_slot_coverage is not None
                        else None
                    ),
                    "memory_slot_policy_identity": (
                        prepared.memory_slot_coverage.policy_identity
                        if prepared.memory_slot_coverage is not None
                        else None
                    ),
                    "memory_slot_evidence_depth": (
                        prepared.memory_slot_coverage.evidence_depth
                        if prepared.memory_slot_coverage is not None
                        else None
                    ),
                    "dependency_frontier_position": (
                        prepared.memory_slot_coverage.dependency_frontier.get("canonical_position")
                        if prepared.memory_slot_coverage is not None
                        else None
                    ),
                    "cache_validation_outcome": (
                        (
                            "HIT"
                            if prepared.status == "UNCHANGED"
                            and prepared.validation_token is not None
                            else (prepared.reason or "MISS")
                        )
                        if requested_memory_route == "CACHE"
                        else None
                    ),
                    "timing": {
                        **prepare_timing,
                        "broker_transport_ms": _nonnegative_difference(
                            uds_roundtrip_ms, mcp_handler_ms
                        ),
                        "mcp_overhead_ms": _nonnegative_difference(
                            mcp_handler_ms, runtime_total_ms
                        ),
                        "context_compile_ms": prepare_timing.get("context_compile_ms", 0.0),
                    },
                    "access_trace_link": _host_access_trace_link(
                        attempt_trace_id=attempt_trace_id,
                        retrieval_trace_id=prepared.trace_pointer,
                        timing=prepare_timing,
                        host_total_ms=memory_control_ms,
                    ),
                    "compiled_memory_tokens": (
                        prepared.delta.metrics.actual_tokens if prepared.delta is not None else None
                    ),
                    "compiled_memory_bytes": (
                        len(prepared.delta.delta.rendered_context.encode("utf-8"))
                        if prepared.delta is not None
                        and prepared.delta.delta.rendered_context is not None
                        else None
                    ),
                    "representation_tiers": (
                        [list(value) for value in prepared.delta.metrics.representation_tiers]
                        if prepared.delta is not None
                        else []
                    ),
                    "recall_execution_trace": _shadow_route_trace(
                        requested_route=(requested_memory_route),
                        actual_route=prepared.route,
                        host_terminal=False,
                        runtime_trace=prepared.recall_execution_trace,
                    ),
                }
            )
            if context.status == "UNAVAILABLE":
                return (
                    _memory_terminal_completion(payload_input, prepared.outcome),
                    "HOST_" + prepared.outcome.status,
                )
        if (
            recall_name is not None
            and recall is None
            and context is None
            and not has_tool_result
            and _should_recall(self.memory_mode)
        ):
            request_id = (
                "chatcmpl-route-" + hashlib.sha256(_canonical(payload_input)).hexdigest()[:24]
            )
            with self._pending_lock:
                self._pending_recall[question_sha256].append(time.perf_counter())
            self._record(
                {
                    "event": "MCP_ROUTE",
                    "provider_call": False,
                    "request_id": request_id,
                    "question_sha256": question_sha256,
                    "memory_mode": self.memory_mode,
                    "adapter_route_ms": round((time.perf_counter() - adapter_started) * 1000, 3),
                }
            )
            return (
                _completion(
                    request_id=request_id,
                    content=None,
                    finish_reason="tool_calls",
                    usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    tool_name=recall_name,
                    query=_recall_query(question),
                ),
                "MCP_ROUTE",
            )

        ordinary_tool_continuation = (
            self.single_ordinary_tool_required_once is not None and has_tool_result
        )
        if (
            context is None
            and recall is None
            and (recall_name is None or has_tool_result)
            and not ordinary_tool_continuation
        ):
            answer = {"answer": "UNKNOWN", "status": "UNKNOWN", "memory_used": False}
            request_id = (
                "chatcmpl-unavailable-" + hashlib.sha256(_canonical(payload_input)).hexdigest()[:18]
            )
            self._record(
                {
                    "event": "MCP_UNAVAILABLE_NO_PROVIDER",
                    "provider_call": False,
                    "request_id": request_id,
                    "answer": answer,
                }
            )
            return (
                _completion(
                    request_id=request_id,
                    content=_canonical(answer).decode(),
                    finish_reason="stop",
                    usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                ),
                "MCP_UNAVAILABLE_NO_PROVIDER",
            )

        if context is None:
            context = (
                prepare_prefetch(recall) if recall is not None else PrefetchContext.no_memory()
            )
        if recall is not None and memory_source == "NO_MEMORY":
            memory_source = "OPENWORKER_MCP_TOOL"
            mcp_calls = 1
            with self._pending_lock:
                pending = self._pending_recall.get(question_sha256)
                tool_recalled_at = pending.popleft() if pending else None
                if pending is not None and not pending:
                    self._pending_recall.pop(question_sha256, None)
            if tool_recalled_at is not None:
                memory_control_ms = (time.perf_counter() - tool_recalled_at) * 1000
        rendered_context = context.rendered if context.status != "NO_MEMORY" else None
        payload, excluded_memory_tools = incoming.provider_payload(rendered_context)
        ordinary_tool_policy = (
            _apply_single_ordinary_tool_required_once(
                payload, self.single_ordinary_tool_required_once
            )
            if self.single_ordinary_tool_required_once is not None
            else None
        )
        memory_answer = _memory_answer_eligible(
            memory_mode=self.memory_mode,
            rendered_context=rendered_context,
            payload=payload,
            ordinary_tool_policy=ordinary_tool_policy,
        )
        visible_aliases = (
            memory_recall.visible_aliases if memory_recall is not None else ()
        )
        if memory_answer and (
            self.evidence_use_mode != "direct" or self.settlement_enabled
        ) and not visible_aliases:
            raise OpenWorkerAdapterError("EVIDENCE_USE_ALIAS_INVENTORY_EMPTY")
        evidence_use_applied = memory_answer and self.evidence_use_mode != "direct"
        evidence_use_base_payload = dict(payload)
        if evidence_use_applied and self.evidence_use_mode != "model-native":
            payload = apply_evidence_use_protocol(
                payload,
                mode=self.evidence_use_mode,
                visible_aliases=visible_aliases,
            )
        settlement_required = (
            self.settlement_enabled
            and self.memory_mode == "query-first"
            and ordinary_tool_policy is None
            and not payload.get("tools")
        )
        ordinary_tool_compatibility_applied = False
        ordinary_tool_delivery = "NATIVE"
        ordinary_tool_delivery_evidence: dict[str, Any] | None = None
        if self.ordinary_tool_provider_compatibility is not None:
            if not incoming.stream:
                raise OpenWorkerAdapterError(
                    "PROVIDER_SINGLE_ORDINARY_COMPATIBILITY_REQUIRES_STREAM"
                )
            assert ordinary_tool_policy is not None
            ordinary_tool_compatibility_applied = _apply_vllm_json_schema_named_tool_compatibility(
                payload, ordinary_tool_policy
            )
            ordinary_tool_delivery = (
                self.ordinary_tool_provider_compatibility
                if ordinary_tool_compatibility_applied
                else "NATIVE_NONE"
            )
            if ordinary_tool_compatibility_applied:
                ordinary_tool_delivery_evidence = {
                    "incoming_tool_choice": ordinary_tool_policy.get("requested_tool_choice"),
                    "provider_tool_choice": (
                        "ABSENT" if "tool_choice" not in payload else "PRESENT"
                    ),
                    "provider_tool_count": len(payload.get("tools", [])),
                    "native_tool_call_count": 0,
                    "delivery_owner": "HOST_ADAPTER",
                    "client_finish_reason": "tool_calls",
                    "delivered_read_count": 1,
                }
        logical_request_id = self._logical_request_id()
        prompt_budget = _per_request_token_budget(
            self.provider_capability.max_prompt_tokens,
            self.provider_capability.max_native_requests,
        )
        per_request_completion_budget = _per_request_token_budget(
            self.provider_capability.max_completion_tokens,
            self.provider_capability.max_native_requests,
        )
        completion_budget = min(
            incoming.max_tokens or per_request_completion_budget,
            per_request_completion_budget,
        )
        transport_name = "stream" if incoming.stream else "json"
        provider_request = ProviderRequest(
            logical_request_id=logical_request_id,
            transport=transport_name,
            payload=payload,
            prompt_token_budget=prompt_budget,
            completion_token_budget=completion_budget,
            timeout_seconds=self.provider_timeout_seconds,
        )
        provider_started = time.perf_counter()
        trace_base = {
            "event": "PROVIDER_ANSWER",
            "provider_call": True,
            "logical_request_id": logical_request_id,
            "memory_status": context.status,
            "memory_mode": self.memory_mode,
            "memory_source": memory_source,
            "mcp_calls": mcp_calls,
            "memory_control_ms": (
                round(memory_control_ms, 3) if memory_control_ms is not None else None
            ),
            "request_parse_ms": (
                round(request_parse_ms, 3) if request_parse_ms is not None else None
            ),
            "context_sha256": context.context_sha256,
            "context_in_prompt": rendered_context is not None,
            "trace_id": context.trace_id,
            "claim_refs": list(context.claim_refs),
            "open_issue_ids": list(context.open_issue_ids),
            "provider_payload_sha256": hashlib.sha256(_canonical(payload)).hexdigest(),
            "excluded_memory_tools": list(excluded_memory_tools),
            "ordinary_tool_count": len(payload.get("tools", [])),
            "ordinary_tool_policy": ordinary_tool_policy,
            "ordinary_tool_delivery": ordinary_tool_delivery,
            "provider_transport": transport_name,
            "evidence_use_mode": self.evidence_use_mode,
            "evidence_use_applied": evidence_use_applied,
            "evidence_use_pass_count": (
                2
                if evidence_use_applied and self.evidence_use_mode == "ledger"
                else 1
                if evidence_use_applied
                else 0
            ),
            "reader_visible_alias_count": len(visible_aliases),
            "settlement_required": settlement_required,
        }
        if evidence_use_applied and self.evidence_use_mode == "model-native":
            reader_request = ReaderSessionInput(
                question=question,
                reader_visible_context=rendered_context or "",
                visible_evidence_aliases=tuple(visible_aliases),
                source_identity_digest=context.context_sha256,
                model_profile=ReaderModelProfile(
                    model_id=self.provider_capability.model_id,
                ),
                max_turns=2,
                token_budget=min(completion_budget, 4096),
                max_tool_calls=4,
            )
            reader_payload_sha256: list[str] = []

            def invoke_reader(
                reader_payload: Mapping[str, Any],
                ordinal: int,
            ) -> ReaderProviderRound:
                reader_logical_request_id = (
                    logical_request_id if ordinal == 1 else self._logical_request_id()
                )
                reader_payload_sha256.append(
                    hashlib.sha256(_canonical(reader_payload)).hexdigest()
                )
                request = ProviderRequest(
                    logical_request_id=reader_logical_request_id,
                    transport="json",
                    payload=reader_payload,
                    prompt_token_budget=prompt_budget,
                    completion_token_budget=completion_budget,
                    timeout_seconds=self.provider_timeout_seconds,
                )
                gateway_result = self.gateway.execute(
                    request,
                    self.transport,
                    lambda response: dict(response),
                )
                try:
                    content, _ = final_assistant_content(gateway_result.value)
                except CompletionCaptureError as exc:
                    raise ReaderSessionError("READER_RESPONSE_INVALID") from exc
                return ReaderProviderRound(
                    logical_request_id=gateway_result.logical_request_id,
                    native_request_id=gateway_result.native_request_id,
                    content=content,
                    finish_reason=gateway_result.finish_reason,
                    prompt_tokens=gateway_result.prompt_tokens,
                    completion_tokens=gateway_result.completion_tokens,
                )

            reader_result: ReaderSessionResult | None = None
            reader_error: Exception | None = None
            stop_reason: str
            try:
                reader_result = VllmEvidenceReaderSession(reader_request).run(
                    evidence_use_base_payload,
                    invoke_reader,
                )
            except (
                ReaderSessionError,
                ProviderCallError,
                BudgetError,
                CapabilityError,
            ) as exc:
                reader_error = exc

            if reader_result is not None:
                assistant_content = reader_result.answer_text
                provider_usage = reader_result.provider_usage
                support_aliases = (
                    reader_result.valid_cited_aliases
                    if reader_result.citation_supplied
                    else tuple(visible_aliases)
                )
                final_round = reader_result.provider_rounds[-1]
                request_id = final_round.native_request_id
                finish_reason = final_round.finish_reason
                stop_reason = reader_result.stop_reason
                tool_summaries = [item.summary() for item in reader_result.tool_calls]
                invalid_citation_count = reader_result.invalid_citation_count
                valid_cited_aliases = reader_result.valid_cited_aliases
                fallback = False
                fallback_reason = None
            else:
                assert reader_error is not None
                assistant_content = _READER_FALLBACK_ANSWER
                support_aliases = ()
                error_rounds = (
                    reader_error.rounds
                    if isinstance(reader_error, ReaderSessionError)
                    else ()
                )
                error_tools = (
                    reader_error.tool_calls
                    if isinstance(reader_error, ReaderSessionError)
                    else ()
                )
                prompt_tokens = sum(item.prompt_tokens for item in error_rounds)
                completion_tokens = sum(item.completion_tokens for item in error_rounds)
                provider_usage = {
                    "rounds": len(error_rounds),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                }
                request_id = (
                    error_rounds[-1].native_request_id
                    if error_rounds
                    else "chatcmpl-reader-fallback-"
                    + hashlib.sha256(_canonical(payload_input)).hexdigest()[:18]
                )
                finish_reason = "stop"
                stop_reason = "HOST_FALLBACK"
                tool_summaries = [item.summary() for item in error_tools]
                invalid_citation_count = 0
                valid_cited_aliases = ()
                fallback = True
                fallback_reason = (
                    reader_error.reason_code
                    if isinstance(reader_error, ReaderSessionError)
                    else str(reader_error)
                )
                self._record(
                    {
                        "event": "HOST_READER_SESSION_FALLBACK",
                        "provider_call": False,
                        "logical_request_id": logical_request_id,
                        "reason_code": fallback_reason,
                        "provider_rounds": provider_usage["rounds"],
                        "tool_call_count": len(tool_summaries),
                        "context_sha256": context.context_sha256,
                    }
                )

            completion = _completion(
                request_id=request_id,
                content=assistant_content,
                finish_reason=finish_reason,
                usage={
                    "prompt_tokens": provider_usage["prompt_tokens"],
                    "completion_tokens": provider_usage["completion_tokens"],
                    "total_tokens": provider_usage["total_tokens"],
                },
            )
            if settlement_required:
                if bound is None or memory_recall is None:
                    raise ProviderCallError("HOST_SETTLEMENT_CONTEXT_ABSENT")
                self._settle_answer(
                    metadata=metadata,
                    bound=bound,
                    messages=messages,
                    assistant_content=assistant_content,
                    context_sha256=context.context_sha256,
                    support_aliases=support_aliases,
                    recall=memory_recall,
                )
            self._record(
                {
                    **trace_base,
                    "logical_request_id": (
                        reader_result.provider_rounds[-1].logical_request_id
                        if reader_result is not None
                        else logical_request_id
                    ),
                    "native_request_id": request_id,
                    "finish_reason": finish_reason,
                    "provider_transport": "json",
                    "prompt_tokens": provider_usage["prompt_tokens"],
                    "completion_tokens": provider_usage["completion_tokens"],
                    "provider_prefill_answer_ms": round(
                        (time.perf_counter() - provider_started) * 1000,
                        3,
                    ),
                    "adapter_total_ms": round(
                        (time.perf_counter() - adapter_started) * 1000,
                        3,
                    ),
                    "response_sha256": hashlib.sha256(_canonical(completion)).hexdigest(),
                    "reader_session_result": {
                        "source_identity_digest": reader_request.source_identity_digest,
                        "transport": reader_request.model_profile.transport,
                        "provider_rounds": provider_usage["rounds"],
                        "stop_reason": stop_reason,
                        "fallback": fallback,
                        "fallback_reason": fallback_reason,
                        "citation_supplied": (
                            reader_result.citation_supplied
                            if reader_result is not None
                            else False
                        ),
                        "valid_cited_aliases": list(valid_cited_aliases),
                        "invalid_citation_count": invalid_citation_count,
                        "tool_calls": tool_summaries,
                        "provider_usage": provider_usage,
                    },
                    "reader_provider_payload_sha256": reader_payload_sha256,
                    "evidence_use_pass_count": provider_usage["rounds"],
                    "delivered_answer_sha256": hashlib.sha256(
                        assistant_content.encode()
                    ).hexdigest(),
                }
            )
            if incoming.stream:
                return (
                    StreamingCompletion(iter((_sse(completion),))),
                    f"PROVIDER_{context.status}",
                )
            return completion, f"PROVIDER_{context.status}"
        if incoming.stream:
            if evidence_use_applied and self.evidence_use_mode == "ledger":
                try:
                    ledger_buffer = buffer_openai_stream(
                        self.gateway.execute_stream(provider_request, self.stream_transport)
                    )
                    if ledger_buffer.finish_reason != "stop":
                        raise EvidenceUseValidationError(
                            "EVIDENCE_USE_ANSWER_INCOMPLETE"
                        )
                    evidence_ledger = parse_evidence_ledger(
                        ledger_buffer.content,
                        visible_aliases=visible_aliases,
                    )
                    final_payload = apply_ledger_final_protocol(
                        evidence_use_base_payload,
                        ledger=evidence_ledger,
                        visible_aliases=visible_aliases,
                    )
                    final_logical_request_id = self._logical_request_id()
                    final_request = ProviderRequest(
                        logical_request_id=final_logical_request_id,
                        transport=transport_name,
                        payload=final_payload,
                        prompt_token_budget=prompt_budget,
                        completion_token_budget=completion_budget,
                        timeout_seconds=self.provider_timeout_seconds,
                    )
                    final_buffer = buffer_openai_stream(
                        self.gateway.execute_stream(final_request, self.stream_transport)
                    )
                    if final_buffer.finish_reason != "stop":
                        raise EvidenceUseValidationError(
                            "EVIDENCE_USE_ANSWER_INCOMPLETE"
                        )
                    grounded_use = parse_grounded_evidence_use(
                        final_buffer.content,
                        visible_aliases=visible_aliases,
                    )
                except (CompletionCaptureError, EvidenceUseValidationError) as exc:
                    self._record(
                        {
                            "event": "HOST_EVIDENCE_USE_REJECTED",
                            "provider_call": False,
                            "logical_request_id": logical_request_id,
                            "evidence_use_pass": "ledger_or_final",
                            "reason_code": str(exc),
                        }
                    )
                    raise ProviderCallError("ANSWER_PARSE_FAILED") from exc
                if settlement_required:
                    if bound is None or memory_recall is None:
                        raise ProviderCallError("HOST_SETTLEMENT_CONTEXT_ABSENT")
                    self._settle_answer(
                        metadata=metadata,
                        bound=bound,
                        messages=messages,
                        assistant_content=grounded_use.answer_text,
                        context_sha256=context.context_sha256,
                        support_aliases=grounded_use.evidence_aliases,
                        recall=memory_recall,
                    )
                self._record(
                    {
                        **trace_base,
                        "native_request_id": final_buffer.native_request_id,
                        "ledger_native_request_id": ledger_buffer.native_request_id,
                        "logical_request_id": final_logical_request_id,
                        "ledger_logical_request_id": logical_request_id,
                        "finish_reason": final_buffer.finish_reason,
                        "ordinary_tool_delivery_evidence": None,
                        "prompt_tokens": (
                            ledger_buffer.usage["prompt_tokens"]
                            + final_buffer.usage["prompt_tokens"]
                        ),
                        "completion_tokens": (
                            ledger_buffer.usage["completion_tokens"]
                            + final_buffer.usage["completion_tokens"]
                        ),
                        "ledger_provider_payload_sha256": trace_base[
                            "provider_payload_sha256"
                        ],
                        "final_provider_payload_sha256": hashlib.sha256(
                            _canonical(final_payload)
                        ).hexdigest(),
                        "provider_prefill_answer_ms": round(
                            (time.perf_counter() - provider_started) * 1000, 3
                        ),
                        "adapter_total_ms": round(
                            (time.perf_counter() - adapter_started) * 1000, 3
                        ),
                        "evidence_use_result": _evidence_use_trace_result(
                            grounded_use,
                            pass_count=2,
                        ),
                        "delivered_answer_sha256": hashlib.sha256(
                            grounded_use.answer_text.encode()
                        ).hexdigest(),
                    }
                )
                return (
                    StreamingCompletion(
                        iter(
                            (
                                _sse(
                                    _completion(
                                        request_id=final_buffer.native_request_id,
                                        content=grounded_use.answer_text,
                                        finish_reason=final_buffer.finish_reason,
                                        usage=final_buffer.usage,
                                    )
                                ),
                            )
                        )
                    ),
                    f"PROVIDER_{context.status}",
                )
            chunks = self.gateway.execute_stream(provider_request, self.stream_transport)
            if ordinary_tool_compatibility_applied:
                chunks = _vllm_json_schema_named_tool_chunks(chunks)

            if settlement_required or (
                evidence_use_applied and self.evidence_use_mode == "grounded"
            ):
                try:
                    buffered = buffer_openai_stream(chunks)
                    stream_grounded_use = (
                        parse_grounded_evidence_use(
                            buffered.content,
                            visible_aliases=visible_aliases,
                        )
                        if self.evidence_use_mode == "grounded"
                        else None
                    )
                except (CompletionCaptureError, EvidenceUseValidationError) as exc:
                    self._record(
                        {
                            "event": "HOST_EVIDENCE_USE_REJECTED",
                            "provider_call": False,
                            "logical_request_id": logical_request_id,
                            "reason_code": str(exc),
                        }
                    )
                    raise ProviderCallError("ANSWER_PARSE_FAILED") from exc
                assistant_content = (
                    stream_grounded_use.answer_text
                    if stream_grounded_use is not None
                    else buffered.content
                )
                support_aliases = (
                    stream_grounded_use.evidence_aliases
                    if stream_grounded_use is not None
                    else visible_aliases
                )
                if settlement_required:
                    if bound is None or memory_recall is None:
                        raise ProviderCallError("HOST_SETTLEMENT_CONTEXT_ABSENT")
                    if buffered.finish_reason != "stop":
                        raise ProviderCallError("HOST_SETTLEMENT_ANSWER_INCOMPLETE")
                    self._settle_answer(
                        metadata=metadata,
                        bound=bound,
                        messages=messages,
                        assistant_content=assistant_content,
                        context_sha256=context.context_sha256,
                        support_aliases=support_aliases,
                        recall=memory_recall,
                    )
                terminal = next(
                    event
                    for event in reversed(self.gateway.read_ledger())
                    if event.get("event") == "PROVIDER_TERMINAL"
                    and event.get("logical_request_id") == logical_request_id
                )
                evidence_result = (
                    _evidence_use_trace_result(stream_grounded_use)
                    if stream_grounded_use is not None
                    else None
                )
                self._record(
                    {
                        **trace_base,
                        "native_request_id": terminal.get("native_request_id"),
                        "finish_reason": terminal.get("finish_reason"),
                        "ordinary_tool_delivery_evidence": None,
                        "prompt_tokens": terminal.get("prompt_tokens"),
                        "completion_tokens": terminal.get("completion_tokens"),
                        "provider_prefill_answer_ms": round(
                            (time.perf_counter() - provider_started) * 1000, 3
                        ),
                        "adapter_total_ms": round(
                            (time.perf_counter() - adapter_started) * 1000, 3
                        ),
                        "evidence_use_result": evidence_result,
                        "delivered_answer_sha256": hashlib.sha256(
                            assistant_content.encode()
                        ).hexdigest(),
                    }
                )
                delivery = (
                    (
                        _sse(
                            _completion(
                                request_id=buffered.native_request_id,
                                content=assistant_content,
                                finish_reason=buffered.finish_reason,
                                usage=buffered.usage,
                            )
                        ),
                    )
                    if stream_grounded_use is not None
                    else buffered.chunks
                )
                return StreamingCompletion(iter(delivery)), f"PROVIDER_{context.status}"

            def traced_chunks() -> Iterator[bytes]:
                yield from chunks
                ledger = self.gateway.read_ledger()
                terminal = next(
                    event
                    for event in reversed(ledger)
                    if event.get("event") == "PROVIDER_TERMINAL"
                    and event.get("logical_request_id") == logical_request_id
                )
                self._record(
                    {
                        **trace_base,
                        "native_request_id": terminal.get("native_request_id"),
                        "finish_reason": terminal.get("finish_reason"),
                        "ordinary_tool_delivery_evidence": (
                            {
                                **ordinary_tool_delivery_evidence,
                                "native_finish_reason": terminal.get("finish_reason"),
                            }
                            if ordinary_tool_delivery_evidence is not None
                            else None
                        ),
                        "prompt_tokens": terminal.get("prompt_tokens"),
                        "completion_tokens": terminal.get("completion_tokens"),
                        "provider_prefill_answer_ms": round(
                            (time.perf_counter() - provider_started) * 1000, 3
                        ),
                        "adapter_total_ms": round(
                            (time.perf_counter() - adapter_started) * 1000, 3
                        ),
                    }
                )

            return StreamingCompletion(traced_chunks()), f"PROVIDER_{context.status}"

        if evidence_use_applied and self.evidence_use_mode == "ledger":
            evidence_ledgers: list[EvidenceLedgerV01] = []

            def parse_ledger(response: Mapping[str, Any]) -> dict[str, Any]:
                content, finish_reason = final_assistant_content(response)
                if finish_reason != "stop":
                    raise EvidenceUseValidationError(
                        "EVIDENCE_USE_ANSWER_INCOMPLETE"
                    )
                evidence_ledgers.append(
                    parse_evidence_ledger(
                        content,
                        visible_aliases=visible_aliases,
                    )
                )
                return dict(response)

            ledger_result = self.gateway.execute(
                provider_request,
                self.transport,
                parse_ledger,
            )
            evidence_ledger = evidence_ledgers[0]
            final_payload = apply_ledger_final_protocol(
                evidence_use_base_payload,
                ledger=evidence_ledger,
                visible_aliases=visible_aliases,
            )
            final_logical_request_id = self._logical_request_id()
            final_request = ProviderRequest(
                logical_request_id=final_logical_request_id,
                transport=transport_name,
                payload=final_payload,
                prompt_token_budget=prompt_budget,
                completion_token_budget=completion_budget,
                timeout_seconds=self.provider_timeout_seconds,
            )

            grounded_results: list[GroundedEvidenceUseV01] = []

            def parse_final(response: Mapping[str, Any]) -> dict[str, Any]:
                content, finish_reason = final_assistant_content(response)
                if finish_reason != "stop":
                    raise EvidenceUseValidationError(
                        "EVIDENCE_USE_ANSWER_INCOMPLETE"
                    )
                grounded = parse_grounded_evidence_use(
                    content,
                    visible_aliases=visible_aliases,
                )
                grounded_results.append(grounded)
                return replace_assistant_content(response, grounded.answer_text)

            final_result = self.gateway.execute(
                final_request,
                self.transport,
                parse_final,
            )
            provider_prefill_answer_ms = (time.perf_counter() - provider_started) * 1000
            assistant_content, _ = final_assistant_content(final_result.value)
            ledger_grounded_result = grounded_results[0]
            if settlement_required:
                if bound is None or memory_recall is None:
                    raise ProviderCallError("HOST_SETTLEMENT_CONTEXT_ABSENT")
                self._settle_answer(
                    metadata=metadata,
                    bound=bound,
                    messages=messages,
                    assistant_content=assistant_content,
                    context_sha256=context.context_sha256,
                    support_aliases=ledger_grounded_result.evidence_aliases,
                    recall=memory_recall,
                )
            self._record(
                {
                    **trace_base,
                    "native_request_id": final_result.native_request_id,
                    "ledger_native_request_id": ledger_result.native_request_id,
                    "logical_request_id": final_logical_request_id,
                    "ledger_logical_request_id": logical_request_id,
                    "finish_reason": final_result.finish_reason,
                    "prompt_tokens": (
                        ledger_result.prompt_tokens + final_result.prompt_tokens
                    ),
                    "completion_tokens": (
                        ledger_result.completion_tokens + final_result.completion_tokens
                    ),
                    "provider_prefill_answer_ms": round(provider_prefill_answer_ms, 3),
                    "adapter_total_ms": round(
                        (time.perf_counter() - adapter_started) * 1000, 3
                    ),
                    "response_sha256": hashlib.sha256(
                        _canonical(final_result.value)
                    ).hexdigest(),
                    "ledger_provider_payload_sha256": trace_base[
                        "provider_payload_sha256"
                    ],
                    "final_provider_payload_sha256": hashlib.sha256(
                        _canonical(final_payload)
                    ).hexdigest(),
                    "evidence_use_result": _evidence_use_trace_result(
                        ledger_grounded_result,
                        pass_count=2,
                    ),
                }
            )
            return dict(final_result.value), f"PROVIDER_{context.status}"

        parsed_grounded_results: list[GroundedEvidenceUseV01] = []

        def parse_response(response: Mapping[str, Any]) -> dict[str, Any]:
            value = dict(response)
            if evidence_use_applied and self.evidence_use_mode == "grounded":
                content, finish_reason = final_assistant_content(value)
                if finish_reason != "stop":
                    raise EvidenceUseValidationError("EVIDENCE_USE_ANSWER_INCOMPLETE")
                grounded = parse_grounded_evidence_use(
                    content,
                    visible_aliases=visible_aliases,
                )
                parsed_grounded_results.append(grounded)
                value = replace_assistant_content(value, grounded.answer_text)
            return value

        result = self.gateway.execute(
            provider_request,
            self.transport,
            parse_response,
        )
        provider_prefill_answer_ms = (time.perf_counter() - provider_started) * 1000
        if settlement_required:
            if bound is None or memory_recall is None:
                raise ProviderCallError("HOST_SETTLEMENT_CONTEXT_ABSENT")
            assistant_content, finish_reason = final_assistant_content(result.value)
            if finish_reason != "stop":
                raise ProviderCallError("HOST_SETTLEMENT_ANSWER_INCOMPLETE")
            self._settle_answer(
                metadata=metadata,
                bound=bound,
                messages=messages,
                assistant_content=assistant_content,
                context_sha256=context.context_sha256,
                support_aliases=(
                    parsed_grounded_results[0].evidence_aliases
                    if parsed_grounded_results
                    else visible_aliases
                ),
                recall=memory_recall,
            )
        self._record(
            {
                **trace_base,
                "native_request_id": result.native_request_id,
                "finish_reason": result.finish_reason,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "provider_prefill_answer_ms": round(provider_prefill_answer_ms, 3),
                "adapter_total_ms": round((time.perf_counter() - adapter_started) * 1000, 3),
                "response_sha256": hashlib.sha256(_canonical(result.value)).hexdigest(),
                "evidence_use_result": (
                    _evidence_use_trace_result(parsed_grounded_results[0])
                    if parsed_grounded_results
                    else None
                ),
            }
        )
        return dict(result.value), f"PROVIDER_{context.status}"
