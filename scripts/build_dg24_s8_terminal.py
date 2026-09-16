#!/usr/bin/env python3
"""Verify DG-24 lineage and seal its single honest terminal disposition."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "var/dg24/s8"
GOAL = ROOT / "MiLAi_DG-24_检索首损点审计与候选生命周期归因_GOALS.md"
RUNBOOK = ROOT / "docs/runbooks/dg24-retrieval-first-loss-audit.md"
FAILURE_INDEX = ROOT / "var/dg24/failure-index.jsonl"
ARCHITECTURE_MANIFEST = ROOT / "architecture/v1.0/architecture_manifest.json"
ARCHITECTURE_MANIFEST_SHA256 = (
    "ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e"
)
STAGE_RECEIPTS = {
    "s0": ROOT / "var/dg24/s0/dg24-s0-freeze-20260829-008/receipt.json",
    "s1": ROOT / "var/dg24/s1/dg24-s1-contracts-20260829-007/receipt.json",
    "s2": ROOT / (
        "var/dg24/s2/dg24-s2-behavior-equivalence-20260829-005/receipt.json"
    ),
    "s3": ROOT / "var/dg24/s3/dg24-s3-product-trace-20260829-002/receipt.json",
    "s4": ROOT / "var/dg24/s4/dg24-s4-official-probes-20260829-002/receipt.json",
    "s5": ROOT / "var/dg24/s5/dg24-s5-registry-reopen-20260829-001/receipt.json",
    "s6": ROOT / "var/dg24/s6/dg24-s6-scoring-20260829-003/receipt.json",
    "s7": ROOT / "var/dg24/s7/dg24-s7-quality-20260829-003/receipt.json",
}
EXPECTED_STATUS = {
    "s0": "PASS_DG24_S0_FREEZE",
    "s1": "PASS_DG24_S1_CONTRACTS",
    "s2": "PASS_DG24_S2_BEHAVIOR_EQUIVALENCE",
    "s3": "PASS_DG24_S3_PRODUCT_TRACE",
    "s4": "PASS_DG24_S4_OFFICIAL_PROBES",
    "s5": "PASS_DG24_S5_REGISTRY_REOPEN",
    "s6": "PASS_DG24_S6_SCORING",
    "s7": "PASS_DG24_S7_QUALITY_POSTGRESQL_SECURITY_ARCHITECTURE",
}
DELIVERABLE_NAMES = (
    "s0_baseline_source_stage_freeze_receipt",
    "transitive_source_manifest",
    "stage_implementation_registry_v0_1",
    "trace_schema_bundle",
    "reason_code_registry",
    "synthetic_lifecycle_matrix",
    "trace_off_on_behavior_equivalence_report",
    "sealed_product_retrieval_trace_collection",
    "candidate_lifecycle_trace_collection",
    "channel_invocation_report",
    "dedup_lineage_report",
    "product_phase_seal",
    "sealed_official_audit_probe_trace_collection",
    "channel_availability_curves",
    "probe_phase_seal",
    "gold_equivalence_registry_v0_1",
    "proof_obligation_registry_v0_1",
    "registry_seal_reopen_boundary_receipt",
    "requirement_loss_attribution_collection",
    "proof_obligation_trace_collection",
    "stage_retention_report",
    "first_loss_distribution",
    "rule_feature_attribution_report",
    "channel_availability_report",
    "authorized_absence_report",
    "successor_routing_report",
    "quality_receipt",
    "real_postgresql_integration_security_receipt",
    "append_only_failure_index",
    "source_artifact_manifests",
    "retrieval_first_loss_audit_runbook",
    "s8_terminal_receipt",
    "input_only_case_manifest_and_forbidden_field_validation",
)
PRODUCT = ROOT / (
    "var/dg24/s3/dg24-s3-product-trace-20260829-002/sealed-product-traces.json"
)


class DG24S8Error(RuntimeError):
    """Terminal evidence is missing, inconsistent, or overstated."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    return {
        "path": resolved.relative_to(ROOT).as_posix(),
        "sha256": _sha256(resolved),
        "size": resolved.stat().st_size,
    }


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DG24S8Error(f"cannot read JSON evidence: {path}") from exc
    if not isinstance(value, dict):
        raise DG24S8Error(f"JSON object required: {path}")
    return value


def _write(path: Path, value: object) -> None:
    if path.exists():
        raise DG24S8Error(f"refusing to overwrite terminal artifact: {path}")
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _referenced_identities(value: object) -> Iterator[Mapping[str, object]]:
    if isinstance(value, Mapping):
        if {"path", "sha256", "size"} <= set(value):
            yield value
        for item in value.values():
            yield from _referenced_identities(item)
    elif isinstance(value, list):
        for item in value:
            yield from _referenced_identities(item)


def _verify_identity(reference: Mapping[str, object]) -> None:
    relative = reference.get("path")
    if not isinstance(relative, str):
        raise DG24S8Error("artifact identity path is missing")
    path = ROOT / relative
    if (
        not path.is_file()
        or reference.get("size") != path.stat().st_size
        or reference.get("sha256") != _sha256(path)
    ):
        raise DG24S8Error(f"artifact identity drifted: {relative}")


def _verify_manifest(reference: Mapping[str, object]) -> None:
    _verify_identity(reference)
    manifest = _read(ROOT / str(reference["path"]))
    entries = manifest.get("identities")
    if not isinstance(entries, list) or not entries:
        raise DG24S8Error("manifest identity denominator is empty")
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise DG24S8Error("manifest identity is malformed")
        _verify_identity(entry)


def derive_terminal_disposition(signals: Mapping[str, bool]) -> str:
    """Apply the predeclared safety-first terminal precedence."""

    expected = {
        "safety_integrity",
        "label_product_boundary",
        "behavior_neutrality",
        "candidate_lineage",
        "gold_proof_mapping",
        "official_probe_fidelity",
        "attribution_completeness",
        "quality",
    }
    if set(signals) != expected:
        raise DG24S8Error("terminal signal denominator is incomplete")
    if not signals["safety_integrity"]:
        return "FAIL_SAFETY_OR_INTEGRITY"
    if not signals["label_product_boundary"]:
        return "PARKED_LABEL_PRODUCT_BOUNDARY_VIOLATION"
    if not signals["behavior_neutrality"]:
        return "PARKED_BEHAVIOR_CHANGED"
    if not signals["candidate_lineage"]:
        return "PARKED_UNRESOLVED_CANDIDATE_LINEAGE"
    if not signals["gold_proof_mapping"]:
        return "PARKED_GOLD_MAPPING_INCOMPLETE"
    if not signals["official_probe_fidelity"]:
        return "PARKED_EVAL_PRODUCT_PATH_DIVERGENCE"
    if not signals["attribution_completeness"] or not signals["quality"]:
        return "FAIL_SAFETY_OR_INTEGRITY"
    return "PASS_RETRIEVAL_FIRST_LOSS_LOCALIZED"


def _validate_failure_index() -> list[dict[str, Any]]:
    records = [
        json.loads(line)
        for line in FAILURE_INDEX.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ids = [str(record.get("failure_id", "")) for record in records]
    if (
        not records
        or not all(isinstance(record, dict) for record in records)
        or not all(ids)
        or len(ids) != len(set(ids))
        or not all(record.get("preserved") is True for record in records)
        or not all(record.get("automatic_retry") is False for record in records)
        or not all(record.get("root_cause") for record in records)
        or not all(record.get("repair") for record in records)
        or not all(record.get("successor_run_id") for record in records)
    ):
        raise DG24S8Error("append-only failure/reflection evidence is incomplete")
    return records


def _validate_stage_receipts() -> dict[str, dict[str, Any]]:
    receipts: dict[str, dict[str, Any]] = {}
    failure_relative = FAILURE_INDEX.relative_to(ROOT).as_posix()
    for stage, path in STAGE_RECEIPTS.items():
        receipt = _read(path)
        if receipt.get("status") != EXPECTED_STATUS[stage]:
            raise DG24S8Error(f"{stage} status is not authoritative")
        gate = receipt.get("hard_gate")
        if not isinstance(gate, Mapping) or gate.get("passed") is not True:
            raise DG24S8Error(f"{stage} hard gate did not pass")
        for identity in _referenced_identities(receipt):
            if identity.get("path") == failure_relative and stage != "s7":
                continue
            _verify_identity(identity)
        receipts[stage] = receipt

    s2_checks = receipts["s2"]["hard_gate"]["checks"]
    s3_checks = receipts["s3"]["hard_gate"]["checks"]
    s4_checks = receipts["s4"]["hard_gate"]["checks"]
    s5_checks = receipts["s5"]["hard_gate"]["checks"]
    s6_checks = receipts["s6"]["score_hard_gate"]["checks"]
    s7 = receipts["s7"]
    privacy = _read(ROOT / str(s7["privacy_secret_scan"]["path"]))
    postgresql = _read(ROOT / str(s7["postgresql"]["path"]))
    manifest_verification = _read(ROOT / str(s7["manifest_verification"]["path"]))
    if (
        s7.get("passed") is not True
        or s7.get("gate_count") != 12
        or s7.get("passed_gate_count") != 12
        or postgresql.get("passed") is not True
        or postgresql.get("cleanup", {}).get("status") != "PASS"
        or privacy.get("passed") is not True
        or manifest_verification.get("passed") is not True
        or s7.get("database_schema_changed_by_dg24") is not False
        or s7.get("candidate_default") is not False
        or s7.get("formal_holdout_consumed") is not False
        or s7.get("reader_calls") != 0
        or s7.get("generative_provider_calls") != 0
        or s7.get("automatic_retries") != 0
    ):
        raise DG24S8Error("S7 quality/security/cleanup evidence is incomplete")
    if _sha256(ARCHITECTURE_MANIFEST) != ARCHITECTURE_MANIFEST_SHA256:
        raise DG24S8Error("frozen architecture manifest drifted")
    _verify_manifest(s7["source_manifest"])
    _verify_manifest(s7["artifact_manifest"])
    required_checks = (
        all(s2_checks.values()),
        all(s3_checks.values()),
        all(s4_checks.values()),
        all(s5_checks.values()),
        all(s6_checks.values()),
    )
    if not all(required_checks):
        raise DG24S8Error("terminal attribution/boundary denominator is incomplete")
    return receipts


def _project_product_reports(output: Path) -> dict[str, dict[str, object]]:
    product = _read(PRODUCT)
    lifecycle_records: list[dict[str, Any]] = []
    channel_records: list[dict[str, Any]] = []
    dedup_records: list[dict[str, Any]] = []
    for record in product["records"]:
        trace = record["trace"]
        lifecycle_records.extend(
            {
                "case_id": record["case_id"],
                "request_identity": trace["request_identity"],
                "trace": lifecycle,
            }
            for lifecycle in trace["candidate_lifecycles"]
        )
        channel_records.append(
            {
                "case_id": record["case_id"],
                "request_identity": trace["request_identity"],
                "channel_decisions": trace["channel_decisions"],
                "repository_call_trace": trace["repository_call_trace"],
            }
        )
        dedup_records.extend(
            {
                "case_id": record["case_id"],
                "request_identity": trace["request_identity"],
                "decision": decision,
            }
            for decision in trace["dedup_decisions"]
        )
    lifecycle_path = output / "candidate-lifecycle-trace-collection.json"
    channel_path = output / "channel-invocation-report.json"
    dedup_path = output / "dedup-lineage-report.json"
    _write(
        lifecycle_path,
        {
            "schema": "milai.dg24.candidate-lifecycle-trace-collection.v0.1",
            "source_product": _identity(PRODUCT),
            "record_count": len(lifecycle_records),
            "records": lifecycle_records,
        },
    )
    _write(
        channel_path,
        {
            "schema": "milai.dg24.channel-invocation-report.v0.1",
            "source_product": _identity(PRODUCT),
            "product_request_count": len(channel_records),
            "records": channel_records,
        },
    )
    recoverable = all(
        bool(record["decision"].get("winner_candidate_identity"))
        and bool(record["decision"].get("preserved_channel_lineage"))
        for record in dedup_records
    )
    _write(
        dedup_path,
        {
            "schema": "milai.dg24.dedup-lineage-report.v0.1",
            "source_product": _identity(PRODUCT),
            "decision_count": len(dedup_records),
            "recoverable_lineage_rate": 1.0 if recoverable else 0.0,
            "records": dedup_records,
        },
    )
    if not lifecycle_records or len(channel_records) != 10 or not recoverable:
        raise DG24S8Error("product lifecycle/channel/dedup projection is incomplete")
    return {
        "candidate_lifecycle": _identity(lifecycle_path),
        "channel_invocation": _identity(channel_path),
        "dedup_lineage": _identity(dedup_path),
    }


def _deliverable_index(
    receipts: Mapping[str, Mapping[str, Any]],
    projections: Mapping[str, Mapping[str, object]],
    terminal_receipt: Path,
) -> dict[str, Any]:
    s0 = receipts["s0"]
    s1 = receipts["s1"]
    s2 = receipts["s2"]
    s3 = receipts["s3"]
    s4 = receipts["s4"]
    s5 = receipts["s5"]
    s6 = receipts["s6"]
    s7 = receipts["s7"]
    stage = {name: _identity(path) for name, path in STAGE_RECEIPTS.items()}
    evidence: list[list[Mapping[str, object]]] = [
        [stage["s0"]],
        [s0["source_manifest"]],
        [s0["stage_registry"]],
        [s1["trace_schema_bundle"]],
        [s0["reason_code_registry"]],
        [s1["synthetic_lifecycle_matrix"]],
        [s2["behavior_equivalence_report"]],
        [s3["product_collection"]],
        [projections["candidate_lifecycle"]],
        [projections["channel_invocation"]],
        [projections["dedup_lineage"]],
        [s3["product_phase_receipt"]],
        [s4["sealed_probe_collection"]],
        [s6["reports"]["channel_availability"]],
        [s4["source_probe_phase_receipt"]],
        [s5["gold_registry"]],
        [s5["proof_registry"]],
        [s5["boundary_receipt"]],
        [s6["reports"]["requirement_loss_attributions"]],
        [s6["reports"]["proof_obligation_traces"]],
        [s6["reports"]["stage_retention_report"]],
        [s6["reports"]["first_loss_distribution"]],
        [s6["reports"]["rule_feature_attribution"]],
        [s6["reports"]["channel_availability"]],
        [s6["reports"]["authorized_absence"]],
        [s6["reports"]["successor_routing"]],
        [stage["s7"]],
        [s7["postgresql"]],
        [_identity(FAILURE_INDEX)],
        [s7["source_manifest"], s7["artifact_manifest"]],
        [_identity(RUNBOOK)],
        [],
        [s0["input_only_manifest"], s0["input_only_validation"]],
    ]
    if len(DELIVERABLE_NAMES) != 33 or len(evidence) != 33:
        raise DG24S8Error("deliverable denominator is not 33")
    items: list[dict[str, Any]] = []
    for index, (name, identities) in enumerate(
        zip(DELIVERABLE_NAMES, evidence, strict=True), start=1
    ):
        if index == 32:
            items.append(
                {
                    "id": index,
                    "name": name,
                    "path": terminal_receipt.relative_to(ROOT).as_posix(),
                    "sealed_by_terminal_parent": True,
                }
            )
        else:
            items.append({"id": index, "name": name, "evidence": identities})
    return {
        "schema": "milai.dg24.s8-deliverable-index.v0.1",
        "deliverable_count": len(items),
        "all_non_self_deliverables_identity_bound": True,
        "items": items,
    }


def run(*, run_id: str, output: Path) -> dict[str, Any]:
    if output.exists():
        raise DG24S8Error("output exists; choose a fresh S8 run ID")
    output.mkdir(parents=True)
    receipts = _validate_stage_receipts()
    failures = _validate_failure_index()
    projections = _project_product_reports(output)
    terminal_receipt_path = output / "receipt.json"
    deliverable_index_path = output / "deliverable-index.json"
    _write(
        deliverable_index_path,
        _deliverable_index(receipts, projections, terminal_receipt_path),
    )

    artifact_paths = {
        GOAL.resolve(),
        RUNBOOK.resolve(),
        FAILURE_INDEX.resolve(),
        ARCHITECTURE_MANIFEST.resolve(),
        Path(__file__).resolve(),
        (ROOT / "scripts/run_dg24_s7_quality.py").resolve(),
        deliverable_index_path.resolve(),
    }
    artifact_paths.update(
        (ROOT / str(identity["path"])).resolve()
        for identity in projections.values()
    )
    for path in STAGE_RECEIPTS.values():
        artifact_paths.add(path.resolve())
        artifact_paths.update(item.resolve() for item in path.parent.rglob("*") if item.is_file())
    terminal_manifest_path = output / "terminal-artifact-manifest.json"
    _write(
        terminal_manifest_path,
        {
            "schema": "milai.dg24.s8-terminal-artifact-manifest.v0.1",
            "identities": [_identity(path) for path in sorted(artifact_paths)],
            "failed_run_evidence_indexed_by": _identity(FAILURE_INDEX),
        },
    )
    _verify_manifest(_identity(terminal_manifest_path))

    s0_checks = receipts["s0"]["hard_gate"]["checks"]
    s2_checks = receipts["s2"]["hard_gate"]["checks"]
    s3_checks = receipts["s3"]["hard_gate"]["checks"]
    s4_checks = receipts["s4"]["hard_gate"]["checks"]
    s5_checks = receipts["s5"]["hard_gate"]["checks"]
    s6_checks = receipts["s6"]["score_hard_gate"]["checks"]
    signals = {
        "safety_integrity": all(s0_checks.values())
        and s3_checks["canonical_mutation_zero"]
        and s3_checks["automatic_retry_zero"],
        "label_product_boundary": s3_checks["label_access_zero"]
        and s4_checks["label_access_zero"]
        and s5_checks["registry_identity_drift_zero"],
        "behavior_neutrality": all(s2_checks.values()),
        "candidate_lineage": s6_checks["dedup_lineage_recoverable_100"]
        and s6_checks["observed_occurrence_lifecycle_100"],
        "gold_proof_mapping": s5_checks["all_required_roles_mapped"]
        and s5_checks["all_proof_obligations_emitted"],
        "official_probe_fidelity": all(s4_checks.values()),
        "attribution_completeness": all(s6_checks.values()),
        "quality": receipts["s7"]["passed"] is True,
    }
    disposition = derive_terminal_disposition(signals)
    first_loss = _read(
        ROOT / str(receipts["s6"]["reports"]["first_loss_distribution"]["path"])
    )
    successor = _read(
        ROOT / str(receipts["s6"]["reports"]["successor_routing"]["path"])
    )
    failure_reason_counts: dict[str, int] = {}
    for failure in failures:
        reason = str(failure["reason_code"])
        failure_reason_counts[reason] = failure_reason_counts.get(reason, 0) + 1
    receipt = {
        "schema": "milai.dg24.s8-terminal-receipt.v0.1",
        "run_id": run_id,
        "status": disposition,
        "terminal": f"DG24 = {disposition}",
        "hard_gate": {
            "passed": disposition == "PASS_RETRIEVAL_FIRST_LOSS_LOCALIZED",
            "signals": signals,
        },
        "stage_receipts": {
            stage: _identity(path) for stage, path in STAGE_RECEIPTS.items()
        },
        "deliverable_index": _identity(deliverable_index_path),
        "deliverable_count": 33,
        "terminal_artifact_manifest": _identity(terminal_manifest_path),
        "projections": projections,
        "result_summary": {
            "first_irrecoverable_loss_counts": first_loss["counts"],
            "successor_routes": successor["routes"],
            "proof_failure_counts": successor["proof_failure_counts"],
            "treatment_executed": successor["treatment_executed"],
            "causal_claim": successor["causal_claim"],
        },
        "failure_reflection": {
            "append_only_record_count": len(failures),
            "all_failed_artifacts_preserved": all(
                failure["preserved"] is True for failure in failures
            ),
            "automatic_retry_count": sum(
                failure["automatic_retry"] is not False for failure in failures
            ),
            "all_failures_have_root_cause_and_general_repair": all(
                bool(failure["root_cause"]) and bool(failure["repair"])
                for failure in failures
            ),
            "reason_code_counts": failure_reason_counts,
        },
        "safety": {
            "candidate_default": False,
            "formal_holdout_consumed": False,
            "reader_calls": 0,
            "generative_provider_calls": 0,
            "automatic_retries": 0,
            "canonical_mutations": 0,
            "architecture_v1_changed": False,
            "public_mcp_schema_changed": False,
            "postgresql_schema_changed": False,
        },
        "claim_boundary": {
            "localized_on": (
                "frozen deidentified opened-development cases, current Runtime, "
                "official acquisition channels, policy, scope, and snapshots"
            ),
            "retrieval_recall_improved": "NOT_CLAIMED",
            "rule_causal_effect": "NOT_ESTIMATED",
            "reader_or_answer_improvement": "NOT_MEASURED_DG24",
            "formal_holdout_improvement": "NOT_MEASURED",
            "production_ready": False,
        },
    }
    _write(terminal_receipt_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg24-s8-terminal-20260829-003")
    args = parser.parse_args()
    output = OUTPUT_ROOT / args.run_id
    receipt = run(run_id=args.run_id, output=output)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "deliverable_count": receipt["deliverable_count"],
                "receipt": (output / "receipt.json").relative_to(ROOT).as_posix(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
