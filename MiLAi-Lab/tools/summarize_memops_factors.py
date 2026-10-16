"""Reconcile first receipts and literal inputs for the closed MemOps factor slice.

Semantic judgments are supplied separately by source review, never inferred from
successful execution, a parsable response, or a lower token count.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.laya_impact import impact_payload


def receipt_totals(folder: Path) -> dict:
    totals: Counter = Counter()
    for path in (folder / "http").rglob("response.json"):
        response = read_json(path)
        relative = path.relative_to(folder / "http").parts
        kind = "embedding" if relative[0] == "embedding" else "generation"
        usage = response.get("usage") or {}
        totals[kind + "_responses"] += 1
        totals[kind + "_tokens"] += usage.get("total_tokens", 0)
        totals[kind + "_unknown"] += int("total_tokens" not in usage)
        if "edit" in relative and relative[0] == "maintenance":
            totals["writer_prompt_tokens"] += usage["prompt_tokens"]
            totals["writer_completion_tokens"] += usage["completion_tokens"]
    for path in (folder / "typed-http").rglob("response.json"):
        receipt = read_json(path)
        response = json.loads(receipt["response_text"])
        usage = response["usage"]
        totals["typed_responses"] += 1
        totals["typed_unit_questions"] += receipt["unit_count"]
        totals["typed_input_tokens"] += usage["input_tokens"]
        totals["typed_output_tokens"] += usage["output_tokens"]
        totals["typed_wall_seconds"] += receipt["latency_seconds"]
        totals["typed_truncated_responses"] += int(usage.get("truncated", False))
    return dict(totals)


def ledger_differences(folder: Path, totals: dict) -> dict:
    before = read_json(folder / "accounting-start.json")
    after = read_json(folder / "accounting-predict-end.json")
    expected = {"generation": totals.get("generation_tokens", 0)
                + totals.get("typed_input_tokens", 0) + totals.get("typed_output_tokens", 0),
                "embedding": totals.get("embedding_tokens", 0)}
    differences = {}
    for kind, tokens in expected.items():
        differences[kind + "_known_token_difference"] = (
            after[kind]["known_tokens"] - before[kind]["known_tokens"] - tokens)
        differences[kind + "_new_unknown_usage"] = (
            after[kind]["unknown_usage"] - before[kind]["unknown_usage"])
    differences["generation_request_difference"] = (
        after["generation_requests"] - before["generation_requests"]
        - totals.get("generation_responses", 0) - totals.get("typed_responses", 0))
    return differences


def reused_cost(folder: Path) -> dict:
    tokens, seconds, calls = 0, 0.0, 0
    for path in (folder / "reused-impact").rglob("selection.json"):
        reuse = read_json(path)
        origin = Path(reuse["source"])
        receipt = read_json(origin / "response.json")
        if reuse["provider"] == "laya":
            usage = json.loads(receipt["response_text"])["usage"]
            tokens += usage["input_tokens"] + usage["output_tokens"]
            seconds += receipt["latency_seconds"]
        else:
            tokens += receipt["usage"]["total_tokens"]
            index = origin.parts.index("http")
            case = Path(*origin.parts[:index])
            stage = Path(*origin.parts[index + 1:])
            seconds += read_json(case / "call-timings" / stage / "timing.json")["wall_seconds"]
        calls += 1
    return {"original_controller_tokens": tokens, "original_controller_seconds": seconds,
            "reused_calls": calls, "new_controller_calls": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    protocol = read_json(args.root / "prepared.json")
    config = protocol["config"]
    labels = {row["case"]: row for row in read_json(args.labels)["cases"]}
    locations = {**{arm: Path(path) for arm, path in config["existing_controls"].items()},
                 **{arm: args.root / arm for arm in config["dispatch_order"]}}
    arms, audit_errors = {}, []
    for arm, location in locations.items():
        totals: Counter = Counter()
        cases, role_confusion = {}, Counter()
        for case in protocol["cases"]:
            key = case["id"]
            folder = location / key
            result = read_json(folder / "result.json")
            receipt = receipt_totals(folder)
            difference = ledger_differences(folder, receipt)
            if any(difference.values()):
                audit_errors.append({"arm": arm, "case": key, "ledger": difference})
            totals.update(receipt)
            totals["wall_seconds"] += result["wall_seconds"]
            totals["closed_cases"] += 1
            totals["completed_maintenance"] += int(result["maintenance"]["status"] == "completed")
            original = read_json(Path(config["source_run"]) / key / "seed/result.json")
            same_before = {r["id"]: r["value"] for r in result["before"]} == {
                r["id"]: r["value"] for r in original["actual_state"]}
            if not same_before or not result["read_values_unchanged"]:
                audit_errors.append({"arm": arm, "case": key, "state_integrity": False})
            cases[key] = {"maintenance_status": result["maintenance"]["status"],
                          "same_actual_before": same_before,
                          "answers": len(result["answers"]),
                          "read_values_unchanged": result["read_values_unchanged"],
                          "receipts": receipt, "ledger_difference": difference,
                          "reused_controller": reused_cost(folder)}
            for request_path in (folder / "typed-http").rglob("request.json"):
                request = read_json(request_path)
                old = read_json(locations["D1"] / key
                    / "http/maintenance/update/batch-0/impact/work-0/request.json")
                expected = impact_payload(old["messages"], old["response_format"]["json_schema"][
                    "schema"])
                if {k: request[k] for k in ("state", "questions")} != expected:
                    audit_errors.append({"arm": arm, "case": key, "typed_input_changed": True})
                selection = read_json(request_path.with_name("selection.json"))
                for unit in labels[key]["labels"]:
                    if unit["label"] is None:
                        continue
                    predicted = ("direct_root" if unit["alias"] in selection["roots"] else
                                 "preserve_successor" if unit["alias"] in selection["preserve"]
                                 else "other")
                    role_confusion[unit["label"], predicted] += 1
            for name in ("http", "typed-http"):
                for request_path in (folder / name).rglob("request.json"):
                    if not request_path.with_name("response.json").exists():
                        audit_errors.append({"unclosed_request": str(request_path)})
        arms[arm] = {"totals": dict(totals), "cases": cases, "role_confusion": [
            {"gold": g, "predicted": p, "count": n} for (g, p), n in role_confusion.items()]}
        reused = [row["reused_controller"] for row in cases.values()]
        arms[arm]["standalone_warm_seconds"] = totals["wall_seconds"] + sum(
            row["original_controller_seconds"] for row in reused)
        arms[arm]["reused_controller_tokens"] = sum(
            row["original_controller_tokens"] for row in reused)
    write_json(args.output, {"status": "CLOSED_RECEIPT_AUDIT", "root": str(args.root.resolve()),
        "driver": read_json(args.root / "driver.json"), "arms": arms, "audit_errors": audit_errors,
        "semantic_review": str((args.root / "author-review-progress.json").resolve()),
        "scope": "Three exposed training families; shared actual before, single Writer draw. "
                 "No independent trajectories, blind benchmark or net-benefit claim.",
        "cost_scope": "Update plus18QA per arm. Source formation costs remain in original run; "
                      "D3/D4 standalone adds original controller work without recharging ledger.",
        "typed_encoding": {
            "http_requests": sum(a["totals"].get("typed_responses", 0) for a in arms.values()),
            "unit_questions": sum(a["totals"].get("typed_unit_questions", 0)
                                  for a in arms.values()),
            "sequence_layout": "One native encoded sequence per unit question",
            "batch_forward_count": None, "batch_forward_note": "Not instrumented by server"},
        "sha_validation": False})


if __name__ == "__main__":
    main()
