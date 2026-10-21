"""Reconcile closed Host trajectories and separate source-authored semantic reviews."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def generation_stage(event: dict[str, Any]) -> str:
    schema = event["request"].get("response_format", {}).get("json_schema", {}).get("schema", {})
    if "nodes" in schema.get("properties", {}):
        return "view_generation"
    if "choice" in schema.get("properties", {}):
        return "control_generation"
    choice = event["receipt"]["choices"][0]
    if choice["finish_reason"] == "length":
        return "host_incomplete"
    try:
        response = json.loads(choice["message"]["content"])
    except (json.JSONDecodeError, TypeError):
        return "unparsed_host_response"
    return "host_completion" if "answer" in response else "host_request"


def summarize(roots: list[Path], reviews: list[dict[str, Any]]) -> dict[str, Any]:
    reviewed = {(r["history"], r["policy"], r["request"], r.get("interface", "rich")): r
                for r in reviews}
    seen: set[tuple[str, str, str, str]] = set()
    rows, runs = [], []
    stages: dict[str, Counter[str]] = defaultdict(Counter)
    local: dict[str, Counter[str]] = defaultdict(Counter)
    compute: dict[str, Counter[str]] = defaultdict(Counter)
    for root in roots:
        driver = read_json(root / "driver.json")
        if driver["status"] == "RUNNING":
            raise ValueError("Use closed run receipts, not a partial live ledger")
        before = read_json(root / "budget-before.json")
        after = read_json(root / "budget-after.json")
        runs.append({"root": str(root), "status": driver["status"],
            "source_version": driver["source_version"], "closed": len(driver["completed"]),
            "transport": driver["transport"], "wall_seconds": driver["wall_seconds"],
            "generation": {k: after["generation"][k] - before["generation"][k]
                           for k in after["generation"]},
            "embedding": {k: after["embedding"][k] - before["embedding"][k]
                          for k in after["embedding"]},
            "generation_requests": after["generation_requests"] - before["generation_requests"]})
        for name, metrics in after.get("compute", {}).items():
            delta = {k: v - before.get("compute", {}).get(name, {}).get(k, 0)
                     for k, v in metrics.items()}
            if any(delta.values()):
                compute[name].update(delta)
        for name in ("dynamic_memory_laya", "dynamic_memory_laya_load"):
            local[name].update({k: v - before.get("compute", {}).get(name, {}).get(k, 0)
                for k, v in after.get("compute", {}).get(name, {}).items()})
        fixture = {h["id"]: h for h in read_json(root / "fixture.json")["histories"]}
        for position in driver["completed"]:
            key = (position["history"], position["policy"], position["request"],
                   position.get("interface", "rich"))
            if key in seen:
                raise ValueError("A closed position was included twice: " + str(key))
            seen.add(key)
            history = fixture[position["history"]]
            request = next(r for r in history["requests"] if r["id"] == position["request"])
            bank = (history["id"] if history.get("continuous") and not request.get("independent")
                    else "-".join((key[0], key[2])))
            profile = position.get("profile", position["policy"])
            candidates = [(p, read_json(p)) for p in (root / profile / "banks").glob(
                "*/*-result.json")]
            path, result = next((p, r) for p, r in candidates if r["bank"] == bank
                                and r["message_id"] in {key[2], "request"})
            trace = next(path.parent.glob(path.name.replace("-result.json", "-trace-*.jsonl")))
            events = [json.loads(line) for line in trace.read_text().splitlines()]
            deliveries = [e for e in events if e.get("event") == "milai_retrieve_result"]
            messages = result.get("messages", [])
            current = max((i for i, message in enumerate(messages)
                           if message.get("type") == "human"), default=-1)
            tools = [m for m in messages[current + 1:]
                     if m.get("type") == "tool" and m.get("name") == "milai_retrieve"]
            requested = [call for m in messages[current + 1:] if m.get("type") == "ai"
                         for call in m.get("tool_calls", []) if call["name"] == "milai_retrieve"]
            row_stages: dict[str, Counter[str]] = defaultdict(Counter)
            for event in events:
                if event.get("event") != "vllm_response":
                    continue
                stage = generation_stage(event)
                for target in (stages, row_stages):
                    target[stage].update(requests=1, tokens=event["usage"]["total_tokens"],
                                         http_wall_seconds=event["wall_seconds"])
            rows.append({**position, "review": reviewed[key], "result_path": str(path),
                "tool_attempts": len(requested), "tool_returns": len(tools),
                "tool_rejections": sum(t.get("status") == "error" for t in tools),
                "executed_retrievals": len(deliveries),
                "empty_returns": sum(not e["result"]["evidence"] for e in deliveries),
                "retrievals": [{"request": e["request"],
                    "path": [step["selected"] for step in e["control"]["trace"]],
                    "reason": e["result"]["termination_reason"],
                    "evidence_kinds": [v["kind"] for v in e["result"]["evidence"]],
                    "known_evidence_count": len(e["control"]["state"]["task"]["known_evidence"]),
                    "remaining_candidates": len(e["control"]["state"]["pending_candidates"]),
                    "usage": e["result"]["usage"]} for e in deliveries],
                "views": [v for e in deliveries for v in e["result"]["evidence"]
                          if v["kind"] == "query_structure"],
                "stage_costs": dict(row_stages),
                "semantic_mutation_receipts": len(result.get("memory_mutation_receipts", []))})
    tokens = sum(stage["tokens"] for stage in stages.values())
    if tokens != sum(run["generation"]["known_tokens"] for run in runs):
        raise ValueError("Stage response tokens do not reconcile with closed-run ledger deltas")
    counts = {profile: dict(Counter(row["review"]["grade"] for row in rows
                                   if row.get("profile", row["policy"]) == profile))
              for profile in sorted({row.get("profile", row["policy"]) for row in rows})}
    return {"schema": "host_intent_closed_results_v1", "runs": runs, "positions": rows,
            "grades": counts, "stages": dict(stages), "local_model": dict(local),
            "local_compute": dict(compute),
            "known_generation_tokens": tokens, "model_outcomes_rewritten": False,
            "semantic_review_kind": "author_source_review_not_independent_judgment",
            "cost_note": "Stage HTTP wall is nested inside retrieval/message wall; "
                         "do not sum twice."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--reviews", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = summarize(args.roots, read_json(args.reviews)["reviews"])
    write_json(args.output, result)
    print(json.dumps({"positions": len(result["positions"]), "grades": result["grades"],
                      "known_generation_tokens": result["known_generation_tokens"]}))


if __name__ == "__main__":
    main()
