"""CPU LoRA pilot with identical sequences, initialization and steps across objectives.

Uses local model files and writes adapters/receipts only. No model service or
experiment bank is modified. Run in an environment with Torch/Transformers.
"""

from __future__ import annotations

import argparse
import gc
import json
import platform
import resource
import time
from pathlib import Path
from typing import Any

OBJECTIVES = ("imitation", "quality_weighted", "relation_consequence")


def render_target(target: dict[str, Any]) -> tuple[str, list[tuple[int, int, str]]]:
    """JSON serialization with exact value spans, including Unicode source text."""
    parts: list[str] = []
    spans: list[tuple[int, int, str]] = []
    position = 0

    def add(text: str) -> None:
        nonlocal position
        parts.append(text)
        position += len(text)

    def render(value: Any, path: tuple[str, ...]) -> None:
        start = position
        if isinstance(value, dict):
            add("{")
            for i, (key, child) in enumerate(value.items()):
                if i:
                    add(",")
                add(json.dumps(key, ensure_ascii=False) + ":")
                render(child, (*path, key))
            add("}")
        elif isinstance(value, list):
            add("[")
            for i, child in enumerate(value):
                if i:
                    add(",")
                render(child, path)
            add("]")
        else:
            add(json.dumps(value, ensure_ascii=False))
        if path == ("consequences",):
            spans.append(
                (start, position, "consequence" if target["consequences"] else "empty_aux")
            )
        elif path and "rules" in path:
            spans.append((start, position, "relation"))
        elif path and path[-1] in {"text", "kind", "basis", "also", "applicability"}:
            spans.append((start, position, "quality"))

    render(target, ())
    return "".join(parts), spans


def token_weights(
    offsets: list[tuple[int, int]],
    spans: list[tuple[int, int, str]],
    objective: str,
) -> list[float]:
    weights = []
    for start, end in offsets:
        labels = {label for left, right, label in spans if left < end and start < right}
        if "empty_aux" in labels or (
            "consequence" in labels and objective != "relation_consequence"
        ):
            weight = 0.0
        elif "consequence" in labels:
            weight = 1.0
        elif "relation" in labels and objective == "relation_consequence":
            weight = 2.0
        elif "quality" in labels and objective != "imitation":
            weight = 2.0
        else:
            weight = 1.0
        weights.append(weight)
    return weights


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("data", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20261016)
    parser.add_argument("--rank", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=0.0005)
    parser.add_argument("--source-version", default="working-tree")
    args = parser.parse_args()
    import torch  # type: ignore[import-not-found]
    import transformers
    from safetensors.torch import save_file  # type: ignore[import-untyped]
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from innovation_lora import install_lora

    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    args.output.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in args.data.read_text().splitlines() if line.strip()]
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)

    def encode(row: dict[str, Any], *, auxiliary: bool = False) -> dict[str, Any]:
        prompt = tokenizer.apply_chat_template(
            row["messages"], tokenize=False, add_generation_prompt=True
        )
        prompt_ids = tokenizer.encode(prompt, add_special_tokens=False)
        target, spans = render_target(row["target"])
        encoded = tokenizer(target, add_special_tokens=False, return_offsets_mapping=True)
        ids = [*prompt_ids, *encoded["input_ids"], tokenizer.eos_token_id]
        weights = {
            objective: [0.0] * len(prompt_ids)
            + token_weights(encoded["offset_mapping"], spans, objective)
            + [1.0]
            for objective in OBJECTIVES
        }
        if auxiliary:
            weights = {
                objective: [0.0] * len(prompt_ids)
                + [1.0 if objective == "relation_consequence" else 0.0]
                * (len(encoded["input_ids"]) + 1)
                for objective in OBJECTIVES
            }
        return {
            "ids": ids,
            "weights": weights,
            "auxiliary": auxiliary,
            "prompt_tokens": len(prompt_ids),
            "target_tokens": len(encoded["input_ids"]),
        }

    examples = [
        {
            "id": row["example_id"],
            "tasks": [
                encode(row),
                *([encode(row["auxiliary"], auxiliary=True)] if "auxiliary" in row else []),
            ],
        }
        for row in rows
    ]
    order = list(range(len(examples))) * args.epochs
    permutation = torch.randperm(len(order), generator=torch.Generator().manual_seed(args.seed))
    order = [order[index] for index in permutation.tolist()]
    protocol = {
        "model_path": str(args.model),
        "model_source": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct",
        "device": "cpu",
        "dtype": "float32",
        "threads": args.threads,
        "seed": args.seed,
        "rank": args.rank,
        "alpha": 2 * args.rank,
        "learning_rate": args.learning_rate,
        "epochs": args.epochs,
        "examples": len(examples),
        "example_order": [examples[i]["id"] for i in order],
        "objectives": list(OBJECTIVES),
        "input_tokens_per_arm": sum(
            task["prompt_tokens"] for i in order for task in examples[i]["tasks"]
        ),
        "target_tokens_per_arm": sum(
            task["target_tokens"] for i in order for task in examples[i]["tasks"]
        ),
        "max_sequence_tokens": max(len(task["ids"]) for item in examples for task in item["tasks"]),
        "auxiliary_examples": sum(
            "auxiliary" in row or bool(row["target"].get("consequences")) for row in rows
        ),
        "matching": "Identical sequences, order, initialization, parameters and optimizer steps. "
        "Every response position is projected in every arm, including zero-weight auxiliary "
        "tokens. Only loss weights differ; each update normalized by its supervised weight sum.",
        "quality_proxy": "2x weights on text, kind, evidence aliases and applicability values; "
        "not a learned correctness reward or a preference optimization claim.",
        "relation_objective": "Quality weights plus 2x rule spans and nonempty consequence labels.",
        "scope": "Exposed author references; pipeline pilot, not a generalization result.",
        "data_formats": sorted({row.get("format", "wrapped") for row in rows}),
        "reference_authoring_cost": "Not independently metered; not zero.",
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "python": platform.python_version(),
        "source_version": args.source_version,
        "cpu_model": next(
            line.split(":", 1)[1].strip()
            for line in Path("/proc/cpuinfo").read_text().splitlines()
            if line.startswith("model name")
        ),
    }
    (args.output / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")

    for objective in OBJECTIVES:
        started, cpu_started = time.perf_counter(), time.process_time()
        torch.manual_seed(args.seed)
        model = AutoModelForCausalLM.from_pretrained(
            args.model, local_files_only=True, torch_dtype=torch.float32, attn_implementation="sdpa"
        )
        parameters = install_lora(model, rank=args.rank, seed=args.seed)
        model.train()
        initial = {name: value.detach().clone() for name, value in parameters.items()}
        optimizer = torch.optim.AdamW(
            list(parameters.values()), lr=args.learning_rate, weight_decay=0.0
        )
        folder = args.output / objective
        folder.mkdir(parents=True, exist_ok=True)
        steps = []
        for step, index in enumerate(order):
            example = examples[index]
            normalization = sum(sum(task["weights"][objective]) for task in example["tasks"])
            optimizer.zero_grad(set_to_none=True)
            loss_value, supervised, projected = 0.0, 0, 0
            for task in example["tasks"]:
                ids = torch.tensor([task["ids"]], dtype=torch.long)
                weight = torch.tensor(task["weights"][objective][1:], dtype=torch.float32)
                response_positions = torch.arange(len(task["ids"]) - 1) >= task["prompt_tokens"] - 1
                hidden = model.model(input_ids=ids, use_cache=False).last_hidden_state[0, :-1]
                logits = model.lm_head(hidden[response_positions])
                losses = torch.nn.functional.cross_entropy(
                    logits, ids[0, 1:][response_positions], reduction="none"
                )
                loss = (losses * weight[response_positions]).sum() / normalization
                loss.backward()
                loss_value += float(loss.detach())
                supervised += int((weight > 0).sum())
                projected += int(response_positions.sum())
                del hidden, logits, losses, loss
            gradient_norm = torch.nn.utils.clip_grad_norm_(list(parameters.values()), 1.0)
            optimizer.step()
            receipt = {
                "step": step + 1,
                "example_id": example["id"],
                "input_tokens": sum(task["prompt_tokens"] for task in example["tasks"]),
                "target_tokens": sum(task["target_tokens"] for task in example["tasks"]),
                "tasks": len(example["tasks"]),
                "projected_response_tokens": projected,
                "supervised_tokens": supervised,
                "loss": loss_value,
                "gradient_norm_before_clip": float(gradient_norm),
                "elapsed_seconds": time.perf_counter() - started,
                "cpu_seconds": time.process_time() - cpu_started,
            }
            steps.append(receipt)
            (folder / "progress.json").write_text(
                json.dumps({"status": "RUNNING", "objective": objective, "steps": steps}, indent=2)
                + "\n"
            )
            print(json.dumps({"objective": objective, **receipt}), flush=True)
        saved = {name: parameter.detach().contiguous() for name, parameter in parameters.items()}
        save_file(saved, str(folder / "adapter.safetensors"))
        result = {
            "status": "COMPLETED",
            "objective": objective,
            "steps": steps,
            "optimizer_steps": len(steps),
            "trainable_parameters": sum(p.numel() for p in parameters.values()),
            "parameter_l1_change": sum(
                float((saved[name] - initial[name]).abs().sum()) for name in saved
            ),
            "wall_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu_started,
            "process_peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            "model_http_requests": 0,
            "semantic_bank_writes": 0,
            "evaluation": "not yet run",
        }
        (folder / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        del model, optimizer, parameters, saved, initial
        gc.collect()
    (args.output / "terminal.json").write_text(
        json.dumps(
            {"status": "COMPLETED", "objectives": list(OBJECTIVES), "evaluation": "not yet run"},
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
