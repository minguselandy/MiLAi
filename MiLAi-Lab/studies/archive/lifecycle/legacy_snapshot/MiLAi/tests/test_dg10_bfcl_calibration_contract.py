from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values),
        encoding="utf-8",
    )


def _fixture(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, tuple[str, ...]]:
    root = tmp_path / "bfcl"
    data_root = root / "bfcl_eval/data"
    checker_paths = [
        root / "bfcl_eval/eval_checker/eval_runner.py",
        root / "bfcl_eval/eval_checker/ast_eval/ast_checker.py",
        root / "bfcl_eval/eval_checker/multi_turn_eval/multi_turn_checker.py",
        root / "bfcl_eval/model_handler/api_inference/openai_completion.py",
        root / "bfcl_eval/model_handler/utils.py",
        root / "bfcl_eval/constants/default_prompts.py",
        root / "bfcl_eval/model_handler/local_inference/qwen.py",
        root / "bfcl_eval/model_handler/local_inference/base_oss_handler.py",
    ]
    for path in checker_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# frozen checker {path.name}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.name=DG10", "-c", "user.email=dg10@example.invalid", "commit", "--allow-empty", "-qm", "fixture"],
        cwd=root,
        check=True,
    )
    git_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    disclosed = (
        "simple_java_3",
        "simple_python_4",
        "multiple_5",
        "parallel_6",
    )
    categories: dict[str, Any] = {}
    all_ids: list[str] = []
    for category in bfcl_contract.LOCAL_NON_LIVE_CATEGORIES:
        rows = [
            {
                "id": f"{category}_{index}",
                "question": [[{"role": "user", "content": f"raw prompt {category} {index}"}]],
                "function": [],
            }
            for index in range(20)
        ]
        ids = [str(row["id"]) for row in rows]
        all_ids.extend(ids)
        source_path = data_root / f"BFCL_v4_{category}.json"
        _write_jsonl(source_path, rows)
        if category == "irrelevance":
            possible_answer = {
                "path": None,
                "status": "NOT_PRESENT_EXPECTED_FOR_RELEVANCE_OR_IRRELEVANCE_CATEGORY",
            }
        else:
            answer_path = data_root / "possible_answer" / f"BFCL_v4_{category}.json"
            _write_jsonl(
                answer_path,
                [
                    {"id": source_id, "ground_truth": f"raw label {source_id}"}
                    for source_id in ids
                ],
            )
            possible_answer = {
                "path": str(answer_path.relative_to(root)),
                "sha256": dev_smoke._sha256_file(answer_path),
                "size": answer_path.stat().st_size,
                "status": "COVERAGE_MATCHES_CASE_IDS",
            }
        categories[category] = {
            "category": category,
            "path": str(source_path.relative_to(root)),
            "sha256": dev_smoke._sha256_file(source_path),
            "size": source_path.stat().st_size,
            "case_count": len(rows),
            "case_ids_sha256": dev_smoke._json_sha256(sorted(ids)),
            "possible_answer": possible_answer,
        }
    all_ids.sort()
    dataset_lock = {
        "schema": "milai.dg10.benchmark-dataset-lock.v1",
        "status": "DATASET_LOCK_CANDIDATE_REVIEW_REQUIRED",
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "datasets": {
            "bfcl_v4_local_non_live": {
                "git_head": git_head,
                "categories": categories,
                "eval_runner": {
                    "sha256": dev_smoke._sha256_file(checker_paths[0])
                },
                "local_non_live": {
                    "case_count": len(all_ids),
                    "case_ids_sha256": dev_smoke._json_sha256(all_ids),
                },
            }
        },
    }
    feasibility = {
        "schema": "milai.dg10.benchmark-feasibility.v1",
        "status": "FEASIBILITY_CANDIDATE_REVIEW_REQUIRED",
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "datasets": {
            "bfcl_v4_local_non_live": {
                "decision": "LOCAL_NON_LIVE_CASE_LIST_CANDIDATE_NOT_RUN",
                "compatible_case_count": len(all_ids),
                "compatible_case_ids_sha256": dev_smoke._json_sha256(all_ids),
            }
        },
        "gate_results": {"BMG-03": "CANDIDATE_LOCKED_NOT_RUN"},
    }
    dataset_lock_path = tmp_path / "dataset-lock.json"
    feasibility_path = tmp_path / "feasibility.json"
    _write_json(dataset_lock_path, dataset_lock)
    _write_json(feasibility_path, feasibility)
    probe_path = tmp_path / "probe.json"
    _write_json(
        probe_path,
        {
            "schema": "milai.dg10.bfcl-prompt-capability-probe.v1",
            "candidate": "candidate.1",
            "status": "BFCL_ADAPTED_PROMPT_SYNTHETIC_CAPABILITY_PROBE_PASS",
            "benchmark_material_opened_by_probe": False,
            "test_access_authorized": False,
            "quality_thresholds_frozen": False,
            "local_vllm_requests": 5,
            "retry_model_calls": 0,
            "hidden_or_extra_model_calls": 0,
            "provider_requests": 0,
            "external_provider_requests": 0,
            "aggregates": {"dialogues_passed": 4, "model_rounds_executed": 5},
            "gate_results": {"synthetic_prompt_capability": "PASS"},
            "repo_external_sidecar": {"status": "WRITTEN_HASH_BOUND"},
        },
    )
    return dataset_lock_path, feasibility_path, root, probe_path, disclosed


def test_bfcl_contract_freezes_stratified_dev_without_opening_labels(
    tmp_path: Path,
) -> None:
    dataset_lock, feasibility, root, probe, disclosed = _fixture(tmp_path)
    report = bfcl_contract.build_report(
        dataset_lock_path=dataset_lock,
        feasibility_path=feasibility,
        bfcl_root=root,
        probe_report_path=probe,
        disclosed_case_ids=disclosed,
    )

    assert report["status"].endswith("NOT_RUN")
    assert report["candidate"] == "candidate.5"
    assert report["split"]["locked_case_count"] == 220
    assert report["split"]["eligible_case_count"] == 216
    assert report["split"]["dev_fraction"] <= 0.10
    assert report["quarantine"]["case_ids"] == sorted(disclosed)
    assert report["test_access_authorized"] is False
    assert report["test_labels_or_outputs_opened_by_this_report"] is False
    assert report["lane_contract"]["mcp_transport_claim"] is False
    assert report["lane_contract"]["normative_clarification_status"].startswith(
        "REVIEW_REQUIRED"
    )
    assert report["scorer_contract"]["scorer_file_sha256"][
        "model_handler_utils"
    ] == dev_smoke._sha256_file(root / "bfcl_eval/model_handler/utils.py")
    assert report["lane_contract"]["native_auto_lane"]["status"].startswith(
        "NOT_APPLICABLE"
    )
    assert report["generation_contract"]["native_tools_field_present"] is False
    assert report["generation_contract"]["tool_choice_field_present"] is False
    assert report["synthetic_capability_probe"]["total_model_rounds"] == 5
    assert report["synthetic_capability_probe"]["status"] == "PASS_BOUND"
    assert report["synthetic_capability_probe"]["fixtures_sha256"] == (
        dev_smoke._json_sha256(bfcl_contract.SYNTHETIC_PROBE_FIXTURES)
    )
    encoded = json.dumps(report, ensure_ascii=False)
    assert "raw prompt" not in encoded
    assert "raw label" not in encoded
    for category in bfcl_contract.LOCAL_NON_LIVE_CATEGORIES:
        item = report["split"]["categories"][category]
        assert item["dev_case_count"] > 0
        assert item["labels_semantically_opened_by_plan"] is False


def test_bfcl_contract_rejects_unknown_disclosed_case(tmp_path: Path) -> None:
    dataset_lock, feasibility, root, probe, _disclosed = _fixture(tmp_path)
    with pytest.raises(bfcl_contract.BfclContractError, match="quarantine IDs are absent"):
        bfcl_contract.build_report(
            dataset_lock_path=dataset_lock,
            feasibility_path=feasibility,
            bfcl_root=root,
            probe_report_path=probe,
            disclosed_case_ids=["simple_python_missing"],
        )


def test_bfcl_contract_rejects_source_byte_drift(tmp_path: Path) -> None:
    dataset_lock, feasibility, root, probe, disclosed = _fixture(tmp_path)
    source = root / "bfcl_eval/data/BFCL_v4_simple_python.json"
    source.write_text(source.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
    with pytest.raises(bfcl_contract.BfclContractError, match="differs"):
        bfcl_contract.build_report(
            dataset_lock_path=dataset_lock,
            feasibility_path=feasibility,
            bfcl_root=root,
            probe_report_path=probe,
            disclosed_case_ids=disclosed,
        )
