from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evals.benchmark import lme_product_smoke as smoke
from scripts import run_dg10_lme_product_smoke as runner


def _row(source_id: str) -> dict[str, object]:
    return {
        "question_id": source_id,
        "question_type": "knowledge-update",
        "question": f"question {source_id}",
        "answer": [f"answer {source_id}"],
        "haystack_session_ids": [f"session-{source_id}"],
        "haystack_sessions": [
            [{"role": "user", "content": f"memory {source_id}"}]
        ],
        "haystack_dates": ["2023/05/21 (Sun) 05:48"],
        "question_date": "2023/05/31 (Wed) 07:54",
        "answer_session_ids": [f"session-{source_id}"],
    }


def test_fixed_smoke_schedule_is_counterbalanced() -> None:
    schedules = [smoke._schedule(index) for index in range(5)]

    assert all(set(schedule) == set(smoke.ARMS) for schedule in schedules)
    assert [schedule[0] for schedule in schedules] == [
        "NO_MEMORY",
        "NAIVE_RAG",
        "MILAI_T3A",
        "NO_MEMORY",
        "NAIVE_RAG",
    ]
    with pytest.raises(ValueError, match="non-negative"):
        smoke._schedule(-1)


def test_installed_product_worker_accepts_every_frozen_benchmark_phase() -> None:
    assert smoke.BENCHMARK_PHASES == ("SMOKE", "DEV", "CONFIRMATION")


def test_load_cases_uses_only_fixed_public_smoke_ids(tmp_path: Path) -> None:
    dataset = tmp_path / "longmemeval.json"
    rows = [_row(source_id) for source_id in reversed(smoke.SMOKE_SOURCE_IDS)]
    rows.append(_row("not-selected"))
    dataset.write_text(json.dumps(rows), encoding="utf-8")

    cases, identity = smoke._load_cases(dataset)

    assert [case.source_case_id for case in cases] == list(smoke.SMOKE_SOURCE_IDS)
    assert identity["confirmation_or_test_opened"] is False
    assert identity["labels_opened"] == "PUBLIC_DEV_ONLY"
    assert set(identity["answer_session_ids"]) == set(smoke.SMOKE_SOURCE_IDS)
    assert cases[0].session_observed_at[0].isoformat() == "2023-05-21T05:48:00+00:00"
    assert cases[0].question_at.isoformat() == "2023-05-31T07:54:00+00:00"


def test_aggregate_includes_quality_token_and_latency_dimensions() -> None:
    record = {
        "arm": "MILAI_T3A",
        "score": {"exact_match": 1, "normalized_f1": 0.75},
        "prompt_tokens": 100,
        "completion_tokens": 5,
        "memory_tokens": 40,
        "answer_latency_ms": 20.0,
        "retrieval_latency_ms": 3.0,
        "memory_context_chars": 120,
        "retrieval_recall_at_k": 1.0,
        "retrieval_relevant_coverage_at_k": 0.5,
    }

    aggregate = smoke._aggregate([record])["MILAI_T3A"]

    assert aggregate["total_tokens_mean"] == 105
    assert aggregate["memory_tokens_mean"] == 40
    assert aggregate["total_latency_ms_mean"] == 23.0
    assert aggregate["retrieval_relevant_coverage_at_k"] == 0.5


def test_prompt_contract_digest_covers_template_schema_and_generation() -> None:
    contract = smoke.prompt_contract()

    assert contract["system_prompt"] == smoke.SYSTEM_PROMPT
    assert contract["user_prompt_template"] == smoke.USER_PROMPT_TEMPLATE
    assert contract["answer_schema"] == smoke.ANSWER_SCHEMA
    assert len(smoke.prompt_contract_sha256()) == 64


def test_messages_supply_historical_query_time_to_every_arm() -> None:
    question_at = smoke._longmemeval_datetime("2023/05/02 (Tue) 08:12")
    messages = smoke._messages(
        "What happened a month ago?",
        question_at,
        smoke.PrefetchContext.no_memory(),
    )

    assert "QUESTION_AS_OF=2023-05-02T08:12:00+00:00" in messages[1]["content"]


def test_frozen_dev_split_identity_is_unchanged() -> None:
    case_ids = [f"longmemeval:{source_id}" for source_id in smoke.DEV_SOURCE_IDS]

    assert len(case_ids) == 50
    assert hashlib.sha256(smoke._canonical(case_ids)).hexdigest() == smoke.DEV_CASE_IDS_SHA256


def test_confirmation_split_is_frozen_and_disjoint_from_dev() -> None:
    source_ids = smoke.CONFIRMATION_SOURCE_IDS
    case_ids = [f"longmemeval:{source_id}" for source_id in source_ids]

    assert len(source_ids) == 50
    assert not set(source_ids).intersection(smoke.DEV_SOURCE_IDS)
    assert not set(source_ids).intersection(
        smoke.CONSUMED_CONFIRMATION_V1_SOURCE_IDS
    )
    assert not set(source_ids).intersection(
        smoke.CONSUMED_CONFIRMATION_V2_SOURCE_IDS
    )
    assert (
        hashlib.sha256(smoke._canonical(source_ids)).hexdigest()
        == smoke.CONFIRMATION_SOURCE_IDS_SHA256
    )
    assert (
        hashlib.sha256(smoke._canonical(case_ids)).hexdigest()
        == smoke.CONFIRMATION_CASE_IDS_SHA256
    )


def test_mcp_failure_summary_is_bounded_and_omits_memory_payload() -> None:
    detail = smoke._mcp_failure_summary(
        {
            "is_error": True,
            "structured": {
                "status": "UNAVAILABLE",
                "reason": "ENDPOINT_UNAVAILABLE",
                "items": [{"payload": {"memory_text": "private-memory"}}],
            },
            "content": [{"text": "endpoint timed out" + "x" * 2_000}],
        }
    )

    assert len(detail) <= smoke._MCP_FAILURE_DETAIL_CHARS
    assert "x" * smoke._MCP_FAILURE_CONTENT_CHARS not in detail
    assert "ENDPOINT_UNAVAILABLE" in detail
    assert "private-memory" not in detail


def test_authorized_http_recall_conversion_preserves_canonical_results() -> None:
    result = smoke._recall_envelope_from_api(
        {
            "results": [{"claim_version_id": "claim-v1", "payload": {"session_id": "s1"}}],
            "open_issue_ids": ["issue-2", "issue-1"],
            "degraded_components": [],
            "fallback_used": False,
            "fallback_reason": None,
            "abstained": False,
            "abstention_reason": None,
            "retrieval_trace_id": "trace-1",
            "consistency": "CANONICAL_REQUIRED",
        }
    )

    assert result["status"] == "OK"
    assert result["items"][0]["payload"]["session_id"] == "s1"
    assert result["open_issue_ids"] == ["issue-1", "issue-2"]
    assert result["trace_id"] == "trace-1"


def test_authorized_http_recall_conversion_rejects_invalid_results() -> None:
    with pytest.raises(smoke.BenchmarkSmokeError, match="invalid results"):
        smoke._recall_envelope_from_api(
            {"results": "TRUNCATED", "open_issue_ids": [], "degraded_components": []}
        )


def test_retrieval_only_conversion_preserves_results_from_operator_abstention() -> None:
    result = smoke._recall_envelope_from_api(
        {
            "results": [{"payload": {"session_id": "s1"}}],
            "open_issue_ids": [],
            "degraded_components": [],
            "fallback_used": False,
            "abstained": True,
            "abstention_reason": "OPERATOR_INSUFFICIENT_OPERANDS",
        },
        preserve_operator_results=True,
    )

    assert result["status"] == "OK"
    assert result["items"][0]["payload"]["session_id"] == "s1"
    assert result["operator_abstention_bypassed"] is True
    assert result["operator_abstention_reason"] == "OPERATOR_INSUFFICIENT_OPERANDS"


def test_provider_ledger_summary_counts_started_requests_after_run_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events = [
        {"event": "RESERVED"},
        {
            "event": "PROVIDER_TERMINAL",
            "request_started": True,
            "native_request_id": "native-1",
        },
        {"event": "POST_PROVIDER_TERMINAL"},
        {"event": "RESERVED"},
        {
            "event": "PROVIDER_TERMINAL",
            "request_started": False,
            "native_request_id": None,
        },
    ]

    class FakeGateway:
        def __init__(self, _manifest: Path, _ledger: Path) -> None:
            pass

        def read_ledger(self) -> list[dict[str, object]]:
            return events

    monkeypatch.setattr(runner.benchmark, "ProviderExecutionGateway", FakeGateway)

    summary = runner._provider_ledger_summary(
        tmp_path / "manifest.json",
        tmp_path / "ledger.jsonl",
    )

    assert summary == {
        "status": "VALID",
        "error": None,
        "reservations": 2,
        "provider_terminals": 2,
        "post_provider_terminals": 1,
        "native_requests_started": 1,
        "native_request_ids_observed": 1,
    }


def test_confirmation_freeze_manifest_is_consumed_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    freeze_root = tmp_path / "freeze"
    consumption = freeze_root / "confirmation-consumption.json"
    manifest = freeze_root / "freeze-manifest.json"
    freeze_root.mkdir()
    code_identity = "c" * 64
    dataset_digest = "d" * 64
    prompt_digest = smoke.prompt_contract_sha256()
    manifest.write_text(
        json.dumps(
            {
                "schema": "milai.dg10.freeze-manifest.v1",
                "status": "FROZEN",
                "package_run_id": "f0-package-test-001",
                "model_id": smoke.MODEL_ID,
                "dataset_sha256": dataset_digest,
                "prompt_contract_sha256": prompt_digest,
                "confirmation_source_ids_sha256": (
                    smoke.CONFIRMATION_SOURCE_IDS_SHA256
                ),
                "confirmation_case_ids_sha256": smoke.CONFIRMATION_CASE_IDS_SHA256,
                "confirmation_case_count": 50,
                "confirmation_code_identity": code_identity,
                "confirmation_consumption_path": consumption.relative_to(
                    runner.ROOT
                ).as_posix()
                if consumption.is_relative_to(runner.ROOT)
                else str(consumption),
                "development_ai_audits": 0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "FREEZE_ROOT", freeze_root)
    monkeypatch.setattr(runner, "CONFIRMATION_CONSUMPTION", consumption)
    monkeypatch.setattr(runner, "confirmation_code_identity", lambda: code_identity)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    frozen = json.loads(manifest.read_text(encoding="utf-8"))
    frozen["confirmation_consumption_path"] = "freeze/confirmation-consumption.json"
    manifest.write_text(json.dumps(frozen), encoding="utf-8")

    runner._consume_confirmation(
        freeze_manifest=manifest,
        run_id="lme-confirmation-test-001",
        package_run_id="f0-package-test-001",
        dataset_digest=dataset_digest,
        prompt_digest=prompt_digest,
        source_ids_digest=smoke.CONFIRMATION_SOURCE_IDS_SHA256,
    )

    consumed = json.loads(consumption.read_text(encoding="utf-8"))
    assert consumed["new_attempts_allowed"] is False
    with pytest.raises(runner.state.F0Error, match="already consumed"):
        runner._consume_confirmation(
            freeze_manifest=manifest,
            run_id="lme-confirmation-test-002",
            package_run_id="f0-package-test-001",
            dataset_digest=dataset_digest,
            prompt_digest=prompt_digest,
            source_ids_digest=smoke.CONFIRMATION_SOURCE_IDS_SHA256,
        )
