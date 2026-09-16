"""Offline discovery observations, actual request reconciliation and explicit denominators."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from replay_v0213_cost import read, save, sha
from v02_local_provider import accounting, read_events


def summarize(root: Path) -> dict:
    manifest = read(root / "manifest.json")
    cfg = manifest["config"]
    rows, violations = [], []
    previous_sources = {}
    for key in cfg["tasks"]:
        for phase in cfg["phases"]:
            for arm in cfg["arms"]:
                directory = root / "runs" / key / arm / f"phase-{phase}"
                if not (directory / "result.json").exists():
                    rows.append({"key": key, "phase": phase, "arm": arm, "status": "NOT_RUN"})
                    continue
                row = read(directory / "result.json")
                contract = read(root / "cases" / key / "evaluation" / f"phase-{phase}.json")
                ledger = read_events(directory / "provider-ledger.jsonl")
                cost = accounting(ledger)
                if cost != row["accounting"]:
                    violations.append(f"COST_MISMATCH:{key}/{arm}/{phase}")
                settlements = {item["request_id"]: item for item in ledger
                               if item["event"] == "SETTLED"}
                seen = set()
                for event in ledger:
                    if event["event"] != "RESERVED":
                        continue
                    rid = event["request_id"]
                    path = directory / f"{rid}-request.json"
                    assert sha(path.read_bytes()) == event["payload_sha256"]
                    response_path = directory / f"{rid}-http.json"
                    if not response_path.exists():
                        continue
                    response = read(response_path)
                    if rid in settlements:
                        value = json.loads(response["body"])
                        assert value["usage"] == settlements[rid]["usage"]
                        assert read(directory / f"{rid}-tokenize.json")["count"] == settlements[
                            rid]["input_tokens"]
                    for message in read(path)["messages"]:
                        if message["role"] == "user":
                            for page in json.loads(message["content"]).get("source_pages", []):
                                if page["text"]:
                                    seen.add((page["source_id"], page["version"]))
                acquisitions = read(directory / "acquisition-calls.json")
                pairs = [(item["page"]["source_id"], item["page"]["version"])
                         for item in acquisitions if item["page"]["text"]]
                old = previous_sources.setdefault((key, arm), set())
                repeated = sum(pair in old for pair in pairs)
                old.update(pairs)
                public = read_events(directory / "public-calls.jsonl")
                actions = read_events(directory / "actions.jsonl")
                final = row["final"]
                decision_correct = (row["status"] == "DELIVERED" and
                    final["decision"] == contract["expected_decision"])
                rows.append({"key": key, "arm": arm, "phase": phase, "status": row["status"],
                    "pid": row["pid"], "decision_correct": decision_correct,
                    "final": final, "expected_decision": contract["expected_decision"],
                    "source_reads": row["source_reads"], "searches": row["searches"],
                    "acquired_source_order": [pair[0] for pair in pairs],
                    "presented_source_versions": sorted(seen),
                    "reread_unchanged_source_versions": repeated,
                    "source_bytes_received": sum(item["acquired_bytes"] for item in acquisitions),
                    "exogenous_reopen_opportunity": contract["exogenous_reopen_opportunity"],
                    "stable_negative_control": contract["stable_negative_control"],
                    "current_target_source_presented": any(pair[0] == contract[
                        "required_current_source"] for pair in seen),
                    "state_writes": row["state_writes"],
                    "note_bytes_requested": sum(len(item["action"]["note"].encode())
                        for item in actions), "public_calls": len(public),
                    "initial_seed_writes": row["initial_seed_writes"],
                    "accounting": cost, "seconds": row["seconds"],
                    "semantic_review": "SEPARATE_OFFLINE_RESEARCHER_REVIEW_NOT_BLIND"})
    arms = {}
    for arm in cfg["arms"]:
        selected = [row for row in rows if row["arm"] == arm]
        attempted = [row for row in selected if row["status"] != "NOT_RUN"]
        arms[arm] = {"allocated": len(selected), "attempted": len(attempted),
            "delivered": sum(row["status"] == "DELIVERED" for row in attempted),
            "decision_correct": sum(row["decision_correct"] for row in attempted),
            **{field: sum(row[field] for row in attempted) for field in (
                "source_reads", "searches", "state_writes", "initial_seed_writes",
                "public_calls", "reread_unchanged_source_versions")},
            "requests": sum(row["accounting"]["requests"] for row in attempted),
            "raw_tokens": sum(row["accounting"]["raw_tokens"] for row in attempted)}
    return {"status": "DISCOVERY_OBSERVATIONS_NOT_CONFIRMATION", "rows": rows, "arms": arms,
        "requests": sum(row["requests"] for row in arms.values()),
        "raw_tokens": sum(row["raw_tokens"] for row in arms.values()),
        "unknown_requests": sum(len(row.get("accounting", {}).get("pending", [])) for row in rows),
        "violations": violations, "statuses": dict(Counter(row["status"] for row in rows)),
        "measurement_version": "OBSERVATION_V1_POST_HOC_EXPLORATORY_READ_REPETITION",
        "pre_run_metric": "Exact decision label; explanations/citations separately reviewed",
        "repeat_metric_limit": "Rereading unchanged data is not automatically unnecessary work; "
            "same version does not establish that a saved claim is correct or sufficient.",
        "reopen_metric_limit": "Reading the changed status source is an observable proxy, not "
            "evidence that an internally parked cognitive branch was reactivated.",
        "contamination_rate": "N/A_UNTIL_CLAIM_LEVEL_SEMANTIC_REVIEW"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    target = args.root / "observations-v1.json"
    if target.exists():
        raise ValueError("PRESERVE_PREVIOUS_EVALUATION_USE_NEW_VERSION")
    report = summarize(args.root)
    save(target, report)
    print(json.dumps({k: report[k] for k in (
        "status", "requests", "raw_tokens", "unknown_requests", "statuses", "arms")}))
