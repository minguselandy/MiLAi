"""Matched SFT, source-reviewed pairwise preference, and consequence objectives.

The ranking term uses mean response NLL, including EOS. It is a simple paired
sequence loss, not DPO, RL or a learned correctness reward. All conditions run
the same positive, negative and auxiliary sequences and backward graph shapes.
"""

from __future__ import annotations

import argparse
import gc
import json
import resource
import time
from pathlib import Path

from innovation_lora import install_lora
from train_innovation_adapter import render_target

OBJECTIVES = ("imitation", "quality_preference", "relation_consequence")


def preference_loss(chosen_mean, rejected_means, beta=1.0):
    import torch

    return torch.stack([
        torch.nn.functional.softplus(beta * (chosen_mean - rejected))
        for rejected in rejected_means
    ]).mean()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("data", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20261016)
    parser.add_argument("--rank", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=0.0005)
    parser.add_argument("--preference-weight", type=float, default=0.5)
    parser.add_argument("--consequence-weight", type=float, default=0.25)
    parser.add_argument("--source-version", default="working-tree")
    args = parser.parse_args()
    import torch
    from safetensors.torch import save_file
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    rows = [json.loads(line) for line in args.data.read_text().splitlines() if line.strip()]

    def encode(messages, target):
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        prompt_ids = tokenizer.encode(prompt, add_special_tokens=False)
        text, _ = render_target(target)
        response = [*tokenizer.encode(text, add_special_tokens=False), tokenizer.eos_token_id]
        return {"ids": [*prompt_ids, *response], "prompt_tokens": len(prompt_ids),
                "response_tokens": len(response)}

    examples = [{"id": row["example_id"],
        "chosen": encode(row["messages"], row["target"]),
        "rejected": [encode(row["messages"], item["target"]) for item in row["rejected"]],
        "auxiliary": (encode(row["auxiliary"]["messages"], row["auxiliary"]["target"])
                      if "auxiliary" in row else None)} for row in rows]
    order = list(range(len(examples))) * args.epochs
    permutation = torch.randperm(len(order), generator=torch.Generator().manual_seed(args.seed))
    order = [order[i] for i in permutation.tolist()]
    batches = [order[start:start + args.batch_size]
               for start in range(0, len(order), args.batch_size)]
    tasks = [task for i in order for task in [examples[i]["chosen"], *examples[i]["rejected"],
             *([examples[i]["auxiliary"]] if examples[i]["auxiliary"] else [])]]
    args.output.mkdir(parents=True, exist_ok=True)
    protocol = {"source_version": args.source_version, "model_path": str(args.model),
        "device": "cpu", "dtype": "float32", "threads": args.threads, "seed": args.seed,
        "rank": args.rank, "alpha": 2 * args.rank, "learning_rate": args.learning_rate,
        "epochs": args.epochs, "batch_size": args.batch_size, "examples": len(rows),
        "optimizer_steps_per_arm": len(batches), "objectives": list(OBJECTIVES),
        "example_order": [examples[i]["id"] for i in order],
        "input_tokens_per_arm": sum(t["prompt_tokens"] for t in tasks),
        "response_positions_per_arm": sum(t["response_tokens"] for t in tasks),
        "preference_weight": args.preference_weight, "preference_beta": 1.0,
        "consequence_weight": args.consequence_weight,
        "main_loss": "Uniform chosen-token CE normalized over each minibatch.",
        "preference_loss": "Mean softplus(chosen mean response NLL - rejected mean response NLL), "
                           "averaged over alternatives and examples. Not DPO or RL.",
        "matching": "Same sequences, ordering, initialization, trainable parameters and steps. "
                    "Unused negative/auxiliary terms remain in the graph with zero coefficients. "
                    "No claim of bit-for-bit kernel/FLOP equality.",
        "scope": "Exposed author-reviewed local preferences; not perfect global states or holdout.",
        "torch": torch.__version__, "model_http_calls": 0}
    (args.output / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")

    def losses(network, task):
        ids = torch.tensor([task["ids"]], dtype=torch.long)
        hidden = network.model(input_ids=ids, use_cache=False).last_hidden_state
        logits = network.lm_head(hidden[0, task["prompt_tokens"] - 1:-1])
        return torch.nn.functional.cross_entropy(logits,
            ids[0, task["prompt_tokens"]:], reduction="none")

    for objective in OBJECTIVES:
        started, cpu_started = time.perf_counter(), time.process_time()
        torch.manual_seed(args.seed)
        model = AutoModelForCausalLM.from_pretrained(args.model, local_files_only=True,
            torch_dtype=torch.float32, attn_implementation="sdpa")
        parameters = install_lora(model, rank=args.rank, seed=args.seed)
        initial = {name: value.detach().clone() for name, value in parameters.items()}
        optimizer = torch.optim.AdamW(list(parameters.values()), lr=args.learning_rate,
                                     weight_decay=0.0)
        model.train()
        folder = args.output / objective
        folder.mkdir(parents=True)
        steps = []

        for step, batch in enumerate(batches):
            optimizer.zero_grad(set_to_none=True)
            denominator = sum(examples[i]["chosen"]["response_tokens"] for i in batch)
            auxiliary_count = sum(examples[i]["auxiliary"] is not None for i in batch)
            totals = {"loss": 0.0, "sft_loss": 0.0, "preference_loss": 0.0, "auxiliary_loss": 0.0}
            for index in batch:
                example = examples[index]
                chosen = losses(model, example["chosen"])
                rejected = [losses(model, task).mean() for task in example["rejected"]]
                auxiliary = (losses(model, example["auxiliary"]).mean()
                             if example["auxiliary"] is not None else chosen.mean() * 0)
                sft = chosen.sum() / denominator
                preference = preference_loss(chosen.mean(), rejected) / len(batch)
                consequence = auxiliary / max(auxiliary_count, 1)
                total = (sft + (0 if objective == "imitation" else args.preference_weight)
                         * preference
                         + (args.consequence_weight if objective == "relation_consequence" else 0)
                         * consequence)
                total.backward()
                for key, value in (("loss", total), ("sft_loss", sft),
                                   ("preference_loss", preference),
                                   ("auxiliary_loss", consequence)):
                    totals[key] += float(value.detach())
                del chosen, rejected, auxiliary, sft, preference, consequence, total
            norm = torch.nn.utils.clip_grad_norm_(list(parameters.values()), 1.0)
            optimizer.step()
            receipt = {"step": step + 1, "example_ids": [examples[i]["id"] for i in batch],
                       **totals, "gradient_norm_before_clip": float(norm),
                       "wall_seconds": time.perf_counter() - started,
                       "cpu_seconds": time.process_time() - cpu_started}
            steps.append(receipt)
            (folder / "progress.json").write_text(json.dumps({"status": "RUNNING", "steps": steps},
                                                            indent=2) + "\n")
            print(json.dumps({"objective": objective, **receipt}), flush=True)
        saved = {name: value.detach().contiguous() for name, value in parameters.items()}
        save_file(saved, str(folder / "adapter.safetensors"))
        result = {"status": "COMPLETED", "objective": objective, "optimizer_steps": len(steps),
            "trainable_parameters": sum(p.numel() for p in parameters.values()),
            "parameter_l1_change": sum(float((saved[k] - initial[k]).abs().sum()) for k in saved),
            "wall_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu_started,
            "process_peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            "model_http_calls": 0, "semantic_bank_writes": 0, "steps": steps}
        (folder / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        del model, parameters, initial, optimizer, saved
        gc.collect()
    (args.output / "terminal.json").write_text(json.dumps({"status": "COMPLETED",
        "objectives": list(OBJECTIVES), "evaluation": "not yet run"}, indent=2) + "\n")


if __name__ == "__main__":
    main()
