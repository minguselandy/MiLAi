"""C-grade frozen-teacher answer likelihood on already executed native TRAIN packets."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json


def collect(args: Any) -> None:
    import torch  # type: ignore[import-not-found]
    import torch.nn.functional as functional  # type: ignore[import-not-found]
    from transformers import AutoModelForCausalLM, AutoTokenizer

    args.output.mkdir(parents=True, exist_ok=False)
    tick, cpu = time.perf_counter(), time.process_time()
    torch.set_num_threads(4)
    preparation = read_json(args.prepared / "run.json")
    if preparation["status"] != "COMPLETED":
        raise ValueError("Weak scores require completed actual branch preparation")
    roles = {h["source_group"]: h["split"] for h in read_json(
        Path(preparation["sources"]) / "sources.json")["histories"]}
    cases = read_json(args.prepared / "cases.json")
    if any(roles[c["family"]] != "train" for c in cases):
        raise ValueError("Teacher supervision is limited to assigned TRAIN roots")
    controls = {row["source_group"]: row for row in read_jsonl(args.controls)}
    tokenizer = AutoTokenizer.from_pretrained(  # type: ignore[no-untyped-call]
        str(args.teacher_model), local_files_only=True)
    device = torch.device(args.device)
    dtype = torch.float32
    model = AutoModelForCausalLM.from_pretrained(str(args.teacher_model), local_files_only=True,
                                                torch_dtype=dtype).to(device).eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    run: dict[str, Any] = {"status": "RUNNING", "pid": os.getpid(),
        "prepared": str(args.prepared),
        "controls": str(args.controls), "teacher_model": str(args.teacher_model),
        "dtype": str(dtype), "device": str(device),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "declared_max_input_tokens": args.max_input_tokens,
        "planned_branches": sum(len(c["branches"]) for c in cases),
        "closed_branches": 0, "forwards": 0, "input_tokens": 0, "target_tokens": 0,
        "Reader_calls": 0, "optimizer_updates": 0, "sha_validation": False,
        "pair_tolerance_mean_logprob": 0.0001,
        "protocol": "Original actual Reader messages, Qwen chat template thinking disabled, "
            "assistant JSON answer-field prefix then native JSON string. Exact canonical token "
            "prefix required; FP32 token log-softmax/mean. No task-outcome labels used.",
        "label_grade": "C_frozen_small_teacher_conditional_answer_likelihood",
        "scope": "Weak proxy from the frozen 0.6B teacher, not task Reader likelihood, "
            "task success, or semantic evidence verification. No unexecuted actions scored."}
    write_json(args.output / "run.json", run)
    probes: list[tuple[list[int], int, float]] = []
    try:
        for ci, case in enumerate(cases):
            for bi, branch in enumerate(case["branches"]):
                messages = branch["readout_request"]["messages"]
                prefix = tokenizer.apply_chat_template(messages, tokenize=False,
                    add_generation_prompt=True, enable_thinking=False) + '{"answer":'
                answer = " " + json.dumps(controls[case["family"]]["native_answer"],
                                           ensure_ascii=False)
                prefix_ids = tokenizer(prefix, add_special_tokens=False)["input_ids"]
                complete = tokenizer(prefix + answer, add_special_tokens=False)["input_ids"]
                boundary = len(prefix_ids)
                if complete[:boundary] != prefix_ids or len(complete) <= boundary:
                    raise ValueError("Canonical answer-token boundary is not prefix stable")
                if len(complete) > min(args.max_input_tokens, model.config.max_position_embeddings):
                    raise ValueError("Teacher input exceeds declared capacity; no truncation")
                ids = torch.tensor([complete], device=device)
                with torch.no_grad():
                    output = model(input_ids=ids, use_cache=False)
                    logits = output.logits[0, boundary-1:-1].float()
                    losses = functional.cross_entropy(logits, ids[0, boundary:], reduction="none")
                    if not bool(torch.isfinite(losses).all()):
                        raise ValueError("Nonfinite weak answer likelihood")
                    token_logprobs = (-losses).cpu().tolist()
                record = {"event_id": case["event_id"], "action": branch["action"],
                    "case_index": ci, "branch_index": bi,
                    "readout_request": branch["readout_request"],
                    "mean_answer_logprob": sum(token_logprobs) / len(token_logprobs),
                    "sum_answer_logprob": sum(token_logprobs),
                    "answer_token_ids": complete[boundary:], "token_logprobs": token_logprobs,
                    "input_tokens": len(complete), "label_grade": run["label_grade"]}
                if len(probes) < 2:
                    probes.append((complete, boundary, record["mean_answer_logprob"]))
                with (args.output / "scores.jsonl").open("a") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                run["closed_branches"] += 1
                run["forwards"] += 1
                run["input_tokens"] += len(complete)
                run["target_tokens"] += len(token_logprobs)
                del output, logits, losses, ids
            write_json(args.output / "run.json", run)
            if (ci + 1) % 8 == 0:
                print(json.dumps({"closed_branches": run["closed_branches"]}), flush=True)
        width = max(len(ids) for ids, _, _ in probes)
        pad = (tokenizer.pad_token_id if tokenizer.pad_token_id is not None
               else tokenizer.eos_token_id)
        batch = torch.full((len(probes), width), pad, device=device, dtype=torch.long)
        attention = torch.zeros_like(batch)
        for index, (tokens, _, _) in enumerate(probes):
            batch[index, :len(tokens)] = torch.tensor(tokens, device=device)
            attention[index, :len(tokens)] = 1
        with torch.no_grad():
            output = model(input_ids=batch, attention_mask=attention, use_cache=False)
            differences = []
            for index, (tokens, boundary, original) in enumerate(probes):
                logits = output.logits[index, boundary-1:len(tokens)-1].float()
                nll = functional.cross_entropy(logits, batch[index, boundary:len(tokens)])
                differences.append(abs(float(-nll) - original))
        if not all(torch.isfinite(torch.tensor(differences))):
            raise ValueError("Nonfinite teacher batch-combination probe")
        run["numeric_probe"] = {"cases": len(probes), "single_vs_padded_batch_abs_mean_differences":
            differences, "scope": "Finite first-two-branch probe, not a universal numerical bound"}
        run["pair_tolerance_mean_logprob"] = max(0.0001, 2 * max(differences))
        run["forwards"] += 1
        run["probe_input_tokens"] = sum(len(tokens) for tokens, _, _ in probes)
        run["probe_padded_tokens"] = len(probes) * width
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        run["status"] = "COMPLETED"
    except Exception as error:
        run.update(status="FAILED", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        run.update(wall_seconds=time.perf_counter()-tick, cpu_seconds=time.process_time()-cpu,
                   compute_ledger_status="pending_idle_settlement")
        write_json(args.output / "run.json", run)
    print(json.dumps({k: run[k] for k in ["status", "forwards", "input_tokens"]}), flush=True)
