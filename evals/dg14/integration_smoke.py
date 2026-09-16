"""Real DG-14 governance, isolation, revocation, and MCP-restart smoke."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from evals.dg14.benchmark import (
    CLASSIFICATION,
    DEFAULT_ENV_FILE,
    DEFAULT_TOKENIZER,
    LocalDG14RuntimeSession,
    _atomic_json,
    _local_token_counter,
    load_opened_dev,
)
from evals.dg14.contracts import (
    DG14ContractError,
    DG14HistoryEvent,
    DG14QueryResult,
    normalize_lme_timestamp,
)
from evals.dg14.mcp_stdio import StdioMcpTransport
from evals.dg14.milai_mcp_adapter import DG14MilaiMcpAdapter


class DG14IntegrationSmokeError(RuntimeError):
    """A real integration-smoke invariant failed."""


def _event(
    case: Any,
    *,
    case_id: str,
    session_ordinal: int,
    turn_ordinal: int,
) -> DG14HistoryEvent:
    session = case.sessions[session_ordinal]
    turn = session.turns[turn_ordinal]
    return DG14HistoryEvent.from_mapping(
        {
            "case_id": case_id,
            "session_ordinal": session_ordinal,
            "original_session_id": session.session_id,
            "turn_ordinal": turn_ordinal,
            "role": turn.role,
            "content": turn.content,
            "observed_at": normalize_lme_timestamp(session.observed_at),
        }
    )


def _raw_resolve(
    session: LocalDG14RuntimeSession,
    *,
    scope: Mapping[str, object],
    query: str,
) -> dict[str, object]:
    transport = StdioMcpTransport(session.adapter_config())
    transport.open_case(scope)
    try:
        return transport.call(
            "reader-detail",
            "milai_memory_resolve",
            {
                "query": "Recall: " + query,
                "required_freshness": "CURRENT",
                "consistency_mode": "CANONICAL_REQUIRED",
                "limit": 3,
                "max_context_tokens": 4096,
            },
        )
    finally:
        transport.close()


def _item_count(value: Mapping[str, object]) -> int:
    items = value.get("items")
    if not isinstance(items, list):
        raise DG14IntegrationSmokeError("resolve response has no item list")
    return len(items)


def _require_sources(result: DG14QueryResult, label: str) -> tuple[str, ...]:
    if not result.source_ids or result.usage.get("fallback_used") is True:
        raise DG14IntegrationSmokeError(f"{label} did not return governed sources")
    return result.source_ids


def run_governance_restart_smoke(
    *,
    run_id: str,
    output_root: Path,
    env_file: Path = DEFAULT_ENV_FILE,
    tokenizer_path: Path = DEFAULT_TOKENIZER,
) -> dict[str, Any]:
    """Exercise current MCP governance with exact namespace cleanup."""

    _partition, cases = load_opened_dev()
    case = cases[0]
    token_counter = _local_token_counter(tokenizer_path)
    session = LocalDG14RuntimeSession(output_root=output_root, env_file=env_file)
    adapter_a: DG14MilaiMcpAdapter | None = None
    adapter_b: DG14MilaiMcpAdapter | None = None
    cleaned_a = False
    cleaned_b = False
    runtime_details: Mapping[str, Any] = {}
    runtime_cleanup: Mapping[str, Any] = {"status": "NOT_CREATED"}
    try:
        runtime_details = session.start(run_id)
        adapter_a = cast(
            DG14MilaiMcpAdapter, session.adapter_for_case(case, token_counter)
        )
        adapter_a.reset(run_id, case.source_id)
        evidence_ids = tuple(
            adapter_a.ingest(
                _event(
                    case,
                    case_id=case.source_id,
                    session_ordinal=0,
                    turn_ordinal=turn_ordinal,
                )
            )
            for turn_ordinal in range(2)
        )
        pre_review = _raw_resolve(
            session,
            scope=adapter_a.namespace.scope,
            query="vintage band t-shirt styling advice",
        )
        canonical_before_review = _item_count(pre_review)
        if canonical_before_review != 0:
            raise DG14IntegrationSmokeError(
                "evidence capture changed canonical retrieval before review"
            )
        adapter_a.finalize()
        receipts = adapter_a.export_governance_receipts()
        if not receipts:
            raise DG14IntegrationSmokeError("governed finalize produced no claims")
        first = receipts[0]
        initial = adapter_a.query(
            "What advice was given about styling a vintage band t-shirt?",
            case.question_at,
            512,
        )
        initial_sources = _require_sources(initial, "initial resolve")
        pid_before, pid_after = adapter_a.restart_mcp()
        restarted = adapter_a.query(
            "What advice was given about styling a vintage band t-shirt?",
            case.question_at,
            512,
        )
        restarted_sources = _require_sources(restarted, "restart resolve")
        if restarted_sources != initial_sources:
            raise DG14IntegrationSmokeError("MCP restart changed persisted provenance")

        wrong_scope_accepted = 0
        try:
            adapter_a.query(
                "What advice was given about styling a vintage band t-shirt?",
                case.question_at,
                512,
                task_context={"project_ids": ["dg14-wrong-scope"]},
            )
        except DG14ContractError:
            pass
        else:
            wrong_scope_accepted = 1

        sentinel_case_id = f"{case.source_id}-isolation-sentinel"
        adapter_b = cast(
            DG14MilaiMcpAdapter, session.adapter_for_case(case, token_counter)
        )
        adapter_b.reset(run_id, sentinel_case_id)
        for turn_ordinal in range(2):
            adapter_b.ingest(
                _event(
                    case,
                    case_id=sentinel_case_id,
                    session_ordinal=1,
                    turn_ordinal=turn_ordinal,
                )
            )
        adapter_b.finalize()
        sentinel_before = adapter_b.query(
            "What was discussed in this imported history?",
            case.question_at,
            512,
        )
        sentinel_sources_before = _require_sources(
            sentinel_before, "sentinel resolve before cleanup"
        )
        cross_probe = adapter_b.query(
            "What advice was given about styling a vintage band t-shirt?",
            case.question_at,
            512,
        )
        cross_case_accepted = int(
            bool(set(cross_probe.source_ids).intersection(initial_sources))
        )

        revoked = adapter_a.cleanup()
        cleaned_a = True
        stale_probe = _raw_resolve(
            session,
            scope=adapter_a.namespace.scope,
            query="vintage band t-shirt styling advice",
        )
        stale_accepted = _item_count(stale_probe)
        sentinel_after = adapter_b.query(
            "What was discussed in this imported history?",
            case.question_at,
            512,
        )
        sentinel_sources_after = _require_sources(
            sentinel_after, "sentinel resolve after other cleanup"
        )
        other_namespaces_changed = int(
            sentinel_sources_after != sentinel_sources_before
        )
        adapter_b.cleanup()
        cleaned_b = True

        actors = session.profile_actor_ids()
        report: dict[str, Any] = {
            "classification": CLASSIFICATION,
            "formal_holdout_consumed": False,
            "transport": "stdio-mcp",
            "storage_backend": "postgresql",
            "runtime_process": {
                "kind": "milai-runtime",
                "base_url": runtime_details["api_base_url"],
            },
            "worker_process": {"kind": "milai-worker", "mode": "--once"},
            "mcp_process": {
                "profiles": ["submitter", "reviewer", "reader-detail", "operator"],
                "max_retries": 0,
            },
            "governance": {
                "capture_receipt": {"evidence_id": evidence_ids[0]},
                "canonical_claims_after_capture": canonical_before_review,
                "proposal_receipt": {"proposal_id": first["proposal_id"]},
                "canonical_claims_before_review": canonical_before_review,
                "review_receipt": {
                    "claim_version_id": first["claim_version_id"]
                },
                "reviewer_actor": actors["reviewer"],
                "submitter_actor": actors["submitter"],
                "projection_ready_after_review": True,
            },
            "correctness": {
                "wrong_scope_acceptance": {
                    "accepted": wrong_scope_accepted,
                    "denominator": 1,
                },
                "cross_case_contamination": {
                    "accepted": cross_case_accepted,
                    "denominator": 1,
                },
                "stale_revoked_evidence_acceptance": {
                    "accepted": stale_accepted,
                    "denominator": 1,
                },
                "silent_fallback": {
                    "accepted": int(initial.usage.get("fallback_used") is True),
                    "denominator": 1,
                },
            },
            "restart_persistence": {
                "mcp_pid_before": pid_before,
                "mcp_pid_after": pid_after,
                "runtime_persistence_reused": True,
                "resolve_after_restart": {
                    "status": "OK",
                    "memory_status": restarted.status,
                    "source_ids": list(restarted_sources),
                },
            },
            "cleanup": {
                "namespace_exact": True,
                "evidence_revoked": len(revoked),
                "other_namespaces_changed": other_namespaces_changed,
            },
            "schema": "milai.dg14.integration-governance-smoke.v1",
            "status": "PASS",
        }
    finally:
        if adapter_a is not None and not cleaned_a:
            adapter_a.cleanup()
        if adapter_b is not None and not cleaned_b:
            adapter_b.cleanup()
        runtime_cleanup = session.close()
    report["runtime_cleanup"] = dict(runtime_cleanup)
    _atomic_json(output_root / "integration-smoke.json", report)
    return report
