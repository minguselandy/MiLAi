#!/usr/bin/env python3
"""Run one fail-closed, read-only DG13U U1 independent review attempt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESPONSE_SCHEMA_PATH = ROOT / "contracts/agent/v1/dg13u-u1-review-response.schema.json"
PROMPT_PATH = ROOT / "contracts/agent/v1/dg13u-u1-review-prompt.md"
BUNDLE_SCHEMA = "milai.dg13u.u1-review-bundle-manifest.v1"
RELEASE_LABEL = "LOCAL_OPENWORKER_MCP_CURRENT_STATE_USABLE"
MODEL = "gpt-5.6-sol"
REASONING_EFFORT = "xhigh"
DEFAULT_TIMEOUT_SECONDS = 1800
MAX_CONTROL_FILE_BYTES = 8 * 1024 * 1024
MAX_BUNDLE_FILE_BYTES = 64 * 1024 * 1024
MAX_MODEL_OUTPUT_BYTES = 2 * 1024 * 1024
GATE_NAMES = tuple(f"U1-G{index}" for index in range(6))
REQUIRED_CASE_IDS = (
    "U1-NONE-EN",
    "U1-NONE-CN",
    "U1-EXACT-TARGET-EN",
    "U1-EXACT-TARGET-CN",
    "U1-EXACT-DATABASE-EN",
    "U1-EXACT-DATABASE-CN",
    "U1-EXACT-DECISION-EN",
    "U1-EXACT-DECISION-CN",
    "U1-CACHE-FALLBACK",
    "U1-WRONG-TASK",
    "U1-WRONG-SCOPE",
    "U1-STALE-CURRENT",
    "U1-REVOKE-REENTRY",
    "U1-AUTHORITY-ESCALATION",
    "U1-RUNTIME-UNAVAILABLE",
    "U1-ALIAS-COLLISION",
    "U1-OPEN-ISSUE",
    "U1-BROKER-DOWN",
    "U1-BROKER-MALFORMED",
    "U1-BROKER-TIMEOUT",
    "U1-PROVIDER-DOWN",
    "U1-PROVIDER-MALFORMED",
    "U1-PROVIDER-TIMEOUT",
    "U1-BROKER-INODE-RECREATE",
    "U1-ADAPTER-RESTART",
    "U1-STREAM",
    "U1-ORDINARY-SYNC-TOOL",
    "U1-TASK-CONTINUE",
    "U1-TASK-SWITCH",
    "U1-TASK-RETURN",
    "U1-TASK-CONCURRENT",
    "U1-RUNTIME-DOWN",
    "U1-RUNTIME-MALFORMED",
    "U1-RUNTIME-TIMEOUT",
    "U1-MCP-CHILD-DOWN",
    "U1-MCP-CHILD-MALFORMED",
    "U1-MCP-CHILD-TIMEOUT",
)
REQUIRED_RUN_ARTIFACTS_PER_CASE = 8
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ATTEMPT_ID = re.compile(r"^dg13u-u1-review-[a-z0-9][a-z0-9._-]{0,95}$")
_FINDING_ID = re.compile(r"^DG13U-U1-RV-[0-9]{3}$")
_RESPONSE_KEYS = {
    "schema",
    "review_scope",
    "verdict",
    "summary",
    "open_findings",
    "missing_evidence",
    "reviewed_manifest_sha256",
}
_FINDING_KEYS = {
    "finding_id",
    "severity",
    "title",
    "evidence",
    "required_action",
}
_MANIFEST_KEYS = {
    "schema",
    "status",
    "release_label",
    "release_label_earned",
    "input_mode",
    "network_calls",
    "resource_starts",
    "reruns",
    "gates",
    "aggregate_sha256",
    "counts",
    "entries_sha256",
    "files",
    "secret_scan",
}
_MANIFEST_FILE_KEYS = {
    "bytes",
    "case_id",
    "path",
    "run_id",
    "schema",
    "sha256",
    "source_kind",
}
_ENVIRONMENT_ALLOWLIST = {
    "CODEX_API_KEY",
    "CODEX_HOME",
    "HOME",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "OPENAI_API_KEY",
    "PATH",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
}


class ReviewRunError(RuntimeError):
    """The independent review boundary could not be established."""


@dataclass(frozen=True, slots=True)
class BundleSnapshot:
    root: Path
    manifest_sha256: str
    closure_sha256: str
    file_count: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    returncode: int
    termination_reason: str
    stdout: bytes
    stderr: bytes
    child_pid: int
    proc_exe_sha256: str | None
    proc_cmdline_sha256: str | None


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest_object(value: object) -> str:
    return _digest(_canonical(value))


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ReviewRunError(reason)


def _absolute(path: str | Path, label: str) -> Path:
    candidate = Path(path)
    _require(candidate.is_absolute(), f"{label} must be an explicit absolute path")
    return Path(os.path.normpath(os.fspath(candidate)))


def _reject_symlink_chain(path: Path, label: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            break
        _require(not stat.S_ISLNK(metadata.st_mode), f"{label} symlink is forbidden")


def _read_regular(path: Path, label: str, maximum: int) -> bytes:
    _reject_symlink_chain(path, label)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ReviewRunError(f"{label} is absent or unsafe") from exc
    try:
        before = path.lstat()
        opened = os.fstat(descriptor)
        _require(
            stat.S_ISREG(opened.st_mode)
            and not stat.S_ISLNK(before.st_mode)
            and (before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino),
            f"{label} is not a stable regular file",
        )
        _require(opened.st_size <= maximum, f"{label} exceeds the byte bound")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            block = os.read(descriptor, min(1024 * 1024, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        raw = b"".join(chunks)
        _require(len(raw) <= maximum, f"{label} exceeds the byte bound")
        after = os.fstat(descriptor)
        _require(
            (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
            f"{label} changed while being read",
        )
        return raw
    finally:
        os.close(descriptor)


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewRunError(f"{label} is not a JSON object") from exc
    _require(isinstance(value, dict), f"{label} is not a JSON object")
    return value


def _bundle_relative(value: object) -> PurePosixPath:
    _require(isinstance(value, str) and bool(value), "bundle manifest path is invalid")
    relative = PurePosixPath(value)
    _require(
        not relative.is_absolute()
        and all(part not in {"", ".", ".."} for part in relative.parts),
        "bundle manifest path escapes its root",
    )
    return relative


def _validate_bundle(
    bundle: str | Path, expected_manifest_sha256: str
) -> BundleSnapshot:
    root = _absolute(bundle, "bundle")
    _reject_symlink_chain(root, "bundle")
    _require(
        root.is_dir() and not root.is_symlink(),
        "bundle must be a real directory",
    )
    _require(
        stat.S_IMODE(root.stat().st_mode) & 0o022 == 0,
        "bundle root must not be group/world writable",
    )
    _require(
        isinstance(expected_manifest_sha256, str)
        and _SHA256.fullmatch(expected_manifest_sha256) is not None,
        "expected manifest SHA-256 is invalid",
    )
    manifest_path = root / "manifest.json"
    manifest_raw = _read_regular(
        manifest_path, "bundle manifest", MAX_CONTROL_FILE_BYTES
    )
    manifest_sha256 = _digest(manifest_raw)
    _require(
        manifest_sha256 == expected_manifest_sha256,
        "bundle manifest SHA-256 binding mismatch",
    )
    manifest = _json_object(manifest_raw, "bundle manifest")
    _require(set(manifest) == _MANIFEST_KEYS, "bundle manifest key set drift")
    _require(
        manifest.get("schema") == BUNDLE_SCHEMA
        and manifest.get("status") == "PASS"
        and manifest.get("release_label") == RELEASE_LABEL
        and manifest.get("release_label_earned") is True
        and manifest.get("input_mode") == "EXPLICIT_PATHS_ONLY_NO_DISCOVERY"
        and manifest.get("network_calls") == 0
        and manifest.get("resource_starts") == 0
        and manifest.get("reruns") == 0,
        "bundle manifest has not established a reviewable release input",
    )
    gates = manifest.get("gates")
    _require(
        isinstance(gates, Mapping)
        and set(gates) == set(GATE_NAMES)
        and all(gates[name] == "PASS" for name in GATE_NAMES),
        "bundle manifest gate closure is incomplete",
    )
    secret_scan = manifest.get("secret_scan")
    _require(
        isinstance(secret_scan, Mapping)
        and secret_scan.get("status") == "PASS"
        and secret_scan.get("raw_secret_persisted") is False,
        "bundle secret scan is not PASS",
    )
    rows = manifest.get("files")
    _require(
        isinstance(rows, list) and bool(rows), "bundle manifest file index is absent"
    )
    _require(
        isinstance(manifest.get("entries_sha256"), str)
        and _SHA256.fullmatch(manifest["entries_sha256"]) is not None
        and manifest["entries_sha256"] == _digest(_canonical(rows)),
        "bundle manifest entries SHA-256 binding mismatch",
    )
    expected_files: set[str] = {"manifest.json"}
    closure: list[dict[str, object]] = [
        {
            "path": "manifest.json",
            "bytes": len(manifest_raw),
            "sha256": manifest_sha256,
        }
    ]
    total_bytes = len(manifest_raw)
    source_kind_counts = {
        "AGGREGATE": 0,
        "RUN_REPORT": 0,
        "RUN_ARTIFACT": 0,
        "SUPPLEMENTAL": 0,
    }
    report_identities: set[tuple[str, str]] = set()
    run_artifact_counts = {case_id: 0 for case_id in REQUIRED_CASE_IDS}
    aggregate_file_sha256: str | None = None
    for row in rows:
        _require(
            isinstance(row, Mapping) and set(row) == _MANIFEST_FILE_KEYS,
            "bundle manifest file binding is malformed",
        )
        relative = _bundle_relative(row.get("path"))
        logical = relative.as_posix()
        _require(logical not in expected_files, "bundle manifest path is duplicated")
        expected_files.add(logical)
        expected_bytes = row.get("bytes")
        expected_sha256 = row.get("sha256")
        source_kind = row.get("source_kind")
        _require(
            isinstance(expected_bytes, int)
            and not isinstance(expected_bytes, bool)
            and 0 <= expected_bytes <= MAX_BUNDLE_FILE_BYTES
            and isinstance(expected_sha256, str)
            and _SHA256.fullmatch(expected_sha256) is not None,
            "bundle manifest file identity is invalid",
        )
        _require(
            isinstance(source_kind, str) and source_kind in source_kind_counts,
            "bundle manifest source kind is invalid",
        )
        source_kind_counts[source_kind] += 1
        case_id = row.get("case_id")
        run_id = row.get("run_id")
        if source_kind == "AGGREGATE":
            _require(
                logical == "aggregate/aggregate.json"
                and case_id is None
                and run_id is None,
                "bundle aggregate binding is invalid",
            )
            aggregate_file_sha256 = expected_sha256
        elif source_kind == "RUN_REPORT":
            _require(
                isinstance(case_id, str)
                and case_id in REQUIRED_CASE_IDS
                and isinstance(run_id, str)
                and bool(run_id)
                and logical == f"reports/{case_id}--{run_id}.json",
                "bundle report identity is invalid",
            )
            identity = (case_id, run_id)
            _require(
                identity not in report_identities,
                "bundle report identity is duplicated",
            )
            report_identities.add(identity)
        elif source_kind == "RUN_ARTIFACT":
            _require(
                isinstance(case_id, str)
                and case_id in REQUIRED_CASE_IDS
                and isinstance(run_id, str)
                and bool(run_id)
                and logical.startswith(f"runs/{case_id}--{run_id}/"),
                "bundle run artifact identity is invalid",
            )
            run_artifact_counts[case_id] += 1
        else:
            _require(
                case_id is None
                and run_id is None
                and logical.startswith("supplemental/"),
                "bundle supplemental identity is invalid",
            )
        source = root.joinpath(*relative.parts)
        raw = _read_regular(source, f"bundle file {logical}", MAX_BUNDLE_FILE_BYTES)
        _require(
            len(raw) == expected_bytes and _digest(raw) == expected_sha256,
            "bundle file identity binding mismatch",
        )
        _require(
            stat.S_IMODE(source.stat().st_mode) & 0o022 == 0,
            "bundle file must not be group/world writable",
        )
        closure.append({"path": logical, "bytes": len(raw), "sha256": expected_sha256})
        total_bytes += len(raw)
    actual_files: set[str] = set()
    for item in root.rglob("*"):
        _require(not item.is_symlink(), "bundle contains a symlink")
        if item.is_dir():
            _require(
                stat.S_IMODE(item.stat().st_mode) & 0o022 == 0,
                "bundle directory must not be group/world writable",
            )
        elif item.is_file():
            actual_files.add(item.relative_to(root).as_posix())
        else:
            raise ReviewRunError("bundle contains a non-file filesystem object")
    _require(actual_files == expected_files, "bundle file closure drift")
    counts = manifest.get("counts")
    _require(
        isinstance(counts, Mapping)
        and set(counts)
        == {"aggregate", "reports", "run_artifacts", "supplemental_artifacts"}
        and all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in counts.values()
        )
        and sum(counts.values()) == len(rows),
        "bundle manifest count binding mismatch",
    )
    _require(
        source_kind_counts["AGGREGATE"] == counts["aggregate"] == 1
        and source_kind_counts["RUN_REPORT"]
        == counts["reports"]
        == len(REQUIRED_CASE_IDS)
        and source_kind_counts["RUN_ARTIFACT"] == counts["run_artifacts"]
        and source_kind_counts["SUPPLEMENTAL"] == counts["supplemental_artifacts"]
        and {case_id for case_id, _run_id in report_identities}
        == set(REQUIRED_CASE_IDS)
        and all(
            count >= REQUIRED_RUN_ARTIFACTS_PER_CASE
            for count in run_artifact_counts.values()
        )
        and aggregate_file_sha256 == manifest.get("aggregate_sha256")
        and secret_scan.get("files_scanned") == len(rows),
        "bundle manifest review matrix closure is incomplete",
    )
    for case_id, run_id in report_identities:
        _require(
            any(
                row.get("source_kind") == "RUN_ARTIFACT"
                and row.get("case_id") == case_id
                and row.get("run_id") == run_id
                for row in rows
            ),
            "bundle run artifact/report identity binding is incomplete",
        )
    closure.sort(key=lambda item: str(item["path"]))
    return BundleSnapshot(
        root=root,
        manifest_sha256=manifest_sha256,
        closure_sha256=_digest_object(closure),
        file_count=len(closure),
        total_bytes=total_bytes,
    )


def _load_review_controls() -> tuple[bytes, bytes, dict[str, Any]]:
    prompt = _read_regular(PROMPT_PATH, "review prompt", MAX_CONTROL_FILE_BYTES)
    schema_raw = _read_regular(
        RESPONSE_SCHEMA_PATH, "review response schema", MAX_CONTROL_FILE_BYTES
    )
    schema = _json_object(schema_raw, "review response schema")
    properties = schema.get("properties")
    _require(
        schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema"
        and schema.get("type") == "object"
        and schema.get("additionalProperties") is False
        and set(schema.get("required", [])) == _RESPONSE_KEYS
        and isinstance(properties, Mapping)
        and properties.get("schema", {}).get("const")
        == "milai.dg13u.u1-review-response.v1"
        and properties.get("review_scope", {}).get("const") == "DG13U_U1_RELEASE_BUNDLE"
        and properties.get("verdict", {}).get("enum")
        == ["PASS", "REVISE", "BLOCKED_BY_MISSING_EVIDENCE"],
        "review response schema is invalid",
    )
    return prompt, schema_raw, schema


def _codex_path(explicit: str | Path | None) -> Path:
    raw = os.fspath(explicit) if explicit is not None else shutil.which("codex")
    _require(isinstance(raw, str) and bool(raw), "Codex CLI is unavailable")
    candidate = Path(raw).resolve(strict=True)
    _require(
        candidate.is_file()
        and not candidate.is_symlink()
        and os.access(candidate, os.X_OK),
        "Codex CLI executable is unsafe",
    )
    _require(
        stat.S_IMODE(candidate.stat().st_mode) & 0o022 == 0,
        "Codex CLI executable is group/world writable",
    )
    return candidate


def build_command(
    *, codex: Path, bundle: Path, output: Path, response_schema: Path
) -> list[str]:
    """Return the shell-free, single-attempt Codex command."""

    return [
        str(codex),
        "--ask-for-approval",
        "never",
        "exec",
        "--strict-config",
        "--model",
        MODEL,
        "--config",
        f'model_reasoning_effort="{REASONING_EFFORT}"',
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--sandbox",
        "read-only",
        "--cd",
        str(bundle),
        "--skip-git-repo-check",
        "--output-schema",
        str(response_schema),
        "--json",
        "--output-last-message",
        str(output),
        "-",
    ]


def _child_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in _ENVIRONMENT_ALLOWLIST and value
    }
    environment.update({"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC"})
    return environment


def _argv_raw(command: Sequence[str]) -> bytes:
    return b"".join(item.encode() + b"\0" for item in command)


def _execute_once(
    command: Sequence[str],
    prompt: bytes,
    timeout_seconds: int,
    environment: Mapping[str, str],
) -> ExecutionResult:
    process = subprocess.Popen(
        list(command),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(environment),
    )
    proc_exe_sha256: str | None = None
    proc_cmdline_sha256: str | None = None
    try:
        proc_exe = Path(f"/proc/{process.pid}/exe").resolve(strict=True)
        proc_exe_sha256 = _digest(
            _read_regular(proc_exe, "child executable", 512 * 1024 * 1024)
        )
        proc_cmdline_sha256 = _digest(Path(f"/proc/{process.pid}/cmdline").read_bytes())
    except (OSError, ReviewRunError):
        pass
    try:
        stdout, stderr = process.communicate(prompt, timeout=timeout_seconds)
        return ExecutionResult(
            returncode=process.returncode,
            termination_reason="COMPLETED",
            stdout=stdout,
            stderr=stderr,
            child_pid=process.pid,
            proc_exe_sha256=proc_exe_sha256,
            proc_cmdline_sha256=proc_cmdline_sha256,
        )
    except subprocess.TimeoutExpired as exc:
        process.kill()
        tail_out, tail_err = process.communicate()
        stdout = exc.stdout if isinstance(exc.stdout, bytes) else b""
        stderr = exc.stderr if isinstance(exc.stderr, bytes) else b""
        return ExecutionResult(
            returncode=124,
            termination_reason="TIMEOUT",
            stdout=stdout + tail_out,
            stderr=stderr + tail_err + b"\nDG13U_REVIEW_TIMEOUT_FAIL_CLOSED\n",
            child_pid=process.pid,
            proc_exe_sha256=proc_exe_sha256,
            proc_cmdline_sha256=proc_cmdline_sha256,
        )
    except KeyboardInterrupt:
        process.kill()
        stdout, stderr = process.communicate()
        return ExecutionResult(
            returncode=130,
            termination_reason="OPERATOR_INTERRUPTED",
            stdout=stdout,
            stderr=stderr + b"\nDG13U_REVIEW_INTERRUPTED_FAIL_CLOSED\n",
            child_pid=process.pid,
            proc_exe_sha256=proc_exe_sha256,
            proc_cmdline_sha256=proc_cmdline_sha256,
        )


def _write_new(path: Path, raw: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _secure_model_output(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    metadata = path.lstat()
    _require(
        stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode),
        "model review output is not a regular file",
    )
    path.chmod(0o600)


def _prepare_attempt_root(path: str | Path, attempt_id: str, bundle: Path) -> Path:
    root = _absolute(path, "attempt root")
    _reject_symlink_chain(root, "attempt root")
    _require(
        _ATTEMPT_ID.fullmatch(attempt_id) is not None, "review attempt ID is invalid"
    )
    _require(not root.exists() and not root.is_symlink(), "attempt root must be new")
    _require(
        root != bundle and bundle not in root.parents and root not in bundle.parents,
        "attempt root must be disjoint from the review bundle",
    )
    root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _reject_symlink_chain(root.parent, "attempt root parent")
    _require(
        root.parent.is_dir()
        and not root.parent.is_symlink()
        and stat.S_IMODE(root.parent.stat().st_mode) & 0o022 == 0,
        "attempt root parent is unsafe",
    )
    root.mkdir(mode=0o700)
    return root


def _validate_response(
    output: Path, _schema: Mapping[str, Any], manifest_sha256: str
) -> dict[str, Any]:
    raw = _read_regular(output, "model review output", MAX_MODEL_OUTPUT_BYTES)
    response = _json_object(raw, "model review output")
    _require(
        set(response) == _RESPONSE_KEYS
        and response.get("schema") == "milai.dg13u.u1-review-response.v1"
        and response.get("review_scope") == "DG13U_U1_RELEASE_BUNDLE"
        and response.get("verdict") in {"PASS", "REVISE", "BLOCKED_BY_MISSING_EVIDENCE"}
        and isinstance(response.get("summary"), str)
        and 1 <= len(response["summary"]) <= 8000
        and isinstance(response.get("open_findings"), list)
        and len(response["open_findings"]) <= 256
        and isinstance(response.get("missing_evidence"), list)
        and len(response["missing_evidence"]) <= 256
        and isinstance(response.get("reviewed_manifest_sha256"), str)
        and _SHA256.fullmatch(response["reviewed_manifest_sha256"]) is not None,
        "model review output failed local schema validation",
    )
    for finding in response["open_findings"]:
        _require(
            isinstance(finding, Mapping)
            and set(finding) == _FINDING_KEYS
            and isinstance(finding.get("finding_id"), str)
            and _FINDING_ID.fullmatch(finding["finding_id"]) is not None
            and finding.get("severity") in {"P0", "P1", "P2", "P3"}
            and isinstance(finding.get("title"), str)
            and 1 <= len(finding["title"]) <= 500
            and isinstance(finding.get("evidence"), list)
            and 1 <= len(finding["evidence"]) <= 32
            and all(
                isinstance(item, str) and 1 <= len(item) <= 1000
                for item in finding["evidence"]
            )
            and isinstance(finding.get("required_action"), str)
            and 1 <= len(finding["required_action"]) <= 2000,
            "model review output failed local schema validation",
        )
    _require(
        all(
            isinstance(item, str) and 1 <= len(item) <= 2000
            for item in response["missing_evidence"]
        ),
        "model review output failed local schema validation",
    )
    _require(
        response.get("reviewed_manifest_sha256") == manifest_sha256,
        "model review output manifest binding mismatch",
    )
    findings = response["open_findings"]
    finding_ids = [finding["finding_id"] for finding in findings]
    _require(
        len(finding_ids) == len(set(finding_ids)),
        "model review finding IDs are duplicated",
    )
    if response["verdict"] == "PASS":
        _require(
            not [
                finding for finding in findings if finding["severity"] in {"P0", "P1"}
            ],
            "PASS cannot retain an open P0/P1 finding",
        )
        _require(
            not response["missing_evidence"],
            "model review output failed local schema validation",
        )
    elif response["verdict"] == "REVISE":
        _require(
            bool(response["open_findings"]),
            "model review output failed local schema validation",
        )
    else:
        _require(
            bool(response["missing_evidence"]),
            "model review output failed local schema validation",
        )
    return response


def _review_markdown(response: Mapping[str, Any]) -> bytes:
    lines = [
        "# DG13U U1 Independent Review",
        "",
        f"- Verdict: `{response['verdict']}`",
        f"- Reviewed manifest SHA-256: `{response['reviewed_manifest_sha256']}`",
        "",
        "## Summary",
        "",
        str(response["summary"]),
        "",
        "## Open findings",
        "",
    ]
    findings = response["open_findings"]
    if findings:
        for finding in findings:
            lines.extend(
                [
                    f"### {finding['finding_id']} — {finding['severity']}",
                    "",
                    str(finding["title"]),
                    "",
                    "Evidence:",
                    "",
                    *(f"- {item}" for item in finding["evidence"]),
                    "",
                    f"Required action: {finding['required_action']}",
                    "",
                ]
            )
    else:
        lines.extend(["None.", ""])
    lines.extend(["## Missing evidence", ""])
    missing = response["missing_evidence"]
    lines.extend((f"- {item}" for item in missing) if missing else ["None."])
    return ("\n".join(lines).rstrip() + "\n").encode()


def _failure_terminal(
    *, attempt_id: str, manifest_sha256: str, reason_code: str
) -> tuple[bytes, bytes]:
    terminal = {
        "schema": "milai.dg13u.u1-review-terminal.v1",
        "status": "FAIL_CLOSED",
        "attempt_id": attempt_id,
        "verdict": "BLOCKED_BY_MISSING_EVIDENCE",
        "verdict_origin": "RUNNER_FAIL_CLOSED",
        "reviewed_manifest_sha256": manifest_sha256,
        "reason_code": reason_code,
        "model_response_valid": False,
    }
    markdown = (
        "# DG13U U1 Independent Review\n\n"
        "- Status: `FAIL_CLOSED`\n"
        "- Verdict: `BLOCKED_BY_MISSING_EVIDENCE`\n"
        f"- Reason code: `{reason_code}`\n"
        f"- Reviewed manifest SHA-256: `{manifest_sha256}`\n"
    ).encode()
    return _canonical(terminal), markdown


def run_review(
    *,
    bundle: str | Path,
    expected_manifest_sha256: str,
    attempt_root: str | Path,
    attempt_id: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    codex: str | Path | None = None,
) -> tuple[Path, int]:
    """Execute exactly one model review and materialize a locally validated terminal."""

    _require(
        isinstance(timeout_seconds, int)
        and not isinstance(timeout_seconds, bool)
        and 60 <= timeout_seconds <= 3600,
        "review timeout is outside the fixed safe range",
    )
    before = _validate_bundle(bundle, expected_manifest_sha256)
    prompt, schema_raw, schema = _load_review_controls()
    executable = _codex_path(codex)
    attempt = _prepare_attempt_root(attempt_root, attempt_id, before.root)
    model_output = attempt / "model-output.json"
    command = build_command(
        codex=executable,
        bundle=before.root,
        output=model_output,
        response_schema=RESPONSE_SCHEMA_PATH,
    )
    environment = _child_environment()
    try:
        result = _execute_once(command, prompt, timeout_seconds, environment)
    except (OSError, subprocess.SubprocessError):
        result = ExecutionResult(
            returncode=127,
            termination_reason="LAUNCH_FAILED",
            stdout=b"",
            stderr=b"DG13U_REVIEW_LAUNCH_FAILED_CLOSED\n",
            child_pid=0,
            proc_exe_sha256=None,
            proc_cmdline_sha256=None,
        )
    _write_new(attempt / "events.jsonl", result.stdout)
    _write_new(attempt / "stderr.log", result.stderr)

    reason_code: str | None = None
    response: dict[str, Any] | None = None
    try:
        try:
            after = _validate_bundle(bundle, expected_manifest_sha256)
        except ReviewRunError:
            raise ReviewRunError("review bundle changed during execution") from None
        _require(after == before, "review bundle changed during execution")
        _secure_model_output(model_output)
        _require(
            result.returncode == 0, "Codex review process did not complete successfully"
        )
        _require(
            result.proc_exe_sha256
            == _digest(_read_regular(executable, "Codex CLI", 512 * 1024 * 1024)),
            "Codex child executable identity was not attested",
        )
        _require(
            result.proc_cmdline_sha256 == _digest(_argv_raw(command)),
            "Codex child argv identity was not attested",
        )
        response = _validate_response(model_output, schema, before.manifest_sha256)
    except ReviewRunError as exc:
        known = {
            "review bundle changed during execution": "BUNDLE_DRIFT",
            "Codex review process did not complete successfully": "MODEL_PROCESS_FAILED",
            "Codex child executable identity was not attested": "PROCESS_IDENTITY_UNATTESTED",
            "Codex child argv identity was not attested": "ARGV_IDENTITY_UNATTESTED",
            "model review output failed local schema validation": "OUTPUT_SCHEMA_INVALID",
            "model review output manifest binding mismatch": "OUTPUT_MANIFEST_UNBOUND",
            "model review finding IDs are duplicated": "OUTPUT_FINDING_ID_DUPLICATE",
            "PASS cannot retain an open P0/P1 finding": "OUTPUT_PASS_WITH_OPEN_P0_P1",
        }
        reason_code = known.get(str(exc), "MODEL_OUTPUT_INVALID")

    if response is not None:
        review_raw = _canonical(response)
        review_markdown = _review_markdown(response)
        _write_new(attempt / "review.json", review_raw)
        _write_new(attempt / "review.md", review_markdown)
        terminal_raw = _canonical(
            {
                "schema": "milai.dg13u.u1-review-terminal.v1",
                "status": "COMPLETED",
                "attempt_id": attempt_id,
                "verdict": response["verdict"],
                "verdict_origin": "MODEL_SCHEMA_VALIDATED",
                "reviewed_manifest_sha256": before.manifest_sha256,
                "reason_code": "REVIEW_SCHEMA_VALIDATED",
                "model_response_valid": True,
            }
        )
        terminal_markdown = review_markdown
        returncode = 0
    else:
        terminal_raw, terminal_markdown = _failure_terminal(
            attempt_id=attempt_id,
            manifest_sha256=before.manifest_sha256,
            reason_code=reason_code or "MODEL_OUTPUT_INVALID",
        )
        returncode = result.returncode if result.returncode != 0 else 2
    _write_new(attempt / "terminal.json", terminal_raw)
    _write_new(attempt / "terminal.md", terminal_markdown)

    output_paths = {
        "events": attempt / "events.jsonl",
        "stderr": attempt / "stderr.log",
        "model_output": model_output,
        "review_json": attempt / "review.json",
        "review_markdown": attempt / "review.md",
        "terminal_json": attempt / "terminal.json",
        "terminal_markdown": attempt / "terminal.md",
    }
    output_identities = {
        name: (
            {
                "bytes": path.stat().st_size,
                "sha256": _digest(_read_regular(path, name, MAX_MODEL_OUTPUT_BYTES)),
            }
            if path.is_file() and not path.is_symlink()
            else None
        )
        for name, path in output_paths.items()
    }
    inputs = {
        "bundle_manifest_sha256": before.manifest_sha256,
        "bundle_closure_sha256": before.closure_sha256,
        "bundle_file_count": before.file_count,
        "bundle_total_bytes": before.total_bytes,
        "prompt_sha256": _digest(prompt),
        "response_schema_sha256": _digest(schema_raw),
    }
    process_identity = {
        "child_pid": result.child_pid,
        "codex_executable_sha256": _digest(
            _read_regular(executable, "Codex CLI", 512 * 1024 * 1024)
        ),
        "proc_exe_sha256": result.proc_exe_sha256,
        "proc_cmdline_sha256": result.proc_cmdline_sha256,
        "environment_names": sorted(environment),
        "environment_sha256": _digest_object(environment),
    }
    attestation = {
        "schema": "milai.dg13u.u1-review-process.v1",
        "status": "PASS" if returncode == 0 else "FAIL_CLOSED",
        "attempt_id": attempt_id,
        "attempt_count": 1,
        "automatic_retries": 0,
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "approval_policy": "never",
        "sandbox": "read-only",
        "ephemeral": True,
        "ignore_user_config": True,
        "ignore_rules": True,
        "process_exit_code": result.returncode,
        "termination_reason": result.termination_reason,
        "timeout_seconds": timeout_seconds,
        "inputs": inputs,
        "inputs_sha256": _digest_object(inputs),
        "argv_sha256": _digest(_argv_raw(command)),
        "process": process_identity,
        "process_sha256": _digest_object(process_identity),
        "outputs": output_identities,
        "outputs_sha256": _digest_object(output_identities),
    }
    _write_new(attempt / "process.json", _canonical(attestation))
    return attempt, returncode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one independent Sol/xhigh review of a frozen DG13U U1 bundle"
    )
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--attempt-root", type=Path, required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--codex", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        attempt, returncode = run_review(
            bundle=args.bundle,
            expected_manifest_sha256=args.expected_manifest_sha256,
            attempt_root=args.attempt_root,
            attempt_id=args.attempt_id,
            timeout_seconds=args.timeout_seconds,
            codex=args.codex,
        )
    except (ReviewRunError, FileExistsError, OSError) as exc:
        print(
            _canonical(
                {
                    "schema": "milai.dg13u.u1-review-launch.v1",
                    "status": "FAIL_CLOSED",
                    "reason": str(exc),
                }
            ).decode(),
            end="",
        )
        return 2
    terminal = _json_object(
        _read_regular(attempt / "terminal.json", "terminal", MAX_CONTROL_FILE_BYTES),
        "terminal",
    )
    print(
        _canonical(
            {
                "attempt_root": str(attempt),
                "status": terminal["status"],
                "verdict": terminal["verdict"],
            }
        ).decode(),
        end="",
    )
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
