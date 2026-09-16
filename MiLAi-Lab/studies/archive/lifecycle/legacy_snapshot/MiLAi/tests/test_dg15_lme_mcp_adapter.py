from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from milai.domain import EvidenceIngestRequest

from evals.dg14.contracts import (
    DG14ContractError,
    DG14HistoryEvent,
    DG14ReadinessError,
    DG14TransportError,
    deterministic_history_session_id,
)
from evals.dg15.contracts import DG15AdapterConfig
from evals.dg15.mcp_stdio import (
    McpBatchCall,
    McpBatchOutcome,
    MultiplexedStdioMcpTransport,
)
from evals.dg15.milai_mcp_adapter import DG15MilaiMcpAdapter
from evals.mvp01.u0_warm import build_synthetic_fixture


class _FakeMultiplexedTransport:
    def __init__(self) -> None:
        self.scope: dict[str, object] | None = None
        self.calls: list[tuple[int, tuple[McpBatchCall, ...]]] = []
        self.captures: list[dict[str, object]] = []
        self.closed = False
        self.derived_result: dict[str, object] | None = None
        self.selected_evidence_ids: list[str] | None = None
        self.readiness_statuses = ["READY"]
        self.resolve_overrides: dict[str, object] = {}
        self.memory_context_overrides: dict[str, object] = {}
        self.context_receipt_overrides: dict[str, object] = {}
        self.cleanup_overrides: dict[str, object] = {}
        self.receipt_source_ref_override: str | None = None

    def open_case(self, scope: Mapping[str, object]) -> None:
        self.scope = dict(scope)

    def call_many(
        self,
        calls: Sequence[McpBatchCall],
        *,
        max_concurrency: int,
    ) -> tuple[McpBatchOutcome, ...]:
        batch = tuple(calls)
        self.calls.append((max_concurrency, batch))
        outcomes: list[McpBatchOutcome] = []
        for ordinal, call in enumerate(batch):
            response: dict[str, object]
            if call.tool_name == "milai_evidence_capture":
                captured = dict(call.arguments)
                self.captures.append(captured)
                index = len(self.captures)
                response = {
                    "evidence_id": f"evidence-{index}",
                    "outbox_id": f"outbox-{index}",
                    "request_id": f"capture-request-{index}",
                    "replayed": False,
                    "confirmation_summary": {
                        "source_type": captured["source_type"],
                        "source_ref": captured["source_ref"],
                        "subject_id": captured["subject_id"],
                        "speaker": captured["speaker"],
                        "structured_source_context": True,
                        "scope": captured["permission_snapshot"],
                        "retention_state": captured["retention_state"],
                        "data_classification": captured["data_classification"],
                        "content_sha256": hashlib.sha256(
                            str(captured["content"]).encode()
                        ).hexdigest(),
                        "content_chars": len(str(captured["content"])),
                    },
                }
            elif call.tool_name == "milai_projection_readiness_wait":
                status = (
                    self.readiness_statuses.pop(0)
                    if self.readiness_statuses
                    else "READY"
                )
                response = {
                    "status": status,
                    "target_watermark": len(self.captures),
                    "barrier_wait_ms": 1.25,
                    "projection_work_started": False,
                    "request_id": "barrier-request",
                }
            elif call.tool_name == "milai_memory_resolve":
                selected_ids = self.selected_evidence_ids or [
                    f"evidence-{index}" for index in range(1, len(self.captures) + 1)
                ]
                selected = [
                    (f"evidence-{index}", capture)
                    for index, capture in enumerate(self.captures, start=1)
                    if f"evidence-{index}" in selected_ids
                ]
                derived_ids = {
                    value
                    for value in (
                        self.derived_result.get("evidence_refs", [])
                        if self.derived_result is not None
                        else []
                    )
                    if isinstance(value, str)
                }
                window_selected = [
                    value for value in selected if value[0] not in derived_ids
                ]
                context_parts = [
                    "MILAI_MEMORY_DATA_BEGIN",
                    "memory_status=HIT",
                    (
                        "candidate_kind=EVIDENCE_OBSERVATION canonical=false "
                        "authority=EVIDENCE_ONLY"
                    ),
                ]
                if self.derived_result is not None:
                    context_parts.extend(
                        [
                            "[D1 DERIVED OPERATOR RESULT / NON-CANONICAL READ-ONLY]",
                            json.dumps(
                                {
                                    key: value
                                    for key, value in self.derived_result.items()
                                    if key
                                    not in {
                                        "evidence_refs",
                                        "source_turn_refs",
                                        "operands",
                                    }
                                },
                                sort_keys=True,
                            ),
                            "[COMPLETENESS STATUS]",
                            json.dumps(self.derived_result.get("completeness")),
                        ]
                    )
                context_parts.extend(
                    f"[E{index} EVIDENCE WINDOW / NON-CANONICAL]\n{capture['content']}"
                    for index, (_evidence_id, capture) in enumerate(
                        window_selected, start=1
                    )
                )
                context_parts.append("MILAI_MEMORY_DATA_END")
                context_text = "\n\n".join(context_parts)
                reader_digest = hashlib.sha256(context_text.encode()).hexdigest()
                semantic_digest = hashlib.sha256(
                    json.dumps(
                        {
                            "derived": self.derived_result,
                            "content": [
                                value[1]["content"] for value in window_selected
                            ],
                        },
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
                receipt_mapping: list[dict[str, object]] = [
                    {
                        "alias": f"E{index}",
                        "evidence_ids": [evidence_id],
                        "source_turn_refs": [
                            self.receipt_source_ref_override
                            or str(capture["source_ref"])
                        ],
                        "claim_versions": [],
                        "issue_revisions": [],
                    }
                    for index, (evidence_id, capture) in enumerate(
                        window_selected, start=1
                    )
                ]
                if self.derived_result is not None:
                    receipt_mapping.insert(
                        0,
                        {
                            "alias": "D1",
                            "evidence_ids": self.derived_result.get(
                                "evidence_refs", []
                            ),
                            "source_turn_refs": self.derived_result.get(
                                "source_turn_refs", []
                            ),
                            "claim_versions": [],
                            "issue_revisions": [],
                        },
                    )
                response = {
                    "status": "HIT",
                    "items": [
                        {
                            "kind": "EVIDENCE_OBSERVATION",
                            "canonical": False,
                            "evidence_id": f"evidence-{index}",
                            "source_ref": capture["source_ref"],
                            "subject_id": capture["subject_id"],
                            "relevance_score": 1.0 / index,
                        }
                        for index, capture in enumerate(self.captures, start=1)
                    ],
                    "canonical_position": {
                        "canonical_outbox_sequence": len(self.captures),
                        "evidence_watermark": len(self.captures),
                        "fts_watermark": 0,
                        "vector_watermark": 0,
                    },
                    "degraded_components": [],
                    "fallback_used": False,
                    "fallback_reason": None,
                    "trace_id": "trace-1",
                    "access_trace": {"terminal_stage": "EVIDENCE_FTS"},
                    "request_id": "resolve-request",
                    "memory_context": {
                        "schema_version": "memory-context-v0.1",
                        "authority_class": "EVIDENCE_ONLY",
                        "text": context_text,
                        "semantic_context_digest": semantic_digest,
                        "reader_context_digest": reader_digest,
                        "token_budget": call.arguments["max_context_tokens"],
                        "estimated_tokens": math.ceil(
                            len(context_text.encode("utf-8")) / 3
                        ),
                        "token_counting_method": "utf8-bytes-ceil-div-3-v1",
                        "available_windows": len(window_selected),
                        "selected_windows": len(window_selected),
                        "context_truncated": False,
                        "selected_evidence_ids": [value[0] for value in selected],
                        "selected_source_turn_refs": [
                            str(value[1]["source_ref"]) for value in selected
                        ],
                        "claim_versions": [],
                        "open_issue_ids": [],
                        "windows": [
                            {
                                "window_id": f"window-{index}",
                                "session_id": capture["source_context"]["session_id"],
                                "evidence_ids": [evidence_id],
                                "source_turn_refs": [capture["source_ref"]],
                                "expansions": [],
                                "truncated": False,
                            }
                            for index, (evidence_id, capture) in enumerate(
                                window_selected, start=1
                            )
                        ],
                        "compile_trace": {
                            "owner": "RUNTIME",
                            "atomic_unit_truncation_count": 0,
                        },
                    },
                    "context_receipt": {
                        "schema_version": "context-receipt-v0.2",
                        "context_id": "context-1",
                        "authority_class": "EVIDENCE_ONLY",
                        "query_ir_digest": "a" * 64,
                        "requirement_digest": "b" * 64,
                        "semantic_context_digest": semantic_digest,
                        "reader_context_digest": reader_digest,
                        "receipt_mapping": receipt_mapping,
                        "source_evidence_ids": [value[0] for value in selected],
                        "claim_versions": [],
                        "issue_revisions": [],
                        "sufficiency_status": "COMPLETE",
                        "missing_slots": [],
                        "canonical_position": len(self.captures),
                        "projection_watermarks": {
                            "evidence_watermark": len(self.captures)
                        },
                        "issued_at": "2026-08-27T00:00:00+00:00",
                        "persisted": False,
                        "canonical_mutation": False,
                    },
                }
                if self.derived_result is not None:
                    response["derived_result"] = self.derived_result
                memory_context = cast(dict[str, object], response["memory_context"])
                memory_context.update(self.memory_context_overrides)
                context_receipt = cast(dict[str, object], response["context_receipt"])
                context_receipt.update(self.context_receipt_overrides)
                response.update(self.resolve_overrides)
            elif call.tool_name == "milai_namespace_cleanup_submit":
                response = {
                    "cleanup_job_id": "cleanup-job-1",
                    "cleanup_accepted": True,
                    "status": "ACCEPTED",
                    "evidence_count": len(self.captures),
                    "accepted_count": len(self.captures),
                    "failed_count": 0,
                    "request_id": "cleanup-request",
                }
                response.update(self.cleanup_overrides)
            else:
                raise AssertionError(f"unexpected tool {call.tool_name}")
            outcomes.append(McpBatchOutcome(ordinal, "SUCCEEDED", response, None))
        return tuple(outcomes)

    def close(self) -> None:
        self.closed = True


class _FailureBeforeSuccessTransport(_FakeMultiplexedTransport):
    """Return one failed capture followed by three committed successes."""

    def call_many(
        self,
        calls: Sequence[McpBatchCall],
        *,
        max_concurrency: int,
    ) -> tuple[McpBatchOutcome, ...]:
        if calls and all(
            call.tool_name == "milai_evidence_capture" for call in calls
        ):
            batch = tuple(calls)
            self.calls.append((max_concurrency, batch))
            outcomes: list[McpBatchOutcome] = []
            for ordinal, call in enumerate(batch):
                if ordinal == 0:
                    outcomes.append(
                        McpBatchOutcome(
                            ordinal,
                            "FAILED",
                            None,
                            "INVALID_REQUEST:source_context.extra:extra_forbidden",
                        )
                    )
                    continue
                captured = dict(call.arguments)
                self.captures.append(captured)
                index = len(self.captures)
                response = {
                    "evidence_id": f"mixed-evidence-{index}",
                    "outbox_id": f"mixed-outbox-{index}",
                    "request_id": f"mixed-request-{index}",
                    "replayed": False,
                    "confirmation_summary": {
                        "source_type": captured["source_type"],
                        "source_ref": captured["source_ref"],
                        "subject_id": captured["subject_id"],
                        "speaker": captured["speaker"],
                        "structured_source_context": True,
                        "scope": captured["permission_snapshot"],
                        "retention_state": captured["retention_state"],
                        "data_classification": captured["data_classification"],
                        "content_sha256": hashlib.sha256(
                            str(captured["content"]).encode()
                        ).hexdigest(),
                        "content_chars": len(str(captured["content"])),
                    },
                }
                outcomes.append(
                    McpBatchOutcome(ordinal, "SUCCEEDED", response, None)
                )
            return tuple(outcomes)
        return super().call_many(calls, max_concurrency=max_concurrency)


class _UnknownEnvelopeTransport(_FakeMultiplexedTransport):
    def call_many(
        self,
        calls: Sequence[McpBatchCall],
        *,
        max_concurrency: int,
    ) -> tuple[McpBatchOutcome, ...]:
        if calls and all(
            call.tool_name == "milai_evidence_capture" for call in calls
        ):
            raise TimeoutError("synthetic lost MCP envelope")
        return super().call_many(calls, max_concurrency=max_concurrency)


def _config() -> DG15AdapterConfig:
    return DG15AdapterConfig(
        base_url="http://127.0.0.1:18080",
        executable=Path("/synthetic/milai-mcp"),
        profile_tokens={
            "submitter": "s" * 32,
            "reviewer": "r" * 32,
            "reader-detail": "d" * 32,
            "operator": "o" * 32,
        },
        mcp_concurrency=4,
    )


def _event(
    session_ordinal: int,
    session_id: str,
    turn_ordinal: int,
    role: str,
    content: str,
) -> DG14HistoryEvent:
    return DG14HistoryEvent.from_mapping(
        {
            "case_id": "case-opened-1",
            "session_ordinal": session_ordinal,
            "original_session_id": session_id,
            "turn_ordinal": turn_ordinal,
            "role": role,
            "content": content,
            "observed_at": "2026-08-20T10:00:00Z",
        }
    )


def _budget_infeasible_resolve_overrides(
    transport: _FakeMultiplexedTransport,
    *,
    status: str,
    budget: int = 512,
) -> dict[str, object]:
    context_text = (
        "MILAI_MEMORY_DATA_BEGIN\n"
        f"memory_status={status}\n"
        "reader_readiness=BUDGET_INFEASIBLE\n"
        "MILAI_MEMORY_DATA_END"
    )
    reader_digest = hashlib.sha256(context_text.encode()).hexdigest()
    items = [
        {
            "kind": "EVIDENCE_OBSERVATION",
            "canonical": False,
            "evidence_id": f"evidence-{index}",
            "source_ref": capture["source_ref"],
            "subject_id": capture["subject_id"],
            "relevance_score": 1.0 / index,
        }
        for index, capture in enumerate(transport.captures, start=1)
    ]
    return {
        "status": status,
        "items": items,
        "evidence_refs": [item["evidence_id"] for item in items],
        "abstention_reason": "READER_EVIDENCE_BUDGET_INFEASIBLE",
        "context_candidate_kinds": ["EVIDENCE_OBSERVATION"],
        "context_receipt": None,
        "context_receipt_issue_reason": "EVIDENCE_CONTEXT_EMPTY",
        "memory_context": {
            "schema_version": "memory-context-v0.1",
            "authority_class": "CANONICAL_STATE",
            "text": context_text,
            "semantic_context_digest": "a" * 64,
            "reader_context_digest": reader_digest,
            "token_budget": budget,
            "estimated_tokens": len(context_text.split()),
            "token_counting_method": "utf8-bytes-ceil-div-3-v1",
            "available_windows": len(items),
            "selected_windows": 0,
            "context_truncated": True,
            "selected_evidence_ids": [],
            "selected_source_turn_refs": [],
            "claim_versions": [],
            "open_issue_ids": [],
            "windows": [],
            "compile_trace": {
                "compiler_version": "progressive-v0.1",
                "reader_readiness": "BUDGET_INFEASIBLE",
                "selected_unit_ids": [],
                "selected_conditional_unit_ids": [],
                "atomic_unit_truncation_count": 0,
                "long_turn_split_count": 0,
                "rank_first_prefix_violation_count": 0,
                "whole_unit_admission": True,
                "hidden_model_calls": 0,
                "canonical_mutation": False,
            },
        },
    }


def test_dg15_readiness_deadline_uses_public_bounded_wait_slices() -> None:
    transport = _FakeMultiplexedTransport()
    transport.readiness_statuses = ["PROJECTION_READINESS_TIMEOUT", "READY"]
    config = replace(_config(), barrier_timeout_ms=60_000)
    adapter = DG15MilaiMcpAdapter(
        config,
        token_counter=lambda text: max(1, math.ceil(len(text.encode()) / 3)),
        transport=cast(MultiplexedStdioMcpTransport, transport),
        close_transport_on_cleanup=False,
    )
    adapter.reset("run-sliced-barrier", "case-opened-1")
    adapter.ingest(_event(0, "session-a", 0, "user", "Remember value 47."))

    readiness = adapter.finalize()
    wait_calls = [
        call
        for _concurrency, batch in transport.calls
        for call in batch
        if call.tool_name == "milai_projection_readiness_wait"
    ]

    assert readiness["status"] == "READY"
    assert len(wait_calls) == 2
    assert [call.arguments["timeout_ms"] for call in wait_calls] == [30_000, 30_000]


def test_dg15_adapter_batches_raw_evidence_and_never_creates_canonical_truth() -> None:
    transport = _FakeMultiplexedTransport()
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset("dg15-test-run", "case-opened-1")
    adapter.ingest_many(
        [
            _event(0, "duplicate-session", 0, "user", "What is the cobalt code?"),
            _event(0, "duplicate-session", 1, "assistant", "The code is 47."),
            _event(1, "duplicate-session", 0, "user", "What is the amber code?"),
            _event(1, "duplicate-session", 1, "assistant", "The code is 19."),
        ]
    )
    barrier = adapter.finalize()

    assert barrier["status"] == "READY"
    assert len(transport.calls[0][1]) == 4
    assert transport.calls[0][0] == 4
    assert all(
        call.tool_name == "milai_evidence_capture" for call in transport.calls[0][1]
    )
    assert all("answer" not in capture for capture in transport.captures)
    assert all("question" not in capture for capture in transport.captures)
    assert all(
        capture["source_type"] == "LONGMEMEVAL_HISTORY_TURN"
        and capture["data_classification"] == "DEIDENTIFIED"
        and capture["permission_snapshot"]["purpose"] == "OPENED_DEV_BENCHMARK"
        and str(capture["source_ref"]).startswith("longmemeval://case/")
        for capture in transport.captures
    )
    assert [
        capture["source_context"]["round_ordinal"]  # type: ignore[index]
        for capture in transport.captures
    ] == [0, 0, 0, 0]
    first_session_id = deterministic_history_session_id(
        "case-opened-1", 0, "duplicate-session"
    )
    second_session_id = deterministic_history_session_id(
        "case-opened-1", 1, "duplicate-session"
    )
    assert transport.captures[1]["source_context"] == {  # type: ignore[comparison-overlap]
        "session_id": first_session_id,
        "turn_id": f"{first_session_id}:turn:1",
        "turn_ordinal": 1,
        "round_id": f"{first_session_id}:round:0",
        "round_ordinal": 0,
        "previous_turn_id": f"{first_session_id}:turn:0",
        "next_turn_id": None,
    }
    assert transport.captures[2]["source_context"]["session_id"] == second_session_id
    assert first_session_id != second_session_id
    assert all(
        capture["source_context"]["session_id"] != capture["subject_id"]
        for capture in transport.captures
    )
    assert adapter.stats().claim_count == 0
    assert adapter.stats().physical_mcp_batches == 2
    receipts = adapter.export_governance_receipts()
    assert len(receipts) == 4
    assert all(receipt["canonical_changed"] is False for receipt in receipts)
    barrier_call = transport.calls[1][1][0]
    assert barrier_call.arguments["target_outbox_ids"] == [
        "outbox-1",
        "outbox-2",
        "outbox-3",
        "outbox-4",
    ]
    assert barrier_call.arguments["required_projections"] == ["evidence"]


@pytest.mark.parametrize(
    ("capture_profile", "expected_source_type", "expected_classification"),
    (
        (
            "MVP01_SYNTHETIC_WARM",
            "MVP01_SYNTHETIC_WARM_TURN",
            "SYNTHETIC",
        ),
        (
            "LONGMEMEVAL_DEIDENTIFIED",
            "LONGMEMEVAL_HISTORY_TURN",
            "DEIDENTIFIED",
        ),
    ),
)
def test_all_fixture_capture_payloads_match_runtime_strict_evidence_contract(
    capture_profile: str,
    expected_source_type: str,
    expected_classification: str,
) -> None:
    transport = _FakeMultiplexedTransport()
    adapter = DG15MilaiMcpAdapter(
        replace(_config(), capture_profile=capture_profile),  # type: ignore[arg-type]
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    fixture = build_synthetic_fixture()
    adapter.reset("mvp01-capture-contract-probe", fixture.case_id)
    adapter.ingest_many(fixture.history_events)

    assert len(transport.captures) == len(fixture.history_events) == 20
    for event, capture in zip(
        fixture.history_events, transport.captures, strict=True
    ):
        source_context = cast(dict[str, object], capture["source_context"])
        assert set(source_context) == {
            "session_id",
            "turn_id",
            "turn_ordinal",
            "round_id",
            "round_ordinal",
            "previous_turn_id",
            "next_turn_id",
        }
        runtime_payload = {
            key: value
            for key, value in capture.items()
            if key not in {"operation_id", "confirmation"}
        }
        validated = EvidenceIngestRequest.model_validate(runtime_payload)
        assert validated.source_type == expected_source_type
        assert validated.data_classification == expected_classification
        assert validated.source_context is not None
        assert validated.source_context.session_id == source_context["session_id"]

    governance = adapter.export_governance_receipts()
    assert len(governance) == 20
    for event, receipt in zip(fixture.history_events, governance, strict=True):
        capture_request = cast(dict[str, object], receipt["capture_request"])
        audited_context = cast(dict[str, object], capture_request["source_context"])
        assert "session_ordinal" not in audited_context
        source_event_identity = cast(
            dict[str, object], receipt["source_event_identity"]
        )
        assert source_event_identity == {
            "case_id": event.case_id,
            "event_id": event.event_id,
            "original_session_id": event.original_session_id,
            "session_ordinal": event.session_ordinal,
            "turn_ordinal": event.turn_ordinal,
        }


def test_ingest_drains_mixed_wave_and_accounts_for_successes_after_failure() -> None:
    transport = _FailureBeforeSuccessTransport()
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset("dg15-mixed-wave", "case-opened-1")
    events = [
        _event(ordinal, f"session-{ordinal}", 0, "user", f"fact {ordinal}")
        for ordinal in range(4)
    ]

    with pytest.raises(
        DG14TransportError,
        match=(
            r"returned_success=3, registered=3, failed=1, ambiguous=0, "
            r"codes=INVALID_REQUEST:source_context.extra:extra_forbidden"
        ),
    ):
        adapter.ingest_many(events)

    governance = adapter.export_governance_receipts()
    assert len(governance) == 3
    assert [
        cast(dict[str, object], row["source_event_identity"])["session_ordinal"]
        for row in governance
    ] == [1, 2, 3]
    ingest_records = [
        record
        for record in adapter.export_call_records()
        if record.tool_name == "milai_evidence_capture"
    ]
    assert [record.status for record in ingest_records] == [
        "FAILED",
        "SUCCEEDED",
        "SUCCEEDED",
        "SUCCEEDED",
    ]
    assert all(record.sequence <= 4 for record in ingest_records)

    cleanup = adapter.cleanup()
    accounting = cast(dict[str, object], cleanup["capture_accounting"])
    assert accounting == {
        "submitted_call_count": 4,
        "returned_success_count": 3,
        "returned_failure_count": 1,
        "ambiguous_success_count": 0,
        "unknown_outcome_count": 0,
        "registered_evidence_count": 3,
        "runtime_evidence_count": 3,
        "returned_success_unregistered_count": 0,
        "runtime_unregistered_evidence_count": 0,
        "registered_denominator_matches_runtime": True,
        "attempted_outcome_denominator_exact": True,
    }


def test_lost_capture_envelope_is_sealed_as_unknown_without_retry() -> None:
    transport = _UnknownEnvelopeTransport()
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset("dg15-unknown-envelope", "case-opened-1")

    with pytest.raises(
        DG14TransportError,
        match=r"attempted=4, returned=0, unknown=4, error_type=TimeoutError",
    ):
        adapter.ingest_many(
            [
                _event(ordinal, f"session-{ordinal}", 0, "user", f"fact {ordinal}")
                for ordinal in range(4)
            ]
        )

    assert not [
        record
        for record in adapter.export_call_records()
        if record.tool_name == "milai_evidence_capture"
    ]
    cleanup = adapter.cleanup()
    accounting = cast(dict[str, object], cleanup["capture_accounting"])
    assert accounting["submitted_call_count"] == 4
    assert accounting["returned_success_count"] == 0
    assert accounting["returned_failure_count"] == 0
    assert accounting["unknown_outcome_count"] == 4
    assert accounting["runtime_evidence_count"] == 0
    assert accounting["attempted_outcome_denominator_exact"] is True


def test_dg15_synthetic_warm_capture_profile_is_honest_and_runtime_admissible() -> None:
    transport = _FakeMultiplexedTransport()
    adapter = DG15MilaiMcpAdapter(
        replace(_config(), capture_profile="MVP01_SYNTHETIC_WARM"),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset("mvp01-warm-run", "case-opened-1")
    adapter.ingest_many(
        [_event(0, "synthetic-session", 0, "user", "Synthetic memory value 47.")]
    )

    capture = transport.captures[0]
    assert capture["source_type"] == "MVP01_SYNTHETIC_WARM_TURN"
    assert capture["data_classification"] == "SYNTHETIC"
    assert capture["permission_snapshot"]["purpose"] == ("MVP01_U0_WARM_RELIABILITY")
    assert str(capture["source_ref"]).startswith("mvp01-warm://case/")
    assert str(capture["subject_id"]).startswith("mvp01-warm:")


def test_dg15_single_concurrency_envelopes_are_session_and_role_invariant() -> None:
    batch_shapes: list[list[int]] = []
    for events in (
        [
            _event(0, "session-alpha", 0, "user", "Alpha"),
            _event(1, "session-beta", 0, "assistant", "Beta"),
            _event(1, "session-beta", 1, "user", "Gamma"),
        ],
        [
            _event(0, "renamed-beta", 0, "user", "Paraphrased beta"),
            _event(0, "renamed-beta", 1, "assistant", "Paraphrased gamma"),
            _event(1, "renamed-alpha", 0, "assistant", "Paraphrased alpha"),
        ],
    ):
        transport = _FakeMultiplexedTransport()
        adapter = DG15MilaiMcpAdapter(
            replace(_config(), mcp_concurrency=1),
            token_counter=lambda text: len(text.split()),
            transport=cast(MultiplexedStdioMcpTransport, transport),
        )
        adapter.reset("dg15-bounded-envelope-run", "case-opened-1")
        adapter.ingest_many(events)
        batch_shapes.append([len(batch) for _concurrency, batch in transport.calls])

    assert batch_shapes == [[1, 1, 1], [1, 1, 1]]


def test_dg15_adapter_can_freeze_all_retrieval_projection_watermarks() -> None:
    transport = _FakeMultiplexedTransport()
    adapter = DG15MilaiMcpAdapter(
        replace(
            _config(),
            barrier_projections=("evidence", "fts", "vector"),
        ),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset("dg17-q1r-readiness", "case-opened-1")
    adapter.ingest_many([_event(0, "session-a", 0, "user", "Stable evidence")])

    adapter.finalize()

    barrier_call = transport.calls[1][1][0]
    assert barrier_call.arguments["required_projections"] == [
        "evidence",
        "fts",
        "vector",
    ]
    assert barrier_call.arguments["expected_versions"] == {
        "evidence": "evidence-search-v1",
        "fts": "canonical-fts-v1",
        "vector": "canonical-vector-v1",
    }


def test_dg15_adapter_maps_provenance_and_compiles_typed_evidence_context() -> None:
    transport = _FakeMultiplexedTransport()
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset("dg15-test-run", "case-opened-1")
    adapter.ingest_many(
        [
            _event(0, "session-a", 0, "user", "What is the cobalt code?"),
            _event(0, "session-a", 1, "assistant", "The cobalt code is 47."),
            _event(1, "session-b", 0, "user", "What is the amber code?"),
            _event(1, "session-b", 1, "assistant", "The amber code is 19."),
        ]
    )
    adapter.finalize()

    result = adapter.query(
        "What were the cobalt and amber codes?",
        "2026-08-21T10:00:00Z",
        512,
    )

    assert result.method_id == "DG15-MILAI-MCP"
    assert result.source_ids == ("session-a", "session-b")
    assert [item.session_ordinal for item in result.provenance] == [0, 1]
    assert all(
        item.candidate_kind == "EVIDENCE_OBSERVATION" for item in result.provenance
    )
    assert all(item.canonical is False for item in result.provenance)
    assert "candidate_kind=EVIDENCE_OBSERVATION canonical=false" in result.context
    assert "The cobalt code is 47" in result.context
    assert "The amber code is 19" in result.context
    assert result.declared_tokens <= 512
    assert result.usage["trace_logical_calls"] == 0
    assert [record.tool_name for record in adapter.export_call_records()].count(
        "milai_memory_resolve"
    ) == 1
    resolve_call = next(
        call
        for _concurrency, batch in transport.calls
        for call in batch
        if call.tool_name == "milai_memory_resolve"
    )
    assert resolve_call.arguments["reference_time"] == "2026-08-21T10:00:00Z"
    assert resolve_call.arguments["max_context_tokens"] == 512
    assert resolve_call.arguments["max_latency_ms"] == 500
    assert any(record.stage == "context_consume" for record in result.stage_trace)
    assert not hasattr(adapter, "_windows")
    assert not hasattr(adapter, "_compile_context")

    cleanup = adapter.cleanup()
    assert cleanup["status"] == "ACCEPTED"
    assert transport.closed is True
    cleanup_calls = [
        call
        for _concurrency, batch in transport.calls
        for call in batch
        if call.tool_name == "milai_namespace_cleanup_submit"
    ]
    assert len(cleanup_calls) == 1


def test_dg15_canary_accepts_only_proven_raw_formation_fallback() -> None:
    trace = {
        "mode": "CANARY",
        "fallback_taken": True,
        "applied": False,
        "raw_baseline_preserved": True,
        "integration_reason_code": "FORMATION_CANARY_EXECUTION_FAILED",
    }
    transport = _FakeMultiplexedTransport()
    transport.resolve_overrides = {
        "degraded_components": ["formation_projection"],
        "search_trace": {"formation_projection": trace},
    }
    adapter = DG15MilaiMcpAdapter(
        replace(_config(), formation_mode="CANARY"),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset("dg15-canary-fallback", "case-opened-1")
    adapter.ingest_many([_event(0, "session-a", 0, "user", "Remember value 47.")])
    adapter.finalize()

    result = adapter.query("What was the value?", "2026-08-21T10:00:00Z", 512)

    assert result.status == "HIT"

    off_transport = _FakeMultiplexedTransport()
    off_transport.resolve_overrides = dict(transport.resolve_overrides)
    off_adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, off_transport),
    )
    off_adapter.reset("dg15-off-fallback", "case-opened-1")
    off_adapter.ingest_many([_event(0, "session-a", 0, "user", "Remember value 47.")])
    off_adapter.finalize()
    with pytest.raises(DG14ReadinessError, match="formation_projection"):
        off_adapter.query("What was the value?", "2026-08-21T10:00:00Z", 512)


def test_dg15_empty_abstention_needs_no_evidence_receipt() -> None:
    transport = _FakeMultiplexedTransport()
    context_text = (
        "MILAI_MEMORY_DATA_BEGIN\nmemory_status=ABSTAINED\nMILAI_MEMORY_DATA_END"
    )
    reader_digest = hashlib.sha256(context_text.encode()).hexdigest()
    transport.resolve_overrides = {
        "status": "ABSTAINED",
        "items": [],
        "evidence_refs": [],
        "context_receipt": None,
        "memory_context": {
            "schema_version": "memory-context-v0.1",
            "authority_class": "EVIDENCE_ONLY",
            "text": context_text,
            "semantic_context_digest": "a" * 64,
            "reader_context_digest": reader_digest,
            "token_budget": 512,
            "estimated_tokens": 24,
            "token_counting_method": "utf8-bytes-ceil-div-3-v1",
            "available_windows": 0,
            "selected_windows": 0,
            "context_truncated": False,
            "selected_evidence_ids": [],
            "selected_source_turn_refs": [],
            "claim_versions": [],
            "open_issue_ids": [],
            "windows": [],
            "compile_trace": {
                "owner": "RUNTIME",
                "atomic_unit_truncation_count": 0,
            },
        },
    }
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset("dg15-empty-abstention", "case-opened-1")
    adapter.ingest_many([_event(0, "session-a", 0, "user", "Unrelated memory.")])
    adapter.finalize()

    result = adapter.query("What is missing?", "2026-08-21T10:00:00Z", 512)

    assert result.status == "ABSTAINED"
    assert result.provenance == ()
    assert result.selected_source_refs == ()


def test_dg15_budget_infeasible_abstention_retains_raw_candidate_trace() -> None:
    transport = _FakeMultiplexedTransport()
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset("dg15-budget-infeasible-one", "case-opened-1")
    adapter.ingest_many([_event(0, "session-a", 0, "user", "Unrelated memory.")])
    adapter.finalize()
    transport.resolve_overrides = _budget_infeasible_resolve_overrides(
        transport, status="ABSTAINED"
    )

    result = adapter.query("What is missing?", "2026-08-21T10:00:00Z", 512)

    assert result.status == "ABSTAINED"
    assert len(result.provenance) == 1
    assert result.provenance[0].context_selected is False
    assert result.selected_source_refs == ()
    assert result.usage["raw_retrieval_trace"]
    assert result.usage["reader_visible_trace"]["reader_call_count"] == 0


def test_dg15_budget_infeasible_absence_can_retain_multiple_raw_sessions() -> None:
    transport = _FakeMultiplexedTransport()
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset("dg15-budget-infeasible-multi", "case-opened-1")
    adapter.ingest_many(
        [
            _event(0, "session-a", 0, "user", "First unrelated memory."),
            _event(1, "session-b", 0, "assistant", "Second unrelated memory."),
        ]
    )
    adapter.finalize()
    transport.resolve_overrides = _budget_infeasible_resolve_overrides(
        transport, status="ABSENT"
    )

    result = adapter.query("What is absent?", "2026-08-21T10:00:00Z", 512)

    assert result.status == "ABSENT"
    assert len(result.provenance) == 2
    assert all(item.context_selected is False for item in result.provenance)
    assert result.selected_source_refs == ()
    assert len(result.usage["raw_retrieval_trace"]) == 2


@pytest.mark.parametrize(
    "mutation",
    ("receipt_reason", "reader_readiness", "selected_window"),
)
def test_dg15_budget_infeasible_receipt_exception_fails_closed_on_mutation(
    mutation: str,
) -> None:
    transport = _FakeMultiplexedTransport()
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset(f"dg15-budget-infeasible-mutation-{mutation}", "case-opened-1")
    adapter.ingest_many([_event(0, "session-a", 0, "user", "Unrelated memory.")])
    adapter.finalize()
    overrides = _budget_infeasible_resolve_overrides(transport, status="ABSTAINED")
    context = cast(dict[str, object], overrides["memory_context"])
    compile_trace = cast(dict[str, object], context["compile_trace"])
    if mutation == "receipt_reason":
        overrides["context_receipt_issue_reason"] = "CANONICAL_UNAVAILABLE"
    elif mutation == "reader_readiness":
        compile_trace["reader_readiness"] = "READY"
    else:
        context["selected_windows"] = 1
        context["windows"] = [{"truncated": False}]
    transport.resolve_overrides = overrides

    with pytest.raises(
        DG14ContractError, match="lacks ContextReceipt|lacks required window_id"
    ):
        adapter.query("What is missing?", "2026-08-21T10:00:00Z", 512)


def test_dg15_evidence_context_still_requires_receipt() -> None:
    transport = _FakeMultiplexedTransport()
    transport.resolve_overrides = {"context_receipt": None}
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset("dg15-missing-receipt", "case-opened-1")
    adapter.ingest_many([_event(0, "session-a", 0, "user", "Remember value 47.")])
    adapter.finalize()

    with pytest.raises(DG14ContractError, match="lacks ContextReceipt"):
        adapter.query("What was the value?", "2026-08-21T10:00:00Z", 512)


def test_dg15_reader_trace_rejects_receipt_alias_absent_from_context() -> None:
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, _FakeMultiplexedTransport()),
    )

    with pytest.raises(DG14ContractError, match="aliases differ"):
        adapter._reader_visible_trace(
            question="What was the value?",
            question_at="2026-08-21T10:00:00Z",
            context=(
                "MILAI_MEMORY_DATA_BEGIN\n\n"
                "[E1 EVIDENCE WINDOW / NON-CANONICAL]\nuser: value 47\n\n"
                "MILAI_MEMORY_DATA_END"
            ),
            exact_reader_tokens=10,
            standalone_tokens=10,
            receipt_mapping=[
                {
                    "alias": "E2",
                    "evidence_ids": ["evidence-1"],
                    "source_turn_refs": ["memory://turn/1"],
                }
            ],
        )


def test_dg15_reader_trace_rejects_duplicate_alias_in_context() -> None:
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, _FakeMultiplexedTransport()),
    )
    duplicate = "[E1 EVIDENCE WINDOW / NON-CANONICAL]\nuser: value 47"

    with pytest.raises(DG14ContractError, match="aliases differ"):
        adapter._reader_visible_trace(
            question="What was the value?",
            question_at="2026-08-21T10:00:00Z",
            context=(
                f"MILAI_MEMORY_DATA_BEGIN\n\n{duplicate}\n\n{duplicate}\n\n"
                "MILAI_MEMORY_DATA_END"
            ),
            exact_reader_tokens=10,
            standalone_tokens=10,
            receipt_mapping=[
                {
                    "alias": "E1",
                    "evidence_ids": ["evidence-1"],
                    "source_turn_refs": ["memory://turn/1"],
                }
            ],
        )


def test_dg15_reader_trace_ignores_bracketed_evidence_body_lines() -> None:
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, _FakeMultiplexedTransport()),
    )
    context = (
        "MILAI_MEMORY_DATA_BEGIN\n\n"
        "[E1 EVIDENCE WINDOW / NON-CANONICAL]\n"
        "user: literal notes follow\n[A1 note]\n[E1 incidental text]\n\n"
        "MILAI_MEMORY_DATA_END"
    )

    trace = adapter._reader_visible_trace(
        question="What was the value?",
        question_at="2026-08-21T10:00:00Z",
        context=context,
        exact_reader_tokens=10,
        standalone_tokens=10,
        receipt_mapping=[
            {
                "alias": "E1",
                "evidence_ids": ["evidence-1"],
                "source_turn_refs": ["memory://turn/1"],
            }
        ],
    )

    assert (
        trace["reader_context_sha256"] == hashlib.sha256(context.encode()).hexdigest()
    )


@pytest.mark.parametrize(
    "header", ("[I1 OPEN ISSUE / SAFETY]", "[OPEN ISSUE / SAFETY]")
)
def test_dg15_reader_trace_maps_numbered_and_legacy_open_issue_header(
    header: str,
) -> None:
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, _FakeMultiplexedTransport()),
    )
    context = (
        "MILAI_MEMORY_DATA_BEGIN\n\n"
        f"{header}\nGoverned memory is contested.\n\n"
        "MILAI_MEMORY_DATA_END"
    )

    trace = adapter._reader_visible_trace(
        question="Which value is safe?",
        question_at="2026-08-21T10:00:00Z",
        context=context,
        exact_reader_tokens=10,
        standalone_tokens=10,
        receipt_mapping=[
            {
                "alias": "I1",
                "evidence_ids": [],
                "source_turn_refs": [],
                "issue_revisions": [{"issue_id": "issue-alpha", "revision": None}],
            }
        ],
    )

    rendered = trace["rendered_units"]
    assert isinstance(rendered, list)
    assert rendered[0]["alias"] == "I1"


def test_dg15_context_receipt_rejects_wrong_source_ref() -> None:
    transport = _FakeMultiplexedTransport()
    transport.receipt_source_ref_override = "memory://wrong-turn"
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset("dg15-wrong-receipt-ref", "case-opened-1")
    adapter.ingest_many([_event(0, "session-a", 0, "user", "Remember value 47.")])
    adapter.finalize()

    with pytest.raises(DG14ContractError, match="source provenance differs"):
        adapter.query("What was the value?", "2026-08-21T10:00:00Z", 512)


@pytest.mark.parametrize("subject_id", (None, "mvp01-warm:wrong-subject"))
def test_dg15_resolve_rejects_missing_or_wrong_runtime_subject(
    subject_id: object,
) -> None:
    transport = _FakeMultiplexedTransport()
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset("dg15-wrong-runtime-subject", "case-opened-1")
    adapter.ingest_many([_event(0, "session-a", 0, "user", "Remember value 47.")])
    adapter.finalize()
    transport.resolve_overrides = {
        "items": [
            {
                "kind": "EVIDENCE_OBSERVATION",
                "canonical": False,
                "evidence_id": "evidence-1",
                "source_ref": transport.captures[0]["source_ref"],
                "subject_id": subject_id,
                "relevance_score": 1.0,
            }
        ]
    }

    with pytest.raises(DG14ContractError, match="subject_id drifted"):
        adapter.query("What was the value?", "2026-08-21T10:00:00Z", 512)


def test_dg15_context_rejects_unanchored_selected_window() -> None:
    transport = _FakeMultiplexedTransport()
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset("dg15-window-raw-causality", "case-opened-1")
    adapter.ingest_many(
        [
            _event(0, "session-a", 0, "user", "Remember value 47."),
            _event(1, "session-b", 0, "user", "The target value is 19."),
        ]
    )
    adapter.finalize()
    transport.selected_evidence_ids = ["evidence-1", "evidence-2"]
    transport.resolve_overrides = {
        "items": [
            {
                "kind": "EVIDENCE_OBSERVATION",
                "canonical": False,
                "evidence_id": "evidence-1",
                "source_ref": transport.captures[0]["source_ref"],
                "subject_id": transport.captures[0]["subject_id"],
                "relevance_score": 1.0,
            }
        ]
    }

    with pytest.raises(DG14ContractError, match="lacks a raw-resolved anchor"):
        adapter.query("What was the target value?", "2026-08-21T10:00:00Z", 512)


@pytest.mark.parametrize("mutation", ("receipt_ids", "mapping_ids"))
def test_dg15_context_receipt_rejects_duplicate_provenance(mutation: str) -> None:
    transport = _FakeMultiplexedTransport()
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset(f"dg15-duplicate-receipt-{mutation}", "case-opened-1")
    adapter.ingest_many([_event(0, "session-a", 0, "user", "Remember value 47.")])
    adapter.finalize()
    source_ref = str(transport.captures[0]["source_ref"])
    if mutation == "receipt_ids":
        transport.context_receipt_overrides = {
            "source_evidence_ids": ["evidence-1", "evidence-1"]
        }
    else:
        transport.context_receipt_overrides = {
            "receipt_mapping": [
                {
                    "alias": "E1",
                    "evidence_ids": ["evidence-1", "evidence-1"],
                    "source_turn_refs": [source_ref, source_ref],
                    "claim_versions": [],
                    "issue_revisions": [],
                }
            ]
        }

    with pytest.raises(DG14ContractError, match="duplicated"):
        adapter.query("What was the value?", "2026-08-21T10:00:00Z", 512)


def test_dg15_context_rejects_uncaptured_selected_evidence() -> None:
    transport = _FakeMultiplexedTransport()
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset("dg15-unknown-selected-evidence", "case-opened-1")
    adapter.ingest_many([_event(0, "session-a", 0, "user", "Remember value 47.")])
    adapter.finalize()
    source_ref = str(transport.captures[0]["source_ref"])
    session_id = cast(Mapping[str, object], transport.captures[0]["source_context"])[
        "session_id"
    ]
    transport.memory_context_overrides = {
        "selected_evidence_ids": ["unknown-evidence"],
        "selected_source_turn_refs": [source_ref],
        "selected_windows": 1,
        "windows": [
            {
                "window_id": "window-unknown",
                "session_id": session_id,
                "evidence_ids": ["unknown-evidence"],
                "source_turn_refs": [source_ref],
                "expansions": [],
                "truncated": False,
            }
        ],
    }

    with pytest.raises(DG14ContractError, match="uncaptured Evidence"):
        adapter.query("What was the value?", "2026-08-21T10:00:00Z", 512)


def test_dg15_context_rejects_selected_window_count_drift() -> None:
    transport = _FakeMultiplexedTransport()
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset("dg15-selected-window-count-drift", "case-opened-1")
    adapter.ingest_many([_event(0, "session-a", 0, "user", "Remember value 47.")])
    adapter.finalize()
    transport.memory_context_overrides = {"selected_windows": 0}

    with pytest.raises(DG14ContractError, match="window counts"):
        adapter.query("What was the value?", "2026-08-21T10:00:00Z", 512)
    diagnostic = adapter.export_last_resolve_contract_preimage()
    assert diagnostic is not None
    assert diagnostic["status"] == "HIT"
    memory_context = diagnostic["memory_context"]
    assert isinstance(memory_context, Mapping)
    assert memory_context["available_windows"] == 1
    assert memory_context["selected_windows"] == 0
    assert memory_context["window_count"] == 1


def test_dg15_cleanup_rejects_zero_accepted_false_terminal() -> None:
    transport = _FakeMultiplexedTransport()
    transport.cleanup_overrides = {"accepted_count": 0, "failed_count": 0}
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset("dg15-cleanup-denominator", "case-opened-1")
    adapter.ingest_many([_event(0, "session-a", 0, "user", "Remember value 47.")])

    with pytest.raises(DG14ContractError, match="complete Evidence denominator"):
        adapter.cleanup()


def test_dg15_mcp_output_limit_is_a_typed_transport_failure() -> None:
    transport = _FakeMultiplexedTransport()
    transport.resolve_overrides = {
        "status": "TRUNCATED",
        "reason": "MCP_OUTPUT_LIMIT",
        "wire_diagnostics": {
            "top_level_field_bytes": {"memory_context": 70_001},
            "memory_context_field_bytes": {"text": 70_000},
        },
    }
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset("dg15-output-limit", "case-opened-1")
    adapter.ingest_many([_event(0, "session-a", 0, "user", "Remember value 47.")])
    adapter.finalize()

    with pytest.raises(DG14TransportError, match="memory_context.*70001"):
        adapter.query("What was the value?", "2026-08-21T10:00:00Z", 512)


def test_dg15_adapter_renders_noncanonical_operator_result_and_provenance() -> None:
    transport = _FakeMultiplexedTransport()
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset("dg16-q1-test", "case-opened-1")
    adapter.ingest_many(
        [
            _event(0, "session-price", 0, "user", "I spent $60 on five mugs."),
            _event(1, "session-count", 0, "user", "I purchased 5 mugs."),
        ]
    )
    adapter.finalize()
    price_ref = str(transport.captures[0]["source_ref"])
    count_ref = str(transport.captures[1]["source_ref"])
    transport.derived_result = {
        "status": "COMPLETE",
        "kind": "EVIDENCE_COMPOSITION_RESULT",
        "operator": "DIVIDE_EVIDENCE_VALUES",
        "value": 12,
        "unit": "USD_PER_ITEM",
        "display_value": "$12 per item",
        "operands": [
            {
                "slot": "TOTAL_PRICE",
                "value": 60,
                "evidence_id": "evidence-1",
                "source_ref": price_ref,
            },
            {
                "slot": "ITEM_COUNT",
                "value": 5,
                "evidence_id": "evidence-2",
                "source_ref": count_ref,
            },
        ],
        "evidence_refs": ["evidence-1", "evidence-2"],
        "source_turn_refs": [price_ref, count_ref],
        "completeness": {
            "required_slots": ["TOTAL_PRICE", "ITEM_COUNT"],
            "filled_slots": ["TOTAL_PRICE", "ITEM_COUNT"],
            "unresolved_reasons": [],
        },
        "hidden_model_calls": 0,
        "canonical_mutation": False,
    }

    result = adapter.query("How much per mug?", "2026-08-21T10:00:00Z", 512)

    assert "[D1 DERIVED OPERATOR RESULT / NON-CANONICAL READ-ONLY]" in result.context
    assert '"display_value": "$12 per item"' in result.context
    assert "[COMPLETENESS STATUS]" in result.context
    assert "[PROVENANCE]" not in result.context
    assert price_ref not in result.context
    assert "evidence-1" not in result.context
    assert result.declared_tokens <= 512


def test_dg15_quantity_window_prefers_answer_over_question_paraphrase() -> None:
    transport = _FakeMultiplexedTransport()
    transport.selected_evidence_ids = ["evidence-2"]
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset("dg16-quantity-window", "case-opened-1")
    adapter.ingest_many(
        [
            _event(
                0,
                "session-main",
                8,
                "user",
                (
                    "I booked lunch for 6 people. The unrelated event agenda and "
                    "venue plan are already complete. We can discuss those logistics "
                    "separately tomorrow. How many engineers do I lead?"
                ),
            ),
            _event(0, "session-main", 10, "user", "I lead 4 engineers."),
            _event(1, "session-one", 0, "user", "The new role is going well."),
            _event(2, "session-two", 0, "user", "The engineering project shipped."),
            _event(3, "session-three", 0, "user", "The team met today."),
        ]
    )
    adapter.finalize()

    result = adapter.query("How many engineers do I lead?", "2026-08-21T10:00:00Z", 512)

    assert "I lead 4 engineers." in result.context
    assert "How many engineers do I lead?" not in result.context
    assert any("/turn/10?" in value for value in result.selected_source_refs)
    assert all("/turn/8?" not in value for value in result.selected_source_refs)


def test_dg15_adapter_chunks_more_than_512_exact_readiness_receipts() -> None:
    transport = _FakeMultiplexedTransport()
    adapter = DG15MilaiMcpAdapter(
        _config(),
        token_counter=lambda text: len(text.split()),
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset("dg15-large-case-run", "case-opened-1")
    adapter.ingest_many(
        [
            _event(0, "session-large", ordinal, "user", f"Turn {ordinal}")
            for ordinal in range(513)
        ]
    )

    adapter.finalize()

    readiness_calls = [
        call
        for _concurrency, batch in transport.calls
        for call in batch
        if call.tool_name == "milai_projection_readiness_wait"
    ]
    assert [
        len(cast(list[object], call.arguments["target_outbox_ids"]))
        for call in readiness_calls
    ] == [
        512,
        1,
    ]
    assert readiness_calls[0].arguments["target_outbox_ids"] == [
        f"outbox-{index}" for index in range(1, 513)
    ]
    assert readiness_calls[1].arguments["target_outbox_ids"] == ["outbox-513"]
    # 513 captures are emitted as 129 bounded four-call waves, followed by two
    # exact readiness batches (512 + 1 targets).
    assert adapter.stats().physical_mcp_batches == 131
    adapter.cleanup()
