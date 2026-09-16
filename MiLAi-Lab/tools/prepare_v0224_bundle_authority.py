"""Frozen-contract authority preparation, never independent approval or admission.

The outer parent owns the complete 300-second limit including process/report exit.
This helper records phases and refuses additional phases after its local budget;
it cannot attest its own full external lifecycle or retained dynamic SQL state.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import time
from pathlib import Path

FIELDS = {
    "status",
    "roots",
    "fresh_roles",
    "verifier_files",
    "limits",
    "files",
    "expected_inherited_files",
    "allowed_extra_files",
}
LOCAL_LIMIT_NS = 300_000_000_000
EXPECTED_INHERITED_PATHS = 7113


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _mapping(value):
    import re

    _require(type(value) is dict, "EXACT_PIN_MAPPING_REQUIRED")
    for path, digest in value.items():
        _require(
            type(path) is str
            and Path(path).is_absolute()
            and str(Path(path)) == path
            and ".." not in Path(path).parts,
            "CANONICAL_PIN_PATH_REQUIRED",
        )
        _require(
            type(digest) is str and re.fullmatch("[0-9a-f]{64}", digest) is not None,
            "EXACT_SHA256_REQUIRED",
        )


def _validate_contract(contract, source_paths):
    from v0224_static_bundle import BundleLimits, _fresh_roles, _roots

    _require(
        type(contract) is dict and set(contract) == FIELDS, "EXACT_AUTHORITY_CONTRACT_REQUIRED"
    )
    _require(
        contract["status"] == "R03_AUTHORITY_PREPARATION_FROZEN",
        "FROZEN_AUTHORITY_PREPARATION_REQUIRED",
    )
    _roots(contract["roots"])
    _fresh_roles(contract["fresh_roles"])
    for field in ("files", "verifier_files", "expected_inherited_files", "allowed_extra_files"):
        _mapping(contract[field])
    inherited, extras, files = (
        contract[name] for name in ("expected_inherited_files", "allowed_extra_files", "files")
    )
    _require(len(inherited) == EXPECTED_INHERITED_PATHS, "COMPLETE_7113_INHERITED_PATHS_REQUIRED")
    _require(
        all(files.get(name) == digest for name, digest in extras.items()),
        "EXTRA_PINS_MUST_BE_EXTERNALLY_FROZEN_FILES",
    )
    _require(all(name in files for name in source_paths), "COMPLETE_PREPARER_SOURCE_PINS_REQUIRED")
    declared = dict(inherited)
    for name, digest in {**files, **extras}.items():
        _require(name not in declared or declared[name] == digest, "CONFLICTING_EXTERNAL_FILE_PINS")
        declared[name] = digest
    for name, digest in contract["verifier_files"].items():
        _require(files.get(name) == digest, "EXTERNAL_VERIFIER_FILE_PIN_REQUIRED")
    for root in contract["roots"]:
        _require(
            declared.get(root["path"]) == root["sha256"], "EXTERNALLY_PINNED_PROOF_ROOT_REQUIRED"
        )
    for name, row in contract["fresh_roles"].items():
        _require(declared.get(name) == row["sha256"], "EXTERNALLY_PINNED_FRESH_ROLE_REQUIRED")
    limits = contract["limits"]
    _require(
        type(limits) is dict
        and set(limits) == {"max_header_bytes", "max_payload_bytes", "max_paths", "max_blobs"},
        "EXACT_BUNDLE_LIMITS_REQUIRED",
    )
    return BundleLimits(**limits)


def _check_observed_coverage(observed, inherited, extras):
    _mapping(observed)
    _require(
        all(observed.get(name) == digest for name, digest in inherited.items()),
        "INHERITED_STATIC_CLOSURE_MISSING_OR_DRIFTED",
    )
    _require(
        all(name in inherited or extras.get(name) == digest for name, digest in observed.items()),
        "UNDECLARED_SEAL_OBSERVATION_OR_DRIFT",
    )


def prepare_authority(contract_path, contract_sha256):
    # No replay or provider module is imported before irreversible CPU socket denial.
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from v0220_evidence import dependencies
    from v0222_admission_read_scope import AdmissionReadScope
    from v0224_bundle_revalidation import revalidate_candidate
    from v0224_static_bundle import canonical_json, seal_static_bundle

    started = time.monotonic_ns()
    contract_path = Path(contract_path)
    _mapping({str(contract_path): contract_sha256})
    _require(contract_path.resolve() == contract_path, "CANONICAL_CONTRACT_REQUIRED")
    output = contract_path.parent / "authority-v1"
    _require(not output.exists() and not output.is_symlink(), "FRESH_AUTHORITY_OUTPUT_NO_RETRY")
    phases = []
    phase = "external_contract"
    phase_start = started
    output.mkdir()
    output_created = True

    def mark(next_phase):
        nonlocal phase, phase_start
        now = time.monotonic_ns()
        phases.append({"phase": phase, "elapsed_ns": now - phase_start, "completed": True})
        _require(
            now > started and now - started <= LOCAL_LIMIT_NS,
            "LOCAL_AUTHORITY_BUDGET_EXHAUSTED_PARENT_BOUND_STILL_REQUIRED",
        )
        phase, phase_start = next_phase, now

    try:
        with AdmissionReadScope() as scope:
            contract = scope.read_json(contract_path, contract_sha256)
            source_paths = {str(path) for path in dependencies([Path(__file__).resolve()])}
            limits = _validate_contract(contract, source_paths)
            for name, digest in contract["files"].items():
                scope.read_bytes(Path(name), digest)
            mark("original_seal")
            candidate = seal_static_bundle(
                output / "sealed",
                roots=contract["roots"],
                fresh_roles=contract["fresh_roles"],
                limits=limits,
            )
            candidate_path = output / "sealed/candidate-receipt.json"
            bundle_path = output / "sealed/static.bundle"
            observation_path = output / "sealed/seal-observation.json"
            generated = {
                str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (candidate_path, bundle_path, observation_path)
            }
            persisted_candidate = scope.read_json(candidate_path, generated[str(candidate_path)])
            _require(persisted_candidate == candidate, "PERSISTED_SEAL_CANDIDATE_DRIFT")
            observation = scope.read_json(observation_path, generated[str(observation_path)])
            _require(candidate["proof_roots"] == contract["roots"], "SEALED_PROOF_ROOTS_DRIFT")
            _require(
                candidate["bundle_sha256"] == generated[str(bundle_path)], "SEALED_PACKAGE_DRIFT"
            )
            _check_observed_coverage(
                observation["observed_files"],
                contract["expected_inherited_files"],
                contract["allowed_extra_files"],
            )
            _require(
                candidate["fresh_roles"] == contract["fresh_roles"],
                "SEALED_FRESH_CLASSIFICATION_DRIFT",
            )
            mark("mechanical_revalidation")
            mechanical = revalidate_candidate(
                output / "revalidated",
                candidate_path=candidate_path,
                candidate_sha256=generated[str(candidate_path)],
                bundle_path=bundle_path,
                bundle_sha256=generated[str(bundle_path)],
                observation_path=observation_path,
                observation_sha256=generated[str(observation_path)],
                verifier_files=contract["verifier_files"],
                limits=limits,
            )
            _require(
                mechanical["status"] == "MECHANICAL_STATIC_REVALIDATION_COMPLETE_NOT_APPROVAL",
                "MECHANICAL_REVALIDATION_NOT_COMPLETE",
            )
            mechanical_path = output / "revalidated/mechanical-revalidation.json"
            generated[str(mechanical_path)] = hashlib.sha256(
                mechanical_path.read_bytes()
            ).hexdigest()
            persisted_mechanical = scope.read_json(mechanical_path, generated[str(mechanical_path)])
            _require(persisted_mechanical == mechanical, "PERSISTED_MECHANICAL_REVALIDATION_DRIFT")
            mark("external_scope_close")
        mark("report")
        report = {
            "status": "READY_FOR_INDEPENDENT_AUTHORITY_REVIEW",
            "runtime_authorized": False,
            "pid": os.getpid(),
            "parent_pid": os.getppid(),
            "contract_path": str(contract_path),
            "contract_sha256": contract_sha256,
            "generated_files": generated,
            "phases": phases,
            "external_scope_stats": scope.stats,
            "expected_inherited_paths": len(contract["expected_inherited_files"]),
            "observed_paths": len(observation["observed_files"]),
            "elapsed_before_report_ns": time.monotonic_ns() - started,
            "complete_external_300_seconds": "PARENT_ACTUAL_TERMINAL_REQUIRED",
        }
        with (output / "authority-prepared.json").open("xb") as stream:
            stream.write(canonical_json(report))
        # Receipt write duration belongs to the parent lifecycle too, not hidden work.
        mark("return_to_parent")
        with (output / "authority-helper-terminal.json").open("xb") as stream:
            stream.write(
                canonical_json(
                    {
                        "status": "HELPER_RETURNING_NOT_EXTERNAL_EXIT",
                        "pid": os.getpid(),
                        "phases": phases,
                        "elapsed_ns": time.monotonic_ns() - started,
                    }
                )
            )
        return report
    except BaseException as primary:
        if output_created:
            try:
                with (output / "authority-failure.json").open("xb") as stream:
                    stream.write(
                        canonical_json(
                            {
                                "status": "AUTHORITY_PREPARATION_FAILED",
                                "pid": os.getpid(),
                                "parent_pid": os.getppid(),
                                "phase": phase,
                                "phases": phases,
                                "elapsed_ns": time.monotonic_ns() - started,
                                "exception_type": type(primary).__name__,
                                "reason": str(primary),
                            }
                        )
                    )
            except BaseException as secondary:
                primary.add_note("SECONDARY_AUTHORITY_FAILURE_RECORD: " + repr(secondary))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-path", type=Path, required=True)
    parser.add_argument("--contract-sha256", required=True)
    args = parser.parse_args()
    result = prepare_authority(args.contract_path, args.contract_sha256)
    print({"status": result["status"], "pid": result["pid"]})


if __name__ == "__main__":
    main()
