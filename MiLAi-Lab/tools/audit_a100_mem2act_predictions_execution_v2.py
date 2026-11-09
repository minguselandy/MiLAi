"""Read-only full-bank/Host/catalog/SDK/finite-NN audit of closed Mem2Act predictions."""
import argparse
import json
import math
import sqlite3
from collections import Counter
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def lines(path):
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream]


def store_values(bank):
    database=Path(bank)/"memory.sqlite"
    with sqlite3.connect(database.resolve().as_uri()+"?mode=ro",uri=True) as connection:
        return {(prefix,key):json.loads(value) for prefix,key,value in connection.execute(
            "SELECT prefix,key,value FROM store")}


def application_values(bank):
    database=Path(bank)/"applications/reservation/application.sqlite"
    with sqlite3.connect(database.resolve().as_uri()+"?mode=ro",uri=True) as connection:
        return {table:sorted(connection.execute("SELECT * FROM "+table).fetchall())
                for table in ("settings","world_events","reservations","attempts")}


def bank(root):
    database,=Path(root).glob("banks/*/memory.sqlite")
    return database.parent


def control_events(events,settings,learned):
    from milai_lab.memory.literal_projection import expand_observation_state
    from milai_lab.methods.laya_memory_policy import ACTION_BOUND_PROJECTIONS,operation_payload,project_operation_payload
    from milai_lab.methods.memory_control import MemoryAction,MemoryControlState
    projection=settings["state_projection"]
    selector=projection if projection in ACTION_BOUND_PROJECTIONS else "full"
    pending,modeled,records,forced={}, {}, [], []
    operations=Counter()
    current=None
    for position,event in enumerate(events):
        if event["event"]=="memory_control_step" and event["phase"]=="decision_input":
            current=(event["retrieval_call_id"],event["step"])
            assert current not in pending
            pending[current]=event
        elif event["event"]=="memory_control_model_result":
            # Capture/replay sets max_concurrency=1. The model return belongs to
            # the immediately preceding synchronous decision input, even if a
            # previous failed call left an identical, unfinished input.
            assert current in pending and current not in modeled
            before=pending[current]
            payload=operation_payload(MemoryControlState(**before["before"]),
                [MemoryAction(**action) for action in before["actions"]],selector)
            assert project_operation_payload(payload,projection)==event["input"]
            expanded=expand_observation_state(event["input"]["state"])
            assert expanded.pop("action_bindings")==before["actions"] and expanded==before["before"]
            criteria={action["id"]:action["kind"] for action in before["actions"]}
            result=event["result"]
            assert event["input"]["questions"]["next"]["criteria"]==criteria
            assert list(result["logits"])==list(result["probabilities"])==list(criteria)
            assert all(math.isfinite(value) for field in ("logits","probabilities") for value in result[field].values())
            assert result["choice"]==max(result["probabilities"],key=result["probabilities"].get)
            assert result["truncated"] is False and 0<result["input_tokens"]<=settings["max_len"]
            modeled[current]=result
            records.append({"trace_event_index":position,"call_id":current[0],"step":current[1],
                "choice":result["choice"],"input_tokens":result["input_tokens"],
                "offered_actions":len(before["actions"]),"whole_before_all_bindings_head_ID_order_equal":True,
                "finite_argmax_untruncated":True})
        elif event["event"]=="memory_control_step" and event["phase"]=="decision_output":
            key=(event["retrieval_call_id"],event["step"])
            assert key in pending and event["actions"]==pending[key]["actions"]
            chosen,=[action for action in event["actions"] if action["id"]==event["selected"]]
            operations[chosen["kind"]]+=1
            if key in modeled:
                assert event["selected"]==modeled.pop(key)["choice"] and event["selection_mode"]=="policy"
            elif learned:
                only,=event["actions"]
                assert only["id"]==event["selected"] and event["selection_mode"]=="only_available_action"
                forced.append({"call_id":key[0],"step":key[1],"choice":only["id"]})
            else:
                assert event["selection_mode"] in ("policy","only_available_action")
            pending.pop(key)
            current=None
    interrupted=[{"call_id":key[0],"step":key[1],"complete_logged_before":event["before"],
        "complete_offered_actions":event["actions"],"returned_model_result":modeled.get(key),
        "scope":"Unfinished decision retained. Without a model-result event, no successful forward or consumed packed input is inferred; failure/compute remains in the original trajectory and owner cost."}
        for key,event in pending.items()]
    return {"records":records,"audited_returned_NN_predictions":len(records),
        "actual_returned_input_tokens":sum(row["input_tokens"] for row in records),
        "forced_single_action_decisions":forced,"selected_operations":dict(operations),
        "interrupted_decisions":interrupted,
        "scope":"All returned finite predictions and complete logged before/menu/bindings. Unfinished decisions are not dropped, repaired, or counted as zero-cost successful forwards; no effective16k, all-bank-delivery or answer-truth claim."}


def audit_case(case,task,protocol,initial_sources,method,baseline_case=None):
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    from milai_lab.runners.action_intents import proposed_business_calls
    from audit_native_delivered_context import sdk_delivered_context
    from audit_native_source_rows import assert_original_sources_preserved,source_values
    assert case["qa_id"]==task["qa_id"] and case["status"] not in ("NOT_RUN","PREPARING_INPUT","HOST_RUNNING","FAILED_WRAPPER")
    path=Path(case["result"]);result=read(path);runtime=Path(case["runtime"])
    assert result["status"]==case["status"]
    assert result["message_id"]==task["qa_id"] and result["content"]==task["query"]
    assert result["recorded_tool_schemas"]==[task["target_tool_schema"]]
    assert "given_retrieval_request" not in result
    assert result["records"]==[]
    receipt_field_present="memory_mutation_receipts" in result
    if result["status"]=="COMPLETED" or receipt_field_present:
        assert result["memory_mutation_receipts"]==[]
    else:
        assert result["status"]=="FAILED"
    receipt_field={"native_field_present":receipt_field_present,
        "native_literal_value":result["memory_mutation_receipts"] if receipt_field_present else None,
        "missing_native_failure_field_inferred_empty":False,
        "Source_Store_Saver_world_and_application_checks_still_required":True}
    proposals=proposed_business_calls(result["messages"],memory_tool_names={"milai_retrieve"})
    assert proposals==case["proposed_business_calls"]
    assert result.get("recorded_tool_calls",[])==case["recorded_capture_only_intents"]
    captured=Path(case["first_host_capture"] if method=="fixed" else baseline_case["first_host_capture"])
    host=read(captured/"host.json")
    assert host["schema"]=="frozen_host_message_v1" and host["status"]=="CAPTURED_PRE_HOST"
    assert host["public_message"]["content"]==task["query"]
    assert host["public_message"]["recorded_tool_schemas"]==[task["target_tool_schema"]]
    before_bank=captured/"before"/Path(host["source_bank_root"]).relative_to(host["source_root"])
    before,after=store_values(before_bank),store_values(path.parent)
    assert before=={(".".join(row["namespace"]),row["key"]):row["value"] for row in host["ready_state"]["memory_store_values"]}
    assert not before.keys()-after.keys()
    changes=[{"namespace":prefix.split(".")[-1],"key":key,
        "fields":sorted(field for field in before[prefix,key].keys()|after[prefix,key].keys()
                        if before[prefix,key].get(field)!=after[prefix,key].get(field))}
        for prefix,key in before.keys()&after.keys() if before[prefix,key]!=after[prefix,key]]
    assert all(row["namespace"]=="v13_2_public_turns" and row["fields"]==["last_binding_phase"] for row in changes)
    old_sources=source_values(before_bank);actual_sources=source_values(path.parent)
    assert_original_sources_preserved(initial_sources,old_sources)
    assert_original_sources_preserved(old_sources,actual_sources)
    assert result["world"]==host["ready_state"]["world"]
    assert application_values(before_bank)==application_values(path.parent)
    thread,=[thread for thread in read(path.parent/"thread-index.json") if thread["identity"]["v13_turn_id"]==task["qa_id"]]
    with sqlite3.connect((path.parent/"checkpoints.sqlite").resolve().as_uri()+"?mode=ro",uri=True) as connection:
        kind,blob=connection.execute("SELECT type,checkpoint FROM checkpoints WHERE thread_id=? ORDER BY checkpoint_id DESC LIMIT 1",(thread["id"],)).fetchone()
    checkpoint=JsonPlusSerializer().loads_typed((kind,blob))
    assert [message.model_dump(mode="json") for message in checkpoint["channel_values"]["messages"]]==result["messages"]
    stem=path.name.removesuffix("-result.json")
    trace=path.with_name(stem+f"-trace-{result['attempt']}.jsonl")
    events=lines(trace)
    responses=[event for event in events if event["event"]=="vllm_response"]
    first=responses[0]["request"] if responses else None
    paired_first=None
    structural=None
    if method=="primary":
        structural={key:result.get(key) for key in ("frozen_pre_host_state_equal","frozen_host_baseline_context_equal","frozen_host_tool_catalog_equal")}
        if responses:assert all(structural.values())
        replay=read(runtime.parent/"replay.json")
        expected={**read(captured/"before/input-freeze.json")["config"]["memory_control"],**protocol["primary_policy_override"]}
        assert replay["control_policy_override"]==expected
        if responses:assert replay["prefix_model_or_tool_operations_reexecuted"]==0
        baseline_result=read(baseline_case["result"]);baseline_path=Path(baseline_case["result"])
        baseline_trace=baseline_path.with_name(baseline_path.name.removesuffix("-result.json")+f"-trace-{baseline_result['attempt']}.jsonl")
        baseline_responses=[event for event in lines(baseline_trace) if event["event"]=="vllm_response"]
        if responses and baseline_responses:
            assert first==baseline_responses[0]["request"]
            paired_first=True
    else:
        expected=read(runtime/"input-freeze.json")["config"]["memory_control"]
    control=control_events(events,expected,method=="primary")
    packets=0
    for message in result["messages"]:
        if message["type"]=="tool" and message.get("name")=="milai_retrieve":
            packet=json.loads(message["content"])
            assert packet["schema"]=="milai_retrieval_result_v1"
            sdk_delivered_context(runtime,packet,{})
            packets+=1
    usage=[row for row in result["usage"] if row["event"]=="vllm_response"]
    assert len(usage)==len(responses)
    assert all(type(row["usage"]["total_tokens"]) is int for row in usage)
    unknown={kind:result["budget_after"][kind]["unknown_usage"]-result["budget_before"][kind]["unknown_usage"] for kind in ("generation","embedding")}
    assert all(value>=0 for value in unknown.values())
    return {"row":case["row"],"qa_id":task["qa_id"],"native_status":case["status"],"result":str(path),
        "original_capture":str(captured),"initial_Source_compared":len(initial_sources),
        "pre_first_Host_snapshot_replayable":host["initial_baseline_context"] is not None and host["initial_tool_catalog"] is not None,
        "pre_first_Source_compared":len(old_sources),"whole_old_Source_role_origin_clock_body_equal":True,
        "native_memory_mutation_receipt_field_evidence":receipt_field,
        "Store_changes":changes,"Saver_terminal_messages_equal":True,"world_and_application_equal":True,
        "native_SDK_packets_reconstructed":packets,"decoded_provider_responses":len(responses),
        "first_decoded_provider_request":first,"paired_first_decoded_request_equal":paired_first,
        "shared_pre_first_Host_checks":structural,"control":control,
        "known_HTTP_tokens":sum(row["usage"]["total_tokens"] for row in usage),"new_unknown_usage":unknown,
        "missing_decoded_first_request_is_retained_not_inferred_equal":first is None,
        "first_outcome_retry_or_semantic_correctness_claim":False}


def main(protocol_path,predictions,owner_path,output):
    import importlib.metadata
    import sys
    protocol=read(protocol_path)
    import transformers
    assert transformers.__version__=="4.52.3"
    for directory in protocol["site_packages"]:sys.path.append(directory)
    assert {name:importlib.metadata.version(name) for name in protocol["SDK_versions"]}==protocol["SDK_versions"]
    from audit_native_source_rows import source_values
    owner=read(owner_path)
    assert owner["client_CPU_recorded"] and "exit_code" in owner
    assert all(not Path("/proc",str(owner[key])).exists() for key in ("pid","child_pid"))
    driver=read(Path(predictions)/"driver.json")
    assert len(driver["cases"])==driver["planned_positions"]==400
    assert driver["status"] in ("COMPLETED","COMPLETED_WITH_FAILURES","FAILED")
    assert not any(case["status"] in ("NOT_RUN","PREPARING_INPUT","HOST_RUNNING") for case in driver["cases"])
    # Unresolved wrapper metadata failures require an evidence reconciliation;
    # they cannot silently erase a returned native result or certify400 tasks.
    assert all(case["status"]!="FAILED_WRAPPER" for case in driver["cases"])
    tasks=lines(protocol["public_tasks"]);assert len(tasks)==400
    initial=source_values(bank(protocol["prepared_template"]));assert len(initial)==16843
    baseline=read(Path(protocol["fixed_predictions"])/"driver.json") if driver["method"]=="primary" else None
    records=[audit_case(case,task,protocol,initial,driver["method"],baseline["cases"][index] if baseline else None)
             for index,(case,task) in enumerate(zip(driver["cases"],tasks,strict=True))]
    summary={"passed":True,"status":"ALL400_CLOSED_MEM2ACT_ORIGINAL_SOURCE_SDK_HOST_CATALOG_SAVER_AND_RETURNED_NN_AUDITED",
        "method":driver["method"],"positions":400,"records":records,"actual_owner":str(Path(owner_path).resolve()),
        "audit_execution_revision":2,"native_failure_success_only_receipt_fields_not_fabricated":True,
        "initial_Source_comparisons":sum(row["initial_Source_compared"] for row in records),
        "pre_first_Source_comparisons":sum(row["pre_first_Source_compared"] for row in records),
        "native_SDK_packets_reconstructed":sum(row["native_SDK_packets_reconstructed"] for row in records),
        "paired_first_decoded_provider_requests_equal":sum(row["paired_first_decoded_request_equal"] is True for row in records),
        "all400_fixed_first_Host_snapshots_replayable":all(row["pre_first_Host_snapshot_replayable"] for row in records),
        "cases_without_decoded_first_provider_request":sum(row["first_decoded_provider_request"] is None for row in records),
        "returned_NN_predictions_audited":sum(row["control"]["audited_returned_NN_predictions"] for row in records),
        "interrupted_decisions_retained":sum(len(row["control"]["interrupted_decisions"]) for row in records),
        "actual_first_predictions":str(Path(predictions).resolve()),
        "scope":"All400 planned native first outcomes, no label/gold-based row removal. Complete Source and returned finite-NN mechanism evidence, not task accuracy, effective16k proof, independent-user sampling, or inferred equality for missing provider requests.",
        "new_model_tokenizer_HTTP_business_or_ledger_calls":0,"first_outcome_retry":False,"no_sha_validation":True}
    with Path(output).open("x") as stream:json.dump(summary,stream,ensure_ascii=False,indent=2);stream.write("\n")
    print(summary["status"],400,summary["returned_NN_predictions_audited"])


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol",type=Path);parser.add_argument("predictions",type=Path)
    parser.add_argument("owner",type=Path);parser.add_argument("output",type=Path)
    args=parser.parse_args();main(args.protocol,args.predictions,args.owner,args.output)
