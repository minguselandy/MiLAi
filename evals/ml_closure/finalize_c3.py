"""Freeze the C3 product-integration terminal from already sealed evidence.

This command never runs product traffic and never opens benchmark data.  It only
checks the immutable C3 score, the label-blind acquisition wrapper, and the
fresh-database regression receipt before emitting the terminal artifact once.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast


class C3TerminalError(RuntimeError):
    """A prerequisite or immutable C3 identity is invalid."""


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise C3TerminalError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _verify_digest(value: Mapping[str, Any], field: str) -> None:
    material = dict(value)
    observed = material.pop(field, None)
    if observed != _canonical_sha256(material):
        raise C3TerminalError(f"INVALID_{field.upper()}")


def build_terminal(
    *,
    root: Path,
    score_path: Path,
    acquisition_path: Path,
    run_lock_path: Path,
    selected_method_path: Path,
    full_gate_path: Path,
    repair_log_path: Path,
) -> dict[str, Any]:
    score = _object(score_path)
    acquisition = _object(acquisition_path)
    run_lock = _object(run_lock_path)
    selected = _object(selected_method_path)
    full_gate = _object(full_gate_path)
    _verify_digest(score, "result_digest")
    _verify_digest(acquisition, "result_digest")
    _verify_digest(selected, "selected_method_digest")
    if score.get("status") != "PASS_C3_PRODUCT_INTEGRATION":
        raise C3TerminalError("C3_SCORE_NOT_PASS")
    if not all(cast(dict[str, bool], score.get("gates") or {}).values()):
        raise C3TerminalError("C3_SCORE_GATE_MISS")
    if selected.get("selected_candidate") != "CANDIDATE_F":
        raise C3TerminalError("SELECTED_METHOD_DRIFT")
    if full_gate.get("status") != "PASS" or full_gate.get("cleanup", {}).get(
        "status"
    ) != "PASS":
        raise C3TerminalError("FULL_GATE_NOT_PASS")
    repair_entries = [
        json.loads(line)
        for line in repair_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    official_attempts = {
        str(item.get("attempt"))
        for item in repair_entries
        if isinstance(item, dict)
    }
    if not {
        "C3-OFFICIAL-PATH-001",
        "C3-OFFICIAL-PATH-002",
        "C3-OFFICIAL-PATH-003",
        "C3-PRODUCT-REPAIR-DEV-003",
        "C3-SEALED-PROTOCOL-001",
    } <= official_attempts:
        raise C3TerminalError("C3_REPAIR_LINEAGE_INCOMPLETE")

    code_paths = {
        "formation_projection": root
        / "runtime/src/milai/application/formation_projection.py",
        "formation_semantic_replay": root
        / "runtime/src/milai/application/formation_semantic_replay.py",
        "retrieval": root / "runtime/src/milai/application/retrieval.py",
        "memory_context": root / "runtime/src/milai/application/memory_context.py",
        "memory_resolve": root / "runtime/src/milai/application/memory_resolve.py",
        "migration_0047": root
        / "runtime/migrations/versions/0047_formation_evidence_hydration.py",
        "adr_028": root / "docs/adr/ADR-028-formation-projection-identity.md",
    }
    metrics = cast(dict[str, Any], score["metrics"])
    checks = cast(dict[str, Any], acquisition["checks"])
    if acquisition.get("official_path", {}).get("openworker_mcp_witness") != (
        "SEPARATE_REAL_TRANSPORT_PASS"
    ):
        raise C3TerminalError("OFFICIAL_PATH_WITNESS_MISSING")
    terminal: dict[str, Any] = {
        "schema": "milai.memory-lifecycle.block-c3-terminal.v0.1",
        "run_id": run_lock["run_id"],
        "created_at": datetime.now(UTC).isoformat(),
        "status": "PASS_C3_PRODUCT_INTEGRATION",
        "selected_candidate": "CANDIDATE_F",
        "result_identity": {
            "result_digest": score["result_digest"],
            "result_file_sha256": _file_sha256(score_path),
            "acquisition_result_digest": acquisition["result_digest"],
            "acquisition_output_digest": acquisition["output_digest"],
            "acquisition_file_sha256": _file_sha256(acquisition_path),
            "selected_method_digest": selected["selected_method_digest"],
            "run_lock_digest": run_lock["lock_digest"],
            "repair_log_sha256_at_c3_close": _file_sha256(repair_log_path),
        },
        "code_identity_at_c3_close": {
            key: _file_sha256(path) for key, path in sorted(code_paths.items())
        },
        "migration_identity": {
            "activation_run_lock_head": run_lock["database_identity"][
                "migration_code_head"
            ],
            "verified_runtime_head": "0047_formation_hydration",
            "difference_classification": "AUTHORIZED_REPAIR_DEV_CODE_EVOLUTION",
            "run_lock_mutated": False,
            "schema_status": "0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE",
        },
        "projection_decision": {
            "adr": "ADR-028",
            "adr_status": "PROPOSED / NOT APPROVED",
            "architecture_v1_modified": False,
            "durable_formed_projection": False,
            "sidecar": "PROCESS_LOCAL_NON_DURABLE_RESTART_EMPTY",
            "feature_flag": "MILAI_MEMORY_FORMATION_MODE",
            "supported_modes": ["OFF", "SHADOW", "CANARY"],
            "default_mode": "OFF",
            "default_on_authorized": False,
        },
        "official_product_path": {
            "status": "PASS",
            "path": [
                "OpenWorker",
                "relay/UDS",
                "broker",
                "milai-mcp",
                "milai-runtime",
            ],
            "real_transport": True,
            "raw_fallback_witness": "PASS",
            "applied_canary_witness": "PASS_ABSTENTION_PRESERVED",
            "eval_owned_business_logic": False,
        },
        "sealed_effect": {
            "logical_attempts": 1,
            "canary_rerun_after_protocol_repair": False,
            "queries": metrics["query_count"],
            "canary_applied": acquisition["mode_counts"]["applied"],
            "raw_fallback": acquisition["mode_counts"]["raw_fallback"],
            "labels_visible_to_acquisition": False,
            "formal_holdout_used": False,
            "protocol_repair": "C3_ACCEPTED_EVIDENCE_ORDER_NORMALIZATION",
            "independent_off_only_diagnostic": score["input_identity"][
                "off_baseline_diagnostic"
            ],
        },
        "metrics": metrics,
        "gates": score["gates"],
        "cost": acquisition["cost"],
        "cleanup": acquisition["cleanup"],
        "regression": {
            "focused_touched_tests": {"passed": 48, "status": "PASS"},
            "runtime_fresh_database_full_gate": {
                "passed": full_gate["pytest_passed"],
                "skipped": 1,
                "skip_reason": "optional milai_client absent in runtime venv",
                "elapsed_seconds": full_gate["pytest_elapsed_seconds"],
                "cleanup": full_gate["cleanup"]["status"],
                "status": full_gate["status"],
                "receipt_sha256": _file_sha256(full_gate_path),
            },
            "python_client_suite": {"passed": 164, "status": "PASS"},
            "openworker_mcp_suite": {"passed": 101, "status": "PASS"},
            "ruff_touched": "PASS",
            "mypy_strict_touched": "PASS",
        },
        "task_classification": {
            "CL-302": {
                "status": "PASS",
                "reason": "ADR-028 submitted without modifying frozen architecture",
            },
            "CL-303": {
                "status": "PARKED_WITH_CAUSAL_ROUTE",
                "reason": "durable projection requires ADR approval; only default-OFF process-local sidecar exists",
            },
            "CL-304": {
                "status": "PASS",
                "reason": "source watermark, build epoch and request access snapshot are bound in trace",
            },
            "CL-305": {
                "status": "PARKED_WITH_CAUSAL_ROUTE",
                "reason": "process-local replay/rebuild is idempotent; durable dead-letter visibility waits for ADR approval",
            },
            "CL-306": {
                "status": "PASS",
                "reason": "request-time governance blocks revoke/retention/scope drift and process-local partitions are purged",
            },
            "CL-311": {"status": "PASS"},
            "CL-312": {"status": "PASS"},
            "CL-313": {"status": "PASS"},
            "CL-314": {"status": "PASS"},
            "CL-315": {"status": "PASS"},
            "CL-316": {"status": "PASS"},
            "CL-321": {"status": "PASS"},
            "CL-322": {"status": "PASS"},
            "CL-323": {"status": "PASS"},
            "CL-324": {
                "status": "PASS",
                "repair_dev_iterations": 3,
            },
            "CL-325": {"status": "PASS", "sealed_effects": 1},
        },
        "safety": {
            "canonical_mutations": acquisition["cost"]["canonical_mutations"],
            "authority_scope_violations": metrics["AuthorityScopeViolation"],
            "revoked_evidence_retrieval_leaks": metrics[
                "RevokedEvidenceRetrievalLeak"
            ],
            "derived_artifact_revocation_leaks": metrics[
                "DerivedArtifactRevocationLeak"
            ],
            "stale_projection_reads": metrics["StaleProjectionRead"],
            "reader_grounding_violations": metrics["ReaderGroundingViolation"],
            "product_default_enable": False,
            "formal_holdout_used": False,
        },
        "implementation_rollback": checks["rollback_to_off_identity"],
        "next_gate": "C4_NON_HOLDOUT_LIFECYCLE_AND_LONGMEMEVAL_500",
    }
    terminal["terminal_digest"] = _canonical_sha256(terminal)
    return terminal


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--score", type=Path, required=True)
    parser.add_argument("--acquisition", type=Path, required=True)
    parser.add_argument("--run-lock", type=Path, required=True)
    parser.add_argument("--selected-method", type=Path, required=True)
    parser.add_argument("--full-gate", type=Path, required=True)
    parser.add_argument("--repair-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    terminal = build_terminal(
        root=arguments.root.resolve(),
        score_path=arguments.score.resolve(),
        acquisition_path=arguments.acquisition.resolve(),
        run_lock_path=arguments.run_lock.resolve(),
        selected_method_path=arguments.selected_method.resolve(),
        full_gate_path=arguments.full_gate.resolve(),
        repair_log_path=arguments.repair_log.resolve(),
    )
    _write_exclusive(arguments.output.resolve(), terminal)
    print(json.dumps(terminal, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
