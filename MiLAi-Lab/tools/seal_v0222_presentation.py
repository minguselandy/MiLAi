"""Create the sole full-gate instance offline; live scope review remains separate.

No HTTP is sent here. A prepared instance still cannot preflight or launch until
its exact binding and evidence receive the delegated independent scope review.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from prepare_v0222_presentation import episode_specs, materialize_references
from v0220_evidence import LAB, dependencies, read, save, seal, sha
from v0220_provider_hardened import ProviderStop
from v0222_presentation_batch import (
    BOUNDARY_BINDING,
    BOUNDARY_ROOT,
    HISTORICAL_SOURCES,
    IDENTITY,
    PARENT_BINDING,
    PARENT_ROOT,
    REVISION,
    ROOT,
    Batch,
    authorization_source,
    make_authorization,
    verify_lineage,
)

ENTRY_NAMES = (
    "seal_v0222_presentation.py",
    "prepare_v0222_presentation.py",
    "preflight_v0222_presentation.py",
    "v0222_presentation_worker.py",
    "run_v0222_presentation.py",
)
TEST_NAMES = (
    "test_v0222_presentation_contract.py",
    "test_v0222_presentation_references.py",
    "test_v0222_presentation_preparation.py",
    "test_v0222_presentation_audit.py",
    "test_v0222_presentation_batch.py",
    "test_v0222_presentation_transport.py",
    "test_v0222_presentation_http.py",
    "test_v0222_presentation_provider.py",
    "test_v0222_presentation_preflight.py",
    "test_v0222_presentation_worker.py",
    "test_run_v0222_presentation.py",
    "test_v0222_presentation_integration.py",
    "test_v0222_presentation_seal.py",
    "test_v0220_action_adapter.py",
)
ENGINEERING_COMMANDS = {
    "uv run milai-lab-check-boundary",
    "uv run pytest",
    "uv run ruff check src tests tools",
    "uv run mypy src/milai_lab",
    "uv build",
    "git diff --check",
}


def checked_files(path: Path, status: str, *, include_sources: bool = False) -> dict:
    value = read(path)
    if value.get("status") != status or not value.get("files"):
        raise ProviderStop("REQUIRED_OFFLINE_EVIDENCE_NOT_PASS")
    files = {**value["files"], str(path): sha(path)}
    if include_sources:
        if not value.get("sources"):
            raise ProviderStop("CURRENT_AUDITOR_SOURCE_CLOSURE_REQUIRED")
        files.update(value["sources"])
    if any(sha(Path(p)) != h for p, h in files.items()):
        raise ProviderStop("OFFLINE_EVIDENCE_OR_CURRENT_SOURCE_DRIFT")
    return files


def prepare(root: Path, proof_path: Path, engineering_path: Path) -> dict:
    root = root.resolve()
    if root != ROOT or root.exists():
        raise ProviderStop("ONE_FRESH_FIXED_PRESENTATION_INSTANCE_REQUIRED")
    verify_lineage()
    proof = read(proof_path)
    if (
        proof.get("mode") != "OFFLINE_ONLY_NOT_AUTHORIZATION"
        or proof.get("P3_requests") != 16
        or proof.get("P4_requests") != 80
        or proof.get("P4_chains") != 24
        or proof.get("model_requests") != 0
        or proof.get("http_requests") != 0
    ):
        raise ProviderStop("COMPLETE_NEW_OFFLINE_REFERENCE_PROOF_REQUIRED")
    inputs = checked_files(proof_path, "CURRENT_AUDITOR_FULL_REFERENCE_PASS", include_sources=True)
    inputs.update(checked_files(engineering_path, "ENGINEERING_CHECKS_PASS"))
    review_path = BOUNDARY_ROOT / "independent-result-review.json"
    inputs.update(checked_files(review_path, "BOUNDARY_RESULT_REVIEW_PASS"))
    for path, expected in HISTORICAL_SOURCES:
        inputs[path] = expected
    design = LAB / "docs/V0222_PRESENTATION_FULL_GATE_DESIGN_NOT_ADMITTED.md"
    inputs[str(design)] = sha(design)
    entries = [LAB / "tools" / name for name in ENTRY_NAMES]
    entries += [LAB / "tests/unit" / name for name in TEST_NAMES]
    if any(not p.is_file() for p in entries):
        raise ProviderStop("ALL_NEW_ENTRYPOINTS_AND_INTEGRATION_TESTS_REQUIRED")
    engineering = read(engineering_path)
    checks = engineering.get("checks", [])
    if (
        len(checks) != len(ENGINEERING_COMMANDS)
        or {r.get("command") for r in checks} != ENGINEERING_COMMANDS
        or any(type(r.get("exit_code")) is not int or r["exit_code"] != 0 for r in checks)
    ):
        raise ProviderStop("ALL_SIX_TERMINAL_ENGINEERING_CHECKS_REQUIRED")
    if any(engineering["files"].get(str(p)) != sha(p) for p in dependencies(entries)):
        raise ProviderStop("CURRENT_ENTRYPOINT_TEST_AND_DEPENDENCY_ENGINEERING_COVERAGE_REQUIRED")
    proof_sources = proof.get("sources", {})
    if any(
        proof_sources.get(str(p)) != sha(p)
        for p in dependencies([LAB / "tools/prepare_v0222_presentation.py"])
    ):
        raise ProviderStop("COMPLETE_CURRENT_AUDITOR_REFERENCE_PROOF_SOURCE_CLOSURE_REQUIRED")
    if any(sha(Path(p)) != h for p, h in inputs.items()):
        raise ProviderStop("COMPLETE_NEW_INSTANCE_INPUT_CLOSURE_DRIFT")
    plan = {
        **episode_specs(),
        "revision": REVISION,
        "selected_decoder": "D11",
        "selected_presentation": "B1",
        "parent_root": str(PARENT_ROOT),
        "parent_binding": PARENT_BINDING,
        "boundary_root": str(BOUNDARY_ROOT),
        "boundary_binding": BOUNDARY_BINDING,
        "historical_paths": [p for p, _ in HISTORICAL_SOURCES],
        "http_identity": IDENTITY,
        "raw_cap": None,
        "offline_reference_proof": str(proof_path),
        "future_recovery_task_memory": "NOT_ADMITTED_BY_THIS_INSTANCE",
    }
    issued = time.time()
    authorization = make_authorization(root, issued=issued, expires=issued + 36 * 3600)
    seal(root, entries=entries, inputs=[Path(p) for p in inputs], contract=plan)
    save(root / "authorization-source.json", authorization_source())
    save(root / "authorization.json", authorization)
    save(
        root / "execution-binding.json",
        {
            name: sha(root / name)
            for name in ("authorization.json", "authorization-source.json", "manifest.json")
        },
    )
    binding = sha(root / "execution-binding.json")
    batch = Batch(root, binding)
    batch.initialize()
    try:
        save(root / "engineering-checks.json", read(engineering_path))
        batch.freeze_artifact(
            "engineering_checks", root / "engineering-checks.json", "ENGINEERING_CHECKS_PASS"
        )
        materialize_references(batch)
        result = {
            "status": "OFFLINE_INSTANCE_PREPARED_SCOPE_REVIEW_REQUIRED",
            "binding_sha256": binding,
            "root": str(root),
            "model_requests": 0,
            "http_requests": 0,
            "P3": "NOT_STARTED",
            "P4": "NOT_TRIGGERED",
            "Memory": "NOT_ADMITTED",
        }
        save(root / "offline-instance-prepared.json", result)
        return result
    except BaseException as exc:
        batch.stop(str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--offline-proof", type=Path, required=True)
    parser.add_argument("--engineering-checks", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.root, args.offline_proof, args.engineering_checks))
