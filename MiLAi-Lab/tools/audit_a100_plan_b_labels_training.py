"""Recompile B's actual delivery supervision and audit full inputs, losses and real draws."""
import argparse
import copy
import json
import math
import sys
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path


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
    prepared = root/"b64-matched-training"
    plan = read(prepared/"plan.json")
    runtime = Path(plan["jobs"][0]["argv"][3]).parent.parent
    import tokenizers
    import transformers

    assert transformers.__version__ == "4.52.3" and tokenizers.__version__ == "0.21.4"
    sys.path.append(str(Path(plan["jobs"][0]["argv"][0]).parents[2]/"http-env/lib/python3.11/site-packages"))
    sys.path[:0] = [str(runtime/"tools"),str(runtime/"src")]
    from prepare_retrieval_feedback import compile_reached_feedback
    from quality_feedback import quality_counts,quality_event_weights,validate_quality_pool
    trainer_source = (runtime/"tools/train_bounded_laya.py").read_text()
    assert 'write_json(args.output / "training-plan.json", stages)' in trainer_source
    assert "for checkpoint_step, windows in stages:" in trainer_source

    branch = read(root/"original-plan-B-actual-branches-v1.json")
    assert branch["passed"] and branch["shared_baseline_actual_outcomes"] == 128
    records,raw = [],[]
    for segment in ("pilot8","remaining56"):
        bound = read(root/f"b64-{segment}-branches/outcomes-for-review.json")
        records.extend({**record,"segment":segment} for record in bound["records"])
        raw.extend(lines(root/f"b64-{segment}-branches/raw-selected-states.jsonl"))
    assert len(records) == 384 and len(raw) == 128
    by_capture = {str(Path(row["metadata"]["path"]).resolve()):row for row in raw}
    assert len(by_capture) == 128 and all(row["metadata"]["split"] == "train" for row in raw)
    families = defaultdict(list)
    for record in records:
        families[record["family"]].append(record)
    guide = read(root/"b64-delivery-author-guide.json")
    references = read(root/"b64-scoring-reference-input.json")["records"]
    assert [review["index"] for review in guide["reviews"]] == list(range(64))
    reviews_by_family = {references[review["index"]]["family"]:review for review in guide["reviews"]}
    assert set(families) == set(reviews_by_family)
    source_reviews = {name:read(prepared/f"{name}-source-reviews.json")["states"] for name in ("b0","b1")}
    by_review_capture = {name:{review["capture"]:review for review in reviews} for name,reviews in source_reviews.items()}
    assert all(len(reviews) == 128 for reviews in source_reviews.values())
    rank = {"I":0,"P":1,"S":2}
    delivery_counts = {name:Counter() for name in ("b0","b1")}
    shared_baselines = []
    resource_checks = 0
    for family,members in families.items():
        review = reviews_by_family[family]
        assert len(members) == len(review["grades"]) == 6
        for offset in (0,3):
            triad = members[offset:offset+3]
            assert [record["choice_role"] for record in triad] == ["current_argmax","baseline","alternative"]
            capture, = {record["capture"] for record in triad}
            baseline = triad[1]
            shared_baselines.append(baseline["readout"])
            for panel,index in (("b0",0),("b1",2)):
                current = triad[index]
                a,b = review["grades"][offset+index],review["grades"][offset+1]
                expected = "unknown" if "U" in (a,b) else "tie" if a == b else "left" if rank[a] > rank[b] else "right"
                source_review = by_review_capture[panel][capture]
                comparison, = source_review["comparisons"]
                left,right = current["first_action"]["id"],baseline["first_action"]["id"]
                assert source_review["event_id"] == by_capture[capture]["metadata"]["event_id"]
                assert source_review["reviewer"] == guide["reviewer"]
                assert source_review["outcomes"] == {left:current["origin"],right:baseline["origin"]}
                assert comparison["left"] == left and comparison["right"] == right
                basis = comparison["basis"]
                assert basis["quality_before_resource_tiebreak"] == {"answer":"unknown","delivery":expected}
                assert basis["delivery_grades"] == {"left":a,"right":b}
                assert basis["content_target"] == review["target"] and basis["source_review"] == review["review"]
                assert basis["actual_records"] == [{"segment":record["segment"],"record_index":record["record_index"],"first_readout_status":record["status"]} for record in (current,baseline)]
                for side,record in (("left",current),("right",baseline)):
                    resource = basis["resource_order"][side]
                    assert type(resource["wire_tokens"]) is int and resource["wire_tokens"] > 0
                    assert resource["retrieval_generation_requests"] == resource["retrieval_generation_tokens"] == 0
                    assert 0 <= resource["read_operations"] <= resource["acquisition_operations"]
                    resource_checks += 1
                delivery_counts[panel][expected] += 1
    assert len(shared_baselines) == len(set(shared_baselines)) == 128
    assert delivery_counts == {"b0":Counter(tie=117,left=5,right=4,unknown=2),"b1":Counter(tie=103,left=2,right=21,unknown=2)}

    old_root = Path(plan["inherited_E3_run"]).parents[2]
    old_rows = lines(old_root/"e1-matched-data-v1/train.jsonl")
    old_dev = lines(old_root/"e1-matched-data-v1/dev.jsonl")
    old_feedback_dev = lines(old_root/"e1-matched-data-v1/feedback-dev.jsonl")
    assert len(old_rows) == 400 and sum("feedback" in row for row in old_rows) == 200
    next_id = max(row["metadata"]["state_id"] for row in old_rows+old_dev+old_feedback_dev)+1
    panels,weights,quality = {},{},{}
    for name in ("b0","b1"):
        compiled = compile_reached_feedback(raw,source_reviews[name])
        assert len(compiled) == 128
        for index,row in enumerate(compiled):
            row["metadata"].update(state_id=next_id+index,component="reviewed_feedback")
            comparison, = row["feedback"]["comparisons"]
            assert comparison["answer"] == "unknown"
        actual = lines(prepared/name/"train.jsonl")
        assert actual == copy.deepcopy(old_rows)+compiled
        assert len(actual) == 528 and len({row["metadata"]["event_id"] for row in actual}) == 528
        assert lines(prepared/name/"dev.jsonl") == old_dev
        assert lines(prepared/name/"feedback-dev.jsonl") == old_feedback_dev
        assert not {row["metadata"]["family"] for row in actual}&{row["metadata"]["family"] for row in old_dev+old_feedback_dev}
        validate_quality_pool(actual+old_feedback_dev)
        new_counts = quality_counts(actual[400:],"delivery","quality-tie")
        assert new_counts == plan["new_feedback"][name]
        panels[name] = actual
        quality[name] = dict(new128=new_counts,all528=quality_counts(actual,"delivery","quality-tie"))
        weights[name] = quality_event_weights(actual,"delivery","quality-tie",.25,normalize_total=False)
        assert math.isclose(sum(weight for row,weight in zip(actual,weights[name],strict=True) if "feedback" in row)/528,1.0)
        assert math.isclose(sum(weight for row,weight in zip(actual,weights[name],strict=True) if "feedback" not in row)/528,.25)
        print("B_RAW_TRIAD_REVIEWS_AND_COMPILED128_FEEDBACK_REPLAYED",name,new_counts,flush=True)
    assert all(all(a[key] == b[key] for key in ("state","questions","gold","metadata")) for a,b in zip(panels["b0"],panels["b1"],strict=True))
    assert panels["b0"][:400] == panels["b1"][:400] == old_rows
    assert weights["b0"] == weights["b1"]
    original_plan = read(old_root/"e3-matched-training-v1/plan.json")
    original_run = read(plan["inherited_E3_run"])
    actual_runs,arms,schedules,option_orders = {},{},{},{}
    for job in plan["jobs"]:
        name = job["name"]
        expected = list(original_plan["plans"][0]["argv"])
        expected[3:7] = [str(runtime/"tools/train_bounded_laya.py"),str(prepared/name),plan["common_initialization"],job["output"]]
        expected[expected.index("--compute-phase")+1] = job["compute_phase"]
        expected[expected.index("--optimizer-updates")+1] = "66"
        begin,end = expected.index("--eval-at-updates")+1,expected.index("--seed")
        expected[begin:end] = ["17","33","66"]
        expected.extend(["--device","cuda:0","--parallel-mode","single","--precision","bf16"])
        assert job["argv"] == expected
        folder = Path(job["output"])
        run,compute,driver = read(folder/"run.json"),read(folder/"compute.json"),read(root/f"{name}-seed0-driver.json")
        assert run["status"] == driver["status"] == "COMPLETED" and driver["returncode"] == 0
        assert all(not Path("/proc",str(driver[key])).exists() for key in ("pid","child_pid"))
        assert driver["job"] == job
        assert run["base_checkpoint"] == original_plan["common_initialization"] == plan["common_initialization"]
        for field in ("objective","feedback_target","replay_weight","replay_objective","pair_supervision","pair_mass_mode"):
            assert run[field] == original_run[field]
        assert run["objective"] == "pair" and run["feedback_target"] == "delivery" and run["pair_supervision"] == "quality-tie"
        assert run["pair_mass_mode"] == "component-sum" and run["replay_weight"] == .25 and run["replay_objective"] == "set"
        assert run["precision"] == "bf16" and run["parallel_mode"] == "single" and run["device"] == "cuda:0"
        assert run["parameter_precision"] == "float32" and set(run["parameter_dtypes"]) == {"torch.float32"}
        assert run["batch_size"] == 2 and run["gradient_accumulation"] == 8 and not run["freeze_encoder"]
        assert run["optimizer_updates"] == 66 and run["train_sequence_rows"] == 1056
        assert run["max_len"] == 16384 and run["head_max_len"] == 2048 and run["http_requests"] == 0 and not run["calibration_test_loaded"]
        assert run["evaluation_points"] == [17,33,66] and run["evaluate_initial_dev"]
        sampling = read(folder/"sampling.json")
        assert len(sampling) == 528 and [row["weight"] for row in sampling] == weights[name]
        assert [row["event_id"] for row in sampling] == [row["metadata"]["event_id"] for row in panels[name]]
        schedule = read(folder/"training-plan.json")
        windows = [window for _,stage in schedule for window in stage]
        assert len(windows) == 66 and all(len(window) == 16 for window in windows)
        draws = [draw for window in windows for draw in window]
        assert len(draws) == 1056 and set(Counter(index for _,index in draws).values()) == {2}
        assert set(index for _,index in draws) == set(range(528))
        assert Counter(pass_number for pass_number,_ in draws) == {1:528,2:528}
        sampled = [panels[name][index] for _,index in draws]
        sampled_quality = quality_counts(sampled,"delivery","quality-tie")
        for field,key in (("sampled_feedback_states","feedback_states"),("sampled_feedback_target_states","states_with_targets"),
            ("sampled_target_pairs","target_pairs"),("sampled_tie_pairs","tie_pairs"),("sampled_directional_pairs","directional_pairs"),("sampled_unknown_pairs","unknown_pairs")):
            assert run[field] == sampled_quality[key]
        assert run["sampled_feedback_states"] == 656 and run["sampled_replay_states"] == 400 and run["sampled_unknown_pairs"] == 76
        assert run["sampled_cost_only_direction_pairs"] == 0
        lengths = read(folder/"lengths.json")["train"]
        assert len(lengths) == 528 and all(row["state_tokens_dropped"] == row["head_tokens_dropped"] == 0 for row in lengths)
        tokens = sum(lengths[index]["sequence_tokens"] for _,index in draws)
        assert tokens == run["train_input_tokens"] == compute["train_input_tokens"] == 5756552
        profile = lines(folder/"update-profile.jsonl")
        assert len(profile) == 66 and sum(row["rows"] for row in profile) == 1056
        assert sum(row["input_tokens"] for row in profile) == tokens
        assert sum(row["padded_input_tokens"] for row in profile) == run["train_padded_input_tokens"] == 6878474
        assert [row["optimizer_updates"] for row in read(folder/"history.json")] == [0,17,33,66]
        schedules[name] = schedule
        option_orders[name] = {path.name:read(path) for path in (folder/"option-orders").glob("*.json")}
        assert set(option_orders[name]) == {"1.json","2.json"}
        assert all(len(orders) == 528 for orders in option_orders[name].values())
        actual_runs[name] = run
        arms[name] = dict(native_run=str(folder/"run.json"),native_compute=str(folder/"compute.json"),native_driver=str(root/f"{name}-seed0-driver.json"),
            physical_GPU=run["cuda_visible_devices"],actual_slot_count=528,actual_draws=1056,actual_draws_per_slot=2,actual_passes=2,optimizer_updates=66,
            actual_train_input_tokens=tokens,actual_train_padded_input_tokens=6878474,max_actual_sequence_tokens=max(row["sequence_tokens"] for row in lengths),
            native_CPU_seconds=compute["cpu_seconds"],native_wall_seconds=compute["wall_seconds"],native_GPU_interval_hours=compute["gpu_hours"],
            pure_delivery_quality_counts=quality[name],sampled_quality_counts=sampled_quality,sampled_feedback_states=656,sampled_operation_replay_states=400,
            sampled_unknown_pairs=76,unknown_state_slots_preserved_in_draws=True,actual_loss_recipe_inherits_original_E3_argv=True,
            schedule_evidence="Original training-plan is consumed directly by frozen executed trainer; per-update rows/tokens, two option-order passes and actual sampled quality counters independently reconcile. B ordinary sampler has no separate conditional training-windows copy.",
            no_cost_only_quality_direction_pairs=True)
        print("B_ACTUAL528_SLOTS_TWO_FULL_DRAWS_AND_NATIVE_WEIGHTS_RECONCILED",name,flush=True)
    assert schedules["b0"] == schedules["b1"] and option_orders["b0"] == option_orders["b1"]
    for field in ("base_checkpoint","seed","backend","parallel_mode","precision","parameter_precision","max_len","head_max_len","encoder_lr","head_lr",
        "freeze_encoder","objective","feedback_target","pair_supervision","pair_mass_mode","replay_weight","replay_objective","batch_size","gradient_accumulation","tf32_matmul","tf32_cudnn","attention_backend","operation_state"):
        assert actual_runs["b0"][field] == actual_runs["b1"][field]
    assert actual_runs["b0"]["cuda_visible_devices"] != actual_runs["b1"]["cuda_visible_devices"]
    out = dict(passed=True,status="B64_RAW_QUALITY_REVIEWS_COMPILED_PANELS_INHERITED_RECIPE_AND_ACTUAL_TWO_DRAW_MATCHED_FITS_RECONCILED",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),actual_training_runtime=str(runtime),Source_guide=str(root/"b64-delivery-author-guide.json"),
        source_families=64,reached_states=128,actual_bindings=384,shared_actual_baseline_outcomes=128,
        raw_before_and_full_menus_inputs_gold_metadata_identical_between_panels=True,all_actual_supervision_rows_literal_equal_recompiled=True,
        new_delivery_counts={name:dict(counts) for name,counts in delivery_counts.items()},
        quality_labels_derived_before_resource_tiebreak_from_Source_author_grades=True,resource_records_checked=resource_checks,
        wire_token_resource_counts_are_existing_original_counts_not_retokenized=True,
        all256_new_answer_comparisons_remain_unknown_in_closed_actual_fit_data=True,
        old400_rows_literal_preserved=True,old400_composition=dict(existing_feedback=200,operation_replay=200),
        new128_feedback_rows=128,full528_composition=dict(feedback=328,operation_replay=200),
        actual_loss_weight_masses=dict(feedback=1.0,operation_replay=.25),all528_per_slot_native_weights_equal=True,
        same_real_optimizer_schedule_and_option_orders=True,original_E3_recipe=str(plan["inherited_E3_run"]),
        actual_original_argv_inheritance_replayed_before_device_budget_changes=True,
        actual_objective="pair",actual_target="delivery",actual_quality_mode="quality-tie",actual_pair_mass_mode="component-sum",actual_replay_objective="set",
        actual_two_full_exposures_each_slot_verified=True,arms=arms,
        missing_B_training_windows_duplicate_not_fabricated=True,
        scope="Existing200feedback+200operation replay plus128new reached feedback. Same full inputs and actual two complete passes; only declaration of compared argmax/baseline versus alternative/samebaseline changes. All new answer targets remain unknown. Source-author material tiers and pair directions are not full task success or independent human labels; postfit answer review cannot backfill actual training labels.",
        new_training_model_tokenizer_GPU_HTTP_business_or_original_ledger_calls=0,original_data_labels_models_or_firsts_changed=False,
        B_evaluation_stop_and_final763_completion_proven_here=False,no_sha_validation=True,goal_complete=False)
    with args.output.open("x") as stream:
        json.dump(out,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print(out["status"],"528slots1056draws66updates;200oldfeedback+200replay+128new;allnewanswerunknown")


if __name__ == "__main__":
    main()
