from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import stat
import subprocess
import sys
import urllib.parse
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from scripts import dg10_remediation as remediation

MODEL = "gpt-5.6-sol"
REASONING_EFFORT = "xhigh"
AUTHORITY_POLICY = remediation.ROOT / (
    "docs/contracts/DG-10-ai-execution-authority-candidate.4.18.json"
)
AUTHORITY_CODE_RELATIVE_PATHS = (
    "scripts/__init__.py",
    "scripts/dg10_remediation.py",
    "scripts/dg10_ai_provenance.py",
    "scripts/run_dg10_candidate4_ai_audit.py",
)
CODEX_RESOURCE_PATHS = (
    "codex-path/rg",
    "codex-resources/bwrap",
    "codex-resources/zsh/bin/zsh",
)
CODEX_RESOURCE_DIRECTORIES = (
    "codex-path",
    "codex-resources",
    "codex-resources/zsh",
    "codex-resources/zsh/bin",
)
POLICY_KEYS = {
    "schema",
    "candidate_id",
    "status",
    "algorithm",
    "key_id",
    "public_key_base64",
    "public_key_sha256",
    "authority_uid",
    "authority_gid",
    "workspace_author_uid",
    "workspace_author_gid",
    "private_key_path",
    "codex_executable_path",
    "codex_executable_sha256",
    "codex_executable_mode",
    "codex_executable_uid",
    "codex_executable_gid",
    "codex_code_mode_host_path",
    "codex_code_mode_host_sha256",
    "codex_code_mode_host_mode",
    "codex_code_mode_host_uid",
    "codex_code_mode_host_gid",
    "codex_model_catalog_path",
    "codex_model_catalog_sha256",
    "codex_model_catalog_mode",
    "codex_model_catalog_uid",
    "codex_model_catalog_gid",
    "codex_runtime_resources",
    "codex_home_path",
    "codex_child_static_environment",
    "codex_child_static_environment_sha256",
    "authority_code_root",
    "authority_code_manifest_sha256",
    "authority_code_files",
    "authority_runner_path",
    "authority_runner_sha256",
    "authority_python_launcher_path",
    "authority_python_launcher_target",
    "authority_python_executable_path",
    "authority_python_executable_sha256",
    "authority_python_executable_mode",
    "authority_python_executable_uid",
    "authority_python_executable_gid",
    "authority_python_runtime_roots",
    "authority_python_loaded_libraries",
    "authority_python_sys_path",
    "authority_python_isolated_flag",
    "authority_python_dont_write_bytecode_flag",
    "authority_process_static_environment",
    "authority_process_static_environment_sha256",
    "protected_attempt_roots",
    "workspace_author_can_invoke_signer",
    "host_root_or_kernel_compromise",
}
ATTESTATION_KEYS = {
    "schema",
    "channel",
    "authority_policy_sha256",
    "key_id",
    "public_key_sha256",
    "signed_statement",
    "signature_base64",
}
STATEMENT_KEYS = {
    "schema",
    "authority_uid",
    "authority_gid",
    "process",
    "runtime_observations",
    "signed_after_terminal_output_hashes",
}
RUNTIME_KEYS = {
    "authority_code",
    "authority_python_runtime",
    "authority_runner_path",
    "authority_runner_sha256",
    "codex_executable_path",
    "codex_executable_sha256",
    "codex_executable_mode",
    "codex_executable_uid",
    "codex_executable_gid",
    "codex_code_mode_host_path",
    "codex_code_mode_host_sha256",
    "codex_code_mode_host_mode",
    "codex_code_mode_host_uid",
    "codex_code_mode_host_gid",
    "codex_model_catalog_path",
    "codex_model_catalog_sha256",
    "codex_model_catalog_mode",
    "codex_model_catalog_uid",
    "codex_model_catalog_gid",
    "codex_runtime_resources",
    "command_sha256",
    "proc_cmdline_sha256",
    "proc_exe_sha256",
    "child_pid",
    "launcher_uid",
    "launcher_gid",
    "pidfd_opened",
    "codex_child_environment",
    "codex_child_environment_sha256",
    "proc_environ_sha256",
    "launch_nonce_hex",
    "launch_nonce_sha256",
    "launch_nonce_observed_in_child",
    "stdin_transport",
    "stdout_transport",
    "stderr_transport",
    "process_identity_observed_before_output_read",
}


class AIProvenanceError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise AIProvenanceError(reason)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _object(path: Path) -> dict[str, Any]:
    _require(
        path.is_file()
        and not path.is_symlink()
        and not remediation.has_symlink_component(path),
        f"AI authority material is missing or unsafe: {path}",
    )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AIProvenanceError(f"AI authority material is invalid JSON: {path}") from exc
    _require(isinstance(value, dict), f"AI authority material is not an object: {path}")
    return value


def load_authority_policy(path: Path | None = None) -> dict[str, Any]:
    path = AUTHORITY_POLICY if path is None else path
    path = path.resolve()
    _require(path == AUTHORITY_POLICY.resolve(), "AI authority policy path substitution")
    value = _object(path)
    _require(set(value) == POLICY_KEYS, "AI authority policy key set drift")
    _require(
        value.get("schema") == "milai.dg10.ai-execution-authority-policy.v2"
        and value.get("candidate_id") == remediation.CANDIDATE
        and value.get("status") == "FROZEN_ACTIVE_SEPARATE_UID_SIGNING_AUTHORITY"
        and value.get("algorithm") == "Ed25519"
        and value.get("workspace_author_can_invoke_signer") is False
        and value.get("host_root_or_kernel_compromise") == "OUT_OF_SCOPE",
        "AI authority policy semantic drift",
    )
    for key in ("authority_uid", "authority_gid"):
        _require(
            isinstance(value.get(key), int)
            and not isinstance(value[key], bool)
            and value[key] > 0,
            f"AI authority {key} invalid",
        )
    for key in ("workspace_author_uid", "workspace_author_gid"):
        _require(
            isinstance(value.get(key), int)
            and not isinstance(value[key], bool)
            and value[key] > 0,
            f"AI authority {key} invalid",
        )
    _require(
        value["authority_uid"] != value["workspace_author_uid"]
        and value["authority_gid"] != value["workspace_author_gid"],
        "AI authority is not separated from the workspace author identity",
    )
    private_key = value.get("private_key_path")
    codex_path = value.get("codex_executable_path")
    codex_host = value.get("codex_code_mode_host_path")
    codex_catalog = value.get("codex_model_catalog_path")
    codex_home = value.get("codex_home_path")
    code_root = value.get("authority_code_root")
    python_launcher = value.get("authority_python_launcher_path")
    python_executable = value.get("authority_python_executable_path")
    _require(
        all(
            isinstance(item, str) and Path(item).is_absolute()
            for item in (
                private_key,
                codex_path,
                codex_host,
                codex_catalog,
                codex_home,
                code_root,
                python_launcher,
                python_executable,
            )
        ),
        "AI authority external path invalid",
    )
    _require(
        isinstance(value.get("codex_executable_sha256"), str),
        "AI authority Codex executable digest absent",
    )
    remediation._require_sha256(
        value["codex_executable_sha256"], "AI authority Codex executable"
    )
    _require(
        value.get("codex_executable_mode") == "0555"
        and value.get("codex_executable_uid") == 0
        and value.get("codex_executable_gid") == 0,
        "AI authority Codex executable owner or mode policy drift",
    )
    _require(
        Path(str(codex_host)) == Path(str(codex_path)).with_name("codex-code-mode-host")
        and isinstance(value.get("codex_code_mode_host_sha256"), str),
        "AI authority Codex code-mode host policy drift",
    )
    remediation._require_sha256(
        value["codex_code_mode_host_sha256"], "AI authority Codex code-mode host"
    )
    _require(
        value.get("codex_code_mode_host_mode") == "0555"
        and value.get("codex_code_mode_host_uid") == 0
        and value.get("codex_code_mode_host_gid") == 0,
        "AI authority Codex code-mode host owner or mode policy drift",
    )
    _require(
        Path(str(codex_catalog)) == Path(str(codex_path)).with_name("model-catalog.json")
        and isinstance(value.get("codex_model_catalog_sha256"), str),
        "AI authority Codex model catalog policy drift",
    )
    remediation._require_sha256(
        value["codex_model_catalog_sha256"], "AI authority Codex model catalog"
    )
    _require(
        value.get("codex_model_catalog_mode") == "0444"
        and value.get("codex_model_catalog_uid") == 0
        and value.get("codex_model_catalog_gid") == 0,
        "AI authority Codex model catalog owner or mode policy drift",
    )
    resources = value.get("codex_runtime_resources")
    _require(
        isinstance(resources, Mapping)
        and set(resources) == set(CODEX_RESOURCE_PATHS),
        "AI authority Codex runtime resource closure drift",
    )
    for relative, digest in resources.items():
        _require(isinstance(relative, str), "AI authority resource path invalid")
        remediation._require_sha256(digest, f"AI authority resource {relative}")
    static_environment = value.get("codex_child_static_environment")
    expected_environment = {
        "CODEX_HOME": str(codex_home),
        "HOME": str(Path(str(codex_home)).parent),
        "PATH": (
            f"{Path(str(codex_path)).parent / 'codex-path'}:"
            "/usr/local/bin:/usr/bin:/bin"
        ),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
    }
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"):
        setting = static_environment.get(key) if isinstance(static_environment, Mapping) else None
        _require(
            isinstance(setting, str) and setting,
            f"AI authority approved proxy setting absent: {key}",
        )
        if key in {"HTTP_PROXY", "HTTPS_PROXY"}:
            parsed = urllib.parse.urlsplit(setting)
            _require(
                parsed.scheme in {"http", "https"}
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and not parsed.query
                and not parsed.fragment,
                f"AI authority approved proxy setting is unsafe: {key}",
            )
        else:
            _require("\n" not in setting and "\0" not in setting, "AI authority NO_PROXY is unsafe")
        expected_environment[key] = setting
    _require(
        static_environment == expected_environment
        and value.get("codex_child_static_environment_sha256")
        == _sha256_bytes(remediation.encoded_json(expected_environment)),
        "AI authority Codex child environment policy drift",
    )
    code_files = value.get("authority_code_files")
    _require(
        isinstance(code_files, Mapping)
        and set(code_files) == set(AUTHORITY_CODE_RELATIVE_PATHS),
        "AI authority code closure policy drift",
    )
    manifest_basis: list[dict[str, Any]] = []
    for relative in sorted(AUTHORITY_CODE_RELATIVE_PATHS):
        identity = code_files.get(relative)
        _require(
            isinstance(identity, Mapping)
            and set(identity) == {"path", "sha256", "mode", "uid", "gid"}
            and identity.get("path") == str(Path(str(code_root)) / relative)
            and identity.get("mode") == "0444"
            and identity.get("uid") == 0
            and identity.get("gid") == 0,
            f"AI authority code identity policy drift: {relative}",
        )
        remediation._require_sha256(identity.get("sha256"), f"AI authority code {relative}")
        manifest_basis.append(
            {
                "relative_path": relative,
                "sha256": identity["sha256"],
                "mode": identity["mode"],
                "uid": identity["uid"],
                "gid": identity["gid"],
            }
        )
    expected_manifest_sha256 = _sha256_bytes(
        remediation.encoded_json({"files": manifest_basis})
    )
    _require(
        value.get("authority_code_manifest_sha256") == expected_manifest_sha256
        and Path(str(code_root)).name
        == f"authority-code-sha256-{expected_manifest_sha256}",
        "AI authority code manifest identity drift",
    )
    runner_path = value.get("authority_runner_path")
    _require(
        isinstance(runner_path, str)
        and Path(runner_path).is_absolute()
        and Path(runner_path).resolve()
        == (Path(str(code_root)) / "scripts/run_dg10_candidate4_ai_audit.py").resolve()
        and code_files["scripts/run_dg10_candidate4_ai_audit.py"]["sha256"]
        == value.get("authority_runner_sha256")
        and isinstance(value.get("authority_runner_sha256"), str),
        "AI authority runner policy drift",
    )
    remediation._require_sha256(
        value["authority_runner_sha256"], "AI authority runner"
    )
    _require(
        isinstance(value.get("authority_python_launcher_target"), str)
        and value.get("authority_python_isolated_flag") == 1
        and value.get("authority_python_dont_write_bytecode_flag") == 1
        and value.get("authority_python_executable_mode") == "0755"
        and value.get("authority_python_executable_uid") == 0
        and value.get("authority_python_executable_gid") == 0,
        "AI authority Python executable policy drift",
    )
    remediation._require_sha256(
        value.get("authority_python_executable_sha256"),
        "AI authority Python executable",
    )
    runtime_roots = value.get("authority_python_runtime_roots")
    _require(
        isinstance(runtime_roots, Mapping)
        and set(runtime_roots) == {"distribution", "venv"},
        "AI authority Python runtime-root policy drift",
    )
    for name, identity in runtime_roots.items():
        _require(
            isinstance(identity, Mapping)
            and set(identity) == {"path", "entry_count", "tree_sha256"}
            and isinstance(identity.get("path"), str)
            and Path(identity["path"]).is_absolute()
            and isinstance(identity.get("entry_count"), int)
            and not isinstance(identity["entry_count"], bool)
            and identity["entry_count"] > 0,
            f"AI authority Python runtime-root identity drift: {name}",
        )
        remediation._require_sha256(
            identity.get("tree_sha256"), f"AI authority Python runtime root {name}"
        )
    loaded_libraries = value.get("authority_python_loaded_libraries")
    _require(
        isinstance(loaded_libraries, Mapping) and bool(loaded_libraries),
        "AI authority Python loaded-library policy absent",
    )
    for path, identity in loaded_libraries.items():
        _require(
            isinstance(path, str)
            and Path(path).is_absolute()
            and isinstance(identity, Mapping)
            and set(identity) == {"path", "sha256", "mode", "uid", "gid"}
            and identity.get("path") == path
            and identity.get("uid") == 0
            and identity.get("gid") == 0
            and isinstance(identity.get("mode"), str),
            f"AI authority Python loaded-library identity drift: {path}",
        )
        remediation._require_sha256(
            identity.get("sha256"), f"AI authority Python loaded library {path}"
        )
    python_sys_path = value.get("authority_python_sys_path")
    _require(
        isinstance(python_sys_path, list)
        and python_sys_path
        and python_sys_path[0] == str(code_root)
        and all(isinstance(item, str) and Path(item).is_absolute() for item in python_sys_path),
        "AI authority isolated Python sys.path policy drift",
    )
    authority_environment = value.get("authority_process_static_environment")
    expected_authority_environment = {
        "HOME": str(Path(str(codex_home)).parent),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
    }
    _require(
        authority_environment == expected_authority_environment
        and value.get("authority_process_static_environment_sha256")
        == _sha256_bytes(remediation.encoded_json(expected_authority_environment)),
        "AI authority Python process environment policy drift",
    )
    public_encoded = value.get("public_key_base64")
    try:
        public_raw = base64.b64decode(public_encoded, validate=True)
    except (TypeError, ValueError) as exc:
        raise AIProvenanceError("AI authority public key is not canonical base64") from exc
    _require(
        len(public_raw) == 32
        and value.get("public_key_sha256") == _sha256_bytes(public_raw)
        and value.get("key_id") == f"ed25519-sha256-{_sha256_bytes(public_raw)}",
        "AI authority public key identity drift",
    )
    roots = value.get("protected_attempt_roots")
    _require(
        isinstance(roots, Mapping)
        and set(roots) == {"R0_R2_PRIMARY", "TEST_ACCESS_PRIMARY", "R3_PRIMARY"}
        and all(isinstance(item, str) and Path(item).is_absolute() for item in roots.values()),
        "AI authority protected attempt roots drift",
    )
    return value


def _pidfd_open(pid: int) -> int:
    native = getattr(os, "pidfd_open", None)
    if native is not None:
        return int(native(pid))
    libc = ctypes.CDLL(None, use_errno=True)
    function = getattr(libc, "pidfd_open", None)
    if function is not None:
        function.argtypes = [ctypes.c_int, ctypes.c_uint]
        function.restype = ctypes.c_int
        descriptor = int(function(pid, 0))
    else:
        syscall = getattr(libc, "syscall", None)
        _require(syscall is not None, "Linux syscall interface unavailable")
        syscall.restype = ctypes.c_long
        descriptor = int(syscall(434, pid, 0))
    if descriptor < 0:
        error = ctypes.get_errno()
        raise AIProvenanceError(
            f"Linux pidfd_open failed with errno {error}"
        ) from OSError(error, os.strerror(error))
    return descriptor


def pinned_authority_code(
    policy: Mapping[str, Any] | None = None,
    *,
    materialized_runner: Path | None = None,
) -> dict[str, Any]:
    active = load_authority_policy() if policy is None else policy
    code_root = Path(str(active["authority_code_root"]))
    manifest = active["authority_code_files"]
    _require(
        code_root.is_dir()
        and not code_root.is_symlink()
        and not remediation.has_symlink_component(code_root)
        and code_root.stat().st_uid == 0
        and code_root.stat().st_gid == 0
        and stat.S_IMODE(code_root.stat().st_mode) == 0o555,
        "protected authority code root identity drift",
    )
    expected_directories = {Path("scripts")}
    observed_directories = {
        path.relative_to(code_root)
        for path in code_root.rglob("*")
        if path.is_dir() and not path.is_symlink()
    }
    _require(
        observed_directories == expected_directories,
        "protected authority code directory-set drift",
    )
    for relative in expected_directories:
        directory = code_root / relative
        observed = directory.stat()
        _require(
            observed.st_uid == 0
            and observed.st_gid == 0
            and stat.S_IMODE(observed.st_mode) == 0o555,
            f"protected authority code directory identity drift: {relative}",
        )
    observed_files = {
        path.relative_to(code_root).as_posix()
        for path in code_root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    _require(
        observed_files == set(AUTHORITY_CODE_RELATIVE_PATHS),
        "protected authority code file-set drift",
    )
    for relative in AUTHORITY_CODE_RELATIVE_PATHS:
        identity = manifest[relative]
        path = code_root / relative
        observed = path.stat()
        _require(
            str(path) == identity["path"]
            and observed.st_uid == identity["uid"] == 0
            and observed.st_gid == identity["gid"] == 0
            and f"{stat.S_IMODE(observed.st_mode):04o}" == identity["mode"] == "0444"
            and remediation.sha256_file(path) == identity["sha256"],
            f"protected authority code file identity drift: {relative}",
        )
    if materialized_runner is not None:
        source_runner = materialized_runner.resolve(strict=True)
        source_root = source_runner.parents[1]
        _require(
            source_runner
            == (source_root / "scripts/run_dg10_candidate4_ai_audit.py").resolve(),
            "materialized authority runner path drift",
        )
        for relative in AUTHORITY_CODE_RELATIVE_PATHS:
            source = source_root / relative
            _require(
                source.is_file()
                and not source.is_symlink()
                and remediation.sha256_file(source) == manifest[relative]["sha256"],
                f"materialized authority code differs from protected code: {relative}",
            )
    return {
        "root": str(code_root),
        "manifest_sha256": active["authority_code_manifest_sha256"],
        "files": dict(manifest),
    }


def current_python_loaded_library_closure(
    *,
    runtime_roots: Sequence[Path],
) -> dict[str, dict[str, Any]]:
    allowed = tuple(path.resolve(strict=True) for path in runtime_roots)
    mapped: set[Path] = set()
    for raw in Path("/proc/self/maps").read_text(encoding="utf-8").splitlines():
        fields = raw.split(maxsplit=5)
        if len(fields) != 6 or not fields[5].startswith("/"):
            continue
        _require(
            not fields[5].endswith(" (deleted)"),
            "authority Python maps a deleted filesystem object",
        )
        path = Path(fields[5]).resolve(strict=True)
        if any(path.is_relative_to(root) for root in allowed):
            continue
        mapped.add(path)
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(mapped, key=lambda item: item.as_posix()):
        observed = path.stat()
        _require(
            path.is_file()
            and not path.is_symlink()
            and observed.st_uid == 0
            and observed.st_gid == 0
            and stat.S_IMODE(observed.st_mode) & 0o022 == 0,
            f"authority Python loaded library is unsafe: {path}",
        )
        result[str(path)] = {
            "path": str(path),
            "sha256": remediation.sha256_file(path),
            "mode": f"{stat.S_IMODE(observed.st_mode):04o}",
            "uid": observed.st_uid,
            "gid": observed.st_gid,
        }
    return result


def pinned_authority_python_loaded_libraries(
    policy: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    expected = policy["authority_python_loaded_libraries"]
    observed: dict[str, dict[str, Any]] = {}
    for path_value in sorted(expected):
        path = Path(path_value)
        _require(
            path.is_absolute()
            and path.is_file()
            and not path.is_symlink()
            and not remediation.has_symlink_component(path),
            f"protected authority Python loaded library is unavailable: {path}",
        )
        item = path.stat()
        observed[path_value] = {
            "path": path_value,
            "sha256": remediation.sha256_file(path),
            "mode": f"{stat.S_IMODE(item.st_mode):04o}",
            "uid": item.st_uid,
            "gid": item.st_gid,
        }
    _require(
        observed == expected,
        "protected authority Python loaded-library closure drift",
    )
    return observed


def pinned_authority_python_runtime(
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    active = load_authority_policy() if policy is None else policy
    launcher = Path(str(active["authority_python_launcher_path"]))
    executable = Path(str(active["authority_python_executable_path"]))
    _require(
        launcher.is_symlink()
        and os.readlink(launcher) == active["authority_python_launcher_target"]
        and launcher.lstat().st_uid == 0
        and launcher.lstat().st_gid == 0
        and launcher.resolve(strict=True) == executable,
        "protected authority Python launcher identity drift",
    )
    observed_executable = executable.stat()
    _require(
        executable.is_file()
        and not executable.is_symlink()
        and not remediation.has_symlink_component(executable)
        and remediation.sha256_file(executable)
        == active["authority_python_executable_sha256"]
        and f"{stat.S_IMODE(observed_executable.st_mode):04o}"
        == active["authority_python_executable_mode"]
        and observed_executable.st_uid == active["authority_python_executable_uid"] == 0
        and observed_executable.st_gid == active["authority_python_executable_gid"] == 0
        and stat.S_IMODE(observed_executable.st_mode) & 0o022 == 0,
        "protected authority Python executable identity drift",
    )
    expected_roots = active["authority_python_runtime_roots"]
    root_paths = tuple(Path(str(expected_roots[name]["path"])) for name in ("distribution", "venv"))
    observed_roots = {
        name: remediation.protected_tree_identity(
            Path(str(expected_roots[name]["path"])),
            allowed_symlink_roots=root_paths,
        )
        for name in ("distribution", "venv")
    }
    _require(
        observed_roots == expected_roots,
        "protected authority Python runtime tree identity drift",
    )
    loaded_libraries = pinned_authority_python_loaded_libraries(active)
    return {
        "launcher_path": str(launcher),
        "launcher_target": os.readlink(launcher),
        "executable_path": str(executable),
        "executable_sha256": remediation.sha256_file(executable),
        "executable_mode": f"{stat.S_IMODE(observed_executable.st_mode):04o}",
        "executable_uid": observed_executable.st_uid,
        "executable_gid": observed_executable.st_gid,
        "runtime_roots": observed_roots,
        "loaded_libraries": loaded_libraries,
        "sys_path": list(active["authority_python_sys_path"]),
        "isolated_flag": active["authority_python_isolated_flag"],
        "dont_write_bytecode_flag": active[
            "authority_python_dont_write_bytecode_flag"
        ],
        "process_static_environment": dict(
            active["authority_process_static_environment"]
        ),
        "process_static_environment_sha256": active[
            "authority_process_static_environment_sha256"
        ],
    }


def validate_imported_authority_modules(
    *,
    policy: Mapping[str, Any],
    runner_path: Path,
    provenance_module_path: Path | None = None,
    remediation_module_path: Path | None = None,
) -> None:
    code = pinned_authority_code(policy)
    observed_provenance = (
        Path(__file__) if provenance_module_path is None else provenance_module_path
    )
    observed_remediation = (
        Path(remediation.__file__)
        if remediation_module_path is None
        else remediation_module_path
    )
    _require(
        runner_path.resolve(strict=True)
        == Path(str(policy["authority_runner_path"])).resolve(strict=True)
        and observed_provenance.resolve(strict=True)
        == Path(code["files"]["scripts/dg10_ai_provenance.py"]["path"])
        and observed_remediation.resolve(strict=True)
        == Path(code["files"]["scripts/dg10_remediation.py"]["path"]),
        "AI authority imported module closure drift",
    )


def assert_current_authority_process(
    *,
    policy: Mapping[str, Any] | None = None,
    runner_path: Path,
) -> None:
    active = load_authority_policy() if policy is None else policy
    _require(
        os.geteuid() == active["authority_uid"]
        and os.getegid() == active["authority_gid"],
        "AI execution must run as the separately protected authority identity",
    )
    _require(
        sys.flags.isolated == active["authority_python_isolated_flag"] == 1
        and sys.flags.dont_write_bytecode
        == active["authority_python_dont_write_bytecode_flag"]
        == 1
        and Path(sys.executable).absolute()
        == Path(str(active["authority_python_launcher_path"]))
        and sys.path == active["authority_python_sys_path"],
        "AI authority Python process is not the fixed isolated launcher",
    )
    validate_imported_authority_modules(
        policy=active,
        runner_path=runner_path,
    )
    pinned_authority_python_runtime(active)
    current_environment = _validated_proc_environment(
        Path("/proc/self/environ").read_bytes(),
        active["authority_process_static_environment"],
    )
    _require(
        _sha256_bytes(remediation.encoded_json(current_environment))
        == active["authority_process_static_environment_sha256"],
        "AI authority Python process environment digest drift",
    )
    runtime_roots = tuple(
        Path(str(active["authority_python_runtime_roots"][name]["path"]))
        for name in ("distribution", "venv")
    )
    _require(
        current_python_loaded_library_closure(runtime_roots=runtime_roots)
        == active["authority_python_loaded_libraries"],
        "AI authority Python live loaded-library closure drift",
    )


def codex_child_environment(
    *,
    policy: Mapping[str, Any] | None = None,
    launch_nonce: bytes | None = None,
) -> dict[str, str]:
    active = load_authority_policy() if policy is None else policy
    environment = dict(active["codex_child_static_environment"])
    _require(
        _sha256_bytes(remediation.encoded_json(environment))
        == active["codex_child_static_environment_sha256"],
        "Codex child static environment identity drift",
    )
    if launch_nonce is not None:
        _require(len(launch_nonce) == 32, "AI launch nonce size drift")
        environment["MILAI_DG10_AI_LAUNCH_NONCE"] = launch_nonce.hex()
    return environment


def _parse_proc_environment(raw: bytes) -> dict[str, str]:
    _require(raw.endswith(b"\0") and raw != b"\0", "Codex child environment encoding drift")
    result: dict[str, str] = {}
    for item in raw[:-1].split(b"\0"):
        key_raw, separator, value_raw = item.partition(b"=")
        _require(bool(separator) and bool(key_raw), "Codex child environment entry drift")
        try:
            key = key_raw.decode("utf-8")
            value = value_raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AIProvenanceError("Codex child environment is not UTF-8") from exc
        _require(key not in result, "Codex child environment contains duplicate key")
        result[key] = value
    return result


def _validated_proc_environment(
    raw: bytes,
    expected: Mapping[str, str],
) -> dict[str, str]:
    observed = _parse_proc_environment(raw)
    _require(observed == dict(expected), "running Codex environment identity drift")
    return observed


def pinned_codex(policy: Mapping[str, Any] | None = None) -> Path:
    active = load_authority_policy() if policy is None else policy
    executable = Path(str(active["codex_executable_path"]))
    _require(
        executable.is_absolute()
        and executable.is_file()
        and not executable.is_symlink()
        and not remediation.has_symlink_component(executable)
        and os.access(executable, os.X_OK),
        "authority Codex executable unavailable or unsafe",
    )
    mode = stat.S_IMODE(executable.stat().st_mode)
    executable_stat = executable.stat()
    _require(
        f"{mode:04o}" == active["codex_executable_mode"] == "0555"
        and executable_stat.st_uid == active["codex_executable_uid"] == 0
        and executable_stat.st_gid == active["codex_executable_gid"] == 0
        and remediation.sha256_file(executable)
        == active["codex_executable_sha256"],
        "authority Codex executable identity drift",
    )
    return executable.resolve(strict=True)


def pinned_code_mode_host(policy: Mapping[str, Any] | None = None) -> Path:
    active = load_authority_policy() if policy is None else policy
    executable = Path(str(active["codex_code_mode_host_path"]))
    codex = Path(str(active["codex_executable_path"]))
    _require(
        executable == codex.with_name("codex-code-mode-host")
        and executable.is_absolute()
        and executable.is_file()
        and not executable.is_symlink()
        and not remediation.has_symlink_component(executable)
        and os.access(executable, os.X_OK),
        "authority Codex code-mode host unavailable or unsafe",
    )
    mode = stat.S_IMODE(executable.stat().st_mode)
    executable_stat = executable.stat()
    _require(
        f"{mode:04o}" == active["codex_code_mode_host_mode"] == "0555"
        and executable_stat.st_uid == active["codex_code_mode_host_uid"] == 0
        and executable_stat.st_gid == active["codex_code_mode_host_gid"] == 0
        and remediation.sha256_file(executable)
        == active["codex_code_mode_host_sha256"],
        "authority Codex code-mode host identity drift",
    )
    return executable.resolve(strict=True)


def pinned_model_catalog(policy: Mapping[str, Any] | None = None) -> Path:
    active = load_authority_policy() if policy is None else policy
    catalog = Path(str(active["codex_model_catalog_path"]))
    codex = Path(str(active["codex_executable_path"]))
    _require(
        catalog == codex.with_name("model-catalog.json")
        and catalog.is_absolute()
        and catalog.is_file()
        and not catalog.is_symlink()
        and not remediation.has_symlink_component(catalog),
        "authority Codex model catalog unavailable or unsafe",
    )
    catalog_stat = catalog.stat()
    _require(
        catalog_stat.st_uid == active["codex_model_catalog_uid"] == 0
        and catalog_stat.st_gid == active["codex_model_catalog_gid"] == 0
        and f"{stat.S_IMODE(catalog_stat.st_mode):04o}"
        == active["codex_model_catalog_mode"]
        == "0444"
        and remediation.sha256_file(catalog)
        == active["codex_model_catalog_sha256"],
        "authority Codex model catalog identity drift",
    )
    try:
        value = json.loads(catalog.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AIProvenanceError("authority Codex model catalog is invalid JSON") from exc
    models = value.get("models") if isinstance(value, dict) else None
    _require(
        set(value) == {"models"}
        and isinstance(models, list)
        and bool(models)
        and all(isinstance(model, dict) for model in models)
        and any(model.get("slug") == MODEL for model in models),
        "authority Codex model catalog semantic drift",
    )
    return catalog.resolve(strict=True)


def pinned_codex_runtime_resources(
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Path]:
    active = load_authority_policy() if policy is None else policy
    codex = Path(str(active["codex_executable_path"]))
    expected = active["codex_runtime_resources"]
    _require(isinstance(expected, Mapping), "authority Codex resource policy absent")
    for relative in CODEX_RESOURCE_DIRECTORIES:
        directory = (codex.parent / relative).absolute()
        directory_stat = directory.stat() if directory.is_dir() else None
        _require(
            directory_stat is not None
            and not directory.is_symlink()
            and not remediation.has_symlink_component(directory)
            and directory_stat.st_uid == 0
            and directory_stat.st_gid == 0
            and stat.S_IMODE(directory_stat.st_mode) == 0o555,
            f"authority Codex runtime resource directory drift: {relative}",
        )
    observed: dict[str, Path] = {}
    for relative in CODEX_RESOURCE_PATHS:
        parsed = Path(relative)
        target = (codex.parent / parsed).absolute()
        _require(
            not parsed.is_absolute()
            and ".." not in parsed.parts
            and target.is_relative_to(codex.parent.absolute())
            and target.is_file()
            and not target.is_symlink()
            and not remediation.has_symlink_component(target)
            and os.access(target, os.X_OK),
            f"authority Codex runtime resource unavailable or unsafe: {relative}",
        )
        target_stat = target.stat()
        _require(
            target_stat.st_uid == 0
            and target_stat.st_gid == 0
            and stat.S_IMODE(target_stat.st_mode) == 0o555
            and remediation.sha256_file(target) == expected[relative],
            f"authority Codex runtime resource identity drift: {relative}",
        )
        observed[relative] = target.resolve(strict=True)
    return observed


def build_command(*, codex: Path, bundle: Path, output: Path) -> list[str]:
    model_catalog = codex.with_name("model-catalog.json")
    return [
        str(codex),
        "-a",
        "never",
        "exec",
        "-m",
        MODEL,
        "-c",
        f'model_reasoning_effort="{REASONING_EFFORT}"',
        "-c",
        f'model_catalog_json="{model_catalog}"',
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--disable",
        "shell_zsh_fork",
        "--disable",
        "unified_exec_zsh_fork",
        "--disable",
        "shell_snapshot",
        "--sandbox",
        "read-only",
        "-C",
        str(bundle),
        "--skip-git-repo-check",
        "--output-schema",
        str(bundle / "audit-response.schema.json"),
        "--json",
        "-o",
        str(output),
        "-",
    ]


def _command_raw(command: Sequence[str]) -> bytes:
    return b"".join(item.encode("utf-8") + b"\0" for item in command)


def command_sha256(command: Sequence[str]) -> str:
    return _sha256_bytes(_command_raw(command))


def execute_pinned_codex(
    *,
    command: Sequence[str],
    prompt: bytes,
    timeout_seconds: int,
    runner_path: Path,
) -> tuple[bytes, bytes, int, dict[str, Any]]:
    policy = load_authority_policy()
    assert_current_authority_process(policy=policy, runner_path=runner_path)
    _require(bool(command), "Codex command absent")
    codex = pinned_codex(policy)
    codex_host = pinned_code_mode_host(policy)
    codex_catalog = pinned_model_catalog(policy)
    codex_resources = pinned_codex_runtime_resources(policy)
    authority_code = pinned_authority_code(policy)
    authority_python_runtime = pinned_authority_python_runtime(policy)
    _require(Path(command[0]).resolve() == codex, "Codex command executable substitution")
    runner = runner_path.resolve(strict=True)
    _require(
        runner == Path(str(policy["authority_runner_path"])).resolve()
        and runner.is_file()
        and not runner.is_symlink(),
        "AI authority runner identity is unsafe",
    )
    runner_stat = runner.stat()
    _require(
        remediation.sha256_file(runner) == policy["authority_runner_sha256"]
        and runner_stat.st_uid == 0
        and runner_stat.st_gid == 0
        and runner_stat.st_mode & 0o022 == 0,
        "AI authority runner is not frozen under the host operator boundary",
    )
    nonce = os.urandom(32)
    nonce_hex = nonce.hex()
    environment = codex_child_environment(policy=policy, launch_nonce=nonce)
    process = subprocess.Popen(
        list(command),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        start_new_session=True,
    )
    pidfd: int | None = None
    try:
        pidfd = _pidfd_open(process.pid)
        proc_root = Path("/proc") / str(process.pid)
        proc_exe = Path(os.readlink(proc_root / "exe")).resolve(strict=True)
        proc_cmdline = (proc_root / "cmdline").read_bytes()
        proc_environ = (proc_root / "environ").read_bytes()
        observed_environment = _validated_proc_environment(proc_environ, environment)
        expected_cmdline = _command_raw(command)
        _require(proc_exe == codex, "running Codex executable identity drift")
        _require(proc_cmdline == expected_cmdline, "running Codex argv identity drift")
        observations = {
            "authority_code": authority_code,
            "authority_python_runtime": authority_python_runtime,
            "authority_runner_path": str(runner),
            "authority_runner_sha256": remediation.sha256_file(runner),
            "codex_executable_path": str(codex),
            "codex_executable_sha256": remediation.sha256_file(codex),
            "codex_executable_mode": f"{stat.S_IMODE(codex.stat().st_mode):04o}",
            "codex_executable_uid": codex.stat().st_uid,
            "codex_executable_gid": codex.stat().st_gid,
            "codex_code_mode_host_path": str(codex_host),
            "codex_code_mode_host_sha256": remediation.sha256_file(codex_host),
            "codex_code_mode_host_mode": f"{stat.S_IMODE(codex_host.stat().st_mode):04o}",
            "codex_code_mode_host_uid": codex_host.stat().st_uid,
            "codex_code_mode_host_gid": codex_host.stat().st_gid,
            "codex_model_catalog_path": str(codex_catalog),
            "codex_model_catalog_sha256": remediation.sha256_file(codex_catalog),
            "codex_model_catalog_mode": f"{stat.S_IMODE(codex_catalog.stat().st_mode):04o}",
            "codex_model_catalog_uid": codex_catalog.stat().st_uid,
            "codex_model_catalog_gid": codex_catalog.stat().st_gid,
            "codex_runtime_resources": {
                relative: {
                    "path": str(path),
                    "sha256": remediation.sha256_file(path),
                    "mode": f"{stat.S_IMODE(path.stat().st_mode):04o}",
                    "uid": path.stat().st_uid,
                    "gid": path.stat().st_gid,
                }
                for relative, path in codex_resources.items()
            },
            "command_sha256": _sha256_bytes(expected_cmdline),
            "proc_cmdline_sha256": _sha256_bytes(proc_cmdline),
            "proc_exe_sha256": remediation.sha256_file(proc_exe),
            "child_pid": process.pid,
            "launcher_uid": os.geteuid(),
            "launcher_gid": os.getegid(),
            "pidfd_opened": True,
            "codex_child_environment": environment,
            "codex_child_environment_sha256": _sha256_bytes(
                remediation.encoded_json(environment)
            ),
            "proc_environ_sha256": _sha256_bytes(
                remediation.encoded_json(observed_environment)
            ),
            "launch_nonce_hex": nonce_hex,
            "launch_nonce_sha256": _sha256_bytes(nonce),
            "launch_nonce_observed_in_child": True,
            "stdin_transport": "DIRECT_SUBPROCESS_PIPE",
            "stdout_transport": "DIRECT_SUBPROCESS_PIPE",
            "stderr_transport": "DIRECT_SUBPROCESS_PIPE",
            "process_identity_observed_before_output_read": True,
        }
        try:
            stdout, stderr = process.communicate(input=prompt, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            stdout, stderr = process.communicate()
            raise subprocess.TimeoutExpired(
                list(command), timeout_seconds, output=stdout, stderr=stderr
            ) from exc
        except BaseException:
            process.kill()
            process.communicate()
            raise
        return stdout, stderr, process.returncode, observations
    finally:
        if pidfd is not None:
            os.close(pidfd)


def _private_key(policy: Mapping[str, Any]) -> Ed25519PrivateKey:
    key_path = Path(str(policy["private_key_path"]))
    _require(
        key_path.is_absolute()
        and not key_path.is_relative_to(remediation.ROOT.resolve())
        and key_path.is_file()
        and not key_path.is_symlink()
        and not remediation.has_symlink_component(key_path),
        "AI authority private key is missing or unsafe",
    )
    key_stat = key_path.stat()
    parent_stat = key_path.parent.stat()
    _require(
        key_stat.st_uid == policy["authority_uid"]
        and key_stat.st_gid == policy["authority_gid"]
        and stat.S_IMODE(key_stat.st_mode) == 0o600
        and parent_stat.st_uid == policy["authority_uid"]
        and parent_stat.st_gid == policy["authority_gid"]
        and stat.S_IMODE(parent_stat.st_mode) == 0o700,
        "AI authority private-key ownership or mode drift",
    )
    try:
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    except (TypeError, ValueError) as exc:
        raise AIProvenanceError("AI authority private key cannot be loaded") from exc
    _require(isinstance(key, Ed25519PrivateKey), "AI authority private key type drift")
    public_raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    _require(
        _sha256_bytes(public_raw) == policy["public_key_sha256"],
        "AI authority private/public key mismatch",
    )
    return key


def sign_execution_attestation(
    *,
    process_claims: Mapping[str, Any],
    runtime_observations: Mapping[str, Any],
) -> dict[str, Any]:
    policy = load_authority_policy()
    _require(
        os.geteuid() == policy["authority_uid"]
        and os.getegid() == policy["authority_gid"],
        "AI execution signing requires the protected authority identity",
    )
    _require(set(runtime_observations) == RUNTIME_KEYS, "AI runtime observation key drift")
    runner_value = runtime_observations.get("authority_runner_path")
    _require(isinstance(runner_value, str), "AI runtime runner path absent")
    assert_current_authority_process(policy=policy, runner_path=Path(runner_value))
    statement = {
        "schema": "milai.dg10.ai-execution-signed-statement.v3",
        "authority_uid": policy["authority_uid"],
        "authority_gid": policy["authority_gid"],
        "process": dict(process_claims),
        "runtime_observations": dict(runtime_observations),
        "signed_after_terminal_output_hashes": True,
    }
    signature = _private_key(policy).sign(remediation.encoded_json(statement))
    return {
        "schema": "milai.dg10.ai-execution-attestation.v3",
        "channel": "ISOLATED_ROOT_CODE_PYTHON_ENV_ED25519_LIVE_CODEX_V3",
        "authority_policy_sha256": remediation.sha256_file(AUTHORITY_POLICY),
        "key_id": policy["key_id"],
        "public_key_sha256": policy["public_key_sha256"],
        "signed_statement": statement,
        "signature_base64": base64.b64encode(signature).decode("ascii"),
    }


def validate_execution_attestation(
    value: object,
    *,
    bundle: Path,
    output: Path,
    materialized_runner: Path,
    process: Mapping[str, Any],
) -> dict[str, Any]:
    policy = load_authority_policy()
    _require(
        isinstance(value, Mapping) and set(value) == ATTESTATION_KEYS,
        "AI signed execution attestation key drift",
    )
    _require(
        value.get("schema") == "milai.dg10.ai-execution-attestation.v3"
        and value.get("channel")
        == "ISOLATED_ROOT_CODE_PYTHON_ENV_ED25519_LIVE_CODEX_V3"
        and value.get("authority_policy_sha256") == remediation.sha256_file(AUTHORITY_POLICY)
        and value.get("key_id") == policy["key_id"]
        and value.get("public_key_sha256") == policy["public_key_sha256"],
        "AI signed execution authority identity drift",
    )
    statement = value.get("signed_statement")
    _require(
        isinstance(statement, Mapping)
        and set(statement) == STATEMENT_KEYS
        and statement.get("schema") == "milai.dg10.ai-execution-signed-statement.v3"
        and statement.get("authority_uid") == policy["authority_uid"]
        and statement.get("authority_gid") == policy["authority_gid"]
        and statement.get("signed_after_terminal_output_hashes") is True,
        "AI signed execution statement drift",
    )
    signature_encoded = value.get("signature_base64")
    try:
        signature = base64.b64decode(signature_encoded, validate=True)
        public_raw = base64.b64decode(policy["public_key_base64"], validate=True)
        Ed25519PublicKey.from_public_bytes(public_raw).verify(
            signature,
            remediation.encoded_json(dict(statement)),
        )
    except (TypeError, ValueError, InvalidSignature) as exc:
        raise AIProvenanceError("AI execution authority signature verification failed") from exc
    expected_process = {
        key: item for key, item in process.items() if key != "execution_attestation"
    }
    _require(statement.get("process") == expected_process, "signed AI process claims drift")
    observations = statement.get("runtime_observations")
    _require(
        isinstance(observations, Mapping) and set(observations) == RUNTIME_KEYS,
        "signed AI runtime observation key drift",
    )
    authority_code = pinned_authority_code(
        policy,
        materialized_runner=materialized_runner,
    )
    authority_python_runtime = pinned_authority_python_runtime(policy)
    runner = Path(str(policy["authority_runner_path"])).resolve(strict=True)
    _require(
        observations.get("authority_code") == authority_code
        and observations.get("authority_python_runtime") == authority_python_runtime
        and
        observations.get("authority_runner_path")
        == policy["authority_runner_path"]
        and observations.get("authority_runner_sha256")
        == policy["authority_runner_sha256"]
        == remediation.sha256_file(runner),
        "signed AI authority runner identity drift",
    )
    codex = pinned_codex(policy)
    codex_host = pinned_code_mode_host(policy)
    codex_catalog = pinned_model_catalog(policy)
    codex_resources = pinned_codex_runtime_resources(policy)
    mode = stat.S_IMODE(codex.stat().st_mode)
    _require(
        observations.get("codex_executable_path") == str(codex)
        and observations.get("codex_executable_sha256")
        == policy["codex_executable_sha256"]
        == remediation.sha256_file(codex)
        and observations.get("codex_executable_mode") == f"{mode:04o}"
        == policy["codex_executable_mode"]
        and observations.get("codex_executable_uid")
        == codex.stat().st_uid
        == policy["codex_executable_uid"]
        and observations.get("codex_executable_gid")
        == codex.stat().st_gid
        == policy["codex_executable_gid"]
        and observations.get("proc_exe_sha256")
        == observations.get("codex_executable_sha256"),
        "signed Codex executable identity drift",
    )
    host_mode = stat.S_IMODE(codex_host.stat().st_mode)
    _require(
        observations.get("codex_code_mode_host_path") == str(codex_host)
        and observations.get("codex_code_mode_host_sha256")
        == policy["codex_code_mode_host_sha256"]
        == remediation.sha256_file(codex_host)
        and observations.get("codex_code_mode_host_mode") == f"{host_mode:04o}"
        == policy["codex_code_mode_host_mode"]
        and observations.get("codex_code_mode_host_uid")
        == codex_host.stat().st_uid
        == policy["codex_code_mode_host_uid"]
        and observations.get("codex_code_mode_host_gid")
        == codex_host.stat().st_gid
        == policy["codex_code_mode_host_gid"],
        "signed Codex code-mode host identity drift",
    )
    catalog_mode = stat.S_IMODE(codex_catalog.stat().st_mode)
    _require(
        observations.get("codex_model_catalog_path") == str(codex_catalog)
        and observations.get("codex_model_catalog_sha256")
        == policy["codex_model_catalog_sha256"]
        == remediation.sha256_file(codex_catalog)
        and observations.get("codex_model_catalog_mode") == f"{catalog_mode:04o}"
        == policy["codex_model_catalog_mode"]
        and observations.get("codex_model_catalog_uid")
        == codex_catalog.stat().st_uid
        == policy["codex_model_catalog_uid"]
        and observations.get("codex_model_catalog_gid")
        == codex_catalog.stat().st_gid
        == policy["codex_model_catalog_gid"],
        "signed Codex model catalog identity drift",
    )
    expected_resources = {
        relative: {
            "path": str(path),
            "sha256": remediation.sha256_file(path),
            "mode": f"{stat.S_IMODE(path.stat().st_mode):04o}",
            "uid": path.stat().st_uid,
            "gid": path.stat().st_gid,
        }
        for relative, path in codex_resources.items()
    }
    _require(
        observations.get("codex_runtime_resources") == expected_resources,
        "signed Codex runtime resource closure drift",
    )
    expected_command = build_command(codex=codex, bundle=bundle, output=output)
    expected_digest = command_sha256(expected_command)
    _require(
        observations.get("command_sha256") == expected_digest
        and observations.get("proc_cmdline_sha256") == expected_digest,
        "signed Codex command identity drift",
    )
    _require(
        isinstance(observations.get("child_pid"), int)
        and not isinstance(observations["child_pid"], bool)
        and observations["child_pid"] > 1
        and observations.get("launcher_uid") == policy["authority_uid"]
        and observations.get("launcher_gid") == policy["authority_gid"]
        and observations.get("pidfd_opened") is True
        and observations.get("launch_nonce_observed_in_child") is True
        and observations.get("process_identity_observed_before_output_read") is True
        and observations.get("stdin_transport") == "DIRECT_SUBPROCESS_PIPE"
        and observations.get("stdout_transport") == "DIRECT_SUBPROCESS_PIPE"
        and observations.get("stderr_transport") == "DIRECT_SUBPROCESS_PIPE",
        "signed AI live execution observation failed",
    )
    nonce_hex = observations.get("launch_nonce_hex")
    _require(
        isinstance(nonce_hex, str)
        and len(nonce_hex) == 64
        and nonce_hex == nonce_hex.lower(),
        "signed AI launch nonce encoding drift",
    )
    try:
        nonce = bytes.fromhex(nonce_hex)
    except ValueError as exc:
        raise AIProvenanceError("signed AI launch nonce encoding drift") from exc
    expected_environment = codex_child_environment(
        policy=policy,
        launch_nonce=nonce,
    )
    expected_environment_sha256 = _sha256_bytes(
        remediation.encoded_json(expected_environment)
    )
    _require(
        observations.get("codex_child_environment") == expected_environment
        and observations.get("codex_child_environment_sha256")
        == expected_environment_sha256
        and observations.get("proc_environ_sha256")
        == expected_environment_sha256,
        "signed Codex child environment identity drift",
    )
    remediation._require_sha256(
        observations.get("launch_nonce_sha256"), "signed AI launch nonce"
    )
    _require(
        observations.get("launch_nonce_sha256") == _sha256_bytes(nonce),
        "signed AI launch nonce digest drift",
    )
    output_stat = output.stat()
    attempt_stat = output.parent.stat()
    _require(
        output_stat.st_uid == policy["authority_uid"]
        and output_stat.st_gid == policy["authority_gid"]
        and attempt_stat.st_uid == policy["authority_uid"]
        and attempt_stat.st_gid == policy["authority_gid"],
        "signed AI attempt is not owned by the protected authority",
    )
    return dict(value)
