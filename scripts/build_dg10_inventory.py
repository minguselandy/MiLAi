from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from scan_ua_secrets import ArchiveScan, _archive_kind, _secrets, scan_archive_bytes

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-08-22"
DEFAULT_OUTPUT = (
    ROOT / f"docs/reports/DG-10-current-byte-inventory-candidate.2.13-{DATE}.json"
)
EXCLUDED_PARTS = frozenset(
    {
        ".cache",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "submissions",
    }
)
TARGETS = (
    ".github/workflows/ci.yml",
    "MiLAi_真实Provider验证与MCP_Agent接入_GOALS.md",
    "codex_sol_max.md",
    "contracts/agent/v1",
    "docs/contracts/DG-10-claim-matrix.yaml",
    "docs/contracts/DG-10-quality-acceptance.yaml",
    "evals/agent_efficiency",
    "evals/agent_integration",
    "integrations/package-release-manifest.json",
    "integrations/python-client/pyproject.toml",
    "integrations/python-client/uv.lock",
    "integrations/python-client/src",
    "integrations/python-client/tests",
    "integrations/python-client/dist/milai_client-0.1.0-py3-none-any.whl",
    "integrations/python-client/dist/milai_client-0.1.0.tar.gz",
    "integrations/mcp/README.md",
    "integrations/mcp/pyproject.toml",
    "integrations/mcp/uv.lock",
    "integrations/mcp/src",
    "integrations/mcp/tests",
    "integrations/mcp/dist/milai_mcp-0.1.0-py3-none-any.whl",
    "integrations/mcp/dist/milai_mcp-0.1.0.tar.gz",
    "integrations/openworker-mcp",
    "scripts/build_dg10_inventory.py",
    "scripts/build_dg10_musl_wheelhouse.py",
    "scripts/build_package_release_manifest.py",
    "scripts/run_dg10_mcp_package_gate.py",
    "scripts/run_dg10_openworker_host_gate.py",
    "scripts/run_dg10_benchmark_contract.py",
    "scripts/run_dg10_benchmark_adapter_contract.py",
    "scripts/run_dg10_benchmark_dev_smoke.py",
    "scripts/run_dg10_benchmark_milai_mcp_smoke.py",
    "scripts/run_dg10_benchmark_lme_v2_dev_smoke.py",
    "scripts/run_dg10_bfcl_calibration_contract.py",
    "scripts/run_dg10_bfcl_single_turn_dev_smoke.py",
    "scripts/run_dg10_bfcl_prompt_capability_probe.py",
    "scripts/run_dg10_bfcl_prompt_single_turn_dev_smoke.py",
    "scripts/run_dg10_bfcl_prompt_single_turn_dev_calibration.py",
    "scripts/run_dg10_vllm_openworker_e2e.py",
    "scripts/scan_ua_secrets.py",
    "scripts/validate_dg10_contracts.py",
    "tests/test_dg10_openworker_mcp.py",
    "tests/test_dg10_vllm_openworker_e2e.py",
    "tests/test_dg10_benchmark_contract.py",
    "tests/test_dg10_benchmark_adapter_contract.py",
    "tests/test_dg10_benchmark_dev_smoke.py",
    "tests/test_dg10_benchmark_milai_mcp_smoke.py",
    "tests/test_dg10_benchmark_lme_v2_dev_smoke.py",
    "tests/test_dg10_bfcl_calibration_contract.py",
    "tests/test_dg10_bfcl_single_turn_dev_smoke.py",
    "tests/test_dg10_bfcl_prompt_capability_probe.py",
    "tests/test_dg10_bfcl_prompt_single_turn_dev_calibration.py",
    "tests/test_dg10_contracts.py",
    "tests/test_release_safety.py",
    "docs/reports/OE-07-provider-evidence-remediation-candidate.4.6-2026-08-18.md",
    "docs/reviews/OE-07-independent-rereview-candidate.4.6-2026-08-18.md",
    "docs/reports/DG-10-mcp-package-gate-2026-08-20.json",
    "docs/reports/DG-10-mcp-package-gate-candidate.2-2026-08-20.json",
    "docs/reports/DG-10-openworker-mcp-host-gate-candidate.1-2026-08-20.json",
    "docs/reports/DG-10-openworker-mcp-host-gate-candidate.2-2026-08-20.json",
    "docs/reports/DG-10-provider-target-2026-08-20.md",
    "docs/adr/ADR-023-self-hosted-vllm-validation-lane.md",
    "docs/reports/DG-10-vllm-target-2026-08-20.md",
    "docs/reports/DG-10-vllm-local-identity-2026-08-20.json",
    "docs/reports/DG-10-vllm-local-ab-2026-08-20.json",
    "docs/reports/DG-10-vllm-local-ab-candidate.2-2026-08-20.json",
    "docs/reports/DG-10-vllm-openworker-mcp-e2e-2026-08-20.json",
    "docs/reports/DG-10-vllm-openworker-mcp-e2e-candidate.2-2026-08-20.json",
    "docs/reports/DG-10-vllm-openworker-mcp-e2e-candidate.2.1-2026-08-20.json",
    "docs/reports/DG-10-vllm-openworker-mcp-e2e-candidate.2.2-2026-08-20.json",
    "docs/reports/DG-10-vllm-openworker-mcp-e2e-candidate.2.3-2026-08-20.json",
    "docs/reports/DG-10-vllm-openworker-mcp-e2e-candidate.2.4-2026-08-20.json",
    "docs/reports/DG-10-vllm-local-validation-2026-08-20.md",
    "docs/reports/DG-10-completion-audit-candidate.2.4-2026-08-20.md",
    "docs/reports/DG-10-contracts-current-state-candidate.2.5-2026-08-21.json",
    "docs/reports/DG-10-l1-l3-reverify-summary-candidate.2.5-2026-08-21.json",
    "docs/reports/DG-10-benchmark-dataset-lock-candidate.1-2026-08-21.json",
    "docs/reports/DG-10-benchmark-feasibility-candidate.1-2026-08-21.json",
    "docs/reports/DG-10-benchmark-dataset-lock-candidate.2-2026-08-21.json",
    "docs/reports/DG-10-benchmark-feasibility-candidate.2-2026-08-21.json",
    "docs/reports/DG-10-benchmark-dataset-lock-candidate.3-2026-08-21.json",
    "docs/reports/DG-10-benchmark-feasibility-candidate.3-2026-08-21.json",
    "docs/reports/DG-10-benchmark-adapter-contract-candidate.1-2026-08-21.json",
    "docs/reports/DG-10-benchmark-calibration-plan-candidate.1-2026-08-21.json",
    "docs/reports/DG-10-benchmark-adapter-contract-candidate.2-2026-08-21.json",
    "docs/reports/DG-10-benchmark-calibration-plan-candidate.2-2026-08-21.json",
    "docs/reports/DG-10-benchmark-dev-smoke-candidate.1-2026-08-21.json",
    "docs/reports/DG-10-benchmark-adapter-contract-candidate.3-2026-08-21.json",
    "docs/reports/DG-10-benchmark-calibration-plan-candidate.3-2026-08-21.json",
    "docs/reports/DG-10-benchmark-dev-smoke-candidate.2-2026-08-21.json",
    "docs/reports/DG-10-benchmark-adapter-contract-candidate.4-2026-08-21.json",
    "docs/reports/DG-10-benchmark-calibration-plan-candidate.4-2026-08-21.json",
    "docs/reports/DG-10-benchmark-dev-smoke-candidate.3-2026-08-21.json",
    "docs/reports/DG-10-benchmark-dev-smoke-candidate.4-2026-08-21.json",
    "docs/reports/DG-10-benchmark-milai-mcp-dev-smoke-candidate.1-2026-08-21.json",
    "docs/reports/DG-10-benchmark-milai-mcp-dev-smoke-candidate.2-2026-08-21.json",
    "docs/reports/DG-10-benchmark-lme-v2-dev-smoke-candidate.1-2026-08-21.json",
    "docs/reports/DG-10-benchmark-lme-v2-dev-failed-attempt-candidate.2-2026-08-21.json",
    "docs/reports/DG-10-benchmark-lme-v2-dev-smoke-candidate.3-2026-08-21.json",
    "docs/reports/DG-10-bfcl-v4-local-calibration-plan-candidate.1-2026-08-21.json",
    "docs/reports/DG-10-bfcl-v4-local-calibration-plan-candidate.2-2026-08-21.json",
    "docs/reports/DG-10-bfcl-v4-local-calibration-plan-candidate.3-2026-08-21.json",
    "docs/reports/DG-10-bfcl-v4-local-calibration-plan-candidate.4-2026-08-21.json",
    "docs/reports/DG-10-bfcl-v4-local-calibration-plan-candidate.5-2026-08-21.json",
    "docs/reports/DG-10-bfcl-prompt-capability-probe-candidate.1-2026-08-21.json",
    "docs/reports/DG-10-bfcl-prompt-single-turn-dev-smoke-candidate.1-2026-08-21.json",
    "docs/reports/DG-10-bfcl-prompt-single-turn-dev-calibration-candidate.1-2026-08-21.json",
    "docs/reports/DG-10-current-byte-inventory-candidate.2.4-2026-08-20.json",
    "docs/reports/DG-10-current-byte-inventory-candidate.2.5-2026-08-21.json",
    "docs/reports/DG-10-current-byte-inventory-candidate.2.6-2026-08-21.json",
    "docs/reports/DG-10-current-byte-inventory-candidate.2.7-2026-08-21.json",
    "docs/reports/DG-10-current-byte-inventory-candidate.2.8-2026-08-21.json",
    "docs/reports/DG-10-current-byte-inventory-candidate.2.9-2026-08-21.json",
    "docs/reports/DG-10-current-byte-inventory-candidate.2.10-2026-08-21.json",
    "docs/reviews/DG-10-dev-semantic-audit-receipt-candidate.1-2026-08-21.json",
    "docs/reviews/DG-10-vllm-local-independent-review-handoff-2026-08-20.md",
    "docs/runbooks/provider-mcp-agent.md",
    "docs/contracts",
    "docs/reports",
    "docs/reviews",
    "scripts",
    "tests",
    "runtime/src",
    "runtime/migrations",
    "runtime/tests",
    "runtime/pyproject.toml",
    "runtime/uv.lock",
    "runtime/alembic.ini",
    "integrations/python-client",
    "integrations/mcp",
)


class InventoryError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _paths(output: Path) -> list[Path]:
    paths: set[Path] = set()
    for relative in TARGETS:
        target = ROOT / relative
        if not target.exists():
            raise InventoryError(f"required inventory target is missing: {relative}")
        candidates = target.rglob("*") if target.is_dir() else (target,)
        for candidate in candidates:
            if candidate.is_dir() or EXCLUDED_PARTS.intersection(candidate.parts):
                continue
            if candidate.is_symlink():
                raise InventoryError(
                    f"inventory target contains a symlink: {candidate}"
                )
            if candidate.is_file() and candidate.resolve() != output:
                paths.add(candidate.resolve())
    return sorted(paths, key=lambda path: path.relative_to(ROOT).as_posix())


def _scan(paths: list[Path], env_path: Path) -> dict[str, Any]:
    secret_values = _secrets(env_path)
    matching_paths: list[str] = []
    archive = ArchiveScan()
    scanned_bytes = 0
    for path in paths:
        raw = path.read_bytes()
        scanned_bytes += len(raw)
        relative = path.relative_to(ROOT).as_posix()
        if any(secret in raw for secret in secret_values):
            matching_paths.append(relative)
        if _archive_kind(path.name) is not None:
            scan_archive_bytes(relative, path.name, raw, secret_values, state=archive)
    failures = (
        matching_paths
        or archive.matching_members
        or archive.forbidden_members
        or archive.unsafe_archives
    )
    if failures:
        raise InventoryError("DG-10 secret/archive safety scan failed")
    return {
        "status": "PASS",
        "secret_value_count": len(secret_values),
        "scanned_bytes": scanned_bytes,
        "matching_paths": [],
        "archive_member_count": archive.member_count,
        "archive_uncompressed_bytes": archive.uncompressed_bytes,
        "matching_archive_members": [],
        "forbidden_archive_members": [],
        "unsafe_archives": [],
    }


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the DG-10 candidate.2.13 byte inventory"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--secret-source", type=Path, default=ROOT / "runtime/.env")
    args = parser.parse_args()
    output = args.output.resolve()
    secret_source = args.secret_source.resolve()
    paths = _paths(output)
    entries = [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in paths
    ]
    canonical = hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    inventory = {
        "schema": "milai.dg10.current-byte-inventory.v1",
        "candidate": "candidate.2.13-post-sol-no-go-evidence-freeze",
        "integration_candidate": "candidate.2.4",
        "goal_contract_version": "0.3.1",
        "snapshot_date": DATE,
        "status": "LOCAL_CANDIDATE_REVIEW_REQUIRED",
        "source_revision": "NO_GIT_METADATA_WORKTREE_BYTE_INVENTORY",
        "data_boundary": "SYNTHETIC_DEIDENTIFIED_OR_PUBLIC_BENCHMARK_HASH_ONLY",
        "provider_requests": 0,
        "provider_cost": 0,
        "provider_accounting_scope": "EXTERNAL_BILLING_PROVIDER_LANE_ONLY",
        "local_vllm_final_lane_accounting": {
            "longmemeval_three_arm_native_calls": 200,
            "bfcl_latest_complete_native_calls": 1785,
            "serving_candidate_6_including_warmups_native_calls": 125,
            "tier3_candidate_5_native_calls": 36,
            "tier3_superseded_completed_native_calls": 8,
            "tier3_candidate_1_inferred_completed_unreceipted": 1,
            "tier3_candidate_2_completed_native_calls": 0,
            "tier3_known_completed_native_calls": 44,
            "tier3_early_diagnostic_completed_native_calls": "UNKNOWN",
            "self_hosted_compute_cost": "UNAVAILABLE_NOT_ZERO",
            "scope": "LATEST_SUCCESSFUL_LANES_PLUS_EXPLICIT_TIER3_ATTEMPTS; TOTAL_EARLY_DIAGNOSTIC_ATTEMPTS_UNKNOWN",
        },
        "codex_ai_development_audit_calls": 3,
        "codex_ai_development_audit_cost": "UNAVAILABLE",
        "codex_formal_sol_review": {
            "cli_invocations": 1,
            "provider_threads": 1,
            "input_tokens": 11161268,
            "cached_input_tokens": 10650368,
            "output_tokens": 65383,
            "reasoning_output_tokens": 30084,
            "cost": "UNAVAILABLE",
        },
        "public_benchmark_dev_case_counts_opened": {
            "longmemeval": 50,
            "longmemeval_v2_adapted": 42,
            "bfcl": 216,
            "cross_dataset_sum_not_unique_namespace": 308,
        },
        "public_benchmark_test_labels_or_outputs_opened": False,
        "contract_cleanup_only": False,
        "benchmark_research_candidate_bytes_changed": True,
        "runtime_architecture_vllm_candidate_bytes_changed": False,
        "entry_count": len(entries),
        "canonical_entries_sha256": canonical,
        "entries": entries,
        "secret_archive_scan": _scan(paths, secret_source),
        "external_identities": {
            "openworker_base_image_id": (
                "sha256:afa555cfccdb05c0e8a4a0b1ad84f364496d8721d45c9dbd796a7afbe5e7f05d"
            ),
            "openworker_derived_image_id": (
                "sha256:4f90c07d8a1eecdc1bad0f43ecdcb97ef5f0c388f23eca00dce58b120575f410"
            ),
            "opencode_sha256": (
                "c4847b3da969507d5cadf3321883c7b477e5ab75763014d688116a6795b63dce"
            ),
        },
        "boundary": (
            "Inventory excludes repository-external raw benchmark prompt, memory, label and "
            "model-output sidecars, Tier-2 blind/raw packages and mappings, raw Codex events/output/thread metadata, Provider credentials, "
            "billing/reconciliation material, and broker tokens. Hash-only smoke reports, the "
            "invalidated-attempt receipt, AI-development-audit receipt, formal Sol review "
            "receipt, and controlled disposition bind their external evidence."
        ),
    }
    _write(output, inventory)
    print(json.dumps(inventory, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
