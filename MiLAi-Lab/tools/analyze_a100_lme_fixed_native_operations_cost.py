"""Census all closed fixed-prefix LME first calls; never open the live ledger."""
import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def call_record(directory, kind, row):
    call = read(directory / "call.json")
    response = read(directory / "response.json")
    request = read(directory / "request.json")
    assert call["actual_http_attempts"] == 1 and not call["automatic_retry"]
    event, = call["usage"]
    assert event["event"] == "vllm_response" and event["usage"] == response["usage"]
    usage = response["usage"]
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
    capacity = event["capacity"]
    comparison = event["capacity_comparison"]
    assert capacity["prompt_tokens"] == usage["prompt_tokens"]
    assert comparison["prompt_estimate_error_tokens"] == 0
    assert capacity["total_reserved_tokens"] < capacity["context_tokens"] == 65536
    for bucket in ("generation", "embedding"):
        assert call["budget_before"][bucket]["unknown_usage"] == call["budget_after"][bucket]["unknown_usage"]
    choice, = response["choices"]
    final = choice["message"]["content"]
    assert final is None or isinstance(final, str)
    if kind == "Reader":
        assert request["max_tokens"] == 8192
        assert request["chat_template_kwargs"] == {"enable_thinking": True}
    return dict(row=row, kind=kind, path=str(directory / "call.json"),
        status=call["status"], actual_HTTP_attempts=1,
        prompt_tokens=usage["prompt_tokens"], completion_tokens=usage["completion_tokens"],
        total_tokens=usage["total_tokens"], finish_reason=choice["finish_reason"],
        final_content_state="absent" if final is None else "present",
        final_content_characters=0 if final is None else len(final),
        provider_response_wall_seconds=event["wall_seconds"],
        whole_call_wall_seconds=call["wall_seconds"], call_CPU_seconds_nested=call["cpu_seconds"],
        output_reserve_tokens=capacity["output_reserve_tokens"],
        total_reserved_tokens=capacity["total_reserved_tokens"], context_tokens=capacity["context_tokens"],
        actual_prompt_estimate_error_tokens=0)


def usage_summary(rows):
    return dict(actual_HTTP_attempts=sum(r["actual_HTTP_attempts"] for r in rows),
        **{key: sum(r[key] for r in rows) for key in (
            "prompt_tokens", "completion_tokens", "total_tokens", "provider_response_wall_seconds",
            "whole_call_wall_seconds", "call_CPU_seconds_nested")},
        status_counts=dict(Counter(r["status"] for r in rows)),
        finish_reason_counts=dict(Counter(r["finish_reason"] for r in rows)),
        absent_final_content=sum(r["final_content_state"] == "absent" for r in rows),
        present_final_content=sum(r["final_content_state"] == "present" for r in rows),
        max_total_reserved_tokens=max(r["total_reserved_tokens"] for r in rows),
        context_tokens=65536, actual_prompt_estimate_error_tokens=0,
        new_unknown_generation_or_embedding_usage=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    external = root / "external-own-policy-v1"
    stages = external / "stages-lme-v1"
    finalized = external / "finalized-lme-v1"
    predictions = (finalized / "fixed-prefix-predictions").resolve()
    scores = (finalized / "fixed-prefix-scores").resolve()
    source_proof = read(root / "verify-lme-fixed-source-audit-closed-v1.json")
    score_proof = read(root / "verify-lme-fixed-native-scoring-closed-v1.json")
    assert source_proof["passed"] and score_proof["passed"]
    generation, grading = read(predictions / "driver.json"), read(scores / "driver.json")
    metrics = read(scores / "metrics.json")
    assert metrics == score_proof["native_aggregate"]
    assert len(generation["cases"]) == len(grading["cases"]) == 451
    assert [c["question_id"] for c in generation["cases"]] == [c["question_id"] for c in grading["cases"]]
    assert Counter(c["status"] for c in generation["cases"]) == {"COMPLETED": 401, "FAILED_READING": 50}
    assert Counter(c["status"] for c in grading["cases"]) == {"COMPLETED": 401, "UNSCORED_FAILED_READING": 50}
    assert not grading["reader_regenerated"]

    owner_by_output = {}
    for path in stages.glob("*-owner.json"):
        owner = read(path)
        plan = read(owner["plan"])
        if plan["stage_kind"] in {"prediction", "scoring"} and plan.get("initial_stage", plan["name"]) in {
                "fixed-prefix-prediction451-v1", "fixed-prefix-scoring451-v1"}:
            output = Path(plan["output"]).resolve()
            assert output not in owner_by_output
            owner_by_output[output] = (path, owner, plan)
    owners, chains = [], {}
    for name, collection in (("prediction", predictions), ("scoring", scores)):
        current, chain = collection, []
        while True:
            assert current not in chain
            chain.append(current)
            path, owner, plan = owner_by_output[current]
            assert owner["client_CPU_recorded"] and "exit_code" in owner
            assert all(not Path("/proc", str(owner[k])).exists() for k in ("pid", "child_pid"))
            assert owner["new_unknown_usage"] == {"generation": 0, "embedding": 0}
            native_cpu = sum(owner["already_recorded_native_CPU"].values())
            assert abs(native_cpu + owner["client_CPU_residual"] - owner["whole_child_CPU_seconds"]) < 1e-7
            if name == "prediction":
                assert plan["local_policy"] == "fixed" and read(plan["inference"])["model_loads"] == []
                assert owner["GPU2_job_interval_hours"] is None
            owners.append(dict(stage_kind=name, path=str(path), output=str(current),
                **{k: owner[k] for k in ("exit_code", "whole_child_CPU_seconds", "wall_seconds",
                    "already_recorded_native_CPU", "client_CPU_residual", "parent_CPU_seconds_through_billing",
                    "shared_generation_admissions", "known_generation_tokens", "new_unknown_usage")}))
            previous = read(current / "driver.json")["continued_from"]
            if previous is None:
                break
            current = Path(previous).resolve()
        chains[name] = [str(p) for p in reversed(chain)]
    assert len(chains["prediction"]) == 51 and len(chains["scoring"]) == 1

    rows, readers, judges = [], [], []
    selected, outcomes, terminations, packet_usage, evidence_kinds = (Counter() for _ in range(5))
    for row, (case, grade) in enumerate(zip(generation["cases"], grading["cases"], strict=True)):
        assert case["row"] == grade["row"] == row
        reader = call_record(Path(case["prediction_root"]) / "reader", "Reader", row)
        readers.append(reader)
        if case["status"] == "FAILED_READING":
            assert reader["status"] == "FAILED" and reader["finish_reason"] == "length"
            assert reader["completion_tokens"] == 8192 and grade["score"] is None
        else:
            assert reader["status"] == "COMPLETED" and reader["finish_reason"] == "stop"
        judge = None
        if grade["status"] == "COMPLETED" and (Path(grade["score_root"]) / "judge").is_dir():
            judge = call_record(Path(grade["score_root"]) / "judge", "Judge", row)
            assert judge["status"] == "COMPLETED"
            judges.append(judge)
        capture, = (Path(case["owner_predictions"]) / "actual-retrieval-captures" / f"{row:04d}").glob("*/call.json")
        call = read(capture)
        assert call["schema"] == "frozen_retrieval_call_v2" and call["status"] == "ORIGINAL_COMPLETED"
        assert not call["host_request_generated"] and not call["served_from_cache"]
        assert call["public_message"]["given_retrieval_request"] == {"query": call["public_message"]["content"]}
        decisions, operations = [], []
        for event in call["control_events"]:
            assert event["event"] == "memory_control_step"
            action, = [a for a in event["actions"] if a["id"] == event["selected"]]
            if event["phase"] == "decision_output":
                selected[action["kind"]] += 1
                decisions.append(dict(step=event["step"], selected_action=action,
                    offered_actions=len(event["actions"]), selection_mode=event["selection_mode"]))
            else:
                assert event["phase"] == "operation_result"
                outcomes[action["kind"] + ":" + event["result"]["status"]] += 1
                operations.append(dict(step=event["step"], selected_action=action,
                    status=event["result"]["status"], ok=event["result"]["ok"]))
        packet = call["original_result"]
        assert packet["ok"]
        assert len(operations) == packet["usage"]["operations"]
        assert sum(op["selected_action"]["kind"] == "READ" for op in operations) == packet["usage"]["read_operations"]
        packet_usage.update(packet["usage"])
        terminations[packet["termination_reason"]] += 1
        evidence_kinds.update(item["kind"] for item in packet["evidence"])
        rows.append(dict(row=row, question_id=case["question_id"], domain=case["domain"], pool=case["pool"],
            native_prediction_status=case["status"], native_scoring_status=grade["status"],
            native_score=grade["score"], native_valid_UNKNOWN=grade.get("is_unknown"),
            Reader=reader, Judge=judge, capture=str(capture), complete_selected_bindings=decisions,
            actual_operation_results=operations, original_result_usage=packet["usage"],
            returned_packet_evidence_items=len(packet["evidence"])))
    assert len(readers) == 451 and len(judges) == 130
    failed = [r for r in readers if r["status"] == "FAILED"]
    assert Counter(r["final_content_state"] for r in failed) == {"absent": 49, "present": 1}
    assert next(r for r in failed if r["final_content_state"] == "present")["final_content_characters"] == 501
    owner_totals = {}
    for kind, calls in (("prediction", readers), ("scoring", judges)):
        members = [o for o in owners if o["stage_kind"] == kind]
        assert sum(o["shared_generation_admissions"] for o in members) == len(calls)
        assert sum(o["known_generation_tokens"] for o in members) == sum(c["total_tokens"] for c in calls)
        owner_totals[kind] = dict(segments=len(members),
            whole_child_CPU_seconds=sum(o["whole_child_CPU_seconds"] for o in members),
            measured_parent_CPU_seconds=sum(o["parent_CPU_seconds_through_billing"] for o in members),
            whole_child_plus_measured_parent_CPU_seconds=sum(o["whole_child_CPU_seconds"] + o["parent_CPU_seconds_through_billing"] for o in members),
            actual_owner_wall_seconds_sum=sum(o["wall_seconds"] for o in members),
            native_CPU_already_included=sum(sum(o["already_recorded_native_CPU"].values()) for o in members))
    result = dict(status="FIXED451_FIRST_PREDICTION_AND_NATIVE_SCORING_OPERATIONS_COST_CENSUS_CLOSED",
        timestamp_utc=datetime.now(timezone.utc).isoformat(), method="fixed-prefix", planned_positions=451,
        prediction_collection=str(predictions), scoring_collection=str(scores),
        prediction_status_counts=dict(Counter(c["status"] for c in generation["cases"])),
        scoring_status_counts=dict(Counter(c["status"] for c in grading["cases"])),
        native_aggregate=metrics, Reader=usage_summary(readers), failed_Readers=usage_summary(failed),
        Judge=usage_summary(judges), selected_action_counts=dict(selected),
        operation_kind_status_counts=dict(outcomes), termination_reason_counts=dict(terminations),
        native_retrieval_usage_counts=dict(packet_usage), returned_packet_evidence_kind_counts=dict(evidence_kinds),
        owner_totals=owner_totals, owners=owners, ancestry=chains, per_position=rows,
        actual_NN_forwards=0, local_NN_input_tokens=0, local_model_loads=0,
        GPU_job_interval_hours=None, Host_GPU_busy_hours=None,
        Source_and_entire_Reader_wire_audit=str(root / "verify-lme-fixed-source-audit-closed-v1.json"),
        native_score_and_entire_Judge_wire_audit=str(root / "verify-lme-fixed-native-scoring-closed-v1.json"),
        scope="Closed fixed-prefix prediction and scoring invocation costs only. Complete child CPU includes native model/client work; never add nested call, native or residual CPU again. Source preparation, offline audits, archive, training and author/launch/inspection costs are outside this subtotal. The archive stage may still be live; its cost is not inferred here. This is a report, not a ledger or a full-project total. Reader failures stay unscored; valid model UNKNOWN is distinct. No autonomous Host or original-paper model reproduction claim.",
        unmetered_author_inspection_launch_cleanup_CPU="unknown_not_zero",
        original_first_outcomes_rewritten=False, new_model_or_HTTP_calls=0,
        ledger_opened_or_written=False, no_sha_validation=True, goal_complete=False)
    with args.output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print("FIXED451_NATIVE_CENSUS", {k: result[k]["total_tokens"] for k in ("Reader", "Judge")},
        owner_totals, dict(selected), dict(outcomes), flush=True)


if __name__ == "__main__":
    main()
