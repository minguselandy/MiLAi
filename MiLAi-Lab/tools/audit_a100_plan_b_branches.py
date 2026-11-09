"""Audit all actual B64 same-before triads, Source ranges, Reader wires and shared costs."""
import argparse
import copy
import json
import math
import sys
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def lines(path):
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("output",type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    owner = read(root/"b64-pilot8-branch-owner.json")
    runtime = Path(owner["argv"][2]).parent.parent
    import tokenizers
    import transformers

    assert transformers.__version__ == "4.52.3" and tokenizers.__version__ == "0.21.4"
    sys.path.append(str(Path(owner["argv"][0]).parents[2]/"http-env/lib/python3.11/site-packages"))
    sys.path[:0] = [str(runtime/"tools"),str(runtime/"src")]
    from feedback_choices import baseline_choice,full_menu_choice
    from feedback_outcomes import reached_outcomes
    from milai_lab.memory.literal_projection import expand_observation_state

    closeout = read(root/"b64-branch-closeout.json")
    all_records,all_families,all_states = [],set(),set()
    segment_receipts = {}
    source_ranges = model_inputs = 0
    origins = Counter()
    records_per_family = Counter()
    per_state = []
    for segment in ("pilot8","remaining56"):
        folder = root/f"b64-{segment}-branches"
        bound = read(folder/"outcomes-for-review.json")
        owner = read(root/f"b64-{segment}-branch-owner.json")
        driver = read(root/f"b64-{segment}-branch-execution/driver.json")
        assert owner["status"] == "COMPLETED" and owner["exit_code"] == 0 and owner["client_CPU_recorded"]
        assert owner["automatic_retry"] is False
        assert all(not Path("/proc",str(owner[key])).exists() for key in ("pid","child_pid"))
        assert driver["status"] in {"COMPLETED","COMPLETED_WITH_MISSING_READOUTS"}
        assert len(driver["completed"]) == bound["new_executed_bindings"]
        policies = read(folder/"comparison-policies.json")
        fresh = read(folder/"execution-policies.json")
        reused = read(folder/"reused-collector-outcomes.json")
        assert {job["name"] for job in fresh}.isdisjoint(job["job"]["name"] for job in reused)
        assert {job["name"] for job in policies} == {job["name"] for job in fresh}|{job["job"]["name"] for job in reused}
        selection = read(folder/"selection.json")
        source_selection = read(root/f"b64-{segment}-state-selection.json")
        assert source_selection["model_calls"] == source_selection["new_training_labels"] == 0
        assert source_selection["state_selection"] == "acquired_parameter_support"
        assert not source_selection["conditions"]["unscored"]
        selected = {str(Path(row["path"]).resolve()):row for row in selection["selected"]}
        nominations = {row["capture"]:row for row in selection["decision_nominations"]}
        assert selection["split"] == "train" and selection["branch_sampling"] == "current-decision"
        histories = {history["source_group"]:history for history in read(root/f"b64-collection-{segment}-v2/fixture.json")["histories"]}
        states = defaultdict(list)
        for record in bound["records"]:
            states[record["capture"]].append(record)
        receipt = dict(new_HTTP=0,known_generation_tokens=0,prompt_tokens=0,completion_tokens=0,new_unknown_usage=0,
            readout_failures=Counter(),client_CPU_seconds_already_recorded=owner["whole_child_CPU_seconds"],inclusive_job_wall_seconds=owner["wall_seconds"])
        for capture,members in states.items():
            assert capture not in all_states
            all_states.add(capture)
            assert len(members) == 3 and [row["choice_role"] for row in members] == ["current_argmax","baseline","alternative"]
            call = read(Path(capture)/"call.json")
            selected_record = selected[capture]
            assert selected_record["split"] == "train"
            nomination = nominations[selected_record["capture"]]
            assert nomination["distinct_bindings"] == 3 and nomination["has_comparison"]
            action_list = [record["first_action"] for record in members]
            assert all(action in call["initial_actions"] for action in action_list)
            for i,left in enumerate(action_list):
                for right in action_list[i+1:]:
                    assert any(left[key] != right[key] for key in ("kind","target","parameters"))
            assert action_list[0]["id"] == nomination["argmax"]
            assert action_list[1]["id"] == nomination["baseline"] == baseline_choice(call,selection["decision_baseline"],selection["decision_baseline_reads"])
            location = nomination["prediction_location"]
            event = lines(location["trace"])[location["event_index"]]
            assert event["event"] == "memory_control_model_result"
            expanded = expand_observation_state(event["input"]["state"])
            assert expanded.pop("action_bindings") == call["initial_actions"] and expanded == call["initial_observation"]
            result = event["result"]
            assert list(result["logits"]) == list(result["probabilities"]) == [action["id"] for action in call["initial_actions"]]
            assert all(math.isfinite(value) for field in ("logits","probabilities") for value in result[field].values())
            assert result["truncated"] is False and 0 < result["input_tokens"] <= 16384
            assert full_menu_choice(call["initial_actions"],result["logits"]) == nomination["argmax"]
            model_inputs += 1
            actual = reached_outcomes(Path(capture),{record["first_action"]["id"]:record["origin"] for record in members})
            normalized = []
            for record in members:
                observed = actual[record["first_action"]["id"]]
                assert observed["action"] == record["first_action"] and observed["packet"] == record["actual_delivered_packet"]
                readout = read(record["readout"])
                assert readout["status"] == record["status"] and readout["actual_http_attempts"] == 1 and readout["automatic_retry"] is False
                origins[record["origin"]["kind"]] += 1
                if record["origin"]["kind"] == "same_before_first_action":
                    receipt["new_HTTP"] += 1
                    before,after = readout["budget_before"],readout["budget_after"]
                    known = after["generation"]["known_tokens"]-before["generation"]["known_tokens"]
                    unknown = after["generation"]["unknown_usage"]-before["generation"]["unknown_usage"]
                    assert unknown == 0
                    usage, = [row["usage"] for row in readout["usage"] if row["event"] == "vllm_response"]
                    assert known == usage["total_tokens"] == usage["prompt_tokens"]+usage["completion_tokens"]
                    receipt["known_generation_tokens"] += known
                    receipt["prompt_tokens"] += usage["prompt_tokens"]
                    receipt["completion_tokens"] += usage["completion_tokens"]
                    receipt["new_unknown_usage"] += unknown
                    if readout["status"] == "FAILED":
                        receipt["readout_failures"][readout["error"]] += 1
                else:
                    assert record["origin"]["kind"] == "closed_collector_last_decision"
                    assert record["first_action"]["kind"] == "READ" and call["initial_observation"]["budget"]["remaining_control_steps"] == 1
                family = record["family"]
                assert family == selected_record["family"]
                all_families.add(family)
                records_per_family[family] += 1
                piece_count = 0
                for evidence in observed["packet"]["evidence"]:
                    assert evidence["kind"] == "original_source"
                    for piece in evidence["evidence"]:
                        start,end = piece["range"]
                        matches = [source["original_event_id"] for source in histories[family]["sources"]
                            if source["role"] == piece["role"] and source["origin"] == piece["origin"]
                            and len(source["content"]) == piece["source_characters"] and 0 <= start <= end <= len(source["content"])
                            and source["content"][start:end] == piece["content"]]
                        assert matches
                        assert record["actual_source_ranges"][piece_count]["original_source_candidates"] == matches
                        piece_count += 1
                assert piece_count == len(record["actual_source_ranges"])
                source_ranges += piece_count
                wire = copy.deepcopy(observed["wire"])
                body = json.loads(wire["messages"][1]["content"])
                assert body["memory"] == observed["packet"] and body["retrieval_request"] == call["request"]
                body["memory"] = None
                wire["messages"][1]["content"] = body
                normalized.append(wire)
                all_records.append(record)
            assert normalized[0] == normalized[1] == normalized[2]
            per_state.append(dict(capture=capture,family=members[0]["family"],full_NN_input_head_order_finite_argmax_verified=True,
                complete_distinct_first_bindings=action_list,common_before_menu_prefix_and_bounded_continuation_verified=True,
                Reader_wire_literal_equal_except_actual_packet=True))
        receipt["readout_failures"] = dict(receipt["readout_failures"])
        receipt.update(source_families=bound["source_families"],states=bound["comparison_states"],Source_ranges=bound["actual_source_ranges_bound"])
        assert receipt == closeout["new_HTTP_cost_by_segment"][segment]
        segment_receipts[segment] = receipt
        print("B_ACTUAL_TRIADS_SOURCE_RANGES_READER_WIRES_VERIFIED",segment,len(states),len(bound["records"]),flush=True)
    assert len(all_records) == 384 and len(all_states) == model_inputs == 128 and len(all_families) == 64
    assert set(records_per_family.values()) == {6}
    assert origins == {"same_before_first_action":358,"closed_collector_last_decision":26}
    statuses = Counter(record["status"] for record in all_records)
    assert statuses == closeout["actual_readout_status"] == {"COMPLETED":373,"FAILED":11}
    assert len({record["readout"] for record in all_records}) == 384
    assert sum(receipt["new_HTTP"] for receipt in segment_receipts.values()) == 358
    assert sum(record["choice_role"] == "baseline" for record in all_records) == 128
    assert Counter(record["first_action"]["kind"] for record in all_records if record["choice_role"] == "alternative") == {"READ":90,"HANDOFF":38}
    prefix = read(root/"b64-full-collection-reconciliation.json")
    assert prefix["families"] == prefix["requests"] == 64 and prefix["all_native_queries_literal"] and prefix["all_local_inputs_complete"]
    out = dict(passed=True,status="B64_ALL384_FIRST_BINDINGS_FULL_BEFORE_NN_SOURCE_RANGES_READER_WIRES_AND_SHARED_BASELINE_RECONCILED",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),actual_branch_runtime=str(runtime),families=64,states=128,bindings=384,
        all128_NN_inputs_full_before_and_entire_head_order_finite_argmax_verified=True,
        all128_triads_distinct_complete_legal_bindings=True,all_actual_prefix_boundaries_and_bounded_continuations_checked=True,
        all_source_role_origin_body_character_ranges_literal_bound=True,actual_source_range_pieces=source_ranges,
        all_Reader_request_dicts_equal_except_actual_delivered_packet_within_state=True,
        native_readout_status_counts=dict(statuses),alternative_kinds={"READ":90,"HANDOFF":38},
        origin_counts=dict(origins),new_HTTP=358,reused_original_terminal_READ_first_results=26,
        shared_baseline_actual_outcomes=128,baseline_results_not_collected_twice_for_two_panels=True,
        new_HTTP_cost_by_segment=segment_receipts,new_known_generation_tokens=sum(v["known_generation_tokens"] for v in segment_receipts.values()),
        prefix_collection_cost_receipt=str(root/"b64-full-collection-reconciliation.json"),
        prefix_and26_reused_results_not_free_or_recharged=True,per_state=per_state,
        scope="Actual three-branch supervised support comparison with one shared baseline. Different full bindings with identical packets remain distinct executed branches. Complete Source packet ranges/roles/origins, actual before/menu/NN and trace-prefix/continuation/Reader-wire checked; not a new independent semantic review or a claim of equal-cost collector efficiency.",
        new_model_tokenizer_GPU_HTTP_business_or_original_ledger_calls=0,
        original_inputs_labels_or_first_results_changed=False,full763_line_completion_proven=False,no_sha_validation=True,goal_complete=False)
    with args.output.open("x") as stream:
        json.dump(out,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print(out["status"],"64families128triads384firsts;358new+26reuse;sharedBaseline128")


if __name__ == "__main__":
    main()
