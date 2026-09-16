"""Append-only artifact helpers shared by DG-25 stage runners."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


class DG25ArtifactError(RuntimeError):
    """A DG-25 artifact would be overwritten or has an invalid identity."""


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_identity(root: Path, path: Path) -> dict[str, Any]:
    resolved_root = root.resolve()
    resolved = path.resolve()
    if not resolved.is_file():
        raise DG25ArtifactError(f"artifact is not a file: {resolved}")
    try:
        relative = resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise DG25ArtifactError(f"artifact is outside repository: {resolved}") from exc
    return {
        "path": relative.as_posix(),
        "sha256": sha256_file(resolved),
        "size": resolved.stat().st_size,
    }


def write_json_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise DG25ArtifactError(f"refusing to overwrite artifact: {path}") from exc


def write_bytes_new(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(value)
    except FileExistsError as exc:
        raise DG25ArtifactError(f"refusing to overwrite artifact: {path}") from exc


def append_failure(
    root: Path,
    *,
    failure_id: str,
    recorded_at: str,
    command_argv: Sequence[str],
    cwd: str,
    exit_code: int,
    stdout: str,
    stderr: str,
    first_failing_gate: str,
    root_cause: str,
    general_fix: str,
    fresh_rerun_id: str,
    config_identity: Mapping[str, Any] | None = None,
    source_identities: Sequence[Mapping[str, Any]] = (),
    snapshot_identities: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Persist one failure exactly once and append its identity to the ledger."""

    root = root.resolve()
    failure_root = root / "var/dg25/failures" / failure_id
    try:
        failure_root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise DG25ArtifactError(f"duplicate failure id: {failure_id}") from exc

    stdout_path = failure_root / "stdout.txt"
    stderr_path = failure_root / "stderr.txt"
    write_bytes_new(stdout_path, stdout.encode("utf-8"))
    write_bytes_new(stderr_path, stderr.encode("utf-8"))
    receipt = {
        "schema": "milai.dg25.failure-receipt.v0.1",
        "failure_id": failure_id,
        "recorded_at": recorded_at,
        "command": {"argv": list(command_argv), "cwd": cwd, "exit_code": exit_code},
        "config_identity": dict(config_identity or {}),
        "source_identities": [dict(item) for item in source_identities],
        "snapshot_identities": [dict(item) for item in snapshot_identities],
        "stdout": file_identity(root, stdout_path),
        "stderr": file_identity(root, stderr_path),
        "first_failing_gate": first_failing_gate,
        "root_cause": root_cause,
        "general_fix": general_fix,
        "fresh_rerun_id": fresh_rerun_id,
        "automatic_retries": 0,
    }
    receipt_path = failure_root / "receipt.json"
    write_json_new(receipt_path, receipt)
    receipt_identity = file_identity(root, receipt_path)

    index_path = root / "var/dg25/failure-index.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    if index_path.exists():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if isinstance(item, Mapping) and item.get("failure_id") == failure_id:
                raise DG25ArtifactError(f"failure already indexed: {failure_id}")
    index_entry = {
        "failure_id": failure_id,
        "recorded_at": recorded_at,
        "first_failing_gate": first_failing_gate,
        "receipt": receipt_identity,
    }
    with index_path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_bytes(index_entry).decode("utf-8") + "\n")
    return receipt

