#!/usr/bin/env python3
"""Read sealed r52 evidence into a local index; never infer new semantic scores."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_text())


def records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": r["id"],
            "revision": r.get("value", {}).get("revision", r.get("revision")),
            "value_sha256": digest(r["value"]) if "value" in r else None,
            "field_support": r.get("value", {}).get("field_support"),
            "projection_status": r.get("status"),
            "projection_sha256": digest(r),
        }
        for r in rows
    ]


def phase(request: dict[str, Any]) -> str:
    names = [x["function"]["name"] for x in request.get("tools", [])]
    if names in (["review_formation_support"], ["review_revision_support"]):
        return names[0]
    if names in (["classify_current_request"], ["resolve_continuation_operations"]):
        return names[0]
    return "host_execution" if names else "answer_without_tools"


def trace_index(path: Path, parameters: dict[str, Counter[str]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "sha256": file_digest(path),
        "http": [],
        "proposals": [],
        "review_inputs": [],
        "reviews": [],
    }
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        event = json.loads(line)
        if event.get("event") != "vllm_response":
            continue
        request = event["request"]
        stage = phase(request)
        signature = {
            k: request.get(k)
            for k in (
                "model",
                "temperature",
                "max_tokens",
                "chat_template_kwargs",
                "tool_choice",
                "response_format",
            )
        }
        parameters[stage][json.dumps(signature, sort_keys=True)] += 1
        receipt = event.get("receipt") or {}
        choices = receipt.get("choices") or []
        calls = choices[0].get("message", {}).get("tool_calls") or [] if choices else []
        location = {
            "trace_line": line_number,
            "request_sha256": digest(request),
            "response_sha256": digest(receipt),
        }
        result["http"].append(
            {
                **location,
                "stage": stage,
                "finish_reason": choices[0].get("finish_reason") if choices else None,
                "http_status": event.get("http_status"),
                "usage": event.get("usage"),
                "wall_seconds": event.get("wall_seconds"),
            }
        )
        if stage.startswith("review_"):
            evidence = json.loads(request["messages"][-1]["content"])
            changes = []
            for row in evidence["changes"]:
                changes.append(
                    {
                        k: v
                        for k, v in row.items()
                        if k not in {"before", "after", "selected_original_fragments"}
                    }
                    | {
                        "before_sha256": digest(row.get("before")),
                        "after_sha256": digest(row.get("after")),
                        "selected_original_fragments": [
                            {k: v for k, v in fragment.items() if k != "content"}
                            for fragment in row["selected_original_fragments"]
                        ],
                    }
                )
            result["review_inputs"].append(
                {
                    **location,
                    "evidence_sha256": digest(evidence),
                    "record_id": evidence.get("record_id"),
                    "binding": evidence.get("binding"),
                    "changes": changes,
                }
            )
        for call in calls:
            function = call.get("function", {})
            name = function.get("name")
            try:
                args = json.loads(function.get("arguments", ""))
            except (TypeError, ValueError):
                args = None
            if name in {"save_memory", "update_memory", "retract_memory", "forget_memory"}:
                result["proposals"].append(
                    {
                        **location,
                        "tool_name": name,
                        "tool_call_id": call.get("id"),
                        "arguments_sha256": digest(args),
                        "arguments_valid_json": args is not None,
                        "selected_handles": {
                            k: v for k, v in (args or {}).items() if "handle" in k
                        },
                        "candidate_content_sha256": digest((args or {}).get("content")),
                    }
                )
            elif name in {"review_formation_support", "review_revision_support"}:
                fields = (args or {}).get("field_results", [])
                result["reviews"].append(
                    {
                        **location,
                        "decision_sha256": digest(args),
                        "decision": args,
                        "inconsistent_fields": [
                            r.get("field")
                            for r in fields
                            if r.get("assessment") == "supported"
                            and r.get("unsupported_differences")
                        ],
                    }
                )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-lab", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("refusing to overwrite an existing baseline index")
    old = args.baseline_lab.resolve()
    terminal = read(old / "data/manifests/v13-5-r52-terminal-results.json")
    parameters: dict[str, Counter[str]] = defaultdict(Counter)
    index: dict[str, Any] = {
        "schema": "post_r52_baseline_evidence_index_v1",
        "baseline_lab": str(old),
        "semantic_regrading": False,
        "review_identity": "original Root same-family development assessment, not independent",
        "terminal_manifest_sha256": file_digest(
            old / "data/manifests/v13-5-r52-terminal-results.json"
        ),
        "cohorts": [],
        "effective_parameters_from_actual_http": {},
    }
    for cohort in terminal["cohorts"]:
        root = old / "artifacts/v13-5" / cohort["id"]
        seal = read(root / "seal.json")
        missing = []
        changed = []
        for relative, expected in seal["files"].items():
            path = root / relative
            if not path.is_file():
                missing.append(relative)
            elif file_digest(path) != expected:
                changed.append(relative)
        freeze = read(root / "input-freeze.json")
        review = read(root / "review.json")
        attempts: dict[str, list[tuple[Path, dict[str, Any]]]] = defaultdict(list)
        for path in root.glob("banks/**/*-attempt-*.json"):
            value = read(path)
            attempts[value["bank"]].append((path, value))
        cases = []
        for case in freeze["fixture"]["cases"]:
            case_id = case["case_id"]
            order = {m["message_id"]: i for i, m in enumerate(case["messages"])}
            rows = sorted(
                attempts[case_id],
                key=lambda pair: (order[pair[1]["message_id"]], pair[1]["attempt"]),
            )
            message_rows = []
            previous_records: list[dict[str, Any]] | None = None
            for path, value in rows:
                prefix = path.name.split("-attempt-")[0]
                trace = path.with_name(f"{prefix}-trace-{value['attempt']}.jsonl")
                after = records(value.get("records", [])) if "records" in value else None
                message_rows.append(
                    {
                        "message_id": value["message_id"],
                        "attempt": value["attempt"],
                        "owner": value["owner"],
                        "path": str(path),
                        "sha256": file_digest(path),
                        "status": value["status"],
                        "current_request_sha256": digest(value.get("content")),
                        "request_mode": value.get("request_mode"),
                        "operation_status": value.get("operation_status"),
                        "previous_attempt_records": previous_records,
                        "records_after": after,
                        "final_answer_sha256": digest(value.get("final_answer")),
                        "generation_calls": value.get("generation_calls"),
                        "usage": value.get("usage"),
                        "trace": trace_index(trace, parameters) if trace.exists() else None,
                        "review_states": [
                            {"path": str(p), "sha256": file_digest(p), **read(p)}
                            for p in sorted(path.parent.glob(f"{prefix}-*-review-*.json"))
                        ],
                    }
                )
                if after is not None:
                    previous_records = after
            cases.append(
                {
                    "case_id": case_id,
                    "source_groups": sorted(
                        {s["session_id"] for s in case.get("initial_sources", [])}
                    ),
                    "public_case_sha256": digest(case),
                    "original_assessment": review["case_review"].get(case_id),
                    "first_semantic_assessment": (
                        "not_inferred_by_indexer; inspect linked original proposals"
                    ),
                    "first_execution_status": message_rows[0]["status"]
                    if message_rows
                    else "MISSING",
                    "last_retained_attempt_status": message_rows[-1]["status"]
                    if message_rows
                    else "MISSING",
                    "messages": message_rows,
                }
            )
        index["cohorts"].append(
            {
                "id": cohort["id"],
                "source_commit": cohort["source_commit"],
                "seal_sha256": file_digest(root / "seal.json"),
                "review_sha256": file_digest(root / "review.json"),
                "freeze_sha256": file_digest(root / "input-freeze.json"),
                "sealed_files": len(seal["files"]),
                "missing_files": missing,
                "changed_files": changed,
                "replayability": "ORIGINALS_AVAILABLE"
                if not missing and not changed
                else "INCOMPLETE_OR_CHANGED_DO_NOT_RECONSTRUCT_AS_ORIGINAL",
                "original_counts": review["semantic_counts"],
                "cost_delta": review["cost_delta"],
                "cases": cases,
            }
        )
    index["effective_parameters_from_actual_http"] = {
        stage: [
            {"parameters": json.loads(signature), "actual_requests": count}
            for signature, count in counter.items()
        ]
        for stage, counter in parameters.items()
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": file_digest(args.output),
                "cohorts": [
                    {k: c[k] for k in ("id", "sealed_files", "replayability", "original_counts")}
                    for c in index["cohorts"]
                ],
                "effective_parameters": index["effective_parameters_from_actual_http"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
