"""Shared local finite-choice inference; no generation or new model service."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any


class NativeDecision:
    def __init__(self, checkpoint: Path, max_len: int, head_max_len: int) -> None:
        import torch  # type: ignore[import-not-found]
        from laya.train import load_checkpoint  # type: ignore[import-not-found]

        self.model, self.tokenizer, self.config = load_checkpoint(str(checkpoint))
        self.device = torch.device("cpu")
        self.model.to(self.device).eval()
        self.max_len, self.head_max_len = max_len, head_max_len
        self.counters = dict(forwards=0, sequence_rows=0, input_tokens=0,
                             state_tokenizations=0, state_tokens=0)

    def predict(self, payload: dict[str, Any]) -> dict[str, Any]:
        import torch
        from laya.common import (  # type: ignore[import-not-found]
            build_head,
            build_sequence,
            collate_items,
            encode_text,
            serialize_state,
        )
        from laya.train import (
            _forward,
            encode_item,
            make_item,
            to_internal,
        )

        started, cpu = time.perf_counter(), time.process_time()
        question = to_internal("next", payload["questions"]["next"])
        state_ids = encode_text(self.tokenizer, serialize_state(payload["state"]).replace(
            self.tokenizer.mask_token, " "), add_special_tokens=False)["input_ids"]
        self.counters["state_tokenizations"] += 1
        self.counters["state_tokens"] += len(state_ids)
        _, _, stats = build_sequence(self.tokenizer, payload["state"], question,
            max_len=self.max_len, head_max_len=self.head_max_len, state_ids=state_ids,
            return_truncation_stats=True)
        head = build_head(self.tokenizer, question, self.head_max_len)[0]
        full_head = build_head(self.tokenizer, question, 100000)[0]
        if stats["truncated"] or head != full_head:
            raise ValueError("Finite decision input exceeds declared complete-input capacity")
        keys = list(question["crit"])
        # Dummy targets satisfy the batch format; _forward receives no target tensor.
        item, reason = make_item(self.tokenizer, question, [1 / len(keys)] * len(keys),
                                 state_ids, self.head_max_len, self.max_len)
        if reason:
            raise ValueError(f"Unencodable decision: {reason}")
        batch = collate_items([[encode_item(self.tokenizer, item, self.max_len,
                                            self.head_max_len)]], self.tokenizer.pad_token_id)
        preparation_seconds = time.perf_counter() - started
        inference_started = time.perf_counter()
        with torch.no_grad():
            logits = _forward(self.model, batch, self.device, False, False)[0, :len(keys)]
            probabilities = torch.softmax(logits, dim=-1).tolist()
        inference_seconds = time.perf_counter() - inference_started
        self.counters["forwards"] += 1
        self.counters["sequence_rows"] += 1
        self.counters["input_tokens"] += int(batch["attention_mask"].sum())
        return {"choice": keys[max(range(len(keys)), key=lambda i: probabilities[i])],
                "logits": dict(zip(keys, logits.float().tolist(), strict=True)),
                "probabilities": dict(zip(keys, probabilities, strict=True)),
                "input_tokens": int(batch["attention_mask"].sum()), "truncated": False,
                "preparation_seconds": preparation_seconds,
                "inference_seconds": inference_seconds,
                "wall_seconds": time.perf_counter() - started,
                "cpu_seconds": time.process_time() - cpu, "calibrated": False}

