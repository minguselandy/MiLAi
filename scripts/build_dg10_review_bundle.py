from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scan_ua_secrets import _secrets

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-08-22"
CANDIDATE = "candidate.1"
DEFAULT_OUTPUT_ROOT = ROOT.parent / "evidence/dg10-sol-final-review"
DEFAULT_RECEIPT = (
    ROOT / f"docs/reports/DG-10-frozen-review-bundle-{CANDIDATE}-{DATE}.json"
)
MATERIALS = {
    "MiLAi_真实Provider验证与MCP_Agent接入_GOALS.md": "materials/MiLAi_真实Provider验证与MCP_Agent接入_GOALS.md",
    "docs/contracts/DG-10-claim-matrix.yaml": "materials/docs/contracts/DG-10-claim-matrix.yaml",
    "docs/contracts/DG-10-quality-acceptance.yaml": "materials/docs/contracts/DG-10-quality-acceptance.yaml",
    "docs/contracts/DG-10-tier2-blinded-audit-rubric.md": "materials/docs/contracts/DG-10-tier2-blinded-audit-rubric.md",
    "docs/reports/DG-10-current-byte-inventory-candidate.2.12-2026-08-22.json": "materials/docs/reports/DG-10-current-byte-inventory-candidate.2.12-2026-08-22.json",
    "docs/reports/DG-10-contracts-current-state-candidate.3.2-2026-08-22.json": "materials/docs/reports/DG-10-contracts-current-state-candidate.3.2-2026-08-22.json",
    "docs/reports/DG-10-final-quality-state-candidate.1-2026-08-22.json": "materials/docs/reports/DG-10-final-quality-state-candidate.1-2026-08-22.json",
    "docs/reports/DG-10-quality-calibration-assessment-candidate.1-2026-08-22.json": "materials/docs/reports/DG-10-quality-calibration-assessment-candidate.1-2026-08-22.json",
    "docs/reports/DG-10-benchmark-dataset-lock-candidate.3-2026-08-21.json": "materials/docs/reports/DG-10-benchmark-dataset-lock-candidate.3-2026-08-21.json",
    "docs/reports/DG-10-benchmark-feasibility-candidate.3-2026-08-21.json": "materials/docs/reports/DG-10-benchmark-feasibility-candidate.3-2026-08-21.json",
    "docs/reports/DG-10-benchmark-lme-v2-dev-smoke-candidate.3-2026-08-21.json": "materials/docs/reports/DG-10-benchmark-lme-v2-dev-smoke-candidate.3-2026-08-21.json",
    "docs/reports/DG-10-benchmark-three-arm-dev-candidate.3-2026-08-22.json": "materials/docs/reports/DG-10-benchmark-three-arm-dev-candidate.3-2026-08-22.json",
    "docs/reports/DG-10-bfcl-dev-aggregate-candidate.1-2026-08-21.json": "materials/docs/reports/DG-10-bfcl-dev-aggregate-candidate.1-2026-08-21.json",
    "docs/reports/DG-10-bfcl-v4-local-calibration-plan-candidate.5-2026-08-21.json": "materials/docs/reports/DG-10-bfcl-v4-local-calibration-plan-candidate.5-2026-08-21.json",
    "docs/reports/DG-10-serving-characterization-candidate.6-2026-08-22.json": "materials/docs/reports/DG-10-serving-characterization-candidate.6-2026-08-22.json",
    "docs/reports/DG-10-serving-assessment-candidate.1-2026-08-22.json": "materials/docs/reports/DG-10-serving-assessment-candidate.1-2026-08-22.json",
    "docs/reports/DG-10-tier2-blinded-audit-package-candidate.1-2026-08-22.json": "materials/docs/reports/DG-10-tier2-blinded-audit-package-candidate.1-2026-08-22.json",
    "docs/reports/DG-10-tier3-same-vllm-judge-candidate.1-2026-08-22.json": "materials/docs/reports/DG-10-tier3-same-vllm-judge-candidate.1-2026-08-22.json",
    "docs/reports/DG-10-tier3-same-vllm-judge-failure-audit-candidate.1-2026-08-22.json": "materials/docs/reports/DG-10-tier3-same-vllm-judge-failure-audit-candidate.1-2026-08-22.json",
    "docs/reports/DG-10-tier3-same-vllm-judge-candidate.2-2026-08-22.json": "materials/docs/reports/DG-10-tier3-same-vllm-judge-candidate.2-2026-08-22.json",
    "docs/reports/DG-10-tier3-same-vllm-judge-candidate.3-2026-08-22.json": "materials/docs/reports/DG-10-tier3-same-vllm-judge-candidate.3-2026-08-22.json",
    "docs/reports/DG-10-tier3-same-vllm-judge-candidate.4-2026-08-22.json": "materials/docs/reports/DG-10-tier3-same-vllm-judge-candidate.4-2026-08-22.json",
    "docs/reports/DG-10-tier3-same-vllm-judge-candidate.5-2026-08-22.json": "materials/docs/reports/DG-10-tier3-same-vllm-judge-candidate.5-2026-08-22.json",
    "docs/reports/DG-10-mcp-package-gate-candidate.2-2026-08-20.json": "materials/docs/reports/DG-10-mcp-package-gate-candidate.2-2026-08-20.json",
    "docs/reports/DG-10-openworker-mcp-host-gate-candidate.2-2026-08-20.json": "materials/docs/reports/DG-10-openworker-mcp-host-gate-candidate.2-2026-08-20.json",
    "docs/reports/DG-10-vllm-local-identity-2026-08-20.json": "materials/docs/reports/DG-10-vllm-local-identity-2026-08-20.json",
    "docs/reports/DG-10-vllm-local-ab-candidate.2-2026-08-20.json": "materials/docs/reports/DG-10-vllm-local-ab-candidate.2-2026-08-20.json",
    "docs/reports/DG-10-vllm-openworker-mcp-e2e-candidate.2.4-2026-08-20.json": "materials/docs/reports/DG-10-vllm-openworker-mcp-e2e-candidate.2.4-2026-08-20.json",
    "docs/reports/DG-10-l1-l3-reverify-summary-candidate.2.5-2026-08-21.json": "materials/docs/reports/DG-10-l1-l3-reverify-summary-candidate.2.5-2026-08-21.json",
    "docs/reports/DG-10-completion-audit-candidate.2.4-2026-08-20.md": "materials/docs/reports/DG-10-completion-audit-candidate.2.4-2026-08-20.md",
    "docs/reviews/DG-10-bfcl-scoring-remediation-sol-advisory-receipt-candidate.1-2026-08-21.json": "materials/docs/reviews/DG-10-bfcl-scoring-remediation-sol-advisory-receipt-candidate.1-2026-08-21.json",
    "docs/reviews/DG-10-dev-semantic-audit-receipt-candidate.1-2026-08-21.json": "materials/docs/reviews/DG-10-dev-semantic-audit-receipt-candidate.1-2026-08-21.json",
    "docs/runbooks/provider-mcp-agent.md": "materials/docs/runbooks/provider-mcp-agent.md",
    "docs/adr/ADR-023-self-hosted-vllm-validation-lane.md": "materials/docs/adr/ADR-023-self-hosted-vllm-validation-lane.md",
    "integrations/package-release-manifest.json": "materials/integrations/package-release-manifest.json",
    "scripts/run_dg10_final_quality_state.py": "materials/scripts/run_dg10_final_quality_state.py",
    "scripts/run_dg10_quality_calibration_assessment.py": "materials/scripts/run_dg10_quality_calibration_assessment.py",
    "scripts/run_dg10_serving_assessment.py": "materials/scripts/run_dg10_serving_assessment.py",
    "scripts/run_dg10_tier3_same_vllm_judge.py": "materials/scripts/run_dg10_tier3_same_vllm_judge.py",
    "scripts/build_dg10_tier2_blind_package.py": "materials/scripts/build_dg10_tier2_blind_package.py",
    "scripts/validate_dg10_contracts.py": "materials/scripts/validate_dg10_contracts.py",
    "tests/test_dg10_final_quality_state.py": "materials/tests/test_dg10_final_quality_state.py",
    "tests/test_dg10_serving_assessment.py": "materials/tests/test_dg10_serving_assessment.py",
    "tests/test_dg10_tier2_blind_package.py": "materials/tests/test_dg10_tier2_blind_package.py",
    "tests/test_dg10_tier3_same_vllm_judge.py": "materials/tests/test_dg10_tier3_same_vllm_judge.py",
    "docs/reviews/prompts/dg10-independent-review.md": "review-prompt.md",
    "docs/reviews/schemas/dg10-review.schema.json": "response.schema.json",
}


class ReviewBundleError(RuntimeError):
    pass


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()


def _canonical_entries_sha256(entries: list[dict[str, Any]]) -> str:
    return _sha256_bytes(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    )


def _source_entries(
    secret_source: Path,
) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    secrets = _secrets(secret_source)
    entries: list[dict[str, Any]] = []
    raw_by_destination: dict[str, bytes] = {}
    for source_relative, destination in sorted(
        MATERIALS.items(), key=lambda item: item[1]
    ):
        source = ROOT / source_relative
        if not source.is_file() or source.is_symlink():
            raise ReviewBundleError(
                f"review material missing or unsafe: {source_relative}"
            )
        destination_path = Path(destination)
        if (
            destination_path.is_absolute()
            or ".." in destination_path.parts
            or {".git", ".env"}.intersection(destination_path.parts)
        ):
            raise ReviewBundleError(f"unsafe review destination: {destination}")
        raw = source.read_bytes()
        if any(secret in raw for secret in secrets):
            raise ReviewBundleError(
                f"secret value found in review material: {source_relative}"
            )
        if destination in raw_by_destination:
            raise ReviewBundleError(f"duplicate review destination: {destination}")
        raw_by_destination[destination] = raw
        entries.append(
            {
                "path": destination,
                "source_path": source_relative,
                "size": len(raw),
                "sha256": _sha256_bytes(raw),
                "line_count": raw.count(b"\n"),
            }
        )
    return entries, raw_by_destination


def build_bundle(output_root: Path, secret_source: Path) -> tuple[Path, dict[str, Any]]:
    entries, raw_by_destination = _source_entries(secret_source)
    bundle_sha256 = _canonical_entries_sha256(entries)
    final = output_root.resolve() / f"sha256-{bundle_sha256}"
    if final.exists():
        raise ReviewBundleError(f"refusing to overwrite review bundle: {final}")
    output_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".dg10-review-", dir=output_root))
    try:
        for destination, raw in raw_by_destination.items():
            target = temporary / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            os.chmod(target, 0o444)
        manifest = {
            "schema": "milai.dg10.frozen-review-manifest.v1",
            "created_at": datetime.now(UTC).isoformat(),
            "review_kind": "AI_ADVERSARIAL_EVIDENCE_AUDIT_NOT_HUMAN_APPROVAL",
            "bundle_entries_sha256": bundle_sha256,
            "entry_count": len(entries),
            "entries": entries,
            "boundaries": {
                "closed_set_only": True,
                "read_only_required": True,
                "git_metadata_included": False,
                "environment_files_included": False,
                "repo_external_raw_sidecars_included": False,
                "secrets_included": False,
                "test_labels_or_outputs_included": False,
                "candidate_acceptance_authority": False,
            },
        }
        manifest_raw = _json_bytes(manifest)
        manifest_path = temporary / "review-manifest.json"
        manifest_path.write_bytes(manifest_raw)
        os.chmod(manifest_path, 0o444)
        for directory in sorted(
            (path for path in temporary.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            os.chmod(directory, 0o555)
        os.chmod(temporary, 0o555)
        os.replace(temporary, final)
    except BaseException:
        if temporary.exists():
            for path in temporary.rglob("*"):
                if path.is_dir():
                    os.chmod(path, 0o755)
            os.chmod(temporary, 0o755)
            shutil.rmtree(temporary)
        raise
    receipt = {
        "schema": "milai.dg10.frozen-review-bundle-receipt.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "created_at": manifest["created_at"],
        "status": "CRG00_FROZEN_NO_GO_REVIEW_BUNDLE_READY",
        "bundle_entries_sha256": bundle_sha256,
        "bundle_directory_id": final.name,
        "bundle_path_class": "REPO_EXTERNAL_READ_ONLY_MATERIALIZED_WORKSPACE",
        "entry_count": len(entries),
        "manifest_sha256": _sha256_bytes(manifest_raw),
        "manifest_size": len(manifest_raw),
        "secret_scan": {
            "status": "PASS",
            "secret_value_count": len(_secrets(secret_source)),
            "matching_files": [],
        },
        "boundaries": manifest["boundaries"],
        "test_access_authorized": False,
        "test_labels_or_outputs_opened": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "gate_results": {
            "CRG-00": "AUTHOR_BUNDLE_READY_REVIEW_REQUIRED",
            "CRG-01": "NOT_RUN",
            "CRG-02": "CANNOT_PASS_BELOW_TARGET",
        },
    }
    return final, receipt


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the DG-10 frozen Sol review bundle"
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--secret-source", type=Path, default=ROOT / "runtime/.env")
    args = parser.parse_args()
    bundle, receipt = build_bundle(args.output_root, args.secret_source.resolve())
    receipt_path = args.receipt.resolve()
    if receipt_path.exists():
        raise ReviewBundleError(f"refusing to overwrite receipt: {receipt_path}")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_bytes(_json_bytes(receipt))
    os.chmod(receipt_path, 0o600)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "bundle": str(bundle),
                "bundle_entries_sha256": receipt["bundle_entries_sha256"],
                "receipt": str(receipt_path),
                "receipt_sha256": _sha256_bytes(receipt_path.read_bytes()),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
