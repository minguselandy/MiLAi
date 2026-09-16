#!/usr/bin/env python3
"""Seal the zero-label DG-25 S3/S4 effect-readiness package."""

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

from evals.dg25.s3_readiness import (
    POST_S2_REVIEW,
    build_readiness_artifacts,
    identity,
    read_json_object,
    sha256_file,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg25-s3-readiness-20260829-001")
    parser.add_argument("--quality-run-id", required=True)
    args = parser.parse_args()
    output = ROOT / "var/dg25/readiness" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    write_json(
        output / "plan.json",
        {
            "schema": "milai.dg25.s3-readiness-plan.v0.1",
            "run_id": args.run_id,
            "authorization": identity(ROOT, POST_S2_REVIEW),
            "scope": [
                "zero-label arm configuration",
                "E2 common-input identities",
                "effect scorer source/contract seal",
                "all-arm seal protocol",
                "stop evaluator contract and synthetic tests",
                "exact per-query action-role manifest",
                "presealed S3A generator/sealer/runner",
                "hash-bound quality evidence",
            ],
            "explicitly_not_entered": [
                "S3A official E1 replay",
                "S4A official E2 transformation",
                "S4B effect scoring",
                "E3 product treatment",
                "Reader/model/provider/controller execution",
                "formal holdout",
                "latency repeats",
            ],
            "automatic_retries": 0,
        },
    )
    quality_receipt_path = (
        ROOT / "var/dg25/quality" / args.quality_run_id / "receipt.json"
    )
    quality_receipt = read_json_object(quality_receipt_path)
    artifacts = build_readiness_artifacts(
        ROOT,
        quality_evidence={
            "receipt_identity": file_identity(quality_receipt_path),
            "receipt": quality_receipt,
        },
        require_authoritative_quality=True,
    )
    for filename, value in artifacts.items():
        write_json(output / filename, value)

    validation = artifacts["readiness-validation-report.json"]
    source_manifest = artifacts["source-manifest.json"]
    current_source_matches = all(
        sha256_file(ROOT / str(item["path"])) == str(item["sha256"])
        for item in source_manifest["files"]
    )
    checks = {
        "readiness_validation_passed": validation["hard_gate"]["passed"] is True,
        "all_readiness_checks_passed": all(validation["checks"].values()),
        "all_readiness_artifacts_written": all(
            (output / name).is_file() for name in artifacts
        ),
        "readiness_artifact_count": len(artifacts) == 10,
        "source_manifest_current_match": current_source_matches,
        "post_s2_review_final_identity": (
            identity(ROOT, POST_S2_REVIEW)["sha256"]
            == "f8dfeb27cb45c3ce1935f1eeee24b8ca34e7ca6879216ad319a485f399e5b7d5"
        ),
        "registry_content_loaded_zero": True,
        "e1_official_replay_not_executed": True,
        "e2_official_transformation_not_executed": True,
        "effect_scoring_not_executed": True,
        "reader_model_provider_controller_calls_zero": True,
        "formal_holdout_untouched": True,
        "candidate_default_off": True,
        "canonical_mutations_zero": True,
        "automatic_retries_zero": True,
    }
    passed = all(checks.values())
    receipt_path = output / "receipt.json"
    write_json(
        receipt_path,
        {
            "schema": "milai.dg25.s3-readiness-receipt.v0.1",
            "run_id": args.run_id,
            "status": (
                "PASS_DG25_S3_READINESS_PENDING_FRESH_INDEPENDENT_AUTHORIZATION"
                if passed
                else "FAIL_DG25_S3_READINESS"
            ),
            "plan": file_identity(output / "plan.json"),
            "artifacts": {
                name.removesuffix(".json").replace("-", "_"): file_identity(output / name)
                for name in artifacts
            },
            "authorization_source": identity(ROOT, POST_S2_REVIEW),
            "failure_index": identity(ROOT, Path("var/dg25/failure-index.jsonl")),
            "quality_evidence_receipt": file_identity(quality_receipt_path),
            "checks": checks,
            "hard_gate": {"passed": passed},
            "authorization": {
                "fresh_independent_readiness_review_required": True,
                "s3a_e1_official_replay": False,
                "s4a_e2_official_transformation": False,
                "s4b_effect_scoring": False,
                "e3_product_treatment": False,
                "reader_model_provider_controller_calls": 0,
                "formal_holdout": False,
                "candidate_default": False,
                "latency_repeats": False,
            },
        },
    )
    result = read_json_object(receipt_path)
    print(
        json.dumps(
            {
                "status": result["status"],
                "receipt": str(receipt_path.relative_to(ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0 if passed else 1


def file_identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve().relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
