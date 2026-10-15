"""Greedy local CPU generations on the predeclared, common held-out source inputs."""

from __future__ import annotations

import argparse
import gc
import json
import resource
import time
from pathlib import Path

from innovation_lora import install_lora


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("training", type=Path)
    parser.add_argument("data", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    args = parser.parse_args()
    import torch  # type: ignore[import-not-found]
    from safetensors.torch import load_file  # type: ignore[import-untyped]
    from transformers import AutoModelForCausalLM, AutoTokenizer, GenerationConfig

    protocol = json.loads((args.training / "protocol.json").read_text())
    rows = [json.loads(line) for line in args.data.read_text().splitlines() if line.strip()]
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    tokenizer.padding_side = "left"
    prompts = [
        tokenizer.apply_chat_template(row["messages"], tokenize=False, add_generation_prompt=True)
        for row in rows
    ]
    batch = tokenizer(prompts, padding=True, add_special_tokens=False, return_tensors="pt")
    prompt_tokens = batch["attention_mask"].sum(dim=1).tolist()
    args.output.mkdir(parents=True, exist_ok=True)
    for objective in ["base", *protocol["objectives"]]:
        started, cpu_started = time.perf_counter(), time.process_time()
        torch.manual_seed(protocol["seed"])
        model = AutoModelForCausalLM.from_pretrained(
            args.model, local_files_only=True, torch_dtype=torch.float32, attn_implementation="sdpa"
        )
        parameters = install_lora(model, rank=protocol["rank"], seed=protocol["seed"])
        if objective != "base":
            saved = load_file(str(args.training / objective / "adapter.safetensors"))
            with torch.no_grad():
                for name, value in saved.items():
                    parameters[name].copy_(value)
        model.eval()
        eos = model.generation_config.eos_token_id
        generation = GenerationConfig(
            do_sample=False,
            max_new_tokens=args.max_new_tokens,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=eos,
            use_cache=True,
        )
        with torch.no_grad():
            outputs = model.generate(**batch, generation_config=generation)
        eos_ids = [eos] if isinstance(eos, int) else eos
        results = []
        for index, row in enumerate(rows):
            generated = outputs[index, batch["input_ids"].shape[1] :].tolist()
            stop = next(
                (i + 1 for i, token in enumerate(generated) if token in eos_ids), len(generated)
            )
            generated = generated[:stop]
            results.append(
                {
                    "example_id": row["example_id"],
                    "objective": objective,
                    "text": tokenizer.decode(generated, skip_special_tokens=True),
                    "prompt_tokens": prompt_tokens[index],
                    "completion_tokens_including_eos": stop,
                    "finish_reason": "stop" if generated[-1] in eos_ids else "length",
                }
            )
        result = {
            "status": "COMPLETED",
            "objective": objective,
            "device": "cpu",
            "sequences": results,
            "generation_batches": 1,
            "model_http_requests": 0,
            "padded_input_tokens": batch["input_ids"].numel(),
            "logical_prompt_tokens": sum(prompt_tokens),
            "completion_tokens_including_eos": sum(
                r["completion_tokens_including_eos"] for r in results
            ),
            "wall_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu_started,
            "process_peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            "scope": "Four predeclared author formation/composition cases; unreviewed model "
            "outputs, not semantic passes or an external benchmark score.",
        }
        (args.output / f"{objective}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        print(
            json.dumps({key: value for key, value in result.items() if key != "sequences"}),
            flush=True,
        )
        del model, parameters, outputs
        gc.collect()


if __name__ == "__main__":
    main()
