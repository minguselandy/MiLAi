from __future__ import annotations

import fcntl
import json
import os
import stat
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from scripts import dg10_remediation as remediation

ROOT = remediation.ROOT
ACTIVE_STAGE_LEDGER = ROOT / "var/dg10/stage-ledger-candidate.4.17.jsonl"
FIXED_R3_ACCEPTANCE_RECEIPT = ROOT / (
    "docs/reviews/DG-10-dg10-r3-ai-stage-receipt-candidate.4-2026-08-22.json"
)
ALLOWED_STAGES = tuple(f"DG10-R{index}" for index in range(9)) + tuple(
    f"DG10-L{index}" for index in range(1, 6)
)
ALLOWED_STATES = frozenset(
    {
        "NOT_STARTED",
        "AUTHOR_CANDIDATE",
        "REVIEW_REQUIRED",
        "ACCEPTED",
        "REVISE",
        "NO_GO_TERMINAL",
    }
)
ALLOWED_EVIDENCE_CLASSES = frozenset(
    {"AUTHOR", "DETERMINISTIC", "HUMAN", "INDEPENDENT", "AI_INDEPENDENT"}
)
ENTRY_KEYS = {
    "schema",
    "sequence",
    "previous_entry_sha256",
    "entry_sha256",
    "candidate_id",
    "stage_id",
    "stage_state",
    "evidence_class",
    "source_inventory_sha256",
    "receipt",
    "supersedes_entry_sha256",
    "recorded_at",
}


class StageLedgerError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise StageLedgerError(reason)


def _entry_sha256(entry: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in entry.items() if key != "entry_sha256"}
    return remediation.sha256_bytes(remediation.encoded_json(payload))


def _has_symlink_component(path: Path) -> bool:
    lexical = path.absolute()
    root = ROOT.absolute()
    try:
        relative = lexical.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def _active_ledger_path(path: Path) -> Path:
    requested = path.absolute()
    active = ACTIVE_STAGE_LEDGER.absolute()
    _require(requested == active, "stage ledger path is not active")
    _require(
        not _has_symlink_component(requested),
        "stage ledger path has a symlink component",
    )
    return requested


def _reference(path: Path) -> dict[str, str]:
    lexical = path.absolute()
    _require(
        not _has_symlink_component(lexical),
        "stage receipt reference has a symlink component",
    )
    resolved = lexical.resolve()
    _require(
        resolved.is_relative_to(ROOT) and resolved.is_file() and not resolved.is_symlink(),
        "stage receipt reference is missing or unsafe",
    )
    return {
        "path": resolved.relative_to(ROOT).as_posix(),
        "sha256": remediation.sha256_file(resolved),
    }


def _verify_reference(value: object) -> Path:
    _require(isinstance(value, Mapping) and set(value) == {"path", "sha256"}, "stage receipt reference drift")
    relative = value.get("path")
    _require(isinstance(relative, str) and relative, "stage receipt path absent")
    parsed = PurePosixPath(relative)
    _require(not parsed.is_absolute() and ".." not in parsed.parts, "stage receipt path unsafe")
    lexical = (ROOT / parsed).absolute()
    _require(
        not _has_symlink_component(lexical),
        "stage receipt has a symlink component",
    )
    target = lexical.resolve()
    _require(target.is_relative_to(ROOT.resolve()) and target.is_file(), "stage receipt missing or unsafe")
    remediation._require_sha256(value.get("sha256"), "stage receipt")
    _require(remediation.sha256_file(target) == value.get("sha256"), "stage receipt hash drift")
    return target


def _validated_receipt(
    value: object,
    *,
    candidate_id: object,
    stage_id: object,
    stage_state: object,
    evidence_class: object,
    source_inventory_sha256: object,
) -> Path:
    receipt_path = _verify_reference(value)
    if stage_id == "DG10-R3" and stage_state == "ACCEPTED":
        _require(
            receipt_path == FIXED_R3_ACCEPTANCE_RECEIPT.resolve(),
            "R3 ACCEPTED requires the fixed R3 AI importer receipt",
        )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageLedgerError("stage receipt is not valid JSON") from exc
    _require(isinstance(receipt, Mapping), "stage receipt is not an object")
    _require(
        receipt.get("schema")
        in {"milai.dg10.stage-state-binding.v1", "milai.dg10.stage-receipt.v1"}
        and receipt.get("candidate_id") == candidate_id
        and receipt.get("stage_id") == stage_id
        and receipt.get("stage_state") == stage_state
        and receipt.get("evidence_class") == evidence_class
        and receipt.get("source_inventory_sha256") == source_inventory_sha256,
        "stage receipt internal ledger binding drift",
    )
    evidence = receipt.get("evidence")
    _require(isinstance(evidence, list) and bool(evidence), "stage receipt evidence absent")
    evidence_paths = [_verify_reference(reference) for reference in evidence]
    if stage_id == "DG10-R1" and stage_state == "AUTHOR_CANDIDATE":
        _require(
            receipt.get("schema") == "milai.dg10.stage-state-binding.v1"
            and len(evidence_paths) == 1,
            "R1 author binding must identify one subordinate receipt",
        )
        try:
            subordinate = json.loads(evidence_paths[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StageLedgerError("R1 subordinate receipt is invalid") from exc
        source = subordinate.get("source_inventory") if isinstance(subordinate, Mapping) else None
        _require(
            isinstance(subordinate, Mapping)
            and subordinate.get("schema")
            == "milai.dg10.remediation-contract-validation.v1"
            and subordinate.get("candidate_id") == candidate_id
            and subordinate.get("scope") == "all"
            and isinstance(source, Mapping)
            and source.get("schema")
            == "milai.dg10.candidate-source-inventory.v1"
            and source.get("candidate_id") == candidate_id
            and source.get("canonical_entries_sha256")
            == source_inventory_sha256,
            "R1 subordinate receipt internal source identity drift",
        )
    if stage_state == "ACCEPTED":
        _require(
            receipt.get("schema") == "milai.dg10.stage-receipt.v1"
            and receipt.get("independent_acceptance") is True
            and receipt.get("open_p0") == 0
            and receipt.get("open_p1") == 0,
            "accepted stage receipt lacks independent zero-finding semantics",
        )
    return receipt_path


def _recorded_at(value: object) -> datetime:
    _require(isinstance(value, str) and value, "stage ledger timestamp absent")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise StageLedgerError("stage ledger timestamp invalid") from exc
    _require(
        parsed.tzinfo is not None and parsed.utcoffset() is not None,
        "stage ledger timestamp lacks timezone",
    )
    return parsed


def _validate_entry(entry: Mapping[str, Any]) -> None:
    _require(set(entry) == ENTRY_KEYS, "stage ledger entry key set drift")
    _require(entry.get("schema") == "milai.dg10.stage-ledger-entry.v1", "stage ledger schema drift")
    _require(entry.get("candidate_id") == remediation.CANDIDATE, "stage ledger candidate drift")
    _require(entry.get("stage_id") in ALLOWED_STAGES, "stage ledger stage ID drift")
    _require(entry.get("stage_state") in ALLOWED_STATES, "stage ledger state drift")
    _require(entry.get("evidence_class") in ALLOWED_EVIDENCE_CLASSES, "stage ledger evidence class drift")
    _require(
        isinstance(entry.get("sequence"), int)
        and not isinstance(entry.get("sequence"), bool)
        and entry["sequence"] > 0,
        "stage ledger sequence drift",
    )
    for key in ("entry_sha256", "source_inventory_sha256"):
        remediation._require_sha256(entry.get(key), f"stage ledger {key}")
    for key in ("previous_entry_sha256", "supersedes_entry_sha256"):
        if entry.get(key) is not None:
            remediation._require_sha256(entry[key], f"stage ledger {key}")
    _require(_entry_sha256(entry) == entry.get("entry_sha256"), "stage ledger entry hash drift")
    _validated_receipt(
        entry.get("receipt"),
        candidate_id=entry.get("candidate_id"),
        stage_id=entry.get("stage_id"),
        stage_state=entry.get("stage_state"),
        evidence_class=entry.get("evidence_class"),
        source_inventory_sha256=entry.get("source_inventory_sha256"),
    )
    _recorded_at(entry.get("recorded_at"))
    if entry.get("stage_state") == "ACCEPTED":
        _require(
            entry.get("evidence_class") in {"INDEPENDENT", "AI_INDEPENDENT"},
            "accepted stage lacks independent evidence",
        )


def _transition_allowed(previous: str | None, current: str) -> bool:
    if previous is None:
        return current in {"NOT_STARTED", "AUTHOR_CANDIDATE"}
    return current in {
        "NOT_STARTED": {"AUTHOR_CANDIDATE"},
        "AUTHOR_CANDIDATE": {"REVIEW_REQUIRED"},
        "REVIEW_REQUIRED": {"ACCEPTED", "REVISE", "NO_GO_TERMINAL"},
        "ACCEPTED": set(),
        "REVISE": set(),
        "NO_GO_TERMINAL": set(),
    }[previous]


def read_stage_ledger(path: Path = ACTIVE_STAGE_LEDGER) -> list[dict[str, Any]]:
    resolved = _active_ledger_path(path)
    _require(
        resolved.is_file()
        and not resolved.is_symlink()
        and stat.S_IMODE(resolved.stat().st_mode) == 0o600,
        "stage ledger is missing, unsafe, or not mode 0600",
    )
    entries: list[dict[str, Any]] = []
    for line_number, raw in enumerate(resolved.read_bytes().splitlines(), start=1):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StageLedgerError(f"invalid stage ledger JSON at line {line_number}") from exc
        _require(isinstance(value, dict), "stage ledger row is not an object")
        entries.append(value)
    return entries


def reconcile_stage_ledger(path: Path = ACTIVE_STAGE_LEDGER) -> dict[str, Any]:
    active_path = _active_ledger_path(path)
    entries = read_stage_ledger(path)
    previous_hash: str | None = None
    previous_recorded_at: datetime | None = None
    current: dict[str, dict[str, Any]] = {}
    for sequence, entry in enumerate(entries, start=1):
        _validate_entry(entry)
        _require(entry["sequence"] == sequence, "stage ledger sequence is not contiguous")
        _require(entry["previous_entry_sha256"] == previous_hash, "stage ledger hash chain is broken")
        recorded_at = _recorded_at(entry["recorded_at"])
        _require(
            previous_recorded_at is None or recorded_at >= previous_recorded_at,
            "stage ledger timestamp regressed",
        )
        stage_id = str(entry["stage_id"])
        old = current.get(stage_id)
        _require(
            entry["supersedes_entry_sha256"] == (old["entry_sha256"] if old else None),
            "stage ledger supersession link drift",
        )
        _require(
            _transition_allowed(old["stage_state"] if old else None, str(entry["stage_state"])),
            "stage ledger transition is forbidden",
        )
        current[stage_id] = dict(entry)
        previous_hash = str(entry["entry_sha256"])
        previous_recorded_at = recorded_at
    return {
        "schema": "milai.dg10.stage-ledger-reconciliation.v1",
        "candidate_id": remediation.CANDIDATE,
        "entry_count": len(entries),
        "ledger_sha256": remediation.sha256_file(active_path),
        "ledger_size": active_path.stat().st_size,
        "last_entry_sha256": previous_hash,
        "current_stage_states": {
            stage: entry["stage_state"] for stage, entry in sorted(current.items())
        },
        "current_entries": {stage: entry for stage, entry in sorted(current.items())},
        "hash_chain_valid": True,
    }


def append_stage_state(
    *,
    stage_id: str,
    stage_state: str,
    evidence_class: str,
    source_inventory_sha256: str,
    receipt_path: Path,
    path: Path = ACTIVE_STAGE_LEDGER,
) -> dict[str, Any]:
    resolved = _active_ledger_path(path)
    _require(stage_id in ALLOWED_STAGES, "stage ledger stage ID drift")
    _require(stage_state in ALLOWED_STATES, "stage ledger state drift")
    _require(
        evidence_class in ALLOWED_EVIDENCE_CLASSES,
        "stage ledger evidence class drift",
    )
    remediation._require_sha256(source_inventory_sha256, "stage source inventory")
    receipt_reference = _reference(receipt_path)
    _validated_receipt(
        receipt_reference,
        candidate_id=remediation.CANDIDATE,
        stage_id=stage_id,
        stage_state=stage_state,
        evidence_class=evidence_class,
        source_inventory_sha256=source_inventory_sha256,
    )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if not resolved.exists():
        _require(
            _transition_allowed(None, stage_state),
            "stage ledger transition is forbidden",
        )
    if resolved.exists():
        _require(
            resolved.is_file()
            and not resolved.is_symlink()
            and stat.S_IMODE(resolved.stat().st_mode) == 0o600,
            "stage ledger is unsafe or not mode 0600",
        )
    flags = os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(resolved, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "r+b", closefd=False) as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            stream.seek(0)
            existing = stream.read()
            entries: list[dict[str, Any]] = []
            for raw in existing.splitlines():
                value = json.loads(raw)
                _require(isinstance(value, dict), "stage ledger row is not an object")
                entries.append(value)
            previous_hash: str | None = None
            previous_recorded_at: datetime | None = None
            current: dict[str, dict[str, Any]] = {}
            for sequence, item in enumerate(entries, start=1):
                _validate_entry(item)
                _require(item["sequence"] == sequence, "stage ledger sequence is not contiguous")
                _require(item["previous_entry_sha256"] == previous_hash, "stage ledger hash chain is broken")
                recorded_at = _recorded_at(item["recorded_at"])
                _require(
                    previous_recorded_at is None
                    or recorded_at >= previous_recorded_at,
                    "stage ledger timestamp regressed",
                )
                old = current.get(str(item["stage_id"]))
                _require(
                    item["supersedes_entry_sha256"] == (old["entry_sha256"] if old else None),
                    "stage ledger supersession link drift",
                )
                _require(
                    _transition_allowed(old["stage_state"] if old else None, str(item["stage_state"])),
                    "stage ledger transition is forbidden",
                )
                current[str(item["stage_id"])] = item
                previous_hash = str(item["entry_sha256"])
                previous_recorded_at = recorded_at
            old = current.get(stage_id)
            _require(_transition_allowed(old["stage_state"] if old else None, stage_state), "stage ledger transition is forbidden")
            entry: dict[str, Any] = {
                "schema": "milai.dg10.stage-ledger-entry.v1",
                "sequence": len(entries) + 1,
                "previous_entry_sha256": previous_hash,
                "entry_sha256": "",
                "candidate_id": remediation.CANDIDATE,
                "stage_id": stage_id,
                "stage_state": stage_state,
                "evidence_class": evidence_class,
                "source_inventory_sha256": source_inventory_sha256,
                "receipt": receipt_reference,
                "supersedes_entry_sha256": old["entry_sha256"] if old else None,
                "recorded_at": datetime.now(UTC).isoformat(),
            }
            entry["entry_sha256"] = _entry_sha256(entry)
            _validate_entry(entry)
            stream.seek(0, os.SEEK_END)
            stream.write(remediation.encoded_json(entry))
            stream.flush()
            os.fsync(stream.fileno())
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            return entry
    except (OSError, json.JSONDecodeError) as exc:
        raise StageLedgerError("stage ledger append failed") from exc
    finally:
        os.close(descriptor)


def write_checkpoint(
    output_path: Path,
    *,
    required_stages: Sequence[str],
    required_state: str,
    path: Path = ACTIVE_STAGE_LEDGER,
) -> dict[str, Any]:
    active_path = _active_ledger_path(path)
    reconciliation = reconcile_stage_ledger(path)
    current = reconciliation["current_entries"]
    _require(len(required_stages) == len(set(required_stages)), "checkpoint stage list repeats")
    _require(
        all(stage in current and current[stage]["stage_state"] == required_state for stage in required_stages),
        "stage ledger checkpoint state requirement failed",
    )
    value = {
        "schema": "milai.dg10.stage-ledger-checkpoint.v1",
        "candidate_id": remediation.CANDIDATE,
        "ledger_path": active_path.relative_to(ROOT.absolute()).as_posix(),
        "ledger_prefix_sha256": reconciliation["ledger_sha256"],
        "ledger_prefix_size": reconciliation["ledger_size"],
        "entry_count": reconciliation["entry_count"],
        "last_entry_sha256": reconciliation["last_entry_sha256"],
        "required_state": required_state,
        "required_stages": list(required_stages),
        "current_entries": {stage: current[stage] for stage in required_stages},
    }
    remediation.atomic_write_new(output_path.resolve(), remediation.encoded_json(value))
    return value


def verify_checkpoint(
    checkpoint_path: Path,
    *,
    required_stages: Sequence[str],
    required_state: str,
    path: Path = ACTIVE_STAGE_LEDGER,
) -> dict[str, Any]:
    lexical_checkpoint = checkpoint_path.absolute()
    _require(
        not _has_symlink_component(lexical_checkpoint),
        "stage checkpoint has a symlink component",
    )
    resolved_checkpoint = lexical_checkpoint.resolve()
    _require(
        resolved_checkpoint.is_relative_to(ROOT.resolve())
        and resolved_checkpoint.is_file()
        and not resolved_checkpoint.is_symlink(),
        "stage checkpoint is missing or unsafe",
    )
    _require(
        len(required_stages) == len(set(required_stages))
        and all(stage in ALLOWED_STAGES for stage in required_stages),
        "checkpoint stage list is invalid",
    )
    try:
        value = json.loads(resolved_checkpoint.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageLedgerError("stage checkpoint is invalid") from exc
    required = {
        "schema",
        "candidate_id",
        "ledger_path",
        "ledger_prefix_sha256",
        "ledger_prefix_size",
        "entry_count",
        "last_entry_sha256",
        "required_state",
        "required_stages",
        "current_entries",
    }
    _require(isinstance(value, Mapping) and set(value) == required, "stage checkpoint key set drift")
    _require(
        value.get("schema") == "milai.dg10.stage-ledger-checkpoint.v1"
        and value.get("candidate_id") == remediation.CANDIDATE
        and value.get("required_stages") == list(required_stages)
        and value.get("required_state") == required_state,
        "stage checkpoint semantic drift",
    )
    resolved = _active_ledger_path(path)
    _require(
        value.get("ledger_path") == resolved.relative_to(ROOT).as_posix(),
        "stage checkpoint ledger path drift",
    )
    prefix_size = value.get("ledger_prefix_size")
    _require(
        isinstance(prefix_size, int)
        and not isinstance(prefix_size, bool)
        and prefix_size > 0,
        "stage checkpoint prefix size drift",
    )
    raw = resolved.read_bytes()
    _require(len(raw) >= prefix_size, "stage ledger was truncated after checkpoint")
    _require(
        remediation.sha256_bytes(raw[:prefix_size]) == value.get("ledger_prefix_sha256"),
        "stage ledger checkpoint prefix drift",
    )
    prefix_lines = raw[:prefix_size].splitlines()
    _require(
        value.get("entry_count") == len(prefix_lines) and bool(prefix_lines),
        "stage checkpoint entry count drift",
    )
    try:
        prefix_last = json.loads(prefix_lines[-1])
    except json.JSONDecodeError as exc:
        raise StageLedgerError("stage checkpoint prefix is invalid JSON") from exc
    _require(
        isinstance(prefix_last, Mapping)
        and prefix_last.get("entry_sha256") == value.get("last_entry_sha256"),
        "stage checkpoint last-entry drift",
    )
    reconciliation = reconcile_stage_ledger(resolved)
    current = reconciliation["current_entries"]
    checkpoint_entries = value.get("current_entries")
    _require(isinstance(checkpoint_entries, Mapping), "stage checkpoint entries absent")
    for stage in required_stages:
        _require(
            stage in current
            and current[stage]["stage_state"] == required_state
            and checkpoint_entries.get(stage) == current[stage],
            "stage checkpoint/current state mismatch",
        )
    return reconciliation
