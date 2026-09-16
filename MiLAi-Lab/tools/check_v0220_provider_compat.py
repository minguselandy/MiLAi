"""At most two synthetic real-model requests; separate from V2 and natural tasks."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from v02_local_provider import accounting, read_events
from v0213_provider import Provider, payload
from v0220_action_contract import ActionContract, object_schema
from v0220_evidence import LAB, read, save, seal, sha, validate


def check(root: Path, evidence: Path) -> dict:
    required = {
        "v1-fault-matrix-v1": (
            "V1_TYPED_CONTRACT_FAULT_MATRIX_PASS_HOST_AND_PROVIDER_NOT_YET_ADMITTED"
        ),
        "v1-host-matrix-v1": "V1_COLD_SCRIPTED_HOST_MATRIX_PASS",
        "v1-capacity-preflight-v1": "ALL_PROSPECTIVE_INPUTS_FIT",
        "v1-nonbusiness-checker-audit-v1": "V1_NONBUSINESS_COMPLETION_NEGATIVE_AUDIT_PASS",
    }
    plan_path = LAB / "configs/v0220-execution-plan-v1.json"
    old_manifest_path = Path(read(plan_path)["old_batch"]) / "manifest.json"
    inputs = [plan_path, old_manifest_path]
    for name, expected in read(old_manifest_path)["model_assets"].items():
        path = Path(name)
        if sha(path) != expected:
            raise ValueError("MODEL_TEMPLATE_ASSET_DRIFT")
        inputs.append(path)
    for name, status in required.items():
        validate(evidence / name)
        path = evidence / name / "result.json"
        if read(path)["status"] != status:
            raise ValueError("V1_PREREQUISITE_INCOMPLETE")
        inputs.append(path)
    schemas = {
        target: object_schema(
            {
                "object_id": {"const": target},
                "text": {"type": "string"},
                "amount": {"type": "number", "minimum": 0},
                "approved": {"type": "boolean"},
                "extra": {
                    "anyOf": [
                        object_schema({"items": {"type": "array", "items": {"type": "string"}}}),
                        {"type": "null"},
                    ]
                },
            }
        )
        for target in ("left", "right")
    }
    contract = ActionContract(schemas)
    wanted = [
        {"action": "read", "arguments": {"resource": "current"}},
        {
            "action": "put_record",
            "arguments": {
                "object_id": "right",
                "expected_version": 0,
                "data": {
                    "text": '中文 English "quote"\nline\\path',
                    "amount": 12.5,
                    "approved": False,
                    "extra": {"items": ["甲", "b"]},
                },
            },
        },
    ]
    bodies = [
        payload(
            [
                {
                    "role": "system",
                    "content": "Synthetic protocol compatibility test only. "
                    "Return one JSON action matching the supplied ordinary intent "
                    "and typed public schema.",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "action_schema": contract.action_schema(),
                            "authorized_intent": action,
                            "version_domain": "WORLD",
                            "observed_world_version": 0,
                            "profile": "SYNTHETIC_PROVIDER_COMPATIBILITY_NOT_BUSINESS_TASK",
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            contract.action_schema(),
        )
        for action in wanted
    ]
    seal(
        root,
        entries=[Path(__file__), LAB / "tools/v0220_session.py"],
        inputs=inputs,
        contract={
            "stage": "PROVIDER_COMPATIBILITY",
            "generation_allocation": 2,
            "generation_cap": 2,
            "raw_token_cap": None,
            "judge_requests": 0,
            "seconds": 180,
            "no_world_effects": True,
            "stop": "First compatibility failure or unknown usage; no retry.",
            "wanted": wanted,
            "bodies": bodies,
        },
    )
    result = {"status": "INCOMPLETE", "rows": [], "scope": "SYNTHETIC_COMPATIBILITY_ONLY"}
    provider = Provider(root, deadline=time.monotonic() + 180, max_requests=2)
    try:
        provider.verify()
        for index, (body, expected) in enumerate(zip(bodies, wanted, strict=True), 1):
            validate(root)
            raw = provider.generate("v0220-compat", body)
            decoded = contract.decode(raw)
            passed = decoded == expected
            result["rows"].append(
                {
                    "index": index,
                    "intent_fidelity": passed,
                    "decoded": decoded,
                    "world_effect": False,
                }
            )
            if not passed:
                result["status"] = "COMPATIBILITY_INTENT_FAILURE"
                break
        else:
            result["status"] = "TYPED_UNION_PROVIDER_COMPATIBILITY_PASS"
    except Exception as exc:
        result.update(status="COMPATIBILITY_FAIL_CLOSED", exception_type=type(exc).__name__)
    finally:
        provider.close()
    result["cost"] = accounting(read_events(root / "provider-ledger.jsonl"))
    if result["cost"]["pending"] or result["cost"]["violations"]:
        result["status"] = "UNKNOWN_USAGE_OR_BOUND_VIOLATION_STOP"
    result.update(
        manifest_sha256=sha(root / "manifest.json"),
        judge_requests=0,
        unrun_positions=list(range(result["cost"]["requests"] + 1, 3)),
    )
    validate(root)
    save(root / "result.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    check(args.root, args.evidence)
