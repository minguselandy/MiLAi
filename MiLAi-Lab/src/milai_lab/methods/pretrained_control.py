"""Full-parameter GTE interaction controller for legal READ/upgrade/HANDOFF menus."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import torch
from torch import Tensor, nn
from torch.nn import functional as F
from torch.utils.checkpoint import checkpoint
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from milai_lab.methods.control_numeric import (
    ACTION_FIELDS,
    ACTION_WIDTH,
    MATERIAL_UNIT,
    numeric_rows,
)
from milai_lab.methods.control_observation import control_input
from milai_lab.methods.control_state_text import control_sequences
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState


class PretrainedControl(nn.Module):
    def __init__(
        self,
        backbone: Path,
        *,
        device: str = "cpu",
        limit: int = 2048,
        cost_scale: float = 2048.0,
        object_batch: int = 8,
        history: bool = True,
    ):
        super().__init__()
        if not (math.isfinite(cost_scale) and cost_scale > 0 and object_batch > 0):
            raise ValueError("Expected a positive cost scale and object microbatch")
        self.backbone = Path(backbone).resolve()
        self.cost_scale = cost_scale
        self.limit = limit
        self.object_batch = object_batch
        self.history = history
        self.tokenizer = AutoTokenizer.from_pretrained(str(self.backbone), local_files_only=True)
        self.reranker = AutoModelForSequenceClassification.from_pretrained(
            str(self.backbone),
            trust_remote_code=True,
            local_files_only=True,
            torch_dtype=torch.float32,
        )
        width = self.reranker.config.hidden_size
        self.heads = nn.ModuleList(
            nn.Sequential(
                nn.Linear(width + 1 + 3 + ACTION_WIDTH, 128), nn.GELU(), nn.Linear(128, 2)
            )
            for _ in range(4)
        )
        self.counters: Counter[str] = Counter()
        self.counters.update(input_tokens=0, padded_tokens=0, forwards=0, forward_gpu_ms=0.0)
        self.to(device)

    @property
    def device(self):
        return next(self.parameters()).device

    def _encode(self, ids, mask):
        pooled = self.reranker.base_model(input_ids=ids, attention_mask=mask).pooler_output
        relevance = self.reranker.classifier(self.reranker.dropout(pooled))
        return torch.cat([pooled, relevance], -1)

    def score(
        self, online: dict[str, Any], *, diagnostic_evidence: dict[str, Any] | None = None
    ) -> tuple[Tensor, Tensor]:
        sequences, owners, levels = control_sequences(
            self.tokenizer,
            online,
            self.limit,
            history=self.history,
            diagnostic_evidence=diagnostic_evidence,
        )
        _, features = numeric_rows(online)
        self.counters["input_tokens"] += sum(map(len, sequences))
        chunks = []
        start = end = None
        if not self.training and self.device.type == "cuda":
            start, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
            start.record(torch.cuda.current_stream(self.device))
        with torch.autocast(
            self.device.type, enabled=self.device.type == "cuda", dtype=torch.bfloat16
        ):
            i = 0
            while i < len(sequences):
                end_index = i + 1
                longest = len(sequences[i])
                while end_index < min(len(sequences), i + self.object_batch):
                    next_longest = max(longest, len(sequences[end_index]))
                    if next_longest * (end_index - i + 1) > 2 * self.limit:
                        break
                    end_index += 1
                    longest = next_longest
                batch = self.tokenizer.pad(
                    {"input_ids": sequences[i:end_index]}, return_tensors="pt"
                ).to(self.device)
                i = end_index
                ids, mask = batch["input_ids"], batch["attention_mask"]
                self.counters["padded_tokens"] += ids.numel()
                self.counters["forwards"] += 1
                chunks.append(
                    checkpoint(self._encode, ids, mask, use_reentrant=False)
                    if self.training
                    else self._encode(ids, mask)
                )
            vectors = torch.cat(chunks)[owners]
            level = F.one_hot(torch.tensor(levels, device=self.device), 3)
            head_inputs = torch.cat(
                [vectors, level.to(vectors), vectors.new_tensor(features)], dim=-1
            )
            raw = torch.stack([head(head_inputs) for head in self.heads], dim=1).float()
            result = raw[:, :, 0].sigmoid(), F.softplus(raw[:, :, 1])
        if start is not None:
            end.record(torch.cuda.current_stream(self.device))
            end.synchronize()
            self.counters["forward_gpu_ms"] += start.elapsed_time(end)
        return result

    def net_values(self, online: dict[str, Any], utility_lambda: float) -> Tensor:
        quality, future = self.score(online)
        return self.net_from_scores(online, quality, future, utility_lambda)

    def net_from_scores(
        self, online, quality: Tensor, future: Tensor, utility_lambda: float
    ) -> Tensor:
        if not utility_lambda:
            return quality
        _, features = numeric_rows(online)
        i = ACTION_FIELDS.index("incremental_tokens")
        exact = ACTION_FIELDS.index("cost_exact")
        immediate = []
        for row, action in zip(features, online["actions"], strict=True):
            if action["kind"] == "HANDOFF":
                immediate.append(0.0)
            elif row[i + len(ACTION_FIELDS)] and row[exact]:
                immediate.append(row[i] * MATERIAL_UNIT / self.cost_scale)
            else:
                raise ValueError("Cost-aware policy requires exact Host READ preflight")
        return quality - utility_lambda * (future + future.new_tensor(immediate)[:, None])

    def save(self, directory: Path, *, completion=None):
        directory.parent.mkdir(parents=True, exist_ok=True)
        if directory.exists():
            raise FileExistsError(directory)
        with TemporaryDirectory(prefix=".checkpoint-", dir=directory.parent) as stage:
            pending = Path(stage) / "checkpoint"
            pending.mkdir()
            torch.save(self.state_dict(), pending / "control.pt")
            (pending / "controller.json").write_text(
                json.dumps(
                    {
                        "backbone": str(self.backbone),
                        "limit": self.limit,
                        "cost_scale": self.cost_scale,
                        "object_batch": self.object_batch,
                        "history": self.history,
                    }
                )
            )
            if completion is not None:
                (pending / "fit_completion.json").write_text(
                    json.dumps(completion, allow_nan=False)
                )
            pending.rename(directory)

    @classmethod
    def load(cls, directory: Path, *, device: str):
        config = json.loads((directory / "controller.json").read_text())
        config.setdefault("history", False)
        model = cls(**config, device=device)
        model.load_state_dict(
            torch.load(directory / "control.pt", map_location="cpu", weights_only=True, mmap=True)
        )
        return model.eval()


class PretrainedPolicy:
    def __init__(self, model: PretrainedControl, utility_lambda: float):
        if not math.isfinite(utility_lambda) or utility_lambda < 0:
            raise ValueError("Expected a finite nonnegative cost penalty")
        self.model, self.utility_lambda = model, utility_lambda

    @torch.inference_mode()
    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        values = self.model.net_values(control_input(state, actions), self.utility_lambda)
        return actions[values.mean(dim=1).argmax().item()].id


class NativeRelevancePolicy:
    """Frozen original GTE relevance logits on a task and the legal candidate preview."""

    def __init__(self, model: PretrainedControl):
        self.model = model

    @torch.inference_mode()
    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        from milai_lab.methods.control_state_text import candidate_preview

        online = control_input(state, actions)
        obs = online["observation"]
        by_index = {x["item_index"]: x for x in obs["pending_candidates"]}
        nav = obs.get("navigation_upgrades") or {}
        seen = {}
        for action in actions:
            if action.kind == "READ":
                index = action.parameters["index"]
                seen.setdefault(
                    index,
                    (
                        action.id,
                        candidate_preview(
                            by_index.get(index, {}), nav.get(index, nav.get(str(index), {}))
                        ),
                    ),
                )
        if not seen:
            return next(a.id for a in actions if a.kind == "HANDOFF")
        options = list(seen.values())
        question = obs["task"]["request"]
        logits = []
        with torch.autocast(
            self.model.device.type, enabled=self.model.device.type == "cuda", dtype=torch.bfloat16
        ):
            for i in range(0, len(options), self.model.object_batch):
                docs = [doc for _, doc in options[i : i + self.model.object_batch]]
                batch = self.model.tokenizer(
                    [question] * len(docs),
                    docs,
                    truncation=True,
                    max_length=self.model.limit,
                    padding=True,
                    return_tensors="pt",
                ).to(self.model.device)
                if self.model.device.type == "cuda":
                    start, end = (
                        torch.cuda.Event(enable_timing=True),
                        torch.cuda.Event(enable_timing=True),
                    )
                    start.record(torch.cuda.current_stream(self.model.device))
                values = self.model.reranker(**batch).logits[:, 0]
                if self.model.device.type == "cuda":
                    end.record(torch.cuda.current_stream(self.model.device))
                    end.synchronize()
                    self.model.counters["forward_gpu_ms"] += start.elapsed_time(end)
                logits.extend(values.tolist())
                self.model.counters["input_tokens"] += batch.attention_mask.sum().item()
                self.model.counters["padded_tokens"] += batch.input_ids.numel()
                self.model.counters["forwards"] += 1
        return options[max(range(len(options)), key=logits.__getitem__)][0]
