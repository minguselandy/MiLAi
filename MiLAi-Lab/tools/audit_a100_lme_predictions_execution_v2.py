"""Audit a closed native LME prediction cohort using full archived before states; never infer."""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path

from audit_native_control_trace import audit_controls
from audit_native_delivered_context import sdk_delivered_context
from audit_native_source_rows import source_values, assert_native_source_projection, assert_original_sources_preserved
from milai_lab.datasets.lme_protocol import NativeLmeProtocol
from milai_lab.datasets.longmemeval_v2 import public_question, trajectory_sources
from milai_lab.harness.case_archive import restore_case
from milai_lab.runners.lme_reader import final_text


def read(path):
    return json.loads(Path(path).read_text())


def lines(path):
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream]


def bank(runtime):
    database, = Path(runtime).glob("banks/*/memory.sqlite")
    return database.parent


def application_values(runtime):
    out = {}
    for path in Path(runtime).glob("banks/*/applications/**/*.sqlite"):
        with sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True) as connection:
            names = [x[0] for x in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            out[str(path.relative_to(runtime))] = {name:connection.execute(
                'SELECT * FROM "'+name.replace('"','""')+'"').fetchall() for name in names}
    return out


def retained_initial_load_failure(case, question, protocol, collection, actual, expected_units):
    """Audit the real failed pre-capture case; never manufacture an input or a capture."""
    correction = protocol["execution_wiring_correction"]
    reflection = read(correction["failure_reflection"])
    assert reflection["passed"] and case == reflection["native_first_failed_case"]
    assert case["row"] == 0 and case["status"] == "FAILED_RETRIEVING" and case["score"] is None
    owner = read(reflection["actual_owner"])
    assert owner["client_CPU_recorded"] and owner["exit_code"] == 1
    assert all(not Path("/proc", str(owner[k])).exists() for k in ("pid", "child_pid"))
    assert owner["shared_generation_admissions"] == owner["known_generation_tokens"] == 0
    runtime = Path(case["runtime"])
    query = read(runtime / "query.json")
    assert query["status"] == "FAILED" and not query["reader_called"]
    assert query["query"] == question["question"]
    baseline = Path(query["baseline_capture"])
    baseline_call = read(baseline / "call.json")
    assert baseline_call["public_message"]["content"] == question["question"]
    assert query["first_observation_and_all_legal_bindings_equal"]
    result_path = Path(reflection["native_result"])
    assert result_path.is_relative_to(runtime)
    result = read(result_path)
    assert result["status"] == "FAILED" and result["records"] == []
    assert result["error"] == "Actual autonomous Host scorer differs from declared single-GPU conditions"
    assert result["frozen_request_and_allowance_equal"] and result["frozen_initial_observation_and_actions_equal"]
    assert result["given_retrieval_request"] == baseline_call["public_message"]["given_retrieval_request"]
    events = lines(reflection["native_trace"])
    counts = Counter(e["event"] for e in events)
    assert counts["memory_control_model_result"] == counts["vllm_response"] == 0
    step, = [e for e in events if e["event"] == "memory_control_step"]
    assert step["phase"] == "decision_input"
    assert step["before"] == baseline_call["initial_observation"]
    assert step["actions"] == baseline_call["initial_actions"]
    load, = [e for e in events if e["event"] == "memory_control_model_load"]
    assert load["device"] == "cpu" and not load["loaded"]
    inference = read(read(owner["plan"])["inference"])
    assert inference["model_loads"] == [reflection["model_load_receipt"]]
    capture_owner = Path(case["owner_predictions"])
    assert not list((capture_owner / "actual-retrieval-captures/0000").glob("*/call.json"))
    assert not (capture_owner / "predictions/0000/reader").exists()
    descriptor = read(baseline / "before-archive.json")
    assert descriptor["status"] == "COMPLETE_BEFORE_ARCHIVED_EVERY_RECONSTRUCTED_BYTE_EQUAL"
    with tempfile.TemporaryDirectory(prefix="lme-retained-load-failure-audit-", dir=collection) as temporary:
        restored = Path(temporary) / "runtime"
        restore_case(Path(descriptor["archive"]), Path(descriptor["base"]), restored)
        assert source_values(bank(restored)) == actual
        assert application_values(restored) == application_values(runtime)
    return {"index":0, "question_id":question["id"], "native_status":case["status"],
        "runtime":str(runtime), "original_capture":None, "complete_initial_and_step_snapshots":0,
        "retained_pre_capture_constructor_failure":True,
        "restored_complete_baseline_pre_retrieval_snapshot":str(baseline),
        "full_expected_original_Source_units":expected_units,
        "all_original_Source_values_and_native_role_body_clock_projection_equal":True,
        "existing_application_tables_equal":True, "actual_NN_forwards":0,
        "first_observation_and_complete_bindings_literal_equal":True,
        "actual_Reader_or_HTTP_calls":0, "complete_Reader_request_literal_equal":False,
        "absent_capture_input_or_Reader_fabricated":False, "whole_actual_Source_not_answer_truth":True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("owner",type=Path)
    args = parser.parse_args()
    owner = read(args.owner)
    assert owner["client_CPU_recorded"] and owner["validated_stage_terminal"]
    assert all(not Path("/proc",str(owner[k])).exists() for k in ("pid","child_pid"))
    plan = read(owner["plan"])
    assert plan["stage_kind"] == "prediction"
    protocol = read(plan["protocol"])
    initial = protocol["initial_stage_plans"][plan.get("initial_stage",plan["name"])]
    collection = Path(plan["output"]).resolve()
    output = collection/"audit-full-cohort-v1"
    assert not output.exists()
    driver = read(collection/"driver.json")
    assert len(driver["cases"]) == 451
    snapshot = Path(protocol["input_snapshot"])
    questions = lines(snapshot/"questions.jsonl")
    trajectories = {t["id"]:t for t in lines(snapshot/"trajectories.jsonl")}
    haystacks = read(snapshot/"haystacks/lme_v2_small.json")
    native = NativeLmeProtocol(Path(protocol["native_protocol"]))
    expected_config = read(protocol["method_configs"][
        "fixed-prefix" if initial["local_policy"]=="fixed" else "primary-seed0-u32"])["entrypoints"]["functional"]
    template_cache, expected_cache = {}, {}
    records, finite_records, rejection_records = [], [], []
    source_comparisons = archive_snapshots = sdk_contexts = full_reader_wires = 0
    operations = Counter()
    for index,(question,case) in enumerate(zip(questions,driver["cases"],strict=True)):
        assert case["row"] == index and case["question_id"] == question["id"]
        runtime = Path(case["runtime"])
        template = runtime.parents[1]/"template"
        key = str(template)
        if key not in template_cache:
            template_cache[key] = source_values(bank(template))
            expected = [s for identity in haystacks[question["id"]]
                for s in trajectory_sources(trajectories[identity])[0]]
            actual_by_id = {(s["session"],s["capture_key"],s["role"]):s
                for s in template_cache[key].values()}
            assert len(expected) == len(actual_by_id)
            for source in expected:
                assert_native_source_projection(source,actual_by_id[
                    source["session_id"],source["event_key"],source["role"]])
            expected_cache[key] = len(expected)
        originals = template_cache[key]
        actual = source_values(bank(runtime))
        assert_original_sources_preserved(originals,actual)
        source_comparisons += len(originals)
        if index == 0 and initial["local_policy"] == "laya":
            records.append(retained_initial_load_failure(case, question, protocol, collection, actual, expected_cache[key]))
            source_comparisons += len(originals)
            archive_snapshots += 1  # The retained baseline before, explicitly identified in this record.
            continue
        capture_owner = Path(case["owner_predictions"])
        call_path, = (capture_owner/"actual-retrieval-captures"/f"{index:04d}").glob("*/call.json")
        captured = call_path.parent
        call = read(call_path)
        assert call["status"] in ("ORIGINAL_COMPLETED","ORIGINAL_FAILED")
        assert not call["host_request_generated"]
        assert not call.get("served_from_cache",False)
        assert call["public_message"]["content"] == question["question"]
        result_path = runtime/call["host_result_path"]
        result = read(result_path)
        assert result["records"] == [] and result["memory_mutation_receipts"] == []
        trace = runtime/call["host_prefix_trace"]
        events = lines(trace)
        rejection = call.get("error") == "Finite decision input exceeds declared complete-input capacity"
        control = audit_controls(events,projection=expected_config["memory_control"]["state_projection"],
            max_len=expected_config["memory_control"]["max_len"],
            learned=initial["local_policy"]=="laya",expected_capacity_rejection=rejection)
        finite_records.extend({"index":index,**r} for r in control["records"])
        rejection_records.extend({"index":index,**r} for r in control["retained_failed_before_forward_inputs"])
        operations.update(control["selected_operations"])
        snapshots = [captured]+sorted((captured/"steps").glob("step-*"))
        first_sources = None
        for number,state in enumerate(snapshots):
            descriptor = read(state/"before-archive.json")
            assert descriptor["status"] == "COMPLETE_BEFORE_ARCHIVED_EVERY_RECONSTRUCTED_BYTE_EQUAL"
            with tempfile.TemporaryDirectory(prefix="lme-state-audit-",dir=collection) as temporary:
                restored = Path(temporary)/"runtime"
                restore_case(Path(descriptor["archive"]),Path(descriptor["base"]),restored)
                values = source_values(bank(restored))
                assert_original_sources_preserved(originals,values)
                source_comparisons += len(originals)
                if number == 0:
                    first_sources = values
                    assert application_values(restored) == application_values(runtime)
                else:
                    assert_original_sources_preserved(first_sources,values)
            archive_snapshots += 1
        assert_original_sources_preserved(first_sources,actual)
        if initial["local_policy"] == "laya":
            assert result["frozen_initial_observation_and_actions_equal"]
        reader_wire = False
        if result["status"] == "COMPLETED":
            context = read(runtime/"memory-context.json")
            media = read(runtime.parents[1]/"bound-images.json")
            regenerated = sdk_delivered_context(runtime,result["retrieval_result"],media)
            assert regenerated == context
            sdk_contexts += 1
            prediction_owner = Path(case["owner_predictions"])
            prediction_root = prediction_owner/"predictions"/f"{index:04d}"
            query,image = public_question(question,snapshot)
            request_path = prediction_root/"reader/request.json"
            if request_path.exists():
                wire,_ = native.messages(question["domain"],query,image,context)
                request = native.reader_request(wire,expected_config["host"],
                    expected_config["capacity"]["enable_thinking"])
                payload = copy.deepcopy(request)
                assert payload.pop("timeout") == expected_config["host"]["timeout"]
                payload.update(payload.pop("extra_body",{}))
                payload.setdefault("chat_template_kwargs",{
                    "enable_thinking":expected_config["capacity"]["enable_thinking"]})
                assert payload == read(request_path)
                reader_wire = True
                full_reader_wires += 1
            if case["status"] == "COMPLETED":
                assert reader_wire
                prediction = read(prediction_root/"prediction.json")
                assert prediction["response_raw"] == final_text(read(prediction_root/"reader/response.json"))
            elif not reader_wire:
                assert not (prediction_root/"reader/response.json").exists()
                call_receipt = prediction_root/"reader/call.json"
                if call_receipt.exists():
                    assert read(call_receipt)["actual_http_attempts"] == 0
            # A native Reader can reject while preparing its payload; its missing request is not repaired.
        records.append({"index":index,"question_id":question["id"],"native_status":case["status"],
            "runtime":str(runtime),"original_capture":str(captured),
            "complete_initial_and_step_snapshots":len(snapshots),
            "full_expected_original_Source_units":expected_cache[key],
            "all_original_Source_values_and_native_role_body_clock_projection_equal":True,
            "existing_application_tables_equal":True,
            "actual_NN_forwards":control["actual_NN_forwards"],
            "retained_guard_rejection_before_forward":rejection,
            "complete_Reader_request_literal_equal":reader_wire,
            "whole_actual_Source_not_answer_truth":True})
    output.mkdir()
    summary = {"passed":True,"status":"ALL451_CLOSED_SOURCE_ARCHIVED_STATE_NATIVE_SDK_READER_WIRE_AND_CONTROL_INPUTS_AUDITED",
        "native_collection":str(collection),"positions":451,"records":records,
        "existing_Source_comparisons":source_comparisons,"restored_complete_before_snapshots":archive_snapshots,
        "native_SDK_entire_delivered_contexts_equal":sdk_contexts,
        "whole_Reader_requests_literal_equal":full_reader_wires,
        "actual_NN_forwards":len(finite_records),"actual_input_tokens":sum(r["input_tokens"] for r in finite_records),
        "selected_operations":dict(operations),"retained_before_forward_rejections":len(rejection_records),
        "retained_pre_capture_constructor_failure_positions":[r["index"] for r in records if r.get("retained_pre_capture_constructor_failure")],
        "baseline_before_restores_for_retained_constructor_failure":1 if initial["local_policy"]=="laya" else 0,
        "actual_logged_before_and_offered_bindings_not_all_bank_delivery_or_effective_context":True,
        "semantic_qa_or_native_Judge_score_proven":False,"new_model_tokenizer_or_HTTP_calls":0,
        "ledger_opened_or_written":False,"no_sha_validation":True}
    (output/"control-inputs.json").write_text(json.dumps({"records":finite_records,
        "failed_before_forward_inputs":rejection_records},ensure_ascii=False,indent=2)+"\n")
    (output/"launch-next-stage-gate.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    print(summary["status"],"positions451","NN",len(finite_records),"snapshots",archive_snapshots)


if __name__ == "__main__":
    main()
