"""Read-only per-user official scores, explicit opportunities and paired intervals."""

from __future__ import annotations

import copy
import json
import random
import sqlite3
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from statistics import mean
from typing import Any

from milai_lab.analysis.edit_official import HaluMemOfficial
from milai_lab.harness.artifact_io import read_json

PAIRS = (("B0", "B1"), ("B0", "B2"), ("B2", "M"), ("B1", "M"), ("M", "Append-only"))
METRICS = (
    "formation_recall_all",
    "formed_memory_accuracy_all",
    "update_correct_all_opportunities",
    "qa_correct_all",
)


def ratio(numerator: float, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def paired_interval(
    first: Sequence[float], second: Sequence[float], *, seed: int = 20261004, repeats: int = 10000
) -> dict[str, Any]:
    """Resample paired users, not questions or repeated calls."""
    if len(first) != len(second) or not first or repeats < 1:
        raise ValueError("Paired nonempty user vectors and positive resample count required")
    differences = [b - a for a, b in zip(first, second, strict=True)]
    generator = random.Random(seed)  # noqa: S311 -- reproducible statistical resampling
    samples = sorted(
        mean(generator.choices(differences, k=len(differences))) for _ in range(repeats)
    )
    return {
        "difference_second_minus_first": mean(differences),
        "percentile_95_interval": [
            samples[int(0.025 * (repeats - 1))],
            samples[int(0.975 * (repeats - 1))],
        ],
        "users": len(first),
        "sampling_unit": "paired user; equal user weight",
        "seed": seed,
        "resamples": repeats,
        "limit": "few source clusters; descriptive interval, no cross-family claim",
    }


def user_metrics(records: dict[str, Any], counts: dict[str, int]) -> dict[str, Any]:
    integrity = [
        row for row in records["memory_integrity_records"] if row["memory_source"] != "interference"
    ]
    accuracy = records["memory_accuracy_records"]
    updates = records["memory_update_records"]
    questions = records["question_answering_records"]
    valid_updates = [
        row
        for row in updates
        if row["memory_update_type"] in {"Correct", "Hallucination", "Omission", "Other"}
    ]
    valid_questions = [
        row for row in questions if row["result_type"] in {"Correct", "Hallucination", "Omission"}
    ]
    valid_accuracy = [row for row in accuracy if row["memory_accuracy_score"] in {0, 1, 2}]
    correct_updates = sum(row["memory_update_type"] == "Correct" for row in updates)
    correct_questions = sum(row["result_type"] == "Correct" for row in questions)
    return {
        "formation_recall_all": ratio(
            sum(row["memory_integrity_score"] == 2 for row in integrity), len(integrity)
        ),
        "formed_memory_accuracy_all": ratio(
            sum(0.5 * row["memory_accuracy_score"] for row in valid_accuracy), len(accuracy)
        ),
        "update_correct_all_opportunities": ratio(correct_updates, counts["total_updates"]),
        "update_correct_scored": ratio(correct_updates, len(updates)),
        "update_correct_valid": ratio(correct_updates, len(valid_updates)),
        "qa_correct_all": ratio(correct_questions, len(questions)),
        "qa_correct_valid": ratio(correct_questions, len(valid_questions)),
        "denominators": {
            **counts,
            "formation_reference_points": len(integrity),
            "formation_valid_judgments": sum(
                row["memory_integrity_score"] in {0, 1, 2} for row in integrity
            ),
            "formed_memory_outputs": len(accuracy),
            "formed_memory_valid_judgments": len(valid_accuracy),
            "update_scored_records": len(updates),
            "update_valid_judgments": len(valid_updates),
            "update_unscored_opportunities": counts["total_updates"] - len(updates),
            "qa_opportunities": len(questions),
            "qa_valid_judgments": len(valid_questions),
        },
        "update_information_condition": "reference-guided read-only retrieval; separate from QA",
    }


def receipt_effect(receipt: dict[str, Any]) -> str:
    """Keep confirmed replay of an original commit distinct from a pure no-change."""
    if receipt.get("ok") is False:
        return "rejected"
    if receipt.get("ok") is True:
        status = receipt.get("status")
        replayed = receipt.get("replayed") is True
        original = receipt.get("original_status")
        if replayed and (original == "committed" or (original is None and status == "committed")):
            return "replayed_commit"
        if status == "committed" and not replayed:
            return "committed"
        if status == "no_change" and (not replayed or original == "no_change"):
            return "no_change"
    return "other_or_unconfirmed"


def writer_operations(
    folder: Path, owner: str, expected_sessions: Sequence[int] | None
) -> dict[str, Any]:
    """Count recorded first attempts and effects without inferring semantic success."""
    config = folder / "actual-config.json"
    if config.exists() and read_json(config).get("maintenance_recipe"):
        return recipe_writer_operations(folder, owner, expected_sessions)
    maintenance = folder / "maintenance" / "halumem" / owner
    sessions = (
        list(expected_sessions)
        if expected_sessions is not None
        else sorted(int(path.name) for path in maintenance.glob("*") if path.is_dir())
    )
    counts: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    rejections: Counter[str] = Counter()
    receipt_statuses: Counter[str] = Counter()
    proposed_actions: Counter[str] = Counter()
    committed_actions: Counter[str] = Counter()
    proposed_edits: Counter[str] = Counter()
    failure_examples: dict[str, list[str]] = {}
    for session in sessions:
        location = maintenance / str(session)
        coverage_path = location / "source-coverage.json"
        if (folder / "evaluation" / "halumem" / owner / str(session) / "complete.json").exists():
            counts["official_completed_sessions"] += 1
        if not coverage_path.exists():
            continue
        coverage = read_json(coverage_path)
        counts["prepared_sessions"] += 1
        counts["original_characters_in_prepared_sessions"] += coverage["original_characters"]
        counts["prepared_characters"] += coverage["covered_characters"]
        if coverage["original_characters"] != coverage["covered_characters"]:
            counts["prepared_character_coverage_mismatches"] += 1
        if (location / "complete.json").exists():
            counts["maintenance_completed_sessions"] += 1
            counts["upstream_extracted_outputs"] += len(
                read_json(location / "complete.json")["extracted_memories"]
            )
        for ordinal, spans in enumerate(coverage["batches"]):
            batch = location / f"batch-{ordinal:04d}"
            http = folder / "http" / "halumem" / owner / str(session) / "writer" / str(ordinal)
            characters = sum(span["end"] - span["start"] for span in spans)
            counts["prepared_batches"] += 1
            if (batch / "complete.json").exists():
                counts["completed_batches"] += 1
            if (http / "request.json").exists():
                counts["recorded_writer_requests"] += 1
                counts["characters_in_recorded_requests"] += characters
            if (http / "response.json").exists():
                if not (http / "request.json").exists():
                    raise ValueError("Writer response lacks its original recorded request")
                counts["confirmed_writer_responses"] += 1
                counts["characters_in_confirmed_responses"] += characters
            failure_path = batch / "writer-failure.json"
            if failure_path.exists():
                failure = read_json(failure_path)
                message = failure["message"]
                kind = (
                    "context_unavailable_before_http"
                    if message.startswith("Context unavailable without loss:")
                    else "provider_output_incomplete"
                    if message.startswith("Provider output incomplete:")
                    else failure["type"]
                )
                failures[kind] += 1
                counts["first_attempt_writer_failed_batches"] += 1
                counts["additional_writer_attempts"] += failure["additional_attempts"]
                examples = failure_examples.setdefault(kind, [])
                if len(examples) < 3:
                    examples.append(str(failure_path.relative_to(folder)))
            plan_path = batch / "proposals.json"
            proposals = read_json(plan_path) if plan_path.exists() else []
            if plan_path.exists():
                if not isinstance(proposals, list):
                    raise ValueError("Recorded Writer proposal list has invalid shape")
                counts["writer_returned_proposal_list_batches"] += 1
                counts["writer_returned_empty_list_batches"] += not proposals
            counts["proposed_operations"] += len(proposals)
            receipts = sorted(batch.glob("receipt-*.json"))
            counts["recorded_operation_receipts"] += len(receipts)
            for proposal in proposals:
                proposed_actions[str(proposal.get("action", "missing"))] += 1
                for edit in proposal.get("edits", []):
                    proposed_edits[str(edit.get("operation", "missing"))] += 1
            for receipt_path in receipts:
                receipt = read_json(receipt_path)
                status = str(receipt.get("status", "missing"))
                receipt_statuses[status] += 1
                effect = receipt_effect(receipt)
                if receipt.get("replayed") is True:
                    counts["replayed_operation_receipts"] += 1
                if effect in {"committed", "replayed_commit"}:
                    counts[
                        "confirmed_committed_operations"
                        if effect == "committed"
                        else "original_commits_confirmed_by_replay"
                    ] += 1
                    index = int(receipt_path.stem.removeprefix("receipt-"))
                    if index >= len(proposals):
                        raise ValueError("Committed receipt lacks its original proposal")
                    committed_actions[str(proposals[index].get("action", "missing"))] += 1
                elif effect == "no_change":
                    counts["accepted_no_change_operations"] += 1
                elif effect == "rejected":
                    counts["rejected_operations"] += 1
                    reason = str(receipt.get("reason", "missing"))
                    rejections[
                        "ValidationError" if reason.startswith("ValidationError:") else reason
                    ] += 1
                else:
                    counts["other_or_unconfirmed_operation_receipts"] += 1
    return {
        "expected_sessions": len(sessions) if expected_sessions is not None else None,
        "counts": dict(counts),
        "not_yet_prepared_sessions": (
            len(sessions) - counts["prepared_sessions"] if expected_sessions is not None else None
        ),
        "pending_prepared_sessions": (
            counts["prepared_sessions"] - counts["maintenance_completed_sessions"]
        ),
        "pending_prepared_batches": counts["prepared_batches"] - counts["completed_batches"],
        "requests_without_confirmed_responses": (
            counts["recorded_writer_requests"] - counts["confirmed_writer_responses"]
        ),
        "first_attempt_writer_failures": dict(failures),
        "failure_example_paths": failure_examples,
        "receipt_statuses": dict(receipt_statuses),
        "rejection_reasons": dict(rejections),
        "proposed_actions": dict(proposed_actions),
        "committed_actions": dict(committed_actions),
        "proposed_local_operations": dict(proposed_edits),
        "interpretation": (
            "Prepared ranges are not confirmed model exposure. A recorded request is not a "
            "confirmed response. Committed effects and accepted no_change are separate; "
            "replay confirms an original commit without a second write. None establishes "
            "semantic correctness. Pending or failed opportunities remain."
        ),
    }


def recipe_writer_operations(
    folder: Path, owner: str, expected_sessions: Sequence[int] | None
) -> dict[str, Any]:
    """Read the common pipeline's existing checkpoints; never open its bank for writes."""
    counts: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    extraction_failures: Counter[str] = Counter()
    selection_failures: Counter[str] = Counter()
    receipts: Counter[str] = Counter()
    rejected: Counter[str] = Counter()
    proposed: Counter[str] = Counter()
    committed: Counter[str] = Counter()
    edits: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    sessions = set()
    calls: dict[str, dict[str, str]] = {}
    for path in (folder / "maintenance/halumem" / owner).glob("*/batch-*-calls.json"):
        for call in read_json(path):
            calls.setdefault(call["request_id"], {})[call["http_key"]] = (
                call["stage"].partition(":")[0])

    def count_exposure(request_id: str, http: Path, characters: int, *, parent: bool) -> None:
        observed = calls.get(request_id)
        if observed is None:
            observed = {str((http / stage).relative_to(folder / "http")): stage
                        for stage in (("extract", "select") if parent else ("extract", "edit"))}
        for key, stage in observed.items():
            label = {"extract": "extraction", "select": "selection", "edit": "writer"}[stage]
            request = folder / "http" / key / "request.json"
            response = folder / "http" / key / "response.json"
            counts[f"recorded_{label}_requests"] += request.exists()
            counts[f"confirmed_{label}_responses"] += response.exists()
            if stage == "edit":
                counts["characters_in_recorded_requests"] += characters * request.exists()
                counts["characters_in_confirmed_responses"] += characters * response.exists()

    def count_failures(request_id: str, state: dict[str, Any], *, parent: bool) -> None:
        for gap in state["unprocessed"]:
            if "reason" not in gap:
                continue  # Commit rejections come from their actual receipts.
            message = gap["reason"]
            kind = ("context_unavailable_before_http"
                    if message == "EDIT_MAINTENANCE_REQUEST_EXCEEDS_CAPACITY"
                    else "provider_output_incomplete"
                    if "Provider output incomplete:" in message else message)
            label = ("selection" if parent else "extraction"
                     if gap.get("phase") == "start"
                     or gap.get("phase", "").startswith("extract") else "writer")
            {"selection": selection_failures, "extraction": extraction_failures,
             "writer": failures}[label][kind] += 1
            counts[f"first_attempt_{label}_failed_batches"] += 1
            paths = examples.setdefault(kind, [])
            if len(paths) < 3:
                paths.append(f"banks/{owner}/memory.sqlite:{request_id}")

    bank = folder / "banks" / owner / "memory.sqlite"
    if bank.exists():
        with sqlite3.connect(bank.resolve().as_uri() + "?mode=ro", uri=True) as connection:
            rows = connection.execute(
                "SELECT key, value FROM store WHERE prefix LIKE ?", ("%.edit_maintenance",)
            ).fetchall()
        for key, raw in rows:
            _, request_id = json.loads(key)
            prefix = f"halumem/{owner}/"
            if not request_id.startswith(prefix):
                continue
            source_request, _, work = request_id.partition(":work:")
            ordinal, *batch_parts = source_request.removeprefix(prefix).split(":batch:")
            if expected_sessions is not None and int(ordinal) not in expected_sessions:
                continue
            sessions.add(int(ordinal))
            state = json.loads(raw)
            if "batches" in state:
                counts["batch_containers"] += 1
                counts["planned_subbatches"] += len(state["batches"])
                continue  # Parent receipts repeat actual child effects; count each leaf once.
            http = folder / "http/maintenance" / prefix / ordinal / f"batch-{batch_parts[0]}"
            for part in batch_parts[1:]:
                http = http / f"subbatch-{part}"
            characters = sum(s["end"] - s["start"] for s in state["binding"]["sources"])
            if "work_items" in state:
                counts["view_containers"] += 1
                counts["planned_work_items"] += len(state["work_items"])
                count_exposure(request_id, http, characters, parent=True)
                count_failures(request_id, state, parent=True)
                continue  # Work results repeat child receipts and proposals.
            counts["prepared_batches"] += 1
            counts["completed_batches"] += state["phase"] in {"complete", "incomplete"}
            counts["incomplete_maintenance_batches"] += state["phase"] == "incomplete"
            counts["prepared_characters"] += characters
            if work and request_id not in calls:
                calls[request_id] = {str((http / "edit" / f"work-{work}").relative_to(
                    folder / "http")): "edit"}
            count_exposure(request_id, http, characters, parent=False)
            count_failures(request_id, state, parent=False)
            proposals = state.get("proposals", [])
            if "proposals" in state:
                counts["writer_returned_proposal_list_batches"] += 1
                counts["writer_returned_empty_list_batches"] += not proposals
            counts["proposed_operations"] += len(proposals)
            for proposal in proposals:
                proposed[proposal["action"]] += 1
                edits.update(edit["operation"] for edit in proposal.get("edits", []))
            for index, receipt in enumerate(state["receipts"]):
                counts["recorded_operation_receipts"] += 1
                receipts[str(receipt.get("status", "missing"))] += 1
                counts["replayed_operation_receipts"] += receipt.get("replayed") is True
                effect = receipt_effect(receipt)
                if effect in {"committed", "replayed_commit"}:
                    counts["confirmed_committed_operations" if effect == "committed"
                           else "original_commits_confirmed_by_replay"] += 1
                    committed[proposals[index]["action"]] += 1
                elif effect == "no_change":
                    counts["accepted_no_change_operations"] += 1
                elif effect == "rejected":
                    counts["rejected_operations"] += 1
                    rejected[str(receipt.get("reason", "missing"))] += 1
                else:
                    counts["other_or_unconfirmed_operation_receipts"] += 1
    counts["prepared_sessions"] = len(sessions)
    for ordinal in sessions:
        done = folder / "maintenance/halumem" / owner / str(ordinal) / "complete.json"
        counts["maintenance_completed_sessions"] += done.exists()
        if done.exists():
            counts["upstream_extracted_outputs"] += len(read_json(done)["extracted_memories"])
        counts["official_completed_sessions"] += (
            folder / "evaluation/halumem" / owner / str(ordinal) / "complete.json"
        ).exists()
    return {
        "expected_sessions": len(expected_sessions) if expected_sessions is not None else None,
        "counts": dict(counts),
        "not_yet_prepared_sessions": (len(expected_sessions) - len(sessions)
                                     if expected_sessions is not None else None),
        "pending_prepared_sessions": len(sessions) - counts["maintenance_completed_sessions"],
        "pending_prepared_batches": counts["prepared_batches"] - counts["completed_batches"],
        "requests_without_confirmed_responses": (
            counts["recorded_writer_requests"] - counts["confirmed_writer_responses"]),
        "extraction_requests_without_confirmed_responses": (
            counts["recorded_extraction_requests"] - counts["confirmed_extraction_responses"]),
        "selection_requests_without_confirmed_responses": (
            counts["recorded_selection_requests"] - counts["confirmed_selection_responses"]),
        "first_attempt_writer_failures": dict(failures),
        "first_attempt_extraction_failures": dict(extraction_failures),
        "first_attempt_selection_failures": dict(selection_failures),
        "failure_example_paths": examples,
        "receipt_statuses": dict(receipts), "rejection_reasons": dict(rejected),
        "proposed_actions": dict(proposed), "committed_actions": dict(committed),
        "proposed_local_operations": dict(edits),
        "interpretation": "Common pipeline checkpoints read in SQLite mode=ro. Prepared ranges "
        "are not confirmed exposure; incomplete batches are not empty proposals. Commits and "
        "original commits confirmed by replay remain separate, and do not prove semantic success.",
    }


def scoring_terminal(folder: Path) -> Path:
    separate = folder / "terminal-score.json"
    return separate if separate.exists() else folder / "terminal.json"


def halumem_availability(root: Path, arms: Sequence[str]) -> dict[str, Any]:
    """Report partial operational availability without computing paired effects."""
    orders: dict[str, list[int]] = {}
    for arm in arms:
        for path in (root / arm / "banks").glob("*/session-order.json"):
            order = read_json(path)["original_ordinals"]
            owner = path.parent.name
            if owner in orders and orders[owner] != order:
                raise ValueError("Paired arms have different original session order")
            orders[owner] = order
    results: dict[str, Any] = {}
    for arm in arms:
        folder = root / arm
        config_path = folder / "actual-config.json"
        if not config_path.exists():
            results[arm] = {"status": "NOT_STARTED"}
            continue
        config = read_json(config_path)
        terminal_path = scoring_terminal(folder)
        per_user = {
            owner: writer_operations(folder, owner, orders.get(owner))
            for owner in config["halumem"]["users"]
        }
        totals: Counter[str] = Counter()
        for operations in per_user.values():
            totals.update(operations["counts"])
        results[arm] = {
            "status": read_json(terminal_path)["status"] if terminal_path.exists() else "UNSEALED",
            "prediction_phase": read_json(folder / "terminal-predict.json")
            if (folder / "terminal-predict.json").exists() else None,
            "per_user": per_user,
            "counts": dict(totals),
        }
    return results


def halumem_suite(root: Path, arms: Sequence[str]) -> dict[str, Any]:
    availability = halumem_availability(root, arms)
    missing = [
        arm
        for arm in arms
        if not (root / arm / "halumem-official-results.json").exists()
        or not scoring_terminal(root / arm).exists()
    ]
    if missing:
        return {
            "status": "INCOMPLETE",
            "missing_or_unsealed_arms": missing,
            "paired_effects": None,
            "operational_availability": availability,
        }
    results: dict[str, Any] = {}
    selected: list[str] | None = None
    for arm in arms:
        folder = root / arm
        terminal = read_json(scoring_terminal(folder))
        if terminal["status"] != "COMPLETED_EXPERIMENT_PHASE":
            raise ValueError("Cannot summarize an uncompleted experiment arm")
        config = read_json(folder / "actual-config.json")
        users = config["halumem"]["users"]
        if selected is None:
            selected = list(users)
        elif selected != users:
            raise ValueError("Paired arms do not contain the same user selection")
        official = HaluMemOfficial(Path(config["halumem"]["official_checkout"]), lambda _: {})
        raw = read_json(folder / "halumem-official-results.json")
        per_user = {}
        for owner in users:
            records = {
                key: copy.deepcopy([row for row in raw[key] if row["uuid"] == owner])
                for key in (
                    "memory_integrity_records",
                    "memory_accuracy_records",
                    "memory_update_records",
                    "question_answering_records",
                )
            }
            counts: dict[str, int] = {}
            checkpoints = list((folder / "evaluation" / "halumem" / owner).glob("*/complete.json"))
            expected_sessions = read_json(folder / "banks" / owner / "session-order.json")[
                "original_ordinals"
            ]
            if len(checkpoints) != len(expected_sessions):
                raise ValueError("Complete user history checkpoint denominator mismatch")
            for path in checkpoints:
                for name, value in read_json(path)["counts"].items():
                    counts[name] = counts.get(name, 0) + value
            aggregate = official.aggregate_results(records)
            per_user[owner] = {
                "official_score": aggregate["overall_score"],
                "official_aggregation_error": aggregate.get("official_aggregation_error"),
                **user_metrics(records, counts),
            }
        results[arm] = {
            "official_global_score": raw["overall_score"],
            "official_aggregation_error": raw.get("official_aggregation_error"),
            "opportunities": raw["supplemental_denominators"],
            "per_user": per_user,
        }
    pairs = {}
    assert selected is not None
    for first, second in PAIRS:
        if first not in results or second not in results:
            continue
        comparisons = {}
        for metric in METRICS:
            eligible = [
                owner
                for owner in selected
                if results[first]["per_user"][owner][metric] is not None
                and results[second]["per_user"][owner][metric] is not None
            ]
            comparisons[metric] = {
                "eligible_users": eligible,
                "excluded_no_denominator_users": [
                    owner for owner in selected if owner not in eligible
                ],
                "interval": paired_interval(
                    [results[first]["per_user"][owner][metric] for owner in eligible],
                    [results[second]["per_user"][owner][metric] for owner in eligible],
                )
                if eligible
                else None,
            }
        pairs[first + "_to_" + second] = comparisons
    return {
        "status": "COMPLETED_PAIRED_SOURCE_ANALYSIS",
        "arms": results,
        "pairs": pairs,
        "independent_users": len(selected),
        "judge_condition": "same Qwen family; not independent Judge",
        "operational_availability": availability,
    }


def longmemeval_categories(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    categories = sorted({row["question_type"] for row in predictions})
    subsets = {
        category: [row for row in predictions if row["question_type"] == category]
        for category in categories
    }
    subsets["abstention"] = [row for row in predictions if row["question_id"].endswith("_abs")]
    subsets["total"] = predictions
    results = {}
    for name, rows in subsets.items():
        valid = [row for row in rows if type(row.get("autoeval_label")) is bool]
        correct = sum(row["autoeval_label"] is True for row in valid)
        results[name] = {
            "opportunities": len(rows),
            "valid_judgments": len(valid),
            "correct": correct,
            "accuracy_all": ratio(correct, len(rows)),
            "accuracy_valid": ratio(correct, len(valid)),
        }
    return {
        "categories": results,
        "sampling_unit": "one connected shared-history component",
        "interval": None,
        "claim": (
            "descriptive selected-question subset; no independent-row CI or 500-question claim"
        ),
    }
