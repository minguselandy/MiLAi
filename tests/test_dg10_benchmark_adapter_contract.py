from __future__ import annotations

import json
from pathlib import Path

from scripts import run_dg10_benchmark_adapter_contract as adapter_contract


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _make_longmemeval(root: Path, count: int = 20) -> list[str]:
    ids = [f"lme-{index:03d}" for index in range(count)]
    rows = []
    for index, question_id in enumerate(ids):
        rows.append(
            {
                "question_id": question_id,
                "question_type": "knowledge-update"
                if index % 2
                else "single-session-user",
                "question": f"raw secret question {index}",
                "question_date": "2026/08/21",
                "answer": f"raw secret answer {index}",
                "answer_session_ids": [f"s-{index}"],
                "haystack_dates": ["2026/08/20"],
                "haystack_session_ids": [f"s-{index}"],
                "haystack_sessions": [[f"raw haystack {index}"]],
            }
        )
    _write_json(root / "data/longmemeval_s_cleaned.json", rows)
    _write_json(root / "data/longmemeval_m_cleaned.json", rows)
    _write_json(root / "data/longmemeval_oracle.json", rows)
    return ids


def _make_longmemeval_v2(root: Path, text_count: int = 20, image_count: int = 2) -> list[str]:
    text_ids = [f"v2t-{index:03d}" for index in range(text_count)]
    image_ids = [f"v2i-{index:03d}" for index in range(image_count)]
    rows = []
    for question_id in text_ids:
        rows.append(
            {
                "id": question_id,
                "domain": "web",
                "environment": "webarena-reddit",
                "question_type": "static-environment",
                "question": f"raw text-only question {question_id}",
                "image": None,
                "answer": f"raw text-only answer {question_id}",
                "eval_function": "exact_match",
            }
        )
    for question_id in image_ids:
        rows.append(
            {
                "id": question_id,
                "domain": "enterprise",
                "environment": "workarena",
                "question_type": "dynamic-environment",
                "question": f"raw image question {question_id}",
                "image": f"question_screenshots/{question_id}.png",
                "answer": f"raw image answer {question_id}",
                "eval_function": "exact_match",
            }
        )
    data_root = root / "data/longmemeval-v2"
    _write_jsonl(data_root / "questions.jsonl", rows)
    _write_jsonl(
        data_root / "trajectories.jsonl",
        [
            {
                "id": "t1",
                "domain": "web",
                "environment": "webarena-reddit",
                "goal": "raw trajectory goal",
                "outcome": "success",
                "start_url": "https://example.invalid",
                "states": [],
            }
        ],
    )
    _write_json(
        data_root / "haystacks/lme_v2_small.json",
        {question_id: ["t1"] for question_id in [*text_ids, *image_ids]},
    )
    _write_json(
        data_root / "haystacks/lme_v2_medium.json",
        {question_id: ["t1"] for question_id in [*text_ids, *image_ids]},
    )
    return text_ids


def _make_reports(
    tmp_path: Path, lme_ids: list[str], lme_v2_text_ids: list[str]
) -> tuple[Path, Path]:
    dataset_lock = {
        "schema": "milai.dg10.benchmark-dataset-lock.v1",
        "status": "DATASET_LOCK_CANDIDATE_REVIEW_REQUIRED",
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "datasets": {
            "longmemeval": {
                "files": {
                    "data/longmemeval_s_cleaned.json": {
                        "case_ids_sha256": adapter_contract._json_sha256(sorted(lme_ids))
                    }
                }
            },
            "longmemeval_v2": {
                "question_counts": {
                    "text_only_case_ids_sha256": adapter_contract._json_sha256(
                        sorted(lme_v2_text_ids)
                    )
                }
            },
        },
    }
    feasibility = {
        "schema": "milai.dg10.benchmark-feasibility.v1",
        "status": "FEASIBILITY_CANDIDATE_REVIEW_REQUIRED",
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "gate_results": {
            "BMG-03": "NO_GO_MISSING_BFCL_LOCAL_NON_LIVE_LOCK",
        },
    }
    dataset_lock_path = tmp_path / "dataset-lock.json"
    feasibility_path = tmp_path / "feasibility.json"
    _write_json(dataset_lock_path, dataset_lock)
    _write_json(feasibility_path, feasibility)
    return dataset_lock_path, feasibility_path


def test_adapter_contract_builds_three_arm_manifest_without_raw_benchmark_content(
    tmp_path: Path,
) -> None:
    longmemeval_root = tmp_path / "LongMemEval"
    longmemeval_v2_root = tmp_path / "LongMemEval-V2"
    lme_ids = _make_longmemeval(longmemeval_root)
    lme_v2_text_ids = _make_longmemeval_v2(longmemeval_v2_root)
    dataset_lock, feasibility = _make_reports(tmp_path, lme_ids, lme_v2_text_ids)

    adapter_report, calibration_report = adapter_contract.build_reports(
        dataset_lock, feasibility, longmemeval_root, longmemeval_v2_root
    )

    assert adapter_report["status"] == "ADAPTER_CONTRACT_CANDIDATE_REVIEW_REQUIRED"
    assert adapter_report["candidate"] == "candidate.4"
    assert adapter_report["arms"] == ["NO_MEMORY", "NAIVE_RAG", "MILAI_MCP"]
    assert adapter_report["case_manifest"]["case_count"] == 40
    assert adapter_report["arm_request_manifest"]["record_count"] == 120
    assert adapter_report["arm_request_manifest"]["records_per_case"] == 3
    assert adapter_report["adapter_output_schema"]["additionalProperties"] is False
    assert "native_calls" in adapter_report["adapter_output_schema"]["required"]
    assert "native_request_id" not in adapter_report["adapter_output_schema"]["required"]
    assert adapter_report["planned_round_contract"]["model_rounds_by_arm"] == {
        "NO_MEMORY": 1,
        "NAIVE_RAG": 1,
        "MILAI_MCP": 2,
    }
    assert adapter_report["planned_round_contract"]["mcp_calls_by_arm"] == {
        "NO_MEMORY": 0,
        "NAIVE_RAG": 0,
        "MILAI_MCP": 1,
    }

    assert calibration_report["status"] == "CALIBRATION_PLAN_CANDIDATE_NOT_RUN"
    assert calibration_report["candidate"] == "candidate.4"
    assert calibration_report["dev_split"]["dev_case_count"] == 4
    assert calibration_report["dev_split"]["dev_fraction"] <= 0.1
    assert calibration_report["quality_acceptance_update_state"][
        "test_labels_or_outputs_opened_by_this_report"
    ] is False

    encoded = json.dumps([adapter_report, calibration_report], ensure_ascii=False)
    forbidden = (
        "raw secret question",
        "raw secret answer",
        "raw haystack",
        "raw text-only question",
        "raw text-only answer",
        "raw image question",
        "raw image answer",
        "raw trajectory goal",
    )
    assert all(item not in encoded for item in forbidden)


def test_adapter_contract_rejects_case_id_digest_drift(tmp_path: Path) -> None:
    longmemeval_root = tmp_path / "LongMemEval"
    longmemeval_v2_root = tmp_path / "LongMemEval-V2"
    lme_ids = _make_longmemeval(longmemeval_root)
    lme_v2_text_ids = _make_longmemeval_v2(longmemeval_v2_root)
    dataset_lock, feasibility = _make_reports(tmp_path, lme_ids, lme_v2_text_ids)
    value = json.loads(dataset_lock.read_text(encoding="utf-8"))
    value["datasets"]["longmemeval"]["files"]["data/longmemeval_s_cleaned.json"][
        "case_ids_sha256"
    ] = "0" * 64
    _write_json(dataset_lock, value)

    try:
        adapter_contract.build_reports(
            dataset_lock, feasibility, longmemeval_root, longmemeval_v2_root
        )
    except adapter_contract.AdapterContractError as exc:
        assert "LongMemEval case-id digest mismatch" in str(exc)
    else:  # pragma: no cover - failure path
        raise AssertionError("digest drift was accepted")
