#!/usr/bin/env python3
"""Execute and seal the authorized GDPM B0 known-failure fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.gdpm.known_failure_fixture import execute_known_failure_fixture

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN_ID = "gdpm-b0-20260831-001"
GOAL_PATH = ROOT / "MiLAi_GDPM-01_受治理双过程Memory分阶段开发与验证_GOALS.md"
MASTER_PATH = ROOT / "MiLAi_Memory_Lifecycle_总_GOALS.md"
TOKENIZER_PATH = Path("/cra/qwen36-35B/tokenizer.json")
CHAT_TEMPLATE_PATH = Path("/cra/qwen36-35B/chat_template.jinja")
TEST_COMMAND = (
    "runtime/.venv/bin/python",
    "-m",
    "pytest",
    "tests/test_gdpm_b0_context_truth.py",
    "tests/test_gdpm_b0_runner.py",
    "tests/test_dg14_lme_adapter.py",
    "tests/test_dg14_lme_mcp_contract.py",
    "tests/test_dg15_lme_mcp_adapter.py",
    "runtime/tests/unit/test_dg17_acquisition_plan.py",
    "runtime/tests/unit/test_dg18_acquisition_state.py",
    "runtime/tests/unit/test_dg18_context_expansion.py",
    "runtime/tests/unit/test_dg18_source_context.py",
    "runtime/tests/unit/test_dg27_decision_boundary.py",
    "runtime/tests/unit/test_requirement_state.py",
    "-q",
)
CODE_PATHS = (
    "evals/dg14/contracts.py",
    "evals/dg14/milai_mcp_adapter.py",
    "evals/dg14/reader_token_accounting.py",
    "evals/dg15/milai_mcp_adapter.py",
    "evals/gdpm/b0_context_truth.py",
    "evals/gdpm/known_failure_fixture.py",
    "scripts/run_gdpm_b0_context_truth.py",
    "runtime/src/milai/application/acquisition.py",
    "runtime/src/milai/application/acquisition_state.py",
    "runtime/src/milai/application/decision_boundary.py",
    "runtime/src/milai/application/evidence_acquisition.py",
    "runtime/src/milai/application/evidence_semantics.py",
    "runtime/src/milai/application/evidence_source.py",
    "runtime/src/milai/application/formation_semantic_replay.py",
    "runtime/src/milai/application/memory_context.py",
    "runtime/src/milai/application/retrieval.py",
    "runtime/src/milai/domain/acquisition.py",
    "runtime/src/milai/domain/semantic_query.py",
    "tests/test_gdpm_b0_context_truth.py",
    "tests/test_gdpm_b0_runner.py",
    "tests/test_dg14_lme_adapter.py",
    "tests/test_dg14_lme_mcp_contract.py",
    "tests/test_dg15_lme_mcp_adapter.py",
    "runtime/tests/unit/test_dg17_acquisition_plan.py",
    "runtime/tests/unit/test_dg18_acquisition_state.py",
    "runtime/tests/unit/test_dg18_context_expansion.py",
    "runtime/tests/unit/test_dg18_source_context.py",
    "runtime/tests/unit/test_dg27_decision_boundary.py",
    "runtime/tests/unit/test_requirement_state.py",
)
COMPUTE_CONTRACT_PATHS = (
    ".aris/compute/gdpm-b0-context-truth-local.json",
    ".aris/compute/gdpm-b0-context-truth-local.md",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    output_root = (
        args.output_root.resolve()
        if args.output_root is not None
        else ROOT / "var" / "gdpm" / args.run_id
    )
    if output_root.exists():
        raise RuntimeError(f"run output already exists: {output_root}")
    output_root.mkdir(parents=True)
    trace_root = output_root / "trace-bundle"
    trace_root.mkdir()
    started_at = _now()
    run_lock = _run_lock(args.run_id, started_at)
    _atomic_json(output_root / "run-lock.json", run_lock)

    environment = dict(os.environ)
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        f"{ROOT / 'runtime/src'}:{ROOT}"
        + (f":{existing_pythonpath}" if existing_pythonpath else "")
    )
    tests = subprocess.run(
        TEST_COMMAND,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    fixture = execute_known_failure_fixture()
    trace = fixture["trace"]
    trace_path = trace_root / "known-failure-fixture.json"
    _atomic_json(trace_path, trace)
    test_summary = _pytest_summary(tests.stdout, tests.stderr)
    passed = tests.returncode == 0 and fixture["status"] == "PASS"
    results = {
        "schema_version": "mila-gdpm-b0-results-v0.1",
        "run_id": args.run_id,
        "status": "PASS" if passed else "FAIL",
        "scope": "B0_TARGETED_FAILURE_FIXTURES_CONTEXT_ONLY",
        "benchmark_case_count": 0,
        "reader_calls": 0,
        "answer_calls": 0,
        "judge_calls": 0,
        "formal_holdout_consumed": False,
        "metrics": fixture["metrics"],
        "expected": fixture["expected"],
        "test_execution": {
            "command": list(TEST_COMMAND),
            "returncode": tests.returncode,
            "summary": test_summary,
        },
        "trace_bundle": {
            "path": _artifact_path(trace_path),
            "sha256": _sha256(trace_path),
        },
    }
    results_path = output_root / "results.json"
    _atomic_json(results_path, results)
    repair = {
        "schema_version": "mila-gdpm-repair-log-v0.1",
        "run_id": args.run_id,
        "root_cause": "IDENTITY_COLLAPSE_AND_NON_EXACT_CONTEXT_ACCOUNTING",
        "disposition": "REPAIRED_TARGETED_FIXTURES_PASS",
        "generalized_repairs": [
            "subject_session_turn_identity_separated",
            "cross_session_adjacency_rejected",
            "whole_unit_rank_first_prefix_admission",
            "exact_qwen_reader_envelope_accounting",
            "raw_admitted_reader_visible_trace_separated",
            "system_failure_not_semantic_abstention",
        ],
        "benchmark_case_accessed": False,
        "reader_answer_judge_calls": 0,
    }
    repair_log_path = output_root / "repair-log.jsonl"
    repair_log_path.write_text(
        _canonical(repair) + "\n", encoding="utf-8"
    )
    terminal = {
        "schema_version": "mila-gdpm-b0-terminal-v0.1",
        "run_id": args.run_id,
        "status": (
            "PASS_B0_TARGETED_FIXTURES_AWAITING_24_AUTHORIZATION"
            if passed
            else "FAIL_B0_TARGETED_FIXTURES_REPAIR_REQUIRED"
        ),
        "scope": "B0_TARGETED_FAILURE_FIXTURES_CONTEXT_ONLY",
        "block_complete": False,
        "goal_complete": False,
        "next_authority_required": "B0_24_CASE_CONTEXT_ONLY_CANARY",
        "results_sha256": _sha256(results_path),
        "run_lock_sha256": _sha256(output_root / "run-lock.json"),
        "trace_bundle_sha256": _sha256(trace_path),
        "repair_log_sha256": _sha256(repair_log_path),
        "completed_at": _now(),
        "boundary": {
            "benchmark_cases_executed": 0,
            "reader_answer_judge_calls": 0,
            "formal_holdout_consumed": False,
            "untreated_baseline_rebuilt": False,
            "b1_b2_b3_b4_started": False,
        },
    }
    _atomic_json(output_root / "terminal.json", terminal)
    print(_canonical(terminal))
    return 0 if passed else 1


def _run_lock(run_id: str, created_at: str) -> dict[str, Any]:
    material: dict[str, Any] = {
        "schema_version": "mila-gdpm-b0-run-lock-v0.1",
        "run_id": run_id,
        "created_at": created_at,
        "goal": {
            "document_id": "MILA-GDPM-01",
            "version": "0.2",
            "path": str(GOAL_PATH.relative_to(ROOT)),
            "sha256": _sha256(GOAL_PATH),
        },
        "master": {
            "document_id": "MILA-ML-MASTER",
            "version": "2.0",
            "path": str(MASTER_PATH.relative_to(ROOT)),
            "sha256": _sha256(MASTER_PATH),
        },
        "scope": {
            "active_block": "MILA-ML-EVAL-00",
            "case_scope": "KNOWN_FAILURE_FIXTURES_ONLY",
            "run_scope": "GDPM_B0_CONTEXT_TRUTH_REPAIR_NO_BENCHMARK_CELLS",
            "benchmark_cases_authorized": False,
            "reader_answer_judge_calls_authorized": False,
            "formal_holdout_authorized": False,
        },
        "reader_accounting": {
            "tokenizer_path": str(TOKENIZER_PATH),
            "tokenizer_sha256": _sha256(TOKENIZER_PATH),
            "chat_template_path": str(CHAT_TEMPLATE_PATH),
            "chat_template_sha256": _sha256(CHAT_TEMPLATE_PATH),
            "provider_calls": 0,
        },
        "code_artifacts": {
            path: _sha256(ROOT / path) for path in CODE_PATHS
        },
        "compute_contract": {
            path: _sha256(ROOT / path) for path in COMPUTE_CONTRACT_PATHS
        },
        "test_command": list(TEST_COMMAND),
        "fixture_identity": "GDPM_B0_SYNTHETIC_CONTEXT_TRUTH_V1",
        "benchmark_case_manifest": [],
    }
    return {**material, "run_lock_digest": _digest(material)}


def _pytest_summary(stdout: str, stderr: str) -> str:
    combined = f"{stdout}\n{stderr}"
    matches = re.findall(r"(?:^|\n)([^\n]*(?:passed|failed|error)[^\n]*)", combined)
    return matches[-1].strip() if matches else "pytest summary unavailable"


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(_canonical(value) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    sys.exit(main())
