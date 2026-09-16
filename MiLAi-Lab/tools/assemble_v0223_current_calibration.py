"""Assemble six current-candidate inventories; independent review must precede timing."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from assemble_v0223_k0_v2 import (
    canonical,
    compare_scopes,
    normalize_auth,
    normalize_plan,
    normalized_scope,
    validate_snapshot,
)


def main():
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from prepare_v0221_http_v2 import CASES
    from prepare_v0222_full import resolve_p4_spec
    from run_v0223_current_admission import CALIBRATION_ORDER
    from v0220_evidence import LAB, save, sha
    from v0220_provider_hardened import usage_state
    from v0222_presentation_batch_v2 import PRESENTATION_BINDING, PRESENTATION_ROOT
    from v0223_current_cpu_batch import CPU_BASE

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory
    if directory.resolve() != directory:
        raise ValueError("CANONICAL_K0_DIRECTORY_REQUIRED")
    draft_path = directory / "contract-draft.json"
    contract = json.loads(draft_path.read_bytes())
    pins = {str(draft_path): sha(draft_path)}
    for field in (
        "source_inventory",
        "candidate_decision",
        "normative_revision",
        "K1_cost_evidence",
        "prior_K2_review",
    ):
        reference = contract[field]
        path = Path(reference["path"])
        if not path.is_absolute() or sha(path) != reference["sha256"]:
            raise ValueError("DRAFT_EVIDENCE_REFERENCE_DRIFT: " + field)
        pins[str(path)] = reference["sha256"]
    previous_binding_path = PRESENTATION_ROOT / "execution-binding.json"
    if sha(previous_binding_path) != PRESENTATION_BINDING:
        raise ValueError("FROZEN_PUBLIC_SOURCE_BINDING_DRIFT")
    previous_binding = json.loads(previous_binding_path.read_bytes())
    previous_manifest_path = PRESENTATION_ROOT / "manifest.json"
    if sha(previous_manifest_path) != previous_binding["manifest.json"]:
        raise ValueError("FROZEN_PUBLIC_SOURCE_MANIFEST_DRIFT")
    previous = json.loads(previous_manifest_path.read_bytes())
    public_by_root = {}
    for spec in previous["contract"]["P4"]:
        path = CASES / spec["root"] / "public-initial.json"
        digest = previous["inputs"][str(path)]
        if sha(path) != digest:
            raise ValueError("FROZEN_PUBLIC_SOURCE_DRIFT")
        pins[str(path)] = digest
        public_by_root[spec["root"]] = json.loads(path.read_bytes())
    pins[str(previous_binding_path)] = PRESENTATION_BINDING
    pins[str(previous_manifest_path)] = previous_binding["manifest.json"]
    positions = []
    expected_coverage = None
    expected_auth = None
    expected_plan = None
    expected_artifact = None
    mechanical_volume_deltas = {}
    for instance, mode in CALIBRATION_ORDER:
        root = CPU_BASE / ("currentv1-" + instance)
        inventory_path = directory / (instance + "-inventory.json")
        inventory = json.loads(inventory_path.read_bytes())
        if inventory["status"] != "K0_ACTUAL_CONSTRUCTOR_AND_PREP_INVENTORY_NOT_TIMING":
            raise ValueError("ACTUAL_CLOSED_ADMISSION_INVENTORY_REQUIRED")
        if inventory["root"] != str(root):
            raise ValueError("WRONG_INVENTORIED_ROOT")
        binding = sha(root / "execution-binding.json")
        if binding != inventory["binding_sha256"]:
            raise ValueError("INVENTORY_BINDING_CHANGED")
        binding_value = json.loads((root / "execution-binding.json").read_bytes())
        if set(binding_value) != {
            "authorization.json",
            "authorization-source.json",
            "manifest.json",
        }:
            raise ValueError("EXACT_ROOT_BINDING_REQUIRED")
        local = {}
        for name, digest in binding_value.items():
            if sha(root / name) != digest:
                raise ValueError("LOCAL_BINDING_MEMBER_DRIFT")
            local[name] = json.loads((root / name).read_bytes())
        auth = normalize_auth(local["authorization.json"], root)
        plan = local["manifest.json"]["contract"]
        normalized_plan = normalize_plan(plan, root.name, public_by_root, resolve_p4_spec)
        if expected_auth is None:
            expected_auth, expected_plan = auth, normalized_plan
        elif canonical(auth) != canonical(expected_auth) or canonical(normalized_plan) != canonical(
            expected_plan
        ):
            raise ValueError("NONMECHANICAL_AUTH_OR_PLAN_DRIFT")
        normalized_manifest = {**local["manifest.json"], "contract": normalized_plan}
        controls = {
            "authorization.json": auth,
            "manifest.json": normalized_manifest,
            "execution-binding.json": {name: "<VERIFIED_LOCAL_CONTENT>" for name in binding_value},
        }
        if len(inventory["scope_rows"]) != 2:
            raise ValueError("EXACT_CONSTRUCTOR_AND_PREP_SCOPES_REQUIRED")
        for scope in inventory["scope_rows"]:
            for row in scope["files"]:
                if sha(Path(row["path"])) != row["sha256"]:
                    raise ValueError("INVENTORIED_FILE_CHANGED")
                if row["path"] in pins and pins[row["path"]] != row["sha256"]:
                    raise ValueError("CONFLICTING_K0_PIN")
                pins[row["path"]] = row["sha256"]
        coverage = [normalized_scope(row, root, controls) for row in inventory["scope_rows"]]
        if expected_coverage is None:
            expected_coverage = coverage
        else:
            mechanical_volume_deltas[instance] = [
                compare_scopes(old, new, allow_mechanical_bytes=False)
                for old, new in zip(expected_coverage, coverage, strict=True)
            ]
        snapshot = inventory["dynamic_snapshot"]
        validate_snapshot(snapshot, plan, binding, usage_state([]), inventory["accounting_state"])
        artifact = copy.deepcopy(snapshot["artifacts"][0])
        if artifact["path"] != str(root / "engineering-checks.json"):
            raise ValueError("EXACT_LOCAL_ENGINEERING_ARTIFACT_PATH_REQUIRED")
        if sha(Path(artifact["path"])) != artifact["sha256"]:
            raise ValueError("HISTORICAL_ENGINEERING_ARTIFACT_DRIFT")
        artifact["path"] = "<ROOT>/engineering-checks.json"
        if expected_artifact is None:
            expected_artifact = artifact
        elif canonical(artifact) != canonical(expected_artifact):
            raise ValueError("HISTORICAL_ENGINEERING_SQL_DEPENDENCIES_DRIFT")
        pins[str(inventory_path)] = sha(inventory_path)
        positions.append(
            {
                "instance": instance,
                "variant": "candidate",
                "mode": mode,
                "root": str(root),
                "binding_sha256": binding,
            }
        )
    negative_path = directory / "negative-control-plan.json"
    pins[str(negative_path)] = sha(negative_path)
    contract.update(
        status="CURRENT_CANDIDATE_CALIBRATION_REVIEW_REQUIRED",
        calibration_order=positions,
        files=pins,
        matched_initial_coverage=expected_coverage,
        mechanical_volume_deltas=mechanical_volume_deltas,
        normalized_authorization=expected_auth,
        normalized_plan=expected_plan,
        initial_snapshot_comparison="EXACT_PLAN_ROWS_EMPTY_CURRENT_ACCOUNTING_AND_SHARED_ARTIFACT",
        negative_control_plan={"path": str(negative_path), "sha256": sha(negative_path)},
        missing_before_freeze=[
            *contract.get("missing_before_freeze", []),
            "Six actual initial inventories and current SQL independently compared",
            "Current candidate/fix and U/S observation alias, counter and refusal evidence",
            "Exact six-child U/S,S/U,U/S parent/worker and complete lifecycle review",
            "Explicit independent current calibration freeze review and final status; "
            "engineering and K3 remain future",
        ],
        assembly_source={
            "path": str(LAB / "tools/assemble_v0223_current_calibration.py"),
            "sha256": sha(LAB / "tools/assemble_v0223_current_calibration.py"),
        },
    )
    save(directory / "contract-for-review.json", contract)
    print({"status": contract["status"], "pinned_files": len(pins), "positions": len(positions)})


if __name__ == "__main__":
    main()
