from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts import run_dg10_benchmark_adapter_contract as adapter_contract
from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_benchmark_lme_v2_dev_smoke as lme_v2_smoke


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values),
        encoding="utf-8",
    )


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "LongMemEval-V2"
    data_root = root / "data/longmemeval-v2"
    questions: list[dict[str, Any]] = []
    for index in range(20):
        questions.append(
            {
                "id": f"q-{index:03d}",
                "domain": "web",
                "environment": "webarena-cms",
                "question_type": "static-environment",
                "question": f"raw forbidden question memory {index}",
                "image": None,
                "answer": f"raw forbidden answer {index}",
                "eval_function": (
                    "llm_abstention_checker|require_non_empty=true"
                    if index == 1
                    else "norm_phrase_set_match|require_non_empty=true"
                ),
            }
        )
    # The public small tier requires 100 unique trajectory IDs per question.
    trajectories = []
    for index in range(100):
        trajectories.append(
            {
                "id": f"t-{index:03d}",
                "domain": "web",
                "environment": "webarena-cms",
                "goal": f"raw forbidden goal {index}",
                "outcome": "success",
                "start_url": "https://example.invalid",
                "states": [
                    {
                        "state_index": 0,
                        "url": "https://example.invalid/page",
                        "thought": f"raw forbidden memory {index}",
                        "action": {"type": "click", "target": index},
                        "accessibility_tree": (
                            f"raw forbidden answer {index} and relevant visible state"
                        ),
                        "screenshot": f"screenshots/t-{index:03d}/0.png",
                    }
                ],
            }
        )
    haystack = {
        f"q-{index:03d}": [f"t-{offset:03d}" for offset in range(100)]
        for index in range(20)
    }
    questions_path = data_root / "questions.jsonl"
    trajectories_path = data_root / "trajectories.jsonl"
    haystack_path = data_root / "haystacks/lme_v2_small.json"
    _write_jsonl(questions_path, questions)
    _write_jsonl(trajectories_path, trajectories)
    _write_json(haystack_path, haystack)

    all_ids = sorted(row["id"] for row in questions)
    files = {
        "data/longmemeval-v2/questions.jsonl": {
            "sha256": dev_smoke._sha256_file(questions_path),
            "size": questions_path.stat().st_size,
        },
        "data/longmemeval-v2/trajectories.jsonl": {
            "sha256": dev_smoke._sha256_file(trajectories_path),
            "size": trajectories_path.stat().st_size,
            "trajectory_count_from_data_card": len(trajectories),
        },
        "data/longmemeval-v2/haystacks/lme_v2_small.json": {
            "sha256": dev_smoke._sha256_file(haystack_path),
            "size": haystack_path.stat().st_size,
        },
    }
    dataset_lock = {
        "schema": "milai.dg10.benchmark-dataset-lock.v1",
        "status": "DATASET_LOCK_CANDIDATE_REVIEW_REQUIRED",
        "datasets": {
            "longmemeval_v2": {
                "files": files,
                "question_counts": {
                    "total": len(questions),
                    "text_only": len(questions),
                    "all_case_ids_sha256": dev_smoke._json_sha256(all_ids),
                    "text_only_case_ids_sha256": dev_smoke._json_sha256(all_ids),
                },
            }
        },
    }
    dataset_lock_path = tmp_path / "dataset-lock.json"
    _write_json(dataset_lock_path, dataset_lock)
    dataset_lock_sha256 = dev_smoke._sha256_file(dataset_lock_path)

    adapter = {
        "schema": "milai.dg10.benchmark-adapter-contract.v1",
        "status": "ADAPTER_CONTRACT_CANDIDATE_REVIEW_REQUIRED",
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "inputs": {"dataset_lock_report_sha256": dataset_lock_sha256},
        "generation_contract": adapter_contract._generation_contract(),
        "generation_contract_sha256": adapter_contract._json_sha256(
            adapter_contract._generation_contract()
        ),
        "prompt_templates_sha256": adapter_contract._json_sha256(
            adapter_contract._prompt_templates()
        ),
        "gate_results": {"BMG-03": "CANDIDATE_LOCKED_NOT_RUN"},
    }
    dev_ids = ["longmemeval_v2:q-000", "longmemeval_v2:q-001"]
    schedule = [
        {
            "case_id": case_id,
            "order": list(adapter_contract._latin_square_order(case_id)),
        }
        for case_id in dev_ids
    ]
    calibration = {
        "schema": "milai.dg10.benchmark-calibration-plan.v1",
        "status": "CALIBRATION_PLAN_CANDIDATE_NOT_RUN",
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "inputs": {
            "adapter_contract_sha256": dev_smoke._json_sha256(adapter),
            "dataset_lock_report_sha256": dataset_lock_sha256,
        },
        "dev_split": {
            "dev_case_ids": dev_ids,
            "dev_case_count": len(dev_ids),
            "dev_case_ids_sha256": dev_smoke._json_sha256(dev_ids),
            "dev_fraction": 0.10,
            "per_dataset": {
                lme_v2_smoke.DATASET: {
                    "total": len(questions),
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
    return dataset_lock_path, adapter_path, calibration_path, root


class FakeClient:
    def __init__(self, finish_reason: str = "stop") -> None:
        self.tokenizer_requests = 0
        self.max_model_len = 65_536
        self.identity_evidence = {
            "identity_report_sha256": "f" * 64,
            "base_url_class": "TEST_FAKE_LOCAL_ONLY",
            "served_model_id": dev_smoke.MODEL_ID,
            "vllm_lifecycle_mutated": False,
        }
        self.calls = 0
        self.finish_reason = finish_reason

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
        case_index = 1 if "q-001" in request_key else 0
        output = f"raw forbidden answer {case_index}"
        return dev_smoke.CompletionResult(
            text=output,
            native_request_id=f"chatcmpl-test-{self.calls:08d}",
            usage={"input_tokens": expected_prompt_tokens, "output_tokens": 5},
            latency_ms=float(self.calls),
            native_receipt_sha256=dev_smoke._sha256_bytes(request_key.encode()),
            finish_reason=self.finish_reason,
        )


def _run(
    tmp_path: Path,
    *,
    requested_case_ids: list[str] | None = None,
    client: FakeClient | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    dataset_lock, adapter, calibration, root = _fixture(tmp_path)
    return lme_v2_smoke.run_smoke(
        dataset_lock_path=dataset_lock,
        adapter_report_path=adapter,
        calibration_plan_path=calibration,
        longmemeval_v2_root=root,
        qa_evaluator_path=lme_v2_smoke.DEFAULT_QA_EVALUATOR,
        case_limit=1,
        requested_case_ids=requested_case_ids,
        arms=["NO_MEMORY", "NAIVE_RAG"],
        client=client or FakeClient(),
    )


def test_v2_smoke_streams_locked_text_only_data_and_separates_raw_sidecar(
    tmp_path: Path,
) -> None:
    report, sidecar = _run(tmp_path)

    assert report["status"].endswith("NOT_CALIBRATION")
    assert report["local_vllm_requests"] == 2
    assert report["external_provider_requests"] == 0
    assert report["scoring"] == {
        "selected_case_count": 1,
        "official_local_deterministic_case_count": 1,
        "adapted_fallback_case_count": 0,
        "external_llm_judge_calls": 0,
        "denominators_separated": True,
    }
    assert report["adapted_protocol"]["question_images_used"] is False
    assert report["adapted_protocol"]["trajectory_screenshots_used"] is False
    assert report["adapted_protocol"]["leaderboard_claim"] is False
    assert all(
        row["answer_record"]["official_local_deterministic_score"] is True
        for row in report["records"]
    )
    assert all(
        row["native_calls"][0]["finish_reason"] == "stop"
        and row["answer_record"]["output_truncated"] is False
        for row in report["records"]
    )
    assert all(
        set(row) == set(adapter_contract._adapter_output_schema()["required"])
        for row in report["records"]
    )
    encoded_report = json.dumps(report, ensure_ascii=False)
    assert "raw forbidden question" not in encoded_report
    assert "raw forbidden answer" not in encoded_report
    assert "raw forbidden memory" not in encoded_report
    encoded_sidecar = json.dumps(sidecar, ensure_ascii=False)
    assert "raw forbidden question memory 0" in encoded_sidecar
    assert "raw forbidden answer 0" in encoded_sidecar
    assert "raw forbidden memory" in encoded_sidecar


def test_v2_smoke_never_invokes_llm_judge_for_llm_eval_function(
    tmp_path: Path,
) -> None:
    report, _sidecar = _run(
        tmp_path, requested_case_ids=["longmemeval_v2:q-001"]
    )

    assert report["scoring"]["official_local_deterministic_case_count"] == 0
    assert report["scoring"]["adapted_fallback_case_count"] == 1
    assert report["external_provider_requests"] == 0
    for row in report["records"]:
        answer = row["answer_record"]
        assert answer["official_local_deterministic_score"] is None
        assert answer["external_judge_called"] is False
        assert answer["scoring_lane"].startswith("ADAPTED_FALLBACK")


def test_v2_smoke_preserves_terminal_length_and_aggregates_truncation(
    tmp_path: Path,
) -> None:
    report, _sidecar = _run(tmp_path, client=FakeClient(finish_reason="length"))

    assert all(
        row["native_calls"][0]["finish_reason"] == "length"
        and row["answer_record"]["output_truncated"] is True
        and row["status"].endswith("OUTPUT_TRUNCATED")
        for row in report["records"]
    )
    assert all(
        aggregate["truncated_output_count"] == 1
        and aggregate["truncated_output_rate"] == 1.0
        for aggregate in report["aggregates"].values()
    )


def test_v2_smoke_rejects_dataset_bytes_outside_lock(tmp_path: Path) -> None:
    dataset_lock, adapter, calibration, root = _fixture(tmp_path)
    trajectories = root / "data/longmemeval-v2/trajectories.jsonl"
    trajectories.write_text(
        trajectories.read_text(encoding="utf-8") + "{}\n", encoding="utf-8"
    )

    with pytest.raises(lme_v2_smoke.LmeV2SmokeError, match="size differs"):
        lme_v2_smoke.run_smoke(
            dataset_lock_path=dataset_lock,
            adapter_report_path=adapter,
            calibration_plan_path=calibration,
            longmemeval_v2_root=root,
            qa_evaluator_path=lme_v2_smoke.DEFAULT_QA_EVALUATOR,
            case_limit=1,
            requested_case_ids=None,
            arms=["NO_MEMORY"],
            client=FakeClient(),
        )


def test_v2_smoke_rejects_milai_mcp_arm_before_data_access(tmp_path: Path) -> None:
    with pytest.raises(lme_v2_smoke.LmeV2SmokeError, match="not implemented"):
        lme_v2_smoke.run_smoke(
            dataset_lock_path=tmp_path / "missing-lock.json",
            adapter_report_path=tmp_path / "missing-adapter.json",
            calibration_plan_path=tmp_path / "missing-plan.json",
            longmemeval_v2_root=tmp_path / "missing-data",
            qa_evaluator_path=lme_v2_smoke.DEFAULT_QA_EVALUATOR,
            case_limit=1,
            requested_case_ids=None,
            arms=["MILAI_MCP"],
            client=FakeClient(),
        )


def test_v2_smoke_binds_one_invalidated_prior_call_without_denominator_leak(
    tmp_path: Path,
) -> None:
    dataset_lock, adapter, calibration, root = _fixture(tmp_path)
    failed = tmp_path / "failed-attempt.json"
    _write_json(
        failed,
        {
            "schema": "milai.dg10.benchmark-lme-v2-failed-attempt-receipt.v1",
            "status": "INVALIDATED_FAILED_ATTEMPT_EXCLUDED_FROM_CALIBRATION",
            "test_labels_or_outputs_opened": False,
            "execution": {
                "local_vllm_completion_http_200_requests": 1,
                "validated_records": 0,
            },
            "supersession_and_retry_accounting": {
                "cross_attempt_repeated_case_arm_requests_expected": 1
            },
        },
    )

    report, _sidecar = lme_v2_smoke.run_smoke(
        dataset_lock_path=dataset_lock,
        adapter_report_path=adapter,
        calibration_plan_path=calibration,
        longmemeval_v2_root=root,
        qa_evaluator_path=lme_v2_smoke.DEFAULT_QA_EVALUATOR,
        case_limit=1,
        requested_case_ids=None,
        arms=["NO_MEMORY", "NAIVE_RAG"],
        client=FakeClient(),
        superseded_attempt_receipt_path=failed,
    )

    prior = report["superseded_failed_attempt"]
    assert report["local_vllm_requests"] == 2
    assert prior["prior_completion_http_200_requests"] == 1
    assert prior["prior_validated_records"] == 0
    assert prior["cross_attempt_repeated_case_arm_requests"] == 1
    assert prior["current_candidate_internal_retries"] == 0
