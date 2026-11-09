"""Compare all planned native LME first scores with explicit paired coverage and costs."""
import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def comparison(rows):
    common = [row for row in rows if row["primary_scored"] and row["fixed_scored"]]
    coverage = Counter((row["primary_scored"], row["fixed_scored"]) for row in rows)
    gains = sum(row["primary_correct"] and not row["fixed_correct"] for row in common)
    losses = sum(row["fixed_correct"] and not row["primary_correct"] for row in common)
    correct = {method: sum(row[method + "_correct"] for row in rows if row[method + "_scored"])
        for method in ("primary", "fixed")}
    scored = {method: sum(row[method + "_scored"] for row in rows) for method in ("primary", "fixed")}
    lower = sum((row["primary_correct"] if row["primary_scored"] else 0)
        - (row["fixed_correct"] if row["fixed_scored"] else 1) for row in rows)
    upper = sum((row["primary_correct"] if row["primary_scored"] else 1)
        - (row["fixed_correct"] if row["fixed_scored"] else 0) for row in rows)
    return dict(planned=len(rows), own_scored_counts=scored, own_correct_counts=correct,
        own_conditional_accuracy={method: correct[method] / scored[method] if scored[method] else None for method in correct},
        own_all_planned_bounds={method: [correct[method] / len(rows),
            (correct[method] + len(rows) - scored[method]) / len(rows)] for method in correct},
        paired_coverage=dict(both_scored=coverage[(True, True)], primary_only_scored=coverage[(True, False)],
            fixed_only_scored=coverage[(False, True)], neither_scored=coverage[(False, False)]),
        common_scored=dict(count=len(common), gains=gains, losses=losses, ties=len(common)-gains-losses,
            primary_correct=sum(row["primary_correct"] for row in common), fixed_correct=sum(row["fixed_correct"] for row in common),
            primary_minus_fixed=(gains-losses) / len(common) if common else None,
            conditional_on_both_methods_successfully_scored=True),
        all_planned_primary_minus_fixed_bounds=[lower / len(rows), upper / len(rows)],
        all_planned_difference_bound_numerators=[lower, upper], independent_Source_confidence_interval=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    finalized = root / "external-own-policy-v1/finalized-lme-v1"
    primary = read(finalized / "primary-seed0-u32-scores/driver.json")
    fixed = read(finalized / "fixed-prefix-scores/driver.json")
    primary_census = read(root / "lme-primary-native-operations-cost-census-v1.json")
    fixed_census = read(root / "lme-fixed-native-operations-cost-census-v1.json")
    questions = [json.loads(line) for line in (finalized / "primary-seed0-u32-predictions/offline-input/questions.jsonl").read_text().splitlines()]
    fixed_questions = [json.loads(line) for line in (finalized / "fixed-prefix-predictions/offline-input/questions.jsonl").read_text().splitlines()]
    assert questions == fixed_questions
    assert len(primary["cases"]) == len(fixed["cases"]) == len(questions) == 451
    rows = []
    for index, (question, a, b) in enumerate(zip(questions, primary["cases"], fixed["cases"], strict=True)):
        assert question["id"] == a["question_id"] == b["question_id"]
        row = dict(row=index, question_id=question["id"], domain=question["domain"],
            native_question_type=question["question_type"])
        for name, case in (("primary", a), ("fixed", b)):
            known = case["status"] == "COMPLETED"
            assert known or case["status"].startswith("UNSCORED_FAILED_")
            assert known or case["score"] is None
            row.update({name + "_status": case["status"], name + "_scored": known,
                name + "_correct": case["score_bool"] if known else None,
                name + "_valid_UNKNOWN": case["is_unknown"] if known else None})
        rows.append(row)
    overall = comparison(rows)
    method_summaries = {}
    for name, census in (("primary", primary_census), ("fixed", fixed_census)):
        native = census["native_aggregate"]
        assert native["scored"] == overall["own_scored_counts"][name]
        assert native["correct_scored"] == overall["own_correct_counts"][name]
        assert native["all_planned_score_bounds"] == overall["own_all_planned_bounds"][name]
        assert native["native_complete_cohort_metrics"] is None
        method_summaries[name] = {key: census[key] for key in (
            "method", "prediction_status_counts", "scoring_status_counts", "native_aggregate", "Reader", "failed_Readers", "Judge",
            "selected_action_counts", "operation_kind_status_counts", "termination_reason_counts", "native_retrieval_usage_counts",
            "returned_packet_evidence_kind_counts", "owner_totals", "actual_NN_forwards", "local_NN_input_tokens", "local_model_loads")}
        method_summaries[name].update(total_actual_Reader_Judge_HTTP=census["Reader"]["actual_HTTP_attempts"]+census["Judge"]["actual_HTTP_attempts"],
            total_known_Reader_Judge_tokens=census["Reader"]["total_tokens"]+census["Judge"]["total_tokens"])
    result = dict(status="LME_ALL451_FIRST_NATIVE_SCORES_PAIRED_COVERAGE_OPERATIONS_AND_INVOCATION_COST_COMPARISON_CLOSED",
        timestamp_utc=datetime.now(timezone.utc).isoformat(), positions=451, overall=overall,
        by_domain={domain: comparison([row for row in rows if row["domain"] == domain]) for domain in sorted({row["domain"] for row in rows})},
        by_native_question_type={kind: comparison([row for row in rows if row["native_question_type"] == kind]) for kind in sorted({row["native_question_type"] for row in rows})},
        methods=method_summaries, per_position=rows,
        primary_verified_cuda_model_invocation_interval_hours=primary_census["verified_cuda_model_invocation_interval_hours"],
        primary_declared_GPU2_invocation_interval_hours=primary_census["declared_GPU2_job_interval_hours"],
        primary_initial_CPU_condition_mismatch_loads=primary_census["CPU_condition_mismatch_loads"],
        primary_local_decision_head_scalar_scores=primary_census["local_decision_head_scalar_scores"],
        primary_frozen_audit_metadata_correction=primary_census["frozen_audit_metadata_correction"],
        primary_retained_physical_step_snapshot_gap_positions=list(range(1, 10)),
        missing_outcomes_fabricated_or_first_records_rewritten=False,
        exposure="Known development-exposed Small:451 public queries sharing200 histories across two Source pools; not451 independent users, unseen Small/Medium or original-paper model reproduction.",
        metric_scope="Given query retrieval followed by frozen separate Reader and native Judge as required. Not autonomous Host. Own scored subsets have different missing positions. The369-common-scored comparison is conditional on both methods completing, and missingness need not be random. Bounds retain every planned position and do not impute program failures as gold negatives or UNKNOWN. No query bootstrap is presented as an independent Source-family interval.",
        cost_scope="Prediction plus scoring invocations only; all actual serial continuations, first failures, model loads and measured parent CPU included. No nested/native/residual CPU added twice. Source setup, offline audit/report, storage/archive, training and unknown author/launch CPU remain outside these subtotals. GPU invocation/reservation intervals include IO/Host waits; Host GPU busy time and monetary cost unmeasured. Different service times do not establish a controlled latency effect.",
        all_external_experiments_or_full_project_costs_complete=False,
        analyzer=str(Path(__file__).resolve()), primary_census=str(root / "lme-primary-native-operations-cost-census-v1.json"),
        fixed_census=str(root / "lme-fixed-native-operations-cost-census-v1.json"),
        new_model_Reader_Judge_or_HTTP_calls=0, ledger_opened_or_written=False,
        no_sha_validation=True, goal_complete=False)
    with args.output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print("LME_NATIVE451_COMPARISON", overall)


if __name__ == "__main__":
    main()
