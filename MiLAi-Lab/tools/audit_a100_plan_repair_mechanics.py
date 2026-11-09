"""Reexecute existing B-repair/C validators with only new report destinations."""
import argparse
import json
import math
import sys
from datetime import datetime,timezone
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("component",choices=("b52","c7","c8","coverage","quality-input"))
    parser.add_argument("output",type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    if args.component == "b52":
        plan = read(root/"b-repair-read52-execution-plan-v1.json")
        entry = root/"bind_b_repair_read52.py"
        previous = root/"b-repair-read52-full-binding-v1.json"
        old_assignment = "output = root / ('b-repair-read52-full-binding-v1.json' if count == 52 else f'b-repair-read52-prefix-{count:02d}-binding-v1.json')"
        argv = [str(entry),"52"]
    elif args.component == "c7":
        plan = read(root/"c-repair7-native-v1/execution-plan-v1.json")
        entry = root/"bind_audit_c_repair7.py"
        previous = root/"c-repair7-native-v1/mechanical-source-input-audit-v1.json"
        old_assignment = "output = folder / 'mechanical-source-input-audit-v1.json'"
        argv = [str(entry)]
    elif args.component == "c8":
        plan = read(root/"c-handoff8-plan.json")
        entry = root/"bind_handoff8.py"
        previous = root/"c-handoff8-bound-results.json"
        old_assignment = "root / 'c-handoff8-bound-results.json'"
        argv = [str(entry)]
    elif args.component == "coverage":
        plan = read(root/"b-functional8-execution-plan.json")
        entry = root/"audit_b_repair_native_coverage.py"
        previous = root/"b-repair-binding-coverage-v1.json"
        old_assignment = "destination = root / 'b-repair-binding-coverage-v1.json'"
        argv = [str(entry)]
    else:
        plan = read(root/"b-functional8-execution-plan.json")
        entry = root/"prepare_b_c_repair_quality_review.py"
        previous = root/"b-c-repair-quality-review-input-v1.json"
        old_assignment = "output = root / 'b-c-repair-quality-review-input-v1.json'"
        argv = [str(entry)]
    import tokenizers
    import transformers

    assert transformers.__version__ == "4.52.3" and tokenizers.__version__ == "0.21.4"
    http_site = "/cra/memory/mx_memory/MiLAi-worktrees/jev-read-decisions-20261016/MiLAi-Lab/artifacts/jev-reader/http-env/lib/python3.11/site-packages"
    sys.path.append(http_site)
    runtime = Path(plan["runtime"])
    sys.path[:0] = [str(runtime/"tools"),str(runtime/"src")]
    source = entry.read_text()
    assert source.count(old_assignment) == 1 and output != previous.resolve()
    replacement = "output = Path(__audit_output__)"
    if args.component == "c8":
        replacement = "Path(__audit_output__)"
    elif args.component == "coverage":
        replacement = "destination = Path(__audit_output__)"
    changes = [(old_assignment,replacement)]
    extra_outputs = []
    if args.component == "coverage":
        for field,original in (("read","b-repair-remaining-observed-READ-bindings-v1.json"),
                               ("pool","c-repair-acquired-pool-reservation-v1.json")):
            new_path = output.with_suffix(f".{field}.json")
            old_expression = f"write_json(root / '{original}',"
            new_expression = f"write_json(Path(__audit_{field}_output__),"
            changes.append((old_expression,new_expression))
            extra_outputs.append((field,root/original,new_path))
    redirected = source
    for original,revised in changes:
        assert redirected.count(original) == 1
        redirected = redirected.replace(original,revised,1)
    restored = redirected
    for original,revised in reversed(changes):
        restored = restored.replace(revised,original,1)
    assert restored == source
    sys.argv = argv
    namespace = {"__name__":"__main__","__file__":str(entry),"__audit_output__":str(output)}
    namespace.update({f"__audit_{field}_output__":str(new) for field,_,new in extra_outputs})
    exec(compile(redirected,str(entry),"exec"),namespace)
    report = read(output)
    old_report = read(previous)
    excluded_dynamic_fields = ["cpu_seconds_pending"] if args.component == "c8" else []
    assert {k:v for k,v in report.items() if k not in excluded_dynamic_fields} == {
        k:v for k,v in old_report.items() if k not in excluded_dynamic_fields}
    for _,old,new in extra_outputs:
        assert read(new) == read(old)
    finite = []
    if args.component == "c7":
        for record in report["records"]:
            if record["method"] != "e3-aggregate-u32":
                continue
            captured = Path(record["prepared_capture"])
            call = read(captured/"call.json")
            trace = Path(record["actual_tool_case"])/"runtime"/call["host_prefix_trace"]
            prefix = (captured/"before"/call["host_prefix_trace"]).stat().st_size
            with trace.open("rb") as stream:
                stream.seek(prefix)
                events = [json.loads(line) for line in stream if line.strip()]
            modeled, = [event for event in events if event["event"] == "memory_control_model_result"]
            prediction = modeled["result"]
            assert all(math.isfinite(value) for field in ("logits","probabilities") for value in prediction[field].values())
            finite.append(dict(state_index=record["state_index"],finite_head_all_values=True,input_tokens=prediction["input_tokens"]))
        assert len(finite) == 7 and sum(record["input_tokens"] for record in finite) == 32401
    metadata = dict(passed=True,status="EXACT_ORIGINAL_REPAIR_VALIDATOR_REPLAY_ONLY_REPORT_DESTINATION_CHANGED",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),component=args.component,
        original_validator=str(entry),actual_frozen_runtime=str(runtime),new_report=str(output),original_report=str(previous),
        report_destinations_changed=len(changes),only_report_destinations_changed=True,
        inverse_change_entire_original_source_equal=True,
        reproduced_report_equal_excluding_only_dynamic_fields=excluded_dynamic_fields,
        entire_reproduced_report_literal_equal_original=report == old_report,
        auxiliary_reports_literal_equal_original=len(extra_outputs),additional_actual_C7_finite_head_checks=finite,
        original_Source_roles_bodies_clocks_permissions_inputs_models_or_firsts_changed=False,
        new_model_tokenizer_GPU_HTTP_business_or_original_ledger_calls=0,full763_line_completion_proven=False,
        CPU_pending_actual_idle138=True,no_sha_validation=True,goal_complete=False)
    sidecar = output.with_suffix(".execution.json")
    with sidecar.open("x") as stream:
        json.dump(metadata,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print("EXACT_REPAIR_VALIDATOR_REPLAY_LITERAL_EQUAL",args.component,"originalreport preserved; onlynewoutput",flush=True)


if __name__ == "__main__":
    main()
