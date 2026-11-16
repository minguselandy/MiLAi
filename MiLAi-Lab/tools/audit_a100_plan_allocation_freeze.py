"""Audit source allocations, fixed-seed recipes and the confirmation freeze."""

import argparse
import copy
import json
import math
import sys
import tarfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def stamp(value):
    return datetime.fromisoformat(value).timestamp()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    final = root / "final-confirmation-v1"
    allocation = read(root / "source-allocation-v1.json")
    parent = read(allocation["parent_allocation"])
    groups = parent["groups"]
    assert len(groups) == len({row["source_group"] for row in groups})
    used = set(allocation["used_train_families"])
    native_dev = [
        row for row in groups if row["split"] == "unused" and row["native_split"] == "dev"
    ]
    native_train = [
        row for row in groups if row["split"] == "unused" and row["native_split"] == "train"
    ]
    expected_B64 = [
        row for row in groups if row["split"] == "train" and row["source_group"] not in used
    ][:64]
    assert [row["source_group"] for row in expected_B64] == [
        row["source_group"] for row in allocation["B64"]
    ]
    assert [row["source_group"] for row in native_dev[:64]] == [
        row["source_group"] for row in allocation["DEVELOPMENT64"]
    ]
    assert (native_dev[64:] + native_train)[:256] == [
        {key: value for key, value in row.items() if key != "study_role"}
        for row in allocation["CONFIRMATION256"]
    ]
    cohorts = {
        name: {row["source_group"] for row in allocation[name]}
        for name in ("B64", "DEVELOPMENT64", "CONFIRMATION256")
    }
    old32 = {row["source_group"] for row in groups if row["split"] == "dev"}
    assert (
        [len(cohorts[name]) for name in cohorts] == [64, 64, 256]
        and len(used) == 64
        and len(old32) == 32
    )
    sets = [used, old32, *cohorts.values()]
    assert all(not left & right for index, left in enumerate(sets) for right in sets[index + 1 :])
    assert all(row["study_role"] == "TRAIN" for row in allocation["B64"])
    assert all(row["study_role"] == "DEVELOPMENT" for row in allocation["DEVELOPMENT64"])
    assert all(row["study_role"] == "CONFIRMATION" for row in allocation["CONFIRMATION256"])
    assert Counter(row["native_split"] for row in allocation["CONFIRMATION256"]) == {
        "dev": 185,
        "train": 71,
    }

    replication = read(root / "e3-retained-replication/plan.json")
    source_plan = read(replication["source_plan"])
    (source_job,) = [job for job in source_plan["plans"] if job["run_id"] == "aggregate"]
    source_run = read(replication["source_run"])
    assert source_run == replication["source_recipe"] and source_run["seed"] == 0
    assert replication["selected_cut_before_replications"] == 32
    fields = [
        "data",
        "base_checkpoint",
        "physical_gpus",
        "device",
        "torch_version",
        "cuda_version",
        "precision",
        "reference_compile",
        "gradient_checkpointing",
        "backend",
        "task",
        "operation_state",
        "epochs",
        "planned_optimizer_updates",
        "checkpoint_axis",
        "dev_source",
        "batch_size",
        "gradient_accumulation",
        "max_len",
        "head_max_len",
        "train_states",
        "dev_states",
        "encoder_lr",
        "head_lr",
        "freeze_encoder",
        "objective",
        "evaluation_points",
        "feedback_dev",
        "feedback_dev_source",
        "loss_weighting",
        "evaluate_train",
        "train_eval_final_only",
        "evaluate_initial_dev",
        "shuffle_options",
        "calibration_test_loaded",
        "feedback_target",
        "replay_weight",
        "feedback_pool",
        "sampling",
        "tie_unknown_sampling",
        "pair_supervision",
        "selection_rule",
        "pair_mass_mode",
        "replay_objective",
        "replay_target_scope",
    ]
    seed_rows = []
    for job in replication["jobs"]:
        seed = job["seed"]
        expected = copy.deepcopy(source_job["argv"])
        expected[6] = job["output"]
        expected[expected.index("--seed") + 1] = str(seed)
        expected[expected.index("--compute-phase") + 1] = job["compute_phase"]
        assert (
            job["argv"] == expected
            and job["environment"] == source_job["environment"]
            and job["cwd"] == source_job["cwd"]
        )
        run = read(Path(job["output"]) / "run.json")
        assert all(run[field] == source_run[field] for field in fields)
        assert run["status"] == "COMPLETED" and run["seed"] == seed
        assert run["optimizer_updates"] == 128 and run["train_sequence_rows"] == 2048
        assert run["precision"] == "float32" and run["physical_gpus"] == [2, 3]
        assert run["base_checkpoint"] == replication["same_fixed_E1_u16_initialization"]
        assert job["fixed_evaluated_checkpoint"] == str(
            Path(job["output"]) / "checkpoints/update-32"
        )
        assert read(Path(job["output"]) / "lengths.json") == read(
            Path(replication["source_run"]).parent / "lengths.json"
        )
        seed_rows.append(
            dict(
                seed=seed,
                only_training_seed_output_compute_phase_changed=True,
                original_recipe_fields_checked=fields,
                full_fit_updates=128,
                draws=2048,
                actual_train_tokens=run["train_input_tokens"],
                fixed_evaluated_update=32,
                same_E1_initialization=True,
                precision="float32",
                physical_gpus=[2, 3],
            )
        )
    assert [row["seed"] for row in seed_rows] == [1, 2]
    seed_driver = read(root / "e3-retained-replication/driver.json")
    assert not seed_driver["active"] and len(seed_driver["completed"]) == 2

    protocol = read(final / "protocol-before-held-export.json")
    export_start = read(final / "semantic-export-started-v1.json")
    exported = read(final / "source-export-closeout-v1.json")
    basis = read(final / "source-review-guide-basis-before-model-v1.json")
    assert (
        stamp(protocol["timestamp_utc"])
        < stamp(export_start["timestamp_utc"])
        <= stamp(exported["timestamp_utc"])
        < stamp(basis["timestamp_utc"])
    )
    assert protocol["CONFIRMATION256_metadata"] == allocation["CONFIRMATION256"]
    assert (
        protocol["confirmation_families"] == 256 and protocol["planned_task_trajectories"] == 1024
    )
    assert protocol["native_partition_strata"] == {"dev": 185, "train": 71}
    assert not protocol["held_bodies_or_annotations_semantically_opened_at_freeze"]
    assert not protocol["native_test_semantics_opened"] and not protocol["adopted"]
    development = read(root / "task-dev64/protocol-before-body-export.json")
    inherited = read(protocol["inherited_config_file"])
    assert inherited == development["config"] == read(root / "task-dev64/config.json")
    assert (
        protocol["Host"] == development["Host"]
        and protocol["inference"] == development["inference"]
    )
    selection = read(root / "task-dev64-development-selection.json")
    assert protocol["methods"][0]["name"] == selection["strong_simple_reference"] == "fixed-prefix"
    assert (
        protocol["methods"][1]["name"]
        == selection["retained_learned_reference"]["name"]
        == "e3-aggregate-u32"
    )
    assert protocol["methods"][1]["policy"] == selection["retained_learned_reference"]["policy"]
    assert [method["training_RNG_seed"] for method in protocol["methods"][1:]] == [0, 1, 2]
    assert all(
        Path(method["policy"]["checkpoint"]).name == "update-32"
        for method in protocol["methods"][1:]
    )
    fixed_owner = read(final / "pilot8/anchor-owner-v1.json")
    assert stamp(basis["timestamp_utc"]) < fixed_owner["started_epoch"]
    for segment in ("pilot8", "remaining248"):
        owner = read(final / segment / "anchor-owner-v1.json")
        assert owner["exit_code"] == 0 and owner["client_CPU_recorded"]
        assert not any(Path("/proc", str(owner[key])).exists() for key in ("pid", "child_pid"))
    templates = read(final / "frozen-learned-method-job-templates-v1.json")
    assert stamp(protocol["timestamp_utc"]) < stamp(templates["timestamp_utc"])
    actual_methods = []
    for method, job in zip(protocol["methods"][1:], templates["jobs"], strict=True):
        directory = final / method["name"]
        owner = read(directory / "learned-owner-v1.json")
        plan = read(owner["plan"])
        assert owner["exit_code"] == 0 and owner["client_CPU_recorded"]
        assert not any(Path("/proc", str(owner[key])).exists() for key in ("pid", "child_pid"))
        assert owner["started_epoch"] > stamp(templates["timestamp_utc"])
        assert plan["argv"] == job["argv"] and plan["environment"] == job["environment"]
        assert read(plan["policy_config"]) == job["policy"] == method["policy"]
        driver = read(Path(plan["output"]) / "driver.json")
        assert len(driver["completed"]) == driver["planned_positions"] == 256
        assert [row["family"] for row in driver["completed"]] == [
            row["source_group"] for row in allocation["CONFIRMATION256"]
        ]
        assert driver["control_policy"] == method["policy"] and driver["host_enable_thinking"]
        actual_methods.append(
            dict(
                method=method["name"],
                positions=256,
                frozen_policy_and_command_literal_equal=True,
                actual_owner_exit0_CPU_paid_and_processes_gone=True,
                actual_firsts_include_native_failures=True,
            )
        )

    # Re-run only the pure source adapter on the already evaluated paper cohort.
    # Exact train/dev archive members are read; no native TEST member is opened.
    runtime = Path(protocol["runtime"])
    sys.path[:0] = [str(runtime / "src")]
    from milai_lab.datasets.qasper import export_paper, paper_sources

    histories = read(final / "histories.json")["histories"]
    references = read(final / "references.json")["cases"]
    assert len(histories) == len(references) == 256
    source_count = 0
    exported_by_family = {row["family"]: row for row in exported["records"]}
    archive_members = []
    with tarfile.open(exported["source_archive"]) as archive:
        for native_split in ("dev", "train"):
            member = f"qasper-{native_split}-v0.3.json"
            archive_members.append(member)
            with archive.extractfile(member) as stream:
                papers = json.load(stream)
            for index, group in enumerate(allocation["CONFIRMATION256"]):
                if group["native_split"] != native_split:
                    continue
                paper = papers[group["paper_id"]]
                history, controls = export_paper(
                    group["paper_id"], paper, native_split, max_questions=1, given_requests=False
                )
                (source,) = controls
                assert history == histories[index]
                expected_reference = dict(
                    family=history["source_group"],
                    history=history["id"],
                    request=history["requests"][0],
                    native_split=native_split,
                    native_control=source,
                )
                assert references[index] == expected_reference
                literal, _ = paper_sources(group["paper_id"], paper)
                assert history["sources"] == literal
                assert len(literal) == 1 + sum(
                    (section["section_name"] is not None) + len(section["paragraphs"])
                    for section in paper["full_text"]
                ) + len(paper["figures_and_tables"])
                assert set(history["requests"][0]) == {"id", "content"}
                assert (
                    source["native_question_id"]
                    == exported_by_family[group["source_group"]]["first_native_question_id"]
                )
                assert source["native_question_id"] == basis["records"][index]["native_question_id"]
                source_count += len(literal)
            del papers
    assert source_count == exported["source_units"] == 18932
    assert read(final / "pilot8/histories.json")["histories"] == histories[:8]
    assert read(final / "remaining248/histories.json")["histories"] == histories[8:]
    all4 = read(final / "source-author-quality-all4-methods-closeout-v1.json")
    assert all4["positions_each"] == 256 and all4["unique_source_families"] == 256
    assert (
        all4["whole_manual_judgments"] == 1024
        and not all4["adopted"]
        and not all4["frozen_methods_scoring_budgets_N_changed"]
    )
    assert all4["primary_remains_frozen_seed0_not_reselected"]
    assert [row["family"] for row in all4["per_position"]] == [
        row["source_group"] for row in allocation["CONFIRMATION256"]
    ]
    assert all4["first_native_failures_retained_by_method"] == {
        "fixed-prefix": 40,
        "e3-aggregate-u32": 52,
        "e3-aggregate-seed1-u32": 51,
        "e3-aggregate-seed2-u32": 61,
    }
    planning = read(root / "e3-retained-replication/family-comparison.json")[
        "conditional_power_planning"
    ]
    assert protocol["N_planning"]["latest_development_conditional_planning"] == planning
    approximation = (1.96 + 0.84) ** 2 * planning["family_difference_sample_variance"] / 0.05**2
    assert math.ceil(approximation) == 640 and protocol["N_planning"]["fixed_N"] == 256
    assert not protocol["N_planning"]["power_guarantee"]
    result = dict(
        passed=True,
        status=(
            "ORIGINAL_ALLOCATION_FIXED_INIT_SEEDS_AND_PRESEMANTIC_CONFIRMATION_FREEZE"
            "_BOUND_TO_ACTUAL_SOURCE_EXPORT_AND_FIRST_JOBS"
        ),
        timestamp_utc=datetime.now(UTC).isoformat(),
        actual_parent_allocation=str(Path(allocation["parent_allocation"])),
        parent_metadata_unused_dev=len(native_dev),
        parent_metadata_unused_train=len(native_train),
        actual_used_TRAIN64_B64_64_oldDEV32_newDEV64_CONFIRM256_pairwise_disjoint=True,
        entire_original_parent_order_and_native_partition_selection_reproduced=True,
        actual_source_roles=dict(
            old_used_TRAIN=64, new_TRAIN_B64=64, old_DEV=32, new_DEVELOPMENT=64, CONFIRMATION=256
        ),
        native_confirmation_strata=dict(dev=185, train=71),
        native_partition_not_study_role=True,
        seed1_seed2_full_recipe_and_argv_comparison=seed_rows,
        three_seeds_fixed_E1_initialization_training_RNG_not_full_chain_repeats=True,
        actual_freeze_timestamp=protocol["timestamp_utc"],
        actual_export_start=export_start["timestamp_utc"],
        actual_export_end=exported["timestamp_utc"],
        native_annotation_basis_before_first_model=basis["timestamp_utc"],
        method_checkpoint_Host_budget_and_N_frozen_before_selected_held_semantic_export=True,
        original_DEV64_common_Host_and_full_config_literal_inherited=True,
        fixed_primary_seed0_u32_not_reselected=True,
        shared_baseline256_firsts_not_reexecuted_per_seed=True,
        actual_frozen_learned_methods_and_256_firsts=actual_methods,
        all256_current_histories_and_offline_reference_dicts_literal_reexported=True,
        all18932_source_units_headings_paragraphs_captions_preserved=True,
        source_exporter_runtime=str(runtime),
        only_native_archive_members_read=archive_members,
        native_TEST_member_opened=False,
        no_given_retrieval_request_gold_Source_filter_or_table_repair=True,
        all1024_first_result_positions_original_failures_and_N_unchanged=True,
        conditional_development_variance=planning["family_difference_sample_variance"],
        hypothetical_plus5pp_required_N=640,
        actual_frozen_N=256,
        no_power_guarantee_or_outcome_based_N_expansion=True,
        guide_mask_author_exposure_limitations_retained=all4["review_limitations"],
        scope=(
            "Prospective protected-semantic use under fixed "
            "methods/checkpoints/Host/budgets/N, not byte-level no-contact, "
            "public-pretraining isolation or independent/blind author judgment. "
            "Earlier DEV64 parsing touched shared native-dev container bytes but "
            "only its64paper semantics were exported. Current pure reexport reads "
            "train/dev containers for the already evaluated allocated256 only; no "
            "nativeTEST member. Native DEV185/TRAIN71 is separate from study roles. "
            "Original labels/first failures remain; common122mask formed after "
            "baseline80/primary16 review and later82/101/231 guide disclosures "
            "remain, not retrospectively prespecified. Seed1/2 share "
            "fixedE1initializer and original128-update FP32 two-GPU recipe; their "
            "preselectedu32 is evaluated, full fit cost retained."
        ),
        new_model_tokenizer_GPU_HTTP_business_or_original_ledger_calls=0,
        original_Source_inputs_labels_models_or_firsts_changed=False,
        CPU_pending_actual_idle138=True,
        no_sha_validation=True,
        full763_line_completion_proven=False,
        goal_complete=False,
    )
    with args.output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(
        (
            "ALLOCATION64_64_256_FIXED_INIT_SEEDS_PRESEMANTIC_FREEZE_AND18932_ACTUAL_"
            "SOURCE_UNITS_VERIFIED"
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
