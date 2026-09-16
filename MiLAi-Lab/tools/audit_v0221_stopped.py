"""W4 audit of a service-readiness stop; no generation, capacity call or business write."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from v0213_provider import MODEL
from v0218_world import World
from v0220_action_contract import ActionContract
from v0220_evidence import LAB, read, save, seal, validate
from v0220_wire_contract import compile_contract, fingerprint
from v0221_authorization import check_authorization

BASE = Path("/cra/memory/mx_memory/evidence")


def run(source: Path, root: Path) -> dict:
    validate(source)
    stopped = read(source / "result.json")
    if stopped["status"] != "SERVICE_NOT_READY" or not (source / "stop.json").is_file():
        raise ValueError("PERSISTENT_SERVICE_STOP_REQUIRED")
    receipt = read(source / "authorization-check.json")
    auth = check_authorization(
        source, receipt["authorization_sha256"], receipt["source_sha256"], stage="W4"
    )
    frozen_goal = read(source / "goal-frozen.json")
    if hashlib.sha256(frozen_goal["text"].encode()).hexdigest() != auth["goal_sha256"]:
        raise ValueError("ORIGINAL_GOAL_NOT_PRESERVED")
    wire = BASE / "v0220-wire-fix/20260911-v1"
    wire_manifest = validate(wire)
    old = BASE / "v0220/v2-candidate1-v1"
    old_manifest = validate(old)
    selection_path = LAB / "configs/v0220-v2-selection-v1.json"
    selection = read(selection_path)
    inputs = [
        source / "authorization.json",
        source / "authorization-source.json",
        source / "authorization-check.json",
        source / "goal-frozen.json",
        source / "result.json",
        source / "stop.json",
        source / "container-gpu.json",
        source / "host-gpu.json",
        source / "models.json",
        source / "health.json",
        source / "service-diagnostic-v1/result.json",
        old / "manifest.json",
        wire / "manifest.json",
        wire / "result.json",
        wire / "inventory.json",
        selection_path,
    ]
    old_cases = BASE / "v0219/f2-wave1-v1/cases"
    for key in selection["root_order"]:
        inputs.extend(
            old_cases / key / name for name in ("public-initial.json", "independent-reference.json")
        )
    seal(
        root,
        entries=[Path(__file__), LAB / "tests/unit/test_v0221_authorization.py"],
        inputs=inputs,
        contract={
            "stage": "W4_STOPPED_SERVICE_AUDIT",
            "model_requests": 0,
            "goal_sha256": auth["goal_sha256"],
            "no_generation_admission_claim": True,
        },
    )
    roots = selection["root_order"]
    assert roots == wire_manifest["contract"]["roots"]
    selected = {}
    for key in roots:
        public = read(old_cases / key / "public-initial.json")
        reference = read(old_cases / key / "independent-reference.json")
        records = reference.get("records", reference.get("initial_records"))
        contract = ActionContract.from_public(public)
        eligible = sorted(
            target
            for target, schema in contract.write_schemas().items()
            if any(
                d["value"] is True for d in compile_contract(schema).manifest()["deferred_checks"]
            )
        )
        target = eligible[0] if eligible else selection["roots"][key]["single"]
        data = {k: copy.deepcopy(v) for k, v in records[target].items() if k != "object_id"}
        action = {
            "action": "put_record",
            "arguments": {"object_id": target, "expected_version": 0, "data": data},
        }
        contract.validate(action)
        compile_contract(contract.action_schema()).validate_output(json.dumps(action))
        save(root / "offline-selected-intents" / (key + ".json"), action)
        selected[key] = {
            "object_id": target,
            "eligible_unique_array_targets": eligible,
            "selection_rule": "Sorted object_id with deferred uniqueItems; else old single",
            "intent_sha256": fingerprint(action),
            "check": "OFFLINE_FULL_SCHEMA_ONLY_NOT_DISPATCH_OR_CAPACITY",
        }
    w2 = [
        {
            "id": f"w2-{cold}-{i + 1:02d}-{variant}",
            "root": key,
            "cold_client_pass": cold,
            "variant": variant,
            "selected_intent": selected[key] if variant == "full" else None,
            "attempted": False,
            "status": "NOT_TRIGGERED_SERVICE_NOT_READY",
        }
        for cold in (1, 2)
        for i, key in enumerate(roots)
        for variant in ("full", "finish")
    ]
    w3 = []
    for i, spec in enumerate(old_manifest["contract"]["episodes"], 1):
        world = World(old / "worlds" / (spec["id"] + ".sqlite"), spec["scope"])
        snapshot = world.snapshot()
        assert snapshot["version"] == 0 and not snapshot["records"] and not world.ledger()
        w3.append(
            {
                "id": f"v0221-v2-r1-{i:02d}",
                "root": spec["root"],
                "kind": spec["kind"],
                "cold": spec["cold"],
                "old_spec_id": spec["id"],
                "intent_sha256": fingerprint(spec["intent"]),
                "actions_sha256": fingerprint(spec["actions"]),
                "new_world": "NOT_CREATED",
                "attempted": False,
                "status": "NOT_TRIGGERED_SERVICE_NOT_READY_AND_W2_NOT_MET",
            }
        )
    assert len(w2) == 16 and len(w3) == 24
    save(root / "unrun-matrix.json", {"W2": w2, "W3": w3})
    assert not list(source.rglob("provider-ledger-v2.jsonl"))
    assert not list(source.rglob("provider-ledger.jsonl"))
    gpu = read(source / "container-gpu.json")
    driver = read(source / "service-diagnostic-v1/result.json")
    assert gpu["returncode"] == 255 and "Failed to initialize NVML" in gpu["stdout"]
    assert driver["observed"]["cuInit_error_name"] == "CUDA_ERROR_NO_DEVICE"
    models = read(source / "models.json")
    listing = json.loads(models["body"])["data"]
    assert models["status_code"] == 200
    assert len(listing) == 1 and listing[0]["id"] == MODEL and listing[0]["max_model_len"] == 65536
    assert read(source / "health.json")["status_code"] == 200
    result = {
        "status": "SERVICE_NOT_READY_BOUNDED_CHECK_COMPLETE",
        "goal_terminal_basis": "Goal section 10.2 explicit SERVICE_NOT_READY bounded non-pass path",
        "user_authorization": "PATH_B_W2_AND_CONDITIONAL_W3_RECEIVED_AND_RECORDED",
        "historical_usage_settled": False,
        "historical_usage": auth["historical"],
        "gate_status": {
            "G_AUTH": "USER_SCOPE_VALIDATED_DISPATCH_POLICY_NOT_ADMITTED",
            "G_PREFLIGHT": "NOT_MET_SERVICE_READINESS",
            "G_LIVE_COMPAT": "NOT_TRIGGERED",
            "G_KNOWN_INTENT_V0221": "NOT_TRIGGERED",
        },
        "readiness": {
            "backend_identity": "MATCH",
            "selected_parameters": "MATCH",
            "models": "MATCH_HTTP200",
            "health": "HTTP200",
            "host_gpu": "QUERY_PASS",
            "container_nvml": "FAILED_EXIT255",
            "new_process_cuda": "CUDA_ERROR_NO_DEVICE",
        },
        "attribution_limit": "GPU readiness cannot be established; no claim that a real generation "
        "failed, nor proof of existing-engine kernel failure or exact infrastructure repair cause",
        "W2": {"attempted": 0, "passed": None, "unrun": 16},
        "W3": {"attempted_chains": 0, "passed": None, "unrun_chains": 24},
        "this_batch_cost": {
            "model_requests": 0,
            "actual_raw_tokens": 0,
            "unknown_requests": 0,
            "tokenize_requests": 0,
            "judge_requests": 0,
        },
        "unimplemented_or_unexercised_after_early_stop": [
            "Full cross-process generation coordinator and Authorized WireProvider integration",
            "Complete actual wire-payload capacity and reference-output token verification",
            "New-batch CPU/reference/Mock-HTTP full gate (old validated repair not recounted)",
            "Cold W2 live worker and conditional W3 live runner; no live allocation released",
        ],
        "offline_work": "26 authorization scope tests and four selected intent full-schema checks; "
        "not full W1 regression/admission",
        "old_V2": "1 attempted/0 complete/23 unrun, all 24 Worlds still empty, unchanged",
        "Memory": "NOT_ADMITTED_NO_NEW_EVIDENCE",
        "new_tasks_or_State": False,
        "next_minimum_action": "Separately authorize service-owner diagnosis/repair; "
        "freeze a new version and execution authorization. Do not restart this batch.",
    }
    validate(source)
    validate(root)
    save(root / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.root)
