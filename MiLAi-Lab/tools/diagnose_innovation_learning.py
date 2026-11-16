"""Compare reference/no-change likelihoods on exposed training inputs, without updates.

Teacher-forced likelihood is an optimization diagnostic, not semantic accuracy.
The first divergent token compares alternatives under the same literal prefix;
whole-sequence sums/means have length effects and are reported separately.
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("training", type=Path)
    parser.add_argument("data", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    import torch  # type: ignore[import-not-found]
    from safetensors.torch import load_file  # type: ignore[import-untyped]
    from transformers import AutoModelForCausalLM, AutoTokenizer

    protocol = json.loads((args.training / "protocol.json").read_text())
    rows = [json.loads(line) for line in args.data.read_text().splitlines() if line.strip()]
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    empty_text, _ = render_target({"creates": [], "changes": {}})
    empty = [*tokenizer.encode(empty_text, add_special_tokens=False), tokenizer.eos_token_id]
    args.output.mkdir(parents=True, exist_ok=True)
    prepared = []
    for row in rows:
        prompt = tokenizer.apply_chat_template(
            row["messages"], tokenize=False, add_generation_prompt=True
        )
        target_text, _ = render_target(row["target"])
        target = [*tokenizer.encode(target_text, add_special_tokens=False), tokenizer.eos_token_id]
        divergence = next((i for i, (a, b) in enumerate(zip(target, empty, strict=False))
                           if a != b), None)
        prepared.append((row["example_id"], tokenizer.encode(prompt, add_special_tokens=False),
                         target, divergence))
    for objective in ["base", *protocol["objectives"]]:
        started, cpu_started = time.perf_counter(), time.process_time()
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
        results = []
        input_tokens, response_tokens = 0, 0
        for example_id, prompt, target, divergence in prepared:
            record = {"example_id": example_id, "reference_is_no_change": target == empty}
            for name, candidate in (("reference", target), ("no_change", empty)):
                ids = torch.tensor([[*prompt, *candidate]], dtype=torch.long)
                with torch.no_grad():
                    hidden = model.model(input_ids=ids, use_cache=False).last_hidden_state
                    logits = model.lm_head(hidden[0, len(prompt) - 1:-1]).float()
                    losses = torch.nn.functional.cross_entropy(
                        logits, torch.tensor(candidate), reduction="none"
                    )
                record[name] = {"tokens": len(candidate), "nll_sum": float(losses.sum()),
                                "nll_mean": float(losses.mean())}
                if name == "reference" and divergence is not None:
                    probs = logits[divergence].softmax(-1)
                    record["first_divergence"] = {
                        "target_position": divergence,
                        "reference_token": tokenizer.decode([target[divergence]]),
                        "no_change_token": tokenizer.decode([empty[divergence]]),
                        "reference_probability": float(probs[target[divergence]]),
                        "no_change_probability": float(probs[empty[divergence]]),
                        "top_token": tokenizer.decode([int(logits[divergence].argmax())]),
                    }
                input_tokens += len(prompt)
                response_tokens += len(candidate)
                del hidden, logits, losses
            results.append(record)
        output = {"status": "COMPLETED", "objective": objective, "examples": results,
                  "input_tokens": input_tokens, "response_tokens": response_tokens,
                  "wall_seconds": time.perf_counter() - started,
                  "cpu_seconds": time.process_time() - cpu_started,
                  "process_peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                  "model_http_requests": 0, "parameter_updates": 0,
                  "scope": "Exposed training main tasks only; teacher-forced reference vs empty "
                           "edit envelope. No semantic accuracy or generalization claim."}
        (args.output / f"{objective}.json").write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n"
        )
        print(json.dumps({key: value for key, value in output.items() if key != "examples"}),
              flush=True)
        del model, parameters
        gc.collect()


if __name__ == "__main__":
    main()
