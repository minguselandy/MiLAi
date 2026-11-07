"""Census closed native operations, wire delivery and inclusive inference costs."""
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

lab = Path.cwd()
folder = Path(sys.argv[1]).resolve()
root = folder.parent
read = lambda path: json.loads(Path(path).read_text())
quality = read(folder / "source-author-quality-all4-methods-closeout-v1.json")
histories = read(folder / "histories.json")["histories"]
names = list(quality["methods"])
assert len(histories) == 256
all_rows, aggregates = [], {}

def trace_path(path, result):
    stem = path.name.removesuffix(f'-attempt-{result["attempt"]}.json').removesuffix('-result.json')
    return path.with_name(stem + f'-trace-{result["attempt"]}.jsonl')

for name in names:
    baseline = name == "fixed-prefix"
    base = folder if baseline else folder / name
    mappings = read(base / ("anchor-all256-results-v1.json" if baseline else "audit-all256-v1/results.json"))
    review = read(base / ("anchor-all256-review-input-v1.json" if baseline else "audit-all256-v1/review-input.json"))["records"]
    failed = {r["index"]: r for r in read(base / ("anchor-all256-failed-last-inputs-v1.json" if baseline else "audit-all256-v1/failed-last-inputs.json"))["records"]}
    finite = None if baseline else read(base / "audit-all256-v1/finite-input-audit.json")
    owner_paths = [folder / "pilot8/anchor-owner-v1.json", folder / "remaining248/anchor-owner-v1.json"] if baseline else [base / "learned-owner-v1.json"]
    owners = [read(path) for path in owner_paths]
    for owner in owners:
        assert owner["exit_code"] == 0 and owner["client_CPU_recorded"]
        assert owner["new_unknown_usage"] == {"generation": 0, "embedding": 0}
        assert all(not Path("/proc", str(owner[key])).exists() for key in ("pid", "child_pid"))
        assert abs(sum(owner["already_recorded_native_CPU"].values()) + owner["client_CPU_residual"] - owner["whole_child_CPU_seconds"]) < 1e-8
    rows = []
    for i, (record, history) in enumerate(zip(review, histories, strict=True)):
        family = record["family"]
        assert family == history["source_group"] == quality["per_position"][i]["family"]
        path = Path(mappings[family])
        assert str(path) == record["result_path"]
        result = read(path)
        assert result["status"] == record["result_status"]
        assert result["records"] == []
        native_sources = {(s["session"], s["capture_key"]): s for s in result["sources"]}
        original_ids = set()
        for source in history["sources"]:
            actual = native_sources[(source["session_id"], source["event_key"])]
            assert all(actual[key] == source[key] for key in ("content", "role", "origin"))
            original_ids.add(source["session_id"] + "/" + source["event_key"])
        trace = trace_path(path, result)
        events = [json.loads(line) for line in trace.read_text().splitlines()]
        responses = [event for event in events if event["event"] == "vllm_response"]
        usage = [item for item in result["usage"] if item["event"] == "vllm_response"]
        assert len(usage) == len(responses)
        for item, event in zip(usage, responses, strict=True):
            assert item["usage"] == event["usage"]
        for bucket in ("generation", "embedding"):
            assert result["budget_before"][bucket]["unknown_usage"] == result["budget_after"][bucket]["unknown_usage"]
        decisions, operations, operation_outcomes = [], [], Counter()
        nn = []
        returned, received, wire_messages = {}, {}, {}
        for event_index, event in enumerate(events):
            if event["event"] == "memory_control_step" and event["phase"] in ("decision_output", "operation_result"):
                action, = [a for a in event["actions"] if a["id"] == event["selected"]]
                if event["phase"] == "decision_output":
                    decisions.append({"trace_event_index": event_index, "call_id": event["retrieval_call_id"],
                        "step": event["step"], "full_selected_action": action, "offered_actions": len(event["actions"]),
                        "selection_mode": event["selection_mode"], "control_wall_seconds": event["control_wall_seconds"]})
                else:
                    outcome = event["result"]
                    operations.append({"trace_event_index":event_index,"call_id":event["retrieval_call_id"],
                        "step":event["step"],"full_selected_action":action,"ok":outcome["ok"],
                        "status":outcome["status"],"operation_wall_seconds":event["operation_wall_seconds"]})
                    operation_outcomes[action["kind"] + ":" + outcome["status"]] += 1
            elif event["event"] == "memory_control_model_result":
                predicted = event["result"]
                assert not predicted["truncated"]
                nn.append({key:predicted[key] for key in ("input_tokens","preparation_seconds","inference_seconds","wall_seconds","cpu_seconds","calibrated")})
            elif event["event"] == "milai_retrieve_result":
                call_id = event["call_id"]
                assert call_id not in returned
                returned[call_id] = {"trace_event_index":event_index,"packet":event["result"],"retrieval_wall_seconds":event["retrieval_wall_seconds"]}
            if event["event"] == "vllm_response":
                for message in event["request"]["messages"]:
                    if message["role"] == "tool" and message.get("name") == "milai_retrieve":
                        call_id = message["tool_call_id"]
                        if call_id in wire_messages:
                            assert wire_messages[call_id] == message
                        else:
                            wire_messages[call_id] = message
                            received[call_id] = json.loads(message["content"])
        for call_id in returned.keys() & received.keys():
            assert returned[call_id]["packet"] == received[call_id]
        material = record["material_binding"] if record["result_status"] == "COMPLETED" else failed[i]["material_binding"]
        assert material["unmatched_ranges"] == 0
        precise_ids, possible_ids = set(), set()
        ambiguous = 0
        for piece in material["visible_original_ranges"]:
            ids = piece["original_source_candidates"]
            assert ids and set(ids) <= original_ids
            possible_ids.update(ids)
            if len(ids) == 1:
                precise_ids.update(ids)
            else:
                ambiguous += 1
        packet_kinds = Counter(item["kind"] for receipt in material["visible_retrieval_receipts"] if receipt["status"] == "RETRIEVAL_PACKET_RETAINED" for item in receipt["packet"]["evidence"])
        usage_counts = Counter()
        terminations = Counter()
        for call_id, item in returned.items():
            packet = item["packet"]
            usage_counts.update(packet["usage"])
            terminations[packet["termination_reason"]] += 1
            results_for_call = [op for op in operations if op["call_id"] == call_id]
            assert len(results_for_call) == packet["usage"]["operations"]
            assert sum(op["full_selected_action"]["kind"] == "READ" for op in results_for_call) == packet["usage"]["read_operations"]
        q = quality["per_position"][i]["methods"][name]
        rows.append({"index":i,"family":family,"native_split":quality["per_position"][i]["native_split"],
            "native_result":str(path),"trace":str(trace),"native_status":result["status"],"quality":q["quality"],"material":q["material"],
            "initial_original_Source_count":len(history["sources"]),"initial_original_Source_characters":sum(len(s["content"]) for s in history["sources"]),
            "all_original_Source_contents_roles_origins_literal_equal":True,
            "HTTP_responses":len(usage),"native_generation_calls_field_includes_local_control":result["generation_calls"],
            "known_Host_prompt_tokens":sum(u["usage"]["prompt_tokens"] for u in usage),
            "known_Host_completion_tokens":sum(u["usage"]["completion_tokens"] for u in usage),
            "known_Host_total_tokens":sum(u["usage"]["total_tokens"] for u in usage),
            "native_provider_wall_seconds":sum(u["wall_seconds"] for u in usage),"current_tool_counts":record["current_tool_counts"],
            "selected_action_counts":dict(Counter(d["full_selected_action"]["kind"] for d in decisions)),
            "full_selected_action_bindings":decisions,"actual_operation_results":operations,"operation_kind_status_counts":dict(operation_outcomes),
            "native_retrieval_usage_counts":dict(usage_counts),"termination_reason_counts":dict(terminations),
            "native_tool_return_packets":len(returned),"distinct_tool_packets_in_actual_responded_provider_inputs":len(received),
            "returned_packets_without_a_responded_provider_input":sorted(returned.keys()-received.keys()),
            "wire_tool_messages_without_native_retrieval_result":sorted(received.keys()-returned.keys()),
            "whole_native_returned_and_wire_decoded_packets_literal_equal_on_common_call_ids":True,
            "final_or_failed_last_bound_tool_receipts":len(material["visible_retrieval_receipts"]),
            "final_or_failed_last_material_kinds":dict(packet_kinds),
            "literal_original_ranges":material["literal_matched_ranges"],
            "received_original_range_characters_including_repeated_pieces":sum(len(p["visible_piece"]["content"]) for p in material["visible_original_ranges"]),
            "full_original_range_pieces":sum(p["visible_piece"]["range"]==[0,p["visible_piece"]["source_characters"]] for p in material["visible_original_ranges"]),
            "uniquely_bound_received_original_ids":sorted(precise_ids),"possible_received_original_ids":sorted(possible_ids),
            "ambiguous_original_range_pieces":ambiguous,"actual_NN":nn})
    if not baseline:
        audit = read(base / "audit-all256-v1/closeout.json")
        selected = Counter()
        for row in rows:selected.update(row["selected_action_counts"])
        assert dict(selected) == audit["selected_native_action_kinds"]
        assert sum(len(row["actual_NN"]) for row in rows) == len(finite["records"]) == audit["actual_NN_forwards"]
        assert sum(n["input_tokens"] for row in rows for n in row["actual_NN"]) == finite["sum_actual_input_tokens_already_native_recorded"]
        assert abs(sum(n["cpu_seconds"] for row in rows for n in row["actual_NN"]) - sum(n["model_CPU_seconds_already_native_recorded"] for n in finite["records"])) < 1e-7
    else:
        assert not any(row["actual_NN"] for row in rows)
    actual_http = sum(row["HTTP_responses"] for row in rows)
    actual_tokens = sum(row["known_Host_total_tokens"] for row in rows)
    assert actual_http == sum(o["actual_new_HTTP"] if baseline else o["actual_HTTP_responses"] for o in owners)
    assert actual_tokens == sum(o["actual_known_generation_tokens"] if baseline else o["known_HTTP_tokens"] for o in owners)
    counters = {}
    for field in ("selected_action_counts","operation_kind_status_counts","native_retrieval_usage_counts","termination_reason_counts","final_or_failed_last_material_kinds","current_tool_counts"):
        count = Counter()
        for row in rows:count.update(row[field])
        counters[field] = dict(count)
    model_rows = [n for row in rows for n in row["actual_NN"]]
    aggregate = {"positions":256,"main_C":quality["methods"][name]["main_C"],"material_S":quality["methods"][name]["material_counts"]["S"],
        "native_statuses":dict(Counter(row["native_status"] for row in rows)),
        **{field:sum(row[field] for row in rows) for field in ("HTTP_responses","known_Host_prompt_tokens","known_Host_completion_tokens","known_Host_total_tokens","native_provider_wall_seconds","initial_original_Source_count","initial_original_Source_characters","native_tool_return_packets","distinct_tool_packets_in_actual_responded_provider_inputs","final_or_failed_last_bound_tool_receipts","literal_original_ranges","received_original_range_characters_including_repeated_pieces","full_original_range_pieces","ambiguous_original_range_pieces")},
        **counters,"NN_forwards":len(model_rows),"NN_input_tokens":sum(n["input_tokens"] for n in model_rows),
        "native_NN_CPU_seconds_nested":sum(n["cpu_seconds"] for n in model_rows),
        "native_NN_preparation_seconds":sum(n["preparation_seconds"] for n in model_rows),
        "native_NN_inference_seconds":sum(n["inference_seconds"] for n in model_rows),
        "native_NN_wall_seconds":sum(n["wall_seconds"] for n in model_rows),
        "owners": [{"file":str(p),**{key:o[key] for key in ("whole_child_CPU_seconds","wall_seconds","already_recorded_native_CPU","client_CPU_residual","parent_CPU_seconds_through_billing","new_unknown_usage")}} for p,o in zip(owner_paths,owners,strict=True)],
        "whole_job_child_inclusive_CPU_plus_measured_parent_CPU":sum(o["whole_child_CPU_seconds"]+o["parent_CPU_seconds_through_billing"] for o in owners),
        "sum_actual_owner_wall_seconds":sum(o["wall_seconds"] for o in owners),
        "GPU2_job_interval_hours_including_HTTP_IO_wait_not_GPU_busy_hours":None if baseline else owners[0]["one_GPU2_job_interval_hours"],
        "retained_unmetered_author_launch_cleanup_CPU":"unknown_not_zero",
        "returned_packets_without_responded_input":sum(len(row["returned_packets_without_a_responded_provider_input"]) for row in rows),
        "wire_packets_without_native_result":sum(len(row["wire_tool_messages_without_native_retrieval_result"]) for row in rows),
        "all_original_Source_and_common_native_return_wire_packet_comparisons_literal_equal":True}
    aggregates[name] = aggregate
    all_rows.append({"method":name,"records":rows})
    print("NATIVE_CENSUS",name,{k:aggregate[k] for k in ("positions","HTTP_responses","known_Host_total_tokens","NN_forwards","native_tool_return_packets","literal_original_ranges","whole_job_child_inclusive_CPU_plus_measured_parent_CPU")},flush=True)
output = {"status":"ALL4_FULL256_NATIVE_OPERATION_SOURCE_DELIVERY_AND_INCLUSIVE_INFERENCE_COST_CENSUS_CLOSED",
    "timestamp_utc":datetime.now(timezone.utc).isoformat(),"positions_each":256,"methods":aggregates,"per_position":all_rows,
    "native_first_failures_retained_and_charged":True,"all1024_first_native_results_and_trace_paths_bound":True,
    "whole_job_CPU_includes_native_model_load_forward_and_client_residual_once":True,
    "Source_delivery_scope":"Every initial original Source body/role/origin compared to native Source. Literal material ranges refer to completed-final or failed-last actual input Tool receipts, not all initial/history material. Returned retrieval packets and distinct packets in every actual responded provider input are separately counted and whole-dict compared on common call IDs. Unanswered provider requests may be missing from this responded-wire union. Equal text with distinct Source identities stays distinct; ambiguity retained, not arbitrarily deduplicated. Characters are not tokens and repeated received pieces are counted as volume, not independent facts.",
    "operation_scope":"All selected action bindings and operation-result phases are separate. Selection and successful opening do not guarantee handoff or enough material. READ, budget rejection and HANDOFF retain native definitions. Native NN timings are measured instrumentation, not CUDA kernel busy time or effective16k context evidence.",
    "cost_scope":"Closed confirmation inference only; includes all failed first outcomes and measured whole childCPU plus parent through billing, with NN/load CPU nested and never added twice. Job wall/GPU2occupancy includes HTTP waits/copies/load and is not activeGPUkernelhours or HostGPU0/1compute. Setup/training/panel-selection/analysis/archives and unknown author/launch/cleanup remain separate for final full-project costs. Native usage/paid owner receipts are read only; no second ledger, monetary-price estimate or new charge.",
    "quality_scope":"Joined frozen source-author whole-task labels; no mediator subgroup establishes a causal delivery/quality effect, no result-based seed/stratum/budget/scorer selection or adoption.",
    "readonly_schema_failure_reflection":str(root/"inspect-native-cost-schema-v2-reflection-v1.json"),
    "new_model_HTTP_calls":0,"operational_ledger_opened_or_written":False,"native_or_prior_cost_rebilled":False,
    "no_sha_validation":True,"goal_complete":False}
target = Path(sys.argv[2]).resolve()
with target.open("x") as stream:
    json.dump(output,stream,ensure_ascii=False,indent=2)
    stream.write("\n")
print("ALL4_NATIVE_CENSUS_CLOSED",str(target),flush=True)
