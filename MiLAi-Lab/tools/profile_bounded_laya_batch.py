"""Same-model, same-input FP32 comparison of scalar and cached batch evaluation."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from milai_lab.harness.artifact_io import read_jsonl, write_json
from milai_lab.providers.laya_local import NativeDecision


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--rows", type=int, default=64)
    parser.add_argument("--max-len", type=int, default=16384)
    parser.add_argument("--head-max-len", type=int, default=2048)
    parser.add_argument("--task", choices=("mixed_retrieval", "memory_operation"),
                        default="mixed_retrieval")
    parser.add_argument("--operation-state", default="shared_actions")
    args = parser.parse_args()
    import torch

    torch.set_num_threads(4)
    torch.backends.mha.set_fastpath_enabled(False)
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    rows = read_jsonl(args.data)
    if args.task == "mixed_retrieval":
        from retrieval_mixture import project_mixed_row

        rows = [project_mixed_row(row, args.operation_state) for row in rows]
    else:
        from milai_lab.methods.laya_memory_policy import project_operation_payload

        rows = [project_operation_payload(row, args.operation_state) for row in rows]
    # Quantiles of serialized input size include the longest examples without gold selection.
    order = sorted(range(len(rows)), key=lambda i: len(json.dumps(
        {k: rows[i][k] for k in ("state", "questions")})))
    n = min(args.rows, len(rows))
    selected = [order[round(i * (len(order) - 1) / max(n - 1, 1))] for i in range(n)]
    rows = [rows[i] for i in selected]
    model = NativeDecision(args.checkpoint, args.max_len, args.head_max_len, "cuda:0")
    model.model.encoder.config.reference_compile = False
    load_seconds = time.perf_counter() - started
    encode_started = time.perf_counter()
    prepared = model.prepare_batch(rows)
    encode_seconds = time.perf_counter() - encode_started
    model.predict(rows[0])
    model.predict_prepared(prepared[:args.batch_size], args.batch_size)
    measurements = {}
    predictions = {}
    # ABBA alternates order to expose simple warmup/order effects.
    for number, mode in enumerate(("scalar", "batch", "batch", "scalar")):
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        before = dict(model.counters)
        wall, process = time.perf_counter(), time.process_time()
        result = ([model.predict(row) for row in rows] if mode == "scalar" else
                  model.predict_prepared(prepared, args.batch_size))
        torch.cuda.synchronize()
        wall, process = time.perf_counter() - wall, time.process_time() - process
        counts = {k: v - before[k] for k, v in model.counters.items()}
        measurements[f"{number}-{mode}"] = {
            "wall_seconds": wall, "cpu_seconds": process, **counts,
            "effective_tokens_per_second": counts["input_tokens"] / wall,
            "states_per_second": n / wall,
            "padding_fraction": 1 - counts["input_tokens"] / counts["padded_input_tokens"],
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        }
        predictions[mode] = result
        print(json.dumps({"mode": mode, **measurements[f"{number}-{mode}"]}), flush=True)
    differences = []
    for index, (left, right) in enumerate(zip(
            predictions["scalar"], predictions["batch"], strict=True)):
        scalar = sorted(left["logits"].values(), reverse=True)
        differences.append({
            "row": selected[index], "choice_equal": left["choice"] == right["choice"],
            "keys_equal": list(left["logits"]) == list(right["logits"]),
            "input_tokens_equal": left["input_tokens"] == right["input_tokens"],
            "max_logit_error": max(abs(left["logits"][key] - right["logits"][key])
                                   for key in left["logits"]),
            "scalar_top_margin": scalar[0] - scalar[1] if len(scalar) > 1 else None,
        })
    with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU,
                                           torch.profiler.ProfilerActivity.CUDA],
                                record_shapes=True) as profile:
        model.predict_prepared(prepared, args.batch_size)
    profile.export_chrome_trace(str(args.output / "batch-trace.json"))
    (args.output / "profile.txt").write_text(profile.key_averages().table(
        sort_by="self_cuda_time_total", row_limit=30))
    report = {"status": "COMPLETED", "data": str(args.data.resolve()),
              "checkpoint": str(args.checkpoint.resolve()), "selected_rows": selected,
              "no_sha_validation": True, "precision": "float32", "batch_size": args.batch_size,
              "encoding_seconds": encode_seconds, "load_and_input_seconds": load_seconds,
              "measurements": measurements, "comparisons": differences,
              "lengths": [len(item.encoded["ids"]) for item in prepared],
              "menus": [len(item.keys) for item in prepared],
              "wall_seconds": time.perf_counter() - started,
              "cpu_seconds": time.process_time() - cpu,
              "scope": "Engineering comparison; no training, Host or quality gain claim"}
    write_json(args.output / "comparison.json", report)
    write_json(args.output / "predictions.json", predictions)


if __name__ == "__main__":
    main()
