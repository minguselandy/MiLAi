from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from mcp import Client
from milai_client import AuthorizationError, ConflictError, UnavailableError

from milai_mcp import server as server_module
from milai_mcp.server import build_server


class _Client:
    def __init__(self) -> None:
        self.proposals: list[tuple[Any, str]] = []
        self.reviews: list[tuple[str, dict[str, Any], str]] = []
        self.proposal_reads: list[str] = []
        self.proposal_lists: list[tuple[str | None, int]] = []
        self.recalls: list[tuple[str, dict[str, Any]]] = []
        self.resolves: list[tuple[str, dict[str, Any]]] = []
        self.state_reads: list[dict[str, Any]] = []
        self.context_preparations: list[dict[str, Any]] = []
        self.readiness_requests: list[dict[str, Any]] = []
        self.namespace_cleanup_submissions: list[dict[str, Any]] = []
        self.namespace_cleanup_status_reads: list[dict[str, Any]] = []
        self.evidence_captures: list[tuple[dict[str, Any], str]] = []

    def capabilities(self) -> Any:
        return SimpleNamespace(
            raw={
                "api_version": "1",
                "contract_version": "agent.v1",
                "capabilities": ["memory:read"],
            }
        )

    def create_proposal(self, payload: Any, *, operation_id: str) -> Any:
        self.proposals.append((payload, operation_id))
        return SimpleNamespace(raw={"proposal_id": "proposal-1", "status": "PENDING_REVIEW"})

    def capture_evidence(
        self, payload: dict[str, Any], *, operation_id: str
    ) -> Any:
        self.evidence_captures.append((payload, operation_id))
        return SimpleNamespace(
            raw={
                "evidence_id": "11111111-1111-4111-8111-111111111111",
                "outbox_id": "22222222-2222-4222-8222-222222222222",
            }
        )

    def review_proposal(
        self,
        proposal_id: str,
        payload: dict[str, Any],
        *,
        operation_id: str,
    ) -> Any:
        self.reviews.append((proposal_id, payload, operation_id))
        return SimpleNamespace(
            raw={
                "proposal_id": proposal_id,
                "decision_id": "decision-1",
                "decision": payload["decision"],
                "claim_id": "claim-1",
                "claim_version_id": "version-1",
                "canonical_commit_seq": 7,
                "replayed": False,
            }
        )

    def list_proposals(self, status: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
        self.proposal_lists.append((status, limit))
        return [{"proposal_id": "proposal-1", "status": "PENDING_REVIEW"}]

    def get_proposal(self, proposal_id: str) -> dict[str, Any]:
        self.proposal_reads.append(proposal_id)
        return {"proposal_id": proposal_id, "status": "PENDING_REVIEW"}

    def get_claim(self, claim_id: str) -> Any:
        return SimpleNamespace(claim_id=claim_id, claim_version_id="current-version")

    def recall(self, query: str, **options: Any) -> Any:
        self.recalls.append((query, options))
        return SimpleNamespace(
            status="ABSTAINED",
            items=[],
            issues=[],
            trace_id="trace-1",
            consistency=options["consistency"],
            canonical_position={"canonical_outbox_sequence": 1},
            degraded_components=[],
            fallback_used=False,
            fallback_reason=None,
            abstention_reason="NO_CANDIDATE",
            derived_result={
                "status": "ABSTAINED",
                "kind": "DERIVED_QUERY_RESULT",
                "operator": "TEMPORAL_DISTANCE",
                "reason": "OPERAND_MISSING",
            },
            raw={
                "stage_metrics": {
                    "durations_ms": {"query_total_ms": 1.25},
                    "counts": {"query_total_ms": 1},
                },
                "access_trace": {
                    "schema_version": "access-trace-v0.1",
                    "retrieval_trace_id": "trace-1",
                    "runtime_request_id": "request-1",
                    "requested_intent": None,
                    "planned_stage": "SEARCH",
                    "attempted_stages": ["EXACT", "FTS", "CANONICAL_GATE"],
                    "terminal_stage": "CANONICAL_GATE",
                    "stop_reason": "NO_CANDIDATE",
                    "fallback_reason": None,
                    "canonical_position": 1,
                    "spans": {"runtime_kernel_ms": 1.25},
                    "route_trace_complete": True,
                    "trace_gap_reason": None,
                },
            },
        )

    def resolve_memory(self, query: str, **options: Any) -> Any:
        self.resolves.append((query, options))
        return SimpleNamespace(
            raw={
                "schema_version": "access-outcome-v0.1",
                "status": "HIT",
                "items": [{"claim_id": "claim-1"}],
                "open_issue_ids": [],
                "evidence_refs": ["evidence-1"],
                "consistency": options["consistency_mode"],
                "canonical_position": {"canonical_outbox_sequence": 1},
                "trace_id": "trace-1",
                "degraded_components": [],
                "abstention_reason": None,
                "context_receipt": None,
                "memory_context": {
                    "schema_version": "memory-context-v0.1",
                    "authority_class": "CANONICAL_STATE",
                    "text": "MILAI_MEMORY_DATA_BEGIN\ncurrent state\nMILAI_MEMORY_DATA_END",
                    "token_budget": 2500,
                    "estimated_tokens": 20,
                    "selected_evidence_ids": [],
                    "selected_source_turn_refs": [],
                },
                "memory_intent": "REQUIRED",
                "requirement": "EXACT",
                "availability": "AVAILABLE",
                "interpretation": {
                    "version": "runtime-query-interpreter-v1",
                    "reason_code": "QUERY_MEMORY_EXACT_SIGNAL",
                    "retrieval_intent": "CURRENT_STATE",
                },
                "access_trace": {
                    "schema_version": "access-trace-v0.1",
                    "retrieval_trace_id": "trace-1",
                    "runtime_request_id": "request-1",
                    "spans": {"runtime_kernel_ms": 1.25},
                },
                "request_id": "request-1",
                "fallback_used": False,
                "fallback_reason": None,
            }
        )

    def get_memory(self, **options: Any) -> Any:
        self.state_reads.append(options)
        return SimpleNamespace(
            raw={
                "schema_version": "memory-state-view-v0.1",
                "status": "HIT",
                "items": [
                    {
                        "claim_id": "claim-1",
                        "claim_version_id": "version-1",
                        "payload": {"value": "current"},
                    }
                ],
                "open_issue_ids": [],
                "evidence_refs": ["evidence-1"],
                "consistency": options["consistency_mode"],
                "canonical_position": {"canonical_outbox_sequence": 1},
                "trace_id": "trace-state-1",
                "availability": "AVAILABLE",
                "abstention_reason": None,
                "resolution": {
                    "mode": "CURRENT",
                    "valid_at": "2026-08-26T00:00:00+00:00",
                    "known_at": "2026-08-26T00:00:00+00:00",
                    "addressable": True,
                    "reachable": True,
                    "correctly_resolved": True,
                },
                "access_trace": {
                    "schema_version": "access-trace-v0.1",
                    "retrieval_trace_id": "trace-state-1",
                    "runtime_request_id": "request-state-1",
                    "planned_stage": "EXACT",
                    "spans": {"runtime_kernel_ms": 1.0},
                    "structural_cost": {
                        "auxiliary_llm_calls": 0,
                        "embedding_calls": 0,
                        "vector_search_calls": 0,
                        "reranker_calls": 0,
                        "broad_head_scan_calls": 0,
                    },
                },
                "request_id": "request-state-1",
            }
        )

    def prepare_context(self, payload: dict[str, Any]) -> Any:
        self.context_preparations.append(payload)
        return SimpleNamespace(
            raw={
                "route": "CACHE",
                "status": "UNCHANGED",
                "reason": "VALIDATED_TASK_SLOT_REUSE",
                "context_capsule": None,
                "context_delta": {"status": "UNCHANGED"},
                "relevant_open_issue_closure": [],
                "canonical_position": 7,
                "validation_token": "validation-token",
                "trace_pointer": None,
                "usage": {"prepare_context_calls": 2},
            }
        )

    def wait_for_projection_readiness(self, **options: Any) -> dict[str, Any]:
        self.readiness_requests.append(options)
        return {
            "status": "READY",
            "target_outbox_id": options["target_outbox_id"],
            "target_watermark": 17,
            "routing_version": "dg15-routing-v1",
            "projections": [
                {
                    "projection": "evidence",
                    "current_watermark": 17,
                    "target_watermark": 17,
                    "projection_version": "evidence-search-v1",
                    "version_match": True,
                    "ready": True,
                }
            ],
            "projection_work_started": False,
        }

    def submit_namespace_cleanup(self, **options: Any) -> dict[str, Any]:
        self.namespace_cleanup_submissions.append(options)
        return {
            "cleanup_job_id": "33333333-3333-4333-8333-333333333333",
            "project_id": options["project_id"],
            "status": "ACCEPTED",
            "matched_evidence_count": 2,
            "accepted_evidence_count": 2,
            "failed_evidence_count": 0,
            "physical_purge_complete": False,
        }

    def namespace_cleanup_status(
        self,
        cleanup_job_id: str,
        *,
        offset: int,
        limit: int,
    ) -> dict[str, Any]:
        request = {
            "cleanup_job_id": cleanup_job_id,
            "offset": offset,
            "limit": limit,
        }
        self.namespace_cleanup_status_reads.append(request)
        return {
            **request,
            "status": "IN_PROGRESS",
            "physical_purge_complete": False,
            "items": [],
        }


def _tool_names(profile: str) -> set[str]:
    server = build_server(profile, _Client())  # type: ignore[arg-type]
    return {tool.name for tool in asyncio.run(server.list_tools())}


def test_default_runtime_client_timeout_covers_max_projection_barrier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def client_factory(**kwargs: Any) -> _Client:
        captured.update(kwargs)
        return _Client()

    monkeypatch.setattr(server_module, "MilaiClient", client_factory)

    build_server("reader-lite")

    assert captured == {
        "timeout_seconds": server_module._RUNTIME_HTTP_TIMEOUT_SECONDS,
        "max_retries": 2,
    }
    assert captured["timeout_seconds"] == 35.0


def test_runtime_client_zero_retry_policy_is_bound_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def client_factory(**kwargs: Any) -> _Client:
        captured.update(kwargs)
        return _Client()

    monkeypatch.setattr(server_module, "MilaiClient", client_factory)

    build_server("reader-lite", max_retries=0)

    assert captured == {
        "timeout_seconds": server_module._RUNTIME_HTTP_TIMEOUT_SECONDS,
        "max_retries": 0,
    }


def test_zero_retry_policy_makes_access_trace_retry_count_exact() -> None:
    async def run() -> None:
        server = build_server("reader-lite", _Client(), max_retries=0)  # type: ignore[arg-type]
        async with Client(server, mode="2026-07-28") as client:
            result = await client.call_tool(
                "milai_memory_resolve", {"query": "Recall the current status"}
            )
        assert result.structured_content is not None
        trace = result.structured_content["access_trace"]
        assert trace["logical_mcp_calls"] == 1
        assert trace["automatic_retry_count"] == 0

    asyncio.run(run())


@pytest.mark.parametrize("invalid", [-1, True])
def test_runtime_client_retry_policy_rejects_invalid_values(invalid: object) -> None:
    with pytest.raises(ValueError, match="max_retries must be a non-negative integer"):
        build_server("reader-lite", max_retries=invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("environment_value", "cli", "expected"),
    [
        ("0", ["milai-mcp"], 0),
        ("2", ["milai-mcp", "--max-retries", "0"], 0),
    ],
)
def test_main_binds_environment_and_cli_retry_policy(
    monkeypatch: pytest.MonkeyPatch,
    environment_value: str,
    cli: list[str],
    expected: int,
) -> None:
    captured: dict[str, Any] = {}

    class _Server:
        def run(self, *, transport: str) -> None:
            captured["transport"] = transport

    def server_factory(profile: str, **kwargs: Any) -> _Server:
        captured["profile"] = profile
        captured.update(kwargs)
        return _Server()

    monkeypatch.setenv("MILAI_AGENT_MAX_RETRIES", environment_value)
    monkeypatch.setattr(sys, "argv", cli)
    monkeypatch.setattr(server_module, "build_server", server_factory)

    server_module.main()

    assert captured["max_retries"] == expected
    assert captured["transport"] == "stdio"


def test_main_rejects_negative_environment_retry_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MILAI_AGENT_MAX_RETRIES", "-1")
    monkeypatch.setattr(sys, "argv", ["milai-mcp"])

    with pytest.raises(SystemExit, match="MILAI_AGENT_MAX_RETRIES"):
        server_module.main()


def test_reader_profile_is_exact_allowlist() -> None:
    assert _tool_names("reader") == {
        "milai_status",
        "milai_recall",
        "milai_memory_resolve",
        "milai_memory_get",
        "milai_claim_get",
        "milai_open_issues_list",
        "milai_trace_get",
        "milai_evidence_metadata_get",
        "milai_projection_readiness_wait",
    }


def test_vnext_compatibility_mapping_has_one_owner_and_m1_m2_targets_are_registered() -> None:
    assert server_module.TOOL_COMPATIBILITY_VNEXT == {
        "milai_recall": "milai_memory_resolve",
        "milai_claim_get": "milai_memory_get",
        "milai_status": "milai_memory_capabilities",
        "milai_trace_get": "milai_memory_explain",
        "milai_evidence_metadata_get": "milai_memory_explain",
        "milai_evidence_capture": "milai_evidence_capture",
        "milai_proposal_create": "milai_memory_propose",
        "runtime:/v1/proposals/{proposal_id}/review": "milai_memory_review",
        "milai_evidence_revoke": "milai_memory_delete",
        "milai_deletion_status_get": "memory://deletion-requests/{id}",
        "unimplemented:export": "milai_memory_export",
        "milai_prepare_context": "openworker-extension:milai_memory_resolve",
    }
    assert {name for name in _tool_names("reader") if name.startswith("milai_memory_")} == {
        "milai_memory_get",
        "milai_memory_resolve",
    }


def test_reader_detail_projection_barrier_preserves_exact_target_and_versions() -> None:
    async def run() -> None:
        api = _Client()
        server = build_server("reader-detail", api)  # type: ignore[arg-type]
        async with Client(server, mode="2026-07-28") as client:
            result = await client.call_tool(
                "milai_projection_readiness_wait",
                {
                    "target_outbox_id": "22222222-2222-4222-8222-222222222222",
                    "required_projections": ["evidence"],
                    "expected_versions": {"evidence": "evidence-search-v1"},
                    "timeout_ms": 15000,
                    "poll_interval_ms": 25,
                },
            )
            assert result.is_error is False
            assert result.structured_content is not None
            assert result.structured_content["status"] == "READY"
        assert api.readiness_requests == [
            {
                "target_outbox_id": "22222222-2222-4222-8222-222222222222",
                "required_projections": ["evidence"],
                "expected_versions": {"evidence": "evidence-search-v1"},
                "timeout_ms": 15000,
                "poll_interval_ms": 25,
            }
        ]

    asyncio.run(run())


def test_reader_lite_is_default_minimum_catalog_and_detail_alias_is_stable() -> None:
    assert _tool_names("reader-lite") == {"milai_recall", "milai_memory_resolve"}
    assert _tool_names("reader-detail") == _tool_names("reader")


def test_submitter_reviewer_and_operator_are_separate() -> None:
    submitter = _tool_names("submitter")
    reviewer = _tool_names("reviewer")
    operator = _tool_names("operator")
    assert {"milai_evidence_capture", "milai_proposal_create"} <= submitter
    assert {
        "milai_proposals_list",
        "milai_proposal_get",
        "milai_memory_review",
    } <= reviewer
    assert {
        "milai_evidence_revoke",
        "milai_deletion_status_get",
        "milai_namespace_cleanup_submit",
        "milai_namespace_cleanup_status",
    } <= operator
    assert "milai_evidence_revoke" not in submitter
    assert "milai_proposal_create" not in operator
    assert "milai_proposal_create" not in reviewer
    assert "milai_evidence_capture" not in reviewer
    assert "milai_memory_review" not in submitter


def test_operator_namespace_cleanup_is_one_submission_with_explicit_staging() -> None:
    async def run() -> None:
        api = _Client()
        server = build_server("operator", api)  # type: ignore[arg-type]
        async with Client(server, mode="2026-07-28") as client:
            submitted = await client.call_tool(
                "milai_namespace_cleanup_submit",
                {
                    "project_id": "dg15-case-alpha",
                    "operation_id": "dg15-cleanup-alpha",
                    "reason_code": "USER_REQUEST",
                    "confirmation": "CLEANUP_NAMESPACE",
                },
            )
            assert submitted.is_error is False
            assert submitted.structured_content is not None
            assert submitted.structured_content["status"] == "ACCEPTED"
            assert submitted.structured_content["physical_purge_complete"] is False
            status = await client.call_tool(
                "milai_namespace_cleanup_status",
                {
                    "cleanup_job_id": "33333333-3333-4333-8333-333333333333",
                    "offset": 0,
                    "limit": 100,
                },
            )
            assert status.is_error is False
            assert status.structured_content is not None
            assert status.structured_content["status"] == "IN_PROGRESS"
            assert status.structured_content["physical_purge_complete"] is False
        assert api.namespace_cleanup_submissions == [
            {
                "project_id": "dg15-case-alpha",
                "reason_code": "USER_REQUEST",
                "operation_id": "dg15-cleanup-alpha",
            }
        ]
        assert api.namespace_cleanup_status_reads == [
            {
                "cleanup_job_id": "33333333-3333-4333-8333-333333333333",
                "offset": 0,
                "limit": 100,
            }
        ]

    asyncio.run(run())


def test_no_profile_exposes_canonical_or_bulk_dangerous_tools() -> None:
    forbidden = {
        "milai_proposal_review",
        "milai_claim_update",
        "milai_issue_resolve",
        "milai_delete_all",
        "milai_clear_tenant",
        "milai_database_query",
    }
    for profile in (
        "reader-lite",
        "reader-detail",
        "reader",
        "submitter",
        "reviewer",
        "operator",
    ):
        assert _tool_names(profile).isdisjoint(forbidden)


def test_reader_lite_recall_caps_default_limit_and_rejects_profile_escalation() -> None:
    async def run() -> None:
        api = _Client()
        server = build_server("reader-lite", api)  # type: ignore[arg-type]
        async with Client(server, mode="2026-07-28") as client:
            result = await client.call_tool(
                "milai_recall",
                {"query": "synthetic"},
            )
            assert result.is_error is False
            assert result.structured_content is not None
            assert result.structured_content["derived_result"]["reason"] == "OPERAND_MISSING"
            assert result.structured_content["stage_metrics"] == {
                "durations_ms": {"query_total_ms": 1.25},
                "counts": {"query_total_ms": 1},
            }
            access_trace = result.structured_content["access_trace"]
            assert access_trace["logical_mcp_calls"] == 1
            assert access_trace["automatic_retry_count"] is None
            assert access_trace["retry_policy_max_retries"] == 2
            assert access_trace["span_links"] == {
                "runtime_request_id": "request-1",
                "retrieval_trace_id": "trace-1",
                "host_attempt_trace_id": None,
            }
            assert access_trace["spans"]["runtime_client_ms"] >= 0
            assert access_trace["spans"]["mcp_handler_ms"] >= 0
            assert api.recalls[0][1]["limit"] == 3
            assert api.recalls[0][1]["consistency"] == "CANONICAL_REQUIRED"
            rejected_policy = await client.call_tool(
                "milai_recall",
                {"query": "synthetic", "consistency": "EVENTUAL", "limit": 50},
            )
            assert rejected_policy.is_error is True
            rejected = await client.call_tool(
                "milai_recall",
                {"query": "synthetic", "profile": "operator"},
            )
            assert rejected.is_error is True

    asyncio.run(run())


@pytest.mark.parametrize(
    ("status", "fallback_used", "fallback_reason", "abstention_reason"),
    [
        ("OK", False, None, None),
        ("DEGRADED", True, "VECTOR_UNAVAILABLE", None),
        ("ABSTAINED", False, None, "NO_CANDIDATE"),
    ],
)
def test_current_recall_status_and_wire_fields_remain_compatible(
    status: str,
    fallback_used: bool,
    fallback_reason: str | None,
    abstention_reason: str | None,
) -> None:
    class _OutcomeClient(_Client):
        def recall(self, query: str, **options: Any) -> Any:
            result = super().recall(query, **options)
            result.status = status
            result.items = [] if status == "ABSTAINED" else [{"claim_id": "claim-1"}]
            result.degraded_components = ["vector"] if status == "DEGRADED" else []
            result.fallback_used = fallback_used
            result.fallback_reason = fallback_reason
            result.abstention_reason = abstention_reason
            return result

    async def run() -> None:
        server = build_server("reader-lite", _OutcomeClient())  # type: ignore[arg-type]
        async with Client(server, mode="2026-07-28") as client:
            result = await client.call_tool("milai_recall", {"query": "synthetic"})
            assert result.is_error is False
            assert result.structured_content is not None
            payload = result.structured_content
            assert payload["status"] == status
            assert payload["fallback_used"] is fallback_used
            assert payload["fallback_reason"] == fallback_reason
            assert payload["abstention_reason"] == abstention_reason
            assert {
                "items",
                "open_issue_ids",
                "trace_id",
                "consistency",
                "canonical_position",
                "degraded_components",
                "derived_result",
            } <= set(payload)
            assert payload["status"] not in {
                "HIT",
                "PARTIAL",
                "CONTESTED",
                "ABSENT",
                "DENIED",
                "UNAVAILABLE",
            }

    asyncio.run(run())


def test_query_first_target_tool_uses_runtime_contract_without_task_metadata() -> None:
    async def run() -> None:
        api = _Client()
        server = build_server(
            "reader-lite",
            api,  # type: ignore[arg-type]
            default_scope={"project_ids": ["milai"]},
            required_authority="ACTION_SAFE",
            max_limit=3,
        )
        async with Client(server, mode="2026-07-28") as client:
            result = await client.call_tool(
                "milai_memory_resolve",
                {"query": "What is the current release status?"},
            )
            assert result.is_error is False
            assert result.structured_content is not None
            payload = result.structured_content
            assert payload["status"] == "HIT"
            assert payload["memory_intent"] == "REQUIRED"
            assert payload["requirement"] == "EXACT"
            assert payload["trace_id"] == "trace-1"
            assert payload["memory_context"]["schema_version"] == (
                "memory-context-v0.1"
            )
            assert payload["memory_context"]["authority_class"] == (
                "CANONICAL_STATE"
            )
            assert payload["access_trace"]["logical_mcp_calls"] == 1
            assert payload["access_trace"]["automatic_retry_count"] is None
        assert len(api.resolves) == 1
        _query, options = api.resolves[0]
        assert options == {
            "requested_scope": {"project_ids": ["milai"]},
            "required_authority": "ACTION_SAFE",
            "required_freshness": "CURRENT",
            "consistency_mode": "CANONICAL_REQUIRED",
            "budget": {"max_results": 3},
        }
        assert all("task" not in key for key in options)

    asyncio.run(run())


def test_reader_lite_wide_deployment_profile_owns_full_runtime_budget() -> None:
    async def run() -> None:
        api = _Client()
        server = build_server(
            "reader-lite",
            api,  # type: ignore[arg-type]
            max_limit=50,
            resolve_budget_profile="OPENWORKER_USABILITY_WIDE_V01",
        )
        async with Client(server, mode="2026-07-28") as client:
            result = await client.call_tool(
                "milai_memory_resolve",
                {"query": "Recall the current synthetic fact"},
            )
            assert result.is_error is False
            tools = await client.list_tools()
            resolve = next(
                tool for tool in tools.tools if tool.name == "milai_memory_resolve"
            )
            assert set(resolve.input_schema["properties"]) == {
                "query",
                "previous_context_id",
            }
        assert api.resolves[0][1]["budget"] == {
            "max_results": 50,
            "max_candidates": 120,
            "max_context_tokens": 8_192,
            "max_latency_ms": 2_000,
        }

    asyncio.run(run())


def test_reader_lite_wide_v02_prioritizes_usable_context_capacity() -> None:
    async def run() -> None:
        api = _Client()
        server = build_server(
            "reader-lite",
            api,  # type: ignore[arg-type]
            max_limit=50,
            resolve_budget_profile="OPENWORKER_USABILITY_WIDE_V02",
        )
        async with Client(server, mode="2026-07-28") as client:
            result = await client.call_tool(
                "milai_memory_resolve",
                {"query": "Recall the relevant prior information"},
            )
            assert result.is_error is False
        assert api.resolves[0][1]["budget"] == {
            "max_results": 50,
            "max_candidates": 120,
            "max_context_tokens": 16_384,
            "max_latency_ms": 5_000,
        }

    asyncio.run(run())


@pytest.mark.parametrize(
    ("profile", "max_limit", "budget_profile", "message"),
    [
        ("reader-lite", 3, "OPENWORKER_USABILITY_WIDE_V01", "requires max_limit=50"),
        (
            "reader-detail",
            50,
            "OPENWORKER_USABILITY_WIDE_V01",
            "requires reader-lite",
        ),
        ("reader-lite", 50, "MODEL_SELECTED_WIDE", "unknown resolve budget profile"),
    ],
)
def test_resolve_budget_profile_is_exact_and_host_only(
    profile: str,
    max_limit: int,
    budget_profile: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build_server(
            profile,  # type: ignore[arg-type]
            _Client(),  # type: ignore[arg-type]
            max_limit=max_limit,
            resolve_budget_profile=budget_profile,
        )


def test_detail_profile_exact_state_tool_is_policy_bound_and_cost_visible() -> None:
    async def run() -> None:
        api = _Client()
        server = build_server(
            "reader-detail",
            api,  # type: ignore[arg-type]
            default_scope={"project_ids": ["milai"]},
            required_authority="ACTION_SAFE",
            consistency_floor="CANONICAL_REQUIRED",
            max_retries=0,
        )
        async with Client(server, mode="2026-07-28") as client:
            result = await client.call_tool(
                "milai_memory_get",
                {
                    "state_key": {
                        "subject": "project-1",
                        "predicate": "runtime.release.status",
                        "claim_type": "FACT",
                    }
                },
            )
            assert result.is_error is False
            assert result.structured_content is not None
            payload = result.structured_content
            assert payload["schema_version"] == "memory-state-view-v0.1"
            assert payload["status"] == "HIT"
            assert payload["resolution"] == {
                "mode": "CURRENT",
                "valid_at": "2026-08-26T00:00:00+00:00",
                "known_at": "2026-08-26T00:00:00+00:00",
                "addressable": True,
                "reachable": True,
                "correctly_resolved": True,
            }
            assert payload["access_trace"]["structural_cost"] == {
                "auxiliary_llm_calls": 0,
                "embedding_calls": 0,
                "vector_search_calls": 0,
                "reranker_calls": 0,
                "broad_head_scan_calls": 0,
            }
            assert payload["access_trace"]["logical_mcp_calls"] == 1
            assert payload["access_trace"]["automatic_retry_count"] == 0
            invalid = await client.call_tool(
                "milai_memory_get",
                {"claim_id": "claim-1", "requested_scope": {"project_ids": ["attacker"]}},
            )
            assert invalid.is_error is True
        assert api.state_reads == [
            {
                "claim_id": None,
                "state_key": {
                    "subject": "project-1",
                    "predicate": "runtime.release.status",
                    "claim_type": "FACT",
                },
                "requested_scope": {"project_ids": ["milai"]},
                "required_authority": "ACTION_SAFE",
                "consistency_mode": "CANONICAL_REQUIRED",
            }
        ]

    asyncio.run(run())


def test_detail_memory_resolve_forwards_question_reference_time() -> None:
    async def run() -> None:
        api = _Client()
        server = build_server("reader-detail", api)  # type: ignore[arg-type]
        async with Client(server, mode="2026-07-28") as client:
            result = await client.call_tool(
                "milai_memory_resolve",
                {
                    "query": "Recall my March appointments",
                    "reference_time": "2023-03-27T23:35:00Z",
                },
            )
            assert result.is_error is False
        assert api.resolves[0][1]["reference_time"] == "2023-03-27T23:35:00Z"

    asyncio.run(run())


def test_detail_memory_resolve_forwards_bounded_latency_budget() -> None:
    async def run() -> None:
        api = _Client()
        server = build_server("reader-detail", api)  # type: ignore[arg-type]
        async with Client(server, mode="2026-07-28") as client:
            result = await client.call_tool(
                "milai_memory_resolve",
                {
                    "query": "Recall the current status",
                    "max_latency_ms": 2_000,
                },
            )
            assert result.is_error is False
        assert api.resolves[0][1]["budget"] == {
            "max_results": 3,
            "max_latency_ms": 2_000,
        }

        tools = {tool.name: tool for tool in await server.list_tools()}
        latency_schema = tools["milai_memory_resolve"].input_schema["properties"][
            "max_latency_ms"
        ]["anyOf"][0]
        assert latency_schema["minimum"] == 25
        assert latency_schema["maximum"] == 2_000

    asyncio.run(run())


def test_oversized_resolve_compacts_duplicate_proof_material_without_losing_gate() -> None:
    operands = [
        {
            "slot": "ITEM_COUNT",
            "value": ordinal,
            "unit": "ITEM",
            "evidence_id": f"evidence-{ordinal}",
            "source_ref": f"memory://session/s-{ordinal}/turn/0",
            "evidence_span": {"text": "x" * 2_800, "start": 0, "end": 2_800},
            "requirement_binding": {
                "status": "MATCH",
                "authority_class": "EVIDENCE_ONLY",
                "canonical_mutation": False,
            },
        }
        for ordinal in range(7)
    ]
    payload = {
        "status": "PARTIAL",
        "trace_id": "trace-1",
        "canonical_position": {"evidence_watermark": 7},
        "items": [],
        "memory_context": {"text": "Reader context", "windows": []},
        "context_receipt": {"canonical_mutation": False},
        "derived_result": {
            "status": "PARTIAL",
            "reason": "OPERAND_AMBIGUOUS",
            "canonical_mutation": False,
            "completeness": {"bounded_scan_complete": False},
            "operands": operands,
            "trace": {
                "slots": [{"name": "ITEM_COUNT", "operands": operands}],
                "applicability": [
                    {
                        "evidence_id": f"evidence-{ordinal}",
                        "source_turn_ref": f"memory://session/s-{ordinal}/turn/0",
                        "accepted": True,
                        "reason": "MATCH",
                        "span": {"text": "x" * 500},
                    }
                    for ordinal in range(7)
                ],
            },
        },
        "search_trace": {
            "formation_projection": {"status": "NO_MATCH"},
            "terminal_sufficiency_decision": {"status": "PARTIAL"},
            "acquisition_capability": {"material": "a" * 6_000},
            "acquisition_plan": {"material": "b" * 6_000},
            "acquisition_probe_dispositions": [{"material": "c" * 6_000}],
            "sufficiency_decisions": [{"material": "d" * 6_000}],
        },
    }
    original = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    assert len(original) > server_module._MAX_OUTPUT_BYTES

    compact = server_module._bounded_memory_resolve(payload)

    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    assert len(encoded) <= server_module._MAX_OUTPUT_BYTES
    assert compact["status"] == "PARTIAL"
    assert compact["canonical_position"] == payload["canonical_position"]
    assert compact["memory_context"] == payload["memory_context"]
    assert compact["context_receipt"] == payload["context_receipt"]
    assert compact["derived_result"]["completeness"] == {
        "bounded_scan_complete": False
    }
    assert compact["derived_result"]["operands"] == operands
    pointer = compact["derived_result"]["trace"]["slots"][0]["operands"][0]
    assert pointer["evidence_id"] == "evidence-0"
    assert pointer["wire_operand_ordinal"] == 0
    assert pointer["wire_operand_sha256"] == server_module._wire_sha256(operands[0])
    assert compact["search_trace"]["formation_projection"] == {"status": "NO_MATCH"}
    assert "acquisition_plan" not in compact["search_trace"]
    receipt = compact["mcp_output_compaction"]
    assert receipt["full_payload_sha256"] == hashlib.sha256(original).hexdigest()
    assert receipt["operator_result_sha256"] == server_module._wire_sha256(
        payload["derived_result"]
    )
    assert receipt["operator_operand_material"] == "FULL"
    assert receipt["strict_status_preserved"] is True
    assert receipt["strict_completeness_preserved"] is True
    assert receipt["compacted_bytes"] == len(encoded)
    assert "acquisition_plan" in payload["search_trace"]


def test_extreme_resolve_uses_digest_operand_pointers_before_truncating() -> None:
    operands = [
        {
            "slot": "MATCHING_EVENTS_IN_RANGE",
            "evidence_id": f"evidence-{ordinal}",
            "source_ref": f"memory://session/s-{ordinal}/turn/0",
            "span": {"text": "z" * 5_000},
        }
        for ordinal in range(30)
    ]
    payload = {
        "status": "PARTIAL",
        "trace_id": "trace-extreme",
        "canonical_position": {"evidence_watermark": 30},
        "derived_result": {
            "status": "PARTIAL",
            "canonical_mutation": False,
            "completeness": {"bounded_scan_complete": False},
            "operands": operands,
            "trace": {"slots": [{"name": "RANGE", "operands": operands}]},
        },
        "search_trace": {"formation_projection": {"status": "NO_MATCH"}},
    }

    compact = server_module._bounded_memory_resolve(payload)

    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    assert len(encoded) <= server_module._MAX_OUTPUT_BYTES
    assert compact["status"] == "PARTIAL"
    assert compact["derived_result"]["completeness"] == {
        "bounded_scan_complete": False
    }
    assert compact["derived_result"]["operands"][0] == {
        "slot": "MATCHING_EVENTS_IN_RANGE",
        "evidence_id": "evidence-0",
        "source_ref": "memory://session/s-0/turn/0",
        "wire_operand_ordinal": 0,
        "wire_operand_sha256": server_module._wire_sha256(operands[0]),
    }
    receipt = compact["mcp_output_compaction"]
    assert receipt["operator_operand_material"] == "DIGEST_POINTERS"
    assert "derived_result.operands" in receipt["compacted_fields"]
    assert receipt["compacted_bytes"] == len(encoded)


def test_progressive_raw_resolve_compacts_diagnostics_without_losing_context() -> None:
    items = [
        {
            "kind": "EVIDENCE_OBSERVATION",
            "canonical": False,
            "evidence_id": f"evidence-{ordinal}",
            "evidence_ids": [f"evidence-{ordinal}"],
            "source_ref": f"memory://session/s-{ordinal}/turn/0",
            "source_refs": [f"memory://session/s-{ordinal}/turn/0"],
            "relevance_score": 1.0 - ordinal / 100,
            "payload": {"content": "evidence " + "x" * 1_000},
        }
        for ordinal in range(12)
    ]
    payload = {
        "status": "HIT",
        "trace_id": "trace-progressive",
        "canonical_position": {"evidence_watermark": 12},
        "items": items,
        "memory_context": {
            "schema_version": "memory-context-v0.1",
            "text": "Reader context\n" + "c" * 12_000,
            "windows": [],
        },
        "context_receipt": {"canonical_mutation": False},
        "search_trace": {
            "schema_version": "progressive-l1-v0.1",
            "formation_projection": {"status": "NO_MATCH"},
            "terminal_sufficiency_decision": {"status": "PARTIAL"},
            "candidate_observations": [
                {"ordinal": ordinal, "diagnostic": "d" * 5_000}
                for ordinal in range(20)
            ],
        },
    }
    assert len(json.dumps(payload, sort_keys=True).encode()) > server_module._MAX_OUTPUT_BYTES

    compact = server_module._bounded_memory_resolve(payload)

    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    assert len(encoded) <= server_module._MAX_OUTPUT_BYTES
    assert compact["status"] == "HIT"
    assert compact["items"] == items
    assert compact["memory_context"] == payload["memory_context"]
    assert compact["context_receipt"] == payload["context_receipt"]
    assert compact["search_trace"]["formation_projection"] == {"status": "NO_MATCH"}
    assert "candidate_observations" not in compact["search_trace"]
    receipt = compact["mcp_output_compaction"]
    assert "search_trace.compacted_diagnostics" in receipt["compacted_fields"]
    assert receipt["compacted_bytes"] == len(encoded)


def test_extreme_raw_items_keep_identity_score_and_digest_instead_of_truncating() -> None:
    items = [
        {
            "kind": "EVIDENCE_OBSERVATION",
            "canonical": False,
            "evidence_id": f"evidence-{ordinal}",
            "source_ref": f"memory://session/s-{ordinal}/turn/0",
            "relevance_score": 1.0 - ordinal / 100,
            "source_context": {
                "session_id": f"session-{ordinal}",
                "turn_id": f"session-{ordinal}:turn:{ordinal}",
                "turn_ordinal": ordinal,
                "round_id": f"session-{ordinal}:round:{ordinal // 2}",
                "round_ordinal": ordinal // 2,
                "previous_turn_id": "previous-" + "p" * 3_000,
                "next_turn_id": "next-" + "n" * 3_000,
            },
            "valid_time": {"from": "v" * 1_000, "to": None},
            "transaction_time": {"from": "t" * 1_000, "to": None},
            "payload": {"content": "z" * 10_000},
        }
        for ordinal in range(12)
    ]
    payload = {
        "status": "HIT",
        "trace_id": "trace-extreme-raw",
        "canonical_position": {"evidence_watermark": 12},
        "items": items,
        "memory_context": {
            "schema_version": "memory-context-v0.1",
            "text": "Exact Reader context",
            "windows": [],
        },
        "context_receipt": {"canonical_mutation": False},
        "search_trace": {"formation_projection": {"status": "NO_MATCH"}},
    }

    compact = server_module._bounded_memory_resolve(payload)

    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    assert len(encoded) <= server_module._MAX_OUTPUT_BYTES
    assert compact["status"] == "HIT"
    assert compact["memory_context"] == payload["memory_context"]
    assert compact["context_receipt"] == payload["context_receipt"]
    for ordinal, item in enumerate(compact["items"]):
        assert item["evidence_id"] == f"evidence-{ordinal}"
        assert item["source_ref"] == f"memory://session/s-{ordinal}/turn/0"
        assert item["relevance_score"] == 1.0 - ordinal / 100
        assert item["wire_item_sha256"] == server_module._wire_sha256(items[ordinal])
        assert "payload" not in item
        assert "evidence_ids" not in item
        assert "source_refs" not in item
        assert "valid_time" not in item
        assert "transaction_time" not in item
        assert "source_context" not in item
        assert set(item) == {
            "kind",
            "canonical",
            "evidence_id",
            "source_ref",
            "relevance_score",
            "wire_item_sha256",
        }
    assert compact["mcp_wire_receipts"]["compacted_raw_items"] == {
        "sha256": server_module._wire_sha256(items),
        "item_count": 12,
        "preserved_fields": [
            "kind",
            "canonical",
            "evidence_id",
            "source_ref",
            "relevance_score",
        ],
        "wire_representation": (
            "CONSUMER_FIELDS_PER_ITEM_PLUS_ITEM_AND_LIST_DIGESTS"
        ),
    }
    receipt = compact["mcp_output_compaction"]
    assert "items.raw_evidence_payloads" in receipt["compacted_fields"]
    assert receipt["compacted_bytes"] == len(encoded)


def test_extreme_progressive_context_digests_replayable_compile_diagnostics() -> None:
    items = [
        {
            "kind": "EVIDENCE_OBSERVATION",
            "canonical": False,
            "evidence_id": f"evidence-{ordinal}",
            "source_ref": f"memory://session/s-{ordinal}/turn/0",
            "relevance_score": 1.0 - ordinal / 100,
            "payload": {"content": "z" * 10_000},
        }
        for ordinal in range(12)
    ]
    expansion_trace = [
        {
            "source_evidence_id": f"evidence-{ordinal % 12}",
            "expanded_evidence_ids": [f"evidence-{(ordinal + 1) % 12}"],
            "diagnostic": "e" * 1_000,
        }
        for ordinal in range(40)
    ]
    windows = [
        {
            "window_id": f"window-{ordinal}",
            "session_id": f"session-{ordinal}",
            "evidence_ids": [f"evidence-{ordinal}"],
            "source_turn_refs": [f"memory://session/s-{ordinal}/turn/0"],
            "expansions": [],
            "text": "w" * 3_000,
            "truncated": False,
        }
        for ordinal in range(4)
    ]
    compile_trace = {
        "compiler_version": "progressive-v0.1",
        "reader_readiness": "READY",
        "atomic_unit_truncation_count": 0,
        "long_turn_split_count": 0,
        "rank_first_prefix_violation_count": 0,
        "whole_unit_admission": True,
        "hidden_model_calls": 0,
        "canonical_mutation": False,
        "decision_layer_digests": {f"layer-{index}": "a" * 64 for index in range(8)},
        "expansion_trace": expansion_trace,
        "omitted_unit_reasons": {
            f"unit-{index}": "CONDITIONAL_BUDGET_EXHAUSTED" for index in range(30)
        },
        "plan_omitted_units": [
            {"unit_id": f"unit-{index}", "diagnostic": "p" * 500} for index in range(20)
        ],
        "conditional_activation_thresholds": {
            f"unit-{index}": {"threshold": index, "diagnostic": "t" * 100}
            for index in range(30)
        },
        "conditional_unit_order": [f"unit-{index}" for index in range(60)],
    }
    payload = {
        "status": "HIT",
        "trace_id": "trace-progressive-compile",
        "canonical_position": {"evidence_watermark": 12},
        "items": items,
        "memory_context": {
            "schema_version": "memory-context-v0.1",
            "text": "Reader context\n" + "c" * 12_000,
            "windows": windows,
            "compile_trace": compile_trace,
        },
        "context_receipt": {
            "canonical_mutation": False,
            "receipt_mapping": [
                {
                    "alias": f"E{ordinal + 1}",
                    "evidence_ids": [f"evidence-{ordinal}"],
                    "source_turn_refs": [f"memory://session/s-{ordinal}/turn/0"],
                }
                for ordinal in range(4)
            ],
        },
        "search_trace": {"formation_projection": {"status": "NO_MATCH"}},
    }

    compact = server_module._bounded_memory_resolve(payload)

    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    assert len(encoded) <= server_module._MAX_OUTPUT_BYTES
    assert compact["status"] == "HIT"
    assert compact["memory_context"]["text"] == payload["memory_context"]["text"]
    assert compact["memory_context"]["windows"] == windows
    assert compact["context_receipt"] == payload["context_receipt"]
    wire_trace = compact["memory_context"]["compile_trace"]
    assert wire_trace["decision_layer_digests"] == compile_trace["decision_layer_digests"]
    assert wire_trace["atomic_unit_truncation_count"] == 0
    assert wire_trace["whole_unit_admission"] is True
    for field in (
        "expansion_trace",
        "omitted_unit_reasons",
        "plan_omitted_units",
        "conditional_activation_thresholds",
        "conditional_unit_order",
    ):
        assert field not in wire_trace
        field_receipt = wire_trace["mcp_wire_receipts"]["compacted_diagnostics"][field]
        assert field_receipt["sha256"] == server_module._wire_sha256(compile_trace[field])
        assert field_receipt["item_count"] == len(compile_trace[field])
    receipt = compact["mcp_output_compaction"]
    assert "memory_context.compile_trace.compacted_diagnostics" in receipt["compacted_fields"]
    assert receipt["compacted_bytes"] == len(encoded)
    assert payload["memory_context"]["compile_trace"]["expansion_trace"] == expansion_trace


def test_compile_diagnostics_can_be_compacted_without_raw_evidence_items() -> None:
    expansion_trace = [
        {"ordinal": ordinal, "replayable_diagnostic": "x" * 1_000} for ordinal in range(80)
    ]
    payload = {
        "status": "ABSTAINED",
        "trace_id": "trace-budget-infeasible",
        "canonical_position": {"evidence_watermark": 0},
        "items": [],
        "memory_context": {
            "schema_version": "memory-context-v0.1",
            "text": "MILAI_MEMORY_DATA_BEGIN\nmemory_status=ABSTAINED\nMILAI_MEMORY_DATA_END",
            "windows": [],
            "compile_trace": {
                "reader_readiness": "BUDGET_INFEASIBLE",
                "atomic_unit_truncation_count": 0,
                "whole_unit_admission": True,
                "expansion_trace": expansion_trace,
            },
        },
        "context_receipt": None,
    }

    compact = server_module._bounded_memory_resolve(payload)

    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    assert len(encoded) <= server_module._MAX_OUTPUT_BYTES
    assert compact["status"] == "ABSTAINED"
    assert compact["items"] == []
    assert compact["context_receipt"] is None
    wire_trace = compact["memory_context"]["compile_trace"]
    assert wire_trace["reader_readiness"] == "BUDGET_INFEASIBLE"
    assert wire_trace["atomic_unit_truncation_count"] == 0
    assert "expansion_trace" not in wire_trace
    assert wire_trace["mcp_wire_receipts"]["compacted_diagnostics"]["expansion_trace"] == {
        "sha256": server_module._wire_sha256(expansion_trace),
        "item_count": len(expansion_trace),
    }


def test_large_reader_context_compacts_redundant_window_presentation() -> None:
    windows = [
        {
            "window_id": f"window-{ordinal}",
            "session_id": f"session-{ordinal}",
            "evidence_ids": [f"evidence-{ordinal}"],
            "source_turn_refs": [f"memory://session/{ordinal}/turn/0"],
            "speakers": ["USER"],
            "observed_at": "2026-09-01T00:00:00Z",
            "text": "duplicated Reader prose " + "w" * 3_500,
            "source_rank": ordinal + 1,
            "query_overlap": 1,
            "answer_signal": True,
            "requirement_priority": False,
            "truncated": False,
            "expansions": [
                {
                    "trigger": "SAME_ROUND",
                    "source_evidence_id": f"evidence-{ordinal}",
                    "expanded_evidence_ids": [],
                    "cost": 0,
                    "coverage_delta": 0,
                    "stop_reason": "NO_APPLICABLE_NEIGHBOR",
                }
            ],
        }
        for ordinal in range(12)
    ]
    reader_text = "Reader context\n" + "r" * 28_000
    payload = {
        "status": "HIT",
        "trace_id": "trace-window-compaction",
        "canonical_position": {"evidence_watermark": 12},
        "items": [],
        "memory_context": {
            "schema_version": "memory-context-v0.1",
            "text": reader_text,
            "windows": windows,
            "compile_trace": {
                "reader_readiness": "READY",
                "atomic_unit_truncation_count": 0,
                "long_turn_split_count": 0,
                "rank_first_prefix_violation_count": 0,
                "whole_unit_admission": True,
            },
        },
        "context_receipt": {
            "canonical_mutation": False,
            "receipt_mapping": [
                {"alias": f"E{ordinal + 1}", "evidence_ids": [f"evidence-{ordinal}"]}
                for ordinal in range(12)
            ],
        },
    }
    assert len(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()) > (
        server_module._MAX_OUTPUT_BYTES
    )

    compact = server_module._bounded_memory_resolve(payload)

    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    assert len(encoded) <= server_module._MAX_OUTPUT_BYTES
    assert compact["status"] == "HIT"
    assert compact["memory_context"]["text"] == reader_text
    assert compact["context_receipt"] == payload["context_receipt"]
    for ordinal, window in enumerate(compact["memory_context"]["windows"]):
        assert window["window_id"] == f"window-{ordinal}"
        assert window["session_id"] == f"session-{ordinal}"
        assert window["evidence_ids"] == [f"evidence-{ordinal}"]
        assert "source_turn_refs" not in window
        assert window["truncated"] is False
        assert window["expansions"] == windows[ordinal]["expansions"]
        assert "text" not in window
    wire_receipt = compact["memory_context"]["compile_trace"]["mcp_wire_receipts"]
    assert wire_receipt["compacted_windows"] == {
        "sha256": server_module._wire_sha256(windows),
        "item_count": 12,
        "source_turn_ref_count": 12,
        "wire_representation": "IDENTITY_SESSION_ADJACENCY_PLUS_AGGREGATE_DIGEST",
    }
    compaction = compact["mcp_output_compaction"]
    assert "memory_context.windows.redundant_presentation" in compaction[
        "compacted_fields"
    ]
    assert compaction["compacted_bytes"] == len(encoded)


def test_extreme_top_level_plan_and_sufficiency_use_replayable_proof_pointers() -> None:
    reader_text = "Reader context\n" + "r" * 20_000
    query_ir = {
        "schema_version": "memory-query-ir-v0.2",
        "mode": "EXECUTABLE",
        "answer_shape": "LOOKUP",
        "completeness": "ALL_REQUIRED_BINDINGS",
        "requirements": [
            {"slot_id": f"slot-{ordinal}", "diagnostic": "q" * 1_500}
            for ordinal in range(20)
        ],
    }
    sufficiency = {
        "schema_version": "sufficiency-decision-v0.1",
        "status": "COMPLETE",
        "covered_slots": ["LOOKUP_ANSWER"],
        "missing_slots": [],
        "stop_reason": "REQUIREMENT_SATISFIED",
        "proof": [
            {"candidate": ordinal, "diagnostic": "p" * 800}
            for ordinal in range(25)
        ],
    }
    payload = {
        "status": "HIT",
        "trace_id": "trace-top-level-proof",
        "canonical_position": {"evidence_watermark": 1},
        "items": [],
        "memory_query_ir": query_ir,
        "sufficiency_decision": sufficiency,
        "search_trace": {
            "terminal_sufficiency_decision": sufficiency,
            "formation_projection": {"status": "NO_MATCH"},
        },
        "memory_context": {
            "schema_version": "memory-context-v0.1",
            "text": reader_text,
            "windows": [],
            "compile_trace": {
                "reader_readiness": "READY",
                "atomic_unit_truncation_count": 0,
                "whole_unit_admission": True,
            },
        },
        "context_receipt": {
            "canonical_mutation": False,
            "receipt_mapping": [],
        },
    }
    assert len(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()) > (
        server_module._MAX_OUTPUT_BYTES
    )

    compact = server_module._bounded_memory_resolve(payload)

    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    assert len(encoded) <= server_module._MAX_OUTPUT_BYTES
    assert compact["status"] == "HIT"
    assert compact["memory_context"]["text"] == reader_text
    assert compact["context_receipt"] == payload["context_receipt"]
    compact_ir = compact["memory_query_ir"]
    assert compact_ir["mode"] == "EXECUTABLE"
    assert compact_ir["completeness"] == "ALL_REQUIRED_BINDINGS"
    assert compact_ir["wire_proof_sha256"] == server_module._wire_sha256(query_ir)
    assert "requirements" not in compact_ir
    compact_decision = compact["sufficiency_decision"]
    assert compact_decision["status"] == "COMPLETE"
    assert compact_decision["covered_slots"] == ["LOOKUP_ANSWER"]
    assert compact_decision["wire_proof_sha256"] == server_module._wire_sha256(
        sufficiency
    )
    assert "proof" not in compact_decision
    search_decision = compact["search_trace"]["terminal_sufficiency_decision"]
    assert search_decision["status"] == "COMPLETE"
    assert search_decision["wire_proof_sha256"] == server_module._wire_sha256(
        sufficiency
    )
    receipts = compact["mcp_wire_receipts"]["compacted_top_level_proof"]
    assert receipts["memory_query_ir"]["sha256"] == server_module._wire_sha256(
        query_ir
    )
    assert receipts["sufficiency_decision"]["sha256"] == (
        server_module._wire_sha256(sufficiency)
    )
    compaction = compact["mcp_output_compaction"]
    assert "memory_query_ir.replayable_plan" in compaction["compacted_fields"]
    assert "sufficiency_decision.replayable_proof" in compaction[
        "compacted_fields"
    ]
    assert compaction["compacted_bytes"] == len(encoded)


def test_extreme_operator_trace_uses_terminal_summary_and_digest() -> None:
    applicability = [
        {
            "evidence_id": f"evidence-{ordinal}",
            "source_turn_ref": (
                f"memory://session/session-{ordinal}/turn/{ordinal}?" + "s" * 220
            ),
            "slot": "MATCHING_EVENTS_IN_RANGE",
            "accepted": ordinal < 7,
            "reason": "INCLUDE" if ordinal < 7 else "EXCLUDE_OUT_OF_RANGE",
            "span": "candidate span " + "a" * 800,
        }
        for ordinal in range(180)
    ]
    operands = [
        {
            "slot": "MATCHING_EVENTS_IN_RANGE",
            "evidence_id": f"evidence-{ordinal}",
            "source_ref": f"memory://session/session-{ordinal}/turn/{ordinal}",
            "value": ordinal,
        }
        for ordinal in range(7)
    ]
    completeness = {
        "required_slots": ["MATCHING_EVENTS_IN_RANGE"],
        "filled_slots": ["MATCHING_EVENTS_IN_RANGE"],
        "bounded_scan_complete": True,
        "source_partition_closed": True,
        "projection_watermark_covered": True,
        "unresolved_reasons": [],
    }
    payload = {
        "status": "HIT",
        "trace_id": "trace-operator-proof",
        "canonical_position": {"evidence_watermark": 180},
        "items": [],
        "memory_context": {
            "schema_version": "memory-context-v0.1",
            "text": "Exact Reader context\n" + "r" * 15_000,
            "windows": [],
            "compile_trace": {
                "reader_readiness": "READY",
                "atomic_unit_truncation_count": 0,
                "whole_unit_admission": True,
            },
        },
        "context_receipt": {"canonical_mutation": False},
        "derived_result": {
            "kind": "EVIDENCE_COMPOSITION_RESULT",
            "status": "COMPLETE",
            "operator": "TEMPORAL_COUNT_DISTINCT",
            "value": 7,
            "unit": "EVENTS",
            "operands": operands,
            "evidence_refs": [f"evidence-{ordinal}" for ordinal in range(7)],
            "completeness": completeness,
            "hidden_model_calls": 0,
            "canonical_mutation": False,
            "trace": {
                "query_spec": {
                    "schema_version": "query-spec-v0.1",
                    "answer_type": "SCALAR",
                    "operator": "TEMPORAL_COUNT_DISTINCT",
                    "required_slots": ["MATCHING_EVENTS_IN_RANGE"],
                    "completeness": "ALL_MATCHES_IN_RANGE",
                },
                "slots": [
                    {
                        "name": "MATCHING_EVENTS_IN_RANGE",
                        "status": "FILLED",
                        "operands": operands,
                        "unresolved_reason": None,
                    }
                ],
                "applicability": applicability,
                "retrieval_attempts": 1,
                "expansion": ["BOUNDED_TIME_RANGE_SCAN"],
                "join": "DISTINCT_EVENT_DEDUP",
                "terminal_reason": "COMPLETE",
                "top_k_used_as_completeness": False,
                "hidden_model_calls": 0,
                "canonical_mutation": False,
            },
        },
    }
    original = deepcopy(payload)
    assert len(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()) > (
        server_module._MAX_OUTPUT_BYTES
    )

    compact = server_module._bounded_memory_resolve(payload)

    encoded = json.dumps(compact, ensure_ascii=False, sort_keys=True).encode()
    assert len(encoded) <= server_module._MAX_OUTPUT_BYTES
    assert compact["status"] == "HIT"
    assert compact["memory_context"]["text"] == original["memory_context"]["text"]
    assert compact["context_receipt"] == original["context_receipt"]
    derived = compact["derived_result"]
    assert derived["status"] == "COMPLETE"
    assert derived["value"] == 7
    assert derived["completeness"] == completeness
    trace = derived["trace"]
    assert trace["terminal_reason"] == "COMPLETE"
    assert trace["query_spec"] == original["derived_result"]["trace"]["query_spec"]
    assert trace["slots"][0]["name"] == "MATCHING_EVENTS_IN_RANGE"
    assert trace["slots"][0]["status"] == "FILLED"
    assert trace["slots"][0]["operands"] == []
    assert trace["slots"][0]["wire_operand_count"] == 7
    assert trace["applicability"] == []
    assert trace["wire_applicability_summary"] == {
        "item_count": 180,
        "accepted_count": 7,
        "rejected_count": 173,
        "reason_counts": {"EXCLUDE_OUT_OF_RANGE": 173, "INCLUDE": 7},
        "sha256": trace["wire_applicability_summary"]["sha256"],
        "wire_representation": "SUMMARY_AND_SHA256",
    }
    assert len(trace["wire_applicability_summary"]["sha256"]) == 64
    receipts = trace["mcp_wire_receipts"]["compacted_operator_trace"]
    assert receipts["applicability"]["item_count"] == 180
    assert receipts["slots"]["item_count"] == 1
    compaction = compact["mcp_output_compaction"]
    assert "derived_result.trace.replayable_operator_proof" in compaction[
        "compacted_fields"
    ]
    assert compaction["strict_status_preserved"] is True
    assert compaction["strict_completeness_preserved"] is True
    assert compaction["compacted_bytes"] == len(encoded)
    assert payload == original


def test_compile_compaction_does_not_remove_reader_context_to_fit_wire_limit() -> None:
    payload = {
        "status": "HIT",
        "trace_id": "trace-reader-context-too-large",
        "canonical_position": {"evidence_watermark": 1},
        "items": [],
        "memory_context": {
            "schema_version": "memory-context-v0.1",
            "text": "r" * 70_000,
            "windows": [],
            "compile_trace": {
                "atomic_unit_truncation_count": 0,
                "whole_unit_admission": True,
            },
        },
        "context_receipt": {"canonical_mutation": False},
    }

    compact = server_module._bounded_memory_resolve(payload)

    assert compact["status"] == "TRUNCATED"
    assert compact["reason"] == "MCP_OUTPUT_LIMIT"
    assert compact["schema_version"] == "mcp-output-limit-v0.1"
    assert compact["original_bytes"] > server_module._MAX_OUTPUT_BYTES
    assert compact["compacted_bytes"] > server_module._MAX_OUTPUT_BYTES
    diagnostics = compact["wire_diagnostics"]
    assert diagnostics["top_level_field_bytes"]["memory_context"] > (
        server_module._MAX_OUTPUT_BYTES
    )
    assert diagnostics["memory_context_field_bytes"]["text"] > (
        server_module._MAX_OUTPUT_BYTES
    )
    assert len(compact["full_payload_sha256"]) == 64


def test_wide_v02_wire_budget_preserves_large_reader_context() -> None:
    payload = {
        "status": "PARTIAL",
        "trace_id": "trace-wide-reader-context",
        "canonical_position": {"evidence_watermark": 1},
        "items": [],
        "memory_context": {
            "schema_version": "memory-context-v0.1",
            "text": "r" * 70_000,
            "windows": [],
            "compile_trace": {
                "atomic_unit_truncation_count": 0,
                "whole_unit_admission": True,
            },
        },
        "context_receipt": {"canonical_mutation": False},
    }

    result = server_module._bounded_memory_resolve(
        payload,
        max_output_bytes=server_module._WIDE_MAX_OUTPUT_BYTES,
    )

    assert result == payload
    assert len(json.dumps(result, sort_keys=True).encode()) > (
        server_module._MAX_OUTPUT_BYTES
    )
    assert len(json.dumps(result, sort_keys=True).encode()) <= (
        server_module._WIDE_MAX_OUTPUT_BYTES
    )


def test_detail_profile_resolve_forwards_one_composable_state_address() -> None:
    async def run() -> None:
        api = _Client()
        server = build_server(
            "reader-detail",
            api,  # type: ignore[arg-type]
            default_scope={"project_ids": ["milai"]},
            required_authority="ACTION_SAFE",
            max_limit=3,
        )
        async with Client(server, mode="2026-07-28") as client:
            result = await client.call_tool(
                "milai_memory_resolve",
                {
                    "query": "Read the exact current release state",
                    "entities": ["project-1"],
                    "memory_types": ["FACT"],
                    "state_key": {
                        "subject": "project-1",
                        "predicate": "runtime.release.status",
                        "claim_type": "FACT",
                    },
                },
            )
            assert result.is_error is False
        assert len(api.resolves) == 1
        assert api.resolves[0][1]["state_keys"] == [
            {
                "subject": "project-1",
                "predicate": "runtime.release.status",
                "claim_type": "FACT",
            }
        ]
        assert api.resolves[0][1]["budget"] == {"max_results": 3}
        assert api.resolves[0][1]["entities"] == ["project-1"]
        assert api.resolves[0][1]["memory_types"] == ["FACT"]

    asyncio.run(run())


def test_detail_profile_forwards_optional_task_context_as_narrowing_hints() -> None:
    async def run() -> None:
        api = _Client()
        server = build_server(
            "reader-detail",
            api,  # type: ignore[arg-type]
            default_scope={"project_ids": ["milai"]},
            required_authority="ACTION_SAFE",
            max_limit=3,
        )
        async with Client(server, mode="2026-07-28") as client:
            result = await client.call_tool(
                "milai_memory_resolve",
                {
                    "query": "Recall the release state",
                    "task_context": {
                        "project_ids": ["milai"],
                        "entities": ["release-alpha"],
                        "memory_types": ["PROJECT_STATE"],
                        "action_risk": "HIGH",
                    },
                },
            )
            assert result.is_error is False
        assert api.resolves[0][1]["task_context"] == {
            "project_ids": ["milai"],
            "entities": ["release-alpha"],
            "memory_types": ["PROJECT_STATE"],
            "action_risk": "HIGH",
        }

        tools = {tool.name: tool for tool in await server.list_tools()}
        schema = tools["milai_memory_resolve"].input_schema
        assert "task_context" in schema["properties"]
        task_ref = schema["properties"]["task_context"]["anyOf"][0]["$ref"]
        task_name = task_ref.rsplit("/", 1)[-1]
        task_schema = schema["$defs"][task_name]
        assert task_schema["additionalProperties"] is False
        assert set(task_schema["properties"]) == {
            "project_ids",
            "entities",
            "memory_types",
            "action_risk",
        }

    asyncio.run(run())


@pytest.mark.parametrize(
    ("error", "status", "reason"),
    [
        (
            AuthorizationError("denied", code="CAPABILITY_REQUIRED"),
            "DENIED",
            "CAPABILITY_OR_SCOPE_DENIED",
        ),
        (
            UnavailableError("down", code="ENDPOINT_UNAVAILABLE", retryable=True),
            "UNAVAILABLE",
            "ENDPOINT_UNAVAILABLE",
        ),
    ],
)
def test_query_first_target_tool_returns_typed_boundary_failures(
    error: Exception, status: str, reason: str
) -> None:
    class _FailingClient(_Client):
        def resolve_memory(self, query: str, **options: Any) -> Any:
            del query, options
            raise error

    async def run() -> None:
        server = build_server("reader-lite", _FailingClient())  # type: ignore[arg-type]
        async with Client(server, mode="2026-07-28") as client:
            result = await client.call_tool(
                "milai_memory_resolve", {"query": "Recall the current status"}
            )
            assert result.is_error is False
            assert result.structured_content is not None
            assert result.structured_content["status"] == status
            assert result.structured_content["abstention_reason"] == reason
            assert result.structured_content["items"] == []
            assert result.structured_content["memory_intent"] == "REQUIRED"
            assert result.structured_content["requirement"] == "SEARCH"
            assert result.structured_content["availability"] == (
                "UNAVAILABLE" if status == "UNAVAILABLE" else "AVAILABLE"
            )

    asyncio.run(run())


def test_host_owned_as_of_is_forwarded_without_expanding_tool_schema() -> None:
    async def run() -> None:
        api = _Client()
        as_of = datetime.fromisoformat("2023-05-02T08:12:00+00:00")
        server = build_server("reader-lite", api, default_as_of=as_of)  # type: ignore[arg-type]
        async with Client(server, mode="2026-07-28") as client:
            result = await client.call_tool("milai_recall", {"query": "latest transport"})
            assert result.is_error is False
            assert api.recalls[0][1]["as_of"] == as_of.isoformat()
            resolved = await client.call_tool(
                "milai_memory_resolve", {"query": "latest transport"}
            )
            assert resolved.is_error is False
            assert api.resolves[0][1]["reference_time"] == as_of.isoformat()
            tools = await client.list_tools()
            recall = next(tool for tool in tools.tools if tool.name == "milai_recall")
            assert set(recall.input_schema["properties"]) == {"query"}
            resolve = next(
                tool for tool in tools.tools if tool.name == "milai_memory_resolve"
            )
            assert set(resolve.input_schema["properties"]) == {
                "query",
                "previous_context_id",
            }

    asyncio.run(run())


@pytest.mark.parametrize(
    "reason",
    [
        "RETRIEVAL_CONTINUATION_UNAVAILABLE",
        "RETRIEVAL_CONTINUATION_QUERY_MISMATCH",
        "RETRIEVAL_CONTINUATION_REQUEST_MISMATCH",
        "GENERATION_LIMIT_REACHED",
        "SUCCESSOR_LIMIT_REACHED",
        "ROOT_STATE_LIMIT_REACHED",
        "OPERATION_CONFLICT",
    ],
)
def test_continuation_conflict_is_an_actionable_mcp_tool_error(reason: str) -> None:
    class _ConflictingClient(_Client):
        def resolve_memory(self, query: str, **options: Any) -> Any:
            del query, options
            raise ConflictError(
                "continuation unavailable",
                code=reason,
                status_code=409,
            )

    async def run() -> None:
        server = build_server("reader-lite", _ConflictingClient())  # type: ignore[arg-type]
        async with Client(server, mode="2026-07-28") as client:
            result = await client.call_tool(
                "milai_memory_resolve",
                {
                    "query": "Recall the current status",
                    "previous_context_id": "11111111-1111-4111-8111-111111111111",
                },
            )
            assert result.is_error is True
            text = result.content[0].text  # type: ignore[union-attr]
            payload = json.loads(text.split(": ", 1)[1])
            assert payload["problem"] == "the requested continuation cannot be consumed"
            assert payload["reason"] == reason
            assert "without previous_context_id" in payload["fix"]
            assert payload["retryable"] is False

    asyncio.run(run())


def test_reader_lite_schema_is_task_free_with_only_optional_reuse_locator() -> None:
    server = build_server("reader-lite", _Client())  # type: ignore[arg-type]
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    schema = tools["milai_recall"].input_schema
    assert set(schema["properties"]) == {"query"}
    assert schema["required"] == ["query"]
    assert schema["additionalProperties"] is False
    resolve_schema = tools["milai_memory_resolve"].input_schema
    assert set(resolve_schema["properties"]) == {"query", "previous_context_id"}
    assert resolve_schema["required"] == ["query"]
    assert resolve_schema["additionalProperties"] is False

    async def reuse() -> None:
        api = _Client()
        reuse_server = build_server("reader-lite", api)  # type: ignore[arg-type]
        async with Client(reuse_server, mode="2026-07-28") as client:
            result = await client.call_tool(
                "milai_memory_resolve",
                {
                    "query": "Recall the current state",
                    "previous_context_id": "11111111-1111-4111-8111-111111111111",
                },
            )
            assert result.is_error is False
        assert api.resolves[0][1]["previous_context_id"] == (
            "11111111-1111-4111-8111-111111111111"
        )

    asyncio.run(reuse())

    detail = build_server("reader-detail", _Client())  # type: ignore[arg-type]
    detail_tools = {tool.name: tool for tool in asyncio.run(detail.list_tools())}
    get_schema = detail_tools["milai_memory_get"].input_schema
    assert get_schema["additionalProperties"] is False
    assert set(get_schema["properties"]) == {
        "claim_id",
        "state_key",
        "consistency_mode",
        "valid_at",
        "known_at",
    }
    assert get_schema["$defs"]["StateKeyInput"]["additionalProperties"] is False


def test_reader_lite_host_composite_call_is_hidden_and_policy_owned() -> None:
    async def run() -> None:
        api = _Client()
        server = build_server(
            "reader-lite",
            api,  # type: ignore[arg-type]
            default_scope={"project_ids": ["milai"]},
            required_authority="INFORMATIONAL",
            consistency_floor="CANONICAL_REQUIRED",
            max_limit=3,
        )
        async with Client(server, mode="2026-07-28") as client:
            assert {tool.name for tool in (await client.list_tools()).tools} == {
                "milai_recall",
                "milai_memory_resolve",
            }
            result = await client.call_tool(
                "milai_prepare_context",
                {
                    "query": "project status",
                    "active_goal": "finish project",
                    "session_id": "session-1",
                    "agent_id": "openworker",
                    "task_epoch": "task-1",
                    "event": "TOOL_RESULT",
                    "compiler_digest": "a" * 64,
                    "router_digest": "b" * 64,
                    "tokenizer_digest": "c" * 64,
                    "policy_digest": "d" * 64,
                    "limit": 20,
                    "previous_validation_token": "x" * 64,
                },
            )
            assert result.is_error is False
            assert result.structured_content is not None
            assert result.structured_content["status"] == "UNCHANGED"
            payload = api.context_preparations[0]
            assert payload["profile_id"] == "reader-lite"
            assert payload["requested_scope"] == {"project_ids": ["milai"]}
            assert payload["required_authority"] == "INFORMATIONAL"
            assert payload["consistency"] == "CANONICAL_REQUIRED"
            assert payload["limit"] == 3
            rejected = await client.call_tool(
                "milai_prepare_context",
                {
                    "query": "project status",
                    "active_goal": "finish project",
                    "session_id": "session-1",
                    "agent_id": "openworker",
                    "task_epoch": "task-1",
                    "event": "TASK_START",
                    "compiler_digest": "a" * 64,
                    "router_digest": "b" * 64,
                    "tokenizer_digest": "c" * 64,
                    "policy_digest": "d" * 64,
                    "requested_scope": {"project_ids": ["attacker"]},
                },
            )
            assert rejected.is_error is True

    asyncio.run(run())


def test_reader_lite_rebinds_nested_need_authority_but_not_scope() -> None:
    class _PolicyValidatingClient(_Client):
        def prepare_context(self, payload: dict[str, Any]) -> Any:
            signature = payload["memory_need_signature"]
            assert signature["scope"] == payload["requested_scope"]
            assert signature["required_authority"] == payload["required_authority"]
            assert signature["consistency_floor"] == payload["consistency"]
            return super().prepare_context(payload)

    async def run() -> None:
        api = _PolicyValidatingClient()
        server = build_server(
            "reader-lite",
            api,  # type: ignore[arg-type]
            default_scope={"project_ids": ["milai"]},
            required_authority="ACTION_SAFE",
            consistency_floor="CANONICAL_REQUIRED",
        )
        host_signature: dict[str, Any] = {
            "version": "memory-need-v1",
            "scope": {"project_ids": ["milai"]},
            "required_authority": "INFORMATIONAL",
            "consistency_floor": "CANONICAL_REQUIRED",
            "claim_ids": [],
            "state_keys": [
                {
                    "version": "state-key-ref-v1",
                    "scope": {"project_ids": ["milai"]},
                    "subject": "release",
                    "predicate": "release.target",
                    "claim_type": "PROJECT_STATE",
                    "claim_id": None,
                    "relevant_open_issue_ids": [],
                    "canonical_position_seen": None,
                }
            ],
            "open_issue_ids": [],
            "temporal_need": "CURRENT",
            "evidence_need": "SUPPORT_POINTERS",
            "intent_class": "CURRENT_STATE",
        }
        host_signature_id = "need:" + hashlib.sha256(
            json.dumps(
                host_signature,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        async with Client(server, mode="2026-07-28") as client:
            result = await client.call_tool(
                "milai_prepare_context",
                {
                    "query": "current release target",
                    "active_goal": "prepare release",
                    "session_id": "session-1",
                    "agent_id": "openworker",
                    "task_epoch": "task-1",
                    "event": "EXPLICIT_MEMORY_REQUEST",
                    "requested_route": "L0",
                    "need_signature_id": host_signature_id,
                    "memory_need_signature": host_signature,
                    "state_key_ref": host_signature["state_keys"][0],
                    "compiler_digest": "a" * 64,
                    "router_digest": "b" * 64,
                    "tokenizer_digest": "c" * 64,
                    "policy_digest": "d" * 64,
                },
            )
        assert result.is_error is False
        payload = api.context_preparations[0]
        effective = payload["memory_need_signature"]
        assert effective["required_authority"] == "ACTION_SAFE"
        assert effective["scope"] == {"project_ids": ["milai"]}
        assert payload["state_key_ref"]["scope"] == {"project_ids": ["milai"]}
        assert payload["need_signature_id"] != host_signature_id
        assert payload["need_signature_id"] == "need:" + hashlib.sha256(
            json.dumps(
                effective,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    asyncio.run(run())


def test_current_and_preceding_protocols_return_structured_and_text_results() -> None:
    async def run() -> None:
        server = build_server("reader", _Client())  # type: ignore[arg-type]
        for mode, expected in (
            ("2026-07-28", "2026-07-28"),
            ("legacy", "2025-11-25"),
        ):
            async with Client(server, mode=mode) as client:
                assert client.protocol_version == expected
                result = await client.call_tool("milai_status", {})
                assert result.is_error is False
                assert result.structured_content is not None
                assert result.structured_content["contract_version"] == "agent.v1"
                assert result.content[0].type == "text"

    asyncio.run(run())


def test_reconnect_and_schema_override_are_fail_closed() -> None:
    async def run() -> None:
        server = build_server("reader", _Client())  # type: ignore[arg-type]
        for _ in range(2):
            async with Client(server, mode="2026-07-28") as client:
                tools = await client.list_tools()
                assert [tool.name for tool in tools.tools] == sorted(
                    tool.name for tool in tools.tools
                )
                rejected = await client.call_tool("milai_status", {"profile": "submitter"})
                assert rejected.is_error is True

    asyncio.run(run())


def test_sensitive_tool_schema_requires_literal_host_confirmation() -> None:
    submitter = build_server("submitter", _Client())  # type: ignore[arg-type]
    tools = {tool.name: tool for tool in asyncio.run(submitter.list_tools())}
    capture_schema = tools["milai_evidence_capture"].input_schema
    proposal_schema = tools["milai_proposal_create"].input_schema
    assert capture_schema["properties"]["confirmation"]["const"] == "CAPTURE"
    speaker_schema = capture_schema["properties"]["speaker"]
    speaker_variants = speaker_schema.get("anyOf", [speaker_schema])
    assert frozenset({"user", "assistant", "system", "tool"}) in {
        frozenset(variant.get("enum", [])) for variant in speaker_variants
    }
    assert "source_context" in capture_schema["properties"]
    assert "source_context" not in capture_schema["required"]
    source_context_schema = capture_schema["properties"]["source_context"]
    assert "object" in {
        variant.get("type")
        for variant in source_context_schema.get("anyOf", [source_context_schema])
    }
    assert proposal_schema["properties"]["confirmation"]["const"] == "SUBMIT"
    nested = proposal_schema["$defs"]["ProposalDraft"]
    assert proposal_schema["properties"]["proposal"]["$ref"] == "#/$defs/ProposalDraft"
    assert nested["additionalProperties"] is False
    assert {
        "operation",
        "requested_authority",
        "scope_predicate",
        "model_id",
        "template_version",
        "input_snapshot_hash",
        "proposed_patch",
    } <= set(nested["required"])

    reviewer = build_server("reviewer", _Client())  # type: ignore[arg-type]
    review_schema = {
        tool.name: tool for tool in asyncio.run(reviewer.list_tools())
    }["milai_memory_review"].input_schema
    assert review_schema["properties"]["decision"]["enum"] == ["APPROVE", "REJECT"]
    assert review_schema["properties"]["confirmation"]["enum"] == [
        "APPROVE",
        "REJECT",
    ]


def test_submitter_accepts_and_forwards_structured_source_context() -> None:
    async def run() -> None:
        api = _Client()
        server = build_server("submitter", api)  # type: ignore[arg-type]
        source_context = {
            "session_id": "session-1",
            "turn_id": "turn-1",
            "turn_ordinal": 1,
            "round_id": "round-0",
            "round_ordinal": 0,
            "previous_turn_id": "turn-0",
            "next_turn_id": None,
        }
        async with Client(server, mode="2026-07-28") as client:
            result = await client.call_tool(
                "milai_evidence_capture",
                {
                    "operation_id": "capture-source-context-1",
                    "source_type": "LONGMEMEVAL_HISTORY_TURN",
                    "source_ref": "longmemeval://case/1/session/1/s1/turn/1",
                    "subject_id": "session-1",
                    "speaker": "assistant",
                    "source_context": source_context,
                    "observed_at": "2026-08-28T00:00:00+00:00",
                    "content": "assistant: bounded public benchmark content",
                    "permission_snapshot": {"readable": True},
                    "confirmation": "CAPTURE",
                    "retention_state": "READABLE",
                    "data_classification": "DEIDENTIFIED",
                },
            )
        assert result.is_error is False
        assert api.evidence_captures == [
            (
                {
                    "source_type": "LONGMEMEVAL_HISTORY_TURN",
                    "source_ref": "longmemeval://case/1/session/1/s1/turn/1",
                    "subject_id": "session-1",
                    "speaker": "assistant",
                    "source_context": source_context,
                    "observed_at": "2026-08-28T00:00:00+00:00",
                    "content": "assistant: bounded public benchmark content",
                    "data_classification": "DEIDENTIFIED",
                    "permission_snapshot": {"readable": True},
                    "retention_state": "READABLE",
                },
                "capture-source-context-1",
            )
        ]

    asyncio.run(run())


def test_reviewer_records_explicit_decision_and_rejects_mismatched_confirmation() -> None:
    async def run() -> None:
        api = _Client()
        server = build_server("reviewer", api)  # type: ignore[arg-type]
        async with Client(server, mode="2026-07-28") as client:
            rejected = await client.call_tool(
                "milai_memory_review",
                {
                    "proposal_id": "proposal-1",
                    "operation_id": "review-mismatch",
                    "decision": "APPROVE",
                    "policy_version": "review-v1",
                    "reason_code": "SYNTHETIC_VERIFIED",
                    "confirmation": "REJECT",
                },
            )
            assert rejected.is_error is True
            assert api.reviews == []

            accepted = await client.call_tool(
                "milai_memory_review",
                {
                    "proposal_id": "proposal-1",
                    "operation_id": "review-1",
                    "decision": "APPROVE",
                    "policy_version": "review-v1",
                    "reason_code": "SYNTHETIC_VERIFIED",
                    "confirmation": "APPROVE",
                },
            )
            assert accepted.is_error is False
            assert api.reviews == [
                (
                    "proposal-1",
                    {
                        "decision": "APPROVE",
                        "policy_version": "review-v1",
                        "reason_code": "SYNTHETIC_VERIFIED",
                    },
                    "review-1",
                )
            ]
            assert accepted.structured_content is not None
            assert accepted.structured_content["confirmation_summary"][
                "actor_separation"
            ] == "NAMED_PROFILE_CAPABILITY"

            inbox = await client.call_tool(
                "milai_proposals_list",
                {"status": "PENDING_REVIEW", "limit": 10},
            )
            proposal = await client.call_tool(
                "milai_proposal_get", {"proposal_id": "proposal-1"}
            )
            assert inbox.is_error is False
            assert proposal.is_error is False
            assert api.proposal_lists == [("PENDING_REVIEW", 10)]
            assert api.proposal_reads == ["proposal-1"]

    asyncio.run(run())


def test_proposal_tool_validates_before_client_call() -> None:
    async def run() -> None:
        api = _Client()
        server = build_server("submitter", api)  # type: ignore[arg-type]
        async with Client(server, mode="2026-07-28") as client:
            rejected = await client.call_tool(
                "milai_proposal_create",
                {
                    "operation_id": "invalid",
                    "proposal": {"operation": "CREATE"},
                    "confirmation": "SUBMIT",
                },
            )
            assert rejected.is_error is True
            assert api.proposals == []

            accepted = await client.call_tool(
                "milai_proposal_create",
                {
                    "operation_id": "valid",
                    "proposal": {
                        "operation": "CREATE",
                        "supporting_evidence_refs": ["11111111-1111-4111-8111-111111111111"],
                        "requested_authority": "INFORMATIONAL",
                        "scope_predicate": {"project_ids": ["milai"]},
                        "model_id": "extractor-test",
                        "template_version": "v1",
                        "input_snapshot_hash": "a" * 64,
                        "proposed_patch": {
                            "subject_id": "subject",
                            "predicate": "prefers",
                            "claim_type": "FACT",
                            "payload": {"value": "synthetic"},
                            "authority": "INFORMATIONAL",
                            "confidence": 0.8,
                        },
                    },
                    "confirmation": "SUBMIT",
                },
            )
            assert accepted.is_error is False
            assert api.proposals[0][1] == "valid"
            assert api.proposals[0][0].input_snapshot_hash == "a" * 64

            stale = await client.call_tool(
                "milai_proposal_create",
                {
                    "operation_id": "stale",
                    "proposal": {
                        "operation": "SUPERSEDE",
                        "target_claim_id": "claim-1",
                        "expected_version_id": "stale-version",
                        "supporting_evidence_refs": ["11111111-1111-4111-8111-111111111111"],
                        "requested_authority": "INFORMATIONAL",
                        "scope_predicate": {"project_ids": ["milai"]},
                        "model_id": "extractor-test",
                        "template_version": "v1",
                        "input_snapshot_hash": "a" * 64,
                        "proposed_patch": {"authority": "INFORMATIONAL"},
                    },
                    "confirmation": "SUBMIT",
                },
            )
            assert stale.is_error is True
            assert len(api.proposals) == 1

    asyncio.run(run())
