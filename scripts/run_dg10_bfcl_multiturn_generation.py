from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from collections import Counter
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
CONTRACT_CANDIDATE = "candidate.12"
PREFIX_ACK = "execute-exact-four-no-label-operational-prefix"
REMAINING_ACK = "continue-exact-seventy-six-no-label-seal-generation"
DEFAULT_CONTRACT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-safety-contract-{CONTRACT_CANDIDATE}-{DATE}.json"
)
DEFAULT_CAPTURE_DIRECTORY = (
    WORKSPACE_ROOT / "evidence/dg10-bfcl-multiturn-generation"
)
WORKER = ROOT / "scripts/run_dg10_bfcl_multiturn_generation_worker.py"
PREFIX_OUTPUT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-generation-prefix-candidate.4-{DATE}.json"
)
FINAL_OUTPUT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-generation-ledger-candidate.1-{DATE}.json"
)


class GenerationOrchestratorError(RuntimeError):
    pass


class AppendLedger:
    def __init__(self, path: Path, *, create: bool) -> None:
        self.path = path.resolve()
        try:
            dev_smoke._validate_capture_directory(self.path.parent)
        except dev_smoke.DevSmokeError as exc:
            raise GenerationOrchestratorError(str(exc)) from exc
        flags = os.O_WRONLY | os.O_APPEND
        if create:
            flags |= os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError as exc:
            raise GenerationOrchestratorError(f"cannot open ledger: {self.path}") from exc
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
        raise GenerationOrchestratorError(f"invalid JSON file: {path}") from exc
    if not isinstance(value, dict):
        raise GenerationOrchestratorError(f"JSON object required: {path}")
    return value


def _load_contract(path: Path, bundle_path: Path) -> dict[str, Any]:
    report = _load_json(path)
    if (
        report.get("schema") != "milai.dg10.bfcl-multiturn-safety-contract.v1"
        or report.get("candidate") != CONTRACT_CANDIDATE
        or report.get("status")
        != "DEPENDENCY_REMEDIATION_FROZEN_FULL_RERUN_NOT_RUN"
        or report.get("test_access_authorized") is not False
        or report.get("bfcl_dev_answer_labels_opened") is not False
        or report.get("bfcl_test_labels_or_outputs_opened") is not False
        or report.get("gate_results", {}).get("revised_synthetic_local_vllm")
        != "PASS_BOUND"
        or report.get("repo_external_generation_bundle", {}).get("status")
        != "WRITTEN_HASH_BOUND"
        or dev_smoke._sha256_file(bundle_path.resolve())
        != report.get("repo_external_generation_bundle", {}).get("sha256")
    ):
        raise GenerationOrchestratorError("candidate.12 generation boundary mismatch")
    closure = report.get("local_harness_byte_closure", {})
    expected = {
        "generation_worker": WORKER,
        "generation_orchestrator": Path(__file__).resolve(),
    }
    for key, source in expected.items():
        if closure.get(key, {}).get("sha256") != dev_smoke._sha256_file(source):
            raise GenerationOrchestratorError(f"generation closure drift: {key}")
    schedule = report.get("generation_execution_schedule", {})
    ordered = schedule.get("ordered_case_ids")
    prefix = schedule.get("operational_prefix_case_ids")
    if (
        not isinstance(ordered, list)
        or len(ordered) != 80
        or len(set(ordered)) != 80
        or not isinstance(prefix, list)
        or len(prefix) != 4
        or ordered[:4] != prefix
    ):
        raise GenerationOrchestratorError("generation execution schedule mismatch")
    return report


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    resolved = path.resolve()
    try:
        mode = stat.S_IMODE(resolved.stat().st_mode)
    except OSError as exc:
        raise GenerationOrchestratorError(f"cannot stat ledger: {resolved}") from exc
    if mode != 0o600 or resolved.is_symlink():
        raise GenerationOrchestratorError("ledger must be a non-symlink mode 0600 file")
    records: list[dict[str, Any]] = []
    try:
        with resolved.open(encoding="utf-8") as stream:
            for line_number, raw in enumerate(stream, start=1):
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise GenerationOrchestratorError(
                        f"ledger row is not an object: {line_number}"
                    )
                records.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise GenerationOrchestratorError("invalid append-only ledger") from exc
    ids = [item.get("case_id") for item in records]
    if any(not isinstance(item, str) for item in ids) or len(ids) != len(set(ids)):
        raise GenerationOrchestratorError("ledger case IDs are invalid or duplicated")
    return records


def _worker_failure(
    *,
    case_id: str,
    result: subprocess.CompletedProcess[str],
    journal_path: Path,
    stdout_path: Path,
    stderr_path: Path,
) -> dict[str, Any]:
    journal = None
    if journal_path.is_file():
        journal = {
            "sha256": dev_smoke._sha256_file(journal_path),
            "size": journal_path.stat().st_size,
            "mode": f"{stat.S_IMODE(journal_path.stat().st_mode):04o}",
        }
    return {
        "schema": "milai.dg10.bfcl-multiturn-generated-case.v1",
        "date": DATE,
        "case_id": case_id,
        "status": "GENERATION_PROCESS_FAILURE",
        "generation_success": False,
        "evidence_complete": False,
        "failure_code": "GENERATION_PROCESS_FAILURE",
        "worker_exit_code": result.returncode,
        "worker_stdout_sha256": dev_smoke._sha256_bytes(
            result.stdout.encode("utf-8")
        ),
        "worker_stderr_sha256": dev_smoke._sha256_bytes(
            result.stderr.encode("utf-8")
        ),
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
        "journal": journal,
        "native_model_requests": None,
        "hidden_or_extra_model_calls": "UNAVAILABLE_PROCESS_FAILURE",
        "retry_model_calls": 0,
        "development_answer_labels_opened": False,
        "test_material_opened": False,
    }


def _run_worker(
    *,
    case_id: str,
    case_directory: Path,
    bundle_path: Path,
    bfcl_root: Path,
    identity_report: Path,
    base_url: str,
    timeout: float,
) -> dict[str, Any]:
    safe_name = case_id.replace(":", "__")
    journal_path = case_directory / f"{safe_name}.native-steps.jsonl"
    output_path = case_directory / f"{safe_name}.result.json"
    stdout_path = case_directory / f"{safe_name}.worker-stdout.log"
    stderr_path = case_directory / f"{safe_name}.worker-stderr.log"
    command = [
        sys.executable,
        str(WORKER),
        "--bundle",
        str(bundle_path.resolve()),
        "--case-id",
        case_id,
        "--journal",
        str(journal_path),
        "--output",
        str(output_path),
        "--bfcl-root",
        str(bfcl_root.resolve()),
        "--identity-report",
        str(identity_report.resolve()),
        "--base-url",
        base_url,
        "--timeout",
        str(timeout),
    ]
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(300.0, timeout * 150),
        )
    except subprocess.TimeoutExpired as exc:
        timeout_stdout = exc.stdout or ""
        timeout_stderr = exc.stderr or ""
        if isinstance(timeout_stdout, bytes):
            timeout_stdout = timeout_stdout.decode("utf-8", errors="replace")
        if isinstance(timeout_stderr, bytes):
            timeout_stderr = timeout_stderr.decode("utf-8", errors="replace")
        dev_smoke._write_new(stdout_path, timeout_stdout.encode("utf-8"))
        dev_smoke._write_new(stderr_path, timeout_stderr.encode("utf-8"))
        return {
            "schema": "milai.dg10.bfcl-multiturn-generated-case.v1",
            "date": DATE,
            "case_id": case_id,
            "status": "GENERATION_PROCESS_TIMEOUT",
            "generation_success": False,
            "evidence_complete": False,
            "failure_code": "GENERATION_PROCESS_TIMEOUT",
            "timeout_seconds": exc.timeout,
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
            "journal": (
                {
                    "sha256": dev_smoke._sha256_file(journal_path),
                    "size": journal_path.stat().st_size,
                    "mode": f"{stat.S_IMODE(journal_path.stat().st_mode):04o}",
                }
                if journal_path.is_file()
                else None
            ),
            "native_model_requests": None,
            "hidden_or_extra_model_calls": "UNAVAILABLE_PROCESS_TIMEOUT",
            "retry_model_calls": 0,
            "development_answer_labels_opened": False,
            "test_material_opened": False,
        }
    if result.returncode != 0 or not output_path.is_file():
        dev_smoke._write_new(stdout_path, result.stdout.encode("utf-8"))
        dev_smoke._write_new(stderr_path, result.stderr.encode("utf-8"))
        return _worker_failure(
            case_id=case_id,
            result=result,
            journal_path=journal_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
    record = _load_json(output_path)
    if (
        record.get("case_id") != case_id
        or record.get("development_answer_labels_opened") is not False
        or record.get("test_material_opened") is not False
        or record.get("retry_model_calls") != 0
    ):
        raise GenerationOrchestratorError(f"worker result boundary mismatch: {case_id}")
    record["worker_result_file"] = {
        "sha256": dev_smoke._sha256_file(output_path),
        "size": output_path.stat().st_size,
        "mode": f"{stat.S_IMODE(output_path.stat().st_mode):04o}",
    }
    return record


def _summarize(
    *,
    phase: str,
    contract_path: Path,
    bundle_path: Path,
    ledger_path: Path,
    records: Sequence[Mapping[str, Any]],
    phase_case_ids: Sequence[str],
    started: datetime,
) -> dict[str, Any]:
    ended = datetime.now(UTC)
    native_ids = [
        native["native_request_id"]
        for record in records
        for native in record.get("native_records", [])
    ]
    if len(native_ids) != len(set(native_ids)):
        raise GenerationOrchestratorError("native IDs repeat across generated cases")
    status_counts = Counter(str(item.get("status")) for item in records)
    successful = sum(bool(item.get("generation_success")) for item in records)
    evidence_complete = sum(bool(item.get("evidence_complete")) for item in records)
    expected_total = 4 if phase == "operational-prefix" else 80
    phase_integrity = (
        len(records) == expected_total
        and evidence_complete == expected_total
        and len(native_ids)
        == sum(int(item.get("validated_native_receipts") or 0) for item in records)
        and sum(int(item.get("native_model_requests") or 0) for item in records)
        == len(native_ids)
    )
    sealed = phase == "remaining" and len(records) == 80
    return {
        "schema": "milai.dg10.bfcl-multiturn-generation-ledger-report.v1",
        "candidate": "candidate.4" if phase == "operational-prefix" else "candidate.1",
        "date": DATE,
        "phase": phase,
        "status": (
            "LABEL_FREE_GENERATION_LEDGER_SEALED"
            if sealed and phase_integrity
            else (
                "OPERATIONAL_PREFIX_PASS"
                if phase == "operational-prefix" and phase_integrity
                else "GENERATION_FAILURE_RETAINED"
            )
        ),
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "bfcl_dev_generation_inputs_opened": True,
        "bfcl_dev_answer_labels_opened": False,
        "bfcl_test_labels_or_outputs_opened": False,
        "inputs": {
            "generation_contract_sha256": dev_smoke._sha256_file(
                contract_path.resolve()
            ),
            "label_free_bundle_sha256": dev_smoke._sha256_file(
                bundle_path.resolve()
            ),
            "generation_worker_sha256": dev_smoke._sha256_file(WORKER),
            "generation_orchestrator_sha256": dev_smoke._sha256_file(
                Path(__file__).resolve()
            ),
        },
        "execution": {
            "phase_case_count": len(phase_case_ids),
            "phase_case_ids": list(phase_case_ids),
            "ledger_case_count": len(records),
            "generation_success_case_count": successful,
            "generation_failure_case_count": len(records) - successful,
            "evidence_complete_case_count": evidence_complete,
            "evidence_incomplete_case_count": len(records) - evidence_complete,
            "status_counts": dict(sorted(status_counts.items())),
            "fresh_process_per_case": True,
            "worker_process_invocations": len(records),
            "worker_process_retries": 0,
            "native_model_requests": len(native_ids),
            "unique_native_request_ids": len(native_ids),
            "tokenizer_requests": sum(
                int(item.get("tokenizer_requests") or 0) for item in records
            ),
            "validated_native_receipts": len(native_ids),
            "hidden_or_extra_model_calls": 0 if phase_integrity else "REVIEW_FAILURES",
            "retry_model_calls": 0,
            "input_tokens": sum(int(item.get("input_tokens") or 0) for item in records),
            "output_tokens": sum(
                int(item.get("output_tokens") or 0) for item in records
            ),
        },
        "repo_external_append_only_ledger": {
            "status": "SEALED_HASH_BOUND" if sealed else "PREFIX_HASH_BOUND",
            "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
            "sha256": dev_smoke._sha256_file(ledger_path.resolve()),
            "size": ledger_path.resolve().stat().st_size,
            "mode": "0600",
            "record_count": len(records),
            "append_fsync_before_next_case": True,
        },
        "gate_results": {
            "operational_prefix": (
                "PASS"
                if phase == "operational-prefix" and phase_integrity
                else "BOUND"
            ),
            "label_free_generation_ledger": (
                "SEALED" if sealed and phase_integrity else "NOT_SEALED"
            ),
            "development_scoring": "NOT_RUN_LABELS_UNOPENED",
            "BMG-03": "NO_GO_GENERATION_IS_NOT_SCORING",
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
        },
        "known_limits": [
            "This report covers label-free BFCL development generation only and is not a quality score.",
            "Every case uses a fresh process; each native response is fsync-journaled before another request is issued.",
            "Prompt-mode calls remain adapted, client-decoded, non-native, and non-leaderboard-comparable.",
            "Development answers may be loaded only by the separate scoring process after an 80-case sealed ledger; test access remains prohibited.",
        ],
    }


def execute_phase(
    *,
    phase: str,
    contract_path: Path,
    bundle_path: Path,
    capture_directory: Path,
    ledger_path: Path | None,
    bfcl_root: Path,
    identity_report: Path,
    base_url: str,
    timeout: float,
) -> tuple[dict[str, Any], Path]:
    started = datetime.now(UTC)
    frozen_contract = _load_contract(contract_path.resolve(), bundle_path.resolve())
    schedule = frozen_contract["generation_execution_schedule"]
    ordered = schedule["ordered_case_ids"]
    prefix = schedule["operational_prefix_case_ids"]
    if phase == "operational-prefix":
        if ledger_path is not None:
            raise GenerationOrchestratorError("prefix phase creates its own ledger")
        try:
            capture_root = dev_smoke._validate_capture_directory(capture_directory)
        except dev_smoke.DevSmokeError as exc:
            raise GenerationOrchestratorError(str(exc)) from exc
        capture_root.mkdir(parents=True, exist_ok=True)
        run_directory = capture_root / (
            f"dg10-bfcl-multiturn-generation-{DATE}-{uuid4().hex[:12]}"
        )
        run_directory.mkdir(mode=0o700)
        resolved_ledger = run_directory / "generation-ledger.jsonl"
        existing: list[dict[str, Any]] = []
        phase_ids = prefix
        ledger = AppendLedger(resolved_ledger, create=True)
    else:
        if ledger_path is None:
            raise GenerationOrchestratorError("remaining phase requires --ledger")
        resolved_ledger = ledger_path.resolve()
        run_directory = resolved_ledger.parent
        existing = _read_ledger(resolved_ledger)
        existing_ids = [item["case_id"] for item in existing]
        if existing_ids != prefix or not all(
            item.get("evidence_complete") is True for item in existing
        ):
            raise GenerationOrchestratorError(
                "remaining phase requires an exact evidence-complete four-case prefix"
            )
        phase_ids = ordered[4:]
        ledger = AppendLedger(resolved_ledger, create=False)
    case_directory = run_directory / "cases"
    case_directory.mkdir(mode=0o700, exist_ok=True)
    records = list(existing)
    try:
        for case_id in phase_ids:
            result = _run_worker(
                case_id=case_id,
                case_directory=case_directory,
                bundle_path=bundle_path,
                bfcl_root=bfcl_root,
                identity_report=identity_report,
                base_url=base_url,
                timeout=timeout,
            )
            ledger.append(result)
            records.append(result)
    finally:
        ledger.close()
    report = _summarize(
        phase=phase,
        contract_path=contract_path,
        bundle_path=bundle_path,
        ledger_path=resolved_ledger,
        records=records,
        phase_case_ids=phase_ids,
        started=started,
    )
    return report, resolved_ledger


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run or resume the isolated BFCL multi-turn generation ledger"
    )
    parser.add_argument(
        "--phase", choices=("operational-prefix", "remaining"), required=True
    )
    parser.add_argument("--execution-ack", required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument(
        "--capture-directory", type=Path, default=DEFAULT_CAPTURE_DIRECTORY
    )
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--bfcl-root", type=Path, default=bfcl_contract.DEFAULT_BFCL_ROOT)
    parser.add_argument("--identity-report", type=Path, default=dev_smoke.IDENTITY_REPORT)
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    expected_ack = PREFIX_ACK if args.phase == "operational-prefix" else REMAINING_ACK
    if args.execution_ack != expected_ack:
        raise GenerationOrchestratorError("execution acknowledgement mismatch")
    output = args.output or (
        PREFIX_OUTPUT if args.phase == "operational-prefix" else FINAL_OUTPUT
    )
    report, ledger = execute_phase(
        phase=args.phase,
        contract_path=args.contract,
        bundle_path=args.bundle,
        capture_directory=args.capture_directory,
        ledger_path=args.ledger,
        bfcl_root=args.bfcl_root,
        identity_report=args.identity_report,
        base_url=args.base_url,
        timeout=args.timeout,
    )
    raw = dev_smoke._encoded_json(report)
    dev_smoke._write_new(output.resolve(), raw)
    print(
        json.dumps(
            {
                "output": str(output.resolve()),
                "output_sha256": dev_smoke._sha256_bytes(raw),
                "ledger": str(ledger),
                "ledger_sha256": report["repo_external_append_only_ledger"]["sha256"],
                "status": report["status"],
                "ledger_case_count": report["execution"]["ledger_case_count"],
                "native_model_requests": report["execution"][
                    "native_model_requests"
                ],
                "provider_requests": 0,
                "provider_cost": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
