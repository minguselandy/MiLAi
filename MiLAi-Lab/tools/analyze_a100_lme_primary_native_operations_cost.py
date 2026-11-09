"""Census primary LME first outcomes and actual operations without ledger or new calls."""
import argparse
import io
import json
import sys
import tarfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from analyze_a100_lme_fixed_native_operations_cost import call_record, usage_summary


def read(path):
    return json.loads(Path(path).read_text())


def archived_file(entry, relative):
    """Read an already verified immutable archive member without restoring a case."""
    from milai_lab.harness.case_archive import _blocks

    assert entry["status"] == "ARCHIVED"
    detail = entry["details"]
    assert detail["verification"] == "Every reconstructed byte compared directly; no SHA/fingerprint"
    base = Path(detail["base"])
    with tarfile.open(detail["archive"]) as archive:
        with archive.extractfile("case-blocks.json") as stream:
            manifest = json.load(stream)
        assert manifest["schema"] == "case_blocks_v1"
        rows = {row["path"]: row for row in manifest["files"]}
        row = rows[str(relative)]
        seen = set()
        while "same_as" in row:
            assert row["path"] not in seen
            seen.add(row["path"])
            row = rows[row["same_as"]]
        payload = archive.extractfile(row["payload"]) if "payload" in row else io.BytesIO()
        with payload:
            body = b"".join(_blocks(row, base, payload))
        assert len(body) == row["size"]
        return body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root / "runtime-b64/src"))
    external = root / "external-own-policy-v1"
    stages = external / "stages-lme-v1"
    finalized = external / "finalized-lme-v1"
    predictions = (finalized / "primary-seed0-u32-predictions").resolve()
    scores = (finalized / "primary-seed0-u32-scores").resolve()
    source_proof = read(root / "verify-lme-primary-source-audit-closed-v3.json")
    score_proof = read(root / "verify-lme-primary-native-scoring-closed-v1.json")
    assert source_proof["passed"] and score_proof["passed"]
    generation, grading = read(predictions / "driver.json"), read(scores / "driver.json")
    metrics = read(scores / "metrics.json")
    assert metrics == score_proof["native_aggregate"]
    assert len(generation["cases"]) == len(grading["cases"]) == 451
    assert [c["question_id"] for c in generation["cases"]] == [c["question_id"] for c in grading["cases"]]
    assert Counter(c["status"] for c in generation["cases"]) == {"COMPLETED": 401, "FAILED_RETRIEVING": 2, "FAILED_READING": 48}
    assert not grading["reader_regenerated"]
    source_gate = read(predictions / "audit-full-cohort-v1/launch-next-stage-gate.json")
    inputs = read(predictions / "audit-full-cohort-v1/control-inputs.json")["records"]
    archive_index = read(predictions / "case-archives/index.json")
    archive_entries = {entry["row"]: entry for entry in archive_index["cases"]}
    assert all(archive_entries[row]["status"] == "ARCHIVED" for row in range(1, 10))

    owner_by_output = {}
    for path in stages.glob("*-owner.json"):
        owner = read(path)
        plan = read(owner["plan"])
        if plan["stage_kind"] in {"prediction", "scoring"} and plan.get("initial_stage", plan["name"]) in {
                "primary-seed0-u32-prediction451-v1", "primary-seed0-u32-scoring451-v1"}:
            output = Path(plan["output"]).resolve()
            assert output not in owner_by_output
            owner_by_output[output] = (path, owner, plan)
    owners, chains, loads = [], {}, []
    for kind, collection in (("prediction", predictions), ("scoring", scores)):
        current, chain = collection, []
        while True:
            assert current not in chain
            chain.append(current)
            path, owner, plan = owner_by_output[current]
            assert owner["client_CPU_recorded"] and "exit_code" in owner
            assert all(not Path("/proc", str(owner[key])).exists() for key in ("pid", "child_pid"))
            assert owner["new_unknown_usage"] == {"generation": 0, "embedding": 0}
            native_cpu = sum(owner["already_recorded_native_CPU"].values())
            assert abs(native_cpu + owner["client_CPU_residual"] - owner["whole_child_CPU_seconds"]) < 1e-7
            owner_loads = []
            if kind == "prediction":
                assert plan["local_policy"] == "laya"
                owner_loads = read(plan["inference"])["model_loads"]
                load, = owner_loads
                assert load["head_max_len"] == 2048 and load["threads"] == 4
                if plan["name"] == "primary-seed0-u32-prediction451-v1":
                    assert load["status"] == "INFERENCE_CONDITION_MISMATCH" and load["device"] == "cpu" and load["max_len"] == 8192
                else:
                    assert load["status"] == "VERIFIED" and load["device"] == "cuda:0" and load["max_len"] == 16384
                loads.append(dict(owner=str(path), device=load["device"], status=load["status"], max_len=load["max_len"],
                    declared_GPU2_job_interval_hours=owner["GPU2_job_interval_hours"]))
            owners.append(dict(stage_kind=kind, path=str(path), output=str(current), local_model_loads=len(owner_loads),
                **{key: owner[key] for key in ("exit_code", "whole_child_CPU_seconds", "wall_seconds",
                    "already_recorded_native_CPU", "client_CPU_residual", "parent_CPU_seconds_through_billing",
                    "shared_generation_admissions", "known_generation_tokens", "new_unknown_usage", "GPU2_job_interval_hours")}))
            previous = read(current / "driver.json")["continued_from"]
            if previous is None:
                break
            current = Path(previous).resolve()
        chains[kind] = [str(path) for path in reversed(chain)]
    assert len(chains["prediction"]) == 51 and len(chains["scoring"]) == 1

    rows, readers, judges = [], [], []
    selected, outcomes, terminations, packet_usage, evidence_kinds = (Counter() for _ in range(5))
    selected_without_result = []
    for row, (case, grade) in enumerate(zip(generation["cases"], grading["cases"], strict=True)):
        assert case["row"] == grade["row"] == row
        reader = judge = None
        if case["status"] == "FAILED_RETRIEVING":
            assert row in (0, 9) and "prediction_root" not in case and grade["score"] is None
        else:
            reader = call_record(Path(case["prediction_root"]) / "reader", "Reader", row)
            readers.append(reader)
            if case["status"] == "FAILED_READING":
                assert reader["status"] == "FAILED" and reader["finish_reason"] == "length"
                assert reader["completion_tokens"] == 8192 and grade["score"] is None
            else:
                assert reader["status"] == "COMPLETED" and reader["finish_reason"] == "stop"
        if grade["status"] == "COMPLETED" and (Path(grade["score_root"]) / "judge").is_dir():
            judge = call_record(Path(grade["score_root"]) / "judge", "Judge", row)
            assert judge["status"] == "COMPLETED"
            judges.append(judge)

        events, packet, capture, trace_member = [], None, None, None
        if 1 <= row <= 9:
            record = source_gate["records"][row]
            assert record["retained_observer_capture_gap"] and not record["actual_physical_step_snapshot_proof_available"]
            baseline = Path(record["restored_complete_baseline_pre_retrieval_snapshot"])
            baseline_call = read(baseline / "call.json")
            trace_member = baseline_call["host_prefix_trace"]
            body = archived_file(archive_entries[row], trace_member)
            events = [json.loads(line) for line in body.decode().splitlines()]
            if row != 9:
                result = json.loads(archived_file(archive_entries[row], baseline_call["host_result_path"]))
                assert result["status"] == "COMPLETED"
                packet = result["retrieval_result"]
        elif row >= 10:
            capture, = (Path(case["owner_predictions"]) / "actual-retrieval-captures" / f"{row:04d}").glob("*/call.json")
            call = read(capture)
            assert call["schema"] == "frozen_retrieval_call_v2" and call["status"] == "ORIGINAL_COMPLETED"
            assert not call["host_request_generated"] and not call["served_from_cache"]
            assert call["public_message"]["given_retrieval_request"] == {"query": call["public_message"]["content"]}
            events, packet = call["control_events"], call["original_result"]
        else:
            assert source_gate["records"][row]["retained_pre_capture_constructor_failure"]

        decisions, operations = [], []
        for event in events:
            if event["event"] != "memory_control_step" or event["phase"] not in {"decision_output", "operation_result"}:
                continue
            action, = [action for action in event["actions"] if action["id"] == event["selected"]]
            if event["phase"] == "decision_output":
                selected[action["kind"]] += 1
                decisions.append(dict(step=event["step"], selected_action=action,
                    offered_actions=len(event["actions"]), selection_mode=event["selection_mode"]))
            else:
                outcomes[action["kind"] + ":" + event["result"]["status"]] += 1
                operations.append(dict(step=event["step"], selected_action=action,
                    status=event["result"]["status"], ok=event["result"]["ok"]))
        assert len(decisions) == source_gate["records"][row]["actual_NN_forwards"]
        completed_bindings = {(op["step"], op["selected_action"]["id"]) for op in operations}
        missing = [decision for decision in decisions if (decision["step"], decision["selected_action"]["id"]) not in completed_bindings]
        selected_without_result.extend(dict(row=row, **decision) for decision in missing)
        if packet is not None:
            assert packet["ok"] and len(operations) == packet["usage"]["operations"]
            assert sum(op["selected_action"]["kind"] == "READ" for op in operations) == packet["usage"]["read_operations"]
            packet_usage.update(packet["usage"])
            terminations[packet["termination_reason"]] += 1
            evidence_kinds.update(item["kind"] for item in packet["evidence"])
        else:
            assert row in (0, 9)
        rows.append(dict(row=row, question_id=case["question_id"], domain=case["domain"], pool=case["pool"],
            native_prediction_status=case["status"], native_scoring_status=grade["status"],
            native_score=grade["score"], native_valid_UNKNOWN=grade.get("is_unknown"), Reader=reader, Judge=judge,
            capture=None if capture is None else str(capture), retained_trace_member=trace_member,
            archived_trace_source=None if trace_member is None else archive_entries[row]["details"]["archive"],
            actual_physical_step_snapshot_proof_available=False if row < 10 else True,
            complete_selected_bindings=decisions, actual_operation_results=operations,
            original_result_usage=None if packet is None else packet["usage"],
            returned_packet_evidence_items=None if packet is None else len(packet["evidence"])))
    assert len(readers) == source_gate["whole_Reader_requests_literal_equal"] == 449
    assert len(judges) == score_proof["actual_native_Judge_HTTP"] == 134
    assert dict(selected) == source_gate["selected_operations"]
    assert sum(selected.values()) == len(inputs) == source_gate["actual_NN_forwards"] == 3594
    assert sum(record["input_tokens"] for record in inputs) == source_gate["actual_input_tokens"] == 25070604
    assert all(record["finite"] and not record["truncated"] and record["head_logit_probability_ID_order_equal"] for record in inputs)
    failed = [reader for reader in readers if reader["status"] == "FAILED"]
    assert len(failed) == 48 and Counter(reader["final_content_state"] for reader in failed) == {"absent": 47, "present": 1}
    partial, = [reader for reader in failed if reader["final_content_state"] == "present"]
    assert partial["row"] == 258 and partial["final_content_characters"] == 10
    assert Counter(item["selected_action"]["kind"] for item in selected_without_result) == {"HANDOFF": 1, "SEARCH": 1}
    assert [item["row"] for item in selected_without_result if item["selected_action"]["kind"] == "SEARCH"] == [9]

    owner_totals = {}
    for kind, calls in (("prediction", readers), ("scoring", judges)):
        members = [owner for owner in owners if owner["stage_kind"] == kind]
        assert sum(owner["shared_generation_admissions"] for owner in members) == len(calls)
        assert sum(owner["known_generation_tokens"] for owner in members) == sum(call["total_tokens"] for call in calls)
        components = Counter()
        for owner in members:
            components.update(owner["already_recorded_native_CPU"])
        owner_totals[kind] = dict(segments=len(members),
            whole_child_CPU_seconds=sum(owner["whole_child_CPU_seconds"] for owner in members),
            measured_parent_CPU_seconds=sum(owner["parent_CPU_seconds_through_billing"] for owner in members),
            whole_child_plus_measured_parent_CPU_seconds=sum(owner["whole_child_CPU_seconds"] + owner["parent_CPU_seconds_through_billing"] for owner in members),
            actual_owner_wall_seconds_sum=sum(owner["wall_seconds"] for owner in members),
            native_CPU_already_included=sum(components.values()), native_CPU_components_already_included=dict(components))
    result = dict(status="PRIMARY451_FIRST_PREDICTION_AND_NATIVE_SCORING_OPERATIONS_COST_CENSUS_CLOSED",
        timestamp_utc=datetime.now(timezone.utc).isoformat(), method="primary-seed0-u32", planned_positions=451,
        prediction_collection=str(predictions), scoring_collection=str(scores),
        prediction_status_counts=dict(Counter(case["status"] for case in generation["cases"])),
        scoring_status_counts=dict(Counter(case["status"] for case in grading["cases"])),
        native_aggregate=metrics, Reader=usage_summary(readers), failed_Readers=usage_summary(failed), Judge=usage_summary(judges),
        selected_action_counts=dict(selected), operation_kind_status_counts=dict(outcomes),
        selected_actions_without_operation_result=selected_without_result,
        HANDOFF_delivery_selected_results=outcomes["HANDOFF:delivery_selected"],
        selected_READ_without_operation_result_not_opened_Source=0,
        selected_SEARCH_without_operation_result_not_executed=1,
        termination_reason_counts=dict(terminations), native_retrieval_usage_counts=dict(packet_usage),
        returned_packet_evidence_kind_counts=dict(evidence_kinds), returned_retrieval_packets=449,
        owner_totals=owner_totals, owners=owners, ancestry=chains, per_position=rows,
        actual_NN_forwards=3594, local_NN_input_tokens=25070604,
        local_decision_head_scalar_scores=sum(record["offered_actions"] for record in inputs),
        local_model_loads=len(loads), actual_local_model_load_conditions=loads,
        declared_GPU2_job_interval_hours=sum(load["declared_GPU2_job_interval_hours"] for load in loads),
        verified_cuda_model_invocation_interval_hours=sum(load["declared_GPU2_job_interval_hours"] for load in loads if load["status"] == "VERIFIED"),
        CPU_condition_mismatch_loads=sum(load["status"] == "INFERENCE_CONDITION_MISMATCH" for load in loads),
        GPU_scope="Invocation/reservation interval includes copy, capture, client IO and Reader waits; not GPU busy time or encoder latency. Initial failed model loaded on CPU despite declared GPU environment and is reported separately.",
        Host_GPU_busy_hours=None, unmetered_author_inspection_launch_cleanup_CPU="unknown_not_zero",
        Source_and_entire_Reader_wire_audit=str(root / "verify-lme-primary-source-audit-closed-v3.json"),
        native_score_and_entire_Judge_wire_audit=str(root / "verify-lme-primary-native-scoring-closed-v1.json"),
        retained_physical_step_snapshot_gap_positions=list(range(1, 10)), missing_capture_or_snapshot_fabricated=False,
        frozen_audit_metadata_correction={"row": 9, "actual_final_unreturned_action_kind": "SEARCH",
            "historical_field_name": "last_selected_READ_without_result_is_not_success",
            "historical_READ_wording_supported_by_actual_trace": False,
            "actual_complete_bindings_inputs_first_outcomes_or_frozen_audit_edited": False},
        scope="Closed primary prediction and scoring invocation costs only. Whole child CPU includes native model/load/client/capture work; do not add nested/native/residual CPU again. Source preparation, offline audits, archive, training and unmetered author work are outside this subtotal. Reading already archived trace members for rows1..9 does not create missing original per-step snapshots. This report never opens the ledger and can run while native archive progresses. Small input was known development exposure; not autonomous Host, unseen Small/Medium or original-paper model reproduction.",
        original_first_outcomes_rewritten=False, new_model_or_HTTP_calls=0,
        ledger_opened_or_written=False, no_sha_validation=True, goal_complete=False)
    with args.output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print("PRIMARY451_NATIVE_CENSUS", {key: result[key]["total_tokens"] for key in ("Reader", "Judge")},
        owner_totals, dict(selected), dict(outcomes), flush=True)


if __name__ == "__main__":
    main()
