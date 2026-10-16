"""Simple decoder baseline: read action-letter logits, optionally train a LoRA.

The model sees the same visible state and action descriptions. It never generates
an answer or sees evaluator metadata. Conditional action probabilities and the
unconditional probability mass assigned to the allowed letters are both saved.
"""

from __future__ import annotations

import json
import string
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def encode_decision(payload: dict, tokenizer: Any, max_len: int) -> dict:
    question = payload["questions"]["next"]
    keys = list(question["criteria"])
    letters = string.ascii_uppercase[:len(keys)]
    if len(keys) > len(letters):
        raise ValueError("Letter decision supports at most26 actions")
    choices = [{"letter": letter, "action": key, "meaning": question["criteria"][key]}
               for letter, key in zip(letters, keys, strict=True)]
    messages = [{"role": "system", "content": question["instructions"]
                 + " Return only the selected option letter."},
                {"role": "user", "content": json.dumps(
                    {"state": payload["state"], "options": choices}, ensure_ascii=False)}]
    ids = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
    encoded_letters = [tokenizer.encode(letter, add_special_tokens=False) for letter in letters]
    if any(len(item) != 1 for item in encoded_letters):
        raise ValueError("Action letters must have one tokenizer token each")
    if len(ids) > max_len:
        raise ValueError("Complete decoder decision exceeds declared capacity")
    return {"input_ids": ids, "keys": keys, "letter_ids": [item[0] for item in encoded_letters]}


def collate_decisions(encoded: list[dict], pad_id: int, device: Any) -> dict:
    import torch

    width = max(len(row["input_ids"]) for row in encoded)
    ids = torch.full((len(encoded), width), pad_id, dtype=torch.long)
    mask = torch.zeros_like(ids)
    for index, row in enumerate(encoded):
        length = len(row["input_ids"])
        ids[index, -length:] = torch.tensor(row["input_ids"])
        mask[index, -length:] = 1
    positions = (mask.cumsum(-1) - 1).clamp_min(0)
    return {"input_ids": ids.to(device), "attention_mask": mask.to(device),
            "position_ids": positions.to(device)}


class LogitsDecision:
    def __init__(self, base: Path, max_len: int = 8192, *, adapter: Path | None = None,
                 train_lora: bool = False) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.base = base.resolve()
        self.max_len = max_len
        self.tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            base, local_files_only=True, torch_dtype=torch.float32, attn_implementation="sdpa")
        self.model.config.use_cache = False
        if adapter is not None:
            from peft import PeftModel

            self.model = PeftModel.from_pretrained(self.model, adapter, local_files_only=True)
        elif train_lora:
            from peft import LoraConfig, get_peft_model

            self.model = get_peft_model(self.model, LoraConfig(
                task_type="CAUSAL_LM", r=8, lora_alpha=16, lora_dropout=0.0, bias="none",
                target_modules=["q_proj", "k_proj", "v_proj", "o_proj"]))
        self.model.eval()
        self.device = torch.device("cpu")
        self.counters = dict(forwards=0, sequence_rows=0, input_tokens=0,
                             chat_tokenizations=0, letter_tokenizations=0)

    @classmethod
    def load(cls, checkpoint: Path) -> LogitsDecision:
        config = read_json(checkpoint / "reader_config.json")
        return cls(Path(config["base"]), config["max_len"], adapter=checkpoint)

    def save(self, path: Path) -> None:
        self.model.save_pretrained(path, safe_serialization=True)
        self.tokenizer.save_pretrained(path / "tokenizer")
        write_json(path / "reader_config.json", {"base": str(self.base), "max_len": self.max_len,
                   "architecture": "next_token_letter_logits_lora", "r": 8, "alpha": 16,
                   "calibrated": False,
                   "loss": "soft cross-entropy over full next-token vocabulary"})

    def predict(self, payload: dict) -> dict:
        import torch

        start, cpu = time.perf_counter(), time.process_time()
        encoded = encode_decision(payload, self.tokenizer, self.max_len)
        batch = collate_decisions([encoded], self.tokenizer.pad_token_id, self.device)
        with torch.no_grad():
            full = self.model(**batch, use_cache=False, logits_to_keep=1,
                              return_dict=False)[0][0, -1].float()
            logits = full[encoded["letter_ids"]]
            values = torch.softmax(logits, -1).tolist()
            option_mass = torch.exp(torch.logsumexp(logits, 0) - torch.logsumexp(full, 0)).item()
        probabilities = dict(zip(encoded["keys"], values, strict=True))
        self.counters["forwards"] += 1
        self.counters["sequence_rows"] += 1
        self.counters["input_tokens"] += len(encoded["input_ids"])
        self.counters["chat_tokenizations"] += 1
        self.counters["letter_tokenizations"] += len(encoded["letter_ids"])
        return {"choice": max(probabilities, key=probabilities.get), "probabilities": probabilities,
                "logits": dict(zip(encoded["keys"], logits.tolist(), strict=True)),
                "option_probability_mass": option_mass, "input_tokens": len(encoded["input_ids"]),
                "generated_tokens": 0, "calibrated": False,
                "wall_seconds": time.perf_counter() - start,
                "cpu_seconds": time.process_time() - cpu}
