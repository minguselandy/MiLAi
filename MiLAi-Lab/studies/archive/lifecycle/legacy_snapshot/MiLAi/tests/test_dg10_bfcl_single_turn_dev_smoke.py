from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract
from scripts import run_dg10_bfcl_single_turn_dev_smoke as bfcl_smoke


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(value) + "\n" for value in values), encoding="utf-8"
    )


def _descriptor(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(root)),
        "sha256": dev_smoke._sha256_file(path),
        "size": path.stat().st_size,
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    root = tmp_path / "bfcl"
    source = root / "bfcl_eval/data/BFCL_v4_simple_python.json"
    labels = (
        root
        / "bfcl_eval/data/possible_answer/BFCL_v4_simple_python.json"
    )
    checker = root / "bfcl_eval/eval_checker/ast_eval/ast_checker.py"
    utils = root / "bfcl_eval/model_handler/utils.py"
    case_id = "bfcl_v4:simple_python_0"
    _write_jsonl(
        source,
        [
            {
                "id": "simple_python_0",
                "question": [
                    [{"role": "user", "content": "Weather for Paris?"}]
                ],
                "function": [
                    {
                        "name": "weather.get",
                        "description": "Get weather.",
                        "parameters": {
                            "type": "dict",
                            "properties": {
                                "city": {
                                    "type": "string",
                                    "description": "City name.",
                                }
                            },
                            "required": ["city"],
                        },
                    }
                ],
            }
        ],
    )
    _write_jsonl(
        labels,
        [
            {
                "id": "simple_python_0",
                "ground_truth": [{"weather.get": {"city": ["Paris"]}}],
            }
        ],
    )
    checker.parent.mkdir(parents=True, exist_ok=True)
    checker.write_text(
        """from enum import Enum
class Language(Enum):
    PYTHON = 'python'
def ast_checker(functions, output, answers, language, category, model):
    valid = output == [{'weather_get': {'city': 'Paris'}}]
    return {'valid': valid, 'error': [] if valid else ['bad'], 'error_type': None if valid else 'fixture'}
""",
        encoding="utf-8",
    )
    utils.parent.mkdir(parents=True, exist_ok=True)
    utils.write_text("# frozen fixture tool converter\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=DG10",
            "-c",
            "user.email=dg10@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
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
    source_descriptor = {
        **_descriptor(root, source),
        "case_count": 1,
        "case_ids_sha256": dev_smoke._json_sha256(["simple_python_0"]),
        "possible_answer": _descriptor(root, labels),
    }
    dataset_lock = {
        "schema": "milai.dg10.benchmark-dataset-lock.v1",
        "status": "DATASET_LOCK_CANDIDATE_REVIEW_REQUIRED",
        "datasets": {
            "bfcl_v4_local_non_live": {
                "git_head": git_head,
                "categories": {"simple_python": source_descriptor},
            }
        },
    }
    dataset_lock_path = tmp_path / "dataset-lock.json"
    dataset_lock_path.write_text(json.dumps(dataset_lock), encoding="utf-8")
    plan = {
        "schema": "milai.dg10.bfcl-v4-local-calibration-plan.v1",
        "candidate": bfcl_smoke.NATIVE_AUTO_PLAN_CANDIDATE,
        "status": "BFCL_LOCAL_NON_LIVE_CALIBRATION_PLAN_CANDIDATE_NOT_RUN",
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "inputs": {
            "dataset_lock_report_sha256": dev_smoke._sha256_file(
                dataset_lock_path
            )
        },
        "lane_contract": {"name": "fixture"},
        "quarantine": {"case_ids": []},
        "split": {
            "dev_case_ids": [case_id],
            "categories": {
                "simple_python": {"dev_case_ids": [case_id]}
            },
        },
        "scorer_contract": {
            "scorer_file_sha256": {
                "ast_checker": dev_smoke._sha256_file(checker),
                "model_handler_utils": dev_smoke._sha256_file(utils),
            }
        },
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    return dataset_lock_path, plan_path, root, case_id


class _FakeClient:
    max_model_len = 32768

    def __init__(self) -> None:
        self.tokenizer_requests = 1
        self.identity_evidence = {"identity_status": "FROZEN_TEST_FIXTURE"}

    def complete(
        self,
        messages: Any,
        tools: Any,
        *,
        request_key: str,
    ) -> bfcl_smoke.BfclCompletion:
        assert messages[0]["content"] == "Weather for Paris?"
        assert tools[0]["function"]["name"] == "weather_get"
        assert request_key
        return bfcl_smoke.BfclCompletion(
            native_request_id="chatcmpl-fixture-0001",
            finish_reason="tool_calls",
            model_responses=({"weather_get": '{"city":"Paris"}'},),
            content=None,
            usage={"input_tokens": 42, "output_tokens": 8},
            latency_ms=12.5,
            native_receipt_sha256="a" * 64,
            response_sha256="b" * 64,
        )


def test_single_turn_smoke_hash_binds_raw_data_outside_report(
    tmp_path: Path,
) -> None:
    dataset_lock, plan, root, case_id = _fixture(tmp_path)
    report, sidecar = bfcl_smoke.run_smoke(
        dataset_lock_path=dataset_lock,
        plan_path=plan,
        bfcl_root=root,
        case_id=case_id,
        client=_FakeClient(),
    )

    assert report["candidate"] == "candidate.1"
    assert report["record"]["answer_record"]["official_checker_valid"] is True
    assert report["record"]["answer_record"]["tool_selection_correct"] is True
    assert report["local_vllm_requests"] == 1
    assert report["external_provider_requests"] == 0
    assert report["test_access_authorized"] is False
    assert report["inputs"]["tool_conversion_source_sha256"] == (
        dev_smoke._sha256_file(root / "bfcl_eval/model_handler/utils.py")
    )
    encoded_report = json.dumps(report)
    assert "Weather for Paris?" not in encoded_report
    assert '"city":"Paris"' not in encoded_report
    assert sidecar["record"]["messages"][0]["content"] == "Weather for Paris?"
    assert sidecar["record"]["ground_truth"][0]["weather.get"]["city"] == [
        "Paris"
    ]


def test_single_turn_smoke_rejects_quarantined_case(tmp_path: Path) -> None:
    dataset_lock, plan_path, root, case_id = _fixture(tmp_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["quarantine"]["case_ids"] = ["simple_python_0"]
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(bfcl_smoke.BfclSmokeError, match="quarantined"):
        bfcl_smoke.run_smoke(
            dataset_lock_path=dataset_lock,
            plan_path=plan_path,
            bfcl_root=root,
            case_id=case_id,
            client=_FakeClient(),
        )


def test_frozen_official_python_checker_loads_without_vendor_sdks() -> None:
    checker, digest = bfcl_smoke._load_python_ast_checker(
        bfcl_contract.DEFAULT_BFCL_ROOT
    )

    assert callable(checker.ast_checker)
    assert digest == dev_smoke._sha256_file(
        bfcl_contract.DEFAULT_BFCL_ROOT
        / "bfcl_eval/eval_checker/ast_eval/ast_checker.py"
    )
