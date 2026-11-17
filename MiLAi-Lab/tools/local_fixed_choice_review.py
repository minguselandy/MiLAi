"""Bounded local forward-only review classification; no text generation or HTTP."""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import random
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json

CODES = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0")
AXES = ("material_status", "task_resolution", "answer_grounding")


def choices(seed: int) -> dict[str, dict[str, Any]]:
    values = [
        dict(zip(AXES, row, strict=True))
        for row in itertools.product(
            ("SUFFICIENT", "INSUFFICIENT", "UNKNOWN"), (True, False, None), (True, False, None)
        )
    ]
    random.Random(seed).shuffle(values)  # noqa: S311 -- fixed experimental code map
    return dict(zip(CODES, values, strict=True))


def valid_joint(value: dict[str, Any]) -> bool:
    return value["task_resolution"] is not True or (
        value["material_status"] == "SUFFICIENT" and value["answer_grounding"] is True
    )


def prepare_requests(
    cases: list[dict[str, Any]],
    pilot: list[str],
    rubric: dict[str, Any],
    tokenizer: Any,
    *,
    maximum_input: int = 8192,
) -> list[dict[str, Any]]:
    by_code = {row["case_code"]: row for row in cases}
    if len(by_code) != len(cases) or len(pilot) != 10 or len(set(pilot)) != 10:
        raise ValueError("Require complete unique public cases and fixed10-case pilot")
    code_ids = {code: tokenizer.encode(code, add_special_tokens=False) for code in CODES}
    if (
        any(len(ids) != 1 for ids in code_ids.values())
        or len({v[0] for v in code_ids.values()}) != 27
    ):
        raise ValueError("All27 codes must be distinct single tokens")
    rules = [
        rule.replace(
            "Return one JSON object matching the schema without markdown.",
            "Select exactly one code and give no explanation.",
        )
        for rule in rubric["rules"]
    ]
    requests = []
    for ordinal, case_code in enumerate(pilot):
        case = by_code[case_code]
        if {"expected", "proof", "kind", "grade", "world", "pilot"} & case.keys():
            raise ValueError("Private calibration labels are not model inputs")
        for encoding, base_seed in enumerate((17001, 27001)):
            mapping = choices(base_seed + ordinal)
            messages = [
                {
                    "role": "system",
                    "content": "Assess supplied task, delivered evidence and observed answer. "
                    "Choose a code for all three axes. The table includes invalid "
                    "joint combinations; follow the semantic rules. Do not use outside facts.\n"
                    + "\n".join(rules),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "case": case,
                            "code_options": mapping,
                            "instruction": "Return only the selected one-character code.",
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ]
            rendered = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            ids = tokenizer.encode(rendered, add_special_tokens=False)
            if len(ids) > maximum_input:
                raise ValueError(
                    "Complete classifier prompt exceeds registered capacity; no truncation"
                )
            requests.append(
                {
                    "case_code": case_code,
                    "encoding": encoding,
                    "code_seed": base_seed + ordinal,
                    "messages": messages,
                    "rendered_prompt": rendered,
                    "input_token_ids": ids,
                    "input_tokens": len(ids),
                    "code_options": mapping,
                    "code_token_ids": {code: value[0] for code, value in code_ids.items()},
                }
            )
    return requests


def free_devices() -> dict[int, int]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        raise RuntimeError("nvidia-smi is unavailable")
    result = subprocess.run(  # noqa: S603 -- fixed argv and PATH-resolved nvidia-smi
        [executable, "--query-gpu=index,memory.free", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=True,
    )
    return {
        int(row.split(",")[0]): int(row.split(",")[1])
        for row in result.stdout.splitlines()
        if row.strip()
    }


def resource_ready(free: dict[int, int], minimum: int = 35840) -> bool:
    return all(free.get(index, 0) >= minimum for index in (2, 3))


def score_request(model: Any, request: dict[str, Any], *, device: Any) -> dict[str, Any]:
    import torch

    ids = torch.tensor([request["input_token_ids"]], dtype=torch.long, device=device)
    with torch.inference_mode():
        result = model(
            input_ids=ids, attention_mask=torch.ones_like(ids), use_cache=False, logits_to_keep=1
        )
        logits = result.logits[0, -1]
        candidate = torch.tensor(
            [request["code_token_ids"][code] for code in CODES],
            dtype=torch.long,
            device=logits.device,
        )
        scores = logits[candidate].float().cpu().tolist()
    if not all(math.isfinite(value) for value in scores):
        raise FloatingPointError("Nonfinite classification logits")
    code = CODES[max(range(len(CODES)), key=lambda i: scores[i])]
    value = request["code_options"][code]
    return {
        "case_code": request["case_code"],
        "encoding": request["encoding"],
        "status": "SCORED",
        "predicted_code": code,
        "predicted_axes": value,
        "valid_joint_combination": valid_joint(value),
        "all_code_logits": dict(zip(CODES, scores, strict=True)),
        "input_tokens": request["input_tokens"],
        "compared_code_tokens": 27,
        "decision_positions": 1,
        "text_generation_tokens": 0,
        "scope": "Fixed-choice conditional forward, not generated review or rationale",
    }


def worker(prepared: Path, output: Path, model_path: Path) -> None:
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "2,3":
        raise ValueError("This registered worker requires only physical GPU2,3")
    actual = free_devices()
    if not resource_ready(actual):
        raise ValueError("Fresh GPU2,3 free memory is below registered threshold")
    import torch
    from transformers import AutoModelForCausalLM

    requests = read_json(prepared / "requests.json")
    if len(requests) != 20:
        raise ValueError("Only fixed10cases/two encodings admitted")
    output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time()
    run: dict[str, Any] = {
        "status": "RUNNING",
        "pid": os.getpid(),
        "planned_forwards": 20,
        "closed_forwards": 0,
        "model_path": str(model_path),
        "prepared": str(prepared),
        "mode": "local_conditional_one_position_fixed_choice_v1",
        "GPU_physical_devices": [2, 3],
        "Reader_HTTP_calls": 0,
        "text_generation_tokens": 0,
        "sha_validation": False,
    }
    write_json(output / "run.json", run)
    model = None
    try:
        torch.set_num_threads(4)
        model = AutoModelForCausalLM.from_pretrained(
            str(model_path),
            local_files_only=True,
            trust_remote_code=False,
            torch_dtype=torch.bfloat16,
            device_map="auto",
            max_memory={0: "32GiB", 1: "32GiB"},
            attn_implementation="sdpa",
        )
        model.eval()
        mapping = {key: str(value) for key, value in model.hf_device_map.items()}
        if any(value in {"cpu", "disk"} for value in mapping.values()):
            raise ValueError("CPU/disk offload was not registered")
        run["actual_device_map"] = mapping
        run["resident_parameter_count"] = sum(p.numel() for p in model.parameters())
        run["completed_input_tokens"] = 0
        for request in requests:
            if time.perf_counter() - wall > 570:
                raise TimeoutError("Stop before registered hard process deadline")
            tick = time.perf_counter()
            run["active"] = {
                "case_code": request["case_code"],
                "encoding": request["encoding"],
                "input_tokens": request["input_tokens"],
                "status": "BEFORE_FORWARD",
            }
            write_json(output / "run.json", run)
            row = score_request(model, request, device=model.device)
            for index in range(torch.cuda.device_count()):
                torch.cuda.synchronize(index)
            row["wall_seconds"] = time.perf_counter() - tick
            with (output / "scores.jsonl").open("a") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            run["closed_forwards"] += 1
            run["completed_input_tokens"] += request["input_tokens"]
            run.pop("active")
            write_json(output / "run.json", run)
            print(json.dumps({"closed_forwards": run["closed_forwards"]}), flush=True)
        run.update(
            status="COMPLETED",
            input_tokens=sum(r["input_tokens"] for r in requests),
            compared_code_tokens=20 * 27,
            decision_positions=20,
            cuda_peak_allocated_bytes={
                str(i): torch.cuda.max_memory_allocated(i) for i in range(torch.cuda.device_count())
            },
        )
    except Exception as exc:
        run.update(status="FAILED_NO_RETRY", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        run.update(
            wall_seconds=time.perf_counter() - wall,
            cpu_seconds=time.process_time() - cpu,
            scheduled_GPU_job_seconds=2 * (time.perf_counter() - wall),
            compute_ledger_status="pending_original_idle_scope_settlement",
            scope="Local forward-only classification; no HTTP/generation budget touched. "
            "Two-device job wall is not active kernel time. PhysicalIO/energy/money unknown.",
        )
        write_json(output / "run.json", run)
        del model


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--cases", type=Path, required=True)
    prepare.add_argument("--pilot", type=Path, required=True)
    prepare.add_argument("--rubric", type=Path, required=True)
    prepare.add_argument("--model", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("worker")
    run.add_argument("--prepared", type=Path, required=True)
    run.add_argument("--model", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "worker":
        worker(args.prepared, args.output, args.model)
        return
    from transformers import AutoTokenizer

    wall, cpu = time.perf_counter(), time.process_time()
    tokenizer = AutoTokenizer.from_pretrained(
        str(args.model), local_files_only=True, trust_remote_code=False
    )
    requests = prepare_requests(
        read_json(args.cases), read_json(args.pilot), read_json(args.rubric), tokenizer
    )
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "requests.json", requests)
    write_json(
        args.output / "run.json",
        {
            "status": "FROZEN_BEFORE_MODEL_LOAD",
            "cases": 10,
            "forwards": 20,
            "model": str(args.model),
            "input_tokens": sum(r["input_tokens"] for r in requests),
            "maximum_input_tokens": max(r["input_tokens"] for r in requests),
            "maximum_allowed": 8192,
            "private_truth_loaded": False,
            "Reader_HTTP_calls": 0,
            "GPU_job_requested": False,
            "sha_validation": False,
            "wall_seconds": time.perf_counter() - wall,
            "cpu_seconds": time.process_time() - cpu,
            "compute_ledger_status": "pending_idle_settlement",
        },
    )


if __name__ == "__main__":
    main()
