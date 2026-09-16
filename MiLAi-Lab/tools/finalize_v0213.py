"""Reconcile sealed inputs, complete intent scoring, trace attribution and actual costs."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from milai_lab.methods.acquisition_use import score_intent, valid_intent
from replay_v0213_cost import events, read, save, sha
from run_v0212_horizon import source_call
from v02_local_provider import accounting

LAB = Path(__file__).resolve().parents[1]


def unrun_outcome(result: dict, scored: list[dict]) -> dict:
    row = {**result, "outcome": result["status"], "attempted": False,
           "independent_observation": False, "requests": 0, "raw_tokens": 0}
    if result["status"] == "IDENTICAL_INPUT_ALIAS":
        original = next(item for item in scored if item["key"] == result["key"]
                        and item["arm"] == result["alias_of"])
        row.update(outcome=original["outcome"], intent=original.get("intent"))
    return row


def finalize(admission: Path, run: Path) -> dict:
    seal = read(admission / "seal-b.json")
    accepted = read(admission / "accepted.json")
    assert sha((admission / "accepted.json").read_bytes()) == seal["accepted_sha256"]
    aggregate = read(run / "result.json")
    recorded = {(row["key"], row["arm"]): row for row in aggregate["results"]}
    review = read(run / "evaluation-outcome-review.json")
    assert sha((admission / "seal-b.json").read_bytes()) == read(
        admission / "seal-b-sha256.json")["sha256"]
    for relative, expected in seal["implementation"].items():
        assert sha((run / "executed-source" / relative).read_bytes()) == expected
    scored, counts, total_raw, total_requests = [], {}, 0, 0
    for entry in seal["entries"]:
        key = entry["key"]
        evaluation = admission / "evaluation" / key
        contract = read(evaluation / "evaluation-contract.json")
        if "evaluation_contract_sha256" in entry:
            assert sha((evaluation / "evaluation-contract.json").read_bytes()) == (
                entry["evaluation_contract_sha256"])
        support = read(evaluation / "support-review.json")
        assert sha((evaluation / "support-review.json").read_bytes()) == (
            entry["support_review_sha256"])
        source = admission / "online" / key
        frozen = read(source / "source-index.json")
        assert all(sha((source / p).read_bytes()) == h for p, h in frozen.items())
        for arm in ("A0", "R1", "O"):
            result = recorded[key, arm]
            counter = counts.setdefault(arm, Counter({
                "attempted": 0, "responded": 0, "requests": 0, "raw_tokens": 0,
                "valid_intents": 0, "parameter_scored": 0, "acquisition_tools": 0}))
            if "accounting" not in result:
                scored.append(unrun_outcome(result, scored))
                counter[result["status"]] += 1
                continue
            directory = run / key / arm
            assert read(directory / "result.json") == result
            provider = events(directory / "provider-ledger.jsonl")
            state = accounting(provider)
            assert not state["pending"] and not state["violations"]
            assert state == result["accounting"]
            reservations = [row for row in provider if row["event"] == "RESERVED"]
            settled = {row["request_id"]: row for row in provider if row["event"] == "SETTLED"}
            presented_results = []
            for index, reservation in enumerate(reservations):
                rid = reservation["request_id"]
                path = directory / f"{rid}-request.json"
                assert sha(path.read_bytes()) == reservation["payload_sha256"]
                if index == 0:
                    assert sha(path.read_bytes()) == entry["arms"][arm]["sha256"]
                    assert reservation["prompt_tokens"] == entry["arms"][arm]["prompt_tokens"]
                assert settled[rid]["input_tokens"] == read(directory / f"{rid}-tokenize.json")[
                    "count"]
                http = json.loads(read(directory / f"{rid}-http.json")["body"])
                assert http["usage"] == settled[rid]["usage"]
                presented_results = []
                for message in read(path)["messages"]:
                    if message["role"] == "user" and message["content"].startswith("{"):
                        presented_results.extend(json.loads(message["content"]).get(
                            "tool_results", []))
            tool_events = events(directory / "tool-ledger.jsonl")
            assert presented_results == [{"name": row["tool"], "result": row["result"]}
                                         for row in tool_events[:len(presented_results)]]
            score = (score_intent(result["intent"], contract["expected_intent"],
                                  adjudicable=support["adjudicable"])
                     if result["status"] == "ANSWERED" else result["status"])
            counter.update(attempted=1, responded=int(bool(settled)), requests=state["requests"],
                           raw_tokens=state["raw_tokens"], acquisition_tools=len(tool_events))
            counter[score] += 1
            counter["valid_intents"] += int(valid_intent(result["intent"]))
            counter["parameter_scored"] += int(score in ("CORRECT", "INCORRECT"))
            scored.append({"key": key, "arm": arm, "historical_host_status": result["status"],
                           "attempted": True, "independent_observation": True,
                           "outcome": score, "intent": result["intent"],
                           "acquired_tool_calls": len(tool_events),
                           "presented_tool_calls": len(presented_results),
                           "unpresented_tool_calls": len(tool_events) - len(presented_results),
                           "trace_review": review[key][arm], "accounting": state})
            total_raw += state["raw_tokens"]
            total_requests += state["requests"]
            # Replay the Host's original query strings on the *same legal source entry*.
            # This is an evaluator-only mechanical observation, not a new online action.
            for index, tool in enumerate(tool_events):
                if tool["tool"] == "milai_memory_search":
                    queries = list(dict.fromkeys(
                        tool["arguments"][field] for field in ("query", "note_query")
                        if tool["arguments"].get(field)))
                    replayed = source_call(source, frozen, "source_search", {"queries": queries})
                    page = None
                    if replayed["hits"]:
                        first = replayed["hits"][0]
                        page = source_call(source, frozen, "source_read", {
                            "path": first["path"], "offset": first["match_byte_offset"]})
                    save(evaluation / f"same-source-query-replay-{index}.json", {
                        "label": "ZERO_GENERATION_NOT_PRESENTED_TO_MODEL",
                        "original_tool": tool["tool"], "original_arguments": tool["arguments"],
                        "source_queries": queries, "result": replayed,
                        "ordinary_read_at_first_hit": page})
    assert total_raw == aggregate["raw_tokens"] and total_requests == aggregate["requests"]
    cleanup = read(run / "product/cleanup.json")
    assert cleanup["api_stopped"] and cleanup["compose_stop_returncode"] == 0
    paired = {f"{left}_{right}": sum(
        all(any(row["key"] == entry["key"] and row["arm"] == arm
                and row["independent_observation"]
                and row["outcome"] in ("CORRECT", "INCORRECT") for row in scored)
            for arm in (left, right)) for entry in seal["entries"])
        for left, right in (("A0", "R1"), ("A0", "O"), ("R1", "O"))}
    status = "UNRESOLVED_NO_GENERATIONS" if not total_requests else "UNRESOLVED_NO_VALID_PAIRS"
    if any(paired.values()):
        status = "COMPLETED_BOUNDED_DECOMPOSITION_PROPOSE_HOST_FIX"
    elif total_requests and all(not read(admission / "evaluation" / entry["key"]
                                        / "support-review.json")["adjudicable"]
                                for entry in seal["entries"]):
        status = "COMPLETED_BOUNDED_DECOMPOSITION_KEEP_A0"
    wave = seal.get("wave", {"label": "P2", "selected": accepted["first_wave"],
                             "previously_run": []})
    report = {
        "status": status,
        "scope": "NONSTANDARD_LOCAL_ACTION_GROUNDING_DIAGNOSTIC",
        "baseline": "KEEP_0.1.15_A0_NO_STATE", "source_mode": "SOURCE_FILES_ONLY",
        "accepted_clusters": len(accepted["accepted"]),
        "attempted_clusters": len({row["key"] for row in scored if row["attempted"]}),
        "accepted_not_run": [row["key"] for row in accepted["accepted"]
                             if row["key"] not in wave["previously_run"]
                             and not any(item["key"] == row["key"] and item["attempted"]
                                         for item in scored)],
        "wave": wave,
        "counts": counts, "results": scored,
        "paired_parameter_scored": paired,
        "requests": total_requests, "raw_tokens": total_raw,
        "new_paid_calls": 0, "new_benchmark_judge_calls": 0, "business_actions_executed": 0,
        "p3": "RUN_SETTLED" if wave["label"] == "P3" else "NOT_ALLOCATED_NOT_RUN",
        "selected_followup": review["selected_followup"],
        "review_sha256": sha((run / "evaluation-outcome-review.json").read_bytes()),
        "cleanup": cleanup, "model_behavior_after_delivery_fix": (
            "NEW_TASKS_ONLY_NOT_PAIRED" if wave["label"] == "P3" else "NOT_RERUN"),
    }
    save(run / "terminal-result.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    result = finalize(args.admission, args.run)
    print(json.dumps({key: result[key] for key in ("status", "counts", "requests", "raw_tokens")},
                     indent=2))
