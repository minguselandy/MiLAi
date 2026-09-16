"""Offline actual-request/receipt audit. No model calls; no inference from a simulated ACK."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from run_v0218 import costs
from v02_local_provider import read_events
from v0218_memory import content_digest
from v0218_world import digest


def read(path: Path):
    return json.loads(path.read_text())


def audit(root: Path) -> dict:
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    assert sha(root / "manifest.json") == read(root / "manifest-sha256.json")["sha256"]
    manifest = read(root / "manifest.json")
    for name, expected in manifest["implementation"].items():
        assert sha(root / "executed-source" / Path(name).name) == expected
    for name, expected in manifest["input_files"].items():
        assert sha(root / name) == expected
    checker_spec = importlib.util.spec_from_file_location(
        "v0218_frozen_checker", root / "executed-source/v0218_checker.py"
    )
    assert checker_spec is not None and checker_spec.loader is not None
    checker = importlib.util.module_from_spec(checker_spec)
    checker_spec.loader.exec_module(checker)
    evaluate = checker.evaluate
    result = read(root / "result.json")
    assert result["cost"] == costs(root)
    assert not result["cost"]["pending"] and not result["cost"]["violations"]
    episodes = {item["id"]: item for item in manifest["episodes"]}
    rows, upstream, pids = [], {}, set()
    for outcome in result["rows"]:
        key = outcome["root"]
        episode_id = key + (
            "-A" if outcome["phase"] == "A" else f"-{outcome['variant']}-{outcome['arm']}"
        )
        item = episodes[episode_id]
        directory = root / "episodes" / episode_id
        config = read(root / "episode-configs" / (episode_id + ".json"))
        assert outcome["inherited_messages"] == 0
        assert outcome["exit_verified_before_next_episode"] and outcome["pid"] not in pids
        pids.add(outcome["pid"])
        final_world = read(directory / "final-world.json")
        assert evaluate(final_world) == outcome["business_outcome"]
        final_note = (
            read(directory / "final-public-note.json")
            if (directory / "final-public-note.json").exists()
            else None
        )
        if final_note is not None:
            assert content_digest(final_note["content"]) == final_note["content_digest"]
        if item["phase"] == "A":
            upstream[key] = {
                "note": final_note,
                "world": final_world,
                "commit": outcome["note_commit"],
            }
        expected_note = None
        if item["phase"] == "B":
            assert (
                read(root / "branch-audits" / episode_id / "initial-memory-list.json")["items"]
                == []
            )
            if item["arm"] in ("N1", "N2") and upstream[key]["note"] is not None:
                expected_note = upstream[key]["note"]
                copied = read(root / "branch-audits" / episode_id / "note-copy.json")
                assert copied["origin"] == upstream[key]["commit"]
                assert copied["destination"] == config["note_commit"]
                cold = read(directory / "cold-public-note.json")
                assert cold["content"] == expected_note["content"]
                assert cold["content_digest"] == expected_note["content_digest"]
                assert cold["memory_id"] == config["note_commit"]["memory_id"]
                assert cold["version"] == config["note_commit"]["version"]
            else:
                assert config["note_commit"] is None
                assert not (directory / "cold-public-note.json").exists()
        events = read_events(directory / "provider-ledger.jsonl")
        settled = {event["request_id"] for event in events if event["event"] == "SETTLED"}
        dispatches = read(directory / "dispatch-receipts.json")["requests"]
        new_visible, both_visible, note_visible = [], [], []
        spec = read(root / "cases" / key / "evaluation-contract.json")
        expected_current = (
            spec["public"]["current"] if item["phase"] == "A" else spec["variants"][item["variant"]]
        )
        for dispatch in dispatches:
            request_id = dispatch["request_id"]
            request_path = directory / (request_id + "-request.json")
            assert (
                hashlib.sha256(request_path.read_bytes()).hexdigest() == dispatch["payload_sha256"]
            )
            assert request_id in settled
            assert read(directory / (request_id + "-http.json"))["status_code"] == 200
            messages = read(request_path)["messages"]
            if manifest["stage"].startswith("E0_"):
                assert messages[0]["content"] == manifest["system_prompt"] + (
                    "\n" + manifest["reminder"] if item["arm"] == "N2" else ""
                )
            initial = json.loads(messages[1]["content"])
            note_in_request = initial["saved_working_note"]
            assert note_in_request == (expected_note["content"] if expected_note else None)
            current_in_request = False
            for message in messages[2:]:
                if message["role"] != "user":
                    continue
                body = json.loads(message["content"])
                source = body.get("tool_result", {})
                if source.get("resource") == "current":
                    assert digest(source["content"]) == source["content_sha256"]
                    assert source["content"] == expected_current
                    current_in_request = True
            if note_in_request is not None:
                note_visible.append(request_id)
            if current_in_request:
                new_visible.append(request_id)
            if note_in_request is not None and current_in_request:
                both_visible.append(request_id)
        rows.append(
            {
                "episode_id": episode_id,
                "root": key,
                "phase": item["phase"],
                "arm": item["arm"],
                "variant": item["variant"],
                "pid": outcome["pid"],
                "status": outcome["status"],
                "business_status": outcome["business_outcome"]["status"],
                "agent_note_writes": outcome["agent_note_writes"],
                "A_note_available": bool(upstream[key]["note"]),
                "A_business_status": evaluate(upstream[key]["world"])["status"],
                "public_cold_note_verified": expected_note is not None,
                "old_note_actual_requests": note_visible,
                "current_facts_actual_requests": new_visible,
                "both_actual_requests": both_visible,
                "memory_causal_effect_proven": False,
            }
        )
    a_rows = [row for row in rows if row["phase"] == "A"]
    b_rows = [row for row in rows if row["phase"] == "B"]
    result = {
        "status": "ACTUAL_REQUEST_CHAIN_AUDITED_NOT_FULL_TESTBED_GATE",
        "rows": rows,
        "cost": costs(root),
        "denominators": {
            "A_attempts": len(a_rows),
            "A_with_self_written_note": sum(row["agent_note_writes"] > 0 for row in a_rows),
            "A_NO_WRITE": sum(row["agent_note_writes"] == 0 for row in a_rows),
            "B_attempts": len(b_rows),
            "B_with_exact_cold_note": sum(row["public_cold_note_verified"] for row in b_rows),
            "B_with_old_note_dispatched": sum(
                bool(row["old_note_actual_requests"]) for row in b_rows
            ),
            "B_with_current_facts_dispatched": sum(
                bool(row["current_facts_actual_requests"]) for row in b_rows
            ),
            "B_with_both_dispatched": sum(bool(row["both_actual_requests"]) for row in b_rows),
            "independent_lineages_with_both_dispatched": len(
                {row["root"] for row in b_rows if row["both_actual_requests"]}
            ),
        },
        "old_note_correctness": "Requires separately disclosed nonblind semantic review; "
        "business PASS alone is not Note-content correctness",
        "G_TESTBED": "NOT_PASSED_COVERAGE_AND_SECOND_SELF_WRITTEN_CHAIN_MISSING",
        "E1": "NOT_ENTERED",
    }
    if manifest["stage"].startswith("E0_"):
        result.update(
            stage=manifest["stage"],
            G_TESTBED="PRECEDING_T5_GATE_PASSED_NOT_REJUDGED_FROM_E0_OUTCOMES",
            reminder="ACTUAL_REQUEST_N2_ONLY_VERIFIED",
        )
    output = root / "chain-audit-v1.json"
    if output.exists():
        assert read(output) == result
    else:
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    result = audit(parser.parse_args().root)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}))
