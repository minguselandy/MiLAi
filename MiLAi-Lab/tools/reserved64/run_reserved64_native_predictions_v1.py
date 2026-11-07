"""One bounded fixed-model prediction cohort; no gold loading, HTTP, ledger or retries."""
import json
import math
import os
import resource
import sys
import time
from pathlib import Path

import torch
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.providers.laya_local import NativeDecision

plan = read_json(Path(sys.argv[1]))
protocol = read_json(Path(plan["protocol"]))
with Path(plan["public_inputs"]).open(encoding="utf-8") as stream:
    public = [json.loads(line) for line in stream]
assert len(public) == plan["positions"]
assert [row["index"] for row in public] == list(range(len(public)))
assert all(set(row) == {"index", "family", "payload"} and set(row["payload"]) == {"state", "questions"} for row in public)
output = Path(plan["output"])
output.mkdir()
cases = [{"index": row["index"], "family": row["family"], "status": "NOT_RUN"} for row in public]
if plan["continued_from"] is not None:
    prior = read_json(Path(plan["continued_from"]) / "driver.json")
    assert len(prior["cases"]) == len(cases)
    for index, case in enumerate(prior["cases"]):
        if case["status"] != "NOT_RUN":
            cases[index] = case
assert [i for i, case in enumerate(cases) if case["status"] == "NOT_RUN"] == plan["unattempted_indices"]
driver = {"schema": "reserved64_native_prediction_cohort_v1", "status": "RUNNING", "pid": os.getpid(),
    "model": plan["model"], "checkpoint": plan["checkpoint"], "positions": len(public), "cases": cases,
    "public_inputs": plan["public_inputs"], "continued_from": plan["continued_from"],
    "automatic_retry": False, "automatic_next_model": False, "gold_or_reference_loaded": False,
    "HTTP_calls": 0, "ledger_opened_or_written": False, "no_sha_validation": True}
write_json(output / "driver.json", driver)
started, cpu = time.perf_counter(), time.process_time()
model = None
try:
    torch.manual_seed(0)
    assert torch.get_num_threads() == 4 and os.environ["CUDA_VISIBLE_DEVICES"] == "2"
    assert not torch.backends.mha.get_fastpath_enabled()
    torch.cuda.set_per_process_memory_fraction(.75, 0)
    torch.cuda.reset_peak_memory_stats(0)
    model = NativeDecision(Path(plan["checkpoint"]), 16384, 2048, "cuda:0")
    assert str(next(model.model.parameters()).dtype) == "torch.float32"
    assert model.model.encoder.config.reference_compile is False
    for index in plan["unattempted_indices"]:
        row, case = public[index], cases[index]
        assert case["status"] == "NOT_RUN" and case["family"] == row["family"]
        call_root = output / "calls" / f"{index:06d}"
        call_root.mkdir(parents=True)
        case.update(status="FORWARD_STARTED", input=str(call_root / "input.json"),
                    output=str(call_root / "output.json"))
        driver["active_index"] = index
        write_json(call_root / "input.json", row["payload"])
        write_json(output / "driver.json", driver)
        try:
            predicted = model.predict(row["payload"])
        except Exception as error:
            case.update(status="FAILED_FIRST_FORWARD", error_type=type(error).__name__, error=str(error),
                        raw_model_return_captured=False, first_failure_retained=True)
            driver["status"] = "FAILED_RETAINED"
            write_json(output / "driver.json", driver)
            raise
        # Persist the actual native return before metadata validation; never re-forward it.
        write_json(call_root / "output.json", predicted)
        case.update(status="RETURNED_PENDING_VALIDATION", raw_model_return_captured=True)
        write_json(output / "driver.json", driver)
        criteria = row["payload"]["questions"]["applicability"]["criteria"]
        assert list(predicted["logits"]) == list(predicted["probabilities"]) == list(criteria)
        assert all(math.isfinite(v) for key in ("logits", "probabilities") for v in predicted[key].values())
        assert predicted["choice"] == max(predicted["probabilities"], key=predicted["probabilities"].get)
        assert predicted["truncated"] is False and 0 < predicted["input_tokens"] <= 16384
        case.update(status="COMPLETED", input_tokens=predicted["input_tokens"], first_output_retained=True)
        write_json(output / "driver.json", driver)
        if (index + 1) % 64 == 0:
            print("RESERVED64_FIRST_PREDICTIONS", plan["model"], index + 1, "/", len(public), flush=True)
    torch.cuda.synchronize(0)
    driver["status"] = "COMPLETED_FIRST_PREDICTIONS"
    write_json(output / "driver.json", driver)
except BaseException as error:
    driver.update(status="FAILED_RETAINED", error_type=type(error).__name__, error=str(error))
    write_json(output / "driver.json", driver)
    raise
finally:
    compute = {"whole_entry_wall_seconds_nested": time.perf_counter() - started,
        "entry_CPU_seconds_nested": time.process_time() - cpu,
        "actual_native_model_counters": model.counters if model is not None else None,
        "max_RSS_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "ledger_accounting": "No child charge. Parent owns whole childCPU/imports plus measured parent once after real exit.",
        "HTTP_calls": 0, "gold_or_reference_loaded": False, "no_sha_validation": True}
    if torch.cuda.is_initialized():
        torch.cuda.synchronize(0)
        compute.update(peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(0),
                       peak_cuda_reserved_bytes=torch.cuda.max_memory_reserved(0))
    write_json(output / "compute.json", compute)
