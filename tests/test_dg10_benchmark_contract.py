from __future__ import annotations

import json
from pathlib import Path

from scripts import run_dg10_benchmark_contract as benchmark_contract


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _make_longmemeval(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "README.md").write_text("LongMemEval fixture\n", encoding="utf-8")
    (root / "LICENSE").write_text("fixture license\n", encoding="utf-8")
    rows = [
        {
            "question_id": "q1",
            "question_type": "single-session-user",
            "question": "What is my degree?",
            "question_date": "2026/08/21",
            "answer": "Business",
            "answer_session_ids": ["s1"],
            "haystack_dates": ["2026/08/20"],
            "haystack_session_ids": ["s1"],
            "haystack_sessions": [["hello"]],
        },
        {
            "question_id": "q2",
            "question_type": "knowledge-update",
            "question": "What changed?",
            "question_date": "2026/08/21",
            "answer": "runtime",
            "answer_session_ids": ["s2"],
            "haystack_dates": ["2026/08/20"],
            "haystack_session_ids": ["s2"],
            "haystack_sessions": [["runtime"]],
        },
    ]
    _write_json(root / "data/longmemeval_s_cleaned.json", rows)
    _write_json(root / "data/longmemeval_m_cleaned.json", rows)
    _write_json(root / "data/longmemeval_oracle.json", rows)


def _make_longmemeval_v2(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "README.md").write_text("LongMemEval-V2 fixture\n", encoding="utf-8")
    data_root = root / "data/longmemeval-v2"
    data_root.mkdir(parents=True)
    (data_root / "LICENSE").write_text("fixture license\n", encoding="utf-8")
    (data_root / "checksums.sha256").write_text("fixture checksums\n", encoding="utf-8")
    questions = [
        {
            "id": "a",
            "domain": "web",
            "environment": "webarena-reddit",
            "question_type": "static-environment",
            "question": "Text-only?",
            "image": None,
            "answer": "yes",
            "eval_function": "exact_match",
        },
        {
            "id": "b",
            "domain": "enterprise",
            "environment": "workarena",
            "question_type": "dynamic-environment",
            "question": "Needs image?",
            "image": "question_screenshots/b.png",
            "answer": "image",
            "eval_function": "exact_match",
        },
    ]
    _write_jsonl(data_root / "questions.jsonl", questions)
    _write_jsonl(
        data_root / "trajectories.jsonl",
        [
            {
                "id": "t1",
                "domain": "web",
                "environment": "webarena-reddit",
                "goal": "fixture",
                "outcome": "success",
                "start_url": "https://example.invalid",
                "states": [
                    {
                        "state_index": 0,
                        "step": 0,
                        "url": "https://example.invalid",
                        "action": None,
                        "thought": "fixture",
                        "accessibility_tree": "Root",
                        "screenshot": "screenshots/t1/0.png",
                    }
                ],
            }
        ],
    )
    _write_json(data_root / "haystacks/lme_v2_small.json", {"a": ["t1"], "b": ["t1"]})
    _write_json(data_root / "haystacks/lme_v2_medium.json", {"a": ["t1"], "b": ["t1"]})
    (data_root / "question_screenshots").mkdir()
    (data_root / "question_screenshots/b.png").write_bytes(b"png")
    (data_root / "trajectory_screenshots/t1").mkdir(parents=True)
    (data_root / "trajectory_screenshots/t1/0.png").write_bytes(b"png")


def _make_bfcl(root: Path) -> None:
    bfcl_root = root / "gorilla-bfcl/berkeley-function-call-leaderboard"
    data_root = bfcl_root / "bfcl_eval/data"
    answer_root = data_root / "possible_answer"
    (bfcl_root / "bfcl_eval/constants").mkdir(parents=True)
    (bfcl_root / "bfcl_eval/eval_checker").mkdir(parents=True)
    answer_root.mkdir(parents=True)
    (bfcl_root.parent / "LICENSE").write_text("Apache 2 fixture\n", encoding="utf-8")
    (bfcl_root / "README.md").write_text("BFCL fixture\n", encoding="utf-8")
    (bfcl_root / "pyproject.toml").write_text("[project]\nname='bfcl'\n", encoding="utf-8")
    (bfcl_root / "TEST_CATEGORIES.md").write_text("non_live\n", encoding="utf-8")
    (bfcl_root / "bfcl_eval/constants/category_mapping.py").write_text(
        "NON_LIVE_CATEGORY=[]\n",
        encoding="utf-8",
    )
    (bfcl_root / "bfcl_eval/eval_checker/eval_runner.py").write_text(
        "def run():\n    return None\n",
        encoding="utf-8",
    )
    for category in benchmark_contract.BFCL_LOCAL_NON_LIVE_CATEGORIES:
        case_id = f"{category}_0"
        _write_jsonl(
            data_root / f"BFCL_v4_{category}.json",
            [
                {
                    "id": case_id,
                    "question": [[{"role": "user", "content": "fixture"}]],
                    "function": [],
                }
            ],
        )
        if category != "irrelevance":
            _write_jsonl(
                answer_root / f"BFCL_v4_{category}.json",
                [{"id": case_id, "ground_truth": []}],
            )


def test_benchmark_contract_generator_reports_adapted_lme_v2_and_missing_bfcl(
    tmp_path: Path,
) -> None:
    longmemeval = tmp_path / "LongMemEval"
    longmemeval_v2 = tmp_path / "LongMemEval-V2"
    _make_longmemeval(longmemeval)
    _make_longmemeval_v2(longmemeval_v2)

    dataset_lock, feasibility = benchmark_contract.build_reports(
        longmemeval, longmemeval_v2, tmp_path / "empty-search-root"
    )

    assert dataset_lock["status"] == "DATASET_LOCK_CANDIDATE_REVIEW_REQUIRED"
    assert dataset_lock["datasets"]["longmemeval"]["files"][
        "data/longmemeval_s_cleaned.json"
    ]["case_count_verified"] == 2
    assert dataset_lock["datasets"]["longmemeval_v2"]["question_counts"] == {
        "all_case_ids_sha256": benchmark_contract._json_sha256(["a", "b"]),
        "by_category": {
            "domain:enterprise": 1,
            "domain:web": 1,
            "environment:webarena-reddit": 1,
            "environment:workarena": 1,
            "type:dynamic-environment": 1,
            "type:static-environment": 1,
        },
        "image_required_case_ids_sha256": benchmark_contract._json_sha256(["b"]),
        "question_image_required": 1,
        "text_only": 1,
        "text_only_case_ids_sha256": benchmark_contract._json_sha256(["a"]),
        "total": 2,
    }
    assert dataset_lock["gate_results"]["BMG-03"] == (
        "NO_GO_MISSING_BFCL_LOCAL_NON_LIVE_LOCK"
    )

    lme_v2 = feasibility["datasets"]["longmemeval_v2"]
    assert lme_v2["decision"] == "ADAPTED_PROTOCOL_CANDIDATE"
    assert lme_v2["official_full_small_state"] == "NOT_APPLICABLE_WITH_RATIONALE"
    assert lme_v2["case_counts"]["text_only_adapted_candidate"] == 1
    assert lme_v2["case_counts"]["excluded_question_image_cases"] == 1


def test_benchmark_contract_generator_detects_candidate_bfcl_paths(tmp_path: Path) -> None:
    longmemeval = tmp_path / "LongMemEval"
    longmemeval_v2 = tmp_path / "LongMemEval-V2"
    search_root = tmp_path / "search"
    _make_longmemeval(longmemeval)
    _make_longmemeval_v2(longmemeval_v2)
    (search_root / "BFCL-v4-local").mkdir(parents=True)

    dataset_lock, feasibility = benchmark_contract.build_reports(
        longmemeval, longmemeval_v2, search_root
    )

    assert dataset_lock["datasets"]["bfcl_v4_local_non_live"]["status"] == (
        "CANDIDATE_PATHS_FOUND_REVIEW_REQUIRED"
    )
    assert dataset_lock["gate_results"]["BMG-03"] == "REVIEW_REQUIRED"
    assert feasibility["datasets"]["bfcl_v4_local_non_live"]["decision"] == (
        "CANDIDATE_PATHS_FOUND_REVIEW_REQUIRED"
    )


def test_benchmark_contract_generator_locks_official_bfcl_local_non_live(
    tmp_path: Path,
) -> None:
    longmemeval = tmp_path / "LongMemEval"
    longmemeval_v2 = tmp_path / "LongMemEval-V2"
    search_root = tmp_path / "search"
    _make_longmemeval(longmemeval)
    _make_longmemeval_v2(longmemeval_v2)
    _make_bfcl(search_root)

    dataset_lock, feasibility = benchmark_contract.build_reports(
        longmemeval, longmemeval_v2, search_root
    )

    bfcl_lock = dataset_lock["datasets"]["bfcl_v4_local_non_live"]
    assert bfcl_lock["status"] == "LOCAL_NON_LIVE_CASE_LIST_CANDIDATE_REVIEW_REQUIRED"
    assert bfcl_lock["local_non_live"]["case_count"] == len(
        benchmark_contract.BFCL_LOCAL_NON_LIVE_CATEGORIES
    )
    assert dataset_lock["gate_results"]["BMG-03"] == "CANDIDATE_LOCK_REVIEW_REQUIRED"

    bfcl_feasibility = feasibility["datasets"]["bfcl_v4_local_non_live"]
    assert bfcl_feasibility["decision"] == "LOCAL_NON_LIVE_CASE_LIST_CANDIDATE_NOT_RUN"
    assert bfcl_feasibility["compatible_case_count"] == len(
        benchmark_contract.BFCL_LOCAL_NON_LIVE_CATEGORIES
    )
    assert feasibility["gate_results"]["BMG-03"] == "CANDIDATE_LOCKED_NOT_RUN"
