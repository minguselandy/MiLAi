"""Read-only prior-cohort evidence and costs; writes only new audit artifacts.

No provider, Store mutation, generation, or runtime imports. Diagnostic review notes
are supplied separately; they never replace the original rubric or terminal status.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

WRITER_CUE = "Store the useful supported observations from this closed past boundary."


def read(path: Path) -> Any:
    return json.loads(path.read_text())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def audit(coverage_path: Path, notes_path: Path, output: Path, private: Path) -> dict[str, Any]:
    coverage = read(coverage_path)
    notes = read(notes_path)
    note_map = {(r["method_id"], r["case_id"]): r for r in notes["reviews"]}
    old_audit_path = Path(coverage["root_audit_path"])
    old_audit = read(old_audit_path)
    protocol_path = old_audit_path.parent / "protocol.json"
    protocol = read(protocol_path)
    if sha(old_audit_path) != coverage["root_audit_sha256"]:
        raise ValueError("Prior audit identity changed")
    inputs: dict[str, str] = {
        str(coverage_path): sha(coverage_path),
        str(old_audit_path): sha(old_audit_path),
        str(protocol_path): sha(protocol_path),
    }
    by_trajectory: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    costs: dict[str, Counter[str]] = defaultdict(Counter)
    per_method: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    private_rows = []
    call_details = []
    scanned = 0
    for original in coverage["attempts"]:
        path = Path(original["receipt_path"])
        trace_path = path.with_suffix(".jsonl")
        if sha(path) != original["receipt_sha256"]:
            raise ValueError(f"Receipt identity changed: {path}")
        if sha(trace_path) != old_audit["trace_sha256"][str(trace_path)]:
            raise ValueError(f"Trace identity changed: {trace_path}")
        inputs[str(path)] = sha(path)
        inputs[str(trace_path)] = sha(trace_path)
        receipt = read(path)
        events = [json.loads(line) for line in trace_path.read_text().splitlines()]
        key = (original["method_id"], original["case_id"])
        calls: list[dict[str, Any]] = []
        memory_outcomes = Counter()
        first_memory_rejection = None
        for ordinal, event in enumerate(events):
            if event.get("event") == "v13_p5_memory_receipt":
                result = event["receipt"]
                memory_outcomes[result.get("reason", result.get("status", "unknown"))] += 1
                if result.get("ok") is False and first_memory_rejection is None:
                    first_memory_rejection = {
                        "trace_ordinal": ordinal,
                        "reason": result.get("reason"),
                        "call_id": event["call"].get("id"),
                        "proposed_action": event["call"]["args"].get("action"),
                    }
            if event.get("event") not in {"vllm_response", "vllm_error"}:
                continue
            request = event["request"]
            messages = request.get("messages", [])
            if event["path"] == "embeddings":
                category = "embedding"
            elif any(
                m.get("role") == "user" and str(m.get("content", "")).startswith(WRITER_CUE)
                for m in messages
            ):
                category = "boundary_writer"
            elif messages and str(messages[0].get("content", "")).startswith(
                "Reply as exactly one JSON object."
            ):
                category = "host"
            else:
                category = "other_generation"
            usage = event.get("usage")
            tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
            after_rejection = False
            if messages and messages[-1].get("role") == "tool":
                try:
                    previous = json.loads(messages[-1].get("content", ""))
                except (ValueError, TypeError):
                    previous = None
                after_rejection = (
                    isinstance(previous, dict)
                    and previous.get("ok") is False
                    and messages[-1].get("name") == "manage_memory"
                )
            bucket = Counter(requests=1)
            if type(tokens) is int:
                bucket["known_tokens"] = tokens
            else:
                bucket["unknown_usage"] = 1
            costs[category].update(bucket)
            per_method[key[0]][category].update(bucket)
            if after_rejection:
                costs["following_memory_rejection"].update(bucket)
                per_method[key[0]]["following_memory_rejection"].update(bucket)
            calls.append(
                {
                    "trace_ordinal": ordinal,
                    "category": category,
                    "tokens": tokens,
                    "following_memory_rejection": after_rejection,
                    "wall_seconds": event.get("wall_seconds"),
                    "http_status": event.get("http_status"),
                }
            )
        expected_http = Counter()
        expected_tokens = Counter()
        for c in calls:
            kind = "embedding" if c["category"] == "embedding" else "generation"
            expected_http[kind] += 1
            if c["tokens"] is not None:
                expected_tokens[kind] += c["tokens"]
        if dict(expected_http) != original["http"] or dict(expected_tokens) != original["tokens"]:
            raise ValueError(f"Prior cost mismatch: {path}")
        public_input = next(e["content"] for e in events if e.get("event") == "v13_public_input")
        sources = receipt.get("sources", [])
        for source in sources:
            if hashlib.sha256(source["content"].encode()).hexdigest() != source["content_sha256"]:
                raise ValueError(f"Source content changed: {path}")
        by_trajectory[key].append(
            {
                **original,
                "calls": calls,
                "first_memory_rejection": first_memory_rejection,
                "memory_outcomes": dict(memory_outcomes),
                "source_ids": [s["event_id"] for s in sources],
                "answer_sha256": hashlib.sha256(
                    str(receipt.get("final_answer")).encode()
                ).hexdigest(),
            }
        )
        call_details.append(
            {
                "method_id": key[0],
                "case_id": key[1],
                "attempt_id": original["attempt_id"],
                "calls": calls,
            }
        )
        private_rows.append(
            {
                "method_id": key[0],
                "case_id": key[1],
                "message_index": original["message_index"],
                "attempt_id": original["attempt_id"],
                "public_input": public_input,
                "final_answer": receipt.get("final_answer"),
                "sources": sources,
                "records": receipt.get("records", []),
                "world": receipt.get("world"),
                "business_calls": receipt.get("business_calls"),
                "checkpoint": receipt.get("checkpoint"),
                "receipt_path": str(path),
                "trace_path": str(trace_path),
            }
        )
        scanned += 1
    rows = []
    for original in coverage["table"]:
        key = (original["method_id"], original["case_id"])
        attempts = sorted(
            by_trajectory[key],
            key=lambda a: (a["message_index"], 0 if a["attempt_id"].endswith("-start") else 1),
        )
        terminal = next((a for a in attempts if a.get("error") or a.get("evidence_error")), None)
        outcomes = Counter()
        total = Counter()
        for a in attempts:
            outcomes.update(a["memory_outcomes"])
            total.update(a["tokens"])
        if original["trajectory_status"] == "COMPLETE" and key not in note_map:
            raise ValueError(f"Missing complete-trajectory diagnostic review: {key}")
        compact_attempts = [{k: v for k, v in a.items() if k != "calls"} for a in attempts]
        compact_terminal = {k: v for k, v in terminal.items() if k != "calls"} if terminal else None
        rows.append(
            {
                "original": original,
                "raw_evidence_available": bool(attempts),
                "attempts": compact_attempts,
                "first_terminal_error": compact_terminal,
                "memory_tool_outcomes": dict(outcomes),
                "actual_tokens": dict(total),
                "posthoc_root_review": note_map.get(key),
                "original_status_and_scores_unchanged": True,
            }
        )
    primary_categories = ["embedding", "boundary_writer", "host", "other_generation"]
    total_http = Counter()
    total_tokens = Counter()
    for k in primary_categories:
        kind = "embedding" if k == "embedding" else "generation"
        total_http[kind] += costs[k]["requests"]
        total_tokens[kind] += costs[k]["known_tokens"]
    if dict(total_http) != coverage["http"] or dict(total_tokens) != coverage["tokens"]:
        raise ValueError("Cohort costs do not reconcile")
    # Build a prospective review package with explicit method labels removed. The
    # separate mapping remains private. Root has already seen these outcomes;
    # exporting the package does not make Root's diagnostic review independent.
    blinded = []
    mapping = []
    complete = [r for r in rows if r["original"]["trajectory_status"] == "COMPLETE"]
    for row in sorted(
        complete,
        key=lambda r: hashlib.sha256(
            (
                "v13.2-review-v1:" + r["original"]["method_id"] + ":" + r["original"]["case_id"]
            ).encode()
        ).hexdigest(),
    ):
        key = (row["original"]["method_id"], row["original"]["case_id"])
        review_id = f"review-{len(blinded) + 1:03d}"
        items = []
        for value in private_rows:
            if (value["method_id"], value["case_id"]) == key:
                items.append(
                    {
                        k: v
                        for k, v in value.items()
                        if k
                        not in {"method_id", "case_id", "attempt_id", "receipt_path", "trace_path"}
                    }
                )
        blinded.append({"review_id": review_id, "original_evidence": items})
        mapping.append({"review_id": review_id, "method_id": key[0], "case_id": key[1]})
    write(private / "full-evidence.json", private_rows)
    write(private / "call-cost-details.json", call_details)
    write(private / "review-package.json", {"rubric": notes["rubric"], "rows": blinded})
    write(private / "review-map.json", mapping)
    result = {
        "kind": "V13_2_D0_PRIOR_COHORT_DIAGNOSTIC",
        "baseline_commit": "95bf708",
        "original_execution_commit": coverage["source_commit"],
        "script_sha256": sha(Path(__file__)),
        "source_hashes": inputs,
        "input_notes_sha256": sha(notes_path),
        "original_rubric": protocol["scoring"],
        "planned": len(rows),
        "attempted": sum(bool(r["attempts"]) for r in rows),
        "complete": len(complete),
        "actual_process_receipts": scanned,
        "original_answers": sum(v["final_answer"] is not None for v in private_rows),
        "reviewed_complete_trajectories": len(note_map),
        "cost_categories": {k: dict(v) for k, v in costs.items()},
        "per_method_cost_categories": {
            m: {k: dict(v) for k, v in c.items()} for m, c in per_method.items()
        },
        "cost_category_contract": {
            "boundary_writer": "Exact existing writer-policy request cue, including continuation",
            "host": "Other JSON-action adapter requests",
            "other_generation": "Non-JSON-action requests, e.g. native SDK extraction",
            "following_memory_rejection": (
                "Overlapping subset: next paid HTTP after failed memory tool; "
                "not isolated wasted cost"
            ),
        },
        "review_package": {
            "path": str(private / "review-package.json"),
            "sha256": sha(private / "review-package.json"),
            "status": "PREPARED_NOT_INDEPENDENTLY_SCORED",
        },
        "trajectories": rows,
        "qualifications": [
            "Posthoc Root diagnostic review, not blind or independent scoring",
            "Original statuses, rubric and scores unchanged",
            "No new HTTP, old ledger and databases not written",
            "Any absent forensic snapshot stays absent",
        ],
        "new_experiment_generation": 0,
        "product": "NO_GO",
    }
    for name, before in inputs.items():
        if sha(Path(name)) != before:
            raise ValueError(f"Input changed during read-only audit: {name}")
    write(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--notes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--private-dir", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.coverage, args.notes, args.output, args.private_dir)
    print(
        json.dumps(
            {
                k: result[k]
                for k in [
                    "planned",
                    "attempted",
                    "complete",
                    "actual_process_receipts",
                    "original_answers",
                    "cost_categories",
                ]
            }
        )
    )


if __name__ == "__main__":
    main()
