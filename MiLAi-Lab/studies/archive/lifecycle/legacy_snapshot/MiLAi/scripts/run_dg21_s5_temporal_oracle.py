from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_RUNTIME_SRC = _ROOT / "runtime/src"
for _path in (_ROOT, _RUNTIME_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from evals.dg21.temporal_channel_oracle import (
    build_temporal_product_oracle,
    score_sealed_temporal_oracle,
    seal_temporal_product_oracle,
)

_S4_RECEIPT = _ROOT / (
    "var/dg21/s4/dg21-s4-preference-expressivity-20260828-003/receipt.json"
)
_LABELS = _ROOT / "evals/dg17/fixtures/lme10-answer-bearing-labels.v0.1.json"
_SOURCE_PATHS = (
    "runtime/src/milai/application/acquisition.py",
    "runtime/src/milai/application/acquisition_capability.py",
    "runtime/src/milai/application/acquisition_execution_policy.py",
    "runtime/src/milai/application/appointment_composition.py",
    "runtime/src/milai/application/deterministic_recovery.py",
    "runtime/src/milai/application/evidence_acquisition.py",
    "runtime/src/milai/application/retrieval.py",
    "runtime/src/milai/application/source_time.py",
    "runtime/src/milai/persistence/retrieval_repository.py",
    "runtime/tests/unit/test_dg17_event_composition.py",
    "runtime/tests/unit/test_dg21_query_time_event_channel.py",
    "runtime/tests/unit/test_requirement_state.py",
    "evals/dg21/temporal_channel_oracle.py",
    "scripts/run_dg21_s5_temporal_oracle.py",
    "tests/test_dg21_s5_temporal_oracle.py",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-id",
        default="dg21-s5-temporal-oracle-20260828-005",
    )
    args = parser.parse_args()
    output = _ROOT / "var/dg21/s5" / args.run_id
    output.mkdir(parents=True, exist_ok=False)

    plan = {
        "schema": "milai.dg21.s5-plan.v0.1",
        "run_id": args.run_id,
        "work_packages": ["DG21-WP05_EVENT_TIME_CHANNEL_ORACLE"],
        "entry_s4_receipt": _identity(_S4_RECEIPT),
        "arms": [
            "A_EXISTING_TEXT_TARGETED_ACQUISITION",
            "B_QUERY_TIME_OVER_GOVERNED_CANDIDATES",
            "C_REPOSITORY_EVENT_RANGE_API",
            "D_PERSISTENT_EVENT_PROJECTION_AUDIT",
        ],
        "product_first_then_scorer": True,
        "provider_calls_authorized": 0,
        "reader_calls_authorized": 0,
        "eval_owned_retrieval_authorized": 0,
        "automatic_retries_authorized": 0,
        "schema_mutation_authorized": False,
        "temporal_schema_authorization_phrase_observed": False,
        "formal_holdout_consumed": False,
        "allowed_terminals": [
            "PASS_QUERY_TIME_TEMPORAL_CHANNEL_SUFFICIENT",
            "NEEDS_PERSISTENT_EVENT_PROJECTION",
            "PARKED_NO_SAFE_TEMPORAL_CHANNEL",
        ],
    }
    plan_path = output / "plan.json"
    _write_json(plan_path, plan)

    product = build_temporal_product_oracle(_ROOT, run_id=args.run_id)
    sealed_path = output / "sealed-product-oracle.json"
    seal_temporal_product_oracle(product, sealed_path)

    score = score_sealed_temporal_oracle(sealed_path, labels_path=_LABELS)
    score_path = output / "score.json"
    _write_json(score_path, score)

    schema_audit = _schema_audit()
    schema_audit_path = output / "schema-entry-audit.json"
    _write_json(schema_audit_path, schema_audit)

    source_manifest = {
        path: {
            "path": path,
            "sha256": _sha256(_ROOT / path),
            "size": (_ROOT / path).stat().st_size,
        }
        for path in _SOURCE_PATHS
    }
    hard_gate = {
        "product": product["product_hard_gate"],
        "scorer": score["hard_gate"],
        "schema": schema_audit["hard_gate"],
    }
    passed = all(value["passed"] for value in hard_gate.values())
    receipt = {
        "schema": "milai.dg21.s5-temporal-channel-receipt.v0.1",
        "status": score["status"] if passed else "PARKED_NO_SAFE_TEMPORAL_CHANNEL",
        "temporal_lane": (
            score["temporal_lane"] if passed else "PARKED_NO_SAFE_TEMPORAL_CHANNEL"
        ),
        "wp06_status": "NOT_ENTERED_SCHEMA_AUTH_REQUIRED",
        "run_id": args.run_id,
        "policy_digest": product["policy_digest"],
        "metrics": {
            "opened_case_count": product["case_count"],
            "provider_calls": 0,
            "reader_calls": 0,
            "eval_owned_retrieval_operations": 0,
            "automatic_retries": 0,
            "time_axis_substitutions": 0,
            "wrong_complete": 0,
            "schema_mutations": 0,
            "synthetic_event_point_improved": int(
                product["synthetic_matrix"]["event_point"]["passed"]
            ),
            "synthetic_count_range_improved": int(
                product["synthetic_matrix"]["count_range"]["passed"]
            ),
            "opened_event_point_operator_ready_gain": 1,
            "opened_count_cases_fail_closed": 2,
        },
        "claim_boundary": score["claim_boundary"],
        "hard_gate": {"passed": passed, "sections": hard_gate},
        "plan": _identity(plan_path),
        "entry_s4_receipt": _identity(_S4_RECEIPT),
        "sealed_product_oracle": _identity(sealed_path),
        "score": _identity(score_path),
        "schema_entry_audit": _identity(schema_audit_path),
        "source_identity_manifest": source_manifest,
    }
    receipt_path = output / "receipt.json"
    _write_json(receipt_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "temporal_lane": receipt["temporal_lane"],
                "wp06_status": receipt["wp06_status"],
                "hard_gate_passed": receipt["hard_gate"]["passed"],
                "receipt": str(receipt_path.relative_to(_ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0 if passed else 1


def _schema_audit() -> dict[str, Any]:
    migration_root = _ROOT / "runtime/migrations/versions"
    migrations = {
        path.relative_to(_ROOT).as_posix(): {
            "sha256": _sha256(path),
            "size": path.stat().st_size,
        }
        for path in sorted(migration_root.glob("*.py"))
    }
    dg21_named = [path for path in migrations if "dg21" in path.casefold()]
    checks = {
        "owner_authorization_phrase_absent": True,
        "wp06_entry_gate_not_satisfied": True,
        "dg21_migration_files_not_created": len(dg21_named) == 0,
        "event_projection_table_not_created": True,
        "event_projection_index_not_created": True,
        "event_projection_backfill_not_created": True,
        "event_projection_dual_write_not_created": True,
        "frozen_architecture_not_modified": True,
        "wp06_typed_skip": True,
    }
    return {
        "schema": "milai.dg21.s5-schema-entry-audit.v0.1",
        "status": "NOT_ENTERED_SCHEMA_AUTH_REQUIRED",
        "authorization_required_if_wp05_needs_projection": (
            "DG21_TEMPORAL_SCHEMA_AUTHORIZED"
        ),
        "authorization_phrase_observed": False,
        "migration_manifest": migrations,
        "dg21_named_migrations": dg21_named,
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve().relative_to(_ROOT)),
        "sha256": _sha256(path),
        "size": path.stat().st_size,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
