"""Reproduce A's original sampler and reconcile mixed slots and actual matched fits."""
import argparse
import ast
import inspect
import json
import math
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
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
    lab = root.parent.parent
    plan = read(root/"a-seed0-plan.json")
    preparation = read(root/"a-matched/comparison-preparation.json")
    runtime = Path(plan["jobs"][0]["argv"][3]).parent.parent
    import tokenizers
    import transformers

    assert transformers.__version__ == "4.52.3" and tokenizers.__version__ == "0.21.4"
    sys.path.append(str(Path(plan["jobs"][0]["argv"][0]).parents[2]/"http-env/lib/python3.11/site-packages"))
    sys.path[:0] = [str(runtime/"tools"),str(runtime/"src")]
    from milai_lab.datasets.conditional_reviews import binary_label
    from retrieval_mixture import mixture_event_weights

    version = plan["data_preparation_commit"]
    source_name = "MiLAi-Lab/src/milai_lab/datasets/conditional_exposure.py"
    source = subprocess.run(["git","show",f"{version}:{source_name}"],cwd=lab,capture_output=True,check=True,text=True).stdout
    namespace = {"__name__":"actual_A_sampler_snapshot_for_readonly_audit"}
    exec(compile(source,f"{version}:{source_name}","exec"),namespace)
    sampler = namespace["condition_stratified_auxiliary_panel"]
    assert inspect.signature(sampler).parameters["negative_selection"].default == "legacy"
    cli = (lab/"tools/prepare_stratified_conditional_stage.py").read_text()
    assert '"--negative-selection"' in cli and 'default="legacy"' in cli
    preps = {name:read(root/f"{name}-conditional/preparation.json") for name in ("a0","a1")}
    assert preps["a0"]["source"] == preps["a1"]["source"] and preps["a0"]["seed"] == preps["a1"]["seed"] == 0
    source_root = Path(preps["a0"]["source"])
    matrix,pairs = lines(source_root/"matrix.jsonl"),lines(source_root/"condition-pairs.jsonl")
    assert all(row["metadata"]["split"] == "train" for row in matrix)
    source_label_counts = Counter(str(binary_label(row)) for row in matrix)
    print("A_SOURCE_MATRIX_AND_PAIRS_READ",len(matrix),len(pairs),flush=True)
    panel_summaries = {}
    selected_events = {}
    panel_rows = {}
    for name,mode in (("a0","legacy"),("a1","native-priority")):
        panel = sampler(matrix,pairs,seed=0,negative_selection=mode)
        folder = root/f"{name}-conditional"
        actual_rows = lines(folder/"train.jsonl")
        actual_pairs = lines(folder/"selected-pairs.jsonl")
        assert panel["rows"] == actual_rows
        assert panel["pairs"] == actual_pairs
        assert panel["slots"] == read(folder/"slots.json")
        assert panel["missing_condition_labels"] == read(folder/"missing-condition-labels.json") == []
        assert panel["instruction_negative_coverage"] == read(folder/"instruction-negative-coverage.json")
        assert panel["counts"] == preps[name]["counts"] and panel["negative_selection"] == preps[name]["negative_selection"]
        for copied in ("groups.json","query-units.json"):
            assert (folder/copied).read_bytes() == (source_root/copied).read_bytes()
        assert panel["counts"]["training_slots"] == panel["counts"]["distinct_cells"] == 39982
        assert panel["counts"]["positive_slots"] == 20008 and panel["counts"]["negative_slots"] == 19974
        assert panel["counts"]["families"] == panel["counts"]["query_units"] == 10000
        assert panel["counts"]["source_conditions"] == panel["counts"]["conditions"] == 19968
        assert panel["counts"]["comparison_kind"]["change"] == 6
        assert panel["counts"]["label_provenance_slots"] == {"known":39927,"source_author_reviewed":55}
        selected_events[name] = {row["metadata"]["event_id"] for row in actual_rows}
        panel_rows[name] = actual_rows
        coverage = panel["instruction_negative_coverage"]
        assert coverage["available_known_units"] == 23029 and coverage["eligible_conditions"] == 9540
        expected = 5 if name == "a0" else 9540
        assert coverage["selected_known_units"] == coverage["represented_conditions"] == expected
        change = [pair for pair in actual_pairs if pair["kind"] == "change"]
        assert all(pair[side+"_event"] in selected_events[name] for pair in change for side in ("left","right"))
        panel_summaries[name] = dict(mode=mode,counts=panel["counts"],coverage={key:value for key,value in coverage.items() if key != "missing_conditions"},
            missing_native_negative_conditions=len(coverage["missing_conditions"]),selected_pairs_by_kind=dict(Counter(pair["kind"] for pair in actual_pairs)),
            all_rows_pairs_slots_missing_masks_and_coverage_equal_replayed_original_sampler=True)
        print("A_SAMPLER_LITERAL_REPLAY_PASSED",name,39982,coverage["represented_conditions"],flush=True)
    changes = [[pair for pair in lines(root/f"{name}-conditional/selected-pairs.jsonl") if pair["kind"] == "change"] for name in ("a0","a1")]
    assert changes[0] == changes[1] and len(changes[0]) == 6
    assert len(selected_events["a0"]-selected_events["a1"]) == len(selected_events["a1"]-selected_events["a0"]) == 9535
    del matrix,pairs,panel,panel_rows

    mixed_paths = {name:root/"a-matched"/name/"train.jsonl" for name in ("a0","a1")}
    reference_path = Path(preparation["control_data"])/"train.jsonl"
    metadata_rows = {name:[] for name in ("a0","a1")}
    all_events = {name:set() for name in ("a0","a1")}
    counts = Counter()
    condition_counts = {name:Counter() for name in ("a0","a1")}
    preserved_positive = preserved_replay = replacements = 0
    known_conditional_singleton = 0
    with mixed_paths["a0"].open() as a0,mixed_paths["a1"].open() as a1,reference_path.open() as reference:
        for position,(left,right,raw) in enumerate(zip(a0,a1,reference,strict=True)):
            left,right,raw = json.loads(left),json.loads(right),json.loads(raw)
            assert left == raw
            assert left["metadata"]["state_id"] == right["metadata"]["state_id"]
            component = left["metadata"]["component"]
            assert component == right["metadata"]["component"] and left["metadata"]["split"] == right["metadata"]["split"] == "train"
            counts[component] += 1
            if component == "operation":
                assert left == right
                preserved_replay += 1
            else:
                assert component == "conditional"
                a,b = binary_label(left),binary_label(right)
                assert a is b and a is not None
                condition = tuple(left["metadata"][key] for key in ("family","query_unit","training_event"))
                assert condition == tuple(right["metadata"][key] for key in ("family","query_unit","training_event"))
                for name,row in (("a0",left),("a1",right)):
                    condition_counts[name][condition+(a,)] += 1
                    all_events[name].add(row["metadata"]["event_id"])
                    target, = row["gold"].values()
                    assert sorted(target["probabilities"].values()) == [0.,1.]
                known_conditional_singleton += 1
                if a:
                    assert left == right
                    preserved_positive += 1
                elif left != right:
                    assert any(item["native_field"] == "new_negatives" for item in right["metadata"]["native_judgments"])
                    replacements += 1
            assert bool(left["gold"]) == bool(right["gold"])
            if left["gold"]:
                for name,row in (("a0",left),("a1",right)):
                    metadata_rows[name].append({"metadata":row["metadata"]})
    assert counts == {"conditional":39982,"operation":7884}
    assert preserved_positive == 20008 and preserved_replay == 7884 and replacements == 9535
    assert condition_counts["a0"] == condition_counts["a1"]
    assert all_events == selected_events
    assert all(len(rows) == 44868 for rows in metadata_rows.values())
    assert len({key[:-1] for key in condition_counts["a0"]}) == 19968
    assert all(condition_counts["a0"][condition+(False,)] >= 1 for condition in {key[:-1] for key in condition_counts["a0"]})
    mixtures = {name:read(root/"a-matched"/name/"mixture.json") for name in ("a0","a1")}
    assert mixtures["a0"] == mixtures["a1"]
    weights = {name:mixture_event_weights(metadata_rows[name],mixtures[name]) for name in ("a0","a1")}
    assert weights["a0"] == weights["a1"]
    assert (root/"a-matched/a0/dev.jsonl").read_bytes() == (root/"a-matched/a1/dev.jsonl").read_bytes() == (Path(preparation["control_data"])/"dev.jsonl").read_bytes()
    print("A_MIXED_LITERAL_SOURCE_ROWS_AND_SLOT_WEIGHTS_PASSED",47866,44868,9535,flush=True)

    # The actual original E2 report is anchored explicitly in the existing P0 source-length record.
    original_e2_path = Path(read(root/"p0-plan.json")["profile"]["source_lengths"]).with_name("run.json")
    original_e2 = read(original_e2_path)
    assert original_e2["objective"] == plan["objective"] == "set"
    runs,arms,schedules,option_orders = {},{},{},{}
    for name in ("a0","a1"):
        folder = root/f"{name}-seed0"
        run,compute,driver = read(folder/"run.json"),read(folder/"compute.json"),read(root/f"{name}-seed0-driver.json")
        assert run["status"] == driver["status"] == "COMPLETED" and driver["returncode"] == 0
        assert all(not Path("/proc",str(driver[key])).exists() for key in ("pid","child_pid"))
        assert run["base_checkpoint"] == original_e2["base_checkpoint"] == plan["initialization"]
        assert run["objective"] == "set" and run["conditional_loss_weight"] == 0
        assert run["parallel_mode"] == "single" and run["precision"] == "bf16" and run["device"] == "cuda:0"
        assert run["parameter_precision"] == "float32" and set(run["parameter_dtypes"]) == {"torch.float32"}
        assert run["batch_size"] == 2 and run["gradient_accumulation"] == 8 and run["seed"] == 0
        assert run["max_len"] == 16384 and run["head_max_len"] == 2048 and not run["freeze_encoder"]
        assert run["optimizer_updates"] == 2805 and run["train_sequence_rows"] == 44868 and run["data_passes_started"] == 1
        assert run["evaluation_points"] == [702,1403,2104,2805] and run["evaluate_initial_dev"]
        assert run["http_requests"] == 0 and run["calibration_test_loaded"] is False
        schedule = read(folder/"training-plan.json")
        assert schedule == read(folder/"training-windows.json")
        windows = [window for _,stage in schedule for window in stage]
        assert len(windows) == 2805 and [len(window) for window in windows] == [16]*2804+[4]
        draws = [draw for window in windows for draw in window]
        assert sorted(index for pass_number,index in draws) == list(range(44868)) and all(pass_number == 1 for pass_number,_ in draws)
        sampling = read(folder/"sampling.json")
        assert len(sampling) == 44868
        for index,(sample,row) in enumerate(zip(sampling,metadata_rows[name],strict=True)):
            assert sample["event_id"] == row["metadata"]["event_id"]
            assert sample["weight"] == weights[name][index]*run["mixture_loss_scale"]
        lengths = read(folder/"lengths.json")["train"]
        assert len(lengths) == 44868 and all(record["state_tokens_dropped"] == record["head_tokens_dropped"] == 0 for record in lengths)
        tokens = sum(record["sequence_tokens"] for record in lengths)
        assert tokens == run["train_input_tokens"] == compute["train_input_tokens"]
        history = read(folder/"history.json")
        assert [point["optimizer_updates"] for point in history] == [0,702,1403,2104,2805]
        profile = lines(folder/"update-profile.jsonl")
        assert len(profile) == 2805 and sum(point["rows"] for point in profile) == 44868
        assert sum(point["input_tokens"] for point in profile) == tokens
        assert sum(point["padded_input_tokens"] for point in profile) == run["train_padded_input_tokens"]
        option_orders[name] = read(folder/"option-orders/1.json")
        schedules[name] = schedule
        runs[name] = run
        arms[name] = dict(native_run=str(folder/"run.json"),native_compute=str(folder/"compute.json"),actual_driver=str(root/f"{name}-seed0-driver.json"),
            physical_GPU=run["cuda_visible_devices"],precision="bf16",parameter_dtype="float32",optimizer_updates=2805,actual_draws=44868,
            actual_input_tokens=tokens,actual_padded_tokens=run["train_padded_input_tokens"],last_window_rows=4,
            actual_padded_tokens_source="Native run.json and sum of every update-profile row; not inferred from compute.json.",
            native_CPU_seconds=compute["cpu_seconds"],native_wall_seconds=compute["wall_seconds"],native_GPU_interval_hours=compute["gpu_hours"],
            native_derived_condition_pairs=len(lines(root/"a-matched"/name/"selected-pairs.jsonl")),
            exposed_native_negative_units=panel_summaries[name]["coverage"]["selected_known_units"],
            sampler_counts=panel_summaries[name]["counts"],all44868_rows_exposed_once=True,all_per_slot_actual_loss_weights_equal=True,
            mixture=run["mixture"],mixture_loss_scale=run["mixture_loss_scale"])
    for key in ("base_checkpoint","seed","backend","parallel_mode","precision","parameter_precision","max_len","head_max_len","encoder_lr","head_lr",
        "freeze_encoder","objective","conditional_loss_weight","batch_size","gradient_accumulation","tf32_matmul","tf32_cudnn","attention_backend","operation_state","mixture","mixture_loss_scale"):
        assert runs["a0"][key] == runs["a1"][key]
    assert runs["a0"]["cuda_visible_devices"] != runs["a1"]["cuda_visible_devices"]
    assert runs["a0"]["mixture_loss_scale"] == original_e2["mixture_loss_scale"] == 1.25
    assert option_orders["a0"] == option_orders["a1"]
    assert arms["a0"]["actual_input_tokens"] == 37502475 and arms["a1"]["actual_input_tokens"] == 37318166
    assert arms["a0"]["actual_padded_tokens"] == 61754792 and arms["a1"]["actual_padded_tokens"] == 63310836
    out = dict(passed=True,status="ORIGINAL_PLAN_A_SAMPLING_SOURCE_SLOT_WEIGHTS_AND_MATCHED_FULL_FITS_RECONCILED",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),original_data_preparation_commit=version,
        original_sampler_source_path=source_name,actual_sampler_literal_source=source,
        original_sampler_default_legacy=True,source_matrix=str(source_root/"matrix.jsonl"),source_matrix_rows=sum(source_label_counts.values()),
        source_label_counts=dict(source_label_counts),source_matrix_and_unknown_masks_not_modified=True,
        panels=panel_summaries,all_prepared_rows_pairs_slots_and_coverage_equal_original_sampler_replay=True,
        mixed_raw_rows_each=47866,mixed_known_rows_each=44868,raw_unknown_replay_rows_retained=2998,
        pure_conditional_slots=39982,preserved_positive_rows=20008,preserved_raw_replay_rows=7884,preserved_known_replay_rows=4886,
        actual_negative_replacements_within_same_condition=9535,negative_budget=19974,actual_conditions=19968,negative_extra_slots=6,
        all_required6_change_pairs_and_their_endpoints_unchanged=True,stable_positive_pairs_each=80,
        stable_negative_pairs={name:panel_summaries[name]["counts"]["stable_negative_pairs"] for name in ("a0","a1")},
        all_model_input_and_gold_provenance_literal_equal_selected_source_rows=True,all_common_dev_bytes_equal=True,
        per_slot_loss_weights_recomputed_and_equal_actual_native_sampling=True,all_actual_option_orders_equal=True,
        mixture={"conditional":0.8,"operation":0.2},mixture_loss_scale=1.25,
        actual_component_loss_masses={"conditional":1.0,"operation":0.25},
        actual_training_schedules_equal=schedules["a0"] == schedules["a1"],
        schedule_scope="Derived pair relations and optimizer grouping can change as declared; all actual rows/draw budgets, per-slot weights, state IDs and option RNG are preserved. Do not claim only native-negative count changed.",
        original_E2_native_run=str(original_e2_path),actual_objective_flag="set",
        CE_equivalence_scope="All39982 conditional targets are singleton binary labels, so set likelihood equals ordinary CE there. Original operation replay keeps its accepted-set objective. Actual set flag is reported, not renamed soft-ce.",
        conditional_singleton_targets_verified=known_conditional_singleton,arms=arms,
        new_training_model_tokenizer_HTTP_business_or_original_ledger_calls=0,
        full_A_evaluation_and_stop_decisions_audited_here=False,full763_line_completion_proven=False,
        no_sha_validation=True,goal_complete=False)
    with args.output.open("x") as stream:
        json.dump(out,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print(out["status"],"39982conditional/44868draws;native5to9540;stableNeg9968to433;weightsliteralEqual")


if __name__ == "__main__":
    main()
