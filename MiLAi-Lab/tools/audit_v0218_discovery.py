"""Offline E1 audit: frozen prompts, exact common A, actual HTTP bytes and world actions."""

from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter
from pathlib import Path

from run_v0218 import costs, sha
from v02_local_provider import read_events
from v0218_memory import content_digest
from v0218_world import World, digest


def read(path):
    return json.loads(path.read_text())


def audit(root: Path) -> dict:
    manifest = read(root / "manifest.json")
    assert sha(root / "manifest.json") == read(root / "manifest-sha256.json")["sha256"]
    assert manifest["stage"].startswith("E1_")
    for name, expected in manifest["input_files"].items():
        assert sha(root / name) == expected
    for name, expected in manifest["implementation"].items():
        assert sha(root / "executed-source" / Path(name).name) == expected
    assert sha(Path(__file__)) == manifest["implementation"]["tools/audit_v0218_discovery.py"]
    loader = importlib.util.spec_from_file_location(
        "discovery_frozen_checker", root / "executed-source/v0218_checker.py"
    )
    assert loader is not None and loader.loader is not None
    checker = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(checker)
    result = read(root / "result.json")
    assert result["cost"] == costs(root)
    assert not result["cost"]["pending"] and not result["cost"]["violations"]
    assert result["cleanup"]["api_stopped"] and result["cleanup"]["compose_stop_returncode"] == 0
    plan = {item["id"]: item for item in manifest["episodes"]}
    upstream, rows, pids = {}, [], set()
    for outcome in result["rows"]:
        key, phase, arm, variant = (outcome[k] for k in ("root", "phase", "arm", "variant"))
        episode_id = key + ("-A" if phase == "A" else f"-{variant}-{arm}")
        assert plan[episode_id] == {
            "id": episode_id,
            "root": key,
            "phase": phase,
            "arm": arm,
            "variant": variant,
        }
        directory = root / "episodes" / episode_id
        config = read(root / "episode-configs" / (episode_id + ".json"))
        assert config["generation_cap"] == manifest["generation_cap"]
        assert outcome["inherited_messages"] == 0 and outcome["exit_verified_before_next_episode"]
        assert outcome["pid"] not in pids
        pids.add(outcome["pid"])
        final = read(directory / "final-world.json")
        world = World(Path(config["world"]), config["world_scope"])
        assert final == world.snapshot() and digest(final) == outcome["final_world_sha256"]
        assert checker.evaluate(final) == outcome["business_outcome"]
        spec = read(root / "cases" / key / "evaluation-contract.json")
        final_note_path = directory / "final-public-note.json"
        final_note = read(final_note_path) if final_note_path.exists() else None
        if final_note:
            assert content_digest(final_note["content"]) == final_note["content_digest"]
        expected_note = None
        if phase == "A":
            assert "policy" not in config and config["note_commit"] is None
            initial = World(root / "cases" / key / "initial.sqlite", key).snapshot()
            upstream[key] = {"world": final, "note": final_note, "commit": outcome["note_commit"]}
            expected_system = manifest["system_prompt"]
        else:
            assert config["policy"] == arm
            expected_system = manifest["policy_systems"][arm]
            assert config["policy_system"] == expected_system
            events = [event for event in world.ledger() if event.get("kind") == "external_event"]
            assert len(events) == 1 and events[0]["event_id"] == "predefined-B"
            initial = events[0]["snapshot"]
            common = upstream[key]["world"]
            for field in ("records", "pending", "policy", "objects"):
                assert initial[field] == common[field]
            assert initial["history"] == [
                *common["history"],
                {"kind": "prior_public_record", "content": common["current"]},
                initial["history"][-1],
            ]
            assert initial["version"] == common["version"] + 1
            assert (
                initial["current"] == spec["variants"][variant]
                and initial["task"] == spec["task_B"]
            )
            assert (
                read(root / "branch-audits" / episode_id / "initial-memory-list.json")["items"]
                == []
            )
            if manifest["policies"][arm]["carry_note"]:
                expected_note = upstream[key]["note"]
            if expected_note:
                copied = read(root / "branch-audits" / episode_id / "note-copy.json")
                assert copied["origin"] == upstream[key]["commit"]
                assert copied["destination"] == config["note_commit"]
                cold = read(directory / "cold-public-note.json")
                for field in ("content", "content_digest"):
                    assert cold[field] == expected_note[field]
                for field in ("memory_id", "version"):
                    assert cold[field] == config["note_commit"][field]
            else:
                assert config["note_commit"] is None
                assert not (directory / "cold-public-note.json").exists()
        expected_current = spec["public"]["current"] if phase == "A" else spec["variants"][variant]
        ledger = read_events(directory / "provider-ledger.jsonl")
        settled = {event["request_id"] for event in ledger if event["event"] == "SETTLED"}
        dispatches = read(directory / "dispatch-receipts.json")["requests"]
        assert len(dispatches) == outcome["accounting"]["requests"]
        current_requests, note_requests = [], []
        for dispatch in dispatches:
            request_id = dispatch["request_id"]
            path = directory / (request_id + "-request.json")
            assert sha(path) == dispatch["payload_sha256"] and request_id in settled
            assert read(directory / (request_id + "-http.json"))["status_code"] == 200
            body = read(path)
            messages = body["messages"]
            assert messages[0]["content"] == expected_system
            presentation = json.loads(messages[1]["content"])
            assert presentation["saved_working_note"] == (
                expected_note["content"] if expected_note else None
            )
            assert presentation["task"]["content"] == initial["task"]
            assert presentation["objects"] == initial["objects"]
            if expected_note:
                note_requests.append(request_id)
            current_seen = False
            for message in messages[2:]:
                if message["role"] == "user":
                    source = json.loads(message["content"]).get("tool_result", {})
                    if source.get("resource") == "current":
                        assert source["content"] == expected_current
                        assert source["content_sha256"] == digest(expected_current)
                        current_seen = True
            if current_seen:
                current_requests.append(request_id)
        mutations = {
            event["request"]["operation_id"]: event
            for event in world.ledger()
            if "request" in event and event["request"]["scope"] == config["world_scope"]
        }
        state, trajectories = initial, []
        first_correct = None
        first_full = -1 if checker.evaluate(initial)["status"] == "PASS" else None
        redundant = 0
        wrong, opportunities, recovered = set(), set(), set()
        for action in outcome["actions"]:
            turn, request = action["turn"], action["action"]
            current_seen = action["request_id"] in current_requests
            if current_seen and manifest["generation_cap"] - turn >= 3:
                opportunities.update(wrong)
            event = mutations.get(f"{episode_id}-{turn}")
            if event is None:
                continue
            target, next_state = event["request"]["object_id"], event["snapshot"]
            check = checker.evaluate(next_state)
            errors = [
                error for error in check["errors"] if ":" not in error or target in error.split(":")
            ]
            if request["action"] == "put_record" and state["records"].get(target) == next_state[
                "records"
            ].get(target):
                redundant += 1
            if errors:
                wrong.add(target)
            else:
                if first_correct is None:
                    first_correct = turn
                if target in opportunities:
                    recovered.add(target)
                wrong.discard(target)
            if first_full is None and check["status"] == "PASS":
                first_full = turn
            trajectories.append(
                {
                    "turn": turn,
                    "request_id": action["request_id"],
                    "object_id": target,
                    "action": request["action"],
                    "target_errors": errors,
                    "full_status": check["status"],
                    "snapshot_sha256": digest(next_state),
                }
            )
            state = next_state
        rows.append(
            {
                "episode_id": episode_id,
                "root": key,
                "phase": phase,
                "arm": arm,
                "variant": variant,
                "status": outcome["status"],
                "business": outcome["business_outcome"],
                "A_note_available": upstream[key]["note"] is not None,
                "cold_note": expected_note is not None,
                "actual_old_note_requests": note_requests,
                "actual_current_requests": current_requests,
                "both_presented": bool(expected_note and current_requests),
                "agent_note_writes": outcome["agent_note_writes"],
                "requests": outcome["accounting"]["requests"],
                "raw_tokens": outcome["accounting"]["raw_tokens"],
                "seconds": outcome["seconds"],
                "memory_calls": outcome["memory_calls"],
                "source_reads": dict(
                    Counter(
                        a["action"].get("resource")
                        for a in outcome["actions"]
                        if a["action"]["action"] == "read"
                    )
                ),
                "rejections": dict(
                    Counter(
                        a["tool_result"]["reason"].split(":")[0]
                        for a in outcome["actions"]
                        if a.get("tool_result", {}).get("status") == "ACTION_REJECTED"
                    )
                ),
                "first_complete_target_turn": first_correct,
                "first_full_valid_turn": first_full,
                "exact_redundant_writes": redundant,
                "trajectories": trajectories,
                "all_cause_opportunity_objects": sorted(opportunities),
                "recovered_objects": sorted(recovered),
            }
        )
    assert sum(r["requests"] for r in rows) == result["cost"]["requests"]
    assert sum(r["raw_tokens"] for r in rows) == result["cost"]["raw_tokens"]
    if result["status"] == "DISCOVERY_EXECUTED_REQUIRES_AUDIT":
        assert len(rows) == len(plan)
    summary = {
        "status": "DISCOVERY_ALL_ATTEMPT_AUDITED_SEMANTIC_REVIEW_SEPARATE",
        "batch_status": result["status"],
        "stage": manifest["stage"],
        "rows": rows,
        "cost": result["cost"],
        "manifest_sha256": sha(root / "manifest.json"),
        "result_sha256": sha(root / "result.json"),
        "independent_roots": len(upstream),
        "A_attempts": sum(r["phase"] == "A" for r in rows),
        "B_attempts": sum(r["phase"] == "B" for r in rows),
        "A_NO_WRITE": sum(r["phase"] == "A" and not r["A_note_available"] for r in rows),
        "B_both_presented": sum(r["both_presented"] for r in rows),
        "shared_A_cost_once": {
            field: sum(r[field] for r in rows if r["phase"] == "A")
            for field in ("requests", "raw_tokens")
        },
        "B_by_arm": {
            arm: dict(Counter(r["business"]["status"] for r in rows if r["arm"] == arm))
            for arm in manifest["arms"]
        },
        "memory_causality": "Not inferred from aggregate scores or all-cause recovery",
        "whole_goal_complete": False,
    }
    output = root / "discovery-audit-v1.json"
    if output.exists():
        assert read(output) == summary
    else:
        output.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    result = audit(parser.parse_args().root)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}))
