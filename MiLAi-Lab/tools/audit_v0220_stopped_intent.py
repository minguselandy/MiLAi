"""Append-only all-attempt audit of a stopped V2 candidate; never resumes generation."""

from __future__ import annotations

import argparse
from pathlib import Path

from v02_local_provider import accounting, read_events
from v0218_world import World, digest
from v0220_evidence import read, save, seal, sha, validate


def audit(source: Path, diagnostic: Path, root: Path) -> dict:
    manifest = validate(source)
    validate(diagnostic)
    result = read(source / "result.json")
    specs = manifest["contract"]["episodes"]
    assert result["attempted_chains"] == 1 and len(result["unrun"]) == 23
    assert result["status"] == "CANDIDATE_STOPPED_G_KNOWN_INTENT_NOT_MET"
    directory = source / "episodes" / specs[0]["id"]
    ledger_path = directory / "provider-ledger.jsonl"
    http_path = directory / "v2c1-01-01-http.json"
    request_path = directory / "v2c1-01-01-request.json"
    inputs = [
        source / "manifest.json",
        source / "result.json",
        diagnostic / "result.json",
        directory / "worker-result.json",
        ledger_path,
        http_path,
        request_path,
    ]
    seal(
        root,
        entries=[Path(__file__)],
        inputs=inputs,
        contract={
            "stage": "STOPPED_V2_ALL_ATTEMPT_AUDIT",
            "model_requests": 0,
            "never_settle_unknown_from_http_error": True,
            "no_retry": True,
        },
    )
    cost = accounting(read_events(ledger_path))
    assert cost["requests"] == 1 and len(cost["pending"]) == 1 and not cost["violations"]
    assert cost["pending"][0]["payload_sha256"] == sha(request_path)
    assert read(http_path)["status_code"] == 500
    assert not list(directory.glob("*-visible.txt")) and not list(directory.glob("turn-*.json"))
    worker = read(directory / "worker-result.json")
    assert worker["completed_turns"] == 0 and worker["note_writes"] == 0
    assert worker["unresolved_operations"] == []
    rows = []
    for index, spec in enumerate(specs):
        world = World(source / "worlds" / f"{spec['id']}.sqlite", spec["scope"])
        unchanged = digest(world.snapshot()) == spec["initial_state_sha256"] and not world.ledger()
        assert unchanged
        if index:
            assert not (source / "launches" / f"{spec['id']}.json").exists()
            assert not (source / "episodes" / spec["id"]).exists()
        rows.append(
            {
                "episode": spec["id"],
                "root": spec["root"],
                "kind": spec["kind"],
                "cold": spec["cold"],
                "status": "PROVIDER_HTTP500_NO_MODEL_ACTION" if not index else "UNRUN_STOP_RULE",
                "world_unchanged": unchanged,
                "business_effects": 0,
            }
        )
    final = {
        "status": "STOP_RULE_AND_NO_EFFECT_AUDIT_PASS_WITH_USAGE_UNKNOWN",
        "rows": rows,
        "V2_planned_chains": 24,
        "attempted_chains": 1,
        "unrun_chains": 23,
        "completed_chains": 0,
        "business_action_attempts": 0,
        "intent_fidelity": "N/A_NO_VISIBLE_MODEL_OUTPUT",
        "first_attempt_contract_acceptance": "N/A_ZERO_BUSINESS_ACTION_DENOMINATOR",
        "effect_fidelity": "N/A_NO_REQUESTED_BUSINESS_ACTION_DISPATCHED",
        "business_effects": 0,
        "business_commit_unknown": 0,
        "provider_usage_unknown_requests": 1,
        "unsettled_reservation_raw_upper": 28284,
        "pending_prompt_reservation": 24188,
        "pending_output_reservation": 4096,
        "unknown_request_cost": "NOT_ZERO_NOT_SETTLED",
        "second_candidate": "NOT_STARTED_UNKNOWN_USAGE_STOP_RULE",
        "gates": {
            "V1_mechanical": "PASS",
            "G_KNOWN_INTENT": "NOT_MET_PROVIDER_BOUNDARY",
            "G_RECOVERY": "NOT_TRIGGERED",
            "EXECUTION_LAYER_READY": False,
            "G_ACTION_EXECUTION": "NOT_TRIGGERED",
            "V5": "NOT_TRIGGERED",
        },
        "later_unallocated": {
            "V3_chains": 16,
            "V4_episodes": 16,
            "V5_first_episodes": 14,
            "V5_conditional_B_repeat": 12,
        },
        "root_admission": [
            {
                "root": key,
                "TASK_PROFILE_READY": "NOT_EVALUATED_NOT_ADMITTED",
                "V4_planned_episodes": 4,
                "V4_actual_episodes": 0,
            }
            for key in dict.fromkeys(s["root"] for s in specs)
        ],
        "frozen_request_manifest_sha256": sha(source / "manifest.json"),
        "model_requests_in_this_audit": 0,
        "judge_requests": 0,
    }
    assert cost["pending"][0]["raw_upper_bound"] == final["unsettled_reservation_raw_upper"]
    validate(root)
    save(root / "result.json", final)
    return final


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--diagnostic", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    audit(args.source, args.diagnostic, args.root)
