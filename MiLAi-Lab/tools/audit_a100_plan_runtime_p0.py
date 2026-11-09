"""Audit concrete original-plan P0/runtime obligations from actual saved GPU outputs."""
import argparse
import ast
import json
import math
import statistics
import struct
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def lines(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    lab = root.parent.parent
    sys.path.insert(0, str(root))
    from offline_time_receipts import read_timer

    original_path = Path("/cra/memory/mx_memory/MiLAi-worktrees/jev-read-decisions-20261016/MiLAi-Lab/docs/MILAI_DEVELOPMENT_EXPERIMENT_PLAN_2XA100_40GB_20261104.md")
    original_lines = original_path.read_text().splitlines()
    assert len(original_lines) == 763
    plan = read(root / "p0-plan.json")
    analysis = read(root / "p0-analysis.json")
    worksheet = read(lab / "data/manifests/a100-closed-training-compute-20261107-v1.json")
    hardware = read(root / "hardware.json")
    assert "memory.free" in hardware["gpus"] and "GPU2" in hardware["topology"] and "GPU3" in hardware["topology"]
    assert "NVIDIA A100-PCIE-40GB" in hardware["gpus"]
    data = Path(plan["jobs"][0]["argv"][4])
    rows = lines(data / "train.jsonl")
    assert len(rows) == analysis["rows_each"] == plan["profile"]["rows"] == 512
    assert all(row["metadata"]["split"] == "train" for row in rows)
    positions = plan["profile"]["source_positions"]
    assert len(positions) == len(set(positions)) == 512 and positions == sorted(positions)
    selected = set(positions)
    original_rows = {}
    source_train = Path(plan["profile"]["source"]) / "train.jsonl"
    raw_source_count = source_count = 0
    with source_train.open() as stream:
        for line in stream:
            original = json.loads(line)
            raw_source_count += 1
            if not original["gold"]:
                continue
            if source_count in selected:
                original_rows[source_count] = original
            source_count += 1
    assert raw_source_count == 47866 and source_count == 44868
    assert [original_rows[index] for index in positions] == rows
    assert Counter(row["metadata"]["component"] for row in rows) == {"conditional":432, "operation":80}
    pairs = lines(data / "selected-pairs.jsonl")
    assert len(pairs) == plan["profile"]["complete_pairs"] == 121
    event_index = {row["metadata"]["event_id"]:index for index,row in enumerate(rows)}
    assert len(event_index) == 512
    for pair in pairs:
        assert pair["split"] == "train" and type(pair["left_label"]) is type(pair["right_label"]) is bool
        for side in ("left", "right"):
            row = rows[event_index[pair[side+"_event"]]]
            assert row["metadata"]["family"] == pair["family"]
            expected = "satisfies" if pair[side+"_label"] else "does_not_satisfy"
            assert row["gold"]["applicability"]["probabilities"][expected] == 1.0

    trainer_path = Path(plan["source_frozen_by_copy"]) / "tools/train_bounded_laya.py"
    import tokenizers
    import transformers

    assert transformers.__version__ == "4.52.3" and tokenizers.__version__ == "0.21.4"
    http_site = Path(plan["jobs"][0]["argv"][0]).parents[2]/"http-env/lib/python3.11/site-packages"
    sys.path.append(str(http_site))
    sys.path[:0] = [str(trainer_path.parent),str(trainer_path.parent.parent/"src")]
    from retrieval_mixture import project_mixed_row

    projected_rows = [project_mixed_row(row,"shared_actions") for row in rows]
    trainer = trainer_path.read_text()
    tree = ast.parse(trainer)
    forward = next(node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef) and node.name == "training_forward")
    contexts = [node for node in ast.walk(forward) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr == "autocast"]
    assert len(contexts) == 1 and any(keyword.arg == "dtype" and ast.unparse(keyword.value) == "torch.bfloat16" for keyword in contexts[0].keywords)
    sdk_forward = next(node for node in ast.walk(forward) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id == "_forward")
    assert [arg.value for arg in sdk_forward.args[-2:]] == [False,False]
    evaluate = next(node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef) and node.name == "evaluate")
    assert any(isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and ast.unparse(node.func) == "decision.predict" for node in ast.walk(evaluate))
    assert len([node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr == "autocast"]) == 1
    assert "loss.backward()" in trainer and "torch.optim.AdamW" in trainer and "torch.cuda.reset_peak_memory_stats(index)" in trainer
    sdk_path = Path(plan["jobs"][0]["argv"][0]).parent.parent / "lib/python3.11/site-packages/laya/train.py"
    sdk = sdk_path.read_text()
    sdk_tree = ast.parse(sdk)
    native_forward = next(node for node in ast.walk(sdk_tree) if isinstance(node,ast.FunctionDef) and node.name == "_forward")
    assert ast.unparse(native_forward.body[-1]) == "return logits.float()"
    loss_definition = next(node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef) and node.name == "decision_loss")
    loss_scope = {"Any":object}
    exec(compile(ast.Module(body=[loss_definition],type_ignores=[]),str(trainer_path),"exec"),loss_scope)
    native_loss = loss_scope["decision_loss"]
    import torch

    def verify_prediction(row, prediction):
        question, = row["questions"].values()
        assert list(prediction["logits"]) == list(prediction["probabilities"]) == list(question["criteria"])
        assert prediction["choice"] == max(prediction["probabilities"],key=prediction["probabilities"].get)
        assert all(math.isfinite(value) for field in ("logits","probabilities") for value in prediction[field].values())
        assert prediction["truncated"] is False and prediction["input_tokens"] <= 16384

    arms, saved = {}, {}
    for job in plan["jobs"]:
        label = job["name"]
        output = Path(job["output"])
        run, compute = read(output/"run.json"), read(output/"compute.json")
        driver_path = root / f"p0-{label}-driver.json"
        driver = read(driver_path)
        assert driver["status"] == "COMPLETED" and driver["returncode"] == 0
        assert all(not Path("/proc",str(driver[key])).exists() for key in ("pid","child_pid"))
        assert job["argv"][3] == str(trainer_path) and "train_with_declared_attention.py" in job["argv"][2]
        assert run["status"] == "COMPLETED" and run["parallel_mode"] == "single" and run["device"] == "cuda:0"
        assert run["precision"] == label and run["parameter_precision"] == "float32" and set(run["parameter_dtypes"]) == {"torch.float32"}
        assert run["device_ids"] == [0] and len(run["devices"]) == 1 and run["memory_fraction"] == 1.0
        assert run["seed"] == 0 and run["batch_size"] == 2 and run["gradient_accumulation"] == 8
        assert run["base_checkpoint"] == plan["profile"]["checkpoint"] and Path(run["data"]) == data
        assert run["max_len"] == 16384 and run["head_max_len"] == 2048 and run["gradient_checkpointing"]
        assert run["tf32_matmul"] is False and run["tf32_cudnn"] is True and run["attention_backend"] == "sdpa"
        assert run["optimizer_updates"] == 32 and run["train_sequence_rows"] == 512 and run["train_input_tokens"] == 639380
        assert run["train_device_forwards"] == compute["train_device_forwards"] == 256
        assert run["http_requests"] == 0 and run["calibration_test_loaded"] is False
        history = read(output/"history.json")
        assert [point["optimizer_updates"] for point in history] == [0,32]
        assert all("train" in point and "dev" in point for point in history)
        schedule = read(output/"training-plan.json")
        assert schedule == read(output/"training-windows.json") and len(schedule) == 1 and schedule[0][0] == 32
        windows = schedule[0][1]
        assert len(windows) == 32 and all(len(window) == 16 for window in windows)
        actual_order = [(pass_number,index) for window in windows for pass_number,index in window]
        assert all(number == 1 for number,_ in actual_order) and sorted(index for _,index in actual_order) == list(range(512))
        micro_positions = {index:(update,position//2) for update,window in enumerate(windows) for position,(_,index) in enumerate(window)}
        for pair in pairs:
            assert micro_positions[event_index[pair["left_event"]]] == micro_positions[event_index[pair["right_event"]]]
        profile = lines(output/"update-profile.jsonl")
        assert [point["update"] for point in profile] == list(range(1,33)) and all(point["rows"] == 16 for point in profile)
        assert sum(point["input_tokens"] for point in profile) == run["train_input_tokens"]
        assert sum(point["padded_input_tokens"] for point in profile) == run["train_padded_input_tokens"]
        assert math.isclose(sum(point["wall_seconds"] for point in profile),compute["stage_wall_seconds"]["training"],rel_tol=0,abs_tol=1e-7)
        steady = statistics.mean(point["wall_seconds"] for point in profile[4:])
        assert math.isclose(steady,analysis["arms"][label]["steady_mean_update_seconds"],rel_tol=0,abs_tol=1e-12)
        lengths = read(output/"lengths.json")
        assert len(lengths["train"]) == 512 and len(lengths["dev"]) == 32
        assert all(record["state_tokens_dropped"] == record["head_tokens_dropped"] == 0 for record in lengths["train"]+lengths["dev"])
        assert max(record["sequence_tokens"] for record in lengths["train"]) == 9869
        assert sum(record["sequence_tokens"] for record in lengths["train"]) == run["train_input_tokens"]
        assert len(compute["peak_cuda_allocated_bytes"]) == len(compute["peak_cuda_reserved_bytes"]) == len(compute["final_cuda_free_total_bytes"]) == 1
        peak_allocated, peak_reserved = compute["peak_cuda_allocated_bytes"][0], compute["peak_cuda_reserved_bytes"][0]
        free,total = compute["final_cuda_free_total_bytes"][0]
        assert 0 < peak_allocated <= peak_reserved <= total and 0 < free < total
        assert total == run["devices"][0]["total_bytes"] == 42404806656
        predictions, diagnostic_loss = {}, {}
        dev_rows = [project_mixed_row(row,"shared_actions") for row in lines(run["dev_source"])]
        assert len(dev_rows) == 32 and math.isfinite(history[-1]["weighted_loss_mean"])
        for update in (0,32):
            predictions[update] = [read(output/"train"/str(update)/f"{index}.json") for index in range(512)]
            assert len(list((output/"dev"/str(update)).glob("[0-9]*.json"))) == 32
            for index,row in enumerate(dev_rows):
                verify_prediction(row,read(output/"dev"/str(update)/f"{index}.json"))
            losses = []
            for row,prediction in zip(projected_rows,predictions[update],strict=True):
                verify_prediction(row,prediction)
                target, = row["gold"].values()
                keys = list(prediction["logits"])
                logits = torch.tensor([[prediction["logits"][key] for key in keys]],dtype=torch.float32,device="cpu")
                targets = torch.tensor([[target["probabilities"].get(key,0.0) for key in keys]],dtype=torch.float32,device="cpu")
                loss = native_loss(logits,targets,torch.ones_like(logits,dtype=torch.bool),run["objective"])
                assert loss.dtype == torch.float32 and torch.isfinite(loss).all()
                losses.append(float(loss[0]))
            diagnostic_loss[str(update)] = {"mean":statistics.mean(losses),"maximum":max(losses),"rows":512}
        reload = Path(analysis["arms"][label]["reload"])
        reloaded_run = read(reload/"run.json")
        assert reloaded_run["status"] == "COMPLETED" and reloaded_run["completed_states"] == reloaded_run["planned_states"] == 512
        assert reloaded_run["loaded_weight_dtype"] == "torch.float32" and reloaded_run["http_requests"] == 0
        flips = []
        for index,row in enumerate(projected_rows):
            payload = read(reload/"calls"/str(index)/"input.json")
            assert payload == {key:row[key] for key in ("state","questions")}
            prediction = read(reload/"calls"/str(index)/"output.json")
            assert list(prediction["logits"]) == list(predictions[32][index]["logits"])
            assert prediction["truncated"] is False and prediction["input_tokens"] == predictions[32][index]["input_tokens"]
            assert all(math.isfinite(value) for field in ("logits","probabilities") for value in prediction[field].values())
            if prediction["choice"] != predictions[32][index]["choice"]:
                flips.append(index)
        assert flips == [record["index"] for record in analysis["arms"][label]["reload_argmax_flips"]]
        dtypes = Counter()
        for path in Path(reloaded_run["checkpoint"]).rglob("*.safetensors"):
            with path.open("rb") as stream:
                size, = struct.unpack("<Q",stream.read(8))
                header = json.loads(stream.read(size))
            dtypes.update(tensor["dtype"] for key,tensor in header.items() if key != "__metadata__")
        assert dict(dtypes) == analysis["arms"][label]["actual_export_weight_dtypes"] == {"F16":170}
        saved[label] = dict(schedule=schedule,option_orders=read(output/"option-orders/1.json"),lengths=lengths,predictions=predictions)
        arms[label] = dict(output=str(output),native_run=str(output/"run.json"),native_compute=str(output/"compute.json"),
            actual_driver=str(driver_path),physical_GPU=run["cuda_visible_devices"],logical_device="cuda:0",Torch=run["torch_version"],CUDA=run["cuda_version"],
            precision=run["precision"],parameter_dtype="torch.float32",TF32={"matmul":False,"cudnn":True},attention_backend="sdpa",
            rows=512,updates=32,microbatch=2,effective_window=16,full_pairs_preserved_in_same_microbatch=121,
            actual_train_input_tokens=639380,actual_train_padded_input_tokens=run["train_padded_input_tokens"],
            max_observed_sequence_tokens=9869,head_max_len=2048,encoder_config_position_limit=run["encoder_max_position_embeddings"],
            total_device_bytes=total,peak_allocated_bytes=peak_allocated,peak_reserved_bytes=peak_reserved,
            actual_final_device_free_bytes=free,device_free_measurement_scope="Actual final torch.cuda.mem_get_info; not inferred from allocator peaks.",
            native_CPU_seconds=compute["cpu_seconds"],native_wall_seconds=compute["wall_seconds"],native_GPU_interval_hours=compute["gpu_hours"],
            stage_wall_seconds=compute["stage_wall_seconds"],first4_updates_retained_in_cost=True,steady_updates=28,steady_mean_update_seconds=steady,
            initial_and_final_train_prediction_records=1024,initial_and_final_dev_prediction_records=64,
            initial_final_unweighted_set_loss_from_retained_logits_FP32_CPU=diagnostic_loss,
            diagnostic_loss_scope="Exact frozen decision_loss on retained head logits and existing targets, FP32 CPU; not a new model forward, dynamic weighted training loss or Host quality.",
            actual_weighted_training_loss_mean=history[-1]["weighted_loss_mean"],actual_saved_and_reloaded_prediction_records=512,
            exported_tensor_dtype_counts=dict(dtypes),reloaded_parameter_dtype="torch.float32",reload_argmax_flip_indices=flips,
            native_TEST_opened=False,new_model_HTTP_or_ledger_calls=0)
    assert arms["float32"]["physical_GPU"] == "2" and arms["bf16"]["physical_GPU"] == "3"
    assert saved["float32"]["schedule"] == saved["bf16"]["schedule"]
    assert saved["float32"]["option_orders"] == saved["bf16"]["option_orders"]
    assert saved["float32"]["lengths"] == saved["bf16"]["lengths"]
    agreements = {str(update):sum(a["choice"] == b["choice"] for a,b in zip(saved["float32"]["predictions"][update],saved["bf16"]["predictions"][update],strict=True)) for update in (0,32)}
    assert agreements == {"0":512,"32":508}
    ratio = arms["float32"]["steady_mean_update_seconds"]/arms["bf16"]["steady_mean_update_seconds"]
    assert math.isclose(ratio,analysis["training_speed_ratio_fp32_over_bf16"],rel_tol=0,abs_tol=1e-12)
    for row in worksheet["rows"][2:]:
        base = Path(read(row["native_run"])["base_checkpoint"]).resolve()
        assert all(not base.is_relative_to(Path(arm["output"]).resolve()) for arm in arms.values())
    old_test_timer = read_timer(str(root/"p0-tests.time.txt"))
    checks = [
        ("P0-01",[21,82,94,143,144],"两独立单卡、逻辑cuda0、真实forward计数与相同配置",["physical_GPU","logical_device","same_schedule_and_option_orders"]),
        ("P0-02",[103,104,149,164],"沿原初始化与显式single/precision接口，不替换模型",["p0-plan.json","run.json"]),
        ("P0-03",[105,145,155,157],"显式BF16 forward、FP32参数/关键归约、backward在外",["actual_training_forward_AST","SDK_return_logits_float","parameter_dtypes"]),
        ("P0-04",[106,107,125,163,169],"独立512合法TRAIN行、32更新、16行窗口与完整micro2 pair",["all512_entire_rows_equal_source_positions","121_pairs_same_microbatch","actual_windows"]),
        ("P0-05",[112,123,163],"原配置长度、最长样本、全输入与明确名义上下文范围",["all_lengths_no_state_or_head_drop","max_sequence9869","encoder_limit8192"]),
        ("P0-06",[114,164],"同seed/顺序/选项置换；profile输出不作正式初始化",["same_training_plan","same_option_orders","all_later_initializations_checked"]),
        ("P0-07",[121,165,175,433],"allocated/reserved与实际free分别记录，peak覆盖全部更新",["native_compute_peaks","final_cuda_free_total_bytes","reset_before_prepare"]),
        ("P0-08",[165,177,183],"前4仍计成本、后28稳态；吞吐范围不等于GPU忙时",["all32_update_profiles","steady_recomputed","native_compute_scope"]),
        ("P0-09",[166,167],"update0/32完整预测与实际FP16导出后重载行为",["2048_initial_final_predictions","1024_actual_reload_predictions","F16_headers","bf16_flip177_retained"]),
        ("P0-10",[147,151,697],"独立output/phase且沿原预算；不增加第二账本或重试平台",["two_independent_driver_outputs","p0-plan_jobs","existing_closed_cost_cutoff"]),
        ("P0-11",[155,175,528,538],"沿既有attention/dependency wrapper，记录Torch/CUDA/TF32/backend",["actual_job_argv","actual_run_flags","hardware_snapshot"]),
        ("P0-12",[173,505,678],"具体风险验证后取得真实GPU实测，不以测试摘要替代执行",["actual32_updates_each","original_test_summary_has_no_timer_exit_proof","numeric_real_first_results"]),
    ]
    obligations = [dict(id=key,original_plan_lines=references,requirement=text,assessment="PROVED_IN_STATED_P0_SCOPE",
        original_literal_lines=[original_lines[number-1] for number in references],evidence=evidence) for key,references,text,evidence in checks]
    result = dict(passed=True,status="ORIGINAL_PLAN_P0_RUNTIME_OBLIGATIONS_RECONCILED_WITH_ACTUAL_SAVED_GPU_EVIDENCE",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),original_plan=str(original_path),original_plan_lines=763,
        obligations=obligations,arms=arms,source_profile_data=str(data),source_original_train=str(source_train),
        source_original_raw_records=raw_source_count,source_eligible_known_target_records=source_count,
        source_raw_unknown_records_retained_outside_supervised_profile=raw_source_count-source_count,
        source_positions_scope="Exact original trainer's gold-present eligible TRAIN rows; not raw JSONL offsets. All512 entire selected row dicts equal, without changing Source or labels.",
        model_input_projection="Exact original frozen runtime-p0 retrieval_mixture.project_mixed_row(shared_actions); whole reload payloads compared to this declared projection.",
        all512_entire_TRAIN_rows_equal_original_recorded_positions=True,all121_known_pairs_still_complete_and_microbatch_aligned=True,
        same_training_schedule_and_option_orders=True,all_later_training_initializations_exclude_profile_outputs=True,
        argmax_agreement_between_precisions=agreements,steady_FP32_over_BF16_update_time_ratio=ratio,
        training_forward_source=str(trainer_path),actual_local_SDK_forward_source=str(sdk_path),
        audit_runtime={"Transformers":transformers.__version__,"tokenizers":tokenizers.__version__,"HTTP_site_appended_after_original_SDK":str(http_site)},
        original_test_timer=old_test_timer,original_reported_test_summary=plan["tests"],
        original_test_timer_has_direct_exit_code_evidence=old_test_timer["known_exit_code"] is not None,
        missing_original_test_exit_code_fabricated=False,
        BF16_and_FP32_loss_semantics_evidence="Actual trainer AST calls native SDK with amp=False inside explicit BF16-only training context; SDK unconditionally returns logits.float(); backward/evaluation remain outside that context. FP32 parameter dtypes captured in each actual run. This is source/data evidence, not a new tensor execution.",
        final_free_memory_fields_reread_from_native_compute=True,missing_older_E3_TF32_reserved_or_stage_fields_reconstructed=False,
        full763_line_completion_proven=False,remaining_other_plan_packages_and_Mem2Act_and_final_publication_audit=True,
        measurement_scope="P0 only;512 legal TRAIN rows per precision, real saved outputs. Finite beyond8192 does not prove effective16k semantics; BF16 speed ratio concerns steady updates, not whole job or downstream quality. Native CPU/GPU intervals omit unmetered startup/parent gaps where not captured. Old E3 missing fields stay unknown.",
        new_model_tokenizer_GPU_HTTP_business_or_original_ledger_calls=0,no_sha_validation=True,goal_complete=False)
    with args.output.open("x") as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print("PLAN_P0_ACTUAL_EVIDENCE_AUDIT",len(obligations),"obligations;512rows121pairs32updates_each;finalFree",{key:value["actual_final_device_free_bytes"] for key,value in arms.items()},"not_full763_completion")


if __name__ == "__main__":
    main()
