from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
DATE = "2026-08-21"
DEFAULT_LONGMEMEVAL_ROOT = WORKSPACE_ROOT / "benchmarks/LongMemEval"
DEFAULT_LONGMEMEVAL_V2_ROOT = WORKSPACE_ROOT / "benchmarks/LongMemEval-V2"
DEFAULT_BFCL_SEARCH_ROOT = WORKSPACE_ROOT
DEFAULT_DATASET_LOCK_OUTPUT = (
    ROOT / f"docs/reports/DG-10-benchmark-dataset-lock-candidate.3-{DATE}.json"
)
DEFAULT_FEASIBILITY_OUTPUT = (
    ROOT / f"docs/reports/DG-10-benchmark-feasibility-candidate.3-{DATE}.json"
)
BFCL_LOCAL_NON_LIVE_CATEGORIES = (
    "simple_python",
    "simple_java",
    "simple_javascript",
    "multiple",
    "parallel",
    "parallel_multiple",
    "irrelevance",
    "multi_turn_base",
    "multi_turn_miss_func",
    "multi_turn_miss_param",
    "multi_turn_long_context",
)
BFCL_LIVE_CATEGORIES = (
    "live_simple",
    "live_multiple",
    "live_parallel",
    "live_parallel_multiple",
    "live_irrelevance",
    "live_relevance",
)


class BenchmarkContractError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _file_record(path: Path, *, relative_to: Path | None = None) -> dict[str, Any]:
    if not path.is_file():
        raise BenchmarkContractError(f"required file is missing: {path}")
    record = {"size": path.stat().st_size, "sha256": _sha256(path)}
    if relative_to is not None:
        record["path"] = path.relative_to(relative_to).as_posix()
    return record


def _run_git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _git_head(root: Path) -> str:
    result = _run_git(root, ["rev-parse", "HEAD"])
    if result.returncode != 0:
        return "UNAVAILABLE"
    return result.stdout.strip()


def _git_remote(root: Path) -> str:
    result = _run_git(root, ["remote", "get-url", "origin"])
    if result.returncode != 0:
        return "UNAVAILABLE"
    return result.stdout.strip()


def _git_status(root: Path) -> dict[str, Any]:
    result = _run_git(root, ["status", "--short"])
    if result.returncode != 0:
        return {"clean": False, "unavailable": True, "raw_sha256": _json_sha256(result.stderr)}
    modified: list[str] = []
    untracked: list[str] = []
    other: list[str] = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            other.append(line)
            continue
        code = line[:2]
        path = line[3:]
        if code == "??":
            untracked.append(path)
        elif "M" in code or "A" in code or "D" in code or "R" in code or "C" in code:
            modified.append(path)
        else:
            other.append(line)
    return {
        "clean": not (modified or untracked or other),
        "modified": sorted(modified),
        "untracked": sorted(untracked),
        "other": sorted(other),
    }


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkContractError(f"invalid JSON file: {path}") from exc


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise BenchmarkContractError(
                        f"JSONL row is not an object: {path}:{line_number}"
                    )
                rows.append(row)
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkContractError(f"invalid JSONL file: {path}") from exc
    return rows


def _require_keys(row: Mapping[str, Any], keys: set[str], label: str) -> None:
    missing = sorted(keys - set(row))
    if missing:
        raise BenchmarkContractError(f"{label} missing keys: {missing}")


def _longmemeval_summary(root: Path) -> dict[str, Any]:
    data_root = root / "data"
    small_path = data_root / "longmemeval_s_cleaned.json"
    medium_path = data_root / "longmemeval_m_cleaned.json"
    oracle_path = data_root / "longmemeval_oracle.json"
    small = _load_json(small_path)
    if not isinstance(small, list):
        raise BenchmarkContractError("LongMemEval small file must be a JSON array")
    required = {
        "question_id",
        "question_type",
        "question",
        "question_date",
        "answer",
        "answer_session_ids",
        "haystack_dates",
        "haystack_session_ids",
        "haystack_sessions",
    }
    ids: list[str] = []
    types: Counter[str] = Counter()
    for index, row in enumerate(small):
        if not isinstance(row, dict):
            raise BenchmarkContractError(f"LongMemEval small row is not an object: {index}")
        _require_keys(row, required, f"LongMemEval small row {index}")
        question_id = row["question_id"]
        question_type = row["question_type"]
        if not isinstance(question_id, str) or not question_id:
            raise BenchmarkContractError("LongMemEval question_id is invalid")
        if not isinstance(question_type, str) or not question_type:
            raise BenchmarkContractError("LongMemEval question_type is invalid")
        ids.append(question_id)
        types[question_type] += 1
    return {
        "root": root,
        "git_head": _git_head(root),
        "remote_origin": _git_remote(root),
        "working_tree_status": _git_status(root),
        "license": _file_record(root / "LICENSE"),
        "readme_sha256": _sha256(root / "README.md"),
        "files": {
            "data/longmemeval_s_cleaned.json": {
                **_file_record(small_path),
                "case_count_verified": len(ids),
                "case_ids_sha256": _json_sha256(sorted(ids)),
                "question_type_counts": dict(sorted(types.items())),
            },
            "data/longmemeval_m_cleaned.json": _file_record(medium_path),
            "data/longmemeval_oracle.json": _file_record(oracle_path),
        },
    }


def _longmemeval_v2_summary(root: Path) -> dict[str, Any]:
    data_root = root / "data/longmemeval-v2"
    questions_path = data_root / "questions.jsonl"
    trajectories_path = data_root / "trajectories.jsonl"
    small_haystack_path = data_root / "haystacks/lme_v2_small.json"
    medium_haystack_path = data_root / "haystacks/lme_v2_medium.json"
    questions = _read_jsonl(questions_path)
    required = {
        "id",
        "domain",
        "environment",
        "question_type",
        "question",
        "image",
        "answer",
        "eval_function",
    }
    ids: list[str] = []
    text_only: list[str] = []
    image_required: list[str] = []
    counts: Counter[str] = Counter()
    for index, row in enumerate(questions):
        _require_keys(row, required, f"LongMemEval-V2 question row {index}")
        question_id = row["id"]
        if not isinstance(question_id, str) or not question_id:
            raise BenchmarkContractError("LongMemEval-V2 question id is invalid")
        ids.append(question_id)
        image = row.get("image")
        if image:
            image_required.append(question_id)
        else:
            text_only.append(question_id)
        counts[f"domain:{row.get('domain')}"] += 1
        counts[f"environment:{row.get('environment')}"] += 1
        counts[f"type:{row.get('question_type')}"] += 1
    small_haystack = _load_json(small_haystack_path)
    medium_haystack = _load_json(medium_haystack_path)
    if not isinstance(small_haystack, dict) or not isinstance(medium_haystack, dict):
        raise BenchmarkContractError("LongMemEval-V2 haystacks must be JSON objects")
    small_lengths = _haystack_lengths(small_haystack)
    medium_lengths = _haystack_lengths(medium_haystack)
    return {
        "root": root,
        "git_head": _git_head(root),
        "remote_origin": _git_remote(root),
        "working_tree_status": _git_status(root),
        "license": _file_record(data_root / "LICENSE"),
        "readme_sha256": _sha256(root / "README.md"),
        "checksums_sha256": _sha256(data_root / "checksums.sha256"),
        "files": {
            "data/longmemeval-v2/questions.jsonl": {
                **_file_record(questions_path),
                "case_count": len(ids),
                "case_ids_sha256": _json_sha256(sorted(ids)),
            },
            "data/longmemeval-v2/trajectories.jsonl": {
                **_file_record(trajectories_path),
                "trajectory_count_from_data_card": 1870,
            },
            "data/longmemeval-v2/haystacks/lme_v2_small.json": {
                **_file_record(small_haystack_path),
                "question_count": len(small_haystack),
                "case_ids_sha256": _json_sha256(sorted(small_haystack)),
                "min_haystack": min(small_lengths),
                "max_haystack": max(small_lengths),
            },
            "data/longmemeval-v2/haystacks/lme_v2_medium.json": {
                **_file_record(medium_haystack_path),
                "question_count": len(medium_haystack),
                "case_ids_sha256": _json_sha256(sorted(medium_haystack)),
                "min_haystack": min(medium_lengths),
                "max_haystack": max(medium_lengths),
            },
        },
        "question_counts": {
            "total": len(ids),
            "text_only": len(text_only),
            "question_image_required": len(image_required),
            "all_case_ids_sha256": _json_sha256(sorted(ids)),
            "text_only_case_ids_sha256": _json_sha256(sorted(text_only)),
            "image_required_case_ids_sha256": _json_sha256(sorted(image_required)),
            "by_category": dict(sorted(counts.items())),
        },
        "artifact_counts": {
            "question_screenshots_png": _count_files(data_root / "question_screenshots", "*.png"),
            "trajectory_screenshots_png": _count_files(data_root / "trajectory_screenshots", "*.png"),
        },
    }


def _haystack_lengths(value: Mapping[str, Any]) -> list[int]:
    lengths: list[int] = []
    for question_id, trajectory_ids in value.items():
        if not isinstance(question_id, str) or not question_id:
            raise BenchmarkContractError("haystack question id is invalid")
        if not isinstance(trajectory_ids, list) or any(
            not isinstance(item, str) or not item for item in trajectory_ids
        ):
            raise BenchmarkContractError(f"haystack trajectory ids invalid: {question_id}")
        lengths.append(len(trajectory_ids))
    if not lengths:
        raise BenchmarkContractError("haystack is empty")
    return lengths


def _count_files(root: Path, pattern: str) -> int:
    if not root.exists():
        return 0
    return sum(1 for path in root.rglob(pattern) if path.is_file())


def _find_bfcl_roots(search_root: Path, max_depth: int = 5) -> list[Path]:
    if not search_root.exists():
        return []
    matches: list[Path] = []
    root_depth = len(search_root.resolve().parts)
    candidates = (search_root, *search_root.rglob("*"))
    for path in candidates:
        if not path.is_dir():
            continue
        try:
            relative_depth = len(path.resolve().parts) - root_depth
        except OSError:
            continue
        if relative_depth > max_depth:
            continue
        if (path / "bfcl_eval/data").is_dir() and (path / "TEST_CATEGORIES.md").is_file():
            matches.append(path.resolve())
    return sorted(set(matches), key=lambda item: item.as_posix())


def _find_bfcl(search_root: Path, max_depth: int = 4) -> list[str]:
    matches: list[str] = []
    if not search_root.exists():
        return matches
    root_depth = len(search_root.resolve().parts)
    for path in search_root.rglob("*"):
        try:
            relative_depth = len(path.resolve().parts) - root_depth
        except OSError:
            continue
        if relative_depth > max_depth:
            continue
        lowered = path.name.casefold()
        if "bfcl" in lowered or "gorilla" in lowered or ("berkeley" in lowered and "function" in lowered):
            matches.append(path.relative_to(search_root).as_posix())
    return sorted(matches)


def _bfcl_license(root: Path) -> dict[str, Any]:
    for path in (root / "LICENSE", root.parent / "LICENSE"):
        if path.is_file():
            return _file_record(path)
    raise BenchmarkContractError(f"BFCL license file is missing near: {root}")


def _read_bfcl_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = _read_jsonl(path)
    if not rows:
        raise BenchmarkContractError(f"BFCL JSONL file is empty: {path}")
    return rows


def _bfcl_category_summary(root: Path, category: str) -> dict[str, Any]:
    data_root = root / "bfcl_eval/data"
    case_path = data_root / f"BFCL_v4_{category}.json"
    rows = _read_bfcl_jsonl(case_path)
    ids: list[str] = []
    for index, row in enumerate(rows):
        case_id = row.get("id")
        if not isinstance(case_id, str) or not case_id:
            raise BenchmarkContractError(f"BFCL {category} row id is invalid: {index}")
        ids.append(case_id)
    case_ids_sha256 = _json_sha256(sorted(ids))
    possible_answer = _bfcl_possible_answer_summary(
        root,
        category,
        expected_case_ids_sha256=case_ids_sha256,
        expected_case_count=len(ids),
    )
    summary = {
        **_file_record(case_path, relative_to=root),
        "category": category,
        "case_count": len(ids),
        "case_ids_sha256": case_ids_sha256,
        "sample_keys": sorted(rows[0]),
        "possible_answer": possible_answer,
    }
    return summary


def _bfcl_possible_answer_summary(
    root: Path,
    category: str,
    *,
    expected_case_ids_sha256: str,
    expected_case_count: int,
) -> dict[str, Any]:
    answer_path = root / f"bfcl_eval/data/possible_answer/BFCL_v4_{category}.json"
    if not answer_path.exists():
        if category in {"irrelevance", "live_irrelevance", "live_relevance"}:
            return {
                "status": "NOT_PRESENT_EXPECTED_FOR_RELEVANCE_OR_IRRELEVANCE_CATEGORY",
                "path": None,
            }
        raise BenchmarkContractError(f"BFCL possible_answer file is missing: {category}")
    rows = _read_bfcl_jsonl(answer_path)
    ids: list[str] = []
    for index, row in enumerate(rows):
        case_id = row.get("id")
        if not isinstance(case_id, str) or not case_id:
            raise BenchmarkContractError(
                f"BFCL possible_answer row id is invalid: {category}:{index}"
            )
        ids.append(case_id)
    answer_ids_sha256 = _json_sha256(sorted(ids))
    if len(ids) != expected_case_count or answer_ids_sha256 != expected_case_ids_sha256:
        raise BenchmarkContractError(f"BFCL possible_answer id coverage drift: {category}")
    return {
        **_file_record(answer_path, relative_to=root),
        "status": "COVERAGE_MATCHES_CASE_IDS",
        "answer_count": len(ids),
        "answer_ids_sha256": answer_ids_sha256,
    }


def _bfcl_format_sensitivity_summary(root: Path) -> dict[str, Any] | None:
    path = root / "bfcl_eval/data/BFCL_v4_format_sensitivity.json"
    if not path.exists():
        return None
    value = _load_json(path)
    if not isinstance(value, dict):
        raise BenchmarkContractError("BFCL format_sensitivity file must be an object")
    group_counts: dict[str, int] = {}
    for group, ids in value.items():
        if not isinstance(group, str) or not isinstance(ids, list):
            raise BenchmarkContractError("BFCL format_sensitivity group is invalid")
        if any(not isinstance(item, str) or not item for item in ids):
            raise BenchmarkContractError("BFCL format_sensitivity id is invalid")
        group_counts[group] = len(ids)
    return {
        **_file_record(path, relative_to=root),
        "status": "NON_SCORING_EXCLUDED_FROM_LOCAL_NON_LIVE_GATE",
        "group_count": len(group_counts),
        "variant_id_count": sum(group_counts.values()),
        "group_counts": dict(sorted(group_counts.items())),
    }


def _bfcl_summary(search_root: Path) -> dict[str, Any]:
    roots = _find_bfcl_roots(search_root.resolve())
    candidate_matches = _find_bfcl(search_root.resolve())
    if not roots:
        return {
            "available": False,
            "candidate_matches": candidate_matches,
        }
    root = roots[0]
    category_summaries: dict[str, Any] = {}
    for path in sorted((root / "bfcl_eval/data").glob("BFCL_v4_*.json")):
        category = path.stem.removeprefix("BFCL_v4_")
        if category == "format_sensitivity":
            continue
        category_summaries[category] = _bfcl_category_summary(root, category)
    missing_local = [
        category
        for category in BFCL_LOCAL_NON_LIVE_CATEGORIES
        if category not in category_summaries
    ]
    if missing_local:
        raise BenchmarkContractError(f"BFCL local/non-live categories missing: {missing_local}")
    local_ids: list[str] = []
    for category in BFCL_LOCAL_NON_LIVE_CATEGORIES:
        rows = _read_bfcl_jsonl(root / f"bfcl_eval/data/BFCL_v4_{category}.json")
        local_ids.extend(str(row["id"]) for row in rows)
    excluded = {
        "live": {
            "categories": [
                category for category in BFCL_LIVE_CATEGORIES if category in category_summaries
            ],
            "reason": "User-contributed live categories are outside the local/non-live release gate.",
            "case_count": sum(
                category_summaries[category]["case_count"]
                for category in BFCL_LIVE_CATEGORIES
                if category in category_summaries
            ),
        },
        "agentic_web_search": {
            "categories": [
                category for category in ("web_search",) if category in category_summaries
            ],
            "reason": "Web-search categories require live web/SerpAPI-style external access.",
            "case_count": category_summaries.get("web_search", {}).get("case_count", 0),
        },
        "agentic_memory": {
            "categories": [
                category for category in ("memory",) if category in category_summaries
            ],
            "reason": (
                "BFCL agentic memory expands into BFCL-owned memory backends; vector "
                "mode depends on sentence-transformers/faiss and is not the MiLAi MCP "
                "memory path. It needs a separate harness lock before use."
            ),
            "case_count": category_summaries.get("memory", {}).get("case_count", 0),
            "official_backend_expansion": ["memory_kv", "memory_vector", "memory_rec_sum"],
        },
        "format_sensitivity": _bfcl_format_sensitivity_summary(root),
    }
    return {
        "available": True,
        "root": root,
        "git_head": _git_head(root),
        "remote_origin": _git_remote(root),
        "working_tree_status": _git_status(root),
        "license": _bfcl_license(root),
        "readme_sha256": _sha256(root / "README.md"),
        "pyproject": _file_record(root / "pyproject.toml", relative_to=root),
        "test_categories": _file_record(root / "TEST_CATEGORIES.md", relative_to=root),
        "category_mapping": _file_record(
            root / "bfcl_eval/constants/category_mapping.py",
            relative_to=root,
        ),
        "eval_runner": _file_record(
            root / "bfcl_eval/eval_checker/eval_runner.py",
            relative_to=root,
        ),
        "candidate_matches": candidate_matches,
        "all_category_count": len(category_summaries),
        "categories": dict(sorted(category_summaries.items())),
        "local_non_live": {
            "categories": list(BFCL_LOCAL_NON_LIVE_CATEGORIES),
            "case_count": len(local_ids),
            "case_ids_sha256": _json_sha256(sorted(local_ids)),
            "case_count_by_category": {
                category: category_summaries[category]["case_count"]
                for category in BFCL_LOCAL_NON_LIVE_CATEGORIES
            },
        },
        "excluded_from_local_non_live_gate": excluded,
    }


def _dataset_lock_report(
    *,
    longmemeval: Mapping[str, Any],
    longmemeval_v2: Mapping[str, Any],
    bfcl: Mapping[str, Any],
) -> dict[str, Any]:
    lme_root = Path(longmemeval["root"])
    lme_v2_root = Path(longmemeval_v2["root"])
    bfcl_available = bool(bfcl.get("available"))
    return {
        "schema": "milai.dg10.benchmark-dataset-lock.v1",
        "date": DATE,
        "candidate": "candidate.3",
        "status": "DATASET_LOCK_CANDIDATE_REVIEW_REQUIRED",
        "data_boundary": "PUBLIC_BENCHMARK_METADATA_ONLY",
        "provider_requests": 0,
        "provider_cost": 0,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "datasets": {
            "longmemeval": {
                "local_path_class": "repo-external-benchmark-workspace",
                "path": str(lme_root),
                "git_head": longmemeval["git_head"],
                "remote_origin": longmemeval["remote_origin"],
                "working_tree_status": longmemeval["working_tree_status"],
                "license": {
                    "path": "LICENSE",
                    "sha256": longmemeval["license"]["sha256"],
                },
                "readme_sha256": longmemeval["readme_sha256"],
                "files": longmemeval["files"],
                "lock_state": "PARTIAL_LOCK_REVIEW_REQUIRED",
                "blocking_notes": [
                    "The benchmark repository working tree is dirty and contains untracked downloaded data."
                    if not longmemeval["working_tree_status"].get("clean")
                    else "The benchmark repository working tree is clean.",
                    "Only longmemeval_s_cleaned.json case count and IDs are fully verified here; medium/oracle are byte-locked but not case-count scanned.",
                ],
            },
            "longmemeval_v2": {
                "local_path_class": "repo-external-benchmark-workspace",
                "path": str(lme_v2_root),
                "git_head": longmemeval_v2["git_head"],
                "remote_origin": longmemeval_v2["remote_origin"],
                "working_tree_status": longmemeval_v2["working_tree_status"],
                "license": {
                    "path": "data/longmemeval-v2/LICENSE",
                    "sha256": longmemeval_v2["license"]["sha256"],
                },
                "readme_sha256": longmemeval_v2["readme_sha256"],
                "checksums_sha256": longmemeval_v2["checksums_sha256"],
                "files": longmemeval_v2["files"],
                "question_counts": longmemeval_v2["question_counts"],
                "artifact_counts": longmemeval_v2["artifact_counts"],
                "lock_state": "PARTIAL_LOCK_REVIEW_REQUIRED",
                "blocking_notes": [
                    "The benchmark repository has local changes or untracked helpers."
                    if not longmemeval_v2["working_tree_status"].get("clean")
                    else "The benchmark repository working tree is clean.",
                    "Screenshot-dependent artifacts are present and large; only metadata and root file hashes are stored in this MiLAi report.",
                ],
            },
            "bfcl_v4_local_non_live": {
                **_dataset_lock_bfcl_section(bfcl),
            },
        },
        "gate_results": {
            "BMG-00": "PARTIAL_CANDIDATE_REVIEW_REQUIRED",
            "BMG-00A": "PARTIAL_CANDIDATE_REVIEW_REQUIRED",
            "BMG-03": "CANDIDATE_LOCK_REVIEW_REQUIRED"
            if bfcl_available
            else (
                "NO_GO_MISSING_BFCL_LOCAL_NON_LIVE_LOCK"
                if not bfcl.get("candidate_matches")
                else "REVIEW_REQUIRED"
            ),
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
        },
        "known_limits": [
            "This report does not authorize opening benchmark test labels/outputs.",
            "No adapter, grader, Latin-square schedule, calibration threshold, public benchmark run, or quality outcome is frozen here.",
            "Repository-external raw benchmark data is referenced only by path class, size, SHA-256, and case-ID digest.",
        ],
    }


def _dataset_lock_bfcl_section(bfcl: Mapping[str, Any]) -> dict[str, Any]:
    if not bfcl.get("available"):
        matches = list(bfcl.get("candidate_matches", []))
        return {
            "local_path": None,
            "status": "MISSING_LOCAL_DATASET_NO_GO"
            if not matches
            else "CANDIDATE_PATHS_FOUND_REVIEW_REQUIRED",
            "candidate_matches": matches,
            "blocking_notes": [
                "No local BFCL/Gorilla/Berkeley function-calling dataset or harness was found under the configured search root at maxdepth 5."
                if not matches
                else "Candidate BFCL-like paths were found but have not been locked or classified as BFCL V4 local/non-live."
            ],
        }
    root = Path(bfcl["root"])
    return {
        "local_path_class": "repo-external-benchmark-workspace",
        "path": str(root),
        "git_head": bfcl["git_head"],
        "remote_origin": bfcl["remote_origin"],
        "working_tree_status": bfcl["working_tree_status"],
        "license": bfcl["license"],
        "readme_sha256": bfcl["readme_sha256"],
        "pyproject": bfcl["pyproject"],
        "test_categories": bfcl["test_categories"],
        "category_mapping": bfcl["category_mapping"],
        "eval_runner": bfcl["eval_runner"],
        "candidate_matches": bfcl["candidate_matches"],
        "all_category_count": bfcl["all_category_count"],
        "categories": bfcl["categories"],
        "local_non_live": bfcl["local_non_live"],
        "excluded_from_local_non_live_gate": bfcl["excluded_from_local_non_live_gate"],
        "status": "LOCAL_NON_LIVE_CASE_LIST_CANDIDATE_REVIEW_REQUIRED",
        "lock_state": "PARTIAL_LOCK_REVIEW_REQUIRED",
        "blocking_notes": [
            "BFCL local/non-live case IDs and possible_answer coverage are byte-locked, but no model run or scorer execution has been performed.",
            "Live, web-search, agentic memory, and non-scoring format-sensitivity categories are explicitly excluded from this local/non-live gate.",
        ],
    }


def _feasibility_bfcl_section(bfcl: Mapping[str, Any]) -> dict[str, Any]:
    if not bfcl.get("available"):
        matches = list(bfcl.get("candidate_matches", []))
        return {
            "decision": "NOT_STARTED_NO_LOCAL_DATASET"
            if not matches
            else "CANDIDATE_PATHS_FOUND_REVIEW_REQUIRED",
            "rationale": (
                "No local BFCL V4 non-live dataset or harness was present under the current benchmark workspace; BMG-03 remains NO-GO."
                if not matches
                else "Candidate BFCL-like paths exist, but no BFCL V4 local/non-live lock has been established."
            ),
            "candidate_matches": matches,
            "required_modalities": [
                "text prompts",
                "function/tool schemas",
                "expected tool selection and arguments",
            ],
            "claim_scope_if_later_added": "AGENT_TOOL_SELECTION_SEMANTICS_ONLY_NOT_MCP_TRANSPORT",
        }
    local = bfcl["local_non_live"]
    excluded = bfcl["excluded_from_local_non_live_gate"]
    return {
        "decision": "LOCAL_NON_LIVE_CASE_LIST_CANDIDATE_NOT_RUN",
        "rationale": (
            "Official BFCL V4 local/non-live and multi-turn categories are present "
            "and case-ID/possible-answer coverage is locked. This is not a BFCL "
            "quality result because no model generation or scorer run has occurred."
        ),
        "candidate_matches": bfcl["candidate_matches"],
        "compatible_case_count": local["case_count"],
        "compatible_case_ids_sha256": local["case_ids_sha256"],
        "compatible_categories": local["categories"],
        "case_count_by_category": local["case_count_by_category"],
        "excluded_from_current_gate": excluded,
        "required_modalities": [
            "text prompts",
            "function/tool schemas",
            "expected tool selection and arguments",
            "multi-turn text conversations and local initial_config state",
        ],
        "required_tools": [
            "official AST checker for single-turn function calls",
            "official irrelevance/no-call checker",
            "official multi-turn checker with local BFCL function-source backends",
        ],
        "scoring_lane": "BFCL_V4_LOCAL_NON_LIVE_OFFICIAL_CHECKERS_CANDIDATE",
        "blocked_items": [
            "No live/API/web-search BFCL case is in this local-only release gate.",
            "BFCL agentic memory categories require a separate harness/dependency lock before use.",
            "This report does not execute model calls, decode tool calls, or compute accuracy.",
        ],
        "claim_scope": "AGENT_TOOL_SELECTION_ARGUMENTS_NO_CALL_AND_MULTI_TURN_SEMANTICS_ONLY_NOT_MCP_TRANSPORT",
    }


def _feasibility_report(
    *,
    longmemeval: Mapping[str, Any],
    longmemeval_v2: Mapping[str, Any],
    bfcl: Mapping[str, Any],
) -> dict[str, Any]:
    lme_file = longmemeval["files"]["data/longmemeval_s_cleaned.json"]
    lme_v2_counts = longmemeval_v2["question_counts"]
    lme_v2_files = longmemeval_v2["files"]
    bfcl_available = bool(bfcl.get("available"))
    return {
        "schema": "milai.dg10.benchmark-feasibility.v1",
        "date": DATE,
        "candidate": "candidate.3",
        "status": "FEASIBILITY_CANDIDATE_REVIEW_REQUIRED",
        "data_boundary": "PUBLIC_BENCHMARK_METADATA_ONLY",
        "provider_requests": 0,
        "provider_cost": 0,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "vllm_model_capability": {
            "model": "Qwen3.6-35B-A3B-FP8",
            "adapter_modality": "TEXT_ONLY_OPENAI_COMPATIBLE_CHAT_COMPLETIONS",
            "vision_or_ocr_provider": "NOT_AUTHORIZED",
            "external_judge_provider": "NOT_AUTHORIZED",
        },
        "datasets": {
            "longmemeval": {
                "decision": "OFFICIAL_TEXT_INPUT_COMPATIBLE_FOR_CLEANED_500",
                "required_modalities": [
                    "text chat history",
                    "text question",
                    "text reference answer",
                ],
                "required_tools": [],
                "official_input_contract": {
                    "case_count": lme_file["case_count_verified"],
                    "fields": [
                        "question_id",
                        "question_type",
                        "question",
                        "question_date",
                        "answer",
                        "answer_session_ids",
                        "haystack_dates",
                        "haystack_session_ids",
                        "haystack_sessions",
                    ],
                },
                "compatible_case_count": lme_file["case_count_verified"],
                "compatible_case_ids_sha256": lme_file["case_ids_sha256"],
                "lossiness": "NONE_FOR_TEXT_CLEANED_500",
                "scoring_lane": "LOCAL_VLLM_PROTOCOL_TIER_1_DETERMINISTIC_REQUIRED",
                "blocked_items": [
                    "Official or repository evaluator paths that call an external model judge remain prohibited in this vLLM-only goal."
                ],
            },
            "longmemeval_v2": {
                "decision": "ADAPTED_PROTOCOL_CANDIDATE",
                "official_full_small_state": "NOT_APPLICABLE_WITH_RATIONALE",
                "rationale": (
                    "The released input contract contains optional question screenshots and "
                    "trajectory state screenshot paths; this DG-10 lane has only a text vLLM "
                    "adapter and does not authorize VLM, OCR, manual image transcription, or "
                    "external judge calls."
                ),
                "required_modalities": [
                    "text question",
                    "optional question image",
                    "trajectory goal/action/thought/accessibility-tree text",
                    "trajectory screenshot paths",
                    "text reference answer",
                ],
                "required_tools": [
                    "memory_module.insert(trajectory)",
                    "memory_module.query(query, query_image=None)",
                    "local evaluator function from eval_function",
                ],
                "case_counts": {
                    "official_total": lme_v2_counts["total"],
                    "text_only_adapted_candidate": lme_v2_counts["text_only"],
                    "excluded_question_image_cases": lme_v2_counts["question_image_required"],
                    "all_case_ids_sha256": lme_v2_counts["all_case_ids_sha256"],
                    "included_text_only_case_ids_sha256": lme_v2_counts[
                        "text_only_case_ids_sha256"
                    ],
                    "excluded_image_case_ids_sha256": lme_v2_counts[
                        "image_required_case_ids_sha256"
                    ],
                },
                "artifact_counts": {
                    "question_screenshots_png": longmemeval_v2["artifact_counts"][
                        "question_screenshots_png"
                    ],
                    "trajectory_screenshots_png": longmemeval_v2["artifact_counts"][
                        "trajectory_screenshots_png"
                    ],
                    "small_haystack_questions": lme_v2_files[
                        "data/longmemeval-v2/haystacks/lme_v2_small.json"
                    ]["question_count"],
                    "small_haystack_min": lme_v2_files[
                        "data/longmemeval-v2/haystacks/lme_v2_small.json"
                    ]["min_haystack"],
                    "small_haystack_max": lme_v2_files[
                        "data/longmemeval-v2/haystacks/lme_v2_small.json"
                    ]["max_haystack"],
                    "medium_haystack_questions": lme_v2_files[
                        "data/longmemeval-v2/haystacks/lme_v2_medium.json"
                    ]["question_count"],
                    "medium_haystack_min": lme_v2_files[
                        "data/longmemeval-v2/haystacks/lme_v2_medium.json"
                    ]["min_haystack"],
                    "medium_haystack_max": lme_v2_files[
                        "data/longmemeval-v2/haystacks/lme_v2_medium.json"
                    ]["max_haystack"],
                },
                "adapter_transformation": {
                    "text_only_candidate": "Use question text plus trajectory textual fields only; omit question screenshots and trajectory screenshots.",
                    "information_loss": "LOSSY_RELATIVE_TO_OFFICIAL_FULL_SMALL",
                    "claim_label": "ADAPTED_PROTOCOL_ONLY_NOT_LEADERBOARD",
                },
                "scoring_lane": "LOCAL_VLLM_PROTOCOL_TIER_1_DETERMINISTIC_WHERE_EVAL_FUNCTION_IS_LOCAL",
                "blocked_items": [
                    "No full-small or leaderboard-compatible claim may be made without an authorized multimodal lane.",
                    "No external OpenAI/Codex judge may be used for release-blocking scoring in the current vLLM-only scope.",
                ],
            },
            "bfcl_v4_local_non_live": {
                **_feasibility_bfcl_section(bfcl),
            },
        },
        "gate_results": {
            "BMG-00A": "PARTIAL_CANDIDATE_REVIEW_REQUIRED",
            "BMG-02": "NO_GO_NOT_RUN",
            "BMG-03": "CANDIDATE_LOCKED_NOT_RUN"
            if bfcl_available
            else (
                "NO_GO_MISSING_BFCL_LOCAL_NON_LIVE_LOCK"
                if not bfcl.get("candidate_matches")
                else "REVIEW_REQUIRED"
            ),
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
        },
        "known_limits": [
            "This feasibility report is pre-calibration and pre-test.",
            "It does not freeze prompts, answer parsers, retrieval k, budgets, Latin-square schedule, or quality thresholds.",
            "It explicitly separates LongMemEval-V2 adapted protocol from official full-small/leaderboard compatibility.",
        ],
    }


def build_reports(
    longmemeval_root: Path = DEFAULT_LONGMEMEVAL_ROOT,
    longmemeval_v2_root: Path = DEFAULT_LONGMEMEVAL_V2_ROOT,
    bfcl_search_root: Path = DEFAULT_BFCL_SEARCH_ROOT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    longmemeval = _longmemeval_summary(longmemeval_root.resolve())
    longmemeval_v2 = _longmemeval_v2_summary(longmemeval_v2_root.resolve())
    bfcl = _bfcl_summary(bfcl_search_root.resolve())
    return (
        _dataset_lock_report(
            longmemeval=longmemeval,
            longmemeval_v2=longmemeval_v2,
            bfcl=bfcl,
        ),
        _feasibility_report(
            longmemeval=longmemeval,
            longmemeval_v2=longmemeval_v2,
            bfcl=bfcl,
        ),
    )


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate DG-10 benchmark dataset-lock and feasibility candidates"
    )
    parser.add_argument("--longmemeval-root", type=Path, default=DEFAULT_LONGMEMEVAL_ROOT)
    parser.add_argument("--longmemeval-v2-root", type=Path, default=DEFAULT_LONGMEMEVAL_V2_ROOT)
    parser.add_argument("--bfcl-search-root", type=Path, default=DEFAULT_BFCL_SEARCH_ROOT)
    parser.add_argument("--dataset-lock-output", type=Path, default=DEFAULT_DATASET_LOCK_OUTPUT)
    parser.add_argument("--feasibility-output", type=Path, default=DEFAULT_FEASIBILITY_OUTPUT)
    args = parser.parse_args()
    dataset_lock, feasibility = build_reports(
        args.longmemeval_root, args.longmemeval_v2_root, args.bfcl_search_root
    )
    _write(args.dataset_lock_output.resolve(), dataset_lock)
    _write(args.feasibility_output.resolve(), feasibility)
    print(
        json.dumps(
            {
                "dataset_lock_output": str(args.dataset_lock_output.resolve()),
                "dataset_lock_status": dataset_lock["status"],
                "feasibility_output": str(args.feasibility_output.resolve()),
                "feasibility_status": feasibility["status"],
                "provider_requests": 0,
                "provider_cost": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
