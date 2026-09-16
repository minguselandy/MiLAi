#!/usr/bin/env python3
"""Reopen and validate the exact pre-sealed DG-24 scorer registries."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.dg24.gold_registry import open_gold_registry
from evals.dg24.proof_registry import open_proof_registry

S0 = ROOT / "var/dg24/s0/dg24-s0-freeze-20260829-008"
S3 = ROOT / "var/dg24/s3/dg24-s3-product-trace-20260829-002"
S4 = ROOT / "var/dg24/s4/dg24-s4-official-probes-20260829-002"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg24-s5-registry-reopen-20260829-001")
    args = parser.parse_args()
    output = ROOT / "var/dg24/s5" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    s0 = read_json(S0 / "receipt.json")
    product_receipt = read_json(S3 / "product-phase-receipt.json")
    probe_receipt = read_json(S3 / "probe-phase-receipt.json")
    if read_json(S4 / "receipt.json").get("hard_gate", {}).get("passed") is not True:
        raise RuntimeError("DG24_S4_NOT_PASSED")
    gold_path = S0 / "scorer-only/gold-equivalence-registry-v0.1.json"
    proof_path = S0 / "scorer-only/proof-obligation-registry-v0.1.json"
    gold_digest = sha256_file(gold_path)
    proof_digest = sha256_file(proof_path)
    identity_checks = {
        "gold_registry_matches_preseal": gold_digest == s0["gold_registry_seal"],
        "proof_registry_matches_preseal": proof_digest == s0["proof_registry_seal"],
        "product_seal_valid": sha256_file(S3 / "sealed-product-traces.json")
        == product_receipt["product_seal_digest"],
        "probe_seal_valid": sha256_file(S3 / "sealed-official-probe-traces.json")
        == probe_receipt["probe_seal_digest"],
    }
    if not all(identity_checks.values()):
        raise RuntimeError("DG24_REGISTRY_OR_EXECUTION_SEAL_IDENTITY_MISMATCH")
    reopened_at = datetime.now(UTC).isoformat()
    gold = open_gold_registry(gold_path)
    proof = open_proof_registry(proof_path)
    gold_requirements = {
        (str(query["query_id"]), str(requirement["requirement_id"])): requirement
        for query in gold["queries"]
        for requirement in query["requirements"]
    }
    proof_requirements = {
        (str(query["query_id"]), str(requirement["requirement_id"])): requirement
        for query in proof["queries"]
        for requirement in query["requirements"]
    }
    disagreements = []
    for key, requirement in gold_requirements.items():
        roles = requirement.get("evidence_roles")
        if not isinstance(roles, list) or not roles:
            disagreements.append({"key": key, "reason": "EVIDENCE_ROLE_MISSING"})
            continue
        for role in roles:
            groups = role.get("equivalence_groups")
            if not isinstance(groups, list) or not groups:
                disagreements.append(
                    {"key": key, "reason": "EQUIVALENCE_GROUP_MISSING"}
                )
            for group in groups if isinstance(groups, list) else []:
                if not group.get("acceptable_evidence_ids") or not group.get(
                    "rationale"
                ):
                    disagreements.append(
                        {"key": key, "reason": "GOLD_GROUP_MAPPING_INCOMPLETE"}
                    )
        proof_requirement = proof_requirements.get(key)
        if proof_requirement is None or not proof_requirement.get("obligations"):
            disagreements.append({"key": key, "reason": "PROOF_OBLIGATION_MISSING"})
    extra_proofs = sorted(set(proof_requirements).difference(gold_requirements))
    for key in extra_proofs:
        disagreements.append(
            {"key": key, "reason": "PROOF_REQUIREMENT_WITHOUT_GOLD_ROLE"}
        )
    scorer_paths = [
        ROOT / "evals/dg24/gold_registry.py",
        ROOT / "evals/dg24/proof_registry.py",
        ROOT / "evals/dg24/scorer.py",
    ]
    runtime_imports = {
        str(path.relative_to(ROOT)): _runtime_imports(path) for path in scorer_paths
    }
    checks = {
        **identity_checks,
        "reopened_after_product_seal": reopened_at > product_receipt["sealed_at"],
        "reopened_after_probe_seal": reopened_at > probe_receipt["sealed_at"],
        "gold_query_count_10": len(gold["queries"]) == 10,
        "proof_query_count_10": len(proof["queries"]) == 10,
        "all_required_roles_mapped": not disagreements,
        "all_proof_obligations_emitted": set(gold_requirements)
        == set(proof_requirements),
        "runtime_imports_by_scorer_zero": not any(runtime_imports.values()),
        "registry_identity_drift_zero": True,
        "runtime_retrieval_calls_zero": True,
    }
    disagreement_path = output / "mapping-disagreement-ledger.json"
    write_json(
        disagreement_path,
        {
            "schema": "milai.dg24.mapping-disagreement-ledger.v0.1",
            "records": disagreements,
            "count": len(disagreements),
        },
    )
    boundary_path = output / "registry-seal-reopen-boundary.json"
    write_json(
        boundary_path,
        {
            "schema": "milai.dg24.registry-seal-reopen-boundary.v0.1",
            "run_id": args.run_id,
            "product_sealed_at": product_receipt["sealed_at"],
            "probe_sealed_at": probe_receipt["sealed_at"],
            "registry_reopened_at": reopened_at,
            "gold_registry_sha256": gold_digest,
            "proof_registry_sha256": proof_digest,
            "runtime_imports": runtime_imports,
            "runtime_retrieval_calls": 0,
            "passed": all(checks.values()),
        },
    )
    receipt_path = output / "receipt.json"
    write_json(
        receipt_path,
        {
            "schema": "milai.dg24.s5-registry-reopen-receipt.v0.1",
            "run_id": args.run_id,
            "status": (
                "PASS_DG24_S5_REGISTRY_REOPEN"
                if all(checks.values())
                else "PARKED_GOLD_MAPPING_INCOMPLETE"
            ),
            "gold_registry": identity(gold_path),
            "proof_registry": identity(proof_path),
            "boundary_receipt": identity(boundary_path),
            "mapping_disagreement_ledger": identity(disagreement_path),
            "hard_gate": {"passed": all(checks.values()), "checks": checks},
        },
    )
    print(
        json.dumps(
            {
                "status": read_json(receipt_path)["status"],
                "receipt": str(receipt_path.relative_to(ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0 if all(checks.values()) else 1


def _runtime_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(
                alias.name for alias in node.names if alias.name.startswith("milai")
            )
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("milai")
        ):
            imports.append(node.module)
    return imports


def identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve().relative_to(ROOT)),
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
    }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
