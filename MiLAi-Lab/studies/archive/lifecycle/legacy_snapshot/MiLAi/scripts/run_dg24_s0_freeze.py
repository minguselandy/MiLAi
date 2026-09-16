#!/usr/bin/env python3
"""Freeze DG-24 inputs, source/stage identities, and scorer-only registries."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (ROOT, RUNTIME_SRC):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from evals.dg24.freeze import build_s0_freeze, identity
from milai.domain.retrieval_audit import (
    RetrievalAuditIntegrityReason,
    RetrievalAuditReason,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg24-s0-freeze-20260829-008")
    args = parser.parse_args()
    output = ROOT / "var/dg24/s0" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    scorer = output / "scorer-only"
    scorer.mkdir()

    failure_index = ROOT / "var/dg24/failure-index.jsonl"
    failure_index.parent.mkdir(parents=True, exist_ok=True)
    if not failure_index.exists():
        failure_index.write_text("", encoding="utf-8")

    plan_path = output / "plan.json"
    write_json(
        plan_path,
        {
            "schema": "milai.dg24.s0-plan.v0.1",
            "run_id": args.run_id,
            "phase_order": ["PRODUCT", "OFFICIAL_PROBE", "SCORER", "TERMINAL"],
            "reader_calls_authorized": 0,
            "generative_provider_calls_authorized": 0,
            "automatic_retry_authorized": False,
            "formal_holdout_authorized": False,
            "canonical_write_authorized": False,
            "public_schema_change_authorized": False,
            "database_migration_authorized": False,
            "candidate_default": False,
        },
    )
    freeze = build_s0_freeze(ROOT)
    freeze["run_id"] = args.run_id

    input_manifest_path = output / "input-only-case-manifest-v0.1.json"
    write_json(input_manifest_path, freeze.pop("input_manifest"))
    input_validation_path = output / "input-only-forbidden-field-validation.json"
    write_json(input_validation_path, freeze.pop("input_manifest_validation"))
    gold_path = scorer / "gold-equivalence-registry-v0.1.json"
    proof_path = scorer / "proof-obligation-registry-v0.1.json"
    write_json(gold_path, freeze.pop("gold_registry"))
    write_json(proof_path, freeze.pop("proof_registry"))
    source_path = output / "transitive-source-manifest.json"
    write_json(source_path, freeze.pop("source_manifest"))
    stage_registry = freeze.pop("stage_registry")
    stage_registry["source_manifest_digest"] = sha256_file(source_path)
    stage_path = output / "stage-implementation-registry-v0.1.json"
    write_json(stage_path, stage_registry)
    caps_path = output / "official-audit-cap-registry-v0.1.json"
    write_json(caps_path, freeze.pop("audit_caps"))
    semantic_path = output / "semantic-comparison-fields.json"
    write_json(
        semantic_path,
        {
            "schema": "milai.dg24.semantic-comparison-fields.v0.1",
            "fields": freeze.pop("semantic_comparison_fields"),
            "nonsemantic_exclusions": [
                "latency_ms",
                "duration_ms",
                "durations_ms",
                "elapsed_ms",
                "total_ms",
                "causal_waited_ms",
                "waited_ms",
                "*_latency_ms",
                "created_at",
                "timestamp",
                "trace_id",
            ],
        },
    )
    reason_path = output / "reason-code-registry.json"
    write_json(
        reason_path,
        {
            "schema": "milai.dg24.reason-code-registry.v0.1",
            "first_loss_reasons": [item.value for item in RetrievalAuditReason],
            "audit_integrity_reasons": [
                item.value for item in RetrievalAuditIntegrityReason
            ],
            "free_text_primary_reason_allowed": False,
        },
    )
    preseal_time = datetime.now(UTC).isoformat()
    preseal_path = output / "registry-preseal-receipt.json"
    write_json(
        preseal_path,
        {
            "schema": "milai.dg24.registry-preseal-receipt.v0.1",
            "run_id": args.run_id,
            "sealed_at": preseal_time,
            "product_requests_started": 0,
            "product_traces_observed": 0,
            "probe_traces_observed": 0,
            "gold_registry": identity(ROOT, gold_path),
            "proof_registry": identity(ROOT, proof_path),
            "opaque_seals_exposed_to_product_probe": {
                "gold_registry_sha256": sha256_file(gold_path),
                "proof_registry_sha256": sha256_file(proof_path),
            },
            "registry_content_exposed_to_product_probe": False,
            "passed": True,
        },
    )
    baseline_path = output / "baseline-source-stage-freeze.json"
    write_json(baseline_path, freeze)
    receipt_path = output / "receipt.json"
    write_json(
        receipt_path,
        {
            "schema": "milai.dg24.s0-freeze-receipt.v0.1",
            "run_id": args.run_id,
            "status": freeze["status"],
            "hard_gate": freeze["hard_gate"],
            "plan": identity(ROOT, plan_path),
            "baseline": identity(ROOT, baseline_path),
            "input_only_manifest": identity(ROOT, input_manifest_path),
            "input_only_validation": identity(ROOT, input_validation_path),
            "source_manifest": identity(ROOT, source_path),
            "stage_registry": identity(ROOT, stage_path),
            "audit_cap_registry": identity(ROOT, caps_path),
            "semantic_comparison_fields": identity(ROOT, semantic_path),
            "reason_code_registry": identity(ROOT, reason_path),
            "registry_preseal": identity(ROOT, preseal_path),
            "gold_registry_seal": sha256_file(gold_path),
            "proof_registry_seal": sha256_file(proof_path),
            "failure_index": identity(ROOT, failure_index),
            "safety": freeze["safety"],
        },
    )
    print(
        json.dumps(
            {
                "status": freeze["status"],
                "hard_gate_passed": freeze["hard_gate"]["passed"],
                "receipt": str(receipt_path.relative_to(ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0 if freeze["hard_gate"]["passed"] else 1


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
