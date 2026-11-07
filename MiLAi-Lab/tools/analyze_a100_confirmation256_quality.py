"""Join immutable manual/native records and estimate paired family differences."""
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

folder = Path(sys.argv[1]).resolve()
read = lambda path: json.loads(Path(path).read_text())
names = ["fixed-prefix", "e3-aggregate-u32", "e3-aggregate-seed1-u32", "e3-aggregate-seed2-u32"]
mean_name = "within-family-three-seed-mean"
quality_labels = ["C", "I", "Q", "W", "F", "U"]
material_labels = ["S", "P", "I", "U"]
scope_path = folder / "common-source-question-scope-inventory-all256-v2.json"
scope = read(scope_path)
guides = read(folder / "source-author-task-guides-prefix256-v1.json")["records"]
families = [row["family"] for row in scope["records"]]
assert len(families) == len(set(families)) == len(guides) == 256
assert [row["index"] for row in scope["records"]] == list(range(256))
mask = [row["common_stress_withhold_complete_credit"] for row in scope["records"]]
assert all(type(flag) is bool for flag in mask)
assert sum(mask) == 122
assert [i for i, flag in enumerate(mask) if flag] == scope["common_stress_flagged_indices"]
native_f1_closeout = read(folder / "native-answer-f1-all4-methods-closeout-v1.json")
closeouts, reviews, native, raw, methods = {}, {}, {}, {}, {}

def literal_binding(bound, actual, baseline_local_index):
    if baseline_local_index:
        assert bound["index"] == actual["index"] - 8
        assert {k: v for k, v in bound.items() if k != "index"} == {k: v for k, v in actual.items() if k != "index"}
    else:
        assert bound == actual

for name in names:
    baseline = name == "fixed-prefix"
    base = folder if baseline else folder / name
    path = base / ("anchor-all256-source-author-quality-closeout-v1.json" if baseline else "all256-source-author-quality-closeout-v1.json")
    closeout = closeouts[name] = read(path)
    review = read(closeout["whole_manual_review"])
    rows = reviews[name] = review["records"]
    raw_path = base / ("anchor-all256-review-input-v1.json" if baseline else "audit-all256-v1/review-input.json")
    raw_rows = raw[name] = read(raw_path)["records"]
    failure_path = base / ("anchor-all256-failed-last-inputs-v1.json" if baseline else "audit-all256-v1/failed-last-inputs.json")
    failed = {row["index"]: row for row in read(failure_path)["records"]}
    audit = read(closeout["whole_mechanical_binding"])
    f1 = native[name] = read(folder / f"native-answer-f1-{name}-v1.json")
    assert closeout["method"] == name
    assert len(rows) == len(raw_rows) == len(f1["records"]) == closeout["positions"] == audit["positions"] == 256
    assert review["full256_quality_closed"]
    assert [row["index"] for row in rows] == list(range(256))
    if not baseline:
        assert audit["all_actual_NN_inputs_complete_and_untruncated"]
        assert audit["Source_Saver_Store_world_and_application_invariants"]
        assert audit["first_provider_requests_literal_equal"] == 256
    credits = []
    for i, (row, actual, common, f1_row) in enumerate(zip(rows, raw_rows, scope["records"], f1["records"], strict=True)):
        literal_binding(row["original_bound_result_record"], actual, baseline and 8 <= i < 32)
        assert row["family"] == actual["family"] == common["family"] == f1_row["family"] == guides[i]["family"]
        assert row["guide_record"] == guides[i]
        assert actual["public_question"] == common["public_question"]
        assert actual["native_question_id"] == f1_row["question_id"]
        assert common["native_split"] == f1_row["native_split"]
        assert actual["result_status"] == f1_row["native_status"]
        assert row["source_author_not_blind_or_independent"]
        if baseline and i < 8:
            assert row["whole_actual_answer_and_all_received_packets_read"]
            assert row["no_new_answer_or_model_retry"]
        else:
            assert row["entire_actual_answer_and_all_received_non_system_provider_messages_read"]
            assert not row["other_method_labels_inherited"]
        assert row["quality"] in quality_labels and row["material"] in material_labels
        assert (row["quality"] == "F") == (actual["result_status"] != "COMPLETED") == f1_row["first_failure_scored_as_empty"]
        if row["quality"] == "F":
            literal_binding(row["failed_last_provider_binding"], failed[i], baseline and 8 <= i < 32)
            assert f1_row["literal_original_full_answer_or_failed_empty"] == "" and f1_row["Answer F1"] == 0
        else:
            assert f1_row["literal_original_full_answer_or_failed_empty"] == actual["answer"]
        credits.append({"index": i, "family": row["family"], "native_split": common["native_split"],
            "quality": row["quality"], "material": row["material"],
            "common_stress_withhold_complete_credit": mask[i],
            "main_C_credit": int(row["quality"] == "C"),
            "common_scope_stress_C_credit": int(row["quality"] == "C" and not mask[i])})
    assert credits == closeout["derived_per_position_credits"]
    quality = {label: sum(row["quality"] == label for row in rows) for label in quality_labels}
    material = {label: sum(row["material"] == label for row in rows) for label in material_labels}
    assert quality == closeout["quality_counts"] and material == closeout["material_counts"]
    assert quality["F"] == len(failed) == f1["first_failed_empty_positions"]
    assert sum(row["main_C_credit"] for row in credits) == closeout["main_whole_task_C"]
    assert sum(row["common_scope_stress_C_credit"] for row in credits) == closeout["common_source_scope_stress"]["C_credit"]
    assert f1["Answer F1"] == native_f1_closeout["methods"][name]["Answer F1"]
    methods[name] = {"quality_closeout": str(path), "whole_manual_review": closeout["whole_manual_review"],
        "whole_native_review_input": str(raw_path), "whole_mechanical_binding": closeout["whole_mechanical_binding"],
        "positions": 256, "quality_counts": quality, "material_counts": material,
        "main_C": quality["C"], "main_C_rate": quality["C"] / 256,
        "common_scope_stress_C": closeout["common_source_scope_stress"]["C_credit"],
        "common_scope_stress_C_rate_full256": closeout["common_source_scope_stress"]["C_credit"] / 256,
        "quality_by_material": closeout["quality_by_material"],
        "native_partition_strata": closeout["native_partition_strata"],
        "native_answer_F1_separate_metric": f1["Answer F1"], "guide_timing": closeout["guide_timing"]}

metric_names = ["main_C", "common_scope_stress_C", "material_S", "material_P", "material_I", "material_U"]
values = np.array([[[int(reviews[name][i]["quality"] == "C"),
    int(reviews[name][i]["quality"] == "C" and not mask[i]),
    *[int(reviews[name][i]["material"] == label) for label in material_labels]] for name in names] for i in range(256)], dtype=float)
assert values.shape == (256, 4, 6)
values = np.concatenate([values, values[:, 1:4].mean(axis=1, keepdims=True)], axis=1)
all_names = names + [mean_name]
contrasts = names[1:] + [mean_name]
strata = {"all256": list(range(256)),
    "native_dev185": [i for i, row in enumerate(scope["records"]) if row["native_split"] == "dev"],
    "native_train71": [i for i, row in enumerate(scope["records"]) if row["native_split"] == "train"]}
assert [len(indices) for indices in strata.values()] == [256, 185, 71]
analyses = {}
for stratum, indices in strata.items():
    subset = values[indices]
    n = len(indices)
    differences = subset[:, 1:] - subset[:, [0]]
    draws = np.random.default_rng(0).integers(0, n, size=(20000, n))
    # Shared family multiplicities keep every method, seed and metric paired.
    weights = np.stack([np.bincount(draw, minlength=n) for draw in draws])
    boot = (weights @ differences.reshape(n, -1) / n).reshape(20000, 4, 6)
    bounds = np.percentile(boot, [2.5, 97.5], axis=0)
    per_method = {}
    for j, name in enumerate(all_names):
        averages = subset[:, j].mean(axis=0)
        per_method[name] = {"rates": dict(zip(metric_names, averages.tolist(), strict=True)),
            "sum_of_family_credits": dict(zip(metric_names, subset[:, j].sum(axis=0).tolist(), strict=True))}
        if name in names:
            selected = [reviews[name][i] for i in indices]
            per_method[name].update(quality_counts={label: sum(row["quality"] == label for row in selected) for label in quality_labels},
                material_counts={label: sum(row["material"] == label for row in selected) for label in material_labels})
    comparisons = {}
    for j, name in enumerate(contrasts):
        comparisons[name] = {}
        for k, metric in enumerate(metric_names):
            delta = differences[:, j, k]
            increased = np.array(indices)[delta > 0].tolist()
            decreased = np.array(indices)[delta < 0].tolist()
            tied = np.array(indices)[delta == 0].tolist()
            item = {"difference": float(delta.mean()), "difference_pp": float(100 * delta.mean()),
                "CI95_pp": [float(100 * bounds[0, j, k]), float(100 * bounds[1, j, k])],
                "increased_families": len(increased), "decreased_families": len(decreased), "tied_families": len(tied),
                "increased_indices": increased, "decreased_indices": decreased, "tied_indices": tied}
            assert len(increased) + len(decreased) + len(tied) == n
            if name != mean_name:
                assert int(delta.sum()) == len(increased) - len(decreased)
                item["binary_transition_counts"] = {f"baseline{left}_candidate{right}": int(((subset[:, 0, k] == left) & (subset[:, j + 1, k] == right)).sum()) for left in (0, 1) for right in (0, 1)}
            else:
                item["fractional_within_family_seed_mean_not_binary_discordance"] = True
            comparisons[name][metric] = item
        if name != mean_name:
            comparisons[name]["quality_transition_counts"] = {label: dict(Counter(reviews[name][i]["quality"] for i in indices if reviews[names[0]][i]["quality"] == label)) for label in quality_labels}
            comparisons[name]["material_transition_counts"] = {label: dict(Counter(reviews[name][i]["material"] for i in indices if reviews[names[0]][i]["material"] == label)) for label in material_labels}
    analyses[stratum] = {"families": n, "common_stress_flagged": sum(mask[i] for i in indices),
        "all_original_stratum_positions_remain_in_denominator": True,
        "bootstrap_draws": 20000, "seed": 0, "interval": "two-sided unadjusted percentile95",
        "same_family_draws_across_methods_seeds_metrics": True,
        "methods": per_method, "comparisons_against_fixed_prefix": comparisons}

per_position = [{"index": i, "family": families[i], "native_split": scope["records"][i]["native_split"],
    "common_stress_withhold_complete_credit": mask[i],
    "methods": {name: {"quality": reviews[name][i]["quality"], "material": reviews[name][i]["material"],
        "native_status": raw[name][i]["result_status"], "main_C_credit": int(values[i, j, 0]),
        "common_scope_stress_C_credit": int(values[i, j, 1])} for j, name in enumerate(names)},
    "within_family_three_seed_mean": dict(zip(metric_names, values[i, 4].tolist(), strict=True))} for i in range(256)]
out = {"status": "ALL4_FULL256_FIRST_OUTCOME_WHOLE_TASK_MATERIAL_AND_PAIRED_FAMILY_STATISTICS_CLOSED",
    "timestamp_utc": datetime.now(timezone.utc).isoformat(), "positions_each": 256,
    "unique_source_families": 256, "whole_manual_judgments": 1024, "methods": methods,
    "common_scope_inventory": str(scope_path), "same_fixed122_mask_and_full_denominators_all_methods": True,
    "per_position": per_position, "paired_family_statistics": analyses,
    "main_source_author_all4_quality_and_paired_stats_closed": True,
    "whole_native_raw_result_provider_failure_guide_and_derived_record_bindings_literal_equal": True,
    "only_declared_binding_index_exception": "fixed-prefix global8..31 retain local0..23; every other record field equals final global record",
    "first_native_failures_retained_by_method": {name: methods[name]["quality_counts"]["F"] for name in names},
    "primary_remains_frozen_seed0_not_reselected": True,
    "native_F1_closeout_unchanged": str(folder / "native-answer-f1-all4-methods-closeout-v1.json"),
    "statistical_scope": "Fixed256uniqueSourcefamilies; one reviewed first outcome per method/family. Three learnedseeds averaged within family before bootstrap, never768/1024 independent sources. Conditional on commonE1initialization and fixedtrainingfits; family bootstrap does not estimate full-chain or seed/population variance. DEV185/TRAIN71 are original native partitions, not study TRAIN/DEVELOPMENT/CONFIRMATION roles. Stratum intervals exploratory; no result-based selection or multiplicity-adjusted guarantee.",
    "rubric_scope": "C denotes whole-task Source-supported success, including precise Source-limited answers on applicable questions. MaterialS/P/I/U and native COMPLETED/F are separate. U receives noC and is not automatically a confirmed factual error. All coherent literal-question valid paths accepted; guides not a unique exhaustive gold. NativeanswerF1 remains separate unchanged full-string overlap.",
    "review_limitations": "Source-author judgments are not blind or independent. Common122mask followed baseline80/primary16 semantic review; earlier guide82/101/231 additions have disclosed differing exposure timing. Seed1/2guides preceded their corresponding semantic reviews, not all model runs or other-method answers. CIs condition on these labels and fixedmask and do not remove rubric/Source/exposure uncertainty. No nativeTEST or old64reservedquery semantics opened.",
    "adopted": False, "frozen_methods_scoring_budgets_N_changed": False,
    "new_model_or_HTTP_calls": 0, "ledger_opened_or_written": False,
    "native_test_opened": False, "old64_reserved_query_semantics_opened": False,
    "no_sha_validation": True, "goal_complete": False}
target = Path(sys.argv[2]).resolve()
with target.open("x") as stream:
    json.dump(out, stream, ensure_ascii=False, indent=2)
    stream.write("\n")
print("ALL4_WHOLE_QUALITY_AND_FAMILY_STATS_CLOSED", {name: (m["main_C"], m["common_scope_stress_C"], m["material_counts"]["S"]) for name, m in methods.items()})
for name, metrics in analyses["all256"]["comparisons_against_fixed_prefix"].items():
    print(name, {metric: {key: values[key] for key in ("difference_pp", "CI95_pp", "increased_families", "decreased_families", "tied_families")} for metric, values in metrics.items() if metric in ("main_C", "common_scope_stress_C", "material_S")})
