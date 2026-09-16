from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract

DATE = "2026-08-21"
CONTRACT_CANDIDATE = "candidate.13"
EXECUTION_ACK = "open-exact-eighty-bfcl-multiturn-dev-labels-score-no-test"
WORKER = ROOT / "scripts/run_dg10_bfcl_multiturn_scoring_worker.py"
DEFAULT_CONTRACT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-dev-scoring-contract-{CONTRACT_CANDIDATE}-{DATE}.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-dev-scoring-candidate.1-{DATE}.json"
)
DEFAULT_CAPTURE_DIRECTORY = (
    WORKSPACE_ROOT / "evidence/dg10-bfcl-multiturn-scoring"
)


class ScoringOrchestratorError(RuntimeError):
    pass


class AppendLedger:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError as exc:
            raise ScoringOrchestratorError("cannot create scoring ledger") from exc
        os.fchmod(descriptor, 0o600)
        self._stream = os.fdopen(descriptor, "ab", buffering=0)

    def append(self, record: Mapping[str, Any]) -> None:
        raw = (
            json.dumps(
                record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            + "\n"
        ).encode("utf-8")
        self._stream.write(raw)
        self._stream.flush()
        os.fsync(self._stream.fileno())

    def close(self) -> None:
        self._stream.close()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScoringOrchestratorError(f"invalid JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise ScoringOrchestratorError(f"JSON object required: {path}")
    return value


def _load_contract(
    contract_path: Path, ledger_path: Path, bundle_path: Path
) -> dict[str, Any]:
    contract = _load_json(contract_path)
    closure = contract.get("byte_closure", {})
    inputs = contract.get("inputs", {})
    schedule = contract.get("scoring_schedule", {}).get("ordered_case_ids")
    if (
        contract.get("schema")
        != "milai.dg10.bfcl-multiturn-dev-scoring-contract.v1"
        or contract.get("candidate") != CONTRACT_CANDIDATE
        or contract.get("status")
        != "BFCL_MULTITURN_DEV_SCORING_FROZEN_LABELS_NOT_OPENED"
        or contract.get("bfcl_dev_answer_labels_opened") is not False
        or contract.get("bfcl_test_labels_or_outputs_opened") is not False
        or contract.get("test_access_authorized") is not False
        or closure.get("scoring_worker", {}).get("sha256")
        != dev_smoke._sha256_file(WORKER)
        or closure.get("scoring_orchestrator", {}).get("sha256")
        != dev_smoke._sha256_file(Path(__file__).resolve())
        or inputs.get("sealed_generation_ledger_sha256")
        != dev_smoke._sha256_file(ledger_path)
        or inputs.get("label_free_bundle_sha256")
        != dev_smoke._sha256_file(bundle_path)
        or not isinstance(schedule, list)
        or len(schedule) != 80
        or len(set(schedule)) != 80
    ):
        raise ScoringOrchestratorError("candidate.13 scoring boundary mismatch")
    return contract


def _process_failure(
    *,
    case_id: str,
    result: subprocess.CompletedProcess[str] | None,
    stdout_path: Path,
    stderr_path: Path,
    failure_type: str,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "status": "SCORING_PROCESS_FAILURE",
        "evidence_complete": False,
        "final_valid": False,
        "failure_type": failure_type,
        "worker_exit_code": result.returncode if result is not None else None,
        "worker_stdout": {
            "sha256": dev_smoke._sha256_file(stdout_path),
            "size": stdout_path.stat().st_size,
            "mode": "0600",
        },
        "worker_stderr": {
            "sha256": dev_smoke._sha256_file(stderr_path),
            "size": stderr_path.stat().st_size,
            "mode": "0600",
        },
        "development_label_access_state": "UNKNOWN_OR_OPENED_FAIL_CLOSED",
        "test_label_or_output_selected": False,
    }


def _run_worker(
    *,
    case_id: str,
    contract_path: Path,
    ledger_path: Path,
    bundle_path: Path,
    bfcl_root: Path,
    case_directory: Path,
) -> dict[str, Any]:
    safe_name = case_id.replace(":", "__")
    output_path = case_directory / f"{safe_name}.score.json"
    stdout_path = case_directory / f"{safe_name}.worker-stdout.log"
    stderr_path = case_directory / f"{safe_name}.worker-stderr.log"
    command = [
        sys.executable,
        str(WORKER),
        "--contract",
        str(contract_path),
        "--ledger",
        str(ledger_path),
        "--bundle",
        str(bundle_path),
        "--bfcl-root",
        str(bfcl_root),
        "--case-id",
        case_id,
        "--output",
        str(output_path),
    ]
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=600.0,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        dev_smoke._write_new(stdout_path, stdout.encode("utf-8"))
        dev_smoke._write_new(stderr_path, stderr.encode("utf-8"))
        return _process_failure(
            case_id=case_id,
            result=None,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            failure_type="SCORING_PROCESS_TIMEOUT",
        )
    if result.returncode != 0 or not output_path.is_file():
        dev_smoke._write_new(stdout_path, result.stdout.encode("utf-8"))
        dev_smoke._write_new(stderr_path, result.stderr.encode("utf-8"))
        return _process_failure(
            case_id=case_id,
            result=result,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            failure_type="SCORING_PROCESS_NONZERO_OR_OUTPUT_ABSENT",
        )
    scored = _load_json(output_path)
    record = scored.get("record")
    if (
        scored.get("schema")
        != "milai.dg10.bfcl-multiturn-dev-scored-case.v1"
        or scored.get("status") != "BFCL_MULTITURN_DEV_CASE_SCORED"
        or not isinstance(record, dict)
        or record.get("case_id") != case_id
        or record.get("both_official_checkers_invoked") is not True
        or record.get("test_label_or_output_selected") is not False
        or stat.S_IMODE(output_path.stat().st_mode) != 0o600
    ):
        dev_smoke._write_new(stdout_path, result.stdout.encode("utf-8"))
        dev_smoke._write_new(stderr_path, result.stderr.encode("utf-8"))
        return _process_failure(
            case_id=case_id,
            result=result,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            failure_type="SCORING_WORKER_EVIDENCE_INVALID",
        )
    return {
        **record,
        "status": scored["status"],
        "evidence_complete": True,
        "worker_result_sha256": dev_smoke._sha256_file(output_path),
        "worker_result_size": output_path.stat().st_size,
        "worker_result_mode": "0600",
    }


def _aggregates(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    complete = [item for item in records if item.get("evidence_complete") is True]
    grouped: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in complete:
        grouped[str(item["category"])].append(item)

    def metrics(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        return {
            "case_count": len(items),
            "final_valid_count": sum(bool(item["final_valid"]) for item in items),
            "final_accuracy": round(
                sum(bool(item["final_valid"]) for item in items) / len(items), 6
            ),
            "generation_success_count": sum(
                bool(item["generation_success"]) for item in items
            ),
            "multi_turn_checker_valid_count": sum(
                bool(item["official_checkers"]["multi_turn_checker"]["valid"])
                for item in items
            ),
            "multi_turn_irrelevance_checker_valid_count": sum(
                bool(
                    item["official_checkers"][
                        "multi_turn_irrelevance_checker"
                    ]["valid"]
                )
                for item in items
            ),
            "missing_turns_totalized": sum(
                int(item["turn_adapter"]["appended_empty_turn_count"])
                for item in items
            ),
        }

    return {
        "all": metrics(complete) if complete else None,
        "by_category": {
            category: metrics(items) for category, items in sorted(grouped.items())
        },
        "process_failure_count": len(records) - len(complete),
    }


def run_scoring(
    *,
    contract_path: Path,
    generation_ledger_path: Path,
    bundle_path: Path,
    bfcl_root: Path,
    capture_directory: Path,
) -> tuple[dict[str, Any], Path]:
    started = datetime.now(UTC)
    contract = _load_contract(contract_path, generation_ledger_path, bundle_path)
    run_id = f"dg10-bfcl-multiturn-scoring-{DATE}-{uuid4().hex[:12]}"
    run_directory = capture_directory / run_id
    run_directory.mkdir(mode=0o700)
    case_directory = run_directory / "cases"
    case_directory.mkdir(mode=0o700)
    scoring_ledger = run_directory / "scoring-ledger.jsonl"
    append_ledger = AppendLedger(scoring_ledger)
    records: list[dict[str, Any]] = []
    try:
        for case_id in contract["scoring_schedule"]["ordered_case_ids"]:
            record = _run_worker(
                case_id=case_id,
                contract_path=contract_path,
                ledger_path=generation_ledger_path,
                bundle_path=bundle_path,
                bfcl_root=bfcl_root,
                case_directory=case_directory,
            )
            append_ledger.append(record)
            records.append(record)
    finally:
        append_ledger.close()
    complete = [item for item in records if item.get("evidence_complete") is True]
    process_failures = len(records) - len(complete)
    official_invocations = {
        checker: sum(
            int(item["official_checkers"][checker]["invocation_count"])
            for item in complete
        )
        for checker in (
            "multi_turn_checker",
            "multi_turn_irrelevance_checker",
        )
    }
    failure_codes = Counter(
        str(item.get("generation_failure_code") or "NONE") for item in complete
    )
    status = (
        "BFCL_MULTITURN_DEV_SCORING_COMPLETE"
        if process_failures == 0
        else "BFCL_MULTITURN_DEV_SCORING_COMPLETE_WITH_PROCESS_FAILURES"
    )
    report = {
        "schema": "milai.dg10.bfcl-multiturn-dev-scoring-report.v1",
        "date": DATE,
        "candidate": "candidate.1",
        "run_id": run_id,
        "status": status,
        "quality_outcome": "CHARACTERIZED_ONLY_THRESHOLDS_NOT_FROZEN",
        "started_at": started.isoformat(),
        "ended_at": datetime.now(UTC).isoformat(),
        "data_boundary": "PUBLIC_BFCL_DEV_LABELS_SELECTED_TEST_SELECTION_PROHIBITED",
        "bfcl_dev_answer_labels_opened": True,
        "bfcl_dev_case_count_opened": len(complete),
        "bfcl_test_labels_or_outputs_opened_by_this_run": False,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "local_vllm_requests": 0,
        "scoring_worker_process_invocations": 80,
        "scoring_worker_process_retries": 0,
        "official_checker_invocations": official_invocations,
        "inputs": {
            "scoring_contract_sha256": dev_smoke._sha256_file(contract_path),
            "sealed_generation_ledger_sha256": dev_smoke._sha256_file(
                generation_ledger_path
            ),
            "label_free_bundle_sha256": dev_smoke._sha256_file(bundle_path),
            "scoring_worker_sha256": dev_smoke._sha256_file(WORKER),
            "scoring_orchestrator_sha256": dev_smoke._sha256_file(
                Path(__file__).resolve()
            ),
            "bfcl_git_head": bfcl_contract._git_head(bfcl_root),
        },
        "execution": {
            "case_count": len(records),
            "evidence_complete_case_count": len(complete),
            "process_failure_case_count": process_failures,
            "generation_success_case_count": sum(
                bool(item.get("generation_success")) for item in complete
            ),
            "generation_failure_case_count": sum(
                not bool(item.get("generation_success")) for item in complete
            ),
            "generation_failure_codes": dict(sorted(failure_codes.items())),
            "fresh_scoring_process_per_case": True,
            "generation_failure_latch_dominates": True,
            "decoder_or_gate_failure_can_count_as_no_call": False,
            "missing_turn_policy": (
                "APPEND_EXPLICIT_EMPTY_TURNS_ONLY_NEVER_TRUNCATE_OR_REWRITE"
            ),
        },
        "aggregates": _aggregates(records),
        "repo_external_scoring_ledger": {
            "status": "WRITTEN_HASH_BOUND",
            "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
            "sha256": dev_smoke._sha256_file(scoring_ledger),
            "size": scoring_ledger.stat().st_size,
            "mode": "0600",
            "record_count": len(records),
        },
        "gate_results": {
            "BMG-03": (
                "DEV_CHARACTERIZATION_COMPLETE"
                if process_failures == 0
                else "NO_GO_SCORING_EVIDENCE_INCOMPLETE"
            ),
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
            "test_execution": "NOT_AUTHORIZED",
        },
        "known_limits": [
            "This is adapted prompt-mode BFCL development characterization, not an official leaderboard score.",
            "Generation failures remain failures even if a totalized empty turn satisfies an official checker.",
            "Both official multi-turn checkers are invoked once per evidence-complete case in fresh processes.",
            "No local model or external provider request is made during scoring.",
            "Test labels and outputs remain unauthorized and unselected.",
        ],
    }
    return report, scoring_ledger


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score the sealed 80-case BFCL multi-turn development ledger"
    )
    parser.add_argument("--execute-dev-scoring", action="store_true")
    parser.add_argument("--execution-ack")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--bfcl-root", type=Path, default=bfcl_contract.DEFAULT_BFCL_ROOT)
    parser.add_argument(
        "--capture-directory", type=Path, default=DEFAULT_CAPTURE_DIRECTORY
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.execute_dev_scoring or args.execution_ack != EXECUTION_ACK:
        raise ScoringOrchestratorError(
            "dev scoring requires the execution flag and exact acknowledgement"
        )
    capture_directory = dev_smoke._validate_capture_directory(
        args.capture_directory
    )
    report, scoring_ledger = run_scoring(
        contract_path=args.contract.resolve(),
        generation_ledger_path=args.ledger.resolve(),
        bundle_path=args.bundle.resolve(),
        bfcl_root=args.bfcl_root.resolve(),
        capture_directory=capture_directory,
    )
    raw = dev_smoke._encoded_json(report)
    dev_smoke._write_new(args.output.resolve(), raw)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_sha256": dev_smoke._sha256_bytes(raw),
                "scoring_ledger_sha256": dev_smoke._sha256_file(scoring_ledger),
                "status": report["status"],
                "final_accuracy": report["aggregates"]["all"]["final_accuracy"],
                "provider_requests": 0,
                "provider_cost": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
