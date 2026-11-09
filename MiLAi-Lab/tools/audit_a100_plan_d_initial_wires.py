"""Bind D first Provider requests to actual pre-Host trace boundaries and distinguish later tool arguments."""
import argparse
import json
from collections import Counter
from datetime import datetime,timezone
from itertools import combinations
from pathlib import Path

from audit_a100_plan_d_existing_execution import read


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("output",type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    old = Path("/cra/memory/mx_memory/MiLAi-worktrees/evidence-gap-development-20261023/MiLAi-Lab/artifacts/development-training-20261102/e5-controlled-lifecycle-v1/executions/extractive-2048")
    names = ["view_cache","view_cache_incremental","e3-aggregate-u32"]
    comparisons,counts = {},{}
    actual_requests = 0
    output_bindings = Counter()
    for cohort in ("old8","new32"):
        wires,arguments,keys = {},{},None
        for name in names:
            folder = old if cohort == "old8" and name == "view_cache" else root/"d-update32/reviews"/(cohort+"-"+name)
            rows = [row for row in read(folder/"source-review-packet-v1.json")["records"] if row["request"] == "initial"]
            row_keys = [(row["history"],row["request"]) for row in rows]
            if keys is None:
                keys = row_keys
            else:
                assert row_keys == keys
            assert len(rows) == (16 if cohort == "old8" else 64)
            wires[name],arguments[name] = [],[]
            for row in rows:
                boundary = row["final_host_input"] if row["status"] == "COMPLETED" else row["failed_last_provider_input"]
                host = read(Path(row["closed_snapshot"]).parent/"host.json")
                assert host["public_message"]["message_id"] == "initial" and host["bank"] == row["history"]
                assert Path(row["result_path"]) == Path(host["source_root"])/host["host_result_path"]
                assert Path(boundary["trace"]) == Path(host["source_root"])/host["host_prefix_trace"]
                prefix = (Path(row["closed_snapshot"]).parent/"before"/host["host_prefix_trace"]).read_bytes()
                with Path(boundary["trace"]).open("rb") as stream:
                    assert stream.read(len(prefix)) == prefix
                    providers = [event for event in map(json.loads,stream) if event["event"] == "vllm_response"]
                first = providers[0]
                recorded = [item for item in host["delivered_model_requests"] if item["output_message_id"] == first["receipt"]["id"]]
                assert len(recorded) <= 1
                if recorded:
                    assert recorded[0]["schema"] == "provider_request_content_v1"
                    output_bindings["decoded_first_output_callback_bound"] += 1
                else:
                    output_bindings["first_response_has_no_decoded_output_callback"] += 1
                wires[name].append(first["request"])
                result = read(row["result_path"])
                output_bindings["first_response_id_also_in_native_AI_messages"] += any(
                    message.get("id") == first["receipt"]["id"] for message in result["messages"] if message["type"] == "ai")
                batches = [message["tool_calls"] for message in result["messages"] if message["type"] == "ai" and message.get("tool_calls")]
                arguments[name].append([dict(name=call["name"],args=call["args"]) for call in batches[0]] if batches else None)
                actual_requests += 1
        original = read(root/"d-update32"/("old8-family-comparison-v1.json" if cohort == "old8" else "new32-family-comparison-v1.json"))
        pairs = []
        for reference,candidate in combinations(names,2):
            same_wire = sum(left == right for left,right in zip(wires[reference],wires[candidate],strict=True))
            same_args = sum(left is not None and left == right for left,right in zip(arguments[reference],arguments[candidate],strict=True))
            saved, = [entry for entry in original["comparisons"] if entry["reference"] == reference and entry["candidate"] == candidate]
            assert same_wire == saved["paired_initial_first_HTTP_wire_equal"] == len(keys)
            saved_arg_key = "paired_initial_first_retrieval_arguments_equal" if cohort == "old8" else "paired_initial_first_retrieval_argument_batches_equal"
            assert same_args == saved[saved_arg_key] == 0
            pairs.append(dict(reference=reference,candidate=candidate,actual_first_Provider_request_dicts_literal_equal=same_wire,
                initial_flow_positions=len(keys),actual_first_tool_argument_batches_equal=same_args))
        comparisons[cohort] = pairs
        counts[cohort] = len(keys)
    assert actual_requests == 240
    result = dict(passed=True,status="D240_ACTUAL_FIRST_PROVIDER_REQUESTS_BOUND_TO_PRE_HOST_TRACE_BOUNDARIES_ALL_INITIAL_WIRES_MATCH_LATER_TOOL_ARGUMENTS_DIFFER",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),actual_first_Provider_requests_bound=240,
        decoded_output_callback_and_native_message_binding_counts=dict(output_bindings),
        first_undecoded_response_callbacks_not_fabricated=True,
        initial_flow_positions_per_method=counts,comparisons=comparisons,
        all_three_method_pairs_old8_first_Provider_wires_equal16_of16=True,
        all_three_method_pairs_new32_first_Provider_wires_equal64_of64=True,
        first_tool_argument_batches_equal_zero_in_all_pairs=True,
        current_summary_correction="Earlier broad wording that D initial Provider wires were not all equal is unsupported. Actual first Provider request dicts are all equal within each predeclared initial flow position. Actual runtime Source IDs/capture clocks and subsequent tool arguments/endogenous histories differ; distinguish those from initial Provider input. Fair autonomous initial information is matched, while later reached-state/controller causality and matched Host RNG are not established.",
        original_comparison_numeric_fields_literal_preserved=True,
        source_author_not_independent_or_blind=True,new_model_tokenizer_GPU_HTTP_business_or_original_ledger_calls=0,
        original_Source_inputs_labels_models_or_firsts_changed=False,CPU_pending_actual_idle138=True,
        no_sha_validation=True,full763_line_completion_proven=False,goal_complete=False)
    with args.output.open("x") as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print("D240_ACTUAL_FIRST_PROVIDER_REQUESTS_TRACE_BOUND_ALL_INITIAL_WIRES_MATCH_FIRST_TOOL_ARGUMENTS_DIFFER",dict(output_bindings),flush=True)


if __name__ == "__main__":
    main()
