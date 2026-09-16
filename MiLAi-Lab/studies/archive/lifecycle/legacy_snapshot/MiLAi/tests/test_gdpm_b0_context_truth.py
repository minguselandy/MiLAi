from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

from evals.dg14 import (
    DG14AdapterConfig,
    DG14HistoryEvent,
    DG14MilaiMcpAdapter,
    deterministic_history_session_id,
)
from evals.dg14 import milai_mcp_adapter as adapter_module
from evals.dg14.contracts import DG14ContractError, McpProfile, lexical_terms
from evals.dg14.reader_token_accounting import (
    EXPECTED_READER_CHAT_TEMPLATE_SHA256,
    EXPECTED_READER_TOKENIZER_SHA256,
)
from evals.gdpm import PreflightFailureClass, run_context_preflight
from evals.gdpm.known_failure_fixture import execute_known_failure_fixture


class _CaptureTransport:
    def __init__(self) -> None:
        self.arguments: list[dict[str, object]] = []
        self.opened = False

    def open_case(self, _scope: Mapping[str, object]) -> None:
        self.opened = True

    def call(
        self,
        _profile: McpProfile,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> Mapping[str, object]:
        if tool_name != "milai_evidence_capture":
            raise AssertionError(f"unexpected B0 preflight call: {tool_name}")
        self.arguments.append(dict(arguments))
        return {"evidence_id": f"evidence-{len(self.arguments)}"}

    def close(self) -> None:
        self.opened = False


def _adapter(tmp_path: Path) -> tuple[DG14MilaiMcpAdapter, _CaptureTransport]:
    transport = _CaptureTransport()
    adapter = DG14MilaiMcpAdapter(
        DG14AdapterConfig(
            base_url="http://127.0.0.1:8765",
            executable=tmp_path / "milai-mcp",
            profile_tokens={
                "submitter": "submitter-token",
                "reviewer": "reviewer-token",
                "reader-detail": "reader-token",
                "operator": "operator-token",
            },
            allowed_budgets=(128, 4096),
        ),
        transport=transport,
        token_counter=lambda text: len(text.split()),
    )
    adapter.reset("gdpm-b0-fixture", "case-b0")
    return adapter, transport


def _event(
    *, session_ordinal: int, turn_ordinal: int, role: str, content: str
) -> DG14HistoryEvent:
    return DG14HistoryEvent.from_mapping(
        {
            "case_id": "case-b0",
            "session_ordinal": session_ordinal,
            "original_session_id": "repeated-scorer-session",
            "turn_ordinal": turn_ordinal,
            "role": role,
            "content": content,
            "observed_at": f"2026-08-31T0{session_ordinal}:0{turn_ordinal}:00+00:00",
        }
    )


def _resolved_session(
    adapter: DG14MilaiMcpAdapter,
    events: tuple[DG14HistoryEvent, ...],
    *,
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


def test_b0_identity_whole_unit_and_three_layer_trace_replay(tmp_path: Path) -> None:
    adapter, transport = _adapter(tmp_path)
    session_a = (
        _event(
            session_ordinal=0,
            turn_ordinal=0,
            role="user",
            content="Tell me the lower-ranked lexical decoy.",
        ),
        _event(
            session_ordinal=0,
            turn_ordinal=1,
            role="assistant",
            content="The rank-one memory says cobalt 47.",
        ),
    )
    session_b = (
        _event(
            session_ordinal=1,
            turn_ordinal=0,
            role="user",
            content="cobalt cobalt cobalt exact query terms",
        ),
        _event(
            session_ordinal=1,
            turn_ordinal=1,
            role="assistant",
            content="The rank-two memory says amber 19.",
        ),
    )
    for event in (*session_a, *session_b):
        adapter.ingest(event)

    subjects = {str(value["subject_id"]) for value in transport.arguments}
    source_sessions = {
        str(value["source_context"]["session_id"])  # type: ignore[index]
        for value in transport.arguments
    }
    assert len(subjects) == 1
    assert source_sessions == {
        deterministic_history_session_id("case-b0", 0, "repeated-scorer-session"),
        deterministic_history_session_id("case-b0", 1, "repeated-scorer-session"),
    }
    assert subjects.isdisjoint(source_sessions)

    sessions = (
        _resolved_session(adapter, session_a, rank=1),
        _resolved_session(adapter, session_b, rank=2),
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

    raw = full.raw_retrieval_trace
    assert len(raw) == 4
    assert (
        len(
            {
                row["evidence_identity"]["source_session_id"]  # type: ignore[index]
                for row in raw
            }
        )
        == 2
    )
    admitted = full.admitted_evidence_trace
    assert admitted["atomic_unit_truncation_count"] == 0
    assert len(admitted["admitted_units"]) == 2  # type: ignore[arg-type]
    assert full.selected_windows == 2

    visible = full.reader_visible_trace
    assert visible["reader_call_count"] == 0
    assert visible["tokenizer_sha256"] == EXPECTED_READER_TOKENIZER_SHA256
    assert visible["chat_template_sha256"] == EXPECTED_READER_CHAT_TEMPLATE_SHA256
    replayed = "\n\n".join(visible["serialization_parts"])  # type: ignore[arg-type]
    assert replayed == full.text
    assert (
        hashlib.sha256(replayed.encode()).hexdigest()
        == visible["serialization_replay_sha256"]
    )
    encoded = full.text.encode()
    for unit in visible["rendered_units"]:  # type: ignore[union-attr]
        offsets = unit["serialized_utf8_byte_offset"]
        source = encoded[offsets["start"] : offsets["end"]]
        assert hashlib.sha256(source).hexdigest() == unit["serialized_unit_sha256"]
        assert unit["reader_prompt_token_end"] > unit["reader_prompt_token_start"]

    windows_a, _trace = adapter._session_windows(sessions[0], lexical_terms(question))
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
    assert prefix.selected_windows == 1
    assert "cobalt 47" in prefix.text
    assert "amber 19" not in prefix.text
    assert "cobalt cobalt cobalt" not in prefix.text
    assert prefix.admitted_evidence_trace["atomic_unit_truncation_count"] == 0
    assert prefix.tokens == rank_one_budget


def test_b0_long_turn_is_never_split_at_canonical_chunk_boundary(
    tmp_path: Path,
) -> None:
    adapter, _transport = _adapter(tmp_path)
    event = _event(
        session_ordinal=0,
        turn_ordinal=0,
        role="user",
        content="界" * 2000,
    )
    adapter.ingest(event)
    evidence = adapter._evidence_by_event[event.event_id]

    chunks = adapter._session_chunks([evidence])

    assert len(chunks) == 1
    assert chunks[0].evidence == (evidence,)
    assert chunks[0].memory_text == f"user: {event.content}"


def test_b0_system_failures_are_never_semantic_abstentions() -> None:
    infrastructure = run_context_preflight(
        lambda: (_ for _ in ()).throw(TimeoutError("lease expired"))
    )
    protocol = run_context_preflight(
        lambda: (_ for _ in ()).throw(DG14ContractError("bad serialization"))
    )
    semantic = run_context_preflight(lambda: {"status": "ABSTAINED"})

    assert infrastructure.failure_class == PreflightFailureClass.INFRASTRUCTURE
    assert protocol.failure_class == PreflightFailureClass.PROTOCOL_IMPLEMENTATION
    assert infrastructure.semantic_abstention is False
    assert protocol.semantic_abstention is False
    assert semantic.failure_class == PreflightFailureClass.SEMANTIC_ABSTENTION
    assert semantic.semantic_abstention is True
    assert {
        infrastructure.reader_calls,
        protocol.reader_calls,
        semantic.reader_calls,
    } == {0}


def test_b0_executable_fixture_bundle_passes_all_declared_gates() -> None:
    result = execute_known_failure_fixture()

    assert result["status"] == "PASS"
    assert result["metrics"] == result["expected"]
