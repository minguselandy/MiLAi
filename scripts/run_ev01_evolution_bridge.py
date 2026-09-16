#!/usr/bin/env python3
"""Run EV-01 typed mapping plus a fresh-PostgreSQL Canonical replay."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for source_root in (ROOT, RUNTIME_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from milai.config import load_settings
from milai.domain.requirement_state import canonical_sha256
from milai.operations.local_runtime import load_runtime_environment
from milai.operations.smoke import _create_database, _database_url, _drop_database

from evals.ev01.evolution_bridge_effect import execute_ev01_mapping_effect

RUN_ID = "ev01-governed-evolution-bridge-20260830-001"
OUTPUT_DIR = ROOT / "var/ev01" / RUN_ID
MAPPING = OUTPUT_DIR / "mapping-effect.json"
PG_LOG = OUTPUT_DIR / "postgresql-replay.log"
RECEIPT = OUTPUT_DIR / "receipt.json"
LATEST = ROOT / "var/ev01/latest.json"
MF04 = ROOT / "var/mf04/mf04-state-change-formation-20260830-001/receipt.json"
ENV_FILE = ROOT / "runtime/.env"
TEST = (
    "tests/integration/test_canonical_api.py::"
    "test_formation_evolution_bridge_replays_update_revoke_and_reground"
)


def run() -> dict[str, Any]:
    if OUTPUT_DIR.exists():
        raise RuntimeError("EV01_OUTPUT_ALREADY_EXISTS")
    OUTPUT_DIR.mkdir(parents=True)
    mapping = execute_ev01_mapping_effect(ROOT)
    _write_exclusive(MAPPING, mapping)
    database_gate = _run_postgresql_replay()
    hard_gates = {
        "UnsupportedCanonicalPromotion": mapping["metrics"][
            "UnsupportedCanonicalPromotion"
        ],
        "WrongTransitionDisposition": mapping["metrics"][
            "WrongTransitionDisposition"
        ],
        "MissingProvenanceClosure": mapping["metrics"]["MissingProvenanceClosure"],
        "ValidTimeMisassignment": mapping["metrics"]["ValidTimeMisassignment"],
        "RevocationSupportLeak": 0 if database_gate["passed"] else 1,
        "RollbackReplayMismatch": 0 if database_gate["passed"] else 1,
    }
    passed = (
        mapping["status"] == "PASS_EV01_TYPED_MAPPING"
        and database_gate["passed"]
        and all(value == 0 for value in hard_gates.values())
    )
    receipt: dict[str, Any] = {
        "schema": "milai.ev01.terminal-receipt.v0.1",
        "run_id": RUN_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "PASS_EV01_GOVERNED_EVOLUTION_BRIDGE" if passed else "NEEDS_REPAIR",
        "predecessor": _identity(MF04),
        "mapping_result_digest": mapping["result_digest"],
        "hard_gates": hard_gates,
        "postgresql_replay": database_gate,
        "repair_iterations": [
            {
                "failure": "REVOKED_IDENTICAL_CONTENT_REINGEST_REJECTED",
                "root_cause": "revoked bytes are not independent recovery Evidence",
                "repair": "use a fresh independently observed reconfirmation before REGROUND",
            }
        ],
        "next_route": "MF02_OR_MF06_OPPORTUNITY_REVIEW" if passed else "EV01_REPAIR",
        "safety": {
            "formal_holdout_used": False,
            "experimental_feature_flags": "OFF",
            "schema_changed": False,
            "canonical_mutations_limited_to_ephemeral_test_database": True,
            "temporary_database_cleanup": database_gate["cleanup"],
            "model_calls": 0,
            "automatic_retries": 0,
        },
    }
    receipt["receipt_digest"] = canonical_sha256(receipt)
    _write_exclusive(RECEIPT, receipt)
    _write_latest(LATEST, receipt)
    return receipt


def validate() -> dict[str, Any]:
    mapping = _object(MAPPING)
    receipt = _object(RECEIPT)
    _verify(mapping, "result_digest")
    _verify(receipt, "receipt_digest")
    if (
        receipt["mapping_result_digest"] != mapping["result_digest"]
        or _object(LATEST) != receipt
        or _identity(PG_LOG) != receipt["postgresql_replay"]["log"]
    ):
        raise RuntimeError("EV01_ARTIFACT_LINKAGE_INVALID")
    return {
        "valid": True,
        "status": receipt["status"],
        "receipt_digest": receipt["receipt_digest"],
        "hard_gates": receipt["hard_gates"],
    }


def _run_postgresql_replay() -> dict[str, Any]:
    load_runtime_environment(ENV_FILE)
    settings = load_settings()
    owner = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
    worker = os.environ.get("MILAI_WORKER_DATABASE_URL")
    audit = os.environ.get("MILAI_AUDIT_DATABASE_URL")
    if not owner or not worker or not audit:
        raise RuntimeError("EV01_DATABASE_ROLE_URLS_MISSING")
    database = f"milai_smoke_ev01_{secrets.token_hex(8)}"
    created = False
    cleanup: dict[str, object] = {"status": "NOT_CREATED"}
    completed: subprocess.CompletedProcess[str] | None = None
    try:
        _create_database(owner, database)
        created = True
        environment = dict(os.environ)
        environment.update(
            {
                "PYTHONPATH": f"{RUNTIME_SRC}:{ROOT}",
                "MILAI_MIGRATION_DATABASE_URL": _database_url(owner, database),
                "MILAI_TEST_DATABASE_URL": _database_url(owner, database),
                "MILAI_TEST_API_DATABASE_URL": _database_url(
                    settings.database_dsn, database
                ),
                "MILAI_TEST_STEWARD_DATABASE_URL": _database_url(
                    settings.steward_database_dsn, database
                ),
                "MILAI_TEST_WORKER_DATABASE_URL": _database_url(worker, database),
                "MILAI_TEST_AUDIT_DATABASE_URL": _database_url(audit, database),
            }
        )
        completed = subprocess.run(
            [str(ROOT / "runtime/.venv/bin/pytest"), "-q", TEST],
            cwd=ROOT / "runtime",
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        PG_LOG.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    finally:
        cleanup = (
            dict(_drop_database(owner, database))
            if created
            else {"status": "NOT_CREATED"}
        )
    if completed is None:
        raise RuntimeError("EV01_POSTGRESQL_REPLAY_NOT_EXECUTED")
    passed = (
        completed.returncode == 0
        and cleanup.get("status") == "PASS"
        and bool(re.search(r"1 passed", completed.stdout))
    )
    return {
        "passed": passed,
        "exit_code": completed.returncode,
        "test": TEST,
        "summary": "1 passed" if "1 passed" in completed.stdout else "not passed",
        "fresh_ephemeral_database": True,
        "database_name_sha256": hashlib.sha256(database.encode()).hexdigest(),
        "credentials_recorded": False,
        "cleanup": cleanup,
        "log": _identity(PG_LOG),
    }


def _verify(value: dict[str, Any], field: str) -> None:
    material = dict(value)
    observed = material.pop(field, None)
    if observed != canonical_sha256(material):
        raise RuntimeError(f"EV01_DIGEST_INVALID:{field}")


def _identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)


def _write_latest(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command not in {"run", "validate"}:
        raise SystemExit("usage: run_ev01_evolution_bridge.py [run|validate]")
    output = run() if command == "run" else validate()
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
