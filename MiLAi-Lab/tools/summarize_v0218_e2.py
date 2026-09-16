"""Terminal E2 descriptive summary; no model calls, selection or semantic Note judging."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from audit_v0218_e2 import audit
from run_v0218 import costs, sha


def read(path):
    return json.loads(path.read_text())


def summarize(root: Path) -> dict:
    audited = audit(root)
    assert audited["batch_status"] == "DISCOVERY_EXECUTED_REQUIRES_AUDIT"
    manifest = read(root / "manifest.json")
    assert audited["A_attempts"] == 2 and audited["B_attempts"] == 30
    assert audited["harness_public_prefetch_reads"] == 120
    rows = []
    for row in audited["rows"]:
        episode = root / "episodes" / row["episode_id"]
        outcome = read(episode / "result.json")
        actions = outcome["actions"]
        saves = [
            a
            for a in actions
            if a["action"]["action"] == "save_note"
            and a.get("tool_result", {}).get("status") == "PUBLIC_NOTE_COMMITTED"
        ]
        mutations = [
            a
            for a in actions
            if a.get("tool_result", {}).get("status") == ("ACTION_EXECUTED_LOCAL_WORLD")
        ]
        note_path = episode / "final-public-note.json"
        rows.append(
            {
                **row,
                "saved_note_characters": [len(a["action"]["note"]) for a in saves],
                "saved_note_turns": [a["turn"] for a in saves],
                "first_business_mutation_turn": mutations[0]["turn"] if mutations else None,
                "checkpoint_before_business": bool(
                    saves and mutations and saves[0]["turn"] < mutations[0]["turn"]
                ),
                "actual_clarification_objects": [
                    a["action"]["object_id"]
                    for a in mutations
                    if a["action"]["action"] == "request_clarification"
                ],
                "final_note_sha256": sha(note_path) if note_path.exists() else None,
                "final_reservation_reached": row["requests"] == manifest["generation_cap"],
            }
        )
    arm_stats = {}
    for arm in manifest["arms"]:
        selected = [r for r in rows if r["phase"] == "B" and r["arm"] == arm]
        arm_stats[arm] = {
            "outcomes": dict(Counter(r["business"]["status"] for r in selected)),
            "by_variant": {
                variant: dict(
                    Counter(r["business"]["status"] for r in selected if r["variant"] == variant)
                )
                for variant in manifest["variants"]
            },
            "cost": {
                field: sum(r[field] for r in selected)
                for field in ("requests", "raw_tokens", "seconds", "memory_calls")
            },
            "note_writes": sum(r["agent_note_writes"] for r in selected),
            "note_characters": sum(sum(r["saved_note_characters"]) for r in selected),
            "redundant_writes": sum(r["exact_redundant_writes"] for r in selected),
            "final_reservation_episodes": [
                r["episode_id"] for r in selected if r["final_reservation_reached"]
            ],
        }
    preceding = read(root / "e0-summary.json")["all_goal_provider_cost"]
    for item in manifest["preceding_evidence"]:
        prior_cost = costs(Path(item["path"]))
        preceding = {key: preceding[key] + prior_cost[key] for key in preceding}
    total = {key: preceding[key] + audited["cost"][key] for key in preceding}
    summary = {
        "stage": manifest["stage"],
        "status": "DESCRIPTIVE_NOT_SELECTION_OR_CAUSAL_PROOF",
        "rows": rows,
        "B_by_arm": arm_stats,
        "shared_A_cost_once": audited["shared_A_cost_once"],
        "batch_cost": audited["cost"],
        "all_goal_provider_cost": total,
        "original_lineages": 2,
        "new_independent_roots_from_repeats": 0,
        "unopened_C": 0,
        "manifest_sha256": sha(root / "manifest.json"),
        "result_sha256": sha(root / "result.json"),
        "audit_sha256": sha(root / "control-audit-v1.json"),
        "analyzer_sha256": sha(Path(__file__)),
    }
    output = root / "control-summary-v1.json"
    if output.exists():
        assert read(output) == summary
    else:
        output.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    result = summarize(parser.parse_args().root)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}))
