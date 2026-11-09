"""Audit already executed old D native tool slices and post-View READ probes without replay."""
import argparse
import ast
import json
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

from audit_a100_plan_d_controls import application,source_values,store_values
from audit_a100_plan_d_existing_execution import read,replay


def events(capture,case,call):
    relative = call["host_prefix_trace"]
    prefix = (capture/"before"/relative).read_bytes()
    with (case/"runtime"/relative).open("rb") as stream:
        assert stream.read(len(prefix)) == prefix
        result = [json.loads(line) for line in stream if line.strip()]
    assert not any(event["event"] in ("memory_control_model_result","memory_control_model_load","vllm_response") for event in result)
    return result


def verify(capture,case):
    call,replayed = read(capture/"call.json"),read(case/"replay.json")
    result = replayed["result"]
    assert Path(replayed["captured_call"]).resolve() == capture.resolve()
    assert result["status"] == replayed["status"] == "COMPLETED"
    assert result["frozen_request_and_allowance_equal"] and result["frozen_initial_observation_and_actions_equal"]
    assert result["usage"] == [] and result["final_answer"] is None
    assert result["generation_calls"] == call["generation_calls_before"]
    assert result["records"] == result["memory_mutation_receipts"] == []
    for key in ("generation","generation_requests","embedding","limits"):
        assert replayed["budget_before"][key] == replayed["budget_after"][key]
    relative = Path(call["source_bank_root"]).relative_to(call["source_root"])
    before_bank,after_bank = capture/"before"/relative,case/"runtime"/relative
    before,after = source_values(store_values(before_bank)),source_values(store_values(after_bank))
    assert before == after and application(before_bank) == application(after_bank)
    suffix = events(capture,case,call)
    decisions = [event for event in suffix if event["event"] == "memory_control_step" and event["phase"] == "decision_output"]
    assert decisions and decisions[0]["before"] == call["initial_observation"] and decisions[0]["actions"] == call["initial_actions"]
    assert len(decisions) <= call["initial_observation"]["budget"]["remaining_control_steps"]
    actual_actions = []
    for decision in decisions:
        action, = [action for action in decision["actions"] if action["id"] == decision["selected"]]
        actual_actions.append(action)
    packet = result["retrieval_result"]
    receipt, = [message for message in result["messages"] if message.get("type") == "tool" and message.get("tool_call_id") == call["call_id"]]
    assert json.loads(receipt["content"]) == packet
    pieces = 0
    for material in packet["evidence"]:
        if material["kind"] != "original_source":
            continue
        for piece in material["evidence"]:
            start,end = piece["range"]
            matches = [source for source in after.values() if source["role"] == piece["role"] and source["origin"] == piece["origin"]
                and source["observed_at"] == piece["captured_at"] and source.get("occurred_at") == piece["reported_at"]
                and len(source["content"]) == piece["source_characters"] and 0 <= start <= end <= len(source["content"])
                and source["content"][start:end] == piece["content"]]
            assert matches
            pieces += 1
    return call,replayed,actual_actions,len(before),pieces


def ast_parts(path):
    text = path.read_text()
    return {node.name:ast.get_source_segment(text,node) for node in ast.parse(text).body
        if isinstance(node,(ast.ClassDef,ast.FunctionDef)) and node.name in (
            "text_overlap","source_relevance","_request_context","CacheMemoryPolicy")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("output",type=Path)
    args = parser.parse_args()
    root,output = args.root.resolve(),args.output.resolve()
    output.mkdir()
    protocol = read(root/"d-update32/protocol-before-body-projection.json")
    matrix = read(root/"d-update32/matrix-plan.json")
    close = read(root/"d-update32/optional-native-initial-slice-closeout.json")
    plan = read(root/"d-update32/optional-native-initial-slice-plan.json")
    assert [cell["family"] for cell in plan["cells"]] == protocol["old8"]["families"]
    first = {}
    for path in sorted((Path(matrix["reuse_output"])/"frozen-retrieval-calls").glob("*/call.json")):
        call = read(path)
        if call["initial_observation"] is None or not call["bank"].endswith("-content") or call["public_message"]["message_id"] != "initial":
            continue
        family = call["bank"].split("-e5-controlled-v1-")[0]
        if family not in first or call["captured_epoch"] < first[family][1]["captured_epoch"]:
            first[family] = (path.parent,call)
    actual,missing,source_comparisons,raw = [],[],0,0
    for index,(cell,record) in enumerate(zip(plan["cells"],close["records"],strict=True)):
        assert cell["family"] == record["family"]
        if cell["family"] not in first:
            assert cell == record and record["status"] == "NO_ACTUAL_INITIAL_CONTENT_TOOL_CAPTURE_RETAINED"
            missing.append(cell["family"])
            continue
        capture,original = first[cell["family"]]
        assert capture == Path(cell["capture"])
        case = Path(record["output"])
        call,replayed,actions,count,pieces = verify(capture,case)
        assert replayed["policy"] == cell["policy"] and replayed["source_version"] == cell["source_version"]["git_commit"]
        assert "intervention" not in replayed and replayed["result"]["frozen_start_step"] == 0
        assert count == record["original_Source_values_unchanged"]
        views = {row["key"]:row["value"] for row in store_values(case/"runtime"/Path(call["source_bank_root"]).relative_to(call["source_root"]))
            if row["namespace"][-1] == "query_structure_v1"}
        sources = source_values(store_values(capture/"before"/Path(call["source_bank_root"]).relative_to(call["source_root"])))
        packet = replayed["result"]["retrieval_result"]
        for item in packet["evidence"]:
            if item["kind"] == "query_structure":
                assert item["builder"] == "extractive"
                assert any(view.get("structure") == item["interpretation"] for view in views.values() if isinstance(view,dict))
        for view in views.values():
            if not isinstance(view,dict) or "structure" not in view:
                continue
            assert view["builder"] == "extractive"
            for node in view["structure"]["nodes"].values():
                assert any(node["text"] in sources[view["source_bindings"][alias]["source_ref"]]["content"] for alias in node["evidence"])
        actual.append(dict(family=cell["family"],initial_complete_before_full_menu_and_no_forced_intervention=True,
            selected_kind_counts=dict(Counter(action["kind"] for action in actions)),new_HTTP_or_model=0,
            before_after_whole_Source_comparisons=count,literal_raw_Source_pieces=pieces,
            actual_View_plus_raw="query_structure" in record["evidence_kinds"] and "original_source" in record["evidence_kinds"]))
        source_comparisons += count
        raw += pieces
    assert len(actual) == close["actual_executed_source_families"] == 7 and missing == close["unavailable_cells_retained"] == ["memops_B30"]
    assert sum(row["actual_View_plus_raw"] for row in actual) == close["View_plus_raw_packets"] == 3
    assert raw == close["native_Source_ranges"] == 9
    probes = read(root/"d-update32/old8-read-probe-plan.json")["records"]
    for index,probe in enumerate(probes):
        capture = Path(probe["capture"]).parent
        case = root/f"d-old8-read-probe/position-{index:02d}"
        call,replayed,actions,count,pieces = verify(capture,case)
        assert replayed["intervention"] == probe["intervention"]
        assert replayed["prefix_operations_reexecuted"] == 0 and replayed["restored_control_step"] == call["control_step"]
        assert actions[0] == probe["existing_READ_nomination"] and [action["kind"] for action in actions] == ["READ","HANDOFF"]
        assert probe["intervention"]["continuation_steps"] == 0
        source_comparisons += count
    report,proof = replay(root,output,"close_d_old8_read_probe.py","old8-post-View-probe",
        "(root / 'd-update32/old8-native-read-probe-closeout.json')",root/"d-update32/old8-native-read-probe-closeout.json")
    assert report["actual_saved_states"] == 9 and report["actual_View_plus_raw_packets"] == 9
    assert len(report["actual_source_backgrounds"]) == 5 and report["new_Host_answers"] == 0
    baseline_runtime = Path(protocol["old8"]["histories"]).parent/"runtime"
    assert ast_parts(root/"runtime-d-update32/src/milai_lab/methods/cache_memory_policy.py") == ast_parts(baseline_runtime/"src/milai_lab/methods/cache_memory_policy.py")
    result = dict(passed=True,status="D_OLD8_NATIVE_INITIAL_SLICE_AND_POST_GENERATED_VIEW_READ_FIRST_PROBES_RECONCILED_NO_REEXECUTION",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),original_baseline_cache_class_and_context_scoring_functions_literal_equal=True,
        optional_slice_planned_families=8,optional_slice_actual_native_first_tools=7,optional_slice_unavailable=missing,
        optional_slice_earliest_actual_initial_content_capture_per_family_verified=True,
        optional_slice_no_other_flow_later_turn_or_generated_builder_replacement=True,
        optional_slice_View_plus_raw_packets=3,optional_slice_raw_Source_pieces=9,
        optional_slice_actual_per_family=actual,
        post_generated_View_saved_states=9,post_generated_View_distinct_source_backgrounds=5,
        post_generated_View_plus_raw_packets=9,post_generated_View_actual_new_READ_then_HANDOFF_each=9,
        all_original_prefix_bytes_boundaries_complete_before_and_menus_verified=True,
        all_Source_bodies_roles_clocks_and_application_tables_unchanged=True,
        whole_before_after_Source_value_comparisons=source_comparisons,
        generated_View_structure_native_locator_and_factored_metadata_literal_preserved=True,
        restored_shared_generation_counter_kept_literal_not_reset_or_claimed_as_new_calls=True,
        original_post_View_probe_closeout_literal_reproduced=proof,
        actual_new_Host_readouts_or_answers_in_original_probes=0,
        scope="Actual original tool executions only:7initial extractive-policy packets from8predeclared families (B30has no initial capture), and9post-generated-View READ+HANDOFF probes across5backgrounds. Neither set has new Host answers. A fitting View+raw packet establishes executor capability, not clean/pending View reuse, generated factuality, task benefit or independent confirmation. Original selected READs and cached structures preserved, not retrospectively created. Historical budget copies only; no live original ledger or real tool/model rerun.",
        new_model_tokenizer_GPU_HTTP_business_or_original_ledger_calls=0,original_Source_inputs_labels_models_or_firsts_changed=False,
        CPU_pending_actual_idle138=True,no_sha_validation=True,full763_line_completion_proven=False,goal_complete=False)
    with (output/"summary.json").open("x") as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print("D_NATIVE_INITIAL7_OF8_AND_POST_VIEW9_ACROSS5_BACKGROUNDS_VERIFIED_NO_NEW_HOST_ANSWERS",flush=True)


if __name__ == "__main__":
    main()
