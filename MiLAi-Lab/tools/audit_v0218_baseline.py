"""All-attempt E0 state/action/cost audit; descriptive trajectories, not causal proof."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
from collections import Counter
from pathlib import Path

from audit_v0218_chain import audit, read
from run_v0218 import sha
from v0218_world import World, digest


def audit_baseline(root: Path) -> dict:
    manifest = read(root / "manifest.json")
    assert manifest["stage"].startswith("E0_")
    archived = root / "analysis-source"
    archived.mkdir(exist_ok=True)
    for name in (Path(__file__).name, "audit_v0218_chain.py"):
        target = archived / name
        if target.exists():
            assert sha(target) == sha(Path(__file__).with_name(name))
        else:
            shutil.copyfile(Path(__file__).with_name(name), target)
    chains = audit(root)
    chain_rows = {row["episode_id"]: row for row in chains["rows"]}
    result = read(root / "result.json")
    loader = importlib.util.spec_from_file_location(
        "baseline_frozen_checker", root / "executed-source/v0218_checker.py"
    )
    assert loader is not None and loader.loader is not None
    checker = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(checker)
    upstream, rows = {}, []
    for outcome in result["rows"]:
        key, phase, arm, variant = (outcome[k] for k in ("root", "phase", "arm", "variant"))
        episode_id = key + ("-A" if phase == "A" else f"-{variant}-{arm}")
        config = read(root / "episode-configs" / f"{episode_id}.json")
        world = World(Path(config["world"]), config["world_scope"])
        ledger = world.ledger()
        final = world.snapshot()
        assert digest(final) == outcome["final_world_sha256"]
        spec = read(root / "cases" / key / "evaluation-contract.json")
        if phase == "A":
            before = World(root / "cases" / key / "initial.sqlite", key).snapshot()
            upstream[key] = {"state": final, "outcome": outcome}
        else:
            publication = [x for x in ledger if x.get("kind") == "external_event"]
            assert len(publication) == 1 and publication[0]["event_id"] == "predefined-B"
            before = publication[0]["snapshot"]
            common = upstream[key]["state"]
            assert before["records"] == common["records"] and before["pending"] == common["pending"]
            assert before["history"][:-2] == common["history"]
            assert before["history"][-2] == {
                "kind": "prior_public_record",
                "content": common["current"],
            }
            assert before["current"] == spec["variants"][variant]
            assert before["task"] == spec["task_B"] and before["version"] == common["version"] + 1
        initial_check = checker.evaluate(before)
        mutations = {
            item["request"]["operation_id"]: item
            for item in ledger
            if "request" in item and item["request"]["scope"] == config["world_scope"]
        }
        state = before
        first_target_correct = None
        first_full_valid = -1 if initial_check["status"] == "PASS" else None
        redundant, trajectories, wrong_targets, opportunities, recovered = (
            0,
            [],
            set(),
            set(),
            set(),
        )
        sources = []
        for action in outcome["actions"]:
            turn, request = action["turn"], action["action"]
            current_seen = (
                action["request_id"] in chain_rows[episode_id]["current_facts_actual_requests"]
            )
            remaining = manifest["generation_cap"] - turn
            if current_seen and remaining >= 3:
                opportunities.update(wrong_targets)
            if request["action"] == "read":
                sources.append(request.get("resource"))
            operation_id = f"{episode_id}-{turn}"
            if operation_id not in mutations:
                continue
            event = mutations[operation_id]
            target = event["request"]["object_id"]
            next_state = event["snapshot"]
            check = checker.evaluate(next_state)
            if request["action"] == "put_record" and state["records"].get(target) == next_state[
                "records"
            ].get(target):
                redundant += 1
            # A complete local object is not the same as a complete multi-object task.
            # Global/cross-object errors still count against the affected object.
            target_errors = [
                error for error in check["errors"] if ":" not in error or target in error.split(":")
            ]
            if target_errors:
                wrong_targets.add(target)
            else:
                if first_target_correct is None:
                    first_target_correct = turn
                if target in opportunities:
                    recovered.add(target)
                wrong_targets.discard(target)
            if check["status"] == "PASS" and first_full_valid is None:
                first_full_valid = turn
            trajectories.append(
                {
                    "turn": turn,
                    "request_id": action["request_id"],
                    "action": request["action"],
                    "object_id": target,
                    "current_facts_actually_presented": current_seen,
                    "complete_target_errors": target_errors,
                    "full_state": check,
                    "state_sha256": digest(next_state),
                }
            )
            state = next_state
        row = {
            "episode_id": episode_id,
            "root": key,
            "phase": phase,
            "arm": arm,
            "variant": variant,
            "execution_status": outcome["status"],
            "business_status": outcome["business_outcome"]["status"],
            "initial_business_status": initial_check["status"],
            "first_complete_target_action_turn_zero_based": first_target_correct,
            "first_full_valid_state_turn_zero_based": first_full_valid,
            "first_full_valid_minus_one_means": "Valid inherited A work at episode start",
            "business_mutations": len(trajectories),
            "exact_redundant_business_writes": redundant,
            "source_reads": dict(Counter(sources)),
            "repeated_source_reads": sum(max(0, count - 1) for count in Counter(sources).values()),
            "repeated_read_necessity": "NOT_INFERRED_FROM_REPEAT_COUNT",
            "agent_note_writes": outcome["agent_note_writes"],
            "memory_calls": outcome["memory_calls"],
            "seconds": outcome["seconds"],
            "requests": outcome["accounting"]["requests"],
            "raw_tokens": outcome["accounting"]["raw_tokens"],
            "input_tokens": sum(
                x["input_tokens"] for x in outcome["accounting"]["sessions"].values()
            ),
            "output_tokens": sum(
                x["output_tokens"] for x in outcome["accounting"]["sessions"].values()
            ),
            "cold_old_note": chain_rows[episode_id]["public_cold_note_verified"],
            "both_presented": bool(chain_rows[episode_id]["both_actual_requests"]),
            "all_cause_recovery_objects_with_current_and_two_action_slots": sorted(opportunities),
            "all_cause_recovered_objects": sorted(recovered),
            "memory_induced_recovery": "NOT_PROVEN",
            "trajectories": trajectories,
        }
        rows.append(row)
    a_rows = [row for row in rows if row["phase"] == "A"]
    b_rows = [row for row in rows if row["phase"] == "B"]
    assert sum(row["requests"] for row in rows) == result["cost"]["requests"]
    assert sum(row["raw_tokens"] for row in rows) == result["cost"]["raw_tokens"]
    summary = {
        "status": "E0_ALL_ATTEMPT_ACTION_COST_AUDITED_REQUIRES_NOTE_SEMANTIC_REVIEW",
        "stage": manifest["stage"],
        "rows": rows,
        "cost": result["cost"],
        "shared_A_cost_counted_once": {
            k: sum(row[k] for row in a_rows) for k in ("requests", "raw_tokens", "seconds")
        },
        "B_cost": {k: sum(row[k] for row in b_rows) for k in ("requests", "raw_tokens", "seconds")},
        "business_statuses": dict(Counter(row["business_status"] for row in rows)),
        "chain_denominators": chains["denominators"],
        "memory_causal_effect_proven": False,
        "new_model_requests": 0,
        "analysis_source_sha256": {p.name: sha(p) for p in archived.iterdir()},
        "semantics": "Target-level first correct action from frozen checker error attribution; "
        "full-state completion separately tracked. Recovery excludes inherited A errors until "
        "a B wrong action and requires current presentation with two available action slots. "
        "This is a descriptive all-cause path, not independent cases or Note-induced recovery.",
    }
    output = root / "baseline-audit-v1.json"
    if output.exists():
        assert read(output) == summary
    else:
        output.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    result = audit_baseline(parser.parse_args().root)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}))
