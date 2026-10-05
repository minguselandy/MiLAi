"""Diagnose sealed v1 inputs and freeze at most 24 unique pre-call samples.

No HTTP, state restoration, reserved data or new method decisions occur here.
Run with the preserved v1 evaluator package on PYTHONPATH, not a changing v2 tree.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

from transformers import AutoTokenizer

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.edit_memory import Arm, EditMemory


def summarize(values: list[int]) -> dict[str, int | float]:
    return {"min": min(values), "median": median(values), "max": max(values)} if values else {}


def frozen_samples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fixed category quotas, source-user/stage rotation, unique call inputs."""
    selected: list[dict[str, Any]] = []
    used: set[str] = set()
    owners = sorted({row["user"] for row in rows})
    for category in ("capacity", "unsupported_action", "wrong_reference", "normal_control"):
        eligible = [row for row in rows if category in row["sample_categories"]]
        for slot in range(6):
            preferred = owners[slot % len(owners)]
            stage = ("early", "middle", "late")[slot % 3]
            candidates = [row for row in eligible if row["input_id"] not in used]
            candidates.sort(
                key=lambda row: (
                    row["user"] != preferred,
                    row["stage"] != stage,
                    row["arm"] != ("B0" if slot % 2 == 0 else "B1"),
                    row["input_id"],
                )
            )
            if not candidates:
                break
            chosen = candidates[0]
            used.add(chosen["input_id"])
            selected.append(
                {
                    "category": category,
                    "input_id": chosen["input_id"],
                    "arm": chosen["arm"],
                    "user": chosen["user"],
                    "session": chosen["session"],
                    "stage": chosen["stage"],
                    "prompt_tokens": chosen["prompt_tokens"],
                    "delivery_path": chosen["delivery_path"],
                    "before_path": chosen["before_path"],
                    "rejection_reasons": chosen["rejection_reasons"],
                    "reference_explanation": chosen["reference_explanation"],
                }
            )
    return selected


def diagnose(
    suite: Path, output: Path, arms: list[Arm], *,
    reference_diagnostic: Path | None = None, select_stage_a: bool = True,
) -> dict[str, Any]:
    if output.exists():
        raise ValueError("Preserve prior diagnosis; select a fresh output")
    if select_stage_a and arms != ["B0", "B1"]:
        raise ValueError("Stage A selection is fixed to B0/B1; use --no-selection")
    config = read_json(suite / arms[0] / "actual-config.json")
    tokenizer = AutoTokenizer.from_pretrained(config["tokenizer_path"], local_files_only=True)  # type: ignore[no-untyped-call]

    def count(value: Any) -> int:
        return len(
            tokenizer.encode(json.dumps(value, ensure_ascii=False), add_special_tokens=False)
        )

    reference = read_json(
        reference_diagnostic or suite / "sealed-b0-b1-reference-diagnostic-v1.json"
    )
    ref_rows = {
        str(Path(row["receipt"]).parent): row
        for arm in arms
        for row in reference["arms"][arm]["records"]
    }
    rows: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []
    for arm in arms:
        root = suite / arm
        if read_json(root / "terminal.json")["status"] != "COMPLETED_EXPERIMENT_PHASE":
            raise ValueError("Only sealed arms are eligible for this fixed development sample")
        schema = EditMemory.__new__(EditMemory).proposal_schema()
        for owner in config["halumem"]["users"]:
            order = read_json(root / "banks" / owner / "session-order.json")["original_ordinals"]
            for position, ordinal in enumerate(order):
                key = f"halumem/{owner}/{ordinal}"
                folder = root / "maintenance" / key
                complete = read_json(folder / "complete.json")
                session_rows: list[dict[str, Any]] = []
                for batch in sorted(folder.glob("batch-*")):
                    delivery_path = batch / "delivery.json"
                    if not delivery_path.exists():
                        continue
                    delivery = read_json(delivery_path)
                    http = root / "http" / key / "writer" / str(int(batch.name.split("-")[1]))
                    request = (
                        read_json(http / "request.json")
                        if (http / "request.json").exists()
                        else None
                    )
                    failure = (
                        read_json(batch / "writer-failure.json")
                        if (batch / "writer-failure.json").exists()
                        else None
                    )
                    prompt_tokens = (
                        request["prompt_tokens"]
                        if request
                        else (
                            int(failure["message"].split(": ")[1].split()[0])
                            if failure
                            and failure["message"].startswith("Context unavailable without loss:")
                            else None
                        )
                    )
                    receipts = read_json(batch / "complete.json")["receipts"]
                    reasons = [r["reason"] for r in receipts if not r["ok"]]
                    record_states = [
                        r["edit_state"] for r in delivery["records"] if r.get("edit_state")
                    ]
                    units = [u for state in record_states for u in state["units"]]
                    relations = [r for state in record_states for r in state["relations"]]
                    support = [e for item in [*units, *relations] for e in item["evidence_refs"]]
                    input_id = str(batch.relative_to(suite))
                    explanation = ref_rows.get(input_id, {}).get("distinct_per_proposal", {})
                    categories = []
                    if failure and failure["message"].startswith(
                        "Context unavailable without loss:"
                    ):
                        categories.append("capacity")
                    if any(
                        "EDIT_LOCAL_OPERATIONS_REQUIRED" in reason
                        or "EDIT_FULL_REWRITE_NOT_AVAILABLE" in reason
                        for reason in reasons
                    ):
                        categories.append("unsupported_action")
                    if any("EDIT_SOURCE_UNAVAILABLE" in reason for reason in reasons):
                        categories.append("wrong_reference")
                    if not failure and receipts and all(r["ok"] for r in receipts):
                        categories.append("normal_control")
                    structures = [
                        {k: v for k, v in r.items() if k != "content"} for r in delivery["records"]
                    ]
                    before = read_json(batch / "before.json")
                    after = read_json(batch / "after.json")
                    row = {
                        "input_id": input_id,
                        "arm": arm,
                        "user": owner,
                        "session": ordinal,
                        "chronological_position": position,
                        "stage": (
                            "early"
                            if position < len(order) / 3
                            else "middle"
                            if position < len(order) * 2 / 3
                            else "late"
                        ),
                        "delivery_path": str(delivery_path),
                        "before_path": str(batch / "before.json"),
                        "prompt_tokens": prompt_tokens,
                        "prepared_source_characters": sum(
                            len(s["text"]) for s in delivery["sources"]
                        ),
                        "sent": request is not None,
                        "response_received": (http / "response.json").exists(),
                        "complete_response_parsed": (batch / "proposals.json").exists(),
                        "accepted_proposals": sum(r["ok"] for r in receipts),
                        "maintained_records": len(
                            read_json(batch / "complete.json")["changed_records"]
                        ),
                        "retrieved_records": len(delivery["records"]),
                        "units": len(units),
                        "relations": len(relations),
                        "unit_tokens": summarize([count(u["text"]) for u in units]),
                        "old_max_record_body_tokens": max(
                            (count(r["content"]) for r in delivery["records"]), default=0
                        ),
                        "bank_records_before": len(before),
                        "bank_records_after": len(after),
                        "bank_body_characters_before": sum(
                            len(r["value"]["content"]) for r in before
                        ),
                        "bank_body_characters_after": sum(
                            len(r["value"]["content"]) for r in after
                        ),
                        "old_rendered_characters": sum(
                            len(r["content"]) for r in delivery["records"]
                        ),
                        "old_unit_text_characters": sum(len(u["text"]) for u in units),
                        "support_occurrences": len(support),
                        "distinct_support_ids": len({e["evidence_id"] for e in support}),
                        "isolated_component_tokens_not_additive": {
                            "new_source": count(delivery["sources"]),
                            "old_record_text": count([r["content"] for r in delivery["records"]]),
                            "structure_and_support": count(structures),
                            "historical_evidence": count(delivery["historical_evidence"]),
                            "schema": count(schema),
                        },
                        "rejection_reasons": reasons,
                        "reference_explanation": explanation,
                        "sample_categories": categories,
                    }
                    rows.append(row)
                    session_rows.append(row)
                sessions.append(
                    {
                        "arm": arm,
                        "user": owner,
                        "session": ordinal,
                        "chronological_position": position,
                        "batches": len(session_rows),
                        "prepared_source_characters": sum(
                            r["prepared_source_characters"] for r in session_rows
                        ),
                        "sent_source_characters": sum(
                            r["prepared_source_characters"] for r in session_rows if r["sent"]
                        ),
                        "received_source_characters": sum(
                            r["prepared_source_characters"]
                            for r in session_rows
                            if r["response_received"]
                        ),
                        "maintained_records": len(complete["extracted_memories"]),
                        "capacity_failures": sum(
                            "capacity" in r["sample_categories"] for r in session_rows
                        ),
                        "rejected_proposals": sum(
                            len(r["rejection_reasons"]) for r in session_rows
                        ),
                    }
                )
    samples = frozen_samples(rows) if select_stage_a else []
    result = {
        "status": "R0_SEALED_V1_DIAGNOSIS_AND_FIXED_STAGE_A_SAMPLE"
        if select_stage_a else "R0_SEALED_V1_DIAGNOSIS_ONLY",
        "actual_http_calls": 0,
        "candidate_selected": False,
        "arms": arms,
        "session_availability": sessions,
        "input_composition_and_growth": rows,
        "fixed_samples": samples,
        "sample_counts": dict(Counter(s["category"] for s in samples)),
        "unique_sample_inputs": len({s["input_id"] for s in samples}),
        "selection_rule": (
            "Before v2 output: six per category, user/stage/arm rotation, lexical ties; "
            "no duplicate input or quota padding."
        ) if select_stage_a else "No new Stage A selection; preserve the existing fixed 24.",
        "limits": (
            "Listed sealed v1 arms only. Component token counts overlap and are not additive. "
            "Accepted/no_change is not semantic maintenance success. Missing packet IDs "
            "are not proven unissued or invisible. Samples are exposed development, "
            "not independent evaluation."
        ),
    }
    write_json(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--arms", nargs="+", choices=["B0", "B1", "B2", "M"],
                        default=["B0", "B1"])
    parser.add_argument("--reference-diagnostic", type=Path)
    parser.add_argument("--no-selection", action="store_true")
    args = parser.parse_args()
    report = diagnose(
        args.suite, args.output, args.arms,
        reference_diagnostic=args.reference_diagnostic, select_stage_a=not args.no_selection,
    )
    print(
        json.dumps(
            {
                "samples": report["sample_counts"],
                "unique": report["unique_sample_inputs"],
                "sessions": len(report["session_availability"]),
                "actual_http_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
