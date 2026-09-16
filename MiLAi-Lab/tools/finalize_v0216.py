"""Preserve offline nonblind review and compact costs without changing original labels."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

from replay_v0213_cost import read, save, sha
from v02_local_provider import read_events

LAB = Path(__file__).resolve().parents[1]


def finalize(base: Path) -> dict:
    review_path = LAB / "configs/v0216-offline-review.json"
    review = read(review_path)
    target = base / "review-v1"
    target.mkdir(mode=0o700, exist_ok=False)
    rows, batches, manifests = [], [], []
    used_reviews = set()
    for name in ("low", "high32", "fallback8"):
        root = base / f"{name}-v1-20260910"
        manifest = read(root / "manifest.json")
        manifests.append(manifest)
        report = read(root / "failure-map-v1.json")
        terminal = read(root / "result.json")
        assert report["unknown_requests"] == 0 and report["violations"] == []
        assert terminal["requests"] == report["requests"]
        assert terminal["raw_tokens"] == report["raw_tokens"]
        assert terminal["cleanup"]["api_stopped"]
        assert terminal["cleanup"]["compose_stop_returncode"] == 0
        assert read(root / "mechanical-preflight/result.json")["status"] == "PASS"
        batch_rows = []
        for row in report["rows"]:
            assert row["status"] == "DELIVERED"
            directory = root / row["evidence_directory"]
            row_id = f"{name}/{row['key']}/{row['arm']}/{row['phase']}"
            row["row_id"] = row_id
            annotation = review["failures"].get(row_id)
            if row["decision_correct"]:
                assert annotation is None and all(row["final_presented_support"])
                row.update(outcome="SUPPORTED_CORRECT_DELIVERY",
                    earliest_layer="NO_TASK_SUPPORT_FAILURE", pattern="SUCCESS",
                    first_error_event=None)
            else:
                assert annotation and row["final"]["decision"] == "INSUFFICIENT_EVIDENCE"
                assert not all(row["final_presented_support"])
                events = read_events(directory / "actions.jsonl")
                first = next(x for x in events if x["request_id"] == annotation["first_event"])
                row.update(outcome="UNJUSTIFIED_GLOBAL_ABSENCE_ABSTENTION",
                    earliest_layer=annotation["layer"], pattern=annotation["pattern"],
                    first_error_event=first, review_detail=annotation["detail"])
                used_reviews.add(row_id)
            row["earliest_layer_review"] = "REVIEWED_NONBLIND_NO_JUDGE"
            row["evidence_root"] = str(root)
            row["evidence_links"] = {item: str(directory / item) for item in (
                "actions.jsonl", "tool-results.jsonl", "cold-resume.json",
                "provider-ledger.jsonl", "transport-presentation.json")}
            cost = row["accounting"]["sessions"].values()
            row["input_tokens"] = sum(x["input_tokens"] for x in cost)
            row["output_tokens"] = sum(x["output_tokens"] for x in cost)
            row["search_bytes_scanned"] = sum(x["result"].get("bytes_scanned", 0)
                for x in read_events(directory / "tool-results.jsonl"))
            row["host_cpu_seconds"] = read(directory / "result.json")["host_cpu_seconds"]
            row["final_reserved_slot_used"] = row["accounting"]["requests"] == 8
            assert row["state_writes"] == 0 and row["restored_note"] is None
            row["memory_use_result"] = "NOT_EXERCISED_MODEL_CHOSE_NO_NOTES"
            batch_rows.append(row)
            rows.append(row)
        batches.append({"name": name, "arms": report["arms"],
            "requests": report["requests"], "raw_tokens": report["raw_tokens"],
            "seconds": terminal["seconds"],
            "pressure": manifest["config"]["pressure"],
            "manifest_sha256": sha((root / "manifest.json").read_bytes()),
            "map_sha256": sha((root / "failure-map-v1.json").read_bytes()),
            "root": str(root), "pids": [row["pid"] for row in batch_rows]})
    assert used_reviews == set(review["failures"])
    for manifest in manifests[1:]:
        for field in ("implementation", "baseline_system_sha256", "model_assets",
                      "host_acquisition", "goal_sha256"):
            assert manifest[field] == manifests[0][field], field
        for field in ("max_generations_per_phase", "max_source_reads_per_phase",
                      "max_searches_per_phase", "context_tokens", "output_reservation",
                      "final_delivery_reserve", "seconds_per_phase", "source_parallelism"):
            assert manifest["config"][field] == manifests[0]["config"][field], field
    total = {field: sum(row[field] for row in rows) for field in (
        "input_tokens", "output_tokens", "source_reads", "searches", "source_bytes_received",
        "search_bytes_scanned", "state_writes", "public_calls", "seconds", "host_cpu_seconds")}
    total.update(requests=sum(x["requests"] for x in batches),
        raw_tokens=sum(x["raw_tokens"] for x in batches),
        attempted=len(rows), delivered=len(rows), scorable=len(rows),
        supported_correct=sum(row["decision_correct"] for row in rows),
        earliest_layers=dict(Counter(row["earliest_layer"] for row in rows)),
        independent_roots=2, owned_preflight_public_calls=15,
        pending_requests=0, raw_cap=None, model_selected_notes=0)
    assert total["requests"] <= 192
    assert total["input_tokens"] + total["output_tokens"] == total["raw_tokens"]
    goal_path = LAB / manifests[0]["config"]["goal_document"]
    assert sha(goal_path.read_bytes()) == manifests[0]["goal_sha256"]
    shutil.copyfile(goal_path, target / "goal-as-executed-v0.1.md")
    save(target / "review-input.json", review)
    save(target / "reviewed-rows.json", rows)
    compact = {"status": "FAILURE_MAP_RECORDED_KEEP_SIMPLE_NO_MEMORY_CAUSAL_CLAIM",
        "totals": total, "batches": batches, "baseline_identity": {
            field: manifests[0][field] for field in ("implementation", "baseline_system_sha256",
                "model_assets", "host_acquisition", "goal_sha256")},
        "review_sha256": sha(review_path.read_bytes()),
        "reviewed_rows_sha256": sha((target / "reviewed-rows.json").read_bytes()),
        "mechanism_development": False, "paid_requests": 0, "judge_requests": 0,
        "attribution_limit": review["common_limit"]}
    save(target / "summary.json", compact)
    return compact


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    args = parser.parse_args()
    result = finalize(args.base)
    print(json.dumps(result["totals"]))
