"""Greedy local CPU generations on predeclared, common source inputs."""

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
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--guided-json", action="store_true",
                        help="Use each native request's existing JSON schema during decoding.")
    parser.add_argument("--objectives", nargs="+",
                        choices=("base", "imitation", "quality_weighted", "relation_consequence"))
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
    batch_size = args.batch_size or len(rows)
    args.output.mkdir(parents=True, exist_ok=True)
    grammars = None
    if args.guided_json:
        import importlib.metadata

        import xgrammar as xgr  # type: ignore[import-not-found]
        from xgrammar.contrib.hf import LogitsProcessor  # type: ignore[import-not-found]

        grammar_started = time.perf_counter()
        model_config = json.loads((args.model / "config.json").read_text())
        generation_config = json.loads((args.model / "generation_config.json").read_text())
        info = xgr.TokenizerInfo.from_huggingface(
            tokenizer, vocab_size=model_config["vocab_size"],
            stop_token_ids=generation_config["eos_token_id"])
        compiler = xgr.GrammarCompiler(info, max_threads=args.threads)
        grammars = [compiler.compile_json_schema(
            json.loads(row["messages"][1]["content"])["response_schema"]) for row in rows]
        (args.output.parent / "grammar-preparation.json").write_text(json.dumps({
            "xgrammar": importlib.metadata.version("xgrammar"), "schemas": len(grammars),
            "wall_seconds": time.perf_counter() - grammar_started,
            "scope": "Existing request schemas only; empty valid deltas remain allowed. "
                     "Grammar does not verify semantic coverage, attribution or consequences.",
        }, indent=2) + "\n")
    for objective in args.objectives or ["base", *protocol["objectives"]]:
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
        eos_ids = [eos] if isinstance(eos, int) else eos
        results = []
        padded_input_tokens, generation_batches = 0, 0
        for start in range(0, len(rows), batch_size):
            batch = tokenizer(prompts[start:start + batch_size], padding=True,
                              add_special_tokens=False, return_tensors="pt")
            prompt_tokens = batch["attention_mask"].sum(dim=1).tolist()
            padded_input_tokens += batch["input_ids"].numel()
            generation_batches += 1
            processors = ([LogitsProcessor(grammars[start:start + batch_size])]
                          if grammars is not None else None)
            with torch.no_grad():
                outputs = model.generate(**batch, generation_config=generation,
                                         logits_processor=processors)
            for index, row in enumerate(rows[start:start + batch_size]):
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
            print(json.dumps({"objective": objective, "completed_cases": len(results),
                              "generation_batches": generation_batches}), flush=True)
        result = {
            "status": "COMPLETED",
            "objective": objective,
            "device": "cpu",
            "sequences": results,
            "generation_batches": generation_batches,
            "model_http_requests": 0,
            "guided_json": args.guided_json,
            "padded_input_tokens": padded_input_tokens,
            "logical_prompt_tokens": sum(row["prompt_tokens"] for row in results),
            "completion_tokens_including_eos": sum(
                r["completion_tokens_including_eos"] for r in results
            ),
            "wall_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu_started,
            "process_peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            "scope": f"{len(rows)} predeclared author cases; unreviewed model "
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
