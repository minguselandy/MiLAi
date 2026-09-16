#!/usr/bin/env python3
"""Run fresh implementation-only quality gates for DG-25 S4A readiness."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_SCRIPT_PATH = Path(__file__)
ROOT = _SCRIPT_PATH.resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (str(ROOT), str(RUNTIME_SRC)):
    if value not in sys.path:
        sys.path.insert(0, value)

from evals.dg25.s4a_readiness import build_s4a_source_manifest, file_identity

SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
QUALITY_ROOT = Path("var/dg25/quality")
ARCHITECTURE_MANIFEST_SHA256 = (
    "ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e"
)
PROTECTED_DIFF_DIGESTS = {
    "scripts/dg13u_u1_review.py": (
        "5469b6ac14898ca55d92489f47ec4868893b40060912f06ed24d6ae5360ee476"
    ),
    "tests/test_dg13u_u1_review.py": (
        "588b98756db645a5ee93090245e6e510945145bfd86ec235074b44717929e4cd"
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    return run_quality(run_id=str(args.run_id), root=ROOT)


def run_quality(*, run_id: str, root: Path) -> int:
    root = root.resolve()
    output = _validated_output(root, run_id)
    if output.is_symlink() or output.exists():
        raise FileExistsError("DG25_S4A_QUALITY_EXISTING_OUTPUT_REJECTED")
    _validate_protected_diffs(root)
    before = build_s4a_source_manifest(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=output.parent))
    gates: list[dict[str, Any]] = []
    try:
        for gate_id, argv in _gate_vectors(root):
            result = subprocess.run(
                argv,
                cwd=root,
                check=False,
                capture_output=True,
                env=_quality_environment(root),
            )
            stdout_path = temporary / f"{gate_id}.stdout.txt"
            stderr_path = temporary / f"{gate_id}.stderr.txt"
            stdout_path.write_bytes(result.stdout)
            stderr_path.write_bytes(result.stderr)
            gate = {
                "gate_id": gate_id,
                "argv": argv,
                "cwd": str(root),
                "exit_code": result.returncode,
                "stdout": _temporary_identity(root, stdout_path, output),
                "stderr": _temporary_identity(root, stderr_path, output),
            }
            gates.append(gate)
            if result.returncode != 0:
                raise RuntimeError(f"DG25_S4A_QUALITY_GATE_FAILED:{gate_id}")

        _validate_protected_diffs(root)
        after = build_s4a_source_manifest(root)
        if before["files"] != after["files"]:
            raise ValueError("DG25_S4A_SOURCE_CHANGED_DURING_QUALITY_GATES")
        receipt: dict[str, Any] = {
            "schema": "milai.dg25.s4a-quality-receipt.v0.1",
            "run_id": run_id,
            "status": "PASS_DG25_S4A_QUALITY",
            "gates": gates,
            "source_files": before["files"],
            "source_set_digest": before["source_set_digest"],
            "source_files_current_after_gates": True,
            "source_boundary_scan": before["source_scan"],
            "protected_diff_digests": dict(PROTECTED_DIFF_DIGESTS),
            "architecture_manifest_sha256": ARCHITECTURE_MANIFEST_SHA256,
            "labels_loaded": False,
            "registry_content_loaded": False,
            "scoring_executed": False,
            "reader_model_provider_controller_calls": 0,
            "formal_holdout_consumed": False,
            "automatic_retries": 0,
        }
        _write_json(temporary / "receipt.json", receipt)
        temporary.rename(output)
    except Exception:
        _write_json(
            temporary / "failed-quality-gates.json",
            {
                "schema": "milai.dg25.s4a-quality-failure.v0.1",
                "run_id": run_id,
                "gates": gates,
                "automatic_retries": 0,
            },
        )
        raise

    print(
        json.dumps(
            {
                "status": receipt["status"],
                "output": output.relative_to(root).as_posix(),
                "gate_count": len(gates),
                "source_set_digest": receipt["source_set_digest"],
            },
            sort_keys=True,
        )
    )
    return 0


def _gate_vectors(root: Path) -> list[tuple[str, list[str]]]:
    python = str(root / "runtime/.venv/bin/python")
    pytest = str(root / "runtime/.venv/bin/pytest")
    mypy = str(root / "runtime/.venv/bin/mypy")
    ruff = str(root / "runtime/.venv/bin/ruff")
    expanded_tests = [
        "runtime/tests/unit",
        "runtime/tests/contract",
        "tests/test_dg25_s0_baseline_freeze.py",
        "tests/test_dg25_s1_contracts.py",
        "tests/test_dg25_review_gate.py",
        "tests/test_dg25_s2_plan_execution.py",
        "tests/test_dg25_s3_readiness.py",
        "tests/test_dg25_s4a.py",
    ]
    typed_sources = [
        "runtime/src/milai",
        "evals/dg25/arm_sealing.py",
        "evals/dg25/effect_scorer.py",
        "evals/dg25/routing_ablation.py",
        "evals/dg25/s4a_generator.py",
        "evals/dg25/s4a_readiness.py",
        "scripts/run_dg25_s4a.py",
        "scripts/run_dg25_s4a_quality.py",
        "scripts/run_dg25_s4a_readiness.py",
    ]
    lint_sources = [*typed_sources, "tests/test_dg25_s4a.py"]
    return [
        ("targeted-pytest", [pytest, "-q", "tests/test_dg25_s4a.py"]),
        ("expanded-pytest", [pytest, "-q", *expanded_tests]),
        ("strict-mypy", [mypy, "--strict", *typed_sources]),
        ("ruff", [ruff, "check", *lint_sources]),
        (
            "compileall",
            [
                python,
                "-m",
                "compileall",
                "-q",
                "runtime/src/milai",
                "evals/dg25",
                "scripts/run_dg25_s4a.py",
                "scripts/run_dg25_s4a_quality.py",
                "scripts/run_dg25_s4a_readiness.py",
            ],
        ),
        (
            "architecture-validate",
            [python, "architecture/v1.0/scripts/validate_bundle.py"],
        ),
        (
            "architecture-release-lock",
            [
                python,
                "architecture/v1.0/scripts/verify_lock.py",
                "--scope",
                "bundle",
                "--mode",
                "release",
                "--expected-manifest-sha256",
                ARCHITECTURE_MANIFEST_SHA256,
            ],
        ),
    ]


def _validate_protected_diffs(root: Path) -> None:
    for path, expected in PROTECTED_DIFF_DIGESTS.items():
        result = subprocess.run(
            ["git", "diff", "--", path],
            cwd=root,
            check=True,
            capture_output=True,
        )
        observed = hashlib.sha256(result.stdout).hexdigest()
        if observed != expected:
            raise ValueError(f"DG25_S4A_PROTECTED_USER_DIFF_DRIFT:{path}")


def _quality_environment(root: Path) -> dict[str, str]:
    environment = dict(os.environ)
    prefix = os.pathsep.join((str(root), str(root / "runtime/src")))
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        prefix if not existing else prefix + os.pathsep + existing
    )
    return environment


def _validated_output(root: Path, run_id: str) -> Path:
    if run_id in {".", ".."} or SAFE_COMPONENT.fullmatch(run_id) is None:
        raise ValueError("DG25_S4A_QUALITY_RUN_ID_NOT_SAFE")
    parent = root / QUALITY_ROOT
    if parent.resolve(strict=False) != parent.absolute():
        raise ValueError("DG25_S4A_QUALITY_ROOT_SYMLINK_OR_DRIFT")
    output = parent / run_id
    if output.absolute().parent != parent.absolute():
        raise ValueError("DG25_S4A_QUALITY_OUTPUT_NOT_DIRECT_CHILD")
    return output


def _temporary_identity(root: Path, path: Path, final_output: Path) -> dict[str, Any]:
    identity = file_identity(root, path)
    identity["path"] = (final_output / path.name).relative_to(root).as_posix()
    return identity


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
