"""Diagnose sealed v1 inputs, or an explicitly failed partial cohort without selection.

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

from milai_lab.datasets.edit_benchmarks import halumem_time
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.edit_memory import Arm, EditMemory


def summarize(values: list[int]) -> dict[str, int | float]:
    return {"min": min(values), "median": median(values), "max": max(values)} if values else {}


def declared_metadata(
    config: dict[str, Any],
) -> tuple[dict[str, list[int]], dict[tuple[str, int], str]]:
    """Read only selected development-user rows, before parsing any other row."""
    selection = config["halumem"]
    owners = selection["users"]
    result: dict[str, list[int]] = {}
    dates: dict[tuple[str, int], str] = {}
    with Path(selection["path"]).open(encoding="utf-8") as stream:
        for line in stream:
            if not any(owner in line for owner in owners):
                continue
            user = json.loads(line)
            owner = user["uuid"]
            if owner not in owners:
                raise ValueError("Only declared development-user metadata is allowed")
            sessions = user["sessions"]
            prefix = selection.get("session_prefix")
            if prefix is not None:
                sessions = sessions[:prefix]  # Original v1 selection, not v2 prefix semantics.
            ordered = list(enumerate(sessions))
            if config.get("chronological_order") == "timestamp":
                ordered.sort(key=lambda item: (halumem_time(item[1]["start_time"]), item[0]))
            result[owner] = [ordinal for ordinal, _ in ordered]
            dates.update({(owner, ordinal): raw["start_time"] for ordinal, raw in ordered})
    if set(result) != set(owners):
        raise ValueError("Declared development session metadata is incomplete")
    return result, dates


def capacity_messages(arm: Arm, date: str, delivery: dict[str, Any]) -> list[dict[str, str]]:
    """Exact original v1 Writer template; import the frozen v1 package to reproduce."""
    method = EditMemory.__new__(EditMemory)
    method.arm = arm
    method.conditioned = arm in {"B2", "M"}
    method.interface_version = "v1"
    return [
        {"role": "system", "content": method.instructions()
         + " Group distinct topics into separate records. "
         'Preserve dates and roles. Return {"proposals":[...]}, '
         "each proposal following the supplied schema. "
         "Evidence fields select evidence_id, never source_ref. "
         "Return an empty list when no durable information occurs. "
         "Do not duplicate unchanged records."},
        {"role": "user", "content": json.dumps(
            {"observed_date": date, "delivery": delivery,
             "proposal_schema": method.proposal_schema()}, ensure_ascii=False)},
    ]


def reference_counts(batch: Path, delivery: dict[str, Any]) -> dict[str, int]:
    """Classify actual rejected handles, without claiming issued or semantic support."""
    references = [*delivery["sources"], *delivery["historical_evidence"]]
    references.extend(
        ref
        for record in delivery["records"] if record.get("edit_state")
        for item in [*record["edit_state"]["units"], *record["edit_state"]["relations"]]
        for ref in item["evidence_refs"]
    )
    identities = {ref["evidence_id"] for ref in references}
    provenance = {ref["source_ref"] for ref in references}
    proposals_path = batch / "proposals.json"
    if not proposals_path.exists():
        return {}
    proposals = read_json(proposals_path)
    counts: Counter[str] = Counter()
    for path in sorted(batch.glob("receipt-*.json")):
        receipt = read_json(path)
        if receipt.get("reason") != "FunctionalRejection: EDIT_SOURCE_UNAVAILABLE":
            continue
        proposal = proposals[int(path.stem.removeprefix("receipt-"))]
        handles = {
            handle
            for item in [*proposal.get("units", []), *proposal.get("relations", []),
                         *proposal.get("edits", [])]
            for handle in item.get("evidence", [])
        }
        counts.update(
            "evidence_id_in_writer_reference_index" if handle in identities else
            "source_ref_instead_of_evidence_id" if handle in provenance else
            "not_in_writer_reference_index"
            for handle in handles
        )
    return dict(counts)


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
    allow_failed_partial: bool = False,
    verify_capacity: bool = False,
) -> dict[str, Any]:
    if output.exists():
        raise ValueError("Preserve prior diagnosis; select a fresh output")
    if select_stage_a and arms != ["B0", "B1"]:
        raise ValueError("Stage A selection is fixed to B0/B1; use --no-selection")
    if allow_failed_partial and select_stage_a:
        raise ValueError("Failed partial diagnosis cannot select or replace Stage A inputs")
    config = read_json(suite / arms[0] / "actual-config.json")
    tokenizer = AutoTokenizer.from_pretrained(config["tokenizer_path"], local_files_only=True)  # type: ignore[no-untyped-call]

    def count(value: Any) -> int:
        return len(
            tokenizer.encode(json.dumps(value, ensure_ascii=False), add_special_tokens=False)
        )

    reference_path = reference_diagnostic or suite / "sealed-b0-b1-reference-diagnostic-v1.json"
    reference = read_json(reference_path)
    ref_rows = {
        str(Path(row["receipt"]).parent): row
        for arm in arms
        for row in reference["arms"].get(arm, {}).get("records", [])
    }
    rows: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []
    orders, dates = (
        declared_metadata(config) if allow_failed_partial or verify_capacity else ({}, {})
    )
    terminals = {}
    reconstruction_mismatches = 0
    for arm in arms:
        root = suite / arm
        terminal = read_json(root / "terminal.json")
        terminals[arm] = terminal
        if terminal["status"] != "COMPLETED_EXPERIMENT_PHASE" and not (
            allow_failed_partial and terminal["status"] == "FAILED"
        ):
            raise ValueError("Only sealed arms are eligible for this fixed development sample")
        schema = EditMemory.__new__(EditMemory).proposal_schema()
        for owner in config["halumem"]["users"]:
            order_path = root / "banks" / owner / "session-order.json"
            order = (
                read_json(order_path)["original_ordinals"] if order_path.exists()
                else orders[owner]
            )
            if allow_failed_partial and order != orders[owner]:
                raise ValueError("Actual session order differs from original declared cohort")
            for position, ordinal in enumerate(order):
                key = f"halumem/{owner}/{ordinal}"
                folder = root / "maintenance" / key
                evaluation_complete = (root / "evaluation" / key / "complete.json").exists()
                complete_path = folder / "complete.json"
                if not complete_path.exists():
                    if not allow_failed_partial:
                        raise ValueError("A sealed cohort has a missing maintenance checkpoint")
                    sessions.append({
                        "arm": arm, "user": owner, "session": ordinal,
                        "chronological_position": position,
                        "maintenance_complete": False,
                        "evaluation_complete": evaluation_complete,
                        "availability": "MAINTENANCE_INCOMPLETE" if folder.exists() else "NOT_RUN",
                        "batches": None,
                        "prepared_source_characters": None, "sent_source_characters": None,
                        "received_source_characters": None, "maintained_records": None,
                        "capacity_failures": None, "rejected_proposals": None,
                    })
                    continue
                complete = read_json(complete_path)
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
                    explanation = (
                        ref_rows[input_id]["distinct_per_proposal"] if input_id in ref_rows
                        else reference_counts(batch, delivery)
                    )
                    categories = []
                    if failure and failure["message"].startswith(
                        "Context unavailable without loss:"
                    ):
                        categories.append("capacity")
                    reconstructed_tokens = None
                    if verify_capacity and "capacity" in categories:
                        reconstructed_tokens = len(tokenizer.apply_chat_template(
                            capacity_messages(arm, dates[(owner, ordinal)], delivery),
                            tokenize=True, add_generation_prompt=True, enable_thinking=False,
                        ))
                        reconstruction_mismatches += reconstructed_tokens != prompt_tokens
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
                        "maintenance_complete": True,
                        "evaluation_complete": evaluation_complete,
                        "availability": "EVALUATION_COMPLETE" if evaluation_complete
                        else "MAINTENANCE_COMPLETE_EVALUATION_INCOMPLETE",
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
                        "capacity_reconstructed_prompt_tokens": reconstructed_tokens,
                        "capacity_token_count_matches": (
                            reconstructed_tokens == prompt_tokens
                            if reconstructed_tokens is not None
                            else None
                        ),
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
                        "maintenance_complete": True,
                        "evaluation_complete": evaluation_complete,
                        "availability": "EVALUATION_COMPLETE" if evaluation_complete
                        else "MAINTENANCE_COMPLETE_EVALUATION_INCOMPLETE",
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
        "status": "R0_FAILED_V1_PARTIAL_DIAGNOSIS_ONLY" if allow_failed_partial else (
            "R0_SEALED_V1_DIAGNOSIS_AND_FIXED_STAGE_A_SAMPLE"
            if select_stage_a else "R0_SEALED_V1_DIAGNOSIS_ONLY"
        ),
        "actual_http_calls": 0,
        "candidate_selected": False,
        "arms": arms,
        "observed_terminals": terminals,
        "capacity_reconstruction_mismatches": (
            reconstruction_mismatches if verify_capacity else None
        ),
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
            "Only actual completed maintenance contributes input/body metrics; unrun and "
            "incomplete opportunities remain in declared session denominators with null metrics. "
            "No failed call replay or missing-score replacement. "
            "Component token counts overlap and are not additive. "
            "Accepted/no_change is not semantic maintenance success. Missing packet IDs "
            "are not proven unissued or invisible. Samples are exposed development, "
            "not independent evaluation."
        ),
    }
    write_json(output, result)
    if reconstruction_mismatches:
        raise ValueError("Original v1 capacity token reconstruction differs; preserve report")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--arms", nargs="+", choices=["B0", "B1", "B2", "M"],
                        default=["B0", "B1"])
    parser.add_argument("--reference-diagnostic", type=Path)
    parser.add_argument("--no-selection", action="store_true")
    parser.add_argument("--allow-failed-partial", action="store_true",
                        help="Explicit FAILED terminal only; requires --no-selection")
    parser.add_argument("--verify-capacity", action="store_true",
                        help="Rebuild original v1 capacity template with frozen v1 PYTHONPATH")
    args = parser.parse_args()
    report = diagnose(
        args.suite, args.output, args.arms,
        reference_diagnostic=args.reference_diagnostic, select_stage_a=not args.no_selection,
        allow_failed_partial=args.allow_failed_partial,
        verify_capacity=args.verify_capacity,
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
