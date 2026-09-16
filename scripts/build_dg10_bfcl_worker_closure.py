from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_remediation as remediation

R2_CLOSURE = ROOT / (
    "docs/reports/DG-10-benchmark-worker-closure-candidate.4.25-2026-08-22.json"
)
ENVIRONMENT_MATERIALS = (
    ROOT / "evals/dg10/pyproject.toml",
    ROOT / "evals/dg10/uv.lock",
    ROOT / "evals/dg10/wheels/milai_runtime-0.1.0-py3-none-any.whl",
)
ADAPTER_MATERIALS = (
    ROOT / "scripts/dg10_bfcl_loop.py",
    ROOT / "scripts/dg10_bfcl_scoring.py",
    ROOT / "scripts/run_dg10_bfcl_multiturn_scoring_worker.py",
    ROOT / "scripts/run_dg10_bfcl_multiturn_scoring_worker_v4.py",
)
DEFAULT_OUTPUT = ROOT / (
    "docs/reports/DG-10-bfcl-worker-closure-candidate.4.13-2026-08-22.json"
)


def _reference(path: Path) -> dict[str, Any]:
    lexical = path.absolute()
    if (
        not lexical.is_relative_to(ROOT.absolute())
        or remediation.has_symlink_component(lexical)
        or not lexical.is_file()
    ):
        raise remediation.RemediationError(f"unsafe BFCL worker material: {path}")
    return {
        "path": lexical.relative_to(ROOT.absolute()).as_posix(),
        "sha256": remediation.sha256_file(lexical),
        "size": lexical.stat().st_size,
    }


def _identity(paths: tuple[Path, ...]) -> dict[str, Any]:
    materials = [_reference(path) for path in paths]
    return {
        "identity_sha256": remediation.sha256_bytes(
            remediation.encoded_json({"materials": materials})
        ),
        "materials": materials,
    }


def build_closure() -> dict[str, Any]:
    _reference(R2_CLOSURE)
    r2 = json.loads(R2_CLOSURE.read_text(encoding="utf-8"))
    environment = r2.get("environment") if isinstance(r2, dict) else None
    verification = r2.get("verification") if isinstance(r2, dict) else None
    bfcl = r2.get("bfcl") if isinstance(r2, dict) else None
    if not isinstance(environment, dict) or not isinstance(verification, dict) or not isinstance(bfcl, dict):
        raise remediation.RemediationError("coherent final R2 closure shape drift")
    expected_by_path = {item.relative_to(ROOT).as_posix(): _reference(item) for item in ENVIRONMENT_MATERIALS}
    if (
        environment.get("pyproject", {}).get("sha256")
        != expected_by_path["evals/dg10/pyproject.toml"]["sha256"]
        or environment.get("lock", {}).get("sha256")
        != expected_by_path["evals/dg10/uv.lock"]["sha256"]
        or r2.get("fresh_install", {}).get("runtime_wheel_sha256")
        != expected_by_path["evals/dg10/wheels/milai_runtime-0.1.0-py3-none-any.whl"]["sha256"]
        or not isinstance(verification.get("pytest", {}).get("passed"), int)
        or isinstance(verification.get("pytest", {}).get("passed"), bool)
        or verification.get("pytest", {}).get("passed", 0) <= 0
        or verification.get("pytest", {}).get("exit_code") != 0
        or verification.get("ruff", {}).get("exit_code") != 0
        or verification.get("explicit_configuration", {}).get("sha256")
        != expected_by_path["evals/dg10/pyproject.toml"]["sha256"]
        or verification.get("explicit_configuration", {}).get("pytest_config_explicit") is not True
        or verification.get("explicit_configuration", {}).get("ruff_config_explicit") is not True
    ):
        raise remediation.RemediationError("R2 config/lock/wheel/capture identity is incoherent")
    if (
        bfcl.get("git_head") != "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
        or bfcl.get("tracked_file_count") != 192
        or bfcl.get("canonical_entries_sha256")
        != "1e8be069f93b5b910d37f90db6208cca389b5e9d0bcdd03d56ae7037f18b5fb5"
    ):
        raise remediation.RemediationError("R2 BFCL upstream closure drift")
    return {
        "schema": "milai.dg10.bfcl-worker-closure.v1",
        "candidate_id": remediation.CANDIDATE,
        "frozen_at": datetime.now(UTC).isoformat(),
        "coherent_r2_closure": _reference(R2_CLOSURE),
        "environment": _identity(ENVIRONMENT_MATERIALS),
        "adapter": _identity(ADAPTER_MATERIALS),
        "verification": {
            "pytest_passed": verification["pytest"]["passed"],
            "pytest_command": verification["pytest"]["command"],
            "pytest_capture": verification["pytest"]["capture"],
            "ruff_command": verification["ruff"]["command"],
            "ruff_capture": verification["ruff"]["capture"],
            "explicit_configuration": verification["explicit_configuration"],
            "fresh_install_status": r2["fresh_install"]["status"],
            "runtime_wheel_reproducible": r2["fresh_install"]["runtime_wheel_reproducible"],
        },
        "upstream_bfcl": {
            "git_head": bfcl["git_head"],
            "tracked_file_count": bfcl["tracked_file_count"],
            "canonical_entries_sha256": bfcl["canonical_entries_sha256"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze coherent candidate.4 BFCL worker closure")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    value = build_closure()
    output = args.output.absolute()
    remediation.atomic_write_new(output, remediation.encoded_json(value))
    print(json.dumps({"output": str(output), "frozen_at": value["frozen_at"]}, sort_keys=True))


if __name__ == "__main__":
    main()
