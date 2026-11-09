"""Reproduce D control paired statistics and paid cost receipts using an existing frozen snapshot."""
import argparse
import json
import sys
from datetime import datetime,timezone
from pathlib import Path

from audit_a100_plan_d_existing_execution import read


def reproduce(entry,changes,namespace):
    source = entry.read_text()
    revised = source
    for old,new in changes:
        assert revised.count(old) == 1
        revised = revised.replace(old,new,1)
    restored = revised
    for old,new in reversed(changes):
        restored = restored.replace(new,old,1)
    assert restored == source
    exec(compile(revised,str(entry),"exec"),dict(__name__="__main__",__file__=str(entry),**namespace))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("output",type=Path)
    args = parser.parse_args()
    root,output = args.root.resolve(),args.output.resolve()
    output.mkdir()
    runtime = root/"runtime-d-update32"
    sys.path[:0] = [str(runtime/"src"),str(runtime/"tools")]
    mem_plan = read(root/"external-own-policy-v1/stages-mem2act-v1/fixed-prefix-prediction400-v1-plan.json")
    snapshot = Path(mem_plan["budget_before_snapshot"])
    original_ledger = Path("/cra/memory/mx_memory/MiLAi/MiLAi-Lab/artifacts/ser-v20/budget.json")
    assert snapshot.resolve() != original_ledger and snapshot.is_file()
    known_path = output/"known-View-control-closeout-reproduced.json"
    reproduce(root/"close_d_known_view_controls.py",[
        ("ledger = read_json(Path(read_json(folder / 'execution-plan-v3.json')['original_ledger']))",
         "ledger = read_json(Path(__frozen_budget_snapshot__))"),
        ("folder / 'known-View-control-closeout-v1.json'","Path(__known_output__)"),
    ],dict(__frozen_budget_snapshot__=str(snapshot),__known_output__=str(known_path)))
    known = read(known_path)
    assert known == read(root/"d-controls-v1/known-View/known-View-control-closeout-v1.json")
    old_path,comparison_path = output/"old-output-control-closeout-reproduced.json",output/"old-output-family-comparison-reproduced.json"
    reproduce(root/"close_d_old_output_controls.py",[
        ("folder / 'old-output-family-comparison-v1.json'","Path(__comparison_output__)"),
        ("folder / 'old-output-control-closeout-v1.json'","Path(__old_output__)"),
    ],dict(__comparison_output__=str(comparison_path),__old_output__=str(old_path)))
    old,comparison = read(old_path),read(comparison_path)
    assert old == read(root/"d-controls-v1/old-output/old-output-control-closeout-v1.json")
    assert comparison == read(root/"d-controls-v1/old-output/old-output-family-comparison-v1.json")
    assert old["original_child_exit_code"] is None and old["lost_parent_CPU_seconds"] == "unknown_not_zero"
    assert old["unobserved_child_cleanup_CPU"] == "unknown_not_zero"
    result = dict(passed=True,status="D_CONTROL_ORIGINAL_PAIRED_STATISTICS_AND_KNOWN_PAID_COST_CLOSEOUTS_LITERAL_REPRODUCED_WITH_FROZEN_PRE_MEM_SNAPSHOT",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),actual_historical_snapshot=str(snapshot),
        original_live_ledger_read_or_written=False,
        known_View_original_closeout_entire_literal_equal=True,
        old_output_original_closeout_and_family_comparison_entire_literal_equal=True,
        only_known_View_ledger_input_replaced_by_existing_frozen_snapshot_and_three_report_destinations_changed=True,
        inverse_source_replacements_restore_both_entire_original_validators=True,
        known_View=dict(first_cells=9,actual_HTTP=8,known_Host_tokens_already_paid=75003,
            local_model_forwards=24,local_input_tokens=287238,admission_reservations=33,
            one_first_template_preflight_slot_consumed_without_HTTP=True,
            known_child_CPU_already_paid=known["whole_child_CPU_seconds_already_paid"],
            native_local_load_CPU_included_not_readded=known["native_local_and_load_CPU_seconds_already_paid"],
            residual_CPU_included_not_readded=known["client_residual_CPU_seconds_already_paid"],
            GPU_job_interval_including_waits=known["GPU_reserved_job_interval_hours_including_failed_jobs_and_waits"]),
        old_output=dict(first_cells=42,actual_HTTP=40,known_Host_tokens_already_paid=old["actual_known_Host_tokens_already_paid"],
            local_model_forwards=93,local_input_tokens=643723,admission_reservations=133,
            initial_capacity_failures_with_zero_forward_tool_and_Host_dispatch=2,
            observed_child_CPU_lower_bound_already_paid=old["whole_child_CPU_seconds_observed_lower_bound_already_paid"],
            native_local_load_CPU_included_not_readded=old["native_local_and_load_CPU_seconds_already_paid"],
            residual_lower_bound_included_not_readded=old["client_CPU_residual_observed_lower_bound_already_paid"],
            baseline_collection_CPU_already_paid_separately=old["baseline_tool_collection_CPU_seconds_already_paid"],
            unknown_parent_CPU=old["lost_parent_CPU_seconds"],unknown_child_cleanup_CPU=old["unobserved_child_cleanup_CPU"],
            original_exit_code=None,GPU_launch_to_observed_terminal_interval_upper_bound=old["GPU_launch_to_observed_terminal_interval_hours_upper_bound"]),
        old_output_first_inventory48_eligible42_ineligible6_not_imputed=comparison["original_first8_inventory"],
        old_output_by_method_condition=comparison["by_method_and_condition"],
        old_output_family_comparisons=comparison["comparisons"],Host_generation_seed_matched=False,
        scope="All original first failures/unknown cost fields and author judgments retained. Snapshot is the existing postidle137/preMem2Act budget copy, never the live original ledger or a second operational ledger. Reported costs already paid, no rebilling. Seven correlated TRAIN families and unmatched Host RNG do not identify general old-output harm/benefit. GPU job/observed intervals include waits, not active GPU compute; unknown parent/cleanup retain literal unknown_not_zero. Original exit code remains None. Original historical next fields are evidence of then-current scheduling, not a current queue.",
        new_model_tokenizer_GPU_HTTP_business_or_original_ledger_calls=0,
        original_Source_inputs_labels_models_or_firsts_changed=False,CPU_pending_actual_idle138=True,
        no_sha_validation=True,full763_line_completion_proven=False,goal_complete=False)
    with (output/"summary.json").open("x") as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print("D_CONTROL_COST_AND_PAIRED_CLOSEOUTS_LITERAL_REPRODUCED_FROM_FROZEN_SNAPSHOT_NO_LIVE_LEDGER",flush=True)


if __name__ == "__main__":
    main()
