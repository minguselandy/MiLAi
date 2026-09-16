from __future__ import annotations

import argparse
import base64
import json
import os
import pwd
import shutil
import stat
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_remediation as remediation

AUTHORITY_USER = "milai-dg10-audit"
WORKSPACE_AUTHOR_USER = "www"
AUTHORITY_ROOT = Path("/var/lib/milai-dg10-ai-authority")
PRIVATE_DIRECTORY = AUTHORITY_ROOT / "private"
PRIVATE_KEY = PRIVATE_DIRECTORY / "ed25519-private.pem"
CODEX_HOME = AUTHORITY_ROOT / "codex-home"
CODEX_EXECUTABLE = Path("/usr/local/libexec/milai-dg10-ai-authority/codex")
CODEX_CODE_MODE_HOST = CODEX_EXECUTABLE.with_name("codex-code-mode-host")
CODEX_MODEL_CATALOG = CODEX_EXECUTABLE.with_name("model-catalog.json")
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
AUTHORITY_PYTHON_DISTRIBUTION = Path(
    "/usr/local/libexec/milai-dg10-ai-authority/python-3.11"
)
AUTHORITY_VENV = Path("/usr/local/libexec/milai-dg10-ai-authority/venv")
AUTHORITY_PYTHON = AUTHORITY_VENV / "bin/python"
AUTHORITY_CODE_PARENT = Path("/usr/local/libexec/milai-dg10-ai-authority")
AUTHORITY_CODE_RELATIVE_PATHS = (
    "scripts/__init__.py",
    "scripts/dg10_remediation.py",
    "scripts/dg10_ai_provenance.py",
    "scripts/run_dg10_candidate4_ai_audit.py",
)
AUTHORITY_RUNNER_RELATIVE_PATH = "scripts/run_dg10_candidate4_ai_audit.py"
APPROVED_PROXY_ENVIRONMENT_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")
SOURCE_CODEX_HOME = Path("/root/.codex")
PROTECTED_ATTEMPT_ROOTS = {
    "R0_R2_PRIMARY": ROOT.parent
    / "evidence/dg10-candidate4-xhigh-ai-r0-r2-authority-audits",
    "TEST_ACCESS_PRIMARY": ROOT.parent
    / "evidence/dg10-candidate4-xhigh-ai-test-access-authority-audits",
    "R3_PRIMARY": ROOT.parent
    / "evidence/dg10-candidate4-xhigh-ai-r3-authority-audits",
}
REVIEW_ROOTS = (
    ROOT.parent / "evidence/dg10-candidate4-xhigh-ai-r0-r2-review",
    ROOT.parent / "evidence/dg10-candidate4-ai-test-access-review",
    ROOT.parent / "evidence/dg10-candidate4-xhigh-ai-r3-review",
)


class AuthorityProvisionError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise AuthorityProvisionError(reason)


def _authority_identity() -> tuple[int, int]:
    try:
        entry = pwd.getpwnam(AUTHORITY_USER)
    except KeyError:
        completed = subprocess.run(
            [
                "/usr/sbin/useradd",
                "--system",
                "--home-dir",
                str(AUTHORITY_ROOT),
                "--shell",
                "/usr/sbin/nologin",
                "--no-create-home",
                AUTHORITY_USER,
            ],
            check=False,
            capture_output=True,
        )
        _require(completed.returncode == 0, "failed to create AI authority identity")
        entry = pwd.getpwnam(AUTHORITY_USER)
    _require(
        entry.pw_dir == str(AUTHORITY_ROOT)
        and entry.pw_shell == "/usr/sbin/nologin"
        and entry.pw_uid > 0
        and entry.pw_gid > 0,
        "AI authority account identity drift",
    )
    return entry.pw_uid, entry.pw_gid


def _directory(path: Path, *, mode: int, uid: int, gid: int) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    os.chown(path, uid, gid)
    path.chmod(mode)
    observed = path.stat()
    _require(
        observed.st_uid == uid
        and observed.st_gid == gid
        and stat.S_IMODE(observed.st_mode) == mode,
        f"AI authority directory mode/owner drift: {path}",
    )


def _write_new(path: Path, raw: bytes, *, mode: int, uid: int, gid: int) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        if path.exists():
            path.unlink()
        raise
    os.chown(path, uid, gid)
    path.chmod(mode)


def _copy_or_verify(
    source: Path, target: Path, *, mode: int, uid: int, gid: int
) -> None:
    source = source.resolve(strict=True)
    if target.exists():
        _require(
            target.is_file()
            and not target.is_symlink()
            and target.read_bytes() == source.read_bytes(),
            f"existing protected authority material drift: {target}",
        )
        os.chown(target, uid, gid)
        target.chmod(mode)
        return
    _write_new(target, source.read_bytes(), mode=mode, uid=uid, gid=gid)


def _canonical_model_catalog(source: Path) -> bytes:
    _require(
        source.is_file() and not source.is_symlink(),
        "source Codex model cache is absent or unsafe",
    )
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AuthorityProvisionError("source Codex model cache is invalid JSON") from exc
    models = value.get("models") if isinstance(value, dict) else None
    _require(
        isinstance(models, list)
        and bool(models)
        and all(isinstance(model, dict) for model in models)
        and any(model.get("slug") == "gpt-5.6-sol" for model in models),
        "source Codex model cache does not contain the required audit model",
    )
    return remediation.encoded_json({"models": models})


def _provision_model_catalog() -> None:
    if CODEX_MODEL_CATALOG.exists():
        _require(
            CODEX_MODEL_CATALOG.is_file()
            and not CODEX_MODEL_CATALOG.is_symlink()
            and CODEX_MODEL_CATALOG.read_bytes()
            == _canonical_model_catalog(CODEX_MODEL_CATALOG),
            "existing protected Codex model catalog is invalid",
        )
        os.chown(CODEX_MODEL_CATALOG, 0, 0)
        CODEX_MODEL_CATALOG.chmod(0o444)
        return
    source = SOURCE_CODEX_HOME / "models_cache.json"
    _write_new(
        CODEX_MODEL_CATALOG,
        _canonical_model_catalog(source),
        mode=0o444,
        uid=0,
        gid=0,
    )


def _python_runtime() -> None:
    source_python = Path(sys.executable).resolve(strict=True)
    source_distribution = source_python.parents[1]
    _require(
        source_python.name.startswith("python3.11")
        and source_distribution.is_dir(),
        "authority provisioning requires the frozen Python 3.11 distribution",
    )
    if not AUTHORITY_PYTHON_DISTRIBUTION.exists():
        shutil.copytree(
            source_distribution,
            AUTHORITY_PYTHON_DISTRIBUTION,
            symlinks=True,
        )
    _require(
        (AUTHORITY_PYTHON_DISTRIBUTION / "bin/python3.11").is_file(),
        "protected authority Python distribution is incomplete",
    )
    if not AUTHORITY_PYTHON.exists():
        created = subprocess.run(
            [
                "/usr/local/bin/uv",
                "venv",
                "--python",
                str(AUTHORITY_PYTHON_DISTRIBUTION / "bin/python3.11"),
                str(AUTHORITY_VENV),
            ],
            check=False,
            capture_output=True,
        )
        _require(created.returncode == 0, "failed to create protected authority venv")
        installed = subprocess.run(
            [
                "/usr/local/bin/uv",
                "pip",
                "install",
                "--offline",
                "--python",
                str(AUTHORITY_PYTHON),
                "cryptography==50.0.0",
            ],
            check=False,
            capture_output=True,
        )
        _require(installed.returncode == 0, "failed to install protected authority crypto runtime")
    _require(
        AUTHORITY_PYTHON.is_file()
        and not remediation.has_symlink_component(AUTHORITY_PYTHON.resolve()),
        "protected authority Python runtime is unsafe",
    )
    for root in (AUTHORITY_PYTHON_DISTRIBUTION, AUTHORITY_VENV):
        for path in [root, *root.rglob("*")]:
            if path.is_symlink():
                os.lchown(path, 0, 0)
            else:
                os.chown(path, 0, 0)
                path.chmod(stat.S_IMODE(path.stat().st_mode) & ~0o022)


def _authority_code() -> tuple[Path, dict[str, dict[str, Any]], str]:
    sources = {relative: ROOT / relative for relative in AUTHORITY_CODE_RELATIVE_PATHS}
    for relative, source in sources.items():
        _require(
            source.is_file()
            and not source.is_symlink()
            and not remediation.has_symlink_component(source),
            f"authority source code is absent or unsafe: {relative}",
        )
    manifest_basis = [
        {
            "relative_path": relative,
            "sha256": remediation.sha256_file(source),
            "mode": "0444",
            "uid": 0,
            "gid": 0,
        }
        for relative, source in sorted(sources.items())
    ]
    manifest_sha256 = remediation.sha256_bytes(
        remediation.encoded_json({"files": manifest_basis})
    )
    code_root = AUTHORITY_CODE_PARENT / f"authority-code-sha256-{manifest_sha256}"
    expected_files = {Path(relative) for relative in AUTHORITY_CODE_RELATIVE_PATHS}
    if code_root.exists():
        _require(
            code_root.is_dir() and not code_root.is_symlink(),
            "existing protected authority code root is unsafe",
        )
    else:
        code_root.mkdir(mode=0o555)
    scripts_directory = code_root / "scripts"
    if scripts_directory.exists():
        _require(
            scripts_directory.is_dir() and not scripts_directory.is_symlink(),
            "existing protected authority package directory is unsafe",
        )
    else:
        scripts_directory.mkdir(mode=0o555)
    for relative, source in sources.items():
        target = code_root / relative
        _copy_or_verify(source, target, mode=0o444, uid=0, gid=0)
    observed_files = {
        path.relative_to(code_root)
        for path in code_root.rglob("*")
        if path.is_file()
    }
    _require(observed_files == expected_files, "protected authority code file-set drift")
    for directory in (scripts_directory, code_root):
        os.chown(directory, 0, 0)
        directory.chmod(0o555)
    manifest = {
        relative: {
            "path": str(code_root / relative),
            "sha256": remediation.sha256_file(code_root / relative),
            "mode": "0444",
            "uid": 0,
            "gid": 0,
        }
        for relative in AUTHORITY_CODE_RELATIVE_PATHS
    }
    return code_root, manifest, manifest_sha256


def _authority_process_environment() -> dict[str, str]:
    return {
        "HOME": str(AUTHORITY_ROOT),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
    }


def _isolated_python_sys_path(code_root: Path) -> list[str]:
    probe = subprocess.run(
        [
            str(AUTHORITY_PYTHON),
            "-I",
            "-B",
            "-c",
            "import json,sys;print(json.dumps({'isolated':sys.flags.isolated,'path':sys.path}))",
        ],
        check=False,
        capture_output=True,
        env=_authority_process_environment(),
    )
    _require(probe.returncode == 0, "protected authority Python isolation probe failed")
    try:
        value = json.loads(probe.stdout)
    except json.JSONDecodeError as exc:
        raise AuthorityProvisionError("protected authority Python probe is invalid") from exc
    path = value.get("path") if isinstance(value, dict) else None
    _require(
        value.get("isolated") == 1
        and isinstance(path, list)
        and all(isinstance(item, str) and Path(item).is_absolute() for item in path),
        "protected authority Python is not isolated",
    )
    return [str(code_root), *path]


def _loaded_library_closure(code_root: Path) -> dict[str, dict[str, Any]]:
    source = (
        "import json,sys;"
        f"sys.path.insert(0,{str(code_root)!r});"
        "from pathlib import Path;"
        "from scripts import dg10_ai_provenance as p;"
        f"roots=(Path({str(AUTHORITY_PYTHON_DISTRIBUTION)!r}),"
        f"Path({str(AUTHORITY_VENV)!r}));"
        "print(json.dumps(p.current_python_loaded_library_closure(runtime_roots=roots),sort_keys=True))"
    )
    probe = subprocess.run(
        [str(AUTHORITY_PYTHON), "-I", "-B", "-c", source],
        check=False,
        capture_output=True,
        env=_authority_process_environment(),
    )
    _require(probe.returncode == 0, "protected authority loaded-library probe failed")
    try:
        value = json.loads(probe.stdout)
    except json.JSONDecodeError as exc:
        raise AuthorityProvisionError("protected authority loaded-library probe is invalid") from exc
    _require(isinstance(value, dict) and bool(value), "protected authority loaded-library closure absent")
    return value


def _approved_proxy_environment() -> dict[str, str]:
    values: dict[str, str] = {}
    for key in APPROVED_PROXY_ENVIRONMENT_KEYS:
        value = os.environ.get(key)
        _require(isinstance(value, str) and value, f"approved proxy setting absent: {key}")
        if key in {"HTTP_PROXY", "HTTPS_PROXY"}:
            parsed = urllib.parse.urlsplit(value)
            _require(
                parsed.scheme in {"http", "https"}
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and not parsed.query
                and not parsed.fragment,
                f"approved proxy setting is unsafe: {key}",
            )
        else:
            _require("\n" not in value and "\0" not in value, "NO_PROXY is unsafe")
        values[key] = value
    return values


def provision() -> dict[str, Any]:
    _require(os.geteuid() == 0, "AI authority provisioning requires host root")
    uid, gid = _authority_identity()
    try:
        workspace_author = pwd.getpwnam(WORKSPACE_AUTHOR_USER)
    except KeyError as exc:
        raise AuthorityProvisionError("workspace author identity is absent") from exc
    _require(
        workspace_author.pw_uid > 0
        and workspace_author.pw_gid > 0
        and workspace_author.pw_uid != uid
        and workspace_author.pw_gid != gid,
        "workspace author and AI authority identities are not separated",
    )
    _directory(AUTHORITY_ROOT, mode=0o750, uid=0, gid=gid)
    _directory(PRIVATE_DIRECTORY, mode=0o700, uid=uid, gid=gid)
    _directory(CODEX_HOME, mode=0o700, uid=uid, gid=gid)
    executable_parent = CODEX_EXECUTABLE.parent
    _directory(executable_parent, mode=0o755, uid=0, gid=0)
    _python_runtime()
    authority_code_root, authority_code_files, authority_code_manifest_sha256 = (
        _authority_code()
    )

    discovered = shutil.which("codex")
    _require(isinstance(discovered, str) and discovered, "source Codex executable absent")
    source_codex = Path(discovered).resolve(strict=True)
    _require(
        source_codex.is_file()
        and not source_codex.is_symlink()
        and stat.S_IMODE(source_codex.stat().st_mode) & 0o022 == 0,
        "source Codex executable is unsafe",
    )
    _copy_or_verify(source_codex, CODEX_EXECUTABLE, mode=0o555, uid=0, gid=0)
    source_code_mode_host = source_codex.with_name("codex-code-mode-host")
    _require(
        source_code_mode_host.is_file()
        and not source_code_mode_host.is_symlink()
        and stat.S_IMODE(source_code_mode_host.stat().st_mode) & 0o022 == 0,
        "source Codex code-mode host is unsafe",
    )
    _copy_or_verify(
        source_code_mode_host,
        CODEX_CODE_MODE_HOST,
        mode=0o555,
        uid=0,
        gid=0,
    )
    _provision_model_catalog()
    source_release = source_codex.parent.parent
    for relative in CODEX_RESOURCE_DIRECTORIES:
        _directory(
            CODEX_EXECUTABLE.parent / relative,
            mode=0o555,
            uid=0,
            gid=0,
        )
    for relative in CODEX_RESOURCE_PATHS:
        if relative == "codex-resources/zsh/bin/zsh":
            discovered_zsh = shutil.which("zsh")
            _require(
                isinstance(discovered_zsh, str) and discovered_zsh,
                "compatible host zsh executable absent",
            )
            source_resource = Path(discovered_zsh).resolve(strict=True)
        else:
            source_resource = source_release / relative
        target_resource = CODEX_EXECUTABLE.parent / relative
        _require(
            source_resource.is_file()
            and not source_resource.is_symlink()
            and stat.S_IMODE(source_resource.stat().st_mode) & 0o022 == 0,
            f"source Codex runtime resource is unsafe: {relative}",
        )
        if relative == "codex-resources/zsh/bin/zsh":
            probe = subprocess.run(
                [str(source_resource), "--version"],
                check=False,
                capture_output=True,
            )
            _require(
                probe.returncode == 0 and probe.stdout.startswith(b"zsh "),
                "compatible host zsh executable probe failed",
            )
        _copy_or_verify(source_resource, target_resource, mode=0o555, uid=0, gid=0)
    authority_runner = authority_code_root / AUTHORITY_RUNNER_RELATIVE_PATH
    runner_stat = authority_runner.stat()
    _require(
        authority_runner.is_file()
        and not authority_runner.is_symlink()
        and runner_stat.st_uid == 0
        and runner_stat.st_gid == 0
        and runner_stat.st_mode & 0o022 == 0,
        "AI authority runner is not frozen under the host operator boundary",
    )
    for name in ("auth.json", "installation_id"):
        source = SOURCE_CODEX_HOME / name
        _require(source.is_file() and not source.is_symlink(), f"Codex credential material absent: {name}")
        _copy_or_verify(source, CODEX_HOME / name, mode=0o600, uid=uid, gid=gid)

    if PRIVATE_KEY.exists():
        key_raw = PRIVATE_KEY.read_bytes()
    else:
        private_key = Ed25519PrivateKey.generate()
        key_raw = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        _write_new(PRIVATE_KEY, key_raw, mode=0o600, uid=uid, gid=gid)
    try:
        loaded = serialization.load_pem_private_key(key_raw, password=None)
    except (TypeError, ValueError) as exc:
        raise AuthorityProvisionError("protected authority key cannot be loaded") from exc
    _require(isinstance(loaded, Ed25519PrivateKey), "protected authority key type drift")
    public_raw = loaded.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_sha256 = remediation.sha256_bytes(public_raw)

    runtime_roots = (AUTHORITY_PYTHON_DISTRIBUTION, AUTHORITY_VENV)
    authority_python_runtime_roots = {
        "distribution": remediation.protected_tree_identity(
            AUTHORITY_PYTHON_DISTRIBUTION,
            allowed_symlink_roots=runtime_roots,
        ),
        "venv": remediation.protected_tree_identity(
            AUTHORITY_VENV,
            allowed_symlink_roots=runtime_roots,
        ),
    }
    authority_python_executable = AUTHORITY_PYTHON.resolve(strict=True)
    authority_python_executable_stat = authority_python_executable.stat()
    authority_python_launcher_stat = AUTHORITY_PYTHON.lstat()
    _require(
        AUTHORITY_PYTHON.is_symlink()
        and authority_python_launcher_stat.st_uid == 0
        and authority_python_launcher_stat.st_gid == 0
        and authority_python_executable_stat.st_uid == 0
        and authority_python_executable_stat.st_gid == 0
        and not stat.S_IMODE(authority_python_executable_stat.st_mode) & 0o022,
        "protected authority Python launcher identity drift",
    )
    authority_python_sys_path = _isolated_python_sys_path(authority_code_root)
    authority_python_loaded_libraries = _loaded_library_closure(authority_code_root)
    authority_process_static_environment = _authority_process_environment()
    codex_child_static_environment = {
        "CODEX_HOME": str(CODEX_HOME),
        "HOME": str(AUTHORITY_ROOT),
        "PATH": (
            f"{CODEX_EXECUTABLE.parent / 'codex-path'}:"
            "/usr/local/bin:/usr/bin:/bin"
        ),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        **_approved_proxy_environment(),
    }

    for attempt_root in PROTECTED_ATTEMPT_ROOTS.values():
        _directory(attempt_root, mode=0o700, uid=uid, gid=gid)
    for review_root in REVIEW_ROOTS:
        if review_root.exists():
            _require(
                review_root.is_dir() and not review_root.is_symlink(),
                f"AI review root is unsafe: {review_root}",
            )
            os.chown(review_root, 0, gid)
            review_root.chmod(0o750)

    return {
        "schema": "milai.dg10.ai-execution-authority-policy.v2",
        "candidate_id": remediation.CANDIDATE,
        "status": "FROZEN_ACTIVE_SEPARATE_UID_SIGNING_AUTHORITY",
        "algorithm": "Ed25519",
        "key_id": f"ed25519-sha256-{public_sha256}",
        "public_key_base64": base64.b64encode(public_raw).decode("ascii"),
        "public_key_sha256": public_sha256,
        "authority_uid": uid,
        "authority_gid": gid,
        "workspace_author_uid": workspace_author.pw_uid,
        "workspace_author_gid": workspace_author.pw_gid,
        "private_key_path": str(PRIVATE_KEY),
        "codex_executable_path": str(CODEX_EXECUTABLE),
        "codex_executable_sha256": remediation.sha256_file(CODEX_EXECUTABLE),
        "codex_executable_mode": "0555",
        "codex_executable_uid": 0,
        "codex_executable_gid": 0,
        "codex_code_mode_host_path": str(CODEX_CODE_MODE_HOST),
        "codex_code_mode_host_sha256": remediation.sha256_file(
            CODEX_CODE_MODE_HOST
        ),
        "codex_code_mode_host_mode": "0555",
        "codex_code_mode_host_uid": 0,
        "codex_code_mode_host_gid": 0,
        "codex_model_catalog_path": str(CODEX_MODEL_CATALOG),
        "codex_model_catalog_sha256": remediation.sha256_file(
            CODEX_MODEL_CATALOG
        ),
        "codex_model_catalog_mode": "0444",
        "codex_model_catalog_uid": 0,
        "codex_model_catalog_gid": 0,
        "codex_runtime_resources": {
            relative: remediation.sha256_file(CODEX_EXECUTABLE.parent / relative)
            for relative in CODEX_RESOURCE_PATHS
        },
        "codex_home_path": str(CODEX_HOME),
        "codex_child_static_environment": codex_child_static_environment,
        "codex_child_static_environment_sha256": remediation.sha256_bytes(
            remediation.encoded_json(codex_child_static_environment)
        ),
        "authority_code_root": str(authority_code_root),
        "authority_code_manifest_sha256": authority_code_manifest_sha256,
        "authority_code_files": authority_code_files,
        "authority_runner_path": str(authority_runner),
        "authority_runner_sha256": remediation.sha256_file(authority_runner),
        "authority_python_launcher_path": str(AUTHORITY_PYTHON),
        "authority_python_launcher_target": os.readlink(AUTHORITY_PYTHON),
        "authority_python_executable_path": str(authority_python_executable),
        "authority_python_executable_sha256": remediation.sha256_file(
            authority_python_executable
        ),
        "authority_python_executable_mode": (
            f"{stat.S_IMODE(authority_python_executable_stat.st_mode):04o}"
        ),
        "authority_python_executable_uid": authority_python_executable_stat.st_uid,
        "authority_python_executable_gid": authority_python_executable_stat.st_gid,
        "authority_python_runtime_roots": authority_python_runtime_roots,
        "authority_python_loaded_libraries": authority_python_loaded_libraries,
        "authority_python_sys_path": authority_python_sys_path,
        "authority_python_isolated_flag": 1,
        "authority_python_dont_write_bytecode_flag": 1,
        "authority_process_static_environment": authority_process_static_environment,
        "authority_process_static_environment_sha256": remediation.sha256_bytes(
            remediation.encoded_json(authority_process_static_environment)
        ),
        "protected_attempt_roots": {
            key: str(path) for key, path in PROTECTED_ATTEMPT_ROOTS.items()
        },
        "workspace_author_can_invoke_signer": False,
        "host_root_or_kernel_compromise": "OUT_OF_SCOPE",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provision the separate-UID DG-10 AI execution authority"
    )
    parser.add_argument(
        "--apply-host-changes",
        action="store_true",
        help="required acknowledgement for host user, key, credential, and ownership changes",
    )
    args = parser.parse_args()
    _require(args.apply_host_changes, "host-change acknowledgement is required")
    print(json.dumps(provision(), sort_keys=True))


if __name__ == "__main__":
    main()
