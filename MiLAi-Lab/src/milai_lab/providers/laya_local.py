"""Shared local finite-choice inference; no generation or new model service."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PreparedDecision:
    """SDK encoding tied to this tokenizer and capacity, reusable across model updates."""

    keys: tuple[str, ...]
    encoded: dict[str, Any]


class NativeDecision:
    def __init__(self, checkpoint: Path, max_len: int, head_max_len: int,
                 device: str = "cpu") -> None:
        import torch  # type: ignore[import-not-found]
        from laya.train import load_checkpoint  # type: ignore[import-not-found]

        self.model, self.tokenizer, self.config = load_checkpoint(str(checkpoint))
        self.device = torch.device(device)
        self.model.to(self.device).eval()
        self.max_len, self.head_max_len = max_len, head_max_len
        self.counters = dict(forwards=0, sequence_rows=0, input_tokens=0,
                             state_tokenizations=0, state_tokens=0, padded_input_tokens=0)

    def prepare_batch(self, payloads: list[dict[str, Any]]) -> list[PreparedDecision]:
        """Encode fixed inputs once, using the same SDK boundaries as single inference.

        Only state/questions are consumed. The caller owns this ordinary in-memory
        cache; no content digest, global registry or cached hidden states are used.
        """
        from laya.common import build_head, build_sequence, encode_text, serialize_state
        from laya.train import encode_item, make_item, to_internal

        prepared = []
        for payload in payloads:
            ((question_id, schema),) = payload["questions"].items()
            question = to_internal(question_id, schema)
            state_ids = encode_text(self.tokenizer, serialize_state(payload["state"]).replace(
                self.tokenizer.mask_token, " "), add_special_tokens=False)["input_ids"]
            self.counters["state_tokenizations"] += 1
            self.counters["state_tokens"] += len(state_ids)
            _, _, stats = build_sequence(
                self.tokenizer, payload["state"], question, max_len=self.max_len,
                head_max_len=self.head_max_len, state_ids=state_ids, return_truncation_stats=True)
            head = build_head(self.tokenizer, question, self.head_max_len)[0]
            if stats["truncated"] or head != build_head(self.tokenizer, question, 100000)[0]:
                raise ValueError("Finite decision input exceeds declared complete-input capacity")
            keys = tuple(question["crit"])
            item, reason = make_item(self.tokenizer, question, [1 / len(keys)] * len(keys),
                                    state_ids, self.head_max_len, self.max_len)
            if reason:
                raise ValueError(f"Unencodable decision: {reason}")
            prepared.append(PreparedDecision(keys, encode_item(
                self.tokenizer, item, self.max_len, self.head_max_len)))
        return prepared

    def predict_prepared(self, prepared: list[PreparedDecision], batch_size: int = 4,
                         *, length_bucketed: bool = True,
                         precision: str = "float32") -> list[dict[str, Any]]:
        """Batched fixed-input evaluation, restored to the caller's original order.

        Per-row durations are shares of measured batch durations, not independent
        latency measurements. Encoding time belongs to prepare_batch, separately.
        """
        import torch
        from laya.common import collate_items
        from laya.train import _forward

        if batch_size < 1 or precision not in {"float32", "bf16"}:
            raise ValueError("Positive batch size and float32/bf16 precision required")
        order = list(range(len(prepared)))
        if length_bucketed:
            order.sort(key=lambda i: len(prepared[i].encoded["ids"]))
        results: dict[int, dict[str, Any]] = {}
        self.model.eval()
        for start in range(0, len(order), batch_size):
            started, cpu = time.perf_counter(), time.process_time()
            indices = order[start:start + batch_size]
            batch = collate_items([[prepared[i].encoded] for i in indices],
                                  self.tokenizer.pad_token_id)
            preparation_seconds = time.perf_counter() - started
            inference_started = time.perf_counter()
            with torch.inference_mode(), torch.autocast(
                    self.device.type, dtype=torch.bfloat16, enabled=precision == "bf16"):
                logits = _forward(self.model, batch, self.device, False, False)
                # Padded menu slots must never enter a row's probability denominator.
                logits = logits.masked_fill(~batch["marker_mask"].to(self.device), -torch.inf)
                probabilities = torch.softmax(logits, dim=-1)
                scores = torch.stack((logits, probabilities)).cpu().tolist()
            inference_seconds = time.perf_counter() - inference_started
            wall_seconds, cpu_seconds = time.perf_counter() - started, time.process_time() - cpu
            self.counters["forwards"] += 1
            self.counters["sequence_rows"] += len(indices)
            self.counters["input_tokens"] += sum(len(prepared[i].encoded["ids"]) for i in indices)
            self.counters["padded_input_tokens"] += batch["input_ids"].numel()
            for slot, index in enumerate(indices):
                keys = prepared[index].keys
                row_logits, row_probs = (score[slot][:len(keys)] for score in scores)
                results[index] = {
                    "choice": keys[max(range(len(keys)), key=row_probs.__getitem__)],
                    "logits": dict(zip(keys, row_logits, strict=True)),
                    "probabilities": dict(zip(keys, row_probs, strict=True)),
                    "input_tokens": len(prepared[index].encoded["ids"]),
                    "truncated": False, "calibrated": False,
                    "preparation_seconds": preparation_seconds / len(indices),
                    "inference_seconds": inference_seconds / len(indices),
                    "wall_seconds": wall_seconds / len(indices),
                    "cpu_seconds": cpu_seconds / len(indices),
                    "timing_scope": "amortized_batch_excludes_cached_encoding",
                    "batch_rows": len(indices), "precision": precision,
                }
        return [results[i] for i in range(len(prepared))]

    def predict_batch(self, payloads: list[dict[str, Any]], batch_size: int = 4,
                      *, length_bucketed: bool = True,
                      precision: str = "float32") -> list[dict[str, Any]]:
        return self.predict_prepared(self.prepare_batch(payloads), batch_size,
                                     length_bucketed=length_bucketed, precision=precision)

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
        ((question_id, schema),) = payload["questions"].items()
        question = to_internal(question_id, schema)
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
        self.counters["padded_input_tokens"] += batch["input_ids"].numel()
        return {"choice": keys[max(range(len(keys)), key=lambda i: probabilities[i])],
                "logits": dict(zip(keys, logits.float().tolist(), strict=True)),
                "probabilities": dict(zip(keys, probabilities, strict=True)),
                "input_tokens": int(batch["attention_mask"].sum()), "truncated": False,
                "preparation_seconds": preparation_seconds,
                "inference_seconds": inference_seconds,
                "wall_seconds": time.perf_counter() - started,
                "cpu_seconds": time.process_time() - cpu, "calibrated": False}

