"""Assemble a reviewable K0 draft from prepared, independently inventoried roots.

It never grants timing permission: a separate independent review and explicit
final freeze are required. It reads no protected corpus or provider credentials.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def normalize_auth(auth, root):
    if auth.get("root") != str(root) or auth.get("batch_id") != root.name:
        raise ValueError("AUTH_ROOT_OR_BATCH_ID_DRIFT")
    issued, expires = auth.get("issued_unix"), auth.get("expires_unix")
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (issued, expires)):
        raise ValueError("FINITE_AUTH_CLOCK_REQUIRED")
    if expires - issued != 36 * 3600:
        raise ValueError("UNCHANGED_AUTH_WINDOW_REQUIRED")
    return {
        k: v
        for k, v in auth.items()
        if k not in {"root", "batch_id", "issued_unix", "expires_unix"}
    }


def normalize_plan(plan, instance, public_by_root, resolve):
    normalized = copy.deepcopy(plan)
    for stage, count in (("P3", 16), ("P4", 24)):
        if len(plan[stage]) != count:
            raise ValueError("COMPLETE_FROZEN_MATRIX_REQUIRED")
        for index, spec in enumerate(normalized[stage], 1):
            expected_id = f"{instance}-{stage.lower()}-{index:02d}"
            if spec["id"] != expected_id or spec["scope"] != "v0223-" + expected_id:
                raise ValueError("ONLY_EXPLICIT_MECHANICAL_ID_MAP_ALLOWED")
            if stage == "P4":
                resolved, _ = resolve(spec, public_by_root[spec["root"]])
                if resolved["initial_state_sha256"] != spec["initial_state_sha256"]:
                    raise ValueError("P4_INITIAL_HASH_NOT_PUBLIC_SOURCE_DERIVED")
                spec["initial_state_sha256"] = "<VERIFIED_SCOPE_DERIVED_HASH>"
            spec["id"] = f"<INSTANCE>-{stage.lower()}-{index:02d}"
            spec["scope"] = "v0223-" + spec["id"]
    return normalized


def validate_snapshot(snapshot, plan, binding, empty_accounting, accounting):
    if set(snapshot) != {"meta", "episodes", "events", "artifacts", "launches", "claims"}:
        raise ValueError("EXACT_SIX_INITIAL_TABLES_REQUIRED")
    if any(snapshot[name] for name in ("events", "launches", "claims")):
        raise ValueError("UNLAUNCHED_EMPTY_MEASUREMENT_SNAPSHOT_REQUIRED")
    expected = [
        {
            "id": spec["id"],
            "stage": stage,
            "ordinal": index,
            "cap": 1 if stage == "P3" else 4,
            "status": "PENDING",
            "pid": None,
            "deadline": None,
        }
        for stage in ("P3", "P4")
        for index, spec in enumerate(plan[stage])
    ]
    if canonical(snapshot["episodes"]) != canonical(expected):
        raise ValueError("EXACT_FORTY_PENDING_EPISODE_PLAN_REQUIRED")
    if snapshot["meta"] != [{"key": "binding", "value": binding}]:
        raise ValueError("UNSTOPPED_NEW_INITIAL_META_REQUIRED")
    if [row["name"] for row in snapshot["artifacts"]] != ["engineering_checks"]:
        raise ValueError("EXACT_HISTORICAL_ENGINEERING_WORKLOAD_REQUIRED")
    if canonical(accounting) != canonical(empty_accounting):
        raise ValueError("EXACT_EMPTY_CURRENT_ACCOUNTING_REQUIRED")


def normalized_scope(scope, root, normalized_controls):
    if scope["status"] != "CLOSED_VERIFIED_TWO_OBSERVATIONS":
        raise ValueError("CLOSED_TWO_OBSERVATIONS_REQUIRED")
    roles, total = {}, 0
    for row in scope["files"]:
        path = Path(row["path"])
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["sha256"] or len(raw) != row["bytes"]:
            raise ValueError("INVENTORIED_FILE_CHANGED")
        relative = path.relative_to(root).as_posix() if path.is_relative_to(root) else None
        role = "<ROOT>/" + relative if relative is not None else str(path)
        if role in roles:
            raise ValueError("DUPLICATE_SCOPE_ROLE")
        normalized_hash = (
            hashlib.sha256(canonical(normalized_controls[relative]).encode()).hexdigest()
            if relative in normalized_controls
            else row["sha256"]
        )
        roles[role] = {
            "hash": normalized_hash,
            "bytes": len(raw),
            "json_parsed": row["json_parsed"],
            "mechanically_mapped": relative in normalized_controls,
        }
        total += len(raw)
    stats = scope["stats"]
    if (
        stats["first_reads"] != len(roles)
        or stats["closing_reads"] != len(roles)
        or stats["first_bytes"] != total
        or stats["closing_bytes"] != total
    ):
        raise ValueError("SCOPE_VOLUME_COUNTERS_NOT_FILE_DERIVED")
    return {"roles": roles, "stats": stats, "total_bytes": total}


def compare_scopes(baseline, current, *, allow_mechanical_bytes):
    if baseline["roles"].keys() != current["roles"].keys():
        raise ValueError("INITIAL_FILE_ROLES_DIFFER")
    deltas = []
    for role, old in baseline["roles"].items():
        new = current["roles"][role]
        if {k: v for k, v in old.items() if k != "bytes"} != {
            k: v for k, v in new.items() if k != "bytes"
        }:
            raise ValueError("NONMECHANICAL_INITIAL_FILE_CONTENT_DRIFT")
        delta = new["bytes"] - old["bytes"]
        if delta and not (allow_mechanical_bytes and new["mechanically_mapped"]):
            raise ValueError("U_S_INITIAL_FILE_BYTES_DIFFER")
        if delta:
            deltas.append({"role": role, "bytes_delta": delta})
    total_delta = sum(row["bytes_delta"] for row in deltas)
    expected_stats = dict(baseline["stats"])
    for key in ("first_bytes", "closing_bytes"):
        expected_stats[key] += total_delta
    if current["stats"] != expected_stats:
        raise ValueError("INITIAL_SCOPE_COUNTERS_DIFFER")
    return {"file_deltas": deltas, "total_bytes_delta": total_delta}


def main():
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    from prepare_v0221_http_v2 import CASES
    from prepare_v0222_full import resolve_p4_spec
    from run_v0223_admission_pair_v2 import CALIBRATION_ORDER
    from v0220_evidence import LAB, save, sha
    from v0220_provider_hardened import usage_state
    from v0222_presentation_batch_v2 import PRESENTATION_BINDING, PRESENTATION_ROOT
    from v0223_cpu_batch_v2 import CPU_BASE

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory
    if directory.resolve() != directory:
        raise ValueError("CANONICAL_K0_DIRECTORY_REQUIRED")
    draft_path = directory / "contract-draft.json"
    contract = json.loads(draft_path.read_bytes())
    pins = {str(draft_path): sha(draft_path)}
    source_ref = contract["source_inventory"]
    if sha(Path(source_ref["path"])) != source_ref["sha256"]:
        raise ValueError("DRAFT_INPUT_INVENTORY_REFERENCE_DRIFT")
    pins[source_ref["path"]] = source_ref["sha256"]
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
    for instance, mode in (*CALIBRATION_ORDER, ("k1-prefix", "S")):
        root = CPU_BASE / ("v2-" + instance)
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
                compare_scopes(old, new, allow_mechanical_bytes=instance == "k1-prefix")
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
            {"instance": instance, "mode": mode, "root": str(root), "binding_sha256": binding}
        )
    negative_path = directory / "negative-control-plan.json"
    pins[str(negative_path)] = sha(negative_path)
    contract.update(
        status="K0_REVIEW_REQUIRED_NOT_TIMING_AUTHORIZED",
        calibration_order=positions[:6],
        prefix55=positions[6],
        files=pins,
        matched_initial_coverage=expected_coverage,
        mechanical_volume_deltas=mechanical_volume_deltas,
        normalized_authorization=expected_auth,
        normalized_plan=expected_plan,
        initial_snapshot_comparison="EXACT_PLAN_ROWS_EMPTY_CURRENT_ACCOUNTING_AND_SHARED_ARTIFACT",
        negative_control_plan={"path": str(negative_path), "sha256": sha(negative_path)},
        missing_before_freeze=[
            *contract.get("missing_before_freeze", []),
            "Assembler checks are evidence; independent review must resolve "
            "each original missing item explicitly",
            "Five/55 scope call-boundary and runtime-added-input mapping; "
            "initial two scopes do not prove it",
            "Controlled injection details for negative-control coverage gaps "
            "before respective candidate admission",
            "Independent concrete K0 review and final sealed status",
        ],
        assembly_source={
            "path": str(LAB / "tools/assemble_v0223_k0_v2.py"),
            "sha256": sha(LAB / "tools/assemble_v0223_k0_v2.py"),
        },
    )
    save(directory / "contract-for-review.json", contract)
    print({"status": contract["status"], "pinned_files": len(pins), "positions": len(positions)})


if __name__ == "__main__":
    main()
