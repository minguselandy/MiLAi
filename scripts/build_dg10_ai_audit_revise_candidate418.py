from __future__ import annotations

import argparse
import json
import stat
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_remediation as remediation
from scripts.import_dg10_candidate4_ai_audits import (
    _validate_attempt,
    _verify_bundle,
)

ATTEMPT = ROOT.parent / (
    "evidence/dg10-candidate4-xhigh-ai-r0-r2-authority-audits/"
    "candidate.4-primary-018"
)
BUNDLE_ROOT = ROOT.parent / "evidence/dg10-candidate4-xhigh-ai-r0-r2-review"
BUNDLE_RECEIPT = ROOT / (
    "docs/reports/DG-10-r0-r2-ai-review-bundle-candidate.4.17-2026-08-22.json"
)
AUTHORITY_POLICY = ROOT / (
    "docs/contracts/DG-10-ai-execution-authority-candidate.4.18.json"
)
AUTHORITY_POLICY_SHA256 = (
    "4a3b635f3dd1d4a3f62369a4fe4588f41f1e32affc2128d941963f4ebc1a7b57"
)
EXPECTED_RAW_HASHES = {
    "events.jsonl": "0473f4e4b6283157a46f5c74fa04ab06d6c2ec80040506457549feaa849c85b5",
    "process.json": "bc6ffe4eee0118dc4eafcfc8c2c9b00f883bce15a784091152b9464bfd7c1d80",
    "review-output.json": "757ab011069584d520c378d37cecb97c879caf8b3656e70afc1c646c15632e84",
    "stderr.log": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
}
DEFAULT_OUTPUT = ROOT / (
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.18-2026-08-22.json"
)


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise remediation.RemediationError(reason)


def build() -> dict[str, Any]:
    _require(
        remediation.sha256_file(AUTHORITY_POLICY) == AUTHORITY_POLICY_SHA256,
        "candidate.4.18 authority policy drift",
    )
    _require(
        ATTEMPT.is_dir()
        and not ATTEMPT.is_symlink()
        and ATTEMPT.stat().st_uid == 998
        and ATTEMPT.stat().st_gid == 998
        and stat.S_IMODE(ATTEMPT.stat().st_mode) == 0o700,
        "protected primary-018 attempt root drift",
    )
    for name, expected in EXPECTED_RAW_HASHES.items():
        path = ATTEMPT / name
        _require(
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_uid == 998
            and path.stat().st_gid == 998
            and stat.S_IMODE(path.stat().st_mode) == 0o600
            and remediation.sha256_file(path) == expected,
            f"protected primary-018 material drift: {name}",
        )
    bundle_receipt = json.loads(BUNDLE_RECEIPT.read_text(encoding="utf-8"))
    bundle = BUNDLE_ROOT / str(bundle_receipt["bundle_directory_id"])
    manifest, manifest_paths = _verify_bundle(bundle, bundle_receipt)
    review, run_receipt, semantic_sha256 = _validate_attempt(
        ATTEMPT,
        bundle=bundle,
        manifest=manifest,
        manifest_paths=manifest_paths,
        manifest_sha256=remediation.sha256_file(bundle / "review-manifest.json"),
    )
    finding_ids = {item.get("finding_id") for item in review["findings"]}
    _require(
        run_receipt.get("decision") == "REVISE"
        and review.get("overall_disposition") == "REVISE"
        and review.get("bootstrap_policy_disposition")
        == "REVISE_R0_R2_AND_DO_NOT_AUTHORIZE_ANY_MODEL_CALL"
        and review.get("open_p0_count") == 1
        and review.get("open_p1_count") == 1
        and review.get("open_p2_count") == 0
        and finding_ids == {"DG10-C3-AI-007", "DG10-C4-AI-024"},
        "primary-018 REVISE semantics drift",
    )
    return {
        "schema": "milai.dg10.r0-r2-ai-audit-revise-receipt.v3",
        "candidate_id": remediation.CANDIDATE,
        "attempt_id": "candidate.4-primary-018",
        "bundle_directory_id": bundle.name,
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "closed_set_validation": {
            "status": "PASS",
            "execution_attestation": (
                "V3_CONTENT_ADDRESSED_CODE_ISOLATED_PYTHON_EXACT_ENV_"
                "ED25519_SIGNATURE_VERIFIED"
            ),
            "authority_policy_sha256": AUTHORITY_POLICY_SHA256,
            "provider_thread_id": run_receipt["provider_thread_id"],
            "semantic_sha256": semantic_sha256,
            "acceptance_effect": False,
            "unbound_evidence_paths": [],
        },
        "review_result": review,
        "raw_evidence": {
            "path_class": (
                "../evidence/dg10-candidate4-xhigh-ai-r0-r2-authority-audits/"
                "candidate.4-primary-018"
            ),
            "hashes": EXPECTED_RAW_HASHES,
        },
        "accepted_stages": [],
        "model_run_authorized": False,
        "release_authorized": False,
        "status": "VALID_PROTECTED_V3_REVISE_NO_ACCEPTANCE_EFFECT",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze candidate.4-primary-018 valid V3 AI REVISE"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    value = build()
    output = args.output.absolute()
    remediation.atomic_write_new(output, remediation.encoded_json(value))
    print(json.dumps({"output": str(output), "status": value["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
