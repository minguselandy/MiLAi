"""Object-level embeddings and a finite-menu latent pointer, independent of an LLM family."""
from __future__ import annotations

import copy
import json
from typing import Any

from milai_lab.methods.control_observation import control_texts

OBJECT_COLLECTIONS = (
    "pending_candidates", "visible_evidence", "observed_evidence", "observed_materials",
    "retrieved_scopes", "views", "new_events",
)


def object_control_texts(online: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Only the online observation; every actual collection item is retained.

    Task/global context occupy the first two tokens. Other tokens are objects,
    with explicit observed/selected collection roles. No positional embeddings,
    menu IDs, offline outcomes, root IDs or split identifiers are encoded.
    """
    observation = copy.deepcopy(online["observation"])
    observation.pop("action_bindings", None)
    last = observation.get("last_result")
    if last is not None and "action" in last:
        last["action"].pop("id", None)

    def dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    objects = []
    for collection in OBJECT_COLLECTIONS:
        for item in observation.pop(collection, []) or []:
            objects.append(dumps({"collection": collection, "object": item}))
    task = observation.pop("task")
    _, actions = control_texts(online, delivery_context=True)
    return [dumps({"task": task}), dumps({"context": observation}), *objects], actions


def build_object_head(embedding_width: int, *, architecture: str = "latent_pointer",
                      width: int = 384, heads: int = 6, slots: int = 16,
                      blocks: int = 4, ffn_width: int = 1024, dropout: float = .1) -> Any:
    """Two heads on exactly the same independent object/action encodings.

    The independent MLP pools objects. The latent head recomputes a small
    query-conditioned workspace, then points to a complete action embedding.
    This is computation over already supplied information, never a source read.
    """
    import torch  # type: ignore[import-not-found]
    from torch import nn

    if architecture not in {"object_mlp", "latent_pointer"}:
        raise ValueError("Unknown memory object architecture")
    if min(embedding_width, width, heads, slots, blocks, ffn_width) < 1 or width % heads:
        raise ValueError("Positive object dimensions and a head-divisible width are required")

    class ObjectHead(nn.Module):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__()
            self.memory_projection = nn.Linear(embedding_width, width)
            self.action_projection = nn.Linear(embedding_width, width)
            self.context_projection = nn.Linear(embedding_width * 2, width)
            if architecture == "latent_pointer":
                self.slots = nn.Parameter(torch.randn(slots, width) * .02)
                self.cross = nn.ModuleList([nn.MultiheadAttention(
                    width, heads, dropout=dropout, batch_first=True) for _ in range(blocks)])
                self.self_blocks = nn.ModuleList([nn.TransformerEncoderLayer(
                    width, heads, ffn_width, dropout, activation="gelu", batch_first=True,
                    norm_first=True) for _ in range(blocks)])
                self.cross_norms = nn.ModuleList([nn.LayerNorm(width) for _ in range(blocks)])
                self.pointer = nn.MultiheadAttention(width, heads, dropout=dropout,
                                                     batch_first=True)
            self.output = nn.Sequential(nn.Linear(width * 4, ffn_width), nn.GELU(),
                                        nn.Dropout(dropout), nn.Linear(ffn_width, 1))

        def forward(self, state: Any, actions: Any, owners: Any) -> Any:
            if state.ndim != 3 or state.shape[1] < 2:
                raise ValueError("Object head requires task, context and optional memory tokens")
            mask = state.abs().sum(-1) == 0
            if mask[:, :2].any():
                raise ValueError("Actual task and global context must be encoded")
            memory = self.memory_projection(state)
            context = self.context_projection(state[:, :2].flatten(1))
            action = self.action_projection(actions)
            if architecture == "object_mlp":
                valid = (~mask).to(memory.dtype)[..., None]
                pooled = (memory * valid).sum(1) / valid.sum(1)
                conditioned = (pooled + context)[owners]
            else:
                workspace = self.slots[None].expand(len(state), -1, -1) + context[:, None]
                for cross, norm, block in zip(self.cross, self.cross_norms,
                                               self.self_blocks, strict=True):
                    query = norm(workspace)
                    delta, _ = cross(query, memory, memory, key_padding_mask=mask,
                                     need_weights=False)
                    workspace = block(workspace + delta)
                # Ragged menus stay separate: an action can attend only its own workspace.
                pieces = []
                for index in range(len(state)):
                    selected = action[owners == index][None]
                    value, _ = self.pointer(selected, workspace[index:index + 1],
                                            workspace[index:index + 1], need_weights=False)
                    pieces.append(value[0])
                # Owners are state-major in the common features/training interface.
                if not torch.equal(owners, owners.sort().values):
                    raise ValueError("Object pointer requires state-major action owners")
                conditioned = torch.cat(pieces)
            features = torch.cat((action, conditioned, action * conditioned,
                                  action - conditioned), dim=-1)
            return self.output(features).squeeze(-1)

    return ObjectHead()
