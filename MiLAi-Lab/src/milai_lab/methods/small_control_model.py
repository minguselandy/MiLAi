"""Frozen embeddings, tunable encoders and decoder hidden-state scoring, without generation.

All routes use legal observations and the same head family. The dual readout
pools bounded chunks without dropping tokens. The joint decoder shares literal
content and reads all binding markers in one forward, rejecting over-capacity
inputs explicitly. Neither layout certifies semantic sufficiency.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from milai_lab.methods.control_observation import control_texts, joint_control_texts
from milai_lab.methods.small_memory_policy import PolicyScores


@dataclass
class SmallControlConfig:
    family: str
    backbone: str
    hidden_size: int = 256
    chunk_tokens: int = 512
    encode_batch_size: int = 16
    adaptation: str = "frozen"
    set_interaction: bool = False
    projection_version: str = "control-observation-v1"
    readout: str = "dual"
    joint_max_tokens: int = 8192
    joint_layout: str = "literal_json_v2"
    state_representation: str = "whole_v1"


def build_action_head(width: int, hidden: int, *, set_interaction: bool = False) -> Any:
    import torch  # type: ignore[import-not-found]

    class ActionHead(torch.nn.Module):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__()
            self.network = torch.nn.Sequential(
                torch.nn.Linear(width * (5 if set_interaction else 4), hidden),
                torch.nn.GELU(), torch.nn.Linear(hidden, 1))

        def forward(self, state: Any, actions: Any, owners: Any) -> Any:
            selected = state[owners]
            features = [selected, actions, selected * actions, selected - actions]
            if set_interaction:
                pooled = torch.zeros_like(state).index_add(0, owners, actions)
                counts = torch.bincount(owners, minlength=len(state)).clamp_min(1)
                features.append((pooled / counts[:, None])[owners])
            return self.network(torch.cat(features, dim=-1)).squeeze(-1)

    return ActionHead()


class SmallControlModel:
    def __init__(self, config: SmallControlConfig, *, device: str = "cpu") -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        if config.family not in {"frozen_mlp", "encoder", "decoder"}:
            raise ValueError("Unknown small control family")
        if config.adaptation not in {"frozen", "full", "lora"}:
            raise ValueError("Unknown backbone adaptation")
        if config.family == "frozen_mlp" and config.adaptation != "frozen":
            raise ValueError("M0 requires a frozen encoder")
        if config.projection_version != "control-observation-v1":
            raise ValueError("Use the model's original observation projection")
        if config.readout not in {"dual", "joint"}:
            raise ValueError("Unknown control readout")
        if config.readout == "joint" and config.family != "decoder":
            raise ValueError("Joint causal markers require the decoder route")
        if config.joint_layout not in {"literal_json_v2", "wrapped_json_v1"}:
            raise ValueError("Unknown joint input layout")
        if config.state_representation not in {"whole_v1", "query_residual_v1"}:
            raise ValueError("Unknown state representation")
        if config.readout == "joint" and config.state_representation != "whole_v1":
            raise ValueError("Query residual is a separate dual-encoder representation")
        self.config, self.device = config, torch.device(device)
        self.tokenizer = AutoTokenizer.from_pretrained(  # type: ignore[no-untyped-call]
            config.backbone, local_files_only=True)
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.encoder = AutoModel.from_pretrained(config.backbone, local_files_only=True)
        if config.adaptation == "lora":
            from peft import LoraConfig, get_peft_model  # type: ignore[import-not-found]

            # These modules are inspected for the decoder route; other backbones
            # must explicitly supply a suitable adaptation instead of silent matching.
            if not any(name.endswith("q_proj") for name, _ in self.encoder.named_modules()):
                raise ValueError("LoRA route requires inspected q_proj/v_proj modules")
            self.encoder = get_peft_model(self.encoder, LoraConfig(
                r=16, lora_alpha=32, lora_dropout=0.05,
                target_modules=["q_proj", "v_proj"], bias="none"))
        elif config.adaptation == "frozen":
            self.encoder.requires_grad_(False)
        if config.adaptation != "frozen":
            self.encoder.gradient_checkpointing_enable()
            if config.adaptation == "lora":
                self.encoder.enable_input_require_grads()
        self.encoder.to(self.device)
        width = self.encoder.config.hidden_size
        self.head = build_action_head(width, config.hidden_size,
                                      set_interaction=config.set_interaction).to(self.device)
        self.counters: dict[str, int] = dict(forwards=0, input_tokens=0, padded_tokens=0,
                                            texts=0, chunked_texts=0, chunks=0, joint_sequences=0)

    def parameters(self) -> list[Any]:
        return [p for module in (self.encoder, self.head)
                for p in module.parameters() if p.requires_grad]

    def train(self, mode: bool = True) -> None:
        self.encoder.train(mode and self.config.adaptation != "frozen")
        self.head.train(mode)

    def encode(self, texts: list[str]) -> Any:
        import torch
        import torch.nn.functional as F  # type: ignore[import-not-found]

        chunks, owners = [], []
        limit = self.config.chunk_tokens - self.tokenizer.num_special_tokens_to_add()
        if limit < 8:
            raise ValueError("Chunk capacity is too small")
        for owner, text in enumerate(texts):
            prefix = "query: " if self.config.family != "decoder" else ""
            ids = self.tokenizer.encode(prefix + text, add_special_tokens=False, verbose=False)
            self.counters["texts"] += 1
            self.counters["chunked_texts"] += int(len(ids) > limit)
            for start in range(0, max(1, len(ids)), limit):
                chunks.append({"input_ids": self.tokenizer.build_inputs_with_special_tokens(
                    ids[start:start + limit])})
                owners.append(owner)
        vectors = []
        for start in range(0, len(chunks), self.config.encode_batch_size):
            batch = self.tokenizer.pad(chunks[start:start + self.config.encode_batch_size],
                                       padding=True, return_tensors="pt").to(self.device)
            mask = batch["attention_mask"]
            self.counters["forwards"] += 1
            self.counters["input_tokens"] += int(mask.sum())
            self.counters["padded_tokens"] += mask.numel()
            self.counters["chunks"] += len(mask)
            with torch.set_grad_enabled(torch.is_grad_enabled()
                                        and self.config.adaptation != "frozen"), torch.autocast(
                    device_type=self.device.type, dtype=torch.bfloat16,
                    enabled=self.device.type == "cuda" and self.config.adaptation != "frozen"):
                output = self.encoder(**batch, **({"use_cache": False}
                    if self.config.family == "decoder" else {})).last_hidden_state
                if self.config.family == "decoder":
                    positions = torch.arange(mask.shape[1], device=self.device)[None, :]
                    last = (positions * mask).max(dim=1).values
                    pooled = output[torch.arange(len(mask), device=self.device), last]
                else:
                    pooled = (output * mask[..., None]).sum(1) / mask.sum(1)[:, None]
                vectors.append(F.normalize(pooled.float(), dim=-1))
        vectors_tensor = torch.cat(vectors)
        owner_tensor = torch.tensor(owners, device=self.device)
        summed = vectors_tensor.new_zeros((len(texts), vectors_tensor.shape[-1])).index_add(
            0, owner_tensor, vectors_tensor)
        counts = torch.bincount(owner_tensor, minlength=len(texts))[:, None]
        return F.normalize(summed / counts, dim=-1)

    def features(self, online: list[dict[str, Any]]) -> tuple[Any, Any, Any, list[int]]:
        import torch

        if self.config.readout == "joint":
            return self.joint_features(online)
        states, queries, actions, owners, lengths = [], [], [], [], []
        for index, row in enumerate(online):
            state_text, action_texts = control_texts(row)
            if not action_texts:
                raise ValueError("A policy state requires at least one action")
            states.append(state_text)
            if self.config.state_representation == "query_residual_v1":
                task = row["observation"]["task"]
                query = task.get("request", task.get("query"))
                if not isinstance(query, str) or not query:
                    raise ValueError("Query-conditioned input needs the actual task query")
                queries.append(query)
            actions.extend(action_texts)
            owners.extend([index] * len(action_texts))
            lengths.append(len(action_texts))
        vectors = self.encode(states + queries + actions)
        state_vectors = vectors[:len(states)]
        if queries:
            import torch.nn.functional as F

            state_vectors = F.normalize(state_vectors + vectors[len(states):len(states) * 2],
                                        dim=-1)
        return (state_vectors, vectors[len(states) + len(queries):],
                torch.tensor(owners, device=self.device), lengths)

    def joint_layout(self, online: dict[str, Any]) -> tuple[list[int], int, list[int]]:
        prefix, options = joint_control_texts(online,
            wrapped_json=self.config.joint_layout == "wrapped_json_v1")
        ids = self.tokenizer.encode(prefix, add_special_tokens=False, verbose=False)
        state_position = len(ids) - 1
        positions = []
        for text in options:
            ids.extend(self.tokenizer.encode(text, add_special_tokens=False, verbose=False))
            positions.append(len(ids) - 1)
        if len(ids) > self.config.joint_max_tokens:
            raise ValueError(f"JOINT_INPUT_CAPACITY: actual={len(ids)}, "
                             f"limit={self.config.joint_max_tokens}; no tokens dropped")
        return ids, state_position, positions

    def joint_features(self, online: list[dict[str, Any]]) -> tuple[Any, Any, Any, list[int]]:
        """Exactly one backbone forward for this batch, with no token generation."""
        import torch
        import torch.nn.functional as F

        layouts = [self.joint_layout(row) for row in online]
        if any(not positions for _, _, positions in layouts):
            raise ValueError("A policy state requires an offered action")
        batch = self.tokenizer.pad([{"input_ids": ids} for ids, _, _ in layouts],
                                   padding=True, return_tensors="pt").to(self.device)
        mask = batch["attention_mask"]
        self.counters["forwards"] += 1
        self.counters["input_tokens"] += int(mask.sum())
        self.counters["padded_tokens"] += mask.numel()
        self.counters["joint_sequences"] += len(online)
        self.counters["texts"] += len(online)
        with torch.autocast(device_type=self.device.type, dtype=torch.bfloat16,
                            enabled=self.device.type == "cuda"):
            hidden = self.encoder(**batch, use_cache=False).last_hidden_state
        states = torch.stack([hidden[index, state] for index, (_, state, _) in enumerate(layouts)])
        actions = torch.cat([hidden[index, positions]
                             for index, (_, _, positions) in enumerate(layouts)])
        lengths = [len(positions) for _, _, positions in layouts]
        owners = torch.repeat_interleave(torch.arange(len(online), device=self.device),
                                        torch.tensor(lengths, device=self.device))
        return (F.normalize(states.float(), dim=-1), F.normalize(actions.float(), dim=-1),
                owners, lengths)

    def score(self, online: dict[str, Any]) -> PolicyScores:
        import torch

        self.train(False)
        with torch.no_grad():
            states, actions, owners, _ = self.features([online])
            scores = self.head(states, actions, owners).float().cpu().tolist()
        return PolicyScores([a["id"] for a in online["actions"]], scores)

    def save(self, root: Path) -> None:
        import torch

        root.mkdir(parents=True, exist_ok=True)
        (root / "config.json").write_text(json.dumps(asdict(self.config), indent=2))
        adapted = {name for name, p in self.encoder.named_parameters() if p.requires_grad}
        torch.save({"encoder": {k: v.detach().cpu() for k, v in self.encoder.state_dict().items()
                                if self.config.adaptation != "lora" or k in adapted}
                    if self.config.adaptation != "frozen" else None,
                    "head": self.head.state_dict()}, root / "weights.pt")

    @classmethod
    def load(cls, root: Path, *, device: str = "cpu") -> SmallControlModel:
        import torch

        values = json.loads((root / "config.json").read_text())
        if values.get("readout") == "joint" and "joint_layout" not in values:
            values["joint_layout"] = "wrapped_json_v1"
        config = SmallControlConfig(**values)
        model = cls(config, device=device)
        weights = torch.load(root / "weights.pt", map_location="cpu", weights_only=True)
        if weights["encoder"] is not None:
            if config.adaptation == "lora":
                current = model.encoder.state_dict()
                current.update(weights["encoder"])
                model.encoder.load_state_dict(current)
            else:
                model.encoder.load_state_dict(weights["encoder"])
        model.head.load_state_dict(weights["head"])
        model.train(False)
        return model
