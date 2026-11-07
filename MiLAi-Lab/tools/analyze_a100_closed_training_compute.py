"""Reconcile eight closed new-goal fit/profile jobs without opening a budget."""

import argparse
import json
from collections import Counter
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def analyze(root):
    e3_plan = read(root / "e3-retained-replication/plan.json")
    e3_jobs = {job["seed"]: job for job in e3_plan["jobs"]}
    e3_closed = {job["seed"]: job for job in read(root / "e3-retained-replication/driver.json")["completed"]}
    specs = [("P0 FP32", "p0-float32", None), ("P0 BF16", "p0-bf16", None),
             ("A0", "a0-seed0", 2104), ("A1", "a1-seed0", 2104),
             ("B0", "b0-seed0", 33), ("B1", "b1-seed0", 33),
             ("E3 seed1", "e3-retained-replication/seed-1", 32),
             ("E3 seed2", "e3-retained-replication/seed-2", 32)]
    rows = []
    for label, directory, evaluated_cut in specs:
        output = root / directory
        run = read(output / "run.json")
        compute = read(output / "compute.json")
        lengths = read(output / "lengths.json")["train"]
        schedule = read(output / "training-plan.json")
        groups = [group for _, segment in schedule for group in segment]
        draws = [index for group in groups for _, index in group]
        tokens = sum(lengths[index]["sequence_tokens"] for index in draws)
        assert run["status"] == "COMPLETED" and compute["runs"] == 1
        assert len(groups) == run["optimizer_updates"] == run["planned_optimizer_updates"]
        assert len(draws) == run["train_sequence_rows"] == compute["train_sequence_rows"]
        assert len(lengths) == run["train_states"]
        assert tokens == run["train_input_tokens"] == compute["train_input_tokens"]
        assert not run["calibration_test_loaded"] and run["http_requests"] == 0
        assert all(row["state_tokens_dropped"] == row["head_tokens_dropped"] == 0 for row in lengths)
        if directory.startswith("e3-"):
            job = e3_jobs[run["seed"]]
            closed = e3_closed[run["seed"]]
            gpus = [int(value) for value in job["environment"]["CUDA_VISIBLE_DEVICES"].split(",")]
            assert gpus == e3_plan["physical_gpus"] == [2, 3]
            assert closed["exit_code"] == 0 and closed["client_CPU_recorded"]
            outer_cpu, outer_wall = closed["whole_child_CPU_seconds"], closed["wall_seconds"]
            residual = closed["client_CPU_residual"]
            assert closed["native_CPU_already_recorded"] == compute["cpu_seconds"]
            assert abs(outer_cpu - compute["cpu_seconds"] - residual) < 1e-9
            assert outer_wall * 2 / 3600 == closed["two_GPU_job_interval_hours"]
            mode = e3_plan["parallel_mode"]
            padded_tokens = reserved = stages = None
            tf32 = dict(matmul=None, cudnn=None, scope="Not captured in this original recipe run.json")
            driver_path = root / "e3-retained-replication/driver.json"
            memory_scope = "Original trainer records max_memory_allocated since process CUDA initialization; no reset_peak_memory_stats in its source. Reserved peak not recorded."
        else:
            driver_path = root / f"{directory}-driver.json"
            driver = read(driver_path)
            assert driver["returncode"] == 0
            gpus = [int(value) for value in run["cuda_visible_devices"].split(",")]
            assert len(gpus) == len(run["device_ids"]) == 1
            assert driver["job"]["environment"]["CUDA_VISIBLE_DEVICES"] == run["cuda_visible_devices"]
            mode = run["parallel_mode"]
            assert mode == "single"
            assert abs(compute["gpu_hours"] - compute["wall_seconds"] / 3600) < 1e-12
            padded_tokens = run["train_padded_input_tokens"]
            reserved = compute["peak_cuda_reserved_bytes"]
            stages = compute["stage_wall_seconds"]
            tf32 = dict(matmul=run["tf32_matmul"], cudnn=run["tf32_cudnn"], scope="Recorded in actual training run")
            memory_scope = "Peak reset once before native prepare/train/evaluation/save; covers all updates, including Adam allocation. Not a training-only peak."
            if directory.startswith("b"):
                assert driver["residual_CPU_recorded"]
                outer_cpu, outer_wall = driver["whole_child_CPU_seconds"], driver["wall_seconds"]
                residual = driver["client_CPU_residual"]
                assert driver["native_CPU_already_recorded"] == compute["cpu_seconds"]
                assert abs(outer_cpu - compute["cpu_seconds"] - residual) < 1e-9
            else:
                outer_cpu = outer_wall = residual = None
        assert compute["train_device_forwards"] == len(gpus) * compute["train_batch_forwards"]
        assert len(compute["peak_cuda_allocated_bytes"]) == len(gpus)
        if evaluated_cut is not None:
            assert (output / "checkpoints" / f"update-{evaluated_cut}").is_dir()
        evaluation_tokens = {name: value for name, value in compute.items()
                             if name in {"dev_input_tokens", "feedback-dev_input_tokens", "train_eval_input_tokens"}}
        rows.append(dict(label=label, output=str(output), native_run=str(output / "run.json"),
            native_compute=str(output / "compute.json"), actual_driver=str(driver_path),
            actual_training_schedule=str(output / "training-plan.json"), actual_lengths=str(output / "lengths.json"),
            physical_GPUs=gpus, parallel_mode=mode, precision=run["precision"], seed=run["seed"],
            Torch=run["torch_version"], CUDA=run["cuda_version"], TF32=tf32,
            configured_max_len=run["max_len"], configured_head_max_len=run["head_max_len"],
            encoder_max_position_embeddings=run.get("encoder_max_position_embeddings"),
            microbatch=run["batch_size"], accumulation=run["gradient_accumulation"],
            train_slots=run["train_states"], actual_optimizer_updates=len(groups), actual_draws=len(draws),
            actual_update_group_sizes=dict(Counter(len(group) for group in groups)),
            actual_train_input_tokens=tokens, actual_train_padded_input_tokens=padded_tokens,
            actual_train_max_sequence_tokens=max(row["sequence_tokens"] for row in lengths),
            all_train_length_projection_drops_zero=True,
            recorded_evaluation_input_tokens=evaluation_tokens,
            sum_recorded_evaluation_input_tokens=sum(evaluation_tokens.values()),
            native_CPU_seconds=compute["cpu_seconds"], native_wall_seconds=compute["wall_seconds"],
            native_GPU_job_interval_hours=len(gpus) * compute["wall_seconds"] / 3600,
            native_stage_wall_seconds=stages,
            stage_wall_unallocated_seconds=(compute["wall_seconds"] - sum(stages.values()) if stages is not None else None),
            native_peak_allocated_bytes=compute["peak_cuda_allocated_bytes"], native_peak_reserved_bytes=reserved,
            memory_measurement_scope=memory_scope,
            whole_child_CPU_seconds_if_measured=outer_cpu,
            whole_child_wall_seconds_if_measured=outer_wall,
            whole_child_GPU_job_interval_hours_if_measured=(len(gpus) * outer_wall / 3600 if outer_wall is not None else None),
            whole_child_CPU_residual_over_native_if_measured=residual,
            unmeasured_parent_and_outside_child_cleanup_CPU="unknown_not_zero; not filled from native or whole-child timing",
            fixed_evaluated_cut=evaluated_cut, profile_only=directory.startswith("p0-"),
            native_test_loaded=False, new_model_HTTP_or_ledger_calls=0))
    a0, a1, b0, b1 = rows[2:6]
    for pair in [(rows[0], rows[1]), (a0, a1), (b0, b1)]:
        assert pair[0]["actual_draws"] == pair[1]["actual_draws"]
        assert pair[0]["actual_optimizer_updates"] == pair[1]["actual_optimizer_updates"]
    profiles = [[json.loads(line) for line in (root / directory / "update-profile.jsonl").read_text().splitlines()]
                for directory in ["p0-float32", "p0-bf16"]]
    assert all(len(profile) == 32 for profile in profiles)
    assert [[(row["rows"], row["input_tokens"], row["padded_input_tokens"]) for row in profile]
            for profile in profiles][0] == [
                (row["rows"], row["input_tokens"], row["padded_input_tokens"]) for row in profiles[1]]
    steady = {}
    for row, profile in zip(rows[:2], profiles):
        assert sum(update["input_tokens"] for update in profile) == row["actual_train_input_tokens"]
        selected = profile[4:]
        steady[row["precision"]] = dict(warmup_updates_retained_in_cost=4, steady_updates=28,
            mean_update_wall_seconds=sum(update["wall_seconds"] for update in selected) / 28,
            measured_update_wall_seconds=sum(update["wall_seconds"] for update in selected),
            input_tokens=sum(update["input_tokens"] for update in selected))
    steady["FP32_over_BF16_mean_update_time"] = (
        steady["float32"]["mean_update_wall_seconds"] / steady["bf16"]["mean_update_wall_seconds"])
    return dict(status="EIGHT_CLOSED_NEW_GOAL_TRAINING_PROFILE_JOBS_RECONCILED_FROM_ACTUAL_SCHEDULES_AND_NATIVE_RECORDS",
        rows=rows, totals=dict(jobs=len(rows), profile_jobs=2, full_fit_jobs=6,
            optimizer_updates=sum(row["actual_optimizer_updates"] for row in rows),
            draws=sum(row["actual_draws"] for row in rows),
            train_input_tokens=sum(row["actual_train_input_tokens"] for row in rows),
            recorded_evaluation_input_tokens=sum(row["sum_recorded_evaluation_input_tokens"] for row in rows),
            native_CPU_seconds=sum(row["native_CPU_seconds"] for row in rows),
            native_GPU_job_interval_hours=sum(row["native_GPU_job_interval_hours"] for row in rows),
            whole_child_instrumentation_jobs=sum(row["whole_child_CPU_seconds_if_measured"] is not None for row in rows)),
        P0_steady_28_update_profile=steady,
        paired_treatment_facts=dict(A1_minus_A0_actual_train_tokens=a1["actual_train_input_tokens"]-a0["actual_train_input_tokens"],
            A1_minus_A0_padded_train_tokens=a1["actual_train_padded_input_tokens"]-a0["actual_train_padded_input_tokens"],
            B0_B1_draws_updates_and_train_tokens_equal=b0["actual_train_input_tokens"] == b1["actual_train_input_tokens"]),
        cost_scope="Native CPU and GPU intervals already included in prior paid evidence; this report adds no charge. Whole child, native and residual are alternative nested views and must never be added together. GPU interval includes load/evaluation/save/waits and is not active kernel time.",
        missing_scope="E3 padded tokens, reserved peak, native stage times and recorded TF32 flags absent; P0/A whole-child/parent startup cleanup unmeasured here. These stay unknown, not zero.",
        excludes="Historical E3 seed0/common E1 upstream training; P0 reloaded inference; data/branch preparation and feedback; all task inference, Source/storage, analysis and external jobs. Not final all-project costs, FLOPs, Host GPU busy time or currency.",
        conditional_A20k_B192_J_not_triggered_and_twelve_fit_cap_not_quota=True,
        original_results_labels_weights_frozen_protocols_or_recipes_changed=False,
        new_model_HTTP_or_ledger_calls=0, no_sha_validation=True, goal_complete=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_root", type=Path)
    parser.add_argument("new_summary", type=Path)
    args = parser.parse_args()
    result = analyze(args.artifact_root.resolve())
    with args.new_summary.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(result["status"])
    print(json.dumps(result["totals"], ensure_ascii=False))


if __name__ == "__main__":
    main()
