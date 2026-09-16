#!/usr/bin/env python3
"""Run and validate the sole MD-02 boundary and product-shadow effects."""

from __future__ import annotations

import hashlib
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

from milai.domain.requirement_state import canonical_sha256

from evals.md02.boundary_shadow_effect import (
    evaluate_repair_dev,
    execute_boundary_effect,
    execute_shadow_effect,
    mf02_historical_non_regression,
)

RUN_ID = "md02-boundary-product-shadow-20260830-001"
OUTPUT_DIR = ROOT / "var/md02" / RUN_ID
RUN_LOCK = OUTPUT_DIR / "run-lock.json"
RESULTS = OUTPUT_DIR / "results.json"
TERMINAL = OUTPUT_DIR / "terminal.json"
REPAIR_LOG = OUTPUT_DIR / "repair-log.jsonl"

LEGAL_STATUSES = {
    "PASS_MD02_BOUNDARY_ROBUST_PRODUCT_SHADOW",
    "PASS_MD02_SHADOW_EQUIVALENT_BOUNDARY_UNRESOLVED",
    "PARKED_MD02_SHADOW_INTEGRATION_NOT_EQUIVALENT",
    "PARKED_MD02_NO_GENERALIZED_PRODUCT_GAIN",
    "FAIL_MD02_AUTHORITY_OR_EVIDENCE_BOUNDARY",
}
REGRESSION_TARGETS = (
    "runtime/tests/unit/test_memory_formation_bundle.py",
    "runtime/tests/unit/test_mf03_formation_extraction.py",
    "runtime/tests/unit/test_mf04_state_change_formation.py",
    "runtime/tests/unit/test_semantic_episode_boundary_v02.py",
    "runtime/tests/unit/test_semantic_episode_shadow.py",
    "tests/test_md01_formation_bundle_effect.py",
    "tests/test_md01_artifacts.py",
    "tests/test_mf02_four_arm_effect.py",
    "tests/test_mf02_artifacts.py",
    "tests/test_md02_boundary_shadow_effect.py",
    "tests/test_dg30_read_path_integration.py",
)
IMPLEMENTATION_PATHS = (
    "runtime/src/milai/domain/semantic_episode_shadow.py",
    "runtime/src/milai/application/semantic_episode_boundary_v02.py",
    "runtime/src/milai/application/semantic_episode_shadow.py",
    "evals/md02/boundary_shadow_effect.py",
    "scripts/seal_md02_labels.py",
    "scripts/run_md02_semantic_episode_shadow.py",
    "runtime/tests/unit/test_semantic_episode_boundary_v02.py",
    "runtime/tests/unit/test_semantic_episode_shadow.py",
    "tests/test_md02_boundary_shadow_effect.py",
    "tests/test_md02_artifacts.py",
)


def run() -> dict[str, Any]:
    lock = _verify_pre_effect_lock()
    regression = _run_regression()
    if not regression["passed"]:
        raise RuntimeError("MD02_PRE_EFFECT_REGRESSION_FAILED")

    repair = evaluate_repair_dev(ROOT)
    if not repair["h1_supported"]:
        raise RuntimeError("MD02_REPAIR_DEV_POLICY_NOT_FROZEN")

    boundary = execute_boundary_effect(ROOT)
    shadow = execute_shadow_effect(ROOT)
    historical = mf02_historical_non_regression(ROOT)
    h1 = bool(_mapping(boundary["score"], "boundary score")["h1_supported"])
    h2 = bool(_mapping(shadow["score"], "shadow score")["h2_supported"])
    authority_safe = _authority_safe(boundary, shadow)
    status = _status(h1=h1, h2=h2, authority_safe=authority_safe)
    if status not in LEGAL_STATUSES:
        raise RuntimeError("MD02_ILLEGAL_TERMINAL_STATUS")

    results: dict[str, Any] = {
        "schema": "milai.md02.results.v0.1",
        "run_id": RUN_ID,
        "executed_at": datetime.now(UTC).isoformat(),
        "execution_authority": "USER_EXPLICIT_20260830_MD02_EXECUTE",
        "run_lock": _identity(RUN_LOCK),
        "run_lock_digest": lock["run_lock_digest"],
        "effect_attempts": {"boundary": 1, "product_shadow": 1},
        "repair_dev_summary": {
            "conversation_count": len(repair["records"]),
            "deltas": repair["deltas"],
            "checks": repair["checks"],
            "failure_distribution": repair["failure_distribution"],
            "used_for_v02_repair": True,
            "included_in_main_denominator": False,
        },
        "boundary_effect": boundary,
        "product_shadow_effect": shadow,
        "mf02_historical_non_regression": historical,
        "hypotheses": {
            "MD02-H1": "PASS" if h1 else "MISS",
            "MD02-H2": "PASS" if h2 else "MISS",
        },
        "authority_safe": authority_safe,
        "status": status,
        "formal_holdout_used": False,
    }
    results["results_digest"] = canonical_sha256(results)
    results_payload = _payload(results)
    results_identity = _payload_identity(RESULTS, results_payload)
    terminal: dict[str, Any] = {
        "schema": "milai.md02.terminal.v0.1",
        "run_id": RUN_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "status": status,
        "execution_authority": "USER_EXPLICIT_20260830_MD02_EXECUTE",
        "effect_attempts": {"boundary": 1, "product_shadow": 1},
        "run_lock": _identity(RUN_LOCK),
        "results": results_identity,
        "results_digest": results["results_digest"],
        "boundary_prediction_digest_before_scoring": boundary[
            "prediction_digest_before_scoring"
        ],
        "shadow_digest_before_contract_scoring": shadow[
            "shadow_digest_before_contract_scoring"
        ],
        "implementation_identity": [
            _identity(ROOT / relative_path) for relative_path in IMPLEMENTATION_PATHS
        ],
        "repair_log": _identity(REPAIR_LOG) if REPAIR_LOG.is_file() else None,
        "hypotheses": results["hypotheses"],
        "authority_safe": authority_safe,
        "boundary_summary": {
            "boundary": boundary["score"]["boundary"],
            "simple_read": boundary["score"]["simple_read"],
            "deltas": boundary["score"]["deltas"],
            "checks": boundary["score"]["checks"],
        },
        "shadow_summary": {
            "metrics": shadow["score"]["metrics"],
            "checks": shadow["score"]["checks"],
            "cost": shadow["score"]["cost"],
        },
        "failure_distribution": {
            "boundary": boundary["score"]["failure_distribution"],
            "shadow": shadow["score"]["disposition_distribution"],
        },
        "mf02_historical_non_regression": historical,
        "regression": regression,
        "safety": {
            "boundary": boundary["score"]["safety"],
            "shadow": shadow["score"]["safety"],
        },
        "scope": {
            "claim": "SEALED_NON_HOLDOUT_BOUNDARY_AND_OBSERVATION_ONLY_SHADOW",
            "product_release_ready_claimed": False,
            "formal_holdout_used": False,
            "schema_changed": False,
            "public_mcp_changed": False,
            "database_accessed": False,
            "canonical_state_changed": False,
            "product_feature_flag_changed": False,
            "durable_episode_created": False,
        },
        "next_route": _next_route(status),
    }
    terminal["terminal_digest"] = canonical_sha256(terminal)
    _write_exclusive_payload(RESULTS, results_payload)
    _write_exclusive_payload(TERMINAL, _payload(terminal))
    return validate()


def validate() -> dict[str, Any]:
    lock = _object(RUN_LOCK)
    results = _object(RESULTS)
    terminal = _object(TERMINAL)
    _verify_embedded_digest(lock, "run_lock_digest")
    _verify_embedded_digest(results, "results_digest")
    _verify_embedded_digest(terminal, "terminal_digest")
    status = str(terminal["status"])
    if status not in LEGAL_STATUSES or status != results["status"]:
        raise RuntimeError("MD02_TERMINAL_STATUS_INVALID")
    if terminal["run_lock"] != _identity(RUN_LOCK):
        raise RuntimeError("MD02_TERMINAL_RUN_LOCK_LINK_INVALID")
    if terminal["results"] != _identity(RESULTS):
        raise RuntimeError("MD02_TERMINAL_RESULTS_LINK_INVALID")
    if terminal["results_digest"] != results["results_digest"]:
        raise RuntimeError("MD02_TERMINAL_RESULTS_DIGEST_INVALID")
    if terminal["effect_attempts"] != {"boundary": 1, "product_shadow": 1}:
        raise RuntimeError("MD02_EFFECT_ATTEMPT_COUNT_INVALID")
    if terminal["implementation_identity"] != [
        _identity(ROOT / relative_path) for relative_path in IMPLEMENTATION_PATHS
    ]:
        raise RuntimeError("MD02_IMPLEMENTATION_DRIFT_AFTER_EFFECT")
    if terminal["repair_log"] != (
        _identity(REPAIR_LOG) if REPAIR_LOG.is_file() else None
    ):
        raise RuntimeError("MD02_REPAIR_LOG_LINK_INVALID")
    expected_artifacts = {"run-lock.json", "results.json", "terminal.json"}
    if REPAIR_LOG.is_file():
        expected_artifacts.add("repair-log.jsonl")
    if {
        path.name for path in OUTPUT_DIR.iterdir() if path.is_file()
    } != expected_artifacts:
        raise RuntimeError("MD02_MAJOR_ARTIFACT_SET_INVALID")
    _verify_frozen_inputs(lock)
    if status == "PASS_MD02_BOUNDARY_ROBUST_PRODUCT_SHADOW":
        if results["hypotheses"] != {"MD02-H1": "PASS", "MD02-H2": "PASS"}:
            raise RuntimeError("MD02_PASS_HYPOTHESES_INCOMPLETE")
        if results["authority_safe"] is not True:
            raise RuntimeError("MD02_PASS_AUTHORITY_SAFETY_INVALID")
    if results["formal_holdout_used"] is not False:
        raise RuntimeError("MD02_FORMAL_HOLDOUT_BOUNDARY_INVALID")
    return {
        "valid": True,
        "status": status,
        "terminal_digest": terminal["terminal_digest"],
        "hypotheses": terminal["hypotheses"],
        "boundary_summary": terminal["boundary_summary"],
        "shadow_summary": terminal["shadow_summary"],
        "failure_distribution": terminal["failure_distribution"],
        "safety": terminal["safety"],
        "next_route": terminal["next_route"],
    }


def _verify_pre_effect_lock() -> dict[str, Any]:
    if not RUN_LOCK.is_file():
        raise RuntimeError("MD02_RUN_LOCK_MISSING")
    if RESULTS.exists() or TERMINAL.exists():
        raise RuntimeError("MD02_OFFICIAL_OUTPUT_ALREADY_EXISTS")
    existing = {path.name for path in OUTPUT_DIR.iterdir() if path.is_file()}
    allowed = {"run-lock.json", "repair-log.jsonl"}
    if not existing <= allowed:
        raise RuntimeError("MD02_PRE_EFFECT_ARTIFACT_SET_INVALID")
    lock = _object(RUN_LOCK)
    _verify_embedded_digest(lock, "run_lock_digest")
    _verify_frozen_inputs(lock)
    if REPAIR_LOG.is_file():
        lines = [
            line for line in REPAIR_LOG.read_text(encoding="utf-8").splitlines() if line
        ]
        if not 1 <= len(lines) <= 3:
            raise RuntimeError("MD02_REPAIR_ITERATION_COUNT_INVALID")
        for line in lines:
            value = json.loads(line)
            if (
                not isinstance(value, dict)
                or value.get("sealed_effect_executed") is not False
            ):
                raise RuntimeError("MD02_REPAIR_LOG_INVALID")
    return lock


def _verify_frozen_inputs(lock: Mapping[str, Any]) -> None:
    fixtures = _mapping(lock["fixtures"], "fixtures")
    for fixture in fixtures.values():
        identity = _mapping(fixture, "fixture identity")
        _verify_identity(ROOT / str(identity["path"]), identity)
    _verify_identity(
        ROOT / str(_mapping(lock["frozen_v01_builder"], "frozen V01")["path"]),
        lock["frozen_v01_builder"],
    )
    for identity in _sequence(lock["official_read_path"], "official read path"):
        item = _mapping(identity, "official read identity")
        _verify_identity(ROOT / str(item["path"]), item)
    predecessor = _mapping(lock["predecessor_terminal"], "predecessor terminal")
    _verify_identity(ROOT / str(predecessor["path"]), predecessor)


def _authority_safe(boundary: Mapping[str, Any], shadow: Mapping[str, Any]) -> bool:
    boundary_safety = _mapping(
        _mapping(boundary["score"], "boundary score")["safety"],
        "boundary safety",
    )
    shadow_score = _mapping(shadow["score"], "shadow score")
    shadow_metrics = _mapping(shadow_score["metrics"], "shadow metrics")
    shadow_safety = _mapping(shadow_score["safety"], "shadow safety")
    return (
        all(
            boundary_safety[name] == 1.0
            for name in (
                "raw_span_coverage",
                "source_order_preservation",
                "user_semantic_source_precision",
                "artifact_lineage_closure",
                "deterministic_replay",
            )
        )
        and all(
            boundary_safety[name] == 0
            for name in (
                "canonical_mutations",
                "database_calls",
                "database_writes",
                "provider_calls",
                "reader_calls",
                "model_calls",
            )
        )
        and boundary_safety["formal_holdout_used"] is False
        and boundary_safety["default_feature_flag"] == "OFF"
        and shadow_metrics["revoked_evidence_leak_rate"] == 0.0
        and shadow_metrics["permission_leak_rate"] == 0.0
        and shadow_metrics["additional_official_acquisition_calls"] == 0
        and shadow_metrics["additional_reader_provider_model_calls"] == 0
        and shadow_metrics["canonical_mutations"] == 0
        and shadow_metrics["database_writes"] == 0
        and shadow_safety["formal_holdout_used"] is False
        and shadow_safety["default_feature_flag"] == "OFF"
        and shadow_safety["public_mcp_changed"] is False
        and shadow_safety["schema_changed"] is False
        and shadow_safety["database_accessed"] is False
    )


def _status(*, h1: bool, h2: bool, authority_safe: bool) -> str:
    if not authority_safe:
        return "FAIL_MD02_AUTHORITY_OR_EVIDENCE_BOUNDARY"
    if h1 and h2:
        return "PASS_MD02_BOUNDARY_ROBUST_PRODUCT_SHADOW"
    if not h1 and h2:
        return "PASS_MD02_SHADOW_EQUIVALENT_BOUNDARY_UNRESOLVED"
    if h1 and not h2:
        return "PARKED_MD02_SHADOW_INTEGRATION_NOT_EQUIVALENT"
    return "PARKED_MD02_NO_GENERALIZED_PRODUCT_GAIN"


def _next_route(status: str) -> str:
    if status == "PASS_MD02_BOUNDARY_ROBUST_PRODUCT_SHADOW":
        return "ELIGIBLE_FOR_SEPARATELY_AUTHORIZED_FORMATION_TOPOLOGY_AND_ADMISSION_EVALUATION"
    if status == "PASS_MD02_SHADOW_EQUIVALENT_BOUNDARY_UNRESOLVED":
        return "KEEP_SHADOW_CONTRACT_REJECT_V02_BOUNDARY_POLICY"
    return "PARK_MD02_PRODUCT_ROUTE"


def _run_regression() -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-q", *REGRESSION_TARGETS]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(ROOT), str(RUNTIME_SRC)))
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    return {
        "command": command,
        "targets": list(REGRESSION_TARGETS),
        "exit_code": completed.returncode,
        "passed": completed.returncode == 0,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _payload_identity(path: Path, payload: bytes) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }


def _verify_identity(path: Path, identity: object) -> None:
    expected = _mapping(identity, "identity")
    if _identity(path) != {
        "path": str(expected["path"]),
        "sha256": str(expected["sha256"]),
        "size": int(expected["size"]),
    }:
        raise RuntimeError(f"MD02_IDENTITY_DRIFT:{path}")


def _verify_embedded_digest(value: Mapping[str, Any], field: str) -> None:
    material = dict(value)
    observed = material.pop(field, None)
    if observed != canonical_sha256(material):
        raise RuntimeError(f"MD02_DIGEST_INVALID:{field}")


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"MD02_JSON_OBJECT_REQUIRED:{path}")
    return value


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"MD02_MAPPING_REQUIRED:{name}")
    return value


def _sequence(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"MD02_LIST_REQUIRED:{name}")
    return value


def _payload(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()


def _write_exclusive_payload(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)


if __name__ == "__main__":
    command_name = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command_name not in {"run", "validate"}:
        raise SystemExit("usage: run_md02_semantic_episode_shadow.py [run|validate]")
    output = run() if command_name == "run" else validate()
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
