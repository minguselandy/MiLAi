from __future__ import annotations

import argparse
import ast
import hashlib
import ipaddress
import json
import os
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from time import monotonic, perf_counter_ns, sleep
from typing import Any, Self, TextIO, cast
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = ROOT.parent.resolve()
WORKLOAD_PATH = Path(__file__).resolve().with_name("provider_ab_workload.json")
SANDBOX_LAUNCHER = Path(__file__).resolve().with_name("provider_sandbox_exec.py")
SANDBOX_RUNTIME = Path(sys.executable).resolve()
SDK_SOURCE = ROOT / "integrations" / "python-client" / "src"
ADAPTER_PROTOCOL = "milai-provider-adapter-v2"
DATA_BOUNDARY_ACK = "synthetic-deidentified-only"
REPORT_FORMAT = "milai-provider-ab-evidence-v3"
SANDBOX_FILE_POLICY = "landlock-read-execute-allowlist-v1"
MINIMUM_LANDLOCK_ABI = 1
HOST_EXECUTION_POLICY = "static-import-and-recursive-elf-closure-v1"
HOST_TOOL_SEARCH_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
REQUIRED_PROVIDER_REQUESTS = 1_000
MAX_RESPONSE_BYTES = 2_000_000
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_PROVIDER_CREDENTIAL_NAME = re.compile(
    r"^MILAI_PROVIDER_CREDENTIAL_[A-Z][A-Z0-9_]{0,47}$"
)
_NATIVE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_REPORT_OUTPUT_KEYS = {
    "answer",
    "abstained",
    "open_issue_ids",
    "claim_refs",
    "reason_code",
}
_CANONICAL_ENV_MARKERS = (
    "DATABASE",
    "POSTGRES",
    "STEWARD",
    "MILAI",
    "CAUSAL_AGENT",
    "KEK",
    "TENANT",
    "ACTOR",
)
_FINISH_REASONS = {"stop", "completed"}
_CAPTURE_STATUS = "PROVIDER_CAPTURE_COMPLETE_REVIEW_REQUIRED"
_RECONCILED_STATUS = "PROVIDER_EVIDENCE_RECONCILED_REVIEW_REQUIRED"


class ProviderEvidenceError(RuntimeError):
    """Fail-closed provider evidence validation error."""


@dataclass(frozen=True, slots=True)
class Pricing:
    currency: str
    input_per_million: Decimal
    cached_input_per_million: Decimal
    output_per_million: Decimal
    snapshot_sha256: str

    def cost(self, usage: Mapping[str, Any]) -> Decimal:
        input_tokens = Decimal(int(usage["input_tokens"]))
        cached_tokens = Decimal(int(usage["cached_input_tokens"]))
        output_tokens = Decimal(int(usage["output_tokens"]))
        return (
            (input_tokens - cached_tokens) * self.input_per_million
            + cached_tokens * self.cached_input_per_million
            + output_tokens * self.output_per_million
        ) / Decimal(1_000_000)

    def reservation(self, input_tokens: int, max_output_tokens: int) -> Decimal:
        return (
            Decimal(input_tokens)
            * max(self.input_per_million, self.cached_input_per_million)
            + Decimal(max_output_tokens) * self.output_per_million
        ) / Decimal(1_000_000)


@dataclass(frozen=True, slots=True)
class TurnSpec:
    turn_index: int
    case_id: str
    requires_memory: bool
    query: str
    baseline_memory: str
    optimized_memory: str
    expected: Mapping[str, Any]
    forbidden_output_terms: tuple[str, ...]
    safety_labels: tuple[str, ...]


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_fd(fd: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while True:
        block = os.pread(fd, 1024 * 1024, offset)
        if not block:
            break
        digest.update(block)
        offset += len(block)
    return digest.hexdigest()


def _load_object(path: Path, *, label: str) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ProviderEvidenceError(f"{label} is not readable valid JSON") from exc
    if not isinstance(value, dict):
        raise ProviderEvidenceError(f"{label} must be a JSON object")
    return value, _sha256_bytes(raw)


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ProviderEvidenceError(f"{label} must use the exact closed schema")


def _require_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderEvidenceError(f"{name} must be a non-empty string")
    return value


def _require_sha(value: object, name: str) -> str:
    result = _require_string(value, name)
    if not _HEX_64.fullmatch(result):
        raise ProviderEvidenceError(f"{name} must be a lowercase SHA-256")
    return result


def _require_nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProviderEvidenceError(f"{name} must be a non-negative integer")
    return value


def _decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ProviderEvidenceError(f"{name} must be a decimal string or number")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ProviderEvidenceError(f"{name} is not a decimal") from exc
    if not result.is_finite() or result < 0:
        raise ProviderEvidenceError(f"{name} must be finite and non-negative")
    return result


def _external_regular_file(value: object, name: str) -> Path:
    path = Path(_require_string(value, name))
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ProviderEvidenceError(
            f"{name} must be an absolute non-symlink regular file"
        )
    resolved = path.resolve()
    for forbidden_root in (WORKSPACE_ROOT, Path("/root")):
        try:
            resolved.relative_to(forbidden_root)
        except ValueError:
            continue
        raise ProviderEvidenceError(f"{name} must remain outside protected roots")
    return resolved


def _load_workload(path: Path = WORKLOAD_PATH) -> tuple[dict[str, Any], str]:
    workload, digest = _load_object(path, label="provider workload")
    if workload.get("format") != "milai-provider-ab-workload-v1":
        raise ProviderEvidenceError("unsupported provider workload format")
    if workload.get("data_boundary") != DATA_BOUNDARY_ACK:
        raise ProviderEvidenceError(
            "provider workload is outside the allowed data boundary"
        )
    if workload.get("required_turn_counts") != [100, 500]:
        raise ProviderEvidenceError(
            "provider workload must retain the frozen 100/500 turn counts"
        )
    period = _require_nonnegative_int(
        workload.get("memory_recall_period"), "memory_recall_period"
    )
    if period < 2:
        raise ProviderEvidenceError("memory_recall_period must be at least two")
    for name in ("memory_cases", "non_memory_cases"):
        cases = workload.get(name)
        if not isinstance(cases, list) or not cases:
            raise ProviderEvidenceError(f"{name} must be a non-empty array")
    _require_string(workload.get("system_instruction"), "system_instruction")
    if (
        _require_nonnegative_int(workload.get("max_output_tokens"), "max_output_tokens")
        <= 0
    ):
        raise ProviderEvidenceError("max_output_tokens must be positive")
    return workload, digest


def _turns(workload: Mapping[str, Any], count: int) -> tuple[TurnSpec, ...]:
    if count <= 0:
        raise ProviderEvidenceError("turn count must be positive")
    period = int(workload["memory_recall_period"])
    memory_cases = workload["memory_cases"]
    non_memory_cases = workload["non_memory_cases"]
    if not isinstance(memory_cases, list) or not isinstance(non_memory_cases, list):
        raise ProviderEvidenceError("workload cases are malformed")
    result: list[TurnSpec] = []
    memory_index = 0
    non_memory_index = 0
    for index in range(count):
        requires_memory = index % period == 0
        cases = memory_cases if requires_memory else non_memory_cases
        case_index = memory_index if requires_memory else non_memory_index
        case = cases[case_index % len(cases)]
        if requires_memory:
            memory_index += 1
        else:
            non_memory_index += 1
        if not isinstance(case, dict):
            raise ProviderEvidenceError("workload case must be an object")
        expected = case.get("expected")
        if not isinstance(expected, dict) or set(expected) != _REPORT_OUTPUT_KEYS:
            raise ProviderEvidenceError(
                "each expected output must have the exact response keys"
            )
        forbidden = case.get("forbidden_output_terms", [])
        safety = case.get("safety_labels", [])
        if not isinstance(forbidden, list) or not all(
            isinstance(item, str) for item in forbidden
        ):
            raise ProviderEvidenceError("forbidden_output_terms must be strings")
        if not isinstance(safety, list) or not all(
            isinstance(item, str) for item in safety
        ):
            raise ProviderEvidenceError("safety_labels must be strings")
        result.append(
            TurnSpec(
                turn_index=index,
                case_id=_require_string(case.get("case_id"), "case_id"),
                requires_memory=requires_memory,
                query=_require_string(case.get("query"), "query"),
                baseline_memory=str(case.get("baseline_memory", "")),
                optimized_memory=str(case.get("optimized_memory", "")),
                expected=expected,
                forbidden_output_terms=tuple(forbidden),
                safety_labels=tuple(safety),
            )
        )
    return tuple(result)


def _shipped_tool_catalog(profile: str) -> tuple[dict[str, Any], ...]:
    sdk = str(SDK_SOURCE)
    if sdk not in sys.path:
        sys.path.insert(0, sdk)
    from milai_client.models import AgentRecallPolicy
    from milai_client.tools import create_milai_tools

    policy = AgentRecallPolicy(
        scope={"project": "synthetic-milai"},
        authority="ACTION_SAFE",
        consistency_floor="CANONICAL_REQUIRED",
        max_limit=3,
    )
    tools = create_milai_tools(
        client=cast(Any, object()), recall_policy=policy, profile=cast(Any, profile)
    )
    return tuple(tool.as_function_schema() for tool in tools)


def _reader_detail_tools() -> tuple[dict[str, Any], ...]:
    return _shipped_tool_catalog("reader")


def _reader_lite_tools() -> tuple[dict[str, Any], ...]:
    return _shipped_tool_catalog("reader-lite")


def _tool_schema_hashes() -> dict[str, str]:
    return {
        "reader": _sha256_bytes(_canonical_bytes(_reader_detail_tools())),
        "reader_lite": _sha256_bytes(_canonical_bytes(_reader_lite_tools())),
    }


def _request_payload(
    workload: Mapping[str, Any],
    workload_sha256: str,
    turn: TurnSpec,
    variant: str,
    provider: str,
    model_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if variant not in {"baseline", "optimized"}:
        raise ProviderEvidenceError("variant must be baseline or optimized")
    if variant == "baseline":
        memory = turn.baseline_memory or (
            "IRRELEVANT CURRENT MEMORY: synthetic project status is green. "
            "TRACE trace-irrelevant."
        )
        tools = _reader_detail_tools()
    else:
        memory = turn.optimized_memory if turn.requires_memory else ""
        tools = _reader_lite_tools() if turn.requires_memory else ()
    user_content = f"TASK:\n{turn.query}"
    if memory:
        user_content += f"\n\n<MILAI_MEMORY_DATA>\n{memory}\n</MILAI_MEMORY_DATA>"
    messages = (
        {"role": "system", "content": str(workload["system_instruction"])},
        {"role": "user", "content": user_content},
    )
    request_id = (
        "oe-ab-"
        + _sha256_bytes(
            _canonical_bytes(
                {
                    "workload_sha256": workload_sha256,
                    "provider": provider,
                    "model_id": model_id,
                    "turn_index": turn.turn_index,
                    "case_id": turn.case_id,
                    "variant": variant,
                }
            )
        )[:32]
    )
    request = {
        "op": "model_call",
        "protocol": ADAPTER_PROTOCOL,
        "request_id": request_id,
        "provider": provider,
        "model_id": model_id,
        "variant": variant,
        "turn_index": turn.turn_index,
        "case_id": turn.case_id,
        "messages": messages,
        "tools": tools,
        "temperature": workload["temperature"],
        "max_output_tokens": workload["max_output_tokens"],
    }
    private = {
        "memory_context": memory,
        "expected": turn.expected,
        "forbidden_output_terms": turn.forbidden_output_terms,
        "safety_labels": turn.safety_labels,
        "prompt_sha256": _sha256_bytes(_canonical_bytes(messages)),
        "tool_schema_sha256": _sha256_bytes(_canonical_bytes(tools)),
    }
    return request, private


def _adapter_environment(
    secret_names: tuple[str, ...], *, require_values: bool
) -> tuple[dict[str, str], tuple[str, ...]]:
    result: dict[str, str] = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    secret_values: set[str] = set()
    sensitive_name_parts = (
        "KEY",
        "TOKEN",
        "SECRET",
        "PASSWORD",
        "CREDENTIAL",
        "COOKIE",
        *_CANONICAL_ENV_MARKERS,
    )
    for environment_name, environment_value in os.environ.items():
        if (
            environment_value
            and len(environment_value) >= 8
            and (
                environment_name.startswith("PG")
                or any(part in environment_name for part in sensitive_name_parts)
            )
        ):
            secret_values.add(environment_value)
    local_env = ROOT / "runtime" / ".env"
    if local_env.is_file():
        try:
            local_env_lines = local_env.read_text(encoding="utf-8").splitlines()
        except OSError:
            local_env_lines = []
        for line in local_env_lines:
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            environment_name, environment_value = line.split("=", 1)
            environment_value = environment_value.strip().strip('"').strip("'")
            if (
                environment_value
                and len(environment_value) >= 8
                and (
                    environment_name.startswith("PG")
                    or any(part in environment_name for part in sensitive_name_parts)
                )
            ):
                secret_values.add(environment_value)
    for name in secret_names:
        provider_secret = os.environ.get(name)
        if not provider_secret:
            if require_values:
                raise ProviderEvidenceError(
                    f"required secret environment variable is absent: {name}"
                )
            continue
        if len(provider_secret) < 8:
            raise ProviderEvidenceError(
                "provider secret values must be at least eight characters"
            )
        result[name] = provider_secret
        secret_values.add(provider_secret)
    return result, tuple(sorted(secret_values))


def _dependency_lock(path: Path, expected_sha: str, runtime_sha: str) -> dict[str, Any]:
    value, digest = _load_object(path, label="adapter dependency lock")
    if digest != expected_sha:
        raise ProviderEvidenceError("adapter dependency lock hash mismatch")
    _exact_keys(
        value, {"format", "runtime_executable_sha256", "files"}, "dependency lock"
    )
    if value.get("format") != "milai-provider-dependency-lock-v1":
        raise ProviderEvidenceError("unsupported dependency lock format")
    if value.get("runtime_executable_sha256") != runtime_sha:
        raise ProviderEvidenceError("dependency lock runtime mismatch")
    files = value.get("files")
    if not isinstance(files, list):
        raise ProviderEvidenceError("dependency lock files must be an array")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            raise ProviderEvidenceError("dependency lock entry must be an object")
        _exact_keys(item, {"path", "sha256"}, f"dependency lock files[{index}]")
        dependency = _external_regular_file(item.get("path"), "dependency path")
        expected = _require_sha(item.get("sha256"), "dependency sha256")
        if str(dependency) in seen:
            raise ProviderEvidenceError("dependency lock paths must be unique")
        seen.add(str(dependency))
        if _sha256_file(dependency) != expected:
            raise ProviderEvidenceError("dependency file hash mismatch")
        normalized.append({"path": str(dependency), "sha256": expected})
    return {
        "format": value["format"],
        "runtime_executable_sha256": runtime_sha,
        "files": normalized,
    }


def _host_tool_paths() -> tuple[Path, dict[str, Path | None]]:
    unshare = Path(shutil.which("unshare", path=HOST_TOOL_SEARCH_PATH) or "").resolve()
    if not unshare.is_file():
        raise ProviderEvidenceError("unshare executable is unavailable")
    network_tools: dict[str, Path | None] = {}
    for tool in ("slirp4netns", "nsenter", "nft", "ip"):
        resolved = shutil.which(tool, path=HOST_TOOL_SEARCH_PATH)
        network_tools[tool] = None if resolved is None else Path(resolved).resolve()
    return unshare, network_tools


def _sandbox_python_import_files() -> tuple[Path, ...]:
    """Enumerate the launcher's file-backed imports under the exact sandbox Python."""
    try:
        tree = ast.parse(SANDBOX_LAUNCHER.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise ProviderEvidenceError(
            "sandbox launcher imports are not inspectable"
        ) from exc
    top_level_imports = {
        id(node) for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
    }
    all_imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    if any(id(node) not in top_level_imports for node in all_imports):
        raise ProviderEvidenceError(
            "sandbox launcher must keep every import at module scope for closure tracing"
        )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if (
            isinstance(function, ast.Name)
            and function.id == "__import__"
            or isinstance(function, ast.Attribute)
            and function.attr == "import_module"
        ):
            raise ProviderEvidenceError(
                "sandbox launcher dynamic imports are forbidden"
            )
    probe = f"""
import importlib.util
import os
import sys
launcher = {str(SANDBOX_LAUNCHER)!r}
spec = importlib.util.spec_from_file_location('_milai_sandbox_closure_probe', launcher)
if spec is None or spec.loader is None:
    raise SystemExit(91)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
paths = set()
for loaded in tuple(sys.modules.values()):
    for attribute in ('__file__', '__cached__'):
        raw = getattr(loaded, attribute, None)
        if raw:
            resolved = os.path.realpath(raw)
            if os.path.isfile(resolved):
                paths.add(resolved)
for resolved in sorted(paths):
    print(resolved)
"""
    completed = subprocess.run(
        [str(SANDBOX_RUNTIME), "-I", "-S", "-B", "-c", probe],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
    )
    if completed.returncode != 0 or completed.stderr:
        raise ProviderEvidenceError("sandbox Python import closure probe failed")
    paths = tuple(
        sorted(
            {
                Path(line).resolve()
                for line in completed.stdout.splitlines()
                if line and Path(line).resolve().is_file()
            },
            key=str,
        )
    )
    if not paths:
        raise ProviderEvidenceError("sandbox Python import closure is empty")
    return paths


def _elf_dependencies(path: Path) -> tuple[Path, ...]:
    try:
        with path.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                return ()
    except OSError as exc:
        raise ProviderEvidenceError("host execution file became unreadable") from exc
    ldd = next(
        (
            candidate
            for candidate in (Path("/usr/bin/ldd"), Path("/bin/ldd"))
            if candidate.is_file()
        ),
        None,
    )
    if ldd is None:
        raise ProviderEvidenceError("host ELF dependency enumerator is unavailable")
    completed = subprocess.run(
        [str(ldd), str(path)],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
    )
    combined = completed.stdout + completed.stderr
    if "not found" in combined:
        raise ProviderEvidenceError("host executable has an unresolved ELF dependency")
    if completed.returncode != 0:
        if "not a dynamic executable" in combined or "statically linked" in combined:
            return ()
        raise ProviderEvidenceError("host ELF dependency closure could not be resolved")
    dependencies: set[Path] = set()
    for line in completed.stdout.splitlines():
        candidate = line.split("=>", 1)[1].strip() if "=>" in line else line.strip()
        if not candidate.startswith("/"):
            continue
        raw_path = candidate.split(None, 1)[0]
        resolved = Path(raw_path).resolve()
        if not resolved.is_file():
            raise ProviderEvidenceError("host ELF dependency is not a regular file")
        dependencies.add(resolved)
    return tuple(sorted(dependencies, key=str))


def build_host_execution_lock() -> dict[str, Any]:
    """Build the independently reproducible privileged execution-byte closure."""
    unshare, network_tools = _host_tool_paths()
    roles: dict[Path, set[str]] = defaultdict(set)

    def add(path: Path, role: str) -> None:
        resolved = path.resolve()
        if not resolved.is_file() or resolved.is_symlink():
            raise ProviderEvidenceError("host execution closure contains a non-file")
        roles[resolved].add(role)

    add(SANDBOX_LAUNCHER, "sandbox-launcher")
    add(SANDBOX_RUNTIME, "sandbox-runtime")
    add(unshare, "namespace-helper:unshare")
    for name, path in network_tools.items():
        if path is not None:
            add(path, f"network-helper:{name}")
    for path in _sandbox_python_import_files():
        add(path, "sandbox-python-import")

    pending = list(roles)
    inspected: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in inspected:
            continue
        inspected.add(path)
        for dependency in _elf_dependencies(path):
            is_new = dependency not in roles
            add(dependency, "dynamic-dependency")
            if is_new:
                pending.append(dependency)

    files = [
        {
            "path": str(path),
            "size": path.stat().st_size,
            "sha256": _sha256_file(path),
            "roles": sorted(roles[path]),
        }
        for path in sorted(roles, key=str)
    ]
    uname = os.uname()
    return {
        "format": "milai-provider-host-execution-lock-v1",
        "policy": HOST_EXECUTION_POLICY,
        "platform": {
            "sysname": uname.sysname,
            "release": uname.release,
            "machine": uname.machine,
            "python_cache_tag": sys.implementation.cache_tag,
        },
        "file_count": len(files),
        "entries_sha256": _sha256_bytes(_canonical_bytes(files)),
        "files": files,
    }


def _host_execution_lock(path: Path, expected_sha: str) -> dict[str, Any]:
    value, digest = _load_object(path, label="host execution lock")
    if digest != expected_sha:
        raise ProviderEvidenceError("host execution lock hash mismatch")
    _exact_keys(
        value,
        {"format", "policy", "platform", "file_count", "entries_sha256", "files"},
        "host execution lock",
    )
    if (
        value.get("format") != "milai-provider-host-execution-lock-v1"
        or value.get("policy") != HOST_EXECUTION_POLICY
    ):
        raise ProviderEvidenceError("unsupported host execution lock")
    expected = build_host_execution_lock()
    if value != expected:
        raise ProviderEvidenceError(
            "host execution lock does not match the independently enumerated closure"
        )
    return expected


def _manifest(
    path: Path,
    *,
    expected_approval_sha256: str,
    require_secret_values: bool = True,
) -> tuple[dict[str, Any], str, dict[str, str], tuple[str, ...]]:
    value, digest = _load_object(path, label="adapter manifest")
    expected_keys = {
        "format",
        "provider",
        "provider_origin",
        "model_id",
        "tokenizer_id",
        "runtime_executable_path",
        "runtime_executable_sha256",
        "adapter_source_path",
        "adapter_source_sha256",
        "dependency_lock_path",
        "dependency_lock_sha256",
        "host_execution_lock_path",
        "host_execution_lock_sha256",
        "secret_environment_names",
        "egress_mode",
        "provider_ip_addresses",
        "run_as_uid",
        "run_as_gid",
        "approval_path",
    }
    _exact_keys(value, expected_keys, "adapter manifest")
    if value.get("format") != "milai-provider-adapter-manifest-v3":
        raise ProviderEvidenceError("unsupported adapter manifest format")
    provider = _require_string(value.get("provider"), "manifest provider")
    origin = _require_string(value.get("provider_origin"), "manifest provider_origin")
    parsed_origin = urlsplit(origin)
    try:
        origin_port = parsed_origin.port
    except ValueError as exc:
        raise ProviderEvidenceError("provider_origin contains an invalid port") from exc
    if (
        parsed_origin.scheme != "https"
        or parsed_origin.hostname is None
        or parsed_origin.path
        or parsed_origin.query
        or parsed_origin.fragment
        or parsed_origin.username is not None
        or parsed_origin.password is not None
        or origin_port not in (None, 443)
    ):
        raise ProviderEvidenceError(
            "provider_origin must be one HTTPS origin without a path"
        )
    model_id = _require_string(value.get("model_id"), "manifest model_id")
    tokenizer_id = _require_string(value.get("tokenizer_id"), "manifest tokenizer_id")
    runtime = _external_regular_file(
        value.get("runtime_executable_path"), "runtime_executable_path"
    )
    runtime_sha = _require_sha(
        value.get("runtime_executable_sha256"), "runtime_executable_sha256"
    )
    if _sha256_file(runtime) != runtime_sha:
        raise ProviderEvidenceError("adapter runtime hash mismatch")
    source = _external_regular_file(
        value.get("adapter_source_path"), "adapter_source_path"
    )
    source_sha = _require_sha(
        value.get("adapter_source_sha256"), "adapter_source_sha256"
    )
    if _sha256_file(source) != source_sha:
        raise ProviderEvidenceError("adapter source hash mismatch")
    lock_path = _external_regular_file(
        value.get("dependency_lock_path"), "dependency_lock_path"
    )
    lock_sha = _require_sha(
        value.get("dependency_lock_sha256"), "dependency_lock_sha256"
    )
    lock = _dependency_lock(lock_path, lock_sha, runtime_sha)
    host_lock_path = _external_regular_file(
        value.get("host_execution_lock_path"), "host_execution_lock_path"
    )
    host_lock_sha = _require_sha(
        value.get("host_execution_lock_sha256"), "host_execution_lock_sha256"
    )
    host_lock = _host_execution_lock(host_lock_path, host_lock_sha)
    secret_names_value = value.get("secret_environment_names")
    if not isinstance(secret_names_value, list) or not secret_names_value:
        raise ProviderEvidenceError(
            "secret_environment_names must be a non-empty array"
        )
    if not all(
        isinstance(name, str) and _PROVIDER_CREDENTIAL_NAME.fullmatch(name)
        for name in secret_names_value
    ):
        raise ProviderEvidenceError(
            "provider secrets must use the isolated "
            "MILAI_PROVIDER_CREDENTIAL_* namespace"
        )
    secret_names = tuple(cast(list[str], secret_names_value))
    if len(set(secret_names)) != len(secret_names):
        raise ProviderEvidenceError("secret environment variable names must be unique")
    egress_mode = value.get("egress_mode")
    if egress_mode not in {"deny-all", "https-origin-ip-allowlist"}:
        raise ProviderEvidenceError("egress_mode must use a closed policy")
    address_values = value.get("provider_ip_addresses")
    if not isinstance(address_values, list) or not all(
        isinstance(address, str) for address in address_values
    ):
        raise ProviderEvidenceError("provider_ip_addresses must be an array")
    try:
        addresses = tuple(
            str(ipaddress.ip_address(address)) for address in address_values
        )
    except ValueError as exc:
        raise ProviderEvidenceError(
            "provider_ip_addresses contains an invalid IP"
        ) from exc
    if len(set(addresses)) != len(addresses) or list(addresses) != sorted(addresses):
        raise ProviderEvidenceError("provider_ip_addresses must be sorted and unique")
    if (egress_mode == "deny-all") != (not addresses):
        raise ProviderEvidenceError(
            "deny-all requires no addresses; HTTPS allowlist requires addresses"
        )
    uid = _require_nonnegative_int(value.get("run_as_uid"), "run_as_uid")
    gid = _require_nonnegative_int(value.get("run_as_gid"), "run_as_gid")
    if uid == 0 or gid == 0 or uid == os.geteuid() or gid == os.getegid():
        raise ProviderEvidenceError(
            "provider adapter must run as a distinct non-root uid/gid"
        )
    approval_path = _external_regular_file(value.get("approval_path"), "approval_path")
    approval, approval_sha = _load_object(approval_path, label="provider approval")
    expected_approval_sha = _require_sha(
        expected_approval_sha256, "expected approval SHA-256"
    )
    if approval_sha != expected_approval_sha:
        raise ProviderEvidenceError(
            "provider approval does not match the out-of-band digest"
        )
    approval_keys = {
        "format",
        "provider",
        "provider_origin",
        "model_id",
        "tokenizer_id",
        "data_boundary",
        "manifest_sha256",
        "workload_sha256",
        "pricing_snapshot_sha256",
        "runtime_executable_sha256",
        "adapter_source_sha256",
        "dependency_lock_sha256",
        "host_execution_lock_sha256",
        "host_execution_entries_sha256",
        "host_execution_file_count",
        "host_execution_policy",
        "sandbox_launcher_sha256",
        "sandbox_runtime_sha256",
        "unshare_executable_sha256",
        "slirp4netns_executable_sha256",
        "nsenter_executable_sha256",
        "nft_executable_sha256",
        "ip_executable_sha256",
        "sandbox_file_policy",
        "minimum_landlock_abi",
        "reader_tool_schema_sha256",
        "reader_lite_tool_schema_sha256",
        "secret_environment_names",
        "egress_mode",
        "provider_ip_addresses",
        "run_as_uid",
        "run_as_gid",
        "max_provider_requests",
        "max_input_tokens_per_request",
        "max_output_tokens_per_request",
        "max_cost_usd",
        "billing_tolerance_usd",
        "approved_by",
        "approved_at",
    }
    _exact_keys(approval, approval_keys, "provider approval")
    if approval.get("format") != "milai-provider-approval-v3":
        raise ProviderEvidenceError("unsupported provider approval format")
    if (
        approval.get("sandbox_file_policy") != SANDBOX_FILE_POLICY
        or _require_nonnegative_int(
            approval.get("minimum_landlock_abi"), "minimum_landlock_abi"
        )
        != MINIMUM_LANDLOCK_ABI
    ):
        raise ProviderEvidenceError("unsupported sandbox file-access policy")
    workload, workload_sha = _load_workload()
    tool_hashes = _tool_schema_hashes()
    unshare, network_tools = _host_tool_paths()
    network_tool_hashes = {
        f"{tool}_executable_sha256": (None if path is None else _sha256_file(path))
        for tool, path in network_tools.items()
    }
    if egress_mode == "https-origin-ip-allowlist" and any(
        path is None for path in network_tools.values()
    ):
        raise ProviderEvidenceError("approved egress sandbox tools are unavailable")
    matches: dict[str, object] = {
        "provider": provider,
        "provider_origin": origin,
        "model_id": model_id,
        "tokenizer_id": tokenizer_id,
        "data_boundary": DATA_BOUNDARY_ACK,
        "manifest_sha256": digest,
        "workload_sha256": workload_sha,
        "runtime_executable_sha256": runtime_sha,
        "adapter_source_sha256": source_sha,
        "dependency_lock_sha256": lock_sha,
        "host_execution_lock_sha256": host_lock_sha,
        "host_execution_entries_sha256": host_lock["entries_sha256"],
        "host_execution_file_count": host_lock["file_count"],
        "host_execution_policy": HOST_EXECUTION_POLICY,
        "sandbox_launcher_sha256": _sha256_file(SANDBOX_LAUNCHER),
        "sandbox_runtime_sha256": _sha256_file(SANDBOX_RUNTIME),
        "unshare_executable_sha256": _sha256_file(unshare),
        **network_tool_hashes,
        "sandbox_file_policy": SANDBOX_FILE_POLICY,
        "minimum_landlock_abi": MINIMUM_LANDLOCK_ABI,
        "reader_tool_schema_sha256": tool_hashes["reader"],
        "reader_lite_tool_schema_sha256": tool_hashes["reader_lite"],
        "secret_environment_names": list(secret_names),
        "egress_mode": egress_mode,
        "provider_ip_addresses": list(addresses),
        "run_as_uid": uid,
        "run_as_gid": gid,
        "max_provider_requests": REQUIRED_PROVIDER_REQUESTS,
        "max_output_tokens_per_request": workload["max_output_tokens"],
    }
    for name, expected in matches.items():
        if approval.get(name) != expected:
            raise ProviderEvidenceError(f"provider approval mismatch: {name}")
    _require_sha(approval.get("pricing_snapshot_sha256"), "pricing_snapshot_sha256")
    _require_string(approval.get("approved_by"), "approval approved_by")
    _require_string(approval.get("approved_at"), "approval approved_at")
    approved_input = _require_nonnegative_int(
        approval.get("max_input_tokens_per_request"), "max_input_tokens_per_request"
    )
    approved_cost = _decimal(approval.get("max_cost_usd"), "max_cost_usd")
    tolerance = _decimal(approval.get("billing_tolerance_usd"), "billing_tolerance_usd")
    if (
        approved_input <= 0
        or approved_cost <= 0
        or tolerance > approved_cost / Decimal(100)
    ):
        raise ProviderEvidenceError(
            "approval limits are invalid or billing tolerance exceeds one percent"
        )
    environment, secret_values = _adapter_environment(
        secret_names, require_values=require_secret_values
    )
    normalized = dict(value)
    normalized.update(
        {
            "provider": provider,
            "provider_origin": origin,
            "model_id": model_id,
            "tokenizer_id": tokenizer_id,
            "runtime_path": runtime,
            "source_path": source,
            "lock_path": lock_path,
            "dependency_lock": lock,
            "host_lock_path": host_lock_path,
            "host_execution_lock": host_lock,
            "approval": dict(approval, sha256=approval_sha),
            "approval_sha256": approval_sha,
            "unshare_path": unshare,
            "network_tool_paths": network_tools,
            "provider_origin_host": parsed_origin.hostname,
            "provider_ip_addresses": addresses,
        }
    )
    return normalized, digest, environment, secret_values


def _pricing(
    path: Path, provider: str, model_id: str
) -> tuple[Pricing, dict[str, Any]]:
    value, digest = _load_object(path, label="pricing snapshot")
    _exact_keys(
        value,
        {
            "format",
            "provider",
            "model_id",
            "currency",
            "effective_at",
            "source_url",
            "input_per_million",
            "cached_input_per_million",
            "output_per_million",
        },
        "pricing snapshot",
    )
    if value.get("format") != "milai-provider-pricing-snapshot-v1":
        raise ProviderEvidenceError("unsupported provider pricing snapshot format")
    if value.get("provider") != provider or value.get("model_id") != model_id:
        raise ProviderEvidenceError("pricing identity does not match adapter identity")
    currency = _require_string(value.get("currency"), "pricing currency")
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ProviderEvidenceError("pricing currency must use three uppercase letters")
    _require_string(value.get("effective_at"), "pricing effective_at")
    source_url = _require_string(value.get("source_url"), "pricing source_url")
    if not source_url.startswith("https://"):
        raise ProviderEvidenceError("pricing source_url must use HTTPS")
    pricing = Pricing(
        currency=currency,
        input_per_million=_decimal(value.get("input_per_million"), "input_per_million"),
        cached_input_per_million=_decimal(
            value.get("cached_input_per_million"), "cached_input_per_million"
        ),
        output_per_million=_decimal(
            value.get("output_per_million"), "output_per_million"
        ),
        snapshot_sha256=digest,
    )
    public = {
        "provider": provider,
        "model_id": model_id,
        "currency": currency,
        "effective_at": value["effective_at"],
        "source_url": source_url,
        "sha256": digest,
        "rates_per_million": {
            "input": str(pricing.input_per_million),
            "cached_input": str(pricing.cached_input_per_million),
            "output": str(pricing.output_per_million),
        },
    }
    return pricing, public


def _assert_no_secret_reflection(value: object, secret_values: Sequence[str]) -> None:
    if isinstance(value, str):
        if any(secret and secret in value for secret in secret_values):
            raise ProviderEvidenceError(
                "adapter response contains a supplied secret value"
            )
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _assert_no_secret_reflection(key, secret_values)
            _assert_no_secret_reflection(item, secret_values)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for item in value:
            _assert_no_secret_reflection(item, secret_values)


class AdapterProcess:
    def __init__(
        self,
        manifest: Mapping[str, Any],
        environment: Mapping[str, str],
        secret_values: Sequence[str],
        *,
        timeout_seconds: float,
    ) -> None:
        self._manifest = manifest
        self._environment = dict(environment)
        self._secret_values = tuple(secret_values)
        self._timeout_seconds = timeout_seconds
        self._process: subprocess.Popen[bytes] | None = None
        self._selector: selectors.BaseSelector | None = None
        self._buffer = bytearray()
        self._fds: list[int] = []
        self._host_fds: list[tuple[int, Path, str, int, int, int]] = []
        self._host_execution_preverified = False
        self._host_execution_revalidated = False
        self._expected_execution_hashes: tuple[str, ...] = ()
        self._network_tool_fds: dict[str, int] = {}
        self._network_process: subprocess.Popen[bytes] | None = None
        self._start_gate: tuple[int, int] | None = None

    def __enter__(self) -> Self:
        try:
            return self._enter()
        except BaseException:
            self.__exit__()
            raise

    def _enter(self) -> Self:
        if os.geteuid() != 0:
            raise ProviderEvidenceError("provider sandbox requires a root launcher")
        uid = int(self._manifest["run_as_uid"])
        gid = int(self._manifest["run_as_gid"])
        environment = dict(self._environment)
        environment.update(
            {
                "HOME": "/tmp/milai-provider/home",
                "TMPDIR": "/tmp/milai-provider/cwd",
                "XDG_CACHE_HOME": "/tmp/milai-provider/cwd/cache",
                "XDG_CONFIG_HOME": "/tmp/milai-provider/cwd/config",
            }
        )

        def open_approved(path: Path) -> int:
            descriptor = os.open(path, os.O_RDONLY)
            self._fds.append(descriptor)
            return descriptor

        for item in self._manifest["host_execution_lock"]["files"]:
            host_path = Path(item["path"])
            descriptor = os.open(
                host_path,
                os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            )
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                os.close(descriptor)
                raise ProviderEvidenceError(
                    "host execution closure entry is not regular"
                )
            self._host_fds.append(
                (
                    descriptor,
                    host_path,
                    str(item["sha256"]),
                    opened.st_dev,
                    opened.st_ino,
                    opened.st_size,
                )
            )
        if any(
            _sha256_fd(descriptor) != expected
            for descriptor, _path, expected, _dev, _ino, _size in self._host_fds
        ):
            raise ProviderEvidenceError(
                "opened host execution bytes do not match the approved closure"
            )
        self._host_execution_preverified = True

        runtime_fd = open_approved(cast(Path, self._manifest["runtime_path"]))
        source_fd = open_approved(cast(Path, self._manifest["source_path"]))
        launcher_fd = open_approved(SANDBOX_LAUNCHER)
        sandbox_runtime_fd = open_approved(SANDBOX_RUNTIME)
        unshare_fd = open_approved(cast(Path, self._manifest["unshare_path"]))
        self._network_tool_fds = {
            name: open_approved(path)
            for name, path in self._manifest["network_tool_paths"].items()
            if path is not None
        }
        dependency_fds = [
            open_approved(Path(item["path"]))
            for item in self._manifest["dependency_lock"]["files"]
        ]
        self._start_gate = os.pipe()
        start_gate_read, start_gate_write = self._start_gate
        expected = (
            str(self._manifest["runtime_executable_sha256"]),
            str(self._manifest["adapter_source_sha256"]),
            str(self._manifest["approval"]["sandbox_launcher_sha256"]),
            str(self._manifest["approval"]["sandbox_runtime_sha256"]),
            str(self._manifest["approval"]["unshare_executable_sha256"]),
            *(
                str(self._manifest["approval"][f"{name}_executable_sha256"])
                for name in self._network_tool_fds
            ),
            *(
                str(item["sha256"])
                for item in self._manifest["dependency_lock"]["files"]
            ),
        )
        self._expected_execution_hashes = expected
        if tuple(_sha256_fd(fd) for fd in self._fds) != expected:
            raise ProviderEvidenceError(
                "opened execution bytes do not match approved hashes"
            )
        command = [
            f"/proc/self/fd/{unshare_fd}",
            "--mount",
            "--pid",
            "--net",
            "--mount-proc",
            "--fork",
            "--kill-child",
            "--",
            f"/proc/self/fd/{sandbox_runtime_fd}",
            "-I",
            "-S",
            "-B",
            f"/proc/self/fd/{launcher_fd}",
            "--uid",
            str(uid),
            "--gid",
            str(gid),
            "--workspace-root",
            str(WORKSPACE_ROOT),
            "--provider-host",
            str(self._manifest["provider_origin_host"]),
            "--runtime-fd",
            str(runtime_fd),
            "--source-fd",
            str(source_fd),
            "--start-gate-fd",
            str(start_gate_read),
        ]
        for hidden in (
            "/root",
            "/home",
            "/run",
            "/var/lib",
            "/var/log",
            "/var/tmp",
            "/srv",
            "/mnt",
            "/media",
            "/opt",
            "/dev/shm",
        ):
            command.extend(["--hidden-root", hidden])
        for address in self._manifest["provider_ip_addresses"]:
            command.extend(["--provider-ip", str(address)])
        for fd, item in zip(
            dependency_fds,
            self._manifest["dependency_lock"]["files"],
            strict=True,
        ):
            command.extend(["--dependency", str(fd), str(item["path"])])
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
            pass_fds=(*self._fds, start_gate_read),
            start_new_session=True,
        )
        if self._process.stdout is None:
            raise ProviderEvidenceError("adapter stdout was not created")
        if self._process.stdin is None:
            raise ProviderEvidenceError("adapter stdin was not created")
        os.set_blocking(self._process.stdin.fileno(), False)
        os.set_blocking(self._process.stdout.fileno(), False)
        self._selector = selectors.DefaultSelector()
        self._selector.register(self._process.stdout, selectors.EVENT_READ)
        self._configure_network()
        os.write(start_gate_write, b"1")
        os.close(start_gate_write)
        os.close(start_gate_read)
        self._start_gate = None
        return self

    def _configure_network(self) -> None:
        process = self._process
        if process is None:
            raise ProviderEvidenceError("provider sandbox process is unavailable")
        if self._manifest["egress_mode"] == "deny-all":
            return
        required = ("slirp4netns", "nsenter", "nft", "ip")
        if any(name not in self._network_tool_fds for name in required):
            raise ProviderEvidenceError("approved egress sandbox tools are unavailable")
        slirp_fd = self._network_tool_fds["slirp4netns"]
        nsenter_fd = self._network_tool_fds["nsenter"]
        nft_fd = self._network_tool_fds["nft"]
        ip_fd = self._network_tool_fds["ip"]
        slirp = f"/proc/self/fd/{slirp_fd}"
        nsenter = f"/proc/self/fd/{nsenter_fd}"
        nft = f"/proc/self/fd/{nft_fd}"
        ip = f"/proc/self/fd/{ip_fd}"
        self._network_process = subprocess.Popen(
            [slirp, "--configure", "--mtu=65520", str(process.pid), "tap0"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            pass_fds=(slirp_fd,),
        )
        deadline = monotonic() + 8
        while monotonic() < deadline:
            probe = subprocess.run(
                [nsenter, "-t", str(process.pid), "-n", ip, "link", "show", "tap0"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                pass_fds=(nsenter_fd, ip_fd),
            )
            if probe.returncode == 0:
                break
            if self._network_process.poll() is not None:
                raise ProviderEvidenceError("approved egress transport failed to start")
            sleep(0.02)
        else:
            raise ProviderEvidenceError("approved egress transport timed out")
        addresses = cast(Sequence[str], self._manifest["provider_ip_addresses"])
        ipv4 = sorted(address for address in addresses if ":" not in address)
        ipv6 = sorted(address for address in addresses if ":" in address)
        rules = [
            "table inet milai_provider {",
            "chain output { type filter hook output priority 0; policy drop;",
            'oifname "lo" accept',
            "ct state established,related accept",
        ]
        if ipv4:
            rules.append(f"ip daddr {{ {', '.join(ipv4)} }} tcp dport 443 accept")
        if ipv6:
            rules.append(f"ip6 daddr {{ {', '.join(ipv6)} }} tcp dport 443 accept")
        rules.extend(["}", "}"])
        configured = subprocess.run(
            [nsenter, "-t", str(process.pid), "-n", nft, "-f", "-"],
            input=("\n".join(rules) + "\n").encode("ascii"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            pass_fds=(nsenter_fd, nft_fd),
        )
        if configured.returncode != 0:
            raise ProviderEvidenceError("approved egress firewall configuration failed")

    def exchange(self, request: Mapping[str, Any]) -> dict[str, Any]:
        process = self._process
        selector = self._selector
        if (
            process is None
            or selector is None
            or process.stdin is None
            or process.stdout is None
        ):
            raise ProviderEvidenceError("adapter process is not running")
        if process.poll() is not None:
            raise ProviderEvidenceError("adapter exited before request")
        encoded = _canonical_bytes(request) + b"\n"
        deadline = monotonic() + self._timeout_seconds
        input_fd = process.stdin.fileno()
        offset = 0
        with selectors.DefaultSelector() as writer:
            writer.register(input_fd, selectors.EVENT_WRITE)
            while offset < len(encoded):
                remaining = deadline - monotonic()
                if remaining <= 0 or not writer.select(remaining):
                    self._terminate_group()
                    raise ProviderEvidenceError("adapter input timed out")
                try:
                    written = os.write(input_fd, encoded[offset:])
                except BlockingIOError:
                    continue
                except (BrokenPipeError, OSError) as exc:
                    raise ProviderEvidenceError("adapter input failed") from exc
                if written <= 0:
                    raise ProviderEvidenceError("adapter input made no progress")
                offset += written
        while b"\n" not in self._buffer:
            remaining = deadline - monotonic()
            if remaining <= 0:
                self._terminate_group()
                raise ProviderEvidenceError("adapter response timed out")
            if not selector.select(remaining):
                self._terminate_group()
                raise ProviderEvidenceError("adapter response timed out")
            try:
                block = os.read(process.stdout.fileno(), 65_536)
            except BlockingIOError:
                continue
            if not block:
                raise ProviderEvidenceError("adapter closed stdout without a response")
            self._buffer.extend(block)
            if len(self._buffer) > MAX_RESPONSE_BYTES:
                self._terminate_group()
                raise ProviderEvidenceError(
                    "adapter response exceeds the two-megabyte limit"
                )
        raw, _, remainder = self._buffer.partition(b"\n")
        self._buffer = bytearray(remainder)
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderEvidenceError("adapter response is not JSON") from exc
        if not isinstance(value, dict):
            raise ProviderEvidenceError("adapter response must be a JSON object")
        _assert_no_secret_reflection(value, self._secret_values)
        return value

    def _terminate_group(self) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=0.5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=1)

    def _stop_network_helper(self) -> bool:
        helper = self._network_process
        if helper is None:
            return True
        try:
            if helper.poll() is None:
                try:
                    os.killpg(helper.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    helper.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(helper.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    helper.wait(timeout=1)
        except (OSError, subprocess.SubprocessError):
            return False
        stopped = helper.poll() is not None
        if stopped:
            self._network_process = None
        return stopped

    def host_execution_evidence(self) -> dict[str, Any]:
        host_lock = self._manifest["host_execution_lock"]
        return {
            "policy": host_lock["policy"],
            "file_count": host_lock["file_count"],
            "entries_sha256": host_lock["entries_sha256"],
            "pre_execution_verified": self._host_execution_preverified,
            "post_execution_revalidated": self._host_execution_revalidated,
        }

    def __exit__(self, *_args: object) -> None:
        process = self._process
        if self._start_gate is not None:
            for fd in self._start_gate:
                try:
                    os.close(fd)
                except OSError:
                    pass
            self._start_gate = None
        try:
            if (
                process is not None
                and process.poll() is None
                and process.stdin is not None
            ):
                try:
                    os.write(process.stdin.fileno(), b'{"op":"close"}\n')
                    process.wait(timeout=2)
                except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                    self._terminate_group()
        finally:
            if self._selector is not None:
                self._selector.close()
            if process is not None:
                if process.stdin is not None:
                    process.stdin.close()
                if process.stdout is not None:
                    process.stdout.close()
            adapter_stopped = process is not None and process.poll() is not None
            network_helper_stopped = self._stop_network_helper()
            execution_bytes_changed = False
            execution_bytes_unreadable = False
            if adapter_stopped and network_helper_stopped and self._fds:
                try:
                    execution_bytes_changed = (
                        tuple(_sha256_fd(fd) for fd in self._fds)
                        != self._expected_execution_hashes
                    )
                except OSError:
                    execution_bytes_unreadable = True
            host_execution_changed = False
            host_execution_unreadable = False
            if adapter_stopped and network_helper_stopped and self._host_fds:
                try:
                    for (
                        descriptor,
                        path,
                        expected,
                        device,
                        inode,
                        size,
                    ) in self._host_fds:
                        opened = os.fstat(descriptor)
                        live = os.stat(path, follow_symlinks=False)
                        if (
                            not stat.S_ISREG(live.st_mode)
                            or opened.st_dev != device
                            or opened.st_ino != inode
                            or opened.st_size != size
                            or live.st_dev != device
                            or live.st_ino != inode
                            or live.st_size != size
                            or _sha256_fd(descriptor) != expected
                            or _sha256_file(path) != expected
                        ):
                            host_execution_changed = True
                            break
                except OSError:
                    host_execution_unreadable = True
                self._host_execution_revalidated = not (
                    host_execution_changed or host_execution_unreadable
                )
            for fd in self._fds:
                try:
                    os.close(fd)
                except OSError:
                    pass
            self._fds = []
            for descriptor, _path, _expected, _dev, _ino, _size in self._host_fds:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            self._host_fds = []
            if not adapter_stopped:
                raise ProviderEvidenceError(
                    "provider sandbox did not stop before final byte revalidation"
                )
            if not network_helper_stopped:
                raise ProviderEvidenceError(
                    "provider network helper did not stop before final byte revalidation"
                )
            if execution_bytes_changed:
                raise ProviderEvidenceError(
                    "executed bytes changed during provider run"
                )
            if execution_bytes_unreadable:
                raise ProviderEvidenceError(
                    "executed bytes could not be revalidated after provider run"
                )
            if host_execution_changed:
                raise ProviderEvidenceError(
                    "host execution closure changed during provider run"
                )
            if host_execution_unreadable:
                raise ProviderEvidenceError(
                    "host execution closure could not be revalidated after provider run"
                )


def _validate_handshake(
    value: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, Any]:
    expected = {
        "op": "handshake",
        "protocol": ADAPTER_PROTOCOL,
        "provider": manifest["provider"],
        "provider_origin": manifest["provider_origin"],
        "model_id": manifest["model_id"],
        "tokenizer_id": manifest["tokenizer_id"],
        "ready": True,
        "usage_source": "native_provider_response",
        "component_token_counting": "target_model_tokenizer",
    }
    _exact_keys(value, set(expected), "adapter handshake")
    if dict(value) != expected:
        raise ProviderEvidenceError("adapter handshake identity mismatch")
    return expected


def _validate_count_result(
    value: Mapping[str, Any], request: Mapping[str, Any], manifest: Mapping[str, Any]
) -> tuple[int, dict[str, Any]]:
    expected_keys = {
        "op",
        "request_id",
        "provider",
        "model_id",
        "tokenizer_id",
        "usage_source",
        "input_tokens",
        "component_tokens",
    }
    _exact_keys(value, expected_keys, "count result")
    fixed = {
        "op": "count_result",
        "request_id": request["request_id"],
        "provider": manifest["provider"],
        "model_id": manifest["model_id"],
        "tokenizer_id": manifest["tokenizer_id"],
        "usage_source": "target_model_tokenizer",
    }
    for name, expected in fixed.items():
        if value.get(name) != expected:
            raise ProviderEvidenceError(f"count result mismatch: {name}")
    input_tokens = _require_nonnegative_int(
        value.get("input_tokens"), "count input_tokens"
    )
    components_value = value.get("component_tokens")
    if not isinstance(components_value, dict):
        raise ProviderEvidenceError("count component_tokens must be an object")
    _exact_keys(
        components_value,
        {"memory_context_tokens", "tool_schema_tokens"},
        "count component_tokens",
    )
    components = {
        "tokenizer_id": manifest["tokenizer_id"],
        "verified": False,
        "memory_context_tokens": _require_nonnegative_int(
            components_value.get("memory_context_tokens"), "memory_context_tokens"
        ),
        "tool_schema_tokens": _require_nonnegative_int(
            components_value.get("tool_schema_tokens"), "tool_schema_tokens"
        ),
    }
    if (
        components["memory_context_tokens"] + components["tool_schema_tokens"]
        > input_tokens
    ):
        raise ProviderEvidenceError(
            "MiLAi component tokens exceed counted input tokens"
        )
    return input_tokens, components


def _usage(value: object, label: str) -> dict[str, int | None]:
    if not isinstance(value, dict):
        raise ProviderEvidenceError(f"{label} must be an object")
    _exact_keys(
        value,
        {"input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens"},
        label,
    )
    result: dict[str, int | None] = {
        name: _require_nonnegative_int(value.get(name), f"{label}.{name}")
        for name in ("input_tokens", "cached_input_tokens", "output_tokens")
    }
    reasoning = value.get("reasoning_tokens")
    result["reasoning_tokens"] = (
        None
        if reasoning is None
        else _require_nonnegative_int(reasoning, f"{label}.reasoning_tokens")
    )
    if int(result["cached_input_tokens"] or 0) > int(result["input_tokens"] or 0):
        raise ProviderEvidenceError(f"{label} cached input exceeds input")
    return result


def _sum_usage(values: Sequence[Mapping[str, int | None]]) -> dict[str, int | None]:
    result: dict[str, int | None] = {
        name: sum(int(value[name] or 0) for value in values)
        for name in ("input_tokens", "cached_input_tokens", "output_tokens")
    }
    result["reasoning_tokens"] = (
        None
        if any(value["reasoning_tokens"] is None for value in values)
        else sum(int(value["reasoning_tokens"] or 0) for value in values)
    )
    return result


def _validate_model_result(
    value: Mapping[str, Any],
    request: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    counted_input_tokens: int,
) -> tuple[str, dict[str, int | None], list[dict[str, Any]], str]:
    expected_keys = {
        "op",
        "request_id",
        "provider",
        "model_id",
        "usage_source",
        "text",
        "usage",
        "native_calls",
    }
    _exact_keys(value, expected_keys, "model result")
    fixed = {
        "op": "model_result",
        "request_id": request["request_id"],
        "provider": manifest["provider"],
        "model_id": manifest["model_id"],
        "usage_source": "native_provider_response",
    }
    for name, expected in fixed.items():
        if value.get(name) != expected:
            raise ProviderEvidenceError(f"model result mismatch: {name}")
    text = _require_string(value.get("text"), "model result text")
    usage = _usage(value.get("usage"), "usage")
    if usage["input_tokens"] != counted_input_tokens:
        raise ProviderEvidenceError(
            "provider input usage differs from pre-call target token count"
        )
    native_values = value.get("native_calls")
    if not isinstance(native_values, list) or not native_values:
        raise ProviderEvidenceError("native_calls must be a non-empty array")
    native_calls: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(native_values):
        if not isinstance(item, dict):
            raise ProviderEvidenceError("native call must be an object")
        _exact_keys(
            item,
            {
                "provider_request_id",
                "model_id",
                "usage",
                "terminal",
                "finish_reason",
                "native_receipt_sha256",
            },
            f"native_calls[{index}]",
        )
        request_id = _require_string(
            item.get("provider_request_id"), "provider_request_id"
        )
        if not _NATIVE_REQUEST_ID.fullmatch(request_id):
            raise ProviderEvidenceError(
                "provider_request_id has an invalid closed format"
            )
        if request_id in seen:
            raise ProviderEvidenceError("duplicate native provider_request_id")
        seen.add(request_id)
        if item.get("model_id") != manifest["model_id"]:
            raise ProviderEvidenceError("native call model mismatch")
        finish = _require_string(item.get("finish_reason"), "finish_reason")
        if item.get("terminal") is not True or finish not in _FINISH_REASONS:
            raise ProviderEvidenceError(
                "native call is not in an approved terminal state"
            )
        native_calls.append(
            {
                "provider_request_id": request_id,
                "model_id": manifest["model_id"],
                "usage": _usage(item.get("usage"), "native usage"),
                "terminal": True,
                "finish_reason": finish,
                "native_receipt_sha256": _require_sha(
                    item.get("native_receipt_sha256"), "native_receipt_sha256"
                ),
            }
        )
    if (
        _sum_usage(
            [cast(Mapping[str, int | None], item["usage"]) for item in native_calls]
        )
        != usage
    ):
        raise ProviderEvidenceError(
            "top-level usage does not equal all native model calls"
        )
    if int(usage["output_tokens"] or 0) > int(request["max_output_tokens"]):
        raise ProviderEvidenceError("provider output exceeded the requested ceiling")
    return text, usage, native_calls, native_calls[-1]["finish_reason"]


def _normalize_output(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or set(value) != _REPORT_OUTPUT_KEYS:
        return None
    return value


def _score_normalized(
    value: Mapping[str, Any] | None,
    expected: Mapping[str, Any],
    forbidden_terms: Sequence[str],
    safety_labels: Sequence[str],
) -> dict[str, Any]:
    dimensions: dict[str, bool] = {"strict_json_contract": value is not None}
    for key in sorted(_REPORT_OUTPUT_KEYS):
        dimensions[f"expected_{key}"] = value is not None and value.get(
            key
        ) == expected.get(key)
    encoded = "" if value is None else _canonical_bytes(value).decode("utf-8")
    dimensions["forbidden_output_absent"] = all(
        term.casefold() not in encoded.casefold() for term in forbidden_terms
    )
    passed = all(dimensions.values())
    return {
        "passed": passed,
        "dimensions": dimensions,
        "safety_labels": list(safety_labels),
        "safety_passed": passed if safety_labels else True,
    }


def _score_output(
    text: str,
    expected: Mapping[str, Any],
    forbidden_terms: Sequence[str],
    safety_labels: Sequence[str],
) -> dict[str, Any]:
    return _score_normalized(
        _normalize_output(text), expected, forbidden_terms, safety_labels
    )


def _variant_aggregate(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        raise ProviderEvidenceError("cannot aggregate an empty provider record set")
    usage: dict[str, int | None] = {
        name: sum(int(record["usage"][name]) for record in records)
        for name in ("input_tokens", "cached_input_tokens", "output_tokens")
    }
    reasoning = [record["usage"]["reasoning_tokens"] for record in records]
    usage["reasoning_tokens"] = (
        None
        if any(item is None for item in reasoning)
        else sum(int(item) for item in reasoning)
    )
    components = {
        name: sum(int(record["component_tokens"][name]) for record in records)
        for name in ("memory_context_tokens", "tool_schema_tokens")
    }
    safety_failures: dict[str, int] = defaultdict(int)
    for record in records:
        if not record["quality"]["safety_passed"]:
            for label in record["quality"]["safety_labels"]:
                safety_failures[str(label)] += 1
    wall_values = [float(record["wall_ms"]) for record in records]
    return {
        "model_calls": len(records),
        "native_model_calls": sum(len(record["native_calls"]) for record in records),
        "usage": usage,
        "component_tokens": components,
        "max_component_tokens": {
            name: max(int(record["component_tokens"][name]) for record in records)
            for name in ("memory_context_tokens", "tool_schema_tokens")
        },
        "quality_passes": sum(bool(record["quality"]["passed"]) for record in records),
        "quality_rate": sum(bool(record["quality"]["passed"]) for record in records)
        / len(records),
        "safety_failures": dict(sorted(safety_failures.items())),
        "end_to_end_wall_ms": round(sum(wall_values), 3),
        "first_request_wall_ms": round(wall_values[0], 3),
        "expected_cost": str(
            sum(Decimal(str(record["expected_cost"])) for record in records)
        ),
    }


def _aggregates(
    records: Sequence[Mapping[str, Any]], required_counts: Sequence[int]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for count in required_counts:
        prefix = [record for record in records if int(record["turn_index"]) < count]
        result[str(count)] = {
            variant: _variant_aggregate(
                [record for record in prefix if record["variant"] == variant]
            )
            for variant in ("baseline", "optimized")
        }
        result[str(count)]["extra_optimized_model_round_trips"] = (
            result[str(count)]["optimized"]["native_model_calls"]
            - result[str(count)]["baseline"]["native_model_calls"]
        )
    return result


def _gates(
    workload: Mapping[str, Any], aggregates: Mapping[str, Any]
) -> dict[str, bool]:
    required_counts = workload["required_turn_counts"]
    quality_gates = workload["quality_gates"]
    minimum_quality = float(quality_gates["minimum_task_success"])
    max_regression = float(quality_gates["maximum_optimized_regression"])
    max_safety = int(quality_gates["maximum_safety_failures"])
    gates: dict[str, bool] = {}
    for count in required_counts:
        pair = aggregates[str(count)]
        baseline = pair["baseline"]
        optimized = pair["optimized"]
        gates[f"{count}_same_model_call_count"] = (
            baseline["model_calls"] == optimized["model_calls"] == count
        )
        gates[f"{count}_quality_minimum"] = (
            baseline["quality_rate"] >= minimum_quality
            and optimized["quality_rate"] >= minimum_quality
        )
        gates[f"{count}_quality_no_regression"] = (
            optimized["quality_rate"] + max_regression >= baseline["quality_rate"]
        )
        gates[f"{count}_safety"] = (
            sum(baseline["safety_failures"].values()) <= max_safety
            and sum(optimized["safety_failures"].values()) <= max_safety
        )
        gates[f"{count}_input_tokens_reduced"] = (
            optimized["usage"]["input_tokens"] < baseline["usage"]["input_tokens"]
        )
        gates[f"{count}_expected_cost_reduced"] = Decimal(
            optimized["expected_cost"]
        ) < Decimal(baseline["expected_cost"])
        gates[f"{count}_no_extra_model_rounds"] = (
            pair["extra_optimized_model_round_trips"] <= 0
        )
    hundred = aggregates["100"]["optimized"]
    gates["100_turn_milai_tokens_under_30000"] = (
        hundred["component_tokens"]["memory_context_tokens"]
        + hundred["component_tokens"]["tool_schema_tokens"]
        < 30_000
    )
    for count in required_counts:
        optimized = aggregates[str(count)]["optimized"]
        gates[f"{count}_memory_budget"] = (
            optimized["max_component_tokens"]["memory_context_tokens"] <= 1_600
        )
        gates[f"{count}_tool_budget"] = (
            optimized["max_component_tokens"]["tool_schema_tokens"] <= 250
        )
    return gates


def _native_request_ids(records: Sequence[Mapping[str, Any]]) -> list[str]:
    values = [
        str(call["provider_request_id"])
        for record in records
        for call in record["native_calls"]
    ]
    if len(values) != len(set(values)):
        raise ProviderEvidenceError(
            "native provider request IDs are not globally unique"
        )
    return values


def _request_ids_root(records: Sequence[Mapping[str, Any]]) -> str:
    return _sha256_bytes(_canonical_bytes(sorted(_native_request_ids(records))))


def _plan_binding(
    manifest: Mapping[str, Any],
    manifest_sha: str,
    workload_sha: str,
    pricing_sha: str,
    *,
    max_input_tokens_per_request: int,
    max_cost_usd: Decimal,
) -> dict[str, Any]:
    approval = manifest["approval"]
    return {
        "format": "milai-provider-ab-plan-binding-v3",
        "data_boundary": DATA_BOUNDARY_ACK,
        "provider": manifest["provider"],
        "provider_origin": manifest["provider_origin"],
        "model_id": manifest["model_id"],
        "tokenizer_id": manifest["tokenizer_id"],
        "workload_sha256": workload_sha,
        "adapter_manifest_sha256": manifest_sha,
        "provider_approval_sha256": manifest["approval_sha256"],
        "pricing_snapshot_sha256": pricing_sha,
        "runtime_executable_sha256": manifest["runtime_executable_sha256"],
        "adapter_source_sha256": manifest["adapter_source_sha256"],
        "dependency_lock_sha256": manifest["dependency_lock_sha256"],
        "host_execution_lock_sha256": manifest["host_execution_lock_sha256"],
        "host_execution_entries_sha256": approval["host_execution_entries_sha256"],
        "host_execution_file_count": approval["host_execution_file_count"],
        "host_execution_policy": approval["host_execution_policy"],
        "sandbox_launcher_sha256": approval["sandbox_launcher_sha256"],
        "sandbox_runtime_sha256": approval["sandbox_runtime_sha256"],
        "unshare_executable_sha256": approval["unshare_executable_sha256"],
        "slirp4netns_executable_sha256": approval["slirp4netns_executable_sha256"],
        "nsenter_executable_sha256": approval["nsenter_executable_sha256"],
        "nft_executable_sha256": approval["nft_executable_sha256"],
        "ip_executable_sha256": approval["ip_executable_sha256"],
        "sandbox_file_policy": approval["sandbox_file_policy"],
        "minimum_landlock_abi": approval["minimum_landlock_abi"],
        "reader_tool_schema_sha256": approval["reader_tool_schema_sha256"],
        "reader_lite_tool_schema_sha256": approval["reader_lite_tool_schema_sha256"],
        "provider_request_count": REQUIRED_PROVIDER_REQUESTS,
        "max_input_tokens_per_request": max_input_tokens_per_request,
        "max_output_tokens_per_request": approval["max_output_tokens_per_request"],
        "max_cost_usd": str(max_cost_usd),
        "billing_tolerance_usd": str(approval["billing_tolerance_usd"]),
        "egress_mode": approval["egress_mode"],
        "provider_ip_addresses": approval["provider_ip_addresses"],
    }


def _build_plan_value(
    manifest: Mapping[str, Any],
    manifest_sha: str,
    workload: Mapping[str, Any],
    workload_sha: str,
    pricing: Pricing,
    pricing_public: Mapping[str, Any],
    *,
    max_input_tokens_per_request: int,
    max_cost_usd: Decimal,
) -> dict[str, Any]:
    approval = manifest["approval"]
    if pricing.snapshot_sha256 != approval["pricing_snapshot_sha256"]:
        raise ProviderEvidenceError("pricing snapshot is not bound by approval")
    if max_input_tokens_per_request != int(approval["max_input_tokens_per_request"]):
        raise ProviderEvidenceError(
            "input token limit must exactly match provider approval"
        )
    if max_cost_usd != Decimal(str(approval["max_cost_usd"])):
        raise ProviderEvidenceError("cost limit must exactly match provider approval")
    max_output = int(workload["max_output_tokens"])
    upper_bound = Decimal(REQUIRED_PROVIDER_REQUESTS) * pricing.reservation(
        max_input_tokens_per_request, max_output
    )
    binding = _plan_binding(
        manifest,
        manifest_sha,
        workload_sha,
        pricing.snapshot_sha256,
        max_input_tokens_per_request=max_input_tokens_per_request,
        max_cost_usd=max_cost_usd,
    )
    return {
        "format": "milai-provider-ab-plan-v3",
        "generated_at": datetime.now(UTC).isoformat(),
        "plan_sha256": _sha256_bytes(_canonical_bytes(binding)),
        "binding": binding,
        "provider_approval": {
            "sha256": manifest["approval_sha256"],
            "approved_by": approval["approved_by"],
            "approved_at": approval["approved_at"],
        },
        "pricing_snapshot": pricing_public,
        "conservative_cost_upper_bound": str(upper_bound),
        "authorized_by_cost_limit": upper_bound <= max_cost_usd,
        "network_executed": False,
    }


def build_plan(
    manifest_path: Path,
    pricing_path: Path,
    *,
    expected_approval_sha256: str,
    max_input_tokens_per_request: int,
    max_cost_usd: Decimal,
) -> dict[str, Any]:
    if max_input_tokens_per_request <= 0 or max_cost_usd <= 0:
        raise ProviderEvidenceError("plan token and cost limits must be positive")
    workload, workload_sha = _load_workload()
    manifest, manifest_sha, _environment, _secrets = _manifest(
        manifest_path,
        expected_approval_sha256=expected_approval_sha256,
        require_secret_values=False,
    )
    pricing, pricing_public = _pricing(
        pricing_path, str(manifest["provider"]), str(manifest["model_id"])
    )
    return _build_plan_value(
        manifest,
        manifest_sha,
        workload,
        workload_sha,
        pricing,
        pricing_public,
        max_input_tokens_per_request=max_input_tokens_per_request,
        max_cost_usd=max_cost_usd,
    )


def _report_base(
    manifest: Mapping[str, Any],
    manifest_sha: str,
    workload: Mapping[str, Any],
    workload_sha: str,
    pricing_public: Mapping[str, Any],
    plan_sha: str,
) -> dict[str, Any]:
    approval = manifest["approval"]
    return {
        "format": REPORT_FORMAT,
        "generated_at": datetime.now(UTC).isoformat(),
        "data_boundary": workload["data_boundary"],
        "provider": manifest["provider"],
        "provider_origin": manifest["provider_origin"],
        "model_id": manifest["model_id"],
        "tokenizer_id": manifest["tokenizer_id"],
        "provider_usage_claimed_native": True,
        "provider_usage_verified": False,
        "independent_provider_review_required": True,
        "same_model_ab": True,
        "workload_path": str(WORKLOAD_PATH.relative_to(ROOT)),
        "workload_sha256": workload_sha,
        "adapter_manifest_sha256": manifest_sha,
        "adapter_source_sha256": manifest["adapter_source_sha256"],
        "runtime_executable_sha256": manifest["runtime_executable_sha256"],
        "dependency_lock_sha256": manifest["dependency_lock_sha256"],
        "host_execution_lock_sha256": manifest["host_execution_lock_sha256"],
        "provider_approval": {
            "sha256": manifest["approval_sha256"],
            "approved_by": approval["approved_by"],
            "approved_at": approval["approved_at"],
            "max_provider_requests": approval["max_provider_requests"],
            "max_input_tokens_per_request": approval["max_input_tokens_per_request"],
            "max_output_tokens_per_request": approval["max_output_tokens_per_request"],
            "max_cost_usd": str(approval["max_cost_usd"]),
            "billing_tolerance_usd": str(approval["billing_tolerance_usd"]),
            "sandbox_file_policy": approval["sandbox_file_policy"],
            "minimum_landlock_abi": approval["minimum_landlock_abi"],
            "host_execution_entries_sha256": approval["host_execution_entries_sha256"],
            "host_execution_file_count": approval["host_execution_file_count"],
            "host_execution_policy": approval["host_execution_policy"],
        },
        "plan_sha256": plan_sha,
        "pricing_snapshot": dict(pricing_public),
        "tool_schema_sha256": {
            "reader": approval["reader_tool_schema_sha256"],
            "reader_lite": approval["reader_lite_tool_schema_sha256"],
        },
        "privacy": {
            "prompt_or_response_text_retained": False,
            "secret_values_retained": False,
            "canonical_workspace_visible_to_adapter": False,
            "report_fields": "normalized-output,hashes,counters,timings,native-receipts,scores",
        },
        "limitations": [
            "Native usage and receipt fields remain provider-adapter claims until independent provider review.",
            "Billing reconciliation never promotes this tool's output to PASS.",
            "Latency is an observation for this run and is not an SLA.",
        ],
    }


def run_provider_ab(
    manifest_path: Path,
    pricing_path: Path,
    *,
    expected_approval_sha256: str,
    expected_plan_sha256: str,
    execute_provider: bool,
    data_boundary_ack: str,
    max_provider_requests: int,
    max_input_tokens_per_request: int,
    max_cost_usd: Decimal,
    timeout_seconds: float,
) -> dict[str, Any]:
    if execute_provider is not True:
        raise ProviderEvidenceError("provider execution requires --execute-provider")
    if data_boundary_ack != DATA_BOUNDARY_ACK:
        raise ProviderEvidenceError(
            "provider execution requires the exact synthetic data boundary"
        )
    if timeout_seconds <= 0:
        raise ProviderEvidenceError("timeout_seconds must be positive")
    workload, workload_sha = _load_workload()
    manifest, manifest_sha, environment, secret_values = _manifest(
        manifest_path, expected_approval_sha256=expected_approval_sha256
    )
    pricing, pricing_public = _pricing(
        pricing_path, str(manifest["provider"]), str(manifest["model_id"])
    )
    plan = _build_plan_value(
        manifest,
        manifest_sha,
        workload,
        workload_sha,
        pricing,
        pricing_public,
        max_input_tokens_per_request=max_input_tokens_per_request,
        max_cost_usd=max_cost_usd,
    )
    expected_plan = _require_sha(expected_plan_sha256, "expected plan SHA-256")
    if plan["plan_sha256"] != expected_plan:
        raise ProviderEvidenceError(
            "run inputs do not match the out-of-band plan digest"
        )
    if max_provider_requests != REQUIRED_PROVIDER_REQUESTS:
        raise ProviderEvidenceError(
            f"max_provider_requests must exactly equal {REQUIRED_PROVIDER_REQUESTS}"
        )
    if plan["authorized_by_cost_limit"] is not True:
        raise ProviderEvidenceError(
            "operator cost limit is below the conservative upper bound"
        )
    turns = _turns(workload, 500)
    records: list[dict[str, Any]] = []
    seen_native_ids: set[str] = set()
    total_cost = Decimal(0)
    total_reserved = Decimal(0)
    handshake: dict[str, Any] = {}
    handshake_ms = 0.0
    started = perf_counter_ns()
    failure: Exception | None = None
    adapter_process = AdapterProcess(
        manifest, environment, secret_values, timeout_seconds=timeout_seconds
    )
    try:
        with adapter_process as adapter:
            handshake_started = perf_counter_ns()
            handshake = _validate_handshake(
                adapter.exchange(
                    {
                        "op": "handshake",
                        "protocol": ADAPTER_PROTOCOL,
                        "provider": manifest["provider"],
                        "provider_origin": manifest["provider_origin"],
                        "model_id": manifest["model_id"],
                    }
                ),
                manifest,
            )
            handshake_ms = (perf_counter_ns() - handshake_started) / 1_000_000
            for turn in turns:
                order = (
                    ("baseline", "optimized")
                    if turn.turn_index % 2 == 0
                    else ("optimized", "baseline")
                )
                for variant in order:
                    request, private = _request_payload(
                        workload,
                        workload_sha,
                        turn,
                        variant,
                        str(manifest["provider"]),
                        str(manifest["model_id"]),
                    )
                    count_request = dict(request)
                    count_request["op"] = "count_request"
                    counted_input, components = _validate_count_result(
                        adapter.exchange(count_request), request, manifest
                    )
                    if counted_input > max_input_tokens_per_request:
                        raise ProviderEvidenceError(
                            "target-tokenizer input exceeds the authorized per-call limit"
                        )
                    if (
                        not private["memory_context"]
                        and components["memory_context_tokens"] != 0
                    ):
                        raise ProviderEvidenceError(
                            "adapter reported memory tokens for empty memory context"
                        )
                    if not request["tools"] and components["tool_schema_tokens"] != 0:
                        raise ProviderEvidenceError(
                            "adapter reported tool tokens for empty tool catalog"
                        )
                    reservation = pricing.reservation(
                        counted_input, int(request["max_output_tokens"])
                    )
                    if total_reserved + reservation > max_cost_usd:
                        raise ProviderEvidenceError(
                            "next provider call exceeds pre-authorized spend reservation"
                        )
                    total_reserved += reservation
                    call_started = perf_counter_ns()
                    response = adapter.exchange(request)
                    wall_ms = (perf_counter_ns() - call_started) / 1_000_000
                    text, usage, native_calls, finish_reason = _validate_model_result(
                        response, request, manifest, counted_input_tokens=counted_input
                    )
                    for native in native_calls:
                        request_id = str(native["provider_request_id"])
                        if request_id in seen_native_ids:
                            raise ProviderEvidenceError(
                                "duplicate native request ID across logical calls"
                            )
                        seen_native_ids.add(request_id)
                    call_cost = pricing.cost(usage)
                    total_cost += call_cost
                    if total_cost > max_cost_usd or call_cost > reservation:
                        raise ProviderEvidenceError(
                            "actual provider cost exceeds its authorized reservation"
                        )
                    normalized_output = _normalize_output(text)
                    quality = _score_normalized(
                        normalized_output,
                        private["expected"],
                        private["forbidden_output_terms"],
                        private["safety_labels"],
                    )
                    output_hash_source = (
                        text.encode("utf-8")
                        if normalized_output is None
                        else _canonical_bytes(normalized_output)
                    )
                    records.append(
                        {
                            "request_id": request["request_id"],
                            "native_calls": native_calls,
                            "turn_index": turn.turn_index,
                            "case_id": turn.case_id,
                            "requires_memory": turn.requires_memory,
                            "variant": variant,
                            "prompt_sha256": private["prompt_sha256"],
                            "tool_schema_sha256": private["tool_schema_sha256"],
                            "normalized_output": normalized_output,
                            "output_sha256": _sha256_bytes(output_hash_source),
                            "finish_reason": finish_reason,
                            "usage": usage,
                            "component_tokens": components,
                            "wall_ms": round(wall_ms, 3),
                            "expected_cost": str(call_cost),
                            "quality": quality,
                        }
                    )
    except (ProviderEvidenceError, OSError, subprocess.SubprocessError) as exc:
        failure = exc
    base = _report_base(
        manifest,
        manifest_sha,
        workload,
        workload_sha,
        pricing_public,
        str(plan["plan_sha256"]),
    )
    elapsed_ms = (perf_counter_ns() - started) / 1_000_000
    execution = {
        "provider_requests": len(records),
        "native_model_calls": sum(len(record["native_calls"]) for record in records),
        "provider_request_ids_sha256": _request_ids_root(records)
        if records
        else _sha256_bytes(_canonical_bytes([])),
        "handshake_ms": round(handshake_ms, 3),
        "end_to_end_wall_ms": round(elapsed_ms, 3),
        "actual_expected_cost": str(total_cost),
        "reserved_cost_ceiling": str(total_reserved),
        "operator_cost_limit": str(max_cost_usd),
        "billing_reconciled": False,
        "host_execution": adapter_process.host_execution_evidence(),
    }
    if failure is not None:
        return dict(
            base,
            status="FAIL_PARTIAL",
            execution=execution,
            aggregates={},
            gates={},
            records=records,
            handshake=handshake,
            failure={
                "code": "PROVIDER_EVIDENCE_CAPTURE_FAILED",
                "after_validated_provider_requests": len(records),
                "reason_sha256": _sha256_bytes(str(failure).encode("utf-8")),
            },
        )
    aggregates = _aggregates(records, workload["required_turn_counts"])
    gates = _gates(workload, aggregates)
    return dict(
        base,
        status=_CAPTURE_STATUS if all(gates.values()) else "FAIL_COMPLETE",
        execution=execution,
        aggregates=aggregates,
        gates=gates,
        records=records,
        handshake=handshake,
        failure=None,
    )


def _validate_record_schema(record: Mapping[str, Any], index: int) -> None:
    _exact_keys(
        record,
        {
            "request_id",
            "native_calls",
            "turn_index",
            "case_id",
            "requires_memory",
            "variant",
            "prompt_sha256",
            "tool_schema_sha256",
            "normalized_output",
            "output_sha256",
            "finish_reason",
            "usage",
            "component_tokens",
            "wall_ms",
            "expected_cost",
            "quality",
        },
        f"records[{index}]",
    )


def _validate_capture_report(
    report: Mapping[str, Any],
    manifest: Mapping[str, Any],
    manifest_sha: str,
    workload: Mapping[str, Any],
    workload_sha: str,
    pricing: Pricing,
    pricing_public: Mapping[str, Any],
    expected_plan_sha256: str,
) -> None:
    expected_top = {
        "format",
        "generated_at",
        "status",
        "data_boundary",
        "provider",
        "provider_origin",
        "model_id",
        "tokenizer_id",
        "provider_usage_claimed_native",
        "provider_usage_verified",
        "independent_provider_review_required",
        "same_model_ab",
        "workload_path",
        "workload_sha256",
        "adapter_manifest_sha256",
        "adapter_source_sha256",
        "runtime_executable_sha256",
        "dependency_lock_sha256",
        "host_execution_lock_sha256",
        "provider_approval",
        "plan_sha256",
        "pricing_snapshot",
        "tool_schema_sha256",
        "privacy",
        "limitations",
        "execution",
        "aggregates",
        "gates",
        "records",
        "handshake",
        "failure",
    }
    _exact_keys(report, expected_top, "provider capture report")
    identity = {
        "format": REPORT_FORMAT,
        "status": _CAPTURE_STATUS,
        "data_boundary": DATA_BOUNDARY_ACK,
        "provider": manifest["provider"],
        "provider_origin": manifest["provider_origin"],
        "model_id": manifest["model_id"],
        "tokenizer_id": manifest["tokenizer_id"],
        "provider_usage_claimed_native": True,
        "provider_usage_verified": False,
        "independent_provider_review_required": True,
        "same_model_ab": True,
        "workload_path": str(WORKLOAD_PATH.relative_to(ROOT)),
        "workload_sha256": workload_sha,
        "adapter_manifest_sha256": manifest_sha,
        "adapter_source_sha256": manifest["adapter_source_sha256"],
        "runtime_executable_sha256": manifest["runtime_executable_sha256"],
        "dependency_lock_sha256": manifest["dependency_lock_sha256"],
        "host_execution_lock_sha256": manifest["host_execution_lock_sha256"],
        "plan_sha256": expected_plan_sha256,
    }
    for name, expected in identity.items():
        if report.get(name) != expected:
            raise ProviderEvidenceError(f"capture report identity mismatch: {name}")
    if report.get("failure") is not None:
        raise ProviderEvidenceError("capture report contains a failure")
    base = _report_base(
        manifest,
        manifest_sha,
        workload,
        workload_sha,
        pricing_public,
        expected_plan_sha256,
    )
    for name in (
        "provider_approval",
        "pricing_snapshot",
        "tool_schema_sha256",
        "privacy",
        "limitations",
    ):
        if report.get(name) != base[name]:
            raise ProviderEvidenceError(
                f"capture report immutable section mismatch: {name}"
            )
    _require_string(report.get("generated_at"), "report generated_at")
    if report.get("handshake") != _validate_handshake(
        cast(Mapping[str, Any], report.get("handshake")), manifest
    ):
        raise ProviderEvidenceError("capture report handshake mismatch")
    records_value = report.get("records")
    if (
        not isinstance(records_value, list)
        or len(records_value) != REQUIRED_PROVIDER_REQUESTS
    ):
        raise ProviderEvidenceError("capture report must contain exactly 1,000 records")
    turns = _turns(workload, 500)
    expected_records: list[tuple[TurnSpec, str]] = []
    for turn in turns:
        for variant in (
            ("baseline", "optimized")
            if turn.turn_index % 2 == 0
            else ("optimized", "baseline")
        ):
            expected_records.append((turn, variant))
    records: list[Mapping[str, Any]] = []
    native_ids: set[str] = set()
    for index, (raw, expected_spec) in enumerate(
        zip(records_value, expected_records, strict=True)
    ):
        if not isinstance(raw, dict):
            raise ProviderEvidenceError("capture record must be an object")
        _validate_record_schema(raw, index)
        turn, variant = expected_spec
        request, private = _request_payload(
            workload,
            workload_sha,
            turn,
            variant,
            str(manifest["provider"]),
            str(manifest["model_id"]),
        )
        fixed = {
            "request_id": request["request_id"],
            "turn_index": turn.turn_index,
            "case_id": turn.case_id,
            "requires_memory": turn.requires_memory,
            "variant": variant,
            "prompt_sha256": private["prompt_sha256"],
            "tool_schema_sha256": private["tool_schema_sha256"],
        }
        for name, expected in fixed.items():
            if raw.get(name) != expected:
                raise ProviderEvidenceError(f"capture record mismatch: {name}")
        normalized = raw.get("normalized_output")
        if normalized is not None and not isinstance(normalized, dict):
            raise ProviderEvidenceError("normalized_output must be an object or null")
        if normalized is not None:
            _exact_keys(
                normalized,
                _REPORT_OUTPUT_KEYS,
                "record normalized_output",
            )
        expected_quality = _score_normalized(
            cast(Mapping[str, Any] | None, normalized),
            private["expected"],
            private["forbidden_output_terms"],
            private["safety_labels"],
        )
        if raw.get("quality") != expected_quality:
            raise ProviderEvidenceError("capture quality result is not reproducible")
        if normalized is not None and raw.get("output_sha256") != _sha256_bytes(
            _canonical_bytes(normalized)
        ):
            raise ProviderEvidenceError("normalized output hash mismatch")
        _require_sha(raw.get("output_sha256"), "record output_sha256")
        usage = _usage(raw.get("usage"), "record usage")
        components = raw.get("component_tokens")
        if not isinstance(components, dict):
            raise ProviderEvidenceError("record component_tokens must be an object")
        _exact_keys(
            components,
            {"tokenizer_id", "verified", "memory_context_tokens", "tool_schema_tokens"},
            "record component_tokens",
        )
        if (
            components.get("tokenizer_id") != manifest["tokenizer_id"]
            or components.get("verified") is not False
        ):
            raise ProviderEvidenceError("record component token identity mismatch")
        for name in ("memory_context_tokens", "tool_schema_tokens"):
            _require_nonnegative_int(components.get(name), f"record {name}")
        if int(components["memory_context_tokens"]) + int(
            components["tool_schema_tokens"]
        ) > int(usage["input_tokens"] or 0):
            raise ProviderEvidenceError("record component tokens exceed input usage")
        if not private["memory_context"] and components["memory_context_tokens"] != 0:
            raise ProviderEvidenceError("record claims memory tokens for empty context")
        if not request["tools"] and components["tool_schema_tokens"] != 0:
            raise ProviderEvidenceError("record claims tool tokens for empty catalog")
        native = raw.get("native_calls")
        if not isinstance(native, list) or not native:
            raise ProviderEvidenceError("record native_calls must be a non-empty array")
        parsed_native: list[Mapping[str, int | None]] = []
        for item in native:
            if not isinstance(item, dict):
                raise ProviderEvidenceError("record native call must be an object")
            _exact_keys(
                item,
                {
                    "provider_request_id",
                    "model_id",
                    "usage",
                    "terminal",
                    "finish_reason",
                    "native_receipt_sha256",
                },
                "record native call",
            )
            request_id = _require_string(
                item.get("provider_request_id"), "provider_request_id"
            )
            if not _NATIVE_REQUEST_ID.fullmatch(request_id) or request_id in native_ids:
                raise ProviderEvidenceError(
                    "record native request ID is invalid or duplicate"
                )
            native_ids.add(request_id)
            if (
                item.get("model_id") != manifest["model_id"]
                or item.get("terminal") is not True
                or item.get("finish_reason") not in _FINISH_REASONS
            ):
                raise ProviderEvidenceError(
                    "record native call identity/state mismatch"
                )
            _require_sha(item.get("native_receipt_sha256"), "native receipt SHA-256")
            parsed_native.append(_usage(item.get("usage"), "record native usage"))
        if _sum_usage(parsed_native) != usage:
            raise ProviderEvidenceError("record native usage sum mismatch")
        if raw.get("finish_reason") != native[-1]["finish_reason"]:
            raise ProviderEvidenceError("record finish reason mismatch")
        wall = raw.get("wall_ms")
        if isinstance(wall, bool) or not isinstance(wall, (int, float)) or wall < 0:
            raise ProviderEvidenceError("record wall_ms must be non-negative")
        if Decimal(str(raw.get("expected_cost"))) != pricing.cost(usage):
            raise ProviderEvidenceError("record expected cost is not reproducible")
        if int(usage["input_tokens"] or 0) > int(
            manifest["approval"]["max_input_tokens_per_request"]
        ) or int(usage["output_tokens"] or 0) > int(
            manifest["approval"]["max_output_tokens_per_request"]
        ):
            raise ProviderEvidenceError("record usage exceeds approved per-call limits")
        records.append(raw)
    aggregates = _aggregates(records, workload["required_turn_counts"])
    gates = _gates(workload, aggregates)
    if report.get("aggregates") != aggregates or report.get("gates") != gates:
        raise ProviderEvidenceError("capture aggregates or gates are not reproducible")
    if (
        set(gates) != set(_gates(workload, aggregates))
        or not gates
        or not all(gates.values())
    ):
        raise ProviderEvidenceError("capture gate set is incomplete or failed")
    execution = report.get("execution")
    if not isinstance(execution, dict):
        raise ProviderEvidenceError("capture execution must be an object")
    _exact_keys(
        execution,
        {
            "provider_requests",
            "native_model_calls",
            "provider_request_ids_sha256",
            "handshake_ms",
            "end_to_end_wall_ms",
            "actual_expected_cost",
            "reserved_cost_ceiling",
            "operator_cost_limit",
            "billing_reconciled",
            "host_execution",
        },
        "capture execution",
    )
    if execution.get(
        "provider_requests"
    ) != REQUIRED_PROVIDER_REQUESTS or execution.get("native_model_calls") != len(
        native_ids
    ):
        raise ProviderEvidenceError("capture execution counts mismatch")
    if execution.get("provider_request_ids_sha256") != _request_ids_root(records):
        raise ProviderEvidenceError("capture native request coverage root mismatch")
    total_cost = sum(Decimal(str(record["expected_cost"])) for record in records)
    if Decimal(str(execution.get("actual_expected_cost"))) != total_cost:
        raise ProviderEvidenceError("capture total expected cost mismatch")
    approved_cost = Decimal(str(manifest["approval"]["max_cost_usd"]))
    reserved_cost = _decimal(
        execution.get("reserved_cost_ceiling"), "capture reserved cost ceiling"
    )
    expected_reserved_cost = sum(
        pricing.reservation(
            int(record["usage"]["input_tokens"]),
            int(workload["max_output_tokens"]),
        )
        for record in records
    )
    if (
        _decimal(execution.get("operator_cost_limit"), "capture operator cost limit")
        != approved_cost
        or total_cost > approved_cost
        or reserved_cost > approved_cost
        or reserved_cost < total_cost
        or reserved_cost != expected_reserved_cost
    ):
        raise ProviderEvidenceError("capture execution cost authorization mismatch")
    for timing_name in ("handshake_ms", "end_to_end_wall_ms"):
        timing = execution.get(timing_name)
        if (
            isinstance(timing, bool)
            or not isinstance(timing, (int, float))
            or timing < 0
        ):
            raise ProviderEvidenceError("capture execution timing must be non-negative")
    record_wall = sum(float(record["wall_ms"]) for record in records)
    if float(execution["end_to_end_wall_ms"]) + 1 < record_wall:
        raise ProviderEvidenceError(
            "capture execution wall time is internally inconsistent"
        )
    if execution.get("billing_reconciled") is not False:
        raise ProviderEvidenceError("capture cannot claim billing reconciliation")
    host_execution = execution.get("host_execution")
    if not isinstance(host_execution, dict):
        raise ProviderEvidenceError("capture host execution evidence must be an object")
    _exact_keys(
        host_execution,
        {
            "policy",
            "file_count",
            "entries_sha256",
            "pre_execution_verified",
            "post_execution_revalidated",
        },
        "capture host execution evidence",
    )
    expected_host = {
        "policy": manifest["approval"]["host_execution_policy"],
        "file_count": manifest["approval"]["host_execution_file_count"],
        "entries_sha256": manifest["approval"]["host_execution_entries_sha256"],
        "pre_execution_verified": True,
        "post_execution_revalidated": True,
    }
    if host_execution != expected_host:
        raise ProviderEvidenceError("capture host execution evidence mismatch")


def reconcile_billing(
    report_path: Path,
    billing_evidence_path: Path,
    manifest_path: Path,
    pricing_path: Path,
    *,
    expected_report_sha256: str,
    expected_approval_sha256: str,
    expected_plan_sha256: str,
) -> dict[str, Any]:
    report, report_sha = _load_object(report_path, label="provider A/B report")
    if report_sha != _require_sha(expected_report_sha256, "expected report SHA-256"):
        raise ProviderEvidenceError(
            "capture report does not match the out-of-band digest"
        )
    workload, workload_sha = _load_workload()
    manifest, manifest_sha, _environment, _secrets = _manifest(
        manifest_path,
        expected_approval_sha256=expected_approval_sha256,
        require_secret_values=False,
    )
    pricing, pricing_public = _pricing(
        pricing_path, str(manifest["provider"]), str(manifest["model_id"])
    )
    expected_plan = _require_sha(expected_plan_sha256, "expected plan SHA-256")
    plan = _build_plan_value(
        manifest,
        manifest_sha,
        workload,
        workload_sha,
        pricing,
        pricing_public,
        max_input_tokens_per_request=int(
            manifest["approval"]["max_input_tokens_per_request"]
        ),
        max_cost_usd=Decimal(str(manifest["approval"]["max_cost_usd"])),
    )
    if plan["plan_sha256"] != expected_plan:
        raise ProviderEvidenceError("reconciliation plan digest mismatch")
    _validate_capture_report(
        report,
        manifest,
        manifest_sha,
        workload,
        workload_sha,
        pricing,
        pricing_public,
        expected_plan,
    )
    evidence, evidence_sha = _load_object(
        billing_evidence_path, label="billing evidence"
    )
    _exact_keys(
        evidence,
        {
            "format",
            "provider",
            "model_id",
            "currency",
            "normalized_source_path",
            "normalized_source_sha256",
            "upstream_provider_artifact_path",
            "upstream_provider_artifact_sha256",
            "source_type",
        },
        "billing evidence",
    )
    if evidence.get("format") != "milai-provider-billing-evidence-v2":
        raise ProviderEvidenceError("unsupported billing evidence format")
    for name, expected in {
        "provider": manifest["provider"],
        "model_id": manifest["model_id"],
        "currency": pricing.currency,
    }.items():
        if evidence.get(name) != expected:
            raise ProviderEvidenceError(f"billing evidence {name} mismatch")
    normalized_path = _external_regular_file(
        evidence.get("normalized_source_path"), "normalized_source_path"
    )
    upstream_path = _external_regular_file(
        evidence.get("upstream_provider_artifact_path"),
        "upstream_provider_artifact_path",
    )
    normalized_sha = _sha256_file(normalized_path)
    upstream_sha = _sha256_file(upstream_path)
    if normalized_sha != _require_sha(
        evidence.get("normalized_source_sha256"), "normalized_source_sha256"
    ):
        raise ProviderEvidenceError("normalized billing source hash mismatch")
    if upstream_sha != _require_sha(
        evidence.get("upstream_provider_artifact_sha256"),
        "upstream_provider_artifact_sha256",
    ):
        raise ProviderEvidenceError("upstream provider artifact hash mismatch")
    source, _source_sha = _load_object(
        normalized_path, label="normalized provider billing export"
    )
    _exact_keys(
        source,
        {
            "format",
            "provider",
            "model_id",
            "currency",
            "period_start",
            "period_end",
            "upstream_provider_artifact_sha256",
            "records",
        },
        "normalized billing export",
    )
    if source.get("format") != "milai-normalized-provider-billing-export-v2":
        raise ProviderEvidenceError("unsupported normalized provider billing export")
    for name, expected in {
        "provider": manifest["provider"],
        "model_id": manifest["model_id"],
        "currency": pricing.currency,
        "upstream_provider_artifact_sha256": upstream_sha,
    }.items():
        if source.get(name) != expected:
            raise ProviderEvidenceError(f"normalized billing export {name} mismatch")
    _require_string(source.get("period_start"), "period_start")
    _require_string(source.get("period_end"), "period_end")
    billing_records = source.get("records")
    if not isinstance(billing_records, list) or not billing_records:
        raise ProviderEvidenceError(
            "normalized billing records must be a non-empty array"
        )
    ids: list[str] = []
    actual = Decimal(0)
    for index, item in enumerate(billing_records):
        if not isinstance(item, dict):
            raise ProviderEvidenceError("normalized billing record must be an object")
        _exact_keys(item, {"provider_request_id", "cost"}, f"billing records[{index}]")
        request_id = _require_string(
            item.get("provider_request_id"), "billing provider_request_id"
        )
        if not _NATIVE_REQUEST_ID.fullmatch(request_id):
            raise ProviderEvidenceError(
                "billing provider request ID has invalid format"
            )
        ids.append(request_id)
        actual += _decimal(item.get("cost"), "billing record cost")
    if len(ids) != len(set(ids)):
        raise ProviderEvidenceError("normalized billing request IDs are not unique")
    root = _sha256_bytes(_canonical_bytes(sorted(ids)))
    if root != report["execution"]["provider_request_ids_sha256"]:
        raise ProviderEvidenceError("billing request coverage root mismatch")
    expected = _decimal(report["execution"]["actual_expected_cost"], "expected cost")
    tolerance = _decimal(
        manifest["approval"]["billing_tolerance_usd"], "approved billing tolerance"
    )
    approved_cost = _decimal(manifest["approval"]["max_cost_usd"], "approved max cost")
    difference = abs(actual - expected)
    reconciled = difference <= tolerance and actual <= approved_cost
    result = dict(report)
    result["source_report_sha256"] = report_sha
    result["billing_reconciliation"] = {
        "billing_evidence_sha256": evidence_sha,
        "source_type": _require_string(
            evidence.get("source_type"), "billing source_type"
        ),
        "normalized_source_sha256": normalized_sha,
        "upstream_provider_artifact_sha256": upstream_sha,
        "period_start": source["period_start"],
        "period_end": source["period_end"],
        "provider_request_ids_sha256": root,
        "billing_record_count": len(billing_records),
        "currency": pricing.currency,
        "expected_cost": str(expected),
        "actual_cost": str(actual),
        "absolute_difference": str(difference),
        "approved_tolerance": str(tolerance),
        "approved_cost_ceiling": str(approved_cost),
        "reconciled": reconciled,
    }
    result["execution"] = dict(cast(Mapping[str, Any], report["execution"]))
    result["execution"]["billing_reconciled"] = reconciled
    result["status"] = _RECONCILED_STATUS if reconciled else "FAIL"
    result["provider_usage_verified"] = False
    result["independent_provider_review_required"] = True
    return result


def _write_json(
    path: Path | None, value: object, *, stream: TextIO = sys.stdout
) -> None:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path is None:
        stream.write(encoded)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _shared_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--adapter-manifest", type=Path, required=True)
    parser.add_argument("--pricing-snapshot", type=Path, required=True)
    parser.add_argument("--expected-approval-sha256", required=True)
    parser.add_argument("--max-input-tokens-per-request", type=int, required=True)
    parser.add_argument("--max-cost-usd", type=Decimal, required=True)
    parser.add_argument("--output", type=Path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture privacy-bounded same-model provider A/B evidence for MiLAi"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    host_lock = subparsers.add_parser(
        "host-lock",
        help="enumerate the privileged sandbox/runtime/helper execution closure",
    )
    host_lock.add_argument("--output", type=Path, required=True)
    plan = subparsers.add_parser(
        "plan", help="validate inputs and calculate a no-network plan"
    )
    _shared_arguments(plan)
    run = subparsers.add_parser("run", help="execute the frozen provider workload")
    _shared_arguments(run)
    run.add_argument("--expected-plan-sha256", required=True)
    run.add_argument("--execute-provider", action="store_true")
    run.add_argument("--data-boundary-ack", required=True)
    run.add_argument("--max-provider-requests", type=int, required=True)
    run.add_argument("--timeout-seconds", type=float, default=120.0)
    reconcile = subparsers.add_parser(
        "reconcile", help="reconcile captured evidence without promoting it to PASS"
    )
    reconcile.add_argument("--report", type=Path, required=True)
    reconcile.add_argument("--billing-evidence", type=Path, required=True)
    reconcile.add_argument("--adapter-manifest", type=Path, required=True)
    reconcile.add_argument("--pricing-snapshot", type=Path, required=True)
    reconcile.add_argument("--expected-report-sha256", required=True)
    reconcile.add_argument("--expected-approval-sha256", required=True)
    reconcile.add_argument("--expected-plan-sha256", required=True)
    reconcile.add_argument("--output", type=Path)
    return parser


def _command_exit_code(command: str, status: object) -> int:
    if str(status).startswith("FAIL"):
        return 1
    if command in {"run", "reconcile"}:
        return 3
    return 0


def main() -> None:
    args = _parser().parse_args()
    try:
        if args.command == "host-lock":
            value = build_host_execution_lock()
        elif args.command == "plan":
            value = build_plan(
                args.adapter_manifest,
                args.pricing_snapshot,
                expected_approval_sha256=args.expected_approval_sha256,
                max_input_tokens_per_request=args.max_input_tokens_per_request,
                max_cost_usd=args.max_cost_usd,
            )
        elif args.command == "run":
            value = run_provider_ab(
                args.adapter_manifest,
                args.pricing_snapshot,
                expected_approval_sha256=args.expected_approval_sha256,
                expected_plan_sha256=args.expected_plan_sha256,
                execute_provider=args.execute_provider,
                data_boundary_ack=args.data_boundary_ack,
                max_provider_requests=args.max_provider_requests,
                max_input_tokens_per_request=args.max_input_tokens_per_request,
                max_cost_usd=args.max_cost_usd,
                timeout_seconds=args.timeout_seconds,
            )
        else:
            value = reconcile_billing(
                args.report,
                args.billing_evidence,
                args.adapter_manifest,
                args.pricing_snapshot,
                expected_report_sha256=args.expected_report_sha256,
                expected_approval_sha256=args.expected_approval_sha256,
                expected_plan_sha256=args.expected_plan_sha256,
            )
    except ProviderEvidenceError as exc:
        sys.stderr.write(f"provider evidence gate failed: {exc}\n")
        raise SystemExit(2) from exc
    _write_json(args.output, value)
    raise SystemExit(_command_exit_code(args.command, value.get("status")))


if __name__ == "__main__":
    main()
