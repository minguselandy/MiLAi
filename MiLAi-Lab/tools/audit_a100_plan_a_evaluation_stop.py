"""Reconcile saved A predictions, nominal selection and first task outcomes without inference."""
import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def lines(path):
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream]


def check_prediction(row,prediction):
    question, = row["questions"].values()
    assert list(prediction["logits"]) == list(prediction["probabilities"]) == list(question["criteria"])
    assert all(math.isfinite(value) for field in ("logits","probabilities") for value in prediction[field].values())
    assert prediction["choice"] == max(prediction["probabilities"],key=prediction["probabilities"].get)
    assert prediction["truncated"] is False and 0 < prediction["input_tokens"] <= 16384


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("output",type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    lab = root.parent.parent
    plan = read(root/"a-seed0-plan.json")
    runtime = Path(plan["jobs"][0]["argv"][3]).parent.parent
    import tokenizers
    import transformers

    assert transformers.__version__ == "4.52.3" and tokenizers.__version__ == "0.21.4"
    sys.path.append(str(Path(plan["jobs"][0]["argv"][0]).parents[2]/"http-env/lib/python3.11/site-packages"))
    sys.path[:0] = [str(runtime/"tools"),str(runtime/"src")]
    from analyze_conditional_unit_fit import family_balanced_accuracy
    from evaluate_bounded_laya import score_applicability_predictions
    from milai_lab.datasets.conditional_applicability import score_condition_pairs
    from milai_lab.memory.literal_projection import expand_observation_state
    from milai_lab.methods.laya_memory_policy import project_operation_payload
    from retrieval_mixture import project_applicability_row,project_mixed_row,score_mixed_predictions

    full_fit = read(root/"a-full-fit-closeout.json")
    saved = read(root/"a-saved-evaluation-closeout.json")
    native,reviewed = lines(root/"a-newdev128-native/matrix.jsonl"),lines(root/"a-newdev128-reviewed16/matrix.jsonl")
    native_pairs,reviewed_pairs = lines(root/"a-newdev128-native/condition-pairs.jsonl"),lines(root/"a-newdev128-reviewed16/condition-pairs.jsonl")
    assert len(native) == len(reviewed) == 8744
    families = {row["metadata"]["family"] for row in native}
    declared = read(root/"a-newdev128-groups.json")
    assert families == {row["source_group"] for row in declared["groups"]} and len(families) == 128
    assert all(row["metadata"]["split"] == "dev" for row in native)
    train_families = {row["metadata"]["family"] for row in lines(root/"a0-conditional/train.jsonl")}
    assert not families & train_families
    q64 = read(lab/"data/manifests/a100-reserved64-native-results-20261107-v1.json")
    reservation = read(q64["protocol"])
    assert not families & {row["source_group"] for row in reservation["reserved64_metadata"]}
    reviewed_cells = supplemental_labels = 0
    for a,b in zip(native,reviewed,strict=True):
        assert all(a[key] == b[key] for key in ("state","questions"))
        if a["gold"]:
            assert a == b
        if a != b:
            assert not a["gold"] and not a["metadata"]["native_judgments"]
            review = b["metadata"]["source_author_review"]
            for anchor in review["anchors"]:
                text = a["state"]["candidate"][anchor["field"]]
                start,end = anchor["range"]
                assert text[start:end] == anchor["quote"]
            reviewed_cells += 1
            supplemental_labels += bool(b["gold"])
    assert sum(pair["kind"] == "change" for pair in native_pairs) == 0
    assert sum(pair["kind"] == "change" for pair in reviewed_pairs) == 2

    common = lines(root/"a-matched/a0/dev.jsonl")
    assert (root/"a-matched/a0/dev.jsonl").read_bytes() == (root/"a-matched/a1/dev.jsonl").read_bytes()
    projected_common = [project_mixed_row(row,"shared_actions") for row in common]
    conditional_indices = [i for i,row in enumerate(common) if row["metadata"]["task"] == "instruction_applicability"]
    conditional = [common[i] for i in conditional_indices]
    assert len({row["metadata"]["family"] for row in conditional}) == 32
    assert not families & {row["metadata"]["family"] for row in common}
    original = Path(read(root/"p0-plan.json")["profile"]["source_lengths"]).parents[2]
    old_pairs = lines(original/"conditional-dev32-review-v1/reviewed-v1/condition-pairs.jsonl")
    old_semantics = read(original/"conditional-dev32-review-v1/actual-audit-v1.json")["change_audit"]
    supported = [record["pair"] for record in old_semantics if record["source_author_pair_status"] == "supported_request_condition_change"]
    curves = {}
    for model in ("a0","a1"):
        points = []
        for recorded in full_fit["arms"][model]["points"]:
            update = recorded["update"]
            folder = root/f"{model}-seed0/dev/{update}"
            predictions = [read(folder/f"{i}.json") for i in range(len(common))]
            for row,prediction in zip(projected_common,predictions,strict=True):
                check_prediction(row,prediction)
            macro = family_balanced_accuracy(conditional,[predictions[i] for i in conditional_indices])
            mixed = score_mixed_predictions(common,predictions)
            assert macro["family_macro_balanced_accuracy"] == recorded["family_macro_balanced_accuracy"]
            assert mixed == recorded["mixed_dev"]
            operation = mixed["by_task"]["memory_operation"]["family_macro_acceptance"]
            assert operation == recorded["operation_family_macro_acceptance"]
            points.append(dict(update=update,family_macro_balanced_accuracy=macro["family_macro_balanced_accuracy"],operation_family_macro_acceptance=operation))
        entry = points[0]
        assert entry["update"] == 0 and [point["update"] for point in points] == [0,702,1403,2104,2805]
        eligible = [point for point in points if entry["operation_family_macro_acceptance"]-point["operation_family_macro_acceptance"] <= .02]
        chosen = max(eligible,key=lambda point:(point["family_macro_balanced_accuracy"],-point["update"]))
        assert chosen["update"] == full_fit["arms"][model]["nominee"]["update"] == 2104
        curves[model] = dict(points=points,nominee=chosen,predeclared2pp_operation_guard_passed=True)
        print("A_DECLARED_CURVE_AND_NOMINATION_RECOMPUTED",model,2104,flush=True)
    saved_views = {}
    for model in ("initial","a0","a1"):
        folder = root/"a-saved-evaluation"/model/"newdev128"
        run = read(folder/"run.json")
        assert run["status"] == "COMPLETED" and run["completed_states"] == run["planned_states"] == 8744
        assert run["checkpoint"] == saved["models"][model]["checkpoint"]
        predictions = []
        for index,row in enumerate(native):
            expected = project_applicability_row(row,"shared_actions")
            assert read(folder/"calls"/str(index)/"input.json") == {key:expected[key] for key in ("state","questions")}
            prediction = read(folder/"calls"/str(index)/"output.json")
            check_prediction(expected,prediction)
            predictions.append(prediction)
        views = {}
        for name,rows,pairs in (("native",native,native_pairs),("reviewed16",reviewed,reviewed_pairs)):
            result = dict(family_balanced=family_balanced_accuracy(rows,predictions),applicability=score_applicability_predictions(rows,predictions),
                changed_pairs=score_condition_pairs(rows,[p for p in pairs if p["kind"] == "change"],predictions),
                stable_pairs=score_condition_pairs(rows,[p for p in pairs if p["kind"] == "stable"],predictions),
                unknown_pairs=score_condition_pairs(rows,[p for p in pairs if p["kind"] == "unknown"],predictions))
            assert result == saved["models"][model]["newdev128"][name]
            views[name] = result
        if model == "initial":
            old_predictions = [read(root/"a0-seed0/dev/0"/f"{i}.json") for i in range(len(common))]
        else:
            old_predictions = [read(root/"a-saved-evaluation"/model/"common-dev/calls"/str(i)/"output.json") for i in range(len(common))]
        old_score = score_condition_pairs(conditional,supported,[old_predictions[i] for i in conditional_indices])
        assert old_score == saved["models"][model]["old8_supported_changes"]
        saved_views[model] = dict(checkpoint=run["checkpoint"],actual_saved_predictions=8744,newdev128=views,old8_supported_changes=old_score)
        print("A_SAVED8744_WHOLE_INPUT_AND_BOTH_LABEL_VIEWS_RECOMPUTED",model,flush=True)

    choices = read(root/"a-task32-closed-choices-v2.json")
    choice_plan = read(root/"a-task32-evaluation-plan.json")
    choice_rows = lines(choice_plan["data"])
    by_capture = {str(Path(position["capture"]).resolve()):position for position in choices["positions"] if position["status"] == "ACTUAL_PRE_HANDOFF_EXPORTED"}
    assert len(choice_rows) == len(by_capture) == 31
    task_results = read(root/"a-task32-results-v2.json")
    readout_map = read(root/"a-task32-all-readouts-v2.json")
    binding_origins = Counter()
    for model in ("a0","a1"):
        folder = root/"a-task32-evaluation"/model
        run = read(folder/"run.json")
        assert run["status"] == "COMPLETED" and run["completed_states"] == 31
        for index,row in enumerate(choice_rows):
            position = by_capture[str(Path(row["metadata"]["capture"]).resolve())]
            call = read(Path(position["capture"])/"call.json")
            payload = read(folder/"calls"/str(index)/"input.json")
            expected = project_operation_payload(row,"shared_actions")
            assert payload == {key:expected[key] for key in ("state","questions")}
            expanded = expand_observation_state(payload["state"])
            assert expanded.pop("action_bindings") == call["initial_actions"]
            assert expanded == call["initial_observation"]
            prediction = read(folder/"calls"/str(index)/"output.json")
            check_prediction(expected,prediction)
            selected = position["model_choices"][model]
            assert prediction["choice"] == selected["action"]["id"]
            assert selected["action"] in call["initial_actions"]
            binding = position["bindings"][selected["binding_index"]]
            assert binding["action"] == selected["action"] and model in binding["models"]
            actual_path = binding["readout"]["result"]
            assert actual_path == readout_map[model][position["family"]]
            task, = [task for task in task_results["conditions"][model]["positions"] if task["family"] == position["family"]]
            assert task["family"] == position["family"] and task["readout"] == actual_path
            actual = read(actual_path)
            assert actual["answer"] == binding["readout"]["answer"] and actual["status"] == binding["readout"]["status"]
            if binding["origin"] == "closed_raw_collection":
                assert selected["action"]["kind"] == "HANDOFF" and selected["action"]["parameters"] == {}
                assert actual_path == readout_map["raw_delivery"][position["family"]]
            binding_origins[binding["origin"]] += 1
    for model,condition in task_results["conditions"].items():
        assert len(condition["positions"]) == condition["planned_families"] == 32
        assert [position["index"] for position in condition["positions"]] == list(range(32))
        assert all(position["complete"] == (position["answer_status"] == "complete") for position in condition["positions"])
        assert sum(position["complete"] for position in condition["positions"]) == condition["complete"]
    assert {name:condition["complete"] for name,condition in task_results["conditions"].items()} == {"raw_delivery":14,"initial":14,"a0":15,"a1":15}
    a,b = task_results["conditions"]["a0"]["positions"],task_results["conditions"]["a1"]["positions"]
    gains = sum(y["complete"] and not x["complete"] for x,y in zip(a,b,strict=True))
    losses = sum(x["complete"] and not y["complete"] for x,y in zip(a,b,strict=True))
    assert gains == losses == 0
    registry = read(root/"task-first-outcome-registry-v2.json")
    assert len(registry["later_duplicate_attempts"]) == 1
    for duplicate in registry["later_duplicate_attempts"]:
        assert duplicate["literal_packet_and_full_intervention_equal"]
        assert duplicate["later_attempt_status"] == "UNNECESSARY_REPEAT_RETAINED_NOT_PRIMARY"
        earlier_path = duplicate["earlier_primary"]["readout"]["result"]
        assert Path(earlier_path).is_file() and Path(duplicate["later_readout"]).is_file()
        earlier,later = read(earlier_path),read(duplicate["later_readout"])
        earlier_branch,later_branch = read(earlier["branch_result"]),read(later["branch_result"])
        assert earlier_branch["intervention"] == later_branch["intervention"]
        assert earlier_branch["result"].keys() == later_branch["result"].keys()
        for key in earlier_branch["result"].keys()-{"process_id","budget_before","budget_after"}:
            assert earlier_branch["result"][key] == later_branch["result"][key]
        assert earlier_branch["result"]["retrieval_result"] == later_branch["result"]["retrieval_result"]
        for model in duplicate["models"]:
            position = next(position for position in task_results["conditions"][model]["positions"] if position["family"] == duplicate["family"])
            assert position["readout"] == earlier_path and position["readout"] != duplicate["later_readout"]
    assert not task_results["A20k_extra_seeds_or_J_adopted"] and not task_results["deployment_adoption"]
    assert task_results["new_training_rows"] == 0 and saved["training_from_development"] is False
    out = dict(passed=True,status="ORIGINAL_PLAN_A_CURVES_SAVED_FULL_INPUTS_LABEL_VIEWS_EARLIEST_TASK_OUTCOMES_AND_STOP_RULES_RECONCILED",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),curves=curves,saved_models=saved_views,
        new_development_families=128,native_matrix_cells_each=8744,total_saved_new128_first_predictions_verified=26232,
        entire_saved_model_inputs_and_finite_argmax_heads_equal=True,native_known_gold_and_source_author_supplements_separate=True,
        supplemental_reviewed_cells=reviewed_cells,supplemental_known_labels=supplemental_labels,
        no_overlap_with_A_TRAIN_old32_or_reserved64_query_families=True,
        new128_native_change_pairs=0,new128_source_author_change_pairs=2,
        predeclared_curve_nominees_each=2104,checkpoint_source_selection="Original frozen dev-family balanced metric, earliest tie,2pp operation guard; not selected by final confirmation or best seed.",
        saved_prediction_reuse_across_label_views=True,old8_scope="Exposed Source-author-supported regression diagnostics, not new confirmation.",
        actual_full_before_all_bindings_NN_choice_reconciled=62,actual_task_binding_origin_counts=dict(binding_origins),
        reused_empty_parameter_HANDOFF_raw_outcome_explicitly_verified=True,
        task32_manual_Source_review_complete_counts={name:condition["complete"] for name,condition in task_results["conditions"].items()},
        task32_A1_minus_A0=dict(gains=0,losses=0,ties=32,difference=0.,exposed_family_bootstrap_interval=[0.,0.]),
        raw_task_denominator32_missing_state_retained=True,historical_one_unnecessary_repeat_retained_and_excluded_from_primary=True,
        historical_repeat_entire_actual_intervention_and_return_packet_reread_literal_equal=True,
        historical_repeat_only_process_identity_and_distinct_accounting_snapshots_differ=True,
        compact_actual_state_indices_joined_to_full32_panel_by_family_identity=True,
        current_task_labels_reannotated_or_claimed_independent_human=False,
        A20k_extra_A_seeds_J_or_deployment_adoption_triggered=False,training_from_DEV_or_TEST=False,
        scope="Source/data and numerical reconciliation of actual saved first outputs; conditional readouts and author labels remain development exposure, not autonomous Host, unseen corpus, independent human scoring or a proof of zero population effect. Current Mem2Act unaffected.",
        new_model_tokenizer_GPU_HTTP_business_or_original_ledger_calls=0,no_sha_validation=True,full763_line_completion_proven=False,goal_complete=False)
    with args.output.open("x") as stream:
        json.dump(out,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print(out["status"],"26232saved/62bindings;A0=A1:15/32;no20k/seeds/J/adopt")


if __name__ == "__main__":
    main()
