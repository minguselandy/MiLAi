#!/usr/bin/env python3
"""Execute, terminalize, and validate the MF-01 passive first-loss audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for source_root in (ROOT, RUNTIME_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from milai.domain.requirement_state import canonical_sha256

from evals.mf01.first_loss import (
    behavior_equivalence_smoke,
    build_passive_traces,
    load_s0_s1_lock,
    score_first_loss,
)

OLD_LOCK = ROOT / "var/mf01/run-lock.json"
TRACE = ROOT / "var/mf01/trace.jsonl"
RESULTS = ROOT / "var/mf01/results.json"
TERMINAL = ROOT / "var/mf01/terminal.json"
RUN_ID = "mf01-s2-s4-passive-first-loss-20260830-001"

IMPLEMENTATION_PATHS = (
    "MiLAi_Memory_Lifecycle_总_GOALS.md",
    "MiLAi_MF-01_Formation_First-Loss_Audit_GOALS.md",
    "runtime/src/milai/observability/formation_audit.py",
    "evals/mf01/first_loss.py",
    "scripts/run_mf01.py",
    "runtime/tests/unit/test_formation_audit.py",
    "tests/test_mf01_first_loss.py",
    "tests/test_mf01_s0_s1_design.py",
    "var/mf01/run-lock.json",
)


class MF01RunnerError(RuntimeError):
    """The passive audit cannot be sealed under the authorized contract."""


def effect(
    trace_path: Path = TRACE,
    results_path: Path = RESULTS,
) -> dict[str, Any]:
    """Pass the behavior gate, write 125 traces, then seal the score."""

    if trace_path.exists() or results_path.exists():
        raise MF01RunnerError("MF01_EFFECT_ARTIFACT_ALREADY_EXISTS")
    old_lock = load_s0_s1_lock(ROOT)
    seal, traces = build_passive_traces(ROOT)
    behavior = behavior_equivalence_smoke(ROOT, seal)
    if behavior.get("exact_match") is not True:
        raise MF01RunnerError("MF01_BEHAVIOR_EQUIVALENCE_FAILED")
    score = score_first_loss(seal, traces, behavior)
    rows = [item.model_dump(mode="json") for item in traces]
    _write_jsonl_exclusive(trace_path, rows)
    trace_identity = _identity(trace_path)
    output: dict[str, Any] = {
        "schema": "milai.mf01.s2-s3.results.v0.1",
        "goal_id": "MF-01",
        "run_id": RUN_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "review_status": "INTERNAL_PROVISIONAL",
        "execution_authority": "MILA-ML-MASTER@1.2",
        "historical_s0_s1_lock": {
            "lock_digest": old_lock["lock_digest"],
            **_identity(OLD_LOCK),
            "scope_at_creation": "S0_S1_ONLY",
            "superseding_authorization": "MILA-ML-MASTER@1.2_S2_S4",
        },
        "label_seal": {
            "seal_digest": seal.seal_digest,
            "case_count": seal.case_count,
            "label_count": seal.label_count,
            "counts_by_kind": seal.counts_by_kind,
            "formal_holdout_used": seal.formal_holdout_used,
        },
        "trace": {
            **trace_identity,
            "line_count": len(rows),
            "content_digest": canonical_sha256(rows),
            "analysis_unit": "SEALED_SOURCE_GROUNDED_OBLIGATION",
            "full_candidate_lifecycle_copied": False,
        },
        "behavior_equivalence": behavior,
        "score": score,
        "implementation_identities": [
            _identity(ROOT / path) for path in IMPLEMENTATION_PATHS
        ],
        "cost": {
            "cpu_workers": 1,
            "provider_calls": 0,
            "embedding_calls": 0,
            "reader_calls": 0,
            "canonical_writes": 0,
            "database_writes": 0,
            "trace_rows": len(rows),
        },
        "safety": {
            "product_behavior_changed": False,
            "introduced_provider_calls": 0,
            "canonical_mutations_caused_by_audit": 0,
            "formal_holdout_used": False,
            "public_mcp_schema_changed": False,
            "postgresql_schema_changed": False,
            "architecture_v1_changed": False,
        },
    }
    output["results_digest"] = canonical_sha256(output)
    _write_json_exclusive(results_path, output)
    return output


def terminalize(
    results_path: Path = RESULTS,
    terminal_path: Path = TERMINAL,
) -> dict[str, Any]:
    """Run focused gates and seal the observational terminal."""

    if terminal_path.exists():
        raise MF01RunnerError("MF01_TERMINAL_ALREADY_EXISTS")
    results = _verified_digest_object(results_path, "results_digest")
    _verify_result_identities(results)
    trace = _mapping(results.get("trace"), "trace identity")
    expected_trace_identity = {
        key: trace[key] for key in ("path", "size", "sha256")
    }
    if _identity(TRACE) != expected_trace_identity:
        raise MF01RunnerError("MF01_TRACE_FILE_IDENTITY_DRIFT")
    quality = {
        "targeted_tests": _run_quality(
            [
                str(ROOT / "runtime/.venv/bin/pytest"),
                "-q",
                "runtime/tests/unit/test_formation_audit.py",
                "tests/test_mf01_first_loss.py",
            ]
        ),
        "lint": _run_quality(
            [
                str(ROOT / "runtime/.venv/bin/ruff"),
                "check",
                "runtime/src/milai/observability/formation_audit.py",
                "evals/mf01/first_loss.py",
                "scripts/run_mf01.py",
                "runtime/tests/unit/test_formation_audit.py",
                "tests/test_mf01_first_loss.py",
            ]
        ),
        "typecheck": _run_quality(
            [
                str(ROOT / "runtime/.venv/bin/mypy"),
                "--config-file",
                "runtime/pyproject.toml",
                "runtime/src/milai/observability/formation_audit.py",
                "evals/mf01/first_loss.py",
                "scripts/run_mf01.py",
            ]
        ),
    }
    quality_passed = all(item["returncode"] == 0 for item in quality.values())
    score = _mapping(results.get("score"), "score")
    score_passed = score.get("status") == "PASS_FORMATION_FIRST_LOSS_LOCALIZED"
    behavior = _mapping(results.get("behavior_equivalence"), "behavior")
    if not quality_passed:
        status = "FAIL_AUDIT_CHANGED_BEHAVIOR"
    elif not score_passed:
        status = str(score.get("status"))
    elif behavior.get("exact_match") is not True:
        status = "FAIL_AUDIT_CHANGED_BEHAVIOR"
    else:
        status = "PASS_FORMATION_FIRST_LOSS_LOCALIZED"
    routing = _mapping(score.get("successor_routing"), "routing")
    terminal: dict[str, Any] = {
        "schema": "milai.mf01.s4.terminal.v0.1",
        "goal_id": "MF-01",
        "run_id": results["run_id"],
        "created_at": datetime.now(UTC).isoformat(),
        "review_status": "INTERNAL_PROVISIONAL",
        "status": status,
        "claims": {
            "MF01_H1_FIRST_LOSS_LOCALIZED": (
                "SUPPORTED"
                if status == "PASS_FORMATION_FIRST_LOSS_LOCALIZED"
                else "NOT_SUPPORTED"
            ),
            "MF01_H2_AUDIT_BEHAVIOR_NEUTRAL": (
                "SUPPORTED" if behavior.get("exact_match") is True else "NOT_SUPPORTED"
            ),
        },
        "quality_gates": quality,
        "results_digest": results["results_digest"],
        "trace_sha256": _sha256_file(TRACE),
        "successor_routes": {
            **dict(routing),
            "execution_status": "RECORDED_NOT_STARTED_NOT_AUTHORIZED",
            "authorization": "MILA-ML-MASTER@1.2_EXCLUDES_MF02_MF03_MF04",
        },
        "safety": results["safety"],
    }
    terminal["terminal_digest"] = canonical_sha256(terminal)
    _write_json_exclusive(terminal_path, terminal)
    return terminal


def validate(
    results_path: Path = RESULTS,
    terminal_path: Path = TERMINAL,
) -> dict[str, Any]:
    results = _verified_digest_object(results_path, "results_digest")
    terminal = _verified_digest_object(terminal_path, "terminal_digest")
    trace = _mapping(results.get("trace"), "trace")
    if trace.get("sha256") != _sha256_file(TRACE):
        raise MF01RunnerError("MF01_VALIDATE_TRACE_DIGEST_MISMATCH")
    if terminal.get("results_digest") != results.get("results_digest"):
        raise MF01RunnerError("MF01_VALIDATE_TERMINAL_RESULTS_MISMATCH")
    if terminal.get("trace_sha256") != trace.get("sha256"):
        raise MF01RunnerError("MF01_VALIDATE_TERMINAL_TRACE_MISMATCH")
    return {
        "valid": True,
        "status": terminal["status"],
        "MF01_H1": terminal["claims"]["MF01_H1_FIRST_LOSS_LOCALIZED"],
        "MF01_H2": terminal["claims"]["MF01_H2_AUDIT_BEHAVIOR_NEUTRAL"],
        "trace_lines": trace["line_count"],
        "results_digest": results["results_digest"],
        "terminal_digest": terminal["terminal_digest"],
    }


def _verify_result_identities(results: Mapping[str, Any]) -> None:
    for raw in _sequence(results.get("implementation_identities"), "identities"):
        expected = _mapping(raw, "implementation identity")
        if _identity(ROOT / str(expected["path"])) != expected:
            raise MF01RunnerError(f"MF01_IMPLEMENTATION_DRIFT:{expected['path']}")


def _run_quality(command: list[str]) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(RUNTIME_SRC), str(ROOT), environment.get("PYTHONPATH", "")]
    )
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "stdout_tail": completed.stdout[-4_000:],
        "stderr_tail": completed.stderr[-4_000:],
    }


def _identity(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise MF01RunnerError(f"MF01_PATH_MISSING:{path}")
    return {
        "path": str(path.resolve().relative_to(ROOT)),
        "size": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verified_digest_object(path: Path, digest_key: str) -> dict[str, Any]:
    value = _object(path)
    material = dict(value)
    observed = material.pop(digest_key, None)
    if observed != canonical_sha256(material):
        raise MF01RunnerError(f"MF01_DIGEST_MISMATCH:{path}")
    return value


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MF01RunnerError(f"MF01_JSON_OBJECT_REQUIRED:{path}")
    return value


def _mapping(value: object, source: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MF01RunnerError(f"MF01_MAPPING_REQUIRED:{source}")
    return value


def _sequence(value: object, source: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MF01RunnerError(f"MF01_SEQUENCE_REQUIRED:{source}")
    return value


def _write_jsonl_exclusive(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )
            handle.write("\n")


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("effect", "terminal", "all", "validate"))
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "effect":
        output = effect()
    elif args.command == "terminal":
        output = terminalize()
    elif args.command == "validate":
        output = validate()
    else:
        effect()
        output = terminalize()
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
