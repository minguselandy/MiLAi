"""Reconcile frozen D controls through read-only SQLite, native Source APIs and exact inputs."""
import argparse
import ast
import __future__
import json
import math
import sqlite3
import sys
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace

from audit_a100_plan_d_existing_execution import read,replay,physical_lines


def functions(path,names,namespace):
    text = path.read_text()
    nodes = [node for node in ast.parse(text).body if isinstance(node,ast.FunctionDef) and node.name in names]
    assert {node.name for node in nodes} == set(names) and len(nodes) == len(names)
    for node in nodes:
        assert ast.get_source_segment(text,node) is not None and not node.decorator_list
    module = ast.Module(body=nodes,type_ignores=[])
    exec(compile(module,str(path),"exec",flags=__future__.annotations.compiler_flag),namespace)
    return SimpleNamespace(**{name:namespace[name] for name in names})


def ro_connection(path):
    return sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,check_same_thread=False)


def store_values(bank):
    with ro_connection(bank/"memory.sqlite") as db:
        return sorted([dict(namespace=prefix.split("."),key=key,value=json.loads(value))
            for prefix,key,value in db.execute("SELECT prefix,key,value FROM store")],key=lambda row:(row["namespace"],row["key"]))


def source_values(store):
    return {row["key"]:row["value"] for row in store if row["namespace"][-1] == "v13_1_sources"}


def application(bank):
    with ro_connection(bank/"applications/reservation/application.sqlite") as db:
        return {table:sorted(db.execute("SELECT * FROM "+table).fetchall())
            for table in ("settings","world_events","reservations","attempts")}


def native_projection(bank,call,settings,expected,lock_path):
    from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore
    from milai_lab.memory.service import MemoryService
    from milai_lab.runners.frozen_host_message import memory_store_values

    original = store_values(bank)
    with ro_connection(bank/"memory.sqlite") as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(store)")}
        assert {"prefix","key","value","created_at","updated_at","expires_at","ttl_minutes"} <= columns
        db.execute("PRAGMA query_only=ON")
        native_store = TransactionalSqliteStore(db)
        # This immutable database already has the original SDK schema. Declaring
        # setup complete avoids the normal setup DDL on the read-only connection.
        native_store.is_setup = True
        assert native_store.index_config is None and native_store.ttl_config is None
        service = MemoryService(native_store,tuple(call["binding"]["bank"]),call["binding"]["owner"],lock_path,
            functional_contract="functional_v1",memory_profile=settings.get("memory_profile","ordinary"),
            memory_ranking=settings.get("memory_ranking","dense"))
        assert memory_store_values(service) == original
        assert service.sources() == expected
        assert memory_store_values(service) == original and db.total_changes == 0
    assert store_values(bank) == original


def verify_anchors(decision,record,known):
    host = record["Host_source_binding"]
    if host is None:
        assert decision["grade"] == "F"
        return
    anchors = decision.get("anchors",[]) if known else decision["actual_Host_anchors"]
    for anchor in anchors:
        mi,ei = anchor["message_index"],anchor["evidence_index"]
        message = record["actual_provider_request"]["messages"][mi]
        assert message["role"] == "tool"
        evidence = json.loads(message["content"])["evidence"][ei]
        if anchor["kind"] == "View":
            occurrence, = [row for row in host["Views"] if row["message_index"] == mi and row["evidence_index"] == ei]
            node, = [row for row in occurrence["nodes"] if row["node_id"] == anchor["node_id"]]
            assert anchor["text"] in node["node"]["text"]
            assert all(source["literal_full_body_match"] and all(source["metadata_checks"].values()) for source in node["source_bindings"])
            if not known:
                assert anchor["actual_node"] == node["node"] and anchor["literal_Source_bindings"] == node["source_bindings"]
        else:
            si = anchor["source_index"]
            piece = evidence["evidence"][si]
            assert anchor["text"] in piece["content"]
            actual, = [row for row in host["original_ranges"]["visible_original_ranges"]
                if (row["message_index"],row["evidence_index"],row["source_index"]) == (mi,ei,si)]
            assert actual["metadata_matched_source_candidates"]
            if not known:
                assert anchor["actual_visible_piece"] == piece
                assert anchor["metadata_matched_Source_candidates"] == actual["metadata_matched_source_candidates"]
    for quote in decision.get("issues",[]) + decision.get("issue_quotes",[]):
        assert quote in record["answer"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("component",choices=("known-View","old-output"))
    parser.add_argument("output",type=Path)
    args = parser.parse_args()
    root,output = args.root.resolve(),args.output.resolve()
    output.mkdir()
    known = args.component == "known-View"
    folder = root/"d-controls-v1"/args.component
    import tokenizers
    import transformers

    assert transformers.__version__ == "4.52.3" and tokenizers.__version__ == "0.21.4"
    sys.path.append("/cra/memory/mx_memory/MiLAi-worktrees/jev-read-decisions-20261016/MiLAi-Lab/artifacts/jev-reader/http-env/lib/python3.11/site-packages")
    runtime = root/("runtime-d-update32" if known else "runtime-d-old-output-v1")
    sys.path[:0] = [str(runtime/"tools"),str(runtime/"src")]
    from milai_lab.runners.frozen_host_readout import readout_answer,substitute_receipt

    old = Path("/cra/memory/mx_memory/MiLAi-worktrees/evidence-gap-development-20261023/MiLAi-Lab/artifacts/development-training-20261102/e5-controlled-lifecycle-v1")
    visible = functions(runtime/"tools/prepare_qasper_host_review.py",["visible_original_ranges"],dict(json=json)).visible_original_ranges
    binding = functions(old/"bind_review.py",["bind_sources","source_inventory_binding"],dict(visible_original_ranges=visible))
    views = functions(old/"bind_views.py",["resolve_source_binding"],{})
    original_binder = root/("bind_d_known_view_controls.py" if known else "bind_d_old_output_controls.py")
    bind = functions(original_binder,["bind_materials"],dict(json=json,binding=binding,views=views)).bind_materials
    packet = read(folder/"reviews-v1/source-review-packet-v1.json")
    decisions = read(folder/"reviews-v1/author-decisions-v1.json")
    quality = read(folder/"reviews-v1/answer-review-closeout-v1.json")
    assert len(packet["records"]) == len(decisions) == (9 if known else 42)
    total_sources = http = known_tokens = structural = sdk = host_views = component_views = 0
    raw_ranges = 0
    rows,frames,view_groups = [],{},[]
    for record,decision in zip(packet["records"],decisions,strict=True):
        index,family = record["index"],record["family"]
        assert index == decision["index"] and family == decision["family"] and record["method"] == decision["method"]
        assert (decision["grade"] == "F") == (record["status"] != "COMPLETED")
        assert decision["source_author_not_independent_or_blind"]
        capture = Path(record["captured_call"])
        call = read(capture/"call.json")
        preparation = read(folder/family/"preparation.json")
        before_bank = capture/"before"/preparation["bank_relative"]
        before = store_values(before_bank)
        before_sources = source_values(before)
        available = [row["declared"] for row in record["controlled_exogenous_sources"]]
        assert binding.bind_sources(available,before) == record["controlled_exogenous_sources"]
        if not known:
            common = source_values(read(preparation["common_Store_values"]))
            assert before_sources == common
            old_ref = record["earlier_Host_output_Source_ref"]
            old_source = before_sources[old_ref]
            assert old_source == record["earlier_Host_output_Source"]
            assert old_source["role"] == "assistant" and old_source["origin"] == "public_assistant_message"
            original_wire = preparation["donor"]["first_provider_wire"]
            assert sum(message["role"] == "assistant" and message.get("content") == old_source["content"]
                for message in original_wire["messages"]) == 1
        if record["actual_tool_component_result"] is None:
            assert not known and record["status"] == "STRUCTURAL_INITIAL_COMPLETE_INPUT_CAPACITY_FAILURE"
            assert family == "memops_A05" and record["method"] == "e3-aggregate-u32"
            preflight = record["capacity_preflight"]
            assert preflight["complete_input_admitted"] is False and preflight["truncation_stats"]["truncated"]
            assert preflight["declared_K_reference_count"] == preflight["native_K_container_count"] == 7
            assert preflight["initial_state_tokens"] > preflight["sequence_tokens"] == 16384
            assert preflight["complete_native_state_and_all_action_bindings_literal_equal"]
            assert preflight["no_state_K_menu_budget_or_projection_reduction"]
            assert record["actual_provider_request"] is record["actual_tool_case"] is record["readout_file"] is None
            assert decision["material"] == "unknown"
            structural += 1
            rows.append(dict(index=index,family=family,status=record["status"],initial_capacity_failure_retained=True,
                prepared_full_K=7,actual_forward_tool_packet_Host_dispatch=0))
            continue
        case = Path(record["actual_tool_case"])
        replayed = read(case/"replay.json")
        result = read(record["native_runtime_result_path"])
        assert result == replayed["result"] == record["actual_tool_component_result"] and result["status"] == "COMPLETED"
        assert result["records"] == [] and result["memory_mutation_receipts"] == []
        after_bank = case/"runtime"/preparation["bank_relative"]
        after = store_values(after_bank)
        assert before_sources == source_values(after) and application(before_bank) == application(after_bank)
        assert len(before_sources) == record["all_before_Source_values_literal_preserved"]
        total_sources += len(before_sources)
        assert binding.bind_sources(available,after) == record["controlled_exogenous_sources"]
        settings = read(case/"runtime/input-freeze.json")["config"]
        if not known:
            expected_excluded = [old_ref] if record["condition"] == "prior_Host_output_excluded" else []
            assert settings["memory_control"]["excluded_source_refs"] == expected_excluded
        native_projection(after_bank,call,settings,result["sources"],output/f"native-source-projection-{index:02d}.lock")
        sdk += 1
        external_ids = {row["actual"]["event_id"] for row in record["controlled_exogenous_sources"]}
        component_messages = [{key:value for key,value in message.items() if key in ("name","tool_call_id","content")}
            | {"role":"tool"} for message in result["messages"]]
        kind = "actual_tool_component_packet_not_automatically_Host_delivered" if known else "fresh_actual_tool_component_packet"
        actual_component = bind(component_messages,after,external_ids,index,kind)
        assert actual_component == record["component_source_binding"]
        component_views += len(actual_component["Views"])
        receipt, = result["messages"]
        assert json.loads(receipt["content"]) == result["retrieval_result"]
        readout_path = Path(record["readout_file"])
        readout = read(readout_path)
        assert readout["generation_calls_after"] == readout["generation_calls_before"]+1
        assert all(readout["budget_after"][key]["unknown_usage"] == readout["budget_before"][key]["unknown_usage"]
            for key in ("generation","embedding"))
        if record["actual_provider_request"] is None:
            assert known and index == 0 and readout["status"] == "FAILED" and readout["error_type"] == "TemplateError"
            assert readout["actual_http_attempts"] == 0 and not (readout_path.parent/"trace.jsonl").exists()
            assert record["Host_source_binding"] is None and decision["material"] == "unknown"
            verify_anchors(decision,record,known)
            rows.append(dict(index=index,family=family,status=record["status"],actual_Source_projection_and_packet=True,
                actual_HTTP=0,component_View_not_credited_as_Host_delivery=True))
            continue
        provider, = [event for event in map(json.loads,physical_lines(readout_path.parent/"trace.jsonl")) if event["event"] == "vllm_response"]
        wire = record["actual_provider_request"]
        assert provider["request_sent"] and provider["request"] == wire == read(readout_path.parent/"request.json")
        frame = read(readout_path.parent/"frame.json")
        assert wire == substitute_receipt(frame,receipt)
        assert readout["actual_http_attempts"] == 1 and readout.get("answer") == record["answer"]
        if readout["status"] == "COMPLETED":
            response = read(readout_path.parent/"response.json")
            assert json.loads(provider["response_text"]) == response
            assert readout_answer(response,frame["tool_mode"],wire) == record["answer"]
        else:
            assert not known and readout["status"] == "FAILED" and readout["error_type"] == "IncompleteChatResponse"
        if not known:
            assert wire["messages"][:len(original_wire["messages"])] == original_wire["messages"]
        kind = "actually_sent_and_responded_conditional_Host_input" if known else "actually_sent_conditional_Host_input"
        actual_host = bind(wire["messages"],after,external_ids,index,kind)
        assert actual_host == record["Host_source_binding"]
        raw_ranges += len(actual_host["original_ranges"]["visible_original_ranges"])
        host_views += len(actual_host["Views"])
        for occurrence in actual_host["Views"]:
            group = [group for group in view_groups if group["family"] == family and group["actual_View"] == occurrence["actual_view"]]
            if group:
                group, = group
            else:
                group = dict(family=family,actual_View=occurrence["actual_view"],occurrences=[])
                view_groups.append(group)
            group["occurrences"].append({key:occurrence[key] for key in ("case_index","message_index","evidence_index")})
        verify_anchors(decision,record,known)
        if family in frames:
            assert frames[family] == frame["request"]
        else:
            frames[family] = frame["request"]
        known_tokens += readout["budget_after"]["generation"]["known_tokens"]-readout["budget_before"]["generation"]["known_tokens"]
        http += 1
        rows.append(dict(index=index,family=family,status=record["status"],actual_Source_projection_and_packet=True,
            actual_HTTP=1,whole_Provider_frame_receipt_response_and_original_binding_equal=True,
            actual_Host_Views=len(actual_host["Views"])))
    assert total_sources == (165 if known else 476) and sdk == (9 if known else 40)
    assert http == (8 if known else 40) and known_tokens == (75003 if known else 343013)
    assert host_views == (21 if known else 49) and len(view_groups) == (10 if known else 16)
    assert component_views == (2 if known else 9) and structural == (0 if known else 2)
    assert dict(Counter(row["grade"] for row in decisions)) == quality["answer_grades"]
    assert dict(Counter(row["material"] for row in decisions)) == quality["material_statuses"]
    for group in view_groups:
        saved, = [row for row in quality["Host_View_reviews"] if row["family"] == group["family"] and row["actual_View"] == group["actual_View"]]
        assert saved["occurrences"] == group["occurrences"]
    script = "audit_d_known_view_operations_inputs.py" if known else "audit_d_old_output_operations_inputs.py"
    operations,proof = replay(root,output,script,args.component,
        "folder / 'reviews-v1/operations-and-finite-input-audit-v1.json'",folder/"reviews-v1/operations-and-finite-input-audit-v1.json")
    by_trace = defaultdict(list)
    for record in operations["learned_forwards"]:
        by_trace[record["trace"]].append(record)
    for trace,members in by_trace.items():
        events = list(map(json.loads,physical_lines(trace)))
        for member in members:
            prediction = events[member["event_index"]]["result"]
            assert all(math.isfinite(value) for field in ("logits","probabilities") for value in prediction[field].values())
    summary = dict(passed=True,status="D_CONTROL_ORIGINAL_SOURCE_VIEW_NATIVE_SDK_FULL_HOST_INPUT_AND_FIRST_RESULTS_RECONCILED_READ_ONLY",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),component=args.component,actual_frozen_runtime=str(runtime),
        planned_first_cells=len(rows),families=3 if known else 7,actual_Tool_packets=sdk,
        whole_before_after_Source_value_comparisons=total_sources,actual_native_Source_SDK_projections_through_SQLite_mode_ro=sdk,
        no_setup_DDL_original_DB_or_original_lock_writes=True,all_actual_existing_Store_values_preserved_by_projection=True,
        all_actual_application_tables_literal_equal=True,semantic_records_or_business_writes=0,
        actual_HTTP=http,known_Host_tokens_already_paid=known_tokens,retained_initial_capacity_failures=structural,
        retained_template_failure_without_HTTP=1 if known else 0,
        all_actual_Component_and_Host_original_ranges_View_nodes_roles_revisions_clocks_literal_bound=True,
        actual_Host_original_range_occurrences=raw_ranges,Host_View_occurrences=host_views,unique_Host_View_payloads=len(view_groups),
        component_View_occurrences=component_views,unsent_Component_View_not_credited=1 if known else 0,
        all_actual_whole_Host_frames_receipts_completed_responses_and_known_usage_failures_bound=True,
        old_Host_output_remains_exact_assistant_context_under_both_conditions=not known,
        original_author_anchor_and_issue_quotes_verified=True,original_answer_grades=quality["answer_grades"],
        original_material_statuses=quality["material_statuses"],all_original_judgments_unchanged=True,
        source_author_not_independent_or_blind=True,original_operations_full_input_report_literal_replayed=proof,
        actual_model_forwards=operations["recorded_learned_forwards"],all_actual_head_values_finite=True,
        actual_local_input_tokens=operations["sum_actual_input_tokens_already_native_recorded"],
        minimum_actual_local_input_tokens=operations["minimum_actual_input_tokens"],maximum_actual_local_input_tokens=operations["maximum_actual_input_tokens"],
        original_K_menu_and_capacity_failures_retained_without_cropping=True,per_case=rows,
        scope="Actual frozen conditional TRAIN controls and original Source-author review reconciliation. Faithful literal View/Source roles and clocks do not certify underlying claims or current task coverage. Known-ViewA05baseline first template failure has no dispatched Host input; only A33/B03 have complete matched three-method frames. Old-output toggles additional acquisition while all already received Host knowledge remains; Host generation seeds unmatched. First capacity/HTTP/template failures remain, with no independent confirmation/adoption or general old-output harm/benefit conclusion.",
        new_model_tokenizer_GPU_HTTP_business_or_original_ledger_calls=0,original_Source_inputs_labels_models_or_firsts_changed=False,
        CPU_pending_actual_idle138=True,no_sha_validation=True,full763_line_completion_proven=False,goal_complete=False)
    with (output/"summary.json").open("x") as stream:
        json.dump(summary,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print("D_CONTROL_READ_ONLY_SOURCE_SDK_ACTUAL_WIRES_FIRST_RESULTS_VERIFIED",args.component,"cells",len(rows),"HTTP",http,"known",known_tokens,flush=True)


if __name__ == "__main__":
    main()
