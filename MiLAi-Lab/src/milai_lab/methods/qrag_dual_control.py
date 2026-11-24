"""Trainable Q-RAG double-Q dual tower and separate future-cost prediction for MiLAi."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import torch
from torch import Tensor, nn
from torch.nn import functional as F
from transformers import AutoModel, AutoTokenizer

from milai_lab.methods.control_numeric import ACTION_FIELDS, MATERIAL_UNIT, numeric_rows
from milai_lab.methods.control_observation import control_input
from milai_lab.methods.control_state_text import candidate_preview, compact, evidence_text


def td_lambda(reward: Tensor, next_values: Tensor, terminal: Tensor, coefficient: float) -> Tensor:
    """Finite, undiscounted lambda-return for one trajectory or a real bootstrapped segment."""
    if (
        not 0 <= coefficient <= 1
        or reward.shape != next_values.shape
        or reward.shape != terminal.shape
        or reward.ndim != 1
        or not reward.numel()
    ):
        raise ValueError("Expected aligned nonempty trajectory vectors")
    targets = torch.empty_like(reward)
    following = next_values[-1]
    for i in reversed(range(len(reward))):
        following = reward[i] + (~terminal[i]).to(reward.dtype) * (
            coefficient * following + (1 - coefficient) * next_values[i]
        )
        targets[i] = following
    return targets


class Tower(nn.Module):
    def __init__(self, backbone):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(
            backbone, local_files_only=True, trust_remote_code=True, torch_dtype=torch.float32
        )
        self.projection = nn.Linear(self.encoder.config.hidden_size, 384)

    def forward(self, batch):
        pooled = self.encoder(**batch).last_hidden_state[:, 0]
        return self.projection(pooled)


class QragDualControl(nn.Module):
    def __init__(self, backbone: Path, *, device: str, cost_scale: float, seq_len: int = 2048):
        super().__init__()
        self.backbone, self.cost_scale, self.seq_len = str(backbone), cost_scale, seq_len
        self.tokenizer = AutoTokenizer.from_pretrained(backbone, local_files_only=True)
        self.state_tower = Tower(backbone)
        self.action_tower = Tower(backbone)
        self.future_cost = nn.Sequential(
            nn.Linear(384 + len(ACTION_FIELDS) * 2, 64), nn.GELU(), nn.Linear(64, 1)
        )
        self.counters = Counter(input_tokens=0, padded_tokens=0, forwards=0, forward_gpu_ms=0.0)
        self.to(device)

    @property
    def device(self):
        return self.state_tower.projection.weight.device

    def encode_batch(self, sequences):
        batch = self.tokenizer.pad({"input_ids": sequences}, return_tensors="pt").to(self.device)
        self.counters["input_tokens"] += sum(map(len, sequences))
        self.counters["padded_tokens"] += batch.input_ids.numel()
        self.counters["forwards"] += 1
        return batch

    def ids(self, fields):
        usable = self.seq_len - self.tokenizer.num_special_tokens_to_add(pair=False)
        ids, caps = [], []
        for label, value, share in fields:
            piece = self.tokenizer.encode(
                label + "\n" + compact(value),
                add_special_tokens=False,
                max_length=usable,
                truncation=True,
            )
            ids.append(piece)
            caps.append(min(len(piece), usable * share // 100))
        remaining = usable - sum(caps)
        for i, piece in enumerate(ids):
            extra = min(remaining, len(piece) - caps[i])
            caps[i] += extra
            remaining -= extra
        joined = [v for piece, count in zip(ids, caps, strict=True) for v in piece[:count]]
        return self.tokenizer.build_inputs_with_special_tokens(joined)

    def scores(self, online, *, selected: int | None = None):
        obs = online["observation"]
        candidates = {r["item_index"]: r for r in obs["pending_candidates"]}
        nav = obs.get("navigation_upgrades", {})
        _, numeric = numeric_rows(online)
        previews, action_sequences, immediate = [], [], []
        features = []
        for i, action in enumerate(online["actions"]):
            index = action["parameters"].get("index")
            preview = candidate_preview(
                candidates.get(index, {}), nav.get(index, nav.get(str(index), {}))
            )
            previews.append(preview)
            if selected is not None and selected != i:
                continue
            features.append(numeric[i])
            params = action["parameters"]
            tier = "HANDOFF" if index is None else "R3" if params.get("expand_context") else "R2"
            action_sequences.append(
                self.ids(
                    [
                        ("Operation", (tier, params), 15),
                        ("Preview", preview, 65),
                        ("Public costs", numeric[i], 20),
                    ]
                )
            )
            immediate.append(
                numeric[i][ACTION_FIELDS.index("incremental_tokens")]
                * MATERIAL_UNIT
                / self.cost_scale
            )
        state = self.ids(
            [
                ("Task", obs["task"], 20),
                ("Budget", obs["budget"], 9),
                ("Acquired only", evidence_text(obs.get("observed_evidence") or []), 20),
                ("Delivered", evidence_text(obs["visible_evidence"]), 32),
                ("History", [obs.get("action_history"), obs["last_result"]], 9),
                ("Candidate menu", previews, 10),
            ]
        )
        start = end = None
        if self.device.type == "cuda" and not self.training:
            start, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
            start.record()
        with torch.autocast(
            self.device.type, enabled=self.device.type == "cuda", dtype=torch.bfloat16
        ):
            s = self.state_tower(self.encode_batch([state]))
            a = self.action_tower(self.encode_batch(action_sequences))
            # Normalize the projection to keep the low-temperature PQN bootstrap well scaled.
            product = F.normalize(s.float(), dim=-1) * F.normalize(a.float(), dim=-1)
            halves = torch.stack([part.sum(dim=-1) for part in product.chunk(2, dim=-1)], -1)
            future = (
                F.softplus(self.future_cost(torch.cat((product, a.new_tensor(features)), -1)))
                .flatten()
                .float()
            )
        if start is not None:
            end.record()
            end.synchronize()
            self.counters["forward_gpu_ms"] += start.elapsed_time(end)
        return halves, future, future.new_tensor(immediate)

    def net(self, online, penalty):
        halves, future, immediate = self.scores(online)
        return halves.sum(-1) - penalty * (future + immediate)

    @classmethod
    def load(cls, directory, *, device):
        cfg = json.loads((directory / "controller.json").read_text())
        model = cls(**cfg, device=device)
        model.load_state_dict(
            torch.load(directory / "control.pt", weights_only=True, map_location="cpu", mmap=True)
        )
        return model.eval()


class QragPolicy:
    def __init__(self, model, penalty, *, alpha=0.005, seed=None):
        self.model, self.penalty, self.alpha = model, penalty, alpha
        self.generator = (
            None if seed is None else torch.Generator(device=model.device).manual_seed(seed)
        )

    @torch.inference_mode()
    def choose(self, state, actions):
        logits = self.model.net(control_input(state, actions), self.penalty)
        if self.generator is None:
            index = logits.argmax().item()
        else:
            top, indices = logits.topk(min(5, len(actions)))
            p = torch.softmax((top - top[0]) / self.alpha, dim=0)
            index = indices[p.multinomial(1, generator=self.generator)].item()
        return actions[index].id
