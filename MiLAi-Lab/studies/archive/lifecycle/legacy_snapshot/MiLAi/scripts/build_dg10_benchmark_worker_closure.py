from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import inspect
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import dg10_remediation as remediation

ROOT = remediation.ROOT
PROJECT = ROOT / "evals/dg10"
LOCK = PROJECT / "uv.lock"
PYPROJECT = PROJECT / "pyproject.toml"
BFCL_ROOT = ROOT.parent / "benchmarks/gorilla-bfcl/berkeley-function-call-leaderboard"
DEFAULT_OUTPUT = ROOT / (
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.28-2026-08-22.json"
)
DEFAULT_CAPTURE_ROOT = ROOT.parent / "evidence/dg10-remediation-worker-closure"
EXPECTED_MPMATH_TREE_SHA256 = (
    "376efeae63abdfd9378ce98ddb38509387ba0237c82e8e70429ddea11089079b"
)
PASS_PATTERN = re.compile(r"(?P<passed>\d+) passed")


class WorkerClosureError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise WorkerClosureError(reason)


def _run(
    command: list[str],
    *,
    environment: dict[str, str] | None = None,
    timeout: float = 180.0,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _require_success(result: subprocess.CompletedProcess[bytes], label: str) -> None:
    if result.returncode != 0:
        diagnostic = (result.stdout + result.stderr)[-4000:].decode(errors="replace")
        raise WorkerClosureError(f"{label} failed: {diagnostic}")


def _command_identity(command: str) -> dict[str, Any]:
    path_value = shutil.which(command)
    if path_value is None:
        raise WorkerClosureError(f"required executable is missing: {command}")
    path = Path(path_value).resolve()
    version = _run([str(path), "--version"])
    _require_success(version, f"{command} version")
    return {
        "name": command,
        "path_class": "HOST_EXECUTABLE",
        "sha256": remediation.sha256_file(path),
        "size": path.stat().st_size,
        "version": version.stdout.decode(errors="replace").strip(),
    }


def _git_head(path: Path) -> str:
    result = _run(["git", "-C", str(path), "rev-parse", "HEAD"])
    _require_success(result, "BFCL git identity")
    value = result.stdout.decode().strip()
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise WorkerClosureError("BFCL commit is not a full lowercase Git object ID")
    return value


def _tree_closure(path: Path) -> dict[str, Any]:
    files = sorted(
        item
        for item in path.rglob("*")
        if item.is_file() and "__pycache__" not in item.parts
    )
    digest = hashlib.sha256()
    for item in files:
        relative = item.relative_to(path).as_posix()
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(item.read_bytes())
    return {"file_count": len(files), "tree_sha256": digest.hexdigest()}


def _imported_file_closure() -> dict[str, Any]:
    modules = (
        "mpmath",
        "yaml",
        "tree_sitter",
        "tree_sitter_java",
        "tree_sitter_javascript",
    )
    entries: list[dict[str, Any]] = []
    for name in modules:
        module = importlib.import_module(name)
        path = Path(inspect.getfile(module)).resolve()
        entries.append(
            {
                "module": name,
                "path_class": "BENCHMARK_VENV_SITE_PACKAGE",
                "basename": path.name,
                "sha256": remediation.sha256_file(path),
                "size": path.stat().st_size,
            }
        )
    entries.sort(key=lambda item: item["module"])
    return {
        "entry_count": len(entries),
        "entries_sha256": remediation.sha256_bytes(remediation.encoded_json({"entries": entries})),
        "entries": entries,
    }


def _distribution_closure() -> dict[str, Any]:
    distributions = sorted(
        {
            (
                str(distribution.metadata.get("Name") or "").lower(),
                distribution.version,
            )
            for distribution in importlib.metadata.distributions()
            if distribution.metadata.get("Name")
        }
    )
    rows = [{"name": name, "version": version} for name, version in distributions]
    return {
        "distribution_count": len(rows),
        "canonical_sha256": remediation.sha256_bytes(
            remediation.encoded_json({"distributions": rows})
        ),
        "distributions": rows,
    }


def _environment_identity() -> dict[str, Any]:
    executable = Path(sys.executable).absolute()
    executable_bytes = executable.resolve()
    environment_prefix = Path(sys.prefix).resolve()
    project_environment = (PROJECT / ".venv").resolve()
    allowed_prefixes = {project_environment}
    configured_environment = os.environ.get("UV_PROJECT_ENVIRONMENT")
    if configured_environment:
        configured_path = Path(configured_environment)
        if not configured_path.is_absolute():
            raise WorkerClosureError("UV_PROJECT_ENVIRONMENT must be absolute")
        allowed_prefixes.add(configured_path.resolve())
    if environment_prefix not in allowed_prefixes:
        raise WorkerClosureError("worker closure must run in evals/dg10/.venv")
    if environment_prefix == (ROOT / "runtime/.venv").resolve():
        raise WorkerClosureError("runtime/.venv is forbidden for benchmark work")
    freeze = _run(["uv", "pip", "freeze", "--python", sys.executable])
    _require_success(freeze, "benchmark environment freeze")
    mpmath_module = importlib.import_module("mpmath")
    mpmath_tree = _tree_closure(Path(inspect.getfile(mpmath_module)).resolve().parent)
    if (
        getattr(mpmath_module, "__version__", None) != "1.3.0"
        or mpmath_tree["file_count"] != 87
        or mpmath_tree["tree_sha256"] != EXPECTED_MPMATH_TREE_SHA256
    ):
        raise WorkerClosureError("mpmath imported-file closure drifted")
    os_release = Path("/etc/os-release")
    platform_record = {
        "system": platform.system(),
        "machine": platform.machine(),
        "release": platform.release(),
        "python_platform": platform.platform(),
        "os_release_sha256": (
            remediation.sha256_file(os_release) if os_release.is_file() else "UNAVAILABLE"
        ),
    }
    return {
        "python": {
            "version": platform.python_version(),
            "executable_path_class": "EVALS_DG10_VENV",
            "environment_instance": (
                "PROJECT_LOCKED_VENV"
                if environment_prefix == project_environment
                else "FRESH_EXPLICIT_LOCKED_VENV"
            ),
            "executable_sha256": remediation.sha256_file(executable_bytes),
            "executable_size": executable_bytes.stat().st_size,
        },
        "uv": _command_identity("uv"),
        "lock": {
            "path": LOCK.relative_to(ROOT).as_posix(),
            "sha256": remediation.sha256_file(LOCK),
            "size": LOCK.stat().st_size,
        },
        "pyproject": {
            "path": PYPROJECT.relative_to(ROOT).as_posix(),
            "sha256": remediation.sha256_file(PYPROJECT),
            "size": PYPROJECT.stat().st_size,
        },
        "pip_freeze_sha256": remediation.sha256_bytes(freeze.stdout),
        "pip_freeze_line_count": len(freeze.stdout.splitlines()),
        "distributions": _distribution_closure(),
        "imported_files": _imported_file_closure(),
        "mpmath": {"version": "1.3.0", **mpmath_tree},
        "platform": {
            **platform_record,
            "identity_sha256": remediation.sha256_bytes(
                remediation.encoded_json(platform_record)
            ),
        },
    }


def _fresh_install_probe(capture_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="dg10-worker-fresh-") as temporary_name:
        temporary = Path(temporary_name)
        run_directory = capture_root / f"candidate.4-{os.getpid()}"
        run_directory.mkdir(parents=True, mode=0o700)
        environment = dict(os.environ)
        environment["UV_PROJECT_ENVIRONMENT"] = str(temporary / "worker-venv")
        rebuilt_wheel_directory = temporary / "wheel-rebuild"
        rebuilt_wheel_directory.mkdir()
        wheel_build = _run(
            [
                "uv",
                "build",
                "--wheel",
                str(ROOT / "runtime"),
                "--out-dir",
                str(rebuilt_wheel_directory),
            ],
            environment=environment,
        )
        _require_success(wheel_build, "reproducible Runtime wheel build")
        rebuilt_wheel = rebuilt_wheel_directory / "milai_runtime-0.1.0-py3-none-any.whl"
        frozen_wheel = PROJECT / "wheels/milai_runtime-0.1.0-py3-none-any.whl"
        _require_success(
            subprocess.CompletedProcess(
                args=["wheel-hash-compare"],
                returncode=int(
                    not rebuilt_wheel.is_file()
                    or remediation.sha256_file(rebuilt_wheel)
                    != remediation.sha256_file(frozen_wheel)
                ),
                stdout=b"",
                stderr=b"wheel digest mismatch",
            ),
            "reproducible Runtime wheel digest",
        )
        sync = _run(
            ["uv", "sync", "--project", str(PROJECT), "--frozen"],
            environment=environment,
        )
        _require_success(sync, "fresh benchmark worker install")
        python = temporary / "worker-venv/bin/python"
        probe = _run(
            [
                str(python),
                "-I",
                "-c",
                (
                    "import mpmath, tree_sitter, tree_sitter_java, "
                    "tree_sitter_javascript, yaml; print(mpmath.__version__)"
                ),
            ],
            environment=environment,
        )
        _require_success(probe, "fresh benchmark worker import probe")
        freeze = _run(["uv", "pip", "freeze", "--python", str(python)], environment=environment)
        _require_success(freeze, "fresh benchmark worker freeze")
        setup_captures = {
            "wheel_build": _write_capture(
                run_directory / "wheel-build.log", wheel_build.stdout + wheel_build.stderr
            ),
            "sync": _write_capture(run_directory / "sync.log", sync.stdout + sync.stderr),
            "import_probe": _write_capture(
                run_directory / "import-probe.log", probe.stdout + probe.stderr
            ),
            "freeze": _write_capture(run_directory / "freeze.txt", freeze.stdout),
            "rebuilt_wheel": _write_capture(
                run_directory / "milai_runtime-0.1.0-py3-none-any.whl",
                rebuilt_wheel.read_bytes(),
            ),
        }
        for name, receipt in setup_captures.items():
            if name == "rebuilt_wheel":
                receipt["capture_id"] = (
                    f"{run_directory.name}/milai_runtime-0.1.0-py3-none-any.whl"
                )
            else:
                receipt["capture_id"] = (
                    f"{run_directory.name}/{name.replace('_', '-')}"
                    f"{'.txt' if name == 'freeze' else '.log'}"
                )
        collection_result = _run(
            [
                str(python),
                "-m",
                "pytest",
                "-c",
                str(PYPROJECT),
                "--rootdir",
                str(ROOT),
                "--collect-only",
                "-q",
                "tests",
            ],
            environment=environment,
            timeout=300.0,
        )
        collection_raw = collection_result.stdout + collection_result.stderr
        collection_receipt = _write_capture(
            run_directory / "pytest-collect.log", collection_raw
        )
        collection_receipt["capture_id"] = (
            f"{run_directory.name}/pytest-collect.log"
        )
        _require_success(collection_result, "root pytest collection in fresh environment")
        pytest_result = _run(
            [
                str(python),
                "-m",
                "pytest",
                "-c",
                str(PYPROJECT),
                "--rootdir",
                str(ROOT),
                "-q",
                "tests",
            ],
            environment=environment,
            timeout=600.0,
        )
        pytest_raw = pytest_result.stdout + pytest_result.stderr
        pytest_receipt = _write_capture(run_directory / "pytest.log", pytest_raw)
        pytest_receipt["capture_id"] = f"{run_directory.name}/pytest.log"
        _require_success(pytest_result, "root pytest in fresh benchmark environment")
        match = PASS_PATTERN.search(pytest_raw.decode(errors="replace"))
        if match is None:
            raise WorkerClosureError("pytest pass count is not parseable")
        ruff_result = _run(
            [
                str(temporary / "worker-venv/bin/ruff"),
                "check",
                "--config",
                str(PYPROJECT),
                "scripts",
                "tests",
            ],
            environment=environment,
            timeout=300.0,
        )
        ruff_raw = ruff_result.stdout + ruff_result.stderr
        ruff_receipt = _write_capture(run_directory / "ruff.log", ruff_raw)
        ruff_receipt["capture_id"] = f"{run_directory.name}/ruff.log"
        _require_success(ruff_result, "root ruff in fresh benchmark environment")
        fresh = {
            "command": ["uv", "sync", "--project", "evals/dg10", "--frozen"],
            "exit_code": sync.returncode,
            "stdout_sha256": remediation.sha256_bytes(sync.stdout),
            "stderr_sha256": remediation.sha256_bytes(sync.stderr),
            "import_probe": "PASS",
            "import_probe_stdout_sha256": remediation.sha256_bytes(probe.stdout),
            "freeze_sha256": remediation.sha256_bytes(freeze.stdout),
            "freeze_line_count": len(freeze.stdout.splitlines()),
            "temporary_environment_removed_after_probe": True,
            "runtime_install_source": "CONTENT_ADDRESSED_LOCAL_WHEEL",
            "runtime_wheel_sha256": remediation.sha256_file(
                PROJECT / "wheels/milai_runtime-0.1.0-py3-none-any.whl"
            ),
            "runtime_wheel_rebuild_sha256": remediation.sha256_file(rebuilt_wheel),
            "runtime_wheel_reproducible": True,
            "captures": setup_captures,
            "status": "PASS_FRESH_INSTALL",
        }
        verification = {
            "collection": {
                "command": [
                    "FRESH_EVALS_DG10_PYTHON",
                    "-m",
                    "pytest",
                    "-c",
                    "evals/dg10/pyproject.toml",
                    "--rootdir",
                    ".",
                    "--collect-only",
                    "-q",
                    "tests",
                ],
                "exit_code": collection_result.returncode,
                "capture": collection_receipt,
            },
            "pytest": {
                "command": [
                    "FRESH_EVALS_DG10_PYTHON",
                    "-m",
                    "pytest",
                    "-c",
                    "evals/dg10/pyproject.toml",
                    "--rootdir",
                    ".",
                    "-q",
                    "tests",
                ],
                "exit_code": pytest_result.returncode,
                "passed": int(match.group("passed")),
                "failed": 0,
                "capture": pytest_receipt,
            },
            "ruff": {
                "command": [
                    "FRESH_EVALS_DG10_RUFF",
                    "check",
                    "--config",
                    "evals/dg10/pyproject.toml",
                    "scripts",
                    "tests",
                ],
                "exit_code": ruff_result.returncode,
                "capture": ruff_receipt,
            },
            "explicit_configuration": {
                "path": PYPROJECT.relative_to(ROOT).as_posix(),
                "sha256": remediation.sha256_file(PYPROJECT),
                "pytest_config_explicit": True,
                "ruff_config_explicit": True,
            },
            "status": "PASS_FRESH_ENVIRONMENT",
        }
        return fresh, verification


def _write_capture(path: Path, raw: bytes) -> dict[str, Any]:
    remediation.atomic_write_new(path, raw)
    return {
        "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        "sha256": remediation.sha256_file(path),
        "size": path.stat().st_size,
        "mode": "0600",
    }


def _runner_closure() -> dict[str, Any]:
    paths = [*ROOT.glob("scripts/*.py"), *ROOT.glob("tests/test_dg10_*.py")]
    paths.extend(ROOT.glob("tests/**/*.py"))
    paths.extend(ROOT.glob("docs/contracts/*"))
    paths.extend(ROOT.glob("integrations/**/*.py"))
    paths.extend(ROOT.glob("integrations/*/.python-version"))
    paths.extend(ROOT.glob("integrations/*/pyproject.toml"))
    paths.extend(ROOT.glob("integrations/*/uv.lock"))
    paths.extend(ROOT.glob("integrations/openworker-mcp/**/*.json"))
    paths.extend(ROOT.glob("integrations/openworker-mcp/**/*.sh"))
    paths.extend(ROOT.glob("integrations/openworker-mcp/**/Dockerfile"))
    paths.extend(ROOT.glob("evals/agent_efficiency/*.py"))
    paths.extend(ROOT.glob("evals/agent_efficiency/*.json"))
    paths.extend(ROOT.glob("evals/agent_efficiency/*.md"))
    paths.extend(ROOT.glob("evals/agent_integration/**/*.py"))
    paths.extend(ROOT.glob("runtime/src/**/*"))
    paths.extend(ROOT.glob("runtime/migrations/**/*"))
    paths.extend(ROOT.glob("runtime/tests/**/*.py"))
    paths.extend(ROOT.glob("runtime/docker/**/*"))
    paths.extend(
        [
            ROOT / "runtime/pyproject.toml",
            ROOT / "runtime/uv.lock",
            ROOT / "runtime/.python-version",
            ROOT / "runtime/README.md",
            ROOT / "runtime/alembic.ini",
            ROOT / "runtime/compose.yaml",
            ROOT / "evals/dg10/pyproject.toml",
            ROOT / "evals/dg10/uv.lock",
            ROOT / "evals/dg10/.python-version",
            ROOT / "evals/dg10/wheels/milai_runtime-0.1.0-py3-none-any.whl",
        ]
    )
    excluded_parts = {
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "dist",
        "wheelhouse",
    }
    safe = [
        path
        for path in paths
        if path.is_file()
        and not path.is_symlink()
        and not excluded_parts.intersection(path.parts)
        and not (
            "docs/contracts" in path.as_posix()
            and path.name.startswith(
                (
                    "DG-10-bfcl-case-manifest-",
                    "DG-10-bfcl-execution-identity-",
                )
            )
        )
    ]
    return remediation.canonical_inventory(safe)


def _bfcl_tree_closure(capture_root: Path) -> dict[str, Any]:
    status = _run(["git", "-C", str(BFCL_ROOT), "status", "--porcelain", "-z"])
    tracked = _run(["git", "-C", str(BFCL_ROOT), "ls-files", "-z"])
    _require_success(status, "BFCL dirty-state capture")
    _require_success(tracked, "BFCL tracked-file capture")
    if status.stdout:
        raise WorkerClosureError("BFCL upstream checkout is dirty")
    names = [name.decode() for name in tracked.stdout.split(b"\0") if name]
    _require(names == sorted(set(names)), "BFCL tracked file order or uniqueness drift")
    entries: list[dict[str, Any]] = []
    aggregate = hashlib.sha256()
    for relative in names:
        parsed = Path(relative)
        _require(
            not parsed.is_absolute() and ".." not in parsed.parts,
            "BFCL tracked path is unsafe",
        )
        lexical = (BFCL_ROOT / parsed).absolute()
        _require(
            lexical.is_relative_to(BFCL_ROOT.absolute())
            and not remediation.has_symlink_component(lexical)
            and lexical.is_file(),
            "BFCL tracked member is missing or unsafe",
        )
        target = lexical.resolve()
        digest = remediation.sha256_file(target)
        entries.append({"path": relative, "sha256": digest, "size": target.stat().st_size})
        aggregate.update(relative.encode())
        aggregate.update(b"\0")
        aggregate.update(digest.encode())
        aggregate.update(b"\0")
    run_directory = capture_root / f"candidate.4-{os.getpid()}-bfcl"
    run_directory.mkdir(parents=True, mode=0o700)
    status_capture = _write_capture(run_directory / "git-status-porcelain-z.bin", status.stdout)
    status_capture["capture_id"] = f"{run_directory.name}/git-status-porcelain-z.bin"
    tracked_capture = _write_capture(run_directory / "git-ls-files-z.bin", tracked.stdout)
    tracked_capture["capture_id"] = f"{run_directory.name}/git-ls-files-z.bin"
    return {
        "git_head": _git_head(BFCL_ROOT),
        "dirty": False,
        "tracked_file_count": len(entries),
        "canonical_entries_sha256": aggregate.hexdigest(),
        "entries": entries,
        "captures": {"git_status": status_capture, "git_ls_files": tracked_capture},
    }


def build_report(*, run_dynamic: bool, capture_root: Path) -> dict[str, Any]:
    capture_root = capture_root.absolute()
    allowed_capture_root = (ROOT.parent / "evidence").absolute()
    _require(
        capture_root.is_relative_to(allowed_capture_root)
        and not remediation.has_symlink_component(capture_root),
        "worker capture root is unsafe",
    )
    environment = _environment_identity()
    report: dict[str, Any] = {
        "schema": "milai.dg10.benchmark-worker-closure.v1",
        "candidate_id": remediation.CANDIDATE,
        "date": remediation.DATE,
        "status": "R2_AUTHOR_CANDIDATE_REVIEW_REQUIRED",
        "stage_id": "DG10-R2",
        "stage_state": "AUTHOR_CANDIDATE",
        "independent_acceptance": False,
        "runtime_venv_reused": False,
        "environment": environment,
        "bfcl": {"root_class": "WORKSPACE_UPSTREAM_CHECKOUT"},
        "runner_and_helper_closure": _runner_closure(),
        "historical_worker_freeze": {
            "sha256": "e21b21a1df79293faa2dcf1bca352a82d44f5910767f22b5e34d0b847661ec39",
            "policy": "IMMUTABLE_CANDIDATE_2_ONLY_NOT_UPDATED",
            "candidate_4_uses_content_addressed_runtime_wheel": True,
        },
        "fresh_install": "NOT_RUN",
        "verification": "NOT_RUN",
    }
    report["bfcl"].update(_bfcl_tree_closure(capture_root))
    if run_dynamic:
        fresh, verification = _fresh_install_probe(capture_root)
        report["fresh_install"] = fresh
        report["verification"] = verification
        report["status"] = "R2_AUTHOR_CANDIDATE_DYNAMIC_PASS_REVIEW_REQUIRED"
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build DG-10 benchmark worker closure")
    parser.add_argument("--run-dynamic", action="store_true")
    parser.add_argument("--capture-root", type=Path, default=DEFAULT_CAPTURE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_report(run_dynamic=args.run_dynamic, capture_root=args.capture_root)
    output = args.output.absolute()
    _require(
        output.is_relative_to(ROOT.absolute())
        and not remediation.has_symlink_component(output),
        "worker closure output is unsafe",
    )
    remediation.atomic_write_new(output, remediation.encoded_json(report))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
