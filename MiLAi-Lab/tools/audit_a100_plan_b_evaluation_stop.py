"""Reconcile B's declared nominees, postfit-only answer labels and actual task comparisons."""
import argparse
import json
import math
import random
import sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

from audit_a100_plan_a_evaluation_stop import check_prediction


def read(path):
    return json.loads(Path(path).read_text())


def lines(path):
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("output",type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    plan = read(root/"b64-matched-training/plan.json")
    runtime = Path(plan["jobs"][0]["argv"][3]).parent.parent
    import tokenizers
    import transformers

    assert transformers.__version__ == "4.52.3" and tokenizers.__version__ == "0.21.4"
    sys.path.append(str(Path(plan["jobs"][0]["argv"][0]).parents[2]/"http-env/lib/python3.11/site-packages"))
    sys.path[:0] = [str(runtime/"tools"),str(runtime/"src")]
    from milai_lab.memory.literal_projection import expand_observation_state
    from milai_lab.methods.laya_memory_policy import project_operation_payload
    from milai_lab.methods.memory_control_learning import score_operation_predictions
    from quality_feedback import score_quality_feedback
    from retrieval_feedback import score_feedback

    labels = read(root/"original-plan-B-labels-training-v1.json")
    assert labels["passed"] and labels["all256_new_answer_comparisons_remain_unknown_in_closed_actual_fit_data"]
    closed_fit = read(root/"b-full-fit-closeout.json")
    dev = lines(root/"b64-matched-training/b0/dev.jsonl")
    feedback_dev = lines(root/"b64-matched-training/b0/feedback-dev.jsonl")
    assert len(dev) == 860 and len(feedback_dev) == 64
    assert dev == lines(root/"b64-matched-training/b1/dev.jsonl") and feedback_dev == lines(root/"b64-matched-training/b1/feedback-dev.jsonl")
    projected = {"dev":[project_operation_payload(row,"shared_actions") for row in dev],
        "feedback-dev":[project_operation_payload(row,"shared_actions") for row in feedback_dev]}
    curves,initials = {},{}
    for model in ("b0","b1"):
        history = read(root/f"{model}-seed0/history.json")
        points = []
        for point in history:
            update = point["optimizer_updates"]
            predictions = {}
            for split,rows in (("dev",dev),("feedback-dev",feedback_dev)):
                folder = root/f"{model}-seed0"/split/str(update)
                predictions[split] = [read(folder/f"{i}.json") for i in range(len(rows))]
                for row,prediction in zip(projected[split],predictions[split],strict=True):
                    check_prediction(row,prediction)
            operation = score_operation_predictions(dev,predictions["dev"])
            operation["reviewed_branch_pairs"] = score_feedback(dev,predictions["dev"],"delivery")
            quality = score_quality_feedback(feedback_dev,predictions["feedback-dev"],"delivery","quality-tie")
            assert operation == point["dev"]
            assert quality == point["feedback-dev"]["pure_quality"]["delivery"]
            points.append(dict(update=update,operation_family_macro_acceptance=operation["family_macro_acceptance"],
                pure_delivery_direction_accuracy=quality["directional"]["family_macro_state_pair_accuracy"]))
            if update == 0:
                initials[model] = predictions
        assert [point["update"] for point in points] == [0,17,33,66]
        entry = points[0]
        eligible = [point for point in points[1:] if point["operation_family_macro_acceptance"] >= entry["operation_family_macro_acceptance"]-.02]
        chosen = min(eligible,key=lambda point:(-point["pure_delivery_direction_accuracy"],point["update"])) if eligible else entry
        assert chosen["update"] == closed_fit["nominees"][model]["update"] == 33
        assert chosen["operation_family_macro_acceptance"] == closed_fit["nominees"][model]["operation_macro_acceptance"]
        assert chosen["pure_delivery_direction_accuracy"] == closed_fit["nominees"][model]["pure_delivery_direction_accuracy"]
        curves[model] = dict(points=points,nominee=chosen,nonzero_nominee_and2pp_operation_guard_recomputed=True)
        print("B_SAVED_CURVES_AND_PREDECLARED_U33_NOMINATION_VERIFIED",model,flush=True)
    for split in ("dev","feedback-dev"):
        a,b = initials["b0"][split],initials["b1"][split]
        assert all(x["input_tokens"] == y["input_tokens"] and x["logits"] == y["logits"] and x["choice"] == y["choice"] for x,y in zip(a,b,strict=True))

    records = [record for segment in ("pilot8","remaining56") for record in read(root/f"b64-{segment}-branches/outcomes-for-review.json")["records"]]
    by_readout = {record["readout"]:record for record in records}
    assert len(by_readout) == 384
    answer = read(root/"b64-answer-review-full.json")
    delivery = {record["index"]:record for record in read(root/"b64-delivery-author-guide.json")["reviews"]}
    postfit = read(root/"b64-postfit-quality-diagnosis.json")
    panels = {model:dict(cross=Counter(),same_packet_answer_comparisons=Counter(),same_packet_pairs=0,rows=[]) for model in ("b0","b1")}
    all_answer_grades = Counter()
    below_coarse_S = []
    material_rank = {"I":0,"P":1,"S":2}
    for family,reviewed in answer["families"].items():
        annotation = reviewed["review"]
        materials = delivery[annotation["index"]]["grades"]
        members = [by_readout[path] for path in reviewed["readouts"]]
        assert len(members) == len(annotation["grades"]) == len(materials) == 6
        assert all(record["family"] == family for record in members)
        for i,grade in enumerate(annotation["grades"]):
            all_answer_grades[grade] += 1
            assert (grade == "F") == (members[i]["status"] == "FAILED")
            if grade == "C" and materials[i] != "S":
                below_coarse_S.append(dict(family=family,family_index=annotation["index"],binding_position=i,delivery_grade=materials[i],
                    actual_readout=members[i]["readout"],answer_note=annotation["notes"][i],material_target=delivery[annotation["index"]]["target"]))
        for pair_index,(model,left,right) in enumerate((("b0",0,1),("b1",2,1),("b0",3,4),("b1",5,4))):
            answer_comparison = annotation["comparisons"][pair_index]
            x,y = materials[left],materials[right]
            comparison = "U" if "U" in (x,y) else "T" if material_rank[x] == material_rank[y] else "L" if material_rank[x] > material_rank[y] else "R"
            same = members[left]["actual_delivered_packet"] == members[right]["actual_delivered_packet"]
            table = panels[model]
            table["cross"][comparison+"_delivery__"+answer_comparison+"_answer"] += 1
            if same:
                table["same_packet_pairs"] += 1
                table["same_packet_answer_comparisons"][answer_comparison] += 1
            table["rows"].append(dict(family=family,family_index=annotation["index"],state_position=pair_index//2,
                delivery_comparison=comparison,answer_comparison=answer_comparison,left_answer_grade=annotation["grades"][left],
                right_answer_grade=annotation["grades"][right],literal_packet_objects_equal=same,
                left_readout=members[left]["readout"],right_readout=members[right]["readout"]))
    assert dict(all_answer_grades) == answer["grades"] == postfit["answer_grades"]
    assert all_answer_grades["F"] == 11
    for model,table in panels.items():
        table["cross"] = dict(table["cross"])
        table["same_packet_answer_comparisons"] = dict(table["same_packet_answer_comparisons"])
        table["answer_counts"] = dict(Counter(row["answer_comparison"] for row in table["rows"]))
        table["delivery_counts"] = dict(Counter(row["delivery_comparison"] for row in table["rows"]))
        table["known_direction_reversals"] = sum(row["delivery_comparison"] in {"L","R"} and row["answer_comparison"] in {"L","R"} and row["delivery_comparison"] != row["answer_comparison"] for row in table["rows"])
        table["answer_directions_inside_coarse_delivery_ties"] = sum(row["delivery_comparison"] == "T" and row["answer_comparison"] in {"L","R"} for row in table["rows"])
        assert table == postfit["panels"][model]
        assert table["answer_counts"] == answer["pair_counts_by_panel"][model]
    assert below_coarse_S == postfit["complete_answers_below_coarse_delivery_sufficient"] and len(below_coarse_S) == 27
    assert not postfit["closed_B0_B1_fit_data_changed"] and not answer["running_and_closed_fit_data_changed"]
    assert postfit["new_training_rows"] == answer["new_training_rows"] == 0
    print("B_POSTFIT384_ANSWER_VS_DELIVERY_LABEL_VIEWS_RECONCILED_WITHOUT_BACKFILL",flush=True)

    choices = read(root/"b-task32-closed-choices.json")
    choice_plan = read(root/"b-task32-evaluation-plan.json")
    rows = lines(choice_plan["data"])
    by_capture = {str(Path(position["capture"]).resolve()):position for position in choices["positions"] if position["status"] == "ACTUAL_PRE_HANDOFF_EXPORTED"}
    assert len(rows) == len(by_capture) == 31
    task = read(root/"b-task32-results.json")
    readout_map = read(root/"b-task32-all-readouts.json")
    origins = Counter()
    for model in ("initial","b0","b1"):
        folder = root/"b-task32-evaluation"/model
        assert read(folder/"run.json")["completed_states"] == 31
        for index,row in enumerate(rows):
            position = by_capture[str(Path(row["metadata"]["capture"]).resolve())]
            call = read(Path(position["capture"])/"call.json")
            expected = project_operation_payload(row,"shared_actions")
            payload = read(folder/"calls"/str(index)/"input.json")
            assert payload == {key:expected[key] for key in ("state","questions")}
            expanded = expand_observation_state(payload["state"])
            assert expanded.pop("action_bindings") == call["initial_actions"] and expanded == call["initial_observation"]
            prediction = read(folder/"calls"/str(index)/"output.json")
            check_prediction(expected,prediction)
            selected = position["model_choices"][model]
            assert prediction["choice"] == selected["action"]["id"] and selected["action"] in call["initial_actions"]
            binding = position["bindings"][selected["binding_index"]]
            assert binding["action"] == selected["action"] and model in binding["models"]
            path = binding["readout"]["result"]
            target, = [entry for entry in task["conditions"][model]["positions"] if entry["family"] == position["family"]]
            assert path == target["readout"] == readout_map[model][position["family"]]
            original = read(path)
            assert original["status"] == binding["readout"]["status"] and original["answer"] == binding["readout"]["answer"]
            origins[binding["origin"]] += 1
    task_counts = {name:condition["complete"] for name,condition in task["conditions"].items()}
    assert task_counts == {"raw_delivery":14,"initial":14,"b0":13,"b1":13}
    assert all(len(condition["positions"]) == condition["planned_families"] == 32 for condition in task["conditions"].values())
    assert task["later_A_repeat_never_used"] and not task["B192_256_extra_seeds_or_adoption"] and not task["deployment_adoption"]
    assert task["new_first_answers_source_reviewed"] == 5

    reviews = read(root/"task-dev64/source-author-reviews.json")
    development = read(root/"task-dev64-development-selection.json")
    paired = read(root/"task-dev64-paired-selection-progress.json")
    families = reviews["cases"]
    assert len(families) == 64 and len({row["family"] for row in families}) == 64
    full64_counts = {}
    for model in ("fixed-prefix","incumbent-delivery-u16","b0-u33","b1-u33","e3-aggregate-u32"):
        grades = [family["reviews"][model]["answer_grade"] for family in families]
        count = grades.count("C")
        assert count == development["complete"][model] == paired["conditions"][model]["confirmed_complete"]
        assert dict(Counter(grades)) == paired["conditions"][model]["grade_counts"]
        full64_counts[model] = count
    assert full64_counts == {"fixed-prefix":25,"incumbent-delivery-u16":25,"b0-u33":33,"b1-u33":32,"e3-aggregate-u32":40}
    differences = [int(row["reviews"]["b1-u33"]["answer_grade"] == "C")-int(row["reviews"]["b0-u33"]["answer_grade"] == "C") for row in families]
    rng = random.Random(0)
    draws = sorted(sum(rng.choices(differences,k=64))/64 for _ in range(20000))
    comparison = paired["comparisons"]["b1-u33-minus-b0-u33"]
    assert comparison["gains"] == differences.count(1) and comparison["losses"] == differences.count(-1)
    assert comparison["delta"] == sum(differences)/64 == -1/64
    assert comparison["family_bootstrap_95_percent"] == [draws[499],draws[19499]]
    assert not development["candidate_adopted"]
    out = dict(passed=True,status="B_SAVED_U33_NOMINATION_POSTFIT_ONLY_ANSWER_LABELS_AND_FIRST_TASK_STOP_EVIDENCE_RECONCILED",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),curves=curves,
        original924_initial_full_input_token_sequences_logits_and_argmax_equal=True,
        postfit_all384_first_answer_grades=dict(all_answer_grades),postfit_delivery_answer_panels=panels,
        complete_answers_below_coarse_material_S=27,postfit_labels_never_backfilled_to_closed_training_data=True,
        literal_same_packet_pairs={model:table["same_packet_pairs"] for model,table in panels.items()},
        known_direction_reversals={model:table["known_direction_reversals"] for model,table in panels.items()},
        actual_saved_models=3,actual_saved_full_before_menu_binding_choices_per_model=31,actual_saved_task32_binding_checks=93,
        task32_binding_origin_counts=dict(origins),task32_Source_author_complete=task_counts,
        task32_families=32,missing_state_retained=True,new_task32_first_answers=5,later_A_better_repeat_excluded=True,
        autonomous64_first_outcome_source_review_counts=full64_counts,
        B1_minus_B0_autonomous64=dict(gains=differences.count(1),losses=differences.count(-1),ties=differences.count(0),
            delta=-1/64,family_bootstrap_95_percent=[draws[499],draws[19499]],draws=20000,analysis_seed=0),
        B192_256_extra_B_seeds_or_adoption_triggered=False,
        scope="Numerical and identity reconciliation of existing Source-author labels and first outputs. Feedback-dev selection is not autonomous success; old32 readouts are exposed/conditional. DEV64 is development selection, not independent confirmation. Same packet with different full bindings witnesses first-generation variation, not a best-answer resample. No independent human relabeling.",
        new_training_model_tokenizer_GPU_HTTP_business_or_original_ledger_calls=0,
        original_Source_labels_models_or_firsts_changed=False,full763_line_completion_proven=False,no_sha_validation=True,goal_complete=False)
    with args.output.open("x") as stream:
        json.dump(out,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print(out["status"],"u33both;384answerspostfit;B32=13/13;B64=33/32;no192/256/adopt")


if __name__ == "__main__":
    main()
