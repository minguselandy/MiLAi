"""Prepare one current-candidate calibration fixture, never a timing run or K3 seal.

The historical engineering artifact is retained as workload with its original
bytes. It is not current engineering certification. No generation stage is
launched. A separate reviewed K0 contract must precede any timed worker.
"""

from __future__ import annotations

import argparse
import copy
import os
import sys
import time
from pathlib import Path


def _require_fresh_root(root: Path) -> None:
    if root.resolve() != root:
        raise ValueError("CANONICAL_MEASUREMENT_FIXTURE_ROOT_REQUIRED")
    if root.exists() or root.is_symlink():
        raise ValueError("FRESH_MEASUREMENT_FIXTURE_REQUIRED_NO_RETRY")


def _check_sealed_pins(manifest: dict, inputs: dict, sources: dict) -> None:
    if manifest["inputs"] != inputs:
        raise ValueError("MEASUREMENT_INPUT_CHANGED_AFTER_SCOPE_CLOSE")
    if manifest["dependencies"] != sources:
        raise ValueError("MEASUREMENT_SOURCE_CHANGED_AFTER_SCOPE_CLOSE")


def _public_inputs(scope, root: Path, binding_sha256: str) -> dict:
    """Public cases are direct inputs of the historical presentation manifest."""
    binding = scope.read_json(root / "execution-binding.json", binding_sha256)
    return scope.read_json(root / "manifest.json", binding["manifest.json"])["inputs"]


def _prepare():
    # Install the irreversible guard before importing any replay/provider code.
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from prepare_v0221_http_v2 import CASES
    from prepare_v0222_full import resolve_p4_spec
    from v0220_evidence import LAB, dependencies, save, seal, sha
    from v0222_admission_read_scope import AdmissionReadScope
    from v0222_presentation_lineage_v2 import verify_lineage
    from v0222_scoped_cpu_batch import CPU_ROOT as OLD_ROOT
    from v0222_scoped_cpu_batch import PRESENTATION_BINDING, PRESENTATION_ROOT
    from v0222_scoped_evidence import verify_manifest
    from v0223_diagnostic_cpu_batch import (
        CPU_REVISION,
        OfflineBatch,
        cpu_authorization_source,
        make_cpu_authorization,
        selected_root,
    )

    root = selected_root()
    if root.name.removeprefix("diagv1-") not in {
        "d1-u1",
        "d1-s1",
        "d1-s2",
        "d1-u2",
        "d1-u3",
        "d1-s3",
    }:
        raise ValueError("ONLY_CURRENT_CALIBRATION_PREPARATION_NOT_K3_SEAL")
    _require_fresh_root(root)
    with AdmissionReadScope() as scope:
        history = verify_lineage(scope)
        binding = scope.read_json(
            OLD_ROOT / "execution-binding.json", sha(OLD_ROOT / "execution-binding.json")
        )
        original = verify_manifest(scope, OLD_ROOT, binding["manifest.json"])
        public_inputs = _public_inputs(scope, PRESENTATION_ROOT, PRESENTATION_BINDING)
        plan = copy.deepcopy(original["contract"])
        plan["coordinator_revision"] = CPU_REVISION
        mappings = []
        for stage in ("P3", "P4"):
            for index, spec in enumerate(plan[stage]):
                before = copy.deepcopy(spec)
                spec["id"] = f"{root.name}-{stage.lower()}-{index + 1:02d}"
                spec["scope"] = f"v0223-{root.name}-{stage.lower()}-{index + 1:02d}"
                if stage == "P4":
                    path = CASES / spec["root"] / "public-initial.json"
                    public = scope.read_json(path, public_inputs[str(path)])
                    spec, _ = resolve_p4_spec(spec, public)
                    plan[stage][index] = spec
                allowed = (
                    {"id", "scope", "initial_state_sha256"} if stage == "P4" else {"id", "scope"}
                )
                assert {k: v for k, v in before.items() if k not in allowed} == {
                    k: v for k, v in spec.items() if k not in allowed
                }
                mappings.append(
                    {
                        "before": {k: before[k] for k in allowed},
                        "after": {k: spec[k] for k in allowed},
                    }
                )
        # Retain every original input and source/copy as benchmark burden.
        inputs = {Path(name) for name in original["inputs"]}
        inputs.update(Path(name) for name in original["dependencies"])
        inputs.update(
            OLD_ROOT / "executed-source" / Path(name).relative_to(LAB)
            for name in original["dependencies"]
        )
        inputs.add(OLD_ROOT / "manifest.json")
        engineering_path = OLD_ROOT / "engineering-checks.json"
        engineering = scope.read_json(engineering_path, sha(engineering_path))
        inputs.add(engineering_path)
        # Retain every frozen current source/input/copy, never its mutable stopped SQLite.
        prior_root = Path(
            "/cra/memory/mx_memory/evidence/v0224/20260913-gate-a-current-v1/currentv1-k3-u1"
        )
        prior_binding = scope.read_json(
            prior_root / "execution-binding.json",
            "f5419c3f8f0c2cf81820b385d16e499002696a99a67f9a348918acbc61f24110",
        )
        prior_manifest = verify_manifest(scope, prior_root, prior_binding["manifest.json"])
        inputs.update(Path(name) for name in prior_manifest["inputs"])
        inputs.update(Path(name) for name in prior_manifest["dependencies"])
        inputs.update(
            prior_root / "executed-source" / Path(name).relative_to(LAB)
            for name in prior_manifest["dependencies"]
        )
        inputs.add(prior_root / "manifest.json")
        entries = [
            LAB / "tools" / name
            for name in (
                "v0223_diagnostic_cpu_batch.py",
                "prepare_v0223_diagnostic_fixture.py",
                "inventory_v0223_diagnostic_fixture.py",
                "v0223_reference_prefix_v2.py",
                "v0223_coarse_observation.py",
                "v0223_inventory_breakdown.py",
                "v0223_tree_readonly_candidate.py",
                "v0223_transaction_primary_fix.py",
                "run_v0223_diagnostic_admission.py",
                "run_v0223_diagnostic_calibration.py",
                "assemble_v0223_diagnostic_calibration.py",
            )
        ]
        entries.extend(
            LAB / "tests/unit" / name
            for name in (
                "test_v0223_diagnostic_admission.py",
                "test_v0223_diagnostic_calibration.py",
                "test_v0223_inventory_breakdown.py",
            )
        )
        entries.extend(Path(name) for name in prior_manifest["dependencies"])
        entries.extend(Path(name) for name in original["dependencies"])
        # Freeze observed bytes before scope.close; seal must not bless drift.
        input_pins = {str(path): sha(path) for path in sorted(inputs)}
        source_pins = {str(path): sha(path) for path in dependencies(entries)}
        for pins in (input_pins, source_pins):
            for name, digest in pins.items():
                scope.read_bytes(Path(name), digest)
    _require_fresh_root(root)
    manifest = seal(root, entries=entries, inputs=sorted(inputs), contract=plan)
    _check_sealed_pins(manifest, input_pins, source_pins)
    # Fixed-width timestamps avoid accidental U/S file-size differences.
    issued = int(time.time())
    save(
        root / "authorization.json",
        make_cpu_authorization(root, issued=issued, expires=issued + 36 * 3600, history=history),
    )
    save(root / "authorization-source.json", cpu_authorization_source())
    save(
        root / "execution-binding.json",
        {
            name: sha(root / name)
            for name in ("authorization.json", "authorization-source.json", "manifest.json")
        },
    )
    digest = sha(root / "execution-binding.json")
    batch = OfflineBatch(root, digest)
    batch.initialize()
    save(root / "engineering-checks.json", engineering)
    batch.freeze_artifact(
        "engineering_checks", root / "engineering-checks.json", "ENGINEERING_CHECKS_PASS"
    )
    snapshot = batch.snapshot()
    assert snapshot["stop"] is None and len(snapshot["episodes"]) == 40
    assert all(row["status"] == "PENDING" for row in snapshot["episodes"])
    result = {
        "status": "CURRENT_CANDIDATE_FIXTURE_ONLY_NOT_ENGINEERING_OR_CALIBRATION_PASS",
        "root": str(root),
        "binding_sha256": digest,
        "mappings": mappings,
        "historical_engineering_only": True,
        "http_requests": 0,
        "model_requests": 0,
        "new_source_count": len(manifest["dependencies"]),
        "snapshot": snapshot,
    }
    save(root / "fixture-prepared.json", result)
    return result


def prepare():
    if sys.getprofile() is not None or sys.gettrace() is not None:
        raise ValueError("UNPROFILED_UNTRACED_PROCESS_REQUIRED")
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from v0223_transaction_primary_fix import installed_transaction_fix
    from v0223_tree_readonly_candidate import installed_candidate

    with installed_transaction_fix(), installed_candidate():
        return _prepare()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", required=True)
    args = parser.parse_args()
    os.environ["MILA_V0223_INSTANCE"] = args.instance
    result = prepare()
    print({key: result[key] for key in ("status", "root", "binding_sha256")})


if __name__ == "__main__":
    main()
