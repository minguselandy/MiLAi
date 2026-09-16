from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from milai.config import SettingsError

DEFAULT_PACKAGE_ROOTS = (
    "runtime",
    "integrations/python-client",
    "integrations/mcp",
    "integrations/langgraph",
    "integrations/autogen",
    "integrations/hooks",
    "integrations/openworker-mcp",
)


@dataclass(frozen=True, slots=True)
class PackageInstallCase:
    name: str
    root: str
    wheel: Path
    import_name: str


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _site_packages(package_root: Path) -> Path:
    matches = sorted((package_root / ".venv/lib").glob("python*/site-packages"))
    if len(matches) != 1:
        raise SettingsError(f"expected one site-packages directory for {package_root}")
    return matches[0]


def _metadata_value(package_metadata: metadata.PackageMetadata, key: str) -> str:
    try:
        return package_metadata[key] or ""
    except KeyError:
        return ""


def _license_fact(package_name: str, package_metadata: metadata.PackageMetadata | None) -> str:
    if package_metadata is None:
        return "NOT_AVAILABLE_ON_BUILD_PLATFORM"
    expression = _metadata_value(package_metadata, "License-Expression").strip()
    if expression:
        return expression
    classifiers = sorted(
        classifier.removeprefix("License :: ")
        for classifier in package_metadata.get_all("Classifier", [])
        if classifier.startswith("License :: ")
    )
    if classifiers:
        return " | ".join(classifiers)
    license_value = _metadata_value(package_metadata, "License").strip()
    if license_value and "\n" not in license_value and len(license_value) <= 160:
        return license_value
    if package_name.startswith("milai-"):
        return "UNDECLARED"
    if license_value:
        return "SEE_INSTALLED_DISTRIBUTION_METADATA"
    return "NOT_DECLARED_IN_INSTALLED_METADATA"


def _project(package_root: Path) -> dict[str, Any]:
    return tomllib.loads((package_root / "pyproject.toml").read_text(encoding="utf-8"))


def _package_record(workspace_root: Path, relative_root: str) -> dict[str, Any]:
    package_root = workspace_root / relative_root
    project = _project(package_root)["project"]
    lock_path = package_root / "uv.lock"
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    installed = {
        _canonical_name(distribution.metadata["Name"]): distribution.metadata
        for distribution in metadata.distributions(path=[str(_site_packages(package_root))])
        if distribution.metadata["Name"]
    }
    dependencies = []
    for locked in sorted(lock["package"], key=lambda item: (item["name"], item["version"])):
        name = _canonical_name(locked["name"])
        package_metadata = installed.get(name)
        dependencies.append(
            {
                "name": name,
                "version": locked["version"],
                "installed_on_build_platform": package_metadata is not None,
                "license_metadata": _license_fact(name, package_metadata),
            }
        )
    artifacts = [
        {
            "path": artifact.relative_to(workspace_root).as_posix(),
            "size": artifact.stat().st_size,
            "sha256": _digest(artifact),
        }
        for artifact in sorted((package_root / "dist").glob("*"))
        if artifact.is_file() and artifact.name != ".gitignore"
    ]
    if len(artifacts) != 2:
        raise SettingsError(f"expected one wheel and one sdist for {relative_root}")
    return {
        "name": project["name"],
        "version": project["version"],
        "root": relative_root,
        "requires_python": project["requires-python"],
        "project_license": "UNDECLARED",
        "lock": {
            "path": lock_path.relative_to(workspace_root).as_posix(),
            "sha256": _digest(lock_path),
        },
        "artifacts": artifacts,
        "locked_dependency_license_inventory": dependencies,
    }


def build_package_release_manifest(
    workspace_root: Path,
    output: Path,
    *,
    package_roots: tuple[str, ...] = DEFAULT_PACKAGE_ROOTS,
    snapshot_date: str | None = None,
) -> dict[str, Any]:
    """Build one release manifest for the canonical local product packages."""
    root = workspace_root.resolve()
    manifest = {
        "format": "milai-local-package-release-manifest-v1",
        "snapshot_date": snapshot_date or datetime.now(UTC).date().isoformat(),
        "distribution_policy": "LOCAL_ONLY_PROJECT_LICENSE_UNDECLARED",
        "license_inventory_method": (
            "Locked names/versions joined to installed wheel metadata on this build host; "
            "platform-conditional packages not installed here are marked unavailable."
        ),
        "packages": [_package_record(root, relative) for relative in package_roots],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def package_install_cases(
    workspace_root: Path,
    *,
    package_roots: tuple[str, ...] = DEFAULT_PACKAGE_ROOTS,
    wheel_root: Path | None = None,
) -> tuple[PackageInstallCase, ...]:
    cases: list[PackageInstallCase] = []
    for relative_root in package_roots:
        package_root = workspace_root / relative_root
        project_data = _project(package_root)
        wheel_packages = project_data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
        distribution_name = project_data["project"]["name"].replace("-", "_")
        artifact_root = wheel_root if wheel_root is not None else package_root / "dist"
        wheels = sorted(artifact_root.glob(f"{distribution_name}-*.whl"))
        if len(wheel_packages) != 1 or len(wheels) != 1:
            raise SettingsError(f"package artifacts are ambiguous for {relative_root}")
        cases.append(
            PackageInstallCase(
                name=project_data["project"]["name"],
                root=relative_root,
                wheel=wheels[0],
                import_name=Path(wheel_packages[0]).name,
            )
        )
    return tuple(cases)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- package tool paths are explicit arguments
        command, check=False, capture_output=True, text=True
    )


def _install_case(
    uv: str,
    workspace: Path,
    root: Path,
    case: PackageInstallCase,
    client_wheel: Path,
) -> dict[str, Any]:
    started = time.monotonic()
    marker = f"{case.import_name}/py.typed"
    with ZipFile(case.wheel) as archive:
        has_type_marker = marker in archive.namelist()
    if not has_type_marker:
        return {
            "name": case.name,
            "status": "FAIL",
            "stage": "wheel_metadata",
            "diagnostic_tail": f"missing PEP 561 marker {marker}",
        }
    venv = workspace / case.name
    create = _run([uv, "venv", "--python", "3.11", str(venv)])
    if create.returncode != 0:
        return {
            "name": case.name,
            "status": "FAIL",
            "stage": "venv",
            "diagnostic_tail": create.stderr[-2_000:],
        }
    python = venv / "bin/python"
    wheels = [str(case.wheel)]
    if case.name not in {"milai-runtime", "milai-client"}:
        wheels.append(str(client_wheel))
    install = _run([uv, "pip", "install", "--python", str(python), *wheels])
    if install.returncode != 0:
        return {
            "name": case.name,
            "status": "FAIL",
            "stage": "install",
            "diagnostic_tail": install.stderr[-2_000:],
        }
    imported = _run([str(python), "-I", "-c", f"import {case.import_name}"])
    return {
        "name": case.name,
        "wheel": case.wheel.relative_to(root).as_posix(),
        "wheel_sha256": _digest(case.wheel),
        "status": "PASS" if imported.returncode == 0 else "FAIL",
        "stage": "import",
        "import": case.import_name,
        "pep561_type_marker": has_type_marker,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "diagnostic_tail": "" if imported.returncode == 0 else imported.stderr[-2_000:],
    }


def _write_json_atomic(output: Path, value: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def run_package_clean_install_gate(
    workspace_root: Path,
    output: Path,
    *,
    package_roots: tuple[str, ...] = DEFAULT_PACKAGE_ROOTS,
    wheel_root: Path | None = None,
) -> dict[str, Any]:
    """Install every canonical wheel in an isolated environment and import it."""
    root = workspace_root.resolve()
    uv = shutil.which("uv")
    if uv is None:
        raise SettingsError("uv is required")
    cases = package_install_cases(
        root,
        package_roots=package_roots,
        wheel_root=wheel_root.resolve() if wheel_root is not None else None,
    )
    client_wheel = next(case.wheel for case in cases if case.name == "milai-client")
    with tempfile.TemporaryDirectory(prefix="milai-package-gate-") as temporary:
        workspace = Path(temporary)
        results = [_install_case(uv, workspace, root, case, client_wheel) for case in cases]
    report = {
        "schema": "milai.package-clean-install.v1",
        "isolation": "fresh temporary virtual environments; import uses Python -I",
        "status": "PASS" if all(result["status"] == "PASS" for result in results) else "FAIL",
        "results": results,
    }
    _write_json_atomic(output.resolve(), report)
    return report
