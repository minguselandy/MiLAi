from __future__ import annotations

import fcntl
import hashlib
import io
import json
import os
import stat
import tarfile
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Self
from uuid import uuid4

# The remediation workspace is an explicit protocol constant.  Authority code is
# installed outside the workspace, so deriving ROOT from ``__file__`` would make
# a protected copy silently read a different evidence tree.
ROOT = Path("/cra/memory/mx_memory/MiLAi")
CANDIDATE = "candidate.4"
DATE = "2026-08-22"
SHA256_PATTERN_LENGTH = 64
AI_AUDIT_MODEL_REFRESH_DIAGNOSTIC = (
    "ERROR codex_models_manager::manager: failed to refresh available models: "
    "timeout waiting for child process to exit"
)
AI_AUDIT_STDERR_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

BASELINE_ARCHIVE = ROOT / "dist/DG-10-experiment-results-candidate.2-2026-08-22.tar.gz"
BASELINE_RECEIPT = ROOT / (
    "dist/DG-10-experiment-results-candidate.2-2026-08-22.receipt.json"
)
BASELINE_FINAL_REPORT = ROOT / (
    "docs/reports/DG-10-final-completion-audit-candidate.2-2026-08-22.json"
)
BASELINE_CLAIM_MATRIX = ROOT / "docs/contracts/DG-10-claim-matrix.yaml"
BASELINE_QUALITY_CONTRACT = ROOT / "docs/contracts/DG-10-quality-acceptance.yaml"
BASELINE_SOL_DISPOSITION = ROOT / (
    "docs/reviews/DG-10-sol-final-audit-disposition-candidate.1-2026-08-22.json"
)
GOALS = ROOT / "MiLAi_DG-10实验结果整改与复验_GOALS.md"
PARENT_CANDIDATE_3_AI_AUDIT = ROOT / (
    "docs/reviews/DG-10-r0-r2-ai-blind-semantic-audit-receipt-candidate.3-2026-08-22.json"
)
AI_POLICY_OVERRIDE = ROOT / (
    "docs/contracts/DG-10-ai-audit-reasoning-amendment-candidate.4.2.json"
)

EXPECTED_BASELINE_HASHES = {
    BASELINE_ARCHIVE: "7e1b88267d2c9cd6f819d937ddd1ed5a1f15b5cb5b38b547f8067938f7702166",
    BASELINE_RECEIPT: "9452677d39c14649a42dea31c974373ffe25570ef0792b1615a4315998891c12",
    BASELINE_FINAL_REPORT: "b2c59ee959470b5ff1c73692d2b74eff94c83969a8e7803b1d704bcabcc303cb",
    BASELINE_CLAIM_MATRIX: "77d3252b06dde83f85cdfa8a321e85dd7a96fbfa821a740dd377860c0cc89665",
    BASELINE_QUALITY_CONTRACT: "50599ac26f478370f85655df8acaa4b278d7ea3e94aba4938110474b1fcf9f51",
    BASELINE_SOL_DISPOSITION: "d73147e8df49ca27056a878a3ac9bcf0bdcb49668018146abb4ce2a065dc523f",
    GOALS: "64610cf9a443e1a3227787de6fd6bb83e87f89905554ebdfec83c5e487bfd2af",
    PARENT_CANDIDATE_3_AI_AUDIT: "b16882fe56a173a1a1a7ecd3619075df609e53c1b8c243ee515c025f6a0118e8",
    AI_POLICY_OVERRIDE: "55b9359b26ba45dbc8357587fe7febbb315e130ec0de604bf98d5c5515b8a598",
}

STABLE_REASON_CODES = frozenset(
    {
        "PROVIDER_REQUEST_FAILED",
        "PROVIDER_TERMINAL_MISSING",
        "AGENT_EVENT_PARSE_FAILED",
        "AGENT_TERMINAL_EVENT_MISSING",
        "AGENT_POLICY_REJECTED",
        "OUTPUT_SCHEMA_INVALID",
        "DEADLINE_EXCEEDED",
        "SUCCESS",
    }
)
ATTEMPT_STATES = (
    "PLANNED",
    "PROVIDER_CLAIMED",
    "PROVIDER_ACCEPTED",
    "PROVIDER_TERMINAL",
    "FINALIZED",
)
RETENTION_STATES = frozenset({"retained", "superseded", "failed", "partial"})
USAGE_KEYS = ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens")
ATTEMPT_SNAPSHOT_KEYS = frozenset(
    {
        "schema",
        "sequence",
        "previous_entry_sha256",
        "entry_sha256",
        "attempt_id",
        "parent_attempt_id",
        "candidate_id",
        "phase",
        "arm",
        "case_id",
        "attempt_state",
        "planned_model_calls",
        "planned_mcp_calls",
        "native_request_ids",
        "native_mcp_request_ids",
        "usage",
        "provider_terminal",
        "mcp_terminal",
        "agent_terminal",
        "parser_terminal",
        "started_at",
        "provider_claimed_at",
        "native_completed_at",
        "mcp_completed_at",
        "finished_at",
        "retention_state",
        "failure_reason_code",
        "external_billed_cost",
        "self_hosted_compute_cost",
        "raw_sidecar_digest",
        "provider_claim_digest",
        "raw_mcp_sidecar_digest",
        "redacted_public_receipt_digest",
    }
)
ATTEMPT_IMMUTABLE_KEYS = frozenset(
    {
        "schema",
        "attempt_id",
        "parent_attempt_id",
        "candidate_id",
        "phase",
        "arm",
        "case_id",
        "planned_model_calls",
        "planned_mcp_calls",
        "started_at",
    }
)


class RemediationError(RuntimeError):
    pass


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def protected_tree_identity(
    root: Path,
    *,
    allowed_symlink_roots: tuple[Path, ...],
    expected_uid: int = 0,
    expected_gid: int = 0,
) -> dict[str, Any]:
    """Return a canonical identity for a non-writable protected filesystem tree."""

    root = root.absolute()
    allowed = tuple(path.resolve(strict=True) for path in allowed_symlink_roots)
    if (
        not root.is_dir()
        or root.is_symlink()
        or has_symlink_component(root)
        or not allowed
    ):
        raise RemediationError(f"protected tree root is absent or unsafe: {root}")
    entries: list[dict[str, Any]] = []
    for path in [root, *sorted(root.rglob("*"), key=lambda item: item.as_posix())]:
        relative = "." if path == root else path.relative_to(root).as_posix()
        observed = path.lstat()
        common = {
            "path": relative,
            "mode": f"{stat.S_IMODE(observed.st_mode):04o}",
            "uid": observed.st_uid,
            "gid": observed.st_gid,
        }
        if observed.st_uid != expected_uid or observed.st_gid != expected_gid:
            raise RemediationError(f"protected tree ownership drift: {path}")
        if stat.S_ISLNK(observed.st_mode):
            resolved = path.resolve(strict=True)
            if not any(resolved.is_relative_to(prefix) for prefix in allowed):
                raise RemediationError(f"protected tree symlink escapes closure: {path}")
            entries.append(
                {
                    **common,
                    "type": "symlink",
                    "target": os.readlink(path),
                    "resolved_path": str(resolved),
                }
            )
        elif stat.S_ISDIR(observed.st_mode):
            if stat.S_IMODE(observed.st_mode) & 0o022:
                raise RemediationError(f"protected tree directory is writable: {path}")
            entries.append({**common, "type": "directory"})
        elif stat.S_ISREG(observed.st_mode):
            if stat.S_IMODE(observed.st_mode) & 0o022:
                raise RemediationError(f"protected tree file is writable: {path}")
            entries.append({**common, "type": "file", "sha256": sha256_file(path)})
        else:
            raise RemediationError(f"protected tree contains special file: {path}")
    return {
        "path": str(root),
        "entry_count": len(entries),
        "tree_sha256": sha256_bytes(encoded_json({"entries": entries})),
    }


def has_symlink_component(path: Path) -> bool:
    lexical = path.absolute()
    current = Path(lexical.anchor)
    for part in lexical.parts[1:]:
        current /= part
        if current.is_symlink():
            return True
    return False


def encoded_json(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def ai_audit_stderr_is_nonfatal(raw: bytes) -> bool:
    if not raw:
        return True
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return False
    if text.count("\n") != 1 or not text.endswith("\n") or "\r" in text:
        return False
    timestamp, separator, diagnostic = text[:-1].partition(" ")
    if separator != " " or diagnostic != AI_AUDIT_MODEL_REFRESH_DIAGNOSTIC:
        return False
    try:
        parsed = datetime.strptime(timestamp, AI_AUDIT_STDERR_TIMESTAMP_FORMAT)
    except ValueError:
        return False
    return parsed.strftime(AI_AUDIT_STDERR_TIMESTAMP_FORMAT) == timestamp


def atomic_write_new(path: Path, raw: bytes, *, mode: int = 0o600) -> None:
    if has_symlink_component(path):
        raise RemediationError(f"refusing unsafe symlink artifact path: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RemediationError(f"refusing to overwrite immutable artifact: {path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_json(path: Path) -> dict[str, Any]:
    if has_symlink_component(path):
        raise RemediationError(f"unsafe symlink JSON path: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RemediationError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise RemediationError(f"JSON root is not an object: {path}")
    return value


def _safe_archive_path(name: str) -> bool:
    if "\\" in name:
        return False
    parsed = PurePosixPath(name)
    return bool(parsed.parts) and not parsed.is_absolute() and ".." not in parsed.parts


def inspect_baseline_archive(path: Path) -> dict[str, Any]:
    members = 0
    regular = 0
    unsafe = 0
    symlinks = 0
    hardlinks = 0
    seen: set[str] = set()
    with tarfile.open(fileobj=io.BytesIO(path.read_bytes()), mode="r:gz") as archive:
        for member in archive.getmembers():
            members += 1
            unsafe += int(not _safe_archive_path(member.name) or member.name in seen)
            seen.add(member.name)
            symlinks += int(member.issym())
            hardlinks += int(member.islnk())
            regular += int(member.isfile())
    return {
        "member_count": members,
        "regular_file_count": regular,
        "unsafe_path_or_duplicate_count": unsafe,
        "symlink_count": symlinks,
        "hardlink_count": hardlinks,
        "status": (
            "PASS_SAFE_REGULAR_MEMBERS"
            if members == regular and unsafe == symlinks == hardlinks == 0
            else "FAIL_UNSAFE_ARCHIVE"
        ),
    }


def build_baseline_report() -> dict[str, Any]:
    bindings: dict[str, Any] = {}
    for path, expected in EXPECTED_BASELINE_HASHES.items():
        if not path.is_file() or has_symlink_component(path):
            raise RemediationError(f"frozen baseline input is missing: {path}")
        observed = sha256_file(path)
        if observed != expected:
            raise RemediationError(f"frozen baseline input drifted: {path}")
        bindings[path.relative_to(ROOT).as_posix()] = {
            "sha256": observed,
            "size": path.stat().st_size,
        }

    receipt = _load_json(BASELINE_RECEIPT)
    final_report = _load_json(BASELINE_FINAL_REPORT)
    disposition = _load_json(BASELINE_SOL_DISPOSITION)
    parent_ai_audit = _load_json(PARENT_CANDIDATE_3_AI_AUDIT)
    archive = inspect_baseline_archive(BASELINE_ARCHIVE)
    if (
        receipt.get("archive_member_count") != 201
        or receipt.get("payload_entry_count") != 198
        or receipt.get("archive_sha256") != EXPECTED_BASELINE_HASHES[BASELINE_ARCHIVE]
        or archive["status"] != "PASS_SAFE_REGULAR_MEMBERS"
    ):
        raise RemediationError("candidate.2 archive closure mismatch")
    if (
        final_report.get("candidate") != "candidate.2"
        or final_report.get("decision", {}).get("result") != "NO_GO"
        or final_report.get("quality", {}).get("outcome") != "BELOW_TARGET"
    ):
        raise RemediationError("candidate.2 final decision mismatch")

    findings = disposition.get("finding_dispositions")
    if not isinstance(findings, list) or len(findings) != 14:
        raise RemediationError("Sol finding register mismatch")
    if (
        parent_ai_audit.get("candidate_id") != "candidate.3"
        or parent_ai_audit.get("status") != "AI_AUDIT_REVISE"
        or parent_ai_audit.get("review_result", {}).get("open_p0_count") != 2
        or parent_ai_audit.get("review_result", {}).get("open_p1_count") != 6
    ):
        raise RemediationError("candidate.3 AI audit parent disposition mismatch")
    issue_register = [
        {
            "finding_id": item["id"],
            "severity": item["severity"],
            "parent_disposition": item["disposition"],
            "required_action": item.get("required_action"),
            "successor_state": (
                "OPEN_BLOCKING" if item["id"] in {"DG10-SOL-001", "DG10-SOL-002"} else "BOUND_PARENT_FINDING"
            ),
        }
        for item in findings
    ]
    open_blocking = [
        item["finding_id"]
        for item in issue_register
        if item["successor_state"] == "OPEN_BLOCKING"
    ]
    parent_candidate_3_blocking = parent_ai_audit["review_result"]["finding_ids"][:8]
    return {
        "schema": "milai.dg10.remediation-baseline.v1",
        "candidate_id": CANDIDATE,
        "date": DATE,
        "status": "R0_AUTHOR_CANDIDATE_BOUND_REVIEW_REQUIRED",
        "stage_id": "DG10-R0",
        "stage_state": "AUTHOR_CANDIDATE",
        "independent_acceptance": False,
        "model_run_authorized": False,
        "historical_bytes_modified": False,
        "bound_inputs": bindings,
        "archive_closure": archive,
        "parent_decision": "NO_GO_RELEASE_STOPPED",
        "parent_quality_outcome": "BELOW_TARGET",
        "issue_register": issue_register,
        "open_blocking_findings": [*open_blocking, *parent_candidate_3_blocking],
        "parent_candidate_3_review": {
            "status": "REVISE",
            "receipt_sha256": EXPECTED_BASELINE_HASHES[PARENT_CANDIDATE_3_AI_AUDIT],
            "open_p0": 2,
            "open_p1": 6,
            "blocking_findings": parent_candidate_3_blocking,
        },
        "external_provider_gate": "OE-F06_OPEN_PARKED",
        "data_boundary": "SYNTHETIC_OR_DEIDENTIFIED_ONLY",
    }


def canonical_inventory(paths: Sequence[Path]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    original_paths = tuple(paths)
    for path in original_paths:
        if has_symlink_component(path):
            raise RemediationError(f"inventory target has a symlink component: {path}")
    resolved_paths = sorted(
        {path.resolve() for path in original_paths},
        key=lambda item: item.relative_to(ROOT).as_posix(),
    )
    for path in resolved_paths:
        if not path.is_file() or path.is_symlink():
            raise RemediationError(f"inventory target is missing or unsafe: {path}")
        relative = path.relative_to(ROOT).as_posix()
        item_hash = sha256_file(path)
        entries.append({"path": relative, "sha256": item_hash, "size": path.stat().st_size})
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(item_hash.encode())
        digest.update(b"\0")
    return {
        "entry_count": len(entries),
        "canonical_entries_sha256": digest.hexdigest(),
        "entries": entries,
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _blank_usage() -> dict[str, int | None]:
    return dict.fromkeys(USAGE_KEYS)


def _validate_usage(value: Mapping[str, Any]) -> dict[str, int | None]:
    if set(value) != set(USAGE_KEYS):
        raise RemediationError("usage key set is incomplete")
    result: dict[str, int | None] = {}
    for key in USAGE_KEYS:
        item = value[key]
        if item is not None and (not isinstance(item, int) or isinstance(item, bool) or item < 0):
            raise RemediationError(f"invalid usage value: {key}")
        result[key] = item
    return result


def _entry_hash(snapshot: Mapping[str, Any]) -> str:
    without_self = {key: value for key, value in snapshot.items() if key != "entry_sha256"}
    return sha256_bytes(encoded_json(without_self))


@dataclass(slots=True)
class _Attempt:
    snapshot: dict[str, Any]


class AttemptLedger:
    """Append-only, fsync-before-parse journal for DG-10 external attempts.

    A candidate uses one ledger across its sequential runners.  ``resume=True``
    replays the complete hash chain, restores every live attempt, and then
    continues appending under an exclusive process lock.  It never truncates or
    rewrites an earlier snapshot.
    """

    def __init__(
        self,
        path: Path,
        *,
        candidate_id: str = CANDIDATE,
        authorized_model_call_slots: Sequence[str] | None = None,
        resume: bool = False,
    ) -> None:
        if not isinstance(candidate_id, str) or not candidate_id:
            raise RemediationError("attempt-ledger candidate ID is invalid")
        slots = tuple(authorized_model_call_slots or ())
        if (
            any(not isinstance(slot, str) or not slot for slot in slots)
            or len(slots) != len(set(slots))
        ):
            raise RemediationError("authorized model call slots are invalid")
        lexical_path = path.absolute()
        if has_symlink_component(lexical_path):
            raise RemediationError("attempt ledger path has a symlink component")
        self.path = lexical_path.resolve()
        self.candidate_id = candidate_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._sequence = 0
        self._previous_hash: str | None = None
        self._attempts: dict[str, _Attempt] = {}
        self._native_ids: set[str] = set()
        self._authorized_model_call_slots = frozenset(slots)
        self._consumed_model_call_slots: set[str] = set()
        flags = os.O_RDWR | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        if resume:
            flags |= 0
        else:
            flags |= os.O_CREAT | os.O_EXCL
        try:
            self._descriptor = os.open(self.path, flags, 0o600)
        except OSError as exc:
            action = "resume" if resume else "create"
            raise RemediationError(f"cannot {action} attempt ledger") from exc
        try:
            try:
                fcntl.flock(self._descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                action = "resume" if resume else "create"
                raise RemediationError(
                    f"cannot {action} attempt ledger: another writer holds the lock"
                ) from exc
            observed_mode = stat.S_IMODE(os.fstat(self._descriptor).st_mode)
            if observed_mode != 0o600:
                raise RemediationError("attempt ledger is not mode 0600")
            if resume:
                self._restore_existing(slots)
            self._stream = os.fdopen(self._descriptor, "ab", buffering=0)
        except BaseException:
            os.close(self._descriptor)
            raise

    def _restore_existing(self, slots: Sequence[str]) -> None:
        reconciliation = reconcile_attempt_ledger(
            self.path,
            candidate_id=self.candidate_id,
        )
        entries = read_attempt_ledger(self.path)
        latest: dict[str, dict[str, Any]] = {}
        for entry in entries:
            latest[str(entry["attempt_id"])] = dict(entry)
        planned_model_slots = {
            attempt_id
            for attempt_id, entry in latest.items()
            if entry["planned_model_calls"] == 1
        }
        if slots and not planned_model_slots.issubset(set(slots)):
            raise RemediationError(
                "existing model attempt is outside the authorized call slots"
            )
        self._sequence = int(reconciliation["entry_count"])
        self._previous_hash = entries[-1]["entry_sha256"] if entries else None
        self._attempts = {
            attempt_id: _Attempt(snapshot=entry)
            for attempt_id, entry in latest.items()
        }
        self._native_ids = {
            native_id
            for entry in latest.values()
            for native_id in (
                *entry["native_request_ids"],
                *entry["native_mcp_request_ids"],
            )
        }
        self._consumed_model_call_slots = planned_model_slots

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if not self._stream.closed:
            self._stream.flush()
            os.fsync(self._stream.fileno())
            fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
            self._stream.close()

    def _append(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        self._sequence += 1
        snapshot["sequence"] = self._sequence
        snapshot["previous_entry_sha256"] = self._previous_hash
        snapshot["entry_sha256"] = _entry_hash(snapshot)
        raw = encoded_json(snapshot)
        self._stream.write(raw)
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._previous_hash = snapshot["entry_sha256"]
        return dict(snapshot)

    def start_attempt(
        self,
        *,
        phase: str,
        case_id: str,
        planned_model_calls: int,
        planned_mcp_calls: int,
        arm: str | None = None,
        parent_attempt_id: str | None = None,
        attempt_id: str | None = None,
    ) -> str:
        if (
            not isinstance(planned_model_calls, int)
            or isinstance(planned_model_calls, bool)
            or not isinstance(planned_mcp_calls, int)
            or isinstance(planned_mcp_calls, bool)
            or planned_model_calls not in (0, 1)
            or planned_mcp_calls not in (0, 1)
        ):
            raise RemediationError("each attempt permits at most one model and one MCP call")
        if not isinstance(phase, str) or not phase:
            raise RemediationError("attempt phase is invalid")
        if not isinstance(case_id, str) or not case_id:
            raise RemediationError("attempt case ID is invalid")
        if arm is not None and (not isinstance(arm, str) or not arm):
            raise RemediationError("attempt arm is invalid")
        if parent_attempt_id is not None and (
            not isinstance(parent_attempt_id, str) or not parent_attempt_id
        ):
            raise RemediationError("parent attempt ID is invalid")
        if attempt_id is not None and (
            not isinstance(attempt_id, str) or not attempt_id
        ):
            raise RemediationError("attempt ID is invalid")
        if parent_attempt_id is not None and parent_attempt_id not in self._attempts:
            raise RemediationError("parent attempt is unknown")
        if self._authorized_model_call_slots and planned_model_calls == 1:
            if attempt_id is None or attempt_id not in self._authorized_model_call_slots:
                raise RemediationError("model attempt does not consume an authorized call slot")
            if attempt_id in self._consumed_model_call_slots:
                raise RemediationError("authorized model call slot was already consumed")
        identifier = attempt_id or f"dg10-{uuid4()}"
        if identifier in self._attempts:
            raise RemediationError("attempt ID is not unique")
        snapshot: dict[str, Any] = {
            "schema": "milai.dg10.attempt-ledger.snapshot.v1",
            "sequence": 0,
            "previous_entry_sha256": None,
            "entry_sha256": "",
            "attempt_id": identifier,
            "parent_attempt_id": parent_attempt_id,
            "candidate_id": self.candidate_id,
            "phase": phase,
            "arm": arm,
            "case_id": case_id,
            "attempt_state": "PLANNED",
            "planned_model_calls": planned_model_calls,
            "planned_mcp_calls": planned_mcp_calls,
            "native_request_ids": [],
            "native_mcp_request_ids": [],
            "usage": _blank_usage(),
            "provider_terminal": None,
            "mcp_terminal": None,
            "agent_terminal": None,
            "parser_terminal": None,
            "started_at": _utc_now(),
            "provider_claimed_at": None,
            "native_completed_at": None,
            "mcp_completed_at": None,
            "finished_at": None,
            "retention_state": "partial",
            "failure_reason_code": "PROVIDER_TERMINAL_MISSING",
            "external_billed_cost": "UNAVAILABLE",
            "self_hosted_compute_cost": "UNAVAILABLE_NOT_ZERO",
            "raw_sidecar_digest": None,
            "provider_claim_digest": None,
            "raw_mcp_sidecar_digest": None,
            "redacted_public_receipt_digest": None,
        }
        self._attempts[identifier] = _Attempt(snapshot=snapshot)
        self._append(snapshot)
        if self._authorized_model_call_slots and planned_model_calls == 1:
            self._consumed_model_call_slots.add(identifier)
        return identifier

    def record_provider_claimed(
        self, attempt_id: str, *, provider_claim_digest: str
    ) -> None:
        _require_sha256(provider_claim_digest, "provider claim digest")
        attempt = self._get(attempt_id)
        snapshot = dict(attempt.snapshot)
        if (
            snapshot["attempt_state"] != "PLANNED"
            or snapshot["planned_model_calls"] != 1
            or snapshot["provider_claim_digest"] is not None
            or snapshot["provider_claimed_at"] is not None
        ):
            raise RemediationError("provider slot cannot be claimed more than once")
        snapshot["provider_claim_digest"] = provider_claim_digest
        snapshot["provider_claimed_at"] = _utc_now()
        snapshot["attempt_state"] = "PROVIDER_CLAIMED"
        attempt.snapshot = snapshot
        self._append(snapshot)

    def record_provider_accepted(
        self,
        attempt_id: str,
        native_request_id: str,
        *,
        raw_sidecar_digest: str | None = None,
    ) -> None:
        if not isinstance(native_request_id, str) or not native_request_id:
            raise RemediationError("native request ID is invalid")
        if raw_sidecar_digest is not None:
            _require_sha256(raw_sidecar_digest, "raw sidecar digest")
        attempt = self._get(attempt_id)
        snapshot = dict(attempt.snapshot)
        if (
            snapshot["phase"] == "T2_CONTROL_PATH_SMOKE"
            and snapshot["attempt_state"] != "PROVIDER_CLAIMED"
        ):
            raise RemediationError(
                "T2 provider acceptance requires a durable pre-I/O slot claim"
            )
        if (
            snapshot["phase"] == "T2_CONTROL_PATH_SMOKE"
            and raw_sidecar_digest is None
        ):
            raise RemediationError(
                "T2 provider acceptance requires a retained raw sidecar"
            )
        if snapshot["attempt_state"] not in {
            "PLANNED",
            "PROVIDER_CLAIMED",
            "PROVIDER_ACCEPTED",
        }:
            raise RemediationError("provider acceptance is out of order")
        if native_request_id in self._native_ids:
            raise RemediationError("native request ID is not unique")
        native_ids = list(snapshot["native_request_ids"])
        if len(native_ids) >= snapshot["planned_model_calls"]:
            raise RemediationError("native model call exceeds the plan")
        native_ids.append(native_request_id)
        self._native_ids.add(native_request_id)
        snapshot["native_request_ids"] = native_ids
        if raw_sidecar_digest is not None:
            snapshot["raw_sidecar_digest"] = raw_sidecar_digest
        snapshot["attempt_state"] = "PROVIDER_ACCEPTED"
        attempt.snapshot = snapshot
        self._append(snapshot)

    def record_mcp_accepted(self, attempt_id: str, native_request_id: str) -> None:
        if not isinstance(native_request_id, str) or not native_request_id:
            raise RemediationError("native MCP request ID is invalid")
        attempt = self._get(attempt_id)
        snapshot = dict(attempt.snapshot)
        if snapshot["attempt_state"] == "FINALIZED":
            raise RemediationError("MCP acceptance cannot mutate a finalized attempt")
        native_ids = list(snapshot["native_mcp_request_ids"])
        if native_request_id in self._native_ids:
            raise RemediationError("native request ID is not unique")
        if len(native_ids) >= snapshot["planned_mcp_calls"]:
            raise RemediationError("native MCP call exceeds the plan")
        native_ids.append(native_request_id)
        self._native_ids.add(native_request_id)
        snapshot["native_mcp_request_ids"] = native_ids
        attempt.snapshot = snapshot
        self._append(snapshot)

    def record_provider_terminal(
        self,
        attempt_id: str,
        *,
        usage: Mapping[str, Any],
        raw_sidecar_digest: str,
    ) -> None:
        attempt = self._get(attempt_id)
        snapshot = dict(attempt.snapshot)
        if (
            snapshot["attempt_state"] != "PROVIDER_ACCEPTED"
            or snapshot["planned_model_calls"] != 1
            or len(snapshot["native_request_ids"]) != 1
            or snapshot["provider_terminal"] is True
        ):
            raise RemediationError("provider terminal requires a journaled native ID")
        _require_sha256(raw_sidecar_digest, "raw sidecar digest")
        if (
            snapshot["raw_sidecar_digest"] is not None
            and snapshot["raw_sidecar_digest"] != raw_sidecar_digest
        ):
            raise RemediationError("retained raw sidecar digest drifted before terminal")
        snapshot["usage"] = _validate_usage(usage)
        snapshot["provider_terminal"] = True
        snapshot["native_completed_at"] = _utc_now()
        snapshot["raw_sidecar_digest"] = raw_sidecar_digest
        snapshot["attempt_state"] = "PROVIDER_TERMINAL"
        attempt.snapshot = snapshot
        self._append(snapshot)

    def record_mcp_terminal(
        self,
        attempt_id: str,
        *,
        raw_sidecar_digest: str,
    ) -> None:
        attempt = self._get(attempt_id)
        snapshot = dict(attempt.snapshot)
        if (
            snapshot["attempt_state"] == "FINALIZED"
            or
            snapshot["planned_mcp_calls"] <= 0
            or len(snapshot["native_mcp_request_ids"]) != snapshot["planned_mcp_calls"]
            or snapshot["mcp_terminal"] is True
        ):
            raise RemediationError("MCP terminal requires all planned journaled MCP IDs")
        _require_sha256(raw_sidecar_digest, "raw MCP sidecar digest")
        snapshot["mcp_terminal"] = True
        snapshot["mcp_completed_at"] = _utc_now()
        snapshot["raw_mcp_sidecar_digest"] = raw_sidecar_digest
        attempt.snapshot = snapshot
        self._append(snapshot)

    def finalize(
        self,
        attempt_id: str,
        *,
        agent_terminal: bool,
        parser_terminal: bool,
        retention_state: str,
        failure_reason_code: str,
        redacted_public_receipt_digest: str,
        external_billed_cost: float | str = "UNAVAILABLE",
    ) -> None:
        attempt = self._get(attempt_id)
        if not isinstance(agent_terminal, bool) or not isinstance(parser_terminal, bool):
            raise RemediationError("attempt terminal flags must be boolean")
        if retention_state not in RETENTION_STATES:
            raise RemediationError("unknown retention state")
        if failure_reason_code not in STABLE_REASON_CODES:
            raise RemediationError("unknown terminal reason")
        _require_sha256(redacted_public_receipt_digest, "public receipt digest")
        if not (
            external_billed_cost == "UNAVAILABLE"
            or (
                isinstance(external_billed_cost, (int, float))
                and not isinstance(external_billed_cost, bool)
                and external_billed_cost >= 0
            )
        ):
            raise RemediationError("external billed cost is invalid")
        snapshot = dict(attempt.snapshot)
        if snapshot["attempt_state"] == "FINALIZED":
            raise RemediationError("attempt already finalized")
        if failure_reason_code == "SUCCESS" and (
            (
                snapshot["planned_model_calls"] > 0
                and snapshot["provider_terminal"] is not True
            )
            or (
                snapshot["planned_mcp_calls"] > 0
                and snapshot["mcp_terminal"] is not True
            )
            or not agent_terminal
            or not parser_terminal
            or retention_state != "retained"
            or len(snapshot["native_request_ids"]) != snapshot["planned_model_calls"]
            or len(snapshot["native_mcp_request_ids"]) != snapshot["planned_mcp_calls"]
        ):
            raise RemediationError("SUCCESS terminal invariants are not satisfied")
        if snapshot["provider_terminal"] is True and any(
            snapshot["usage"][key] is None for key in USAGE_KEYS
        ):
            raise RemediationError("completed provider usage is incomplete")
        snapshot["agent_terminal"] = agent_terminal
        snapshot["parser_terminal"] = parser_terminal
        snapshot["retention_state"] = retention_state
        snapshot["failure_reason_code"] = failure_reason_code
        snapshot["external_billed_cost"] = external_billed_cost
        snapshot["redacted_public_receipt_digest"] = redacted_public_receipt_digest
        snapshot["finished_at"] = _utc_now()
        snapshot["attempt_state"] = "FINALIZED"
        attempt.snapshot = snapshot
        self._append(snapshot)

    def _get(self, attempt_id: str) -> _Attempt:
        try:
            return self._attempts[attempt_id]
        except KeyError as exc:
            raise RemediationError("attempt ID is unknown") from exc


def _require_sha256(value: object, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != SHA256_PATTERN_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RemediationError(f"{label} is not a lowercase SHA-256")


def _ledger_datetime(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise RemediationError(f"ledger timestamp field is invalid: {label}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RemediationError(f"ledger timestamp field is invalid: {label}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RemediationError(f"ledger timestamp lacks timezone: {label}")
    return parsed


def read_attempt_ledger(path: Path) -> list[dict[str, Any]]:
    if (
        has_symlink_component(path)
        or not path.is_file()
        or stat.S_IMODE(path.stat().st_mode) & 0o077
    ):
        raise RemediationError("attempt ledger is missing or not mode 0600")
    entries: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_bytes().splitlines(), start=1):
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RemediationError(f"invalid ledger JSON at line {line_number}") from exc
        if not isinstance(item, dict):
            raise RemediationError("ledger entry is not an object")
        entries.append(item)
    return entries


def _validate_attempt_snapshot(entry: Mapping[str, Any]) -> None:
    if set(entry) != ATTEMPT_SNAPSHOT_KEYS:
        raise RemediationError("ledger snapshot key set drift")
    if entry.get("schema") != "milai.dg10.attempt-ledger.snapshot.v1":
        raise RemediationError("ledger snapshot schema drift")
    for key in ("sequence", "planned_model_calls", "planned_mcp_calls"):
        value = entry.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise RemediationError(f"ledger integer field is invalid: {key}")
    if entry["planned_model_calls"] not in {0, 1} or entry["planned_mcp_calls"] not in {0, 1}:
        raise RemediationError("ledger attempt contains a multi-call plan")
    for key in ("attempt_id", "candidate_id", "phase", "case_id"):
        if not isinstance(entry.get(key), str) or not entry[key]:
            raise RemediationError(f"ledger string field is invalid: {key}")
    for key in ("parent_attempt_id", "arm"):
        if entry.get(key) is not None and not isinstance(entry[key], str):
            raise RemediationError(f"ledger nullable string field is invalid: {key}")
    for key, planned_key in (
        ("native_request_ids", "planned_model_calls"),
        ("native_mcp_request_ids", "planned_mcp_calls"),
    ):
        values = entry.get(key)
        if (
            not isinstance(values, list)
            or any(not isinstance(value, str) or not value for value in values)
            or len(values) != len(set(values))
            or len(values) > entry[planned_key]
        ):
            raise RemediationError(f"ledger native ID field is invalid: {key}")
    usage = entry.get("usage")
    if not isinstance(usage, Mapping):
        raise RemediationError("ledger usage is not an object")
    _validate_usage(usage)
    for key in ("provider_terminal", "mcp_terminal"):
        if entry.get(key) is not None and entry.get(key) is not True:
            raise RemediationError(f"ledger external terminal field is invalid: {key}")
    for key in ("agent_terminal", "parser_terminal"):
        if entry.get(key) is not None and not isinstance(entry.get(key), bool):
            raise RemediationError(f"ledger local terminal field is invalid: {key}")
    started_at = _ledger_datetime(entry.get("started_at"), "started_at")
    parsed_times: dict[str, datetime | None] = {}
    for key in (
        "provider_claimed_at",
        "native_completed_at",
        "mcp_completed_at",
        "finished_at",
    ):
        value = entry.get(key)
        parsed_times[key] = None if value is None else _ledger_datetime(value, key)
        if parsed_times[key] is not None and parsed_times[key] < started_at:
            raise RemediationError(f"ledger timestamp predates attempt: {key}")
    if entry.get("retention_state") not in RETENTION_STATES:
        raise RemediationError("ledger retention state is invalid")
    if entry.get("failure_reason_code") not in STABLE_REASON_CODES:
        raise RemediationError("ledger failure reason is invalid")
    cost = entry.get("external_billed_cost")
    if not (
        cost == "UNAVAILABLE"
        or (
            isinstance(cost, (int, float))
            and not isinstance(cost, bool)
            and cost >= 0
        )
    ):
        raise RemediationError("ledger external billed cost is invalid")
    if entry.get("self_hosted_compute_cost") not in {"UNAVAILABLE_NOT_ZERO", "MEASURED"}:
        raise RemediationError("ledger self-hosted compute cost is invalid")
    for key in (
        "provider_claim_digest",
        "raw_sidecar_digest",
        "raw_mcp_sidecar_digest",
        "redacted_public_receipt_digest",
    ):
        if entry.get(key) is not None:
            _require_sha256(entry[key], key)
    if (entry["provider_claim_digest"] is None) != (
        entry["provider_claimed_at"] is None
    ):
        raise RemediationError("ledger provider claim fields are not atomic")
    if (
        entry["provider_claim_digest"] is not None
        and entry["planned_model_calls"] != 1
    ):
        raise RemediationError("ledger provider claim lacks one planned model call")
    if (
        entry["phase"] == "T2_CONTROL_PATH_SMOKE"
        and entry["native_request_ids"]
        and entry["provider_claim_digest"] is None
    ):
        raise RemediationError("T2 native acceptance lacks a durable pre-I/O claim")
    if entry["provider_terminal"] is True:
        if (
            entry["planned_model_calls"] != 1
            or len(entry["native_request_ids"]) != 1
            or entry["native_completed_at"] is None
            or entry["raw_sidecar_digest"] is None
            or any(entry["usage"][key] is None for key in USAGE_KEYS)
        ):
            raise RemediationError("ledger provider terminal invariants failed")
    elif entry["native_completed_at"] is not None:
        raise RemediationError("ledger provider completion timestamp lacks a terminal")
    elif entry["raw_sidecar_digest"] is not None and not (
        entry["phase"] == "T2_CONTROL_PATH_SMOKE"
        and len(entry["native_request_ids"]) == 1
    ):
        raise RemediationError("ledger raw sidecar lacks a T2 native acceptance")
    if entry["mcp_terminal"] is True:
        if (
            entry["planned_mcp_calls"] != 1
            or len(entry["native_mcp_request_ids"]) != 1
            or entry["mcp_completed_at"] is None
            or entry["raw_mcp_sidecar_digest"] is None
        ):
            raise RemediationError("ledger MCP terminal invariants failed")
    elif entry["mcp_completed_at"] is not None or entry["raw_mcp_sidecar_digest"] is not None:
        raise RemediationError("ledger MCP terminal side effects lack a terminal")
    finalized = entry.get("attempt_state") == "FINALIZED"
    if finalized:
        if (
            entry["finished_at"] is None
            or not isinstance(entry["agent_terminal"], bool)
            or not isinstance(entry["parser_terminal"], bool)
            or entry["redacted_public_receipt_digest"] is None
        ):
            raise RemediationError("ledger finalized invariants failed")
    elif any(
        entry[key] is not None
        for key in ("agent_terminal", "parser_terminal", "finished_at", "redacted_public_receipt_digest")
    ):
        raise RemediationError("ledger non-final snapshot contains final fields")
    if finalized and any(
        timestamp is not None and parsed_times["finished_at"] < timestamp
        for timestamp in (
            parsed_times["provider_claimed_at"],
            parsed_times["native_completed_at"],
            parsed_times["mcp_completed_at"],
        )
    ):
        raise RemediationError("ledger completion timestamp follows finalization")
    state = entry.get("attempt_state")
    if state == "PLANNED" and (
        entry["native_request_ids"]
        or entry["provider_claim_digest"] is not None
        or entry["provider_claimed_at"] is not None
        or entry["provider_terminal"] is not None
        or entry["native_completed_at"] is not None
        or entry["raw_sidecar_digest"] is not None
    ):
        raise RemediationError("ledger PLANNED model-call invariants failed")
    if state == "PROVIDER_CLAIMED" and (
        entry["planned_model_calls"] != 1
        or entry["native_request_ids"]
        or entry["provider_claim_digest"] is None
        or entry["provider_claimed_at"] is None
        or entry["provider_terminal"] is not None
        or entry["raw_sidecar_digest"] is not None
    ):
        raise RemediationError("ledger PROVIDER_CLAIMED invariants failed")
    if state == "PROVIDER_ACCEPTED" and (
        entry["planned_model_calls"] != 1
        or len(entry["native_request_ids"]) != 1
        or (
            entry["phase"] == "T2_CONTROL_PATH_SMOKE"
            and (
                entry["provider_claim_digest"] is None
                or entry["raw_sidecar_digest"] is None
            )
        )
        or entry["provider_terminal"] is not None
    ):
        raise RemediationError("ledger PROVIDER_ACCEPTED invariants failed")
    if state == "PROVIDER_TERMINAL" and entry["provider_terminal"] is not True:
        raise RemediationError("ledger PROVIDER_TERMINAL invariants failed")
    if not finalized and (
        entry["retention_state"] != "partial"
        or entry["failure_reason_code"] != "PROVIDER_TERMINAL_MISSING"
    ):
        raise RemediationError("ledger non-final disposition drift")
    if entry.get("failure_reason_code") == "SUCCESS" and (
        not finalized
        or entry.get("retention_state") != "retained"
        or entry.get("agent_terminal") is not True
        or entry.get("parser_terminal") is not True
        or len(entry["native_request_ids"]) != entry["planned_model_calls"]
        or len(entry["native_mcp_request_ids"]) != entry["planned_mcp_calls"]
        or (entry["planned_model_calls"] == 1 and entry["provider_terminal"] is not True)
        or (entry["planned_mcp_calls"] == 1 and entry["mcp_terminal"] is not True)
    ):
        raise RemediationError("ledger SUCCESS invariants failed")


def reconcile_attempt_ledger(
    path: Path,
    *,
    candidate_id: str = CANDIDATE,
    expected_model_call_slots: Sequence[str] | None = None,
) -> dict[str, Any]:
    entries = read_attempt_ledger(path)
    previous_hash: str | None = None
    last_state: dict[str, dict[str, Any]] = {}
    native_ids: set[str] = set()
    for expected_sequence, entry in enumerate(entries, start=1):
        _validate_attempt_snapshot(entry)
        if entry.get("sequence") != expected_sequence:
            raise RemediationError("ledger sequence is not contiguous")
        if entry.get("previous_entry_sha256") != previous_hash:
            raise RemediationError("ledger hash chain is broken")
        _require_sha256(entry.get("entry_sha256"), "ledger entry digest")
        if _entry_hash(entry) != entry["entry_sha256"]:
            raise RemediationError("ledger entry digest mismatch")
        if entry.get("candidate_id") != candidate_id:
            raise RemediationError("ledger contains a cross-candidate entry")
        attempt_id = entry.get("attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id:
            raise RemediationError("ledger attempt ID is invalid")
        state = entry.get("attempt_state")
        if state not in ATTEMPT_STATES:
            raise RemediationError("ledger attempt state is invalid")
        previous = last_state.get(attempt_id)
        if previous is None and state != "PLANNED":
            raise RemediationError("attempt does not begin with PLANNED")
        if previous is not None:
            if previous["attempt_state"] == "FINALIZED":
                raise RemediationError("finalized attempt was mutated")
            for key in ATTEMPT_IMMUTABLE_KEYS:
                if entry.get(key) != previous.get(key):
                    raise RemediationError(f"ledger immutable field was rewritten: {key}")
            if ATTEMPT_STATES.index(state) < ATTEMPT_STATES.index(previous["attempt_state"]):
                raise RemediationError("attempt state regressed")
            old_model_ids = previous["native_request_ids"]
            old_mcp_ids = previous["native_mcp_request_ids"]
            if entry.get("native_request_ids", [])[: len(old_model_ids)] != old_model_ids:
                raise RemediationError("native model ID journal was rewritten")
            if entry.get("native_mcp_request_ids", [])[: len(old_mcp_ids)] != old_mcp_ids:
                raise RemediationError("native MCP ID journal was rewritten")
            for key in (
                "provider_claim_digest",
                "provider_claimed_at",
                "provider_terminal",
                "mcp_terminal",
                "native_completed_at",
                "mcp_completed_at",
                "raw_sidecar_digest",
                "raw_mcp_sidecar_digest",
            ):
                if previous.get(key) is not None and entry.get(key) != previous.get(key):
                    raise RemediationError(f"ledger terminal field was rewritten: {key}")
        for native_id in [
            *entry.get("native_request_ids", []),
            *entry.get("native_mcp_request_ids", []),
        ]:
            if previous is None or native_id not in (
                previous.get("native_request_ids", [])
                + previous.get("native_mcp_request_ids", [])
            ):
                if native_id in native_ids:
                    raise RemediationError("native ID is duplicated across attempts")
                native_ids.add(native_id)
        if len(entry.get("native_request_ids", [])) > entry.get("planned_model_calls", -1):
            raise RemediationError("hidden or extra model call detected")
        if len(entry.get("native_mcp_request_ids", [])) > entry.get("planned_mcp_calls", -1):
            raise RemediationError("hidden or extra MCP call detected")
        last_state[attempt_id] = entry
        previous_hash = entry["entry_sha256"]

    finalized = [entry for entry in last_state.values() if entry["attempt_state"] == "FINALIZED"]
    retained_successful = sum(
        len(entry["native_request_ids"])
        for entry in finalized
        if entry["failure_reason_code"] == "SUCCESS"
        and entry["retention_state"] == "retained"
    )
    known_completed = sum(
        len(entry["native_request_ids"])
        for entry in last_state.values()
        if entry["provider_terminal"] is True
    )
    claimed_model_calls = sum(
        entry.get("provider_claim_digest") is not None
        for entry in last_state.values()
    )
    retained_successful_mcp = sum(
        len(entry["native_mcp_request_ids"])
        for entry in finalized
        if entry["failure_reason_code"] == "SUCCESS"
        and entry["retention_state"] == "retained"
    )
    known_completed_mcp = sum(
        len(entry["native_mcp_request_ids"])
        for entry in last_state.values()
        if entry.get("mcp_terminal") is True
    )
    known_failed = sum(
        len(entry["native_request_ids"]) + len(entry["native_mcp_request_ids"])
        for entry in finalized
        if entry["failure_reason_code"] != "SUCCESS"
        and (entry["provider_terminal"] is True or entry["mcp_terminal"] is True)
    )
    unfinalized_attempts = sum(
        entry["attempt_state"] != "FINALIZED" for entry in last_state.values()
    )
    missing_native_ids = sum(
        entry["planned_model_calls"]
        - len(entry["native_request_ids"])
        + entry["planned_mcp_calls"]
        - len(entry["native_mcp_request_ids"])
        for entry in last_state.values()
    )
    missing_terminals = sum(
        (len(entry["native_request_ids"]) if entry["provider_terminal"] is not True else 0)
        + (len(entry["native_mcp_request_ids"]) if entry["mcp_terminal"] is not True else 0)
        for entry in last_state.values()
    )
    unknown = missing_native_ids + missing_terminals
    planned_model_attempt_ids = {
        attempt_id
        for attempt_id, entry in last_state.items()
        if entry["planned_model_calls"] == 1
    }
    expected_slots = set(expected_model_call_slots or ())
    if len(expected_slots) != len(tuple(expected_model_call_slots or ())):
        raise RemediationError("expected model call slot manifest is duplicated")
    slot_manifest_match = not expected_slots or planned_model_attempt_ids == expected_slots
    return {
        "schema": "milai.dg10.attempt-ledger-reconciliation.v1",
        "candidate_id": candidate_id,
        "entry_count": len(entries),
        "attempt_count": len(last_state),
        "attempt_ids_unique": True,
        "native_request_ids_unique": True,
        "hash_chain_valid": True,
        "retained_successful_calls": retained_successful,
        "known_completed_calls": known_completed,
        "claimed_model_calls": claimed_model_calls,
        "retained_successful_mcp_calls": retained_successful_mcp,
        "known_completed_mcp_calls": known_completed_mcp,
        "known_failed_calls": known_failed,
        "unknown_early_diagnostics": unknown,
        "unfinalized_attempt_count": unfinalized_attempts,
        "missing_native_id_count": missing_native_ids,
        "missing_terminal_count": missing_terminals,
        "expected_model_call_slot_count": len(expected_slots),
        "consumed_model_call_slot_count": len(planned_model_attempt_ids),
        "model_call_slot_manifest_match": slot_manifest_match,
        "ledger_sha256": sha256_file(path),
        "ledger_size": path.stat().st_size,
        "mode": "0600",
        "complete": unknown == 0 and unfinalized_attempts == 0 and slot_manifest_match,
    }
