from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from evals.dg14 import (
    DG14AdapterConfig,
    DG14HistoryEvent,
    DG14LifecycleError,
    DG14MilaiMcpAdapter,
    DG14Provenance,
    DG14TransportError,
)
from evals.dg14.contracts import McpProfile
from evals.dg14.mcp_stdio import StdioMcpTransport
from evals.paper.scorers.longmemeval import score_retrieval


class RecordingMcpTransport:
    def __init__(self, *, fail_tool: str | None = None) -> None:
        self.scope: dict[str, object] | None = None
        self.calls: list[tuple[str, str, dict[str, object]]] = []
        self.closed = False
        self.fail_tool = fail_tool
        self.proposal: dict[str, object] | None = None

    def open_case(self, scope: Mapping[str, object]) -> None:
        assert self.scope is None
        self.scope = dict(scope)

    def call(
        self,
        profile: str,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> Mapping[str, object]:
        args = dict(arguments)
        self.calls.append((profile, tool_name, args))
        if tool_name == self.fail_tool:
            raise DG14TransportError(f"injected {tool_name} failure")
        if tool_name == "milai_evidence_capture":
            return {"evidence_id": "evidence-1", "request_id": "request-capture"}
        if tool_name == "milai_proposal_create":
            raw_proposal = args["proposal"]
            assert isinstance(raw_proposal, dict)
            self.proposal = raw_proposal
            return {"proposal_id": "proposal-1", "request_id": "request-proposal"}
        if tool_name == "milai_proposal_get":
            assert self.proposal is not None
            return {
                "proposal_id": "proposal-1",
                "operation": self.proposal["operation"],
                "supporting_evidence_refs": self.proposal["supporting_evidence_refs"],
                "requested_authority": self.proposal["requested_authority"],
                "scope_predicate": self.proposal["scope_predicate"],
                "proposed_patch": self.proposal["proposed_patch"],
                "model_id": self.proposal["model_id"],
                "template_id": self.proposal["template_version"],
                "derivation_policy_id": self.proposal["derivation_policy_id"],
                "derivation_snapshot": {
                    "input_snapshot_hash": self.proposal["input_snapshot_hash"]
                },
            }
        if tool_name == "milai_memory_review":
            return {
                "decision": "APPROVE",
                "claim_id": "claim-1",
                "claim_version_id": "claim-version-1",
                "request_id": "request-review",
            }
        if tool_name == "milai_memory_resolve":
            snapshot = {
                "canonical_outbox_sequence": 1,
                "fts_watermark": 1,
                "vector_watermark": 1,
            }
            if str(args["query"]).startswith("observed benchmark history sessions"):
                return {
                    "status": "ABSENT",
                    "items": [],
                    "degraded_components": [],
                    "fallback_used": False,
                    "fallback_reason": None,
                    "canonical_position": snapshot,
                    "request_id": "request-readiness",
                }
            assert self.proposal is not None
            patch = self.proposal["proposed_patch"]
            assert isinstance(patch, dict)
            return {
                "status": "HIT",
                "items": [
                    {
                        "claim_id": "claim-1",
                        "claim_version_id": "claim-version-1",
                        "payload": patch["payload"],
                        "evidence_ids": ["evidence-1"],
                        "valid_time_from": "2026-08-26T01:02:03+00:00",
                        "relevance_score": 0.9,
                    }
                ],
                "degraded_components": [],
                "fallback_used": False,
                "fallback_reason": None,
                "canonical_position": snapshot,
                "trace_id": "trace-1",
                "request_id": "request-query",
                "search_trace": {
                    "candidate_counts": {"fts": 1, "vector": 1},
                    "stop_stage": "hybrid",
                    "context_budget_truncated": False,
                },
                "access_trace": {
                    "planned_stage": "hybrid",
                    "terminal_stage": "hybrid",
                },
            }
        if tool_name == "milai_trace_get":
            return {"trace_id": "trace-1", "stages": ["hybrid"]}
        if tool_name == "milai_evidence_revoke":
            return {
                "evidence_id": args["evidence_id"],
                "logical_revocation_status": "APPLIED",
            }
        raise AssertionError(f"unexpected MCP call: {profile}/{tool_name}")

    def close(self) -> None:
        self.closed = True


def _config(tmp_path: Path) -> DG14AdapterConfig:
    return DG14AdapterConfig(
        base_url="http://127.0.0.1:8765",
        executable=tmp_path / "milai-mcp",
        profile_tokens={
            "submitter": "submitter-token",
            "reviewer": "reviewer-token",
            "reader-detail": "reader-token",
            "operator": "operator-token",
        },
        tenant_id="00000000-0000-0000-0000-000000000001",
        principal_id="00000000-0000-0000-0000-000000000002",
    )


def _event() -> DG14HistoryEvent:
    return DG14HistoryEvent(
        case_id="001be529",
        session_ordinal=3,
        original_session_id="session-repeated",
        turn_ordinal=0,
        role="user",
        content="My asylum application decision took six months.",
        observed_at="2026-08-26T01:02:03+00:00",
    )


def _adapter(
    tmp_path: Path,
    transport: RecordingMcpTransport,
) -> DG14MilaiMcpAdapter:
    return DG14MilaiMcpAdapter(
        _config(tmp_path),
        transport=transport,
        token_counter=lambda text: len(text.split()),
    )


def test_stdio_profiles_bind_current_scope_and_mechanically_disable_retries(
    tmp_path: Path,
) -> None:
    transport = StdioMcpTransport(_config(tmp_path))
    scope: dict[str, object] = {"project_ids": ["dg14-case-one"]}

    profiles: tuple[McpProfile, ...] = (
        "submitter",
        "reviewer",
        "reader-detail",
        "operator",
    )
    for profile in profiles:
        environment = transport._environment(profile, scope)
        assert (
            environment["MILAI_AGENT_TOKEN"]
            == {
                "submitter": "submitter-token",
                "reviewer": "reviewer-token",
                "reader-detail": "reader-token",
                "operator": "operator-token",
            }[profile]
        )
        assert environment["MILAI_AGENT_SCOPE_JSON"] == (
            '{"project_ids":["dg14-case-one"]}'
        )
        assert environment["MILAI_AGENT_CONSISTENCY_FLOOR"] == "CANONICAL_REQUIRED"
        assert environment["MILAI_AGENT_MAX_RETRIES"] == "0"
        assert "DG10" not in " ".join(environment)


def test_stdio_transport_fails_typed_before_open_and_does_not_fallback() -> None:
    transport = StdioMcpTransport.__new__(StdioMcpTransport)
    transport._loop = None
    transport._clients = {}

    with pytest.raises(DG14LifecycleError, match="no open case"):
        transport.call(
            "reader-detail",
            "milai_memory_resolve",
            {"query": "Where is the memory?"},
        )


def test_fake_mcp_executes_governed_profiles_without_task_context_or_retry(
    tmp_path: Path,
) -> None:
    transport = RecordingMcpTransport()
    adapter = _adapter(tmp_path, transport)

    namespace = adapter.reset("run-unit", "001be529")
    adapter.ingest(_event())
    adapter.finalize()
    result = adapter.query(
        "How long did the decision take?",
        "2026/08/26 (Wed) 01:03",
        512,
    )
    revoked = adapter.cleanup()

    assert transport.scope == {"project_ids": [namespace.project_id]}
    assert [(profile, tool) for profile, tool, _arguments in transport.calls] == [
        ("submitter", "milai_evidence_capture"),
        ("submitter", "milai_proposal_create"),
        ("reviewer", "milai_proposal_get"),
        ("reviewer", "milai_memory_review"),
        ("reader-detail", "milai_memory_resolve"),
        ("reader-detail", "milai_memory_resolve"),
        ("reader-detail", "milai_trace_get"),
        ("operator", "milai_evidence_revoke"),
    ]
    query_args = transport.calls[5][2]
    assert query_args == {
        "query": "Recall: How long did the decision take?",
        "required_freshness": "CURRENT",
        "consistency_mode": "CANONICAL_REQUIRED",
        "limit": 3,
        "max_context_tokens": 4_096,
    }
    assert "task_context" not in query_args
    assert all(record.status == "SUCCEEDED" for record in adapter.export_call_records())
    assert all(
        record.sequence == index
        for index, record in enumerate(adapter.export_call_records(), start=1)
    )
    assert result.source_ids == ("session-repeated",)
    assert result.provenance[0].session_id == "session-repeated"
    assert result.usage["fallback_used"] is False
    assert result.usage["mcp_logical_calls"] == 2
    assert adapter.export_context() == result.context
    assert adapter.export_provenance() == result.provenance
    assert revoked == ("evidence-1",)
    assert transport.closed is True


def test_adapter_records_typed_transport_failure_and_never_attempts_a_fallback(
    tmp_path: Path,
) -> None:
    transport = RecordingMcpTransport(fail_tool="milai_memory_resolve")
    adapter = _adapter(tmp_path, transport)
    adapter.reset("run-unit", "001be529")
    adapter.ingest(_event())

    with pytest.raises(DG14TransportError, match="injected"):
        adapter.finalize()

    records = adapter.export_call_records()
    assert records[-1].tool_name == "milai_memory_resolve"
    assert records[-1].status == "FAILED"
    assert [tool for _profile, tool, _args in transport.calls].count(
        "milai_memory_resolve"
    ) == 1
    assert not any(tool == "milai_recall" for _profile, tool, _args in transport.calls)


def test_dg14_provenance_uses_original_session_ids_accepted_by_the_lme_scorer() -> None:
    provenance = (
        DG14Provenance(
            rank=1,
            source_id="longmemeval://case/case/session/7/session-relevant-b",
            session_id="session-relevant-b",
            session_ordinal=7,
            claim_id="claim-b",
            claim_version_id="version-b",
            evidence_ids=("evidence-b",),
            relevance_score=0.91,
            context_selected=True,
        ),
        DG14Provenance(
            rank=2,
            source_id="longmemeval://case/case/session/2/session-relevant-a",
            session_id="session-relevant-a",
            session_ordinal=2,
            claim_id="claim-a",
            claim_version_id="version-a",
            evidence_ids=("evidence-a",),
            relevance_score=0.73,
            context_selected=True,
        ),
    )

    scored = score_retrieval(
        [
            {"session_id": item.session_id, "source_id": item.source_id}
            for item in provenance
        ],
        ["session-relevant-a", "session-relevant-b"],
    )

    assert scored == {
        "hit_at_k": 1,
        "ndcg_at_k": 1.0,
        "relevant_coverage_at_k": 1.0,
        "retrieved_k": 2,
    }
