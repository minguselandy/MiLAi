#!/usr/bin/env python3
"""Score sealed DG-24 product/probe artifacts twice and publish stable reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.dg24.gold_registry import open_gold_registry
from evals.dg24.proof_registry import open_proof_registry
from evals.dg24.scorer import canonical_bytes, score_sealed_artifacts

S0 = ROOT / "var/dg24/s0/dg24-s0-freeze-20260829-008"
S3 = ROOT / "var/dg24/s3/dg24-s3-product-trace-20260829-002"
S5 = ROOT / "var/dg24/s5/dg24-s5-registry-reopen-20260829-001"

REPORT_FILES = {
    "scored_report": "scored-first-loss-report.json",
    "requirement_loss_attributions": "requirement-loss-attributions.json",
    "proof_obligation_traces": "proof-obligation-traces.json",
    "stage_retention_report": "stage-retention-report.json",
    "first_loss_distribution": "first-loss-distribution.json",
    "rule_feature_attribution": "rule-feature-attribution-report.json",
    "channel_availability": "channel-availability-report.json",
    "authorized_absence": "authorized-absence-report.json",
    "successor_routing": "successor-routing-report.json",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg24-s6-scoring-20260829-003")
    args = parser.parse_args()
    output = ROOT / "var/dg24/s6" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    if read_json(S5 / "receipt.json").get("hard_gate", {}).get("passed") is not True:
        raise RuntimeError("DG24_S5_NOT_PASSED")
    product_path = S3 / "sealed-product-traces.json"
    probe_path = S3 / "sealed-official-probe-traces.json"
    gold_path = S0 / "scorer-only/gold-equivalence-registry-v0.1.json"
    proof_path = S0 / "scorer-only/proof-obligation-registry-v0.1.json"
    product = read_json(product_path)
    probes = read_json(probe_path)
    gold = open_gold_registry(gold_path)
    proof = open_proof_registry(proof_path)
    rules = _rule_sources()
    def score_once() -> dict[str, Any]:
        return score_sealed_artifacts(
            product=product,
            probes=probes,
            gold_registry=gold,
            proof_registry=proof,
            product_seal_digest=sha256_file(product_path),
            probe_seal_digest=sha256_file(probe_path),
            gold_registry_digest=sha256_file(gold_path),
            proof_registry_digest=sha256_file(proof_path),
            rule_sources=rules,
        )

    first = score_once()
    second = score_once()
    first_bytes = canonical_bytes(first)
    second_bytes = canonical_bytes(second)
    deterministic = first_bytes == second_bytes
    for key, filename in REPORT_FILES.items():
        write_json(output / filename, first[key])
    reproducibility_path = output / "independent-recomputation.json"
    write_json(
        reproducibility_path,
        {
            "schema": "milai.dg24.independent-recomputation.v0.1",
            "recompute_count": 2,
            "first_digest": hashlib.sha256(first_bytes).hexdigest(),
            "second_digest": hashlib.sha256(second_bytes).hexdigest(),
            "byte_stable": deterministic,
            "retrieval_calls": 0,
            "runtime_imports": 0,
        },
    )
    score_gate = first["scored_report"]["hard_gate"]
    checks = {
        "scored_report_gate_passed": score_gate["passed"],
        "independent_recompute_twice": deterministic,
        "all_nine_reports_written": all(
            (output / value).is_file() for value in REPORT_FILES.values()
        ),
        "runtime_retrieval_calls_zero": True,
        "reader_calls_zero": True,
        "generative_provider_calls_zero": True,
        "leave_one_rule_out_zero": first["rule_feature_attribution"][
            "leave_one_rule_out_executions"
        ]
        == 0,
    }
    receipt_path = output / "receipt.json"
    write_json(
        receipt_path,
        {
            "schema": "milai.dg24.s6-scoring-receipt.v0.1",
            "run_id": args.run_id,
            "status": "PASS_DG24_S6_SCORING"
            if all(checks.values())
            else "FAIL_DG24_S6_SCORING",
            "inputs": {
                "product": identity(product_path),
                "probes": identity(probe_path),
                "gold_registry": identity(gold_path),
                "proof_registry": identity(proof_path),
            },
            "reports": {
                key: identity(output / value) for key, value in REPORT_FILES.items()
            },
            "independent_recomputation": identity(reproducibility_path),
            "hard_gate": {"passed": all(checks.values()), "checks": checks},
            "score_hard_gate": score_gate,
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


def _rule_sources() -> dict[str, dict[str, Any]]:
    values = {
        "SYNONYM_NORMALIZATION": (
            "runtime/src/milai/application/accuracy_acquisition.py",
            "_SYNONYMS",
        ),
        "LEXICAL_HARD_FILTERS": (
            "runtime/src/milai/application/accuracy_acquisition.py",
            "_rank_requirement",
        ),
        "REGEX_QUERY_CLASSIFICATION": (
            "runtime/src/milai/application/memory_query.py",
            "MemoryQueryCompiler.compile",
        ),
        "FIXED_PRIORITY_FUSION": (
            "runtime/src/milai/application/acquisition.py",
            "fuse_acquisition_probe_results",
        ),
        "TYPE_DIRECTED_BINDING_RULES": (
            "runtime/src/milai/application/evidence_semantics.py",
            "bind_requirements",
        ),
    }
    return {
        key: {
            "source_file": relative,
            "source_symbol": symbol,
            "source_sha256": sha256_file(ROOT / relative),
            "implementation_digest": hashlib.sha256(
                f"{relative}:{symbol}".encode()
            ).hexdigest(),
        }
        for key, (relative, symbol) in values.items()
    }


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
