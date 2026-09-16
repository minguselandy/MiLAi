from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DG11_ROOT = ROOT / "var/dg11"
CURRENT_STATE = DG11_ROOT / "current-state.json"
LEDGER = DG11_ROOT / "dev/experiment-ledger.jsonl"
LATEST_RESULT = DG11_ROOT / "dev/latest-result.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: MappingLike) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


MappingLike = dict[str, Any]


def append_ledger(value: MappingLike) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def record_result(
    result: MappingLike,
    *,
    phase: str,
    work_package: str,
    state_status: str | None = None,
) -> None:
    current = json.loads(CURRENT_STATE.read_text(encoding="utf-8"))
    if result.get("provider_requests") != 0 and work_package == "DG11-00":
        raise ValueError("DG11-00 must not call the Provider")
    atomic_json(LATEST_RESULT, result)
    append_ledger(
        {
            "run_id": result["run_id"],
            "work_package": work_package,
            "status": result["status"],
            "decision": result.get("decision"),
            "provider_requests": result.get("provider_requests", 0),
            "development_ai_reviews": 0,
            "metrics": result.get("summary", {}),
        }
    )
    current["phase"] = phase
    current["work_packages"][work_package] = state_status or result["status"]
    current["latest_result"] = result["run_id"]
    current["development_ai_reviews"] = 0
    atomic_json(CURRENT_STATE, current)
