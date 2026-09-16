#!/usr/bin/env python3
"""Inspect or explicitly recover one journaled MVP-01 U0 Runtime orphan."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import time
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(RUNTIME_SRC) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SRC))

from milai.operations import load_runtime_environment
from milai.operations.smoke import _drop_database

from evals.dg14.benchmark import _atomic_json, _process_identity
from evals.mvp01.u0_warm_contract import AUTHORIZED_RUN_ID


class RecoveryBlocked(RuntimeError):
    """The journal or live resource identity was not safe to mutate."""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_journal(path: Path) -> dict[str, object]:
    expected_root = (ROOT / "var/mvp01").resolve()
    resolved = path.resolve()
    if resolved.name != "runtime-ownership.json" or not resolved.is_relative_to(
        expected_root
    ):
        raise RecoveryBlocked("journal is outside the MVP-01 ownership root")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryBlocked("ownership journal is unreadable") from exc
    if not isinstance(value, dict):
        raise RecoveryBlocked("ownership journal is not an object")
    database = value.get("database")
    if (
        value.get("schema_version") != "milai-local-runtime-ownership-v0.1"
        or value.get("run_id") != AUTHORIZED_RUN_ID
        or not isinstance(database, str)
        or not database.startswith("milai_smoke_dg14_")
        or len(database) > 63
    ):
        raise RecoveryBlocked("ownership journal identity is unsafe")
    return value


def _same_process(stored: Mapping[str, object], current: Mapping[str, object]) -> bool:
    return all(
        stored.get(key) == current.get(key)
        for key in (
            "pid",
            "proc_start_ticks",
            "executable",
            "cwd",
            "cmdline_sha256",
            "cmdline",
        )
    )


def _inspect_process(value: object, label: str) -> dict[str, object]:
    if value is None:
        return {"label": label, "status": "NOT_JOURNALED"}
    if not isinstance(value, Mapping):
        raise RecoveryBlocked(f"{label} journal identity is invalid")
    pid = value.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise RecoveryBlocked(f"{label} PID is invalid")
    proc_path = Path("/proc") / str(pid)
    if not proc_path.exists():
        return {"label": label, "pid": pid, "status": "NOT_RUNNING"}
    try:
        current = _process_identity(pid)
    except Exception as exc:
        if not proc_path.exists():
            return {"label": label, "pid": pid, "status": "NOT_RUNNING"}
        raise RecoveryBlocked(f"{label} live process identity is unreadable") from exc
    if not _same_process(value, current):
        raise RecoveryBlocked(f"{label} PID was reused or its identity drifted")
    return {
        **current,
        "label": label,
        "status": "LIVE_EXACT_MATCH",
    }


def _terminate_exact(process: Mapping[str, object]) -> dict[str, object]:
    if process.get("status") != "LIVE_EXACT_MATCH":
        return dict(process)
    pid = process.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool):
        raise RecoveryBlocked("verified process lost its PID")

    def still_exact() -> bool:
        proc_path = Path("/proc") / str(pid)
        if not proc_path.exists():
            return False
        try:
            current = _process_identity(pid)
        except Exception as exc:
            if not proc_path.exists():
                return False
            raise RecoveryBlocked(
                f"verified process {pid} identity became unreadable"
            ) from exc
        # PID reuse means the owned process is gone, but the new process must
        # never receive either TERM or KILL from this recovery command.
        return _same_process(process, current)

    if not still_exact():
        return {**dict(process), "status": "NOT_RUNNING_OR_PID_REUSED"}
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and still_exact():
        time.sleep(0.05)
    if still_exact():
        os.kill(pid, signal.SIGKILL)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and still_exact():
            time.sleep(0.05)
    if still_exact():
        raise RecoveryBlocked(f"verified process {pid} did not terminate")
    return {**dict(process), "status": "TERMINATED"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="terminate exact matching processes and drop the exact isolated database",
    )
    args = parser.parse_args()
    journal_path = args.journal.resolve()
    journal = _load_journal(journal_path)
    before_sha256 = _sha256_file(journal_path)
    processes = [
        _inspect_process(journal.get("worker_process"), "worker"),
        _inspect_process(journal.get("api_process"), "api"),
    ]
    receipt: dict[str, object] = {
        "schema_version": "mila-mvp01-u0-orphan-cleanup-v0.1",
        "run_id": AUTHORIZED_RUN_ID,
        "journal": str(journal_path.relative_to(ROOT)),
        "journal_before_sha256": before_sha256,
        "mode": "EXECUTE" if args.execute else "INSPECT_ONLY",
        "processes": processes,
        "database": journal["database"],
        "status": "INSPECTED_NOT_MUTATED",
    }
    if not args.execute:
        print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    terminated = [_terminate_exact(value) for value in processes]
    load_runtime_environment((ROOT / "runtime/.env").resolve())
    owner_url = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
    if not owner_url:
        raise RecoveryBlocked("migration owner URL is absent")
    database = journal["database"]
    assert isinstance(database, str)
    database_cleanup = _drop_database(owner_url, database)
    if database_cleanup.get("status") != "PASS":
        raise RecoveryBlocked(
            f"database cleanup was blocked: {database_cleanup.get('reason')}"
        )
    receipt.update(
        {
            "processes": terminated,
            "database_cleanup": database_cleanup,
            "status": "PASS",
        }
    )
    receipt_path = journal_path.with_name("operator-cleanup-receipt.json")
    _atomic_json(receipt_path, receipt)
    journal.update(
        {
            "status": "RELEASED",
            "operator_cleanup_receipt": str(receipt_path.relative_to(ROOT)),
            "operator_cleanup_receipt_sha256": _sha256_file(receipt_path),
            "updated_at_unix_ns": time.time_ns(),
        }
    )
    _atomic_json(journal_path, journal)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RecoveryBlocked as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
