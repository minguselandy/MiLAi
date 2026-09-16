#!/usr/bin/env python3
"""Freeze, execute once, terminalize, and validate the DG-27 V02 experiment."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for source_root in (ROOT, RUNTIME_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from milai.adapters.grounded_interpretation import (
    DG27_RESPONSE_SCHEMA,
    DG27_SYSTEM_PROMPT,
    LoopbackGroundedInterpretationAdapter,
)
from milai.domain.requirement_state import canonical_sha256

from evals.dg27.decision_boundary import (
    execute_effect,
    frozen_candidate_manifest,
    historical_baseline_accepted_sources,
    historical_wrong_complete_occurrences,
    load_run_lock,
)

OLD_LOCK = ROOT / "var/dg27/run-lock.json"
V02_DIR = ROOT / "var/dg27/v02"
RUN_LOCK = V02_DIR / "run-lock.json"
RESULTS = V02_DIR / "results.json"
TERMINAL = V02_DIR / "terminal.json"
DG26_LOCK = ROOT / "var/dg26/run-lock.json"
DG26_RESULTS = ROOT / "var/dg26/results.json"
DG26_TERMINAL = ROOT / "var/dg26/terminal.json"
DG25_OUTPUTS = (
    ROOT
    / "var/dg25/s3a/dg25-s3a-e1-label-free-20260830-001/"
    "e1-label-free-arm-outputs.json"
)
GOLD_REGISTRY = (
    ROOT
    / "var/dg24/s0/dg24-s0-freeze-20260829-008/scorer-only/"
    "gold-equivalence-registry-v0.1.json"
)
MODEL_HOST = "127.0.0.1"
MODEL_PORT = 7860
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
RUN_ID = "dg27-v02-decision-boundary-20260830-001"

BOUND_PATHS = (
    "runtime/src/milai/domain/decision_boundary.py",
    "runtime/src/milai/application/decision_boundary.py",
    "runtime/src/milai/adapters/grounded_interpretation.py",
    "evals/dg27/decision_boundary.py",
    "scripts/run_dg27.py",
    "runtime/tests/unit/test_dg27_decision_boundary.py",
    "tests/test_dg27_v02_effect.py",
    "var/dg26/run-lock.json",
    "var/dg26/results.json",
    "var/dg26/terminal.json",
    (
        "var/dg25/s3a/dg25-s3a-e1-label-free-20260830-001/"
        "e1-label-free-arm-outputs.json"
    ),
    (
        "var/dg24/s0/dg24-s0-freeze-20260829-008/scorer-only/"
        "gold-equivalence-registry-v0.1.json"
    ),
)


class DG27RunnerError(RuntimeError):
    """The one-shot DG-27 V02 protocol cannot proceed safely."""


def freeze(path: Path = RUN_LOCK) -> dict[str, Any]:
    """Seal the corrected pre-execution contract without overwriting V01."""

    if path.exists():
        raise DG27RunnerError("DG27_V02_RUN_LOCK_ALREADY_EXISTS")
    old_lock = _verified_digest_object(OLD_LOCK, "lock_digest")
    if old_lock.get("schema") != "milai.dg27.run-lock.v0.1":
        raise DG27RunnerError("DG27_V01_LOCK_SCHEMA_DRIFT")
    dg26_terminal = _verified_digest_object(DG26_TERMINAL, "terminal_digest")
    manifest = frozen_candidate_manifest(ROOT)
    occurrences = historical_wrong_complete_occurrences(ROOT)
    baseline_accepted = historical_baseline_accepted_sources(ROOT)
    if len(manifest) != 15 or sum(len(row["candidates"]) for row in manifest) != 110:
        raise DG27RunnerError("DG27_CANDIDATE_DENOMINATOR_DRIFT")
    model_identity = _model_identity()
    if model_identity["model_id"] != MODEL_ID:
        raise DG27RunnerError("DG27_MODEL_IDENTITY_MISMATCH")

    config: dict[str, Any] = {
        "arms": {
            "D0": "DG25_HISTORICAL_REPLAY_ONLY",
            "D1": "DETERMINISTIC_INTERPRETATION_PLUS_DECISION_BOUNDARY_V02",
            "D2": "MODEL_N_BEST_PLUS_PROVISIONAL_BINDING_PLUS_DECISION_BOUNDARY_V02",
            "D3": "D2_SINGLE_BEST_FROM_SAME_MODEL_OUTPUT",
        },
        "candidate_source": "DG26_FIXED_R0_SELECTED_TOP8_PER_REQUIREMENT",
        "candidate_feature_flag": "OFF",
        "interpretation_hypotheses_per_candidate": [0, 3],
        "model_temperature": 0,
        "model_top_p": 1,
        "max_completion_tokens_per_call": 8192,
        "system_prompt_digest": canonical_sha256(DG27_SYSTEM_PROMPT),
        "response_schema_digest": canonical_sha256(DG27_RESPONSE_SCHEMA),
        "decision_boundary_profile": "decision-boundary-v0.2",
        "binding_compatibility_profile": "dg22-v0.2",
        "main_metrics": [
            "WrongComplete",
            "KnownFalseAcceptedBinding",
            "AcceptedBindingPrecision",
            "RequiredEvidenceCoverage",
            "RecoveredValidBinding",
            "AmbiguityPreservation",
            "OperatorReady",
        ],
    }
    material: dict[str, Any] = {
        "schema": "milai.dg27.v02.run-lock.v0.2",
        "goal_id": "DG-27",
        "run_id": RUN_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "review_status": "INTERNAL_PROVISIONAL",
        "execution_authority": "MILA-ML-MASTER@1.1",
        "supersedes": {
            **_identity(OLD_LOCK),
            "reason": "PRE_EXECUTION_ARCHITECTURE_CORRECTION",
            "model_calls_under_superseded_lock": 0,
            "results_under_superseded_lock": 0,
        },
        "prerequisites": {
            "DG26_terminal_status": dg26_terminal["status"],
            "DG26_terminal_reason_code": dg26_terminal["reason_code"],
            "DG26_run_lock_digest": _object(DG26_LOCK)["lock_digest"],
            "DG26_results_digest": _object(DG26_RESULTS)["results_digest"],
        },
        "D0_replay": {
            "occurrence_count": len(occurrences),
            "occurrence_digest": canonical_sha256(occurrences),
            "baseline_accepted_source_count": len(baseline_accepted),
            "baseline_accepted_source_digest": canonical_sha256(baseline_accepted),
        },
        "candidate_snapshot": {
            "query_count": 10,
            "requirement_count": len(manifest),
            "candidate_occurrence_count": sum(
                len(row["candidates"]) for row in manifest
            ),
            "unique_candidate_count": len(
                {
                    candidate["evidence_id"]
                    for row in manifest
                    for candidate in row["candidates"]
                }
            ),
            "manifest_digest": canonical_sha256(manifest),
        },
        "model": model_identity,
        "config": config,
        "config_digest": canonical_sha256(config),
        "budget": {
            "model_calls": 15,
            "D3_reuses_D2_outputs": True,
            "interpreted_candidate_occurrences": 110,
            "automatic_retries": 0,
            "acquisition_calls": 0,
            "reader_calls": 0,
            "canonical_writes": 0,
        },
        "label_boundary": {
            "gold_registry_model_visible": False,
            "gold_registry_scorer_only": True,
            "gold_registry_open_phase": "POST_D0_D3_OUTPUT_SEAL",
        },
        "bound_identities": [_identity(ROOT / value) for value in BOUND_PATHS],
        "safety": {
            "candidate_feature_flag": "OFF",
            "canonical_mutations": 0,
            "public_mcp_schema_changed": False,
            "postgresql_schema_changed": False,
            "architecture_v1_changed": False,
        },
        "formal_holdout_used": False,
    }
    material["lock_digest"] = canonical_sha256(material)
    _write_exclusive(path, material)
    return material


def effect(
    run_lock_path: Path = RUN_LOCK,
    results_path: Path = RESULTS,
) -> dict[str, Any]:
    """Execute D0-D3 once; failures are surfaced and never retried automatically."""

    if results_path.exists():
        raise DG27RunnerError("DG27_V02_RESULTS_ALREADY_EXIST_NO_RERUN")
    lock = load_run_lock(ROOT, run_lock_path)
    model = _mapping(lock.get("model"), "model")
    config = _mapping(lock.get("config"), "config")
    adapter = LoopbackGroundedInterpretationAdapter(
        model_id=str(model["model_id"]),
        host=str(model["host"]),
        port=int(model["port"]),
        timeout_seconds=120.0,
        max_completion_tokens=int(config["max_completion_tokens_per_call"]),
    )
    result = execute_effect(ROOT, run_lock_path, adapter=adapter)
    result["created_at"] = datetime.now(UTC).isoformat()
    result["review_status"] = "INTERNAL_PROVISIONAL"
    if (
        result["cost"]["model_calls"] != 15
        or result["cost"]["interpreted_candidate_occurrences"] != 110
        or result["cost"]["automatic_retries"] != 0
    ):
        raise DG27RunnerError("DG27_FROZEN_BUDGET_DRIFT")
    result.pop("results_digest")
    result["results_digest"] = canonical_sha256(result)
    _write_exclusive(results_path, result)
    return result


def terminalize(
    run_lock_path: Path = RUN_LOCK,
    results_path: Path = RESULTS,
    terminal_path: Path = TERMINAL,
) -> dict[str, Any]:
    """Run targeted quality gates and seal the evidence-derived terminal."""

    if terminal_path.exists():
        raise DG27RunnerError("DG27_V02_TERMINAL_ALREADY_EXISTS")
    lock = load_run_lock(ROOT, run_lock_path)
    results = _verified_digest_object(results_path, "results_digest")
    if results.get("run_lock_digest") != lock.get("lock_digest"):
        raise DG27RunnerError("DG27_V02_RESULTS_LOCK_MISMATCH")
    quality = {
        "targeted_tests": _run_quality(
            [
                str(ROOT / "runtime/.venv/bin/pytest"),
                "-q",
                "runtime/tests/unit/test_dg27_decision_boundary.py",
                "tests/test_dg27_v02_effect.py",
                "runtime/tests/unit/test_requirement_state.py",
            ]
        ),
        "lint": _run_quality(
            [
                str(ROOT / "runtime/.venv/bin/ruff"),
                "check",
                *BOUND_PATHS[:7],
            ]
        ),
        "typecheck": _run_quality(
            [
                str(ROOT / "runtime/.venv/bin/mypy"),
                "--config-file",
                "runtime/pyproject.toml",
                *BOUND_PATHS[:5],
            ]
        ),
    }
    quality_passed = all(item["returncode"] == 0 for item in quality.values())
    score = _mapping(results.get("scores"), "scores")
    safety = _mapping(results.get("safety"), "safety")
    score_status = str(score["status"])
    score_reason = str(score["reason_code"])
    status = score_status if quality_passed else "FAIL"
    reason = score_reason if quality_passed else "SAFETY_OR_PROTOCOL"
    checks = _mapping(score.get("checks"), "score checks")
    hard_gate = (
        all(
            checks.get(key) is True
            for key in (
                "d1_wrong_complete_zero",
                "d2_wrong_complete_zero",
                "d3_wrong_complete_zero",
                "d1_correct_group_non_regression",
                "d2_known_false_binding_zero",
                "d2_correct_group_non_regression",
            )
        )
        and safety.get("canonical_mutations") == 0
        and safety.get("authority_violations") == 0
    )
    terminal: dict[str, Any] = {
        "schema": "milai.dg27.v02.terminal.v0.2",
        "goal_id": "DG-27",
        "run_id": lock["run_id"],
        "created_at": datetime.now(UTC).isoformat(),
        "review_status": "INTERNAL_PROVISIONAL",
        "status": status,
        "reason_code": reason,
        "claims": {
            "DG27_H1_DECISION_BOUNDARY_REPAIR": (
                "SUPPORTED" if hard_gate and quality_passed else "NOT_SUPPORTED"
            ),
            "DG27_H2_PROVISIONAL_INTERPRETATION_GAIN": (
                "SUPPORTED"
                if status == "PASS" and reason == "PROVISIONAL_INTERPRETATION_GAIN"
                else "NOT_SUPPORTED"
            ),
        },
        "quality_gates": quality,
        "run_lock_digest": lock["lock_digest"],
        "results_digest": results["results_digest"],
        "safety": {
            **dict(safety),
            "public_mcp_schema_changed": False,
            "postgresql_schema_changed": False,
            "architecture_v1_changed": False,
        },
        "rollback": {
            "model_interpretation_feature_flag": "OFF",
            "decision_boundary_v02_retained": True,
            "v01_lock_retained": OLD_LOCK.is_file(),
            "provisional_state_persisted": False,
        },
    }
    terminal["terminal_digest"] = canonical_sha256(terminal)
    _write_exclusive(terminal_path, terminal)
    return terminal


def validate(
    run_lock_path: Path = RUN_LOCK,
    results_path: Path = RESULTS,
    terminal_path: Path = TERMINAL,
) -> dict[str, Any]:
    lock = load_run_lock(ROOT, run_lock_path)
    results = _verified_digest_object(results_path, "results_digest")
    terminal = _verified_digest_object(terminal_path, "terminal_digest")
    if results.get("run_lock_digest") != lock.get("lock_digest"):
        raise DG27RunnerError("DG27_VALIDATE_RESULTS_LOCK_MISMATCH")
    if terminal.get("run_lock_digest") != lock.get("lock_digest"):
        raise DG27RunnerError("DG27_VALIDATE_TERMINAL_LOCK_MISMATCH")
    if terminal.get("results_digest") != results.get("results_digest"):
        raise DG27RunnerError("DG27_VALIDATE_TERMINAL_RESULTS_MISMATCH")
    return {
        "valid": True,
        "status": terminal["status"],
        "reason_code": terminal["reason_code"],
        "lock_digest": lock["lock_digest"],
        "results_digest": results["results_digest"],
        "terminal_digest": terminal["terminal_digest"],
    }


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


def _model_identity() -> dict[str, Any]:
    connection = http.client.HTTPConnection(MODEL_HOST, MODEL_PORT, timeout=10.0)
    try:
        connection.request("GET", "/v1/models")
        response = connection.getresponse()
        body = response.read()
    except (OSError, TimeoutError) as error:
        raise DG27RunnerError("DG27_MODEL_UNAVAILABLE_AT_FREEZE") from error
    finally:
        connection.close()
    if response.status != 200:
        raise DG27RunnerError(f"DG27_MODEL_IDENTITY_HTTP_{response.status}")
    decoded = json.loads(body)
    rows = decoded.get("data") if isinstance(decoded, Mapping) else None
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        raise DG27RunnerError("DG27_MODEL_IDENTITY_RESPONSE_INVALID")
    return {
        "model_id": str(rows[0].get("id", "")),
        "host": MODEL_HOST,
        "port": MODEL_PORT,
        "endpoint": "/v1/chat/completions",
        "identity_endpoint": "/v1/models",
    }


def _identity(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise DG27RunnerError(f"DG27_BOUND_PATH_MISSING:{path}")
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
        raise DG27RunnerError(f"DG27_DIGEST_MISMATCH:{path}")
    return value


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG27RunnerError(f"DG27_JSON_OBJECT_REQUIRED:{path}")
    return value


def _mapping(value: object, source: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DG27RunnerError(f"DG27_MAPPING_REQUIRED:{source}")
    return value


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("freeze", "effect", "terminal", "all", "validate")
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "freeze":
        output = freeze()
    elif args.command == "effect":
        output = effect()
    elif args.command == "terminal":
        output = terminalize()
    elif args.command == "validate":
        output = validate()
    else:
        freeze()
        effect()
        output = terminalize()
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
