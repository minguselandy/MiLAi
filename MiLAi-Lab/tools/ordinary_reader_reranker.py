"""Ordinary CLS cross-encoder over the same visible state and finite actions.

Each action gets one independent encoder sequence and a scalar linear score.
There is no typed decision head. The encoder starts from the identical base
Laya encoder weights; differences in processed rows and tokens remain visible.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any


def encode_actions(payload: dict[str, Any], tokenizer: Any, max_len: int = 4096) -> dict:
    from laya.common import serialize_state

    question = payload["questions"]["next"]
    state = tokenizer.encode(serialize_state(payload["state"]), add_special_tokens=False)
    keys = list(question["criteria"])
    sequences = []
    for key in keys:
        head = tokenizer.encode(question["instructions"] + "\nCandidate action: " + key + ": "
                                + question["criteria"][key], add_special_tokens=False)
        ids = [tokenizer.cls_token_id, *head, tokenizer.sep_token_id,
               *state, tokenizer.sep_token_id]
        if len(ids) > max_len:
            raise ValueError("Ordinary cross-encoder input exceeds complete-input capacity")
        sequences.append(ids)
    return {"keys": keys, "sequences": sequences,
            "state_tokenizations": 1, "action_tokenizations": len(keys),
            "state_tokens": len(state), "input_tokens": sum(map(len, sequences))}


def collate(encoded: dict, pad_id: int, device: Any) -> dict:
    import torch

    sequences = encoded["sequences"]
    ids = torch.full((len(sequences), max(map(len, sequences))), pad_id, dtype=torch.long)
    mask = torch.zeros_like(ids)
    for index, sequence in enumerate(sequences):
        ids[index, :len(sequence)] = torch.tensor(sequence)
        mask[index, :len(sequence)] = 1
    return {"input_ids": ids.to(device), "attention_mask": mask.to(device)}


def build_model(encoder: Any) -> Any:
    import torch

    class CrossEncoder(torch.nn.Module):
        def __init__(self, backbone: Any) -> None:
            super().__init__()
            self.encoder = backbone
            self.scorer = torch.nn.Linear(backbone.config.hidden_size, 1)

        def forward(self, input_ids: Any, attention_mask: Any) -> Any:
            output = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
            return self.scorer(output.last_hidden_state[:, 0]).squeeze(-1)

    return CrossEncoder(encoder)


def save_model(model: Any, tokenizer: Any, path: Path) -> None:
    from safetensors.torch import save_file

    path.mkdir(parents=True, exist_ok=True)
    # Match native Laya checkpoint storage precision; inference reloads in fp32.
    encoder_weights = {key: value.detach().half().cpu().contiguous()
                       for key, value in model.encoder.state_dict().items()}
    model.encoder.save_pretrained(path / "encoder", safe_serialization=True,
                                 state_dict=encoder_weights)
    tokenizer.save_pretrained(path / "tokenizer")
    weights = {key: value.detach().half().cpu().contiguous()
               for key, value in model.scorer.state_dict().items()}
    save_file(weights, str(path / "scorer.safetensors"))


class OrdinaryDecision:
    def __init__(self, model: Any, tokenizer: Any, device: Any) -> None:
        self.model, self.tokenizer, self.device = model, tokenizer, device
        self.counters = dict(forwards=0, sequence_rows=0, input_tokens=0,
                             state_tokenizations=0, action_tokenizations=0)

    @classmethod
    def load(cls, checkpoint: Path, device: Any) -> OrdinaryDecision:
        from safetensors.torch import load_file
        from transformers import AutoModel, AutoTokenizer

        encoder = AutoModel.from_pretrained(checkpoint / "encoder", local_files_only=True)
        encoder.config.reference_compile = False
        model = build_model(encoder)
        model.scorer.load_state_dict(load_file(str(checkpoint / "scorer.safetensors")))
        model.to(device).eval()
        return cls(model, AutoTokenizer.from_pretrained(checkpoint / "tokenizer",
                                                        local_files_only=True), device)

    def predict(self, payload: dict[str, Any]) -> dict[str, Any]:
        import torch

        start, cpu = time.perf_counter(), time.process_time()
        encoded = encode_actions(payload, self.tokenizer)
        batch = collate(encoded, self.tokenizer.pad_token_id, self.device)
        with torch.no_grad():
            probabilities = torch.softmax(self.model(**batch), -1).tolist()
        self.counters["forwards"] += 1
        self.counters["sequence_rows"] += len(encoded["keys"])
        for key in ("input_tokens", "state_tokenizations", "action_tokenizations"):
            self.counters[key] += encoded[key]
        probabilities = dict(zip(encoded["keys"], probabilities, strict=True))
        return {"choice": max(probabilities, key=probabilities.get),
                "probabilities": probabilities, "input_tokens": encoded["input_tokens"],
                "sequence_rows": len(encoded["keys"]), "calibrated": False,
                "wall_seconds": time.perf_counter() - start,
                "cpu_seconds": time.process_time() - cpu}
