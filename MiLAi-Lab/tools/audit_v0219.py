"""Audit actual full requests, public Note receipts and SQLite actions; no semantic proxy."""

from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from pathlib import Path

from run_v0219 import ARMS, costs, read, save, sha, validate
from v02_local_provider import accounting, read_events
from v0213_provider import payload
from v0218_host import SCHEMA, TOOLS, decode_action
from v0218_memory import read_note, save_note
from v0218_world import World, digest
from v0219_host import PUBLIC_PREFETCH
from v0219_record_check import evaluate


def audit_prefetch(receipt: dict, start: dict) -> list[dict]:
    assert receipt["origin"] == "HARNESS_PUBLIC_PREFETCH" and receipt["scope"] == start["scope"]
    assert receipt["world_snapshot_sha256"] == digest(start)
    assert receipt["model_calls"] == receipt["business_mutations"] == 0
    responses = [r["response"] for r in receipt["reads"]]
    assert [r["resource"] for r in responses] == PUBLIC_PREFETCH
    for r in responses:
        assert r == {
            "resource": r["resource"],
            "version": start["version"],
            "content": start[r["resource"]],
            "content_sha256": digest(start[r["resource"]]),
        }
    return [
        {
            "role": "user",
            "content": json.dumps({"origin": "HARNESS_PUBLIC_PREFETCH", "tool_result": r}),
        }
        for r in responses
    ]


class RecordedMemory:
    """Replay validation of observed calls, never make a new MCP request."""

    def __init__(self, calls: list[dict]):
        self.calls, self.index = calls, 0

    def __call__(self, name, arguments):
        row = self.calls[self.index]
        assert row["tool"] == name and row["arguments"] == arguments
        self.index += 1
        return row["response"]

    def complete(self):
        assert self.index == len(self.calls)


def expected_branch(a: dict, scope: str, changed: dict | None) -> dict:
    start = copy.deepcopy(a)
    start["scope"] = scope
    if changed is not None:
        start["history"].append({"kind": "prior_public_record", "content": start["current"]})
        start["current"] = changed
        start["version"] += 1
        start["history"].append(
            {
                "kind": "publication",
                "event_id": "source-grounded-changed",
                "request_hash": digest({"current": changed, "task": None}),
                "version": start["version"],
            }
        )
    return start


def audit_episode(
    root: Path, episode: dict, outcome: dict, manifest: dict, upstream: dict | None
) -> dict:
    eid, key = episode["id"], episode["root"]
    directory = root / "episodes" / eid
    config = read(root / "episode-configs" / (eid + ".json"))
    exited = read(root / "episode-configs" / (eid + ".exit.json"))
    assert exited == outcome["exit_receipt"] and exited["returncode"] == 0 and exited["wait_reaped"]
    assert exited["pid"] == outcome["pid"] and outcome["inherited_messages"] == 0
    assert config["generation_cap"] == manifest["generation_cap"] and config["seconds"] == 900
    assert config["policy_system"] == manifest["policy_systems"][episode["arm"]]
    start = read(root / "starts" / (eid + ".json"))
    public = read(root / "cases" / key / "public-initial.json")
    branch_calls = RecordedMemory(read(root / "branch-audits" / eid / "public-calls.json")["calls"])
    empty = branch_calls("milai_memory_list", {"selection": {"kind": "NOTE"}, "limit": 100})
    assert not empty.get("mcp_error") and empty["items"] == []
    assert empty == read(root / "branch-audits" / eid / "initial-memory-list.json")
    inherited = None
    if episode["phase"] == "A":
        assert start == {
            **public,
            "scope": config["world_scope"],
            "version": 0,
            "records": {},
            "pending": {},
            "history": [],
        }
        assert config["note_commit"] is None and "public_prefetch" not in config
    else:
        assert upstream is not None
        assert upstream["exit"]["exited_unix"] <= exited["started_unix"]
        change = (
            read(root / "cases" / key / "public-changed.json")
            if episode["variant"] == "changed"
            else None
        )
        assert start == expected_branch(upstream["world"], config["world_scope"], change)
        if episode["arm"] != "N0" and upstream["note"] is not None:
            inherited = upstream["note"]
            copied = read(root / "branch-audits" / eid / "note-copy.json")
            assert copied["origin"] == upstream["commit"] and copied["content_rewritten"] is False
            assert copied["source_A_process_exit"] == upstream["exit"]
            commit = save_note(
                branch_calls, inherited["content"], config["memory_scope"] + "-exact-copy"
            )
            assert commit == copied["destination"] == config["note_commit"]
            assert read_note(branch_calls, commit) == copied["public_readback"]
        else:
            assert config["note_commit"] is None
            assert not (root / "branch-audits" / eid / "note-copy.json").exists()
    branch_calls.complete()
    memory_path = directory / "memory-calls.json"
    memory = RecordedMemory(read(memory_path)["calls"] if memory_path.exists() else [])
    commit = config["note_commit"]
    if inherited is not None:
        cold = read_note(memory, commit)
        assert cold == read(directory / "cold-public-note.json")
        assert (
            cold["content"] == inherited["content"]
            and cold["content_digest"] == inherited["content_digest"]
        )
    else:
        assert not (directory / "cold-public-note.json").exists()
    presentation = read(directory / "initial-presentation.json")["payload"]
    assert presentation["saved_working_note"] == (inherited["content"] if inherited else None)
    assert presentation["tools"] == TOOLS and presentation["action_schema"] == SCHEMA
    assert presentation["objects"] == start["objects"]
    assert presentation["task"] == {
        "resource": "task",
        "version": start["version"],
        "content": start["task"],
        "content_sha256": digest(start["task"]),
    }
    messages = [
        {"role": "system", "content": config["policy_system"]},
        {"role": "user", "content": json.dumps(presentation)},
    ]
    prefetched = []
    if episode["phase"] == "B":
        assert config["public_prefetch"] == PUBLIC_PREFETCH
        prefetched = audit_prefetch(read(directory / "public-prefetch.json"), start)
        messages.extend(prefetched)
    else:
        assert not (directory / "public-prefetch.json").exists()
    world = World(Path(config["world"]), config["world_scope"])
    ledger = read_events(directory / "provider-ledger.jsonl")
    usage = accounting(ledger)
    assert usage == outcome["accounting"] and not usage["pending"] and not usage["violations"]
    reserved = {r["request_id"]: r for r in ledger if r["event"] == "RESERVED"}
    settled = {r["request_id"]: r for r in ledger if r["event"] == "SETTLED"}
    dispatch_path = directory / "dispatch-receipts.json"
    dispatches = read(dispatch_path)["requests"] if dispatch_path.exists() else []
    assert len(dispatches) == len(reserved) == len(settled) == len(outcome["actions"])
    mutations = {
        r["request"]["operation_id"]: r
        for r in world.ledger()
        if "request" in r and r["request"]["scope"] == config["world_scope"]
    }
    state, note_writes, used_mutations = start, 0, set()
    current_requests, trajectories = [], []
    oracle_name = (
        "oracle-changed.json" if episode["variant"] == "changed" else "oracle-initial.json"
    )
    oracle = read(root / "cases" / key / oracle_name)
    for turn, action in enumerate(outcome["actions"]):
        assert action["turn"] == turn
        dispatch = dispatches[turn]
        rid = action["request_id"]
        assert dispatch["request_id"] == rid and rid in settled
        request = directory / (rid + "-request.json")
        assert sha(request) == dispatch["payload_sha256"] == reserved[rid]["payload_sha256"]
        count = read(directory / (rid + "-tokenize.json"))["count"]
        assert type(count) is int and count == reserved[rid]["prompt_tokens"]
        schema = copy.deepcopy(SCHEMA)
        remaining = manifest["generation_cap"] - turn
        if remaining == 1:
            schema["properties"]["action"]["enum"] = ["finish"]
        body = payload(
            [
                *messages,
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "remaining_generation_opportunities": remaining,
                            "final_delivery_reservation": 1,
                            "current_world_version": state["version"],
                        }
                    ),
                },
            ],
            schema,
        )
        assert read(request) == body  # full trajectory/schema; no hidden projection allowed
        assert (
            count + body["max_tokens"] <= read(directory / "model.json")["max_model_len"] == 65536
        )
        http = read(directory / (rid + "-http.json"))
        assert http["status_code"] == 200
        response = json.loads(http["body"])
        assert response["usage"] == settled[rid]["usage"]
        raw = response["choices"][0]["message"]["content"]
        assert raw == (directory / (rid + "-visible.txt")).read_text()
        try:
            decoded = decode_action(raw)
        except (ValueError, TypeError):
            decoded = {"action": "invalid_action"}
        assert decoded == action["action"]
        for message in messages[2:]:
            if message["role"] == "user":
                source = json.loads(message["content"]).get("tool_result", {})
                if source.get("resource") == "current":
                    assert source["content"] == start["current"]
                    assert source["content_sha256"] == digest(start["current"])
                    current_requests.append(rid)
                    break
        op = f"{eid}-{turn}"
        event = mutations.get(op)
        if event:
            used_mutations.add(op)
            req = event["request"]
            assert req == {
                "operation_id": op,
                "expected_version": decoded["expected_version"],
                "action": decoded["action"],
                "object_id": decoded["object_id"],
                "data": decoded["data"],
                "scope": state["scope"],
            }
            assert req["expected_version"] == state["version"]
            after = copy.deepcopy(state)
            target = req["object_id"]
            if req["action"] == "put_record":
                after["records"][target] = {"object_id": target, **req["data"]}
                after["pending"].pop(target, None)
            else:
                assert req["action"] == "request_clarification"
                after["pending"][target] = req["data"]["question"]
            after["version"] += 1
            after["history"].append(
                {
                    "kind": "business_action",
                    "action": req["action"],
                    "object_id": target,
                    "data": req["data"],
                }
            )
            assert event["snapshot"] == after
            assert event["receipt"]["before_sha256"] == digest(state)
            assert event["receipt"]["after_sha256"] == digest(after)
            assert event["receipt"] == action["tool_result"]
            state = after
            trajectories.append(
                {
                    "turn": turn,
                    "request_id": rid,
                    "object_id": target,
                    "snapshot_sha256": digest(state),
                    "unreviewed_full_check": evaluate(state, oracle),
                    "interpretation": "Missing not-yet-written objects during normal progress "
                    "are not by themselves a behavioral failure.",
                }
            )
        elif (
            decoded["action"] == "save_note"
            and action["tool_result"].get("status") != "ACTION_REJECTED"
        ):
            commit = save_note(memory, decoded["note"], f"{eid}-note-{turn}", commit)
            note_writes += 1
            assert action["tool_result"] == {
                "status": "PUBLIC_NOTE_COMMITTED",
                "version": commit["version"],
                "content_digest": commit["content_digest"],
            }
        elif (
            decoded["action"] == "read" and action["tool_result"].get("status") != "ACTION_REJECTED"
        ):
            resource = decoded["resource"]
            assert action["tool_result"] == {
                "resource": resource,
                "version": state["version"],
                "content": state[resource],
                "content_sha256": digest(state[resource]),
            }
        elif decoded["action"] != "finish":
            assert action["tool_result"]["status"] == "ACTION_REJECTED"
        if decoded["action"] == "finish":
            assert turn == len(outcome["actions"]) - 1 and outcome["status"] == "FINISHED"
        else:
            assert action["world_snapshot_sha256"] == digest(state)
            messages.extend(
                [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": json.dumps({"tool_result": action["tool_result"]})},
                ]
            )
    assert used_mutations == set(mutations)
    assert state == world.snapshot() == read(directory / "final-world.json")
    assert digest(state) == outcome["final_world_sha256"]
    note = None
    if commit is not None and (directory / "final-public-note.json").exists():
        note = read_note(memory, commit)
        assert note == read(directory / "final-public-note.json")
    elif commit is not None:
        assert outcome["status"] == "INFRASTRUCTURE_OR_PROTOCOL_STOP"
        assert outcome.get("reason") in {"MODEL_CONTEXT_LIMIT", "WALL_CLOCK_LIMIT"}
        if episode["phase"] == "A":
            assert outcome["handoff_recovered_by_public_read_only"]
            recovery = directory / "handoff-recovery"
            receipt = read(recovery / "receipt.json")
            assert receipt["source_exit"] == exited
            assert receipt["started_unix"] >= exited["exited_unix"]
            assert receipt["harness_read_only"]
            assert receipt["generation_requests"] == receipt["note_mutations"] == 0
            recovered_calls = RecordedMemory(read(recovery / "public-calls.json")["calls"])
            note = read_note(recovered_calls, commit)
            recovered_calls.complete()
            assert receipt["commit"] == commit and receipt["note"] == note
    memory.complete()
    assert note_writes == outcome["agent_note_writes"]
    if "note_commit" in outcome:
        assert commit == outcome["note_commit"]
    assert evaluate(state, oracle) == outcome["business_unreviewed"]
    if outcome["export"].get("files"):
        for path, expected in outcome["export"]["files"].items():
            target = root / "exports" / eid / path
            assert sha(target) == expected
            assert read(target) in state["records"].values()
    business_turns = [
        a["turn"] for a in outcome["actions"] if a["action"]["action"] == "put_record"
    ]
    first_business = min(business_turns) if business_turns else None
    review_before = any(
        a["action"]["action"] == "save_note"
        and (first_business is None or a["turn"] < first_business)
        for a in outcome["actions"]
    )
    return {
        **episode,
        "pid": outcome["pid"],
        "status": outcome["status"],
        "exit": exited,
        "world": state,
        "note": note,
        "commit": commit,
        "business_unreviewed": outcome["business_unreviewed"],
        "current_requests": current_requests,
        "old_note_requests": [d["request_id"] for d in dispatches] if inherited else [],
        "both_presented": inherited is not None and bool(current_requests),
        "agent_note_writes": note_writes,
        "prefetch_sha256": digest(prefetched) if prefetched else None,
        "prefetch_reads": len(prefetched),
        "prefetch_bytes_per_request": sum(len(m["content"].encode()) for m in prefetched),
        "requests": usage["requests"],
        "raw_tokens": usage["raw_tokens"],
        "memory_calls": memory.index,
        "branch_memory_calls": branch_calls.index,
        "first_business_turn": first_business,
        "note_action_before_business": review_before,
        "trajectories": trajectories,
        "note_review_limit": "Save-before-business alone does not establish source-aware R1 "
        "semantic review; inspect actual free text.",
    }


def audit(root: Path) -> dict:
    manifest, result = validate(root), read(root / "result.json")
    assert result["cost"] == costs(root)
    assert not result["cost"]["pending"] and not result["cost"]["violations"]
    assert result["cleanup"]["api_stopped"] and result["cleanup"]["compose_stop_returncode"] == 0
    rows, upstream, pairs, pids = [], {}, {}, set()
    for episode, outcome in zip(manifest["episodes"], result["rows"], strict=False):
        assert episode["id"] == outcome["id"]
        row = audit_episode(root, episode, outcome, manifest, upstream.get(episode["root"]))
        assert row["pid"] not in pids
        pids.add(row["pid"])
        if row["phase"] == "A":
            upstream[row["root"]] = row
        else:
            key = (row["root"], row["variant"])
            assert key not in pairs or pairs[key] == row["prefetch_sha256"]
            pairs[key] = row["prefetch_sha256"]
        save(root / "audit-details-v1" / (row["id"] + ".json"), row)
        rows.append(
            {k: v for k, v in row.items() if k not in {"world", "note", "commit", "trajectories"}}
        )
    assert sum(r["requests"] for r in rows) == result["cost"]["requests"]
    assert sum(r["raw_tokens"] for r in rows) == result["cost"]["raw_tokens"]
    complete = len(rows) == len(manifest["episodes"]) and not result["not_completed"]
    summary = {
        "status": "ACTUAL_CHAIN_AUDITED_SEMANTIC_REVIEW_REQUIRED",
        "complete_wave": complete,
        "manifest_sha256": sha(root / "manifest.json"),
        "result_sha256": sha(root / "result.json"),
        "rows": rows,
        "cost": result["cost"],
        "roots_attempted": len(upstream),
        "families": sorted({r["family"] for r in manifest["roots"]}),
        "A_attempts": len(upstream),
        "A_NO_WRITE": sum(r["agent_note_writes"] == 0 for r in upstream.values()),
        "B_attempts": sum(r["phase"] == "B" for r in rows),
        "B_both_presented": sum(r["both_presented"] for r in rows),
        "harness_prefetch_reads": sum(r["prefetch_reads"] for r in rows),
        "shared_A_cost_once": {
            f: sum(r[f] for r in rows if r["phase"] == "A") for f in ("requests", "raw_tokens")
        },
        "B_by_arm_unreviewed": {
            a: dict(Counter(r["business_unreviewed"]["status"] for r in rows if r["arm"] == a))
            for a in ARMS
        },
        "F3": "Requires complete source-bound final/trajectory/Note review, earliest-layer map "
        "and G_REGIME decision.",
        "memory_causality": "Not inferred from chain presence, score or save-before-write.",
        "goal_complete": False,
    }
    save(root / "chain-audit-v1.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    result = audit(parser.parse_args().root)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}))
