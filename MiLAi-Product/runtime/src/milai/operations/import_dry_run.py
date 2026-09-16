from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

from milai.config import RuntimeSettings, SettingsError

ImportSource = Literal["mem0-json-v1", "graphiti-json-v1", "hindsight-json-v1"]
_MAX_INPUT_BYTES = 10 * 1024 * 1024
_MAX_RECORDS = 10_000


def dry_run_import(
    settings: RuntimeSettings,
    *,
    source: ImportSource,
    input_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    raw = _read_input(input_path)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SettingsError("import source must be a UTF-8 JSON array") from exc
    if not isinstance(value, list) or len(value) > _MAX_RECORDS:
        raise SettingsError(f"import source must contain at most {_MAX_RECORDS} records")

    accepted: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        normalized, reasons = _normalize(source, item)
        if reasons:
            quarantined.append({"index": index, "reason_codes": sorted(set(reasons))})
        else:
            assert normalized is not None
            accepted.append(normalized)

    report = {
        "format": "milai-import-dry-run-v1",
        "mode": "READ_ONLY_NO_DATABASE_NO_BLOB_WRITE",
        "source_adapter": source,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_bytes": len(raw),
        "record_count": len(value),
        "accepted_count": len(accepted),
        "quarantined_count": len(quarantined),
        "accepted_records": accepted,
        "quarantine": quarantined,
        "data_gate": {
            "configured_mode": settings.data_mode,
            "blob_encryption": settings.blob_encryption,
            "backup_key_recovery_confirmed": settings.backup_key_recovery_confirmed,
            "user_import_authorization": "NOT_PROVIDED_BY_DRY_RUN",
            "execution_authorized": False,
        },
        "next_required": [
            "source-specific mapping review",
            "privacy/threat review",
            "explicit user authorization",
            "encrypted backup/restore and deletion rehearsal",
            "separate immutable Evidence import command",
            "independent Proposal review",
        ],
    }
    _exclusive_report(report_path, report)
    return {
        "status": "DRY_RUN_COMPLETE_NO_WRITES",
        "source": source,
        "records": len(value),
        "accepted": len(accepted),
        "quarantined": len(quarantined),
        "report": str(report_path.expanduser().resolve(strict=False)),
        "execution_authorized": False,
    }


def _normalize(source: ImportSource, item: object) -> tuple[dict[str, Any] | None, list[str]]:
    if not isinstance(item, dict):
        return None, ["RECORD_NOT_OBJECT"]
    reasons: list[str] = []
    if source == "mem0-json-v1":
        identifier = _string(item.get("id"), "SOURCE_ID_MISSING", reasons)
        content = _string(item.get("memory"), "CONTENT_MISSING", reasons)
        observed_at = _string(item.get("created_at"), "OBSERVED_AT_MISSING", reasons)
        scope = {
            key: item[key]
            for key in ("user_id", "agent_id", "app_id", "run_id")
            if isinstance(item.get(key), str) and item[key]
        }
        if not scope:
            reasons.append("SOURCE_SCOPE_MISSING")
    elif source == "graphiti-json-v1":
        identifier = _string(item.get("uuid"), "SOURCE_ID_MISSING", reasons)
        content = _string(item.get("content"), "CONTENT_MISSING", reasons)
        observed_at = _string(
            item.get("valid_at", item.get("created_at")), "OBSERVED_AT_MISSING", reasons
        )
        group_id = _string(item.get("group_id"), "SOURCE_SCOPE_MISSING", reasons)
        scope = {"group_id": group_id} if group_id else {}
        if not isinstance(item.get("source_description"), str):
            reasons.append("SOURCE_DESCRIPTION_MISSING")
    else:
        identifier = _string(item.get("id", item.get("document_id")), "SOURCE_ID_MISSING", reasons)
        content = _string(item.get("content"), "CONTENT_MISSING", reasons)
        observed_at = _string(
            item.get("timestamp", item.get("created_at")), "OBSERVED_AT_MISSING", reasons
        )
        bank_id = _string(item.get("bank_id"), "SOURCE_SCOPE_MISSING", reasons)
        scope = {"bank_id": bank_id} if bank_id else {}

    permission = item.get("permission_snapshot")
    if not isinstance(permission, dict) or permission.get("authorized") is not True:
        reasons.append("IMPORT_PERMISSION_UNPROVEN")
    retention = item.get("retention_state")
    if retention not in {"READABLE", "LEGAL_HOLD"}:
        reasons.append("RETENTION_UNPROVEN_OR_UNREADABLE")
    if item.get("tenant_id") is None:
        reasons.append("TENANT_MAPPING_MISSING")
    if reasons or identifier is None or content is None or observed_at is None:
        return None, reasons
    content_bytes = content.encode()
    return (
        {
            "source_id": identifier,
            "source_scope": scope,
            "tenant_mapping": str(item["tenant_id"]),
            "observed_at": observed_at,
            "content_sha256": hashlib.sha256(content_bytes).hexdigest(),
            "content_bytes": len(content_bytes),
            "permission_fingerprint": hashlib.sha256(
                json.dumps(permission, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "retention_state": retention,
            "proposed_target": "IMMUTABLE_EVIDENCE_ONLY",
            "canonical_claim_created": False,
        },
        [],
    )


def _string(value: object, code: str, reasons: list[str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        reasons.append(code)
        return None
    return value.strip()


def _read_input(path: Path) -> bytes:
    target = path.expanduser().resolve(strict=True)
    if not target.is_file() or target.is_symlink():
        raise SettingsError("import source must be a regular non-symlink file")
    size = target.stat().st_size
    if size > _MAX_INPUT_BYTES:
        raise SettingsError("import source exceeds the 10 MiB dry-run limit")
    return target.read_bytes()


def _exclusive_report(path: Path, report: dict[str, Any]) -> None:
    target = path.expanduser().resolve(strict=False)
    if not target.parent.is_dir():
        raise SettingsError("import report parent directory must exist")
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SettingsError("import dry-run never overwrites an existing report") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
