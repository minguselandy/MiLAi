"""Audit frozen D0/P5 development receipts and actual HTTP; no runtime imports.

This collector supplies evidence and accounting, not automatic semantic scores.
Every planned trajectory stays in the output. A missing or altered provider final
is explicit and cannot become a synthesized successful answer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def read(path: Path) -> Any:
    return json.loads(path.read_text())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def actual_final(receipt: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    answer = receipt.get("final_answer")
    finals = [
        row
        for row in receipt.get("messages", [])
        if row.get("type") == "ai" and not row.get("tool_calls")
    ]
    final = finals[-1] if finals else None
    if answer is None:
        return {"status": "NO_FINAL", "provider_id": None}
    if final is None or not final.get("id") or final.get("content") != answer:
        return {"status": "UNLINKED_GRAPH_FINAL", "provider_id": None}
    matches = []
    for ordinal, event in enumerate(events):
        if event.get("event") != "vllm_response" or event.get("path") != "chat/completions":
            continue
        raw = event.get("response_text")
        if not isinstance(raw, str):
            continue
        try:
            response = json.loads(raw)
            if not isinstance(response, dict):
                continue
            if response.get("id") != final.get("id"):
                continue
            if len(response["choices"]) != 1:
                continue
            choice = response["choices"][0]
            if not isinstance(choice, dict):
                continue
            wire = choice["message"]
            if not isinstance(wire, dict):
                continue
            content = wire.get("content")
        except (ValueError, KeyError, TypeError, IndexError):
            continue
        try:
            decoded = json.loads(content) if isinstance(content, str) else None
        except ValueError:
            decoded = None
        if choice.get("finish_reason") in {"stop", "tool_calls"} and (
            (isinstance(decoded, dict) and decoded.get("answer") == answer)
            or (content == answer and not wire.get("tool_calls"))
        ):
            matches.append(
                {
                    "trace_ordinal": ordinal,
                    "provider_id": response["id"],
                    "raw_response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                }
            )
    return {
        "status": "LINKED_ACTUAL_HTTP" if len(matches) == 1 else "UNLINKED_HTTP_FINAL",
        "matches": matches,
    }


def collect(
    root: Path,
    output: Path,
    private: Path,
    receipt_pattern: str,
    writer_prefixes: list[str],
    ledger_before: Path | None,
    ledger_after: Path | None,
) -> dict[str, Any]:
    frozen_path = root / "input-freeze.json"
    frozen = read(frozen_path)
    fixture_path = Path(frozen["fixture_path"])
    config_path = Path(frozen["config_path"])
    if sha(fixture_path) != frozen["fixture_sha256"] or sha(config_path) != frozen["config_sha256"]:
        raise ValueError("Frozen public fixture/config bytes changed")
    inputs = {
        str(frozen_path): sha(frozen_path),
        str(fixture_path): sha(fixture_path),
        str(config_path): sha(config_path),
    }
    trajectories, review_rows, cost_rows = [], [], []
    totals: Counter[str] = Counter()
    for case in frozen["fixture"]["cases"]:
        case_root = root / hashlib.sha256(case["case_id"].encode()).hexdigest()[:16]
        rows, processes = [], []
        for index, public in enumerate(case["messages"]):
            path = case_root / receipt_pattern.format(index=index)
            row: dict[str, Any] = {
                "message_index": index,
                "message_id": public["message_id"],
                "status": "NOT_RUN",
                "receipt_path": str(path),
            }
            if not path.exists():
                rows.append(row)
                continue
            receipt, trace_path = read(path), path.with_suffix(".jsonl")
            if (
                receipt.get("case_id") != case["case_id"]
                or receipt.get("message_id") != public["message_id"]
            ):
                raise ValueError(f"Public message identity mismatch: {path}")
            events = (
                [json.loads(line) for line in trace_path.read_text().splitlines()]
                if trace_path.exists()
                else []
            )
            inputs[str(path)] = sha(path)
            if trace_path.exists():
                inputs[str(trace_path)] = sha(trace_path)
            processes.append(receipt.get("process_id"))
            sources = receipt.get("sources", [])
            for source in sources:
                if (
                    source["owner"] != case["owner"]
                    or hashlib.sha256(source["content"].encode()).hexdigest()
                    != source["content_sha256"]
                ):
                    raise ValueError(f"Source owner/hash mismatch: {path}")
            for ordinal, event in enumerate(events):
                if event.get("event") not in {"vllm_response", "vllm_error"}:
                    continue
                category = "embedding" if event["path"] == "embeddings" else "generation"
                writer = category == "generation" and any(
                    message.get("role") == "user"
                    and any(
                        str(message.get("content", "")).startswith(prefix)
                        for prefix in writer_prefixes
                    )
                    for message in event.get("request", {}).get("messages", [])
                )
                detail = "semantic_writer" if writer else category
                usage = event.get("usage")
                tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
                totals[category + "_requests"] += 1
                totals[detail + "_classified_requests"] += 1
                if type(tokens) is int:
                    totals[category + "_known_tokens"] += tokens
                    totals[detail + "_classified_known_tokens"] += tokens
                else:
                    totals[category + "_unknown_usage"] += 1
                cost_rows.append(
                    {
                        "receipt_path": str(path),
                        "trace_ordinal": ordinal,
                        "category": category,
                        "detail": detail,
                        "known_tokens": tokens,
                        "event": event["event"],
                        "wall_seconds": event.get("wall_seconds"),
                    }
                )
            linkage = actual_final(receipt, events)
            row.update(
                status=receipt["status"],
                receipt_sha256=sha(path),
                trace_sha256=sha(trace_path) if trace_path.exists() else None,
                process_id=receipt.get("process_id"),
                final_linkage=linkage,
                error_type=receipt.get("error_type"),
                error=receipt.get("error"),
                source_count=len(sources),
                semantic_review="UNREVIEWED",
            )
            rows.append(row)
            review_rows.append(
                {
                    "case_id": case["case_id"],
                    "message_index": index,
                    "public_message": public,
                    "receipt_path": str(path),
                    "receipt_sha256": sha(path),
                    "trace_path": str(trace_path),
                    "final_answer": receipt.get("final_answer"),
                    "final_linkage": linkage,
                    "actual_receipt": receipt,
                }
            )
        complete = all(row["status"] == "completed" for row in rows)
        trajectories.append(
            {
                "case_id": case["case_id"],
                "category": case.get("category"),
                "complete": complete,
                "messages": rows,
                "distinct_recorded_processes": bool(processes)
                and None not in processes
                and len(set(processes)) == len(processes),
                "semantic_verdict": "UNREVIEWED",
            }
        )
    ledger = None
    if ledger_before is not None and ledger_after is not None:
        before, after = read(ledger_before), read(ledger_after)
        inputs.update(
            {str(ledger_before): sha(ledger_before), str(ledger_after): sha(ledger_after)}
        )
        if before["limits"] != after["limits"]:
            raise ValueError("Continuous ledger limits changed")
        ledger = {
            "generation_requests": after["generation_requests"] - before["generation_requests"]
        }
        for kind in ("generation", "embedding"):
            ledger[kind] = {
                key: after[kind][key] - before[kind][key]
                for key in ("charged_tokens", "known_tokens", "unknown_usage")
            }
        ledger["trace_known_tokens_match"] = all(
            ledger[kind]["known_tokens"] == totals[kind + "_known_tokens"]
            for kind in ("generation", "embedding")
        )
        ledger["trace_generation_requests_match"] = (
            ledger["generation_requests"] == totals["generation_requests"]
        )
    write(private / "review-evidence.json", {"rows": review_rows, "inputs_sha256": inputs})
    write(private / "call-costs.json", cost_rows)
    result = {
        "kind": "V13_2_DEVELOPMENT_EVIDENCE_AUDIT",
        "runtime_freeze_sha256": sha(frozen_path),
        "execution_source_sha256": frozen["source_sha256"],
        "script_sha256": sha(Path(__file__)),
        "input_artifacts_sha256": inputs,
        "planned": len(trajectories),
        "complete": sum(row["complete"] for row in trajectories),
        "trajectories": trajectories,
        "trace_costs": dict(totals),
        "ledger_delta": ledger,
        "writer_prefixes": writer_prefixes,
        "review_status": "NOT_SCORED",
        "qualifications": [
            "Collector is not an independent Judge or semantic scorer.",
            "Unclassified generation includes Host and any writer without declared prefix.",
            "Trace known usage is separate from conservative ledger charges; unknown is not zero.",
        ],
        "product": "NO_GO",
    }
    write(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--receipt-pattern", default="message-{index}.json")
    parser.add_argument("--writer-prefix", action="append", default=[])
    parser.add_argument("--ledger-before", type=Path)
    parser.add_argument("--ledger-after", type=Path)
    args = parser.parse_args()
    if bool(args.ledger_before) != bool(args.ledger_after):
        parser.error("Supply both ledger snapshots or neither")
    result = collect(
        args.run_root,
        args.output,
        args.private_dir,
        args.receipt_pattern,
        args.writer_prefix,
        args.ledger_before,
        args.ledger_after,
    )
    print(json.dumps({key: result[key] for key in ("planned", "complete", "review_status")}))


if __name__ == "__main__":
    main()
