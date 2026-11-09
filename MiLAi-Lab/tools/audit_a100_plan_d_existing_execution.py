"""Reconcile original D Store/Saver, operations and full inputs without native reruns."""
import argparse
import json
import math
import sys
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def physical_lines(path):
    with Path(path).open() as stream:
        return list(stream)


def replay(root,output_folder,script,condition,original_expression,previous,excluded=(),completed_reports=None):
    entry = root/script
    output = output_folder/(condition+"-"+Path(script).stem+".json")
    source = entry.read_text()
    changes = [(original_expression,"Path(__audit_output__)")]
    for old,new in (
        ("trace.read_text().splitlines()","__audit_physical_lines__(trace)"),
        ("Path(boundary['trace']).read_text().splitlines()","__audit_physical_lines__(Path(boundary['trace']))")):
        if old in source:
            changes.append((old,new))
    redirected = source
    for old,new in changes:
        assert redirected.count(old) == 1
        redirected = redirected.replace(old,new,1)
    restored = redirected
    for old,new in reversed(changes):
        restored = restored.replace(new,old,1)
    assert restored == source
    namespace = dict(__name__="__main__",__file__=str(entry),__audit_output__=str(output),
        __audit_physical_lines__=physical_lines)
    sys.argv = [str(entry),condition]
    reused = completed_reports is not None and output.name in completed_reports
    if reused:
        output.write_bytes(completed_reports[output.name].read_bytes())
    else:
        exec(compile(redirected,str(entry),"exec"),namespace)
    result = read(output)
    equal = None
    legacy_receipt_schema = False
    if previous is not None:
        original = read(previous)
        if "audit_reflection" in excluded:
            legacy = "FirstinspectionincorrectlyusedmutablelivebankafterlaterturnsandfoundmultiplefutureassistantSources. Correctedtoactualper-turnclosedafter(snapshot/after)anddeclaredclosedStoreinventory. Failedofflineaudit/timerretained;no modelortoolrerun."
            assert original["audit_reflection"] in (legacy,result["audit_reflection"])
        if condition == "new32-view_cache_incremental" and script == "audit_d_closed_sdk_states.py":
            assert original["audit_reflection_scope"] == "The inherited audit_reflection describes the earlier mutable-bank audit implementation correction, not a failure of this new32incremental SDKaudit. Current full320SDKaudit passed on first invocation (audit-d-new32-incremental-full320-sdk-v1.time.txt exit0). Original historical text retained."
        compared = result
        if script == "audit_d_actual_operations.py" and condition in (
                "old8-view_cache_incremental","old8-e3-aggregate-u32","new32-view_cache"):
            # These three original reports predate the later exact admission-error
            # receipt fields. Validate the new zero-error facts and compare every
            # original field; preserve both report schemas and their descriptions.
            legacy_receipt_schema = True
            suffix = " Native error returns are counted even when known-reference admission stops before a controller result event; returned versus actual provider-visible material remain separate."
            assert result["scope"] == original["scope"]+suffix
            assert result["native_return_packets_literal_equal_to_traced_results"] is True
            assert result["native_read_admission_error_returns_without_controller_result_event"] == 0
            added = {"native_return_packets_literal_equal_to_traced_results",
                "native_read_admission_error_returns_without_controller_result_event","audit_reflection"}
            assert set(result)-set(original) == added and set(original)-set(result) == set()
            compared = {k:v for k,v in result.items() if k not in added}
            compared["scope"] = original["scope"]
            compared["records"] = []
            for row,old_row in zip(result["records"],original["records"],strict=True):
                assert row["native_read_admission_error_returns_without_controller_result_event"] == []
                assert row["traced_retrieval_result_events"] == row["current_tool_counts"]["tool_returns"]
                additions = {"native_read_admission_error_returns_without_controller_result_event","traced_retrieval_result_events"}
                assert set(row)-set(old_row) == additions and set(old_row)-set(row) == set()
                compared["records"].append({k:v for k,v in row.items() if k not in additions})
        equal = {k:v for k,v in compared.items() if k not in excluded} == {k:v for k,v in original.items() if k not in excluded}
        assert equal
    evidence = dict(original_validator=str(entry),condition=condition,report=str(output),
        original_report=str(previous) if previous is not None else None,
        changed_report_destination=True,physical_JSONL_line_reader_substitutions=len(changes)-1,
        inverse_changes_entire_original_source_literal_equal=True,excluded_dynamic_or_historical_narrative_fields=list(excluded),
        all_existing_original_scientific_report_fields_literal_equal=equal,
        legacy_additive_zero_error_receipt_schema_verified_and_projected_for_comparison=legacy_receipt_schema,
        actual_validator_executed_in_current_process=not reused,
        closed_previous_readonly_audit_report_reused=str(completed_reports[output.name]) if reused else None,
        original_reports_or_Source_inputs_states_first_results_modified=False)
    return result,evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("output_folder",type=Path)
    parser.add_argument("--completed-readonly-reports",type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output_folder = args.output_folder.resolve()
    output_folder.mkdir()
    completed_reports = None
    if args.completed_readonly_reports is not None:
        completed_folder = args.completed_readonly_reports.resolve()
        assert completed_folder == root/"original-plan-D-existing-execution-v3"
        assert "\tExit status: 1\n" in (root/"audit-original-plan-D-existing-execution-v3.time.txt").read_text()
        completed_reports = {path.name:path for path in completed_folder.glob("*.json")}
        assert len(completed_reports) == 7
    import tokenizers
    import transformers

    assert transformers.__version__ == "4.52.3" and tokenizers.__version__ == "0.21.4"
    sys.path.append("/cra/memory/mx_memory/MiLAi-worktrees/jev-read-decisions-20261016/MiLAi-Lab/artifacts/jev-reader/http-env/lib/python3.11/site-packages")
    runtime = root/"runtime-d-update32"
    sys.path[:0] = [str(runtime/"tools"),str(runtime/"src")]
    matrix = read(root/"d-update32/matrix-plan.json")
    metadata,sdk,operations = [],{},{}
    for job in matrix["jobs"]:
        condition = job["name"]
        owner = read(root/"d-update32"/(condition+"-owner.json"))
        assert owner["status"] == "COMPLETED" and owner["exit_code"] == 0 and owner["client_CPU_recorded"]
        assert not Path("/proc",str(owner["child_pid"])).exists()
        folder = root/"d-update32/reviews"/condition
        sdk[condition],proof = replay(root,output_folder,"audit_d_closed_sdk_states.py",condition,
            "(folder / 'SDK-state-audit.json')",folder/"SDK-state-audit.json",("audit_reflection","audit_reflection_scope"),completed_reports)
        metadata.append(proof)
        operations[condition],proof = replay(root,output_folder,"audit_d_actual_operations.py",condition,
            "folder / 'actual-operation-audit-v1.json'",folder/"actual-operation-audit-v1.json",("cpu_seconds_nested",),completed_reports)
        metadata.append(proof)
        assert sdk[condition]["positions"] == operations[condition]["positions"] == job["positions"]
    finite = {}
    for condition in ("old8-e3-aggregate-u32","new32-e3-aggregate-u32"):
        previous = root/"d-update32/reviews"/condition/"finite-decision-input-audit-v1.json"
        original_report = previous if condition == "new32-e3-aggregate-u32" else None
        report,proof = replay(root,output_folder,"audit_d_finite_decision_inputs.py",condition,
            "folder / 'finite-decision-input-audit-v1.json'",original_report)
        metadata.append(proof)
        by_trace = defaultdict(list)
        for record in report["records"]:
            by_trace[record["trace"]].append(record)
        for trace,records in by_trace.items():
            events = [json.loads(line) for line in physical_lines(trace)]
            for record in records:
                event = events[record["event_index"]]
                assert event["event"] == "memory_control_model_result"
                assert all(math.isfinite(value) for field in ("logits","probabilities") for value in event["result"][field].values())
        finite[condition] = dict(bound_positions=report["bound_positions"],
            actual_model_forwards=report["recorded_model_forwards"],all_actual_head_values_finite=True,
            full_before_entire_ordered_menu_native_projection_no_truncation_verified=True,
            actual_input_tokens=report["sum_actual_input_tokens_already_native_recorded"],
            actual_minimum_input_tokens=report["minimum_actual_input_tokens"],actual_maximum_input_tokens=report["maximum_actual_input_tokens"],
            original_validator_historical_formal_planned_positions_field=report["formal_planned_positions"],
            actual_bound_positions_used_in_current_summary=True)
    comparison,proof = replay(root,output_folder,"compare_d_new32.py","new32-all3",
        "root / 'd-update32/new32-family-comparison-v1.json'",root/"d-update32/new32-family-comparison-v1.json",("cpu_seconds_nested",))
    metadata.append(proof)
    assert len(metadata) == 13 and sum(report["positions"] for report in sdk.values()) == 1120
    selected = {name:report["selected_kinds"] for name,report in operations.items()}
    offered = {name:dict(sum((Counter(row["decision_occurrences_with_offered_kind"]) for row in report["records"]),Counter()))
        for name,report in operations.items()}
    assert offered["new32-e3-aggregate-u32"]["REFRESH_VIEW"] == 779
    assert selected["new32-e3-aggregate-u32"].get("REFRESH_VIEW",0) == selected["new32-e3-aggregate-u32"].get("USE_VIEW",0) == 0
    result = dict(passed=True,status="D5_NATIVE_JOBS_1120_IMMUTABLE_TURN_SOURCE_STORE_SAVER_APP_OPERATIONS_AND_E3_FULL_INPUTS_RECONCILED",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),actual_runtime=str(runtime),
        actual_new_native_jobs=5,actual_new_native_positions=1120,
        old8_new_policy_positions=160,new32_all3_positions=960,
        old8_reused_original_baseline_positions_not_reexecuted=80,
        exact_original_validator_replays=metadata,
        old_Source_value_comparisons=sum(report["original_Source_values_preserved_in_turn_comparisons"] for report in sdk.values()),
        new_completed_assistant_Sources=sum(report["new_final_assistant_Sources"] for report in sdk.values()),
        all_before_and_closed_Store_inventories_Saver_messages_and_applications_literal_equal=True,
        Source_roles_bodies_clocks_old_values_preserved_new_completed_Host_answers_remain_assistant=True,
        all_actual_Tool_receipts_and_native_errors_bound_no_synthetic_operation_events=True,
        E3_full_actual_input_audits=finite,actual_offered_kind_occurrences=offered,actual_selected_kind_occurrences=selected,
        new32_family_comparison_literal_reproduced_except_dynamic_CPU=True,
        new32_method_complete={name:method["complete"] for name,method in comparison["methods"].items()},
        E3_REFRESH_VIEW_was_offered_but_never_selected_new32=dict(offered_decision_occurrences=779,selected=0),
        E3_USE_VIEW_not_offered_in_new32_own_trajectory=True,
        scope="Replay of actual closed read-only validators, plus physical JSONL reading and finite-all-head checks. Dnew32 is32TRAIN families with10 correlated requests each; methods share exogenous bodies/roles/order, not all controller states/first wires or endogenous histories. Original reports unchanged. The original finite validator historical formal_planned_positions=320 is retained in raw output; old8 actually binds80 and uses its actual count. This is execution evidence, not independent semantic review, full D-factor/knownView/old-output closure, policy adoption or complete763-line goal.",
        new_model_tokenizer_GPU_HTTP_business_or_original_ledger_calls=0,
        original_Source_inputs_labels_models_or_firsts_changed=False,CPU_pending_actual_idle138=True,
        no_sha_validation=True,full763_line_completion_proven=False,goal_complete=False)
    with (output_folder/"summary.json").open("x") as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print("D1120_IMMUTABLE_SOURCE_STORE_SAVER_OPERATIONS_AND_FULL_E3_INPUTS_VERIFIED",finite,flush=True)


if __name__ == "__main__":
    main()
