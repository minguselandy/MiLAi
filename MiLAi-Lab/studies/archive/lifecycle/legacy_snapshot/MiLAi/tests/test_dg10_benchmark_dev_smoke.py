from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts import run_dg10_benchmark_adapter_contract as adapter_contract
from scripts import run_dg10_benchmark_dev_smoke as dev_smoke


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
    source = longmemeval_root / "data/longmemeval_s_cleaned.json"
    _write_json(source, rows)
    case_ids = [f"longmemeval:lme-{index:03d}" for index in range(10)]
    dev_ids = case_ids[:2]
    adapter = {
        "schema": "milai.dg10.benchmark-adapter-contract.v1",
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
        "inputs": {"adapter_contract_sha256": dev_smoke._json_sha256(adapter)},
        "dev_split": {
            "dev_case_ids": dev_ids,
            "dev_case_count": len(dev_ids),
            "dev_case_ids_sha256": dev_smoke._json_sha256(dev_ids),
            "dev_fraction": 0.10,
            "per_dataset": {
                "LONGMEMEVAL_CLEANED_500": {
                    "total": len(case_ids),
                    "dev": len(dev_ids),
                    "dev_case_ids_sha256": dev_smoke._json_sha256(dev_ids),
                }
            },
        },
        "schedule": {
            "dev_case_arm_schedule_sha256": dev_smoke._json_sha256(schedule)
        },
    }
    adapter_path = tmp_path / "adapter.json"
    calibration_path = tmp_path / "calibration.json"
    _write_json(adapter_path, adapter)
    _write_json(calibration_path, calibration)
    return adapter_path, calibration_path, longmemeval_root


class FakeClient:
    def __init__(self) -> None:
        self.tokenizer_requests = 0
        self.max_model_len = 65_536
        self.identity_evidence = {
            "identity_report_sha256": "f" * 64,
            "base_url_class": "TEST_FAKE_LOCAL_ONLY",
            "served_model_id": dev_smoke.MODEL_ID,
            "vllm_lifecycle_mutated": False,
        }
        self.calls = 0

    def count_tokens(self, messages: object) -> int:
        self.tokenizer_requests += 1
        return max(1, len(json.dumps(messages, ensure_ascii=False)) // 4)

    def complete(
        self,
        messages: object,
        *,
        request_key: str,
        expected_prompt_tokens: int,
    ) -> dev_smoke.CompletionResult:
        self.calls += 1
        output = "raw forbidden answer 0"
        return dev_smoke.CompletionResult(
            text=output,
            native_request_id=f"chatcmpl-test-{self.calls:08d}",
            usage={"input_tokens": expected_prompt_tokens, "output_tokens": 5},
            latency_ms=float(self.calls),
            native_receipt_sha256=dev_smoke._sha256_bytes(request_key.encode()),
        )


def test_dev_smoke_builds_hash_only_report_and_raw_external_sidecar(
    tmp_path: Path,
) -> None:
    adapter, calibration, longmemeval_root = _fixture(tmp_path)
    client = FakeClient()
    report, sidecar = dev_smoke.run_smoke(
        adapter_report_path=adapter,
        calibration_plan_path=calibration,
        longmemeval_root=longmemeval_root,
        case_limit=1,
        arms=["NO_MEMORY", "NAIVE_RAG"],
        client=client,
    )

    assert report["status"] == "DEV_SMOKE_PARTIAL_NOT_CALIBRATION"
    assert report["quality_outcome"] == "CHARACTERIZED_ONLY"
    assert report["calibration_dev_labels_opened"] is True
    assert report["test_labels_or_outputs_opened"] is False
    assert report["quality_thresholds_frozen"] is False
    assert report["local_vllm_requests"] == 2
    assert report["external_provider_requests"] == 0
    assert report["unique_native_request_ids"] == 2
    assert report["execution"]["planned_model_rounds_by_executed_arm"] == {
        "NO_MEMORY": 1,
        "NAIVE_RAG": 1,
    }
    assert all(
        row["usage"]["hidden_or_extra_model_calls"] == 0
        for row in report["records"]
    )
    assert all(len(row["native_calls"]) == 1 for row in report["records"])
    assert all(
        row["native_calls"][0]["finish_reason"] == "stop"
        and row["answer_record"]["output_truncated"] is False
        for row in report["records"]
    )
    assert all(
        aggregate["truncated_output_count"] == 0
        for aggregate in report["aggregates"].values()
    )
    expected_record_fields = set(
        adapter_contract._adapter_output_schema()["required"]
    )
    assert all(set(row) == expected_record_fields for row in report["records"])
    assert client.calls == 2

    encoded_report = json.dumps(report, ensure_ascii=False)
    assert "raw forbidden question" not in encoded_report
    assert "raw forbidden answer" not in encoded_report
    assert "raw forbidden memory" not in encoded_report
    encoded_sidecar = json.dumps(sidecar, ensure_ascii=False)
    assert "raw forbidden question 0" in encoded_sidecar
    assert "raw forbidden answer 0" in encoded_sidecar
    assert "raw forbidden memory 0" in encoded_sidecar


def test_dev_smoke_rejects_unimplemented_milai_mcp_arm(tmp_path: Path) -> None:
    adapter, calibration, longmemeval_root = _fixture(tmp_path)
    with pytest.raises(dev_smoke.DevSmokeError, match="MILAI_MCP is not implemented"):
        dev_smoke.run_smoke(
            adapter_report_path=adapter,
            calibration_plan_path=calibration,
            longmemeval_root=longmemeval_root,
            case_limit=1,
            arms=["MILAI_MCP"],
            client=FakeClient(),
        )


def test_raw_capture_directory_must_be_outside_repository(tmp_path: Path) -> None:
    with pytest.raises(dev_smoke.DevSmokeError, match="outside the MiLAi repository"):
        dev_smoke._validate_capture_directory(dev_smoke.ROOT / "docs/raw")
    assert dev_smoke._validate_capture_directory(tmp_path) == tmp_path.resolve()


def test_answer_values_normalizes_integer_labels_without_bool_coercion() -> None:
    assert dev_smoke._answer_values(42) == ("42",)
    with pytest.raises(dev_smoke.DevSmokeError, match="answer"):
        dev_smoke._answer_values(True)


def test_benchmark_completion_retains_terminal_length_as_truncated_quality_output() -> None:
    response = {
        "id": "chatcmpl-test-length-0001",
        "model": dev_smoke.MODEL_ID,
        "choices": [
            {
                "finish_reason": "length",
                "message": {"content": "capped output", "tool_calls": []},
            }
        ],
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": dev_smoke.MAX_OUTPUT_TOKENS,
            "total_tokens": 11 + dev_smoke.MAX_OUTPUT_TOKENS,
        },
    }

    text, usage, native_id, receipt_sha256, finish_reason = (
        dev_smoke._validate_benchmark_completion(
            response,
            {"x-request-id": "request-test-length-0001"},
            expected_prompt_tokens=11,
            max_output_tokens=dev_smoke.MAX_OUTPUT_TOKENS,
        )
    )

    assert text == "capped output"
    assert usage["output_tokens"] == dev_smoke.MAX_OUTPUT_TOKENS
    assert native_id == response["id"]
    assert len(receipt_sha256) == 64
    assert finish_reason == "length"
