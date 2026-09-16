from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts import run_dg10_benchmark_adapter_contract as adapter_contract
from scripts import run_dg10_benchmark_milai_mcp_smoke as mcp_smoke


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    longmemeval_root = tmp_path / "LongMemEval"
    rows: list[dict[str, Any]] = []
    for index in range(10):
        source_id = f"lme-{index:03d}"
        rows.append(
            {
                "question_id": source_id,
                "question_type": "single-session-user",
                "question": f"raw forbidden question {index}",
                "answer": f"raw forbidden answer {index}",
                "haystack_session_ids": [f"session-{index}"],
                "haystack_sessions": [
                    [
                        {"role": "user", "content": f"raw forbidden memory {index}"},
                        {
                            "role": "assistant",
                            "content": f"raw forbidden answer {index}",
                        },
                    ]
                ],
            }
        )
    _write_json(longmemeval_root / "data/longmemeval_s_cleaned.json", rows)
    case_ids = [f"longmemeval:lme-{index:03d}" for index in range(10)]
    dev_ids = case_ids[:2]
    adapter = {
        "schema": "milai.dg10.benchmark-adapter-contract.v1",
        "candidate": "candidate.4",
        "status": "ADAPTER_CONTRACT_CANDIDATE_REVIEW_REQUIRED",
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "generation_contract": adapter_contract._generation_contract(),
        "generation_contract_sha256": adapter_contract._json_sha256(
            adapter_contract._generation_contract()
        ),
        "prompt_templates_sha256": adapter_contract._json_sha256(
            adapter_contract._prompt_templates()
        ),
        "planned_round_contract": {
            "model_rounds_by_arm": adapter_contract.PLANNED_MODEL_ROUNDS,
            "mcp_calls_by_arm": adapter_contract.PLANNED_MCP_CALLS,
        },
        "adapter_output_schema": adapter_contract._adapter_output_schema(),
        "gate_results": {"BMG-03": "CANDIDATE_LOCKED_NOT_RUN"},
    }
    schedule = [
        {"case_id": case_id, "order": list(adapter_contract._latin_square_order(case_id))}
        for case_id in dev_ids
    ]
    calibration = {
        "schema": "milai.dg10.benchmark-calibration-plan.v1",
        "status": "CALIBRATION_PLAN_CANDIDATE_NOT_RUN",
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "inputs": {"adapter_contract_sha256": mcp_smoke._json_sha256(adapter)},
        "dev_split": {
            "dev_case_ids": dev_ids,
            "dev_case_count": len(dev_ids),
            "dev_case_ids_sha256": mcp_smoke._json_sha256(dev_ids),
            "dev_fraction": 0.10,
            "per_dataset": {
                "LONGMEMEVAL_CLEANED_500": {
                    "total": len(case_ids),
                    "dev": len(dev_ids),
                    "dev_case_ids_sha256": mcp_smoke._json_sha256(dev_ids),
                }
            },
        },
        "schedule": {
            "dev_case_arm_schedule_sha256": mcp_smoke._json_sha256(schedule)
        },
    }
    adapter_path = tmp_path / "adapter.json"
    calibration_path = tmp_path / "calibration.json"
    _write_json(adapter_path, adapter)
    _write_json(calibration_path, calibration)
    return adapter_path, calibration_path, longmemeval_root


class FakeExecutor:
    def __init__(self, *, model_calls: int = 2) -> None:
        self.model_calls = model_calls

    def execute(self, **kwargs: Any) -> mcp_smoke.McpArmExecution:
        marker = str(kwargs["marker"])
        native_ids = ("chatcmpl-test-tool-0001", "chatcmpl-test-answer-0002")
        native_calls = tuple(
            {
                "native_request_id": native_id,
                "model": mcp_smoke.MODEL_ID,
                "native_finish_reason": "stop",
                "usage": {
                    "prompt_tokens": 50 + index,
                    "completion_tokens": 5,
                    "total_tokens": 55 + index,
                },
                "tokenizer_recount": 50 + index,
                "usage_recount_match": True,
                "latency_ms": 1.0 + index,
                "native_receipt_sha256": chr(ord("c") + index) * 64,
            }
            for index, native_id in enumerate(native_ids)
        )
        return mcp_smoke.McpArmExecution(
            raw_output="raw forbidden answer 0",
            model_calls=self.model_calls,
            mcp_calls=1,
            tool_names=("milai_recall",),
            aggregate_tokens={"input": 100, "output": 10, "reasoning": 0, "cache_read": 0},
            wall_ms=10.0,
            route_records=(
                {
                    "route": "tool",
                    "request_id_sha256": mcp_smoke._sha256_bytes(
                        native_ids[0].encode()
                    ),
                },
                {
                    "route": "answer",
                    "request_id_sha256": mcp_smoke._sha256_bytes(
                        native_ids[1].encode()
                    ),
                },
            ),
            native_calls=native_calls,
            fixture_ids_sha256={"claim_id": "c" * 64},
            runtime_recall_trace_id_sha256="d" * 64,
            runtime_recall_payload_sha256="e" * 64,
            identity={
                "model_id": mcp_smoke.MODEL_ID,
                "external_provider_requests": 0,
                "external_provider_cost": 0,
                "vllm_lifecycle_mutated": False,
            },
            security={"secret_scan": "PASS"},
            cleanup={"runtime_database": {"status": "PASS"}},
            raw_runtime_recall={"marker": marker, "raw": "raw forbidden memory 0"},
        )


def test_milai_mcp_smoke_reports_two_visible_rounds_without_raw_repo_content(
    tmp_path: Path,
) -> None:
    adapter, calibration, longmemeval_root = _fixture(tmp_path)
    report, sidecar = mcp_smoke.run_smoke(
        adapter_report_path=adapter,
        calibration_plan_path=calibration,
        longmemeval_root=longmemeval_root,
        executor=FakeExecutor(),
    )
    assert report["status"] == "MILAI_MCP_TELEMETRY_DEV_SMOKE_COMPLETE_NOT_CALIBRATION"
    assert report["record"]["planned_model_rounds"] == 2
    assert report["record"]["usage"]["model_rounds"] == 2
    assert report["record"]["usage"]["mcp_rounds"] == 1
    assert len(report["record"]["native_calls"]) == 2
    assert set(report["record"]) == set(
        adapter_contract._adapter_output_schema()["required"]
    )
    assert report["test_labels_or_outputs_opened"] is False
    assert report["quality_thresholds_frozen"] is False
    assert report["external_provider_requests"] == 0
    assert report["fixture_ingestion"]["selection_uses_gold_answer"] is False
    encoded_report = json.dumps(report, ensure_ascii=False)
    assert "raw forbidden question" not in encoded_report
    assert "raw forbidden answer" not in encoded_report
    assert "raw forbidden memory" not in encoded_report
    encoded_sidecar = json.dumps(sidecar, ensure_ascii=False)
    assert "raw forbidden question 0" in encoded_sidecar
    assert "raw forbidden answer 0" in encoded_sidecar
    assert "raw forbidden memory 0" in encoded_sidecar


def test_milai_mcp_smoke_rejects_one_round_masquerading_as_agent_tool_use(
    tmp_path: Path,
) -> None:
    adapter, calibration, longmemeval_root = _fixture(tmp_path)
    with pytest.raises(mcp_smoke.McpSmokeError, match="visible round or route"):
        mcp_smoke.run_smoke(
            adapter_report_path=adapter,
            calibration_plan_path=calibration,
            longmemeval_root=longmemeval_root,
            executor=FakeExecutor(model_calls=1),
        )


def test_benchmark_telemetry_adapter_is_ephemeral_and_base_hash_bound(
    tmp_path: Path,
) -> None:
    base_before = mcp_smoke._sha256_file(mcp_smoke.openworker_e2e.ADAPTER)
    generated, identity = mcp_smoke._materialize_benchmark_adapter(tmp_path)
    assert base_before == mcp_smoke._BASE_ADAPTER_SHA256
    assert mcp_smoke._sha256_file(mcp_smoke.openworker_e2e.ADAPTER) == base_before
    assert identity["base_adapter_sha256"] == base_before
    assert identity["generated_adapter_sha256"] == mcp_smoke._sha256_file(generated)
    assert identity["integration_adapter_bytes_changed"] is False
    source = generated.read_text(encoding="utf-8")
    assert "DG10_BENCHMARK_NATIVE_CALL" in source
    compile(source, str(generated), "exec")
