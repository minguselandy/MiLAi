"""Prepare one R03 bundle fixture from externally pinned authority; never approve a bundle.

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

REQUIRED_TOOLS = (
    "v0224_static_bundle.py",
    "v0224_bundle_read_scope.py",
    "v0224_bundle_lineage.py",
    "v0224_bundle_cpu_batch.py",
    "v0224_bundle_revalidation.py",
    "v0224_reference_outer_bounds.py",
    "prepare_v0224_bundle_fixture.py",
    "run_v0224_bundle_reference_slice.py",
    "v0223_transaction_primary_fix.py",
    "prepare_v0224_bundle_authority.py",
    "finalize_v0224_bundle_authority.py",
    "run_v0224_bundle_preparation.py",
    "v0224_bundle_cpu_batch_v2.py",
    "prepare_v0224_bundle_fixture_v2.py",
    "run_v0224_bundle_reference_slice_v2.py",
    "run_v0224_bundle_preparation_v2.py",
    "v0224_runtime_union_batch.py",
    "prepare_v0224_runtime_union_fixture.py",
    "run_v0224_runtime_union_preparation.py",
    "v0224_runtime_admission_observation.py",
    "run_v0224_runtime_union_calibration.py",
)
REQUIRED_TESTS = (
    "test_v0224_static_bundle.py",
    "test_v0224_bundle_read_scope.py",
    "test_v0224_bundle_cpu_batch.py",
    "test_v0224_bundle_revalidation.py",
    "test_v0224_reference_outer_bounds.py",
    "test_prepare_v0224_bundle_fixture.py",
    "test_prepare_v0224_bundle_authority.py",
    "test_finalize_v0224_bundle_authority.py",
    "test_run_v0224_bundle_reference_slice.py",
    "test_run_v0224_bundle_preparation.py",
    "test_v0224_bundle_workpoint_v2.py",
    "test_run_v0224_bundle_reference_slice_v2.py",
    "test_v0224_runtime_admission_observation.py",
    "test_run_v0224_runtime_union_calibration.py",
    "test_v0224_runtime_union_workpoint.py",
)


FAILED_PREPARATION_REVIEW = Path(
    "/cra/memory/mx_memory/evidence/v0224/20260913-a-bundle-v2/"
    "independent-preparation-complete-review.json"
)
FAILED_PREPARATION_REVIEW_SHA256 = (
    "32ad1cdfedf638478c15dc356597f8183cefb79d797b43fbbcb2b5bd392de77f"
)


FAILED_REFERENCE_REVIEW = Path(
    "/cra/memory/mx_memory/evidence/v0224/20260913-a-bundle-v3/"
    "independent-first-reference-failure-review.json"
)
FAILED_REFERENCE_REVIEW_SHA256 = "44c265a11de8c1fee0d52f00c1d5b4ee18f549b29c439e7d105699898c07001b"


def _public_source_pins(plan: dict, public_inputs: dict, cases: Path) -> dict:
    paths = {str(cases / spec["root"] / "public-initial.json") for spec in plan["P4"]}
    if len(paths) != 4 or not paths <= set(public_inputs):
        raise ValueError("EXACT_FOUR_EXTERNALLY_PINNED_PUBLIC_SOURCES_REQUIRED")
    return {name: public_inputs[name] for name in sorted(paths)}


def _collect_input_pins(inputs, trusted_pins, hash_file):
    # A public/source authority hash is not rediscovered from potentially drifted bytes.
    if not set(trusted_pins) <= {str(path) for path in inputs}:
        raise ValueError("ALL_TRUSTED_INPUTS_MUST_BE_DECLARED")
    return {
        str(path): trusted_pins[str(path)] if str(path) in trusted_pins else hash_file(path)
        for path in sorted(inputs)
    }


def _required_entries(lab: Path) -> list[Path]:
    entries = [lab / "tools" / name for name in REQUIRED_TOOLS]
    entries.extend(lab / "tests/unit" / name for name in REQUIRED_TESTS)
    for path in entries:
        if not path.is_file() or path.resolve() != path:
            raise ValueError("REQUIRED_R03_SOURCE_MISSING_OR_ALIASED: " + str(path))
    return entries


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


def _check_initialized_state(snapshot: dict, events: list) -> None:
    if (
        snapshot["stop"] is not None
        or len(snapshot["episodes"]) != 40
        or any(row["status"] != "PENDING" for row in snapshot["episodes"])
        or events != []
    ):
        raise ValueError("EXACT_40_PENDING_EMPTY_EVENT_FIXTURE_REQUIRED")


def _public_inputs(scope, root: Path, binding_sha256: str) -> dict:
    """Public cases are direct inputs of the historical presentation manifest."""
    binding = scope.read_json(root / "execution-binding.json", binding_sha256)
    return scope.read_json(root / "manifest.json", binding["manifest.json"])["inputs"]


def _prepare(static_authority):
    # Install the irreversible guard before importing any replay/provider code.
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from prepare_v0221_http_v2 import CASES
    from prepare_v0222_full import resolve_p4_spec
    from v0220_evidence import LAB, dependencies, save, seal, sha
    from v0222_scoped_cpu_batch import CPU_ROOT as OLD_ROOT
    from v0222_scoped_cpu_batch import PRESENTATION_BINDING, PRESENTATION_ROOT
    from v0222_scoped_evidence import verify_manifest
    from v0224_bundle_lineage import verify_lineage_r03
    from v0224_bundle_read_scope import BundleReadScope
    from v0224_runtime_union_batch import (
        CPU_REVISION,
        INSTANCE_ORDER,
        OfflineBatch,
        StaticAuthority,
        cpu_authorization_source,
        make_cpu_authorization,
        selected_root,
    )

    root = selected_root()
    if root.name not in INSTANCE_ORDER:
        raise ValueError("ONLY_FIXED_R03_BUNDLE_FIXTURE_REQUIRED")
    if type(static_authority) is not StaticAuthority:
        raise TypeError("EXPLICIT_EXTERNAL_STATIC_AUTHORITY_REQUIRED")
    _required_entries(LAB)
    _require_fresh_root(root)
    with BundleReadScope(**static_authority.scope_arguments()) as scope:
        history = verify_lineage_r03(scope)
        binding = scope.read_json(
            OLD_ROOT / "execution-binding.json", sha(OLD_ROOT / "execution-binding.json")
        )
        original = verify_manifest(scope, OLD_ROOT, binding["manifest.json"])
        public_inputs = _public_inputs(scope, PRESENTATION_ROOT, PRESENTATION_BINDING)
        plan = copy.deepcopy(original["contract"])
        plan["coordinator_revision"] = CPU_REVISION
        plan["static_authority"] = static_authority.contract_value()
        public_pins = _public_source_pins(plan, public_inputs, CASES)
        scope.read_bytes(FAILED_PREPARATION_REVIEW, FAILED_PREPARATION_REVIEW_SHA256)
        scope.read_bytes(FAILED_REFERENCE_REVIEW, FAILED_REFERENCE_REVIEW_SHA256)
        mappings = []
        for stage in ("P3", "P4"):
            for index, spec in enumerate(plan[stage]):
                before = copy.deepcopy(spec)
                spec["id"] = f"{root.name}-{stage.lower()}-{index + 1:02d}"
                spec["scope"] = f"v0224-{root.name}-{stage.lower()}-{index + 1:02d}"
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
        inputs.update(Path(name) for name in public_pins)
        inputs.add(FAILED_PREPARATION_REVIEW)
        inputs.add(FAILED_REFERENCE_REVIEW)
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
            "/cra/memory/mx_memory/evidence/v0224/20260913-gate-a-diagnostic-v1/diagv1-d1-u1"
        )
        prior_binding = scope.read_json(
            prior_root / "execution-binding.json",
            "a72effffc756a8ee237304e3672cc35bd43e4c3a4dcb4afca1b5a284ff3577a6",
        )
        prior_manifest = verify_manifest(scope, prior_root, prior_binding["manifest.json"])
        inputs.update(Path(name) for name in prior_manifest["inputs"])
        inputs.update(Path(name) for name in prior_manifest["dependencies"])
        inputs.update(
            prior_root / "executed-source" / Path(name).relative_to(LAB)
            for name in prior_manifest["dependencies"]
        )
        inputs.add(prior_root / "manifest.json")
        inputs.add(prior_root / "execution-binding.json")
        inputs.update({static_authority.bundle_path, static_authority.receipt_path})
        entries = _required_entries(LAB)
        entries.extend(Path(name) for name in prior_manifest["dependencies"])
        entries.extend(Path(name) for name in original["dependencies"])
        # Freeze observed bytes before scope.close; seal must not bless drift.
        trusted_pins = {
            **public_pins,
            str(FAILED_PREPARATION_REVIEW): FAILED_PREPARATION_REVIEW_SHA256,
            str(FAILED_REFERENCE_REVIEW): FAILED_REFERENCE_REVIEW_SHA256,
            str(static_authority.bundle_path): static_authority.bundle_sha256,
            str(static_authority.receipt_path): static_authority.receipt_sha256,
        }
        input_pins = _collect_input_pins(inputs, trusted_pins, sha)
        source_pins = {str(path): sha(path) for path in dependencies(entries)}
        for pins in (input_pins, source_pins):
            for name, digest in pins.items():
                with scope.physical_reads():
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
    batch = OfflineBatch(root, digest, static_authority=static_authority)
    batch.initialize()
    save(root / "engineering-checks.json", engineering)
    batch.freeze_artifact(
        "engineering_checks", root / "engineering-checks.json", "ENGINEERING_CHECKS_PASS"
    )
    snapshot = batch.snapshot()
    with batch.transaction() as db:
        initial_events = batch.events(db)
    _check_initialized_state(snapshot, initial_events)
    result = {
        "status": "R03_BUNDLE_FIXTURE_ONLY_NOT_ENGINEERING_OR_GATE_A_PASS",
        "root": str(root),
        "binding_sha256": digest,
        "mappings": mappings,
        "historical_engineering_only": True,
        "http_requests": 0,
        "model_requests": 0,
        "new_source_count": len(manifest["dependencies"]),
        "snapshot": snapshot,
        "initial_events": initial_events,
        "static_authority": static_authority.contract_value(),
    }
    save(root / "fixture-prepared.json", result)
    return result


def prepare(static_authority):
    if sys.getprofile() is not None or sys.gettrace() is not None:
        raise ValueError("UNPROFILED_UNTRACED_PROCESS_REQUIRED")
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from v0223_transaction_primary_fix import installed_transaction_fix

    with installed_transaction_fix():
        return _prepare(static_authority)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--bundle-path", type=Path, required=True)
    parser.add_argument("--bundle-sha256", required=True)
    parser.add_argument("--receipt-path", type=Path, required=True)
    parser.add_argument("--receipt-sha256", required=True)
    for field in ("max-header-bytes", "max-payload-bytes", "max-paths", "max-blobs"):
        parser.add_argument("--" + field, type=int, required=True)
    args = parser.parse_args()
    # Guard precedes imports of the binding and complete replay stack.
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from v0224_runtime_union_batch import StaticAuthority
    from v0224_static_bundle import BundleLimits

    os.environ["MILA_V0224_INSTANCE"] = args.instance
    authority = StaticAuthority(
        args.bundle_path,
        args.bundle_sha256,
        args.receipt_path,
        args.receipt_sha256,
        BundleLimits(args.max_header_bytes, args.max_payload_bytes, args.max_paths, args.max_blobs),
    )
    result = prepare(authority)
    print({key: result[key] for key in ("status", "root", "binding_sha256")})


if __name__ == "__main__":
    main()
