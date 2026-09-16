"""Raw-Evidence LongMemEval adapter over the optimized governed MCP path."""

from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Literal
from urllib.parse import quote, unquote

from evals.dg14.contracts import (
    DG14ContextBudgetError,
    DG14ContractError,
    DG14HistoryEvent,
    DG14LifecycleError,
    DG14ReadinessError,
    DG14StageRecord,
    DG14TransportError,
    deterministic_history_session_id,
    deterministic_project_id,
    normalize_lme_timestamp,
    sha256_json,
    validate_label_free,
)
from evals.dg14.reader_token_accounting import (
    FrozenReaderTokenCounter,
    frozen_reader_token_counter,
)
from evals.dg15.contracts import (
    METHOD_ID,
    DG14CaseNamespace,
    DG15AdapterConfig,
    DG15AdapterStats,
    DG15CallRecord,
    DG15Provenance,
    DG15QueryResult,
    TokenCounter,
)
from evals.dg15.mcp_stdio import (
    McpBatchCall,
    McpBatchOutcome,
    MultiplexedStdioMcpTransport,
)

_STATUS_VALUES = frozenset({"HIT", "PARTIAL", "CONTESTED", "ABSENT", "ABSTAINED"})
_MAX_READINESS_TARGETS = 512
_PROJECTION_VERSIONS = {
    "evidence": "evidence-search-v1",
    "fts": "canonical-fts-v1",
    "vector": "canonical-vector-v1",
}
_READER_UNIT_HEADER = re.compile(
    r"(?m)^(?:"
    r"\[(?P<alias>(?:C|D|E)\d+) "
    r"(?:"
    r"DERIVED OPERATOR RESULT / NON-CANONICAL READ-ONLY|"
    r"CANONICAL STATE / GOVERNED|"
    r"ACCEPTED BINDING SPAN / NON-CANONICAL(?: [^\]\n]+)?|"
    r"EVIDENCE WINDOW / NON-CANONICAL(?: [^\]\n]+)?"
    r")\]|"
    r"\[(?P<issue_alias>I\d+) OPEN ISSUE / SAFETY\]|"
    r"\[(?P<issue>OPEN ISSUE / SAFETY)\]"
    r")$"
)


def _output_limit_diagnostic_suffix(response: Mapping[str, object]) -> str:
    diagnostics = response.get("wire_diagnostics")
    if not isinstance(diagnostics, Mapping):
        return ""
    ranked: list[tuple[str, int]] = []
    for section_name, prefix, limit in (
        ("top_level_field_bytes", "top", 6),
        ("memory_context_field_bytes", "memory_context", 4),
        ("derived_result_field_bytes", "derived_result", 2),
    ):
        section = diagnostics.get(section_name)
        if not isinstance(section, Mapping):
            continue
        values = sorted(
            (
                (f"{prefix}.{key}", value)
                for key, value in section.items()
                if isinstance(value, int) and not isinstance(value, bool)
            ),
            key=lambda item: (-item[1], item[0]),
        )
        ranked.extend(values[:limit])
    sizes = ",".join(f"{name}:{size}" for name, size in ranked)
    return (
        f"; original_bytes={response.get('original_bytes')};"
        f" compacted_bytes={response.get('compacted_bytes')};"
        f" dominant_fields={sizes}"
    )


def _resolve_contract_preimage(response: Mapping[str, object]) -> Mapping[str, object]:
    """Return bounded structural fields needed to audit pre-validation failures."""

    memory_context = response.get("memory_context")
    context = memory_context if isinstance(memory_context, Mapping) else {}
    raw_windows = context.get("windows")
    windows = raw_windows if isinstance(raw_windows, list) else []
    raw_receipt = response.get("context_receipt")
    receipt = raw_receipt if isinstance(raw_receipt, Mapping) else {}
    raw_mapping = receipt.get("receipt_mapping")
    receipt_mapping = raw_mapping if isinstance(raw_mapping, list) else []
    raw_access = response.get("access_trace")
    access = raw_access if isinstance(raw_access, Mapping) else {}
    raw_span_links = access.get("span_links")
    span_links = raw_span_links if isinstance(raw_span_links, Mapping) else {}

    return {
        "schema_version": "dg15-resolve-contract-preimage-v0.1",
        "response_sha256": sha256_json(response),
        "request_id": response.get("request_id"),
        "trace_id": response.get("trace_id"),
        "status": response.get("status"),
        "reason": response.get("reason"),
        "fallback_used": response.get("fallback_used"),
        "item_count": _bounded_sequence_count(response.get("items")),
        "evidence_ref_count": _bounded_sequence_count(response.get("evidence_refs")),
        "memory_context": {
            "present": isinstance(memory_context, Mapping),
            "schema_version": context.get("schema_version"),
            "authority_class": context.get("authority_class"),
            "available_windows": context.get("available_windows"),
            "selected_windows": context.get("selected_windows"),
            "window_count": len(windows) if isinstance(raw_windows, list) else None,
            "selected_evidence_ids": _bounded_string_values(
                context.get("selected_evidence_ids")
            ),
            "selected_source_turn_refs": _bounded_string_values(
                context.get("selected_source_turn_refs")
            ),
            "context_truncated": context.get("context_truncated"),
            "semantic_context_digest": context.get("semantic_context_digest"),
            "reader_context_digest": context.get("reader_context_digest"),
        },
        "context_receipt": {
            "present": isinstance(raw_receipt, Mapping),
            "schema_version": receipt.get("schema_version"),
            "source_evidence_ids": _bounded_string_values(
                receipt.get("source_evidence_ids")
            ),
            "mapping_count": (
                len(receipt_mapping) if isinstance(raw_mapping, list) else None
            ),
            "mapping": [
                {
                    "alias": item.get("alias"),
                    "evidence_ids": _bounded_string_values(item.get("evidence_ids")),
                    "source_turn_refs": _bounded_string_values(
                        item.get("source_turn_refs")
                    ),
                }
                for item in receipt_mapping[:32]
                if isinstance(item, Mapping)
            ],
            "mapping_truncated": len(receipt_mapping) > 32,
        },
        "access_trace": {
            "logical_mcp_calls": access.get("logical_mcp_calls"),
            "automatic_retry_count": access.get("automatic_retry_count"),
            "retry_policy_max_retries": access.get("retry_policy_max_retries"),
            "runtime_request_id": span_links.get("runtime_request_id"),
            "retrieval_trace_id": span_links.get("retrieval_trace_id"),
        },
    }


def _bounded_sequence_count(value: object) -> int | None:
    return len(value) if isinstance(value, list) else None


def _bounded_string_values(value: object) -> Mapping[str, object]:
    if not isinstance(value, list):
        return {"valid": False, "count": None, "values": [], "truncated": False}
    values = [item for item in value[:64] if isinstance(item, str)]
    return {
        "valid": len(values) == min(len(value), 64)
        and all(isinstance(item, str) for item in value),
        "count": len(value),
        "values": values,
        "truncated": len(value) > 64,
    }


_LME_SOURCE_REF = re.compile(
    r"^longmemeval://case/([^/]+)/session/(\d+)/([^/]+)/turn/(\d+)(?:\?|$)"
)


def compact_lme_source_ref(value: str) -> str:
    """Render an exact LongMemEval turn identity without query-string bulk."""

    matched = _LME_SOURCE_REF.match(value)
    if matched is None:
        return value
    case_id, session_ordinal, session_id, turn_ordinal = matched.groups()
    return (
        f"{unquote(case_id)}:s{session_ordinal}:{unquote(session_id)}:t{turn_ordinal}"
    )


@dataclass(frozen=True, slots=True)
class _CaptureGovernance:
    source_type: str
    source_ref: str
    subject_id: str
    speaker: str
    session_id: str
    session_ordinal: int
    turn_id: str
    turn_ordinal: int
    round_id: str
    round_ordinal: int
    previous_turn_id: str | None
    next_turn_id: str | None
    purpose: str
    confirmation: str
    retention_state: str
    data_classification: str
    content_sha256: str
    content_chars: int
    runtime_request_id: str


@dataclass(frozen=True, slots=True)
class _Evidence:
    event: DG14HistoryEvent
    evidence_id: str
    outbox_id: str
    source_ref: str
    capture_governance: _CaptureGovernance


@dataclass(frozen=True, slots=True)
class _ResolvedEvidence:
    rank: int
    evidence: _Evidence
    relevance_score: float | None


@dataclass(frozen=True, slots=True)
class _PackedContext:
    text: str
    tokens: int
    standalone_tokens: int
    selected_sessions: frozenset[tuple[int, str]]
    selected_source_refs: tuple[str, ...]
    selected_windows: int
    available_windows: int
    locally_truncated: bool
    semantic_context_digest: str
    reader_context_digest: str
    raw_retrieval_trace: tuple[Mapping[str, object], ...]
    admitted_evidence_trace: Mapping[str, object]
    reader_visible_trace: Mapping[str, object]


class DG15MilaiMcpAdapter:
    """One isolated case using Raw Evidence projection and no canonical wrapper."""

    method_id = METHOD_ID

    def __init__(
        self,
        config: DG15AdapterConfig,
        token_counter: TokenCounter,
        transport: MultiplexedStdioMcpTransport | None = None,
        *,
        close_transport_on_cleanup: bool = True,
    ) -> None:
        self._config = config
        self._token_counter = token_counter
        self._reader_tokens: FrozenReaderTokenCounter = frozen_reader_token_counter()
        self._transport = transport or MultiplexedStdioMcpTransport(
            config.dg14_config()
        )
        self._close_transport_on_cleanup = close_transport_on_cleanup
        self._state: Literal[
            "NEW", "RESET", "INGESTING", "FINALIZED", "QUERIED", "CLEANED"
        ] = "NEW"
        self._namespace: DG14CaseNamespace | None = None
        self._pending: list[DG14HistoryEvent] = []
        self._events_by_id: dict[str, DG14HistoryEvent] = {}
        self._evidence_by_id: dict[str, _Evidence] = {}
        self._evidence_by_event: dict[str, _Evidence] = {}
        self._call_records: list[DG15CallRecord] = []
        self._stage_records: list[DG14StageRecord] = []
        self._physical_batches = 0
        self._last_result: DG15QueryResult | None = None
        self._last_resolve_contract_preimage: Mapping[str, object] | None = None
        self._ingest_ms = 0.0
        self._finalize_ms = 0.0
        self._query_ms: list[float] = []
        self._context_tokens: list[int] = []
        self._cleanup_receipt: Mapping[str, object] | None = None
        self._capture_attempted_count = 0
        self._capture_returned_success_count = 0
        self._capture_returned_failure_count = 0
        self._capture_ambiguous_success_count = 0
        self._capture_unknown_outcome_count = 0

    @property
    def namespace(self) -> DG14CaseNamespace:
        if self._namespace is None:
            raise DG14LifecycleError("adapter has no active case namespace")
        return self._namespace

    def reset(self, run_id: str, case_id: str) -> DG14CaseNamespace:
        if self._state not in {"NEW", "CLEANED"}:
            raise DG14LifecycleError("reset requires a new or cleaned adapter")
        started = perf_counter()
        project_id = deterministic_project_id(
            run_id, case_id, prefix=self._config.project_prefix
        )
        scope = {**dict(self._config.scope), "project_ids": [project_id]}
        self._transport.open_case(scope)
        self._namespace = DG14CaseNamespace(
            run_id=run_id,
            case_id=case_id,
            project_id=project_id,
            scope=scope,
            tenant_id=self._config.tenant_id,
            principal_id=self._config.principal_id,
        )
        self._pending = []
        self._events_by_id = {}
        self._evidence_by_id = {}
        self._evidence_by_event = {}
        self._call_records = []
        self._stage_records = []
        self._physical_batches = 0
        self._last_result = None
        self._last_resolve_contract_preimage = None
        self._ingest_ms = 0.0
        self._finalize_ms = 0.0
        self._query_ms = []
        self._context_tokens = []
        self._cleanup_receipt = None
        self._capture_attempted_count = 0
        self._capture_returned_success_count = 0
        self._capture_returned_failure_count = 0
        self._capture_ambiguous_success_count = 0
        self._capture_unknown_outcome_count = 0
        self._state = "RESET"
        self._stage("reset", started, 0, {"project_id": project_id})
        return self.namespace

    def ingest(self, event: DG14HistoryEvent) -> str:
        if self._state not in {"RESET", "INGESTING"}:
            raise DG14LifecycleError("ingest requires a reset, non-finalized case")
        validate_label_free(event.canonical())
        if event.case_id != self.namespace.case_id:
            raise DG14ContractError(
                "history event case_id differs from active namespace"
            )
        if event.event_id in self._events_by_id:
            raise DG14ContractError("duplicate deterministic Event identity")
        self._events_by_id[event.event_id] = event
        self._pending.append(event)
        self._state = "INGESTING"
        return event.event_id

    def ingest_many(self, events: Sequence[DG14HistoryEvent]) -> tuple[str, ...]:
        identities = tuple(self.ingest(event) for event in events)
        self.flush_ingest()
        return identities

    def flush_ingest(self) -> tuple[str, ...]:
        if not self._pending:
            return ()
        started = perf_counter()
        logical_start = len(self._call_records)
        captured: list[str] = []
        returned_success_count = 0
        returned_failure_count = 0
        ambiguous_success_count = 0
        failure_codes: set[str] = set()
        invalid_success_types: set[str] = set()
        while self._pending:
            # The stdio envelope has one fixed outer deadline.  Keep each
            # envelope to one concurrency wave so aggregate sequential tool
            # latency cannot invalidate the request/response identity stream.
            events = tuple(self._pending[: self._config.mcp_concurrency])
            del self._pending[: len(events)]
            calls = [
                McpBatchCall(
                    "submitter",
                    "milai_evidence_capture",
                    self._capture_arguments(event),
                )
                for event in events
            ]
            self._capture_attempted_count += len(events)
            try:
                outcomes = self._call_many("ingest", calls)
            except Exception as exc:
                self._capture_unknown_outcome_count += len(events)
                elapsed = (perf_counter() - started) * 1_000
                self._ingest_ms += elapsed
                self._stage(
                    "ingest",
                    started,
                    logical_start,
                    {
                        "logical_items": len(captured),
                        "attempted_count": self._capture_attempted_count,
                        "returned_success_count": returned_success_count,
                        "returned_failure_count": returned_failure_count,
                        "registered_evidence_count": len(captured),
                        "ambiguous_success_count": ambiguous_success_count,
                        "unknown_outcome_count": self._capture_unknown_outcome_count,
                        "envelope_error_type": type(exc).__name__,
                        "physical_batches": self._physical_batches,
                        "mcp_concurrency": self._config.mcp_concurrency,
                    },
                )
                raise DG14TransportError(
                    "Evidence capture wave outcome is unknown after MCP envelope "
                    f"failure: attempted={len(events)}, returned=0, "
                    f"unknown={len(events)}, error_type={type(exc).__name__}"
                ) from exc
            for event, outcome in zip(events, outcomes, strict=True):
                if outcome.status != "SUCCEEDED" or outcome.structured is None:
                    returned_failure_count += 1
                    self._capture_returned_failure_count += 1
                    failure_codes.add(outcome.error_code or "UNKNOWN_MCP_FAILURE")
                    continue
                returned_success_count += 1
                self._capture_returned_success_count += 1
                try:
                    response = outcome.structured
                    evidence_id = self._required_text(response, "evidence_id")
                    outbox_id = self._required_text(response, "outbox_id")
                    if evidence_id in self._evidence_by_id:
                        raise DG14ContractError(
                            "Runtime reused one Evidence ID for distinct Events"
                        )
                    evidence = _Evidence(
                        event=event,
                        evidence_id=evidence_id,
                        outbox_id=outbox_id,
                        source_ref=self._event_source_ref(event),
                        capture_governance=self._capture_governance(event, response),
                    )
                except Exception as exc:  # noqa: BLE001 - drain the entire wave
                    ambiguous_success_count += 1
                    self._capture_ambiguous_success_count += 1
                    invalid_success_types.add(type(exc).__name__)
                    continue
                self._evidence_by_id[evidence_id] = evidence
                self._evidence_by_event[event.event_id] = evidence
                captured.append(evidence_id)
            if returned_failure_count or ambiguous_success_count:
                elapsed = (perf_counter() - started) * 1_000
                self._ingest_ms += elapsed
                details = {
                    "logical_items": len(captured),
                    "returned_success_count": returned_success_count,
                    "returned_failure_count": returned_failure_count,
                    "registered_evidence_count": len(captured),
                    "ambiguous_success_count": ambiguous_success_count,
                    "unknown_outcome_count": self._capture_unknown_outcome_count,
                    "failure_codes": sorted(failure_codes),
                    "invalid_success_types": sorted(invalid_success_types),
                    "physical_batches": self._physical_batches,
                    "mcp_concurrency": self._config.mcp_concurrency,
                }
                self._stage("ingest", started, logical_start, details)
                raise DG14TransportError(
                    "Evidence capture wave failed after complete outcome drain: "
                    f"returned_success={returned_success_count}, "
                    f"registered={len(captured)}, "
                    f"failed={returned_failure_count}, "
                    f"ambiguous={ambiguous_success_count}, "
                    f"codes={','.join(sorted(failure_codes)) or 'NONE'}, "
                    "invalid_success_types="
                    f"{','.join(sorted(invalid_success_types)) or 'NONE'}"
                )
        elapsed = (perf_counter() - started) * 1_000
        self._ingest_ms += elapsed
        self._stage(
            "ingest",
            started,
            logical_start,
            {
                "logical_items": len(captured),
                "returned_success_count": returned_success_count,
                "returned_failure_count": returned_failure_count,
                "registered_evidence_count": len(captured),
                "ambiguous_success_count": ambiguous_success_count,
                "unknown_outcome_count": self._capture_unknown_outcome_count,
                "physical_batches": self._physical_batches,
                "mcp_concurrency": self._config.mcp_concurrency,
            },
        )
        return tuple(captured)

    def finalize(self) -> Mapping[str, object]:
        if self._state != "INGESTING":
            raise DG14LifecycleError("finalize requires at least one ingested Event")
        started = perf_counter()
        logical_start = len(self._call_records)
        self.flush_ingest()
        targets = [item.outbox_id for item in self._evidence_by_id.values()]
        barrier_responses: list[Mapping[str, object]] = []
        for offset in range(0, len(targets), _MAX_READINESS_TARGETS):
            remaining_ms = self._config.barrier_timeout_ms
            while True:
                wait_slice_ms = min(30_000, remaining_ms)
                response = self._call(
                    "finalize_barrier",
                    "reader-detail",
                    "milai_projection_readiness_wait",
                    {
                        "target_outbox_ids": targets[
                            offset : offset + _MAX_READINESS_TARGETS
                        ],
                        "required_projections": list(self._config.barrier_projections),
                        "expected_versions": {
                            projection: _PROJECTION_VERSIONS[projection]
                            for projection in self._config.barrier_projections
                        },
                        "timeout_ms": wait_slice_ms,
                        "poll_interval_ms": 25,
                    },
                )
                remaining_ms -= wait_slice_ms
                if (
                    response.get("status") != "PROJECTION_READINESS_TIMEOUT"
                    or remaining_ms <= 0
                ):
                    break
            if response.get("status") != "READY":
                raise DG14ReadinessError(
                    f"Evidence projection barrier returned {response.get('status')}"
                )
            if response.get("projection_work_started") is not False:
                raise DG14ReadinessError(
                    "barrier did not prove readiness-only execution"
                )
            barrier_responses.append(response)
        response = barrier_responses[-1]
        self._state = "FINALIZED"
        self._finalize_ms = (perf_counter() - started) * 1_000
        self._stage(
            "finalize_barrier",
            started,
            logical_start,
            {
                "claim_count": 0,
                "evidence_count": len(self._evidence_by_id),
                "target_count": len(targets),
                "barrier_calls": len(barrier_responses),
                "barrier_wait_slices": sum(
                    1
                    for record in self._call_records[logical_start:]
                    if record.stage == "finalize_barrier"
                ),
                "target_watermark": response.get("target_watermark"),
                "barrier_wait_ms": response.get("barrier_wait_ms"),
            },
        )
        return response

    def query(
        self,
        question: str,
        timestamp: str,
        budget: int,
        mode: str = "default",
        *,
        task_context: Mapping[str, object] | None = None,
    ) -> DG15QueryResult:
        if self._state not in {"FINALIZED", "QUERIED"}:
            raise DG14LifecycleError("query requires a finalized case")
        if not question.strip() or mode != "default":
            raise DG14ContractError("query and default mode are required")
        if budget not in self._config.allowed_budgets:
            raise DG14ContractError("memory token budget is not enabled")
        question_at = normalize_lme_timestamp(timestamp)
        if task_context is not None:
            validate_label_free(task_context, path="query.task_context")
            projects = task_context.get("project_ids")
            if projects is not None and projects != [self.namespace.project_id]:
                raise DG14ContractError("TaskContext project scope differs from case")
        started = perf_counter()
        retrieval_started = perf_counter()
        logical_start = len(self._call_records)
        arguments: dict[str, object] = {
            "query": f"Recall previous history evidence: {question}",
            "required_freshness": "CURRENT",
            "consistency_mode": "CANONICAL_REQUIRED",
            "limit": self._config.max_limit,
            "max_context_tokens": budget,
            "max_latency_ms": self._config.max_latency_ms,
            "reference_time": question_at,
        }
        if task_context is not None:
            arguments["task_context"] = dict(task_context)
        response = self._call(
            "retrieval", "reader-detail", "milai_memory_resolve", arguments
        )
        # Preserve a bounded, prose-free structural preimage before any adapter
        # validation can raise.  A failed response is otherwise represented only
        # by its digest in the call ledger, which is insufficient to diagnose a
        # contract mismatch such as selected/available window drift.
        self._last_resolve_contract_preimage = _resolve_contract_preimage(response)
        status = self._validate_resolve(response)
        resolved = self._resolved_evidence(response)
        retrieval_ms = (perf_counter() - retrieval_started) * 1_000
        self._stage(
            "retrieval",
            retrieval_started,
            logical_start,
            {
                "status": status,
                "candidate_count": len(resolved),
                "retrieval_trace_id": response.get("trace_id"),
                "terminal_stage": self._terminal_stage(response),
                "separate_trace_call": False,
            },
        )

        compile_started = perf_counter()
        compile_start = len(self._call_records)
        packed = self._runtime_context(
            response,
            budget,
            question=question,
            question_at=question_at,
            resolved=resolved,
        )
        provenance = self._provenance(resolved, packed.selected_sessions)
        source_ids = tuple(item.session_id for item in provenance[:3])
        self._stage(
            "context_consume",
            compile_started,
            compile_start,
            {
                "owner": "RUNTIME",
                "available_windows": packed.available_windows,
                "selected_windows": packed.selected_windows,
                "context_tokens": packed.tokens,
                "standalone_context_tokens": packed.standalone_tokens,
                "context_truncated": packed.locally_truncated,
            },
        )
        elapsed = (perf_counter() - started) * 1_000
        raw_access_trace = response.get("access_trace")
        usage: dict[str, object] = {
            "evidence_count": len(self._evidence_by_id),
            "claim_count": 0,
            "logical_mcp_calls": len(self._call_records),
            "physical_mcp_batches": self._physical_batches,
            "retrieval_logical_calls": 1,
            "trace_logical_calls": 0,
            "retrieval_ms": retrieval_ms,
            "context_compile_ms": (perf_counter() - compile_started) * 1_000,
            "semantic_context_digest": packed.semantic_context_digest,
            "reader_context_digest": packed.reader_context_digest,
            "memory_context_tokens": packed.tokens,
            "standalone_context_tokens": packed.standalone_tokens,
            "raw_retrieval_trace": list(packed.raw_retrieval_trace),
            "admitted_evidence_trace": packed.admitted_evidence_trace,
            "reader_visible_trace": packed.reader_visible_trace,
            "candidate_count": len(resolved),
            "fallback_used": response.get("fallback_used") is True,
            "retrieval_terminal_stage": self._terminal_stage(response),
            "sufficiency_decision": response.get("sufficiency_decision"),
            "retrieval_attempted_stages": (
                raw_access_trace.get("attempted_stages")
                if isinstance(raw_access_trace, Mapping)
                else None
            ),
        }
        result = DG15QueryResult(
            method_id=METHOD_ID,
            status=status,
            context=packed.text,
            source_ids=source_ids,
            selected_source_refs=packed.selected_source_refs,
            provenance=provenance,
            stage_trace=tuple(self._stage_records),
            declared_tokens=packed.tokens,
            latency_ms=elapsed,
            usage=usage,
            raw_resolve=response,
        )
        self._last_result = result
        self._state = "QUERIED"
        self._query_ms.append(elapsed)
        self._context_tokens.append(packed.tokens)
        return result

    def cleanup(self) -> Mapping[str, object]:
        if self._state not in {"RESET", "INGESTING", "FINALIZED", "QUERIED"}:
            raise DG14LifecycleError("cleanup requires an active case")
        started = perf_counter()
        logical_start = len(self._call_records)
        try:
            response = self._call(
                "cleanup_submission",
                "operator",
                "milai_namespace_cleanup_submit",
                {
                    "project_id": self.namespace.project_id,
                    "operation_id": self._operation_id(
                        "namespace-cleanup", self.namespace.project_id
                    ),
                    "reason_code": "SOURCE_REMOVED",
                    "confirmation": "CLEANUP_NAMESPACE",
                },
            )
            if response.get("cleanup_accepted") is not True:
                raise DG14TransportError("namespace cleanup was not accepted")
            evidence_count = response.get("evidence_count")
            accepted_count = response.get("accepted_count")
            failed_count = response.get("failed_count")
            if (
                not isinstance(evidence_count, int)
                or isinstance(evidence_count, bool)
                or evidence_count < 0
                or not isinstance(accepted_count, int)
                or isinstance(accepted_count, bool)
                or accepted_count < 0
                or not isinstance(failed_count, int)
                or isinstance(failed_count, bool)
                or failed_count < 0
                or accepted_count != evidence_count
                or failed_count != 0
            ):
                raise DG14ContractError(
                    "namespace cleanup did not accept the complete Evidence denominator"
                )
            registered_count = len(self._evidence_by_id)
            capture_accounting = {
                "submitted_call_count": self._capture_attempted_count,
                "returned_success_count": self._capture_returned_success_count,
                "returned_failure_count": self._capture_returned_failure_count,
                "ambiguous_success_count": self._capture_ambiguous_success_count,
                "unknown_outcome_count": self._capture_unknown_outcome_count,
                "registered_evidence_count": registered_count,
                "runtime_evidence_count": evidence_count,
                "returned_success_unregistered_count": (
                    self._capture_returned_success_count - registered_count
                ),
                "runtime_unregistered_evidence_count": (
                    evidence_count - registered_count
                ),
                "registered_denominator_matches_runtime": (
                    registered_count == evidence_count
                ),
                "attempted_outcome_denominator_exact": (
                    self._capture_returned_success_count
                    + self._capture_returned_failure_count
                    + self._capture_unknown_outcome_count
                    == self._capture_attempted_count
                ),
            }
            response = {**dict(response), "capture_accounting": capture_accounting}
            self._cleanup_receipt = response
            self._stage(
                "cleanup_submission",
                started,
                logical_start,
                {
                    "cleanup_job_id": response.get("cleanup_job_id"),
                    "evidence_count": response.get("evidence_count"),
                    "accepted_count": response.get("accepted_count"),
                    "failed_count": response.get("failed_count"),
                    "capture_accounting": capture_accounting,
                },
            )
        finally:
            if self._close_transport_on_cleanup:
                self._transport.close()
        self._state = "CLEANED"
        return response

    def cleanup_status(
        self, *, offset: int = 0, limit: int = 100
    ) -> Mapping[str, object]:
        receipt = self._cleanup_receipt
        if receipt is None:
            raise DG14LifecycleError("cleanup status requires a submitted cleanup")
        job_id = self._required_text(receipt, "cleanup_job_id")
        return self._call(
            "cleanup_status",
            "operator",
            "milai_namespace_cleanup_status",
            {"cleanup_job_id": job_id, "offset": offset, "limit": limit},
        )

    def export_context(self) -> str:
        return self._require_result().context

    def export_provenance(self) -> tuple[DG15Provenance, ...]:
        return self._require_result().provenance

    def export_stage_trace(self) -> tuple[DG14StageRecord, ...]:
        return tuple(self._stage_records)

    def export_call_records(self) -> tuple[DG15CallRecord, ...]:
        return tuple(self._call_records)

    def export_last_resolve_contract_preimage(self) -> Mapping[str, object] | None:
        value = self._last_resolve_contract_preimage
        return dict(value) if isinstance(value, Mapping) else None

    def export_governance_receipts(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "event_id": item.event.event_id,
                "evidence_id": item.evidence_id,
                "outbox_id": item.outbox_id,
                "source_ref": item.source_ref,
                "canonical_changed": False,
                **self._capture_governance_receipt(
                    item.capture_governance,
                    item.event,
                ),
            }
            for item in self._evidence_by_id.values()
        )

    def stats(self) -> DG15AdapterStats:
        return DG15AdapterStats(
            method_id=METHOD_ID,
            case_id=self._namespace.case_id if self._namespace else None,
            evidence_count=len(self._evidence_by_id),
            claim_count=0,
            query_count=len(self._query_ms),
            logical_mcp_calls=len(self._call_records),
            physical_mcp_batches=self._physical_batches,
            evidence_ingest_ms=self._ingest_ms,
            finalize_ms=self._finalize_ms,
            query_ms=tuple(self._query_ms),
            context_tokens=tuple(self._context_tokens),
        )

    def _capture_arguments(self, event: DG14HistoryEvent) -> dict[str, object]:
        subject_id = self._case_subject()
        source_type, purpose, data_classification = self._capture_policy()
        session_id = deterministic_history_session_id(
            event.case_id,
            event.session_ordinal,
            event.original_session_id,
        )
        round_ordinal = event.turn_ordinal // 2
        return {
            "operation_id": self._operation_id("capture", event.event_id),
            "source_type": source_type,
            "source_ref": self._event_source_ref(event),
            "subject_id": subject_id,
            "speaker": event.role,
            "source_context": {
                "session_id": session_id,
                "turn_id": f"{session_id}:turn:{event.turn_ordinal}",
                "turn_ordinal": event.turn_ordinal,
                "round_id": f"{session_id}:round:{round_ordinal}",
                "round_ordinal": round_ordinal,
                "previous_turn_id": (
                    f"{session_id}:turn:{event.turn_ordinal - 1}"
                    if event.turn_ordinal > 0
                    else None
                ),
                "next_turn_id": None,
            },
            "observed_at": event.observed_at,
            "content": f"{event.role}: {event.content}",
            "permission_snapshot": {
                "readable": True,
                "project_ids": [self.namespace.project_id],
                "purpose": purpose,
            },
            "confirmation": "CAPTURE",
            "retention_state": "READABLE",
            "data_classification": data_classification,
        }

    def _capture_governance(
        self,
        event: DG14HistoryEvent,
        response: Mapping[str, object],
    ) -> _CaptureGovernance:
        arguments = self._capture_arguments(event)
        source_context = arguments["source_context"]
        permission_snapshot = arguments["permission_snapshot"]
        if not isinstance(source_context, Mapping) or not isinstance(
            permission_snapshot, Mapping
        ):
            raise DG14ContractError("Evidence capture request identity is incomplete")
        summary = response.get("confirmation_summary")
        if not isinstance(summary, Mapping):
            raise DG14ContractError(
                "Evidence capture lacks Runtime confirmation summary"
            )
        content = self._required_text(arguments, "content")
        expected_summary: dict[str, object] = {
            "source_type": arguments["source_type"],
            "source_ref": arguments["source_ref"],
            "subject_id": arguments["subject_id"],
            "speaker": arguments["speaker"],
            "structured_source_context": True,
            "scope": dict(permission_snapshot),
            "retention_state": arguments["retention_state"],
            "data_classification": arguments["data_classification"],
            "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "content_chars": len(content),
        }
        if any(summary.get(key) != value for key, value in expected_summary.items()):
            raise DG14ContractError("Evidence capture Runtime confirmation drifted")
        return _CaptureGovernance(
            source_type=self._required_text(arguments, "source_type"),
            source_ref=self._required_text(arguments, "source_ref"),
            subject_id=self._required_text(arguments, "subject_id"),
            speaker=self._required_text(arguments, "speaker"),
            session_id=self._required_text(source_context, "session_id"),
            # session_ordinal is benchmark/event provenance, not a field in the
            # Runtime EvidenceSourceContext API.  Preserve it from the immutable
            # source Event for audit and ordering without sending an extra field
            # to Runtime's strict (extra="forbid") request model.
            session_ordinal=event.session_ordinal,
            turn_id=self._required_text(source_context, "turn_id"),
            turn_ordinal=self._nonnegative_int(source_context, "turn_ordinal"),
            round_id=self._required_text(source_context, "round_id"),
            round_ordinal=self._nonnegative_int(source_context, "round_ordinal"),
            previous_turn_id=(
                str(source_context["previous_turn_id"])
                if source_context.get("previous_turn_id") is not None
                else None
            ),
            next_turn_id=(
                str(source_context["next_turn_id"])
                if source_context.get("next_turn_id") is not None
                else None
            ),
            purpose=self._required_text(permission_snapshot, "purpose"),
            confirmation=self._required_text(arguments, "confirmation"),
            retention_state=self._required_text(arguments, "retention_state"),
            data_classification=self._required_text(arguments, "data_classification"),
            content_sha256=str(expected_summary["content_sha256"]),
            content_chars=len(content),
            runtime_request_id=self._required_text(response, "request_id"),
        )

    @staticmethod
    def _capture_governance_receipt(
        capture: _CaptureGovernance,
        event: DG14HistoryEvent,
    ) -> dict[str, object]:
        source_context = {
            "session_id": capture.session_id,
            "turn_id": capture.turn_id,
            "turn_ordinal": capture.turn_ordinal,
            "round_id": capture.round_id,
            "round_ordinal": capture.round_ordinal,
            "previous_turn_id": capture.previous_turn_id,
            "next_turn_id": capture.next_turn_id,
        }
        return {
            # Evaluation provenance is deliberately separate from Runtime's
            # strict EvidenceSourceContext wire contract.
            "source_event_identity": {
                "case_id": event.case_id,
                "event_id": event.event_id,
                "original_session_id": event.original_session_id,
                "session_ordinal": capture.session_ordinal,
                "turn_ordinal": event.turn_ordinal,
            },
            "capture_request": {
                "source_type": capture.source_type,
                "source_ref": capture.source_ref,
                "subject_id": capture.subject_id,
                "speaker": capture.speaker,
                "source_context": source_context,
                "permission_purpose": capture.purpose,
                "confirmation": capture.confirmation,
                "retention_state": capture.retention_state,
                "data_classification": capture.data_classification,
            },
            "confirmation_summary": {
                "runtime_request_id": capture.runtime_request_id,
                "source_type": capture.source_type,
                "source_ref": capture.source_ref,
                "subject_id": capture.subject_id,
                "speaker": capture.speaker,
                "structured_source_context": True,
                "permission_purpose": capture.purpose,
                "retention_state": capture.retention_state,
                "data_classification": capture.data_classification,
                "content_sha256": capture.content_sha256,
                "content_chars": capture.content_chars,
            },
        }

    def _validate_resolve(self, response: Mapping[str, object]) -> str:
        status = response.get("status")
        if status == "TRUNCATED" and response.get("reason") == "MCP_OUTPUT_LIMIT":
            raise DG14TransportError(
                "memory resolve exceeded the MCP wire output limit"
                + _output_limit_diagnostic_suffix(response)
            )
        if not isinstance(status, str) or status not in _STATUS_VALUES:
            raise DG14ContractError("memory resolve returned an unknown status")
        if response.get("fallback_used") is True:
            raise DG14ContractError("memory resolve used an unrequested fallback")
        degraded = response.get("degraded_components")
        if not isinstance(degraded, list):
            raise DG14ContractError("memory resolve lacks degradation accounting")
        allowed_degradation = {"context_budget"}
        if "formation_projection" in degraded:
            formation = response.get("search_trace")
            formation = (
                formation.get("formation_projection")
                if isinstance(formation, Mapping)
                else None
            )
            expected_canary_fallback = (
                self._config.formation_mode == "CANARY"
                and isinstance(formation, Mapping)
                and formation.get("mode") == "CANARY"
                and formation.get("fallback_taken") is True
                and formation.get("applied") is False
                and formation.get("raw_baseline_preserved") is True
                and formation.get("integration_reason_code")
                == "FORMATION_CANARY_EXECUTION_FAILED"
            )
            if expected_canary_fallback:
                allowed_degradation.add("formation_projection")
        unexpected = [item for item in degraded if item not in allowed_degradation]
        if unexpected:
            raise DG14ReadinessError(f"memory resolve degraded: {unexpected}")
        position = response.get("canonical_position")
        if not isinstance(position, Mapping):
            raise DG14ContractError("memory resolve lacks projection snapshot")
        evidence_watermark = position.get("evidence_watermark")
        if not isinstance(evidence_watermark, int) or evidence_watermark < 0:
            raise DG14ContractError("memory resolve lacks Evidence watermark")
        return status

    def _resolved_evidence(
        self, response: Mapping[str, object]
    ) -> tuple[_ResolvedEvidence, ...]:
        raw_items = response.get("items")
        if not isinstance(raw_items, list):
            raise DG14ContractError("memory resolve items must be a list")
        result: list[_ResolvedEvidence] = []
        seen_evidence_ids: set[str] = set()
        seen_source_refs: set[str] = set()
        for rank, raw in enumerate(raw_items, start=1):
            if not isinstance(raw, Mapping):
                raise DG14ContractError("memory resolve item must be an object")
            if (
                raw.get("kind") != "EVIDENCE_OBSERVATION"
                or raw.get("canonical") is not False
            ):
                raise DG14ContractError("DG15 Context candidate is not Raw Evidence")
            evidence_id = self._required_text(raw, "evidence_id")
            evidence = self._evidence_by_id.get(evidence_id)
            if evidence is None:
                raise DG14ContractError("cross-case Evidence candidate was accepted")
            if raw.get("source_ref") != evidence.source_ref:
                raise DG14ContractError("Evidence provenance source_ref drifted")
            if raw.get("subject_id") != self._case_subject():
                raise DG14ContractError("Evidence provenance subject_id drifted")
            if (
                evidence_id in seen_evidence_ids
                or evidence.source_ref in seen_source_refs
            ):
                raise DG14ContractError("memory resolve duplicated Evidence provenance")
            seen_evidence_ids.add(evidence_id)
            seen_source_refs.add(evidence.source_ref)
            score = raw.get("relevance_score")
            if score is not None and (
                isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(float(score))
            ):
                raise DG14ContractError("memory resolve relevance score is invalid")
            result.append(
                _ResolvedEvidence(
                    rank=rank,
                    evidence=evidence,
                    relevance_score=(
                        float(score)
                        if isinstance(score, (int, float))
                        and not isinstance(score, bool)
                        else None
                    ),
                )
            )
        return tuple(result)

    def _runtime_context(
        self,
        response: Mapping[str, object],
        budget: int,
        *,
        question: str,
        question_at: str,
        resolved: tuple[_ResolvedEvidence, ...],
    ) -> _PackedContext:
        raw = response.get("memory_context")
        if not isinstance(raw, Mapping):
            raise DG14ContractError("memory resolve lacks Runtime MemoryContext")
        if raw.get("schema_version") != "memory-context-v0.1":
            raise DG14ContractError("memory resolve returned an unknown MemoryContext")
        if raw.get("token_budget") != budget:
            raise DG14ContractError(
                "Runtime MemoryContext budget differs from protocol"
            )
        text = raw.get("text")
        if not isinstance(text, str) or not text:
            raise DG14ContractError("Runtime MemoryContext lacks rendered text")
        standalone_tokens = self._count_tokens(text)
        tokens = self._reader_tokens.memory_tokens(
            question=question,
            question_as_of=question_at,
            memory_context=text,
        )
        if tokens > budget:
            raise DG14ContextBudgetError(
                "Runtime MemoryContext exceeds the exact Reader evidence token budget"
            )
        estimated = raw.get("estimated_tokens")
        if (
            isinstance(estimated, bool)
            or not isinstance(estimated, int)
            or estimated < 0
            or estimated > budget
        ):
            raise DG14ContractError("Runtime MemoryContext token estimate is invalid")
        selected_refs = self._string_list(raw, "selected_source_turn_refs")
        selected_ids = self._string_list(raw, "selected_evidence_ids")
        if len(set(selected_ids)) != len(selected_ids) or len(
            set(selected_refs)
        ) != len(selected_refs):
            raise DG14ContractError(
                "Runtime MemoryContext selected duplicate Evidence provenance"
            )
        selected_evidence: list[_Evidence] = []
        for evidence_id in selected_ids:
            evidence = self._evidence_by_id.get(evidence_id)
            if evidence is None:
                raise DG14ContractError(
                    "Runtime MemoryContext selected uncaptured Evidence"
                )
            selected_evidence.append(evidence)
        expected_selected_refs = [item.source_ref for item in selected_evidence]
        if selected_refs != expected_selected_refs:
            raise DG14ContractError(
                "Runtime MemoryContext Evidence/source identity is not bijective"
            )
        resolved_ids = {item.evidence.evidence_id for item in resolved}
        if selected_ids and not resolved_ids.intersection(selected_ids):
            raise DG14ContractError(
                "Runtime MemoryContext is not anchored in resolved Evidence"
            )
        semantic_context_digest = self._digest(raw, "semantic_context_digest")
        reader_context_digest = self._digest(raw, "reader_context_digest")
        if reader_context_digest != hashlib.sha256(text.encode()).hexdigest():
            raise DG14ContractError("Runtime Reader Context digest is invalid")
        if any(value in text for value in (*selected_ids, *selected_refs)):
            raise DG14ContractError(
                "Runtime leaked opaque provenance into Reader prose"
            )
        raw_windows = raw.get("windows")
        if not isinstance(raw_windows, list) or any(
            not isinstance(window, Mapping) for window in raw_windows
        ):
            raise DG14ContractError("Runtime MemoryContext windows are invalid")
        selected_windows = self._nonnegative_int(raw, "selected_windows")
        available_windows = self._nonnegative_int(raw, "available_windows")
        if selected_windows > available_windows or selected_windows != len(raw_windows):
            raise DG14ContractError("Runtime MemoryContext window counts are invalid")
        window_ids: set[str] = set()
        window_evidence_ids: list[str] = []
        window_source_refs: list[str] = []
        for window in raw_windows:
            window_id = self._required_text(window, "window_id")
            if window_id in window_ids:
                raise DG14ContractError("Runtime MemoryContext duplicated a window")
            window_ids.add(window_id)
            evidence_ids = self._string_list(window, "evidence_ids")
            source_refs = self._string_list(window, "source_turn_refs")
            if (
                not evidence_ids
                or len(set(evidence_ids)) != len(evidence_ids)
                or len(set(source_refs)) != len(source_refs)
            ):
                raise DG14ContractError(
                    "Runtime MemoryContext window provenance is duplicated or empty"
                )
            if not resolved_ids.intersection(evidence_ids):
                raise DG14ContractError(
                    "Runtime MemoryContext window lacks a raw-resolved anchor"
                )
            window_evidence = [
                self._evidence_by_id.get(value) for value in evidence_ids
            ]
            if any(value is None for value in window_evidence):
                raise DG14ContractError(
                    "Runtime MemoryContext window contains uncaptured Evidence"
                )
            captured_window_evidence = [
                value for value in window_evidence if value is not None
            ]
            exact_refs = [value.source_ref for value in captured_window_evidence]
            if source_refs != exact_refs:
                raise DG14ContractError(
                    "Runtime MemoryContext window Evidence/source identity drifted"
                )
            session_id = self._required_text(window, "session_id")
            if any(
                deterministic_history_session_id(
                    value.event.case_id,
                    value.event.session_ordinal,
                    value.event.original_session_id,
                )
                != session_id
                for value in captured_window_evidence
            ):
                raise DG14ContractError(
                    "Runtime MemoryContext window crossed a source session"
                )
            expansions = window.get("expansions")
            if not isinstance(expansions, list):
                raise DG14ContractError(
                    "Runtime MemoryContext window expansions are invalid"
                )
            for expansion in expansions:
                if not isinstance(expansion, Mapping):
                    raise DG14ContractError(
                        "Runtime MemoryContext window expansion is invalid"
                    )
                source_id = self._required_text(expansion, "source_evidence_id")
                expanded_ids = self._string_list(expansion, "expanded_evidence_ids")
                if (
                    source_id not in resolved_ids
                    or source_id not in evidence_ids
                    or any(value not in evidence_ids for value in expanded_ids)
                ):
                    raise DG14ContractError(
                        "Runtime MemoryContext expansion escaped its source window"
                    )
            window_evidence_ids.extend(evidence_ids)
            window_source_refs.extend(source_refs)
        if (
            len(set(window_evidence_ids)) != len(window_evidence_ids)
            or len(set(window_source_refs)) != len(window_source_refs)
            or not set(window_evidence_ids).issubset(selected_ids)
            or not set(window_source_refs).issubset(selected_refs)
        ):
            raise DG14ContractError(
                "Runtime MemoryContext window provenance escaped selected Context"
            )
        selected_sessions = frozenset(
            (
                evidence.event.session_ordinal,
                deterministic_history_session_id(
                    evidence.event.case_id,
                    evidence.event.session_ordinal,
                    evidence.event.original_session_id,
                ),
            )
            for evidence in self._evidence_by_id.values()
            if evidence.evidence_id in selected_ids
            or evidence.source_ref in selected_refs
        )
        truncated = raw.get("context_truncated")
        if not isinstance(truncated, bool):
            raise DG14ContractError("Runtime MemoryContext lacks truncation status")
        compile_trace = raw.get("compile_trace")
        if not isinstance(compile_trace, Mapping):
            raise DG14ContractError("Runtime MemoryContext lacks compile trace")
        atomic_unit_truncation_count = self._nonnegative_int(
            compile_trace, "atomic_unit_truncation_count"
        )
        if selected_ids and atomic_unit_truncation_count != 0:
            raise DG14ContractError(
                "Runtime MemoryContext did not prove whole-unit admission"
            )
        if any(window.get("truncated") is True for window in raw_windows):
            raise DG14ContractError("Runtime MemoryContext contains a truncated unit")
        receipt = response.get("context_receipt")
        receipt_mapping: list[Mapping[str, object]] = []
        if not isinstance(receipt, Mapping):
            safe_empty_abstention = (
                receipt is None
                and response.get("status") in {"ABSENT", "ABSTAINED"}
                and response.get("items") == []
                and response.get("evidence_refs") == []
                and not selected_ids
                and not selected_refs
                and selected_windows == 0
            )
            safe_budget_infeasible_abstention = (
                receipt is None
                and response.get("status") in {"ABSENT", "ABSTAINED"}
                and response.get("context_receipt_issue_reason")
                == "EVIDENCE_CONTEXT_EMPTY"
                and raw.get("authority_class") == "CANONICAL_STATE"
                and raw.get("context_truncated") is True
                and raw.get("claim_versions") == []
                and raw.get("open_issue_ids") == []
                and raw_windows == []
                and not selected_ids
                and not selected_refs
                and selected_windows == 0
                and compile_trace.get("reader_readiness") == "BUDGET_INFEASIBLE"
                and compile_trace.get("selected_unit_ids") == []
                and compile_trace.get("selected_conditional_unit_ids") == []
            )
            if not (safe_empty_abstention or safe_budget_infeasible_abstention):
                raise DG14ContractError("Evidence MemoryContext lacks ContextReceipt")
        else:
            if receipt.get("schema_version") != "context-receipt-v0.2":
                raise DG14ContractError("Evidence ContextReceipt schema is unknown")
            if receipt.get("authority_class") not in {"EVIDENCE_ONLY", "MIXED"}:
                raise DG14ContractError(
                    "Evidence ContextReceipt authority class is invalid"
                )
            if receipt.get("canonical_mutation") is not False:
                raise DG14ContractError(
                    "Evidence ContextReceipt can mutate canonical state"
                )
            if receipt.get("persisted") is not False:
                raise DG14ContractError(
                    "Evidence ContextReceipt persistence was not declared"
                )
            if receipt.get("semantic_context_digest") != semantic_context_digest:
                raise DG14ContractError(
                    "ContextReceipt semantic digest differs from Context"
                )
            if receipt.get("reader_context_digest") != reader_context_digest:
                raise DG14ContractError(
                    "ContextReceipt Reader digest differs from Context"
                )
            receipt_ids = self._string_list(receipt, "source_evidence_ids")
            if len(set(receipt_ids)) != len(receipt_ids):
                raise DG14ContractError(
                    "ContextReceipt source Evidence identities are duplicated"
                )
            if set(receipt_ids) != set(selected_ids):
                raise DG14ContractError(
                    "ContextReceipt Evidence provenance is incomplete"
                )
            raw_mapping = receipt.get("receipt_mapping")
            if not isinstance(raw_mapping, list):
                raise DG14ContractError("ContextReceipt lacks stable alias mapping")
            receipt_mapping = [
                item for item in raw_mapping if isinstance(item, Mapping)
            ]
            aliases = [item.get("alias") for item in receipt_mapping]
            if (
                len(receipt_mapping) != len(raw_mapping)
                or any(not isinstance(alias, str) or not alias for alias in aliases)
                or len(set(aliases)) != len(aliases)
            ):
                raise DG14ContractError(
                    "ContextReceipt aliases are incomplete or duplicated"
                )
            mapped_id_list = [
                value
                for item in receipt_mapping
                for value in self._string_list(item, "evidence_ids")
            ]
            if len(set(mapped_id_list)) != len(mapped_id_list):
                raise DG14ContractError(
                    "ContextReceipt alias mapping provenance is duplicated"
                )
            if mapped_id_list != selected_ids:
                raise DG14ContractError("ContextReceipt alias mapping is not lossless")
            mapped_ref_list = [
                value
                for item in receipt_mapping
                for value in self._string_list(item, "source_turn_refs")
            ]
            if len(set(mapped_ref_list)) != len(mapped_ref_list):
                raise DG14ContractError(
                    "ContextReceipt alias source provenance is duplicated"
                )
            if mapped_ref_list != selected_refs:
                raise DG14ContractError(
                    "ContextReceipt source provenance differs from MemoryContext"
                )
            mapped_window_ids = [
                value
                for item in receipt_mapping
                if str(item.get("alias", "")).startswith("E")
                for value in self._string_list(item, "evidence_ids")
            ]
            mapped_window_refs = [
                value
                for item in receipt_mapping
                if str(item.get("alias", "")).startswith("E")
                for value in self._string_list(item, "source_turn_refs")
            ]
            if (
                mapped_window_ids != window_evidence_ids
                or mapped_window_refs != window_source_refs
            ):
                raise DG14ContractError(
                    "ContextReceipt E-alias provenance differs from Context windows"
                )
            expected_ref_by_evidence = {
                item.evidence_id: item.source_ref
                for item in self._evidence_by_id.values()
            }
            for item in receipt_mapping:
                item_ids = self._string_list(item, "evidence_ids")
                item_refs = self._string_list(item, "source_turn_refs")
                if len(set(item_ids)) != len(item_ids) or len(set(item_refs)) != len(
                    item_refs
                ):
                    raise DG14ContractError(
                        "ContextReceipt mapping provenance is duplicated"
                    )
                expected_item_refs = [
                    expected_ref_by_evidence.get(evidence_id)
                    for evidence_id in item_ids
                ]
                if (
                    any(value is None for value in expected_item_refs)
                    or item_refs != expected_item_refs
                ):
                    raise DG14ContractError(
                        "ContextReceipt Evidence/source provenance is not lossless"
                    )
        raw_trace = self._raw_retrieval_trace(resolved)
        visible_trace = self._reader_visible_trace(
            question=question,
            question_at=question_at,
            context=text,
            exact_reader_tokens=tokens,
            standalone_tokens=standalone_tokens,
            receipt_mapping=receipt_mapping,
        )
        admitted_trace: Mapping[str, object] = {
            "schema_version": "admitted-evidence-trace-v0.1",
            "selector_identity": sha256_json(
                {
                    "compiler_version": compile_trace.get("compiler_version"),
                    "reader_context_digest": reader_context_digest,
                    "selected_evidence_ids": selected_ids,
                }
            ),
            "admitted_units": [
                {
                    "evidence_id": evidence_id,
                    "source_ref": next(
                        (
                            item.source_ref
                            for item in self._evidence_by_id.values()
                            if item.evidence_id == evidence_id
                        ),
                        None,
                    ),
                }
                for evidence_id in selected_ids
            ],
            "atomic_unit_truncation_count": 0,
        }
        return _PackedContext(
            text=text,
            tokens=tokens,
            standalone_tokens=standalone_tokens,
            selected_sessions=selected_sessions,
            selected_source_refs=tuple(selected_refs),
            selected_windows=selected_windows,
            available_windows=available_windows,
            locally_truncated=truncated,
            semantic_context_digest=semantic_context_digest,
            reader_context_digest=reader_context_digest,
            raw_retrieval_trace=raw_trace,
            admitted_evidence_trace=admitted_trace,
            reader_visible_trace=visible_trace,
        )

    def _raw_retrieval_trace(
        self, resolved: tuple[_ResolvedEvidence, ...]
    ) -> tuple[Mapping[str, object], ...]:
        return tuple(
            {
                "channel": "RUNTIME_EVIDENCE_RESOLVE",
                "channel_rank": item.rank,
                "raw_score": item.relevance_score,
                "capture_governance_sha256": sha256_json(
                    self._capture_governance_receipt(
                        item.evidence.capture_governance,
                        item.evidence.event,
                    )
                ),
                "evidence_identity": {
                    "evidence_id": item.evidence.evidence_id,
                    "original_session_id": item.evidence.event.original_session_id,
                    "session_ordinal": item.evidence.event.session_ordinal,
                    "source_ref": item.evidence.source_ref,
                    "source_session_id": item.evidence.capture_governance.session_id,
                    "subject_id": item.evidence.capture_governance.subject_id,
                    "turn_id": item.evidence.capture_governance.turn_id,
                },
            }
            for item in resolved
        )

    def _reader_visible_trace(
        self,
        *,
        question: str,
        question_at: str,
        context: str,
        exact_reader_tokens: int,
        standalone_tokens: int,
        receipt_mapping: list[Mapping[str, object]],
    ) -> Mapping[str, object]:
        rendered_units: list[Mapping[str, object]] = []
        receipt_aliases = [str(mapping["alias"]) for mapping in receipt_mapping]
        header_matches = list(_READER_UNIT_HEADER.finditer(context))
        issue_ordinal = 0
        context_aliases: list[str] = []
        for match in header_matches:
            alias = match.group("alias") or match.group("issue_alias")
            if alias is None:
                issue_ordinal += 1
                alias = f"I{issue_ordinal}"
            context_aliases.append(alias)
        if context_aliases != receipt_aliases or len(set(context_aliases)) != len(
            context_aliases
        ):
            raise DG14ContractError(
                "Reader Context unit aliases differ from ContextReceipt"
            )
        previous_content_end = -1
        for index, mapping in enumerate(receipt_mapping):
            alias = mapping.get("alias")
            if not isinstance(alias, str):
                raise DG14ContractError("ContextReceipt mapping alias is invalid")
            marker_start = header_matches[index].start()
            content_start = context.find("\n", marker_start)
            if content_start < 0:
                raise DG14ContractError("Reader Context unit lacks a content boundary")
            content_start += 1
            if index + 1 < len(header_matches):
                next_header = header_matches[index + 1].start()
                content_end = (
                    next_header - 2
                    if context[max(0, next_header - 2) : next_header] == "\n\n"
                    else next_header
                )
            else:
                end_marker = context.find("\n\nMILAI_MEMORY_DATA_END", content_start)
                content_end = end_marker if end_marker >= 0 else len(context)
            if marker_start <= previous_content_end or content_end <= content_start:
                raise DG14ContractError(
                    "Reader Context unit spans are unordered or overlapping"
                )
            previous_content_end = content_end
            token_start, token_end = self._reader_tokens.unit_prompt_token_span(
                question=question,
                question_as_of=question_at,
                memory_context=context,
                context_char_start=content_start,
                context_char_end=content_end,
            )
            serialized = context[content_start:content_end]
            rendered_units.append(
                {
                    "alias": alias,
                    "evidence_ids": self._string_list(mapping, "evidence_ids"),
                    "source_turn_refs": self._string_list(mapping, "source_turn_refs"),
                    "serialized_char_offset": {
                        "start": content_start,
                        "end": content_end,
                    },
                    "serialized_utf8_byte_offset": {
                        "start": len(context[:content_start].encode()),
                        "end": len(context[:content_end].encode()),
                    },
                    "reader_prompt_token_start": token_start,
                    "reader_prompt_token_end": token_end,
                    "serialized_unit_sha256": hashlib.sha256(
                        serialized.encode()
                    ).hexdigest(),
                }
            )
        parts = context.split("\n\n")
        digest = hashlib.sha256(context.encode()).hexdigest()
        return {
            "schema_version": "reader-visible-trace-v0.1",
            "tokenizer_identity": str(self._reader_tokens.tokenizer_path),
            "tokenizer_sha256": self._reader_tokens.tokenizer_sha256,
            "chat_template_identity": str(self._reader_tokens.chat_template_path),
            "chat_template_sha256": self._reader_tokens.chat_template_sha256,
            "reader_accounting_identity": self._reader_tokens.accounting_identity,
            "accounting_mode": "OFFLINE_LOCAL_NO_READER_CALL",
            "reader_call_count": 0,
            "exact_reader_memory_tokens": exact_reader_tokens,
            "standalone_context_tokens": standalone_tokens,
            "reader_context_sha256": digest,
            "serialization_replay_sha256": hashlib.sha256(
                "\n\n".join(parts).encode()
            ).hexdigest(),
            "serialization_parts": parts,
            "rendered_units": rendered_units,
        }

    @staticmethod
    def _digest(value: Mapping[str, object], key: str) -> str:
        digest = value.get(key)
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise DG14ContractError(f"Runtime {key} is invalid")
        return digest

    def _provenance(
        self,
        resolved: tuple[_ResolvedEvidence, ...],
        selected_sessions: frozenset[tuple[int, str]],
    ) -> tuple[DG15Provenance, ...]:
        grouped: dict[tuple[int, str], list[_ResolvedEvidence]] = defaultdict(list)
        order: list[tuple[int, str]] = []
        for item in resolved:
            event = item.evidence.event
            identity = (event.session_ordinal, event.original_session_id)
            if identity not in grouped:
                order.append(identity)
            grouped[identity].append(item)
        return tuple(
            DG15Provenance(
                rank=rank,
                source_id=(
                    f"{self._source_ref_scheme()}://case/"
                    f"{quote(self.namespace.case_id, safe='')}/"
                    f"session/{identity[0]}/{quote(identity[1], safe='')}"
                ),
                session_id=identity[1],
                session_ordinal=identity[0],
                evidence_ids=tuple(
                    item.evidence.evidence_id for item in grouped[identity]
                ),
                source_refs=tuple(
                    item.evidence.source_ref for item in grouped[identity]
                ),
                relevance_score=max(
                    (
                        item.relevance_score
                        for item in grouped[identity]
                        if item.relevance_score is not None
                    ),
                    default=None,
                ),
                context_selected=(
                    identity[0],
                    deterministic_history_session_id(
                        self.namespace.case_id,
                        identity[0],
                        identity[1],
                    ),
                )
                in selected_sessions,
            )
            for rank, identity in enumerate(order, start=1)
        )

    def _call_many(
        self, stage: str, calls: Sequence[McpBatchCall]
    ) -> tuple[McpBatchOutcome, ...]:
        started = perf_counter()
        self._physical_batches += 1
        batch_sequence = self._physical_batches
        outcomes = self._transport.call_many(
            calls, max_concurrency=self._config.mcp_concurrency
        )
        elapsed = (perf_counter() - started) * 1_000
        for call, outcome in zip(calls, outcomes, strict=True):
            response = outcome.structured
            request_id = response.get("request_id") if response else None
            trace_id = response.get("trace_id") if response else None
            self._call_records.append(
                DG15CallRecord(
                    sequence=len(self._call_records) + 1,
                    physical_batch_sequence=batch_sequence,
                    stage=stage,
                    profile=call.profile,
                    tool_name=call.tool_name,
                    request_sha256=sha256_json(call.arguments),
                    response_sha256=sha256_json(response) if response else None,
                    batch_latency_ms=elapsed,
                    status=outcome.status,
                    error_code=outcome.error_code,
                    runtime_request_id=(
                        str(request_id) if isinstance(request_id, str) else None
                    ),
                    retrieval_trace_id=(
                        str(trace_id) if isinstance(trace_id, str) else None
                    ),
                )
            )
        return outcomes

    def _call(
        self,
        stage: str,
        profile: Literal["submitter", "reviewer", "reader-detail", "operator"],
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> Mapping[str, object]:
        outcome = self._call_many(stage, [McpBatchCall(profile, tool_name, arguments)])[
            0
        ]
        return self._required_success(outcome, tool_name)

    @staticmethod
    def _required_success(
        outcome: McpBatchOutcome, operation: str
    ) -> Mapping[str, object]:
        if outcome.status != "SUCCEEDED" or outcome.structured is None:
            raise DG14TransportError(f"{operation} failed: {outcome.error_code}")
        return outcome.structured

    def _stage(
        self,
        name: str,
        started: float,
        logical_start: int,
        details: Mapping[str, object],
    ) -> None:
        self._stage_records.append(
            DG14StageRecord(
                sequence=len(self._stage_records) + 1,
                stage=name,
                latency_ms=(perf_counter() - started) * 1_000,
                logical_call_start=logical_start,
                logical_call_end=len(self._call_records),
                details=dict(details),
            )
        )

    def _count_tokens(self, value: str) -> int:
        count = self._token_counter(value)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise DG14ContextBudgetError("token_counter returned an invalid value")
        return count

    def _event_source_ref(self, event: DG14HistoryEvent) -> str:
        return (
            f"{self._source_ref_scheme()}://case/"
            f"{quote(event.case_id, safe='')}/session/"
            f"{event.session_ordinal}/{quote(event.original_session_id, safe='')}/turn/"
            f"{event.turn_ordinal}?event_id={event.event_id}"
        )

    def _capture_policy(self) -> tuple[str, str, str]:
        if self._config.capture_profile == "MVP01_SYNTHETIC_WARM":
            return (
                "MVP01_SYNTHETIC_WARM_TURN",
                "MVP01_U0_WARM_RELIABILITY",
                "SYNTHETIC",
            )
        return (
            "LONGMEMEVAL_HISTORY_TURN",
            "OPENED_DEV_BENCHMARK",
            "DEIDENTIFIED",
        )

    def _source_ref_scheme(self) -> str:
        if self._config.capture_profile == "MVP01_SYNTHETIC_WARM":
            return "mvp01-warm"
        return "longmemeval"

    def _case_subject(self) -> str:
        digest = sha256_json(
            {
                "project_id": self.namespace.project_id,
                "case_id": self.namespace.case_id,
            }
        )
        prefix = (
            "mvp01-warm"
            if self._config.capture_profile == "MVP01_SYNTHETIC_WARM"
            else "dg15"
        )
        return f"{prefix}:{self.namespace.project_id}:subject:{digest[:24]}"

    @staticmethod
    def _operation_id(family: str, identity: str) -> str:
        return f"dg15-{family}-{sha256_json({'identity': identity})[:48]}"

    @staticmethod
    def _required_text(value: Mapping[str, object], key: str) -> str:
        result = value.get(key)
        if not isinstance(result, str) or not result:
            raise DG14ContractError(f"response lacks required {key}")
        return result

    @staticmethod
    def _string_list(value: Mapping[str, object], key: str) -> list[str]:
        raw = value.get(key)
        if not isinstance(raw, list) or not all(
            isinstance(item, str) and item for item in raw
        ):
            raise DG14ContractError(f"response lacks valid {key}")
        return raw

    @staticmethod
    def _nonnegative_int(value: Mapping[str, object], key: str) -> int:
        raw = value.get(key)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise DG14ContractError(f"response lacks valid {key}")
        return raw

    @staticmethod
    def _terminal_stage(response: Mapping[str, object]) -> str | None:
        trace = response.get("access_trace")
        if not isinstance(trace, Mapping):
            return None
        value = trace.get("terminal_stage")
        return str(value) if isinstance(value, str) else None

    def _require_result(self) -> DG15QueryResult:
        if self._last_result is None:
            raise DG14LifecycleError("adapter has no query result")
        return self._last_result
