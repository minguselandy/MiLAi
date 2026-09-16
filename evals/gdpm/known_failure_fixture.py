"""Outcome-blind synthetic fixtures for the GDPM B0 context-truth gates."""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Mapping
from pathlib import Path

from milai.application.evidence_acquisition import _governed_adjacent_items

from evals.dg14 import (
    DG14AdapterConfig,
    DG14HistoryEvent,
    DG14MilaiMcpAdapter,
    deterministic_history_session_id,
)
from evals.dg14 import milai_mcp_adapter as adapter_module
from evals.dg14.contracts import DG14ContractError, McpProfile, lexical_terms
from evals.gdpm.b0_context_truth import ContextPreflightReceipt, run_context_preflight


class _CaptureTransport:
    def __init__(self) -> None:
        self.arguments: list[dict[str, object]] = []

    def open_case(self, _scope: Mapping[str, object]) -> None:
        return

    def call(
        self,
        _profile: McpProfile,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> Mapping[str, object]:
        if tool_name != "milai_evidence_capture":
            raise AssertionError(f"unexpected context-only call: {tool_name}")
        self.arguments.append(dict(arguments))
        return {"evidence_id": f"evidence-{len(self.arguments)}"}

    def close(self) -> None:
        return


def execute_known_failure_fixture() -> dict[str, object]:
    """Execute the six B0 invariants without benchmark or Reader calls."""

    with tempfile.TemporaryDirectory(prefix="gdpm-b0-") as temporary:
        transport = _CaptureTransport()
        adapter = DG14MilaiMcpAdapter(
            DG14AdapterConfig(
                base_url="http://127.0.0.1:8765",
                executable=Path(temporary) / "unused-milai-mcp",
                profile_tokens={
                    "submitter": "fixture-submit",
                    "reviewer": "fixture-review",
                    "reader-detail": "fixture-reader",
                    "operator": "fixture-operator",
                },
                allowed_budgets=(128, 4096),
            ),
            transport=transport,
            token_counter=lambda text: len(text.split()),
        )
        adapter.reset("gdpm-b0-fixture", "synthetic-context-truth")
        session_a = _events(0, "rank-one memory says cobalt 47")
        session_b = _events(1, "rank-two memory says amber 19")
        for event in (*session_a, *session_b):
            adapter.ingest(event)
        sessions = (
            _resolved(adapter, session_a, 1),
            _resolved(adapter, session_b, 2),
        )
        question = "What are the cobalt exact query terms?"
        question_at = "2026-08-31T03:00:00Z"
        full = adapter._compile_context(
            question=question,
            question_at=question_at,
            status="HIT",
            sessions=sessions,
            derived_result=None,
            budget=4096,
        )
        windows_a, _raw = adapter._session_windows(sessions[0], lexical_terms(question))
        rank_one_context = adapter._render_context("HIT", None, windows_a)
        rank_one_budget = adapter._count_reader_tokens(
            question, question_at, rank_one_context
        )
        prefix = adapter._compile_context(
            question=question,
            question_at=question_at,
            status="HIT",
            sessions=sessions,
            derived_result=None,
            budget=rank_one_budget,
        )
        long_event = _event(2, 0, "user", "界" * 2000)
        adapter.ingest(long_event)
        long_evidence = adapter._evidence_by_event[long_event.event_id]
        long_chunks = adapter._session_chunks([long_evidence])

    visible = full.reader_visible_trace
    replayed = "\n\n".join(visible["serialization_parts"])  # type: ignore[arg-type]
    encoded = full.text.encode()
    offsets_exact = all(
        hashlib.sha256(
            encoded[
                unit["serialized_utf8_byte_offset"]["start"] : unit[
                    "serialized_utf8_byte_offset"
                ]["end"]
            ]
        ).hexdigest()
        == unit["serialized_unit_sha256"]
        for unit in visible["rendered_units"]  # type: ignore[union-attr]
    )
    subjects = {str(item["subject_id"]) for item in transport.arguments}
    source_sessions = {
        str(item["source_context"]["session_id"])  # type: ignore[index]
        for item in transport.arguments[:4]
    }
    session_integrity = (
        len(subjects) == 1
        and len(source_sessions) == 2
        and subjects.isdisjoint(source_sessions)
        and source_sessions
        == {
            deterministic_history_session_id(
                "synthetic-context-truth", 0, "repeated-scorer-session"
            ),
            deterministic_history_session_id(
                "synthetic-context-truth", 1, "repeated-scorer-session"
            ),
        }
    )
    cross_session_expansion = _cross_session_expansion_count()
    infrastructure = run_context_preflight(
        lambda: (_ for _ in ()).throw(TimeoutError("fixture lease timeout"))
    )
    protocol = run_context_preflight(
        lambda: (_ for _ in ()).throw(DG14ContractError("fixture serialization"))
    )
    system_as_semantic = sum(
        int(receipt.semantic_abstention) for receipt in (infrastructure, protocol)
    )
    metrics: dict[str, int | float] = {
        "SessionIdentityIntegrity": float(session_integrity),
        "CrossSourceSessionAdjacencyExpansion": cross_session_expansion,
        "ReaderVisibleTraceExactness": float(offsets_exact),
        "ContextSerializationReplayEquivalence": float(replayed == full.text),
        "SystemFailureAsSemanticAbstention": system_as_semantic,
        "ReaderCallsDuringContextPreflight": int(visible["reader_call_count"]),
        "AtomicUnitTruncationCount": int(
            full.admitted_evidence_trace["atomic_unit_truncation_count"]
        ),
        "LongTurnSplitCount": int(
            len(long_chunks) != 1
            or long_chunks[0].memory_text != f"user: {long_event.content}"
        ),
        "RankFirstPrefixViolationCount": int(
            prefix.selected_windows != 1
            or "cobalt 47" not in prefix.text
            or "amber 19" in prefix.text
        ),
    }
    expected = {
        "SessionIdentityIntegrity": 1.0,
        "CrossSourceSessionAdjacencyExpansion": 0,
        "ReaderVisibleTraceExactness": 1.0,
        "ContextSerializationReplayEquivalence": 1.0,
        "SystemFailureAsSemanticAbstention": 0,
        "ReaderCallsDuringContextPreflight": 0,
        "AtomicUnitTruncationCount": 0,
        "LongTurnSplitCount": 0,
        "RankFirstPrefixViolationCount": 0,
    }
    return {
        "status": "PASS" if metrics == expected else "FAIL",
        "metrics": metrics,
        "expected": expected,
        "trace": {
            "raw_retrieval_trace": list(full.raw_retrieval_trace),
            "admitted_evidence_trace": full.admitted_evidence_trace,
            "reader_visible_trace": visible,
            "reader_context": full.text,
            "rank_first_prefix_context": prefix.text,
            "rank_first_prefix_budget": rank_one_budget,
            "typed_failure_receipts": {
                "infrastructure": _receipt(infrastructure),
                "protocol": _receipt(protocol),
            },
        },
    }


def _events(
    session_ordinal: int, answer: str
) -> tuple[DG14HistoryEvent, DG14HistoryEvent]:
    return (
        _event(
            session_ordinal,
            0,
            "user",
            "cobalt cobalt cobalt exact query terms",
        ),
        _event(session_ordinal, 1, "assistant", answer),
    )


def _event(
    session_ordinal: int,
    turn_ordinal: int,
    role: str,
    content: str,
) -> DG14HistoryEvent:
    return DG14HistoryEvent.from_mapping(
        {
            "case_id": "synthetic-context-truth",
            "session_ordinal": session_ordinal,
            "original_session_id": "repeated-scorer-session",
            "turn_ordinal": turn_ordinal,
            "role": role,
            "content": content,
            "observed_at": "2026-08-31T00:00:00+00:00",
        }
    )


def _resolved(
    adapter: DG14MilaiMcpAdapter,
    events: tuple[DG14HistoryEvent, ...],
    rank: int,
) -> adapter_module._ResolvedSession:
    evidence = tuple(adapter._evidence_by_event[event.event_id] for event in events)
    return adapter_module._ResolvedSession(
        rank=rank,
        session_ordinal=events[0].session_ordinal,
        session_id=events[0].original_session_id,
        chunk_ordinal=0,
        source_id=f"fixture-session-{events[0].session_ordinal}",
        observed_at=events[0].observed_at,
        memory_text="\n\n".join(f"{item.role}: {item.content}" for item in events),
        claim_id=f"claim-{rank}",
        claim_version_id=f"claim-version-{rank}",
        evidence_ids=tuple(item.evidence_id for item in evidence),
        relevance_score=1.0 - rank / 10,
    )


def _cross_session_expansion_count() -> int:
    anchor = _adjacency_item("anchor", "session-a", 0)
    candidate = _adjacency_item("candidate", "session-b", 0)
    candidate["context_expansion"] = {
        "trigger": "SAME_ROUND",
        "source_evidence_id": "anchor",
    }
    selected = _governed_adjacent_items(
        [candidate],
        anchors=[anchor],
        requested_scope={"project_ids": ["gdpm-b0"]},
        radius=1,
        max_items=5,
        strict=True,
    )
    return len(selected)


def _adjacency_item(
    evidence_id: str, session_id: str, round_ordinal: int
) -> dict[str, object]:
    return {
        "kind": "EVIDENCE_OBSERVATION",
        "canonical": False,
        "evidence_id": evidence_id,
        "source_ref": f"fixture://{session_id}/{evidence_id}",
        "subject_id": "fixture-subject",
        "speaker": "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "source_context": {
            "session_id": session_id,
            "turn_id": f"{session_id}:turn:0",
            "turn_ordinal": 0,
            "round_id": f"{session_id}:round:{round_ordinal}",
            "round_ordinal": round_ordinal,
            "previous_turn_id": None,
            "next_turn_id": None,
        },
        "source_context_source": "STRUCTURED_TURN_METADATA",
        "observed_at": "2026-08-31T00:00:00+00:00",
        "content": evidence_id,
        "permission_snapshot": {
            "readable": True,
            "project_ids": ["gdpm-b0"],
        },
        "retention_state": "READABLE",
        "revoked_at": None,
    }


def _receipt(value: ContextPreflightReceipt) -> dict[str, object]:
    return {
        "disposition": value.disposition,
        "failure_class": str(value.failure_class),
        "failure_type": value.failure_type,
        "semantic_abstention": value.semantic_abstention,
        "reader_calls": value.reader_calls,
    }


__all__ = ["execute_known_failure_fixture"]
