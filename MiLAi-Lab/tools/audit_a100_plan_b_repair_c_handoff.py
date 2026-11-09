"""Reconcile actual functional8/C8 Source effects, full inputs and earliest bindings."""
import argparse
import copy
import json
import math
import sqlite3
import sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def lines(path):
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def sources(bank):
    with sqlite3.connect((bank/"memory.sqlite").resolve().as_uri()+"?mode=ro",uri=True) as db:
        return {key:json.loads(value) for prefix,key,value in db.execute("SELECT prefix,key,value FROM store")
                if prefix.split(".")[-1] == "v13_1_sources"}


def application(bank):
    with sqlite3.connect((bank/"applications/reservation/application.sqlite").resolve().as_uri()+"?mode=ro",uri=True) as db:
        return {table:sorted(db.execute("SELECT * FROM "+table).fetchall())
                for table in ("settings","world_events","reservations","attempts")}


def effects(capture,case,packet):
    call = read(capture/"call.json")
    relative = Path(call["source_bank_root"]).relative_to(call["source_root"])
    before_bank,after_bank = capture/"before"/relative,case/"runtime"/relative
    before,after = sources(before_bank),sources(after_bank)
    assert before == after and application(before_bank) == application(after_bank)
    replay = read(case/"replay.json")
    assert replay["result"]["records"] == [] and replay["result"]["memory_mutation_receipts"] == []
    pieces = 0
    for material in packet["evidence"]:
        assert material["kind"] == "original_source"
        for piece in material["evidence"]:
            start,end = piece["range"]
            matches = [source for source in after.values() if source["role"] == piece["role"]
                and source["origin"] == piece["origin"] and source["observed_at"] == piece["captured_at"]
                and source.get("occurred_at") == piece["reported_at"]
                and len(source["content"]) == piece["source_characters"]
                and 0 <= start <= end <= len(source["content"]) and source["content"][start:end] == piece["content"]]
            assert matches
            pieces += 1
    return len(before),pieces


def receipt(case):
    folder = case/"host-readout"
    report,wire = read(folder/"readout.json"),read(folder/"request.json")
    event, = [event for event in lines(folder/"trace.jsonl") if event["event"] == "vllm_response"]
    assert event["request_sent"] and event["request"] == wire and report["actual_http_attempts"] == 1
    assert report["automatic_retry"] is False
    before,after = report["budget_before"],report["budget_after"]
    assert all(after[key]["unknown_usage"] == before[key]["unknown_usage"] for key in ("generation","embedding"))
    known = after["generation"]["known_tokens"]-before["generation"]["known_tokens"]
    assert known == event["usage"]["total_tokens"]
    return report,wire,known


def normalized_wire(wire):
    result = copy.deepcopy(wire)
    body = json.loads(result["messages"][1]["content"])
    body["memory"] = None
    result["messages"][1]["content"] = body
    return result


def check_head(prediction,actions,full_menu_choice):
    ids = [action["id"] for action in actions]
    assert list(prediction["logits"]) == list(prediction["probabilities"]) == ids
    assert all(math.isfinite(value) for field in ("logits","probabilities") for value in prediction[field].values())
    assert prediction["truncated"] is False and 0 < prediction["input_tokens"] <= 16384
    assert prediction["choice"] == full_menu_choice(actions,prediction["logits"])


def functional(root):
    from feedback_outcomes import observed_outcome

    bound = read(root/"b-functional8-bound-results.json")
    nominees = read(root/"b-functional8-actual-nominations.json")
    source_count = pieces = known = 0
    kinds,statuses = Counter(),Counter()
    for record,nominee in zip(bound["records"],nominees,strict=True):
        capture,case = Path(nominee["capture"]),Path(record["origin"]["case"])
        actual = observed_outcome(capture,record["origin"])
        assert actual["action"] == record["action"] == nominee["action"]
        assert actual["packet"] == record["packet"] and actual["wire"] == record["readout_wire"]
        call = read(capture/"call.json")
        assert call["host_request_generated"] is False and call["request"].get("task_context",{}).get("known_evidence_refs",[]) == []
        count,ranges = effects(capture,case,actual["packet"])
        source_count += count
        pieces += ranges
        report,wire,tokens = receipt(case)
        assert report["status"] == record["readout_status"] and report.get("answer") == record["answer"]
        assert wire == actual["wire"]
        known += tokens
        kinds[actual["action"]["kind"]] += 1
        statuses[report["status"]] += 1
    assert len(nominees) == bound["states"] == 8 and kinds == {"READ":5,"HANDOFF":3}
    assert pieces == bound["Source_ranges"] == 16 and known == bound["known_generation_tokens"] == 30879
    return dict(states=8,actual_kinds=dict(kinds),actual_Source_range_pieces=pieces,
        whole_before_after_Source_values_compared=source_count,applications_unchanged=True,
        actual_full_before_menu_prefix_bounded_continuation_packet_Reader_wire_verified=True,
        actual_HTTP=8,known_Host_tokens=known,first_readout_statuses=dict(statuses),
        fabricated_Host_known_refs=0,semantic_records_or_business_writes=0,
        scope="Eight exposed TRAIN functional first bindings, not autonomous Host or independent confirmation.")


def c8(root):
    from feedback_choices import full_menu_choice
    from milai_lab.memory.literal_projection import expand_observation_state
    from milai_lab.methods.laya_memory_policy import operation_payload,project_operation_payload
    from milai_lab.methods.memory_control import MemoryAction,MemoryControlState
    from prepare_e1_choice_branches import binding_equal
    from summarize_handoff_comparison import completed_tool

    old = read(root/"c-handoff8-bound-results.json")
    quality = read(root/"c-handoff8-quality-review.json")
    grades = {row["case"]:row for row in quality["records"]}
    retained = read(root/"c-handoff8-retained-model-results.json")
    e3 = read(root/"c-handoff8-e3-saved-choices.json")
    new = read(root/"c-handoff8-new6-outcomes-for-review.json")
    new_grades = read(root/"c-handoff8-new6-author-decisions.json")["decisions"]
    new_plan = read(root/"c-handoff8-new-bindings/plan.json")
    new_policies = read(root/"c-handoff8-new-bindings/policies.json")
    registry,normalized = [],{}
    source_count = pieces = known = model_inputs = model_tokens = 0
    statuses = Counter()
    for record in [*old["records"],*new["records"]]:
        case = Path(record["case"])
        replay = read(case/"replay.json")
        capture = Path(replay["captured_call"]).resolve()
        call = read(capture/"call.json")
        trace = case/"runtime"/call["host_prefix_trace"]
        prefix = (capture/"before"/call["host_prefix_trace"]).read_bytes()
        with trace.open("rb") as stream:
            assert stream.read(len(prefix)) == prefix
            events = [json.loads(line) for line in stream if line.strip()]
        if "policy" in record:
            tool = completed_tool(case,capture,replay["policy"],replay["source_version"])
        else:
            index = record["index"]
            job,expected_binding = new_policies[index],new_plan["new_distinct_bindings"][index]
            assert replay["policy"] == job["policy"] and replay["intervention"] == job["intervention"]
            assert replay["status"] == replay["result"]["status"] == "COMPLETED"
            assert replay["prefix_operations_reexecuted"] == 0
            assert replay["result"]["frozen_initial_observation_and_actions_equal"]
            assert replay["result"]["frozen_request_and_allowance_equal"]
            assert job["intervention"]["continuation_steps"] == 0
            decision, = [event for event in events if event["event"] == "memory_control_step"
                and event["phase"] == "decision_output"]
            assert decision["before"] == call["initial_observation"] and decision["actions"] == call["initial_actions"]
            assert decision["selection_mode"] == "intervention_first_action"
            actual_action, = [action for action in decision["actions"] if action["id"] == decision["selected"]]
            assert actual_action == expected_binding["action"] == job["intervention"]["first_action"]
            assert actual_action["kind"] == "HANDOFF"
            actual_receipt, = [message for message in replay["result"]["messages"]
                if message.get("type") == "tool" and message.get("tool_call_id") == call["call_id"]]
            actual_packet = json.loads(actual_receipt["content"])
            assert actual_packet == replay["result"]["retrieval_result"]
            tool = dict(action=actual_action,packet=actual_packet)
        action = record["tool"]["action"] if "tool" in record else record["actual_action"]
        packet = record["tool"]["packet"] if "tool" in record else record["packet"]
        assert tool["action"] == action and tool["packet"] == packet
        count,ranges = effects(capture,case,packet)
        source_count += count
        pieces += ranges
        report,wire,tokens = receipt(case)
        known += tokens
        statuses[report["status"]] += 1
        assert report.get("answer") == record["answer"]
        body = json.loads(wire["messages"][1]["content"])
        assert body["memory"] == packet and body["retrieval_request"] == call["request"]
        expected_wire = normalized_wire(wire)
        state_index = record["state_index"]
        if state_index in normalized:
            assert normalized[state_index] == expected_wire
        else:
            normalized[state_index] = expected_wire
        policy_inputs = [event for event in events if event["event"] == "handoff_comparison_input"]
        offered = [action for action in call["initial_actions"] if action["kind"] == "HANDOFF"]
        if "policy" in record:
            policy_input, = policy_inputs
            assert policy_input["state"] == call["initial_observation"] and policy_input["actions"] == offered
        else:
            assert policy_inputs == []
        modeled = [event for event in events if event["event"] == "memory_control_model_result"]
        if record.get("policy") == "laya":
            event, = modeled
            expected = project_operation_payload(operation_payload(MemoryControlState(**policy_input["state"]),
                [MemoryAction(**a) for a in offered],"shared_actions"),"shared_actions")
            assert expected == event["input"]
            decoded = expand_observation_state(event["input"]["state"])
            assert decoded.pop("action_bindings") == offered and decoded == call["initial_observation"]
            check_head(event["result"],offered,full_menu_choice)
            assert event["result"]["choice"] == action["id"]
            model_inputs += 1
            model_tokens += event["result"]["input_tokens"]
        else:
            assert modeled == []
        grade = grades[str(case)] if "policy" in record else new_grades[record["index"]]
        assert (grade["answer_status"] == "failed") == (report["status"] == "FAILED")
        registry.append(dict(state_index=state_index,action=action,source_case=str(case),
            answer_status=grade["answer_status"],material_status=grade["material_status"],
            first_readout_status=report["status"],generation_requests_before=report["budget_before"]["generation_requests"]))
    assert len(registry) == 30 and model_inputs == 8 and len(normalized) == 8
    assert sum(row["known_generation_tokens"] for row in old["records"]) == 71109
    saved_proofs,complete = [],{}
    jobs = [*read(root/"c-handoff8-saved-plan.json")["jobs"],*read(root/"c-handoff8-e3-saved-plan.json")["jobs"]]
    for job in jobs:
        directory = Path(job["output"])
        run = read(directory/"run.json")
        assert run["status"] == "COMPLETED" and run["completed_states"] == 8
        assert run["loaded_weight_dtype"] == "torch.float32" and run["device"] == "cuda:0"
        selected_records = e3["records"] if job["name"] == "e3" else retained["conditions"][job["name"]]["records"]
        rows = lines(run["data"])
        assert len(rows) == len(selected_records) == 8
        for index,(row,selected_record) in enumerate(zip(rows,selected_records,strict=True)):
            capture = Path(row["metadata"]["path"])
            call = read(capture/"call.json")
            offered = [action for action in call["initial_actions"] if action["kind"] == "HANDOFF"]
            actual = read(directory/f"calls/{index}/input.json")
            expected = project_operation_payload(operation_payload(MemoryControlState(**call["initial_observation"]),
                [MemoryAction(**a) for a in offered],"shared_actions"),"shared_actions")
            assert actual == expected
            prediction = read(directory/f"calls/{index}/output.json")
            check_head(prediction,offered,full_menu_choice)
            action, = [action for action in offered if action["id"] == prediction["choice"]]
            assert action == selected_record["action"] and selected_record["state_index"] == index
            matches = [entry for entry in registry if entry["state_index"] == index and binding_equal(entry["action"],action)]
            assert matches
            earliest = min(matches,key=lambda entry:entry["generation_requests_before"])
            for key in ("source_case","answer_status","material_status","first_readout_status"):
                assert selected_record[key] == earliest[key]
            saved_proofs.append(dict(model=job["name"],state_index=index,input_tokens=prediction["input_tokens"],
                full_before_original_HANDOFF_menu_input_and_finite_head_equal=True,
                exact_full_binding_earliest_actual_generation_request_retained=True))
        complete[job["name"]] = sum(row["answer_status"] == "complete" for row in selected_records)
    assert complete == {"initial":1,"b0":1,"b1":1,"e3":1}
    assert len(saved_proofs) == 32 and retained["actual_new_HTTP"] == 6 and e3["new_distinct_bindings"] == []
    return dict(acquired_pools=8,original_three_policy_firsts=24,new_distinct_saved_bindings=6,
        before_after_whole_Source_values_compared=source_count,actual_Source_range_pieces=pieces,
        applications_unchanged=True,semantic_records_or_business_writes=0,
        original_policy_model_inputs=8,original_policy_model_input_tokens=model_tokens,
        original_policy_complete={key:value["complete"] for key,value in quality["by_method"].items()},
        saved_model_whole_before_original_HANDOFF_menu_and_finite_head_checks=32,
        saved_models_complete=complete,saved_choices_earliest_actual_generation_request_verified=32,
        E3_new_Reader_calls=0,actual_HTTP=30,known_Host_tokens=known,first_readout_statuses=dict(statuses),
        all_Reader_wires_equal_except_actual_packet_within_state=True,
        initial_B0_B1_historical_mtime_selection_checked_against_actual_generation_request_chronology=True,
        original_menus_unchanged=True,menu_expansion_justified=False,adoption=False,saved_model_proofs=saved_proofs,
        scope="Eight exposed TRAIN acquired pools, full declared HANDOFF restriction before encoding. Original24 plus six distinct saved-model bindings. First Reader failures retained; no autonomous Host or independent-source benefit established.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("component",choices=("functional8","c8"))
    parser.add_argument("output",type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    import tokenizers
    import transformers

    assert transformers.__version__ == "4.52.3" and tokenizers.__version__ == "0.21.4"
    sys.path.append("/cra/memory/mx_memory/MiLAi-worktrees/jev-read-decisions-20261016/MiLAi-Lab/artifacts/jev-reader/http-env/lib/python3.11/site-packages")
    runtime = root/("runtime-b-functional8" if args.component == "functional8" else "runtime-c-handoff8")
    sys.path[:0] = [str(runtime/"tools"),str(runtime/"src")]
    result = functional(root) if args.component == "functional8" else c8(root)
    result.update(passed=True,status="ACTUAL_B_FUNCTIONAL_OR_C_HANDOFF_INPUT_SOURCE_AND_FIRST_RESULTS_RECONCILED",
        component=args.component,timestamp_utc=datetime.now(timezone.utc).isoformat(),actual_frozen_runtime=str(runtime),
        Source_author_implementation_review_not_independent_human_or_blind=True,
        new_model_tokenizer_GPU_HTTP_business_or_original_ledger_calls=0,
        original_inputs_labels_or_first_results_changed=False,full763_line_completion_proven=False,
        CPU_pending_actual_idle138=True,no_sha_validation=True,goal_complete=False)
    with args.output.open("x") as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print("B_REPAIR_C_HANDOFF_INPUT_SOURCE_FIRST_RESULTS_VERIFIED",args.component,flush=True)


if __name__ == "__main__":
    main()
