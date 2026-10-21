"""Audit all T1 text-arm inputs using literal reconstruction and the actual tokenizer.

No checkpoint is loaded and no model is called. Timing is left pending for the
original ledger's next idle settlement. The decoder is an offline audit only.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import write_json
from retrieval_mixture import project_mixed_row
from train_laya_matched import audit

_SUBJECTS = {
    "The search query": "request",
    "The query time": "query_time",
    "The normalized reading goal": "read_goal",
    "The complete Host request": "retrieval_request",
}


def recover_request_fields(text: str) -> dict[str, Any]:
    """Independent reader of the declared prose grammar, for equality auditing."""
    lines = iter(text.split("\n"))

    def value(line: str, subject: str, depth: int) -> Any:
        prefix = "  " * depth + subject
        assert line.startswith(prefix)
        tail = line[len(prefix):]
        if tail.startswith(" has "):
            count = int(tail.split()[1])
            if tail.endswith(" named details:"):
                details = {}
                for _ in range(count):
                    child = next(lines)
                    start = "  " * (depth + 1) + "For "
                    assert child.startswith(start)
                    key, length = json.JSONDecoder().raw_decode(child[len(start):])
                    child_subject = f"For {child[len(start):len(start) + length]}, the value"
                    details[key] = value(child, child_subject, depth + 1)
                return details
            assert tail.endswith(" ordered items:")
            return [value(next(lines), f"Item {i}", depth + 1) for i in range(1, count + 1)]
        if tail == " is explicitly null.":
            return None
        for kind, expected in (("text", str), ("boolean", bool), ("number", (int, float))):
            marker = f" is the {kind} "
            if tail.startswith(marker):
                assert tail.endswith(".")
                result = json.loads(tail[len(marker):-1])
                assert isinstance(result, expected)
                return result
        raise ValueError(f"Unrecognized prose clause: {tail}")

    recovered = {}
    for line in lines:
        subject = next(subject for subject in _SUBJECTS if line.startswith(subject))
        recovered[_SUBJECTS[subject]] = value(line, subject, 0)
    return recovered


def check_projection(row: dict[str, Any], projected: dict[str, Any],
                     reference_projection: str = "shared") -> None:
    reference = project_mixed_row(row, reference_projection)
    task = projected["state"]["task"]
    restored = {key: val for key, val in task.items() if key != "request_text"}
    restored.update(recover_request_fields(task["request_text"]))
    assert {**projected["state"], "task": restored} == reference["state"]
    assert {key: val for key, val in projected.items() if key != "state"} == {
        key: val for key, val in reference.items() if key != "state"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("tokenizer", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version", required=True, help="Git provenance label, no checksum")
    parser.add_argument("--max-len", type=int, default=12288)
    parser.add_argument("--head-max-len", type=int, default=2048)
    parser.add_argument("--complete-actions", action="store_true",
                        help="Compare the explicit full-action-table input condition")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    report: dict[str, Any] = {
        "phase": "host_intent_e3_request_text_input_audit_v1",
        "status": "RUNNING", "data": str(args.data), "tokenizer": str(args.tokenizer),
        "projection": ("shared_actions_request_text" if args.complete_actions
                       else "shared_request_text"), "model_loads": 0, "model_calls": 0,
        "ledger_recorded": False, "splits": {}, "max_len": args.max_len,
        "head_max_len": args.head_max_len,
        "source_version": args.source_version,
    }
    try:
        from laya.train import items_from_rows
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(  # type: ignore[no-untyped-call]
            args.tokenizer, local_files_only=True)
        for split in ("train", "dev"):
            rows = [json.loads(line) for line in (args.data / f"{split}.jsonl").open()]
            projected = [project_mixed_row(row, report["projection"]) for row in rows]
            for row, transformed in zip(rows, projected, strict=True):
                check_projection(row, transformed,
                                 "shared_actions" if args.complete_actions else "shared")
            with (args.output / f"{split}.jsonl").open("w") as stream:
                for transformed in projected:
                    stream.write(json.dumps(transformed, ensure_ascii=False) + "\n")
            lengths = audit(projected, tokenizer, args.max_len, args.head_max_len)
            write_json(args.output / f"{split}-lengths.json", lengths)
            bad = [item for item in lengths
                   if item["state_tokens_dropped"] or item["head_tokens_dropped"]]
            labelled = [row for row in projected if row["gold"]]
            items, skipped = items_from_rows(
                tokenizer, labelled, args.max_len, args.head_max_len)
            report["splits"][split] = {
                "rows": len(rows), "literal_task_reconstructions_equal": len(rows),
                "observations_questions_gold_metadata_equal": len(rows),
                "labelled": len(labelled), "sdk_items": len(items), "sdk_skipped": skipped,
                "max_sequence_tokens": max(item["sequence_tokens"] for item in lengths),
                "sequence_tokens": sum(item["sequence_tokens"] for item in lengths),
                "truncated": len(bad),
                "component_rows": dict(Counter(row["metadata"]["component"] for row in rows)),
            }
            assert not bad and not skipped and len(items) == len(labelled)
            print(json.dumps({"split": split, **report["splits"][split]}), flush=True)
        report["status"] = "PASS_COMPLETE_EQUAL_INFORMATION_INPUTS"
    except BaseException as exc:
        report.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        report.update(wall_seconds=time.perf_counter() - started,
                      cpu_seconds=time.process_time() - cpu)
        write_json(args.output / "audit.json", report)


if __name__ == "__main__":
    main()
