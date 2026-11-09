"""Compare both frozen full400 Mem2Act methods after native Source and score audits close."""

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path


def read(path: Path | str) -> dict:
    return json.loads(Path(path).read_text())


def verify_earliest_primary_prefix(protocol: dict, driver: dict) -> dict:
    checkpoint_path = (
        Path(protocol["stage_directory"]).parent.parent
        / "mem2act-primary-first100-earliest-case-records-v1.json"
    )
    checkpoint = read(checkpoint_path)
    assert driver["method"] == "primary"
    assert len(checkpoint["records"]) == 100
    assert checkpoint["records"] == driver["cases"][:100]
    assert all(row["status"] in ("COMPLETED", "FAILED") for row in checkpoint["records"])
    return {
        "checkpoint": str(checkpoint_path),
        "first100_entire_earliest_case_records_literal_equal": True,
        "scope": "Saved running-stage earliest prefix; no new task, retry, score or all400 gate.",
    }


def reference_components(
    coverage: dict, references: list[dict], sessions: list[dict]
) -> list[list[str]]:
    cases = coverage["cases"]
    assert len(cases) == len({row["qa_id"] for row in cases}) == 400
    parent = list(range(400))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    source_sessions = defaultdict(list)
    for index, session in enumerate(sessions):
        for source in session["original_conversation_ids"]:
            source_sessions[source].append(index)
    by_source = defaultdict(list)
    for index, (row, reference) in enumerate(zip(cases, references, strict=True)):
        assert row["qa_id"] == reference["qa_id"]
        requested = set(reference["source_conversation_ids"])
        matched = sorted({item for source in requested for item in source_sessions[source]})
        missing = sorted(source for source in requested if not source_sessions[source])
        assert matched == row["session_indices"] and missing == row["missing_source_ids"]
        assert len(requested) == row["requested_sources"]
        exposed = requested | {
            source for item in matched for source in sessions[item]["original_conversation_ids"]
        }
        for source in exposed:
            by_source[source].append(index)
    for members in by_source.values():
        first = find(members[0])
        for index in members[1:]:
            parent[find(index)] = first
    grouped = defaultdict(list)
    for index, row in enumerate(cases):
        grouped[find(index)].append(row["qa_id"])
    components = list(grouped.values())

    def normalize(values):
        return sorted(tuple(sorted(component)) for component in values)

    assert normalize(components) == normalize(coverage["source_components"])
    assert len(components) == coverage["counts"]["source_components"] == 341
    assert (
        dict(Counter(str(len(component)) for component in components))
        == (coverage["component_sizes"])
    )
    assert sum(map(len, components)) == 400
    return components


def summarize_method(protocol: dict, method: str) -> dict:
    audit = read(protocol[method + "_full_audit"])
    score_audit = read(protocol[method + "_score_audit"])
    closure = read(protocol[method + "_closure"])
    assert audit["passed"] and score_audit["passed"] and closure["passed"]
    scores = read(protocol[method + "_scores"])
    driver = read(Path(protocol[method + "_predictions"]) / "driver.json")
    earliest_prefix = (
        verify_earliest_primary_prefix(protocol, driver) if method == "primary" else None
    )
    assert driver["method"] == scores["method"] == audit["method"] == method
    assert driver["planned_positions"] == len(driver["cases"]) == len(scores["records"]) == 400
    assert audit["positions"] == score_audit["positions"] == 400
    owner = read(audit["actual_owner"])
    assert owner["client_CPU_recorded"] and owner["validated_stage_terminal"]
    assert not any(Path("/proc", str(owner[key])).exists() for key in ("pid", "child_pid"))
    assert closure["all400_entire_earliest_case_records_literal_equal"]
    owners = [read(path) for path in closure["ancestor_owners_oldest_first"]]
    assert owners and owners[-1] == owner
    for ancestor in owners:
        assert ancestor["client_CPU_recorded"] and "exit_code" in ancestor
        assert not any(Path("/proc", str(ancestor[key])).exists() for key in ("pid", "child_pid"))
    credits = {}
    for case, score in zip(driver["cases"], scores["records"], strict=True):
        assert case["status"] in ("COMPLETED", "FAILED")
        assert case["qa_id"] == score["qa_id"] and case["row"] == score["row"]
        assert case["status"] == score["native_status"]
        assert case["proposed_business_calls"] == score["all_proposed_business_calls"]
        assert score["completed_strict_call_match"] == (
            case["status"] == "COMPLETED" and score["metrics"]["strict_call_match"]
        )
        credits[case["qa_id"]] = score
    assert len(credits) == 400
    successes = sum(row["completed_strict_call_match"] for row in credits.values())
    assert successes == scores["completed_strict_call_matches"]
    assert scores["completed_strict_call_match_rate"] == successes / 400
    response_callbacks = sum(row["decoded_provider_responses"] for row in audit["records"])
    known_tokens = sum(row["known_HTTP_tokens"] for row in audit["records"])
    assert known_tokens == sum(ancestor["known_generation_tokens"] for ancestor in owners)
    return {
        "method": method,
        "positions": 400,
        "native_first_status": dict(Counter(case["status"] for case in driver["cases"])),
        "completed_strict_call_matches": successes,
        "completed_strict_call_match_rate": successes / 400,
        "strict_intent_match_rate_including_failed_Host": (
            scores["strict_intent_match_rate_including_failed_Host"]
        ),
        "parameter_value_F1_task_macro": scores["parameter_value_F1_task_macro"],
        "BLEU1_canonical_JSON_task_macro": scores["BLEU1_canonical_JSON_task_macro"],
        "proposed_call_cardinality_counts": dict(
            Counter(str(len(row["all_proposed_business_calls"])) for row in credits.values())
        ),
        "failed_Host_with_strictly_correct_intent_not_promoted": sum(
            row["native_status"] == "FAILED" and row["metrics"]["strict_call_match"]
            for row in credits.values()
        ),
        "actual_HTTP": response_callbacks,
        "provider_response_callbacks_recorded": response_callbacks,
        "provider_response_callback_scope": (
            "Native vllm_response events, including known error/partial responses. "
            "Not delivered_model_requests or shared generation admissions; "
            "an independent network transmission count is not established by this field. "
            "The existing frozen audit field decoded_provider_responses is retained verbatim."
        ),
        "known_Host_tokens": known_tokens,
        "known_tokens_equal_all_actual_paid_owner_ancestors": True,
        "actual_returned_NN_predictions": audit["returned_NN_predictions_audited"],
        "actual_returned_NN_input_tokens": sum(
            row["control"]["actual_returned_input_tokens"] for row in audit["records"]
        ),
        "interrupted_decisions_retained": audit["interrupted_decisions_retained"],
        "paired_first_decoded_provider_requests_equal": (
            audit["paired_first_decoded_provider_requests_equal"]
        ),
        "whole_child_CPU_seconds_already_paid": sum(
            ancestor["whole_child_CPU_seconds"] for ancestor in owners
        ),
        "measured_parent_CPU_seconds_already_paid": sum(
            ancestor["parent_CPU_seconds_through_billing"] for ancestor in owners
        ),
        "native_CPU_included_in_whole_not_readded": [
            ancestor["already_recorded_native_CPU"] for ancestor in owners
        ],
        "actual_owner_ancestry_including_retained_failures": (
            closure["ancestor_owners_oldest_first"]
        ),
        "saved_running_stage_earliest_primary_prefix": earliest_prefix,
        "credits": credits,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    protocol = read(args.protocol)
    coverage = read(protocol["offline_source_coverage"])
    with Path(protocol["offline_references"]).open() as stream:
        references = [json.loads(line) for line in stream]
    with Path(protocol["released_history"]).open() as stream:
        sessions = [json.loads(line) for line in stream]
    assert len(references) == 400 and len(sessions) == 429
    components = reference_components(coverage, references, sessions)
    gate_paths = [
        protocol[name]
        for name in (
            "fixed_closure",
            "primary_closure",
            "fixed_full_audit",
            "primary_full_audit",
            "fixed_score_audit",
            "primary_score_audit",
        )
    ]
    pending = [path for path in gate_paths if not Path(path).exists()]
    common = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "protocol": str(args.protocol.resolve()),
        "released_tasks": 400,
        "common_bank_sessions": 429,
        "reference_lineage_components": 341,
        "reference_lineage_component_size_counts": coverage["component_sizes"],
        "all400_components_rederived_from_declared_IDs_and_full_released_session_metadata": True,
        "missing_declared_IDs_retained_in_lineage_not_dropped_as_unmatched": True,
        "offline_Source_coverage_counts_retained": coverage["counts"],
        "shared_common_bank_is_not400_independent_users_or341_independent_experiments": True,
        "query_iid_or_component_independence_confidence_interval_computed": False,
        "original_Source_tasks_labels_or_firsts_changed": False,
        "new_model_tokenizer_GPU_HTTP_business_or_original_ledger_calls": 0,
        "no_sha_validation": True,
        "full763_line_completion_proven": False,
        "goal_complete": False,
    }
    if args.preflight_only:
        report = {
            **common,
            "passed": True,
            "status": "REFERENCE_LINEAGE_AND_FROZEN_COMPARISON_INPUT_PREFLIGHT_ONLY",
            "pending_actual_required_gates": pending,
            "actual_all800_first_predictions_or_scores_certified": False,
            "actual_task_metrics_computed": False,
        }
    else:
        assert not pending, pending
        assert all(read(path)["passed"] for path in gate_paths)
        fixed, primary = [summarize_method(protocol, name) for name in ("fixed", "primary")]
        assert fixed["credits"].keys() == primary["credits"].keys()
        per_task = []
        for qa_id in fixed["credits"]:
            left, right = fixed["credits"][qa_id], primary["credits"][qa_id]
            per_task.append(
                {
                    "qa_id": qa_id,
                    "fixed_completed_strict": left["completed_strict_call_match"],
                    "primary_completed_strict": right["completed_strict_call_match"],
                    "fixed_status": left["native_status"],
                    "primary_status": right["native_status"],
                }
            )
        components_summary = []
        for component in components:
            n = len(component)
            components_summary.append(
                {
                    "qa_ids": component,
                    "tasks": n,
                    "fixed_completed_strict_rate": sum(
                        fixed["credits"][qa_id]["completed_strict_call_match"]
                        for qa_id in component
                    )
                    / n,
                    "primary_completed_strict_rate": sum(
                        primary["credits"][qa_id]["completed_strict_call_match"]
                        for qa_id in component
                    )
                    / n,
                }
            )
        gains = sum(
            row["primary_completed_strict"] and not row["fixed_completed_strict"]
            for row in per_task
        )
        losses = sum(
            row["fixed_completed_strict"] and not row["primary_completed_strict"]
            for row in per_task
        )
        report = {
            **common,
            "passed": True,
            "status": "BOTH_FROZEN400_NATIVE_ADAPTED_SCORES_AND_DESCRIPTIVE_PAIRED_COMPARISON",
            "methods": {
                method["method"]: {key: value for key, value in method.items() if key != "credits"}
                for method in (fixed, primary)
            },
            "paired_task_gains": gains,
            "paired_task_losses": losses,
            "paired_task_ties": 400 - gains - losses,
            "completed_strict_difference": (gains - losses) / 400,
            "per_task": per_task,
            "reference_component_balanced_descriptive_rates": {
                method: sum(row[method + "_completed_strict_rate"] for row in components_summary)
                / len(components_summary)
                for method in ("fixed", "primary")
            },
            "reference_components": components_summary,
            "scope": (
                "Frozen MiLAi-adapted complete-call metrics, not paper TA or leaderboard scores. "
                "All400 tasks and all original zero/invalid/multiple/failed proposals retained. "
                "Correct intent in a failed Host trajectory is not completed success. "
                "Reference-component balanced rates only describe a declared partition; "
                "the common bank and possible cross-session retrieval do not establish "
                "independent users/components. No IID or lineage-component CI, inferential "
                "superiority, adoption, unseen-user generalization or business execution claim. "
                "Native/model/load CPU is included in whole child and not readded. "
                "Archives and final project costs remain separate required closeouts."
            ),
        }
    with args.output.open("x") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(report["status"], "400tasks/341reference-components;no independence CI", flush=True)


if __name__ == "__main__":
    main()
