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

from milai_lab.methods.control_observation import (
    BOUND_VIEW_UNITS_V3,
    VISIBLE_SOURCE_HANDLES_V2,
    control_texts,
    joint_control_texts,
    visible_source_handle_input,
)
from milai_lab.methods.memory_control import (
    FixedContextMemoryPolicy,
    MemoryAction,
    MemoryControlState,
    RulesMemoryPolicy,
)
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
    action_representation: str = "binding_v1"
    lora_target_modules: tuple[str, ...] = ("q_proj", "v_proj")
    feature_normalization: str = "raw_v1"
    prior_policy: str = "none"
    prior_reads: int = 4
    prior_margin: float = 1.0
    prior_menu_order: str = "offered_v1"
    head_initialization: str = "standard_v1"
    object_architecture: str = "latent_pointer"
    object_width: int = 384
    object_heads: int = 6
    object_slots: int = 16
    object_blocks: int = 4
    object_ffn_width: int = 1024
    object_dropout: float = .1
    maximum_memory_objects: int = 256
    object_feature_layout: str = "literal_v1"


def conditioned_chunks(body: list[int], context: list[int], limit: int) -> list[list[int]]:
    """Keep every token; expose every body chunk to every bounded query fragment.

    Long contexts form an explicit Cartesian product rather than truncating a
    task or pretending that a late body fragment attended an absent query.
    The encoder's ordinary counters charge all repeated prefix/body tokens.
    """
    if limit < 8:
        raise ValueError("Chunk capacity is too small")
    if not context:
        return [body[start:start + limit] for start in range(0, max(1, len(body)), limit)]
    result: list[list[int]] = []
    for start in range(0, len(context), limit // 2):
        prefix = context[start:start + limit // 2]
        available = limit - len(prefix)
        result.extend(prefix + body[offset:offset + available]
                      for offset in range(0, max(1, len(body)), available))
    return result


def build_action_head(width: int, hidden: int, *, set_interaction: bool = False,
                      feature_normalization: str = "raw_v1",
                      initialization: str = "standard_v1") -> Any:
    import torch  # type: ignore[import-not-found]

    if feature_normalization not in {
            "raw_v1", "block_layernorm_v2", "block_layernorm_stats_v3"}:
        raise ValueError("Unknown action-head feature normalization")
    if initialization not in {"standard_v1", "zero_output_v1"}:
        raise ValueError("Unknown action-head initialization")

    class ActionHead(torch.nn.Module):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__()
            blocks = 5 if set_interaction else 4
            statistics_width = blocks * 2 if feature_normalization == (
                "block_layernorm_stats_v3") else 0
            self.network = torch.nn.Sequential(
                torch.nn.Linear(width * blocks + statistics_width, hidden),
                torch.nn.GELU(), torch.nn.Linear(hidden, 1))
            if initialization == "zero_output_v1":
                torch.nn.init.zeros_(self.network[-1].weight)
                torch.nn.init.zeros_(self.network[-1].bias)

        def forward(self, state: Any, actions: Any, owners: Any) -> Any:
            selected = state[owners]
            features = [selected, actions, selected * actions, selected - actions]
            if set_interaction:
                pooled = torch.zeros_like(state).index_add(0, owners, actions)
                counts = torch.bincount(owners, minlength=len(state)).clamp_min(1)
                features.append((pooled / counts[:, None])[owners])
            statistics = (torch.stack([value for block in features for value in (
                block.sum(dim=-1), torch.linalg.vector_norm(block, dim=-1))], dim=-1)
                if feature_normalization == "block_layernorm_stats_v3" else None)
            if feature_normalization in {"block_layernorm_v2", "block_layernorm_stats_v3"}:
                features = [torch.nn.functional.layer_norm(block, (width,)) for block in features]
            if statistics is not None:
                # Unit-vector product sums retain cosine; sums and norms preserve
                # the block mean/scale that LayerNorm alone removes. Online inputs
                # and complete binding alignment remain unchanged.
                features.append(statistics)
            return self.network(torch.cat(features, dim=-1)).squeeze(-1)

    return ActionHead()


class SmallControlModel:
    _base_encoding_cache: Any = None
    _base_encoder_versions: Any = None

    def __init__(self, config: SmallControlConfig, *, device: str = "cpu") -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        if config.family not in {"frozen_mlp", "encoder", "decoder"}:
            raise ValueError("Unknown small control family")
        if config.prior_policy not in {"none", "fixed_context", "rules"}:
            raise ValueError("Unknown explicitly declared policy prior")
        if config.prior_margin <= 0:
            raise ValueError("Policy prior margin must be positive")
        if config.prior_menu_order not in {"offered_v1", "bound_parameters_v2"}:
            raise ValueError("Unknown declared prior menu order")
        if config.adaptation not in {"frozen", "full", "lora"}:
            raise ValueError("Unknown backbone adaptation")
        if config.family == "frozen_mlp" and config.adaptation != "frozen":
            raise ValueError("M0 requires a frozen encoder")
        if config.projection_version not in {
            "control-observation-v1", VISIBLE_SOURCE_HANDLES_V2, BOUND_VIEW_UNITS_V3,
        }:
            raise ValueError("Use the model's original observation projection")
        if config.readout not in {"dual", "joint", "objects"}:
            raise ValueError("Unknown control readout")
        if config.object_feature_layout not in {"literal_v1", "dual_raw_v1", "dual_semantic_v1"}:
            raise ValueError("Unknown object feature layout")
        if config.readout != "objects" and config.object_feature_layout != "literal_v1":
            raise ValueError("Object feature layouts require the object readout")
        if config.readout == "joint" and config.family != "decoder":
            raise ValueError("Joint causal markers require the decoder route")
        if config.joint_layout not in {"literal_json_v2", "wrapped_json_v1"}:
            raise ValueError("Unknown joint input layout")
        if config.state_representation not in {"whole_v1", "query_residual_v1"}:
            raise ValueError("Unknown state representation")
        if config.readout == "joint" and config.state_representation != "whole_v1":
            raise ValueError("Query residual is a separate dual-encoder representation")
        if config.action_representation not in {
                "binding_v1", "query_pair_v2", "query_delivery_pair_v3"}:
            raise ValueError("Unknown action representation")
        if config.readout == "joint" and config.action_representation != "binding_v1":
            raise ValueError("Binding-conditioned encoding is a separate dual readout")
        self.config, self.device = config, torch.device(device)
        self.tokenizer = AutoTokenizer.from_pretrained(  # type: ignore[no-untyped-call]
            config.backbone, local_files_only=True)
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.encoder = AutoModel.from_pretrained(config.backbone, local_files_only=True)
        # Initialize the common head before adapter RNG draws, so matched frozen
        # and LoRA encoder probes really begin with the same head parameters.
        width = self.encoder.config.hidden_size
        if config.readout == "objects":
            from milai_lab.methods.memory_object_policy import build_object_head

            if (config.state_representation != "whole_v1"
                    or config.action_representation != "binding_v1" or config.set_interaction
                    or config.feature_normalization != "raw_v1"
                    or config.head_initialization != "standard_v1"):
                raise ValueError("Object readout uses its explicit object-head configuration")
            if config.maximum_memory_objects < 0:
                raise ValueError("Memory object capacity must be nonnegative")
            object_width = width * (1 if config.object_feature_layout == "literal_v1" else 2)
            self.head = build_object_head(object_width, architecture=config.object_architecture,
                width=config.object_width, heads=config.object_heads, slots=config.object_slots,
                blocks=config.object_blocks, ffn_width=config.object_ffn_width,
                dropout=config.object_dropout).to(self.device)
        else:
            self.head = build_action_head(width, config.hidden_size,
                set_interaction=config.set_interaction,
                feature_normalization=config.feature_normalization,
                initialization=config.head_initialization).to(self.device)
        if config.adaptation == "lora":
            from peft import LoraConfig, get_peft_model  # type: ignore[import-not-found]

            # Targets are explicit and inspected, never silently remapped between
            # backbone families (e.g. encoder query/value vs decoder q_proj/v_proj).
            targets = list(config.lora_target_modules)
            names = [name for name, _ in self.encoder.named_modules()]
            if not targets or any(not any(name.endswith("." + target)
                                         for name in names) for target in targets):
                raise ValueError("LoRA route requires inspected explicit target modules")
            self.encoder = get_peft_model(self.encoder, LoraConfig(
                r=16, lora_alpha=32, lora_dropout=0.05,
                target_modules=targets, bias="none"))
        elif config.adaptation == "frozen":
            self.encoder.requires_grad_(False)
        if config.adaptation != "frozen":
            self.encoder.gradient_checkpointing_enable()
            if config.adaptation == "lora":
                self.encoder.enable_input_require_grads()
        self.encoder.to(self.device)
        self.counters: dict[str, int] = dict(forwards=0, input_tokens=0, padded_tokens=0,
                                            texts=0, chunked_texts=0, chunks=0, joint_sequences=0)
        self._base_encoding_cache = None
        self._base_encoder_versions = None
        self.batch_tokens_by_length = False

    def configure_base_encoding_cache(self, max_bytes: int = 0) -> None:
        """Runtime-only optimization; old checkpoints and defaults stay unchanged."""
        from milai_lab.methods.base_encoding_cache import BaseEncodingCache

        if type(max_bytes) is not int or max_bytes < 0:
            raise ValueError("Base encoding cache bytes must be a nonnegative integer")
        self._base_encoding_cache = None
        self._base_encoder_versions = None
        if max_bytes:
            if (self.config.adaptation != "frozen" or self.config.family == "decoder"
                    or self.config.readout == "joint"):
                raise ValueError("Base encoding cache requires a frozen independent encoder")
            self._base_encoding_cache = BaseEncodingCache(max_bytes)

    def clear_base_encoding_cache(self) -> None:
        if self._base_encoding_cache is not None:
            self._base_encoding_cache.clear()

    def base_encoding_cache_report(self) -> dict[str, Any] | None:
        return (self._base_encoding_cache.report()
                if self._base_encoding_cache is not None else None)

    def _check_base_encoder(self) -> None:
        if self._base_encoding_cache is None:
            return
        if (self.config.adaptation != "frozen" or self.config.family == "decoder"
                or self.config.readout == "joint" or self.encoder.training
                or any(p.requires_grad for p in self.encoder.parameters())):
            self.clear_base_encoding_cache()
            raise ValueError("Base encoding cache requires an unchanged frozen eval encoder")
        # Native tensor mutation versions detect optimizer/load_state_dict changes;
        # these are runtime versions, not hashes or replacement fingerprints.
        versions = (self.config, tuple((id(p), p._version, p.device, p.dtype)
                                       for p in (*self.encoder.parameters(),
                                                 *self.encoder.buffers())))
        if versions != self._base_encoder_versions:
            self.clear_base_encoding_cache()
            self._base_encoder_versions = versions

    def parameters(self) -> list[Any]:
        return [p for module in (self.encoder, self.head)
                for p in module.parameters() if p.requires_grad]

    def train(self, mode: bool = True) -> None:
        if mode:
            self.clear_base_encoding_cache()
        self.encoder.train(mode and self.config.adaptation != "frozen")
        self.head.train(mode)

    def encode(self, texts: list[str], *, prefixes: list[str] | None = None,
               text_role: str = "query") -> Any:
        cache = self._base_encoding_cache
        if cache is None:
            return self._encode_uncached(texts, prefixes=prefixes, text_role=text_role)
        self._check_base_encoder()
        if cache.active is None:
            with cache.scope():
                return self._encode_cached(texts, prefixes=prefixes, text_role=text_role)
        return self._encode_cached(texts, prefixes=prefixes, text_role=text_role)

    def _encode_cached(self, texts: list[str], *, prefixes: list[str] | None,
                       text_role: str) -> Any:
        import torch

        if prefixes is not None and len(prefixes) != len(texts):
            raise ValueError("A conditional encoding needs one actual prefix per text")
        if text_role not in {"query", "passage"}:
            raise ValueError("Encoder text role must be query or passage")
        cache = self._base_encoding_cache
        missing: dict[tuple[str, str, str], list[int]] = {}
        result: list[Any] = [None] * len(texts)
        for index, text in enumerate(texts):
            key = (text_role, prefixes[index] if prefixes else "", text)
            value = cache.get(key)
            if value is not None:
                result[index] = value
            else:
                if key in missing:
                    cache.counters["same_call_reuses"] += 1
                missing.setdefault(key, []).append(index)
        if missing:
            keys = list(missing)
            vectors = self._encode_uncached([k[2] for k in keys],
                prefixes=[k[1] for k in keys] if prefixes is not None else None,
                text_role=text_role)
            for key, vector in zip(keys, vectors, strict=True):
                cache.put(key, vector)
                for index in missing[key]:
                    result[index] = vector
        return torch.stack(result)

    def _encode_uncached(self, texts: list[str], *, prefixes: list[str] | None = None,
                         text_role: str = "query") -> Any:
        import torch
        import torch.nn.functional as F  # type: ignore[import-not-found]

        chunks, owners = [], []
        limit = self.config.chunk_tokens - self.tokenizer.num_special_tokens_to_add()
        if limit < 8:
            raise ValueError("Chunk capacity is too small")
        if prefixes is not None and len(prefixes) != len(texts):
            raise ValueError("A conditional encoding needs one actual prefix per text")
        if text_role not in {"query", "passage"}:
            raise ValueError("Encoder text role must be query or passage")
        if self.config.family == "decoder" and text_role != "query":
            raise ValueError("Query/passage retrieval prefixes require an encoder backbone")
        for owner, text in enumerate(texts):
            prefix = text_role + ": " if self.config.family != "decoder" else ""
            context = prefixes[owner] if prefixes is not None else ""
            if context:
                context_ids = self.tokenizer.encode(prefix + "Task request:\n" + context
                    + "\nCandidate binding:\n", add_special_tokens=False, verbose=False)
                ids = self.tokenizer.encode(text, add_special_tokens=False, verbose=False)
            else:
                context_ids = []
                ids = self.tokenizer.encode(prefix + text, add_special_tokens=False, verbose=False)
            self.counters["texts"] += 1
            token_chunks = conditioned_chunks(ids, context_ids, limit)
            self.counters["chunked_texts"] += int(len(token_chunks) > 1)
            for tokens in token_chunks:
                chunks.append({"input_ids": self.tokenizer.build_inputs_with_special_tokens(
                    tokens)})
                owners.append(owner)
        vectors = []
        order: range | list[int] = range(len(chunks))
        if getattr(self, "batch_tokens_by_length", False):
            order = sorted(order, key=lambda i: len(chunks[i]["input_ids"]))
        for start in range(0, len(chunks), self.config.encode_batch_size):
            offered = [chunks[i] for i in order[start:start + self.config.encode_batch_size]]
            batch = self.tokenizer.pad(offered, padding=True, return_tensors="pt").to(self.device)
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
        if isinstance(order, list):
            original_order = torch.tensor(sorted(range(len(order)), key=order.__getitem__),
                                          device=self.device)
            vectors_tensor = vectors_tensor[original_order]
        owner_tensor = torch.tensor(owners, device=self.device)
        summed = vectors_tensor.new_zeros((len(texts), vectors_tensor.shape[-1])).index_add(
            0, owner_tensor, vectors_tensor)
        counts = torch.bincount(owner_tensor, minlength=len(texts))[:, None]
        return F.normalize(summed / counts, dim=-1)

    def features(
        self, online: list[dict[str, Any]], *, pad_to_batch: bool = False,
    ) -> tuple[Any, Any, Any, list[int]]:
        if self._base_encoding_cache is None:
            return self._features_uncached(online, pad_to_batch=pad_to_batch)
        self._check_base_encoder()
        with self._base_encoding_cache.scope():
            return self._features_uncached(online, pad_to_batch=pad_to_batch)

    def _features_uncached(
        self, online: list[dict[str, Any]], *, pad_to_batch: bool = False,
    ) -> tuple[Any, Any, Any, list[int]]:
        import torch

        if self.config.readout == "joint":
            return self.joint_features(online)
        if self.config.projection_version in {VISIBLE_SOURCE_HANDLES_V2, BOUND_VIEW_UNITS_V3}:
            online = [visible_source_handle_input(row) for row in online]
        if self.config.readout == "objects":
            return self.object_features(online, pad_to_batch=pad_to_batch)
        states, queries, actions, owners, lengths, action_queries = [], [], [], [], [], []
        for index, row in enumerate(online):
            state_text, action_texts = control_texts(row, delivery_context=(
                self.config.action_representation == "query_delivery_pair_v3"),
                view_unit_context=self.config.projection_version == BOUND_VIEW_UNITS_V3)
            if not action_texts:
                raise ValueError("A policy state requires at least one action")
            states.append(state_text)
            if (self.config.state_representation == "query_residual_v1"
                    or self.config.action_representation != "binding_v1"):
                task = row["observation"]["task"]
                query = task.get("request", task.get("query"))
                if not isinstance(query, str) or not query:
                    raise ValueError("Query-conditioned input needs the actual task query")
                if self.config.state_representation == "query_residual_v1":
                    queries.append(query)
                if self.config.action_representation != "binding_v1":
                    action_queries.extend([query] * len(action_texts))
            actions.extend(action_texts)
            owners.extend([index] * len(action_texts))
            lengths.append(len(action_texts))
        texts = states + queries + actions
        vectors = (self.encode(texts, prefixes=[""] * (len(states) + len(queries)) + action_queries)
                   if action_queries else self.encode(texts))
        state_vectors = vectors[:len(states)]
        if queries:
            import torch.nn.functional as F

            state_vectors = F.normalize(state_vectors + vectors[len(states):len(states) * 2],
                                        dim=-1)
        return (state_vectors, vectors[len(states) + len(queries):],
                torch.tensor(owners, device=self.device), lengths)

    def object_features(
        self, online: list[dict[str, Any]], *, pad_to_batch: bool = False,
    ) -> tuple[Any, Any, Any, list[int]]:
        import torch

        from milai_lab.methods.memory_object_policy import (
            object_control_texts,
            object_semantic_texts,
        )

        projections = [object_control_texts(row,
            view_unit_context=self.config.projection_version == BOUND_VIEW_UNITS_V3)
            for row in online]
        capacity = self.config.maximum_memory_objects + 2
        if any(len(objects) > capacity for objects, _ in projections):
            raise ValueError("MEMORY_OBJECT_CAPACITY: partition explicitly; no objects dropped")
        if any(not actions for _, actions in projections):
            raise ValueError("A policy state requires an offered action")
        if pad_to_batch:
            capacity = max(len(objects) for objects, _ in projections)
        object_texts = [text for objects, _ in projections for text in objects]
        action_texts = [text for _, actions in projections for text in actions]
        vectors = self.encode(object_texts + action_texts)
        if self.config.object_feature_layout != "literal_v1":
            semantics = [object_semantic_texts(objects, actions)
                         for objects, actions in projections]
            texts = ([text for objects, _ in semantics for text in objects]
                     + [text for _, actions in semantics for text in actions])
            available = [i for i, text in enumerate(texts) if text]
            semantic_vectors = torch.zeros_like(vectors)
            if available:
                semantic_vectors[available] = (
                    vectors[available] if self.config.object_feature_layout == "dual_raw_v1"
                    else self.encode([texts[i] for i in available]))
            # Same dimensionality and missing-text mask in both explicit controls.
            # The complete original vectors are retained without any field deletion.
            vectors = torch.cat((vectors, semantic_vectors), dim=-1)
        offset, states = 0, []
        for objects, _ in projections:
            current = vectors[offset:offset + len(objects)]
            states.append(torch.cat((current, current.new_zeros((capacity - len(objects),
                                                               current.shape[-1])))))
            offset += len(objects)
        lengths = [len(actions) for _, actions in projections]
        owners = torch.repeat_interleave(torch.arange(len(online), device=self.device),
                                        torch.tensor(lengths, device=self.device))
        return torch.stack(states), vectors[offset:], owners, lengths

    def joint_layout(self, online: dict[str, Any]) -> tuple[list[int], int, list[int]]:
        if self.config.projection_version in {VISIBLE_SOURCE_HANDLES_V2, BOUND_VIEW_UNITS_V3}:
            online = visible_source_handle_input(online)
        prefix, options = joint_control_texts(online,
            wrapped_json=self.config.joint_layout == "wrapped_json_v1",
            view_unit_context=self.config.projection_version == BOUND_VIEW_UNITS_V3)
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

    def with_prior(self, scores: Any, online: dict[str, Any],
                   action_ids: list[str] | None = None) -> Any:
        """Declared baseline logits plus learned residual; never an error fallback.

        The baseline always consumes the original executor menu. Training may
        reorder neural readout positions; IDs align the SAME baseline binding.
        Inference still scores every offered action and raises on model failures.
        """
        if self.config.prior_policy == "none":
            return scores
        import torch

        state = MemoryControlState(**online["observation"])
        actions = [MemoryAction(**a) for a in online["actions"]]
        policy = {"fixed_context": FixedContextMemoryPolicy,
                  "rules": RulesMemoryPolicy}[self.config.prior_policy](
                      reads=self.config.prior_reads)
        if self.config.prior_menu_order == "bound_parameters_v2":
            from milai_lab.methods.small_memory_policy import bound_prior_menu

            chosen = policy.choose(state, bound_prior_menu(state, actions))
        else:
            chosen = policy.choose(state, actions)
        original_ids = [a.id for a in actions]
        ids = original_ids if action_ids is None else action_ids
        if len(ids) != len(original_ids) or set(ids) != set(original_ids) or chosen not in ids:
            raise ValueError("Policy prior must align with the complete original menu")
        prior = torch.tensor([self.config.prior_margin if key == chosen else 0.0 for key in ids],
                             device=scores.device, dtype=scores.dtype)
        return scores + prior

    def score(self, online: dict[str, Any]) -> PolicyScores:
        import torch

        self.train(False)
        with torch.no_grad():
            states, actions, owners, _ = self.features([online])
            logits = self.with_prior(self.head(states, actions, owners), online)
            scores = logits.float().cpu().tolist()
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
        if "lora_target_modules" in values:
            values["lora_target_modules"] = tuple(values["lora_target_modules"])
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
