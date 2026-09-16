"""Strict, content-redacted DG13-U1 evidence artifact producers."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from scripts import dg13u_u1_aggregate as aggregate

_READINESS_NAME = "readiness.json"
_SMOKE_NAME = "smoke-evidence.json"
_RECONCILIATION_NAME = "reconciliation.json"
_RUN_ID = re.compile(r"[a-z0-9][a-z0-9._-]{7,95}")
_ENVIRONMENT_NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,127}")
_ROUTE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_PROVIDER_READINESS_STATUSES = frozenset(
    {*aggregate.VALID_STATUSES, "PASS_IDENTITY_ONLY_ZERO_COMPLETIONS"}
)
_READINESS_COMPONENTS = frozenset(
    {"runtime", "broker", "host", "openworker", "provider"}
)
_READINESS_LATENCIES = frozenset(
    {"runtime", "broker", "host", "openworker", "provider"}
)
_EXECUTION_LATENCIES = frozenset(
    {"openworker", "adapter", "mcp", "runtime", "compile", "provider"}
)
_JOIN_FIELDS = frozenset(
    {
        "access_id_sha256",
        "mcp_receipt_sha256",
        "runtime_trace_sha256",
        "provider_native_request_id_sha256",
    }
)
_EXPECTED_LIFECYCLE_PRESERVATION = {
    "U1-BROKER-INODE-RECREATE": {
        "broker_socket_inode_preserved": False,
        "host_process_preserved": True,
        "broker_process_preserved": False,
        "existing_vllm_preserved": True,
    },
    "U1-ADAPTER-RESTART": {
        "broker_socket_inode_preserved": True,
        "host_process_preserved": False,
        "broker_process_preserved": True,
        "existing_vllm_preserved": True,
    },
}
_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@"),
)


class EvidenceArtifactError(RuntimeError):
    """Measured evidence cannot be normalized into a safe artifact."""


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    if "sha256" in normalized or normalized in {
        "context_tokens",
        "durable_credentials_found",
        "forbidden_environment_names",
        "provider_completion_calls",
    }:
        return False
    return normalized in {
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "password",
        "secret",
        "token",
    } or normalized.endswith(
        ("_api_key", "_credential", "_password", "_secret", "_token")
    )


def _reject_secret_like(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise EvidenceArtifactError("measured input keys must be strings")
            if _is_sensitive_key(key):
                raise EvidenceArtifactError(f"secret-like field is forbidden: {key}")
            _reject_secret_like(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_secret_like(item)
    elif isinstance(value, str) and any(
        pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS
    ):
        raise EvidenceArtifactError("secret-like value is forbidden")


def _normalize(measured: Mapping[str, object]) -> dict[str, Any]:
    if not isinstance(measured, Mapping):
        raise EvidenceArtifactError("measured input must be an object")
    _reject_secret_like(measured)
    try:
        raw = json.dumps(
            measured,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        normalized = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise EvidenceArtifactError(
            "measured input must contain strict JSON values"
        ) from exc
    if not isinstance(normalized, dict):
        raise EvidenceArtifactError("measured input must be an object")
    return normalized


def _require_fields(
    value: Mapping[str, object], expected: set[str] | frozenset[str], label: str
) -> None:
    if set(value) != set(expected):
        raise EvidenceArtifactError(f"{label} field set is invalid")


def _common(value: Mapping[str, object], expected: set[str]) -> tuple[str, str, str]:
    _require_fields(value, expected, "artifact")
    run_id = value["run_id"]
    case_id = value["case_id"]
    status_value = value["status"]
    if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
        raise EvidenceArtifactError("run_id is invalid")
    if case_id not in aggregate.REQUIRED_CASE_IDS:
        raise EvidenceArtifactError("case_id is invalid")
    if status_value not in aggregate.VALID_STATUSES:
        raise EvidenceArtifactError("status is invalid")
    return run_id, str(case_id), str(status_value)


def _nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise EvidenceArtifactError(f"{label} must be a nonnegative integer")
    return value


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise EvidenceArtifactError(f"{label} must be an integer")
    return value


def _nonnegative_number(value: object, label: str) -> int | float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or value < 0
    ):
        raise EvidenceArtifactError(f"{label} must be a nonnegative number")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise EvidenceArtifactError(f"{label} must be a boolean")
    return value


def _sha256(value: object, label: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EvidenceArtifactError(f"{label} must be a lowercase SHA-256")
    return value


def _latencies(
    value: object, expected: frozenset[str], label: str
) -> dict[str, int | float]:
    if not isinstance(value, Mapping):
        raise EvidenceArtifactError(f"{label} must be an object")
    _require_fields(value, expected, label)
    return {
        name: _nonnegative_number(value[name], f"{label}.{name}")
        for name in sorted(expected)
    }


def _calls(value: object, case_id: str, status_value: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EvidenceArtifactError("calls must be an object")
    _require_fields(value, {"mcp", "provider"}, "calls")
    result: dict[str, Any] = {}
    contract = aggregate.CASE_CONTRACTS[case_id]
    clean = True
    for name, expected_calls in (
        ("mcp", contract.expected_mcp_calls),
        ("provider", contract.expected_provider_calls),
    ):
        record = value[name]
        if not isinstance(record, Mapping):
            raise EvidenceArtifactError(f"calls.{name} must be an object")
        expected_fields = {
            "expected",
            "observed",
            "unaccounted",
            "automatic_retries",
        }
        if name == "provider":
            expected_fields.update(
                {
                    "maximum_per_model_round",
                    "model_rounds",
                    "calls_per_task_operation",
                    "case_maximum",
                }
            )
        _require_fields(record, expected_fields, f"calls.{name}")
        normalized = {
            field: _nonnegative_int(record[field], f"calls.{name}.{field}")
            for field in expected_fields
        }
        if normalized["expected"] != expected_calls:
            raise EvidenceArtifactError(f"calls.{name}.expected does not match case")
        if name == "provider" and (
            normalized["maximum_per_model_round"] != 1
            or normalized["model_rounds"] != expected_calls
            or normalized["calls_per_task_operation"] != expected_calls
            or normalized["case_maximum"] != expected_calls
        ):
            raise EvidenceArtifactError(
                "provider model-round call policy does not match case"
            )
        clean = clean and (
            normalized["observed"] == normalized["expected"]
            and normalized["unaccounted"] == 0
            and normalized["automatic_retries"] == 0
        )
        result[name] = normalized
    if status_value == "PASS" and not clean:
        raise EvidenceArtifactError("PASS calls must reconcile without retries")
    return result


def _joins(value: object, case_id: str, status_value: str) -> dict[str, str | None]:
    if not isinstance(value, Mapping):
        raise EvidenceArtifactError("joined_identities must be an object")
    _require_fields(value, _JOIN_FIELDS, "joined_identities")
    result = {
        name: _sha256(value[name], f"joined_identities.{name}", nullable=True)
        for name in sorted(_JOIN_FIELDS)
    }
    if status_value == "PASS":
        if (
            case_id in aggregate.PROVIDER_NATIVE_JOIN_CASE_IDS
            and result["provider_native_request_id_sha256"] is None
        ):
            raise EvidenceArtifactError("PASS provider join SHA-256 is required")
        if case_id in aggregate.EXACT_SUCCESS_CASE_IDS and any(
            result[name] is None
            for name in (
                "access_id_sha256",
                "mcp_receipt_sha256",
                "runtime_trace_sha256",
            )
        ):
            raise EvidenceArtifactError("PASS EXACT join SHA-256 values are required")
    return result


def _base_document(
    name: str, run_id: str, case_id: str, status_value: str
) -> dict[str, Any]:
    return {
        "schema": aggregate.REQUIRED_ARTIFACT_SCHEMAS[name],
        "run_id": run_id,
        "case_id": case_id,
        "status": status_value,
    }


def _readiness_document(measured: Mapping[str, object]) -> dict[str, Any]:
    value = _normalize(measured)
    expected = {
        "run_id",
        "case_id",
        "status",
        "components",
        "provider_completion_calls",
        "security",
        "latencies_ms",
        "worker_health_sha256",
        "mcp_list_sha256",
    }
    run_id, case_id, status_value = _common(value, expected)
    components = value["components"]
    if not isinstance(components, Mapping):
        raise EvidenceArtifactError("components must be an object")
    _require_fields(components, _READINESS_COMPONENTS, "components")
    normalized_components: dict[str, str] = {}
    for name in sorted(_READINESS_COMPONENTS):
        component_status = components[name]
        valid = (
            _PROVIDER_READINESS_STATUSES
            if name == "provider"
            else aggregate.VALID_STATUSES
        )
        if component_status not in valid:
            raise EvidenceArtifactError(f"components.{name} status is invalid")
        normalized_components[name] = str(component_status)
    completion_calls = _nonnegative_int(
        value["provider_completion_calls"], "provider_completion_calls"
    )
    if completion_calls != 0:
        raise EvidenceArtifactError(
            "readiness provider probe must have zero completions"
        )

    security = value["security"]
    if not isinstance(security, Mapping):
        raise EvidenceArtifactError("security must be an object")
    security_fields = {
        "status",
        "network_internal",
        "network_mode_sha256",
        "cap_drop_all",
        "no_new_privileges",
        "reader_lite_socket_read_only",
        "docker_socket_mounted",
        "forbidden_environment_names",
    }
    _require_fields(security, security_fields, "security")
    security_status = security["status"]
    if security_status not in aggregate.VALID_STATUSES:
        raise EvidenceArtifactError("security status is invalid")
    forbidden_names = security["forbidden_environment_names"]
    if not isinstance(forbidden_names, list) or any(
        not isinstance(name, str) or _ENVIRONMENT_NAME.fullmatch(name) is None
        for name in forbidden_names
    ):
        raise EvidenceArtifactError("forbidden_environment_names is invalid")
    if len(forbidden_names) != len(set(forbidden_names)):
        raise EvidenceArtifactError("forbidden_environment_names contains duplicates")
    normalized_security = {
        "status": str(security_status),
        "network_internal": _boolean(
            security["network_internal"], "security.network_internal"
        ),
        "network_mode_sha256": _sha256(
            security["network_mode_sha256"], "security.network_mode_sha256"
        ),
        "cap_drop_all": _boolean(security["cap_drop_all"], "security.cap_drop_all"),
        "no_new_privileges": _boolean(
            security["no_new_privileges"], "security.no_new_privileges"
        ),
        "reader_lite_socket_read_only": _boolean(
            security["reader_lite_socket_read_only"],
            "security.reader_lite_socket_read_only",
        ),
        "docker_socket_mounted": _boolean(
            security["docker_socket_mounted"], "security.docker_socket_mounted"
        ),
        "forbidden_environment_names": sorted(forbidden_names),
    }
    pass_security = (
        normalized_security["status"] == "PASS"
        and normalized_security["network_internal"] is True
        and normalized_security["cap_drop_all"] is True
        and normalized_security["no_new_privileges"] is True
        and normalized_security["reader_lite_socket_read_only"] is True
        and normalized_security["docker_socket_mounted"] is False
        and normalized_security["forbidden_environment_names"] == []
    )
    if status_value == "PASS" and (
        any(
            normalized_components[name] != "PASS"
            for name in ("runtime", "broker", "host", "openworker")
        )
        or normalized_components["provider"] != "PASS_IDENTITY_ONLY_ZERO_COMPLETIONS"
        or not pass_security
    ):
        raise EvidenceArtifactError(
            "PASS readiness security and components are invalid"
        )
    document = _base_document(_READINESS_NAME, run_id, case_id, status_value)
    document.update(normalized_components)
    document.update(
        {
            "provider_completion_calls": completion_calls,
            "security": normalized_security,
            "latencies_ms": _latencies(
                value["latencies_ms"], _READINESS_LATENCIES, "latencies_ms"
            ),
            "worker_health_sha256": _sha256(
                value["worker_health_sha256"], "worker_health_sha256"
            ),
            "mcp_list_sha256": _sha256(value["mcp_list_sha256"], "mcp_list_sha256"),
        }
    )
    return document


def _smoke_document(measured: Mapping[str, object]) -> dict[str, Any]:
    value = _normalize(measured)
    expected = {
        "run_id",
        "case_id",
        "status",
        "calls",
        "joined_identities",
        "latencies_ms",
        "context_tokens",
        "model_visible_memory_tool_events",
        "raw_prompt_or_answer_persisted",
        "provider_terminal_status",
        "worker_exit_code",
        "worker_output_sha256",
        "worker_output_bytes",
        "memory_route",
    }
    run_id, case_id, status_value = _common(value, expected)
    calls = _calls(value["calls"], case_id, status_value)
    joins = _joins(value["joined_identities"], case_id, status_value)
    context_tokens = _nonnegative_int(value["context_tokens"], "context_tokens")
    visible_events = _nonnegative_int(
        value["model_visible_memory_tool_events"],
        "model_visible_memory_tool_events",
    )
    raw_persisted = _boolean(
        value["raw_prompt_or_answer_persisted"], "raw_prompt_or_answer_persisted"
    )
    terminal = value["provider_terminal_status"]
    if terminal is not None and (
        not isinstance(terminal, str) or not terminal or len(terminal) > 128
    ):
        raise EvidenceArtifactError("provider_terminal_status is invalid")
    route = value["memory_route"]
    if not isinstance(route, str) or _ROUTE.fullmatch(route) is None:
        raise EvidenceArtifactError("memory_route is invalid")
    if status_value == "PASS":
        should_have_context = case_id in aggregate.MEMORY_CONTEXT_CASE_IDS
        if (should_have_context and context_tokens <= 0) or (
            not should_have_context and context_tokens != 0
        ):
            raise EvidenceArtifactError("PASS context_tokens do not match case")
        if visible_events != 0 or raw_persisted:
            raise EvidenceArtifactError(
                "PASS smoke persisted raw data or visible memory events"
            )
        if case_id in aggregate.PROVIDER_FAILURE_CASE_IDS:
            if terminal != "FAILED":
                raise EvidenceArtifactError(
                    "PASS injected provider failure terminal must be FAILED"
                )
        elif calls["provider"]["expected"] > 0 and terminal != "SUCCEEDED":
            raise EvidenceArtifactError("PASS provider terminal must be SUCCEEDED")
        elif calls["provider"]["expected"] == 0 and terminal is not None:
            raise EvidenceArtifactError("PASS provider barrier terminal must be absent")
    return {
        **_base_document(_SMOKE_NAME, run_id, case_id, status_value),
        "calls": calls,
        "joined_identities": joins,
        "latencies_ms": _latencies(
            value["latencies_ms"], _EXECUTION_LATENCIES, "latencies_ms"
        ),
        "context_tokens": context_tokens,
        "model_visible_memory_tool_events": visible_events,
        "raw_prompt_or_answer_persisted": raw_persisted,
        "provider_terminal_status": terminal,
        "worker_exit_code": _integer(value["worker_exit_code"], "worker_exit_code"),
        "worker_output_sha256": _sha256(
            value["worker_output_sha256"], "worker_output_sha256"
        ),
        "worker_output_bytes": _nonnegative_int(
            value["worker_output_bytes"], "worker_output_bytes"
        ),
        "memory_route": route,
    }


def _reconciliation_document(measured: Mapping[str, object]) -> dict[str, Any]:
    value = _normalize(measured)
    expected = {
        "run_id",
        "case_id",
        "status",
        "calls",
        "joined_identities",
        "latencies_ms",
        "unaccounted_calls",
        "durable_credentials_found",
        "broker_socket_inode_preserved",
        "host_process_preserved",
        "broker_process_preserved",
        "existing_vllm_preserved",
        "external_lifecycle_mutations",
    }
    run_id, case_id, status_value = _common(value, expected)
    calls = _calls(value["calls"], case_id, status_value)
    joins = _joins(value["joined_identities"], case_id, status_value)
    latency_fields = frozenset({*_EXECUTION_LATENCIES, "reconciliation"})
    unaccounted_calls = _nonnegative_int(
        value["unaccounted_calls"], "unaccounted_calls"
    )
    measured_unaccounted = sum(
        calls[name]["unaccounted"] for name in ("mcp", "provider")
    )
    if unaccounted_calls != measured_unaccounted:
        raise EvidenceArtifactError("unaccounted_calls does not reconcile with calls")
    durable_credentials = _nonnegative_int(
        value["durable_credentials_found"], "durable_credentials_found"
    )
    external_mutations = _nonnegative_int(
        value["external_lifecycle_mutations"], "external_lifecycle_mutations"
    )
    preserved = {
        name: _boolean(value[name], name)
        for name in (
            "broker_socket_inode_preserved",
            "host_process_preserved",
            "broker_process_preserved",
            "existing_vllm_preserved",
        )
    }
    if status_value == "PASS":
        expected_preservation = _EXPECTED_LIFECYCLE_PRESERVATION.get(
            case_id,
            {name: True for name in preserved},
        )
        if (
            unaccounted_calls != 0
            or durable_credentials != 0
            or external_mutations != 0
            or preserved != expected_preservation
        ):
            raise EvidenceArtifactError(
                "PASS reconciliation measurements are not clean"
            )
    return {
        **_base_document(_RECONCILIATION_NAME, run_id, case_id, status_value),
        "calls": calls,
        "joined_identities": joins,
        "latencies_ms": _latencies(
            value["latencies_ms"], latency_fields, "latencies_ms"
        ),
        "unaccounted_calls": unaccounted_calls,
        "durable_credentials_found": durable_credentials,
        **preserved,
        "external_lifecycle_mutations": external_mutations,
    }


def _reject_symlink_chain(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            raise EvidenceArtifactError("run-owned directory does not exist") from None
        if stat.S_ISLNK(metadata.st_mode):
            raise EvidenceArtifactError("run-owned directory symlink is forbidden")


def _write_document(
    run_dir: str | Path, name: str, document: Mapping[str, Any]
) -> dict[str, Any]:
    directory = Path(run_dir)
    if not directory.is_absolute():
        raise EvidenceArtifactError(
            "run-owned directory must be an explicit absolute path"
        )
    directory = Path(os.path.normpath(os.fspath(directory)))
    if directory.name != document["run_id"]:
        raise EvidenceArtifactError("run-owned directory does not match run_id")
    _reject_symlink_chain(directory)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        directory_fd = os.open(directory, flags)
    except OSError as exc:
        raise EvidenceArtifactError("run-owned directory is not accessible") from exc
    temporary_name = f".{name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    descriptor = -1
    try:
        opened = os.fstat(directory_fd)
        current = directory.lstat()
        if not stat.S_ISDIR(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            current.st_dev,
            current.st_ino,
        ):
            raise EvidenceArtifactError("run-owned directory identity changed")
        if stat.S_IMODE(opened.st_mode) != 0o700:
            raise EvidenceArtifactError("run-owned directory mode must be 0700")
        try:
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise EvidenceArtifactError(f"artifact already exists: {name}")
        raw = (
            json.dumps(
                document,
                allow_nan=False,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(
                temporary_name,
                name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise EvidenceArtifactError(f"artifact already exists: {name}") from exc
        os.unlink(temporary_name, dir_fd=directory_fd)
        temporary_name = ""
        after = directory.lstat()
        if (opened.st_dev, opened.st_ino) != (after.st_dev, after.st_ino):
            os.unlink(name, dir_fd=directory_fd)
            raise EvidenceArtifactError("run-owned directory identity changed")
        os.fsync(directory_fd)
        return {
            "path": name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_name:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)


def _produce(
    run_dir: str | Path,
    measured: Mapping[str, object],
    name: str,
    parser: Callable[[Mapping[str, object]], dict[str, Any]],
) -> dict[str, Any]:
    document = parser(measured)
    return _write_document(run_dir, name, document)


def write_readiness_artifact(
    run_dir: str | Path, measured: Mapping[str, object]
) -> dict[str, Any]:
    """Validate measured readiness once and atomically create readiness.json."""
    return _produce(run_dir, measured, _READINESS_NAME, _readiness_document)


def write_smoke_evidence_artifact(
    run_dir: str | Path, measured: Mapping[str, object]
) -> dict[str, Any]:
    """Validate measured smoke evidence once and atomically create its artifact."""
    return _produce(run_dir, measured, _SMOKE_NAME, _smoke_document)


def write_reconciliation_artifact(
    run_dir: str | Path, measured: Mapping[str, object]
) -> dict[str, Any]:
    """Validate measured reconciliation once and atomically create its artifact."""
    return _produce(
        run_dir,
        measured,
        _RECONCILIATION_NAME,
        _reconciliation_document,
    )
