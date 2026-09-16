#!/usr/bin/env python3
"""Canary, freeze, execute, terminalize, and validate DG-27 V03."""

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

from milai.adapters.grounded_interpretation_v03 import (
    DG27_V03_RESPONSE_SCHEMA,
    DG27_V03_SYSTEM_PROMPT,
    GroundedInterpretationV03Error,
    LoopbackGroundedInterpretationAdapterV03,
)
from milai.domain.requirement_state import canonical_sha256

from evals.dg26.stateview_reranking import load_experiment_inputs
from evals.dg27.decision_boundary import (
    _case_inputs,
    frozen_candidate_manifest,
    historical_baseline_accepted_sources,
    historical_wrong_complete_occurrences,
)
from evals.dg27.decision_boundary_v03 import execute_v03_effect, load_v03_run_lock

V02_TERMINAL = ROOT / "var/dg27/v02/terminal.json"
V03_BASE_DIR = ROOT / "var/dg27/v03"
REPAIR_ITERATION_003 = (
    V03_BASE_DIR / "attempt-003/canary-repair-iteration-003.json"
)
V03_DIR = V03_BASE_DIR / "attempt-004"
RESTRICTED_DIR = V03_DIR / "restricted"
CANARY_RAW = RESTRICTED_DIR / "canary-raw-response.json"
CANARY = V03_DIR / "canary.json"
RUN_LOCK = V03_DIR / "run-lock.json"
RESULTS = V03_DIR / "results.json"
TERMINAL = V03_DIR / "terminal.json"
DG26_LOCK = ROOT / "var/dg26/run-lock.json"
MODEL_HOST = "127.0.0.1"
MODEL_PORT = 7860
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
RUN_ID = "dg27-v03-protocol-recovery-20260830-004"
CANARY_CASE = "gpt4_8279ba03"
CANARY_REQUIREMENT = "TARGET_EVENT"

BOUND_PATHS = (
    "MiLAi_Memory_Lifecycle_总_GOALS.md",
    "MiLAi_DG-27_Grounded证据解释与Binding验证_GOALS.md",
    "runtime/src/milai/domain/decision_boundary.py",
    "runtime/src/milai/application/decision_boundary.py",
    "runtime/src/milai/adapters/grounded_interpretation_v03.py",
    "evals/dg27/decision_boundary.py",
    "evals/dg27/decision_boundary_v03.py",
    "scripts/run_dg27_v03.py",
    "runtime/tests/unit/test_dg27_decision_boundary.py",
    "runtime/tests/unit/test_dg27_v03_materialization.py",
    "tests/test_dg27_v02_effect.py",
    "var/dg27/v02/terminal.json",
    "var/dg27/v03/run-lock.json",
    "var/dg27/v03/repair-iteration-001.json",
    "var/dg27/v03/attempt-002/run-lock.json",
    "var/dg27/v03/attempt-002/repair-iteration-002.json",
    "var/dg27/v03/attempt-003/canary-repair-iteration-003.json",
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


class DG27V03RunnerError(RuntimeError):
    """The V03 repair protocol cannot proceed without violating its freeze."""


def canary_and_freeze(path: Path = RUN_LOCK) -> dict[str, Any]:
    """Pass offline gates, run one real canary, then write the superseding lock."""

    if path.exists():
        raise DG27V03RunnerError("DG27_V03_RUN_LOCK_ALREADY_EXISTS")
    offline = _offline_quality()
    if any(item["returncode"] != 0 for item in offline.values()):
        raise DG27V03RunnerError("DG27_V03_OFFLINE_GATES_FAILED")
    if CANARY.exists():
        canary = _verified_digest_object(CANARY, "canary_digest")
        if canary.get("status") != "PASS":
            raise DG27V03RunnerError("DG27_V03_CANARY_NOT_PASS")
        if _sha256_file(CANARY_RAW) != canary.get("raw_response_sha256"):
            raise DG27V03RunnerError("DG27_V03_CANARY_RAW_IDENTITY_DRIFT")
    else:
        canary = _run_canary()

    manifest = frozen_candidate_manifest(ROOT)
    occurrences = historical_wrong_complete_occurrences(ROOT)
    baseline_accepted = historical_baseline_accepted_sources(ROOT)
    if len(manifest) != 15 or sum(len(row["candidates"]) for row in manifest) != 110:
        raise DG27V03RunnerError("DG27_V03_CANDIDATE_DENOMINATOR_DRIFT")
    model_identity = _model_identity()
    if model_identity["model_id"] != MODEL_ID:
        raise DG27V03RunnerError("DG27_V03_MODEL_IDENTITY_MISMATCH")
    v02_terminal = _verified_digest_object(V02_TERMINAL, "terminal_digest")

    config: dict[str, Any] = {
        "arms": {
            "D0": "DG25_HISTORICAL_REPLAY_ONLY",
            "D1": "DETERMINISTIC_INTERPRETATION_PLUS_DECISION_BOUNDARY_V02",
            "D2": "V03_QUOTE_GROUNDED_N_BEST_PLUS_DECISION_BOUNDARY_V02",
            "D3": "D2_SINGLE_BEST_FROM_SAME_MODEL_OUTPUT",
        },
        "candidate_source": "DG26_FIXED_R0_SELECTED_TOP8_PER_REQUIREMENT",
        "candidate_feature_flag": "OFF",
        "interpretation_hypotheses_per_candidate": [0, 3],
        "model_temperature": 0,
        "model_top_p": 1,
        "max_completion_tokens_per_call": 8192,
        "system_prompt_digest": canonical_sha256(DG27_V03_SYSTEM_PROMPT),
        "response_schema_digest": canonical_sha256(DG27_V03_RESPONSE_SCHEMA),
        "trusted_materialization": "UNIQUE_EXACT_QUOTE_TO_PYTHON_OFFSETS",
        "candidate_response_mapping": "REQUEST_SCOPED_EXACT_REQUIRED_OBJECT_KEYS",
        "dynamic_schema_derivation": "CANDIDATE_IDS_TO_REQUIRED_PROPERTIES_V01",
        "timezone_policy": "EXPLICIT_OR_SOURCE_CONTEXT_ELSE_UNRESOLVED",
        "local_dispositions": [
            "VALID",
            "REJECTED_PROTOCOL",
            "DOWNGRADED_UNRESOLVED",
        ],
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
        "schema": "milai.dg27.v03.run-lock.v0.3",
        "goal_id": "DG-27",
        "run_id": RUN_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "review_status": "INTERNAL_PROVISIONAL",
        "execution_authority": "MILA-ML-MASTER@1.2",
        "supersedes": {
            **_identity(REPAIR_ITERATION_003),
            "run_disposition": "REPAIR_ITERATION",
            "reason": "EXPLICIT_IRRELEVANT_AND_CANARY_EVIDENCE_REPAIR",
            "matched_effect_formed": False,
        },
        "repair_iteration": _identity(REPAIR_ITERATION_003),
        "canary": {
            "status": canary["status"],
            "canary_digest": canary["canary_digest"],
            "raw_response_sha256": canary["raw_response_sha256"],
            "case_id": CANARY_CASE,
            "requirement_id": CANARY_REQUIREMENT,
            "candidate_count": canary["candidate_count"],
            "automatic_retries": canary["automatic_retries"],
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
            "canary_model_calls": 1,
            "prior_canary_model_calls": 2,
            "prior_invalid_effect_requests_submitted": 30,
            "effect_model_calls": 15,
            "D3_reuses_D2_outputs": True,
            "interpreted_candidate_occurrences": 110,
            "initial_concurrency": 4,
            "concurrency_raised": False,
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
        "offline_quality_gates": offline,
        "bound_identities": [
            *[_identity(ROOT / value) for value in BOUND_PATHS],
            _identity(CANARY),
            _identity(CANARY_RAW),
        ],
        "safety": {
            "candidate_feature_flag": "OFF",
            "canonical_mutations": 0,
            "public_mcp_schema_changed": False,
            "postgresql_schema_changed": False,
            "architecture_v1_changed": False,
        },
        "formal_holdout_used": False,
        "historical_v02_status": v02_terminal["status"],
    }
    material["lock_digest"] = canonical_sha256(material)
    _write_exclusive(path, material)
    return material


def effect(
    run_lock_path: Path = RUN_LOCK,
    results_path: Path = RESULTS,
) -> dict[str, Any]:
    """Execute the one authorized matched effect with no automatic retry."""

    if results_path.exists():
        raise DG27V03RunnerError("DG27_V03_RESULTS_ALREADY_EXIST_NO_RERUN")
    lock = load_v03_run_lock(ROOT, run_lock_path)
    model = _mapping(lock.get("model"), "model")
    config = _mapping(lock.get("config"), "config")
    adapter = LoopbackGroundedInterpretationAdapterV03(
        model_id=str(model["model_id"]),
        host=str(model["host"]),
        port=int(model["port"]),
        timeout_seconds=120.0,
        max_completion_tokens=int(config["max_completion_tokens_per_call"]),
    )
    result = execute_v03_effect(ROOT, run_lock_path, adapter=adapter)
    result["created_at"] = datetime.now(UTC).isoformat()
    result["review_status"] = "INTERNAL_PROVISIONAL"
    cost = _mapping(result.get("cost"), "cost")
    if (
        cost.get("effect_model_calls") != 15
        or cost.get("interpreted_candidate_occurrences") != 110
        or cost.get("automatic_retries") != 0
        or cost.get("concurrency") != 4
    ):
        raise DG27V03RunnerError("DG27_V03_FROZEN_BUDGET_DRIFT")
    result.pop("results_digest")
    result["results_digest"] = canonical_sha256(result)
    _write_exclusive(results_path, result)
    return result


def terminalize(
    run_lock_path: Path = RUN_LOCK,
    results_path: Path = RESULTS,
    terminal_path: Path = TERMINAL,
) -> dict[str, Any]:
    """Apply the hard gates to a valid matched effect and seal the terminal."""

    if terminal_path.exists():
        raise DG27V03RunnerError("DG27_V03_TERMINAL_ALREADY_EXISTS")
    lock = load_v03_run_lock(ROOT, run_lock_path)
    results = _verified_digest_object(results_path, "results_digest")
    if results.get("run_lock_digest") != lock.get("lock_digest"):
        raise DG27V03RunnerError("DG27_V03_RESULTS_LOCK_MISMATCH")
    quality = _terminal_quality()
    if any(item["returncode"] != 0 for item in quality.values()):
        raise DG27V03RunnerError("DG27_V03_TERMINAL_QUALITY_FAILED_REPAIR_REQUIRED")

    score = _mapping(results.get("scores"), "scores")
    checks = _mapping(score.get("checks"), "score checks")
    safety = _mapping(results.get("safety"), "safety")
    wrong_complete_zero = all(
        checks.get(key) is True
        for key in (
            "d1_wrong_complete_zero",
            "d2_wrong_complete_zero",
            "d3_wrong_complete_zero",
        )
    )
    correct_non_regression = all(
        checks.get(key) is True
        for key in (
            "d1_correct_group_non_regression",
            "d2_correct_group_non_regression",
        )
    )
    false_binding_zero = checks.get("d2_known_false_binding_zero") is True
    safe = (
        safety.get("canonical_mutations") == 0
        and safety.get("authority_violations") == 0
    )
    if not wrong_complete_zero:
        status, reason = "FAIL", "WRONG_COMPLETE_REMAINS"
    elif not false_binding_zero:
        status, reason = "FAIL", "KNOWN_FALSE_BINDING_ACCEPTED"
    elif not correct_non_regression:
        status, reason = "FAIL", "FINAL_CORRECT_CASE_REGRESSION"
    elif not safe:
        status, reason = "FAIL", "AUTHORITY_OR_CANONICAL_VIOLATION"
    else:
        status = "PASS"
        reason = (
            "PROVISIONAL_INTERPRETATION_GAIN"
            if score.get("reason_code") == "PROVISIONAL_INTERPRETATION_GAIN"
            else "DECISION_BOUNDARY_REPAIRED"
        )
    h1 = status == "PASS" and safe and wrong_complete_zero and correct_non_regression
    terminal: dict[str, Any] = {
        "schema": "milai.dg27.v03.terminal.v0.3",
        "goal_id": "DG-27",
        "run_id": lock["run_id"],
        "created_at": datetime.now(UTC).isoformat(),
        "review_status": "INTERNAL_PROVISIONAL",
        "status": status,
        "reason_code": reason,
        "claims": {
            "DG27_H1_DECISION_BOUNDARY_REPAIR": (
                "SUPPORTED" if h1 else "NOT_SUPPORTED"
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
            "v02_terminal_retained": V02_TERMINAL.is_file(),
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
    lock = load_v03_run_lock(ROOT, run_lock_path)
    results = _verified_digest_object(results_path, "results_digest")
    terminal = _verified_digest_object(terminal_path, "terminal_digest")
    if results.get("run_lock_digest") != lock.get("lock_digest"):
        raise DG27V03RunnerError("DG27_V03_VALIDATE_RESULTS_LOCK_MISMATCH")
    if terminal.get("run_lock_digest") != lock.get("lock_digest"):
        raise DG27V03RunnerError("DG27_V03_VALIDATE_TERMINAL_LOCK_MISMATCH")
    if terminal.get("results_digest") != results.get("results_digest"):
        raise DG27V03RunnerError("DG27_V03_VALIDATE_TERMINAL_RESULTS_MISMATCH")
    return {
        "valid": True,
        "status": terminal["status"],
        "reason_code": terminal["reason_code"],
        "DG27_H1": terminal["claims"]["DG27_H1_DECISION_BOUNDARY_REPAIR"],
        "lock_digest": lock["lock_digest"],
        "results_digest": results["results_digest"],
        "terminal_digest": terminal["terminal_digest"],
    }


def _run_canary() -> dict[str, Any]:
    inputs = load_experiment_inputs(ROOT, DG26_LOCK)
    cases = _case_inputs(inputs)
    context = inputs.contexts[CANARY_CASE]
    requirement_by_id = {item.slot_id: item for item in context.query_ir.requirements}
    source_records = [
        cases[CANARY_CASE]["source_by_id"][item.candidate_id]
        for item in cases[CANARY_CASE]["candidates"]
        if CANARY_REQUIREMENT in item.matched_slots
    ]
    if len(source_records) != 8:
        raise DG27V03RunnerError("DG27_V03_CANARY_CANDIDATE_DRIFT")
    adapter = LoopbackGroundedInterpretationAdapterV03(
        model_id=MODEL_ID,
        host=MODEL_HOST,
        port=MODEL_PORT,
        timeout_seconds=120.0,
        max_completion_tokens=8192,
    )
    try:
        execution = adapter.interpret(
            query=context.query,
            requirement=requirement_by_id[CANARY_REQUIREMENT],
            candidates=source_records,
            include_raw_response=True,
        )
    except GroundedInterpretationV03Error as error:
        raise DG27V03RunnerError(f"DG27_V03_CANARY_FAILED:{error}") from error
    raw = execution.raw_response
    if raw is None:
        raise DG27V03RunnerError("DG27_V03_CANARY_RAW_MISSING")
    _write_exclusive(CANARY_RAW, raw, mode=0o600)
    rows = [item.model_dump(mode="json") for item in execution.materializations]
    passed = bool(rows)
    receipt: dict[str, Any] = {
        "schema": "milai.dg27.v03.canary.v0.3",
        "goal_id": "DG-27",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if passed else "FAIL",
        "reason_code": (
            "LEGAL_LOCAL_DISPOSITION_OBSERVED"
            if passed
            else "NO_LEGAL_LOCAL_DISPOSITION"
        ),
        "case_id": CANARY_CASE,
        "requirement_id": CANARY_REQUIREMENT,
        "candidate_count": len(source_records),
        "candidate_identity_digest": canonical_sha256(
            [str(item["evidence_id"]) for item in source_records]
        ),
        "response_id": execution.response_id,
        "model_id": execution.model_id,
        "local_dispositions": rows,
        "legal_local_disposition_count": len(rows),
        "raw_response_sha256": _sha256_file(CANARY_RAW),
        "raw_response_visibility": "RESTRICTED_MODE_0600",
        "latency_ms": round(execution.latency_ms, 3),
        "prompt_tokens": execution.prompt_tokens,
        "completion_tokens": execution.completion_tokens,
        "automatic_retries": execution.automatic_retries,
        "canonical_mutations": 0,
        "authority_violations": 0,
    }
    receipt["canary_digest"] = canonical_sha256(receipt)
    _write_exclusive(CANARY, receipt)
    if not passed:
        raise DG27V03RunnerError("DG27_V03_CANARY_NO_LEGAL_LOCAL_DISPOSITION")
    return receipt


def _offline_quality() -> dict[str, Any]:
    return {
        "targeted_tests": _run_quality(
            [
                str(ROOT / "runtime/.venv/bin/pytest"),
                "-q",
                "runtime/tests/unit/test_dg27_v03_materialization.py",
                "runtime/tests/unit/test_dg27_decision_boundary.py",
                "tests/test_dg27_v02_effect.py",
            ]
        ),
        "lint": _run_quality(
            [
                str(ROOT / "runtime/.venv/bin/ruff"),
                "check",
                "runtime/src/milai/adapters/grounded_interpretation_v03.py",
                "evals/dg27/decision_boundary_v03.py",
                "scripts/run_dg27_v03.py",
                "runtime/tests/unit/test_dg27_v03_materialization.py",
            ]
        ),
        "typecheck": _run_quality(
            [
                str(ROOT / "runtime/.venv/bin/mypy"),
                "--config-file",
                "runtime/pyproject.toml",
                "runtime/src/milai/adapters/grounded_interpretation_v03.py",
                "evals/dg27/decision_boundary_v03.py",
                "scripts/run_dg27_v03.py",
            ]
        ),
    }


def _terminal_quality() -> dict[str, Any]:
    return {
        **_offline_quality(),
        "direct_binding_and_sufficiency_regression": _run_quality(
            [
                str(ROOT / "runtime/.venv/bin/pytest"),
                "-q",
                "runtime/tests/unit/test_requirement_state.py",
                "runtime/tests/unit/test_sufficiency.py",
            ]
        ),
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
        raise DG27V03RunnerError("DG27_V03_MODEL_UNAVAILABLE_AT_FREEZE") from error
    finally:
        connection.close()
    if response.status != 200:
        raise DG27V03RunnerError(f"DG27_V03_MODEL_IDENTITY_HTTP_{response.status}")
    decoded = json.loads(body)
    rows = decoded.get("data") if isinstance(decoded, Mapping) else None
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        raise DG27V03RunnerError("DG27_V03_MODEL_IDENTITY_RESPONSE_INVALID")
    return {
        "model_id": str(rows[0].get("id", "")),
        "host": MODEL_HOST,
        "port": MODEL_PORT,
        "endpoint": "/v1/chat/completions",
        "identity_endpoint": "/v1/models",
    }


def _identity(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise DG27V03RunnerError(f"DG27_V03_BOUND_PATH_MISSING:{path}")
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
        raise DG27V03RunnerError(f"DG27_V03_DIGEST_MISMATCH:{path}")
    return value


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG27V03RunnerError(f"DG27_V03_JSON_OBJECT_REQUIRED:{path}")
    return value


def _mapping(value: object, source: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DG27V03RunnerError(f"DG27_V03_MAPPING_REQUIRED:{source}")
    return value


def _write_exclusive(
    path: Path,
    value: Mapping[str, Any],
    *,
    mode: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, mode if mode is not None else 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("canary-freeze", "effect", "terminal", "all", "validate"),
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "canary-freeze":
        output = canary_and_freeze()
    elif args.command == "effect":
        output = effect()
    elif args.command == "terminal":
        output = terminalize()
    elif args.command == "validate":
        output = validate()
    else:
        canary_and_freeze()
        effect()
        output = terminalize()
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
